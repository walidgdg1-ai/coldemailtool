#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

UNKNOWN='UNKNOWN'
def clean(x):
    if pd.isna(x): return None
    s=re.sub(r'\s+',' ',str(x).strip()); return s or None
def norm(x):
    s=clean(x)
    if not s:return ''
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(limited|ltd|plc|incorporated|inc|llc|company|co|the)\b',' ',s)
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()
def stable(prefix,s): return prefix+'_'+hashlib.sha256(str(s).encode()).hexdigest()[:20]
def iso_series(s): return pd.to_datetime(s,errors='coerce',utc=True).dt.strftime('%Y-%m-%d')
def classify(title,desc,code,code_desc):
    t=' '.join(str(x) for x in (title,desc,code_desc) if clean(x)).lower()
    specs=[('Web','Website / CMS',85,[r'website',r'web site',r'\bcms\b',r'web development',r'web support',r'digital portal']),('Document / data','Digitization / OCR',90,[r'digitis',r'digitiz',r'\bocr\b',r'document scanning',r'metadata',r'data entry',r'archive indexing']),('Language','Translation / transcription',88,[r'translat',r'transcri',r'subtit',r'caption',r'locali[sz]ation',r'proofread',r'interpretation service']),('Creative / communications','Design / publishing',80,[r'graphic design',r'brochure',r'annual report',r'publication',r'creative services',r'video edit',r'motion graphic',r'content creation',r'printing']),('Automation / software','Software / automation',72,[r'software development',r'dashboard',r'automation',r'robotic process',r'\brpa\b',r'data migration',r'application development',r'software solution',r'saas',r'information system']),('Monitoring / research','Monitoring / analysis',70,[r'media monitoring',r'monitoring platform',r'monitoring service',r'data analysis',r'research services'])]
    for cat,sub,score,ps in specs:
        if any(re.search(p,t) for p in ps): return cat,sub,score,score
    c=str(code or '')
    if c.startswith(('43','81')) and any(w in t for w in ('software','information technology','computer')): return 'Automation / software','IT services / software',60,60
    return 'Other',clean(code_desc) or UNKNOWN,20,15

def latest_by_key(df,key):
    d=df.copy(); d['_am']=pd.to_numeric(d.get('amendmentNumber-numeroModification'),errors='coerce').fillna(0); d['_pub']=pd.to_datetime(d['publicationDate-datePublication'],errors='coerce',utc=True); return d.sort_values([key,'_am','_pub']).drop_duplicates(key,keep='last')

def run(tender_csv,award_csv,out,start,end):
    out=Path(out); out.mkdir(parents=True,exist_ok=True); ingest=datetime.now(timezone.utc).isoformat(); start_ts=pd.Timestamp(start,tz='UTC'); end_ts=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)-pd.Timedelta(microseconds=1)
    t=pd.read_csv(tender_csv,low_memory=False,encoding='utf-8-sig'); aw=pd.read_csv(award_csv,low_memory=False,encoding='utf-8-sig')
    t['_pub']=pd.to_datetime(t['publicationDate-datePublication'],errors='coerce',utc=True); t=t[(t._pub>=start_ts)&(t._pub<=end_ts)].copy()
    aw['_pub']=pd.to_datetime(aw['publicationDate-datePublication'],errors='coerce',utc=True); aw['_award_date']=pd.to_datetime(aw['contractAwardDate-dateAttributionContrat'],errors='coerce',utc=True); aw=aw[((aw._award_date>=start_ts)&(aw._award_date<=end_ts))|((aw._award_date.isna())&(aw._pub>=start_ts)&(aw._pub<=end_ts))].copy()

    for d in (t,aw):
        d['_sol']=d['solicitationNumber-numeroSollicitation'].map(clean); d['_ref']=d['referenceNumber-numeroReference'].map(clean); d['_buyer']=d['contractingEntityName-nomEntitContractante-eng'].map(clean); d['_buyer']=d['_buyer'].where(d['_buyer'].notna(),d['contractingEntityName-nomEntitContractante-fra'].map(clean)); d['_key']=d['_sol'].where(d['_sol'].notna(),d['_ref']); d['_key']=d['_key'].fillna(d.index.map(lambda x:'row:'+str(x)))+'|'+d['_buyer'].fillna(UNKNOWN).map(norm)
    t=latest_by_key(t,'_key')
    # Keep only awards that can link to a tender in the selected publication window.
    tender_key=set(t._key); aw=aw[aw._key.isin(tender_key)].copy()
    aw['_award_key']=aw['_ref'].where(aw['_ref'].notna(),aw['_sol'].fillna('')+'|'+aw['contractNumber-numeroContrat'].map(clean).fillna('')+'|'+aw['supplierLegalName-nomLegalFournisseur-eng'].map(clean).fillna('')+'|'+aw['_award_date'].astype(str))
    aw=latest_by_key(aw,'_award_key')

    t['_tid']=('CA|'+t._key).map(lambda x:stable('ten',x)); key_tid=dict(zip(t._key,t._tid)); t['_buyer_id']=('CA|'+t._buyer.fillna(UNKNOWN).map(norm)).map(lambda x:stable('buy',x))
    award_by_tender=aw.groupby('_key').size().to_dict()
    t['_title']=t['title-titre-eng'].map(clean); t['_title']=t._title.where(t._title.notna(),t['title-titre-fra'].map(clean)); t['_desc']=t['tenderDescription-descriptionAppelOffres-eng'].map(clean); t['_desc']=t._desc.where(t._desc.notna(),t['tenderDescription-descriptionAppelOffres-fra'].map(clean)); t['_code']=t['unspsc'].map(clean); t['_code']=t._code.where(t._code.notna(),t['gsin-nibs'].map(clean)); t['_code_desc']=t['unspscDescription-eng'].map(clean); t['_code_desc']=t._code_desc.where(t._code_desc.notna(),t['gsinDescription-nibsDescription-eng'].map(clean))
    cls=[classify(a,b,c,d) for a,b,c,d in zip(t._title,t._desc,t._code,t._code_desc)]; t['_cat']=[x[0] for x in cls]; t['_sub']=[x[1] for x in cls]; t['_auto']=[x[2] for x in cls]; t['_lean']=[x[3] for x in cls]
    t['_url']=t['noticeURL-URLavis-eng'].map(clean); t['_url']=t._url.where(t._url.notna(),t['noticeURL-URLavis-fra'].map(clean))
    t['_award_link']=[stable('awdg','CA|'+k) if award_by_tender.get(k,0) else None for k in t._key]
    tenders=pd.DataFrame({'Historical_Tender_ID':t._tid,'Official_Notice_ID':t._ref,'Procurement_Reference':t._sol,'Title':t._title,'Buyer_ID':t._buyer_id,'Buyer_Name':t._buyer,'Country':'Canada','Primary_Source_URL':t._url,'Source_Tier':'A','Publication_Date':t._pub.dt.strftime('%Y-%m-%d'),'Deadline':pd.to_datetime(t['tenderClosingDate-appelOffresDateCloture'],errors='coerce',utc=True).dt.strftime('%Y-%m-%d'),'Category':t._cat,'Subcategory':t._sub,'CPV_NAICS_or_Local_Code':t._code,'Scope_Summary':t._desc,'Official_Estimated_Value':None,'Currency':'CAD','Contract_Duration':None,'Award_Criteria':t['selectionCriteria-criteresSelection-eng'].fillna(UNKNOWN),'Price_Weight':None,'Quality_Weight':None,'Minimum_Turnover':UNKNOWN,'References_Required':UNKNOWN,'Required_Certifications':UNKNOWN,'Onsite_Requirement':UNKNOWN,'Subcontracting_Status':UNKNOWN,'Tender_Document_URLs':t['attachment-piecesJointes-eng'].fillna('[]'),'Award_Link_Status':['LINKED' if award_by_tender.get(k,0) else 'NOT_FOUND' for k in t._key],'Linked_Award_ID':t._award_link,'Automation_Potential':t._auto,'Lean_Fit':t._lean,'Evidence_Confidence':95,'Ingested_At':ingest,'Source_Record_Count':1,'Source_Platform':'CanadaBuys','Competition_Type':t['procurementMethod-methodeApprovisionnement-eng'],'Procedure':t['procurementMethod-methodeApprovisionnement-eng'],'Threshold_Level':None,'Directive':None,'Parent_Agreement_ID':None,'Raw_Spend_Category':t['procurementCategory-categorieApprovisionnement'],'Raw_CPV_Description':t._code_desc,'Cancelled_Date':None})

    aw['_tid']=aw._key.map(key_tid); aw['_buyer_id']=('CA|'+aw._buyer.fillna(UNKNOWN).map(norm)).map(lambda x:stable('buy',x)); aw['_supplier']=aw['supplierLegalName-nomLegalFournisseur-eng'].map(clean); aw['_supplier']=aw._supplier.where(aw._supplier.notna(),aw['supplierLegalName-nomLegalFournisseur-fra'].map(clean)); aw['_supplier_country']=aw['supplierAddressCountry-fournisseurAdressePays-eng'].map(clean); aw['_sid']=('CA|'+aw._supplier.fillna(UNKNOWN).map(norm)+'|'+aw._supplier_country.fillna('').map(norm)).map(lambda x:stable('sup',x)); aw['_aid']=('CA|'+aw._award_key).map(lambda x:stable('awd',x)); total=pd.to_numeric(aw['totalContractValue-valeurTotaleContrat'],errors='coerce'); amount=pd.to_numeric(aw['contractAmount-montantContrat'],errors='coerce'); aw['_value']=total.where(total>0,amount); aw['_currency']=aw['contractCurrency-contratMonnaie'].fillna('CAD')
    awards=pd.DataFrame({'Award_ID':aw._aid,'Historical_Tender_ID':aw._tid,'Official_Award_Notice_ID':aw._ref,'Contract_ID':aw['contractNumber-numeroContrat'],'Buyer_ID':aw._buyer_id,'Supplier_ID':aw._sid,'Supplier_Name':aw._supplier,'Supplier_Country':aw._supplier_country.fillna(UNKNOWN),'Award_Date':aw._award_date.dt.strftime('%Y-%m-%d').where(aw._award_date.notna(),aw._pub.dt.strftime('%Y-%m-%d')),'Award_Value':aw._value,'Currency':aw._currency,'Original_Estimated_Value':None,'Bidder_Count':None,'Electronic_Bidder_Count':None,'SME_Winner_Status':UNKNOWN,'Contract_Duration':None,'Renewal_Options':UNKNOWN,'Award_Criteria':aw['selectionCriteria-criteresSelection-eng'].fillna(UNKNOWN),'Award_Reason_Summary':aw['awardDescription-descriptionAttribution-eng'],'Primary_Source_URL':None,'Verification_Status':'VERIFIED_PRIMARY_DATASET','Modification_Value':None,'Last_Updated_At':ingest,'Award_Group_ID':aw._aid,'Award_Value_Scope':'SUPPLIER_ALLOCATED','Supplier_Count':1,'Source_Record_Count':1})
    bridge=pd.DataFrame({'Award_ID':aw._aid,'Supplier_ID':aw._sid,'Supplier_Name':aw._supplier,'Relationship':'AWARDED_SUPPLIER','Award_Value_Allocated':aw._value})

    buyers=tenders.groupby(['Buyer_ID','Buyer_Name'],dropna=False).agg(Observed_Tenders=('Historical_Tender_ID','size')).reset_index(); ast=awards.groupby('Buyer_ID').agg(Observed_Awards=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value','sum'),Median_Award_Value=('Award_Value','median'),Median_Bidder_Count=('Bidder_Count','median')).reset_index(); buyers=buyers.merge(ast,on='Buyer_ID',how='left'); buyers['Normalized_Name']=buyers.Buyer_Name.map(norm); buyers['Country']='Canada'; buyers['Buyer_Type']=UNKNOWN; buyers['Primary_Procurement_Portal']='CanadaBuys'; buyers['Last_Updated_At']=ingest
    suppliers=bridge[['Supplier_ID','Supplier_Name']].drop_duplicates(); sst=bridge.groupby('Supplier_ID').agg(Observed_Contracts_Won=('Award_ID','nunique'),Observed_Award_Value_Total=('Award_Value_Allocated','sum'),Median_Award_Value=('Award_Value_Allocated','median')).reset_index(); suppliers=suppliers.merge(sst,on='Supplier_ID',how='left'); suppliers['Normalized_Name']=suppliers.Supplier_Name.map(norm); suppliers['Country']=UNKNOWN; suppliers['Repeat_Wins']=suppliers.Observed_Contracts_Won; suppliers['Last_Updated_At']=ingest
    for frame,name in [(tenders,'historical_tenders.csv.gz'),(awards,'awards.csv.gz'),(bridge,'award_suppliers.csv.gz'),(buyers,'buyers.csv.gz'),(suppliers,'suppliers.csv.gz')]: frame.to_csv(out/name,index=False,compression='gzip')
    q={'source':'CanadaBuys complete tender + award notices','raw_tender_rows':int(len(pd.read_csv(tender_csv,usecols=['referenceNumber-numeroReference']))),'raw_award_rows':int(len(pd.read_csv(award_csv,usecols=['referenceNumber-numeroReference']))),'window_tenders':len(tenders),'linked_tenders':int((tenders.Award_Link_Status=='LINKED').sum()),'award_rows':len(awards),'unique_buyers':int(tenders.Buyer_ID.nunique()),'unique_suppliers':int(bridge.Supplier_ID.nunique()),'publication_date_coverage_pct':round(tenders.Publication_Date.notna().mean()*100,2),'deadline_coverage_pct':round(tenders.Deadline.notna().mean()*100,2),'award_link_rate_pct':round((tenders.Award_Link_Status=='LINKED').mean()*100,2),'award_value_coverage_pct':round(awards.Award_Value.notna().mean()*100,2) if len(awards) else 0,'bidder_count_coverage_pct':0.0,'classification_code_coverage_pct':round(tenders.CPV_NAICS_or_Local_Code.notna().mean()*100,2),'notes':['Latest amendment retained per tender/award natural key.','Awards link only by explicit shared solicitation/reference natural key; unmatched awards are not forced.','CanadaBuys award contract amounts are supplier-allocated values; bidder counts are unavailable in this export and remain UNKNOWN.']}; (out/'data_quality.json').write_text(json.dumps(q,indent=2),encoding='utf-8'); print(json.dumps(q,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--tenders',required=True); p.add_argument('--awards',required=True); p.add_argument('--out',required=True); p.add_argument('--start',default='2023-08-01'); p.add_argument('--end',default='2026-07-31'); a=p.parse_args(); run(a.tenders,a.awards,a.out,a.start,a.end)
