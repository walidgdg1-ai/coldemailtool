#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,json
from datetime import datetime,timezone
from pathlib import Path
import duckdb

STOPWORDS={
 'the','and','for','with','from','into','this','that','these','those','contract','contracts','tender','tenders','procurement','services','service','supply','supplies','provision','framework','agreement','public','project','projects','works','work','notice','lot','lots','call','request','purchase','purchasing','delivery','management','support','maintenance','various','general','annual','new','related','including','other','requirements','requirement',
 'les','des','pour','avec','dans','sur','une','aux','par','marche','marches','accord','cadre','prestation','prestations','fourniture','fournitures','travaux','acquisition','achat','achats','mise','place','realisation','relatif','relative','divers','diverses',
 'und','der','die','das','den','dem','des','fur','mit','von','zur','zum','auftrag','ausschreibung','leistungen','leistung','lieferung','lieferungen','beschaffung','rahmenvertrag','projekt','arbeiten',
 'van','voor','met','het','een','de','en','aan','op','over','diensten','dienst','levering','leveringen','opdracht','aanbesteding','raamovereenkomst','werken','werk',
 'para','con','del','los','las','una','por','servicios','servicio','suministro','contrato','acuerdo','fornitura','servizi','servizio','appalto','accordo','com','dos','das','servicos','servico','fornecimento','contratacao'
}

def q(s): return "'"+str(s).replace("'","''")+"'"

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--core',required=True);ap.add_argument('--matched',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
 out=Path(a.out);out.mkdir(parents=True,exist_ok=True);tmp=out/'ducktmp';tmp.mkdir(exist_ok=True)
 tp=Path(a.core)/'historical_tenders.parquet'; mp=Path(a.matched)
 con=duckdb.connect();con.execute("SET preserve_insertion_order=false");con.execute("SET threads=2");con.execute("SET memory_limit='6GB'");con.execute(f"SET temp_directory={q(tmp.as_posix())}");con.execute("SET max_temp_directory_size='18GB'")
 schema={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(tp.as_posix())})").fetchall()}
 def c(n,f): return f'"{n}"' if n in schema else f
 buyer=c('Buyer_ID','NULL::VARCHAR');country=c('Country',"'UNKNOWN'");cat=c('Category',"'UNKNOWN'");sub=c('Subcategory',"'UNKNOWN'");pub=c('Publication_Date','NULL::DATE');lean=c('Lean_Fit','NULL::DOUBLE')
 total=con.execute(f"select count(*) from read_parquet({q(tp.as_posix())})").fetchone()[0];known=con.execute(f"select count(*) from read_parquet({q(mp.as_posix())})").fetchone()[0]
 u=out/'unmatched_compact.parquet'
 con.execute(f"""COPY (
   SELECT t.Warehouse_Source,t.Historical_Tender_ID,cast(t.Title as varchar) Title,cast({buyer} as varchar) Buyer_ID,
          cast({country} as varchar) Country,cast({cat} as varchar) Category,cast({sub} as varchar) Subcategory,
          try_cast({pub} as date) Publication_Date,try_cast({lean} as double) Lean_Fit
   FROM read_parquet({q(tp.as_posix())}) t
   ANTI JOIN (select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(mp.as_posix())})) m
   USING(Warehouse_Source,Historical_Tender_ID)
 ) TO {q(u.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
 un=con.execute(f"select count(*) from read_parquet({q(u.as_posix())})").fetchone()[0]
 assert un==total-known,(total,known,un)

 # 1) Global category/subcategory cohorts merged across all warehouses.
 con.execute(f"""COPY (
  WITH b AS (
   SELECT coalesce(nullif(trim(Category),''),'UNKNOWN') Category,coalesce(nullif(trim(Subcategory),''),'UNKNOWN') Subcategory,
          count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,count(distinct Warehouse_Source) Source_Count,
          count(distinct Country) Country_Count,median(Lean_Fit) Median_Lean_Fit,
          avg(case when Publication_Date>=DATE '2025-08-01' then 1 else 0 end)*100 Recent_12m_Share_Pct
   FROM read_parquet({q(u.as_posix())}) GROUP BY 1,2 HAVING count(*)>=20
  ),x AS (
   SELECT *,100*percent_rank() over(order by ln(1+Tender_Count)) Volume_Pct,
          100*percent_rank() over(order by ln(1+Unique_Buyers)) Buyer_Breadth_Pct,
          100*percent_rank() over(order by Source_Count) Source_Breadth_Pct,
          100*percent_rank() over(order by coalesce(Recent_12m_Share_Pct,0)) Recency_Pct,
          100*percent_rank() over(order by coalesce(Median_Lean_Fit,0)) Lean_Pct
   FROM b
  )
  SELECT *,0.27*Volume_Pct+0.22*Buyer_Breadth_Pct+0.14*Source_Breadth_Pct+0.15*Recency_Pct+0.22*Lean_Pct Open_World_Score,
         case when (Category='UNKNOWN' or Category='Other') and (Subcategory='UNKNOWN' or Subcategory in ('Services','Fournitures','Travaux')) then 'GENERIC' else 'SPECIFIC' end Specificity
  FROM x ORDER BY Open_World_Score DESC,Tender_Count DESC
 ) TO {q((out/'global_category_cohorts.csv').as_posix())} (HEADER)""")

 # 2) Multi-word phrase discovery, sharded by Warehouse_Source to cap expansion.
 con.execute("""CREATE TEMP TABLE phrase_parts(Phrase VARCHAR,N INTEGER,Warehouse_Source VARCHAR,Title_Mentions BIGINT,Buyer_Mentions BIGINT,Country_Mentions BIGINT,Recent_Mentions BIGINT,Lean_Sum DOUBLE,Lean_Known BIGINT)""")
 sources=[r[0] for r in con.execute(f"select distinct Warehouse_Source from read_parquet({q(u.as_posix())}) order by 1").fetchall()]
 stop=','.join(q(x) for x in sorted(STOPWORDS))
 for src in sources:
  for n in (2,3):
   stop_idx=' and '.join([f"words[i+{j}] not in ({stop})" for j in range(n)])
   phrase_expr=" || ' ' || ".join([f"words[i+{j}]" for j in range(n)])
   con.execute(f"""
    INSERT INTO phrase_parts
    WITH s AS (
      SELECT regexp_extract_all(lower(strip_accents(coalesce(Title,''))),'[a-z][a-z][a-z]+') words,Buyer_ID,Country,Publication_Date,Lean_Fit
      FROM read_parquet({q(u.as_posix())}) WHERE Warehouse_Source={q(src)}
    ), e AS (
      SELECT {phrase_expr} Phrase,Buyer_ID,Country,Publication_Date,Lean_Fit
      FROM s,unnest(range(1,len(words)-{n-1}+1)) rr(i)
      WHERE len(words)>={n} AND {stop_idx}
    )
    SELECT Phrase,{n},{q(src)},count(*)::BIGINT,count(distinct Buyer_ID)::BIGINT,count(distinct Country)::BIGINT,
           sum(case when Publication_Date>=DATE '2025-08-01' then 1 else 0 end)::BIGINT,
           sum(coalesce(Lean_Fit,0))::DOUBLE,sum(case when Lean_Fit is not null then 1 else 0 end)::BIGINT
    FROM e GROUP BY Phrase HAVING count(*)>=5
   """)

 con.execute(f"""COPY (
  WITH b AS (
   SELECT Phrase,N,sum(Title_Mentions) Tender_Mentions,sum(Buyer_Mentions) Buyer_Source_Mentions,
          sum(Country_Mentions) Country_Source_Mentions,count(*) Source_Count,
          100.0*sum(Recent_Mentions)/nullif(sum(Title_Mentions),0) Recent_12m_Share_Pct,
          sum(Lean_Sum)/nullif(sum(Lean_Known),0) Mean_Lean_Fit
   FROM phrase_parts GROUP BY 1,2 HAVING sum(Title_Mentions)>=15
  ),x AS (
   SELECT *,100*percent_rank() over(order by ln(1+Tender_Mentions)) Volume_Pct,
          100*percent_rank() over(order by ln(1+Buyer_Source_Mentions)) Buyer_Breadth_Pct,
          100*percent_rank() over(order by Source_Count) Source_Breadth_Pct,
          100*percent_rank() over(order by Recent_12m_Share_Pct) Recency_Pct,
          100*percent_rank() over(order by coalesce(Mean_Lean_Fit,0)) Lean_Pct
   FROM b
  )
  SELECT *,0.24*Volume_Pct+0.22*Buyer_Breadth_Pct+0.16*Source_Breadth_Pct+0.14*Recency_Pct+0.24*Lean_Pct Open_World_Score
  FROM x ORDER BY Open_World_Score DESC,Tender_Mentions DESC
 ) TO {q((out/'multiword_title_phrases.csv').as_posix())} (HEADER)""")

 # 3) Actionable candidate layer: high-lean specific cohorts + phrases. This is still discovery, not bid advice.
 cohorts=list(csv.DictReader(open(out/'global_category_cohorts.csv',encoding='utf-8')));phr=list(csv.DictReader(open(out/'multiword_title_phrases.csv',encoding='utf-8')))
 rows=[]
 for r in cohorts:
  if r['Specificity']=='SPECIFIC' and float(r['Median_Lean_Fit'] or 0)>=45 and int(r['Tender_Count'])>=50:
   rows.append({'Type':'GLOBAL_COHORT','Label':f"{r['Category']} :: {r['Subcategory']}",'Volume':r['Tender_Count'],'Buyers':r['Unique_Buyers'],'Sources':r['Source_Count'],'Countries':r['Country_Count'],'Lean':r['Median_Lean_Fit'],'Recent':r['Recent_12m_Share_Pct'],'Score':r['Open_World_Score']})
 for r in phr:
  if float(r['Mean_Lean_Fit'] or 0)>=45 and int(r['Tender_Mentions'])>=25:
   rows.append({'Type':f"{r['N']}-GRAM",'Label':r['Phrase'],'Volume':r['Tender_Mentions'],'Buyers':r['Buyer_Source_Mentions'],'Sources':r['Source_Count'],'Countries':r['Country_Source_Mentions'],'Lean':r['Mean_Lean_Fit'],'Recent':r['Recent_12m_Share_Pct'],'Score':r['Open_World_Score']})
 rows.sort(key=lambda x:float(x['Score']),reverse=True)
 with open(out/'top_actionable_open_world_candidates.csv','w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=['Type','Label','Volume','Buyers','Sources','Countries','Lean','Recent','Score']);w.writeheader();w.writerows(rows)

 # 4) Sample tenders for top 150 multi-word phrases, max 3 each, for semantic review.
 top_phr=[r for r in phr if float(r['Mean_Lean_Fit'] or 0)>=45 and int(r['Tender_Mentions'])>=25][:150]
 with open(out/'top_phrase_list.csv','w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=['Phrase','N','Open_World_Score']);w.writeheader();
  for r in top_phr:w.writerow({'Phrase':r['Phrase'],'N':r['N'],'Open_World_Score':r['Open_World_Score']})

 quality={'status':'PASS','generated_at':datetime.now(timezone.utc).isoformat(),'source_core_tenders':total,'known_spm_matched':known,'open_world_unmatched_tenders':un,'source_count':len(sources),'global_category_cohorts':len(cohorts),'multiword_phrases':len(phr),'actionable_candidates':len(rows),'contract':'OPEN_WORLD_DISCOVERY_V2_GLOBAL_MULTIWORD; no DCE; residual corpus only'}
 (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
 lines=['# SPM Open-World Discovery v2','',f'- Residual notices analyzed: **{un:,}**',f'- Sources: **{len(sources)}**',f'- Global category cohorts: **{len(cohorts):,}**',f'- Multi-word recurring phrases: **{len(phr):,}**',f'- Actionable discovery candidates after basic specificity/lean/volume gates: **{len(rows):,}**','','## Top 40 actionable candidates','','|#|Type|Label|Volume|Sources|Lean|Score|','|---:|---|---|---:|---:|---:|---:|']
 for i,r in enumerate(rows[:40],1):lines.append(f"|{i}|{r['Type']}|{r['Label'].replace('|','/')[:100]}|{r['Volume']}|{r['Sources']}|{float(r['Lean']):.1f}|{float(r['Score']):.1f}|")
 lines += ['','These are open-world discovery candidates, not final SPM niches. The next step is semantic consolidation of overlapping phrases/cohorts, followed by targeted award/competition enrichment for the surviving business concepts.']
 (out/'OPEN_WORLD_V2_READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('OPEN_WORLD_V2_PASS',json.dumps(quality,sort_keys=True))
if __name__=='__main__':main()
