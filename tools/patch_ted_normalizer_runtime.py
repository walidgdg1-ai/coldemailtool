#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/tender_normalize_ted_bulk.py')
s=p.read_text(encoding='utf-8')

# sqlite3 Cursor.execute() invalidates an active iteration on the same cursor. The canonical
# award loop performs a nested supplier lookup, so materialize award rows before that lookup.
old_awards="""    awards=[]
    for r in c.execute('SELECT '+','.join(acols)+' FROM awards'):
        a=dict(zip(acols,r));hid=hid_by_pk.get(a['procurement_key'])
        if not hid:continue
        bid,bname,country=buyer_by_pk[a['procurement_key']]
        bs=c.execute('SELECT supplier_id,supplier_name,supplier_country,allocated_value FROM bridges WHERE award_id=?',(a['award_id'],)).fetchall();first=bs[0] if len(bs)==1 else (None,None,None,None)
        awards.append({'Award_ID':a['award_id'],'Historical_Tender_ID':hid,'Buyer_ID':bid,'Buyer_Name':bname,'Supplier_ID':first[0],'Supplier_Name':first[1],'Supplier_Country':first[2],'Award_Date':iso_date(a['award_date']),'Award_Value':a['value'],'Currency':a['currency'],'Bidder_Count':a['bidder_count'] if a['bidder_count'] is not None else UNKNOWN,'Supplier_Count':a['supplier_count'] if a['supplier_count'] is not None else UNKNOWN,'Value_Field':a['value_field'],'Schema_Generation':a['schema_generation'],'Source_Notice_ID':a['notice_id']})
"""
new_awards="""    awards=[]
    award_rows_sqlite=c.execute('SELECT '+','.join(acols)+' FROM awards').fetchall()
    for r in award_rows_sqlite:
        a=dict(zip(acols,r));hid=hid_by_pk.get(a['procurement_key'])
        if not hid:continue
        bid,bname,country=buyer_by_pk[a['procurement_key']]
        bs=c.execute('SELECT supplier_id,supplier_name,supplier_country,allocated_value FROM bridges WHERE award_id=?',(a['award_id'],)).fetchall();first=bs[0] if len(bs)==1 else (None,None,None,None)
        awards.append({'Award_ID':a['award_id'],'Historical_Tender_ID':hid,'Buyer_ID':bid,'Buyer_Name':bname,'Supplier_ID':first[0],'Supplier_Name':first[1],'Supplier_Country':first[2],'Award_Date':iso_date(a['award_date']),'Award_Value':a['value'],'Currency':a['currency'],'Bidder_Count':a['bidder_count'] if a['bidder_count'] is not None else UNKNOWN,'Supplier_Count':a['supplier_count'] if a['supplier_count'] is not None else UNKNOWN,'Value_Field':a['value_field'],'Schema_Generation':a['schema_generation'],'Source_Notice_ID':a['notice_id']})
"""
if old_awards not in s:raise SystemExit('award cursor block not found')
s=s.replace(old_awards,new_awards,1)

old="""    bridges=[];suppliers={}
    for aid,sid,sname,scountry,alloc in c.execute('SELECT award_id,supplier_id,supplier_name,supplier_country,allocated_value FROM bridges'):
        if not any(x['Award_ID']==aid for x in awards):continue
        bridges.append({'Award_ID':aid,'Supplier_ID':sid,'Supplier_Name':sname,'Relationship':'WINNER','Award_Value_Allocated':alloc,'Supplier_Country':scountry,'SME_Status':UNKNOWN});suppliers[sid]={'Supplier_ID':sid,'Supplier_Name':sname,'Country':scountry}
"""
new="""    award_ids={x['Award_ID'] for x in awards};award_supplier_count={x['Award_ID']:x['Supplier_Count'] for x in awards}
    bridges=[];suppliers={}
    for aid,sid,sname,scountry,alloc in c.execute('SELECT award_id,supplier_id,supplier_name,supplier_country,allocated_value FROM bridges'):
        if aid not in award_ids:continue
        bridges.append({'Award_ID':aid,'Supplier_ID':sid,'Supplier_Name':sname,'Relationship':'WINNER','Award_Value_Allocated':alloc,'Supplier_Country':scountry,'SME_Status':UNKNOWN});suppliers[sid]={'Supplier_ID':sid,'Supplier_Name':sname,'Country':scountry}
"""
if old not in s:raise SystemExit('bridge block not found')
s=s.replace(old,new,1)
old2="""'award_tender_fk':all(x['Historical_Tender_ID'] in {t['Historical_Tender_ID'] for t in tenders} for x in awards),'multi_supplier_values_not_allocated':all(x['Award_Value_Allocated'] is None for x in bridges if next((a for a in awards if a['Award_ID']==x['Award_ID']),{}).get('Supplier_Count') not in (1,'1'))"""
new2="""'award_tender_fk':all(x['Historical_Tender_ID'] in {t['Historical_Tender_ID'] for t in tenders} for x in awards),'multi_supplier_values_not_allocated':all(x['Award_Value_Allocated'] is None for x in bridges if award_supplier_count.get(x['Award_ID']) not in (1,'1'))"""
if old2 not in s:raise SystemExit('integrity block not found')
s=s.replace(old2,new2,1)
p.write_text(s,encoding='utf-8')
print('TED dual-stack runtime patch applied: award cursor preservation + O(1) bridge integrity')
