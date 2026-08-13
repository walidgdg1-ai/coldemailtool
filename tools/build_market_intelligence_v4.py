#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json
import duckdb


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--core',required=True)
    ap.add_argument('--usa-rank',required=True)
    ap.add_argument('--usa-repeat',required=True)
    ap.add_argument('--out',required=True)
    a=ap.parse_args();core=Path(a.core);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.execute("SET preserve_insertion_order=false");con.execute("SET threads=2");con.execute("SET memory_limit='6GB'")
    t=(core/'historical_tenders.parquet').as_posix();aw=(core/'awards.parquet').as_posix();br=(core/'award_suppliers.parquet').as_posix()
    core_q=json.loads((core/'data_quality.json').read_text())
    assert core_q.get('status')=='PASS',core_q

    con.execute(f"""COPY (
      WITH tend AS (
        SELECT Warehouse_Source,coalesce(nullif(Category,''),'UNKNOWN') Category,coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,
               coalesce(nullif(Currency,''),'UNKNOWN') Currency,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,
               median(try_cast(nullif(Lean_Fit,'') AS DOUBLE)) Median_Lean_Fit,
               median(try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE)) Median_Estimated_Value,
               avg(CASE WHEN try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END)*100 Estimate_Coverage_Pct
        FROM read_parquet('{t}') GROUP BY 1,2,3,4
      ), a AS (
        SELECT tt.Warehouse_Source,coalesce(nullif(tt.Category,''),'UNKNOWN') Category,coalesce(nullif(tt.Subcategory,''),'UNKNOWN') Subcategory,
               coalesce(nullif(tt.Currency,''),'UNKNOWN') Currency,count(distinct aa.Award_ID) Award_Count,
               count(distinct aa.Supplier_ID) Unique_Award_Suppliers,median(try_cast(nullif(aa.Award_Value,'') AS DOUBLE)) Median_Award_Value,
               median(try_cast(nullif(aa.Bidder_Count,'') AS DOUBLE)) Median_Bidder_Count,
               avg(CASE WHEN try_cast(nullif(aa.Bidder_Count,'') AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END)*100 Bidder_Count_Coverage_Pct,
               avg(CASE WHEN try_cast(nullif(aa.Bidder_Count,'') AS DOUBLE)=1 THEN 1 ELSE 0 END)*100 Single_Bid_Award_Pct
        FROM read_parquet('{t}') tt JOIN read_parquet('{aw}') aa USING(Warehouse_Source,Historical_Tender_ID)
        GROUP BY 1,2,3,4
      )
      SELECT tend.*,coalesce(a.Award_Count,0) Award_Count,coalesce(a.Unique_Award_Suppliers,0) Unique_Award_Suppliers,
             a.Median_Award_Value,a.Median_Bidder_Count,a.Bidder_Count_Coverage_Pct,a.Single_Bid_Award_Pct,
             'NOTICE_FIRST' Evidence_Type
      FROM tend LEFT JOIN a USING(Warehouse_Source,Category,Subcategory,Currency)
    ) TO '{(out/'notice_cohort_facts.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      WITH bridge AS (
        SELECT Warehouse_Source,Award_ID,Supplier_ID,1.0/count(*) OVER(PARTITION BY Warehouse_Source,Award_ID) Fractional_Award
        FROM read_parquet('{br}')
      ), sx AS (
        SELECT tt.Warehouse_Source,coalesce(nullif(tt.Category,''),'UNKNOWN') Category,coalesce(nullif(tt.Subcategory,''),'UNKNOWN') Subcategory,
               coalesce(nullif(tt.Currency,''),'UNKNOWN') Currency,b.Supplier_ID,sum(b.Fractional_Award) Fractional_Awards
        FROM read_parquet('{aw}') aa JOIN read_parquet('{t}') tt USING(Warehouse_Source,Historical_Tender_ID)
        JOIN bridge b USING(Warehouse_Source,Award_ID) GROUP BY 1,2,3,4,5
      ), shares AS (
        SELECT *,Fractional_Awards/sum(Fractional_Awards) OVER(PARTITION BY Warehouse_Source,Category,Subcategory,Currency) Supplier_Share FROM sx
      )
      SELECT Warehouse_Source,Category,Subcategory,Currency,count(*) Supplier_Count,max(Supplier_Share)*100 Top_Supplier_Share_Pct,
             sum(Supplier_Share*Supplier_Share)*10000 Supplier_HHI,
             CASE WHEN sum(Supplier_Share*Supplier_Share)*10000<1500 THEN 'FRAGMENTED' WHEN sum(Supplier_Share*Supplier_Share)*10000<2500 THEN 'MODERATE' ELSE 'CONCENTRATED' END Supplier_Concentration,
             'NOTICE_FIRST' Evidence_Type
      FROM shares GROUP BY 1,2,3,4
    ) TO '{(out/'notice_supplier_fragmentation.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      WITH x AS (
        SELECT Warehouse_Source,Buyer_ID,any_value(Buyer_Name) Buyer_Name,coalesce(nullif(Category,''),'UNKNOWN') Category,
               coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,count(*) Tender_Count,min(try_cast(Publication_Date AS DATE)) First_Publication_Date,
               max(try_cast(Publication_Date AS DATE)) Last_Publication_Date,median(try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE)) Median_Estimated_Value,
               any_value(coalesce(nullif(Currency,''),'UNKNOWN')) Currency
        FROM read_parquet('{t}') WHERE nullif(Buyer_ID,'') IS NOT NULL GROUP BY 1,2,4,5
      )
      SELECT *,CASE WHEN Tender_Count>=20 THEN 'VERY_HIGH_REPEAT' WHEN Tender_Count>=10 THEN 'HIGH_REPEAT' WHEN Tender_Count>=5 THEN 'REPEAT' ELSE 'LOW_REPEAT' END Repeat_Band,
             'NOTICE_FIRST' Evidence_Type,'DERIVED_FROM_GLOBAL_CORE_V4' Derived_Status
      FROM x WHERE Tender_Count>=3 ORDER BY Tender_Count DESC
    ) TO '{(out/'notice_repeat_buyers.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      WITH f AS (SELECT * FROM read_csv_auto('{(out/'notice_cohort_facts.csv').as_posix()}',header=true)),
           s AS (SELECT * EXCLUDE(Evidence_Type) FROM read_csv_auto('{(out/'notice_supplier_fragmentation.csv').as_posix()}',header=true)),
           j AS (
             SELECT f.*,s.Supplier_Count,s.Top_Supplier_Share_Pct,s.Supplier_HHI,s.Supplier_Concentration,
                    percent_rank() OVER(PARTITION BY f.Warehouse_Source ORDER BY f.Tender_Count) Vol_Pct,
                    percent_rank() OVER(PARTITION BY f.Warehouse_Source ORDER BY coalesce(f.Unique_Buyers,0)) BuyerBreadth_Pct,
                    percent_rank() OVER(PARTITION BY f.Warehouse_Source ORDER BY coalesce(f.Median_Lean_Fit,0)) Lean_Pct,
                    percent_rank() OVER(PARTITION BY f.Warehouse_Source ORDER BY -coalesce(s.Supplier_HHI,10000)) Fragmentation_Pct
             FROM f LEFT JOIN s USING(Warehouse_Source,Category,Subcategory,Currency)
           )
      SELECT *,round(100*(0.35*Vol_Pct+0.20*BuyerBreadth_Pct+0.20*Lean_Pct+0.15*Fragmentation_Pct+
             0.10*CASE WHEN Bidder_Count_Coverage_Pct>=30 AND Median_Bidder_Count IS NOT NULL THEN greatest(0.0,least(1.0,(8.0-Median_Bidder_Count)/7.0)) ELSE 0.5 END),2) Lean_Opportunity_Score,
             CASE WHEN Bidder_Count_Coverage_Pct>=30 THEN 'COMPETITION_OBSERVED' ELSE 'COMPETITION_LOW_COVERAGE' END Competition_Evidence_Status,
             'DERIVED_HEURISTIC_V4_NOTICE_FIRST' Derived_Status
      FROM j WHERE Tender_Count>=5 ORDER BY Lean_Opportunity_Score DESC,Tender_Count DESC
    ) TO '{(out/'notice_market_opportunity_rank.csv').as_posix()}' (HEADER)""")

    con.execute(f"COPY (SELECT *, 'AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING' Evidence_Type FROM read_csv_auto('{Path(a.usa_rank).as_posix()}',header=true,union_by_name=true)) TO '{(out/'usa_award_first_market_rank.csv').as_posix()}' (HEADER)")
    con.execute(f"COPY (SELECT *, 'AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING' Evidence_Type FROM read_csv_auto('{Path(a.usa_repeat).as_posix()}',header=true,union_by_name=true)) TO '{(out/'usa_award_first_repeat_buyers.csv').as_posix()}' (HEADER)")

    counts={p.name:con.execute(f"SELECT count(*) FROM read_csv_auto('{p.as_posix()}',header=true)").fetchone()[0] for p in out.glob('*.csv')}
    created=datetime.now(timezone.utc).isoformat(); expected=int(core_q['counts_notice_first']['historical_tenders'])
    quality={'version':'GLOBAL_MARKET_INTELLIGENCE_V4','created_at':created,'source_core_release':'tender-normalized-global-core-v4','notice_first_tenders_expected':expected,'source_core_counts':core_q['counts_notice_first'],'usa_award_first_source_release':'tender-normalized-usa-awards-v1','australia_award_first_source_release':'tender-normalized-austender-v1','outputs':counts,'guardrails':['Notice-first opportunity ranks exclude award-first reconstructed lanes','No FX mixing','Competition component neutral when bidder coverage <30%','Consortium supplier links fractionalized','Belgium contributes no invented award facts','All scores labelled DERIVED'],'status':'PASS'}
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    manifest={'version':quality['version'],'created_at':created,'files':{}}
    for p in out.iterdir():
        if p.is_file() and p.name!='run_manifest.json':
            bb=p.read_bytes();manifest['files'][p.name]={'bytes':len(bb),'sha256':hashlib.sha256(bb).hexdigest()}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(quality,indent=2))

if __name__=='__main__':main()
