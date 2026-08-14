#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
import duckdb
from spm_niche_rules import NICHE_RULES,ENTRY_SIGNAL_PATTERNS,STOPWORDS


def q(s): return "'"+str(s).replace("'","''")+"'"
def ident(s): return '"'+s.replace('"','""')+'"'
def first(cols,cands):
    m={c.lower():c for c in cols}
    for x in cands:
        if x.lower() in m:return m[x.lower()]
    return None

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def main():
    pa=argparse.ArgumentParser();pa.add_argument('--core',required=True);pa.add_argument('--out',required=True);a=pa.parse_args()
    core=Path(a.core);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    tp=core/'historical_tenders.parquet'
    con=duckdb.connect();con.execute("SET preserve_insertion_order=false");con.execute("SET threads=2");con.execute("SET memory_limit='6GB'")
    rows=con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(tp.as_posix())})").fetchall();cols={r[0] for r in rows}
    title=first(cols,['Title','Tender_Title','Notice_Title','Object_Title','Name']); desc=first(cols,['Description','Tender_Description','Short_Description','Description_Text','Purpose','Scope'])
    cat=first(cols,['Category']);subcat=first(cols,['Subcategory']);bid=first(cols,['Buyer_ID']);bname=first(cols,['Buyer_Name']);country=first(cols,['Country']);pub=first(cols,['Publication_Date','Published_Date']);deadline=first(cols,['Deadline','Submission_Deadline']);lean=first(cols,['Lean_Fit','Lean_Fit_Score']);url=first(cols,['Source_URL','URL','Notice_URL']);ref=first(cols,['Source_Notice_ID','Notice_ID','Source_ID','OCID']);currency=first(cols,['Currency','Estimated_Value_Currency']);est=first(cols,['Official_Estimated_Value','Estimated_Value','Tender_Value'])
    if not title:raise SystemExit('NO_TITLE')
    def c(x,fb="NULL"):return ident(x) if x else fb
    parts=[c(title)]+([c(desc)] if desc else [])+([c(cat)] if cat else [])+([c(subcat)] if subcat else [])
    text="lower(concat_ws(' ',"+','.join(f"coalesce(cast({x} as varchar),'')" for x in parts)+'))'
    case='CASE '+' '.join(f"WHEN regexp_matches(Text_Blob,{q(r['pattern'])}) THEN {q(r['niche'])}" for r in NICHE_RULES)+' ELSE NULL END'
    con.execute(f"""CREATE TEMP VIEW base AS SELECT cast(Warehouse_Source as varchar) Warehouse_Source,cast(Historical_Tender_ID as varchar) Historical_Tender_ID,
      cast({c(title)} as varchar) Title,{f'cast({c(desc)} as varchar)' if desc else "''"} Description,{f'cast({c(cat)} as varchar)' if cat else "'UNKNOWN'"} Category,{f'cast({c(subcat)} as varchar)' if subcat else "'UNKNOWN'"} Subcategory,
      {f'cast({c(bid)} as varchar)' if bid else 'NULL'} Buyer_ID,{f'cast({c(bname)} as varchar)' if bname else "'UNKNOWN'"} Buyer_Name,{f'cast({c(country)} as varchar)' if country else "'UNKNOWN'"} Country,
      {f'try_cast({c(pub)} as DATE)' if pub else 'NULL::DATE'} Publication_Date,{f'try_cast({c(deadline)} as DATE)' if deadline else 'NULL::DATE'} Deadline,{f'try_cast({c(lean)} as DOUBLE)' if lean else 'NULL::DOUBLE'} Lean_Fit,
      {f'cast({c(url)} as varchar)' if url else 'NULL'} Source_URL,{f'cast({c(ref)} as varchar)' if ref else 'NULL'} Source_Reference,{f'cast({c(currency)} as varchar)' if currency else "'UNKNOWN'"} Currency,{f'try_cast({c(est)} as DOUBLE)' if est else 'NULL::DOUBLE'} Official_Estimated_Value,{text} Text_Blob
      FROM read_parquet({q(tp.as_posix())})""")
    values=','.join('('+','.join([q(r['niche']),q(r['macro']),str(r['ai']),str(r['subcontract']),str(r['remote']),str(r['low_entry']),str(r['low_pain']),str(r['margin'])])+')' for r in NICHE_RULES)
    con.execute("CREATE TEMP TABLE rules(Niche VARCHAR,Macro_Category VARCHAR,AI_Leverage DOUBLE,Subcontractability DOUBLE,Remote_Feasibility DOUBLE,Low_Entry_Burden DOUBLE,Low_Execution_Pain DOUBLE,Margin_Potential DOUBLE)");con.execute('INSERT INTO rules VALUES '+values)
    con.execute(f"""COPY (WITH x AS(SELECT *,{case} Niche FROM base) SELECT x.*,r.* EXCLUDE(Niche) FROM x JOIN rules r USING(Niche)) TO {q((out/'matched_tenders.parquet').as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    mp=out/'matched_tenders.parquet'
    total=con.execute(f"SELECT count(*) FROM read_parquet({q(tp.as_posix())})").fetchone()[0];matched=con.execute(f"SELECT count(*) FROM read_parquet({q(mp.as_posix())})").fetchone()[0]
    con.execute(f"""CREATE TEMP VIEW buyer_niche AS SELECT Niche,Macro_Category,Warehouse_Source,Country,Buyer_ID,any_value(Buyer_Name) Buyer_Name,count(*) Tender_Count,min(Publication_Date) First_Date,max(Publication_Date) Last_Date,count(distinct date_trunc('year',Publication_Date)) Active_Years FROM read_parquet({q(mp.as_posix())}) WHERE Buyer_ID IS NOT NULL GROUP BY 1,2,3,4,5""")
    con.execute(f"COPY (SELECT *,date_diff('day',First_Date,Last_Date) Active_Span_Days FROM buyer_niche WHERE Tender_Count>=3 ORDER BY Tender_Count DESC,Last_Date DESC) TO {q((out/'recurring_buyers_by_niche.csv').as_posix())} (HEADER)")
    con.execute(f"""CREATE TEMP VIEW profile AS WITH t AS(SELECT Niche,any_value(Macro_Category) Macro_Category,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count,median(Lean_Fit) Median_Lean_Fit,avg(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)*100 Recent_12m_Share_Pct,any_value(AI_Leverage) AI_Leverage,any_value(Subcontractability) Subcontractability,any_value(Remote_Feasibility) Remote_Feasibility,any_value(Low_Entry_Burden) Low_Entry_Burden,any_value(Low_Execution_Pain) Low_Execution_Pain,any_value(Margin_Potential) Margin_Potential FROM read_parquet({q(mp.as_posix())}) GROUP BY 1),r AS(SELECT Niche,sum(Tender_Count) Repeat_Tenders,count(*) Repeat_Buyers FROM buyer_niche WHERE Tender_Count>=3 GROUP BY 1) SELECT t.*,coalesce(r.Repeat_Tenders,0) Repeat_Tenders,coalesce(r.Repeat_Buyers,0) Repeat_Buyers,100.0*coalesce(r.Repeat_Tenders,0)/t.Tender_Count Repeat_Tender_Share_Pct FROM t LEFT JOIN r USING(Niche)""")
    con.execute(f"""COPY (WITH p AS(SELECT *,percent_rank() OVER(ORDER BY log(1+Tender_Count)) Volume_Pct,percent_rank() OVER(ORDER BY log(1+Unique_Buyers)) Buyer_Breadth_Pct,percent_rank() OVER(ORDER BY Repeat_Tender_Share_Pct) Repeat_Pct,percent_rank() OVER(ORDER BY coalesce(Recent_12m_Share_Pct,0)) Recency_Pct,percent_rank() OVER(ORDER BY coalesce(Median_Lean_Fit,0)) Lean_Pct FROM profile),s AS(SELECT *,100*(0.18*Volume_Pct+0.16*Buyer_Breadth_Pct+0.16*Repeat_Pct+0.10*Recency_Pct+0.10*Lean_Pct+0.30*(0.25*AI_Leverage+0.25*Subcontractability+0.15*Remote_Feasibility+0.15*Low_Entry_Burden+0.10*Low_Execution_Pain+0.10*Margin_Potential)) Discovery_Score,100*(0.35*Low_Entry_Burden+0.25*Low_Execution_Pain+0.15*Remote_Feasibility+0.15*Subcontractability+0.10*Repeat_Pct) Easy_Money_Proxy,100*(0.45*AI_Leverage+0.20*Volume_Pct+0.15*Buyer_Breadth_Pct+0.10*Repeat_Pct+0.10*Margin_Potential) AI_Leverage_Score,100*(0.40*Subcontractability+0.25*Margin_Potential+0.15*Low_Entry_Burden+0.10*Repeat_Pct+0.10*Buyer_Breadth_Pct) Middleman_Proxy FROM p) SELECT *,'TENDER_ONLY_DISCOVERY_70_EMPIRICAL_30_HEURISTIC' Score_Contract,'DERIVED' Derived_Status FROM s WHERE Tender_Count>=5 ORDER BY Discovery_Score DESC) TO {q((out/'spm_discovery_matrix.csv').as_posix())} (HEADER)""")
    matrix=out/'spm_discovery_matrix.csv'
    for name,col,n in [('top50_discovery.csv','Discovery_Score',50),('top20_easy_money_proxy.csv','Easy_Money_Proxy',20),('top20_ai_leverage.csv','AI_Leverage_Score',20),('top20_middleman_proxy.csv','Middleman_Proxy',20)]:con.execute(f"COPY (SELECT * FROM read_csv_auto({q(matrix.as_posix())},header=true) ORDER BY {col} DESC,Tender_Count DESC LIMIT {n}) TO {q((out/name).as_posix())} (HEADER)")
    sig=[]
    for name,pat in ENTRY_SIGNAL_PATTERNS.items():sig.append(f"avg(CASE WHEN regexp_matches(Text_Blob,{q(pat)}) THEN 1 ELSE 0 END)*100 {ident(name+'_mention_pct')}")
    con.execute(f"COPY (SELECT Niche,count(*) Tender_Count,{','.join(sig)} FROM read_parquet({q(mp.as_posix())}) GROUP BY 1 ORDER BY Tender_Count DESC) TO {q((out/'entry_signal_mentions.csv').as_posix())} (HEADER)")
    con.execute(f"COPY (SELECT Niche,extract(month from Publication_Date) Calendar_Month,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers FROM read_parquet({q(mp.as_posix())}) WHERE Publication_Date IS NOT NULL GROUP BY 1,2 ORDER BY 1,2) TO {q((out/'seasonality_by_niche.csv').as_posix())} (HEADER)")
    con.execute(f"COPY (SELECT Niche,Warehouse_Source,Country,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,median(Lean_Fit) Median_Lean_Fit FROM read_parquet({q(mp.as_posix())}) GROUP BY 1,2,3 ORDER BY Tender_Count DESC) TO {q((out/'country_niche_fit.csv').as_posix())} (HEADER)")
    con.execute(f"""COPY (WITH topn AS(SELECT Niche FROM read_csv_auto({q(matrix.as_posix())},header=true) ORDER BY Discovery_Score DESC LIMIT 50),x AS(SELECT m.Niche,m.Macro_Category,m.Historical_Tender_ID,m.Title,m.Buyer_ID,m.Buyer_Name,m.Country,m.Warehouse_Source,m.Publication_Date,m.Deadline,m.Category,m.Subcategory,m.Currency,m.Official_Estimated_Value,m.Source_URL,m.Source_Reference,row_number() OVER(PARTITION BY m.Niche ORDER BY m.Publication_Date DESC NULLS LAST,m.Historical_Tender_ID) rn FROM read_parquet({q(mp.as_posix())}) m JOIN topn USING(Niche)) SELECT * EXCLUDE(rn) FROM x WHERE rn<=12 ORDER BY Niche,Publication_Date DESC) TO {q((out/'representative_tenders.csv').as_posix())} (HEADER)""")
    # Data-discovered Category/Subcategory cohorts, no manual ontology required.
    con.execute(f"""COPY (WITH t AS(SELECT coalesce(nullif(Category,''),'UNKNOWN') Category,coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count,median(Lean_Fit) Median_Lean_Fit,avg(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)*100 Recent_12m_Share_Pct FROM base GROUP BY 1,2),b AS(SELECT coalesce(nullif(Category,''),'UNKNOWN') Category,coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,Buyer_ID,count(*) Tender_Count FROM base WHERE Buyer_ID IS NOT NULL GROUP BY 1,2,3),r AS(SELECT Category,Subcategory,sum(Tender_Count) Repeat_Tenders FROM b WHERE Tender_Count>=3 GROUP BY 1,2),j AS(SELECT t.*,coalesce(r.Repeat_Tenders,0) Repeat_Tenders,100.0*coalesce(r.Repeat_Tenders,0)/t.Tender_Count Repeat_Tender_Share_Pct,percent_rank() OVER(ORDER BY log(1+t.Tender_Count)) Volume_Pct,percent_rank() OVER(ORDER BY log(1+t.Unique_Buyers)) Buyer_Pct,percent_rank() OVER(ORDER BY coalesce(t.Median_Lean_Fit,0)) Lean_Pct FROM t LEFT JOIN r USING(Category,Subcategory)) SELECT *,100*(0.24*Volume_Pct+0.22*Buyer_Pct+0.24*least(1.0,Repeat_Tender_Share_Pct/70.0)+0.18*Lean_Pct+0.12*least(1.0,Recent_12m_Share_Pct/45.0)) Empirical_Discovery_Score,'DERIVED_EMPIRICAL' Derived_Status FROM j WHERE Tender_Count>=10 ORDER BY Empirical_Discovery_Score DESC) TO {q((out/'data_discovered_cohorts.csv').as_posix())} (HEADER)""")
    # Unmatched high-lean terms are candidate prompts for manual hidden-gem review.
    broad='|'.join('(?:'+r['pattern']+')' for r in NICHE_RULES);stop=','.join(q(x) for x in STOPWORDS)
    con.execute(f"""COPY (WITH u AS(SELECT regexp_extract_all(lower(Title),'[a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ0-9-]{{3,}}') toks FROM base WHERE coalesce(Lean_Fit,0)>=0.45 AND NOT regexp_matches(Text_Blob,{q(broad)})),terms AS(SELECT unnest(toks) Term FROM u) SELECT Term,count(*) Title_Count FROM terms WHERE Term NOT IN ({stop}) AND length(Term)>=4 GROUP BY 1 HAVING count(*)>=20 ORDER BY Title_Count DESC LIMIT 1000) TO {q((out/'unmatched_high_lean_title_terms.csv').as_posix())} (HEADER)""")
    # QA
    nrows=con.execute(f"SELECT count(*) FROM read_csv_auto({q(matrix.as_posix())},header=true)").fetchone()[0]
    qa={'version':'SPM_TENDER_DISCOVERY_V1','created_at':datetime.now(timezone.utc).isoformat(),'source_core':'tender-normalized-global-core-v4','source_tenders':total,'matched_tenders':matched,'match_rate_pct':100*matched/total,'matrix_niches':nrows,'status':'PASS' if total==2250547 and matched>0 and nrows>=10 else 'FAIL','scope':'Tender-only full-corpus discovery. Award values, bidder competition and supplier fragmentation are intentionally deferred to targeted evidence drills on shortlisted niches.','checks':{'source_count_exact':total==2250547,'matched_positive':matched>0,'matrix_positive':nrows>=10}}
    (out/'data_quality.json').write_text(json.dumps(qa,indent=2),encoding='utf-8')
    top=con.execute(f"SELECT Niche,Macro_Category,Tender_Count,Unique_Buyers,Repeat_Tender_Share_Pct,Recent_12m_Share_Pct,Median_Lean_Fit,Discovery_Score FROM read_csv_auto({q(matrix.as_posix())},header=true) ORDER BY Discovery_Score DESC LIMIT 20").fetchall()
    md=['# SPM Tender Discovery v1','',f'- Full Core v4 scan: **{total:,} tenders**.',f'- Matched SPM ontology: **{matched:,}** ({100*matched/total:.2f}%).',f'- Ranked niches: **{nrows}**.','- This stage intentionally excludes award-price, bidder and supplier metrics; those are targeted next on shortlisted niches.','','## Top 20 tender-only discovery signals','','|#|Niche|Tenders|Buyers|Repeat share|Recent 12m|Lean fit|Discovery|','|---:|---|---:|---:|---:|---:|---:|---:|']
    for i,r in enumerate(top,1):md.append(f'|{i}|{r[0]}|{int(r[2]):,}|{int(r[3]):,}|{r[4]:.1f}%|{r[5]:.1f}%|{r[6] if r[6] is not None else "UNKNOWN"}|{r[7]:.1f}|')
    (out/'READOUT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    man={'version':qa['version'],'files':{}}
    for p in out.iterdir():
        if p.is_file():man['files'][p.name]={'bytes':p.stat().st_size,'sha256':sha(p)}
    (out/'run_manifest.json').write_text(json.dumps(man,indent=2),encoding='utf-8')
    print(json.dumps(qa,indent=2))
if __name__=='__main__':main()
