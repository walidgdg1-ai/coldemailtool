# Public Tender Intelligence — Canonical Warehouse Registry v1

Updated: 2026-08-13

This file is the human-readable source of truth for bulk procurement warehouses produced by the tender pipeline. A country/source is `DONE` only when canonical outputs were normalized, integrity-validated, persisted to a private GitHub Release, and read back by the workflow.

| Lane | Status | Canonical tenders / reconstructed procurements | Award groups | Award↔supplier links | Release / storage | Canonical grain / notes |
|---|---:|---:|---:|---:|---|---|
| Ireland | DONE | 22,081 | available in release | available in release | `tender-normalized-ireland-v1` | Official Irish procurement open-data normalization |
| Canada federal | DONE | 19,965 | 11,777 | available in release | `tender-normalized-canada-v1` | CanadaBuys relational normalization |
| United Kingdom | DONE | 132,484 | 164,009 | 263,283 | `tender-normalized-uk-v1` | Find a Tender OCDS relational warehouse |
| Quebec / SEAO | DONE | 164,301 | 221,450 | 224,839 | `tender-normalized-quebec-v1` | Official SEAO OCDS; tender identity = `ocid`; official `numberOfTenderers` used when published |
| France / BOAMP | DONE | 282,684 | 102,159 | persisted | `tender-normalized-france-v1` | Official BOAMP monthly semicolon CSV with embedded JSON; conservative tender↔award linkage; missing bidder counts remain UNKNOWN |
| Germany eForms | IN_PROGRESS | — | — | — | target `tender-normalized-germany-v1` | Official monthly UBL/eForms XML; awards at `LotResult` grain; received-tender counts from official eForms statistics |
| TED RESULT census | IN_PROGRESS | 195,000 safe unique notices at latest fully committed checkpoint | RESULT/AWARD census | source winner arrays preserved | Drive initial 50k + continuation releases | Official Search API v3 `ITERATION`; crash-safe 5k shards; rate-limit hardened autonomous loop targeting exhaustive census |
| USA federal awards | IN_PROGRESS | FY2026 smoke: 3,657,873 award-first reconstructed procurements | FY2026 smoke: 3,657,873 | one supplier bridge per canonical award | target `tender-normalized-usa-awards-v1` | USAspending `Contracts_Full`; latest transaction per `contract_award_unique_key`; explicitly AWARD_FIRST_RECONSTRUCTED, not claimed as original SAM.gov notices |

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

### France / BOAMP
- 428,601 raw monthly records read.
- 282,684 canonical tender/procurement groups.
- 102,159 award groups.
- 34,686 unique buyers; 49,997 unique suppliers.
- Raw parse errors: 0.
- Embedded JSON errors: 0.
- Integrity gates: PASS.
- Public bidder-count coverage at current canonical BOAMP grain: effectively absent; UNKNOWN is retained instead of inference.

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

## Current execution queue

1. Finish full Germany 36-month eForms warehouse and publish `tender-normalized-germany-v1`.
2. Continue rate-limit-hardened TED RESULT census from the safe 195,000-record checkpoint until exhaustive completion.
3. Finish USA FY2023→FY2026 award-grain canonicalization and publish `tender-normalized-usa-awards-v1`.
4. Perform archive hygiene: remove accidental Quebec SQLite sidecars, reconcile the one duplicated TED physical shard, and repair France source-format wording in QA metadata without changing canonical rows.
