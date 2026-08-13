#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/tender_normalize_germany.py')
s=p.read_text(encoding='utf-8')

# Official German monthly exports are partitioned by requested publication date,
# which can differ from the document IssueDate by days/weeks around month boundaries.
old_date="nid=txt(child(root,'ID')); folder=txt(child(root,'ContractFolderID')) or nid\n    issue=txt(child(root,'IssueDate')); version=txt(child(root,'VersionID'))"
new_date="nid=txt(child(root,'ID')); folder=txt(child(root,'ContractFolderID')) or nid\n    issue=txt(child(root,'RequestedPublicationDate')) or txt(child(root,'IssueDate')); version=txt(child(root,'VersionID'))"
if old_date not in s:
    raise SystemExit('publication date target not found; refusing unsafe patch')
s=s.replace(old_date,new_date,1)

# eForms commonly serializes a DATE (not datetime) as e.g. 2026-07-08+02:00.
# pandas treats this XML Schema lexical form inconsistently and previously coerced most
# RequestedPublicationDate values to NaT, falsely marking >800k records out of window.
old_parse="""def parse_date(v):
    try:return pd.to_datetime(v,errors='coerce',utc=True)
    except:return pd.NaT
"""
new_parse="""def parse_date(v):
    try:
        if v is None:return pd.NaT
        sv=str(v).strip()
        m=re.fullmatch(r'(\\d{4}-\\d{2}-\\d{2})(?:Z|[+-]\\d{2}:\\d{2})',sv)
        if m: sv=m.group(1)
        return pd.to_datetime(sv,errors='coerce',utc=True)
    except:return pd.NaT
"""
if old_parse not in s:
    raise SystemExit('parse_date target not found; refusing unsafe patch')
s=s.replace(old_parse,new_parse,1)

# Avoid O(number_of_awards × number_of_buyers) post-processing.
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
    for r in pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Buyer_ID','Buyer_Name'],low_memory=False).itertuples(index=False):
        k=(r.Buyer_ID,r.Buyer_Name);buyers[k]['tenders']+=1;buyer_key_by_id[r.Buyer_ID]=k
    for r in pd.read_csv(out/'awards.csv.gz',usecols=['Buyer_ID','Award_Value','Bidder_Count'],low_memory=False).itertuples(index=False):
        k=buyer_key_by_id.get(r.Buyer_ID)
        if not k: continue
        q=buyers[k];q['awards']+=1
        if pd.notna(r.Award_Value):q['values'].append(float(r.Award_Value))
        if pd.notna(r.Bidder_Count):q['bidders'].append(float(r.Bidder_Count))
"""
if old not in s:
    raise SystemExit('buyer aggregation target not found; refusing unsafe patch')
s=s.replace(old,new,1)

# Empty analytical cohorts must emit a valid empty artifact; volume QA owns the failure decision.
old_rank="pd.DataFrame(rows).sort_values(['Market_Attractiveness_Score','Tender_Count'],ascending=[False,False]).to_csv(out/'market_rank.csv',index=False)"
new_rank="""rank_cols=['Category','Subcategory','Tender_Count','Award_Count','Median_Lean_Fit','Median_Award_Value_EUR','Median_Bidder_Count','Award_Value_Coverage_Pct','Bidder_Count_Coverage_Pct','Market_Attractiveness_Score','Derived_Status']
    rank_df=pd.DataFrame(rows,columns=rank_cols)
    if len(rank_df): rank_df=rank_df.sort_values(['Market_Attractiveness_Score','Tender_Count'],ascending=[False,False])
    rank_df.to_csv(out/'market_rank.csv',index=False)"""
if old_rank not in s:
    raise SystemExit('market rank target not found; refusing unsafe patch')
s=s.replace(old_rank,new_rank,1)

# Analytics later reuses `tdf` as a narrow view. QA needs the full date/value/link columns,
# so read a dedicated QA frame rather than relying on the shadowed variable.
anchor="counts={'normalized_tenders':len(tdf),'award_groups':len(adf),'award_supplier_links':len(bdf),'unique_buyers':int(tdf.Buyer_ID.nunique()),'unique_suppliers':int(bdf.Supplier_ID.nunique()) if len(bdf) else 0}"
replacement="""qdf=pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Historical_Tender_ID','Buyer_ID','Publication_Date','Deadline','Official_Estimated_Value','Award_Link_Status'],low_memory=False)
    counts={'normalized_tenders':len(qdf),'award_groups':len(adf),'award_supplier_links':len(bdf),'unique_buyers':int(qdf.Buyer_ID.nunique()),'unique_suppliers':int(bdf.Supplier_ID.nunique()) if len(bdf) else 0}"""
if anchor not in s:
    raise SystemExit('QA counts target not found; refusing unsafe patch')
s=s.replace(anchor,replacement,1)
s=s.replace("round(tdf.Publication_Date.notna().mean()*100,2)","round(qdf.Publication_Date.notna().mean()*100,2)")
s=s.replace("round(tdf.Deadline.notna().mean()*100,2)","round(qdf.Deadline.notna().mean()*100,2)")
s=s.replace("round(tdf.Official_Estimated_Value.notna().mean()*100,2)","round(qdf.Official_Estimated_Value.notna().mean()*100,2)")
s=s.replace("round((tdf.Award_Link_Status=='LINKED').mean()*100,2)","round((qdf.Award_Link_Status=='LINKED').mean()*100,2)")
s=s.replace("bool(tdf.Historical_Tender_ID.is_unique)","bool(qdf.Historical_Tender_ID.is_unique)")

# Pandas' low-memory C-parser hit an internal _concatenate_chunks IndexError only after
# all 857k XML records had already been normalized. Force single-pass dtype inference
# for the remaining canonical readbacks; this changes no rows and avoids the parser bug.
s=s.replace("pd.read_csv(out/'award_suppliers.csv.gz')", "pd.read_csv(out/'award_suppliers.csv.gz',low_memory=False)")
s=s.replace("pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Historical_Tender_ID','Category','Subcategory','Buyer_ID','Buyer_Name','Lean_Fit'])", "pd.read_csv(out/'historical_tenders.csv.gz',usecols=['Historical_Tender_ID','Category','Subcategory','Buyer_ID','Buyer_Name','Lean_Fit'],low_memory=False)")
s=s.replace("pd.read_csv(out/'awards.csv.gz',usecols=['Historical_Tender_ID','Award_ID','Award_Value','Bidder_Count'])", "pd.read_csv(out/'awards.csv.gz',usecols=['Historical_Tender_ID','Award_ID','Award_Value','Bidder_Count'],low_memory=False)")

p.write_text(s,encoding='utf-8')
print('Germany runtime patch applied: requested-publication date + XML date timezone normalization + buyer O(1) + empty-rank + QA frame isolation + robust pandas readback')
