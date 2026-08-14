# SPM Open-World Remaining Mine Audit v1

## State after executed waves

- Global Core v4 notice-first tenders: **2,250,547**
- Original SPM + Wave 1 unique exclusions before Wave 2: **78,385**
- Wave 2 net-new unique tenders: **7,477**
- Therefore unique tenders covered through executed Wave 2: **85,862**
- Residual after executed Wave 2: **2,164,685**
- Open-World Discovery v2 source signals: **597 global cohorts**, **118,031 recurring multi-word phrases**, **3,221 actionable phrase/cohort candidates**.

The residual count is not an estimate: Wave 2 was explicitly anti-joined against original SPM + Wave 1 and its QA passed. The remaining 2.16M notices are **not presumed commercially relevant**; most are expected to be construction, healthcare, engineering, regulated services, commodities, or other non-SPM work.

## Wave 3 status

Wave 3 code is committed and ready. It targets 26 multilingual/specialist concepts and anti-joins original SPM + Waves 1 and 2 before counting anything.

Current execution blocker is external to the classifier: GitHub Actions rejected the run before assigning a runner with the message that recent account payments failed or the spending limit needs to be increased. No Wave 3 analytical result is claimed until the full-core run executes.

## Remaining candidate pockets after manual long-tail audit

These are **phrase-level candidate signals only**. Phrase volumes can overlap and MUST NOT be summed as unique tenders. They are seeds for a future full-core anti-joined classifier.

| Candidate family | Representative residual evidence | Why keep | Priority |
|---|---|---|---|
| Multilingual CCTV / video protection | `supraveghere video` 64; `monitoringu wizyjnego` 59; `dispositif video protection` 30 | Physical-security resale/subcontract lane; current English/French CCTV rule may miss Eastern-European variants | HIGH |
| Clinical records / medical-data systems | `historia clinica` 40; `danych medycznych` 44; `patient journal` 30; `systemu szpitalnego` 28 | Software/integration lane adjacent to health IT; potentially high value, but eligibility can be heavy | MEDIUM |
| Cadastral / geodetic data modernization | `baz danych egib` 64; `bdot gesut` 46; geodetic-record cluster ~67 | Data/GIS digitisation lane; partnerable and data-heavy | MEDIUM-HIGH |
| Electronic case / records management | `och arendehanteringssystem` 45; `dokument och arendehanteringssystem` 26 | SaaS/document-management adjacency with Nordic-language coverage gap | MEDIUM-HIGH |
| Photography / documentary reporting | `reportages photographiques` 30 with 25 buyers | Very lean/subcontractable creative service; strong buyer breadth for its size | HIGH-LONG-TAIL |
| Technical documentation / manuals | recurring `technical documentation` signal (~27 in discovery tail) | AI-assisted editorial/document production; low execution burden when scope is textual | HIGH-LONG-TAIL |
| Digital signage / digital display | `carteleria digital` 26 | Hardware + creative + installation middleman model; multilingual signage gap | MEDIUM |
| Legal / professional information subscriptions | `informacji prawnej` 27; `banca dati` 34 | Subscription/resale-like lane, but often incumbent/vendor-locked | LOW-MEDIUM |
| Digital-transformation modernization | `transformare digitala` 95; `digitalizarea activitatii` 79 | Large-looking signal but highly concentrated in few buyers and often broad/complex scopes | LOW until decomposed |
| Multilingual application maintenance | `manutenzione software` 42; `mantenimiento aplicaciones informaticas` 32; `mentenanta suport` 48 and related support phrases | Already substantially addressed by planned Wave 3; retain only as a coverage QA lane | WAVE3-QA |

## Stop / continue rule

Do **not** keep adding ontology rules indefinitely. Continue mining only while an anti-joined wave produces either:

1. at least **500 net-new unique tenders**, or
2. at least **5 commercially coherent concepts** with >=20 tenders each and clear SPM fulfillment logic.

When a full wave falls below both gates, declare ontology discovery at diminishing returns and move engineering effort to live classification, historical-prior joins, DCE resolution on finalists, and bid/no-bid execution.

## Next execution sequence

1. Run committed Wave 3 once compute is available.
2. Measure net-new unique yield after anti-joining all prior waves.
3. If Wave 3 passes the continuation rule, build Wave 4 from the candidate pockets above plus any still-uncovered high-breadth multilingual phrases.
4. If Wave 3 fails the continuation rule, stop historical ontology expansion.
5. Merge original + Wave 1 + Wave 2 + successful later-wave priors into the live harvester.
6. Live notice -> niche/cluster -> historical priors -> notice gates -> shortlist -> DCE only when mandatory gates remain unresolved -> bid/no-bid.

## Evidence contract

- Phrase-level evidence is discovery evidence, not a tender count after dedupe.
- Historical scores are priors, not live eligibility decisions.
- Missing evidence remains UNKNOWN.
- No historical DCE retrieval is required for this mining stage.
- Reseller/certification/professional-registration/local-delivery requirements are evaluated only on a specific live opportunity.
