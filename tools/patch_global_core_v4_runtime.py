#!/usr/bin/env python3
from pathlib import Path

p=Path('tools/build_global_core_v4.py')
s=p.read_text(encoding='utf-8')

old="SELECT 'TenderNed' AS Warehouse_Source, *,\n               coalesce(Evidence_Type,'NOTICE_FIRST_TENDERNED') AS Evidence_Type"
new="SELECT 'TenderNed' AS Warehouse_Source, * EXCLUDE(Evidence_Type),\n               coalesce(Evidence_Type,'NOTICE_FIRST_TENDERNED') AS Evidence_Type"
assert s.count(old)==2,('TenderNed projection count',s.count(old))
s=s.replace(old,new)

old="               {norm('Supplier_Name')} AS Normalized_Name,"
new="               lower(trim(regexp_replace(strip_accents(coalesce(arg_max(Supplier_Name,length(coalesce(Supplier_Name,''))),'')), '[^A-Za-z0-9]+', ' ', 'g'))) AS Normalized_Name,"
assert s.count(old)==1,('supplier normalization count',s.count(old))
s=s.replace(old,new)

old="""        SELECT t.Warehouse_Source,t.Buyer_ID,t.Buyer_Name,{norm('t.Buyer_Name')} AS Normalized_Name,
               t.Country,t.Observed_Tenders,coalesce(aw.Observed_Awards,0) Observed_Awards,
               aw.Median_Award_Value,aw.Median_Bidder_Count,'NOTICE_FIRST' Evidence_Type
        FROM t LEFT JOIN aw USING(Warehouse_Source,Buyer_ID)"""
new="""        SELECT coalesce(t.Warehouse_Source,aw.Warehouse_Source) Warehouse_Source,
               coalesce(t.Buyer_ID,aw.Buyer_ID) Buyer_ID,
               coalesce(t.Buyer_Name,'UNKNOWN') Buyer_Name,
               lower(trim(regexp_replace(strip_accents(coalesce(t.Buyer_Name,'UNKNOWN')), '[^A-Za-z0-9]+', ' ', 'g'))) AS Normalized_Name,
               coalesce(t.Country,'UNKNOWN') Country,
               coalesce(t.Observed_Tenders,0) Observed_Tenders,
               coalesce(aw.Observed_Awards,0) Observed_Awards,
               aw.Median_Award_Value,aw.Median_Bidder_Count,'NOTICE_FIRST' Evidence_Type
        FROM t FULL OUTER JOIN aw USING(Warehouse_Source,Buyer_ID)"""
assert s.count(old)==1,('buyer dimension block count',s.count(old))
s=s.replace(old,new)

p.write_text(s,encoding='utf-8')
print('CORE_V4_RUNTIME_PATCHES_PASS tenderned=2 supplier=1 buyer_dimension=1')
