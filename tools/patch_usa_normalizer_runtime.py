#!/usr/bin/env python3
from pathlib import Path

p=Path('tools/tender_normalize_usa_awards.py')
s=p.read_text(encoding='utf-8')

# Give every narrow candidate row a deterministic locator inside its source-member parquet.
old_ing="""                    COALESCE(TRY_CAST(last_modified_date AS TIMESTAMP),TRY_CAST(action_date AS TIMESTAMP),TIMESTAMP '1900-01-01') AS _rank_ts,
                    '{esc(zip_path.name)}' AS _source_zip,
                    '{esc(info.filename)}' AS _source_member
"""
new_ing="""                    COALESCE(TRY_CAST(last_modified_date AS TIMESTAMP),TRY_CAST(action_date AS TIMESTAMP),TIMESTAMP '1900-01-01') AS _rank_ts,
                    ROW_NUMBER() OVER () AS _source_row,
                    '{esc(zip_path.name)}' AS _source_zip,
                    '{esc(info.filename)}' AS _source_member
"""
if old_ing not in s:
    raise SystemExit('USA ingest locator target not found; refusing unsafe patch')
s=s.replace(old_ing,new_ing,1)

# The original finalize sorted all ~18.8M rows with all ~60 columns attached. On a hosted
# runner DuckDB exhausted the 10.8 GiB temp spill area. Rank only a narrow locator index,
# then join winning locators back to the wide parquets and materialize one compact latest file.
old_final="""    con=duckdb.connect(str(work/'usa_awards.duckdb'))
    glob=esc(str(work/'candidates'/'*.parquet'))
    con.execute(f\"\"\"
      CREATE OR REPLACE TABLE latest AS
      SELECT * EXCLUDE(rn) FROM (
        SELECT *, ROW_NUMBER() OVER(
          PARTITION BY COALESCE(NULLIF(contract_award_unique_key,''), awarding_agency_code || '|' || award_id_piid)
          ORDER BY _rank_ts DESC,
                   TRY_CAST(NULLIF(modification_number,'') AS BIGINT) DESC NULLS LAST,
                   TRY_CAST(NULLIF(transaction_number,'') AS BIGINT) DESC NULLS LAST
        ) rn
        FROM read_parquet('{glob}', union_by_name=true)
      ) WHERE rn=1
    \"\"\")
    n=con.execute('SELECT COUNT(*) FROM latest').fetchone()[0]
"""
new_final="""    con=duckdb.connect()
    glob=esc(str(work/'candidates'/'*.parquet'))
    tempdir=work/'ducktemp'; tempdir.mkdir(parents=True,exist_ok=True)
    con.execute(\"SET preserve_insertion_order=false\")
    con.execute(\"SET threads=2\")
    con.execute(\"SET memory_limit='5GB'\")
    con.execute(f\"SET temp_directory='{esc(tempdir)}'\")
    con.execute(\"SET max_temp_directory_size='10GB'\")
    keyexpr=\"COALESCE(NULLIF(contract_award_unique_key,''), awarding_agency_code || '|' || award_id_piid)\"
    con.execute(f\"\"\"
      CREATE TEMP TABLE winner_locators AS
      SELECT _source_zip,_source_member,_source_row FROM (
        SELECT
          {keyexpr} AS _award_key,
          _source_zip,_source_member,_source_row,
          ROW_NUMBER() OVER(
            PARTITION BY {keyexpr}
            ORDER BY _rank_ts DESC,
                     TRY_CAST(NULLIF(modification_number,'') AS BIGINT) DESC NULLS LAST,
                     TRY_CAST(NULLIF(transaction_number,'') AS BIGINT) DESC NULLS LAST
          ) AS rn
        FROM read_parquet('{glob}', union_by_name=true)
      ) WHERE rn=1
    \"\"\")
    latest_path=work/'latest_awards.parquet'
    con.execute(f\"\"\"
      COPY (
        SELECT p.*
        FROM read_parquet('{glob}', union_by_name=true) p
        JOIN winner_locators w
          ON p._source_zip=w._source_zip
         AND p._source_member=w._source_member
         AND p._source_row=w._source_row
      ) TO '{esc(latest_path)}' (FORMAT PARQUET, COMPRESSION ZSTD)
    \"\"\")
    con.execute('DROP TABLE winner_locators')
    con.execute(f\"CREATE OR REPLACE VIEW latest AS SELECT * FROM read_parquet('{esc(latest_path)}')\")
    # Candidate parquets are no longer needed after exact winner materialization; deleting them
    # restores runner disk before the large canonical CSV exports.
    for fp in files: fp.unlink(missing_ok=True)
    try:
        shutil.rmtree(tempdir)
    except Exception:
        pass
    n=con.execute('SELECT COUNT(*) FROM latest').fetchone()[0]
"""
if old_final not in s:
    raise SystemExit('USA finalize target not found; refusing unsafe patch')
s=s.replace(old_final,new_final,1)

p.write_text(s,encoding='utf-8')
print('USA runtime patch applied: source-row locators + narrow winner ranking + wide join-back materialization')
