#!/usr/bin/env python3
"""Map raw room names from a contract JSON to structured attributes. Stdlib only.

Usage:
  python3 map_rooms.py contract.json            # writes room_catalog back into the JSON
  python3 map_rooms.py contract.json --dry-run  # print catalog without writing

Vocabulary lives in room_vocab.json next to this script - extend it there
(patterns are accent-insensitive, matched longest-first) rather than in code.

For each unique room name in rates[] (plus room references in supplements),
produces an entry:
  {"raw", "code", "room_type", "category", "view", "bedding", "accessible",
   "amenities", "capacity_hint", "unmatched_tokens", "confidence", "note"}

confidence: high = room_type matched and no unmatched tokens;
            medium = room_type matched but leftovers remain;
            low = room_type not matched. Claude reviews medium/low entries
            and completes attributes manually (see SKILL.md).
Exit code: 0 if all high, 1 if any medium/low (review needed).
"""
import argparse
import json
import os
import re
import sys
import unicodedata

VOCAB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "room_vocab.json")


def norm(s):
    """Lowercase, strip accents, collapse separators to single spaces."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " " + re.sub(r"\s+", " ", s).strip() + " "


def compile_group(group):
    """[(key, meta, compiled_pattern)] sorted longest pattern first."""
    entries = []
    for key, meta in group.items():
        for p in meta["patterns"]:
            entries.append((key, meta, p))
    entries.sort(key=lambda e: len(e[2]), reverse=True)
    return [(k, m, re.compile(r"(?<= )" + re.escape(norm(p).strip()) + r"(?= )"))
            for k, m, p in entries]


def consume_first(text, compiled):
    """Return (key, meta, remaining_text) for the first (longest) match, else (None, None, text)."""
    for key, meta, rx in compiled:
        m = rx.search(text)
        if m:
            return key, meta, text[:m.start()] + " " + text[m.end():]
    return None, None, text


def consume_all(text, compiled):
    """Return (sorted unique keys, remaining_text)."""
    found = []
    changed = True
    while changed:
        changed = False
        for key, meta, rx in compiled:
            m = rx.search(text)
            if m:
                found.append(key)
                text = text[:m.start()] + " " + text[m.end():]
                changed = True
    return sorted(set(found)), text


def map_room(raw, vocab, compiled):
    text = norm(raw)

    accessible = False
    for rx in compiled["accessible"]:
        if rx.search(text):
            accessible = True
            text = rx.sub(" ", text)

    view, view_meta, text = consume_first(text, compiled["view"])
    bedding, _, text = consume_first(text, compiled["bedding"])
    rtype, rtype_meta, text = consume_first(text, compiled["room_type"])
    category, cat_meta, text = consume_first(text, compiled["category"])
    amenities, text = consume_all(text, compiled["amenities"])

    stop = set(vocab["stopwords"])
    unmatched = [t for t in text.split() if t and t not in stop and not t.isdigit()]

    if rtype is None:
        confidence = "low"
    elif unmatched:
        confidence = "medium"
    else:
        confidence = "high"

    code_parts = []
    code_parts.append(rtype_meta["code"] if rtype_meta else "UNK")
    if cat_meta:
        code_parts.append(cat_meta["code"])
    if view_meta:
        code_parts.append(view_meta["code"])
    if accessible:
        code_parts.append("ACC")

    return {
        "raw": raw,
        "code": "-".join(code_parts),
        "room_type": rtype,
        "category": category,
        "view": view,
        "bedding": bedding,
        "accessible": accessible,
        "amenities": amenities,
        "capacity_hint": rtype_meta["capacity"] if rtype_meta else None,
        "unmatched_tokens": unmatched,
        "confidence": confidence,
        "note": None,
        "mapped_by": "script"
    }


def collect_room_names(contract):
    names = []
    for r in contract.get("rates") or []:
        n = r.get("room")
        if n and n not in names:
            names.append(n)
    for s in contract.get("supplements") or []:
        a = s.get("applies_to") or ""
        if a.startswith("room:"):
            n = a[5:]
            if n and n not in names:
                names.append(n)
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contract")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(VOCAB_PATH, encoding="utf-8") as fh:
        vocab = json.load(fh)
    compiled = {
        "room_type": compile_group(vocab["room_type"]),
        "category": compile_group(vocab["category"]),
        "view": compile_group(vocab["view"]),
        "bedding": compile_group(vocab["bedding"]),
        "amenities": compile_group(vocab["amenities"]),
        "accessible": [re.compile(r"(?<= )" + re.escape(norm(p).strip()) + r"(?= )")
                       for p in sorted(vocab["accessible"]["patterns"], key=len, reverse=True)],
    }

    with open(args.contract, encoding="utf-8") as fh:
        contract = json.load(fh)

    existing = {e["raw"]: e for e in contract.get("room_catalog") or []}
    catalog = []
    for raw in collect_room_names(contract):
        prev = existing.get(raw)
        if prev and prev.get("mapped_by") == "llm":
            catalog.append(prev)  # never overwrite Claude's manual completion
        else:
            catalog.append(map_room(raw, vocab, compiled))

    review = [e for e in catalog if e["confidence"] != "high" and e.get("mapped_by") != "llm"]

    if not args.dry_run:
        contract["room_catalog"] = catalog
        with open(args.contract, "w", encoding="utf-8") as fh:
            json.dump(contract, fh, indent=2, ensure_ascii=False)

    print(json.dumps({
        "status": "review_needed" if review else "ok",
        "mapped": len(catalog),
        "needs_review": [{"raw": e["raw"], "confidence": e["confidence"],
                          "unmatched_tokens": e["unmatched_tokens"]} for e in review],
        "catalog": catalog if args.dry_run else None
    }, indent=2, ensure_ascii=False))
    sys.exit(1 if review else 0)


if __name__ == "__main__":
    main()
