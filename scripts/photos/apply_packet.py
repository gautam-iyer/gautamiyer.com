#!/usr/bin/env python3
"""
Apply a changes file exported by the portable tagger (see make_packet.py).

  python3 scripts/photos/apply_packet.py tagging-changes-durham-2026-09-08.json --dry-run
  python3 scripts/photos/apply_packet.py tagging-changes-durham-2026-09-08.json

Safety:
  * Only the fields the packet is allowed to edit are ever written.
  * Values are validated against data/taxonomy.json and collections.json first —
    nothing is written if anything fails validation.
  * Each change carries the `rev` of the record as it was when the packet was
    built. If the live record has moved since (you edited it in the desktop
    tagger meanwhile) that photo is reported as a CONFLICT and skipped unless
    you pass --force-conflicts.
  * The manifest write is guarded: it re-reads and re-hashes so a concurrently
    running tagger cannot be clobbered.
  * Sets reviewed:true on every photo it touches, matching the desktop tagger.
"""
import argparse, hashlib, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packet_common import EDITABLE, MULTI, FLAGS, rev  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
MANIFEST = DATA / "photos.json"





def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("changes")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-conflicts", action="store_true",
                    help="apply even where the live record changed since the packet was built")
    ap.add_argument("--manifest", default=None,
                    help="manifest to write (default data/photos.json). make_packet.py "
                         "has the same flag; without it a packet built from a staging "
                         "manifest would silently apply to the live one.")
    args = ap.parse_args()
    global MANIFEST
    if args.manifest:
        MANIFEST = Path(args.manifest)

    doc = json.loads(Path(args.changes).read_text())
    if doc.get("kind") != "tagging-packet-changes":
        sys.exit("not a tagging packet changes file")
    changes = doc["changes"]
    print(f"packet '{doc.get('label')}' built {doc.get('packet_generated_at')}")
    print(f"exported {doc.get('exported_at')} — {len(changes)} photos changed\n")

    man = json.loads(MANIFEST.read_text())
    live_md5 = hashlib.md5(MANIFEST.read_bytes()).hexdigest()
    if doc.get("manifest_md5") and doc["manifest_md5"] != live_md5:
        print(f"note: the manifest has changed since this packet was built\n"
              f"      packet {doc['manifest_md5'][:12]} vs live {live_md5[:12]} "
              f"({MANIFEST}) — per-photo rev checks below still apply.\n")
    tax = {d["key"]: set(d["values"]) for d in json.loads((DATA / "taxonomy.json").read_text())["dimensions"]}
    slugs = {c["slug"] for c in json.loads((DATA / "collections.json").read_text())["collections"]}

    errs, conflicts, plan = [], [], {}
    for key, entry in changes.items():
        fields = entry.get("fields", {})
        rec = man.get(key)
        if rec is None:
            errs.append(f"{key}: not in the manifest (deleted since the packet was built?)")
            continue
        for f, v in fields.items():
            if f not in EDITABLE:
                errs.append(f"{key}: field '{f}' is not packet-editable"); continue
            if f in tax:
                if not isinstance(v, list): errs.append(f"{key}.{f}: expected a list"); continue
                bad = [x for x in v if x not in tax[f]]
                if bad: errs.append(f"{key}.{f}: not in taxonomy {bad}")
            elif f == "collections":
                if not isinstance(v, list): errs.append(f"{key}.collections: expected a list"); continue
                bad = [x for x in v if x not in slugs]
                if bad: errs.append(f"{key}.collections: unknown slug(s) {bad}")
            elif f in FLAGS:
                if not isinstance(v, bool): errs.append(f"{key}.{f}: expected true/false")
            elif f == "medium":
                if v not in (None, "Digital", "Film"): errs.append(f"{key}.medium: {v!r}")
            elif v is not None and not isinstance(v, str):
                errs.append(f"{key}.{f}: expected text")
        if entry.get("rev") and entry["rev"] != rev(rec):
            conflicts.append(key)
        plan[key] = fields

    if errs:
        print(f"VALIDATION FAILED — {len(errs)} problem(s), nothing written:")
        for e in errs[:30]: print("  ", e)
        sys.exit(1)
    print("validation OK")

    if conflicts:
        print(f"\n!! {len(conflicts)} CONFLICT(S) — these moved in the live manifest since the packet was built:")
        for k in conflicts[:20]: print("   ", k)
        if not args.force_conflicts:
            print("   skipping them. Re-run with --force-conflicts to overwrite.")
            for k in conflicts: plan.pop(k, None)

    # summary
    n_field = sum(len(v) for v in plan.values())
    from collections import Counter
    per = Counter(f for v in plan.values() for f in v)
    print(f"\nwill update {len(plan)} photos / {n_field} fields")
    for f, n in per.most_common(): print(f"   {f:18} {n}")
    # show a couple of concrete before/afters
    for k in list(plan)[:3]:
        print(f"\n  {k}")
        for f, v in plan[k].items():
            print(f"     {f}: {man[k].get(f)!r} -> {v!r}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return
    if not plan:
        print("\nnothing to apply")
        return

    for attempt in range(6):
        before = hashlib.md5(MANIFEST.read_bytes()).hexdigest()
        live = json.loads(MANIFEST.read_text())
        missing = [k for k in plan if k not in live]
        if missing: sys.exit(f"record vanished mid-apply: {missing[:3]}")
        for k, fields in plan.items():
            changed = False
            for f, v in fields.items():
                new = sorted(v) if f in MULTI and isinstance(v, list) else v
                cur = live[k].get(f)
                cur_cmp = sorted(cur) if f in MULTI and isinstance(cur, list) else cur
                if new != cur_cmp:
                    changed = True
                live[k][f] = new
            # reviewed:true is a ONE-WAY exclusion from vision tagging
            # (pipeline.cmd_tag_apply skips reviewed records forever), so only
            # set it when a field genuinely moved. A no-op edit used to lock a
            # photo out of tagging permanently.
            if changed:
                live[k]["reviewed"] = True
                if any(f not in FLAGS for f in fields):
                    live[k]["tagged"] = True
        ordered = dict(sorted(live.items(), key=lambda kv: (kv[1].get("shoot") or "", kv[1].get("img_no") or 0, kv[0])))
        payload = json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"
        if hashlib.md5(MANIFEST.read_bytes()).hexdigest() != before:
            print("  live manifest moved (tagger is running) — retrying"); time.sleep(0.4); continue
        # Atomic, matching tagger.atomic_write: data/photos.json IS the publish
        # list, and a truncating write interrupted midway leaves it unparseable.
        tmp = MANIFEST.with_suffix(".json.tmp")
        tmp.write_text(payload)
        os.replace(tmp, MANIFEST)
        print(f"\nAPPLIED: {len(plan)} photos updated, reviewed:true set on each.")
        print("Next: python3 scripts/photos/build_index.py && python3 scripts/photos/pipeline.py status")
        return
    sys.exit("could not get a clean write window — stop the tagger and re-run")


if __name__ == "__main__":
    main()
