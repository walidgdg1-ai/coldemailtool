# SPM Open-World Concept Award Enrichment v1

This stage **does not retrieve historical DCEs**. It reuses the successful full-corpus tender classification, then semi-joins award and supplier facts only for the SPM-matched tender keyset.

## QA

- SPM matched tenders analyzed: **7,512**
- SPM niches: **31**
- Linked awards: **5,624**
- Linked award-supplier rows: **5,503**
- Historical DCE dependency: **none**
- Raw cross-currency monetary aggregation: **forbidden / not used**

## Top enriched opportunities

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|Geotechnical investigations & studies|1,180|76.1|1.0|76.6%|
|2|Asset management software|241|72.3|1.0|73.5%|
|3|Call center / contact center services & platforms|526|72.2|3.0|61.7%|
|4|Procurement / e-sourcing platforms|1,031|70.3|2.0|59.7%|
|5|HR / workforce / time management software|163|70.2|1.0|56.7%|
|6|Backup / disaster recovery / storage|418|69.2|2.0|66.1%|
|7|Laboratory / hospital information systems|36|69.1|1.0|62.7%|
|8|LMS / e-learning platforms|321|67.8|2.0|59.4%|
|9|Market research / surveys / data collection|267|65.0|2.0|58.5%|
|10|Telephony / VoIP / unified communications|242|64.4|1.0|59.7%|
|11|E-government / electronic administration platforms|321|63.7|1.0|83.2%|
|12|Identity / SSO / access management|241|62.0|3.0|60.4%|
|13|Fleet management software & services|147|61.0|3.0|58.8%|
|14|Mobile application development|110|60.9|1.0|73.1%|
|15|Document management / ECM / GED|155|60.8|2.0|75.2%|
|16|Online payments / payment platforms|99|60.2|2.0|70.1%|
|17|Data migration services|43|60.0|1.0|67.0%|
|18|Communications campaigns & public relations|240|59.4|3.0|69.0%|
|19|Structured cabling / network installation|184|59.4|2.0|71.1%|
|20|Press review / clipping services|51|59.0|1.0|80.4%|

## Top easiest-money proxy

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|Call center / contact center services & platforms|526|78.8|3.0|61.7%|
|2|Procurement / e-sourcing platforms|1,031|78.7|2.0|59.7%|
|3|LMS / e-learning platforms|321|77.9|2.0|59.4%|
|4|Asset management software|241|77.5|1.0|73.5%|
|5|Geotechnical investigations & studies|1,180|77.2|1.0|76.6%|
|6|Backup / disaster recovery / storage|418|77.0|2.0|66.1%|
|7|Market research / surveys / data collection|267|76.6|2.0|58.5%|
|8|Communications campaigns & public relations|240|75.6|3.0|69.0%|
|9|Telephony / VoIP / unified communications|242|74.7|1.0|59.7%|
|10|HR / workforce / time management software|163|71.8|1.0|56.7%|

## Top expected-profit proxy

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|Call center / contact center services & platforms|526|78.0|3.0|61.7%|
|2|HR / workforce / time management software|163|76.6|1.0|56.7%|
|3|Asset management software|241|75.1|1.0|73.5%|
|4|Laboratory / hospital information systems|36|74.6|1.0|62.7%|
|5|Online payments / payment platforms|99|71.7|2.0|70.1%|
|6|Identity / SSO / access management|241|71.6|3.0|60.4%|
|7|Fleet management software & services|147|70.6|3.0|58.8%|
|8|Communications campaigns & public relations|240|70.1|3.0|69.0%|
|9|Procurement / e-sourcing platforms|1,031|69.9|2.0|59.7%|
|10|Press review / clipping services|51|69.1|1.0|80.4%|

## Interpretation

`Expected_Profit_Proxy` is a prioritization score, not a profit forecast. Award values are compared only within their own currency via percentile ranks before being collapsed into a dimensionless score. Missing bidder/value/supplier evidence is retained as missing and receives a neutral prior only inside derived scoring components.

For live tenders, use `live_scoring_priors.json` as historical priors. Retrieve/read a DCE only after a live opportunity survives notice-level scoring and when mandatory eligibility, deliverables, or commercial gates remain unresolved.
