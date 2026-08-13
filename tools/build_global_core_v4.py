#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import duckdb

TED_NATIONAL_ALIASES = [
    'BE','BEL','BELGIUM',
    'FR','FRA','FRANCE',
    'DE','DEU','GERMANY','DEUTSCHLAND',
    'IE','IRL','IRELAND',
    'NL','NLD','NETHERLANDS','THE NETHERLANDS',
    'GB','GBR','UK','UNITED KINGDOM','GREAT BRITAIN',
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--core-v3', required=True)
    ap.add_argument('--tenderned', required=True)
    ap.add_argument('--belgium', required=True)
    ap.add_argument('--ted', required=True)
    ap.add_argument('--usa-quality', required=True)
    ap.add_argument('--australia-quality', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    core = Path(a.core_v3)
    nl = Path(a.tenderned)
    be = Path(a.belgium)
    ted = Path(a.ted)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / 'ducktmp'
    tmp.mkdir(exist_ok=True)

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=2")
    con.execute("SET memory_limit='6GB'")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='18GB'")

    aliases = ','.join("'" + x.replace("'", "''") + "'" for x in TED_NATIONAL_ALIASES)
    ted_keep = f"upper(trim(coalesce(Country,''))) NOT IN ({aliases})"

    # Materialize the exact TED fallback subset once, then derive its awards and supplier links.
    con.execute(f"""
      COPY (
        SELECT 'TED' AS Warehouse_Source, *,
               'NOTICE_FIRST_TED_FALLBACK' AS Evidence_Type
        FROM read_parquet('{(ted/'historical_tenders.parquet').as_posix()}')
        WHERE {ted_keep}
      ) TO '{(out/'ted_keep_tenders.parquet').as_posix()}'
      (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    con.execute(f"""
      COPY (
        SELECT 'TED' AS Warehouse_Source, a.*,
               'NOTICE_FIRST_TED_FALLBACK' AS Evidence_Type
        FROM read_parquet('{(ted/'awards.parquet').as_posix()}') a
        INNER JOIN read_parquet('{(out/'ted_keep_tenders.parquet').as_posix()}') t
          ON a.Historical_Tender_ID=t.Historical_Tender_ID
      ) TO '{(out/'ted_keep_awards.parquet').as_posix()}'
      (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    con.execute(f"""
      COPY (
        SELECT 'TED' AS Warehouse_Source, b.*,
               'NOTICE_FIRST_TED_FALLBACK' AS Evidence_Type
        FROM read_parquet('{(ted/'award_suppliers.parquet').as_posix()}') b
        INNER JOIN read_parquet('{(out/'ted_keep_awards.parquet').as_posix()}') a
          ON b.Award_ID=a.Award_ID
      ) TO '{(out/'ted_keep_bridge.parquet').as_posix()}'
      (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    # National notice-first warehouses win for their own markets. Belgium contributes no award facts
    # because its public BDA search summary does not expose verified winner/value facts.
    con.execute(f"""
      COPY (
        SELECT * FROM read_parquet('{(core/'historical_tenders.parquet').as_posix()}')
        UNION ALL BY NAME
        SELECT 'TenderNed' AS Warehouse_Source, *,
               coalesce(Evidence_Type,'NOTICE_FIRST_TENDERNED') AS Evidence_Type
        FROM read_csv_auto('{(nl/'historical_tenders.csv.gz').as_posix()}', header=true, all_varchar=true, sample_size=-1)
        UNION ALL BY NAME
        SELECT 'Belgium' AS Warehouse_Source, *,
               'NOTICE_FIRST_BELGIUM_BDA' AS Evidence_Type
        FROM read_csv_auto('{(be/'historical_tenders.csv.gz').as_posix()}', header=true, all_varchar=true, sample_size=-1)
        UNION ALL BY NAME
        SELECT * FROM read_parquet('{(out/'ted_keep_tenders.parquet').as_posix()}')
      ) TO '{(out/'historical_tenders.parquet').as_posix()}'
      (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.execute(f"""
      COPY (
        SELECT * FROM read_parquet('{(core/'awards.parquet').as_posix()}')
        UNION ALL BY NAME
        SELECT 'TenderNed' AS Warehouse_Source, *,
               coalesce(Evidence_Type,'NOTICE_FIRST_TENDERNED') AS Evidence_Type
        FROM read_csv_auto('{(nl/'awards.csv.gz').as_posix()}', header=true, all_varchar=true, sample_size=-1)
        UNION ALL BY NAME
        SELECT * FROM read_parquet('{(out/'ted_keep_awards.parquet').as_posix()}')
      ) TO '{(out/'awards.parquet').as_posix()}'
      (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.execute(f"""
      COPY (
        SELECT * FROM read_parquet('{(core/'award_suppliers.parquet').as_posix()}')
        UNION ALL BY NAME
        SELECT 'TenderNed' AS Warehouse_Source, *,
               'NOTICE_FIRST_TENDERNED' AS Evidence_Type
        FROM read_csv_auto('{(nl/'award_suppliers.csv.gz').as_posix()}', header=true, all_varchar=true, sample_size=-1)
        UNION ALL BY NAME
        SELECT * FROM read_parquet('{(out/'ted_keep_bridge.parquet').as_posix()}')
      ) TO '{(out/'award_suppliers.parquet').as_posix()}'
      (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    def norm(col: str) -> str:
        return f"lower(trim(regexp_replace(strip_accents(coalesce({col},'')), '[^A-Za-z0-9]+', ' ', 'g')))"

    # Rebuild dimensions from retained facts, not by concatenating stale source dimensions.
    con.execute(f"""
      COPY (
        WITH t AS (
          SELECT Warehouse_Source,Buyer_ID,
                 arg_max(Buyer_Name,length(coalesce(Buyer_Name,''))) Buyer_Name,
                 any_value(Country) Country,count(*) Observed_Tenders
          FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}')
          WHERE Buyer_ID IS NOT NULL GROUP BY 1,2
        ), aw AS (
          SELECT Warehouse_Source,Buyer_ID,count(distinct Award_ID) Observed_Awards,
                 median(try_cast(nullif(Award_Value,'') AS DOUBLE)) Median_Award_Value,
                 median(try_cast(nullif(Bidder_Count,'') AS DOUBLE)) Median_Bidder_Count
          FROM read_parquet('{(out/'awards.parquet').as_posix()}')
          WHERE Buyer_ID IS NOT NULL GROUP BY 1,2
        )
        SELECT t.Warehouse_Source,t.Buyer_ID,t.Buyer_Name,{norm('t.Buyer_Name')} AS Normalized_Name,
               t.Country,t.Observed_Tenders,coalesce(aw.Observed_Awards,0) Observed_Awards,
               aw.Median_Award_Value,aw.Median_Bidder_Count,'NOTICE_FIRST' Evidence_Type
        FROM t LEFT JOIN aw USING(Warehouse_Source,Buyer_ID)
      ) TO '{(out/'buyers.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.execute(f"""
      COPY (
        SELECT Warehouse_Source,Supplier_ID,
               arg_max(Supplier_Name,length(coalesce(Supplier_Name,''))) Supplier_Name,
               {norm('Supplier_Name')} AS Normalized_Name,
               any_value(Supplier_Country) Country,
               count(distinct Award_ID) Observed_Contracts_Won,
               median(try_cast(Award_Value_Allocated AS DOUBLE)) Median_Allocated_Value,
               'NOTICE_FIRST' Evidence_Type
        FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}')
        WHERE Supplier_ID IS NOT NULL
        GROUP BY 1,2
      ) TO '{(out/'suppliers.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.execute(f"""
      COPY (
        WITH t AS (
          SELECT Warehouse_Source,count(*) Tender_Count,count(distinct Buyer_ID) Buyer_Count
          FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}') GROUP BY 1
        ), aw AS (
          SELECT Warehouse_Source,count(*) Award_Count,
                 avg(CASE WHEN nullif(Bidder_Count,'') IS NOT NULL AND Bidder_Count<>'UNKNOWN' THEN 1 ELSE 0 END)*100 Bidder_Coverage_Pct
          FROM read_parquet('{(out/'awards.parquet').as_posix()}') GROUP BY 1
        )
        SELECT t.*,aw.Award_Count,aw.Bidder_Coverage_Pct,'NOTICE_FIRST' Evidence_Type
        FROM t LEFT JOIN aw USING(Warehouse_Source) ORDER BY Tender_Count DESC
      ) TO '{(out/'country_summary.csv').as_posix()}' (HEADER)
    """)

    # Cohorts are derived only where the source exposed those canonical fields. Missing fields remain UNKNOWN.
    con.execute(f"""
      COPY (
        SELECT Warehouse_Source,
               coalesce(nullif(Category,''),'UNKNOWN') Category,
               coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,
               coalesce(nullif(Currency,''),'UNKNOWN') Currency,
               count(*) Tender_Count,
               median(try_cast(nullif(Lean_Fit,'') AS DOUBLE)) Median_Lean_Fit,
               avg(CASE WHEN nullif(Official_Estimated_Value,'') IS NOT NULL AND Official_Estimated_Value<>'UNKNOWN' THEN 1 ELSE 0 END)*100 Estimate_Coverage_Pct,
               median(try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE)) Median_Estimated_Value,
               'NOTICE_FIRST' Evidence_Type,'DERIVED_FROM_VALIDATED_CANONICAL_ROWS' Derived_Status
        FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}')
        GROUP BY 1,2,3,4 ORDER BY Tender_Count DESC
      ) TO '{(out/'market_cohorts.csv').as_posix()}' (HEADER)
    """)

    for name in ['historical_tenders','awards','award_suppliers','buyers','suppliers']:
        con.execute(f"COPY (SELECT * FROM read_parquet('{(out/(name+'.parquet')).as_posix()}')) TO '{(out/(name+'.csv.gz')).as_posix()}' (HEADER, COMPRESSION GZIP)")

    counts = {name: con.execute(f"SELECT count(*) FROM read_parquet('{(out/(name+'.parquet')).as_posix()}')").fetchone()[0]
              for name in ['historical_tenders','awards','award_suppliers','buyers','suppliers']}
    source_counts = dict(con.execute(f"SELECT Warehouse_Source,count(*) FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}') GROUP BY 1 ORDER BY 2 DESC").fetchall())
    ted_all = con.execute(f"SELECT count(*) FROM read_parquet('{(ted/'historical_tenders.parquet').as_posix()}')").fetchone()[0]
    ted_kept = con.execute(f"SELECT count(*) FROM read_parquet('{(out/'ted_keep_tenders.parquet').as_posix()}')").fetchone()[0]
    core_v3_tenders = con.execute(f"SELECT count(*) FROM read_parquet('{(core/'historical_tenders.parquet').as_posix()}')").fetchone()[0]
    nl_tenders = con.execute(f"SELECT count(*) FROM read_csv_auto('{(nl/'historical_tenders.csv.gz').as_posix()}',header=true,all_varchar=true,sample_size=-1)").fetchone()[0]
    be_tenders = con.execute(f"SELECT count(*) FROM read_csv_auto('{(be/'historical_tenders.csv.gz').as_posix()}',header=true,all_varchar=true,sample_size=-1)").fetchone()[0]
    expected_tenders = core_v3_tenders + nl_tenders + be_tenders + ted_kept

    checks = {
        'tender_count_matches_source_plan': counts['historical_tenders'] == expected_tenders,
        'tender_ids_unique': con.execute(f"SELECT count(*)=count(distinct Historical_Tender_ID) FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}')").fetchone()[0],
        'award_ids_unique': con.execute(f"SELECT count(*)=count(distinct Award_ID) FROM read_parquet('{(out/'awards.parquet').as_posix()}')").fetchone()[0],
        'bridge_keys_unique': con.execute(f"SELECT count(*)=count(distinct Warehouse_Source||'|'||Award_ID||'|'||Supplier_ID) FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}')").fetchone()[0],
        'award_tender_orphans': con.execute(f"SELECT count(*) FROM read_parquet('{(out/'awards.parquet').as_posix()}') a LEFT JOIN read_parquet('{(out/'historical_tenders.parquet').as_posix()}') t USING(Warehouse_Source,Historical_Tender_ID) WHERE t.Historical_Tender_ID IS NULL").fetchone()[0],
        'award_buyer_orphans': con.execute(f"SELECT count(*) FROM read_parquet('{(out/'awards.parquet').as_posix()}') a LEFT JOIN read_parquet('{(out/'buyers.parquet').as_posix()}') b USING(Warehouse_Source,Buyer_ID) WHERE a.Buyer_ID IS NOT NULL AND b.Buyer_ID IS NULL").fetchone()[0],
        'bridge_award_orphans': con.execute(f"SELECT count(*) FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}') b LEFT JOIN read_parquet('{(out/'awards.parquet').as_posix()}') a USING(Warehouse_Source,Award_ID) WHERE a.Award_ID IS NULL").fetchone()[0],
        'bridge_supplier_orphans': con.execute(f"SELECT count(*) FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}') b LEFT JOIN read_parquet('{(out/'suppliers.parquet').as_posix()}') s USING(Warehouse_Source,Supplier_ID) WHERE s.Supplier_ID IS NULL").fetchone()[0],
        'belgium_awards_not_invented': con.execute(f"SELECT count(*)=0 FROM read_parquet('{(out/'awards.parquet').as_posix()}') WHERE Warehouse_Source='Belgium'").fetchone()[0],
        'ted_national_overlap_absent': con.execute(f"SELECT count(*)=0 FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}') WHERE Warehouse_Source='TED' AND upper(trim(coalesce(Country,''))) IN ({aliases})").fetchone()[0],
    }
    passed = bool(
        checks['tender_count_matches_source_plan'] and checks['tender_ids_unique'] and checks['award_ids_unique'] and checks['bridge_keys_unique']
        and checks['award_tender_orphans']==0 and checks['award_buyer_orphans']==0 and checks['bridge_award_orphans']==0 and checks['bridge_supplier_orphans']==0
        and checks['belgium_awards_not_invented'] and checks['ted_national_overlap_absent']
    )

    usa = json.loads(Path(a.usa_quality).read_text(encoding='utf-8'))
    aus = json.loads(Path(a.australia_quality).read_text(encoding='utf-8'))
    created = datetime.now(timezone.utc).isoformat()
    source_plan = {
        'core_v3_tenders': core_v3_tenders,
        'tenderned_tenders': nl_tenders,
        'belgium_tenders': be_tenders,
        'ted_all_tenders': ted_all,
        'ted_retained_tenders': ted_kept,
        'ted_excluded_for_national_overlap': ted_all - ted_kept,
        'national_precedence_countries': ['BE','FR','DE','IE','NL','UK/GB'],
    }
    priority = {
        'version':'GLOBAL_CORE_V4_OVERLAP_AWARE',
        'rule':'Included national notice-first warehouse wins for its market; TED is fallback coverage elsewhere. No fuzzy cross-source merge.',
        'ted_country_aliases_excluded':TED_NATIONAL_ALIASES,
        'source_plan':source_plan,
    }
    (out/'source_priority.json').write_text(json.dumps(priority,indent=2),encoding='utf-8')
    lanes = {
        'version':'GLOBAL_CORE_V4_OVERLAP_AWARE','created_at':created,
        'notice_first':{'materialized_here':True,'counts':counts,'sources':source_counts,'release_target':'tender-normalized-global-core-v4'},
        'usa_award_first':{'materialized_here':False,'source_release':'tender-normalized-usa-awards-v1','quality':usa,'reason':'Referenced separately; not counted as original opportunities.'},
        'australia_award_first':{'materialized_here':False,'source_release':'tender-normalized-austender-v1','quality':aus,'reason':'Referenced separately; not counted as original opportunities.'},
    }
    (out/'evidence_lanes.json').write_text(json.dumps(lanes,indent=2),encoding='utf-8')
    quality = {
        'version':'GLOBAL_CORE_V4_OVERLAP_AWARE','created_at':created,
        'counts_notice_first':counts,'counts_by_source':source_counts,'source_plan':source_plan,
        'integrity':checks,
        'currency_rule':'No cross-currency monetary aggregation.',
        'evidence_rule':'USA and Australia award-first lanes remain separately typed and are not counted as original opportunities.',
        'status':'PASS' if passed else 'FAIL',
    }
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')

    # Scratch TED subset files are not canonical release assets.
    for p in [out/'ted_keep_tenders.parquet',out/'ted_keep_awards.parquet',out/'ted_keep_bridge.parquet']:
        if p.exists(): p.unlink()
    if tmp.exists():
        try: tmp.rmdir()
        except OSError: pass

    manifest = {'version':'GLOBAL_CORE_V4_OVERLAP_AWARE','created_at':created,'files':{}}
    for p in out.iterdir():
        if p.is_file() and p.name != 'run_manifest.json':
            manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':sha256(p)}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(quality,indent=2),flush=True)
    if not passed:
        raise SystemExit(2)


if __name__=='__main__':
    main()
