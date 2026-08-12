#!/usr/bin/env python3
import argparse, calendar, gzip, hashlib, json, os, re, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

S=requests.Session()
S.headers.update({'User-Agent':'PublicTenderIntelligence/1.0 (+official-open-data)','Accept':'*/*'})
ROOT=Path(os.environ.get('TENDER_OUT','relay_out')).resolve(); ROOT.mkdir(parents=True,exist_ok=True)
MANIFEST=ROOT/'_manifest.jsonl'
TARGET_START=date(2023,8,1); TARGET_END=date(2026,7,31)


def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def record(status,source,url,path=None,**extra):
    x={'ts':datetime.now(timezone.utc).isoformat(),'status':status,'source':source,'url':url}
    if path and Path(path).exists():
        p=Path(path); x.update(file=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha256(p))
    x.update(extra)
    with MANIFEST.open('a',encoding='utf-8') as f:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    print(json.dumps(x,ensure_ascii=False),flush=True)

def get_file(source,url,dest,params=None,timeout=1800,retries=6):
    dest=Path(dest); dest.parent.mkdir(parents=True,exist_ok=True); tmp=dest.with_suffix(dest.suffix+'.part')
    for i in range(retries):
        try:
            r=S.get(url,params=params,stream=True,timeout=(30,timeout),allow_redirects=True)
            if r.status_code in (429,500,502,503,504):
                time.sleep(min(90,int(r.headers.get('Retry-After',2**(i+1))))); continue
            r.raise_for_status()
            with tmp.open('wb') as f:
                for c in r.iter_content(1024*1024):
                    if c:f.write(c)
            tmp.replace(dest); record('ok',source,r.url,dest,content_type=r.headers.get('content-type')); return dest
        except Exception as e:
            if i==retries-1: record('error',source,url,error=repr(e),params=params); return None
            time.sleep(min(60,2**(i+1)))

def months(start,end):
    y,m=start.year,start.month
    while (y,m)<=(end.year,end.month):
        yield y,m
        m+=1
        if m==13:y,m=y+1,1

def month_bounds(y,m):
    return date(y,m,1),date(y,m,calendar.monthrange(y,m)[1])

CANADA_URLS=[
'https://canadabuys.canada.ca/opendata/pub/newTenderNotice-nouvelAvisAppelOffres.csv',
'https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv',
'https://canadabuys.canada.ca/opendata/pub/tenderNoticeComplete-avisAppelOffresComplet.csv',
'https://canadabuys.canada.ca/opendata/pub/2009-2022-tenderNoticeHistorical-AvisAppelOffresHistorique.csv',
'https://canadabuys.canada.ca/opendata/pub/awardNoticeComplete-avisAttributionComplet.csv',
'https://canadabuys.canada.ca/opendata/pub/2012-2022-awardNoticeHistorical-avisAttributionHistorique.csv',
'https://canadabuys.canada.ca/opendata/pub/contractHistoryComplete-contratsOctroyesComplet.csv',
'https://canadabuys.canada.ca/opendata/pub/2009-2023-contractHistoryHistorical-contratsOctroyesHistorique.csv']

def canada():
    for u in CANADA_URLS:get_file('canada',u,ROOT/Path(urlparse(u).path).name)

def ted(year):
    lo=max(TARGET_START,date(year,1,1)); hi=min(TARGET_END,date(year,12,31))
    if lo>hi:return
    for y,m in months(lo,hi):
        u=f'https://ted.europa.eu/packages/monthly/{y}-{m}'
        get_file('ted',u,ROOT/f'ted_{y}_{m:02d}.tar.gz')

def france():
    base='https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/exports/csv'
    for y,m in months(TARGET_START,TARGET_END):
        a,b=month_bounds(y,m); nxt=b+timedelta(days=1)
        p={'where':f"dateparution >= date'{a.isoformat()}' AND dateparution < date'{nxt.isoformat()}'",'lang':'fr','timezone':'Europe/Paris','use_labels':'false','delimiter':';'}
        get_file('france_boamp',base,ROOT/f'boamp_{y}-{m:02d}.csv',params=p)

def germany():
    base='https://oeffentlichevergabe.de/api/notice-exports'
    for y,m in months(TARGET_START,TARGET_END):
        get_file('germany',base,ROOT/f'germany_{y}-{m:02d}.zip',params={'pubMonth':f'{y}-{m:02d}'})

def quebec():
    meta='https://www.donneesquebec.ca/recherche/api/3/action/package_show?id=systeme-electronique-dappel-doffres-seao'
    r=S.get(meta,timeout=120); r.raise_for_status(); rs=r.json()['result'].get('resources',[])
    # Keep newest version of duplicate resource names.
    best={}
    for x in rs:
        n=(x.get('name') or '').strip(); u=x.get('url')
        if not n or not u or '.json' not in n.lower():continue
        prev=best.get(n)
        if not prev or str(x.get('last_modified') or x.get('created') or '')>str(prev.get('last_modified') or prev.get('created') or ''):best[n]=x
    monthly=[]; weekly=[]
    pat=re.compile(r'(mensuel|hebdo)_(\d{8})_(\d{8})\.json$',re.I)
    for n,x in best.items():
        m=pat.search(n)
        if not m:continue
        a=datetime.strptime(m.group(2),'%Y%m%d').date(); b=datetime.strptime(m.group(3),'%Y%m%d').date()
        if b<TARGET_START or a>TARGET_END:continue
        (monthly if m.group(1).lower()=='mensuel' else weekly).append((a,b,n,x))
    # Prefer normal one-month snapshots. Use broader monthly/consolidated resources only to cover gaps.
    chosen=[]; covered=set()
    normal=sorted([z for z in monthly if (z[1]-z[0]).days<=32],key=lambda z:z[0])
    broad=sorted([z for z in monthly if (z[1]-z[0]).days>32],key=lambda z:z[0])
    for z in normal:
        chosen.append(z)
        d=max(z[0],TARGET_START); e=min(z[1],TARGET_END)
        while d<=e:covered.add(d); d+=timedelta(days=1)
    for z in broad+sorted(weekly,key=lambda z:z[0]):
        d=max(z[0],TARGET_START); e=min(z[1],TARGET_END); need=False; q=d
        while q<=e:
            if q not in covered:need=True; break
            q+=timedelta(days=1)
        if not need:continue
        chosen.append(z)
        while d<=e:covered.add(d); d+=timedelta(days=1)
    record('selection','quebec',meta,resources=len(rs),unique_names=len(best),selected=len(chosen),covered_days=len(covered),target_days=(TARGET_END-TARGET_START).days+1)
    for a,b,n,x in chosen:get_file('quebec',x['url'],ROOT/n)

def uk(year):
    lo=max(TARGET_START,date(year,1,1)); hi=min(TARGET_END,date(year,12,31))
    if lo>hi:return
    base='https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages'
    for y,m in months(lo,hi):
        a,b=month_bounds(y,m); out=ROOT/f'uk_fts_{y}-{m:02d}.packages.jsonl.gz'; pages=rels=0
        url=base; params={'updatedFrom':a.isoformat()+'T00:00:00','updatedTo':b.isoformat()+'T23:59:59','limit':100}
        with gzip.open(out,'wt',encoding='utf-8') as f:
            seen=set()
            while url:
                for attempt in range(6):
                    rr=S.get(url,params=params,timeout=180)
                    if rr.status_code in (429,500,502,503,504):time.sleep(min(90,int(rr.headers.get('Retry-After',2**(attempt+1)))));continue
                    rr.raise_for_status(); break
                o=rr.json(); f.write(json.dumps(o,ensure_ascii=False,separators=(',',':'))+'\n'); pages+=1; rels+=len(o.get('releases',[]))
                nxt=(o.get('links') or {}).get('next')
                if not nxt or nxt in seen:url=None
                else:seen.add(nxt);url=nxt;params=None
                time.sleep(0.03)
        record('ok','uk_fts',base,out,month=f'{y}-{m:02d}',pages=pages,releases=rels)

PROC_TYPES=['A','B','C','D','IDV_A','IDV_B','IDV_B_A','IDV_B_B','IDV_B_C','IDV_C','IDV_D','IDV_E']
def usa_month(year,month):
    a,b=month_bounds(year,month); a=max(a,TARGET_START); b=min(b,TARGET_END)
    if a>b:return
    api='https://api.usaspending.gov/api/v2/bulk_download/awards/'
    body={'filters':{'prime_award_types':PROC_TYPES,'date_type':'action_date','date_range':{'start_date':a.isoformat(),'end_date':b.isoformat()}},'file_format':'csv'}
    r=S.post(api,json=body,timeout=180); r.raise_for_status(); o=r.json(); record('requested','usa_usaspending',api,file_name=o.get('file_name'),status_url=o.get('status_url'),file_url=o.get('file_url'))
    status=o.get('status_url'); file_url=o.get('file_url'); fname=o.get('file_name') or f'usa_contracts_{year}-{month:02d}.zip'
    # Poll generation status until finished, then download official generated ZIP.
    ready=False
    for i in range(240):
        sr=S.get(status,timeout=90); sr.raise_for_status(); st=sr.json(); state=str(st.get('status') or '').lower()
        if state in ('finished','complete','completed','success') or st.get('file_url'):
            file_url=st.get('file_url') or file_url; ready=True; break
        if state in ('failed','error'):
            record('error','usa_usaspending',status,response=st); return
        time.sleep(5)
    if not ready:
        # Generated file URL can become valid even if status naming changes.
        record('poll_end','usa_usaspending',status,attempts=240)
    get_file('usa_usaspending',file_url,ROOT/f'usa_usaspending_{year}-{month:02d}_{fname}')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('source');args=ap.parse_args();s=args.source
    if s=='canada':canada()
    elif s=='france':france()
    elif s=='germany':germany()
    elif s=='quebec':quebec()
    elif s.startswith('ted_'):ted(int(s.split('_')[1]))
    elif s.startswith('uk_'):uk(int(s.split('_')[1]))
    elif s.startswith('usa_'):
        _,y,m=s.split('_');usa_month(int(y),int(m))
    else:raise SystemExit('unknown source '+s)

if __name__=='__main__':main()
