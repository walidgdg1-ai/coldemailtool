#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/tender_normalize_germany.py')
s=p.read_text(encoding='utf-8')
old="""    buyers=defaultdict(lambda:{'tenders':0,'awards':0,'values':[],'bidders':[]})
    for r in pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Buyer_ID','Buyer_Name']).itertuples(index=False):buyers[(r.Buyer_ID,r.Buyer_Name)]['tenders']+=1
    for r in pd.read_csv(out/'awards.csv.gz',usecols=['Buyer_ID','Award_Value','Bidder_Count']).itertuples(index=False):
        for k in list(buyers.keys()):
            if k[0]==r.Buyer_ID:
                q=buyers[k];q['awards']+=1
                if pd.notna(r.Award_Value):q['values'].append(float(r.Award_Value))
                if pd.notna(r.Bidder_Count):q['bidders'].append(float(r.Bidder_Count));break
"""
new="""    buyers=defaultdict(lambda:{'tenders':0,'awards':0,'values':[],'bidders':[]}); buyer_key_by_id={}
    for r in pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Buyer_ID','Buyer_Name']).itertuples(index=False):
        k=(r.Buyer_ID,r.Buyer_Name);buyers[k]['tenders']+=1;buyer_key_by_id[r.Buyer_ID]=k
    for r in pd.read_csv(out/'awards.csv.gz',usecols=['Buyer_ID','Award_Value','Bidder_Count']).itertuples(index=False):
        k=buyer_key_by_id.get(r.Buyer_ID)
        if not k: continue
        q=buyers[k];q['awards']+=1
        if pd.notna(r.Award_Value):q['values'].append(float(r.Award_Value))
        if pd.notna(r.Bidder_Count):q['bidders'].append(float(r.Bidder_Count))
"""
if old not in s:
    raise SystemExit('target block not found; refusing unsafe patch')
p.write_text(s.replace(old,new),encoding='utf-8')
print('runtime complexity patch applied')
