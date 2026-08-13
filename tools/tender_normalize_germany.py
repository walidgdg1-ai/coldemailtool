#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math,re,sqlite3,unicodedata,zipfile
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import xml.etree.ElementTree as ET
import pandas as pd

UNKNOWN='UNKNOWN'
VERSION='DE_EFORMS_CANONICAL_V1'

def local(tag): return tag.split('}',1)[-1]
def clean(x):
    if x is None:return None
    s=re.sub(r'\s+',' ',str(x).strip()); return s or None
def norm(x):
    s=clean(x)
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(gmbh|mbh|ag|kg|ohg|gbr|se|ev|e v|gesellschaft|mit|beschrankter|haftung)\b',' ',s)
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()
def stable(prefix,s):return prefix+'_'+hashlib.sha256(str(s).encode()).hexdigest()[:20]
def txt(e):return clean(e.text) if e is not None else None
def child(e,name):
    if e is None:return None
    for c in list(e):
        if local(c.tag)==name:return c
    return None
def children(e,name):return [c for c in list(e or []) if local(c.tag)==name]
def first_desc(e,name):
    if e is None:return None
    for x in e.iter():
        if local(x.tag)==name:return x
    return None
def descendants(e,name):
    if e is None:return []
    return [x for x in e.iter() if local(x.tag)==name]
def attr_local(e,name):
    if e is None:return None
    for k,v in e.attrib.items():
        if local(k)==name:return v
    return None
def parse_num(v):
    try:
        x=float(str(v).replace(',','.')); return x if math.isfinite(x) else None
    except:return None
def parse_date(v):
    try:return pd.to_datetime(v,errors='coerce',utc=True)
    except:return pd.NaT
def iso(v):
    d=parse_date(v); return d.strftime('%Y-%m-%d') if pd.notna(d) else None

def organization_map(root):
    out={}
    for org in descendants(root,'Organization'):
        company=child(org,'Company')
        if company is None:continue
        pid=None
        pi=child(company,'PartyIdentification')
        if pi is not None:pid=txt(child(pi,'ID'))
        if not pid:continue
        pn=child(company,'PartyName'); name=txt(child(pn,'Name')) if pn is not None else None
        country=None
        pa=child(company,'PostalAddress')
        if pa is not None:
            co=child(pa,'Country')
            country=txt(child(co,'IdentificationCode')) if co is not None else None
        out[pid]={'name':name,'country':country}
    return out

def buyer(root,orgs):
    cp=child(root,'ContractingParty')
    if cp is None:return None,None
    party=child(cp,'Party'); pi=child(party,'PartyIdentification') if party is not None else None
    oid=txt(child(pi,'ID')) if pi is not None else None
    return oid,(orgs.get(oid) or {}).get('name')

def project_fields(root):
    pp=child(root,'ProcurementProject')
    title=txt(child(pp,'Name')) if pp is not None else None
    desc=txt(child(pp,'Description')) if pp is not None else None
    pc=child(pp,'MainCommodityClassification') if pp is not None else None
    cpv=txt(child(pc,'ItemClassificationCode')) if pc is not None else None
    estimate=None; currency=None; estimate_field=None
    if pp is not None:
        priority=['EstimatedOverallContractAmount','EstimatedValueAmount','ValueAmount','MaximumValueAmount','OverallApproximateFrameworkContractsAmount']
        for wanted in priority:
            for e in pp.iter():
                if local(e.tag)==wanted and attr_local(e,'currencyID'):
                    n=parse_num(txt(e))
                    if n is not None:
                        estimate=n; currency=attr_local(e,'currencyID'); estimate_field=wanted; break
            if estimate is not None:break
    return title,desc,cpv,estimate,currency,estimate_field

def deadline(root):
    for p in descendants(root,'TenderSubmissionDeadlinePeriod'):
        d=txt(child(p,'EndDate'))
        if d:return d
    return None

def procedure(root):
    tp=child(root,'TenderingProcess')
    return txt(child(tp,'ProcedureCode')) if tp is not None else None

def classify(title,desc,cpv):
    t=' '.join(x for x in (clean(title),clean(desc)) if x).lower()
    rules=[
      ('Web','Website / CMS',88,[r'website',r'webseite',r'internetauftritt',r'webportal',r'\bcms\b',r'content.management',r'webentwicklung']),
      ('Document / data','Digitization / OCR',92,[r'digitalis',r'\bocr\b',r'scann',r'archiv.*digital',r'datenerfassung',r'indexier']),
      ('Language','Translation / transcription',90,[r'ubersetz',r'übersetz',r'transkrip',r'untertitel',r'dolmetsch',r'lektorat']),
      ('Creative / communications','Design / publishing',82,[r'grafik',r'graphic',r'kommunikation',r'publikation',r'redaktion',r'broschur',r'video',r'filmproduktion',r'content.erstell',r'layout']),
      ('Printing','Print / routing',66,[r'druckerei',r'druckleistung',r'printprodukt',r'versand',r'mailing']),
      ('Automation / software','Software / automation',74,[r'software',r'automatis',r'datenmigration',r'anwendungsentwicklung',r'plattform',r'dashboard',r'it.system',r'saas']),
      ('Monitoring / research','Monitoring / analysis',70,[r'monitoring',r'medienbeobachtung',r'datenanalyse',r'marktforschung',r'evaluation',r'studie'])]
    for cat,sub,score,pats in rules:
        if any(re.search(p,t) for p in pats):return cat,sub,score,score
    if str(cpv or '').startswith(('72','48')):return 'Automation / software','IT services / software',60,60
    return 'Other',UNKNOWN,20,15

def notice_url(notice_id):
    # The source is the official German Open Data export; no record-page URL is fabricated here.
    return None

def parse_notice(data,source_asset,member):
    root=ET.fromstring(data); rtype=local(root.tag)
    nid=txt(child(root,'ID')); folder=txt(child(root,'ContractFolderID')) or nid
    issue=txt(child(root,'IssueDate')); version=txt(child(root,'VersionID'))
    nt=child(root,'NoticeTypeCode'); ncode=txt(nt); nlist=attr_local(nt,'listName')
    orgs=organization_map(root); boid,bname=buyer(root,orgs)
    title,desc,cpv,estimate,currency,estimate_field=project_fields(root)
    proc=procedure(root); dl=deadline(root)
    modification=(nlist=='cont-modif' or (ncode or '').endswith('modif'))
    base={'notice_id':nid,'folder_id':folder,'root_type':rtype,'issue_date':issue,'version_id':version,'notice_code':ncode,'notice_list':nlist,'buyer_ref':boid,'buyer_name':bname,'title':title,'description':desc,'cpv':cpv,'procedure':proc,'deadline':dl,'estimate':estimate,'currency':currency,'estimate_field':estimate_field,'source_asset':source_asset,'source_member':member,'modification':1 if modification else 0}
    awards=[]; bridges=[]
    if rtype!='ContractAwardNotice' or not nid:return base,awards,bridges
    nr=first_desc(root,'NoticeResult')
    if nr is None:return base,awards,bridges
    parties={}
    for tp in children(nr,'TenderingParty'):
        tpid=txt(child(tp,'ID')); ids=[]
        for te in children(tp,'Tenderer'):
            oid=txt(child(te,'ID'))
            if oid:ids.append(oid)
        if tpid:parties[tpid]=ids
    lot_tenders={}
    for lt in children(nr,'LotTender'):
        ltid=txt(child(lt,'ID'))
        if not ltid:continue
        tpe=child(lt,'TenderingParty'); tpid=txt(child(tpe,'ID')) if tpe is not None else None
        tle=child(lt,'TenderLot'); lotid=txt(child(tle,'ID')) if tle is not None else None
        value=None; vcur=None; vfield=None
        lmt=child(lt,'LegalMonetaryTotal')
        pe=child(lmt,'PayableAmount') if lmt is not None else None
        if pe is not None:
            value=parse_num(txt(pe)); vcur=attr_local(pe,'currencyID'); vfield='PayableAmount'
        lot_tenders[ltid]={'party':tpid,'lot':lotid,'value':value,'currency':vcur,'value_field':vfield}
    contracts={}
    for sc in children(nr,'SettledContract'):
        cid=txt(child(sc,'ID'))
        ltd=child(sc,'LotTender'); ltid=txt(child(ltd,'ID')) if ltd is not None else None
        ad=txt(child(sc,'AwardDate')) or txt(child(sc,'IssueDate'))
        if cid:contracts[cid]={'lot_tender':ltid,'award_date':ad}
    nr_total=None; nr_cur=None
    te=child(nr,'TotalAmount')
    if te is not None:nr_total=parse_num(txt(te)); nr_cur=attr_local(te,'currencyID')
    lot_results=children(nr,'LotResult')
    for lr in lot_results:
        rid=txt(child(lr,'ID')) or stable('res',ET.tostring(lr,encoding='unicode'))
        trc=txt(child(lr,'TenderResultCode'))
        lte=child(lr,'LotTender'); ltid=txt(child(lte,'ID')) if lte is not None else None
        tle=child(lr,'TenderLot'); lotid=txt(child(tle,'ID')) if tle is not None else None
        sce=child(lr,'SettledContract'); cid=txt(child(sce,'ID')) if sce is not None else None
        bc=None; ebc=None
        for st in children(lr,'ReceivedSubmissionsStatistics'):
            code=txt(child(st,'StatisticsCode')); num=parse_num(txt(child(st,'StatisticsNumeric')))
            if code=='tenders' and num is not None:bc=int(num)
            elif code=='t-esubm' and num is not None:ebc=int(num)
        lt=lot_tenders.get(ltid,{})
        if not lotid:lotid=lt.get('lot')
        tpid=lt.get('party'); supplier_refs=parties.get(tpid,[])
        snames=[]; scountries=[]
        for oid in supplier_refs:
            o=orgs.get(oid,{})
            if o.get('name'):snames.append(o.get('name')); scountries.append(o.get('country'))
        value=lt.get('value'); vcur=lt.get('currency'); vfield=lt.get('value_field')
        if value is None:
            fvals=descendants(lr,'MaximumValueAmount')
            vals=[e for e in fvals if parse_num(txt(e)) is not None]
            if len(vals)==1:
                value=parse_num(txt(vals[0])); vcur=attr_local(vals[0],'currencyID'); vfield='MaximumValueAmount'
        if value is None and len(lot_results)==1 and nr_total is not None:
            value=nr_total; vcur=nr_cur; vfield='NoticeResult.TotalAmount'
        ad=(contracts.get(cid) or {}).get('award_date')
        if ad and iso(ad) and int(iso(ad)[:4])<2005:ad=None
        aid=stable('awd','DE|'+nid+'|'+rid)
        scope='UNKNOWN'
        if value is not None:
            scope='SUPPLIER_ALLOCATED' if len(snames)==1 else ('GROUP_TOTAL_NOT_ALLOCATED' if len(snames)>1 else 'TENDER_OR_AWARD_TOTAL')
        awards.append({'award_id':aid,'notice_id':nid,'folder_id':folder,'result_id':rid,'lot_id':lotid,'tender_id':ltid,'contract_id':cid,'award_date':ad,'value':value,'currency':vcur,'value_field':vfield,'bidder_count':bc,'electronic_bidder_count':ebc,'supplier_count':len(snames) if snames else None,'supplier_names':json.dumps(snames,ensure_ascii=False),'supplier_countries':json.dumps(scountries,ensure_ascii=False),'winner_status':trc,'modification':1 if modification else 0,'source_asset':source_asset,'source_member':member})
        for name,country in zip(snames,scountries):
            sid=stable('sup','DE|'+(norm(name) or name)+'|'+(country or ''))
            bridges.append({'award_id':aid,'supplier_id':sid,'supplier_name':name,'supplier_country':country,'allocated_value':value if len(snames)==1 else None,'modification':1 if modification else 0})
    return base,awards,bridges

def init_db(c):
    c.executescript('''
    PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=MEMORY;
    CREATE TABLE IF NOT EXISTS notices(notice_id TEXT PRIMARY KEY,folder_id TEXT,root_type TEXT,issue_date TEXT,version_id TEXT,notice_code TEXT,notice_list TEXT,buyer_ref TEXT,buyer_name TEXT,title TEXT,description TEXT,cpv TEXT,procedure TEXT,deadline TEXT,estimate REAL,currency TEXT,estimate_field TEXT,source_asset TEXT,source_member TEXT,modification INTEGER);
    CREATE INDEX IF NOT EXISTS ix_notices_folder ON notices(folder_id);
    CREATE TABLE IF NOT EXISTS awards(award_id TEXT PRIMARY KEY,notice_id TEXT,folder_id TEXT,result_id TEXT,lot_id TEXT,tender_id TEXT,contract_id TEXT,award_date TEXT,value REAL,currency TEXT,value_field TEXT,bidder_count INTEGER,electronic_bidder_count INTEGER,supplier_count INTEGER,supplier_names TEXT,supplier_countries TEXT,winner_status TEXT,modification INTEGER,source_asset TEXT,source_member TEXT);
    CREATE INDEX IF NOT EXISTS ix_awards_folder ON awards(folder_id);
    CREATE TABLE IF NOT EXISTS bridges(award_id TEXT,supplier_id TEXT,supplier_name TEXT,supplier_country TEXT,allocated_value REAL,modification INTEGER,PRIMARY KEY(award_id,supplier_id));
    ''')

def write_csv_gz(path,header,rows):
    with gzip.open(path,'wt',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=header,extrasaction='ignore');w.writeheader()
        for r in rows:w.writerow(r)

def run(raw_dir,out_dir,start,end):
    raw=Path(raw_dir);out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);dbp=out/'work.sqlite';
    if dbp.exists():dbp.unlink()
    conn=sqlite3.connect(dbp);init_db(conn);c=conn.cursor();stats=defaultdict(int);start_ts=pd.Timestamp(start,tz='UTC');end_ts=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)-pd.Timedelta(microseconds=1)
    notice_cols=['notice_id','folder_id','root_type','issue_date','version_id','notice_code','notice_list','buyer_ref','buyer_name','title','description','cpv','procedure','deadline','estimate','currency','estimate_field','source_asset','source_member','modification']
    award_cols=['award_id','notice_id','folder_id','result_id','lot_id','tender_id','contract_id','award_date','value','currency','value_field','bidder_count','electronic_bidder_count','supplier_count','supplier_names','supplier_countries','winner_status','modification','source_asset','source_member']
    bridge_cols=['award_id','supplier_id','supplier_name','supplier_country','allocated_value','modification']
    for zp in sorted(raw.glob('germany_*.zip')):
        stats['source_assets']+=1
        with zipfile.ZipFile(zp) as z:
            for member in z.namelist():
                if not member.lower().endswith('.xml'):continue
                stats['raw_xml']+=1
                try:
                    base,aws,brs=parse_notice(z.read(member),zp.name,member)
                except Exception:
                    stats['parse_errors']+=1;continue
                if not base.get('notice_id'):stats['missing_notice_id']+=1;continue
                d=parse_date(base.get('issue_date'))
                if pd.isna(d) or d<start_ts or d>end_ts:stats['out_of_window']+=1;continue
                vals=[base.get(k) for k in notice_cols]
                c.execute('INSERT OR REPLACE INTO notices VALUES ('+','.join('?'*len(vals))+')',vals)
                for a in aws:
                    vals=[a.get(k) for k in award_cols];c.execute('INSERT OR REPLACE INTO awards VALUES ('+','.join('?'*len(vals))+')',vals)
                for b in brs:
                    vals=[b.get(k) for k in bridge_cols];c.execute('INSERT OR REPLACE INTO bridges VALUES ('+','.join('?'*len(vals))+')',vals)
                if stats['raw_xml']%10000==0:conn.commit();print('parsed',stats['raw_xml'])
        conn.commit();print('asset complete',zp.name,'xml',stats['raw_xml'])
    ingest=datetime.now(timezone.utc).isoformat()
    c.execute('DROP TABLE IF EXISTS selected_tenders')
    c.execute('''CREATE TEMP TABLE selected_tenders AS
      WITH ranked AS (
       SELECT n.*,ROW_NUMBER() OVER(PARTITION BY COALESCE(folder_id,notice_id) ORDER BY CASE root_type WHEN 'ContractNotice' THEN 1 WHEN 'PriorInformationNotice' THEN 2 ELSE 3 END, issue_date DESC, CAST(COALESCE(version_id,'0') AS INTEGER) DESC) rn
       FROM notices n WHERE root_type IN ('ContractNotice','PriorInformationNotice','ContractAwardNotice') AND modification=0)
      SELECT * FROM ranked WHERE rn=1''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_sel_folder ON selected_tenders(folder_id)')
    th=['Historical_Tender_ID','Official_Notice_ID','Procurement_Reference','Title','Buyer_ID','Buyer_Name','Country','Primary_Source_URL','Source_Tier','Publication_Date','Deadline','Category','Subcategory','CPV_NAICS_or_Local_Code','Scope_Summary','Official_Estimated_Value','Currency','Contract_Duration','Award_Criteria','Price_Weight','Quality_Weight','Minimum_Turnover','References_Required','Required_Certifications','Onsite_Requirement','Subcontracting_Status','Tender_Document_URLs','Award_Link_Status','Linked_Award_ID','Automation_Potential','Lean_Fit','Evidence_Confidence','Ingested_At','Source_Record_Count','Source_Platform','Competition_Type','Procedure','Threshold_Level','Directive','Parent_Agreement_ID','Raw_Spend_Category','Raw_CPV_Description','Cancelled_Date','Source_Grain_Status','Source_Asset','Estimate_Field']
    def tender_rows():
        for r in c.execute('SELECT * FROM selected_tenders ORDER BY issue_date'):
            d=dict(zip([x[0] for x in c.description],r));key=d.get('folder_id') or d['notice_id'];tid=stable('ten','DE|'+key);buyer_id=stable('buy','DE|'+(norm(d.get('buyer_name')) or key));cat,sub,auto,lean=classify(d.get('title'),d.get('description'),d.get('cpv'))
            aids=[x[0] for x in conn.execute('SELECT award_id FROM awards WHERE folder_id=? AND modification=0',(d.get('folder_id'),))]
            yield {'Historical_Tender_ID':tid,'Official_Notice_ID':d['notice_id'],'Procurement_Reference':key,'Title':d.get('title'),'Buyer_ID':buyer_id,'Buyer_Name':d.get('buyer_name'),'Country':'Germany','Primary_Source_URL':None,'Source_Tier':'A','Publication_Date':iso(d.get('issue_date')),'Deadline':iso(d.get('deadline')),'Category':cat,'Subcategory':sub,'CPV_NAICS_or_Local_Code':d.get('cpv'),'Scope_Summary':d.get('description') or d.get('title'),'Official_Estimated_Value':d.get('estimate'),'Currency':d.get('currency') or 'EUR','Contract_Duration':None,'Award_Criteria':UNKNOWN,'Price_Weight':None,'Quality_Weight':None,'Minimum_Turnover':UNKNOWN,'References_Required':UNKNOWN,'Required_Certifications':UNKNOWN,'Onsite_Requirement':UNKNOWN,'Subcontracting_Status':UNKNOWN,'Tender_Document_URLs':'[]','Award_Link_Status':'LINKED' if aids else 'NOT_FOUND','Linked_Award_ID':' | '.join(aids) if aids else None,'Automation_Potential':auto,'Lean_Fit':lean,'Evidence_Confidence':98 if d['root_type']=='ContractNotice' else 82,'Ingested_At':ingest,'Source_Record_Count':conn.execute('SELECT COUNT(*) FROM notices WHERE folder_id=?',(d.get('folder_id'),)).fetchone()[0],'Source_Platform':'oeffentlichevergabe.de Open Data eForms','Competition_Type':d.get('notice_code'),'Procedure':d.get('procedure'),'Threshold_Level':None,'Directive':None,'Parent_Agreement_ID':None,'Raw_Spend_Category':None,'Raw_CPV_Description':None,'Cancelled_Date':None,'Source_Grain_Status':'TENDER_NOTICE' if d['root_type']=='ContractNotice' else ('PRE_TENDER_ONLY' if d['root_type']=='PriorInformationNotice' else 'RESULT_ONLY_RECONSTRUCTED'),'Source_Asset':d.get('source_asset'),'Estimate_Field':d.get('estimate_field')}
    write_csv_gz(out/'historical_tenders.csv.gz',th,tender_rows())
    ah=['Award_ID','Historical_Tender_ID','Official_Award_Notice_ID','Contract_ID','Buyer_ID','Supplier_ID','Supplier_Name','Supplier_Country','Award_Date','Award_Value','Currency','Original_Estimated_Value','Bidder_Count','Electronic_Bidder_Count','SME_Winner_Status','Contract_Duration','Renewal_Options','Award_Criteria','Award_Reason_Summary','Primary_Source_URL','Verification_Status','Modification_Value','Last_Updated_At','Award_Group_ID','Award_Value_Scope','Supplier_Count','Source_Record_Count','Lot_ID','Tender_ID','Winner_Status','Award_Value_Field','Source_Asset']
    def award_rows():
        for r in conn.execute('SELECT a.*,n.buyer_name FROM awards a LEFT JOIN notices n ON n.notice_id=a.notice_id WHERE a.modification=0 ORDER BY a.award_date'):
            cols=[x[0] for x in conn.execute('SELECT a.*,n.buyer_name FROM awards a LEFT JOIN notices n ON n.notice_id=a.notice_id WHERE 0').description] if False else None
            # sqlite cursor description belongs to execute cursor, so materialize names here from fixed schema
            names=award_cols+['buyer_name'];d=dict(zip(names,r));key=d.get('folder_id') or d['notice_id'];tid=stable('ten','DE|'+key);buyer_id=stable('buy','DE|'+(norm(d.get('buyer_name')) or key));sn=json.loads(d.get('supplier_names') or '[]');sc=json.loads(d.get('supplier_countries') or '[]');first=sn[0] if len(sn)==1 else None;fc=sc[0] if len(sc)==1 and sc else None;sid=stable('sup','DE|'+(norm(first) or first)+'|'+(fc or '')) if first else None;estrow=conn.execute('SELECT estimate FROM selected_tenders WHERE folder_id=?',(d.get('folder_id'),)).fetchone();est=estrow[0] if estrow else None;scope='UNKNOWN'
            if d.get('value') is not None:scope='SUPPLIER_ALLOCATED' if len(sn)==1 else ('GROUP_TOTAL_NOT_ALLOCATED' if len(sn)>1 else 'TENDER_OR_AWARD_TOTAL')
            yield {'Award_ID':d['award_id'],'Historical_Tender_ID':tid,'Official_Award_Notice_ID':d['notice_id'],'Contract_ID':d.get('contract_id'),'Buyer_ID':buyer_id,'Supplier_ID':sid,'Supplier_Name':first,'Supplier_Country':fc or UNKNOWN,'Award_Date':iso(d.get('award_date')),'Award_Value':d.get('value'),'Currency':d.get('currency') or 'EUR','Original_Estimated_Value':est,'Bidder_Count':d.get('bidder_count'),'Electronic_Bidder_Count':d.get('electronic_bidder_count'),'SME_Winner_Status':UNKNOWN,'Contract_Duration':None,'Renewal_Options':UNKNOWN,'Award_Criteria':UNKNOWN,'Award_Reason_Summary':None,'Primary_Source_URL':None,'Verification_Status':'VERIFIED_PRIMARY_EFORMS','Modification_Value':None,'Last_Updated_At':ingest,'Award_Group_ID':d['award_id'],'Award_Value_Scope':scope,'Supplier_Count':d.get('supplier_count'),'Source_Record_Count':1,'Lot_ID':d.get('lot_id'),'Tender_ID':d.get('tender_id'),'Winner_Status':d.get('winner_status'),'Award_Value_Field':d.get('value_field'),'Source_Asset':d.get('source_asset')}
    write_csv_gz(out/'awards.csv.gz',ah,award_rows())
    bh=['Award_ID','Supplier_ID','Supplier_Name','Relationship','Award_Value_Allocated','Supplier_Country','SME_Status']
    write_csv_gz(out/'award_suppliers.csv.gz',bh,({'Award_ID':r[0],'Supplier_ID':r[1],'Supplier_Name':r[2],'Relationship':'AWARDED_SUPPLIER','Award_Value_Allocated':r[4],'Supplier_Country':r[3] or UNKNOWN,'SME_Status':UNKNOWN} for r in conn.execute('SELECT award_id,supplier_id,supplier_name,supplier_country,allocated_value FROM bridges WHERE modification=0')))
    # buyers
    buyers=defaultdict(lambda:{'tenders':0,'awards':0,'values':[],'bidders':[]})
    for r in pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Buyer_ID','Buyer_Name']).itertuples(index=False):buyers[(r.Buyer_ID,r.Buyer_Name)]['tenders']+=1
    for r in pd.read_csv(out/'awards.csv.gz',usecols=['Buyer_ID','Award_Value','Bidder_Count']).itertuples(index=False):
        for k in list(buyers.keys()):
            if k[0]==r.Buyer_ID:
                q=buyers[k];q['awards']+=1
                if pd.notna(r.Award_Value):q['values'].append(float(r.Award_Value))
                if pd.notna(r.Bidder_Count):q['bidders'].append(float(r.Bidder_Count));break
    buyer_rows=[]
    for (bid,bn),q in buyers.items():buyer_rows.append({'Buyer_ID':bid,'Buyer_Name':bn,'Normalized_Name':norm(bn),'Country':'Germany','Buyer_Type':UNKNOWN,'Primary_Procurement_Portal':'oeffentlichevergabe.de','Observed_Tenders':q['tenders'],'Observed_Awards':q['awards'],'Observed_Award_Value_Total':sum(q['values']) if q['values'] else None,'Median_Award_Value':pd.Series(q['values']).median() if q['values'] else None,'Median_Bidder_Count':pd.Series(q['bidders']).median() if q['bidders'] else None,'Last_Updated_At':ingest})
    pd.DataFrame(buyer_rows).to_csv(out/'buyers.csv.gz',index=False,compression='gzip')
    bdf=pd.read_csv(out/'award_suppliers.csv.gz')
    if len(bdf):
        sf=bdf.groupby(['Supplier_ID','Supplier_Name','Supplier_Country'],dropna=False).agg(Observed_Contracts_Won=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value_Allocated','sum'),Median_Award_Value=('Award_Value_Allocated','median')).reset_index();sf['Normalized_Name']=sf.Supplier_Name.map(norm);sf['Country']=sf.Supplier_Country;sf['Repeat_Wins']=sf.Observed_Contracts_Won;sf['Last_Updated_At']=ingest
    else:sf=pd.DataFrame(columns=['Supplier_ID','Supplier_Name','Supplier_Country','Observed_Contracts_Won','Observed_Award_Value_Total','Median_Award_Value','Normalized_Name','Country','Repeat_Wins','Last_Updated_At'])
    sf.to_csv(out/'suppliers.csv.gz',index=False,compression='gzip')
    # derived market analytics
    tdf=pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Historical_Tender_ID','Category','Subcategory','Buyer_ID','Buyer_Name','Lean_Fit']);adf=pd.read_csv(out/'awards.csv.gz',usecols=['Historical_Tender_ID','Award_ID','Award_Value','Bidder_Count']);j=tdf.merge(adf,on='Historical_Tender_ID',how='left');rows=[]
    for (cat,sub),g in j.groupby(['Category','Subcategory'],dropna=False):
        tn=g.Historical_Tender_ID.nunique();an=g.Award_ID.nunique();ml=float(g.Lean_Fit.median());mv=float(g.Award_Value.median()) if g.Award_Value.notna().any() else None;mb=float(g.Bidder_Count.median()) if g.Bidder_Count.notna().any() else None;vc=float(g.Award_Value.notna().mean());bcov=float(g.Bidder_Count.notna().mean());vs=min(100,18*math.log10(max(mv or 1,1))) if mv else 20;cs=50 if mb is None else max(0,100-min(100,mb*12));vol=min(100,18*math.log10(max(tn,1)));ev=min(100,(vc+bcov)*50);score=round(.30*ml+.25*vs+.20*cs+.15*vol+.10*ev,2);rows.append({'Category':cat,'Subcategory':sub,'Tender_Count':tn,'Award_Count':an,'Median_Lean_Fit':ml,'Median_Award_Value_EUR':mv,'Median_Bidder_Count':mb,'Award_Value_Coverage_Pct':round(vc*100,2),'Bidder_Count_Coverage_Pct':round(bcov*100,2),'Market_Attractiveness_Score':score,'Derived_Status':'DERIVED'})
    pd.DataFrame(rows).sort_values(['Market_Attractiveness_Score','Tender_Count'],ascending=[False,False]).to_csv(out/'market_rank.csv',index=False)
    rb=tdf.groupby(['Buyer_ID','Buyer_Name','Category','Subcategory'],dropna=False).agg(Tender_Count=('Historical_Tender_ID','nunique'),Median_Lean_Fit=('Lean_Fit','median')).reset_index();rb=rb[rb.Tender_Count>=2].sort_values(['Tender_Count','Median_Lean_Fit'],ascending=[False,False]);rb['Derived_Status']='DERIVED';rb.to_csv(out/'repeat_buyers.csv',index=False)
    an=j[(j.Lean_Fit.fillna(0)>=70)&((j.Bidder_Count.fillna(999999)<=3)|(j.Award_Value.fillna(0)>=100000))].sort_values(['Lean_Fit','Award_Value'],ascending=[False,False]).head(10000);an['Derived_Status']='DERIVED';an.to_csv(out/'historical_anomalies.csv',index=False)
    counts={'normalized_tenders':len(tdf),'award_groups':len(adf),'award_supplier_links':len(bdf),'unique_buyers':int(tdf.Buyer_ID.nunique()),'unique_suppliers':int(bdf.Supplier_ID.nunique()) if len(bdf) else 0}
    nnot=conn.execute('SELECT COUNT(*) FROM notices').fetchone()[0];mods=conn.execute('SELECT COUNT(*) FROM notices WHERE modification=1').fetchone()[0]
    q={'version':VERSION,'source':'German official procurement Open Data eForms/UBL monthly exports','window_start':start,'window_end':end,**stats,'unique_source_notices':nnot,'modification_notices_excluded_from_primary_awards':mods,**counts,'publication_date_coverage_pct':round(tdf.Publication_Date.notna().mean()*100,2),'deadline_coverage_pct':round(tdf.Deadline.notna().mean()*100,2),'estimated_value_coverage_pct':round(tdf.Official_Estimated_Value.notna().mean()*100,2),'award_link_rate_pct':round((tdf.Award_Link_Status=='LINKED').mean()*100,2),'award_value_coverage_pct':round(adf.Award_Value.notna().mean()*100,2) if len(adf) else 0,'bidder_count_coverage_pct':round(adf.Bidder_Count.notna().mean()*100,2) if len(adf) else 0,'integrity':{'tender_ids_unique':bool(tdf.Historical_Tender_ID.is_unique),'award_ids_unique':bool(adf.Award_ID.is_unique),'bridge_unique':not bdf.duplicated(['Award_ID','Supplier_ID']).any() if len(bdf) else True,'multi_supplier_group_values_not_allocated':bool(bdf.loc[bdf.Award_ID.isin(set(adf.loc[adf.Supplier_Count.fillna(0)>1,'Award_ID'])),'Award_Value_Allocated'].isna().all()) if len(bdf) and len(adf) else True},'notes':['Canonical tender identity uses ContractFolderID where present.','Awards are emitted at eForms LotResult grain.','Bidder_Count is sourced only from ReceivedSubmissionsStatistics StatisticsCode=tenders.','Contract-modification notices are retained in source census but excluded from primary award analytics.','Multi-supplier award totals are never duplicated onto supplier bridge rows.']}
    (out/'data_quality.json').write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding='utf-8')
    dbp.unlink(missing_ok=True);manifest={'version':VERSION,'created_at':ingest,'window':{'start':start,'end':end},'counts':counts,'files':{}}
    for p in out.iterdir():
        if p.is_file() and p.name!='run_manifest.json':manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (out/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(q,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--raw-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--start',default='2023-08-01');ap.add_argument('--end',default='2026-07-31');a=ap.parse_args();run(a.raw_dir,a.out,a.start,a.end)
if __name__=='__main__':main()
