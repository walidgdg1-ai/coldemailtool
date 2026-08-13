#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math,re,sqlite3,unicodedata
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd

UNKNOWN='UNKNOWN'; VERSION='QC_SEAO_OCDS_CANONICAL_V1'
def clean(x):
    if x is None:return None
    s=re.sub(r'\s+',' ',str(x).strip()); return s or None
def norm(x):
    s=clean(x)
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(inc|incorporee|incorporated|ltee|ltd|limitee|limited|senc|sec|compagnie|company|corporation|corp)\b',' ',s)
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()
def stable(p,s):return p+'_'+hashlib.sha256(str(s).encode()).hexdigest()[:20]
def iso(x):
    d=pd.to_datetime(x,errors='coerce',utc=True); return d.strftime('%Y-%m-%d') if pd.notna(d) else None
def amount(v):
    if not isinstance(v,dict):return None,None
    try:x=float(v.get('amount')) if v.get('amount') is not None else None
    except:x=None
    return x,clean(v.get('currency'))
def classify(title,desc,items):
    itxt=[]
    for it in items or []:
        if not isinstance(it,dict):continue
        itxt += [clean(it.get('description')) or '']
        cl=it.get('classification') or {};itxt += [clean(cl.get('description')) or '',clean(cl.get('id')) or '']
        for c in it.get('additionalClassifications') or []:
            if isinstance(c,dict):itxt += [clean(c.get('description')) or '',clean(c.get('id')) or '']
    t=' '.join(x for x in [clean(title) or '',clean(desc) or '',*itxt] if x).lower()
    rules=[
      ('Web','Website / CMS',88,[r'site web',r'website',r'portail web',r'\bcms\b',r'refonte.*site',r'developpement web',r'développement web']),
      ('Document / data','Digitization / OCR',92,[r'numeris',r'numéris',r'\bocr\b',r'balayage',r'indexation',r'saisie de donne',r'saisie de donné']),
      ('Language','Translation / transcription',90,[r'traduction',r'transcription',r'sous.titr',r'interpr[eé]t',r'relecture']),
      ('Creative / communications','Design / publishing',82,[r'graphisme',r'graphique',r'communication',r'brochure',r'mise en page',r'production vid[eé]o',r'contenu',r'publicit[eé]',r'campagne']),
      ('Printing','Print / routing',66,[r'impression',r'imprimerie',r'routage',r'mise sous pli']),
      ('Automation / software','Software / automation',74,[r'logiciel',r'software',r'automatisation',r'd[eé]veloppement applicatif',r'plateforme',r'tableau de bord',r'saas',r'migration de donn']),
      ('Monitoring / research','Monitoring / analysis',70,[r'veille',r'monitoring',r'analyse de donn',r'[eé]tude',r'sondage',r'recherche de march[eé]'])]
    for cat,sub,sc,pats in rules:
        if any(re.search(p,t) for p in pats):return cat,sub,sc,sc
    return 'Other',UNKNOWN,20,15

def init(c):
    c.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=MEMORY;
    CREATE TABLE tender(ocid TEXT PRIMARY KEY,release_id TEXT,release_date TEXT,title TEXT,description TEXT,status TEXT,buyer_id TEXT,buyer_name TEXT,method TEXT,method_details TEXT,start_date TEXT,end_date TEXT,number_tenderers INTEGER,estimate REAL,currency TEXT,main_cat TEXT,add_cats TEXT,items_json TEXT,documents_json TEXT,source_file TEXT);
    CREATE TABLE award(award_key TEXT PRIMARY KEY,ocid TEXT,award_id TEXT,release_id TEXT,release_date TEXT,status TEXT,award_date TEXT,value REAL,currency TEXT,suppliers_json TEXT,source_file TEXT);
    CREATE INDEX ix_award_ocid ON award(ocid);
    CREATE TABLE contract(contract_key TEXT PRIMARY KEY,ocid TEXT,contract_id TEXT,award_id TEXT,status TEXT,date_signed TEXT,start_date TEXT,end_date TEXT,value REAL,currency TEXT,release_date TEXT,source_file TEXT);
    CREATE TABLE party(party_key TEXT PRIMARY KEY,ocid TEXT,party_id TEXT,name TEXT,country TEXT,region TEXT,locality TEXT,roles_json TEXT,neq TEXT,release_date TEXT);
    ''')

def run(raw_dir,out_dir,start,end):
    raw=Path(raw_dir);out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);dbp=out/'work.sqlite';dbp.unlink(missing_ok=True);con=sqlite3.connect(dbp);init(con.cursor());c=con.cursor();stats=defaultdict(int);start_ts=pd.Timestamp(start,tz='UTC');end_ts=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)-pd.Timedelta(microseconds=1)
    files=sorted(raw.glob('mensuel_*.json'))
    for p in files:
        obj=json.load(open(p,encoding='utf-8-sig'));rels=obj.get('releases') or [] if isinstance(obj,dict) else []
        stats['source_files']+=1;stats['raw_releases']+=len(rels)
        for r in rels:
            if not isinstance(r,dict):stats['invalid_release']+=1;continue
            rd=pd.to_datetime(r.get('date'),errors='coerce',utc=True)
            if pd.isna(rd) or rd<start_ts or rd>end_ts:stats['out_of_window']+=1;continue
            ocid=clean(r.get('ocid'));rid=clean(r.get('id'))
            if not ocid:stats['missing_ocid']+=1;continue
            rdate=rd.isoformat()
            b=r.get('buyer') or {};t=r.get('tender') or {}
            if t:
                est,ecur=amount(t.get('value'))
                row=(ocid,rid,rdate,clean(t.get('title')),clean(t.get('description')),clean(t.get('status')),clean(b.get('id') or (t.get('procuringEntity') or {}).get('id')),clean(b.get('name') or (t.get('procuringEntity') or {}).get('name')),clean(t.get('procurementMethod')),clean(t.get('procurementMethodDetails')),clean((t.get('tenderPeriod') or {}).get('startDate')),clean((t.get('tenderPeriod') or {}).get('endDate')),t.get('numberOfTenderers') if isinstance(t.get('numberOfTenderers'),int) else None,est,ecur,clean(t.get('mainProcurementCategory')),json.dumps(t.get('additionalProcurementCategories') or [],ensure_ascii=False),json.dumps(t.get('items') or [],ensure_ascii=False),json.dumps(t.get('documents') or [],ensure_ascii=False),p.name)
                prev=c.execute('SELECT release_date FROM tender WHERE ocid=?',(ocid,)).fetchone()
                if not prev or rdate>=prev[0]:c.execute('INSERT OR REPLACE INTO tender VALUES ('+','.join('?'*len(row))+')',row)
            for a in r.get('awards') or []:
                if not isinstance(a,dict):continue
                aid=clean(a.get('id')) or stable('rawaward',json.dumps(a,sort_keys=True,ensure_ascii=False));ak=ocid+'|'+aid;v,cur=amount(a.get('value'));sups=a.get('suppliers') or []
                row=(ak,ocid,aid,rid,rdate,clean(a.get('status')),clean(a.get('date')),v,cur,json.dumps(sups,ensure_ascii=False),p.name)
                prev=c.execute('SELECT release_date FROM award WHERE award_key=?',(ak,)).fetchone()
                if not prev or rdate>=prev[0]:c.execute('INSERT OR REPLACE INTO award VALUES ('+','.join('?'*len(row))+')',row)
            for ct in r.get('contracts') or []:
                if not isinstance(ct,dict):continue
                cid=clean(ct.get('id')) or stable('rawcontract',json.dumps(ct,sort_keys=True,ensure_ascii=False));ck=ocid+'|'+cid;v,cur=amount(ct.get('value'));period=ct.get('period') or {}
                row=(ck,ocid,cid,clean(ct.get('awardID')),clean(ct.get('status')),clean(ct.get('dateSigned')),clean(period.get('startDate')),clean(period.get('endDate')),v,cur,rdate,p.name)
                prev=c.execute('SELECT release_date FROM contract WHERE contract_key=?',(ck,)).fetchone()
                if not prev or rdate>=prev[0]:c.execute('INSERT OR REPLACE INTO contract VALUES ('+','.join('?'*len(row))+')',row)
            for pa in r.get('parties') or []:
                if not isinstance(pa,dict):continue
                pid=clean(pa.get('id'));name=clean(pa.get('name'))
                if not pid and not name:continue
                pk=ocid+'|'+(pid or stable('anon',name));ad=pa.get('address') or {};det=pa.get('details') or {}
                row=(pk,ocid,pid,name,clean(ad.get('countryName')),clean(ad.get('region')),clean(ad.get('locality')),json.dumps(pa.get('roles') or [],ensure_ascii=False),clean(det.get('NEQ')),rdate)
                prev=c.execute('SELECT release_date FROM party WHERE party_key=?',(pk,)).fetchone()
                if not prev or rdate>=prev[0]:c.execute('INSERT OR REPLACE INTO party VALUES ('+','.join('?'*len(row))+')',row)
        con.commit();print('file',p.name,'releases',len(rels),'cumulative',stats['raw_releases'])
    ingest=datetime.now(timezone.utc).isoformat();tcols=['ocid','release_id','release_date','title','description','status','buyer_id','buyer_name','method','method_details','start_date','end_date','number_tenderers','estimate','currency','main_cat','add_cats','items_json','documents_json','source_file']
    tend=[]
    for rr in c.execute('SELECT * FROM tender ORDER BY release_date'):
        d=dict(zip(tcols,rr));tid=stable('ten','QC|'+d['ocid']);bid=stable('buy','QC|'+(d.get('buyer_id') or norm(d.get('buyer_name')) or d['ocid']));items=json.loads(d.get('items_json') or '[]');cat,sub,auto,lean=classify(d.get('title'),d.get('description'),items);cpv=None
        for it in items:
            cl=(it or {}).get('classification') or {}
            if cl.get('id'):cpv=clean(cl.get('id'));break
        aids=[stable('awd','QC|'+x[0]) for x in c.execute('SELECT award_key FROM award WHERE ocid=?',(d['ocid'],))]
        docs=json.loads(d.get('documents_json') or '[]');urls=[x.get('url') for x in docs if isinstance(x,dict) and x.get('url')]
        tend.append({'Historical_Tender_ID':tid,'Official_Notice_ID':d.get('release_id'),'Procurement_Reference':d['ocid'],'Title':d.get('title'),'Buyer_ID':bid,'Buyer_Name':d.get('buyer_name'),'Country':'Canada - Quebec','Primary_Source_URL':urls[0] if urls else None,'Source_Tier':'A','Publication_Date':iso(d.get('start_date') or d.get('release_date')),'Deadline':iso(d.get('end_date')),'Category':cat,'Subcategory':sub,'CPV_NAICS_or_Local_Code':cpv,'Scope_Summary':d.get('description') or d.get('title'),'Official_Estimated_Value':d.get('estimate'),'Currency':d.get('currency') or 'CAD','Contract_Duration':None,'Award_Criteria':UNKNOWN,'Price_Weight':None,'Quality_Weight':None,'Minimum_Turnover':UNKNOWN,'References_Required':UNKNOWN,'Required_Certifications':UNKNOWN,'Onsite_Requirement':UNKNOWN,'Subcontracting_Status':UNKNOWN,'Tender_Document_URLs':json.dumps(urls,ensure_ascii=False),'Award_Link_Status':'LINKED' if aids else 'NOT_FOUND','Linked_Award_ID':' | '.join(aids) if aids else None,'Automation_Potential':auto,'Lean_Fit':lean,'Evidence_Confidence':98,'Ingested_At':ingest,'Source_Record_Count':1,'Source_Platform':'SEAO OCDS','Competition_Type':d.get('method'),'Procedure':d.get('method_details'),'Threshold_Level':None,'Directive':None,'Parent_Agreement_ID':None,'Raw_Spend_Category':d.get('main_cat'),'Raw_CPV_Description':None,'Cancelled_Date':None,'Official_Bidder_Count':d.get('number_tenderers'),'Source_Grain_Status':'OCDS_COMPILED_FROM_LATEST_RELEASE','Source_File':d.get('source_file')})
    tdf=pd.DataFrame(tend);tdf.to_csv(out/'historical_tenders.csv.gz',index=False,compression='gzip')
    awards=[];bridges=[]
    acols=['award_key','ocid','award_id','release_id','release_date','status','award_date','value','currency','suppliers_json','source_file']
    for rr in c.execute('SELECT * FROM award ORDER BY release_date'):
        d=dict(zip(acols,rr));tid=stable('ten','QC|'+d['ocid']);aid=stable('awd','QC|'+d['award_key']);tr=c.execute('SELECT buyer_id,buyer_name,number_tenderers,estimate FROM tender WHERE ocid=?',(d['ocid'],)).fetchone();buyer_id,buyer_name,bc,est=tr if tr else (None,None,None,None);bid=stable('buy','QC|'+(buyer_id or norm(buyer_name) or d['ocid']));sups=json.loads(d.get('suppliers_json') or '[]');sn=[clean(x.get('name')) for x in sups if isinstance(x,dict) and clean(x.get('name'))];sid0=stable('sup','QC|'+(clean(sups[0].get('id')) or norm(sn[0]))) if len(sn)==1 else None;scope='UNKNOWN' if d.get('value') is None else ('SUPPLIER_ALLOCATED' if len(sn)==1 else ('GROUP_TOTAL_NOT_ALLOCATED' if len(sn)>1 else 'TENDER_OR_AWARD_TOTAL'))
        awards.append({'Award_ID':aid,'Historical_Tender_ID':tid,'Official_Award_Notice_ID':d.get('release_id'),'Contract_ID':None,'Buyer_ID':bid,'Supplier_ID':sid0,'Supplier_Name':sn[0] if len(sn)==1 else None,'Supplier_Country':'Canada' if len(sn)==1 else UNKNOWN,'Award_Date':iso(d.get('award_date')),'Award_Value':d.get('value'),'Currency':d.get('currency') or 'CAD','Original_Estimated_Value':est,'Bidder_Count':bc,'Electronic_Bidder_Count':None,'SME_Winner_Status':UNKNOWN,'Contract_Duration':None,'Renewal_Options':UNKNOWN,'Award_Criteria':UNKNOWN,'Award_Reason_Summary':None,'Primary_Source_URL':None,'Verification_Status':'VERIFIED_PRIMARY_SEAO_OCDS','Modification_Value':None,'Last_Updated_At':ingest,'Award_Group_ID':aid,'Award_Value_Scope':scope,'Supplier_Count':len(sn) if sn else None,'Source_Record_Count':1,'Award_Status':d.get('status'),'Source_File':d.get('source_file')})
        for s in sups:
            if not isinstance(s,dict) or not clean(s.get('name')):continue
            name=clean(s.get('name'));sid=stable('sup','QC|'+(clean(s.get('id')) or norm(name)));bridges.append({'Award_ID':aid,'Supplier_ID':sid,'Supplier_Name':name,'Relationship':'AWARDED_SUPPLIER','Award_Value_Allocated':d.get('value') if len(sn)==1 else None,'Supplier_Country':'Canada','SME_Status':UNKNOWN})
    adf=pd.DataFrame(awards).drop_duplicates('Award_ID') if awards else pd.DataFrame(columns=['Award_ID','Historical_Tender_ID','Award_Value','Bidder_Count','Supplier_Count']);bdf=pd.DataFrame(bridges).drop_duplicates(['Award_ID','Supplier_ID']) if bridges else pd.DataFrame(columns=['Award_ID','Supplier_ID','Supplier_Name','Relationship','Award_Value_Allocated','Supplier_Country','SME_Status']);adf.to_csv(out/'awards.csv.gz',index=False,compression='gzip');bdf.to_csv(out/'award_suppliers.csv.gz',index=False,compression='gzip')
    buyers=tdf.groupby(['Buyer_ID','Buyer_Name'],dropna=False).agg(Observed_Tenders=('Historical_Tender_ID','nunique')).reset_index();ast=adf.groupby('Buyer_ID').agg(Observed_Awards=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value','sum'),Median_Award_Value=('Award_Value','median'),Median_Bidder_Count=('Bidder_Count','median')).reset_index() if len(adf) else pd.DataFrame(columns=['Buyer_ID']);buyers=buyers.merge(ast,on='Buyer_ID',how='left');buyers['Normalized_Name']=buyers.Buyer_Name.map(norm);buyers['Country']='Canada - Quebec';buyers['Buyer_Type']=UNKNOWN;buyers['Primary_Procurement_Portal']='SEAO';buyers['Last_Updated_At']=ingest;buyers.to_csv(out/'buyers.csv.gz',index=False,compression='gzip')
    if len(bdf):
        sf=bdf.groupby(['Supplier_ID','Supplier_Name','Supplier_Country'],dropna=False).agg(Observed_Contracts_Won=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value_Allocated','sum'),Median_Award_Value=('Award_Value_Allocated','median')).reset_index();sf['Normalized_Name']=sf.Supplier_Name.map(norm);sf['Country']=sf.Supplier_Country;sf['Repeat_Wins']=sf.Observed_Contracts_Won;sf['Last_Updated_At']=ingest
    else:sf=pd.DataFrame(columns=['Supplier_ID','Supplier_Name','Observed_Contracts_Won']);sf.to_csv(out/'suppliers.csv.gz',index=False,compression='gzip')
    if len(bdf):sf.to_csv(out/'suppliers.csv.gz',index=False,compression='gzip')
    j=tdf[['Historical_Tender_ID','Category','Subcategory','Buyer_ID','Buyer_Name','Lean_Fit']].merge(adf[['Historical_Tender_ID','Award_ID','Award_Value','Bidder_Count']],on='Historical_Tender_ID',how='left');mr=[]
    for (cat,sub),g in j.groupby(['Category','Subcategory'],dropna=False):
        tn=g.Historical_Tender_ID.nunique();an=g.Award_ID.nunique();ml=float(g.Lean_Fit.median());mv=float(g.Award_Value.median()) if g.Award_Value.notna().any() else None;mb=float(g.Bidder_Count.median()) if g.Bidder_Count.notna().any() else None;vc=float(g.Award_Value.notna().mean());bcov=float(g.Bidder_Count.notna().mean());vs=min(100,18*math.log10(max(mv or 1,1))) if mv else 20;cs=50 if mb is None else max(0,100-min(100,mb*12));vol=min(100,18*math.log10(max(tn,1)));ev=min(100,(vc+bcov)*50);score=round(.30*ml+.25*vs+.20*cs+.15*vol+.10*ev,2);mr.append({'Category':cat,'Subcategory':sub,'Tender_Count':tn,'Award_Count':an,'Median_Lean_Fit':ml,'Median_Award_Value_CAD':mv,'Median_Bidder_Count':mb,'Award_Value_Coverage_Pct':round(vc*100,2),'Bidder_Count_Coverage_Pct':round(bcov*100,2),'Market_Attractiveness_Score':score,'Derived_Status':'DERIVED'})
    pd.DataFrame(mr).sort_values(['Market_Attractiveness_Score','Tender_Count'],ascending=[False,False]).to_csv(out/'market_rank.csv',index=False)
    rb=tdf.groupby(['Buyer_ID','Buyer_Name','Category','Subcategory'],dropna=False).agg(Tender_Count=('Historical_Tender_ID','nunique'),Median_Lean_Fit=('Lean_Fit','median')).reset_index();rb=rb[rb.Tender_Count>=2].sort_values(['Tender_Count','Median_Lean_Fit'],ascending=[False,False]);rb['Derived_Status']='DERIVED';rb.to_csv(out/'repeat_buyers.csv',index=False)
    an=j[(j.Lean_Fit.fillna(0)>=70)&((j.Bidder_Count.fillna(999999)<=3)|(j.Award_Value.fillna(0)>=100000))].sort_values(['Lean_Fit','Award_Value'],ascending=[False,False]).head(10000);an['Derived_Status']='DERIVED';an.to_csv(out/'historical_anomalies.csv',index=False)
    q={'version':VERSION,'source':'SEAO official OCDS monthly release packages','window_start':start,'window_end':end,**stats,'canonical_tenders':len(tdf),'award_groups':len(adf),'award_supplier_links':len(bdf),'unique_buyers':int(tdf.Buyer_ID.nunique()),'unique_suppliers':int(bdf.Supplier_ID.nunique()) if len(bdf) else 0,'publication_date_coverage_pct':round(tdf.Publication_Date.notna().mean()*100,2),'deadline_coverage_pct':round(tdf.Deadline.notna().mean()*100,2),'estimated_value_coverage_pct':round(tdf.Official_Estimated_Value.notna().mean()*100,2),'award_link_rate_pct':round((tdf.Award_Link_Status=='LINKED').mean()*100,2),'award_value_coverage_pct':round(adf.Award_Value.notna().mean()*100,2) if len(adf) else 0,'bidder_count_coverage_pct':round(adf.Bidder_Count.notna().mean()*100,2) if len(adf) else 0,'integrity':{'tender_ids_unique':bool(tdf.Historical_Tender_ID.is_unique),'award_ids_unique':bool(adf.Award_ID.is_unique),'bridge_unique':not bdf.duplicated(['Award_ID','Supplier_ID']).any() if len(bdf) else True,'multi_supplier_group_values_not_allocated':bool(bdf.loc[bdf.Award_ID.isin(set(adf.loc[adf.Supplier_Count.fillna(0)>1,'Award_ID'])),'Award_Value_Allocated'].isna().all()) if len(bdf) and len(adf) else True},'notes':['Only monthly SEAO OCDS packages are used; overlapping weekly feeds are excluded.','Canonical tender identity is OCDS ocid. Latest monthly release carrying tender state is selected per ocid.','Awards are keyed by ocid+award.id and updated from the latest release in the window.','Official tender.numberOfTenderers is used as bidder count; no bidder counts are inferred.','Multi-supplier award totals are never copied to supplier bridge rows.']};(out/'data_quality.json').write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding='utf-8');dbp.unlink(missing_ok=True);man={'version':VERSION,'created_at':ingest,'files':{}};
    for p in out.iterdir():
        if p.is_file() and p.name!='run_manifest.json':man['files'][p.name]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (out/'run_manifest.json').write_text(json.dumps(man,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(q,ensure_ascii=False,indent=2))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--raw-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--start',default='2023-08-01');ap.add_argument('--end',default='2026-07-31');a=ap.parse_args();run(a.raw_dir,a.out,a.start,a.end)
if __name__=='__main__':main()
