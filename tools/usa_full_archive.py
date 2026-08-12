#!/usr/bin/env python3
import argparse, hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

S=requests.Session()
S.headers.update({'User-Agent':'PublicTenderIntelligence/1.0 (+official-open-data)','Accept':'*/*'})
API='https://api.usaspending.gov/api/v2/bulk_download/list_monthly_files/'

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('fiscal_year',type=int); args=ap.parse_args(); fy=args.fiscal_year
    out=Path(os.environ.get('TENDER_OUT',f'relay_out/usa_fy{fy}')).resolve(); out.mkdir(parents=True,exist_ok=True)
    r=S.post(API,json={'agency':'all','fiscal_year':fy,'type':'contracts'},timeout=120); r.raise_for_status()
    candidates=[x for x in r.json().get('monthly_files',[]) if x.get('fiscal_year')==fy and x.get('type')=='contracts']
    if len(candidates)!=1: raise RuntimeError(f'Expected exactly one FY{fy} full contracts archive, got {len(candidates)}')
    meta=candidates[0]; url=meta['url']; dest=out/meta['file_name']; tmp=dest.with_suffix(dest.suffix+'.part')
    with S.get(url,stream=True,timeout=(30,3600),allow_redirects=True) as rr:
        rr.raise_for_status(); expected=int(rr.headers.get('content-length') or 0)
        with open(tmp,'wb') as f:
            for chunk in rr.iter_content(8*1024*1024):
                if chunk:f.write(chunk)
    tmp.replace(dest)
    actual=dest.stat().st_size
    if expected and actual!=expected: raise RuntimeError(f'size mismatch expected={expected} actual={actual}')
    manifest={
      'ts':datetime.now(timezone.utc).isoformat(), 'source':'USAspending', 'kind':'contracts_awards_full_fiscal_year',
      'fiscal_year':fy, 'source_api':API, 'source_url':url, 'file':dest.name,
      'bytes':actual, 'sha256':sha256(dest), 'upstream_updated_date':meta.get('updated_date')
    }
    (out/'_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2),flush=True)

if __name__=='__main__': main()
