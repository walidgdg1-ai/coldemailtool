#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,time,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,timezone

BASE='https://api.tenders.gov.au/ocds/findByDates/contractPublished'
UA='PublicTenderIntelligence/1.0 (+research; official public OCDS API)'


def fetch_json(url,retries=7):
    delay=1.0
    for attempt in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=90) as r:
                return json.loads(r.read().decode('utf-8-sig'))
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as e:
            code=getattr(e,'code',None)
            if code in (400,401,403,404): raise
            if attempt==retries-1: raise
            time.sleep(delay);delay=min(delay*2,20)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',required=True,help='YYYY-MM-DD')
    ap.add_argument('--end',required=True,help='YYYY-MM-DD exclusive')
    ap.add_argument('--out',required=True)
    a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    start=a.start+'T00:00:00Z';end=a.end+'T00:00:00Z';url=f'{BASE}/{start}/{end}'
    seen_release=set();contract_latest={};pages=0;releases_seen=0;raw_rows=[]
    while url:
        x=fetch_json(url);pages+=1
        rels=x.get('releases') or []
        if not isinstance(rels,list): raise RuntimeError('releases is not a list')
        for r in rels:
            rid=str(r.get('id') or '')
            if rid and rid in seen_release: continue
            if rid: seen_release.add(rid)
            releases_seen+=1
            rdate=r.get('date') or ''
            for c in r.get('contracts') or []:
                cid=str(c.get('id') or '')
                if not cid: continue
                row={'contract_id':cid,'release_id':rid,'ocid':r.get('ocid'),'release_date':rdate,'release':r,'contract':c}
                old=contract_latest.get(cid)
                if old is None or (rdate, rid)>(old.get('release_date') or '',old.get('release_id') or ''): contract_latest[cid]=row
        nxt=(x.get('links') or {}).get('next')
        if nxt==url: raise RuntimeError('pagination next URL loop')
        url=nxt
        if pages%25==0: print('AUSTENDER_PROGRESS',a.start,a.end,'pages',pages,'releases',releases_seen,'contracts',len(contract_latest),flush=True)
        time.sleep(0.05)
    # Persist only latest release representation of each contract, retaining full source release+contract evidence.
    raw=out/'contracts.jsonl.gz'
    with gzip.open(raw,'wt',encoding='utf-8') as f:
        for cid in sorted(contract_latest):
            f.write(json.dumps(contract_latest[cid],ensure_ascii=False,separators=(',',':'))+'\n')
    sha=hashlib.sha256(raw.read_bytes()).hexdigest()
    q={'version':'AUSTENDER_OCDS_MONTHLY_RAW_V1','created_at':datetime.now(timezone.utc).isoformat(),'start':a.start,'end_exclusive':a.end,'pages':pages,'release_rows_seen':releases_seen,'unique_release_ids':len(seen_release),'unique_contracts':len(contract_latest),'source_endpoint':BASE,'raw_file':raw.name,'sha256':sha,'status':'PASS' if len(contract_latest)>0 else 'EMPTY'}
    (out/'data_quality.json').write_text(json.dumps(q,indent=2),encoding='utf-8')
    print(json.dumps(q,indent=2))

if __name__=='__main__':main()
