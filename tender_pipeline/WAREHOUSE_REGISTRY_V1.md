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
| Germany eForms | **DONE** | **638,737** | **251,084** | **223,338** | `tender-normalized-germany-v1` | 36 official monthly exports / 857,016 XML. 425,093 buyers; 59,885 suppliers; publication dates 100%; bidder-count coverage 76.25%; all integrity gates PASS |
| USA federal awards | **DONE** | **15,842,317 award-first reconstructed procurements** | **15,842,317** | one supplier bridge per canonical award | `tender-normalized-usa-awards-v1` | USAspending Contracts_Full. 3,166 buyers; 144,015 suppliers; award value 100%; official bidder-count coverage 24.45%; solicitation-ID coverage 11.17%; all integrity gates PASS. Explicitly award-first, not SAM opportunity notices |
| TED official XML bulk | **DONE** | raw official notice XML archive | — | — | `tender-raw-ted-official-bulk-v1` | **45/45 official packages persisted and read back: 36 monthly Aug 2023–Jul 2026 + 9 Aug 2026 daily editions, totaling 2,566,835 XML.** Every package has SHA-256 + manifest + checkpoint. This is the authoritative TED raw lane; Search API lineage is retired |
| TED dual-stack canonical | VALIDATING | smoke source: 356,691 XML across legacy + eForms | parser previously extracted 223,059 raw award rows | 218,664 raw supplier links | target `tender-normalized-ted-v1` | Legacy R2.x + eForms UBL dual parser. Cursor and canonicalization N+1 defects were removed; the remaining long-running smoke was traced to a quadratic FK QA set rebuild and fixed. Final smoke run `31664796258` is the validation gate; staged 45-package full pipeline is wired to start only after smoke SUCCESS |

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
- Release: `tender-normalized-germany-v1`.

## USA full warehouse

- Candidate transactions ingested from FY2023–FY2026 official Contracts_Full archives: **18,810,001** in the successful rerun (date-window filtered during each FY ingestion).
- Canonical federal contract awards: **15,842,317**.
- Award-first reconstructed procurements: **15,842,317**.
- Unique buyers: **3,166**.
- Unique suppliers: **144,015**.
- Award value coverage: **100%**.
- Official `number_of_offers_received` coverage: **24.45%**.
- Solicitation identifier coverage: **11.17%**.
- Tender IDs unique, award IDs unique, one supplier bridge per award: PASS.
- Historical_Tenders rows are explicitly `AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING`; they are not original SAM.gov opportunity notices.
- Release: `tender-normalized-usa-awards-v1`.

## TED authoritative raw archive

- Official package count: **45 / 45 COMPLETE**.
- Monthly packages: Aug 2023 through Jul 2026.
- Daily packages: OJ S 147–155 for Aug 2026 continuation.
- Total XML notices/documents physically enumerated inside official archives: **2,566,835**.
- Final checkpoint and summary were downloaded back from the release and asserted COMPLETE.
- Storage: `tender-raw-ted-official-bulk-v1`.
- Archive format: monthly tar.gz packages can contain nested daily tar.gz packages; XML is counted recursively.

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
10. TED legacy procurement linkage requires buyer identity + reference number when available; otherwise package-namespaced notice grain is retained rather than fuzzy-merging unrelated procedures. eForms linkage uses `ContractFolderID` when published.
11. Award-first reconstructed datasets (USAspending) remain analytically tagged and separable from original opportunity-notice datasets in every cross-market core.

## Current execution queue

1. Pass final linear-time TED dual-stack smoke; automatic 45-package staged canonicalization begins only on SUCCESS.
2. Finalize the staged TED packages into `tender-normalized-ted-v1` and enforce global cross-package identity/FK gates.
3. Build Global Core v3 from Global Core v2 + Germany, with USA included as a separately tagged award-first analytical lane rather than mixed blindly with notice-first procurement counts.
4. Build Market Intelligence v3 using validated Germany/USA evidence, preserving source currencies and notice-vs-award-first distinctions.
5. After TED canonical is independently validated, build the next Core revision incorporating TED without weakening v3 identity or evidence-type guards.
