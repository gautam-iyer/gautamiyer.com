#!/usr/bin/env python3
"""Splice development-level scatter data from the NYCHA analysis workbook into
assets/js/projects/nycha.js (replaces the /*__DATA__*/[...] literal).

Usage: python3 scripts/nycha_extract.py [path-to-xlsx]

New construction only (TYPE == 'NEW CONST'), rows with a completion date and a
positive story count. The era-pivot arrays at the top of nycha.js come from the
workbook's Pivots sheet — update those by hand (or extend this script) if the
pivots change.
"""
import json
import re
import sys
from pathlib import Path

import openpyxl

DEFAULT_XLSX = ("/Users/gautamiyer/Documents/Key Personal Docs/"
                "Mapping and Analysis/2026-02-04_NYCHA-Analysis.xlsx")
JS = Path(__file__).resolve().parent.parent / "assets/js/projects/nycha.js"


def titlecase(s):
    t = str(s).title()
    # fix ordinals ("178Th" -> "178th") and possessives ("'S" -> "'s")
    t = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), t)
    return t.replace("'S ", "'s ")


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["2026-02-04_NYCHA-Analysis"]
    rows = list(ws.iter_rows(values_only=True))
    head = {h: i for i, h in enumerate(rows[0])}

    pts = []
    for r in rows[1:]:
        if r[head["TYPE"]] != "NEW CONST":
            continue
        st, dt = r[head["Number of Stories (Single #)"]], r[head["DATE"]]
        if st is None or dt is None:
            continue
        if isinstance(dt, str):  # some cells are date strings, not datetimes
            m = re.match(r"(\d{4})-(\d{2})", dt)
            if not m:
                continue
            dt = type("D", (), {"year": int(m.group(1)), "month": int(m.group(2))})
        try:
            st = float(st)
        except (TypeError, ValueError):
            continue
        if st <= 0:
            continue
        boro = r[head["BOROUGH"]]
        pts.append([
            round(dt.year + (dt.month - 1) / 12, 2),
            int(st) if st == int(st) else st,
            titlecase(r[head["DEVELOPMENT"]]),
            titlecase(boro) if boro else "",
        ])
    pts.sort()

    src = JS.read_text()
    lit = json.dumps(pts, ensure_ascii=False, separators=(",", ":"))
    new = re.sub(r"/\*__DATA__\*/\[.*?\](?=;)", "/*__DATA__*/" + lit, src,
                 count=1, flags=re.S)
    if new == src:
        sys.exit("no /*__DATA__*/ literal found in " + str(JS))
    JS.write_text(new)
    print(f"spliced {len(pts)} developments into {JS}")


if __name__ == "__main__":
    main()
