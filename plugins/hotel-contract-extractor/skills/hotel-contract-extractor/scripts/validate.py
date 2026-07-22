#!/usr/bin/env python3
"""Validate a hotel contract JSON file. Stdlib only.

Usage: python3 validate.py contract.json
Exit code 0 = no errors (warnings possible), 1 = errors present, 2 = unusable input.
Prints a JSON report to stdout: {"status", "errors", "warnings", "low_confidence"}.
"""
import json
import re
import sys
from datetime import date, timedelta

BOARDS = {"RO", "BB", "HB", "FB", "AI"}
BASES = {"per_room_per_night", "per_person_per_night",
         "per_room_per_stay", "per_person_per_stay"}
SEGMENTS = {"fit", "group"}
FEE_TYPES = {"board_supplement", "meal", "gala_dinner", "parking", "wifi",
             "city_tax", "vat", "resort_fee", "pet", "cot", "extra_bed",
             "single_supplement", "spa", "transfer", "late_checkout",
             "early_checkin", "cleaning", "other"}
PAYMENTS = {"included", "on_site", "invoiced"}
CHANNELS = {"gds", "platform", "extranet", "api", "direct", "email", "phone", "other"}
RESTRICTION_TYPES = {"no_promo", "min_stay", "no_arrival", "no_departure",
                     "closed_to_arrival", "adults_only_period", "other"}
CORE_FEE_CATEGORIES = {
    "board/meals": {"board_supplement", "meal", "gala_dinner"},
    "parking": {"parking"},
    "wifi": {"wifi"},
    "city_tax": {"city_tax"},
    "taxes/vat": {"vat"},
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s, path, errors):
    if not isinstance(s, str) or not DATE_RE.match(s):
        errors.append(f"{path}: invalid ISO date: {s!r}")
        return None
    try:
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except ValueError:
        errors.append(f"{path}: impossible date: {s!r}")
        return None


def parse_range(obj, path, errors):
    if not isinstance(obj, dict):
        errors.append(f"{path}: expected object with from/to")
        return None
    f = parse_date(obj.get("from"), f"{path}.from", errors)
    t = parse_date(obj.get("to"), f"{path}.to", errors)
    if f and t and f > t:
        errors.append(f"{path}: from {f} is after to {t}")
        return None
    return (f, t) if f and t else None


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"status": "fatal", "errors": ["usage: validate.py <contract.json>"]}))
        sys.exit(2)
    try:
        with open(sys.argv[1], encoding="utf-8") as fh:
            c = json.load(fh)
    except Exception as e:
        print(json.dumps({"status": "fatal", "errors": [f"cannot read JSON: {e}"]}))
        sys.exit(2)

    errors, warnings, low = [], [], []

    # --- top level ---
    for field in ("hotel", "currency", "contract_period", "seasons", "rates", "source"):
        if field not in c:
            errors.append(f"missing required field: {field}")
    if isinstance(c.get("hotel"), dict) and not c["hotel"].get("name"):
        errors.append("hotel.name is required")
    cur = c.get("currency")
    if cur is not None and not (isinstance(cur, str) and re.match(r"^[A-Z]{3}$", cur)):
        errors.append(f"currency must be a 3-letter ISO code, got {cur!r}")

    cp = parse_range(c.get("contract_period", {}), "contract_period", errors)

    # --- seasons ---
    season_codes = {}
    all_ranges = []  # (from, to, season_code)
    for i, s in enumerate(c.get("seasons") or []):
        p = f"seasons[{i}]"
        code = s.get("code")
        if not code:
            errors.append(f"{p}: missing code")
            continue
        if code in season_codes:
            errors.append(f"{p}: duplicate season code {code!r}")
        season_codes[code] = s
        ranges = s.get("ranges") or []
        if not ranges:
            errors.append(f"{p}: season has no date ranges")
        for j, r in enumerate(ranges):
            pr = parse_range(r, f"{p}.ranges[{j}]", errors)
            if pr:
                all_ranges.append((pr[0], pr[1], code))
                if cp and (pr[0] < cp[0] or pr[1] > cp[1]):
                    warnings.append(f"{p}.ranges[{j}] ({pr[0]}..{pr[1]}) extends outside contract_period")

    # overlaps and gaps
    all_ranges.sort()
    for (f1, t1, c1), (f2, t2, c2) in zip(all_ranges, all_ranges[1:]):
        if f2 <= t1:
            errors.append(f"season ranges overlap: {c1} ({f1}..{t1}) and {c2} ({f2}..{t2})")
        elif f2 > t1 + timedelta(days=1):
            warnings.append(
                f"gap between seasons {c1} and {c2}: {t1 + timedelta(days=1)}..{f2 - timedelta(days=1)} "
                "has no rates (hotel closed, or extraction miss?)")
    if cp and all_ranges:
        if all_ranges[0][0] > cp[0]:
            warnings.append(f"no season covers start of contract period ({cp[0]}..{all_ranges[0][0] - timedelta(days=1)})")
        if all_ranges[-1][1] < cp[1]:
            warnings.append(f"no season covers end of contract period ({all_ranges[-1][1] + timedelta(days=1)}..{cp[1]})")

    # --- rates ---
    rates = c.get("rates") or []
    if not rates:
        errors.append("rates: empty")
    seen_keys = set()
    for i, r in enumerate(rates):
        p = f"rates[{i}]"
        if not r.get("room"):
            errors.append(f"{p}: missing room")
        board = r.get("board")
        if board not in BOARDS:
            errors.append(f"{p}: board must be one of {sorted(BOARDS)}, got {board!r}")
        basis = r.get("basis")
        if basis not in BASES:
            errors.append(f"{p}: basis must be one of {sorted(BASES)}, got {basis!r}")
        seg = r.get("segment", "fit")
        if seg not in SEGMENTS:
            errors.append(f"{p}: segment must be one of {sorted(SEGMENTS)}, got {seg!r}")
        if r.get("season") not in season_codes:
            errors.append(f"{p}: unknown season code {r.get('season')!r}")
        price = r.get("price")
        if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
            errors.append(f"{p}: price must be a positive number, got {price!r}")
        occ = r.get("occupancy")
        if occ is not None:
            mn, mx = occ.get("min"), occ.get("max")
            if not (isinstance(mn, int) and isinstance(mx, int) and 1 <= mn <= mx):
                errors.append(f"{p}: occupancy min/max incoherent: {occ!r}")
        for fld in ("min_stay", "release"):
            v = r.get(fld)
            if v is not None and (not isinstance(v, int) or v < 0):
                errors.append(f"{p}: {fld} must be a non-negative integer or null, got {v!r}")
        key = (r.get("room"), board, basis, r.get("season"), r.get("rate_plan", "standard"),
               json.dumps(r.get("occupancy"), sort_keys=True), r.get("segment", "fit"))
        if key in seen_keys:
            errors.append(f"{p}: duplicate rate entry for {key[0]!r}/{board}/{key[3]}/{key[4]}")
        seen_keys.add(key)
        if r.get("confidence") == "low":
            low.append({"path": p, "room": r.get("room"), "field": "rate",
                        "value": price, "note": r.get("note")})

    # --- supplements: fee typing, payment, coverage ---
    found_types = set()
    for i, s in enumerate(c.get("supplements") or []):
        p = f"supplements[{i}]"
        ftype = s.get("type")
        if ftype is None:
            warnings.append(f"{p}: missing 'type' (one of {sorted(FEE_TYPES)})")
        elif ftype not in FEE_TYPES:
            errors.append(f"{p}: unknown fee type {ftype!r}")
        else:
            found_types.add(ftype)
        pay = s.get("payment")
        if pay is not None and pay not in PAYMENTS:
            errors.append(f"{p}: payment must be one of {sorted(PAYMENTS)}, got {pay!r}")
        if s.get("mandatory") is not None and not isinstance(s.get("mandatory"), bool):
            errors.append(f"{p}: mandatory must be a boolean")
        amt = s.get("amount")
        if amt is not None and (not isinstance(amt, (int, float)) or isinstance(amt, bool) or amt < 0):
            errors.append(f"{p}: amount must be a non-negative number, got {amt!r}")
    fee_coverage = {cat: bool(types & found_types)
                    for cat, types in CORE_FEE_CATEGORIES.items()}

    # --- optional arrays: light checks + confidence collection ---
    for arr_name in ("supplements", "reductions", "child_policy", "special_events"):
        for i, item in enumerate(c.get(arr_name) or []):
            p = f"{arr_name}[{i}]"
            if item.get("confidence") == "low":
                low.append({"path": p, "field": arr_name,
                            "value": item.get("label") or item.get("condition"),
                            "note": item.get("note")})
            s_ref = item.get("season")
            if s_ref not in (None,) and s_ref not in season_codes:
                errors.append(f"{p}: unknown season code {s_ref!r}")

    # --- group conditions coherence ---
    has_group_rates = any((r.get("segment", "fit")) == "group" for r in rates)
    gc = c.get("group_conditions")
    if has_group_rates and not gc:
        warnings.append("rates contain segment 'group' but group_conditions is missing "
                        "(min pax, free places, deposits, group cancellation?)")
    if gc and not has_group_rates:
        warnings.append("group_conditions present but no rate has segment 'group'")
    if gc:
        mp = gc.get("min_pax")
        if mp is not None and (not isinstance(mp, int) or mp < 2):
            errors.append(f"group_conditions.min_pax must be an integer >= 2, got {mp!r}")
        fp = gc.get("free_places")
        if fp is not None:
            per = fp.get("per_paying")
            if not isinstance(per, int) or per < 1:
                errors.append(f"group_conditions.free_places.per_paying must be a positive integer, got {per!r}")
        for j, dep in enumerate(gc.get("deposit_schedule") or []):
            if not isinstance(dep.get("days_before"), int) or dep.get("days_before") < 0:
                errors.append(f"group_conditions.deposit_schedule[{j}]: invalid days_before")
            pc = dep.get("percent")
            if not isinstance(pc, (int, float)) or not (0 < pc <= 100):
                errors.append(f"group_conditions.deposit_schedule[{j}]: percent must be in (0,100], got {pc!r}")
        for j, cx in enumerate(gc.get("cancellation") or []):
            if not isinstance(cx.get("days_before"), int):
                errors.append(f"group_conditions.cancellation[{j}]: invalid days_before")
        if gc.get("confidence") == "low":
            low.append({"path": "group_conditions", "field": "group_conditions",
                        "value": None, "note": gc.get("note")})

    # --- commission ---
    comm = c.get("commission")
    if comm:
        model = comm.get("model")
        if model not in ("commissionable", "net"):
            errors.append(f"commission.model must be 'commissionable' or 'net', got {model!r}")
        pct = comm.get("percent")
        if model == "commissionable":
            if not isinstance(pct, (int, float)) or isinstance(pct, bool) or not (0 < pct <= 100):
                errors.append(f"commission.percent must be in (0,100] for commissionable model, got {pct!r}")
        if comm.get("confidence") == "low":
            low.append({"path": "commission", "field": "commission",
                        "value": pct, "note": comm.get("note")})

    # --- booking channels ---
    for i, ch in enumerate(c.get("booking_channels") or []):
        if ch.get("channel") not in CHANNELS:
            errors.append(f"booking_channels[{i}]: channel must be one of {sorted(CHANNELS)}, got {ch.get('channel')!r}")

    # --- promotions ---
    for i, promo in enumerate(c.get("promotions") or []):
        p = f"promotions[{i}]"
        if not promo.get("code") and not promo.get("label"):
            errors.append(f"{p}: needs at least a code or a label")
        for w in ("booking_window", "stay_window"):
            if promo.get(w):
                parse_range(promo[w], f"{p}.{w}", errors)
        dp, da = promo.get("discount_percent"), promo.get("discount_amount")
        if dp is not None and (not isinstance(dp, (int, float)) or not (0 < dp <= 100)):
            errors.append(f"{p}: discount_percent must be in (0,100], got {dp!r}")
        if dp is None and da is None:
            warnings.append(f"{p}: no discount_percent nor discount_amount")
        if promo.get("confidence") == "low":
            low.append({"path": p, "field": "promotion", "value": promo.get("code"),
                        "note": promo.get("note")})

    # --- restrictions ---
    for i, rst in enumerate(c.get("restrictions") or []):
        p = f"restrictions[{i}]"
        if rst.get("type") not in RESTRICTION_TYPES:
            errors.append(f"{p}: type must be one of {sorted(RESTRICTION_TYPES)}, got {rst.get('type')!r}")
        if rst.get("from") or rst.get("to"):
            parse_range({"from": rst.get("from"), "to": rst.get("to")}, p, errors)
        if rst.get("type") == "min_stay" and not isinstance(rst.get("min_nights"), int):
            warnings.append(f"{p}: min_stay restriction without integer min_nights")

    # --- modification policy ---
    for i, mp in enumerate(c.get("modification_policy") or []):
        p = f"modification_policy[{i}]"
        if not isinstance(mp.get("days_before"), int) or mp["days_before"] < 0:
            errors.append(f"{p}: days_before must be a non-negative integer")
        fee = mp.get("fee")
        if fee is not None and (not isinstance(fee, (int, float)) or isinstance(fee, bool) or fee < 0):
            errors.append(f"{p}: fee must be a non-negative number or null, got {fee!r}")

    # --- services ---
    svc = c.get("services") or {}
    for side in ("included", "excluded"):
        for i, s in enumerate(svc.get(side) or []):
            if not s.get("label"):
                errors.append(f"services.{side}[{i}]: missing label")

    # --- pets ---
    pp = c.get("pets_policy")
    if pp is not None and not isinstance(pp.get("allowed"), bool):
        errors.append("pets_policy.allowed must be a boolean")

    # --- identifiers / metadata ---
    idf = c.get("identifiers")
    if idf:
        rc = idf.get("room_codes") or {}
        rate_rooms_all = {r.get("room") for r in rates if r.get("room")}
        for name in rc:
            if name not in rate_rooms_all:
                warnings.append(f"identifiers.room_codes: {name!r} does not match any rate room")
    md = c.get("metadata")
    if md:
        kw = md.get("keywords")
        if kw is not None and (not isinstance(kw, list) or not all(isinstance(k, str) for k in kw)):
            errors.append("metadata.keywords must be a list of strings")
        elif kw is not None and len(kw) < 5:
            warnings.append("metadata.keywords: fewer than 5 keywords, weak searchability")
    else:
        warnings.append("metadata missing: generate keywords for searchability")

    # --- room_catalog coverage ---
    catalog = c.get("room_catalog")
    if catalog is not None:
        cat_names = {e.get("raw") for e in catalog}
        rate_rooms = {r.get("room") for r in rates if r.get("room")}
        for missing in sorted(rate_rooms - cat_names):
            warnings.append(f"room_catalog: no mapping for room {missing!r} (re-run map_rooms.py)")
        for e in catalog:
            if e.get("confidence") in ("low", "medium") and e.get("mapped_by") != "llm":
                low.append({"path": f"room_catalog[{e.get('raw')!r}]", "field": "room_mapping",
                            "value": e.get("code"),
                            "note": f"unmatched tokens: {e.get('unmatched_tokens')}"})
    else:
        warnings.append("room_catalog missing: run map_rooms.py to map room attributes")

    for i, b in enumerate(c.get("blackout_dates") or []):
        pr = parse_range(b, f"blackout_dates[{i}]", errors)
        if pr and cp and (pr[0] > cp[1] or pr[1] < cp[0]):
            warnings.append(f"blackout_dates[{i}] entirely outside contract period")

    for i, ev in enumerate(c.get("special_events") or []):
        parse_range(ev, f"special_events[{i}]", errors)

    status = "errors" if errors else "ok"
    print(json.dumps({"status": status, "errors": errors,
                      "warnings": warnings, "low_confidence": low,
                      "fee_coverage": fee_coverage},
                     indent=2, ensure_ascii=False))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
