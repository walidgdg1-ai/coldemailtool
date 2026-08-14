#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
import duckdb
from spm_niche_rules import NICHE_RULES, ENTRY_SIGNAL_PATTERNS

def q(s): return "'"+str(s).replace("'","''")+"'"
def ident(s): return '"'+s.replace('"','""')+'"'
def first(cols,cands):
    low={c.lower():c for c in cols}
    for x in cands:
        if x.lower() in low:return low[x.lower()]
    return None

def main():
    z=argparse.ArgumentParser();z.add_argument('--core',required=True);z.add_argument('--out',required=True);a=z.parse_args();core=Path(a.core);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);tmp=out/'tmp';tmp.mkdir(exist_ok=True)
    con=duckdb.connect();con.execute('SET preserve_insertion_order=false');con.execute('SET threads=2');con.execute("SET memory_limit='6GB'");con.execute(f"SET temp_directory={q(tmp.as_posix())}");con.execute("SET max_temp_directory_size='20GB'")
    tp=core/'historical_tenders.parquet';ap=core/'awards.parquet';bp=core/'award_suppliers.parquet'
    def cols(p):return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(p.as_posix())})").fetchall()}
    tc=cols(tp);ac=cols(ap);bc=cols(bp)
    title=first(tc,['Title','Tender_Title','Notice_Title','Object_Title','Name']);desc=first(tc,['Description','Tender_Description','Short_Description','Description_Text','Purpose','Scope']);cat=first(tc,['Category']);sub=first(tc,['Subcategory']);buyerid=first(tc,['Buyer_ID']);buyer=first(tc,['Buyer_Name']);country=first(tc,['Country']);pub=first(tc,['Publication_Date','Published_Date','Date_Published']);deadline=first(tc,['Deadline','Submission_Deadline','Tender_Deadline']);cur=first(tc,['Currency','Estimated_Value_Currency']);est=first(tc,['Official_Estimated_Value','Estimated_Value','Tender_Value']);lean=first(tc,['Lean_Fit','Lean_Fit_Score']);url=first(tc,['Source_URL','URL','Notice_URL','Source_Notice_URL','Tender_URL']);ref=first(tc,['Source_Notice_ID','Notice_ID','Source_ID','OCID'])
    def ex(c,cast='varchar',fallback='NULL'):
        return f"cast({ident(c)} as {cast})" if c else fallback
    parts=[ident(x) for x in [title,desc,cat,sub] if x];text="lower(concat_ws(' ',"+','.join(f"coalesce(cast({x} as varchar),'')" for x in parts)+'))'
    case='CASE '+' '.join(f"WHEN regexp_matches(Text_Blob,{q(r['pattern'])}) THEN {q(r['niche'])}" for r in NICHE_RULES)+' ELSE NULL END'
    con.execute('CREATE TEMP TABLE rules(Niche VARCHAR, Macro_Category VARCHAR, AI DOUBLE, Subcontract DOUBLE, Remote DOUBLE, LowEntry DOUBLE, LowPain DOUBLE, Margin DOUBLE)')
    con.executemany('INSERT INTO rules VALUES (?,?,?,?,?,?,?,?)',[(r['niche'],r['macro'],r['ai'],r['subcontract'],r['remote'],r['low_entry'],r['low_pain'],r['margin']) for r in NICHE_RULES])
    con.execute(f"""COPY (WITH b AS (SELECT cast(Warehouse_Source AS varchar) Warehouse_Source,cast(Historical_Tender_ID AS varchar) Historical_Tender_ID,{ex(title)} Title,{ex(desc)} Description,{ex(cat)} Category,{ex(sub)} Subcategory,{ex(buyerid)} Buyer_ID,{ex(buyer)} Buyer_Name,{ex(country)} Country,{ex(pub,'DATE')} Publication_Date,{ex(deadline,'DATE')} Deadline,{ex(cur)} Currency,{ex(est,'DOUBLE')} Official_Estimated_Value,{ex(lean,'DOUBLE')} Lean_Fit,{ex(url)} Source_URL,{ex(ref)} Source_Reference,{text} Text_Blob FROM read_parquet({q(tp.as_posix())})), c AS (SELECT *,{case} Niche FROM b) SELECT c.*,r.Macro_Category,r.AI,r.Subcontract,r.Remote,r.LowEntry,r.LowPain,r.Margin FROM c JOIN rules r USING(Niche)) TO {q((out/'matched.parquet').as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    mp=out/'matched.parquet';total=con.execute(f"SELECT count(*) FROM read_parquet({q(tp.as_posix())})").fetchone()[0];matched=con.execute(f"SELECT count(*) FROM read_parquet({q(mp.as_posix())})").fetchone()[0]
    con.execute(f"CREATE TEMP TABLE tprof AS SELECT Niche,any_value(Macro_Category) Macro_Category,count(*) Tender_Count,count(distinct Buyer_ID) Buyer_Count,count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count,median(Lean_Fit) Median_Lean_Fit,avg((Publication_Date>=DATE '2025-08-01')::INT) Recent12mShare,any_value(AI) AI,any_value(Subcontract) Subcontract,any_value(Remote) Remote,any_value(LowEntry) LowEntry,any_value(LowPain) LowPain,any_value(Margin) Margin,min(Publication_Date) First_Date,max(Publication_Date) Last_Date FROM read_parquet({q(mp.as_posix())}) GROUP BY Niche")
    con.execute(f"CREATE TEMP TABLE brep AS WITH x AS (SELECT Niche,Buyer_ID,count(*) n FROM read_parquet({q(mp.as_posix())}) WHERE Buyer_ID IS NOT NULL GROUP BY 1,2) SELECT Niche,count(*) Buyers,sum((n>=2)::INT) Repeat2,sum((n>=3)::INT) Repeat3,avg((n>=2)::INT) RepeatShare FROM x GROUP BY 1")
    av=first(ac,['Award_Value','Official_Award_Value','Value']);ab=first(ac,['Bidder_Count','Number_Of_Offers','NumberOfTenderers']);acu=first(ac,['Currency','Award_Currency','Value_Currency']);aid=first(ac,['Award_ID']);at=first(ac,['Historical_Tender_ID'])
    aval=f"try_cast({ident(av)} AS DOUBLE)" if av else 'NULL::DOUBLE';abid=f"try_cast({ident(ab)} AS DOUBLE)" if ab else 'NULL::DOUBLE';acur=f"cast({ident(acu)} AS varchar)" if acu else 'NULL'
    con.execute(f"CREATE TEMP VIEW abase AS SELECT cast(Warehouse_Source AS varchar) Warehouse_Source,cast({ident(at)} AS varchar) Historical_Tender_ID,cast({ident(aid)} AS varchar) Award_ID,{aval} Award_Value,{abid} Bidder_Count,{acur} Award_Currency FROM read_parquet({q(ap.as_posix())})")
    con.execute(f"CREATE TEMP TABLE aprof AS SELECT m.Niche,count(*) Award_Rows,sum((a.Award_Value IS NOT NULL)::INT) KnownValueRows,sum((a.Bidder_Count IS NOT NULL)::INT) KnownBidderRows,avg((a.Bidder_Count IS NOT NULL)::INT) BidderCoverage,median(a.Bidder_Count) MedianBidders,avg(CASE WHEN a.Bidder_Count IS NOT NULL THEN (a.Bidder_Count=1)::INT ELSE NULL END) SingleBidShare FROM read_parquet({q(mp.as_posix())}) m JOIN abase a USING(Warehouse_Source,Historical_Tender_ID) GROUP BY m.Niche")
    con.execute(f"COPY (SELECT m.Niche,m.Warehouse_Source,m.Country,coalesce(a.Award_Currency,m.Currency,'UNKNOWN') Currency,count(*) Known_Value_Awards,approx_quantile(a.Award_Value,.10) P10,approx_quantile(a.Award_Value,.25) P25,approx_quantile(a.Award_Value,.50) Median,approx_quantile(a.Award_Value,.75) P75,approx_quantile(a.Award_Value,.90) P90,sum(a.Award_Value) Known_Value_Total FROM read_parquet({q(mp.as_posix())}) m JOIN abase a USING(Warehouse_Source,Historical_Tender_ID) WHERE a.Award_Value>0 GROUP BY 1,2,3,4 HAVING count(*)>=5 ORDER BY 1,2,3,4) TO {q((out/'price_quantiles.csv').as_posix())} (HEADER)")
    con.execute(f"COPY (SELECT m.Niche,m.Warehouse_Source,m.Country,count(*) Award_Rows,sum((a.Bidder_Count IS NOT NULL)::INT) Known_Bidder_Rows,avg((a.Bidder_Count IS NOT NULL)::INT) Bidder_Coverage,approx_quantile(a.Bidder_Count,.25) P25,approx_quantile(a.Bidder_Count,.50) Median,approx_quantile(a.Bidder_Count,.75) P75,avg(CASE WHEN a.Bidder_Count IS NOT NULL THEN (a.Bidder_Count=1)::INT ELSE NULL END) Single_Bid_Share FROM read_parquet({q(mp.as_posix())}) m JOIN abase a USING(Warehouse_Source,Historical_Tender_ID) GROUP BY 1,2,3 HAVING count(*)>=5 ORDER BY 1,2,3) TO {q((out/'competition.csv').as_posix())} (HEADER)")
    # Entry-signal mention rates from available title+description text only; absence != no requirement.
    ents=[]
    for name,pat in ENTRY_SIGNAL_PATTERNS.items():ents.append(f"avg(regexp_matches(Text_Blob,{q(pat)})::INT) {ident(name+'_mention_rate')}")
    if ents:con.execute(f"COPY (SELECT Niche,count(*) Tender_Count,{','.join(ents)} FROM read_parquet({q(mp.as_posix())}) GROUP BY 1 ORDER BY Tender_Count DESC) TO {q((out/'entry_signals.csv').as_posix())} (HEADER)")
    # Score empirical components with neutral competition/value if evidence coverage weak.
    con.execute("""CREATE TEMP TABLE score AS WITH x AS (SELECT t.*,coalesce(b.RepeatShare,0) RepeatShare,coalesce(a.Award_Rows,0) Award_Rows,coalesce(a.KnownValueRows,0) KnownValueRows,coalesce(a.KnownBidderRows,0) KnownBidderRows,a.BidderCoverage,a.MedianBidders,a.SingleBidShare FROM tprof t LEFT JOIN brep b USING(Niche) LEFT JOIN aprof a USING(Niche)), mx AS (SELECT max(Tender_Count) mt,max(Buyer_Count) mb FROM x) SELECT x.*,
      ln(1+Tender_Count)/ln(1+mt) VolumeC,ln(1+Buyer_Count)/ln(1+mb) BuyerC,
      least(1.0,RepeatShare*2) RepeatC,
      CASE WHEN BidderCoverage>=.30 AND KnownBidderRows>=10 THEN greatest(0.0,least(1.0,(6-coalesce(MedianBidders,6))/5)) ELSE .5 END CompetitionC,
      CASE WHEN KnownValueRows>=20 THEN .70 ELSE .5 END ValueEvidenceC,
      greatest(0.0,least(1.0,(coalesce(Median_Lean_Fit,50))/100.0)) LeanC,
      (.25*AI+.25*Subcontract+.15*Remote+.15*LowEntry+.10*LowPain+.10*Margin) StrategicC
      FROM x,mx""")
    # No supplier concentration in FAST layer: neutral .5, explicit in output.
    con.execute("""COPY (SELECT *,round(100*(.15*VolumeC+.12*BuyerC+.16*RepeatC+.12*.5+.10*CompetitionC+.08*ValueEvidenceC+.07*Recent12mShare+.05*LeanC+.15*StrategicC),2) SPM_Fast_Evidence_Score,round(100*(.22*LowEntry+.20*Remote+.17*LowPain+.12*Subcontract+.10*CompetitionC+.08*LeanC+.06*RepeatC+.05*StrategicC),2) Easiest_Score,round(100*(.25*AI+.18*LowPain+.17*Remote+.15*Margin+.10*VolumeC+.08*RepeatC+.07*LowEntry),2) AI_Score,round(100*(.30*Subcontract+.20*LowPain+.17*Margin+.12*VolumeC+.10*BuyerC+.06*RepeatC+.05*.5),2) Middleman_Score,round(Tender_Count*greatest(0.05,least(.85,.15+.55*StrategicC+.20*RepeatC-.10*(1-LowEntry)))) Model_Biddable_Like_Historical_Count,greatest(1.0,date_diff('day',First_Date,Last_Date)/365.25) Observed_Years FROM score ORDER BY SPM_Fast_Evidence_Score DESC) TO {q((out/'fast_matrix.csv').as_posix())} (HEADER)")
    con.execute(f"COPY (SELECT Niche,Macro_Category,Warehouse_Source,Country,Buyer_ID,any_value(Buyer_Name) Buyer_Name,count(*) Tender_Count,min(Publication_Date) First_Date,max(Publication_Date) Last_Date,count(distinct year(Publication_Date)) Active_Years FROM read_parquet({q(mp.as_posix())}) WHERE Buyer_ID IS NOT NULL GROUP BY 1,2,3,4,5 HAVING count(*)>=2 ORDER BY Tender_Count DESC LIMIT 500) TO {q((out/'repeat_buyers.csv').as_posix())} (HEADER)")
    # Representative examples: prioritize rows with observed award value / bidder evidence and source URL.
    con.execute(f"COPY (WITH z AS (SELECT m.Niche,m.Historical_Tender_ID,m.Title,m.Buyer_Name,m.Country,m.Publication_Date,m.Deadline,m.Category,m.Subcategory,m.Official_Estimated_Value,m.Currency,m.Source_URL,m.Source_Reference,m.Warehouse_Source,a.Award_ID,a.Award_Value,a.Award_Currency,a.Bidder_Count,row_number() OVER(PARTITION BY m.Niche ORDER BY ((a.Award_Value IS NOT NULL)::INT*3+(a.Bidder_Count IS NOT NULL)::INT*2+(m.Source_URL IS NOT NULL)::INT*2+(m.Deadline IS NOT NULL)::INT) DESC,m.Publication_Date DESC NULLS LAST) rn FROM read_parquet({q(mp.as_posix())}) m LEFT JOIN abase a USING(Warehouse_Source,Historical_Tender_ID)) SELECT * EXCLUDE(rn) FROM z WHERE rn<=5 ORDER BY Niche,Publication_Date DESC) TO {q((out/'representative.csv').as_posix())} (HEADER)")
    d={'status':'PASS','core_total_tenders':total,'matched_tenders':matched,'matched_pct':round(matched/total*100,2),'supplier_fragmentation':'NOT_COMPUTED_IN_FAST_LAYER_NEUTRAL_0.5','biddable_like':'MODEL_ONLY_NOT_LEGAL_ELIGIBILITY','unknown_policy':'UNKNOWN_NEVER_ZERO','currency_policy':'SEPARATE'}; (out/'qa.json').write_text(json.dumps(d,indent=2));print('FAST_QA',json.dumps(d))
if __name__=='__main__':main()
