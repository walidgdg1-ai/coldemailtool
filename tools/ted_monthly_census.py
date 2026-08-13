#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,gzip,hashlib,json,os,pathlib,subprocess,time,urllib.error,urllib.request
from datetime import date,datetime,timedelta,timezone

API='https://api.ted.europa.eu/v3/notices/search'
FIELDS=['publication-number','publication-date','notice-identifier','notice-title','form-type','notice-type','procedure-identifier','procedure-type','buyer-name','buyer-country','classification-cpv','title-proc','description-proc','estimated-value-proc','estimated-value-cur-proc','result-lot-identifier','result-value-lot','result-value-cur-lot','result-value-notice','result-value-cur-notice','tender-identifier','tender-lot-identifier','tender-value','tender-value-cur','winner-name','winner-country','winner-identifier','winner-decision-date','winner-selection-status','received-submissions-type-code','received-submissions-type-val']
WINDOW_START=date(2023,8,11)
WINDOW_END=date(2026,8,11)
VERSION='TED_MONTHLY_CENSUS_V1'


def sha(p:pathlib.Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def cell(v):
    if v is None:return ''
    if isinstance(v,(dict,list)):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
    return str(v)

def d8(d:date):return d.strftime('%Y%m%d')
def month_ranges():
    cur=date(WINDOW_START.year,WINDOW_START.month,1)
    out=[]
    while cur<=WINDOW_END:
        if cur.month==12:nxt=date(cur.year+1,1,1)
        else:nxt=date(cur.year,cur.month+1,1)
        lo=max(cur,WINDOW_START);hi=min(nxt-timedelta(days=1),WINDOW_END)
        if lo<=hi:out.append((lo,hi))
        cur=nxt
    return out

def request(query,token=None,limit=250,retries=8):
    payload={'query':query,'fields':FIELDS,'paginationMode':'ITERATION','limit':limit}
    if token:payload['iterationNextToken']=token
    body=json.dumps(payload).encode()
    for a in range(retries):
        req=urllib.request.Request(API,data=body,headers={'Content-Type':'application/json','Accept':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=150) as r:
                obj=json.loads(r.read())
                if r.status!=200:raise RuntimeError(f'HTTP {r.status}')
                if (obj.get('notices') or []):return obj
                if int(obj.get('totalNoticeCount') or 0)==0:return obj
                delay=min(60,2*(2**a));print('TED_MONTH_EMPTY_RETRY',a+1,'limit',limit,'timedOut',obj.get('timedOut'),'sleep',delay,flush=True);time.sleep(delay)
        except urllib.error.HTTPError as e:
            msg=e.read().decode('utf-8','replace')
            if e.code in (429,500,502,503,504) and a<retries-1:
                ra=e.headers.get('Retry-After') if e.headers else None
                try:delay=max(2,float(ra))
                except:delay=min(60,2*(2**a))
                print('TED_MONTH_HTTP_RETRY',e.code,a+1,'sleep',delay,flush=True);time.sleep(delay);continue
            raise RuntimeError(f'TED HTTP {e.code}: {msg[:2000]}')
        except Exception as e:
            if a<retries-1:
                delay=min(60,2*(2**a));print('TED_MONTH_NET_RETRY',repr(e),a+1,'sleep',delay,flush=True);time.sleep(delay);continue
            raise
    raise RuntimeError('TED monthly cursor remained empty after bounded retries')

def gh_upload(tag,*paths):
    for p in paths:subprocess.run(['gh','release','upload',tag,str(p),'--clobber'],check=True)

def harvest_month(lo,hi,outdir,tag):
    query=f'form-type = result AND publication-date >= {d8(lo)} AND publication-date <= {d8(hi)} SORT BY publication-date DESC'
    key=f'{lo.isoformat()}_{hi.isoformat()}'
    rawp=outdir/f'ted-result-{key}.raw.jsonl.gz';normp=outdir/f'ted-result-{key}.normalized.csv.gz';manp=outdir/f'ted-result-{key}.manifest.json'
    seen=set();count=0;token=None;expected=None;first_pub=None;last_pub=None;requests=0
    with gzip.open(rawp,'wt',encoding='utf-8',newline='') as rf,gzip.open(normp,'wt',encoding='utf-8',newline='') as nf:
        w=csv.DictWriter(nf,fieldnames=FIELDS+['source_urls_json'],extrasaction='ignore');w.writeheader()
        while True:
            obj=request(query,token,250);requests+=1
            if expected is None:expected=int(obj.get('totalNoticeCount') or 0);print('TED_MONTH_START',key,'expected',expected,flush=True)
            batch=obj.get('notices') or []
            if not batch:
                if expected==0:break
                raise RuntimeError(f'{key}: empty batch before expected total {expected}')
            for n in batch:
                pn=n.get('publication-number') if isinstance(n,dict) else None
                if isinstance(pn,list):pn=pn[0] if pn else None
                if not pn:raise RuntimeError(f'{key}: missing publication-number')
                pn=str(pn)
                if pn in seen:raise RuntimeError(f'{key}: duplicate publication-number {pn}')
                seen.add(pn);pd=n.get('publication-date')
                if first_pub is None:first_pub=pd
                last_pub=pd
                rf.write(json.dumps(n,ensure_ascii=False,separators=(',',':'))+'\n')
                row={k:cell(n.get(k)) for k in FIELDS};row['source_urls_json']=cell(n.get('links') or n.get('urls') or n.get('_links'));w.writerow(row);count+=1
            token=obj.get('iterationNextToken')
            if count>=expected:
                if count!=expected:raise RuntimeError(f'{key}: count {count} != expected {expected}')
                break
            if not token:raise RuntimeError(f'{key}: token ended at {count}/{expected}')
            time.sleep(0.75)
    manifest={'version':VERSION,'range_start':lo.isoformat(),'range_end':hi.isoformat(),'query':query,'source_total_notice_count':expected,'source_record_count':count,'unique_publication_numbers':len(seen),'request_batches':requests,'first_publication_date':first_pub,'last_publication_date':last_pub,'raw_file':{'name':rawp.name,'bytes':rawp.stat().st_size,'sha256':sha(rawp)},'normalized_file':{'name':normp.name,'bytes':normp.stat().st_size,'sha256':sha(normp)},'status':'COMPLETE','created_at':datetime.now(timezone.utc).isoformat()}
    manp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');gh_upload(tag,rawp,normp,manp);print('TED_MONTH_COMMITTED',key,count,flush=True)
    return manifest

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--release-tag',required=True);ap.add_argument('--out',default='ted_monthly');ap.add_argument('--checkpoint');a=ap.parse_args()
    out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    cp={'version':VERSION,'window_start':WINDOW_START.isoformat(),'window_end':WINDOW_END.isoformat(),'completed':{},'status':'IN_PROGRESS'}
    if a.checkpoint and pathlib.Path(a.checkpoint).exists():
        cp=json.load(open(a.checkpoint,encoding='utf-8'))
        if cp.get('version')!=VERSION:raise RuntimeError('TED monthly checkpoint version mismatch')
    cpp=out/'ted-monthly-checkpoint.json'
    for lo,hi in month_ranges():
        key=f'{lo.isoformat()}_{hi.isoformat()}'
        if key in cp.get('completed',{}):
            print('TED_MONTH_SKIP',key,cp['completed'][key]['count'],flush=True);continue
        m=harvest_month(lo,hi,out,a.release_tag)
        cp.setdefault('completed',{})[key]={'count':m['source_record_count'],'manifest':f'ted-result-{key}.manifest.json','sha256':sha(out/f'ted-result-{key}.manifest.json')}
        cp['completed_record_sum']=sum(int(v['count']) for v in cp['completed'].values());cp['last_completed_range']=key;cp['updated_at']=datetime.now(timezone.utc).isoformat();cpp.write_text(json.dumps(cp,ensure_ascii=False,indent=2),encoding='utf-8');gh_upload(a.release_tag,cpp)
        # Keep runner disk bounded after release persistence.
        for suffix in ('raw.jsonl.gz','normalized.csv.gz','manifest.json'):(out/f'ted-result-{key}.{suffix}').unlink(missing_ok=True)
    global_query=f'form-type = result AND publication-date >= {d8(WINDOW_START)} AND publication-date <= {d8(WINDOW_END)} SORT BY publication-date DESC'
    g=request(global_query,None,1);global_total=int(g.get('totalNoticeCount') or 0);summed=sum(int(v['count']) for v in cp['completed'].values())
    cp['global_total_notice_count_readback']=global_total;cp['completed_record_sum']=summed;cp['range_count']=len(cp['completed']);cp['expected_range_count']=len(month_ranges());cp['status']='CENSUS_COMPLETE' if len(cp['completed'])==len(month_ranges()) and summed==global_total else 'RECONCILIATION_REQUIRED';cp['updated_at']=datetime.now(timezone.utc).isoformat();cpp.write_text(json.dumps(cp,ensure_ascii=False,indent=2),encoding='utf-8');gh_upload(a.release_tag,cpp)
    summary=out/'ted-monthly-summary.json';summary.write_text(json.dumps(cp,ensure_ascii=False,indent=2),encoding='utf-8');gh_upload(a.release_tag,summary);print(json.dumps(cp,ensure_ascii=False,indent=2))
    if cp['status']!='CENSUS_COMPLETE':raise SystemExit(2)

if __name__=='__main__':main()
