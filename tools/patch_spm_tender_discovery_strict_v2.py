#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/build_spm_tender_discovery_v1.py')
s=p.read_text(encoding='utf-8')
old="parts=[c(title)]+([c(desc)] if desc else [])+([c(cat)] if cat else [])+([c(subcat)] if subcat else [])"
new="parts=[c(title)]  # STRICT V2: classification uses the raw tender title only"
if old not in s: raise SystemExit('STRICT_TEXT_TARGET_NOT_FOUND')
s=s.replace(old,new,1)
s=s.replace("'version':'SPM_TENDER_DISCOVERY_V1'","'version':'SPM_TENDER_DISCOVERY_V2_STRICT'",1)
s=s.replace("'scope':'Tender-only full-corpus discovery. Award values, bidder competition and supplier fragmentation are intentionally deferred to targeted evidence drills on shortlisted niches.'",
            "'scope':'Strict title-only full-corpus discovery. Derived Category/Subcategory and descriptions do not trigger niche classification. Award values, bidder competition and supplier fragmentation are deferred to targeted drills.'",1)
s=s.replace("TENDER_ONLY_DISCOVERY_70_EMPIRICAL_30_HEURISTIC","TITLE_ONLY_STRICT_DISCOVERY_70_EMPIRICAL_30_HEURISTIC")
s=s.replace("# SPM Tender Discovery v1","# SPM Tender Discovery v2 — Strict Title-Only")
s=s.replace("- This stage intentionally excludes award-price, bidder and supplier metrics; those are targeted next on shortlisted niches.",
            "- Classification trigger is the raw tender title only. Category/Subcategory/Description are retained as context but cannot create a niche match.\n- Award-price, bidder and supplier metrics are targeted next on the cleaned shortlist.")
p.write_text(s,encoding='utf-8')
print('SPM_DISCOVERY_STRICT_V2_PATCH_PASS')
