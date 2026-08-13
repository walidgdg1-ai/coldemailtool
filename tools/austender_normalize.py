#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,re,unicodedata
from pathlib import Path
from datetime import datetime,timezone
UNKNOWN='UNKNOWN'

def clean(v):
    if v is None:return None
    s=re.sub(r'\s+',' ',str(v).strip());return s or None

def norm(v):
    s=clean(v)
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()

def stable(prefix,v):return prefix+'_'+hashlib.sha256(v.encode()).hexdigest()[:20]
def party_id(p):
    for x in p.get('additionalIdentifiers') or []:
        if x.get('id'):return f"{x.get('scheme') or 'ID'}:{x['id']}"
    return p.get('id') or norm(p.get('name'))
def role_party(parties,role):return [p for p in parties if role in (p.get('roles') or [])]
def classify(title,desc,code):
    s=' '.join(x for x in (clean(title),clean(desc)) if x).lower()
    rules=[('Web','Website / CMS',88,['website','web site','cms','web portal']),('Document / data','Digitization / OCR',92,['digitis','digitiz','ocr','scann']),('Language','Translation / transcription',90,['translat','transcri','interpre','subtit']),('Creative / communications','Design / publishing',82,['graphic','design','communication','publishing','video','film','content creation']),('Printing','Print / routing',66,['print','printing','mailing']),('Automation / software','Software / automation',74,['software','automat','data migration','application development','platform','dashboard','saas']),('Monitoring / research','Monitoring / analysis',70,['monitoring','market research','data analysis','evaluation','study'])]
    for cat,sub,score,terms in rules:
        if any(t in s for t in terms):return cat,sub,score
    return ('Other',UNKNOWN,20)
def gz(path,rows):
    fields=list(rows[0]) if rows else []
    with gzip.open(path,'wt',encoding='utf-8',newline='') as f:
        if fields:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',action='append',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    best={}
    for inp in a.input:
        with gzip.open(inp,'rt',encoding='utf-8') as f:
            for line in f:
                x=json.loads(line);cid=str(x['contract_id']);key=(x.get('release_date') or '',x.get('release_id') or '')
                if cid not in best or key>(best[cid][0],best[cid][1]):best[cid]=(key[0],key[1],x)
    tenders=[];awards=[];bridges=[];buyers={};suppliers={}
    for cid in sorted(best):
        x=best[cid][2];r=x['release'];c=x['contract'];parties=r.get('parties') or [];bps=role_party(parties,'procuringEntity');buyer=bps[0] if bps else {}
        bid_raw=party_id(buyer);bid=stable('buy','AUSTENDER|'+str(bid_raw)) if bid_raw else None;bname=clean(buyer.get('name'))
        if bid:buyers[bid]={'Buyer_ID':bid,'Buyer_Name':bname,'Country':'Australia'}
        title=clean(c.get('title'));desc=clean(c.get('description'));items=c.get('items') or [];code=None
        if items:code=((items[0].get('classification') or {}).get('id'))
        cat,sub,lean=classify(title,desc,code)
        val=c.get('value') or {};amount=val.get('amount');currency=val.get('currency') or 'AUD';period=c.get('period') or {};tender=r.get('tender') or {}
        hid=stable('aus','AUSTENDER|'+cid);award_id=str(c.get('awardID') or ((r.get('awards') or [{}])[0].get('id') if r.get('awards') else cid));aid=stable('awd','AUSTENDER|'+award_id)
        pub=(r.get('date') or '')[:10] or None;award_date=clean(c.get('dateSigned')) or clean(((r.get('awards') or [{}])[0]).get('date'));award_date=(award_date or '')[:10] or None
        tenders.append({'Historical_Tender_ID':hid,'Source_System':'AUSTENDER_OCDS','Country':'Australia','Publication_Date':pub,'Deadline':UNKNOWN,'Buyer_ID':bid,'Buyer_Name':bname,'Title':title,'Description':desc,'Main_CPV':code,'Procedure_Type':clean(tender.get('procurementMethodDetails') or tender.get('procurementMethod')),'Contract_Type':UNKNOWN,'Official_Estimated_Value':UNKNOWN,'Currency':currency,'Category':cat,'Subcategory':sub,'Lean_Fit':lean,'Award_Link_Status':'LINKED','Source_Contract_ID':cid,'OCID':r.get('ocid'),'Source_URL':f'https://www.tenders.gov.au/Cn/Show/{cid}' if cid.startswith('CN') else UNKNOWN,'Evidence_Type':'CONTRACT_NOTICE_AWARD_FIRST_AUSTENDER'})
        sps=role_party(parties,'supplier');sp_by_id={p.get('id'):p for p in sps};aw=(r.get('awards') or [{}])[0];refs=aw.get('suppliers') or []
        chosen=[]
        for ref in refs:
            p=sp_by_id.get(ref.get('id')) or ref
            if p.get('name') or p.get('id'):chosen.append(p)
        if not chosen:chosen=sps
        supplier_count=len(chosen) or None
        first_sid=first_name=first_country=None
        for p in chosen:
            raw=party_id(p);sid=stable('sup','AUSTENDER|'+str(raw)) if raw else None
            if not sid:continue
            name=clean(p.get('name'));country=clean((p.get('address') or {}).get('countryName')) or 'Australia'
            suppliers[sid]={'Supplier_ID':sid,'Supplier_Name':name,'Country':country}
            bridges.append({'Award_ID':aid,'Supplier_ID':sid,'Supplier_Name':name,'Relationship':'WINNER','Award_Value_Allocated':amount if supplier_count==1 else None,'Supplier_Country':country,'SME_Status':UNKNOWN})
            if supplier_count==1:first_sid,first_name,first_country=sid,name,country
        awards.append({'Award_ID':aid,'Historical_Tender_ID':hid,'Buyer_ID':bid,'Buyer_Name':bname,'Supplier_ID':first_sid,'Supplier_Name':first_name,'Supplier_Country':first_country,'Award_Date':award_date,'Award_Value':amount,'Currency':currency,'Bidder_Count':UNKNOWN,'Supplier_Count':supplier_count if supplier_count is not None else UNKNOWN,'Value_Field':'contract.value.amount','Procedure_Type':clean(tender.get('procurementMethodDetails') or tender.get('procurementMethod')),'Contract_Start':clean(period.get('startDate')),'Contract_End':clean(period.get('endDate')),'Source_Contract_ID':cid,'OCID':r.get('ocid'),'Evidence_Type':'CONTRACT_NOTICE_AWARD_FIRST_AUSTENDER'})
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);gz(out/'historical_tenders.csv.gz',tenders);gz(out/'awards.csv.gz',awards);gz(out/'award_suppliers.csv.gz',bridges);gz(out/'buyers.csv.gz',list(buyers.values()));gz(out/'suppliers.csv.gz',list(suppliers.values()))
    tids={x['Historical_Tender_ID'] for x in tenders};aids={x['Award_ID'] for x in awards};sids=set(suppliers);supplier_count_by_award={x['Award_ID']:x['Supplier_Count'] for x in awards}
    integrity={'tender_ids_unique':len(tenders)==len(tids),'award_ids_unique':len(awards)==len(aids),'bridge_keys_unique':len(bridges)==len({(x['Award_ID'],x['Supplier_ID']) for x in bridges}),'award_tender_fk':all(x['Historical_Tender_ID'] in tids for x in awards),'bridge_award_fk':all(x['Award_ID'] in aids for x in bridges),'bridge_supplier_fk':all(x['Supplier_ID'] in sids for x in bridges),'multi_supplier_values_not_allocated':all(x['Award_Value_Allocated'] is None for x in bridges if supplier_count_by_award.get(x['Award_ID']) not in (1,'1'))}
    q={'version':'AUSTENDER_CANONICAL_V1','created_at':datetime.now(timezone.utc).isoformat(),'canonical_tenders':len(tenders),'canonical_awards':len(awards),'award_supplier_links':len(bridges),'unique_buyers':len(buyers),'unique_suppliers':len(suppliers),'award_value_coverage_pct':round(100*sum(x['Award_Value'] not in (None,'',UNKNOWN) for x in awards)/max(1,len(awards)),2),'bidder_count_coverage_pct':0.0,'evidence_type':'CONTRACT_NOTICE_AWARD_FIRST_AUSTENDER','integrity':integrity,'status':'PASS' if all(integrity.values()) else 'FAIL'}
    (out/'data_quality.json').write_text(json.dumps(q,indent=2),encoding='utf-8');print(json.dumps(q,indent=2));
    if q['status']!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
