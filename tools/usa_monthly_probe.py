#!/usr/bin/env python3
import json, requests
u='https://api.usaspending.gov/api/v2/bulk_download/list_monthly_files/'
s=requests.Session(); s.headers.update({'User-Agent':'PublicTenderIntelligence/1.0','Accept':'application/json'})
for fy in (2023,2024,2025,2026):
    r=s.post(u,json={'agency':'all','fiscal_year':fy,'type':'contracts'},timeout=120); r.raise_for_status()
    files=[x for x in r.json().get('monthly_files',[]) if x.get('fiscal_year')==fy]
    print('FY',fy,'FILES',len(files))
    for x in files:
        url=x['url']; h=s.head(url,allow_redirects=True,timeout=120)
        print(json.dumps({'fy':fy,'file_name':x['file_name'],'url':url,'head_status':h.status_code,'content_length':h.headers.get('content-length'),'content_type':h.headers.get('content-type'),'accept_ranges':h.headers.get('accept-ranges')},ensure_ascii=False))
