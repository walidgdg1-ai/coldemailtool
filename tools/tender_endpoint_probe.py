#!/usr/bin/env python3
import json, requests, sys
S=requests.Session(); S.headers.update({'User-Agent':'PublicTenderIntelligence/1.0','Accept':'application/json'})

def uk():
    u='https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages'
    p={'updatedFrom':'2023-10-10T00:00:00','updatedTo':'2023-10-11T00:00:00','limit':5}
    r=S.get(u,params=p,timeout=90); print('UK',r.status_code,r.url); print(r.text[:4000])

def usa():
    u='https://api.usaspending.gov/api/v2/bulk_download/awards/'
    body={'filters':{'prime_award_types':['A','B','C','D'],'date_type':'action_date','date_range':{'start_date':'2023-08-01','end_date':'2023-08-02'}},'file_format':'csv'}
    r=S.post(u,json=body,timeout=90); print('USA',r.status_code); print(r.text[:4000])

def qc():
    candidates=[
      'https://www.donneesquebec.ca/recherche/api/3/action/package_show?id=systeme-electronique-dappel-doffres-seao',
      'https://www.donneesquebec.ca/recherche/fr/api/3/action/package_show?id=systeme-electronique-dappel-doffres-seao',
      'https://www.donneesquebec.ca/recherche/dataset/systeme-electronique-dappel-doffres-seao.json',
    ]
    for u in candidates:
      try:
        r=S.get(u,timeout=90); print('QC',r.status_code,u,r.headers.get('content-type')); print(r.text[:2000])
      except Exception as e: print('QCERR',u,repr(e))

for f in (uk,usa,qc):
    try:f()
    except Exception as e: print('ERR',f.__name__,repr(e))
