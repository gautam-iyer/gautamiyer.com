#!/usr/bin/env python3
"""
Essay editor — a dependency-free local web app for writing and laying out the
prose in content/work/*.md — essays, walking tours and data pieces alike.

Run:   python3 scripts/work/editor.py           (opens http://localhost:8801)

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

import json, os, re, shutil, sys, threading, time, webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

PORT = 8801
REPO = Path(__file__).resolve().parents[2]
WORK = REPO / "content" / "work"
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
CHART_RE = re.compile(r'\{\{<\s*chart\s+(.*?)\s*>\}\}')
PHOTOS_OPEN_RE = re.compile(r'^\{\{<\s*photos\s*>\}\}$')
PHOTOS_SHUT_RE = re.compile(r'^\{\{<\s*/\s*photos\s*>\}\}$')
IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)\)$')
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def front_list(raw_lines, key):
    """Read a YAML list out of the raw front matter (`scripts:` / `contents:`).
    split_front is deliberately line-based and only models flat `key: "value"`,
    so a list arrives as nothing; this reads just the indented `- item` run that
    follows `key:` and leaves everything else alone."""
    out, collecting = [], False
    for line in raw_lines:
        if re.match(rf'^{key}:\s*$', line):
            collecting = True
            continue
        if collecting:
            m = re.match(r'^\s+-\s*(.*)$', line)
            if not m:
                break
            v = m.group(1).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out.append(v)
    return out


def chart_ids(slug):
    """The chart ids a piece's own JS binds to, for the insert-a-chart picker.

    A {{< chart >}} draws nothing by itself — it is a scaffold the script finds
    by getElementById. So the ids that actually work are exactly the ones in
    that piece's `scripts`, and inventing one silently renders an empty box."""
    p = WORK / f"{slug}.md"
    if not p.exists():
        return []
    fm, raw, body = split_front(p.read_text())
    ids, seen = [], set()
    for rel in front_list(raw, "scripts"):
        f = REPO / "assets" / rel
        if not f.exists() or "vendor" in rel:
            continue
        src = f.read_text()
        for cid in re.findall(r"""(?:ctx|fig|getElementById)\(\s*['"]([\w-]+)['"]""", src):
            # `<id>-model` is EMITTED by the shortcode's model="true", not a
            # figure to place. Offering it would render an empty second box.
            if cid.endswith("-model"):
                continue
            if cid not in seen:
                seen.add(cid)
                ids.append(cid)
    placed = set(b.get("id") for b in md_to_blocks(body) if b.get("type") == "chart")
    return [{"id": c, "placed": c in placed} for c in ids]


def photo_search(q, limit=120):
    """Search the manifest for the insert-by-key picker.

    Most photos have no essay_ref (one, today), so a piece that wants a specific
    frame has to name it by manifest key. Searched server-side rather than
    shipping 4,000+ records to the browser. Withheld photos are RETURNED but
    marked — the publish gate means they render nothing, and the writer needs to
    see that here rather than at deploy time."""
    m = json.loads((DATA / "photos.json").read_text())
    reg = json.loads((DATA / "collections.json").read_text())["collections"]
    withheld = {c["slug"] for c in reg if c.get("withheld")}
    terms = [t for t in (q or "").lower().split() if t]
    out = []
    for k, r in m.items():
        if not r.get("thumb"):
            continue
        hay = " ".join(str(x) for x in (
            k, r.get("city") or "", r.get("neighborhood") or "",
            r.get("tag_notes") or "", r.get("essay_ref") or "")).lower()
        if terms and not all(t in hay for t in terms):
            continue
        out.append({"key": k, "thumb": r.get("thumb"),
                    "ref": (r.get("essay_ref") or "").strip(),
                    "city": r.get("city") or "",
                    "nbhd": r.get("neighborhood") or "",
                    "withheld": bool(withheld & set(r.get("collections") or []))})
        if len(out) >= limit:
            break
    return out


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
        # A chart is a FIGURE SCAFFOLD, not a drawing: the piece's JS binds to
        # its id. Modelling it as a block lets a figure be dragged into the
        # argument instead of living in a fixed list under the prose.
        mc = CHART_RE.match(s)
        if mc:
            a = dict(ATTR_RE.findall(mc.group(1)))
            blocks.append({"type": "chart", "id": a.get("id", ""),
                           "title": a.get("title", ""), "sub": a.get("sub", ""),
                           "h": a.get("h", ""), "model": bool(a.get("model"))})
            i += 1; continue
        # A photo ROW: {{< photos >}} wrapping two-ish {{< photo >}}. Consumed
        # whole so the inner shortcodes never reach the photo branch below and
        # get flattened into separate full-width figures.
        if PHOTOS_OPEN_RE.match(s):
            i += 1
            items = []
            while i < len(lines) and not PHOTOS_SHUT_RE.match(lines[i].strip()):
                mp = PHOTO_RE.match(lines[i].strip())
                if mp:
                    a = dict(ATTR_RE.findall(mp.group(1)))
                    items.append({"ref": a.get("ref", ""), "key": a.get("key", ""),
                                  "caption": a.get("caption", "")})
                i += 1
            i += 1                                   # step past the closer
            blocks.append({"type": "photos", "items": items})
            continue
        m = PHOTO_RE.match(s)
        if m:
            attrs = dict(ATTR_RE.findall(m.group(1)))
            blocks.append({"type": "photo", "ref": attrs.get("ref", ""),
                           "key": attrs.get("key", ""),
                           "caption": attrs.get("caption", "")})
            i += 1; continue
        # Fenced code: keep the whole fence verbatim. The paragraph collector
        # would otherwise strip each line and join them with spaces, turning a
        # code block into one unrunnable line.
        mf = re.match(r'^(```|~~~)', s)
        if mf:
            fence = mf.group(1)
            buf = [lines[i]]; i += 1
            while i < len(lines):
                buf.append(lines[i])
                if lines[i].strip().startswith(fence): i += 1; break
                i += 1
            blocks.append({"type": "raw", "md": "\n".join(buf)}); continue
        # Table rows and indented code: also verbatim, same reason.
        if s.startswith("|") or re.match(r'^ {4,}\S', line):
            buf = []
            while i < len(lines) and (lines[i].strip().startswith("|")
                                      or re.match(r'^ {4,}\S', lines[i])):
                buf.append(lines[i]); i += 1
            blocks.append({"type": "raw", "md": "\n".join(buf)}); continue
        mi = IMAGE_RE.match(s)
        if mi:
            blocks.append({"type": "image", "src": mi.group(2),
                           "caption": mi.group(1)})
            i += 1; continue
        if re.match(r'^(---|\*\*\*|___)\s*$', s):
            blocks.append({"type": "hr"}); i += 1; continue
        # Any ATX heading. h1 maps to h2 (the page supplies the h1) and h4-h6
        # to h3, so every heading round-trips as SOMETHING rather than falling
        # through to the paragraph collector, which used to spin forever on it.
        mh = re.match(r'^(#{1,6})\s+(.*)$', s)
        if mh:
            lvl = len(mh.group(1))
            blocks.append({"type": "h2" if lvl <= 2 else "h3",
                           "html": inline_to_html(mh.group(2))})
            i += 1; continue
        if s.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            blocks.append({"type": "quote", "html": inline_to_html(" ".join(buf))}); continue
        mo = re.match(r'^(\d+)\. ', s)
        if re.match(r'^[-*+] ', s) or mo:
            ordered = bool(mo)
            # Preserve where an ordered list STARTS. The essays split their
            # numbered sections into single-item lists (2., 3., 4. …), so
            # renumbering from 1 on every save silently relabelled them all.
            start = int(mo.group(1)) if mo else 1
            items = []
            while i < len(lines):
                t = lines[i].strip()
                if ordered and re.match(r'^\d+\. ', t): items.append(inline_to_html(re.sub(r'^\d+\.\s*', '', t)))
                elif not ordered and re.match(r'^[-*+] ', t): items.append(inline_to_html(t[2:]))
                else: break
                i += 1
            b = {"type": "ol" if ordered else "ul", "items": items}
            if ordered and start != 1: b["start"] = start
            blocks.append(b); continue
        # Paragraph: consume until a blank line or a block starter.
        start = i
        buf = []
        while i < len(lines):
            t = lines[i].strip()
            if not t or PHOTO_RE.match(t) or IMAGE_RE.match(t) \
               or CHART_RE.match(t) or PHOTOS_OPEN_RE.match(t) or PHOTOS_SHUT_RE.match(t) \
               or re.match(r'^(---|\*\*\*|___)\s*$', t) \
               or re.match(r'^#{1,6}(\s|$)', t) or t.startswith("> ") \
               or re.match(r'^[-*+] ', t) or re.match(r'^\d+\. ', t):
                break
            buf.append(t); i += 1
        if buf:
            blocks.append({"type": "p", "html": inline_to_html(" ".join(buf))})
        elif i == start:
            # NOTHING was consumed and nothing matched a known block: this line
            # is something we do not model (a bare '#', a code fence, a table).
            # Keep it verbatim as a `raw` block and ALWAYS advance. Without this
            # the loop spun forever, and because essay_list() parses every file
            # a single such line bricked the whole editor, not just one essay.
            blocks.append({"type": "raw", "md": lines[i]})
            i += 1
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
            # Only convert items that are still HTML. The editor's harvest()
            # already sends markdown, and converting twice ran the tag-stripper
            # and entity-unescaper over plain text: "Use <div> tags" lost the
            # <div>, and a literal &amp; collapsed to &.
            b["items"] = [x if b.get("items_are_md") else html_to_md(x)
                          for x in b.get("items", [])]
        out.append(b)
    return out


def _photo_tag(b, indent=""):
    """One {{< photo >}}. `ref` is preferred and wins if both are set — it is
    the stable name. A double quote in a caption would close the attribute
    early and silently truncate it on the next read."""
    ref = (b.get("ref") or "").strip()
    key = (b.get("key") or "").strip()
    cap = (b.get("caption") or "").strip().replace('"', "&quot;")
    name = f'ref="{ref}"' if ref else f'key="{key}"'
    return indent + "{{< photo " + name + (f' caption="{cap}"' if cap else "") + " >}}"


def blocks_to_md(blocks):
    blocks = blocks_html_to_md(blocks)
    out = []
    for b in blocks:
        t = b.get("type")
        md = (b.get("md") or "").strip()
        if t == "p":     out.append(md)
        elif t in ("h2", "h3"):
            # An EMPTY heading must not serialise to a bare "## ". That line is
            # not a heading to any markdown parser, and it used to feed straight
            # back into the block reader as an unparseable line. Insert a
            # heading, type nothing, autosave -> the essay became unopenable.
            if md:
                out.append(("## " if t == "h2" else "### ") + md)
        elif t == "quote":
            for ln in (md or "").split("\n"):
                out.append("> " + ln)
        elif t == "hr":  out.append("---")
        elif t == "image":
            out.append(f'![{(b.get("caption") or "").strip()}]({(b.get("src") or "").strip()})')
        elif t == "photo":
            out.append(_photo_tag(b))
        elif t == "photos":
            items = [_photo_tag(x, indent="  ") for x in b.get("items", [])
                     if (x.get("ref") or x.get("key"))]
            if items:
                out.append("{{< photos >}}\n" + "\n".join(items) + "\n{{< /photos >}}")
        elif t == "chart":
            cid = (b.get("id") or "").strip()
            if cid:
                a = [f'id="{cid}"']
                for k in ("title", "sub", "h"):
                    v = (b.get(k) or "").strip().replace('"', "&quot;")
                    if v:
                        a.append(f'{k}="{v}"')
                if b.get("model"):
                    a.append('model="true"')
                out.append("{{< chart " + " ".join(a) + " >}}")
        elif t in ("ul", "ol"):
            # one string, not one per item: joining the whole `out` list with a
            # blank line would otherwise separate the items and markdown would
            # render a LOOSE list (every <li> wrapped in its own <p>).
            items = [it.strip() for it in b.get("items", []) if it.strip()]
            if items:
                first = int(b.get("start") or 1)
                out.append("\n".join((f"{n}. " if t == "ol" else "- ") + it
                                      for n, it in enumerate(items, first)))
        elif t == "raw":
            out.append(b.get("md") or "")
    return "\n\n".join(x for x in out if x is not None) + "\n"


# ------------------------------------------------------------------ essay io
def essay_list():
    items = []
    for p in sorted(WORK.glob("*.md")):
        if p.name == "_index.md":
            continue
        fm, raw, body = split_front(p.read_text())
        items.append({
            "slug": p.stem, "file": p.name,
            "title": fm.get("title", p.stem),
            "subtitle": fm.get("subtitle", ""),
            "date": fm.get("date", ""), "form": fm.get("form", "Essay"),
            "series": fm.get("series", ""),
            "words": len(body.split()),
            "blocks": len(md_to_blocks(body)),
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items


def _thumbs(blocks):
    """Attach a thumbnail path to every photo the editor has to draw.

    md_to_blocks stays pure — it reads markdown and nothing else — so the
    manifest lookup happens here, once, on load. A photo named by `key` has no
    other way to show a picture; one named by `ref` resolves through the same
    map the site uses."""
    m = json.loads((DATA / "photos.json").read_text())
    by_ref = {}
    for k, r in m.items():
        ref = (r.get("essay_ref") or "").strip()
        if ref:
            by_ref.setdefault(ref, r)

    def thumb(item):
        rec = by_ref.get((item.get("ref") or "").strip()) or m.get((item.get("key") or "").strip())
        # A missing thumb is not an error here: it is exactly what a deleted or
        # misspelled photo looks like, and the editor draws it as a gap.
        return (rec or {}).get("thumb") or ""

    for b in blocks:
        if b.get("type") == "photo":
            b["thumb"] = thumb(b)
        elif b.get("type") == "photos":
            for it in b.get("items", []):
                it["thumb"] = thumb(it)
    return blocks


def essay_load(slug):
    p = WORK / f"{slug}.md"
    fm, raw, body = split_front(p.read_text())
    return {"slug": slug, "front": fm, "blocks": _thumbs(md_to_blocks(body))}


BAKDIR = REPO / ".photo-build" / "writing-bak"
_last_bak = {}          # slug -> monotonic time of its last backup
BAK_EVERY = 120         # seconds


class SaveRefused(Exception):
    """A save that would destroy the essay. Surfaced to the client, not written."""


def essay_save(slug, front_updates, blocks):
    # Refuse a slug that escapes content/work. The endpoint is localhost-only
    # but unauthenticated, and any page in the browser can POST to it.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', slug or ""):
        raise SaveRefused(f"bad slug {slug!r}")
    p = (WORK / f"{slug}.md").resolve()
    if p.parent != WORK.resolve() or not p.exists():
        raise SaveRefused(f"no such essay {slug!r}")

    old_text = p.read_text()
    fm, raw, body = split_front(old_text)
    text = join_front(raw, front_updates) + blocks_to_md(blocks)
    _, _, new_body = split_front(text)

    # Guard against a catastrophic shrink. The client defaults `blocks` to [],
    # and blocks_to_md([]) is just "\n" — an empty harvest, a 404'd load or a
    # JS error upstream would otherwise silently empty an 11,000-word essay.
    ow, nw = len(body.split()), len(new_body.split())
    if ow >= 200 and nw < ow * 0.5:
        raise SaveRefused(
            f"refusing to save: body would shrink {ow} -> {nw} words. "
            f"Nothing was written. Reload the editor.")

    # Backups live OUTSIDE content/ (Hugo reads everything under content/, and
    # deploy.sh does `git add -A`), and are rate-limited: the old one-per-save
    # .bak was overwritten by the next autosave ~1s later, so the "undo" never
    # survived long enough to undo anything.
    BAKDIR.mkdir(parents=True, exist_ok=True)
    now = time.monotonic()
    if now - _last_bak.get(slug, -1e9) > BAK_EVERY:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(p, BAKDIR / f"{slug}.{stamp}.md.bak")
        _last_bak[slug] = now

    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(text)
    os.replace(tmp, p)
    return len(text)


def photo_refs():
    """Photos that carry an essay_ref, for the insert-photo picker.

    Mirrors the publish gate. build_index.py builds the site's `refs` map from
    withheld-gated records, so a ref on a `staging`/`needs-review` photo
    resolves to NOTHING once published. The picker used to offer those happily
    and walk the writer straight into a "Missing photo reference" block — the
    mistake is made here, but the warning only arrived at deploy time. Now they
    are marked, and duplicates (which resolve arbitrarily) are marked too."""
    m = json.loads((DATA / "photos.json").read_text())
    reg = json.loads((DATA / "collections.json").read_text())["collections"]
    withheld = {c["slug"] for c in reg if c.get("withheld")}
    seen = {}
    for k, r in m.items():
        ref = (r.get("essay_ref") or "").strip()
        if not ref:
            continue
        seen.setdefault(ref, []).append((k, r))
    out = []
    for ref, owners in seen.items():
        k, r = sorted(owners)[0]                 # build_index picks the same one
        out.append({"ref": ref, "thumb": r.get("thumb"),
                    "city": r.get("city") or "",
                    "withheld": bool(withheld & set(r.get("collections") or [])),
                    "dupes": len(owners) - 1})
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
        if path == "/api/charts":
            return self._send(200, {"charts": chart_ids(q.get("slug", [""])[0])})
        if path == "/api/photos":
            return self._send(200, {"photos": photo_search(q.get("q", [""])[0])})
        if path.startswith("/thumb/"):
            rel = unquote(path[len("/thumb/"):])
            f = (DERIV / rel).resolve()
            if not str(f).startswith(str(DERIV.resolve())) or not f.exists():
                return self._send(404, {"error": "no"})
            return self._send(200, f.read_bytes(), "image/webp")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or "{}")
        if u.path == "/api/save":
            try:
                with _lock:
                    size = essay_save(data["slug"], data.get("front", {}),
                                      data.get("blocks", []))
            except SaveRefused as e:
                return self._send(409, {"ok": False, "error": str(e)})
            return self._send(200, {"ok": True, "bytes": size})
        return self._send(404, {"error": "not found"})


def main():
    if not WORK.exists():
        sys.exit(f"no work directory at {WORK}")
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
