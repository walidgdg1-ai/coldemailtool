#!/usr/bin/env python3
from __future__ import annotations
import argparse, gzip, hashlib, json, math, re, unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

UNKNOWN='UNKNOWN'
def clean(x):
    if x is None:return None
    s=re.sub(r'\s+',' ',str(x).strip()); return s or None
def norm(x):
    s=clean(x)
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(limited|ltd|plc|incorporated|inc|llc|company|co|the)\b',' ',s)
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()
def stable(prefix,s): return prefix+'_'+hashlib.sha256(str(s).encode()).hexdigest()[:20]
def dt(x):
    try:return pd.Timestamp(x)
    except:return pd.NaT
def iso(x):
    x=dt(x); return x.strftime('%Y-%m-%d') if pd.notna(x) else None
def amount(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except:return None
def classify(title,desc,cpvdesc,cpv):
    t=' '.join(str(x) for x in (title,desc,cpvdesc) if clean(x)).lower()
    specs=[('Web','Website / CMS',85,[r'website',r'web site',r'\bcms\b',r'web development',r'web support',r'digital portal']),('Document / data','Digitization / OCR',90,[r'digitis',r'digitiz',r'\bocr\b',r'document scanning',r'metadata',r'data entry',r'archive indexing']),('Language','Translation / transcription',88,[r'translat',r'transcri',r'subtit',r'caption',r'locali[sz]ation',r'proofread',r'interpretation service']),('Creative / communications','Design / publishing',80,[r'graphic design',r'brochure',r'annual report',r'publication',r'creative services',r'video edit',r'motion graphic',r'content creation',r'printing']),('Automation / software','Software / automation',72,[r'software development',r'dashboard',r'automation',r'robotic process',r'\brpa\b',r'data migration',r'application development',r'software solution',r'saas',r'information system']),('Monitoring / research','Monitoring / analysis',70,[r'media monitoring',r'monitoring platform',r'monitoring service',r'data analysis',r'research services'])]
    for cat,sub,score,ps in specs:
        if any(re.search(p,t) for p in ps):return cat,sub,score,score
    if str(cpv or '').startswith(('72','48')): return 'Automation / software','IT services / software',60,60
    return 'Other',clean(cpvdesc) or UNKNOWN,20,15

def bidder_count(bids):
    stats=(bids or {}).get('statistics') or []; by_lot={}; total=[]
    for s in stats:
        if s.get('measure')!='bids':continue
        v=amount(s.get('value'))
        if v is None:continue
        lot=clean(s.get('relatedLot'))
        if lot:by_lot[lot]=v
        else:total.append(v)
    if by_lot:return sum(by_lot.values())
    return max(total) if total else None

def tender_value(t):
    v=amount((t.get('value') or {}).get('amount'))
    cur=(t.get('value') or {}).get('currency')
    if v is not None:return v,cur
    vals=[]; currencies=[]
    for lot in t.get('lots') or []:
        lv=amount((lot.get('value') or {}).get('amount'))
        if lv is not None: vals.append(lv); currencies.append((lot.get('value') or {}).get('currency'))
    return (sum(vals),next((c for c in currencies if c),None)) if vals else (None,None)

def criteria_summary(t):
    out=[]
    for lot in t.get('lots') or []:
        for c in ((lot.get('awardCriteria') or {}).get('criteria') or []):
            out.append({'lot':lot.get('id'),'name':c.get('name'),'type':c.get('type'),'description':c.get('description')})
    return json.dumps(out,ensure_ascii=False) if out else UNKNOWN

def run(raw_dir,out,start,end):
    raw=Path(raw_dir); out=Path(out); out.mkdir(parents=True,exist_ok=True); start_ts=pd.Timestamp(start,tz='UTC'); end_ts=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)-pd.Timedelta(microseconds=1); ingest=datetime.now(timezone.utc).isoformat()
    states={}; release_count=0
    for p in sorted(raw.glob('*.gz')):
        with gzip.open(p,'rt',encoding='utf-8') as f:
            for line in f:
                if not line.strip():continue
                pkg=json.loads(line)
                for r in pkg.get('releases') or []:
                    rd=pd.to_datetime(r.get('date'),errors='coerce',utc=True)
                    if pd.isna(rd) or rd<start_ts or rd>end_ts:continue
                    ocid=clean(r.get('ocid'))
                    if not ocid:continue
                    release_count+=1
                    s=states.setdefault(ocid,{'first_date':rd,'last_date':rd,'tender_date':None,'buyer':None,'tender':{},'awards':{},'contracts':{},'parties':{},'bids':None,'bids_date':None,'release_ids':[],'links':[],'release_count':0})
                    s['release_count']+=1; s['first_date']=min(s['first_date'],rd); s['last_date']=max(s['last_date'],rd); s['release_ids'].append(r.get('id'))
                    tags=r.get('tag') or []
                    if 'tender' in tags and (s['tender_date'] is None or rd<s['tender_date']):s['tender_date']=rd
                    if r.get('buyer'):s['buyer']=r['buyer']
                    if r.get('tender'):s['tender']=r['tender']
                    for a in r.get('awards') or []:
                        aid=clean(a.get('id'))
                        if aid:s['awards'][aid]=(rd,a)
                    for c in r.get('contracts') or []:
                        cid=clean(c.get('id')) or stable('c',json.dumps(c,sort_keys=True))
                        s['contracts'][cid]=(rd,c)
                    for party in r.get('parties') or []:
                        pid=clean(party.get('id'))
                        if pid:s['parties'][pid]=party
                    if r.get('bids') and (s['bids_date'] is None or rd>=s['bids_date']):s['bids']=r['bids']; s['bids_date']=rd
                    for l in r.get('links') or []:
                        href=clean(l.get('href'))
                        if href and href not in s['links']:s['links'].append(href)
    tender_rows=[]; award_rows=[]; bridge_rows=[]
    for ocid,s in states.items():
        t=s['tender'] or {}; buyer=s['buyer'] or {}; bname=clean(buyer.get('name')); bid=clean(buyer.get('id')); buyer_id=stable('buy','UK|'+(bid or norm(bname) or ocid)); tid=stable('ten','UK|'+ocid); title=clean(t.get('title')); desc=clean(t.get('description')); clas=t.get('classification') or {}; cpv=clean(clas.get('id')); cpvdesc=clean(clas.get('description')); cat,sub,auto,lean=classify(title,desc,cpvdesc,cpv); est,currency=tender_value(t); bc=bidder_count(s['bids']); pub=s['tender_date'] or s['first_date']; deadline=((t.get('tenderPeriod') or {}).get('endDate'))
        # Current FTS release packages do not reliably carry a canonical notice-page URL. Do not fabricate one.
        official_link=next((u for u in s['links'] if 'find-tender.service.gov.uk' in u),None)
        award_ids=[]
        for aid,(ard,aobj) in s['awards'].items():
            canonical_aid=stable('awd','UK|'+ocid+'|'+aid); award_ids.append(canonical_aid); sups=aobj.get('suppliers') or []; contracts=[c for _,c in s['contracts'].values() if clean(c.get('awardID'))==aid]
            av=amount((aobj.get('value') or {}).get('amount')); acur=(aobj.get('value') or {}).get('currency'); value_scope='TENDER_OR_AWARD_TOTAL'
            if av is None and contracts:
                cvs=[amount((c.get('value') or {}).get('amount')) for c in contracts]; cvs=[v for v in cvs if v is not None]
                if cvs:av=sum(cvs); acur=next(((c.get('value') or {}).get('currency') for c in contracts if (c.get('value') or {}).get('currency')),None)
            if len(sups)>1:value_scope='GROUP_TOTAL_NOT_ALLOCATED'
            elif len(sups)==1:value_scope='SUPPLIER_ALLOCATED'
            adate=aobj.get('date') or next((c.get('dateSigned') for c in contracts if c.get('dateSigned')),None) or ard
            first_sup=sups[0] if len(sups)==1 else {}; first_party=s['parties'].get(first_sup.get('id'),{}) if first_sup else {}; first_country=((first_party.get('address') or {}).get('countryName')) or UNKNOWN; first_sid=stable('sup','UK|'+(clean(first_sup.get('id')) or norm(first_sup.get('name')))) if first_sup else None
            award_rows.append({'Award_ID':canonical_aid,'Historical_Tender_ID':tid,'Official_Award_Notice_ID':aid,'Contract_ID':' | '.join(clean(c.get('id')) for c in contracts if clean(c.get('id'))) or None,'Buyer_ID':buyer_id,'Supplier_ID':first_sid,'Supplier_Name':clean(first_sup.get('name')) if first_sup else None,'Supplier_Country':first_country,'Award_Date':iso(adate),'Award_Value':av,'Currency':acur or currency or 'GBP','Original_Estimated_Value':est,'Bidder_Count':bc,'Electronic_Bidder_Count':None,'SME_Winner_Status':(first_party.get('details') or {}).get('scale',UNKNOWN) if first_party else UNKNOWN,'Contract_Duration':None,'Renewal_Options':UNKNOWN,'Award_Criteria':criteria_summary(t),'Award_Reason_Summary':None,'Primary_Source_URL':official_link,'Verification_Status':'VERIFIED_PRIMARY_OCDS','Modification_Value':None,'Last_Updated_At':ingest,'Award_Group_ID':canonical_aid,'Award_Value_Scope':value_scope,'Supplier_Count':len(sups) if sups else None,'Source_Record_Count':s['release_count']})
            for sup in sups:
                party=s['parties'].get(sup.get('id'),{}); sid=stable('sup','UK|'+(clean(sup.get('id')) or norm(sup.get('name')))); bridge_rows.append({'Award_ID':canonical_aid,'Supplier_ID':sid,'Supplier_Name':clean(sup.get('name')),'Relationship':'AWARDED_SUPPLIER','Award_Value_Allocated':av if len(sups)==1 else None,'Supplier_Country':((party.get('address') or {}).get('countryName')) or UNKNOWN,'SME_Status':(party.get('details') or {}).get('scale',UNKNOWN)})
        tender_rows.append({'Historical_Tender_ID':tid,'Official_Notice_ID':ocid,'Procurement_Reference':clean(t.get('id')) or ocid,'Title':title,'Buyer_ID':buyer_id,'Buyer_Name':bname,'Country':'United Kingdom','Primary_Source_URL':official_link,'Source_Tier':'A','Publication_Date':iso(pub),'Deadline':iso(deadline),'Category':cat,'Subcategory':sub,'CPV_NAICS_or_Local_Code':cpv,'Scope_Summary':desc,'Official_Estimated_Value':est,'Currency':currency or 'GBP','Contract_Duration':None,'Award_Criteria':criteria_summary(t),'Price_Weight':None,'Quality_Weight':None,'Minimum_Turnover':UNKNOWN,'References_Required':UNKNOWN,'Required_Certifications':UNKNOWN,'Onsite_Requirement':UNKNOWN,'Subcontracting_Status':UNKNOWN,'Tender_Document_URLs':'[]','Award_Link_Status':'LINKED' if award_ids else ('CANCELLED' if t.get('status')=='cancelled' else 'NOT_FOUND'),'Linked_Award_ID':' | '.join(award_ids) if award_ids else None,'Automation_Potential':auto,'Lean_Fit':lean,'Evidence_Confidence':95,'Ingested_At':ingest,'Source_Record_Count':s['release_count'],'Source_Platform':'Find a Tender OCDS','Competition_Type':t.get('procurementMethod'),'Procedure':t.get('procurementMethodDetails'),'Threshold_Level':None,'Directive':(t.get('legalBasis') or {}).get('id'),'Parent_Agreement_ID':None,'Raw_Spend_Category':t.get('mainProcurementCategory'),'Raw_CPV_Description':cpvdesc,'Cancelled_Date':None})
    tenders=pd.DataFrame(tender_rows); awards=pd.DataFrame(award_rows); bridge=pd.DataFrame(bridge_rows)
    if len(tenders): tenders=tenders.drop_duplicates('Historical_Tender_ID')
    if len(awards): awards=awards.sort_values('Award_Date').drop_duplicates('Award_ID',keep='last')
    if len(bridge): bridge=bridge.drop_duplicates(['Award_ID','Supplier_ID'])
    buyers=tenders.groupby(['Buyer_ID','Buyer_Name'],dropna=False).agg(Observed_Tenders=('Historical_Tender_ID','size')).reset_index(); ast=awards.groupby('Buyer_ID').agg(Observed_Awards=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value','sum'),Median_Award_Value=('Award_Value','median'),Median_Bidder_Count=('Bidder_Count','median')).reset_index() if len(awards) else pd.DataFrame(columns=['Buyer_ID']); buyers=buyers.merge(ast,on='Buyer_ID',how='left'); buyers['Normalized_Name']=buyers.Buyer_Name.map(norm); buyers['Country']='United Kingdom'; buyers['Buyer_Type']=UNKNOWN; buyers['Primary_Procurement_Portal']='Find a Tender'; buyers['Last_Updated_At']=ingest
    if len(bridge):
        suppliers=bridge[['Supplier_ID','Supplier_Name','Supplier_Country']].drop_duplicates('Supplier_ID'); sst=bridge.groupby('Supplier_ID').agg(Observed_Contracts_Won=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value_Allocated','sum'),Median_Award_Value=('Award_Value_Allocated','median')).reset_index(); suppliers=suppliers.merge(sst,on='Supplier_ID',how='left'); suppliers['Normalized_Name']=suppliers.Supplier_Name.map(norm); suppliers['Country']=suppliers.Supplier_Country; suppliers['Repeat_Wins']=suppliers.Observed_Contracts_Won; suppliers['Last_Updated_At']=ingest
    else: suppliers=pd.DataFrame(columns=['Supplier_ID','Supplier_Name','Normalized_Name','Country','Observed_Contracts_Won','Observed_Award_Value_Total','Median_Award_Value','Repeat_Wins','Last_Updated_At'])
    for frame,name in [(tenders,'historical_tenders.csv.gz'),(awards,'awards.csv.gz'),(bridge,'award_suppliers.csv.gz'),(buyers,'buyers.csv.gz'),(suppliers,'suppliers.csv.gz')]:frame.to_csv(out/name,index=False,compression='gzip')
    q={'source':'UK Find a Tender OCDS release packages','source_release_count':release_count,'normalized_tenders':len(tenders),'award_groups':len(awards),'award_supplier_links':len(bridge),'unique_buyers':int(tenders.Buyer_ID.nunique()) if len(tenders) else 0,'unique_suppliers':int(bridge.Supplier_ID.nunique()) if len(bridge) else 0,'publication_date_coverage_pct':round(tenders.Publication_Date.notna().mean()*100,2) if len(tenders) else 0,'deadline_coverage_pct':round(tenders.Deadline.notna().mean()*100,2) if len(tenders) else 0,'estimated_value_coverage_pct':round(tenders.Official_Estimated_Value.notna().mean()*100,2) if len(tenders) else 0,'award_link_rate_pct':round((tenders.Award_Link_Status=='LINKED').mean()*100,2) if len(tenders) else 0,'award_value_coverage_pct':round(awards.Award_Value.notna().mean()*100,2) if len(awards) else 0,'bidder_count_coverage_pct':round(awards.Bidder_Count.notna().mean()*100,2) if len(awards) else 0,'cpv_coverage_pct':round(tenders.CPV_NAICS_or_Local_Code.notna().mean()*100,2) if len(tenders) else 0,'notes':['OCDS releases consolidated by OCID across months so tender and later award/contract releases link naturally.','Multiple award groups/lots remain separate; market analytics aggregate them back to tender grain.','Multi-supplier group values are never allocated to suppliers unless exactly one supplier is explicit.']}; (out/'data_quality.json').write_text(json.dumps(q,indent=2),encoding='utf-8'); print(json.dumps(q,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True);p.add_argument('--start',default='2023-08-01');p.add_argument('--end',default='2026-07-31');a=p.parse_args();run(a.raw,a.out,a.start,a.end)
