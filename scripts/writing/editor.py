#!/usr/bin/env python3
"""
Essay editor — a dependency-free local web app for writing and laying out the
prose in content/writing/*.md (and the intro copy of data-projects).

Run:   python3 scripts/writing/editor.py        (opens http://localhost:8801)

It is a BLOCK editor in the Substack mould: a centred column styled with the
site's own .article-body rules, so what you see is what the published page
looks like. Title and subtitle are borderless fields at the top; selecting text
raises a bubble toolbar (bold / italic / link); the + in the left gutter of an
empty block inserts a heading, quote, divider, list or photo.

Photos are referenced by a STABLE SLUG, not a path: `{{< photo ref="utica-1" >}}`.
The slug is attached to a photo in the photo tagger (its "Essay ref" field), so
you can repoint which frame a reference means without touching the prose.

AUTOSAVES to the markdown file on every change (atomic write + .bak).
"""

import json, os, re, shutil, sys, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

PORT = 8801
REPO = Path(__file__).resolve().parents[2]
WRITING = REPO / "content" / "writing"
DATA = REPO / "data"
DERIV = REPO / ".photo-build" / "derivatives"
TEMPLATE = Path(__file__).resolve().parent / "editor.html"
_lock = threading.Lock()


# ---------------------------------------------------------------- frontmatter
def split_front(text):
    """Return (frontmatter_dict, raw_frontmatter_lines, body). Deliberately a
    line-based reader, not a YAML parser: these files are flat key: "value"
    pairs and we must round-trip unknown keys untouched."""
    if not text.startswith("---"):
        return {}, [], text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, [], text
    raw = text[3:end].strip("\n").split("\n")
    body = text[end + 4:].lstrip("\n")
    fm = {}
    for line in raw:
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            fm[m.group(1)] = v
    return fm, raw, body


def join_front(raw_lines, updates):
    """Rewrite only the keys we own; keep every other line byte-identical."""
    out, seen = [], set()
    for line in raw_lines:
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', line)
        if m and m.group(1) in updates:
            k = m.group(1)
            out.append(f'{k}: {json.dumps(updates[k], ensure_ascii=False)}')
            seen.add(k)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f'{k}: {json.dumps(v, ensure_ascii=False)}')
    return "---\n" + "\n".join(out) + "\n---\n\n"


# ------------------------------------------------------------ md <-> blocks
INLINE_MD = [
    (re.compile(r'\*\*([^*]+)\*\*'), r'<strong>\1</strong>'),
    (re.compile(r'(?<!\*)\*([^*\n]+)\*(?!\*)'), r'<em>\1</em>'),
    (re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)'), r'<a href="\2">\1</a>'),
]
PHOTO_RE = re.compile(r'\{\{<\s*photo\s+(.*?)\s*>\}\}')
IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)\)$')
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline_to_html(s):
    s = esc(s)
    for rx, rep in INLINE_MD:
        s = rx.sub(rep, s)
    return s


def md_to_blocks(body):
    """Markdown -> the editor's block list. Anything unrecognised survives as a
    'raw' block so no essay can ever be silently mangled by a round trip."""
    blocks, lines, i = [], body.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1; continue
        m = PHOTO_RE.match(s)
        if m:
            attrs = dict(ATTR_RE.findall(m.group(1)))
            blocks.append({"type": "photo", "ref": attrs.get("ref", ""),
                           "caption": attrs.get("caption", "")})
            i += 1; continue
        mi = IMAGE_RE.match(s)
        if mi:
            blocks.append({"type": "image", "src": mi.group(2),
                           "caption": mi.group(1)})
            i += 1; continue
        if re.match(r'^(---|\*\*\*|___)\s*$', s):
            blocks.append({"type": "hr"}); i += 1; continue
        if s.startswith("### "):
            blocks.append({"type": "h3", "html": inline_to_html(s[4:])}); i += 1; continue
        if s.startswith("## "):
            blocks.append({"type": "h2", "html": inline_to_html(s[3:])}); i += 1; continue
        if s.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            blocks.append({"type": "quote", "html": inline_to_html(" ".join(buf))}); continue
        if re.match(r'^[-*+] ', s) or re.match(r'^\d+\. ', s):
            ordered = bool(re.match(r'^\d+\. ', s))
            items = []
            while i < len(lines):
                t = lines[i].strip()
                if ordered and re.match(r'^\d+\. ', t): items.append(inline_to_html(re.sub(r'^\d+\.\s*', '', t)))
                elif not ordered and re.match(r'^[-*+] ', t): items.append(inline_to_html(t[2:]))
                else: break
                i += 1
            blocks.append({"type": "ol" if ordered else "ul", "items": items}); continue
        # paragraph: consume until a blank line or a block starter
        buf = []
        while i < len(lines):
            t = lines[i].strip()
            if not t or PHOTO_RE.match(t) or IMAGE_RE.match(t) \
               or re.match(r'^(---|\*\*\*|___)\s*$', t) \
               or t.startswith("#") or t.startswith("> ") \
               or re.match(r'^[-*+] ', t) or re.match(r'^\d+\. ', t):
                break
            buf.append(t); i += 1
        if buf:
            blocks.append({"type": "p", "html": inline_to_html(" ".join(buf))})
    return blocks


INLINE_HTML = [
    (re.compile(r'<(?:strong|b)>(.*?)</(?:strong|b)>', re.S), r'**\1**'),
    (re.compile(r'<(?:em|i)>(.*?)</(?:em|i)>', re.S), r'*\1*'),
    (re.compile(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.S), r'[\2](\1)'),
]


def html_to_md(h):
    """Inverse of inline_to_html. The browser serializer produces the same
    subset, so this is also what proves the round trip lossless in tests."""
    h = re.sub(r'<br\s*/?>', ' ', h or '')
    for rx, rep in INLINE_HTML:
        h = rx.sub(rep, h)
    h = re.sub(r'<[^>]+>', '', h)              # strip anything else
    h = (h.replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
          .replace("&amp;", "&"))
    return re.sub(r'[ \t]+', ' ', h).strip()


def blocks_html_to_md(blocks):
    """Fill each block's `md` from its `html` — used by the round-trip test and
    as a fallback when a client sends html only."""
    out = []
    for b in blocks:
        b = dict(b)
        if "html" in b and "md" not in b:
            b["md"] = html_to_md(b["html"])
        if b.get("type") in ("ul", "ol"):
            b["items"] = [html_to_md(x) for x in b.get("items", [])]
        out.append(b)
    return out


def blocks_to_md(blocks):
    blocks = blocks_html_to_md(blocks)
    out = []
    for b in blocks:
        t = b.get("type")
        if t == "p":     out.append(b.get("md", "").strip())
        elif t == "h2":  out.append("## " + b.get("md", "").strip())
        elif t == "h3":  out.append("### " + b.get("md", "").strip())
        elif t == "quote":
            for ln in (b.get("md", "").strip() or "").split("\n"):
                out.append("> " + ln)
        elif t == "hr":  out.append("---")
        elif t == "image":
            out.append(f'![{(b.get("caption") or "").strip()}]({(b.get("src") or "").strip()})')
        elif t == "photo":
            ref = (b.get("ref") or "").strip()
            cap = (b.get("caption") or "").strip()
            attrs = f'ref="{ref}"' + (f' caption="{cap}"' if cap else "")
            out.append("{{< photo " + attrs + " >}}")
        elif t in ("ul", "ol"):
            # one string, not one per item: joining the whole `out` list with a
            # blank line would otherwise separate the items and markdown would
            # render a LOOSE list (every <li> wrapped in its own <p>).
            items = [it.strip() for it in b.get("items", []) if it.strip()]
            if items:
                out.append("\n".join((f"{n}. " if t == "ol" else "- ") + it
                                      for n, it in enumerate(items, 1)))
        elif t == "raw":
            out.append(b.get("md", ""))
    return "\n\n".join(x for x in out if x is not None) + "\n"


# ------------------------------------------------------------------ essay io
def essay_list():
    items = []
    for p in sorted(WRITING.glob("*.md")):
        if p.name == "_index.md":
            continue
        fm, raw, body = split_front(p.read_text())
        items.append({
            "slug": p.stem, "file": p.name,
            "title": fm.get("title", p.stem),
            "subtitle": fm.get("subtitle", ""),
            "date": fm.get("date", ""), "category": fm.get("category", ""),
            "series": fm.get("series", ""),
            "words": len(body.split()),
            "blocks": len(md_to_blocks(body)),
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def essay_load(slug):
    p = WRITING / f"{slug}.md"
    fm, raw, body = split_front(p.read_text())
    return {"slug": slug, "front": fm, "raw_front": raw, "blocks": md_to_blocks(body)}


def essay_save(slug, front_updates, blocks):
    p = WRITING / f"{slug}.md"
    fm, raw, body = split_front(p.read_text())
    bak = p.with_suffix(".md.bak")
    shutil.copy2(p, bak)                       # one-deep undo on disk
    text = join_front(raw, front_updates) + blocks_to_md(blocks)
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(text)
    os.replace(tmp, p)
    return len(text)


def photo_refs():
    """Photos that carry an essay_ref, for the insert-photo picker."""
    m = json.loads((DATA / "photos.json").read_text())
    out = []
    for k, r in m.items():
        ref = (r.get("essay_ref") or "").strip()
        if ref:
            out.append({"ref": ref, "key": k, "thumb": r.get("thumb"),
                        "city": r.get("city"), "file": r.get("file"),
                        "notes": (r.get("tag_notes") or "")[:140]})
    out.sort(key=lambda x: x["ref"])
    return out


# -------------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = json.dumps(obj).encode() if ctype == "application/json" else obj
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        if path == "/":
            return self._send(200, TEMPLATE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/essays":
            return self._send(200, {"essays": essay_list(), "refs": photo_refs()})
        if path == "/api/essay":
            try:
                return self._send(200, essay_load(q["slug"][0]))
            except FileNotFoundError:
                return self._send(404, {"error": "no such essay"})
        if path.startswith("/thumb/"):
            rel = unquote(path[len("/thumb/"):])
            f = (DERIV / rel).resolve()
            if not str(f).startswith(str(DERIV.resolve())) or not f.exists():
                return self._send(404, {"error": "no"})
            return self._send(200, f.read_bytes(), "image/webp")
        if path == "/api/css":
            return self._send(200, (REPO / "assets" / "css" / "main.css").read_bytes(),
                              "text/css; charset=utf-8")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or "{}")
        if u.path == "/api/save":
            with _lock:
                size = essay_save(data["slug"], data.get("front", {}), data.get("blocks", []))
            return self._send(200, {"ok": True, "bytes": size})
        return self._send(404, {"error": "not found"})


def main():
    if not WRITING.exists():
        sys.exit(f"no writing directory at {WRITING}")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Essay editor running at {url}  (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    srv.serve_forever()


if __name__ == "__main__":
    main()
