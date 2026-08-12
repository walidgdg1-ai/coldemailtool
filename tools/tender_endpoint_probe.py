#!/usr/bin/env python3
import json, requests, re
S=requests.Session(); S.headers.update({'User-Agent':'PublicTenderIntelligence/1.0','Accept':'application/json'})

u='https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages'
p={'updatedFrom':'2023-10-10T00:00:00','updatedTo':'2023-10-11T00:00:00','limit':5}
r=S.get(u,params=p,timeout=90); o=r.json()
print('UK_STATUS',r.status_code)
print('UK_KEYS',list(o.keys()))
print('UK_LINKS',json.dumps(o.get('links'),ensure_ascii=False)[:3000])
print('UK_CURSOR',o.get('cursor'),o.get('nextCursor'))
print('UK_RELEASES',len(o.get('releases',[])))

u='https://www.donneesquebec.ca/recherche/api/3/action/package_show?id=systeme-electronique-dappel-doffres-seao'
r=S.get(u,timeout=90); q=r.json()['result']; resources=q.get('resources',[])
print('QC_STATUS',r.status_code,'RESOURCES',len(resources))
for x in resources:
    n=(x.get('name') or x.get('url') or '')
    if ('mensuel_' in n.lower() or '2023' in n.lower()) and (n.lower().endswith('.json') or '.json' in n.lower()):
        print('QC_RES',json.dumps({'name':x.get('name'),'url':x.get('url'),'format':x.get('format'),'last_modified':x.get('last_modified'),'created':x.get('created')},ensure_ascii=False))
