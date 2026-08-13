#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json
import duckdb


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--core-v2',required=True)
    ap.add_argument('--germany',required=True)
    ap.add_argument('--usa-quality',required=True)
    ap.add_argument('--out',required=True)
    a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    tmp=out/'ducktmp';tmp.mkdir(exist_ok=True)
    con=duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=2")
    con.execute("SET memory_limit='6GB'")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='10GB'")
    v2=Path(a.core_v2);de=Path(a.germany)

    def norm(col):
        return f"lower(trim(regexp_replace(strip_accents(coalesce({col},'')), '[^A-Za-z0-9]+', ' ', 'g')))"
    bn=norm('Buyer_Name')
    sn=norm('Supplier_Name')
    de_buyer=f"CASE WHEN nullif({bn},'') IS NULL THEN NULL ELSE 'buy_'||substr(sha256('Germany|'||{bn}),1,20) END"
    de_supplier=f"CASE WHEN nullif({sn},'') IS NULL THEN NULL ELSE 'sup_'||substr(sha256('Germany|'||{sn}||'|'||upper(coalesce(nullif(Supplier_Country,''),'UNKNOWN'))),1,20) END"

    # NOTICE-FIRST fact layer = collision-repaired Global Core v2 + independently validated Germany.
    con.execute(f"""COPY (
      SELECT *, 'NOTICE_FIRST' AS Evidence_Type FROM read_parquet('{(v2/'historical_tenders.parquet').as_posix()}')
      UNION ALL BY NAME
      SELECT 'Germany' AS Warehouse_Source,* EXCLUDE(Buyer_ID),
             Buyer_ID AS Source_Buyer_ID,{de_buyer} AS Buyer_ID,'NOTICE_FIRST' AS Evidence_Type
      FROM read_csv_auto('{(de/'historical_tenders.csv.gz').as_posix()}',header=true,all_varchar=true,union_by_name=true,sample_size=-1)
    ) TO '{(out/'historical_tenders.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")

    # Germany awards inherit the re-keyed tender buyer. Supplier identity is evidence-bearing name+country.
    con.execute(f"""COPY (
      SELECT *, 'NOTICE_FIRST' AS Evidence_Type FROM read_parquet('{(v2/'awards.parquet').as_posix()}')
      UNION ALL BY NAME
      SELECT 'Germany' AS Warehouse_Source,aa.* EXCLUDE(Buyer_ID,Supplier_ID),
             aa.Buyer_ID AS Source_Buyer_ID,aa.Supplier_ID AS Source_Supplier_ID,
             tt.Buyer_ID AS Buyer_ID,{de_supplier.replace('Supplier_Name','aa.Supplier_Name').replace('Supplier_Country','aa.Supplier_Country')} AS Supplier_ID,
             'NOTICE_FIRST' AS Evidence_Type
      FROM read_csv_auto('{(de/'awards.csv.gz').as_posix()}',header=true,all_varchar=true,union_by_name=true,sample_size=-1) aa
      LEFT JOIN read_parquet('{(out/'historical_tenders.parquet').as_posix()}') tt
        ON tt.Warehouse_Source='Germany' AND aa.Historical_Tender_ID=tt.Historical_Tender_ID
    ) TO '{(out/'awards.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")

    # Re-key Germany supplier bridge, collapsing only same award + same evidence-bearing supplier identity.
    bridge_sn=norm('Supplier_Name')
    bridge_sid=f"CASE WHEN nullif({bridge_sn},'') IS NULL THEN NULL ELSE 'sup_'||substr(sha256('Germany|'||{bridge_sn}||'|'||upper(coalesce(nullif(Supplier_Country,''),'UNKNOWN'))),1,20) END"
    con.execute(f"""COPY (
      SELECT *, 'NOTICE_FIRST' AS Evidence_Type FROM read_parquet('{(v2/'award_suppliers.parquet').as_posix()}')
      UNION ALL BY NAME
      SELECT 'Germany' AS Warehouse_Source,Award_ID,New_Supplier_ID AS Supplier_ID,
             any_value(Source_Supplier_ID) AS Source_Supplier_ID,
             any_value(Supplier_Name) AS Supplier_Name,any_value(Relationship) AS Relationship,
             max(try_cast(nullif(Award_Value_Allocated,'') AS DOUBLE)) AS Award_Value_Allocated,
             any_value(Supplier_Country) AS Supplier_Country,any_value(SME_Status) AS SME_Status,
             'NOTICE_FIRST' AS Evidence_Type
      FROM (
        SELECT *,Supplier_ID AS Source_Supplier_ID,{bridge_sid} AS New_Supplier_ID
        FROM read_csv_auto('{(de/'award_suppliers.csv.gz').as_posix()}',header=true,all_varchar=true,union_by_name=true,sample_size=-1)
      ) x
      WHERE New_Supplier_ID IS NOT NULL
      GROUP BY Award_ID,New_Supplier_ID
    ) TO '{(out/'award_suppliers.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")

    # Rebuild entity dimensions from facts so Germany uses the same v2 identity method.
    con.execute(f"""COPY (
      WITH t AS (
        SELECT Warehouse_Source,Buyer_ID,arg_max(Buyer_Name,length(coalesce(Buyer_Name,''))) Buyer_Name,
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
      SELECT t.Warehouse_Source,t.Buyer_ID,t.Buyer_Name,{norm('t.Buyer_Name')} AS Normalized_Name,t.Country,
             t.Observed_Tenders,coalesce(aw.Observed_Awards,0) Observed_Awards,
             aw.Median_Award_Value,aw.Median_Bidder_Count,'NOTICE_FIRST' Evidence_Type
      FROM t LEFT JOIN aw USING(Warehouse_Source,Buyer_ID)
    ) TO '{(out/'buyers.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")

    con.execute(f"""COPY (
      SELECT Warehouse_Source,Supplier_ID,arg_max(Supplier_Name,length(coalesce(Supplier_Name,''))) Supplier_Name,
             {norm('Supplier_Name')} AS Normalized_Name,any_value(Supplier_Country) Country,
             count(distinct Award_ID) Observed_Contracts_Won,median(try_cast(Award_Value_Allocated AS DOUBLE)) Median_Allocated_Value,
             'NOTICE_FIRST' Evidence_Type
      FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}')
      GROUP BY 1,2
    ) TO '{(out/'suppliers.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")

    # Country/source summary; money remains source-currency scoped and is never summed cross-market.
    con.execute(f"""COPY (
      WITH t AS (SELECT Warehouse_Source,count(*) Tender_Count,count(distinct Buyer_ID) Buyer_Count FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}') GROUP BY 1),
           aw AS (SELECT Warehouse_Source,count(*) Award_Count,avg(CASE WHEN nullif(Bidder_Count,'') IS NOT NULL AND Bidder_Count<>'UNKNOWN' THEN 1 ELSE 0 END)*100 Bidder_Coverage_Pct FROM read_parquet('{(out/'awards.parquet').as_posix()}') GROUP BY 1)
      SELECT t.*,aw.Award_Count,aw.Bidder_Coverage_Pct,'NOTICE_FIRST' Evidence_Type FROM t LEFT JOIN aw USING(Warehouse_Source) ORDER BY Tender_Count DESC
    ) TO '{(out/'country_summary.csv').as_posix()}' (HEADER)""")

    # Compact opportunity cohorts only for notice-first evidence.
    con.execute(f"""COPY (
      SELECT Warehouse_Source,coalesce(nullif(Category,''),'UNKNOWN') Category,coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,
             coalesce(nullif(Currency,''),'UNKNOWN') Currency,count(*) Tender_Count,
             median(try_cast(nullif(Lean_Fit,'') AS DOUBLE)) Median_Lean_Fit,
             avg(CASE WHEN nullif(Official_Estimated_Value,'') IS NOT NULL THEN 1 ELSE 0 END)*100 Estimate_Coverage_Pct,
             median(try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE)) Median_Estimated_Value,
             'NOTICE_FIRST' Evidence_Type,'DERIVED_FROM_VALIDATED_CANONICAL_ROWS' Derived_Status
      FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}') GROUP BY 1,2,3,4 ORDER BY Tender_Count DESC
    ) TO '{(out/'market_cohorts.csv').as_posix()}' (HEADER)""")

    # CSV.gz companions for manageable notice-first relations.
    for n in ['historical_tenders','awards','award_suppliers','buyers','suppliers']:
        con.execute(f"COPY (SELECT * FROM read_parquet('{(out/(n+'.parquet')).as_posix()}')) TO '{(out/(n+'.csv.gz')).as_posix()}' (HEADER,COMPRESSION GZIP)")

    counts={n:con.execute(f"SELECT count(*) FROM read_parquet('{(out/(n+'.parquet')).as_posix()}')").fetchone()[0] for n in ['historical_tenders','awards','award_suppliers','buyers','suppliers']}
    checks={}
    checks['tender_ids_unique']=con.execute(f"SELECT count(*)=count(distinct Historical_Tender_ID) FROM read_parquet('{(out/'historical_tenders.parquet').as_posix()}')").fetchone()[0]
    checks['award_ids_unique']=con.execute(f"SELECT count(*)=count(distinct Award_ID) FROM read_parquet('{(out/'awards.parquet').as_posix()}')").fetchone()[0]
    checks['bridge_keys_unique']=con.execute(f"SELECT count(*)=count(distinct Warehouse_Source||'|'||Award_ID||'|'||Supplier_ID) FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}')").fetchone()[0]
    checks['award_tender_orphans']=con.execute(f"SELECT count(*) FROM read_parquet('{(out/'awards.parquet').as_posix()}') a LEFT JOIN read_parquet('{(out/'historical_tenders.parquet').as_posix()}') t USING(Warehouse_Source,Historical_Tender_ID) WHERE t.Historical_Tender_ID IS NULL").fetchone()[0]
    checks['award_buyer_orphans']=con.execute(f"SELECT count(*) FROM read_parquet('{(out/'awards.parquet').as_posix()}') a LEFT JOIN read_parquet('{(out/'buyers.parquet').as_posix()}') b USING(Warehouse_Source,Buyer_ID) WHERE a.Buyer_ID IS NOT NULL AND b.Buyer_ID IS NULL").fetchone()[0]
    checks['bridge_supplier_orphans']=con.execute(f"SELECT count(*) FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}') a LEFT JOIN read_parquet('{(out/'suppliers.parquet').as_posix()}') s USING(Warehouse_Source,Supplier_ID) WHERE s.Supplier_ID IS NULL").fetchone()[0]
    checks['buyer_identity_collisions']=con.execute(f"SELECT count(*) FROM (SELECT Warehouse_Source,Buyer_ID,count(distinct Normalized_Name) n FROM read_parquet('{(out/'buyers.parquet').as_posix()}') GROUP BY 1,2 HAVING n>1)").fetchone()[0]
    checks['supplier_identity_collisions']=con.execute(f"SELECT count(*) FROM (SELECT Warehouse_Source,Supplier_ID,count(distinct Normalized_Name||'|'||upper(coalesce(Country,'UNKNOWN'))) n FROM read_parquet('{(out/'suppliers.parquet').as_posix()}') GROUP BY 1,2 HAVING n>1)").fetchone()[0]

    usa=json.loads(Path(a.usa_quality).read_text(encoding='utf-8'))
    expected_tenders=621515+638737
    expected_awards=510490+251084
    pass_core=(counts['historical_tenders']==expected_tenders and counts['awards']==expected_awards and checks['tender_ids_unique'] and checks['award_ids_unique'] and checks['bridge_keys_unique'] and checks['award_tender_orphans']==0 and checks['award_buyer_orphans']==0 and checks['bridge_supplier_orphans']==0 and checks['buyer_identity_collisions']==0 and checks['supplier_identity_collisions']==0)
    created=datetime.now(timezone.utc).isoformat()
    evidence_lanes={
      'version':'GLOBAL_CORE_V3_FEDERATED', 'created_at':created,
      'notice_first':{'materialized_here':True,'sources':['Global Core v2: Ireland, Canada federal, United Kingdom, Quebec, France','Germany eForms'],'tenders':counts['historical_tenders'],'awards':counts['awards'],'release_target':'tender-normalized-global-core-v3'},
      'usa_award_first':{'materialized_here':False,'source_release':'tender-normalized-usa-awards-v1','evidence_type':'AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING','canonical_tenders':usa.get('canonical_tenders'),'canonical_awards':usa.get('canonical_awards'),'unique_buyers':usa.get('unique_buyers'),'unique_suppliers':usa.get('unique_suppliers'),'award_value_coverage_pct':usa.get('award_value_coverage_pct'),'bidder_count_coverage_pct':usa.get('bidder_count_coverage_pct'),'reason':'Referenced rather than duplicated so opportunity-notice counts are not contaminated and multi-gigabyte validated facts are not copied.'}
    }
    (out/'evidence_lanes.json').write_text(json.dumps(evidence_lanes,indent=2),encoding='utf-8')
    quality={'version':'GLOBAL_CORE_V3_FEDERATED','created_at':created,'counts_notice_first':counts,'integrity':checks,'expected_notice_first_tenders':expected_tenders,'expected_notice_first_awards':expected_awards,'usa_award_first_release':'tender-normalized-usa-awards-v1','currency_rule':'No cross-currency monetary aggregation.','evidence_rule':'USA award-first remains a separately typed federated lane and is not counted as original opportunities.','status':'PASS' if pass_core else 'FAIL'}
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    manifest={'version':'GLOBAL_CORE_V3_FEDERATED','created_at':created,'files':{}}
    for p in out.iterdir():
        if p.is_file() and p.name!='run_manifest.json':
            h=hashlib.sha256()
            with p.open('rb') as f:
                for ch in iter(lambda:f.read(1024*1024),b''):h.update(ch)
            manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':h.hexdigest()}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(quality,indent=2))
    if not pass_core: raise SystemExit(2)

if __name__=='__main__':main()
