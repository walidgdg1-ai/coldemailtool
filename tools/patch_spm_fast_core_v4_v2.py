#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/spm_fast_core_v4.py')
s=p.read_text(encoding='utf-8')
# Fix score query f-string / triple-quote if still on original source.
s=s.replace('    con.execute("""COPY (SELECT *,round(100*(.15*VolumeC+.12*BuyerC+.16*RepeatC+.12*.5+.10*CompetitionC+.08*ValueEvidenceC+.07*Recent12mShare+.05*LeanC+.15*StrategicC),2) SPM_Fast_Evidence_Score','    con.execute(f"""COPY (SELECT *,round(100*(.15*VolumeC+.12*BuyerC+.16*RepeatC+.12*.5+.10*CompetitionC+.08*ValueEvidenceC+.07*Recent12mShare+.05*LeanC+.15*StrategicC),2) SPM_Fast_Evidence_Score',1)
s=s.replace("Observed_Years FROM score ORDER BY SPM_Fast_Evidence_Score DESC) TO {q((out/'fast_matrix.csv').as_posix())} (HEADER)\")","Observed_Years FROM score ORDER BY SPM_Fast_Evidence_Score DESC) TO {q((out/'fast_matrix.csv').as_posix())} (HEADER)\"\"\")",1)
old='        return f"cast({ident(c)} as {cast})" if c else fallback'
new='        return f"try_cast({ident(c)} as {cast})" if c and cast.lower() in ("date","double","float","integer","bigint") else (f"cast({ident(c)} as {cast})" if c else fallback)'
assert old in s,'ex() line not found'
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('SPM_FAST_V2_PATCH_PASS')
