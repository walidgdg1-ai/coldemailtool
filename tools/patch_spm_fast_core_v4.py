#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/spm_fast_core_v4.py')
s=p.read_text(encoding='utf-8')
old='    con.execute("""COPY (SELECT *,round(100*(.15*VolumeC+.12*BuyerC+.16*RepeatC+.12*.5+.10*CompetitionC+.08*ValueEvidenceC+.07*Recent12mShare+.05*LeanC+.15*StrategicC),2) SPM_Fast_Evidence_Score'
new='    con.execute(f"""COPY (SELECT *,round(100*(.15*VolumeC+.12*BuyerC+.16*RepeatC+.12*.5+.10*CompetitionC+.08*ValueEvidenceC+.07*Recent12mShare+.05*LeanC+.15*StrategicC),2) SPM_Fast_Evidence_Score'
assert old in s, 'fast score opening not found'
s=s.replace(old,new,1)
old2="Observed_Years FROM score ORDER BY SPM_Fast_Evidence_Score DESC) TO {q((out/'fast_matrix.csv').as_posix())} (HEADER)\")"
new2="Observed_Years FROM score ORDER BY SPM_Fast_Evidence_Score DESC) TO {q((out/'fast_matrix.csv').as_posix())} (HEADER)\"\"\")"
assert old2 in s, 'fast score closing not found'
s=s.replace(old2,new2,1)
p.write_text(s,encoding='utf-8')
print('SPM_FAST_SYNTAX_PATCH_PASS')
