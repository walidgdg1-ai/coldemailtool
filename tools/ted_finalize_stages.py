#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, pathlib
from datetime import datetime, timezone
import duckdb

VERSION='TED_CANONICAL_GLOBAL_V1'

def sha256(p:pathlib.Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage-dir',required=True);ap.add_argument('--stage-summary',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    stage=pathlib.Path(a.stage_dir);out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    summary=json.loads(pathlib.Path(a.stage_summary).read_text(encoding='utf-8'))
    if summary.get('status')!='STAGE_COMPLETE':raise RuntimeError(f'stage not complete: {summary.get("status")}')
    if int(summary.get('completed_packages',0))!=45:raise RuntimeError('expected 45 completed stage packages')
    tglob=str(stage/'ted-stage-*.historical_tenders.csv.gz').replace("'","''")
    aglob=str(stage/'ted-stage-*.awards.csv.gz').replace("'","''")
    bglob=str(stage/'ted-stage-*.award_suppliers.csv.gz').replace("'","''")
    con=duckdb.connect();con.execute("SET preserve_insertion_order=false");con.execute("SET threads=2");con.execute("SET memory_limit='6GB'");temp=out/'ducktmp';temp.mkdir(exist_ok=True);con.execute(f"SET temp_directory='{str(temp).replace(chr(39),chr(39)*2)}'");con.execute("SET max_temp_directory_size='10GB'")
    # Read all stage facts as strings; canonical output types are deliberately stable across legacy/eForms.
    con.execute(f"CREATE VIEW t0 AS SELECT * FROM read_csv_auto('{tglob}',header=true,all_varchar=true,union_by_name=true,sample_size=-1)")
    con.execute(f"CREATE VIEW a0 AS SELECT * FROM read_csv_auto('{aglob}',header=true,all_varchar=true,union_by_name=true,sample_size=-1)")
    con.execute(f"CREATE VIEW b0 AS SELECT * FROM read_csv_auto('{bglob}',header=true,all_varchar=true,union_by_name=true,sample_size=-1)")
    tender_key_conflicts=con.execute("SELECT count(*) FROM (SELECT Historical_Tender_ID,count(distinct Procurement_Key) n FROM t0 GROUP BY 1 HAVING n>1)").fetchone()[0]
    award_tender_conflicts=con.execute("SELECT count(*) FROM (SELECT Award_ID,count(distinct Historical_Tender_ID) n FROM a0 GROUP BY 1 HAVING n>1)").fetchone()[0]
    if tender_key_conflicts or award_tender_conflicts:raise RuntimeError(f'cross-stage identity conflict tender={tender_key_conflicts} award={award_tender_conflicts}')
    # Select a coherent richest tender row per deterministic ID, then separately preserve earliest publication and any award linkage.
    con.execute("""CREATE TEMP TABLE tenders_final AS
      WITH scored AS (
        SELECT *,
          (CASE WHEN nullif(Buyer_Name,'') IS NOT NULL THEN 1 ELSE 0 END +
           CASE WHEN nullif(Title,'') IS NOT NULL THEN 2 ELSE 0 END +
           CASE WHEN nullif(Description,'') IS NOT NULL THEN 2 ELSE 0 END +
           CASE WHEN nullif(Main_CPV,'') IS NOT NULL THEN 1 ELSE 0 END +
           CASE WHEN try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE) IS NOT NULL THEN 2 ELSE 0 END +
           CASE WHEN nullif(Deadline,'') IS NOT NULL THEN 1 ELSE 0 END +
           CASE WHEN nullif(Reference_Number,'') IS NOT NULL THEN 1 ELSE 0 END) richness,
          row_number() OVER(PARTITION BY Historical_Tender_ID ORDER BY
            (CASE WHEN nullif(Buyer_Name,'') IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN nullif(Title,'') IS NOT NULL THEN 2 ELSE 0 END +
             CASE WHEN nullif(Description,'') IS NOT NULL THEN 2 ELSE 0 END +
             CASE WHEN nullif(Main_CPV,'') IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE) IS NOT NULL THEN 2 ELSE 0 END +
             CASE WHEN nullif(Deadline,'') IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN nullif(Reference_Number,'') IS NOT NULL THEN 1 ELSE 0 END) DESC,
            try_cast(Publication_Date AS DATE) ASC NULLS LAST) rn
        FROM t0
      ), agg AS (
        SELECT Historical_Tender_ID,min(try_cast(Publication_Date AS DATE)) Publication_Date_Min,
               max(CASE WHEN Award_Link_Status='LINKED' THEN 1 ELSE 0 END) Has_Award
        FROM t0 GROUP BY 1
      )
      SELECT s.* EXCLUDE(richness,rn,Publication_Date,Award_Link_Status),
             cast(a.Publication_Date_Min AS VARCHAR) Publication_Date,
             CASE WHEN a.Has_Award=1 THEN 'LINKED' ELSE 'UNLINKED' END Award_Link_Status
      FROM scored s JOIN agg a USING(Historical_Tender_ID) WHERE rn=1""")
    # Award IDs are notice/result deterministic. Keep the richest duplicate without summing values.
    con.execute("""CREATE TEMP TABLE awards_final AS
      SELECT * EXCLUDE(rn) FROM (
        SELECT *,row_number() OVER(PARTITION BY Award_ID ORDER BY
          (CASE WHEN try_cast(nullif(Award_Value,'') AS DOUBLE) IS NOT NULL THEN 3 ELSE 0 END +
           CASE WHEN nullif(Bidder_Count,'') IS NOT NULL AND Bidder_Count<>'UNKNOWN' THEN 2 ELSE 0 END +
           CASE WHEN nullif(Supplier_Name,'') IS NOT NULL THEN 1 ELSE 0 END +
           CASE WHEN nullif(Award_Date,'') IS NOT NULL THEN 1 ELSE 0 END) DESC) rn
        FROM a0
      ) WHERE rn=1""")
    # Bridge duplicates are collapsed at identity grain; allocations are never added together.
    con.execute("""CREATE TEMP TABLE bridges_final AS
      SELECT Award_ID,Supplier_ID,
             arg_max(Supplier_Name,length(coalesce(Supplier_Name,''))) Supplier_Name,
             any_value(Relationship) Relationship,
             max(try_cast(nullif(Award_Value_Allocated,'') AS DOUBLE)) Award_Value_Allocated,
             arg_max(Supplier_Country,length(coalesce(Supplier_Country,''))) Supplier_Country,
             any_value(SME_Status) SME_Status
      FROM b0 WHERE nullif(Supplier_ID,'') IS NOT NULL GROUP BY 1,2""")
    con.execute("""CREATE TEMP TABLE buyers_final AS
      WITH t AS (
        SELECT Buyer_ID,arg_max(Buyer_Name,length(coalesce(Buyer_Name,''))) Buyer_Name,
               arg_max(Country,length(coalesce(Country,''))) Country,count(*) Observed_Tenders
        FROM tenders_final WHERE nullif(Buyer_ID,'') IS NOT NULL GROUP BY 1
      ), aw AS (
        SELECT Buyer_ID,count(*) Observed_Awards,
               median(try_cast(nullif(Award_Value,'') AS DOUBLE)) Median_Award_Value,
               median(try_cast(nullif(Bidder_Count,'') AS DOUBLE)) Median_Bidder_Count
        FROM awards_final WHERE nullif(Buyer_ID,'') IS NOT NULL GROUP BY 1
      )
      SELECT t.*,coalesce(aw.Observed_Awards,0) Observed_Awards,aw.Median_Award_Value,aw.Median_Bidder_Count FROM t LEFT JOIN aw USING(Buyer_ID)""")
    con.execute("""CREATE TEMP TABLE suppliers_final AS
      SELECT Supplier_ID,arg_max(Supplier_Name,length(coalesce(Supplier_Name,''))) Supplier_Name,
             arg_max(Supplier_Country,length(coalesce(Supplier_Country,''))) Country,
             count(distinct Award_ID) Observed_Contracts_Won,
             median(Award_Value_Allocated) Median_Allocated_Award_Value
      FROM bridges_final GROUP BY 1""")
    tables=['historical_tenders','awards','award_suppliers','buyers','suppliers'];sources={'historical_tenders':'tenders_final','awards':'awards_final','award_suppliers':'bridges_final','buyers':'buyers_final','suppliers':'suppliers_final'}
    for name in tables:
        src=sources[name];con.execute(f"COPY (SELECT * FROM {src}) TO '{str(out/(name+'.parquet')).replace(chr(39),chr(39)*2)}' (FORMAT PARQUET,COMPRESSION ZSTD)");con.execute(f"COPY (SELECT * FROM {src}) TO '{str(out/(name+'.csv.gz')).replace(chr(39),chr(39)*2)}' (HEADER,COMPRESSION GZIP)")
    counts={name:con.execute(f'SELECT count(*) FROM {sources[name]}').fetchone()[0] for name in tables}
    integrity={
      'tender_ids_unique':con.execute('SELECT count(*)=count(distinct Historical_Tender_ID) FROM tenders_final').fetchone()[0],
      'award_ids_unique':con.execute('SELECT count(*)=count(distinct Award_ID) FROM awards_final').fetchone()[0],
      'bridge_keys_unique':con.execute("SELECT count(*)=count(distinct Award_ID||'|'||Supplier_ID) FROM bridges_final").fetchone()[0],
      'award_tender_fk':con.execute('SELECT count(*)=0 FROM awards_final a LEFT JOIN tenders_final t USING(Historical_Tender_ID) WHERE t.Historical_Tender_ID IS NULL').fetchone()[0],
      'bridge_award_fk':con.execute('SELECT count(*)=0 FROM bridges_final b LEFT JOIN awards_final a USING(Award_ID) WHERE a.Award_ID IS NULL').fetchone()[0],
      'multi_supplier_values_not_allocated':con.execute("""SELECT count(*)=0 FROM bridges_final b JOIN (SELECT Award_ID,count(*) n FROM bridges_final GROUP BY 1 HAVING n>1) m USING(Award_ID) WHERE b.Award_Value_Allocated IS NOT NULL""").fetchone()[0],
      'tender_key_conflicts_zero':tender_key_conflicts==0,'award_tender_conflicts_zero':award_tender_conflicts==0,
    }
    q={
      'version':VERSION,'created_at':datetime.now(timezone.utc).isoformat(),'stage_version':summary.get('version'),
      'stage_packages':summary.get('completed_packages'),'source_raw_xml':summary.get('raw_xml_sum'),'stage_tender_row_sum':summary.get('stage_tender_row_sum'),'stage_award_row_sum':summary.get('stage_award_row_sum'),'stage_bridge_row_sum':summary.get('stage_bridge_row_sum'),
      'canonical_counts':counts,
      'cross_package_tender_rows_collapsed':int(summary.get('stage_tender_row_sum',0))-counts['historical_tenders'],
      'cross_package_award_rows_collapsed':int(summary.get('stage_award_row_sum',0))-counts['awards'],
      'cross_package_bridge_rows_collapsed':int(summary.get('stage_bridge_row_sum',0))-counts['award_suppliers'],
      'award_value_coverage_pct':round(100*con.execute("SELECT avg(CASE WHEN try_cast(nullif(Award_Value,'') AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END) FROM awards_final").fetchone()[0],2) if counts['awards'] else 0,
      'bidder_count_coverage_pct':round(100*con.execute("SELECT avg(CASE WHEN try_cast(nullif(Bidder_Count,'') AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END) FROM awards_final").fetchone()[0],2) if counts['awards'] else 0,
      'integrity':integrity,
      'status':'PASS' if int(summary.get('raw_xml_sum',0))==2566835 and all(integrity.values()) and counts['historical_tenders']>0 and counts['awards']>0 else 'FAIL'
    }
    (out/'data_quality.json').write_text(json.dumps(q,indent=2),encoding='utf-8')
    manifest={'version':VERSION,'created_at':q['created_at'],'files':{}}
    for p in out.iterdir():
        if p.is_file() and p.name!='run_manifest.json':manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':sha256(p)}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(q,indent=2),flush=True)
    if q['status']!='PASS':raise SystemExit(2)

if __name__=='__main__':main()
