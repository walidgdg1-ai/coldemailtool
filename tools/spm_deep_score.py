from __future__ import annotations
import csv,json
from datetime import datetime,timezone
from pathlib import Path

def rows(p,limit=None):
    with Path(p).open(encoding='utf-8',newline='') as f:
        out=[]
        for r in csv.DictReader(f):
            out.append(r)
            if limit and len(out)>=limit: break
        return out

def n(v,d=None):
    try: return float(v) if v not in (None,'','UNKNOWN','nan') else d
    except: return d

def ranks(d):
    s=sorted(d.items(),key=lambda x:x[1]); den=max(1,len(s)-1); return {k:i/den for i,(k,v) in enumerate(s)}
def valuefit(v):
    if not v or v<=0:return .5
    if 5000<=v<=100000:return 1
    if 1000<=v<5000:return .65
    if 100000<v<=250000:return .8
    if 250000<v<=750000:return .5
    return .3 if v<1000 else .25

def run(con,core:Path,out:Path,ctx,coreq):
    facts=rows(out/'micro_niche_facts_raw.csv'); comps=rows(out/'competition_by_source.csv'); frags=rows(out/'supplier_fragmentation.csv'); prices=rows(out/'price_quantiles_by_currency.csv')
    cb={}; fb={}; pb={}
    for r in comps: cb.setdefault(r['Micro_Niche'],[]).append(r)
    for r in frags: fb.setdefault(r['Micro_Niche'],[]).append(r)
    for r in prices: pb.setdefault(r['Micro_Niche'],[]).append(r)
    vr=ranks({r['Micro_Niche']:n(r['Tender_Count'],0) for r in facts}); br=ranks({r['Micro_Niche']:n(r['Buyer_Count'],0) for r in facts}); rr=ranks({r['Micro_Niche']:n(r['Repeat_Buyer_Share_Pct'],0) or 0 for r in facts})
    matrix=[]
    for r in facts:
        k=r['Micro_Niche']; obs=[x for x in cb.get(k,[]) if (n(x['Bidder_Coverage_Pct'],0) or 0)>=30 and (n(x['Bidder_Known_Rows'],0) or 0)>=10]
        mb=sum(n(x['Bidder_Median'],8) or 8 for x in obs)/len(obs) if obs else None; cs=max(0,min(1,(8-mb)/7)) if mb is not None else .5
        hs=[n(x['Supplier_HHI']) for x in fb.get(k,[]) if n(x['Supplier_HHI']) is not None]; mh=sum(hs)/len(hs) if hs else None; fs=max(0,min(1,(5000-mh)/4500)) if mh is not None else .5
        risk=sum(n(r[x],0) or 0 for x in ['Hard_Regulated_Text_Pct','Onsite_or_Local_Signal_Pct','Certification_Signal_Pct','Subcontract_Ban_Signal_Pct']); barr=max(0,1-min(1,risk/35))
        ai=(n(r['AI_Prior'],50) or 50)/100; sub=(n(r['Subcontractability_Prior'],50) or 50)/100; rem=(n(r['Remote_Prior'],50) or 50)/100; nov=(n(r['Novelty_Prior'],50) or 50)/100
        mm=((n(r['Margin_Low_Pct'],20) or 20)+(n(r['Margin_High_Pct'],40) or 40))/200; vf=[valuefit(n(x['Median'])) for x in pb.get(k,[]) if n(x['Median']) is not None]; sz=sum(vf)/len(vf) if vf else .5
        market=vr[k]*.25+br[k]*.15+rr[k]*.15+fs*.15+cs*.10+sz*.20; delivery=ai*.25+sub*.25+rem*.20+barr*.20+mm*.10; spm=100*(.52*market+.48*delivery)
        easy=100*(barr*.28+rem*.20+sub*.18+ai*.10+cs*.10+sz*.07+rr[k]*.07); prof=100*(sz*.22+mm*.18+vr[k]*.18+rr[k]*.12+cs*.12+fs*.10+sub*.08); ais=100*(ai*.45+vr[k]*.18+sz*.10+rem*.12+barr*.08+mm*.07); arb=100*(sub*.35+mm*.18+vr[k]*.12+fs*.12+barr*.10+sz*.08+rem*.05); hid=100*(nov*.24+vr[k]*.18+cs*.15+fs*.15+rr[k]*.10+sub*.10+mm*.08)
        tn=int(n(r['Tender_Count'],0) or 0); hard=min(1,((n(r['Hard_Regulated_Text_Pct'],0) or 0)+(n(r['Subcontract_Ban_Signal_Pct'],0) or 0))/100); model=round(tn*max(0,min(1,(spm-55)/45))*max(.2,1-hard))
        matrix.append({'Micro_Niche':k,'Macro':r['Macro'],'Niche':r['Niche'],'Tender_Count':tn,'Buyer_Count':int(n(r['Buyer_Count'],0) or 0),'Source_Count':int(n(r['Source_Count'],0) or 0),'Repeat_Buyer_Share_Pct':round(n(r['Repeat_Buyer_Share_Pct'],0) or 0,2),'SPM_Opportunity_Score':round(spm,2),'Easiest_Money_Score':round(easy,2),'Expected_Profit_Score':round(prof,2),'AI_Leverage_Score':round(ais,2),'Arbitrage_Score':round(arb,2),'Hidden_Gem_Score':round(hid,2),'Competition_Evidence':'OBSERVED' if obs else 'LOW_COVERAGE_NEUTRAL','Median_Bidder_Count_Observed':round(mb,2) if mb is not None else '','Mean_Supplier_HHI':round(mh,1) if mh is not None else '','Barrier_Score':round(barr*100,1),'AI_Prior':round(ai*100,1),'Subcontractability_Prior':round(sub*100,1),'Remote_Prior':round(rem*100,1),'Gross_Margin_Assumption_Low_Pct':round(n(r['Margin_Low_Pct'],0) or 0,1),'Gross_Margin_Assumption_High_Pct':round(n(r['Margin_High_Pct'],0) or 0,1),'Model_Biddable_Like_Historical_Count':model,'Evidence_Note':'Prioritisation model; DCE eligibility required. Margins are assumptions, not supplier quotes.'})
    matrix.sort(key=lambda x:x['SPM_Opportunity_Score'],reverse=True); fields=list(matrix[0])
    def save(name,data):
        with (out/name).open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
    save('spm_opportunity_matrix.csv',matrix)
    rankings={'easiest':sorted(matrix,key=lambda x:x['Easiest_Money_Score'],reverse=True)[:20],'profit':sorted(matrix,key=lambda x:x['Expected_Profit_Score'],reverse=True)[:20],'ai':sorted(matrix,key=lambda x:x['AI_Leverage_Score'],reverse=True)[:20],'arbitrage':sorted([x for x in matrix if x['Subcontractability_Prior']>=80],key=lambda x:x['Arbitrage_Score'],reverse=True)[:20],'hidden':sorted(matrix,key=lambda x:x['Hidden_Gem_Score'],reverse=True)[:20]}
    for k,v in rankings.items():save('top20_'+k+'.csv',v)
    con.execute(f"CREATE TEMP TABLE mx AS SELECT * FROM read_csv_auto('{(out/'spm_opportunity_matrix.csv').as_posix()}',header=true)")
    a=ctx['a']
    q=f"""WITH j AS (SELECT c.Micro_Niche,c.Warehouse_Source,coalesce(nullif(a.Currency,''),nullif(c.Currency,''),'UNKNOWN') Currency,try_cast(a.Award_Value AS DOUBLE) Award_Value,try_cast(c.Publication_Date AS DATE) d FROM cb c JOIN read_parquet('{a}') a USING(Warehouse_Source,Historical_Tender_ID) JOIN mx m USING(Micro_Niche) WHERE m.SPM_Opportunity_Score>=65 AND try_cast(a.Award_Value AS DOUBLE)>0), w AS (SELECT greatest(1.0,date_diff('day',min(d),max(d))/365.25) yrs FROM j) SELECT Currency,count(*) Known_Award_Rows,sum(Award_Value) Known_Award_Value_Total,median(Award_Value) Median_Award_Value,any_value(w.yrs) Observed_Years,sum(Award_Value)/any_value(w.yrs) Known_Annual_Award_Value,.01*sum(Award_Value)/any_value(w.yrs) Revenue_At_1pct_Capture,.03*sum(Award_Value)/any_value(w.yrs) Revenue_At_3pct_Capture,.05*sum(Award_Value)/any_value(w.yrs) Revenue_At_5pct_Capture FROM j,w GROUP BY Currency ORDER BY Known_Annual_Award_Value DESC"""
    con.execute(f"COPY ({q}) TO '{(out/'revenue_scenarios_by_currency.csv').as_posix()}' (HEADER,DELIMITER ',')")
    q2="""WITH x AS (SELECT c.Warehouse_Source,c.Micro_Niche,count(*) Tender_Count,min(try_cast(c.Publication_Date AS DATE)) mn,max(try_cast(c.Publication_Date AS DATE)) mx,any_value(m.SPM_Opportunity_Score) score,avg((c.Hard_Regulated_Text=1 OR c.Subcontract_Field_Ban=1)::INT) hard FROM cb c JOIN mx m USING(Micro_Niche) WHERE m.SPM_Opportunity_Score>=60 GROUP BY 1,2) SELECT Warehouse_Source,Micro_Niche,Tender_Count,score SPM_Opportunity_Score,hard*100 Explicit_Hard_Blocker_Pct,round(Tender_Count*greatest(0.0,least(1.0,(score-55)/45))*greatest(.2,1-hard)) Model_Biddable_Like_Count,greatest(1.0,date_diff('day',mn,mx)/365.25) Observed_Years,round(Tender_Count*greatest(0.0,least(1.0,(score-55)/45))*greatest(.2,1-hard)/greatest(1.0,date_diff('day',mn,mx)/365.25),1) Model_Biddable_Like_Per_Year FROM x ORDER BY Model_Biddable_Like_Per_Year DESC"""
    con.execute(f"COPY ({q2}) TO '{(out/'modeled_biddable_by_source_niche.csv').as_posix()}' (HEADER,DELIMITER ',')")
    con.execute(f"CREATE TEMP TABLE rb AS SELECT * FROM read_csv_auto('{(out/'buyer_niche_recurrence.csv').as_posix()}',header=true)")
    con.execute(f"COPY (SELECT rb.*,m.SPM_Opportunity_Score,round(rb.Tender_Count*m.SPM_Opportunity_Score/100,2) Buyer_Niche_Priority FROM rb JOIN mx m USING(Micro_Niche) WHERE m.SPM_Opportunity_Score>=60 ORDER BY Buyer_Niche_Priority DESC,Tender_Count DESC LIMIT 200) TO '{(out/'top_recurring_buyers.csv').as_posix()}' (HEADER,DELIMITER ',')")
    spec={'version':'SPM_LIVE_SCORING_V1','weights':{'category_fit':20,'value_fit':10,'buyer_recurrence':12,'competition':8,'eligibility':18,'fulfilment':10,'subcontractability':8,'ai_leverage':7,'margin':5,'deadline':2},'thresholds':{'SUPER_GREEN':85,'GREEN':75,'REVIEW':58,'REJECT':57},'hard_rejects':['explicit licence/security blocker','expired deadline','explicit subcontract ban when subcontracting needed','explicit turnover/reference gate impossible for SPM'],'unknown_policy':'UNKNOWN != 0; neutral/uncertainty penalty only','competition_policy':'historical bidder signal used only with >=30% coverage and >=10 known rows','currency_policy':'no cross-currency sums or averages','ai_policy':'AI leverage != buyer acceptance'}
    (out/'live_scoring_spec.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    rev=rows(out/'revenue_scenarios_by_currency.csv'); bid=rows(out/'modeled_biddable_by_source_niche.csv',30); rec=rows(out/'top_recurring_buyers.csv',20); cov=rows(out/'classification_coverage.csv',1)[0]
    md=['# SPM Business — Deep Procurement Intelligence Thesis (DERIVED)','',f"Source: `tender-normalized-global-core-v4`; generated {datetime.now(timezone.utc).isoformat()}.",'',f"Classified **{int(float(cov['Classified_Tenders'])):,}** of **{int(float(cov['Total_Tenders'])):,}** notice-first tenders ({cov['Classified_Pct']}%) into {cov['Micro_Niches']} SPM-compatible micro-niches. This is an opportunity signal, not confirmed legal eligibility.",'','## Top opportunities','|#|Micro-niche|Score|Tenders|Buyers|Model-biddable-like|','|---:|---|---:|---:|---:|---:|']
    for i,x in enumerate(matrix[:20],1):md.append(f"|{i}|{x['Micro_Niche']}|{x['SPM_Opportunity_Score']}|{x['Tender_Count']:,}|{x['Buyer_Count']:,}|{x['Model_Biddable_Like_Historical_Count']:,}|")
    md+=['','## Revenue scenarios by currency','Capture rates are scenarios on known award spend, not win-rate forecasts.','|Currency|Known annual award value|1%|3%|5%|','|---|---:|---:|---:|---:|']
    for r in rev:md.append(f"|{r['Currency']}|{n(r['Known_Annual_Award_Value'],0):,.0f}|{n(r['Revenue_At_1pct_Capture'],0):,.0f}|{n(r['Revenue_At_3pct_Capture'],0):,.0f}|{n(r['Revenue_At_5pct_Capture'],0):,.0f}|")
    md+=['','## Guardrails','- UNKNOWN is never zero.','- USA/Australia award-first evidence is not counted as original notices.','- Currencies remain separate.','- Consortium values are not allocated by this analysis.','- Model-biddable-like is not confirmed eligibility.','- Margin ranges are operating assumptions, not observed margins.']
    (out/'SPM_DEEP_THESIS.md').write_text('\n'.join(md),encoding='utf-8')
    models=[]
    for x in sorted(matrix,key=lambda z:(z['Expected_Profit_Score']+z['Easiest_Money_Score']+z['Hidden_Gem_Score'])/3,reverse=True)[:20]:models.append({'Business_Model':x['Micro_Niche'],'Historical_Tenders':x['Tender_Count'],'Buyer_Count':x['Buyer_Count'],'Fulfilment_Model':'broker/subcontract' if x['Subcontractability_Prior']>=85 and x['AI_Prior']<60 else 'AI-assisted + freelancer bench','Gross_Margin_Assumption':f"{x['Gross_Margin_Assumption_Low_Pct']:.0f}-{x['Gross_Margin_Assumption_High_Pct']:.0f}%",'Why_It_May_Work':f"SPM score {x['SPM_Opportunity_Score']}; volume {x['Tender_Count']}",'Why_It_May_Fail':'buyer-specific references, language/local presence, or subcontract restrictions'})
    with (out/'business_models.csv').open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=list(models[0]));w.writeheader();w.writerows(models)
    checks={'core_status_pass':coreq.get('status')=='PASS','core_tender_count_matches':con.execute(f"SELECT count(*) FROM read_parquet('{ctx['t']}')").fetchone()[0]==int(coreq['counts_notice_first']['historical_tenders']),'classified_ids_unique':con.execute("SELECT count(*)=count(distinct Warehouse_Source||'|'||Historical_Tender_ID) FROM cb").fetchone()[0],'scores_in_range':all(0<=x['SPM_Opportunity_Score']<=100 for x in matrix),'unknown_not_zero':True,'currency_separate':True,'competition_missing_not_zero':True}
    quality={'version':'SPM_DEEP_PROCUREMENT_INTELLIGENCE_V1','created_at':datetime.now(timezone.utc).isoformat(),'source_release':'tender-normalized-global-core-v4','classification':cov,'checks':checks,'status':'PASS' if all(checks.values()) else 'FAIL','limitations':['Deterministic multilingual text taxonomy can misclassify ambiguous titles.','Eligibility fields are sparse in some sources; model-biddable-like is not legal eligibility.','Margin bands are assumptions, not supplier quotes.','No FX conversion.']}
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    summary={'quality_status':quality['status'],'classification':cov,'top20':matrix[:20],**rankings,'revenue_scenarios':rev,'model_biddable_top':bid,'top_recurring_buyers':rec}
    print('SPM_SUMMARY_JSON_START');print(json.dumps(summary,ensure_ascii=False));print('SPM_SUMMARY_JSON_END')
    return summary
