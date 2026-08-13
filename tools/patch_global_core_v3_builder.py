#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/build_global_core_v3.py')
s=p.read_text(encoding='utf-8')
old="""    con.execute(f\"\"\"COPY (\n      SELECT Warehouse_Source,Supplier_ID,arg_max(Supplier_Name,length(coalesce(Supplier_Name,''))) Supplier_Name,\n             {norm('Supplier_Name')} AS Normalized_Name,any_value(Supplier_Country) Country,\n             count(distinct Award_ID) Observed_Contracts_Won,median(try_cast(Award_Value_Allocated AS DOUBLE)) Median_Allocated_Value,\n             'NOTICE_FIRST' Evidence_Type\n      FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}')\n      GROUP BY 1,2\n    ) TO '{(out/'suppliers.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)\"\"\")\n"""
new="""    con.execute(f\"\"\"COPY (\n      WITH s AS (\n        SELECT Warehouse_Source,Supplier_ID,arg_max(Supplier_Name,length(coalesce(Supplier_Name,''))) Supplier_Name,\n               any_value(Supplier_Country) Country,count(distinct Award_ID) Observed_Contracts_Won,\n               median(try_cast(Award_Value_Allocated AS DOUBLE)) Median_Allocated_Value\n        FROM read_parquet('{(out/'award_suppliers.parquet').as_posix()}')\n        GROUP BY 1,2\n      )\n      SELECT Warehouse_Source,Supplier_ID,Supplier_Name,{norm('Supplier_Name')} AS Normalized_Name,Country,\n             Observed_Contracts_Won,Median_Allocated_Value,'NOTICE_FIRST' Evidence_Type\n      FROM s\n    ) TO '{(out/'suppliers.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)\"\"\")\n"""
if old not in s: raise SystemExit('supplier dimension target not found')
p.write_text(s.replace(old,new,1),encoding='utf-8')
print('GLOBAL_CORE_V3_BUILDER_PATCH_APPLIED')
