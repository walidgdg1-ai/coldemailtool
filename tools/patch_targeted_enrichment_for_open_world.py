#!/usr/bin/env python3
from pathlib import Path

src=Path('tools/build_spm_targeted_award_enrichment_v1.py')
dst=Path('tools/build_spm_targeted_award_enrichment_open_world_v1.py')
s=src.read_text(encoding='utf-8')
old='"status": "PASS" if counts["spm_matched_tenders"] >= 60000 and counts["spm_niches"] >= 40 else "FAIL",'
new='"status": "PASS" if counts["spm_matched_tenders"] >= 500 and counts["spm_niches"] >= 10 else "FAIL",'
if old not in s:
    raise SystemExit('OPEN_WORLD_QA_PATCH_TARGET_NOT_FOUND')
s=s.replace(old,new,1)
s=s.replace('SPM Targeted Award Enrichment v1','SPM Open-World Concept Award Enrichment v1')
s=s.replace('SPM-matched tenders from full Core v4 discovery','Open-world concept-matched residual tenders from Core v4')
s=s.replace('successful SPM Tender Discovery v1 matches','open-world concept matches')
s=s.replace('SPM_LIVE_SCORING_PRIORS_TARGETED_AWARD_V1','SPM_LIVE_SCORING_PRIORS_OPEN_WORLD_CONCEPT_V1')
dst.write_text(s,encoding='utf-8')
print('OPEN_WORLD_TARGETED_ENRICHMENT_PATCH_PASS')
