#!/usr/bin/env python3
"""Normalize Belgium public BDA publications into a conservative notice-first warehouse.

Award supplier/value facts are deliberately NOT invented from publication-summary cards. The output
keeps every public publication event plus one deterministic procurement row per procedureId and an
exact TED-reference bridge for overlap-aware downstream joins.
"""
from __future__ import annotations

import argparse,csv,gzip,hashlib,json,re
from collections import defaultdict
from datetime import date
from pathlib import Path

UNKNOWN='UNKNOWN'


def stable(prefix,*parts):
    raw='|'.join('' if x is None else str(x) for x in parts)
    return prefix+'_'+hashlib.sha256(raw.encode()).hexdigest()[:24]


def norm(v):
    return re.sub(r'\s+',' ',str(v or '').strip().lower())


def iso_day(v):
    if not v:return None
    s=str(v)[:10]
    try:return date.fromisoformat(s).isoformat()
    except:return None


def values(v):
    if v is None:return []
    if isinstance(v,list):return [x for x in v if x not in (None,'')]
    return [v]


def pick_i18n(v):
    if v is None:return None
    if isinstance(v,str):return v.strip() or None
    if isinstance(v,list):
        for x in v:
            r=pick_i18n(x)
            if r:return r
        return None
    if isinstance(v,dict):
        for k in ('en','fr','nl','de','EN','FR','NL','DE','value','name','label','title','description'):
            if k in v:
                r=pick_i18n(v[k])
                if r:return r
        for x in v.values():
            r=pick_i18n(x)
            if r:return r
    return str(v) if v not in ('',None) else None


def first(obj,*paths):
    for path in paths:
        cur=obj
        ok=True
        for key in path.split('.'):
            if not isinstance(cur,dict) or key not in cur:ok=False;break
            cur=cur[key]
        if ok and cur not in (None,'',[],{}):return cur
    return None


def code_value(v):
    if v is None:return None
    if isinstance(v,(str,int,float)):return str(v)
    if isinstance(v,dict):
        for k in ('code','value','id','cpvCode'):
            if v.get(k) not in (None,''):return str(v[k])
    return pick_i18n(v)


def refs(v):
    out=[]
    for x in values(v):
        if isinstance(x,dict):
            z=first(x,'referenceNumber','number','value','id') or pick_i18n(x)
        else:z=x
        if z not in (None,''):
            z=str(z).strip()
            if z and z not in out:out.append(z)
    return out


def read_raw(raw_dir:Path,start:date,end:date):
    rows=[];bad=0;seen_events=set();raw_lines=0
    for p in sorted(raw_dir.glob('belgium-public-pages-*.jsonl.gz')):
        with gzip.open(p,'rt',encoding='utf-8') as f:
            for line in f:
                raw_lines+=1
                try:o=json.loads(line);pub=o.get('publication') or {};page=o.get('harvest_page')
                except Exception:bad+=1;continue
                d=iso_day(pub.get('publicationDate'))
                if not d:continue
                dd=date.fromisoformat(d)
                if dd<start or dd>end:continue
                ws=str(pub.get('publicationWorkspaceId') or '').strip()
                eid=ws or stable('pub','BELGIUM',pub.get('procedureId'),pub.get('referenceNumber'),d,pub.get('noticeSubType'))
                if eid in seen_events:continue
                seen_events.add(eid)
                rows.append((pub,page,eid,d))
    return rows,raw_lines,bad


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--raw-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--start',default='2023-08-01');ap.add_argument('--end',default='2026-07-31');args=ap.parse_args()
    raw=Path(args.raw_dir);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    start=date.fromisoformat(args.start);end=date.fromisoformat(args.end)
    events,raw_lines,bad=read_raw(raw,start,end)
    if not events:raise SystemExit('No Belgium BDA publication events in requested window')

    publication_rows=[];by_proc=defaultdict(list);buyers={};ted_overlap=[]
    for pub,page,eid,pub_date in events:
        procedure=str(pub.get('procedureId') or '').strip()
        workspace=str(pub.get('publicationWorkspaceId') or '').strip()
        procurement_key=procedure or ('workspace:'+workspace) or ('event:'+eid)
        org=pub.get('organisation') if isinstance(pub.get('organisation'),dict) else {}
        org_id=str(first(org,'organisationId','id','uuid') or '').strip()
        org_name=pick_i18n(first(org,'name','names','organisationName','officialName')) or pick_i18n(org)
        buyer_id=stable('buy','BELGIUM',org_id or norm(org_name) or procurement_key)
        buyers[buyer_id]={'Buyer_ID':buyer_id,'Buyer_Name':org_name or UNKNOWN,'Organisation_ID':org_id or UNKNOWN,'Country':'BE'}
        dossier=pub.get('dossier') if isinstance(pub.get('dossier'),dict) else {}
        title=pick_i18n(first(dossier,'title','titles','name')) or pick_i18n(first(pub,'title','publicationTitle'))
        description=pick_i18n(first(dossier,'description','descriptions','shortDescription')) or pick_i18n(first(pub,'description'))
        procedure_type=code_value(first(dossier,'procedureType','procedure','procedureTypeCode')) or UNKNOWN
        cpv=code_value(pub.get('cpvMainCode')) or UNKNOWN
        deadline=first(pub,'vaultSubmissionDeadline','submissionDeadline')
        bda_refs=refs(pub.get('publicationReferenceNumbersBDA'))
        ted_refs=refs(pub.get('publicationReferenceNumbersTED'))
        reference=str(pub.get('referenceNumber') or '').strip()
        notice_subtype=str(pub.get('noticeSubType') or '').strip()
        event={
            'Publication_Event_ID':eid,'Procedure_ID':procedure or UNKNOWN,'Publication_Workspace_ID':workspace or UNKNOWN,
            'Publication_Date':pub_date,'Dispatch_Date':iso_day(pub.get('dispatchDate')) or UNKNOWN,'Insertion_Date':iso_day(pub.get('insertionDate')) or UNKNOWN,
            'Buyer_ID':buyer_id,'Buyer_Name':org_name or UNKNOWN,'Reference_Number':reference or UNKNOWN,
            'Notice_SubType':notice_subtype or UNKNOWN,'Publication_Type':str(pub.get('publicationType') or UNKNOWN),
            'Title':title or UNKNOWN,'Description':description or UNKNOWN,'Main_CPV':cpv,'Procedure_Type':procedure_type,
            'Submission_Deadline':str(deadline or UNKNOWN),'TED_Published':str(pub.get('tedPublished')) if pub.get('tedPublished') is not None else UNKNOWN,
            'BDA_Reference_Numbers_JSON':json.dumps(bda_refs,ensure_ascii=False),'TED_Reference_Numbers_JSON':json.dumps(ted_refs,ensure_ascii=False),
            'Source_URL':f'https://www.publicprocurement.be/publication-workspaces/{workspace}' if workspace else 'https://www.publicprocurement.be/bda',
            'Harvest_Page':page,
        }
        publication_rows.append(event);by_proc[procurement_key].append((event,pub))
        for tr in ted_refs:
            ted_overlap.append({'Procedure_ID':procedure or UNKNOWN,'Publication_Event_ID':eid,'TED_Reference_Number':tr,'Linkage':'EXACT_SOURCE_REFERENCE'})

    tenders=[]
    for pk,grp in by_proc.items():
        grp=sorted(grp,key=lambda x:x[0]['Publication_Date'])
        evs=[x[0] for x in grp]
        def richest(field):
            vals=[x.get(field) for x in evs if x.get(field) not in (None,'',UNKNOWN)]
            return max(vals,key=lambda z:len(str(z))) if vals else UNKNOWN
        ted_refs_all=[];bda_refs_all=[]
        for e,_ in grp:
            for r in json.loads(e['TED_Reference_Numbers_JSON']):
                if r not in ted_refs_all:ted_refs_all.append(r)
            for r in json.loads(e['BDA_Reference_Numbers_JSON']):
                if r not in bda_refs_all:bda_refs_all.append(r)
        first_ev=evs[0];last_ev=evs[-1]
        hid=stable('bel','BELGIUM',pk)
        tenders.append({
            'Historical_Tender_ID':hid,'Source_System':'BELGIUM_PUBLIC_BDA','Country':'BE','Procedure_ID':pk,
            'Publication_Date':first_ev['Publication_Date'],'Latest_Publication_Date':last_ev['Publication_Date'],
            'Deadline':richest('Submission_Deadline'),'Buyer_ID':first_ev['Buyer_ID'],'Buyer_Name':richest('Buyer_Name'),
            'Title':richest('Title'),'Description':richest('Description'),'Main_CPV':richest('Main_CPV'),'Procedure_Type':richest('Procedure_Type'),
            'Publication_Event_Count':len(evs),'Latest_Notice_SubType':last_ev['Notice_SubType'],
            'TED_Overlap_Count':len(ted_refs_all),'TED_Reference_Numbers_JSON':json.dumps(ted_refs_all,ensure_ascii=False),
            'BDA_Reference_Numbers_JSON':json.dumps(bda_refs_all,ensure_ascii=False),'Source_URL':last_ev['Source_URL'],
            'Award_Facts_Status':'PUBLICATION_EVENTS_ONLY_NO_SUPPLIER_FACTS_IN_SEARCH_SUMMARY'
        })

    # Deduplicate exact overlap rows.
    ov={ (x['Procedure_ID'],x['Publication_Event_ID'],x['TED_Reference_Number']):x for x in ted_overlap }
    ted_overlap=list(ov.values())

    def write_gz(name,rows):
        p=out/name
        if not rows:return p
        with gzip.open(p,'wt',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)
        return p
    write_gz('historical_tenders.csv.gz',tenders);write_gz('publication_events.csv.gz',publication_rows);write_gz('buyers.csv.gz',list(buyers.values()));write_gz('ted_overlap.csv.gz',ted_overlap)

    tender_ids=[x['Historical_Tender_ID'] for x in tenders];event_ids=[x['Publication_Event_ID'] for x in publication_rows]
    q={
        'source':'Belgium e-Procurement Bulletin of Tenders public BDA','window_start':args.start,'window_end':args.end,
        'raw_lines_read':raw_lines,'raw_parse_errors':bad,'publication_events':len(publication_rows),'canonical_tenders':len(tenders),
        'unique_buyers':len(buyers),'exact_ted_reference_links':len(ted_overlap),'tenders_with_exact_ted_reference':sum(1 for x in tenders if x['TED_Overlap_Count']>0),
        'award_facts_status':'NOT_ASSERTED_FROM_SEARCH_SUMMARY','integrity':{
            'tender_ids_unique':len(tender_ids)==len(set(tender_ids)),'publication_event_ids_unique':len(event_ids)==len(set(event_ids)),
            'publication_buyer_fk':all(x['Buyer_ID'] in buyers for x in publication_rows),
            'no_fuzzy_ted_links':all(x['Linkage']=='EXACT_SOURCE_REFERENCE' for x in ted_overlap)
        }
    }
    q['status']='PASS' if all(q['integrity'].values()) and q['canonical_tenders']>0 else 'FAIL'
    (out/'data_quality.json').write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'schema_version':'BELGIUM_PUBLIC_BDA_V1','source_url':'https://www.publicprocurement.be/bda','data_quality':q,'files':{}}
    for p in out.iterdir():
        if p.is_file():manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (out/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(q,ensure_ascii=False,indent=2))
    if q['status']!='PASS':raise SystemExit(1)

if __name__=='__main__':main()
