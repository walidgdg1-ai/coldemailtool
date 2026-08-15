# SPM Award-Led Priorities — Manual Readout v1

Date: 2026-08-15

## Evidence scope

This readout uses already-persisted targeted award enrichments from:

- original SPM ontology enrichment;
- Open-World Wave 1;
- Open-World Wave 2.

It does not claim the not-yet-executed buyer-level `SPM_AWARD_INTELLIGENCE_V1` output. That full-core job is committed but GitHub Actions currently rejects jobs before runner assignment due the account billing/spending-limit blocker.

Historical scores are priors only. Live eligibility still requires authoritative notice/DCE gates.

## Highest-priority SPM lanes after award evidence

### Tier A — strongest combination of lean execution + award evidence

1. **Copywriting / editorial content**
   - 1,140 tenders, 483 linked awards.
   - Bidder-count coverage ~71%; median observed bidders 1.
   - Observed single-bid share ~80%.
   - Very high AI leverage / remote feasibility.

2. **Workflow automation / RPA**
   - 587 tenders, 642 linked awards.
   - Bidder coverage ~87%; median observed bidders 1.
   - Observed single-bid share ~69%.
   - High AI leverage, but live technical/reference gates vary.

3. **Transcription / minutes**
   - 16,816 tenders, 7,862 linked awards.
   - Bidder coverage ~67%; median observed bidders 1.
   - Very large addressable volume and very high remote/AI feasibility.
   - Live language/security/transcription-quality gates still matter.

4. **Web hosting / domain / SSL**
   - 1,030 tenders, 664 linked awards.
   - Bidder coverage ~47%; median observed bidders 1.
   - Very fragmented supplier base.
   - Check SLA/security/data-hosting constraints live.

5. **Press review / clipping services**
   - 51 tenders, 47 linked awards.
   - Bidder coverage ~81%; median observed bidders 1.
   - Observed single-bid share ~61%.
   - High AI leverage and remote feasibility; media-content licensing/source-access is the main live gate.

6. **Mobile application development**
   - 110 tenders, 73 linked awards.
   - Bidder coverage ~78%; median observed bidders 1.
   - Observed single-bid share ~79%.
   - High margin potential; watch references, app security, maintenance SLA and incumbent integrations.

7. **Low-code / no-code implementation**
   - 179 tenders, 112 linked awards.
   - Bidder coverage ~68%; median observed bidders 2.
   - Strong AI leverage and remote feasibility.

8. **Simple API / software integration**
   - 330 tenders, 326 linked awards.
   - Bidder coverage ~52%; median observed bidders 2.
   - High expected-profit proxy; integrations/security/references determine live feasibility.

9. **Market research / surveys / data collection**
   - 267 tenders, 295 linked awards.
   - Bidder coverage ~81%; median observed bidders 2.
   - Broad buyer base (204 buyers) and high AI/subcontract leverage.
   - Separate remote desk research from fieldwork/sample-recruitment-heavy contracts.

10. **LMS / e-learning platforms**
    - 321 tenders, 206 linked awards.
    - Bidder coverage ~49%; median observed bidders 2.
    - Strong resale/implementation/white-label potential.
    - Product ownership, migration, integrations and support SLAs are key live gates.

### Tier A/B — strong evidence but delivery/partner burden is more variable

- HR / workforce / time management software: 163 tenders, 88 awards, median bidders 1, ~78% observed single-bid share.
- Asset management software: 241 tenders, 177 awards, median bidders 1, very fragmented suppliers.
- Video editing / post-production: 37 tenders, 27 awards, median bidders 1 on ~89% bidder coverage; highly lean but low volume.
- Translation / localization: 457 tenders, 158 awards, median bidders 1; language/native-speaker/certification gates vary.
- Data cleaning / deduplication: 68 tenders, 42 awards, median bidders 2; strong AI leverage.
- Cataloguing / indexing / metadata: small sample, but 14 linked awards and median bidders 1; verify sample-size risk.
- DMS / ECM / GED: 155 tenders, 122 awards, median bidders 2; implementation/integration burden can be substantial.
- Communications campaigns / PR: 240 tenders, 187 awards, median bidders 3; operationally feasible but portfolio/reference burden common.

### Middleman / subcontract lanes worth systematic testing

- Printing / brochures / flyers / posters: 8,454 tenders, 11,910 linked award rows/award facts in targeted enrichment; median observed bidders 3.
- Signage / wayfinding / vinyl: 3,197 tenders, 1,487 linked awards; median observed bidders 1, but field logistics/install requirements vary.
- Promotional merchandise / branded items: 174 tenders, 97 awards; median observed bidders 2.
- Geotechnical investigations/studies: 1,180 tenders, 981 linked awards, median bidders 1; attractive only as a partner/subcontract brokerage lane, not SPM self-delivery.
- Structured cabling / network installation: potential local subcontract brokerage; installer qualifications and site obligations must be checked live.

## Lanes that look statistically attractive but should NOT be auto-green

- Health IT / RIS-PACS / HIS
- IAM / SSO
- e-signature / trust services
- payment platforms / PSP
- Microsoft/Adobe/VMware/Red Hat/SAP licensing
- cybersecurity/SOC
- AV/hardware

Low bidder counts can reflect vendor lock-in, certification, regulated status, incumbent systems or framework access. Carry `PARTNER_OR_RESELLER_REQUIREMENT_POSSIBLE` until DCE evidence resolves the gate.

## Current live-ish representatives in the stored corpus worth verification

These are latest stored historical/live-window records, not asserted still-open without live verification:

- Export Development Canada — `Market Research Services`, publication 2026-07-31, stored deadline 2026-09-16.
- Norwegian Directorate of Immigration — `Learning Platform`, publication 2026-07-13, stored deadline 2026-08-31.
- Université Versailles Saint Quentin en Yvelines — `Achat d'une Plateforme LMS pour l'UFR des Sciences de la Santé`, publication 2026-06-18, stored deadline 2026-10-07.
- University of Exeter — `eProcurement Cloud Marketplace`, publication 2026-07-30; deadline unresolved in stored representative record.
- United Lincolnshire Teaching Hospitals NHS Trust — `IT Data Cabling Framework`, publication 2026-07-16, stored deadline 2026-09-07; partner/subcontract lane.

## Remaining historical mine

Executed precise coverage through Original SPM + Wave 1 + Wave 2 = **85,862 unique tenders**.

Residual after Wave 2 = **2,164,685 notice-first tenders**.

The residual is not presumed SPM-relevant. Continue ontology expansion only while a fully anti-joined wave yields either:

- >=500 net-new unique tenders; or
- >=5 commercially coherent concepts with >=20 tenders each and clear fulfillment logic.

Wave 3 is code-ready but has not executed because GitHub Actions rejected the jobs before runner assignment for billing/spending-limit reasons.

## Next analytical step once compute is available

Run `SPM_AWARD_INTELLIGENCE_V1` over all 4,286,784 Core v4 notice-first awards to resolve buyer-level behavior:

- repeat purchasing cadence;
- observed competition;
- supplier concentration/lock-in;
- supplier switching/churn;
- modest-value repeat purchasing;
- buyer/category watchlists.

Then run an explicitly separate USA award-first version over 15,842,317 federal awards. Never merge that lane into notice-first counts.
