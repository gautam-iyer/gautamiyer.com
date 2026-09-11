#!/usr/bin/env python3
"""
Re-import essay bodies from Substack, which is where the real structure lives.

The original import into this repo flattened every post into ONE line and ate
the spaces between block elements, fusing words at the seams ("edificeThe Gut").
This pulls `body_html` back from Substack's public post API and rebuilds proper
markdown: paragraphs, headings, dividers, blockquotes, lists, links, emphasis,
and images with their captions.

  python3 scripts/writing/import_substack.py --all --dry-run
  python3 scripts/writing/import_substack.py the-california-story
  python3 scripts/writing/import_substack.py --all

Frontmatter is preserved byte-for-byte; only the body is replaced. Every file
is copied to <name>.md.bak first, and git is the real safety net.
"""
import argparse, json, re, shutil, subprocess, sys, urllib.parse
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WRITING = REPO / "content" / "writing"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

# Substack chrome that is not part of the prose.
DROP_TAGS = {"button", "svg", "form", "input", "path", "polyline", "line", "g",
             "source", "picture", "style", "script"}
DROP_CLASS = re.compile(r'subscription-widget|pencraft|image-link-expand|'
                        r'restack-image|view-image|button-wrapper|'
                        r'digest-post-embed|poll-embed|footnote-hovercard')

# Void elements emit no end tag. Counting them as "open" is what made the first
# cut of this parser latch into drop-mode forever and swallow whole essays.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr", "path", "polyline",
        "line", "circle", "rect", "use", "stop"}


class Sub2MD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []          # finished block strings
        self.buf = []          # inline text of the current block
        self.block = None      # current block tag
        self.list_stack = []
        self.li_index = []
        self.stack = []        # open non-void elements
        self.drop_at = None    # stack depth at which we entered dropped content
        self.fig = None        # {'src':…, 'cap':[…]}
        self.in_figcap = False
        self.a_href = None
        self.em_stack = []     # (marker, index in self.buf) for open emphasis

    # ---- helpers
    def flush(self):
        txt = "".join(self.buf)
        txt = re.sub(r'[ \t ]+', ' ', txt).strip()
        self.buf = []
        if not txt:
            self.block = None
            return
        b = self.block
        if b in ("h1", "h2"):   self.out.append("## " + txt)
        elif b in ("h3", "h4", "h5", "h6"): self.out.append("### " + txt)
        elif b == "blockquote": self.out.append("\n".join("> " + l for l in txt.split("\n")))
        elif b == "li":
            if self.list_stack and self.list_stack[-1] == "ol":
                self.li_index[-1] += 1
                self.out.append(f"{self.li_index[-1]}. {txt}")
            else:
                self.out.append(f"- {txt}")
        else:                   self.out.append(txt)
        self.block = None

    # ---- parsing
    @property
    def dropping(self):
        return self.drop_at is not None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)          # void/self-closing: never pushed

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        entering_drop = tag in DROP_TAGS or (cls and DROP_CLASS.search(cls))
        if not self.dropping and entering_drop:
            self.drop_at = len(self.stack)
        if tag not in VOID:
            self.stack.append(tag)
        if self.dropping:
            return
        if tag == "figure":
            self.flush(); self.fig = {"src": None, "cap": []}; return
        if tag == "figcaption":
            self.in_figcap = True; return
        if tag == "img" and self.fig is not None and not self.fig["src"]:
            self.fig["src"] = a.get("src"); return
        if tag == "a":
            href = a.get("href", "")
            if self.fig is not None and not self.fig["src"] and "image" in href:
                self.fig["src"] = href                  # figure link = full-size original
                return
            self.a_href = href
            self.buf.append("[")
            return
        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"):
            self.flush(); self.block = tag; return
        if tag in ("ul", "ol"):
            self.flush(); self.list_stack.append(tag); self.li_index.append(0); return
        if tag == "hr":
            self.flush(); self.out.append("---"); return
        if tag in ("strong", "b"):
            self.em_stack.append(("**", len(self.buf))); self.buf.append("**")
        elif tag in ("em", "i"):
            self.em_stack.append(("*", len(self.buf))); self.buf.append("*")
        elif tag == "br":
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag not in VOID:
            # unwind to the matching open tag (tolerates unclosed markup)
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            if self.drop_at is not None and len(self.stack) <= self.drop_at:
                self.drop_at = None
                return
        if self.dropping:
            return
        if tag == "figure":
            if self.fig and self.fig["src"]:
                cap = re.sub(r'\s+', ' ', "".join(self.fig["cap"])).strip()
                src = cdn_url(self.fig["src"])
                self.out.append(f'![{cap}]({src})')
            self.fig = None; return
        if tag == "figcaption":
            self.in_figcap = False; return
        if tag == "a":
            if self.a_href is not None:
                self.buf.append(f"]({self.a_href})")
                self.a_href = None
            return
        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"):
            self.flush(); return
        if tag in ("ul", "ol"):
            self.flush()
            if self.list_stack: self.list_stack.pop(); self.li_index.pop()
            return
        if tag in ("strong", "b"): self.close_em("**")
        elif tag in ("em", "i"):   self.close_em("*")

    def close_em(self, marker):
        """Emit the closing marker, then move any whitespace that sits INSIDE the
        emphasis to the outside. Substack writes <em> “Surely…”</em> with the
        space within the tag; rendered naively that becomes `* “Surely…”*`,
        which markdown reads as a BULLET, not italics. One such line was
        rendering as a list item in Psychic Highway Part 1."""
        if not self.em_stack or self.em_stack[-1][0] != marker:
            self.buf.append(marker); return
        _, start = self.em_stack.pop()
        inner = "".join(self.buf[start + 1:])
        if not inner.strip():
            del self.buf[start:]           # empty emphasis: drop it entirely
            self.buf.append(inner)
            return
        lead = inner[:len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()):]
        del self.buf[start:]
        self.buf.extend([lead, marker, inner.strip(), marker, trail])

    def handle_data(self, d):
        if self.dropping:
            return
        if self.in_figcap and self.fig is not None:
            self.fig["cap"].append(d); return
        if self.fig is not None:
            return                        # stray text inside a figure: ignore
        self.buf.append(d)

    def markdown(self):
        self.flush()
        blocks, prev = [], None
        for b in self.out:
            b = b.strip()
            if not b: continue
            if b == "---" and prev == "---": continue     # collapse doubled rules
            blocks.append(b); prev = b
        while blocks and blocks[-1] == "---": blocks.pop()
        return "\n\n".join(blocks) + "\n"


CDN = ("https://substackcdn.com/image/fetch/"
       "w_1456,c_limit,f_auto,q_auto:good,fl_progressive:steep/")


def cdn_url(url, ):
    """Normalise to Substack's image CDN rather than the raw S3 original.

    Going straight to the S3 object looks purer but is wrong twice over: six of
    these images are .heic, which browsers will not display, and the originals
    run ~0.75 MB apiece (Psychic Highway Part 1 alone has 32, so ~24 MB a page).
    The CDN's f_auto transcodes HEIC and serves webp, and w_1456 caps the size.
    """
    if not url:
        return url
    m = re.search(r'(https%3A%2F%2F.+)$', url)
    original = urllib.parse.unquote(m.group(1)) if m else url
    return CDN + urllib.parse.quote(original, safe="")


def split_front(text):
    if not text.startswith("---"): return None, text
    end = text.find("\n---", 3)
    if end == -1: return None, text
    return text[:end + 4], text[end + 4:].lstrip("\n")


def fm_get(front, key):
    m = re.search(rf'^{key}:\s*(.*)$', front or "", re.M)
    if not m: return ""
    v = m.group(1).strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


CACHE = REPO / ".photo-build" / "substack-cache"


def fetch(pub_url, slug, use_cache=True):
    """Cache each post's JSON on disk. Substack throttles repeated hits, and a
    dry run followed by the real run would otherwise fetch everything twice."""
    api = f"{pub_url.rstrip('/')}/api/v1/posts/{slug}"
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / f"{slug}.json"
    if use_cache and cf.exists():
        d = json.loads(cf.read_text())
        if d.get("body_html"):
            return d
    r = subprocess.run(["curl", "-sS", "--retry", "3", "--retry-delay", "2",
                        "-A", UA, api], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl failed: {r.stderr.strip()[:200]}")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON from {api}: {r.stdout[:160]}")
    if not d.get("body_html"):
        raise RuntimeError(f"no body_html (audience={d.get('audience')}) — "
                           f"throttled or paywalled; retry in a minute")
    cf.write_text(json.dumps(d))
    return d


def convert(html):
    p = Sub2MD()
    p.feed(html)
    return p.markdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*", help="essay file stems (default: those with a source_url)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    targets = []
    for p in sorted(WRITING.glob("*.md")):
        if p.name == "_index.md": continue
        if args.slugs and p.stem not in args.slugs: continue
        front, body = split_front(p.read_text())
        src = fm_get(front, "source_url")
        if not src:
            if args.slugs: print(f"skip {p.stem}: no source_url")
            continue
        targets.append((p, front, body, src))
    if not targets: sys.exit("nothing to import")

    for p, front, body, src in targets:
        u = urllib.parse.urlparse(src)
        pub = f"{u.scheme}://{u.netloc}"
        slug = u.path.rstrip("/").split("/")[-1]
        try:
            d = fetch(pub, slug)
            md = convert(d["body_html"])
        except Exception as e:
            print(f"!! {p.stem}: {e}")
            continue

        ow, nw = len(body.split()), len(md.split())
        paras = md.count("\n\n") + 1
        imgs = md.count("![")
        rules = len([l for l in md.split("\n") if l.strip() == "---"])
        heads = len([l for l in md.split("\n") if l.startswith("#")])
        print(f"{p.stem[:44]:46} words {ow:>6} -> {nw:<6} blocks {paras:>3}  img {imgs:>2}  hr {rules}  h {heads}")

        if args.dry_run: continue
        bakdir = REPO / ".photo-build" / "writing-bak"
        bakdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, bakdir / (p.name + ".bak"))
        p.write_text((front or "") + "\n\n" + md)

    if args.dry_run: print("\n(dry run — nothing written)")


if __name__ == "__main__":
    main()
