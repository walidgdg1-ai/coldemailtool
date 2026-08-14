#!/usr/bin/env python3
from pathlib import Path

p=Path('tools/build_spm_open_world_concepts_v1.py')
s=p.read_text(encoding='utf-8')
old="""    raw=out/'open_world_concept_matches_raw.parquet'\n    con.execute(f\"\"\"COPY (\n      SELECT u.* EXCLUDE(Title_Blob),r.Niche,r.Macro_Category,r.AI_Leverage,r.Subcontractability,r.Remote_Feasibility,\n             r.Low_Entry_Burden,r.Low_Execution_Pain,r.Margin_Potential\n      FROM read_parquet({q(residual.as_posix())}) u\n      JOIN rules r ON regexp_matches(u.Title_Blob,r.Pattern)\n    ) TO {q(raw.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)\"\"\")\n"""
new="""    # One combined regex scan over the 2.19M residual rows first, then evaluate\n    # individual concept rules only against survivors. Same exhaustive semantics,\n    # far fewer dynamic regexp evaluations.\n    combined='('+'|'.join('(?:'+r['pattern']+')' for r in CONCEPTS)+')'\n    candidates=out/'concept_prefilter_candidates.parquet'\n    con.execute(f\"\"\"COPY (\n      SELECT * FROM read_parquet({q(residual.as_posix())})\n      WHERE regexp_matches(Title_Blob,{q(combined)})\n    ) TO {q(candidates.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)\"\"\")\n    raw=out/'open_world_concept_matches_raw.parquet'\n    con.execute(f\"\"\"COPY (\n      SELECT u.* EXCLUDE(Title_Blob),r.Niche,r.Macro_Category,r.AI_Leverage,r.Subcontractability,r.Remote_Feasibility,\n             r.Low_Entry_Burden,r.Low_Execution_Pain,r.Margin_Potential\n      FROM read_parquet({q(candidates.as_posix())}) u\n      JOIN rules r ON regexp_matches(u.Title_Blob,r.Pattern)\n    ) TO {q(raw.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)\"\"\")\n"""
if old not in s:
    raise SystemExit('OPEN_WORLD_PREFILTER_PATCH_TARGET_NOT_FOUND')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('OPEN_WORLD_CONCEPT_PREFILTER_PATCH_PASS')
