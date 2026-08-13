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
| Germany eForms | FULL RUN ACTIVE | July smoke: 23,991 tenders | July smoke: 9,320 | July smoke: 9,035 | target `tender-normalized-germany-v1` | July smoke PASS on 27,041 XML: publication date 100%, award value 62.63%, bidder-count 82.65%, all integrity checks true. Hardened 36-month 857k-XML run `31662908379` active |
| TED official XML bulk | **DONE** | raw official notice XML archive | — | — | `tender-raw-ted-official-bulk-v1` | **45/45 official packages persisted and read back: 36 monthly Aug 2023–Jul 2026 + 9 Aug 2026 daily editions, totaling 2,566,835 XML.** Every package has SHA-256 + manifest + checkpoint. This is the authoritative TED raw lane; Search API lineage is retired |
| TED dual-stack canonical | VALIDATING | smoke source: 356,691 XML across legacy + eForms | smoke parser extracted 223,059 award rows before canonical cursor fix | 218,664 raw supplier links before canonical cursor fix | target canonical release after smoke | Conservative dual parser handles legacy `TED_EXPORT` R2.x and eForms UBL. First smoke exposed a SQLite nested-cursor bug after successful XML extraction; runtime patch now materializes award rows before supplier lookups. Corrected smoke `31662970819` active |
| USA federal awards | PUBLISHING RERUN ACTIVE | **15,842,317 proven canonical contracts** | **15,842,317 proven canonical awards** | one supplier bridge per canonical award where supplier available | target `tender-normalized-usa-awards-v1` | First full compute already PASS: 18,810,214 candidate transactions → 15,842,317 canonical awards/contracts; 3,166 buyers; 144,014 suppliers; award value 100%; bidder-count 24.45%; integrity 100%. It failed only on release targeting. Durable releases are pre-created on branch; rerun `31662555891` is in finalize/publication path |

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

## TED authoritative raw archive

- Official package count: **45 / 45 COMPLETE**.
- Monthly packages: Aug 2023 through Jul 2026.
- Daily packages: OJ S 147–155 for Aug 2026 continuation.
- Total XML notices/documents physically enumerated inside official archives: **2,566,835**.
- Final checkpoint and summary were downloaded back from the release and asserted COMPLETE.
- Storage: `tender-raw-ted-official-bulk-v1`.
- Archive format: monthly tar.gz packages can contain nested daily tar.gz packages; XML is counted recursively.

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

## USA full-compute proof

- Candidate transactions: **18,810,214**.
- Canonical federal contract awards: **15,842,317**.
- Award-first reconstructed procurements: **15,842,317**.
- Unique buyers: **3,166**.
- Unique suppliers: **144,014**.
- Award value coverage: **100%**.
- Official `number_of_offers_received` coverage: **24.45%**.
- Solicitation identifier coverage: **12.11%**.
- Integrity gates: PASS.
- The only failure in the first full run was GitHub release creation against `$GITHUB_SHA`; a publication probe proved branch-target releases work, so durable USA/Germany releases were pre-created and the current reruns use them.

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
10. TED legacy procurement linkage requires buyer identity + reference number when available; otherwise notice grain is retained rather than fuzzy-merging unrelated procedures. eForms linkage uses `ContractFolderID` when published.

## Current execution queue

1. Finish corrected TED dual-stack smoke; if PASS, launch staged full normalization across all 2,566,835 official XML records.
2. Finish/publish hardened full Germany 36-month warehouse.
3. Finish/publish USA 15.84M award-grain warehouse using already-proven finalizer and durable releases.
4. Build the next Global Core revision incorporating independently validated Germany/USA, while TED canonicalization proceeds as its own staged lane.
