# Public Tender Intelligence — Canonical Warehouse Registry v1

Updated: 2026-08-13

This file is the human-readable source of truth for bulk procurement warehouses produced by the tender pipeline. A country/source is `DONE` only when canonical outputs were normalized, integrity-validated, persisted to a private GitHub Release, and read back by the workflow.

| Lane | Status | Canonical tenders / reconstructed procurements | Award groups | Award↔supplier links | Release / storage | Canonical grain / notes |
|---|---:|---:|---:|---:|---|---|
| Ireland | DONE | 22,081 | available in release | available in release | `tender-normalized-ireland-v1` | Official Irish procurement open-data normalization |
| Canada federal | DONE | 19,965 | 11,777 | available in release | `tender-normalized-canada-v1` | CanadaBuys relational normalization |
| United Kingdom | DONE | 132,484 | 164,009 | 263,283 | `tender-normalized-uk-v1` | Find a Tender OCDS relational warehouse |
| Quebec / SEAO | DONE | 164,301 | 221,450 | 224,839 | `tender-normalized-quebec-v1` | Official SEAO OCDS; official `numberOfTenderers` used when published |
| France / BOAMP | DONE | 282,684 | 102,159 | 100,348 | `tender-normalized-france-v1` | Official BOAMP semicolon CSV + embedded JSON; missing bidder counts remain UNKNOWN |
| Global Core v2 | DONE | **621,515** | **510,490** | **584,202** | `tender-normalized-global-core-v2` | Collision-repaired five-market relational core. 47,179 canonical buyers, 195,723 canonical suppliers; zero normalized buyer/supplier identity collisions; zero fact/FK orphans. Legacy IDs retained as lineage |
| Market Intelligence v2 | DONE | source core 621,515 | source core 510,490 | source core 584,202 | `tender-global-market-intelligence-v2` | Derived opportunity/cohort/repeat-buyer/supplier-fragmentation layer built from Global Core v2. No FX mixing; weak bidder coverage is neutralized; all scores labeled DERIVED |
| Germany eForms | VALIDATING | July smoke: 23,991 tenders | July smoke: 9,320 | July smoke: 9,035 | target `tender-normalized-germany-v1` | July source: 27,041 XML; publication date coverage 100%; award value coverage 62.63%; bidder-count coverage 82.65%; all integrity checks true. Full 857k-XML run is queued behind final smoke validation |
| TED official XML bulk | IN_PROGRESS | raw official notice XML archive | — | — | `tender-raw-ted-official-bulk-v1` | Authoritative raw lane now uses direct TED monthly/daily bulk packages instead of Search API. Monthly tar.gz contains nested daily tar.gz containing XML. Aug–Dec 2023 already persisted with SHA-256/manifests/checkpoints; worker continues month-by-month through Jul 2026 + Aug 2026 dailies |
| USA federal awards | IN_PROGRESS | FY2026 smoke: 3,657,873; full input ≈18.81M candidate transactions | pending full canonical count | one supplier bridge per canonical award | target `tender-normalized-usa-awards-v1` | USAspending `Contracts_Full`, explicitly `AWARD_FIRST_RECONSTRUCTED`. All FY2023→FY2026 inputs ingested; memory-bounded finalizer currently ranking narrow locators and joining canonical winners back to wide rows |

## Global Core v2 integrity

- Tenders: **621,515**; IDs unique.
- Awards: **510,490**; IDs unique.
- Award↔supplier links: **584,202**; composite keys unique.
- Buyers: **47,179**; source+canonical keys unique.
- Suppliers: **195,723**; source+canonical keys unique.
- Award→tender orphans: 0.
- Award→buyer FK orphans: 0.
- Bridge→supplier FK orphans: 0.
- Normalized buyer identity collision keys: 0.
- Normalized supplier identity collision keys: 0.
- 634 legacy bridge rows were collapsed or unidentifiable during evidence-bearing supplier re-keying; allocated award values were never summed during collapse.

## Germany July 2026 validation snapshot

- Raw XML: 27,041.
- Unique source notices: 25,629.
- Out-of-window: 1,269 (monthly package boundary effect, not parse loss).
- Contract modification notices excluded from primary awards: 710.
- Canonical tenders: 23,991.
- Award groups: 9,320.
- Award↔supplier links: 9,035.
- Unique buyers: 15,131.
- Unique suppliers: 5,054.
- Publication-date coverage: 100%.
- Deadline coverage: 57.38%.
- Estimated-value coverage: 8.25%.
- Award-value coverage: 62.63%.
- Official bidder-count coverage: 82.65%.
- Tender IDs, award IDs, supplier bridge and multi-supplier value integrity: PASS.

## Canonical guardrails

1. Missing evidence is `UNKNOWN`, never coerced to zero.
2. Multi-supplier group totals are stored once at award grain and are never duplicated into supplier allocations.
3. Tender, award, buyer, supplier and bridge identities must pass deterministic collision and FK gates before a Global Core release can be authoritative.
4. Derived rankings and market intelligence are explicitly labeled `DERIVED`.
5. USAspending award data is award-first reconstruction; it is never misrepresented as original SAM.gov opportunity-notice data.
6. Raw bulk archive continuation is checkpointed and restartable; a failed run cannot silently advance.
7. Retired TED Search-API shards are historical lineage only. The authoritative TED raw archive is now direct official bulk packages.
8. Cross-country monetary analytics preserve source currency unless an explicit sourced FX layer is added.
9. Official package boundary spillover is filtered at canonical normalization time rather than deleting raw source records.

## Current execution queue

1. Pass the corrected Germany July smoke, then execute/publish the hardened full 36-month Germany warehouse.
2. Finish USA FY2023→FY2026 memory-bounded award-grain canonicalization.
3. Finish all official TED bulk packages, then normalize the raw XML across legacy TED and eForms schema generations.
4. After Germany/USA are independently validated, build the next Global Core revision incorporating them without weakening v2 integrity gates.
