#!/usr/bin/env python3
from __future__ import annotations

import argparse,hashlib,json,os,pathlib,shutil,subprocess,tarfile,time,urllib.error,urllib.request,zipfile,gzip
from datetime import datetime,timezone

MONTHS=[(y,m) for y in range(2023,2027) for m in range(1,13) if (y,m)>=(2023,8) and (y,m)<=(2026,7)]
# Current August 2026 OJ S daily editions published through 13 Aug 2026.
DAILIES=[(2026,n) for n in range(147,156)]
VERSION='TED_OFFICIAL_XML_BULK_V1'

def sha256(p:pathlib.Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def download(url:str,dst:pathlib.Path,retries=8):
    tmp=dst.with_suffix(dst.suffix+'.part')
    for a in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'PTIE-public-data-reuser/1.0'})
            with urllib.request.urlopen(req,timeout=180) as r,tmp.open('wb') as f:
                while True:
                    b=r.read(1024*1024)
                    if not b:break
                    f.write(b)
            if tmp.stat().st_size<1000:raise RuntimeError(f'too small: {tmp.stat().st_size}')
            tmp.replace(dst);return
        except Exception as e:
            tmp.unlink(missing_ok=True)
            if a==retries-1:raise
            delay=min(90,3*(2**a));print('DOWNLOAD_RETRY',url,repr(e),'sleep',delay,flush=True);time.sleep(delay)

def inspect_archive(p:pathlib.Path):
    xml=[];kind='unknown';member_count=0
    try:
        with tarfile.open(p,'r:*') as t:
            names=[x.name for x in t.getmembers() if x.isfile()];member_count=len(names);xml=[n for n in names if n.lower().endswith('.xml')];kind='tar'
            return kind,member_count,len(xml),xml[:5]
    except Exception:pass
    try:
        with zipfile.ZipFile(p) as z:
            names=[x.filename for x in z.infolist() if not x.is_dir()];member_count=len(names);xml=[n for n in names if n.lower().endswith('.xml')];kind='zip'
            return kind,member_count,len(xml),xml[:5]
    except Exception:pass
    # Some endpoints advertise application/gzip; support a single gzip member too.
    try:
        with gzip.open(p,'rb') as f:
            head=f.read(256)
        kind='gzip-single';return kind,1,1 if b'<?xml' in head or b'<TED' in head else 0,[]
    except Exception:pass
    raise RuntimeError(f'Unsupported archive format: {p}')

def gh_upload(tag:str,*paths:pathlib.Path):
    for p in paths:subprocess.run(['gh','release','upload',tag,str(p),'--clobber'],check=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--release-tag',required=True);ap.add_argument('--work',default='ted_bulk');ap.add_argument('--checkpoint');args=ap.parse_args()
    work=pathlib.Path(args.work);work.mkdir(parents=True,exist_ok=True)
    cp={'version':VERSION,'completed':{},'status':'IN_PROGRESS','created_at':datetime.now(timezone.utc).isoformat()}
    if args.checkpoint and pathlib.Path(args.checkpoint).exists():
        cp=json.load(open(args.checkpoint,encoding='utf-8'))
        if cp.get('version')!=VERSION:raise RuntimeError('checkpoint version mismatch')
    cpp=work/'ted-official-bulk-checkpoint.json'
    jobs=[]
    for y,m in MONTHS:
        key=f'monthly-{y}-{m:02d}';url=f'https://ted.europa.eu/packages/monthly/{y}-{m}';jobs.append((key,url,'monthly',f'{y}-{m:02d}'))
    for y,n in DAILIES:
        key=f'daily-{y}-{n:05d}';url=f'https://ted.europa.eu/packages/daily/{y}{n:05d}';jobs.append((key,url,'daily',f'{y}-S{n}'))
    for key,url,package_type,period in jobs:
        if key in cp.get('completed',{}):
            print('BULK_SKIP',key,cp['completed'][key].get('xml_count'),flush=True);continue
        p=work/f'ted-{key}.package.gz'
        print('BULK_DOWNLOAD',key,url,flush=True);download(url,p)
        kind,members,xml_count,examples=inspect_archive(p)
        if xml_count<=0:raise RuntimeError(f'{key}: no XML members found')
        manifest={'version':VERSION,'key':key,'package_type':package_type,'period':period,'source_url':url,'archive_kind':kind,'bytes':p.stat().st_size,'sha256':sha256(p),'member_count':members,'xml_count':xml_count,'example_xml_members':examples,'downloaded_at':datetime.now(timezone.utc).isoformat(),'status':'COMPLETE'}
        mp=work/f'ted-{key}.manifest.json';mp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
        gh_upload(args.release_tag,p,mp)
        cp.setdefault('completed',{})[key]={'xml_count':xml_count,'bytes':p.stat().st_size,'sha256':manifest['sha256'],'manifest':mp.name}
        cp['completed_packages']=len(cp['completed']);cp['completed_xml_sum']=sum(int(x['xml_count']) for x in cp['completed'].values());cp['last_completed']=key;cp['updated_at']=datetime.now(timezone.utc).isoformat();cpp.write_text(json.dumps(cp,indent=2),encoding='utf-8');gh_upload(args.release_tag,cpp)
        print('BULK_COMMITTED',key,'xml',xml_count,'bytes',p.stat().st_size,'sum_xml',cp['completed_xml_sum'],flush=True)
        p.unlink(missing_ok=True);mp.unlink(missing_ok=True)
    cp['expected_packages']=len(jobs);cp['status']='COMPLETE' if len(cp['completed'])==len(jobs) else 'PARTIAL';cp['updated_at']=datetime.now(timezone.utc).isoformat();cpp.write_text(json.dumps(cp,indent=2),encoding='utf-8');summary=work/'ted-official-bulk-summary.json';summary.write_text(json.dumps(cp,indent=2),encoding='utf-8');gh_upload(args.release_tag,cpp,summary);print(json.dumps(cp,indent=2))
    if cp['status']!='COMPLETE':raise SystemExit(2)

if __name__=='__main__':main()
