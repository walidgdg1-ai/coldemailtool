# Public Tender Intelligence — Canonical Warehouse Registry v1

Updated: 2026-08-13 03:43 Europe/Brussels

This file is the human-readable source of truth for bulk procurement warehouses produced by the tender pipeline. A country/source is `DONE` only when canonical outputs were normalized, integrity-validated, persisted to a private GitHub Release, and read back by the workflow.

| Lane | Status | Canonical tenders / reconstructed procurements | Award groups | Award↔supplier links | Release / storage | Canonical grain / notes |
|---|---:|---:|---:|---:|---|---|
| Ireland | DONE | 22,081 | available in release | available in release | `tender-normalized-ireland-v1` | Official Irish procurement open-data normalization |
| Canada federal | DONE | 19,965 | 11,777 | available in release | `tender-normalized-canada-v1` | CanadaBuys relational normalization |
| United Kingdom | DONE | 132,484 | 164,009 | 263,283 | `tender-normalized-uk-v1` | Find a Tender OCDS relational warehouse |
| Quebec / SEAO | DONE | 164,301 | 221,450 | 224,839 | `tender-normalized-quebec-v1` | Official SEAO OCDS; tender identity = `ocid`; official `numberOfTenderers` used when published; accidental SQLite WAL/SHM release sidecars removed |
| France / BOAMP | DONE | 282,684 | 102,159 | 100,348 | `tender-normalized-france-v1` | Official BOAMP monthly UTF-8 semicolon CSV with embedded JSON; conservative tender↔award linkage; source metadata corrected; missing bidder counts remain UNKNOWN |
| Germany eForms | IN_PROGRESS | full 36-month run active | pending | pending | target `tender-normalized-germany-v1` | July smoke passed end-to-end. Official monthly UBL/eForms XML; awards at `LotResult` grain; received-tender counts from official eForms statistics |
| TED RESULT census | IN_PROGRESS | 195,000 safe unique notices at latest fully committed checkpoint | RESULT/AWARD census | source winner arrays preserved | Drive initial 50k + continuation releases | Old fixed-size loop hit TED `timedOut=true` around record 198.5k. Adaptive record-range engine now downshifts 250→100→50→25→10→5→1 on the same cursor and flags any minimal-field fallback. Fresh run `31658607961` queued from safe 195k checkpoint |
| USA federal awards | IN_PROGRESS | FY2026 smoke: 3,657,873 award-first reconstructed procurements | FY2026 smoke: 3,657,873 | one supplier bridge per canonical award | target `tender-normalized-usa-awards-v1` | Full FY2023→FY2026 job active. USAspending `Contracts_Full`; latest transaction per `contract_award_unique_key`; explicitly AWARD_FIRST_RECONSTRUCTED, not claimed as original SAM.gov notices |

## Verified quality highlights

### Quebec / SEAO
- 335,789 official OCDS releases read in the 36-month window.
- 164,301 canonical tenders.
- 221,450 award groups.
- 224,839 award↔supplier links.
- 3,869 unique buyers; 56,316 unique suppliers.
- Award-value coverage: 98.49%.
- Official bidder-count coverage: 99.04%.
- Integrity gates: PASS.
- Runtime SQLite WAL/SHM sidecars were removed from the release without changing canonical rows.

### France / BOAMP
- 428,601 raw monthly records read.
- 282,684 canonical tender/procurement groups.
- 102,159 award groups.
- 100,348 award↔supplier links.
- 34,686 unique buyers; 49,997 unique suppliers.
- Raw parse errors: 0.
- Embedded JSON errors: 0.
- Integrity gates: PASS.
- Public bidder-count coverage at current canonical BOAMP grain: effectively absent; UNKNOWN is retained instead of inference.
- Source-format metadata repaired to the actual UTF-8 semicolon CSV + embedded JSON container without changing canonical rows.

### USA FY2026 smoke
- 4,098,932 transaction candidates reduced to 3,657,873 canonical federal contract awards.
- 2,637 unique buyers; 82,519 unique suppliers.
- Award-value coverage: 100%.
- Official `number_of_offers_received` coverage: 27.55%.
- Solicitation-identifier coverage: 13.29%.
- Integrity gates: PASS.

## Canonical guardrails

1. Missing evidence is `UNKNOWN`, never coerced to zero.
2. Multi-supplier group totals are stored once at award grain and are never duplicated into supplier allocations.
3. Tender, award, buyer, supplier and award↔supplier bridge identities are deterministic.
4. Derived rankings and market intelligence are explicitly labeled `DERIVED`.
5. USAspending award data is explicitly modeled as award-first reconstruction; it is not misrepresented as original SAM.gov opportunity-notice data.
6. Bulk archive continuation must be checkpointed and restartable; a failed run cannot silently advance a cursor.
7. TED physical duplicate shards caused by an earlier checkpoint race are lineage/storage duplicates only and must not be counted twice in the unique census.
8. TED HTTP 200 responses with `timedOut=true` and an empty `notices` array are transient query-complexity failures, not census completion; the adaptive engine must retry the identical cursor at smaller batch sizes before any fallback.

## Current execution queue

1. Finish full Germany 36-month eForms warehouse and publish `tender-normalized-germany-v1`.
2. Run adaptive TED RESULT census from the safe 195,000-record checkpoint, then self-chain in up-to-50k record blocks until exhaustive completion.
3. Finish USA FY2023→FY2026 award-grain canonicalization and publish `tender-normalized-usa-awards-v1`.
4. Reconcile the one duplicated TED physical shard from the earlier checkpoint race after the adaptive lineage crosses 200k safely.
