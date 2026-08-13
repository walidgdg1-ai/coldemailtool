# Public Tender Intelligence — Canonical Warehouse Registry v1

Updated: 2026-08-13

This file is the human-readable source of truth for bulk procurement warehouses produced by the tender pipeline. A country/source is `DONE` only when canonical outputs were normalized, integrity-validated, persisted to a private GitHub Release, and read back by the workflow.

| Lane | Status | Canonical tenders / reconstructed procurements | Award groups | Award↔supplier links | Release / storage | Canonical grain / notes |
|---|---:|---:|---:|---:|---|---|
| Ireland | DONE | 22,081 | available in release | available in release | `tender-normalized-ireland-v1` | Official Irish procurement open-data normalization |
| Canada federal | DONE | 19,965 | 11,777 | available in release | `tender-normalized-canada-v1` | CanadaBuys relational normalization |
| United Kingdom | DONE | 132,484 | 164,009 | 263,283 | `tender-normalized-uk-v1` | Find a Tender OCDS relational warehouse |
| Quebec / SEAO | DONE | 164,301 | 221,450 | 224,839 | `tender-normalized-quebec-v1` | Official SEAO OCDS; tender identity = `ocid`; official `numberOfTenderers` used when published; accidental SQLite WAL/SHM release sidecars removed |
| France / BOAMP | DONE | 282,684 | 102,159 | 100,348 | `tender-normalized-france-v1` | Official BOAMP monthly UTF-8 semicolon CSV with embedded JSON; conservative tender↔award linkage; source metadata corrected; missing bidder counts remain UNKNOWN |
| Validated Global Core | BUILDING | expected 621,515 | union of validated awards | union of validated bridges | target `tender-normalized-global-core-v1` | Five validated lanes only: Ireland + Canada federal + UK + Quebec + France. CSV.gz + Parquet relational union; country/currency preserved in analytics. Run `31660607912` |
| Germany eForms | IN_PROGRESS | full 36-month run active | pending | pending | target `tender-normalized-germany-v1` | Previous run parsed all 857,016 XML then hit a pandas readback bug after normalization. Readback hardened with `low_memory=False`; replacement run `31660331188` active |
| TED RESULT census | IN_PROGRESS | legacy safe checkpoint: 195,000 unique notices | RESULT/AWARD census | source winner arrays preserved | authoritative target `tender-ted-monthly-census-v1` | Deep global ITERATION cursor becomes toxic around ~198.5k even at limit=1. Architecture replaced by 36 independent monthly date partitions with atomic raw+normalized+manifest persistence and final `sum(months) == global total` reconciliation. Run `31660463172` active |
| USA federal awards | IN_PROGRESS | FY2026 smoke: 3,657,873; full input ≈18.81M candidate transactions | pending full canonical count | one supplier bridge per canonical award | target `tender-normalized-usa-awards-v1` | First full ingest succeeded but global wide sort exhausted DuckDB spill. Replacement finalizer ranks narrow source-row locators then joins winners back to wide rows. Run `31660382131` active. Explicitly `AWARD_FIRST_RECONSTRUCTED`, never represented as original SAM.gov notices |

## Current validated core

The five completed country lanes contain **621,515 canonical tender/procurement rows** before Germany, USA or the exhaustive TED census are added.

### Quebec / SEAO
- 335,789 official OCDS releases read in the 36-month window.
- 164,301 canonical tenders.
- 221,450 award groups.
- 224,839 award↔supplier links.
- 3,869 unique buyers; 56,316 unique suppliers.
- Award-value coverage: 98.49%.
- Official bidder-count coverage: 99.04%.
- Integrity gates: PASS.

### France / BOAMP
- 428,601 raw monthly records read.
- 282,684 canonical tender/procurement groups.
- 102,159 award groups.
- 100,348 award↔supplier links.
- 34,686 unique buyers; 49,997 unique suppliers.
- Raw parse errors: 0; embedded JSON errors: 0.
- Integrity gates: PASS.
- Missing bidder counts remain `UNKNOWN` rather than inferred.

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
7. TED physical duplicate shards from the retired deep-cursor lineage are storage/lineage duplicates only and must never be counted twice.
8. The authoritative TED census is accepted only when every date partition is complete and the sum of partition counts exactly equals an independently read global `totalNoticeCount` for the same fixed window/query.
9. Cross-country monetary analytics must preserve source currency unless an explicit sourced FX normalization layer is added later.

## Current execution queue

1. Complete and publish the five-country `tender-normalized-global-core-v1` master.
2. Finish Germany 36-month eForms normalization and integrity validation.
3. Finish USA FY2023→FY2026 memory-bounded award-grain canonicalization.
4. Finish the 36-partition TED monthly exhaustive census and reconcile its exact sum to the global total.
5. After Germany/USA validation, build a later Global Core revision that incorporates them without weakening the validated-country gate.
