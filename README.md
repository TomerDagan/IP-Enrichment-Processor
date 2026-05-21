# IP Enrichment Processor

---

## Overview
Enrich FACT events with partner-family IP and geo coordinates from a time-sliced DIM table.

---

## Input Data
This project uses the provided parquet files:

- `data/fact.parquet`: `(timestamp, user_id, ip)`
- `data/dim.parquet`: `(timestamp, ipv4, ipv6, lat, lon)`

Each event is evaluated against the latest DIM slice such that `dim.timestamp <= event.timestamp`.

---

## Dataset Finding (Current Files)
Analysis of the provided files (`data/fact.parquet`, `data/dim.parquet`) shows that masked CIDR events usually match multiple DIM rows with different geolocations in the selected time slice.

This makes masked enrichment non-deterministic for this dataset, including geo-only enrichment.

Therefore masked events are consistently dropped as ambiguous, because no reliable enrichment can be derived without risking incorrect data.

This behavior is intentional and prioritizes correctness over completeness.

Alternative approaches considered:
- Aggregation (for example mean location)
- Majority voting
- Prefix-level canonicalization

These methods introduce heuristic or synthetic outputs that may not correspond to actual DIM records and can misrepresent the underlying data.

Given the lack of deterministic mapping even at the geographic level, the final design prioritizes correctness and explicitly drops ambiguous events.

---

## Supported IP Shapes
The `ip` field in FACT is parsed using `ipaddress` and must match one of these shapes:

1. Full IPv4 (example: `102.214.136.4`)
2. Full IPv6 (example: `2a00:1450:28b4:17ec:b1eb:468e:2849:5fcc`)
3. Masked IPv4 CIDR with fixed `/24` (example: `102.214.136.0/24`)
4. Masked IPv6 CIDR with fixed `/48` (example: `2a00:1450:28b4::/48`)

If a masked event uses another prefix length, it is dropped with:
- `drop_reason = INVALID_MASK_LENGTH`

---

## Decision Logic
### Full IP Events
- Exact-match on the current DIM slice.
- Enrich only when exactly one DIM row matches.
- Drop reasons: `NO_DIM_MATCH`, `NON_UNIQUE_MATCH`

### Masked IP Events
- Collect all DIM rows in the current slice whose address is inside the event network.
- Enrich only when all candidates agree on geo coordinates `(lat, lon)`.
- If geo conflicts across candidates, drop.

Masked-path rationale:
- A masked network can contain many concrete IPs, so partner-family IP identity is ambiguous.
- The strategy is conservative for identity but practical for geolocation.
- For masked enrichments with a single candidate, output `ipv4` and `ipv6` are populated from that candidate.
- For masked enrichments with multiple candidates that agree on geo, output `ipv4` and `ipv6` are left `null` to avoid claiming a specific concrete IP pair.

Drop reasons for masked path:
- `NO_DIM_MATCH`
- `AMBIGUOUS_PREFIX_GEO_CONFLICT`

---

## Assumptions
1. Masked IP shape is strict by family.
- IPv4 masked inputs must be `/24`.
- IPv6 masked inputs must be `/48`.
- Any other CIDR length is dropped as `INVALID_MASK_LENGTH`.

2. Masked enrichment is geo-oriented, not identity-oriented.
- A masked event is enriched only if all candidates in the selected DIM slice agree on `(lat, lon)`.
- If exactly one candidate exists, `ipv4` and `ipv6` are emitted from that candidate.
- If multiple candidates exist, `ipv4` and `ipv6` are emitted as `null` to avoid implying a specific concrete IP pair.

3. Full-IP enrichment is strict and deterministic.
- Full IP events are enriched only on exactly one exact match in the selected DIM slice.
- `NO_DIM_MATCH` and `NON_UNIQUE_MATCH` are treated as data-quality failures and dropped.

4. Temporal join is slice-local.
- Candidate search is performed only on the latest DIM slice where `dim.timestamp <= event.timestamp`.
- Rows from older/newer slices are not mixed into candidate evaluation.

---

## Output Schema
The processor writes `output/result.parquet` with columns:
- `timestamp`
- `timestamp_iso_utc`
- `user_id`
- `ip`
- `ip_type`
- `status` (`ENRICHED` or `DROPPED`)
- `ipv4`
- `ipv6`
- `lat`
- `lon`
- `drop_reason`
- `drop_reason_comments`

---

## Quick Start
```powershell
python src/main.py
```

---

## Example Invocation
From repository root:

```powershell
# 1) Run processor
python src/main.py

# 2) Preview output parquet schema and sample rows
python -c "import pandas as pd; df=pd.read_parquet('output/result.parquet'); print(df.columns.tolist()); print(df.head(5).to_string(index=False))"

# 3) Convert parquet to CSV for spreadsheet viewing
python -c "import pandas as pd; pd.read_parquet('output/result.parquet').to_csv('output/result.csv', index=False)"
```

---

## Tests
```powershell
python -m pytest test/test_main.py -v
```
