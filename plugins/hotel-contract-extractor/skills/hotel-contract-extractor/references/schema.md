# Contract JSON Schema (detailed)

All dates: ISO `YYYY-MM-DD`. All prices: numbers (no currency symbols, dot
decimal). Unknown optional values: `null`, never empty strings.

## Top level

| Field | Required | Type | Notes |
|---|---|---|---|
| `hotel` | yes | object | `name` required; `location`, `category`, `contact` optional |
| `currency` | yes | string | ISO 4217, 3 letters (EUR, USD, MAD...) |
| `contract_period` | yes | object | `{"from","to"}` |
| `seasons` | yes | array | at least 1 |
| `rates` | yes | array | at least 1 |
| `supplements` | no | array | |
| `reductions` | no | array | |
| `child_policy` | no | array | |
| `cancellation` | no | array | |
| `blackout_dates` | no | array | `{"from","to","reason"}` |
| `special_events` | no | array | `{"label","from","to","effect"}` |
| `source` | yes | object | `{"file","pages_used"}` traceability |

## seasons[]

```json
{"code": "A", "label": "Basse saison",
 "ranges": [{"from": "2026-04-01", "to": "2026-06-30"},
            {"from": "2026-09-15", "to": "2026-10-31"}]}
```

- `code`: short unique key referenced by rates. Use the contract's own codes
  when present (A/B/C, 1/2/3, Low/High), else assign A, B, C in date order.
- A season may have multiple non-contiguous ranges (very common).
- Ranges across seasons must not overlap. Gaps are allowed but will raise a
  validation warning (hotel closure vs extraction miss - verify).

## rates[]

```json
{"room": "Double Vue Mer", "room_code": null,
 "board": "HB", "basis": "per_person_per_night",
 "season": "B", "price": 89.0,
 "occupancy": {"min": 2, "max": 2},
 "min_stay": 3, "release": 14,
 "rate_plan": "standard",
 "confidence": "high", "note": null}
```

- `board`: `RO` (room only), `BB`, `HB`, `FB`, `AI`. If the contract uses
  local wording ("logement seul", "petit-déjeuner inclus", "pension
  complète"), map it and note the original wording if non-obvious.
- `basis`: the single most error-prone field. French contracts often state
  "prix par personne et par nuit en chambre double" - that is
  `per_person_per_night` with occupancy min 2. If truly undeterminable,
  choose the most probable, set confidence low, explain in note.
- `rate_plan`: `standard` by default; use `early_booking`, `non_refundable`,
  `long_stay`, etc. for variant grids. One entry per plan × room × board ×
  season.
- `min_stay` / `release`: nights / days. `null` if not stated.

## rates[].segment - FIT vs groups

Every rate entry carries `"segment": "fit"` (individual/leisure, the
default) or `"segment": "group"`. Contracts frequently contain two grids:
extract BOTH as separate rate entries, never average or merge them. If the
contract only covers one segment, do not fabricate the other.

Typical group markers in contracts: "tarifs groupes", "à partir de 15/20
personnes", "group rates", "series", "GIT". FIT markers: "tarifs
individuels", "FIT", "leisure".

## group_conditions (top level, optional)

Required in practice whenever any rate has `segment: "group"`:

```json
{"min_pax": 20,
 "free_places": {"per_paying": 20, "basis": "full_paying", "note": null},
 "deposit_schedule": [
   {"days_before": 60, "percent": 30.0, "note": null},
   {"days_before": 30, "percent": 100.0, "note": null}],
 "cancellation": [
   {"days_before": 30, "penalty": "no penalty", "penalty_type": "none", "penalty_value": null},
   {"days_before": 15, "penalty": "50%", "penalty_type": "percent", "penalty_value": 50.0},
   {"days_before": 0, "penalty": "full stay", "penalty_type": "full_stay", "penalty_value": null}],
 "rooming_list_deadline_days": 14,
 "confidence": "high", "note": null}
```

- `free_places.per_paying`: "1 gratuité par 20 payants" → 20. Note whether
  the free place is in single or shared room if the contract says so.
- Group cancellation is usually per-pax partial release ("réduction du
  groupe jusqu'à 10% sans frais") - capture that nuance in `note`.
- Group cancellation scales replace, not extend, the FIT `cancellation[]`
  array for group bookings.

## supplements[] / reductions[]

```json
{"type": "city_tax", "label": "Taxe de séjour",
 "applies_to": "all", "board": null, "season": null,
 "basis": "per_person_per_night", "amount": 2.5, "unit": "fixed",
 "mandatory": true, "payment": "on_site",
 "confidence": "high", "note": null}
```

- `type` (required on supplements): `board_supplement` (HB/FB upgrade),
  `meal` (lunch/dinner), `gala_dinner`, `parking`, `wifi`, `city_tax`,
  `vat`, `resort_fee`, `pet`, `cot`, `extra_bed`, `single_supplement`,
  `spa`, `transfer`, `late_checkout`, `early_checkin`, `cleaning`, `other`.
- `mandatory`: true (imposed: city tax, réveillon gala), false (optional:
  parking), null if unstated.
- `payment`: `included` (in the rate, amount may be 0), `on_site`
  (payable at the hotel: taxe de séjour), `invoiced` (billed to the
  operator), null if unstated.
- Free included services ("wifi gratuit", "parking offert") ARE
  extracted: amount 0, payment included - the absence of a fee is
  contract information too.
- `unit`: `fixed` (amount in contract currency) or `percent` (amount = %).
- `season: null` = applies to all seasons. `applies_to`: free text but keep
  it machine-usable (`room:<name>`, `board:HB`, `all`).
- Reductions (3rd bed, child in parents' room, long stay) use the same
  shape with positive `amount`; the sign is implied by the array.

## child_policy[]

```json
{"age_from": 2, "age_to": 11, "condition": "sharing with 2 adults",
 "basis": "percent_of_adult", "value": 50.0, "board": null,
 "confidence": "high", "note": null}
```

`basis`: `free`, `fixed_price`, `percent_of_adult`.
Ages: contracts differ on inclusive/exclusive bounds ("moins de 12 ans" =
age_to 11). Resolve to inclusive integer years; note the original wording.

## cancellation[]

```json
{"days_before": 21, "penalty": "1 night", "penalty_type": "nights",
 "penalty_value": 1.0, "season": null, "note": null}
```

`penalty_type`: `nights`, `percent`, `fixed`, `full_stay`, `none`.
Order entries from most lenient to strictest.

## special_events[]

For trade fairs, New Year's Eve, festivals with mandatory supplements or
mandatory gala dinners:

```json
{"label": "Réveillon 31/12", "from": "2026-12-31", "to": "2026-12-31",
 "effect": "mandatory gala dinner 120 EUR per adult",
 "amount": 120.0, "basis": "per_person", "confidence": "high"}
```

## Extraction pitfalls checklist

Run through this list before finalizing the JSON:

1. **DD/MM vs MM/DD**: French sources are DD/MM. `05/04` in a French
   contract is 5 April.
2. **Split tables**: a rate grid continued on the next page, sometimes with
   the header not repeated. Match columns by position and verify totals.
3. **Footnote asterisks**: `145*` with `* sauf ponts et jours fériés` -
   the asterisk creates a special_event or an extra season, never drop it.
4. **"À partir de" prices**: marketing minimums, not contract rates. Skip
   unless they are the only rates present (then confidence low).
5. **Taxes**: city tax ("taxe de séjour") is usually excluded and per
   person per night - record it as a supplement with a note, do not add it
   to prices.
6. **VAT**: note whether prices are stated HT or TTC in `hotel` or a rate
   note if the contract says so.
7. **Currency symbols in cells**: strip them; verify a single currency for
   the whole contract, otherwise error out and ask the user.
8. **Merged cells**: a price spanning several room rows usually means the
   same price applies to each - confirm against the row structure.

## commission (top level, optional but expected in agency contracts)

```json
{"model": "commissionable", "percent": 12.0,
 "base": "accommodation_only", "vat_on_commission": true,
 "payment_terms": "deducted at source",
 "confidence": "high", "note": "city tax and gala dinners non-commissionable"}
```

- `model`: `commissionable` (gross rates, agency deducts commission) or
  `net` (net rates, agency adds its own markup; percent null).
- `base`: `accommodation_only`, `accommodation_and_board`, `total`.
- Per-rate override: rates and supplements accept `"commissionable":
  false` (city tax and taxes are typically non-commissionable). The
  renderer computes the per-room commission amount from percent × price
  in the Daily sheet - never hand-calculate it into prices.

## booking_channels[]

```json
[{"channel": "gds", "detail": "Amadeus", "identifier": "NCE145",
  "instructions": null, "confidence": "high", "note": null},
 {"channel": "platform", "detail": "Extranet SiteMinder",
  "identifier": null, "instructions": "login provided at signature"},
 {"channel": "direct", "detail": "reservations@hotel-exemple.fr",
  "identifier": null, "instructions": "quote contract ref"}]
```

`channel` enum: `gds`, `platform`, `extranet`, `api`, `direct`, `email`,
`phone`, `other`.

## promotions[]

```json
[{"code": "EARLY30", "label": "Early booking -15%",
  "discount_percent": 15.0, "discount_amount": null,
  "booking_window": {"from": "2026-01-01", "to": "2026-03-31"},
  "stay_window": {"from": "2026-04-01", "to": "2026-10-31"},
  "conditions": "non-refundable, prepayment 100%",
  "combinable": false, "confidence": "high", "note": null}]
```

## restrictions[]

Hard closures stay in `blackout_dates`. Everything else goes here:

```json
[{"type": "no_promo", "from": "2026-07-14", "to": "2026-08-15",
  "detail": "promotions not applicable", "note": null},
 {"type": "min_stay", "from": "2026-12-30", "to": "2027-01-02",
  "detail": "minimum 4 nights", "min_nights": 4},
 {"type": "no_arrival", "from": null, "to": null,
  "detail": "no Saturday arrivals in season B", "note": null}]
```

`type` enum: `no_promo`, `min_stay`, `no_arrival`, `no_departure`,
`closed_to_arrival`, `adults_only_period`, `other`.

## modification_policy[]

Same shape logic as cancellation - what changes are allowed, until when,
at what cost:

```json
[{"days_before": 14, "allowed": "free changes",
  "fee": 0.0, "fee_type": "fixed", "note": "dates and room type"},
 {"days_before": 7, "allowed": "name changes only",
  "fee": 25.0, "fee_type": "fixed", "note": "per modification"},
 {"days_before": 0, "allowed": "no changes",
  "fee": null, "fee_type": null, "note": "treated as cancellation"}]
```

## services

Unpriced inclusions/exclusions (priced items belong in `supplements`):

```json
{"included": [
   {"type": "airport_shuttle", "label": "Navette aéroport",
    "detail": "on request, 24h notice", "confidence": "high", "note": null},
   {"type": "wellness", "label": "Accès spa", "detail": "2h/jour"}],
 "excluded": [
   {"type": "minibar", "label": "Mini-bar", "detail": "consommations facturées"},
   {"type": "room_service", "label": "Room service", "detail": "supplément 8 EUR/plateau"}]}
```

`type` suggestions: `airport_shuttle`, `shuttle`, `wellness`, `gym`,
`beach_access`, `minibar`, `room_service`, `laundry`, `luggage`,
`concierge`, `activities`, `other`.

## pets_policy (top level)

```json
{"allowed": true, "max_weight_kg": 10, "max_count": 1,
 "fee_ref": "see supplements type pet", "restrictions": "except restaurant",
 "confidence": "high", "note": null}
```

If the contract is silent on pets: omit the object entirely (do not
default to allowed/refused) - and say so in the final summary.

## identifiers (top level)

Internal references and system identifiers, as found:

```json
{"contract_ref": "CT-2026-0412", "hotel_codes": {
   "chain_code": "EX", "property_code": "EXNCE01",
   "amadeus": "EXNCE145", "sabre": "12345", "galileo": "67890",
   "worldspan": null, "giata_id": "54321", "duns": null},
 "room_codes": {"Double Standard": "DBLSTD", "Double Vue Mer": "DBLSEA"},
 "confidence": "high", "note": null}
```

`room_codes` maps raw room names to the SUPPLIER's own codes when printed
in the contract (distinct from the normalized codes in room_catalog -
keep both). Copy identifiers character-for-character; never invent codes.

## metadata (top level)

Search and classification aids, generated at extraction:

```json
{"keywords": ["nice", "riviera", "4 étoiles", "seafront", "fit", "groupes",
              "demi-pension", "famille", "pmr"],
 "destination": {"city": "Nice", "region": "Côte d'Azur", "country": "FR"},
 "market": ["fit", "group"], "language": "fr",
 "board_types": ["BB", "HB"], "has_promotions": true,
 "extracted_at": "2026-07-22", "source_pages": 12}
```

Keywords: 8-15 lowercase terms mixing location, category, segments,
board, notable amenities and accessibility - what a colleague would type
to find this contract later.
