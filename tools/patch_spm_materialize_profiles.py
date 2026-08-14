#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/build_spm_deep_intelligence_v1.py')
s=p.read_text(encoding='utf-8')
for name in ['niche_tender_profile','niche_award_profile','niche_supplier_profile','niche_value_fit']:
    old=f'CREATE TEMP VIEW {name} AS'
    new=f'CREATE TEMP TABLE {name} AS'
    if old not in s:
        print('already materialized or missing',name)
    s=s.replace(old,new)
p.write_text(s,encoding='utf-8')
print('SPM_MATERIALIZE_PROFILES_PATCH_PASS')
