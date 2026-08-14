#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, math, re
from datetime import datetime, timezone
from pathlib import Path
import duckdb

STOPWORDS = {
    # English
    'the','and','for','with','from','into','this','that','these','those','contract','contracts','tender','tenders','procurement','services','service','supply','supplies','provision','framework','agreement','public','project','projects','works','work','notice','lot','lots','call','request','purchase','purchasing','delivery','management','support','maintenance','various','general','annual','new','related','including','other','requirements','requirement',
    # French
    'les','des','pour','avec','dans','sur','une','aux','par','marché','marches','accord','cadre','prestation','prestations','fourniture','fournitures','services','service','travaux','acquisition','achat','achats','mise','place','realisation','réalisation','relatif','relative','divers','diverses',
    # German
    'und','der','die','das','den','dem','des','für','mit','von','zur','zum','auftrag','ausschreibung','leistungen','leistung','lieferung','lieferungen','beschaffung','rahmenvertrag','projekt','arbeiten',
    # Dutch
    'van','voor','met','het','een','de','en','aan','op','over','diensten','dienst','levering','leveringen','opdracht','aanbesteding','raamovereenkomst','werken','werk',
    # Spanish / Italian / Portuguese common procurement noise
    'para','con','del','los','las','una','por','servicios','servicio','suministro','contrato','acuerdo','fornitura','servizi','servizio','appalto','accordo','com','dos','das','servicos','serviço','fornecimento','contratacao','contratação'
}


def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--core', required=True)
    ap.add_argument('--matched', required=True)
    ap.add_argument('--out', required=True)
    args=ap.parse_args()

    core=Path(args.core)
    matched_path=Path(args.matched)
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    tmp=out/'ducktmp'; tmp.mkdir(exist_ok=True)

    tender_path=core/'historical_tenders.parquet'
    if not tender_path.exists(): raise SystemExit(f'MISSING {tender_path}')
    if not matched_path.exists(): raise SystemExit(f'MISSING {matched_path}')

    con=duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=2")
    con.execute("SET memory_limit='6GB'")
    con.execute(f"SET temp_directory={q(tmp.as_posix())}")
    con.execute("SET max_temp_directory_size='18GB'")

    schema={r[0]:r[1] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(tender_path.as_posix())})").fetchall()}
    (out/'schema_profile.json').write_text(json.dumps(schema,indent=2),encoding='utf-8')
    cols=set(schema)
    required={'Warehouse_Source','Historical_Tender_ID','Title'}
    if not required.issubset(cols): raise SystemExit(f'MISSING_REQUIRED_COLUMNS {required-cols}')

    def col(name: str, fallback: str):
        return f'"{name}"' if name in cols else fallback

    buyer=col('Buyer_ID','NULL::VARCHAR')
    buyer_name=col('Buyer_Name',"'UNKNOWN'")
    country=col('Country',"'UNKNOWN'")
    category=col('Category',"'UNKNOWN'")
    subcategory=col('Subcategory',"'UNKNOWN'")
    pub=col('Publication_Date','NULL::DATE')
    lean=col('Lean_Fit','NULL::DOUBLE')
    desc=col('Description',"''")
    srcurl=col('Source_URL','NULL::VARCHAR')

    total=con.execute(f"SELECT count(*) FROM read_parquet({q(tender_path.as_posix())})").fetchone()[0]
    matched=con.execute(f"SELECT count(*) FROM read_parquet({q(matched_path.as_posix())})").fetchone()[0]

    # Materialize the entire open-world residual exactly once. This is the key volume lane.
    unmatched=out/'unmatched_tenders.parquet'
    con.execute(f"""
      COPY (
        SELECT t.Warehouse_Source,t.Historical_Tender_ID,
               cast(t.Title as varchar) Title,
               cast({desc} as varchar) Description,
               cast({category} as varchar) Category,
               cast({subcategory} as varchar) Subcategory,
               cast({buyer} as varchar) Buyer_ID,
               cast({buyer_name} as varchar) Buyer_Name,
               cast({country} as varchar) Country,
               try_cast({pub} as DATE) Publication_Date,
               try_cast({lean} as DOUBLE) Lean_Fit,
               cast({srcurl} as varchar) Source_URL
        FROM read_parquet({q(tender_path.as_posix())}) t
        ANTI JOIN (
          SELECT distinct Warehouse_Source,Historical_Tender_ID
          FROM read_parquet({q(matched_path.as_posix())})
        ) m USING(Warehouse_Source,Historical_Tender_ID)
      ) TO {q(unmatched.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)
    """)
    unmatched_n=con.execute(f"SELECT count(*) FROM read_parquet({q(unmatched.as_posix())})").fetchone()[0]
    if unmatched_n != total-matched:
        raise SystemExit(f'ANTI_JOIN_COUNT_MISMATCH total={total} matched={matched} unmatched={unmatched_n}')

    # A. Data-native Category/Subcategory cohorts. No ontology assumptions.
    con.execute(f"""
      COPY (
        WITH b AS (
          SELECT Warehouse_Source,
                 coalesce(nullif(trim(Category),''),'UNKNOWN') Category,
                 coalesce(nullif(trim(Subcategory),''),'UNKNOWN') Subcategory,
                 count(*) Tender_Count,
                 count(distinct Buyer_ID) Unique_Buyers,
                 count(distinct Country) Country_Count,
                 median(Lean_Fit) Median_Lean_Fit,
                 avg(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)*100 Recent_12m_Share_Pct,
                 count(distinct date_trunc('year',Publication_Date)) Active_Years
          FROM read_parquet({q(unmatched.as_posix())})
          GROUP BY 1,2,3
        ), x AS (
          SELECT *,
                 100.0*percent_rank() OVER(ORDER BY ln(1+Tender_Count)) Volume_Pct,
                 100.0*percent_rank() OVER(ORDER BY ln(1+Unique_Buyers)) Buyer_Breadth_Pct,
                 100.0*percent_rank() OVER(ORDER BY coalesce(Recent_12m_Share_Pct,0)) Recency_Pct,
                 100.0*percent_rank() OVER(ORDER BY coalesce(Median_Lean_Fit,0)) Lean_Pct
          FROM b WHERE Tender_Count>=10
        )
        SELECT *,
               0.32*Volume_Pct + 0.26*Buyer_Breadth_Pct + 0.18*Recency_Pct + 0.24*Lean_Pct AS Open_World_Score,
               'DATA_NATIVE_COHORT' Discovery_Type
        FROM x
        ORDER BY Open_World_Score DESC,Tender_Count DESC
      ) TO {q((out/'unmatched_category_cohorts.csv').as_posix())} (HEADER)
    """)

    # B. Exact normalized title-pattern recurrence. Numbers/punctuation are stripped so annual IDs do not split a recurring need.
    con.execute(f"""
      COPY (
        WITH z AS (
          SELECT Warehouse_Source,
                 trim(regexp_replace(regexp_replace(lower(strip_accents(Title)),'[0-9]+',' # ','g'),'[^a-z#]+',' ','g')) Title_Pattern,
                 Buyer_ID,Country,Publication_Date,Lean_Fit
          FROM read_parquet({q(unmatched.as_posix())})
          WHERE Title IS NOT NULL AND length(trim(Title))>=8
        ), b AS (
          SELECT Warehouse_Source,Title_Pattern,count(*) Tender_Count,
                 count(distinct Buyer_ID) Unique_Buyers,count(distinct Country) Country_Count,
                 median(Lean_Fit) Median_Lean_Fit,
                 avg(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)*100 Recent_12m_Share_Pct
          FROM z WHERE length(Title_Pattern)>=8 GROUP BY 1,2 HAVING count(*)>=5
        ), x AS (
          SELECT *,
                 100.0*percent_rank() OVER(ORDER BY ln(1+Tender_Count)) Volume_Pct,
                 100.0*percent_rank() OVER(ORDER BY ln(1+Unique_Buyers)) Buyer_Breadth_Pct,
                 100.0*percent_rank() OVER(ORDER BY coalesce(Recent_12m_Share_Pct,0)) Recency_Pct,
                 100.0*percent_rank() OVER(ORDER BY coalesce(Median_Lean_Fit,0)) Lean_Pct
          FROM b
        )
        SELECT *,0.30*Volume_Pct+0.30*Buyer_Breadth_Pct+0.16*Recency_Pct+0.24*Lean_Pct Open_World_Score,
               'NORMALIZED_TITLE_PATTERN' Discovery_Type
        FROM x ORDER BY Open_World_Score DESC,Tender_Count DESC
      ) TO {q((out/'unmatched_title_patterns.csv').as_posix())} (HEADER)
    """)

    # C. Title terms, aggregated source-by-source to bound temporary expansion.
    con.execute("""
      CREATE TEMP TABLE term_parts(
        Term VARCHAR,Warehouse_Source VARCHAR,Tender_Count BIGINT,Unique_Buyers BIGINT,
        Country_Count BIGINT,Recent_Count BIGINT,Lean_Sum DOUBLE,Lean_Known BIGINT
      )
    """)
    sources=[r[0] for r in con.execute(f"SELECT distinct Warehouse_Source FROM read_parquet({q(unmatched.as_posix())}) ORDER BY 1").fetchall()]
    stop_sql=','.join(q(x) for x in sorted(STOPWORDS))
    for src in sources:
        con.execute(f"""
          INSERT INTO term_parts
          WITH src_rows AS (
            SELECT Title,Buyer_ID,Country,Publication_Date,Lean_Fit
            FROM read_parquet({q(unmatched.as_posix())}) WHERE Warehouse_Source={q(src)}
          ), exploded AS (
            SELECT token Term,Buyer_ID,Country,Publication_Date,Lean_Fit
            FROM src_rows,
                 unnest(regexp_extract_all(lower(strip_accents(coalesce(Title,''))),'[a-z][a-z][a-z][a-z]+')) AS u(token)
          )
          SELECT Term,{q(src)},count(*)::BIGINT,count(distinct Buyer_ID)::BIGINT,count(distinct Country)::BIGINT,
                 sum(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)::BIGINT,
                 sum(coalesce(Lean_Fit,0))::DOUBLE,
                 sum(CASE WHEN Lean_Fit IS NOT NULL THEN 1 ELSE 0 END)::BIGINT
          FROM exploded
          WHERE Term NOT IN ({stop_sql})
          GROUP BY Term HAVING count(*)>=5
        """)

    con.execute(f"""
      COPY (
        WITH b AS (
          SELECT Term,sum(Tender_Count) Tender_Mentions,
                 sum(Unique_Buyers) Buyer_Source_Mentions,
                 sum(Country_Count) Country_Source_Mentions,
                 sum(Recent_Count) Recent_Mentions,
                 100.0*sum(Recent_Count)/nullif(sum(Tender_Count),0) Recent_12m_Share_Pct,
                 sum(Lean_Sum)/nullif(sum(Lean_Known),0) Mean_Lean_Fit,
                 count(*) Source_Count
          FROM term_parts GROUP BY Term HAVING sum(Tender_Count)>=20
        ), x AS (
          SELECT *,
                 100.0*percent_rank() OVER(ORDER BY ln(1+Tender_Mentions)) Volume_Pct,
                 100.0*percent_rank() OVER(ORDER BY ln(1+Buyer_Source_Mentions)) Buyer_Breadth_Pct,
                 100.0*percent_rank() OVER(ORDER BY Recent_12m_Share_Pct) Recency_Pct,
                 100.0*percent_rank() OVER(ORDER BY coalesce(Mean_Lean_Fit,0)) Lean_Pct,
                 100.0*percent_rank() OVER(ORDER BY Source_Count) Source_Breadth_Pct
          FROM b
        )
        SELECT *,0.28*Volume_Pct+0.22*Buyer_Breadth_Pct+0.15*Recency_Pct+0.25*Lean_Pct+0.10*Source_Breadth_Pct Open_World_Score,
               'TITLE_TERM' Discovery_Type
        FROM x ORDER BY Open_World_Score DESC,Tender_Mentions DESC
      ) TO {q((out/'unmatched_title_terms.csv').as_posix())} (HEADER)
    """)

    # Representative tender samples for highest-scoring category cohorts and title patterns.
    con.execute(f"""
      COPY (
        WITH topc AS (
          SELECT Warehouse_Source,Category,Subcategory,Open_World_Score
          FROM read_csv_auto({q((out/'unmatched_category_cohorts.csv').as_posix())},header=true)
          WHERE Category<>'UNKNOWN' OR Subcategory<>'UNKNOWN'
          ORDER BY Open_World_Score DESC LIMIT 300
        ), x AS (
          SELECT 'CATEGORY_COHORT' Discovery_Type,c.Open_World_Score,u.*,
                 row_number() OVER(PARTITION BY u.Warehouse_Source,u.Category,u.Subcategory ORDER BY u.Publication_Date DESC NULLS LAST) rn
          FROM read_parquet({q(unmatched.as_posix())}) u JOIN topc c USING(Warehouse_Source,Category,Subcategory)
        )
        SELECT * EXCLUDE(rn) FROM x WHERE rn<=3
        ORDER BY Open_World_Score DESC,Publication_Date DESC
      ) TO {q((out/'representative_unmatched_tenders.csv').as_posix())} (HEADER)
    """)

    # Compact top-candidate union for immediate analyst/LLM review.
    cohorts=list(csv.DictReader(open(out/'unmatched_category_cohorts.csv',encoding='utf-8')))
    patterns=list(csv.DictReader(open(out/'unmatched_title_patterns.csv',encoding='utf-8')))
    terms=list(csv.DictReader(open(out/'unmatched_title_terms.csv',encoding='utf-8')))
    candidates=[]
    for r in cohorts[:1000]:
        candidates.append({'Discovery_Type':'CATEGORY_COHORT','Label':f"{r['Category']} :: {r['Subcategory']}",'Warehouse_Source':r['Warehouse_Source'],'Volume':r['Tender_Count'],'Unique_Buyers':r['Unique_Buyers'],'Countries':r['Country_Count'],'Recent_12m_Share_Pct':r['Recent_12m_Share_Pct'],'Lean_Fit':r['Median_Lean_Fit'],'Open_World_Score':r['Open_World_Score']})
    for r in patterns[:1000]:
        candidates.append({'Discovery_Type':'TITLE_PATTERN','Label':r['Title_Pattern'],'Warehouse_Source':r['Warehouse_Source'],'Volume':r['Tender_Count'],'Unique_Buyers':r['Unique_Buyers'],'Countries':r['Country_Count'],'Recent_12m_Share_Pct':r['Recent_12m_Share_Pct'],'Lean_Fit':r['Median_Lean_Fit'],'Open_World_Score':r['Open_World_Score']})
    for r in terms[:1000]:
        candidates.append({'Discovery_Type':'TITLE_TERM','Label':r['Term'],'Warehouse_Source':'MULTI','Volume':r['Tender_Mentions'],'Unique_Buyers':r['Buyer_Source_Mentions'],'Countries':r['Country_Source_Mentions'],'Recent_12m_Share_Pct':r['Recent_12m_Share_Pct'],'Lean_Fit':r['Mean_Lean_Fit'],'Open_World_Score':r['Open_World_Score']})
    candidates.sort(key=lambda r:float(r['Open_World_Score'] or 0),reverse=True)
    with open(out/'top_open_world_candidates.csv','w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(candidates[0].keys()));w.writeheader();w.writerows(candidates)

    qdata={
      'status':'PASS',
      'generated_at':datetime.now(timezone.utc).isoformat(),
      'source_core_tenders':total,
      'known_spm_matched':matched,
      'open_world_unmatched_tenders':unmatched_n,
      'open_world_share_pct':100.0*unmatched_n/total if total else 0,
      'source_count':len(sources),
      'category_cohorts':len(cohorts),
      'title_patterns':len(patterns),
      'title_terms':len(terms),
      'contract':'OPEN_WORLD_DISCOVERY_V1: no DCE, no fixed SPM ontology used for residual discovery; known SPM matches removed by exact source+tender key'
    }
    (out/'data_quality.json').write_text(json.dumps(qdata,indent=2),encoding='utf-8')

    # Human readout.
    lines=['# SPM Open-World Discovery v1','',f'- Source Core v4 notices: **{total:,}**',f'- Existing SPM matches removed: **{matched:,}**',f'- Residual notices analyzed: **{unmatched_n:,}** ({qdata["open_world_share_pct"]:.2f}%)',f'- Sources represented: **{len(sources)}**',f'- Data-native category cohorts: **{len(cohorts):,}**',f'- Recurring normalized title patterns: **{len(patterns):,}**',f'- High-frequency title terms: **{len(terms):,}**','','## Top 30 open-world candidates','', '|#|Type|Label|Volume|Score|Lean|','|---:|---|---|---:|---:|---:|']
    for i,r in enumerate(candidates[:30],1):
        label=str(r['Label']).replace('|','/')[:90]
        lines.append(f"|{i}|{r['Discovery_Type']}|{label}|{r['Volume']}|{float(r['Open_World_Score']):.1f}|{float(r['Lean_Fit'] or 0):.1f}|")
    lines += ['', '## Interpretation','', 'This is a discovery layer, not a final business ranking. It intentionally searches the previously-unmatched corpus without requiring a predeclared SPM niche. Top clusters should be reviewed, merged into business concepts, then selectively enriched with historical awards/competition before being promoted into live scoring priors. Historical DCE retrieval is not required.']
    (out/'OPEN_WORLD_READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OPEN_WORLD_DISCOVERY_PASS',json.dumps(qdata,sort_keys=True))

if __name__=='__main__':
    main()
