#!/usr/bin/env python3
from __future__ import annotations

import argparse,gzip,hashlib,io,json,pathlib,subprocess,tarfile,time,urllib.request,zipfile
from datetime import datetime,timezone

MONTHS=[(y,m) for y in range(2023,2027) for m in range(1,13) if (y,m)>=(2023,8) and (y,m)<=(2026,7)]
# August 2026 daily editions needed beyond the last complete monthly package.
DAILIES=[(2026,n) for n in range(147,156)]
VERSION='TED_OFFICIAL_XML_BULK_V2'


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


def _inspect_tar(tf:tarfile.TarFile,prefix:str='',depth:int=0):
    """Count XML recursively without extracting archives to disk.

    TED monthly packages are tar.gz files whose regular-file members are daily
    tar.gz packages; those daily packages contain the actual XML notices.
    """
    if depth>3:raise RuntimeError('TED archive nesting deeper than expected')
    regular=[m for m in tf.getmembers() if m.isfile()]
    xml_count=0;examples=[];nested_archives=0;nested_members=0
    for m in regular:
        lname=m.name.lower()
        label=f'{prefix}{m.name}'
        if lname.endswith('.xml'):
            xml_count+=1
            if len(examples)<8:examples.append(label)
            continue
        if lname.endswith(('.tar.gz','.tgz','.tar')):
            src=tf.extractfile(m)
            if src is None:continue
            payload=src.read()
            try:
                with tarfile.open(fileobj=io.BytesIO(payload),mode='r:*') as inner:
                    c,ex,nested,nmembers=_inspect_tar(inner,prefix=label+'::',depth=depth+1)
                xml_count+=c;examples.extend(ex[:max(0,8-len(examples))]);nested_archives+=1+nested;nested_members+=nmembers
            except tarfile.TarError as e:
                raise RuntimeError(f'Nested TED archive unreadable: {label}: {e}')
    return xml_count,examples,nested_archives,len(regular)+nested_members


def inspect_archive(p:pathlib.Path):
    try:
        with tarfile.open(p,'r:*') as t:
            xml_count,examples,nested_archives,total_regular=_inspect_tar(t)
            kind='tar-with-nested-archives' if nested_archives else 'tar'
            return kind,total_regular,xml_count,examples,nested_archives
    except tarfile.TarError:
        pass
    try:
        with zipfile.ZipFile(p) as z:
            infos=[x for x in z.infolist() if not x.is_dir()]
            xml=[x.filename for x in infos if x.filename.lower().endswith('.xml')]
            return 'zip',len(infos),len(xml),xml[:8],0
    except zipfile.BadZipFile:
        pass
    try:
        with gzip.open(p,'rb') as f:head=f.read(512)
        is_xml=b'<?xml' in head or b'<TED' in head or b'<ContractNotice' in head
        return 'gzip-single',1,1 if is_xml else 0,[],0
    except Exception:
        pass
    raise RuntimeError(f'Unsupported archive format: {p}')


def gh_upload(tag:str,*paths:pathlib.Path):
    for p in paths:subprocess.run(['gh','release','upload',tag,str(p),'--clobber'],check=True)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--release-tag',required=True);ap.add_argument('--work',default='ted_bulk');ap.add_argument('--checkpoint');args=ap.parse_args()
    work=pathlib.Path(args.work);work.mkdir(parents=True,exist_ok=True)
    cp={'version':VERSION,'completed':{},'status':'IN_PROGRESS','created_at':datetime.now(timezone.utc).isoformat()}
    if args.checkpoint and pathlib.Path(args.checkpoint).exists():
        cp=json.load(open(args.checkpoint,encoding='utf-8'))
        # V1 did not successfully commit a package, so only accept same-version checkpoints.
        if cp.get('version')!=VERSION:raise RuntimeError(f'checkpoint version mismatch: {cp.get("version")} != {VERSION}')
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
        kind,members,xml_count,examples,nested_archives=inspect_archive(p)
        if xml_count<=0:raise RuntimeError(f'{key}: no XML members found after recursive archive inspection')
        manifest={'version':VERSION,'key':key,'package_type':package_type,'period':period,'source_url':url,'archive_kind':kind,'bytes':p.stat().st_size,'sha256':sha256(p),'regular_member_count_recursive':members,'nested_archive_count':nested_archives,'xml_count':xml_count,'example_xml_members':examples,'downloaded_at':datetime.now(timezone.utc).isoformat(),'status':'COMPLETE'}
        mp=work/f'ted-{key}.manifest.json';mp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
        gh_upload(args.release_tag,p,mp)
        cp.setdefault('completed',{})[key]={'xml_count':xml_count,'bytes':p.stat().st_size,'sha256':manifest['sha256'],'manifest':mp.name,'nested_archive_count':nested_archives}
        cp['completed_packages']=len(cp['completed']);cp['completed_xml_sum']=sum(int(x['xml_count']) for x in cp['completed'].values());cp['last_completed']=key;cp['updated_at']=datetime.now(timezone.utc).isoformat();cpp.write_text(json.dumps(cp,indent=2),encoding='utf-8');gh_upload(args.release_tag,cpp)
        print('BULK_COMMITTED',key,'xml',xml_count,'nested',nested_archives,'bytes',p.stat().st_size,'sum_xml',cp['completed_xml_sum'],flush=True)
        p.unlink(missing_ok=True);mp.unlink(missing_ok=True)
    cp['expected_packages']=len(jobs);cp['status']='COMPLETE' if len(cp['completed'])==len(jobs) else 'PARTIAL';cp['updated_at']=datetime.now(timezone.utc).isoformat();cpp.write_text(json.dumps(cp,indent=2),encoding='utf-8');summary=work/'ted-official-bulk-summary.json';summary.write_text(json.dumps(cp,indent=2),encoding='utf-8');gh_upload(args.release_tag,cpp,summary);print(json.dumps(cp,indent=2))
    if cp['status']!='COMPLETE':raise SystemExit(2)

if __name__=='__main__':main()
