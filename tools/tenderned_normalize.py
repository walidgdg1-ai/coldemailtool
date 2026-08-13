#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,re,unicodedata
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
UNKNOWN='UNKNOWN'

def clean(v):
    if v is None:return None
    s=re.sub(r'\s+',' ',str(v).strip());return s or None

def norm(v):
    s=clean(v)
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()
def stable(prefix,v):return prefix+'_'+hashlib.sha256(str(v).encode()).hexdigest()[:20]
def dateonly(v):
    s=clean(v);return s[:10] if s and re.match(r'^20\d\d-\d\d-\d\d',s) else None
def num(v):
    try:return float(v)
    except:return None
def gz(path,rows):
    fields=list(rows[0]) if rows else []
    with gzip.open(path,'wt',encoding='utf-8',newline='') as f:
        if fields:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def classify(title,desc,cpv):
    s=' '.join(x for x in (clean(title),clean(desc)) if x).lower()
    rules=[('Web','Website / CMS',88,['website','web site','websiteontwikkeling','cms','webportal']),('Document / data','Digitization / OCR',92,['digitalis','digitiz','ocr','scann']),('Language','Translation / transcription',90,['vertal','translat','transcri','tolk','interpre','subtit']),('Creative / communications','Design / publishing',82,['grafisch','graphic','design','communicatie','communication','publishing','video','film','content']),('Printing','Print / routing',66,['drukwerk','print','printing','mailing']),('Automation / software','Software / automation',74,['software','automat','data migrat','applicatie','application development','platform','dashboard','saas']),('Monitoring / research','Monitoring / analysis',70,['monitoring','marktonderzoek','market research','data analysis','evaluatie','evaluation','onderzoek','study'])]
    for cat,sub,score,terms in rules:
        if any(t in s for t in terms):return cat,sub,score
    if str(cpv or '').startswith(('72','48')):return 'Automation / software','IT services / software',60
    return 'Other',UNKNOWN,20

def bidder_for_lots(release,lots):
    stats=((release.get('bids') or {}).get('statistics') or [])
    acceptable=('bids','validbids','receivedbids','tenders','validtenders','receivedtenders','numberoftenders')
    values=[]
    for st in stats:
        measure=norm(st.get('measure')).replace(' ','')
        if measure not in acceptable:continue
        lot=clean(st.get('relatedLot'))
        if lots and lot and lot not in lots:continue
        x=num(st.get('value'))
        if x is not None:values.append(int(x))
    return max(values) if values else None

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',action='append',required=True);ap.add_argument('--start',default='2023-08-01');ap.add_argument('--end',default='2026-07-01');ap.add_argument('--out',required=True);a=ap.parse_args()
    releases=[];source_counts={}
    for inp in a.input:
        x=json.load(open(inp,encoding='utf-8-sig'));rs=x.get('releases') or []
        source_counts[Path(inp).name]=len(rs)
        for r in rs:
            d=dateonly(r.get('date'))
            if d and a.start<=d<a.end:releases.append(r)
    groups=defaultdict(list)
    for r in releases:
        pk=clean(r.get('ocid')) or ('tenderned-notice|'+str(r.get('id')))
        groups[pk].append(r)
    tenders=[];buyers={};award_best={};bridge_by_award={}
    for pk,rs in groups.items():
        rs=sorted(rs,key=lambda r:(r.get('date') or '',str(r.get('id') or '')))
        tender_rs=[r for r in rs if isinstance(r.get('tender'),dict)] or rs
        def rich_t(k):
            vals=[clean((r.get('tender') or {}).get(k)) for r in tender_rs];vals=[x for x in vals if x]
            return max(vals,key=len) if vals else None
        br={}
        for r in rs:
            b=r.get('buyer') or {}
            if b.get('id') is not None:br['id']=b.get('id')
            if clean(b.get('name')):br['name']=clean(b.get('name'))
        bid_raw=br.get('id') if br.get('id') is not None else norm(br.get('name'))
        bid=stable('buy','TENDERNED|'+str(bid_raw)) if bid_raw not in (None,'') else None
        bname=br.get('name')
        if bid:buyers[bid]={'Buyer_ID':bid,'Buyer_Name':bname,'Country':'Netherlands'}
        title=rich_t('title');desc=rich_t('description');cpv=None;ptype=None;ctype=None;deadline=None;est=None;cur=None;src_url=None;notice_type=None;national_eu=None
        for r in tender_rs:
            t=r.get('tender') or {};cl=t.get('classification') or {}
            if clean(cl.get('id')):cpv=clean(cl.get('id'))
            if clean(t.get('procurementMethodDetails')):ptype=clean(t.get('procurementMethodDetails'))
            if clean(t.get('mainProcurementCategory')):ctype=clean(t.get('mainProcurementCategory'))
            dl=dateonly((t.get('tenderPeriod') or {}).get('endDate')) or dateonly((t.get('registrationPeriod') or {}).get('endDate'))
            if dl:deadline=dl
            v=t.get('value') or {}
            if num(v.get('amount')) is not None:est=num(v.get('amount'));cur=clean(v.get('currency'))
            if clean(t.get('noticeTypeDetails')):notice_type=clean(t.get('noticeTypeDetails'))
            if clean(t.get('nationalOrEuropean')):national_eu=clean(t.get('nationalOrEuropean'))
            for d in t.get('documents') or []:
                if clean(d.get('url')) and (d.get('documentType') in ('tenderNotice','contractAwardNotice') or src_url is None):src_url=clean(d.get('url'))
        cat,sub,lean=classify(title,desc,cpv);hid=stable('tn','TENDERNED|'+pk);award_count=0
        for r in rs:
            party_map={str(p.get('id')):p for p in r.get('parties') or [] if p.get('id') is not None}
            contracts_by_award={str(c.get('awardID')):c for c in r.get('contracts') or [] if c.get('awardID') is not None}
            for aw in r.get('awards') or []:
                raw_aid=str(aw.get('id') or stable('raw',json.dumps(aw,sort_keys=True,ensure_ascii=False)))
                aid=stable('awd','TENDERNED|'+pk+'|'+raw_aid);lots={str(x) for x in aw.get('relatedLots') or []};bc=bidder_for_lots(r,lots)
                av=aw.get('value') or {};mv=aw.get('maximumValue') or {};aval=num(av.get('amount'));acur=clean(av.get('currency'));field='award.value.amount'
                if aval is None and num(mv.get('amount')) is not None:aval=num(mv.get('amount'));acur=clean(mv.get('currency'));field='award.maximumValue.amount'
                refs=aw.get('suppliers') or [];suppliers_for_award=[]
                for ref in refs:
                    p=party_map.get(str(ref.get('id'))) or ref;raw_sid=p.get('id') if p.get('id') is not None else norm(p.get('name'))
                    if raw_sid in (None,''):continue
                    sid=stable('sup','TENDERNED|'+str(raw_sid));name=clean(p.get('name') or ref.get('name'));country=clean((p.get('address') or {}).get('countryName')) or UNKNOWN
                    suppliers_for_award.append((sid,name,country))
                c=contracts_by_award.get(str(aw.get('id'))) or {};ad=dateonly(aw.get('date')) or dateonly(c.get('dateSigned'))
                row={'Award_ID':aid,'Historical_Tender_ID':hid,'Buyer_ID':bid,'Buyer_Name':bname,'Supplier_ID':suppliers_for_award[0][0] if len(suppliers_for_award)==1 else None,'Supplier_Name':suppliers_for_award[0][1] if len(suppliers_for_award)==1 else None,'Supplier_Country':suppliers_for_award[0][2] if len(suppliers_for_award)==1 else None,'Award_Date':ad,'Award_Value':aval if aval is not None else UNKNOWN,'Currency':acur or cur or UNKNOWN,'Bidder_Count':bc if bc is not None else UNKNOWN,'Supplier_Count':len(suppliers_for_award) if suppliers_for_award else UNKNOWN,'Value_Field':field if aval is not None else UNKNOWN,'Source_Notice_ID':r.get('id'),'OCID':pk,'Source_Award_ID':raw_aid,'Evidence_Type':'NOTICE_FIRST_TENDERNED'}
                k=(r.get('date') or '',str(r.get('id') or ''));old=award_best.get(aid)
                if old is None or k>old[0]:award_best[aid]=(k,row);bridge_by_award[aid]=[(sid,name,country,aval if len(suppliers_for_award)==1 else None) for sid,name,country in suppliers_for_award]
                award_count+=1
        pub=min([dateonly(r.get('date')) for r in rs if dateonly(r.get('date'))] or [None])
        tenders.append({'Historical_Tender_ID':hid,'Source_System':'TENDERNED_OCDS','Country':'Netherlands','Procurement_Key':pk,'Publication_Date':pub,'Deadline':deadline or UNKNOWN,'Buyer_ID':bid,'Buyer_Name':bname,'Title':title,'Description':desc,'Main_CPV':cpv,'Procedure_Type':ptype,'Contract_Type':ctype,'Official_Estimated_Value':est if est is not None else UNKNOWN,'Currency':cur or UNKNOWN,'Category':cat,'Subcategory':sub,'Lean_Fit':lean,'Award_Link_Status':'LINKED' if award_count else 'UNLINKED','Notice_Type':notice_type,'National_or_European':national_eu,'Source_URL':src_url,'Evidence_Type':'NOTICE_FIRST_TENDERNED'})
    awards=[v[1] for v in award_best.values()];bridges=[];suppliers={}
    for arow in awards:
        aid=arow['Award_ID']
        for sid,name,country,alloc in bridge_by_award.get(aid,[]):
            suppliers[sid]={'Supplier_ID':sid,'Supplier_Name':name,'Country':country};bridges.append({'Award_ID':aid,'Supplier_ID':sid,'Supplier_Name':name,'Relationship':'WINNER','Award_Value_Allocated':alloc,'Supplier_Country':country,'SME_Status':UNKNOWN})
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);gz(out/'historical_tenders.csv.gz',tenders);gz(out/'awards.csv.gz',awards);gz(out/'award_suppliers.csv.gz',bridges);gz(out/'buyers.csv.gz',list(buyers.values()));gz(out/'suppliers.csv.gz',list(suppliers.values()))
    tids={x['Historical_Tender_ID'] for x in tenders};aids={x['Award_ID'] for x in awards};sids=set(suppliers);sc={x['Award_ID']:x['Supplier_Count'] for x in awards}
    integrity={'tender_ids_unique':len(tenders)==len(tids),'award_ids_unique':len(awards)==len(aids),'bridge_keys_unique':len(bridges)==len({(x['Award_ID'],x['Supplier_ID']) for x in bridges}),'award_tender_fk':all(x['Historical_Tender_ID'] in tids for x in awards),'bridge_award_fk':all(x['Award_ID'] in aids for x in bridges),'bridge_supplier_fk':all(x['Supplier_ID'] in sids for x in bridges),'multi_supplier_values_not_allocated':all(x['Award_Value_Allocated'] is None for x in bridges if sc.get(x['Award_ID']) not in (1,'1'))}
    q={'version':'TENDERNED_CANONICAL_V1','created_at':datetime.now(timezone.utc).isoformat(),'window_start':a.start,'window_end_exclusive':a.end,'source_release_counts':source_counts,'source_releases_in_window':len(releases),'canonical_tenders':len(tenders),'canonical_awards':len(awards),'award_supplier_links':len(bridges),'unique_buyers':len(buyers),'unique_suppliers':len(suppliers),'estimated_value_coverage_pct':round(100*sum(x['Official_Estimated_Value']!=UNKNOWN for x in tenders)/max(1,len(tenders)),2),'award_value_coverage_pct':round(100*sum(x['Award_Value']!=UNKNOWN for x in awards)/max(1,len(awards)),2),'bidder_count_coverage_pct':round(100*sum(x['Bidder_Count']!=UNKNOWN for x in awards)/max(1,len(awards)),2),'evidence_type':'NOTICE_FIRST_TENDERNED','integrity':integrity,'status':'PASS' if all(integrity.values()) else 'FAIL'}
    (out/'data_quality.json').write_text(json.dumps(q,indent=2),encoding='utf-8');print(json.dumps(q,indent=2));
    if q['status']!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
