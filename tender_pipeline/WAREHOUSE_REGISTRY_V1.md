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
| Germany eForms | DONE | **638,737** | **251,084** | **223,338** | `tender-normalized-germany-v1` | 36 official monthly exports / 857,016 XML. 425,093 buyers; 59,885 suppliers; publication dates 100%; bidder-count coverage 76.25%; all integrity gates PASS |
| USA federal awards | DONE | **15,842,317 award-first reconstructed procurements** | **15,842,317** | one supplier bridge per canonical award | `tender-normalized-usa-awards-v1` | USAspending `Contracts_Full`. 3,166 buyers; 144,015 suppliers; award value 100%; bidder-count coverage 24.45%; solicitation-ID coverage 11.17%. Explicitly award-first, not SAM opportunity notices |
| TED official XML bulk | DONE | raw official notice XML archive | — | — | `tender-raw-ted-official-bulk-v1` | 45/45 official packages persisted/read back: 36 monthly Aug 2023–Jul 2026 + 9 Aug 2026 daily editions, totaling **2,566,835 XML**. Search API lineage retired |
| TED dual-stack smoke | DONE | **104,652** | **218,964** | **210,713** | `tender-ted-dual-stack-smoke-v1` | Two representative official packages, 124,777 XML: 59,388 legacy + 65,389 eForms. 18,626 buyers; 34,522 suppliers; award-value coverage 79.49%; bidder coverage 63.89%; all integrity gates PASS |
| TED canonical 45-package stage | IN_PROGRESS | checkpointed package outputs | checkpointed package outputs | checkpointed package outputs | `tender-normalized-ted-stage-v1` | Full staging run `31665066999`. Smoke gate PASS. Each official package is downloaded, canonicalized, QA-checked and persisted atomically before continuing. Aug 2023 stage already persisted with checkpoint |
| Global Core v2 | DONE | 621,515 | 510,490 | 584,202 | `tender-normalized-global-core-v2` | Collision-repaired five-market relational core |
| Global Core v3 | **DONE** | **1,260,252 notice-first tenders** | **761,574** | **807,481** | `tender-normalized-global-core-v3` | Core v2 + Germany materialized as notice-first. 68,098 buyers; 257,131 suppliers; zero FK orphans; zero normalized identity collisions. USA award-first is federated separately via `evidence_lanes.json` |
| Market Intelligence v3 | **DONE** | source core 1,260,252 notice-first | source core 761,574 | source core 807,481 | `tender-global-market-intelligence-v3` | Evidence-aware layer: 2,273 notice opportunity cohorts; 42,657 notice repeat-buyer segments; USA kept separately with 1,113 award-first cohorts and 81,266 repeat-buyer segments. No FX mixing; weak bidder coverage neutralized; all scores DERIVED |

## Global Core v3 integrity

- Notice-first tenders: **1,260,252**; IDs unique.
- Notice-first awards: **761,574**; IDs unique.
- Award↔supplier links: **807,481**; composite keys unique.
- Buyers: **68,098**.
- Suppliers: **257,131**.
- Award→tender orphans: 0.
- Award→buyer orphans: 0.
- Bridge→supplier orphans: 0.
- Normalized buyer identity collisions: 0.
- Normalized supplier identity collisions: 0.
- USA award-first facts remain independently validated in `tender-normalized-usa-awards-v1` and are referenced, not copied into original-opportunity counts.

## Germany full warehouse

- Official monthly source assets: **36**.
- Raw XML: **857,016**.
- Unique source notices: **844,373**.
- Out-of-window package-boundary records: 963.
- Modification notices excluded from primary award analytics: 30,871.
- Canonical tenders: **638,737**.
- Award groups: **251,084**.
- Award↔supplier links: **223,338**.
- Unique buyers: **425,093**.
- Unique suppliers: **59,885**.
- Publication-date coverage: **100%**.
- Deadline coverage: 72.76%.
- Estimated-value coverage: 6.24%.
- Award-value coverage: 53.41%.
- Official bidder-count coverage: **76.25%**.
- Tender IDs, award IDs, bridge keys and multi-supplier value integrity: PASS.

## USA full warehouse

- Candidate transactions ingested from FY2023–FY2026 official `Contracts_Full` archives: **18,810,001**.
- Canonical federal contract awards: **15,842,317**.
- Award-first reconstructed procurements: **15,842,317**.
- Unique buyers: **3,166**.
- Unique suppliers: **144,015**.
- Award value coverage: **100%**.
- Official `number_of_offers_received` coverage: **24.45%**.
- Solicitation identifier coverage: **11.17%**.
- Tender IDs unique, award IDs unique, one supplier bridge per award: PASS.
- Rows are explicitly `AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING`; never represented as original SAM.gov opportunity notices.

## TED authoritative raw + smoke

- Official raw package count: **45 / 45 COMPLETE**.
- Raw monthly packages: Aug 2023 through Jul 2026.
- Raw daily continuation: OJ S 147–155 for Aug 2026.
- Raw XML physically enumerated: **2,566,835**.
- Dual-stack validation source: Aug 2023 + Sep 2024 official packages, **124,777 XML**.
- Smoke legacy XML: 59,388; eForms XML: 65,389.
- Smoke canonical tenders: **104,652**.
- Smoke canonical awards: **218,964**.
- Smoke supplier links: **210,713**.
- Smoke award-value coverage: 79.49%; bidder-count coverage: 63.89%.
- Smoke tender IDs, award IDs, bridge keys, award→tender FK and multi-supplier value integrity: PASS.
- Full 45-package staging is resumable through `tender-normalized-ted-stage-v1`.

## Market Intelligence v3 outputs

- Notice-first cohort facts: **10,824**.
- Notice-first opportunity ranking: **2,273**.
- Notice-first supplier-fragmentation cohorts: **7,192**.
- Notice-first repeat-buyer segments: **42,657**.
- USA award-first market cohorts: **1,113**.
- USA award-first repeat-buyer segments: **81,266**.
- Opportunity rankings exclude USA reconstructed rows.
- Cross-currency monetary aggregation is prohibited.
- Bidder competition term is neutralized where coverage <30%.
- Consortium supplier links are fractionalized for concentration analytics.

## Canonical guardrails

1. Missing evidence is `UNKNOWN`, never coerced to zero.
2. Multi-supplier group totals are stored once at award grain and are never duplicated into supplier allocations.
3. Tender, award, buyer, supplier and bridge identities must pass deterministic collision and FK gates before a Global Core release can be authoritative.
4. Derived rankings and market intelligence are explicitly labeled `DERIVED`.
5. USAspending award data is award-first reconstruction; it is never misrepresented as original SAM.gov opportunity-notice data.
6. Raw bulk archive continuation is checkpointed and restartable; a failed run cannot silently advance.
7. Retired TED Search-API shards are historical lineage only. The authoritative TED raw archive is direct official bulk packages.
8. Cross-country monetary analytics preserve source currency unless an explicit sourced FX layer is added.
9. Official package boundary spillover is filtered at canonical normalization time rather than deleting raw source records.
10. TED legacy linkage requires buyer identity + reference number when available; otherwise package-namespaced notice grain is retained instead of fuzzy-merging unrelated procedures. eForms linkage uses `ContractFolderID` when published.
11. Award-first reconstructed datasets remain analytically tagged and separable from original opportunity-notice datasets in every cross-market core.
12. National datasets may overlap TED; future cross-source cores must retain source lineage and only collapse records on evidence-bearing exact identifiers, never fuzzy title/value matching.

## Current execution queue

1. Finish the checkpointed TED 45-package canonical staging and assert the stage census covers all **2,566,835 XML**.
2. Trigger the TED cross-package finalizer, add release-size guards, publish/read back `tender-normalized-ted-v1`, and enforce global identity/FK gates.
3. Add national official lanes that complement TED, prioritizing Belgium, Netherlands and Australia; verify official bulk/API interfaces before implementation.
4. After TED canonical PASS, build the next Core revision with TED kept source-aware so national/TED overlap is not double-counted blindly.
5. Rebuild Market Intelligence on that overlap-aware core while preserving notice-first vs award-first evidence semantics.
