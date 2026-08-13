#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,gzip,hashlib,io,json,math,re,sqlite3,tarfile,unicodedata
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import xml.etree.ElementTree as ET

UNKNOWN='UNKNOWN'
VERSION='TED_DUAL_STACK_CANONICAL_V1'
PRIMARY_LEGACY={'Contract notice','Contract award notice','Prior information notice without call for competition','Prior information notice with call for competition'}
PRIMARY_EFORMS={'ContractNotice','ContractAwardNotice','PriorInformationNotice'}

def local(tag): return tag.rsplit('}',1)[-1]
def clean(v):
    if v is None:return None
    s=re.sub(r'\s+',' ',str(v).strip());return s or None
def txt(e):return clean(e.text) if e is not None else None
def norm(v):
    s=clean(v)
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()
def stable(prefix,v):return prefix+'_'+hashlib.sha256(str(v).encode()).hexdigest()[:20]
def child(e,name):
    if e is None:return None
    for c in list(e):
        if local(c.tag)==name:return c
    return None
def children(e,name):return [c for c in list(e or []) if local(c.tag)==name]
def desc(e,name):
    if e is None:return None
    for x in e.iter():
        if local(x.tag)==name:return x
    return None
def descs(e,name):return [x for x in e.iter() if local(x.tag)==name] if e is not None else []
def attr(e,name):
    if e is None:return None
    for k,v in e.attrib.items():
        if local(k)==name:return clean(v)
    return None
def num(v):
    try:
        x=float(str(v).replace(',','.'));return x if math.isfinite(x) else None
    except:return None
def iso_date(v):
    s=clean(v)
    if not s:return None
    m=re.search(r'(20\d{2}-\d{2}-\d{2})',s)
    return m.group(1) if m else None
def paragraphs(e):
    if e is None:return None
    vals=[]
    for x in e.iter():
        if local(x.tag) in ('P','Name','Description') and txt(x):vals.append(txt(x))
    return clean(' '.join(dict.fromkeys(vals)))
def direct_text_or_p(e):return txt(e) or paragraphs(e)

def classify(title,desc,cpv):
    s=' '.join(x for x in (clean(title),clean(desc)) if x).lower()
    rules=[('Web','Website / CMS',88,[r'website',r'web site',r'webportal',r'\bcms\b',r'content management']),('Document / data','Digitization / OCR',92,[r'digitalis',r'\bocr\b',r'scann',r'digitiz']),('Language','Translation / transcription',90,[r'translat',r'transcri',r'interpre',r'subtit',r'übersetz',r'ubersetz']),('Creative / communications','Design / publishing',82,[r'graphic',r'design',r'communication',r'publishing',r'video',r'film',r'content creation']),('Printing','Print / routing',66,[r'print',r'printing',r'mailing']),('Automation / software','Software / automation',74,[r'software',r'automat',r'data migration',r'application development',r'platform',r'dashboard',r'saas']),('Monitoring / research','Monitoring / analysis',70,[r'monitoring',r'market research',r'data analysis',r'evaluation',r'study'])]
    for cat,sub,score,pats in rules:
        if any(re.search(p,s) for p in pats):return cat,sub,score
    if str(cpv or '').startswith(('72','48')):return 'Automation / software','IT services / software',60
    return 'Other',UNKNOWN,20

def iter_xml(pkg:Path):
    with tarfile.open(pkg,'r:*') as outer:
        for om in outer.getmembers():
            if not om.isfile():continue
            of=outer.extractfile(om)
            if of is None:continue
            lname=om.name.lower()
            fallback_date=None
            m=re.search(r'(20\d{6})',om.name)
            if m:fallback_date=f'{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}'
            if lname.endswith('.xml'):
                yield om.name,of.read(),fallback_date;continue
            if not lname.endswith(('.tar.gz','.tgz','.tar')):continue
            data=of.read()
            with tarfile.open(fileobj=io.BytesIO(data),mode='r:*') as inner:
                for im in inner.getmembers():
                    if not im.isfile() or not im.name.lower().endswith('.xml'):continue
                    xf=inner.extractfile(im)
                    if xf is None:continue
                    d=fallback_date
                    mm=re.search(r'(20\d{6})',im.name)
                    if mm:d=f'{mm.group(1)[:4]}-{mm.group(1)[4:6]}-{mm.group(1)[6:8]}'
                    yield om.name+'::'+im.name,xf.read(),d

def legacy_address(block):
    if block is None:return {}
    def first(name):return txt(desc(block,name))
    country=desc(block,'COUNTRY');country=attr(country,'VALUE') or txt(country)
    return {'name':first('OFFICIALNAME'),'national_id':first('NATIONALID'),'town':first('TOWN'),'country':country,'email':first('E_MAIL'),'url':first('URL_GENERAL')}

def parse_legacy(root,source_asset,member,fallback_date):
    doc_id=attr(root,'DOC_ID') or txt(desc(root,'NO_DOC_OJS')) or stable('notice',member)
    nd=desc(root,'NOTICE_DATA');ojs=txt(desc(nd,'NO_DOC_OJS')) if nd is not None else None
    form=txt(desc(root,'TD_DOCUMENT_TYPE')) or UNKNOWN
    country_e=desc(nd,'ISO_COUNTRY') if nd is not None else None
    source_country=attr(country_e,'VALUE') or txt(country_e) or UNKNOWN
    cb=desc(root,'CONTRACTING_BODY');ba=desc(cb,'ADDRESS_CONTRACTING_BODY') if cb is not None else None;buyer=legacy_address(ba)
    obj=desc(root,'OBJECT_CONTRACT');title=direct_text_or_p(child(obj,'TITLE')) if obj is not None else None;descr=direct_text_or_p(child(obj,'SHORT_DESCR')) if obj is not None else None
    ref=txt(child(obj,'REFERENCE_NUMBER')) if obj is not None else None
    cpv_e=desc(obj,'CPV_CODE') if obj is not None else None;cpv=attr(cpv_e,'CODE') or txt(cpv_e)
    type_e=child(obj,'TYPE_CONTRACT') if obj is not None else None;contract_type=attr(type_e,'CTYPE') or txt(type_e)
    est=None;est_cur=None
    for tag in ('VAL_ESTIMATED_TOTAL','VAL_TOTAL'):
        e=desc(obj,tag) if obj is not None else None
        if e is not None and num(txt(e)) is not None:
            est=num(txt(e));est_cur=attr(e,'CURRENCY');break
    proc=desc(root,'PROCEDURE');deadline=txt(desc(proc,'DATE_RECEIPT_TENDERS')) if proc is not None else None
    proc_type=None
    if proc is not None:
        for e in list(proc):
            if local(e.tag).startswith('PT_'):proc_type=local(e.tag);break
    pub=fallback_date
    buyer_key=buyer.get('national_id') or norm(buyer.get('name'))
    if buyer_key and ref:proc_key='legacy-ref|'+source_country+'|'+buyer_key+'|'+clean(ref)
    else:proc_key='legacy-notice|'+doc_id
    base={'notice_id':doc_id,'source_notice_id':ojs or doc_id,'procurement_key':proc_key,'schema_generation':'TED_LEGACY_R2','notice_type':form,'publication_date':pub,'source_country':source_country,'buyer_name':buyer.get('name'),'buyer_national_id':buyer.get('national_id'),'title':title,'description':descr,'reference_number':ref,'cpv':cpv,'contract_type':contract_type,'procedure':proc_type,'deadline':deadline,'estimate':est,'currency':est_cur,'source_asset':source_asset,'source_member':member,'source_url':txt(desc(nd,'URI_DOC')) if nd is not None else None,'primary':1 if form in PRIMARY_LEGACY else 0}
    awards=[];bridges=[]
    if form!='Contract award notice':return base,awards,bridges
    for i,ac in enumerate(descs(root,'AWARD_CONTRACT'),1):
        item=attr(ac,'ITEM') or str(i);contract_no=txt(desc(ac,'CONTRACT_NO')) or item;awarded=desc(ac,'AWARDED_CONTRACT')
        award_date=txt(desc(awarded,'DATE_CONCLUSION_CONTRACT')) if awarded is not None else None
        bidder=num(txt(desc(awarded,'NB_TENDERS_RECEIVED'))) if awarded is not None else None
        value=None;cur=None;vfield=None
        if awarded is not None:
            vals=desc(awarded,'VALUES')
            for tag in ('VAL_TOTAL','VAL_ESTIMATED_TOTAL'):
                e=desc(vals,tag) if vals is not None else None
                if e is not None and num(txt(e)) is not None:
                    value=num(txt(e));cur=attr(e,'CURRENCY');vfield=tag;break
        contractors=[]
        if awarded is not None:
            for ce in descs(awarded,'CONTRACTOR'):
                ad=desc(ce,'ADDRESS_CONTRACTOR');x=legacy_address(ad)
                if x.get('name'):contractors.append(x)
        aid=stable('awd','TED|'+doc_id+'|'+item+'|'+contract_no)
        awards.append({'award_id':aid,'notice_id':doc_id,'procurement_key':proc_key,'lot_id':item,'contract_id':contract_no,'award_date':award_date,'value':value,'currency':cur,'value_field':vfield,'bidder_count':int(bidder) if bidder is not None else None,'supplier_count':len(contractors) or None,'source_asset':source_asset,'source_member':member,'schema_generation':'TED_LEGACY_R2'})
        for x in contractors:
            sid=stable('sup','TED|'+source_country+'|'+(x.get('national_id') or norm(x.get('name')))+'|'+(x.get('country') or ''))
            bridges.append({'award_id':aid,'supplier_id':sid,'supplier_name':x.get('name'),'supplier_country':x.get('country'),'allocated_value':value if len(contractors)==1 else None})
    return base,awards,bridges

def org_map(root):
    out={}
    for org in descs(root,'Organization'):
        co=child(org,'Company')
        if co is None:continue
        pi=child(co,'PartyIdentification');oid=txt(child(pi,'ID')) if pi is not None else None
        if not oid:continue
        pn=child(co,'PartyName');name=txt(child(pn,'Name')) if pn is not None else None
        pa=child(co,'PostalAddress');country=None
        if pa is not None:
            c=child(pa,'Country');country=txt(child(c,'IdentificationCode')) if c is not None else None
        out[oid]={'name':name,'country':country}
    return out

def parse_eforms(root,source_asset,member,fallback_date):
    rtype=local(root.tag);nid=txt(child(root,'ID')) or stable('notice',member);folder=txt(child(root,'ContractFolderID')) or nid
    issue=txt(child(root,'RequestedPublicationDate')) or txt(child(root,'IssueDate')) or fallback_date
    nt=child(root,'NoticeTypeCode');notice_code=txt(nt) or rtype;orgs=org_map(root)
    cp=child(root,'ContractingParty');party=child(cp,'Party') if cp is not None else None;pi=child(party,'PartyIdentification') if party is not None else None;boid=txt(child(pi,'ID')) if pi is not None else None;bname=(orgs.get(boid) or {}).get('name');bcountry=(orgs.get(boid) or {}).get('country')
    pp=child(root,'ProcurementProject');title=txt(child(pp,'Name')) if pp is not None else None;descr=txt(child(pp,'Description')) if pp is not None else None
    mc=child(pp,'MainCommodityClassification') if pp is not None else None;cpv=txt(child(mc,'ItemClassificationCode')) if mc is not None else None
    est=None;cur=None
    if pp is not None:
        for wanted in ('EstimatedOverallContractAmount','EstimatedValueAmount','ValueAmount','MaximumValueAmount'):
            for e in pp.iter():
                if local(e.tag)==wanted and num(txt(e)) is not None:
                    est=num(txt(e));cur=attr(e,'currencyID');break
            if est is not None:break
    deadline=None
    for p in descs(root,'TenderSubmissionDeadlinePeriod'):
        deadline=txt(child(p,'EndDate'))
        if deadline:break
    tp=child(root,'TenderingProcess');procedure=txt(child(tp,'ProcedureCode')) if tp is not None else None
    proc_key='eforms-folder|'+folder
    base={'notice_id':nid,'source_notice_id':nid,'procurement_key':proc_key,'schema_generation':'EFORMS_UBL','notice_type':notice_code,'publication_date':issue,'source_country':bcountry or UNKNOWN,'buyer_name':bname,'buyer_national_id':boid,'title':title,'description':descr,'reference_number':folder,'cpv':cpv,'contract_type':None,'procedure':procedure,'deadline':deadline,'estimate':est,'currency':cur,'source_asset':source_asset,'source_member':member,'source_url':None,'primary':1 if rtype in PRIMARY_EFORMS else 0}
    awards=[];bridges=[]
    if rtype!='ContractAwardNotice':return base,awards,bridges
    nr=desc(root,'NoticeResult')
    if nr is None:return base,awards,bridges
    parties={}
    for x in children(nr,'TenderingParty'):
        tpid=txt(child(x,'ID'));ids=[]
        for te in children(x,'Tenderer'):
            oid=txt(child(te,'ID'))
            if oid:ids.append(oid)
        if tpid:parties[tpid]=ids
    lot_tenders={}
    for lt in children(nr,'LotTender'):
        ltid=txt(child(lt,'ID'))
        if not ltid:continue
        tpe=child(lt,'TenderingParty');tpid=txt(child(tpe,'ID')) if tpe is not None else None
        tle=child(lt,'TenderLot');lotid=txt(child(tle,'ID')) if tle is not None else None
        lm=child(lt,'LegalMonetaryTotal');pe=child(lm,'PayableAmount') if lm is not None else None
        lot_tenders[ltid]={'party':tpid,'lot':lotid,'value':num(txt(pe)) if pe is not None else None,'currency':attr(pe,'currencyID') if pe is not None else None}
    contracts={}
    for sc in children(nr,'SettledContract'):
        cid=txt(child(sc,'ID'));ltd=child(sc,'LotTender');ltid=txt(child(ltd,'ID')) if ltd is not None else None
        if cid:contracts[cid]={'lot_tender':ltid,'award_date':txt(child(sc,'AwardDate')) or txt(child(sc,'IssueDate'))}
    total_e=child(nr,'TotalAmount');nr_total=num(txt(total_e)) if total_e is not None else None;nr_cur=attr(total_e,'currencyID') if total_e is not None else None
    lot_results=children(nr,'LotResult')
    for i,lr in enumerate(lot_results,1):
        rid=txt(child(lr,'ID')) or str(i);lte=child(lr,'LotTender');ltid=txt(child(lte,'ID')) if lte is not None else None;tle=child(lr,'TenderLot');lotid=txt(child(tle,'ID')) if tle is not None else None;sce=child(lr,'SettledContract');cid=txt(child(sce,'ID')) if sce is not None else None
        bidder=None
        for st in children(lr,'ReceivedSubmissionsStatistics'):
            if txt(child(st,'StatisticsCode'))=='tenders':
                n=num(txt(child(st,'StatisticsNumeric')));bidder=int(n) if n is not None else None
        lt=lot_tenders.get(ltid,{})
        if not lotid:lotid=lt.get('lot')
        refs=parties.get(lt.get('party'),[]);suppliers=[]
        for oid in refs:
            o=orgs.get(oid,{})
            if o.get('name'):suppliers.append({'id':oid,'name':o.get('name'),'country':o.get('country')})
        value=lt.get('value');vcur=lt.get('currency');vfield='PayableAmount' if value is not None else None
        if value is None and len(lot_results)==1 and nr_total is not None:value=nr_total;vcur=nr_cur;vfield='NoticeResult.TotalAmount'
        aid=stable('awd','TED|'+nid+'|'+rid)
        awards.append({'award_id':aid,'notice_id':nid,'procurement_key':proc_key,'lot_id':lotid,'contract_id':cid,'award_date':(contracts.get(cid) or {}).get('award_date'),'value':value,'currency':vcur,'value_field':vfield,'bidder_count':bidder,'supplier_count':len(suppliers) or None,'source_asset':source_asset,'source_member':member,'schema_generation':'EFORMS_UBL'})
        for x in suppliers:
            sid=stable('sup','TED|'+(x['country'] or '')+'|'+(x['id'] or norm(x['name'])))
            bridges.append({'award_id':aid,'supplier_id':sid,'supplier_name':x['name'],'supplier_country':x['country'],'allocated_value':value if len(suppliers)==1 else None})
    return base,awards,bridges

def parse_xml(data,asset,member,fallback):
    root=ET.fromstring(data);rtype=local(root.tag)
    if rtype=='TED_EXPORT':return parse_legacy(root,asset,member,fallback)
    if rtype in PRIMARY_EFORMS or rtype=='BusinessRegistrationInformationNotice':return parse_eforms(root,asset,member,fallback)
    raise ValueError('unsupported_root:'+rtype)

def init_db(c):
    c.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
    CREATE TABLE notices(notice_id TEXT PRIMARY KEY,source_notice_id TEXT,procurement_key TEXT,schema_generation TEXT,notice_type TEXT,publication_date TEXT,source_country TEXT,buyer_name TEXT,buyer_national_id TEXT,title TEXT,description TEXT,reference_number TEXT,cpv TEXT,contract_type TEXT,procedure TEXT,deadline TEXT,estimate REAL,currency TEXT,source_asset TEXT,source_member TEXT,source_url TEXT,primary_notice INTEGER);
    CREATE INDEX ix_proc ON notices(procurement_key);
    CREATE TABLE awards(award_id TEXT PRIMARY KEY,notice_id TEXT,procurement_key TEXT,lot_id TEXT,contract_id TEXT,award_date TEXT,value REAL,currency TEXT,value_field TEXT,bidder_count INTEGER,supplier_count INTEGER,source_asset TEXT,source_member TEXT,schema_generation TEXT);
    CREATE INDEX ix_awproc ON awards(procurement_key);
    CREATE TABLE bridges(award_id TEXT,supplier_id TEXT,supplier_name TEXT,supplier_country TEXT,allocated_value REAL,PRIMARY KEY(award_id,supplier_id));''')

def run(packages,outdir):
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True);db=out/'work.sqlite';db.unlink(missing_ok=True);con=sqlite3.connect(db);c=con.cursor();init_db(c);stats=defaultdict(int)
    ncols=['notice_id','source_notice_id','procurement_key','schema_generation','notice_type','publication_date','source_country','buyer_name','buyer_national_id','title','description','reference_number','cpv','contract_type','procedure','deadline','estimate','currency','source_asset','source_member','source_url','primary_notice']
    acols=['award_id','notice_id','procurement_key','lot_id','contract_id','award_date','value','currency','value_field','bidder_count','supplier_count','source_asset','source_member','schema_generation'];bcols=['award_id','supplier_id','supplier_name','supplier_country','allocated_value']
    for pkg in packages:
        p=Path(pkg);stats['source_packages']+=1
        for member,data,fallback in iter_xml(p):
            stats['raw_xml']+=1
            try:base,aws,brs=parse_xml(data,p.name,member,fallback)
            except ValueError as e:
                if str(e).startswith('unsupported_root:'):stats['unsupported_root']+=1;continue
                stats['parse_errors']+=1;continue
            except Exception:stats['parse_errors']+=1;continue
            stats['legacy_xml' if base['schema_generation'].startswith('TED_LEGACY') else 'eforms_xml']+=1
            row=[base.get(k if k!='primary_notice' else 'primary') for k in ncols]
            c.execute('INSERT OR REPLACE INTO notices VALUES ('+','.join('?'*len(ncols))+')',row)
            for a in aws:
                c.execute('INSERT OR REPLACE INTO awards VALUES ('+','.join('?'*len(acols))+')',[a.get(k) for k in acols]);stats['award_rows']+=1
            for b in brs:
                c.execute('INSERT OR REPLACE INTO bridges VALUES ('+','.join('?'*len(bcols))+')',[b.get(k) for k in bcols]);stats['bridge_rows']+=1
            if stats['raw_xml']%5000==0:con.commit();print('TED_PARSE_PROGRESS',dict(stats),flush=True)
    con.commit()
    # One canonical procurement per exact linkage key. Earliest primary notice defines publication date; richest fields are selected by length/value presence.
    rows=c.execute('SELECT procurement_key,MIN(publication_date) FROM notices WHERE primary_notice=1 GROUP BY procurement_key').fetchall();tenders=[]
    for pk,pub in rows:
        ns=c.execute('SELECT '+','.join(ncols)+' FROM notices WHERE procurement_key=? AND primary_notice=1 ORDER BY publication_date',(pk,)).fetchall();ds=[dict(zip(ncols,r)) for r in ns]
        def richest(k):
            vals=[x.get(k) for x in ds if x.get(k) not in (None,'',UNKNOWN)];return max(vals,key=lambda z:len(str(z))) if vals else None
        buyer_name=richest('buyer_name');country=richest('source_country') or UNKNOWN;buyer_nat=richest('buyer_national_id');buyer_id=stable('buy','TED|'+country+'|'+(buyer_nat or norm(buyer_name) or pk))
        title=richest('title');description=richest('description');cpv=richest('cpv');cat,sub,lean=classify(title,description,cpv)
        estimates=[x for x in ds if x.get('estimate') is not None];est=estimates[-1]['estimate'] if estimates else None;cur=estimates[-1]['currency'] if estimates else richest('currency')
        aid_count=c.execute('SELECT COUNT(*) FROM awards WHERE procurement_key=?',(pk,)).fetchone()[0]
        hid=stable('ted','TED|'+pk)
        tenders.append({'Historical_Tender_ID':hid,'Source_System':'TED_OFFICIAL_BULK','Country':country,'Procurement_Key':pk,'Publication_Date':pub,'Deadline':richest('deadline'),'Buyer_ID':buyer_id,'Buyer_Name':buyer_name,'Title':title,'Description':description,'Main_CPV':cpv,'Procedure_Type':richest('procedure'),'Contract_Type':richest('contract_type'),'Official_Estimated_Value':est,'Currency':cur,'Category':cat,'Subcategory':sub,'Lean_Fit':lean,'Award_Link_Status':'LINKED' if aid_count else 'UNLINKED','Schema_Generation':richest('schema_generation'),'Reference_Number':richest('reference_number'),'Source_URL':richest('source_url')})
    hid_by_pk={x['Procurement_Key']:x['Historical_Tender_ID'] for x in tenders};buyer_by_pk={x['Procurement_Key']:(x['Buyer_ID'],x['Buyer_Name'],x['Country']) for x in tenders}
    awards=[]
    for r in c.execute('SELECT '+','.join(acols)+' FROM awards'):
        a=dict(zip(acols,r));hid=hid_by_pk.get(a['procurement_key'])
        if not hid:continue
        bid,bname,country=buyer_by_pk[a['procurement_key']]
        bs=c.execute('SELECT supplier_id,supplier_name,supplier_country,allocated_value FROM bridges WHERE award_id=?',(a['award_id'],)).fetchall();first=bs[0] if len(bs)==1 else (None,None,None,None)
        awards.append({'Award_ID':a['award_id'],'Historical_Tender_ID':hid,'Buyer_ID':bid,'Buyer_Name':bname,'Supplier_ID':first[0],'Supplier_Name':first[1],'Supplier_Country':first[2],'Award_Date':iso_date(a['award_date']),'Award_Value':a['value'],'Currency':a['currency'],'Bidder_Count':a['bidder_count'] if a['bidder_count'] is not None else UNKNOWN,'Supplier_Count':a['supplier_count'] if a['supplier_count'] is not None else UNKNOWN,'Value_Field':a['value_field'],'Schema_Generation':a['schema_generation'],'Source_Notice_ID':a['notice_id']})
    bridges=[];suppliers={}
    for aid,sid,sname,scountry,alloc in c.execute('SELECT award_id,supplier_id,supplier_name,supplier_country,allocated_value FROM bridges'):
        if not any(x['Award_ID']==aid for x in awards):continue
        bridges.append({'Award_ID':aid,'Supplier_ID':sid,'Supplier_Name':sname,'Relationship':'WINNER','Award_Value_Allocated':alloc,'Supplier_Country':scountry,'SME_Status':UNKNOWN});suppliers[sid]={'Supplier_ID':sid,'Supplier_Name':sname,'Country':scountry}
    buyers={x['Buyer_ID']:{'Buyer_ID':x['Buyer_ID'],'Buyer_Name':x['Buyer_Name'],'Country':x['Country']} for x in tenders if x['Buyer_Name']}
    def gz(name,rows):
        p=out/name;fields=list(rows[0]) if rows else []
        with gzip.open(p,'wt',encoding='utf-8',newline='') as f:
            if fields:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    gz('historical_tenders.csv.gz',tenders);gz('awards.csv.gz',awards);gz('award_suppliers.csv.gz',bridges);gz('buyers.csv.gz',list(buyers.values()));gz('suppliers.csv.gz',list(suppliers.values()))
    quality={'version':VERSION,'created_at':datetime.now(timezone.utc).isoformat(),'source_stats':dict(stats),'canonical_tenders':len(tenders),'canonical_awards':len(awards),'award_supplier_links':len(bridges),'unique_buyers':len(buyers),'unique_suppliers':len(suppliers),'legacy_tenders':sum(1 for x in tenders if x['Schema_Generation']=='TED_LEGACY_R2'),'eforms_tenders':sum(1 for x in tenders if x['Schema_Generation']=='EFORMS_UBL'),'award_value_coverage_pct':round(100*sum(x['Award_Value'] is not None for x in awards)/max(len(awards),1),2),'bidder_count_coverage_pct':round(100*sum(x['Bidder_Count']!=UNKNOWN for x in awards)/max(len(awards),1),2),'integrity':{'tender_ids_unique':len(tenders)==len({x['Historical_Tender_ID'] for x in tenders}),'award_ids_unique':len(awards)==len({x['Award_ID'] for x in awards}),'bridge_keys_unique':len(bridges)==len({(x['Award_ID'],x['Supplier_ID']) for x in bridges}),'award_tender_fk':all(x['Historical_Tender_ID'] in {t['Historical_Tender_ID'] for t in tenders} for x in awards),'multi_supplier_values_not_allocated':all(x['Award_Value_Allocated'] is None for x in bridges if next((a for a in awards if a['Award_ID']==x['Award_ID']),{}).get('Supplier_Count') not in (1,'1'))}}
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(quality,indent=2,ensure_ascii=False))
    con.close();db.unlink(missing_ok=True);(out/'work.sqlite-wal').unlink(missing_ok=True);(out/'work.sqlite-shm').unlink(missing_ok=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--package',action='append',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();run(a.package,a.out)
if __name__=='__main__':main()
