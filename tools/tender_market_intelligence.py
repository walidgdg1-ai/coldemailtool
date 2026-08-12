#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import pandas as pd

def clamp(x,a=0,b=100): return max(a,min(b,x))
def value_score(v):
    if pd.isna(v) or v<=0: return 0
    return clamp((math.log10(v)-3)/3*100)
def competition_score(b):
    if pd.isna(b): return 35
    if b<=1:return 100
    if b<=3:return 90
    if b<=5:return 78
    if b<=10:return 58
    if b<=20:return 35
    return 15
def volume_score(n): return clamp(math.log1p(max(n,0))/math.log(101)*100)
def coverage_score(a,b): return clamp((a*.55+b*.45)*100)

def run(indir,outdir):
    i=Path(indir); o=Path(outdir); o.mkdir(parents=True,exist_ok=True)
    t=pd.read_csv(i/'historical_tenders.csv.gz',low_memory=False)
    a=pd.read_csv(i/'awards.csv.gz',low_memory=False)
    bridge=pd.read_csv(i/'award_suppliers.csv.gz',low_memory=False)
    x=t.merge(a[['Award_ID','Historical_Tender_ID','Award_Value','Bidder_Count','Supplier_Count']],on='Historical_Tender_ID',how='left')
    rows=[]
    for (cat,sub),g in x.groupby(['Category','Subcategory'],dropna=False):
        av=g.Award_Value.dropna(); bc=g.Bidder_Count.dropna(); awcov=g.Award_ID.notna().mean(); bidcov=g.Bidder_Count.notna().mean(); buyers=g.Buyer_ID.nunique(); repeat_buyers=(g.groupby('Buyer_ID').size()>=2).sum(); medv=av.median() if len(av) else None; medb=bc.median() if len(bc) else None; lean=g.Lean_Fit.median()
        score=.30*lean+.25*value_score(medv)+.20*competition_score(medb)+.15*volume_score(len(g))+.10*coverage_score(awcov,bidcov)
        rows.append({'Category':cat,'Subcategory':sub,'Tender_Count':len(g),'Award_Count':int(g.Award_ID.notna().sum()),'Unique_Buyers':buyers,'Repeat_Buyers':int(repeat_buyers),'Median_Award_Value':medv,'P25_Award_Value':av.quantile(.25) if len(av) else None,'P75_Award_Value':av.quantile(.75) if len(av) else None,'Median_Bidder_Count':medb,'Pct_1_Bidder':(bc==1).mean()*100 if len(bc) else None,'Pct_LE3_Bidders':(bc<=3).mean()*100 if len(bc) else None,'Award_Coverage_Pct':awcov*100,'Bidder_Coverage_Pct':bidcov*100,'Median_Lean_Fit':lean,'Market_Attractiveness_Score':round(score,1)})
    rank=pd.DataFrame(rows).sort_values(['Market_Attractiveness_Score','Tender_Count'],ascending=False); rank.to_csv(o/'market_rank.csv',index=False)
    c=x[(x.Lean_Fit>=60)&x.Award_Value.notna()].copy(); c['Individual_Score']=c.apply(lambda r:round(.35*r.Lean_Fit+.35*value_score(r.Award_Value)+.25*competition_score(r.Bidder_Count)+.05*(100 if pd.notna(r.Primary_Source_URL) else 50),1),axis=1)
    cols=['Individual_Score','Historical_Tender_ID','Official_Notice_ID','Title','Buyer_Name','Publication_Date','Category','Subcategory','Official_Estimated_Value','Award_Value','Bidder_Count','Supplier_Count','Lean_Fit','Primary_Source_URL']; c.sort_values(['Individual_Score','Award_Value'],ascending=False)[cols].head(1000).to_csv(o/'historical_anomalies.csv',index=False)
    lt=t[t.Lean_Fit>=60].copy(); by=lt.groupby(['Buyer_ID','Buyer_Name']).agg(Lean_Tenders=('Historical_Tender_ID','size'),Categories=('Category',lambda s:' | '.join(s.value_counts().head(5).index.astype(str)))).reset_index(); ba=a.groupby('Buyer_ID').agg(Awards=('Award_ID','size'),Median_Award_Value=('Award_Value','median'),Median_Bidder_Count=('Bidder_Count','median')).reset_index(); by=by.merge(ba,on='Buyer_ID',how='left').sort_values(['Lean_Tenders','Median_Award_Value'],ascending=False); by.to_csv(o/'repeat_buyers.csv',index=False)
    # Supplier concentration by segment. Multi-supplier awards are association-only; value is never multiplied across suppliers.
    sa=bridge.merge(a[['Award_ID','Historical_Tender_ID']],on='Award_ID',how='left').merge(t[['Historical_Tender_ID','Category','Subcategory']],on='Historical_Tender_ID',how='left'); conc=[]
    for (cat,sub),g in sa.groupby(['Category','Subcategory'],dropna=False):
        wins=g.groupby('Supplier_ID').Award_ID.nunique().sort_values(ascending=False); total=wins.sum(); conc.append({'Category':cat,'Subcategory':sub,'Supplier_Count':wins.size,'Award_Supplier_Associations':int(total),'Top1_Share_Pct':wins.iloc[0]/total*100 if total else None,'Top5_Share_Pct':wins.head(5).sum()/total*100 if total else None})
    pd.DataFrame(conc).to_csv(o/'supplier_concentration.csv',index=False)
    summary={'ranked_segments':len(rank),'lean_segments':int((rank.Median_Lean_Fit>=60).sum()),'historical_anomalies':min(1000,len(c)),'repeat_buyers':len(by),'method':'30% lean fit + 25% log award value + 20% competition + 15% volume + 10% evidence coverage. Missing bidder count gets conservative neutral-low score 35; never guessed.'}; (o/'market_intelligence_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8'); print(json.dumps(summary,indent=2)); print(rank.head(30).to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--out',required=True); a=p.parse_args(); run(a.input,a.out)
