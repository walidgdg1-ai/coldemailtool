#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/build_spm_deep_intelligence_v1.py')
s=p.read_text(encoding='utf-8')
s=s.replace('SET threads=2','SET threads=1')
s=s.replace("SET memory_limit='6GB'","SET memory_limit='8GB'")
s=s.replace("SET max_temp_directory_size='20GB'","SET max_temp_directory_size='30GB'")
p.write_text(s,encoding='utf-8')
print('SPM_RUNNER_LIMITS_PATCH_PASS')
