#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, tempfile, zipfile
from datetime import datetime, timezone
from pathlib import Path
import duckdb

VERSION='USA_USASPENDING_AWARD_CANONICAL_V1'
START='2023-08-01'
END='2026-07-31'

SELECT_COLS=[
'contract_award_unique_key','award_id_piid','modification_number','transaction_number',
'federal_action_obligation','total_dollars_obligated','base_and_exercised_options_value','current_total_value_of_award','base_and_all_options_value','potential_total_value_of_award',
'action_date','period_of_performance_start_date','period_of_performance_current_end_date','period_of_performance_potential_end_date','solicitation_date',
'awarding_agency_code','awarding_agency_name','awarding_sub_agency_code','awarding_sub_agency_name','awarding_office_code','awarding_office_name',
'recipient_uei','recipient_duns','recipient_name','recipient_country_code','recipient_country_name','recipient_state_code','recipient_state_name','cage_code',
'award_or_idv_flag','award_type_code','award_type','idv_type_code','idv_type',
'transaction_description','prime_award_base_transaction_description','action_type_code','action_type','solicitation_identifier',
'product_or_service_code','product_or_service_code_description','naics_code','naics_description',
'extent_competed_code','extent_competed','solicitation_procedures_code','solicitation_procedures','type_of_set_aside_code','type_of_set_aside','number_of_offers_received',
'primary_place_of_performance_country_code','primary_place_of_performance_country_name','primary_place_of_performance_state_code','primary_place_of_performance_state_name',
'usaspending_permalink','initial_report_date','last_modified_date'
]

def qident(s): return '"'+s.replace('"','""')+'"'
def esc(s): return str(s).replace("'","''")
def sha256_file(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def ensure_dirs(work:Path):
    (work/'candidates').mkdir(parents=True,exist_ok=True)
    (work/'meta').mkdir(parents=True,exist_ok=True)

def ingest_zip(zip_path:Path,work:Path,start:str,end:str):
    ensure_dirs(work)
    manifest={'zip':zip_path.name,'zip_bytes':zip_path.stat().st_size,'zip_sha256':sha256_file(zip_path),'members':[],'created_at':datetime.now(timezone.utc).isoformat()}
    con=duckdb.connect()
    with zipfile.ZipFile(zip_path) as z:
        members=[i for i in z.infolist() if (not i.is_dir()) and i.filename.lower().endswith('.csv')]
        for idx,info in enumerate(members,1):
            fd,tmp=tempfile.mkstemp(prefix='usaspending_',suffix='.csv'); os.close(fd); tmp=Path(tmp)
            try:
                with z.open(info) as src,tmp.open('wb') as dst: shutil.copyfileobj(src,dst,1024*1024*8)
                header=con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{esc(tmp)}', header=true, all_varchar=true, sample_size=10000, ignore_errors=false)").fetchall()
                names={r[0] for r in header}
                missing=[c for c in SELECT_COLS if c not in names]
                if missing: raise RuntimeError(f'{info.filename}: missing required columns {missing}')
                dest=work/'candidates'/f'{zip_path.stem}_{idx:02d}.parquet'
                select=',\n'.join(qident(c) for c in SELECT_COLS)
                sql=f"""
                COPY (
                  SELECT {select},
                    COALESCE(TRY_CAST(last_modified_date AS TIMESTAMP),TRY_CAST(action_date AS TIMESTAMP),TIMESTAMP '1900-01-01') AS _rank_ts,
                    '{esc(zip_path.name)}' AS _source_zip,
                    '{esc(info.filename)}' AS _source_member
                  FROM read_csv_auto('{esc(tmp)}', header=true, all_varchar=true, sample_size=10000, ignore_errors=false)
                  WHERE TRY_CAST(action_date AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
                    AND COALESCE(NULLIF(contract_award_unique_key,''),NULLIF(award_id_piid,'')) IS NOT NULL
                ) TO '{esc(dest)}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
                con.execute(sql)
                rows=con.execute(f"SELECT COUNT(*) FROM read_parquet('{esc(dest)}')").fetchone()[0]
                manifest['members'].append({'name':info.filename,'compressed_bytes':info.compress_size,'uncompressed_bytes':info.file_size,'candidate_rows':rows,'candidate_file':dest.name,'candidate_bytes':dest.stat().st_size,'candidate_sha256':sha256_file(dest)})
                print('INGESTED',zip_path.name,info.filename,'candidate_rows',rows,flush=True)
            finally:
                tmp.unlink(missing_ok=True)
    con.close()
    mp=work/'meta'/f'{zip_path.stem}.manifest.json'; mp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'zip':zip_path.name,'members':len(manifest['members']),'candidate_rows':sum(x['candidate_rows'] for x in manifest['members'])},indent=2))

def category_case(alias='a'):
    blob=f"lower(coalesce({alias}.prime_award_base_transaction_description,'') || ' ' || coalesce({alias}.transaction_description,'') || ' ' || coalesce({alias}.naics_description,'') || ' ' || coalesce({alias}.product_or_service_code_description,''))"
    return f"""CASE
      WHEN regexp_matches({blob}, 'website|web site|web development|content management|\\bcms\\b|web portal') THEN 'Web'
      WHEN regexp_matches({blob}, 'digitiz|digitis|ocr|scann|document imaging|data entry|indexing') THEN 'Document / data'
      WHEN regexp_matches({blob}, 'translation|transcription|caption|subtitl|interpretation|language service') THEN 'Language'
      WHEN regexp_matches({blob}, 'graphic design|communications|communication service|advertising|video production|film production|content creation|publishing|publication') THEN 'Creative / communications'
      WHEN regexp_matches({blob}, 'printing|print service|mailing|fulfillment') THEN 'Printing'
      WHEN regexp_matches({blob}, 'software|application development|automation|data migration|dashboard|platform|saas') THEN 'Automation / software'
      WHEN regexp_matches({blob}, 'market research|survey|analysis|monitoring|evaluation|study') THEN 'Monitoring / research'
      ELSE 'Other' END"""

def subcategory_case(alias='a'):
    cat=category_case(alias)
    return f"CASE {cat} WHEN 'Web' THEN 'Website / CMS' WHEN 'Document / data' THEN 'Digitization / OCR' WHEN 'Language' THEN 'Translation / transcription' WHEN 'Creative / communications' THEN 'Design / publishing / media' WHEN 'Printing' THEN 'Print / fulfillment' WHEN 'Automation / software' THEN 'Software / automation' WHEN 'Monitoring / research' THEN 'Monitoring / analysis' ELSE coalesce({alias}.naics_description,'UNKNOWN') END"

def lean_case(alias='a'):
    cat=category_case(alias)
    return f"CASE {cat} WHEN 'Document / data' THEN 92 WHEN 'Language' THEN 90 WHEN 'Web' THEN 88 WHEN 'Creative / communications' THEN 82 WHEN 'Automation / software' THEN 74 WHEN 'Monitoring / research' THEN 70 WHEN 'Printing' THEN 64 ELSE 20 END"

def finalize(work:Path,out:Path,start:str,end:str):
    out.mkdir(parents=True,exist_ok=True)
    files=sorted((work/'candidates').glob('*.parquet'))
    if not files: raise RuntimeError('No USA candidate parquet files found')
    con=duckdb.connect(str(work/'usa_awards.duckdb'))
    glob=esc(str(work/'candidates'/'*.parquet'))
    con.execute(f"""
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
    """)
    n=con.execute('SELECT COUNT(*) FROM latest').fetchone()[0]
    if n<100000: raise RuntimeError(f'Unexpectedly small USA canonical award set: {n}')
    cat=category_case('a'); sub=subcategory_case('a'); lean=lean_case('a')
    # Historical procurement reconstruction: explicit award-first semantics, not represented as an original solicitation notice.
    con.execute(f"""
      COPY (
        SELECT
          'ten_' || substr(sha256('USA|' || coalesce(nullif(a.contract_award_unique_key,''),a.awarding_agency_code || '|' || a.award_id_piid)),1,20) AS Historical_Tender_ID,
          nullif(a.solicitation_identifier,'') AS Official_Notice_ID,
          coalesce(nullif(a.solicitation_identifier,''),nullif(a.award_id_piid,''),a.contract_award_unique_key) AS Procurement_Reference,
          coalesce(nullif(a.prime_award_base_transaction_description,''),nullif(a.transaction_description,''),'Federal contract ' || coalesce(a.award_id_piid,a.contract_award_unique_key)) AS Title,
          'buy_' || substr(sha256('USA|' || coalesce(nullif(a.awarding_office_code,''),nullif(a.awarding_sub_agency_code,''),nullif(a.awarding_agency_code,''),a.awarding_agency_name)),1,20) AS Buyer_ID,
          coalesce(nullif(a.awarding_office_name,''),nullif(a.awarding_sub_agency_name,''),a.awarding_agency_name) AS Buyer_Name,
          'USA' AS Country,
          nullif(a.usaspending_permalink,'') AS Primary_Source_URL,
          'A' AS Source_Tier,
          cast(coalesce(try_cast(a.solicitation_date AS DATE),try_cast(a.action_date AS DATE)) AS VARCHAR) AS Publication_Date,
          NULL AS Deadline,
          {cat} AS Category,
          {sub} AS Subcategory,
          coalesce(nullif(a.naics_code,''),nullif(a.product_or_service_code,'')) AS CPV_NAICS_or_Local_Code,
          coalesce(nullif(a.prime_award_base_transaction_description,''),nullif(a.transaction_description,'')) AS Scope_Summary,
          NULL::DOUBLE AS Official_Estimated_Value,
          'USD' AS Currency,
          CASE WHEN a.period_of_performance_start_date<>'' OR a.period_of_performance_current_end_date<>'' THEN coalesce(a.period_of_performance_start_date,'') || ' → ' || coalesce(a.period_of_performance_current_end_date,'') ELSE NULL END AS Contract_Duration,
          'UNKNOWN' AS Award_Criteria,NULL::DOUBLE AS Price_Weight,NULL::DOUBLE AS Quality_Weight,
          'UNKNOWN' AS Minimum_Turnover,'UNKNOWN' AS References_Required,'UNKNOWN' AS Required_Certifications,
          CASE WHEN coalesce(a.primary_place_of_performance_country_code,'USA')='USA' THEN 'US_DELIVERY' ELSE 'FOREIGN_DELIVERY' END AS Onsite_Requirement,
          'UNKNOWN' AS Subcontracting_Status,'[]' AS Tender_Document_URLs,
          'AWARD_FIRST' AS Award_Link_Status,
          'awd_' || substr(sha256('USA|' || coalesce(nullif(a.contract_award_unique_key,''),a.awarding_agency_code || '|' || a.award_id_piid)),1,20) AS Linked_Award_ID,
          {lean} AS Automation_Potential,{lean} AS Lean_Fit,
          CASE WHEN a.solicitation_identifier<>'' THEN 92 ELSE 85 END AS Evidence_Confidence,
          '{datetime.now(timezone.utc).isoformat()}' AS Ingested_At,
          1 AS Source_Record_Count,'USAspending Contracts_Full' AS Source_Platform,
          coalesce(nullif(a.extent_competed,''),'UNKNOWN') AS Competition_Type,
          coalesce(nullif(a.solicitation_procedures,''),'UNKNOWN') AS Procedure,
          coalesce(nullif(a.type_of_set_aside,''),'NONE/UNKNOWN') AS Threshold_Level,
          NULL AS Directive,NULL AS Parent_Agreement_ID,
          nullif(a.naics_description,'') AS Raw_Spend_Category,
          nullif(a.product_or_service_code_description,'') AS Raw_CPV_Description,
          NULL AS Cancelled_Date,
          'AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING' AS Source_Grain_Status,
          a.contract_award_unique_key AS US_Contract_Award_Unique_Key,
          a.award_id_piid AS PIID,
          a.solicitation_identifier AS Solicitation_Identifier,
          try_cast(nullif(a.number_of_offers_received,'') AS INTEGER) AS Official_Bidder_Count,
          a.type_of_set_aside AS Set_Aside,
          a.extent_competed AS Extent_Competed,
          a.recipient_country_code AS Winner_Country,
          a.naics_code AS NAICS_Code,a.product_or_service_code AS PSC_Code,
          a._source_zip AS Source_Archive
        FROM latest a
      ) TO '{esc(out/'historical_tenders.csv.gz')}' (HEADER, COMPRESSION GZIP)
    """)
    con.execute(f"""
      COPY (
        SELECT
          'awd_' || substr(sha256('USA|' || coalesce(nullif(a.contract_award_unique_key,''),a.awarding_agency_code || '|' || a.award_id_piid)),1,20) AS Award_ID,
          'ten_' || substr(sha256('USA|' || coalesce(nullif(a.contract_award_unique_key,''),a.awarding_agency_code || '|' || a.award_id_piid)),1,20) AS Historical_Tender_ID,
          a.award_id_piid AS Official_Award_Notice_ID,
          a.contract_award_unique_key AS Contract_ID,
          'buy_' || substr(sha256('USA|' || coalesce(nullif(a.awarding_office_code,''),nullif(a.awarding_sub_agency_code,''),nullif(a.awarding_agency_code,''),a.awarding_agency_name)),1,20) AS Buyer_ID,
          'sup_' || substr(sha256('USA|' || coalesce(nullif(a.recipient_uei,''),nullif(a.recipient_duns,''),nullif(a.cage_code,''),a.recipient_name)),1,20) AS Supplier_ID,
          a.recipient_name AS Supplier_Name,
          coalesce(nullif(a.recipient_country_code,''),'UNKNOWN') AS Supplier_Country,
          cast(try_cast(a.action_date AS DATE) AS VARCHAR) AS Award_Date,
          coalesce(try_cast(nullif(a.current_total_value_of_award,'') AS DOUBLE),try_cast(nullif(a.total_dollars_obligated,'') AS DOUBLE),try_cast(nullif(a.base_and_exercised_options_value,'') AS DOUBLE)) AS Award_Value,
          'USD' AS Currency,NULL::DOUBLE AS Original_Estimated_Value,
          try_cast(nullif(a.number_of_offers_received,'') AS INTEGER) AS Bidder_Count,
          NULL::INTEGER AS Electronic_Bidder_Count,
          'UNKNOWN' AS SME_Winner_Status,
          CASE WHEN a.period_of_performance_start_date<>'' OR a.period_of_performance_current_end_date<>'' THEN coalesce(a.period_of_performance_start_date,'') || ' → ' || coalesce(a.period_of_performance_current_end_date,'') ELSE NULL END AS Contract_Duration,
          'UNKNOWN' AS Renewal_Options,'UNKNOWN' AS Award_Criteria,NULL AS Award_Reason_Summary,
          nullif(a.usaspending_permalink,'') AS Primary_Source_URL,'VERIFIED_PRIMARY_USASPENDING' AS Verification_Status,
          try_cast(nullif(a.federal_action_obligation,'') AS DOUBLE) AS Modification_Value,
          '{datetime.now(timezone.utc).isoformat()}' AS Last_Updated_At,
          'awd_' || substr(sha256('USA|' || coalesce(nullif(a.contract_award_unique_key,''),a.awarding_agency_code || '|' || a.award_id_piid)),1,20) AS Award_Group_ID,
          'AWARD_TOTAL_CURRENT_SNAPSHOT' AS Award_Value_Scope,1 AS Supplier_Count,1 AS Source_Record_Count,
          try_cast(nullif(a.total_dollars_obligated,'') AS DOUBLE) AS Total_Dollars_Obligated,
          try_cast(nullif(a.potential_total_value_of_award,'') AS DOUBLE) AS Potential_Total_Value,
          a.type_of_set_aside AS Set_Aside,a.extent_competed AS Extent_Competed,a.solicitation_procedures AS Solicitation_Procedures,
          a.naics_code AS NAICS_Code,a.product_or_service_code AS PSC_Code,a._source_zip AS Source_Archive
        FROM latest a
      ) TO '{esc(out/'awards.csv.gz')}' (HEADER, COMPRESSION GZIP)
    """)
    con.execute(f"""
      COPY (
        SELECT
          'awd_' || substr(sha256('USA|' || coalesce(nullif(a.contract_award_unique_key,''),a.awarding_agency_code || '|' || a.award_id_piid)),1,20) AS Award_ID,
          'sup_' || substr(sha256('USA|' || coalesce(nullif(a.recipient_uei,''),nullif(a.recipient_duns,''),nullif(a.cage_code,''),a.recipient_name)),1,20) AS Supplier_ID,
          a.recipient_name AS Supplier_Name,'AWARDED_SUPPLIER' AS Relationship,
          coalesce(try_cast(nullif(a.current_total_value_of_award,'') AS DOUBLE),try_cast(nullif(a.total_dollars_obligated,'') AS DOUBLE),try_cast(nullif(a.base_and_exercised_options_value,'') AS DOUBLE)) AS Award_Value_Allocated,
          coalesce(nullif(a.recipient_country_code,''),'UNKNOWN') AS Supplier_Country,'UNKNOWN' AS SME_Status
        FROM latest a WHERE nullif(a.recipient_name,'') IS NOT NULL
      ) TO '{esc(out/'award_suppliers.csv.gz')}' (HEADER, COMPRESSION GZIP)
    """)
    con.execute(f"""
      COPY (
        SELECT Buyer_ID,any_value(Buyer_Name) Buyer_Name,lower(any_value(Buyer_Name)) Normalized_Name,'USA' Country,'FEDERAL' Buyer_Type,'USAspending' Primary_Procurement_Portal,
          count(*) Observed_Tenders,count(*) Observed_Awards,sum(Award_Value) Observed_Award_Value_Total,median(Award_Value) Median_Award_Value,median(Bidder_Count) Median_Bidder_Count,'{datetime.now(timezone.utc).isoformat()}' Last_Updated_At
        FROM read_csv_auto('{esc(out/'awards.csv.gz')}',header=true) a
        JOIN (SELECT DISTINCT Buyer_ID,Buyer_Name FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true)) t USING(Buyer_ID)
        GROUP BY Buyer_ID
      ) TO '{esc(out/'buyers.csv.gz')}' (HEADER, COMPRESSION GZIP)
    """)
    con.execute(f"""
      COPY (
        SELECT Supplier_ID,any_value(Supplier_Name) Supplier_Name,lower(any_value(Supplier_Name)) Normalized_Name,any_value(Supplier_Country) Country,
          count(DISTINCT Award_ID) Observed_Contracts_Won,sum(Award_Value_Allocated) Observed_Award_Value_Total,median(Award_Value_Allocated) Median_Award_Value,
          count(DISTINCT Award_ID) Repeat_Wins,'{datetime.now(timezone.utc).isoformat()}' Last_Updated_At
        FROM read_csv_auto('{esc(out/'award_suppliers.csv.gz')}',header=true) GROUP BY Supplier_ID
      ) TO '{esc(out/'suppliers.csv.gz')}' (HEADER, COMPRESSION GZIP)
    """)
    con.execute(f"""
      COPY (
        SELECT Category,Subcategory,count(*) Tender_Count,count(*) Award_Count,median(Lean_Fit) Median_Lean_Fit,median(Award_Value) Median_Award_Value_USD,
          median(Bidder_Count) Median_Bidder_Count,100*avg(CASE WHEN Award_Value IS NOT NULL THEN 1 ELSE 0 END) Award_Value_Coverage_Pct,
          100*avg(CASE WHEN Bidder_Count IS NOT NULL THEN 1 ELSE 0 END) Bidder_Count_Coverage_Pct,
          round(0.35*median(Lean_Fit)+0.20*least(100,18*log10(greatest(coalesce(median(Award_Value),1),1)))+0.20*(CASE WHEN median(Bidder_Count) IS NULL THEN 50 ELSE greatest(0,100-least(100,12*median(Bidder_Count))) END)+0.15*least(100,18*log10(greatest(count(*),1)))+0.10*(50*avg(CASE WHEN Award_Value IS NOT NULL THEN 1 ELSE 0 END)+50*avg(CASE WHEN Bidder_Count IS NOT NULL THEN 1 ELSE 0 END)),2) Market_Attractiveness_Score,
          'DERIVED' Derived_Status
        FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true) t JOIN read_csv_auto('{esc(out/'awards.csv.gz')}',header=true) a USING(Historical_Tender_ID)
        GROUP BY Category,Subcategory ORDER BY Market_Attractiveness_Score DESC,Tender_Count DESC
      ) TO '{esc(out/'market_rank.csv')}' (HEADER)
    """)
    con.execute(f"""
      COPY (
        SELECT Buyer_ID,any_value(Buyer_Name) Buyer_Name,Category,Subcategory,count(*) Tender_Count,median(Lean_Fit) Median_Lean_Fit,'DERIVED' Derived_Status
        FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true)
        GROUP BY Buyer_ID,Category,Subcategory HAVING count(*)>=2 ORDER BY Tender_Count DESC,Median_Lean_Fit DESC
      ) TO '{esc(out/'repeat_buyers.csv')}' (HEADER)
    """)
    con.execute(f"""
      COPY (
        SELECT t.Historical_Tender_ID,t.Title,t.Buyer_Name,t.Category,t.Subcategory,t.Lean_Fit,a.Award_ID,a.Award_Value,a.Bidder_Count,a.Supplier_Name,a.Set_Aside,a.Extent_Competed,'DERIVED' Derived_Status
        FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true) t JOIN read_csv_auto('{esc(out/'awards.csv.gz')}',header=true) a USING(Historical_Tender_ID)
        WHERE t.Lean_Fit>=70 AND (coalesce(a.Bidder_Count,999999)<=3 OR coalesce(a.Award_Value,0)>=100000)
        ORDER BY t.Lean_Fit DESC,a.Award_Value DESC LIMIT 20000
      ) TO '{esc(out/'historical_anomalies.csv')}' (HEADER)
    """)
    counts={
      'canonical_awards':n,
      'canonical_tenders':con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true)").fetchone()[0],
      'unique_buyers':con.execute(f"SELECT COUNT(DISTINCT Buyer_ID) FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true)").fetchone()[0],
      'unique_suppliers':con.execute(f"SELECT COUNT(DISTINCT Supplier_ID) FROM read_csv_auto('{esc(out/'award_suppliers.csv.gz')}',header=true)").fetchone()[0],
    }
    dq={
      'version':VERSION,'source':'USAspending official Contracts_Full prime-award transaction archives','window_start':start,'window_end':end,**counts,
      'award_value_coverage_pct':con.execute(f"SELECT round(100*avg(CASE WHEN Award_Value IS NOT NULL THEN 1 ELSE 0 END),2) FROM read_csv_auto('{esc(out/'awards.csv.gz')}',header=true)").fetchone()[0],
      'bidder_count_coverage_pct':con.execute(f"SELECT round(100*avg(CASE WHEN Bidder_Count IS NOT NULL THEN 1 ELSE 0 END),2) FROM read_csv_auto('{esc(out/'awards.csv.gz')}',header=true)").fetchone()[0],
      'solicitation_identifier_coverage_pct':con.execute(f"SELECT round(100*avg(CASE WHEN Solicitation_Identifier IS NOT NULL AND Solicitation_Identifier<>'' THEN 1 ELSE 0 END),2) FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true)").fetchone()[0],
      'integrity':{
        'tender_ids_unique':con.execute(f"SELECT COUNT(*)=COUNT(DISTINCT Historical_Tender_ID) FROM read_csv_auto('{esc(out/'historical_tenders.csv.gz')}',header=true)").fetchone()[0],
        'award_ids_unique':con.execute(f"SELECT COUNT(*)=COUNT(DISTINCT Award_ID) FROM read_csv_auto('{esc(out/'awards.csv.gz')}',header=true)").fetchone()[0],
        'one_supplier_bridge_per_award':con.execute(f"SELECT COUNT(*)=COUNT(DISTINCT Award_ID) FROM read_csv_auto('{esc(out/'award_suppliers.csv.gz')}',header=true)").fetchone()[0],
      },
      'notes':[
        'USAspending Contracts_Full is transaction-grain evidence. Canonicalization selects the latest transaction snapshot per contract_award_unique_key across FY2023-FY2026.',
        'Historical_Tenders rows are explicitly AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING; they are not asserted to be original SAM.gov opportunity notices.',
        'Award_Value uses current_total_value_of_award when published, then total_dollars_obligated/base_and_exercised_options_value as conservative fallbacks.',
        'Bidder_Count uses official number_of_offers_received only; no bidder counts are inferred.',
        'Solicitation identifiers, competition method, set-aside status, NAICS/PSC and official USAspending permalinks are retained for market intelligence.'
      ]
    }
    (out/'data_quality.json').write_text(json.dumps(dq,indent=2),encoding='utf-8')
    manifest={'version':VERSION,'created_at':datetime.now(timezone.utc).isoformat(),'counts':counts,'files':{}}
    for p in sorted(out.iterdir()):
      if p.is_file() and p.name!='run_manifest.json': manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':sha256_file(p)}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    con.close(); (work/'usa_awards.duckdb').unlink(missing_ok=True)
    print(json.dumps(dq,indent=2))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--work',required=True); ap.add_argument('--ingest-zip'); ap.add_argument('--out'); ap.add_argument('--start',default=START); ap.add_argument('--end',default=END); ap.add_argument('--finalize',action='store_true'); a=ap.parse_args()
    work=Path(a.work); ensure_dirs(work)
    if a.ingest_zip: ingest_zip(Path(a.ingest_zip),work,a.start,a.end)
    if a.finalize:
        if not a.out: raise SystemExit('--out required with --finalize')
        finalize(work,Path(a.out),a.start,a.end)
if __name__=='__main__': main()
