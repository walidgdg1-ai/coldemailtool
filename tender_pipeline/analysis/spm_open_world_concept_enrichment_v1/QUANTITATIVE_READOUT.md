# SPM Open-World Concept Award Enrichment v1

This stage **does not retrieve historical DCEs**. It reuses the successful full-corpus tender classification, then semi-joins award and supplier facts only for the SPM-matched tender keyset.

## QA

- SPM matched tenders analyzed: **18,149**
- SPM niches: **23**
- Linked awards: **15,554**
- Linked award-supplier rows: **15,336**
- Historical DCE dependency: **none**
- Raw cross-currency monetary aggregation: **forbidden / not used**

## Top enriched opportunities

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|SaaS business applications|1,704|81.5|1.0|62.5%|
|2|Software licensing & subscriptions|2,089|77.4|1.0|85.0%|
|3|Cybersecurity / SOC / managed security|2,594|74.9|1.0|66.7%|
|4|Microsoft licensing & cloud resale|1,512|70.5|1.0|72.7%|
|5|Network / WAN / wireless infrastructure|1,316|68.4|1.0|71.3%|
|6|Cloud infrastructure / VMware|633|65.4|1.0|71.7%|
|7|Audio-visual systems & conferencing|909|64.9|2.0|70.9%|
|8|ERP / SAP implementation & support|870|63.2|4.0|67.3%|
|9|Data platform / warehouse / BI|404|62.0|2.0|65.6%|
|10|Open-source / Red Hat / Linux services|536|61.1|1.0|62.8%|
|11|Video surveillance / CCTV|1,165|59.7|4.0|63.6%|
|12|CRM / Dynamics / Business Central|361|59.3|1.0|67.2%|
|13|AI / machine learning solutions|325|58.8|1.0|61.5%|
|14|Database / SQL / Oracle services|146|55.9|1.0|71.1%|
|15|Advertising / media placement|288|55.2|4.0|57.0%|
|16|Digital twin solutions|69|55.2|1.0|50.6%|
|17|Technical studies / feasibility studies|494|53.5|3.0|50.9%|
|18|IT hardware / laptops / endpoint supply|1,213|52.6|2.0|54.0%|
|19|Managed IT / ICT services|625|52.5|4.0|50.0%|
|20|Adobe / Creative Cloud licensing|313|51.7|1.0|78.3%|

## Top easiest-money proxy

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|Software licensing & subscriptions|2,089|91.2|1.0|85.0%|
|2|SaaS business applications|1,704|83.6|1.0|62.5%|
|3|Microsoft licensing & cloud resale|1,512|82.5|1.0|72.7%|
|4|Cybersecurity / SOC / managed security|2,594|82.3|1.0|66.7%|
|5|Network / WAN / wireless infrastructure|1,316|77.8|1.0|71.3%|
|6|IT hardware / laptops / endpoint supply|1,213|73.9|2.0|54.0%|
|7|Cloud infrastructure / VMware|633|71.5|1.0|71.7%|
|8|Open-source / Red Hat / Linux services|536|70.6|1.0|62.8%|
|9|Audio-visual systems & conferencing|909|69.8|2.0|70.9%|
|10|AI / machine learning solutions|325|67.8|1.0|61.5%|

## Top expected-profit proxy

|#|Niche|Tenders|Score|Median bidders|Award evidence|
|---:|---|---:|---:|---:|---:|
|1|SaaS business applications|1,704|85.4|1.0|62.5%|
|2|Cybersecurity / SOC / managed security|2,594|75.8|1.0|66.7%|
|3|Cloud infrastructure / VMware|633|74.2|1.0|71.7%|
|4|Software licensing & subscriptions|2,089|73.5|1.0|85.0%|
|5|Network / WAN / wireless infrastructure|1,316|73.4|1.0|71.3%|
|6|Microsoft licensing & cloud resale|1,512|72.9|1.0|72.7%|
|7|ERP / SAP implementation & support|870|70.8|4.0|67.3%|
|8|CRM / Dynamics / Business Central|361|69.5|1.0|67.2%|
|9|Audio-visual systems & conferencing|909|69.1|2.0|70.9%|
|10|AI / machine learning solutions|325|68.6|1.0|61.5%|

## Interpretation

`Expected_Profit_Proxy` is a prioritization score, not a profit forecast. Award values are compared only within their own currency via percentile ranks before being collapsed into a dimensionless score. Missing bidder/value/supplier evidence is retained as missing and receives a neutral prior only inside derived scoring components.

For live tenders, use `live_scoring_priors.json` as historical priors. Retrieve/read a DCE only after a live opportunity survives notice-level scoring and when mandatory eligibility, deliverables, or commercial gates remain unresolved.
