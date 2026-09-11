#!/usr/bin/env python3
"""
Shared contract between make_packet.py and apply_packet.py.

These two are coupled through a HASH, not through behaviour: make_packet stamps
each photo with rev(record) and apply_packet recomputes it to detect a record
that moved while the packet was out. If the two copies of EDITABLE or rev() ever
drift, every photo in every packet becomes a false CONFLICT and is silently
skipped — and the only way out is --force-conflicts, which disables the one
check that matters. So they live here, once.
"""
import hashlib
import json

# The per-photo fields a packet may change: pipeline.TAG_FIELDS plus the geo
# hierarchy and the curation flags the tagger's Tag mode edits.
EDITABLE = ["sub_neighborhood", "neighborhood", "city", "state",
            "land_use", "architecture", "subject", "medium", "tone",
            "tag_notes", "collections", "hero", "place_cover", "cull"]

# Stored as arrays; order is not meaningful.
MULTI = ["land_use", "architecture", "subject", "tone", "collections"]

# Booleans that are absent-means-false on most records.
FLAGS = ["hero", "place_cover", "cull"]


def rev(rec):
    """Short hash of a record's editable state, used to spot a photo that moved
    in the live manifest while a packet was out."""
    payload = json.dumps({f: rec.get(f) for f in EDITABLE},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()[:10]
