# SPM Targeted Award Enrichment v1

This stage **does not retrieve historical DCEs**. It reuses the successful full-corpus tender classification, then semi-joins award and supplier facts only for the SPM-matched tender keyset.

## QA

- SPM matched tenders analyzed: **60,734**
- SPM niches: **48**
- Linked awards: **55,218**
- Linked award-supplier rows: **50,183**
- Historical DCE dependency: **none**
- Raw cross-currency monetary aggregation: **forbidden / not used**

## Top enriched opportunities

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|Workflow automation / RPA|587|76.9|1.0|83.4%|
|2|Website design / redesign|8,599|76.8|3.0|54.7%|
|3|Copywriting / editorial content|1,140|76.2|1.0|60.8%|
|4|Web hosting / domain / SSL|1,030|75.7|1.0|58.6%|
|5|Simple API / software integration|330|75.1|2.0|65.8%|
|6|Transcription / minutes|16,816|74.7|1.0|48.7%|
|7|Document digitization / scanning|8,091|74.6|2.0|56.1%|
|8|Online forms / lightweight portals|1,882|73.5|2.0|66.1%|
|9|Low-code / no-code implementation|179|71.8|2.0|70.6%|
|10|Signage / wayfinding / vinyl|3,197|69.5|1.0|58.0%|
|11|Translation / localization|457|68.5|1.0|48.5%|
|12|Brochure / flyer / poster printing|8,454|68.1|3.0|56.1%|
|13|Small IT equipment supply|4,607|67.7|2.0|67.8%|
|14|E-learning / training content|613|66.6|2.0|63.3%|
|15|Web accessibility remediation|112|66.4|1.0|59.5%|
|16|AI chatbot / assistant|139|66.3|2.0|55.4%|
|17|Data cleaning / deduplication|68|66.0|2.0|58.6%|
|18|Graphic design / layout|664|65.7|3.0|54.2%|
|19|Website maintenance / content updates|220|65.0|1.0|50.3%|
|20|Video production|123|64.6|1.0|57.7%|

## Top easiest-money proxy

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|Copywriting / editorial content|1,140|87.6|1.0|60.8%|
|2|Web hosting / domain / SSL|1,030|86.2|1.0|58.6%|
|3|Video editing / post-production|37|85.1|1.0|69.5%|
|4|Transcription / minutes|16,816|84.9|1.0|48.7%|
|5|Workflow automation / RPA|587|83.4|1.0|83.4%|
|6|Annual report / publication layout|52|82.8|1.0|56.6%|
|7|Data cleaning / deduplication|68|82.3|2.0|58.6%|
|8|Cataloguing / indexing / metadata|27|82.0|1.0|50.6%|
|9|Translation / localization|457|82.0|1.0|48.5%|
|10|Proofreading / editing|132|80.9|4.0|76.1%|

## Top expected-profit proxy

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|Animation / motion design|21|81.3|2.0|66.2%|
|2|Promotional merchandise / branded items|174|81.3|2.0|50.2%|
|3|Cataloguing / indexing / metadata|27|81.2|1.0|50.6%|
|4|Web hosting / domain / SSL|1,030|80.2|1.0|58.6%|
|5|Simple API / software integration|330|79.3|2.0|65.8%|
|6|Low-code / no-code implementation|179|79.1|2.0|70.6%|
|7|Copywriting / editorial content|1,140|78.7|1.0|60.8%|
|8|Workflow automation / RPA|587|77.8|1.0|83.4%|
|9|Data cleaning / deduplication|68|77.5|2.0|58.6%|
|10|Direct mail / envelope / routing|88|77.5|1.5|48.4%|

## Interpretation

`Expected_Profit_Proxy` is a prioritization score, not a profit forecast. Award values are compared only within their own currency via percentile ranks before being collapsed into a dimensionless score. Missing bidder/value/supplier evidence is retained as missing and receives a neutral prior only inside derived scoring components.

For live tenders, use `live_scoring_priors.json` as historical priors. Retrieve/read a DCE only after a live opportunity survives notice-level scoring and when mandatory eligibility, deliverables, or commercial gates remain unresolved.
