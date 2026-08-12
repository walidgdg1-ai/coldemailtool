#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

UNKNOWN='UNKNOWN'

def clean(x):
    if pd.isna(x): return None
    s=str(x).strip()
    return re.sub(r'\s+',' ',s) if s else None

def norm(x):
    s=clean(x)
    if not s: return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(limited|ltd|plc|incorporated|inc|llc|company|co|the)\b',' ',s)
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()

def stable(prefix,s): return prefix+'_'+hashlib.sha256(str(s).encode()).hexdigest()[:20]
def iso(s): return pd.to_datetime(s,dayfirst=True,errors='coerce').dt.strftime('%Y-%m-%d')
def first(s):
    for v in s.dropna():
        z=clean(v)
        if z: return z
    return None

def maxnum(s):
    x=pd.to_numeric(s,errors='coerce').dropna()
    return x.max() if len(x) else None

def classify(title,desc,spend,cpv):
    t=' '.join(str(x) for x in (title,desc,spend) if x and not pd.isna(x)).lower()
    specs=[
      ('Web','Website / CMS',85,[r'website',r'web site',r'cms\b',r'web development',r'web support',r'portal']),
      ('Document / data','Digitization / OCR',90,[r'digitis',r'digitiz',r'ocr\b',r'document scanning',r'metadata',r'data entry',r'archive indexing']),
      ('Language','Translation / transcription',88,[r'translat',r'transcri',r'subtit',r'caption',r'locali[sz]ation',r'proofread']),
      ('Creative / communications','Design / publishing',80,[r'graphic design',r'brochure',r'annual report',r'catalog',r'publication',r'creative services',r'communications production',r'video edit',r'motion graphic']),
      ('Automation / software','Software / automation',72,[r'software development',r'dashboard',r'automation',r'robotic process',r'\brpa\b',r'information portal',r'data migration',r'application development']),
      ('Monitoring / research','Monitoring / analysis',70,[r'media monitoring',r'monitoring service',r'data analysis',r'research services'])]
    for cat,sub,score,ps in specs:
        if any(re.search(p,t) for p in ps): return cat,sub,score,score
    if str(cpv or '').startswith(('72','48')): return 'Automation / software','IT services / software',65,60
    return 'Other',clean(desc) or clean(spend) or UNKNOWN,20,15

def run(inp,out,start,end):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(inp,encoding='cp1252',low_memory=False)
    pub=pd.to_datetime(df['Notice Published Date / Contract Created Date'],dayfirst=True,errors='coerce')
    mask=pd.Series(True,index=df.index)
    if start: mask &= pub>=pd.Timestamp(start)
    if end: mask &= pub<=pd.Timestamp(end)
    df=df.loc[mask].copy(); pub=pub.loc[mask]
    df['_pub_iso']=pub.dt.strftime('%Y-%m-%d')
    ids=pd.to_numeric(df['Tender ID'],errors='coerce')
    df['_official_id']=ids.apply(lambda x:str(int(x)) if pd.notna(x) else None)
    fallback=df['Contracting Authority'].fillna('').map(norm)+'|'+df['Tender/Contract Name'].fillna('').map(clean).fillna('')+'|'+df['_pub_iso'].fillna('')
    df['_key']=df['_official_id'].fillna('fallback:'+fallback.map(lambda x:hashlib.sha256(x.encode()).hexdigest()[:24]))
    ingest=datetime.now(timezone.utc).isoformat()
    agg={c:first for c in ['Parent Agreement ID','Contracting Authority','Name of Client Contracting Authority','Tender/Contract Name','Notice Published Date / Contract Created Date','Directive','Competition Type','Main Cpv Code','Main Cpv Code Description','Spend Category','Threshold Level','Procedure','Tender Submission Deadline','Evaluation Type','Cancelled Date','Award Published','TED Notice Link','TED CAN Link','Platform','_official_id','_pub_iso']}
    agg.update({'Sum of Notice Estimated Value (€)':maxnum,'Sum of Contract Duration (Months)':maxnum,'Sum of Awarded Value (€)':maxnum,'Sum of No of Bids Received':maxnum})
    g=df.groupby('_key',sort=False).agg(agg).join(df.groupby('_key').size().rename('_source_count')).reset_index()
    buyer=g['Contracting Authority'].where(g['Contracting Authority'].notna(),g['Name of Client Contracting Authority'])
    g['Buyer_ID']=('IE|'+buyer.map(norm)).map(lambda x:stable('buy',x)); g['Historical_Tender_ID']=('IE|'+g['_key']).map(lambda x:stable('ten',x))
    cls=[classify(a,b,c,d) for a,b,c,d in zip(g['Tender/Contract Name'],g['Main Cpv Code Description'],g['Spend Category'],g['Main Cpv Code'])]
    g['Category']=[x[0] for x in cls]; g['Subcategory']=[x[1] for x in cls]; g['Automation_Potential']=[x[2] for x in cls]; g['Lean_Fit']=[x[3] for x in cls]
    supplier_any=df['Awarded Suppliers'].notna().groupby(df['_key']).any(); award_present=g['Award Published'].notna()|g['Sum of Awarded Value (€)'].notna()|g['_key'].map(supplier_any).fillna(False)
    g['Award_ID']=[stable('awd','IE|'+k+'|'+str(d or '')) if hp else None for k,d,hp in zip(g['_key'],g['Award Published'],award_present)]

    s=df[['_key','Awarded Suppliers']].dropna().copy(); s['Supplier_Name']=s['Awarded Suppliers'].astype(str).str.split('|'); s=s.explode('Supplier_Name'); s['Supplier_Name']=s['Supplier_Name'].map(clean); s=s[s.Supplier_Name.notna()]; s['Normalized_Name']=s.Supplier_Name.map(norm); s=s[s.Normalized_Name!=''].drop_duplicates(['_key','Normalized_Name'])
    key_award=g.set_index('_key').Award_ID.to_dict(); s['Award_ID']=s['_key'].map(key_award); s=s[s.Award_ID.notna()]; s['Supplier_ID']=('IE|'+s.Normalized_Name).map(lambda x:stable('sup',x)); supplier_counts=s.groupby('_key').size().to_dict()

    tenders=pd.DataFrame({'Historical_Tender_ID':g.Historical_Tender_ID,'Official_Notice_ID':g._official_id,'Procurement_Reference':g._official_id,'Title':g['Tender/Contract Name'],'Buyer_ID':g.Buyer_ID,'Buyer_Name':buyer,'Country':'Ireland','Primary_Source_URL':g['TED Notice Link'].where(g['TED Notice Link'].notna(),g['TED CAN Link']),'Source_Tier':'A','Publication_Date':iso(g['Notice Published Date / Contract Created Date']),'Deadline':iso(g['Tender Submission Deadline']),'Category':g.Category,'Subcategory':g.Subcategory,'CPV_NAICS_or_Local_Code':g['Main Cpv Code'],'Scope_Summary':g['Tender/Contract Name'],'Official_Estimated_Value':g['Sum of Notice Estimated Value (€)'],'Currency':'EUR','Contract_Duration':g['Sum of Contract Duration (Months)'],'Award_Criteria':g['Evaluation Type'].fillna(UNKNOWN),'Price_Weight':None,'Quality_Weight':None,'Minimum_Turnover':UNKNOWN,'References_Required':UNKNOWN,'Required_Certifications':UNKNOWN,'Onsite_Requirement':UNKNOWN,'Subcontracting_Status':UNKNOWN,'Tender_Document_URLs':[json.dumps([u for u in (a,b) if clean(u)],ensure_ascii=False) for a,b in zip(g['TED Notice Link'],g['TED CAN Link'])],'Award_Link_Status':['LINKED' if a else ('CANCELLED' if clean(c) else 'NOT_FOUND') for a,c in zip(award_present,g['Cancelled Date'])],'Linked_Award_ID':g.Award_ID,'Automation_Potential':g.Automation_Potential,'Lean_Fit':g.Lean_Fit,'Evidence_Confidence':[95 if x else 80 for x in g._official_id],'Ingested_At':ingest,'Source_Record_Count':g._source_count,'Source_Platform':g.Platform,'Competition_Type':g['Competition Type'],'Procedure':g.Procedure,'Threshold_Level':g['Threshold Level'],'Directive':g.Directive,'Parent_Agreement_ID':g['Parent Agreement ID'],'Raw_Spend_Category':g['Spend Category'],'Raw_CPV_Description':g['Main Cpv Code Description'],'Cancelled_Date':iso(g['Cancelled Date'])})
    ag=g.loc[award_present].copy(); awards=pd.DataFrame({'Award_ID':ag.Award_ID,'Historical_Tender_ID':ag.Historical_Tender_ID,'Official_Award_Notice_ID':ag['TED CAN Link'].where(ag['TED CAN Link'].notna(),ag._official_id),'Contract_ID':ag._official_id,'Buyer_ID':ag.Buyer_ID,'Supplier_ID':None,'Supplier_Name':None,'Supplier_Country':UNKNOWN,'Award_Date':iso(ag['Award Published']),'Award_Value':ag['Sum of Awarded Value (€)'],'Currency':'EUR','Original_Estimated_Value':ag['Sum of Notice Estimated Value (€)'],'Bidder_Count':pd.to_numeric(ag['Sum of No of Bids Received'],errors='coerce'),'Electronic_Bidder_Count':None,'SME_Winner_Status':UNKNOWN,'Contract_Duration':ag['Sum of Contract Duration (Months)'],'Renewal_Options':UNKNOWN,'Award_Criteria':ag['Evaluation Type'].fillna(UNKNOWN),'Award_Reason_Summary':None,'Primary_Source_URL':ag['TED CAN Link'].where(ag['TED CAN Link'].notna(),ag['TED Notice Link']),'Verification_Status':'VERIFIED_PRIMARY_DATASET','Modification_Value':None,'Last_Updated_At':ingest,'Award_Group_ID':ag.Award_ID,'Award_Value_Scope':[('GROUP_TOTAL_NOT_ALLOCATED' if supplier_counts.get(k,0)>1 else 'TENDER_OR_AWARD_TOTAL') for k in ag._key],'Supplier_Count':[supplier_counts.get(k,0) or None for k in ag._key],'Source_Record_Count':ag._source_count})
    single=s.groupby('_key').filter(lambda x:len(x)==1).drop_duplicates('_key').set_index('_key') if len(s) else pd.DataFrame()
    if len(single): awards['Supplier_ID']=[single.loc[k,'Supplier_ID'] if k in single.index else None for k in ag._key]; awards['Supplier_Name']=[single.loc[k,'Supplier_Name'] if k in single.index else None for k in ag._key]
    bridge=s[['Award_ID','Supplier_ID','Supplier_Name']].copy(); bridge['Relationship']='AWARDED_SUPPLIER'; av=awards.set_index('Award_ID').Award_Value.to_dict(); sc=awards.set_index('Award_ID').Supplier_Count.to_dict(); bridge['Award_Value_Allocated']=[av.get(a) if sc.get(a)==1 else None for a in bridge.Award_ID]

    tstats=tenders.groupby(['Buyer_ID','Buyer_Name'],dropna=False).agg(Observed_Tenders=('Historical_Tender_ID','size')).reset_index(); astats=awards.groupby('Buyer_ID').agg(Observed_Awards=('Award_ID','size'),Observed_Award_Value_Total=('Award_Value','sum'),Median_Award_Value=('Award_Value','median'),Median_Bidder_Count=('Bidder_Count','median')).reset_index(); buyers=tstats.merge(astats,on='Buyer_ID',how='left'); buyers['Normalized_Name']=buyers.Buyer_Name.map(norm); buyers['Country']='Ireland'; buyers['Buyer_Type']=UNKNOWN; buyers['Primary_Procurement_Portal']='eTenders'; buyers['Last_Updated_At']=ingest
    supplier_base=bridge[['Supplier_ID','Supplier_Name']].drop_duplicates('Supplier_ID'); supplier_base['Normalized_Name']=supplier_base.Supplier_Name.map(norm); sstats=bridge.groupby('Supplier_ID').agg(Observed_Contracts_Won=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value_Allocated','sum'),Median_Award_Value=('Award_Value_Allocated','median')).reset_index(); suppliers=supplier_base.merge(sstats,on='Supplier_ID',how='left'); suppliers['Country']=UNKNOWN; suppliers['Repeat_Wins']=suppliers.Observed_Contracts_Won; suppliers['Last_Updated_At']=ingest

    for frame,name in [(tenders,'historical_tenders.csv.gz'),(awards,'awards.csv.gz'),(bridge,'award_suppliers.csv.gz'),(buyers,'buyers.csv.gz'),(suppliers,'suppliers.csv.gz')]: frame.to_csv(out/name,index=False,compression='gzip')
    linked=tenders.merge(awards[['Historical_Tender_ID','Award_Value','Bidder_Count']],on='Historical_Tender_ID',how='left'); analytics=linked.groupby(['Category','Subcategory'],dropna=False).agg(Tender_Count=('Historical_Tender_ID','size'),Award_Count=('Award_Value','count'),Median_Award_Value=('Award_Value','median'),P25_Award_Value=('Award_Value',lambda x:x.quantile(.25)),P75_Award_Value=('Award_Value',lambda x:x.quantile(.75)),Median_Bidder_Count=('Bidder_Count','median'),Pct_1_Bidder=('Bidder_Count',lambda x:(x.dropna()==1).mean()*100 if x.notna().any() else None),Pct_LE3_Bidders=('Bidder_Count',lambda x:(x.dropna()<=3).mean()*100 if x.notna().any() else None),Median_Lean_Fit=('Lean_Fit','median')).reset_index(); analytics.to_csv(out/'category_analytics.csv',index=False)
    q={'source':'Ireland eTenders consolidated notice dataset','source_rows':len(df),'normalized_tenders':len(tenders),'award_groups':len(awards),'award_supplier_links':len(bridge),'unique_buyers':int(buyers.Buyer_ID.nunique()),'unique_suppliers':int(suppliers.Supplier_ID.nunique()),'duplicate_natural_key_groups_collapsed':int((df.groupby('_key').size()>1).sum()),'publication_date_coverage_pct':round(tenders.Publication_Date.notna().mean()*100,2),'deadline_coverage_pct':round(tenders.Deadline.notna().mean()*100,2),'estimated_value_coverage_pct':round(tenders.Official_Estimated_Value.notna().mean()*100,2),'award_link_rate_pct':round((tenders.Award_Link_Status=='LINKED').mean()*100,2),'award_value_coverage_pct':round(awards.Award_Value.notna().mean()*100,2),'bidder_count_coverage_pct':round(awards.Bidder_Count.notna().mean()*100,2),'cpv_coverage_pct':round(tenders.CPV_NAICS_or_Local_Code.notna().mean()*100,2),'notes':['Duplicate Tender IDs collapsed.','Multi-supplier award values are retained once at award-group level and never allocated unless exactly one supplier.','Unknown requirements remain UNKNOWN.']}; (out/'data_quality.json').write_text(json.dumps(q,indent=2),encoding='utf-8')
    outputs={f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in out.iterdir() if f.is_file()}; (out/'run_manifest.json').write_text(json.dumps({'schema_version':'1.1-relational','generated_at':ingest,'adapter':'ireland_etenders','window':{'start':start,'end':end},'outputs':outputs,'quality':q},indent=2),encoding='utf-8'); print(json.dumps(q,indent=2))

if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('--input',required=True); a.add_argument('--out',required=True); a.add_argument('--start',default='2023-08-01'); a.add_argument('--end',default='2026-07-31'); x=a.parse_args(); run(x.input,x.out,x.start,x.end)
