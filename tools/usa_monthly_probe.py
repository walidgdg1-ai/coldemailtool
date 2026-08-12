#!/usr/bin/env python3
import json, requests
u='https://api.usaspending.gov/api/v2/bulk_download/list_monthly_files/'
s=requests.Session(); s.headers.update({'User-Agent':'PublicTenderIntelligence/1.0','Accept':'application/json'})
for fy in (2023,2024,2025,2026,2027):
    r=s.post(u,json={'agency':'all','fiscal_year':fy,'type':'contracts'},timeout=120)
    print('FY',fy,'STATUS',r.status_code)
    if r.ok:
        o=r.json(); files=o.get('monthly_files',[])
        print('COUNT',len(files))
        for x in files[:80]: print(json.dumps(x,ensure_ascii=False))
    else:
        print(r.text[:4000])
