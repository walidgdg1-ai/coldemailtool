#!/usr/bin/env python3
from pathlib import Path

p=Path('tools/build_spm_deep_intelligence_v1.py')
s=p.read_text(encoding='utf-8')

old="""    text_expr=\"lower(concat_ws(' ',\"+','.join(f\"coalesce(cast({x} as varchar),'')\" for x in text_parts)+'))'\n    # Remove the trailing quote introduced above in a controlled way.\n    text_expr=text_expr[:-1]\n"""
new="""    text_expr=\"lower(concat_ws(' ',\"+','.join(f\"coalesce(cast({x} as varchar),'')\" for x in text_parts)+'))'\n"""
if old not in s:
    raise SystemExit('TEXT_EXPR_PATCH_TARGET_NOT_FOUND')
s=s.replace(old,new,1)

old2="""        ), score AS (\n          SELECT *,\n            100*(0.12*Volume_Pct+0.10*Buyer_Breadth_Pct+0.12*Repeat_Component+0.10*Fragmentation_Component+\n                 0.08*Competition_Component+0.08*Value_Fit_Component+0.05*Recency_Pct+0.05*Lean_Pct+0.30*Strategic_Heuristic_Component) SPM_Opportunity_Score,\n            100*(0.25*Low_Entry_Burden+0.20*Low_Execution_Pain+0.15*Remote_Feasibility+0.15*Subcontractability+\n                 0.10*Competition_Component+0.10*coalesce(Native_Currency_1k_5k_Share_Pct/100,0.5)+0.05*Repeat_Component) Easiest_Money_Score,\n            100*(0.45*AI_Leverage+0.15*Volume_Pct+0.15*Buyer_Breadth_Pct+0.15*Repeat_Component+0.10*Margin_Potential) AI_Leverage_Score,\n            100*(0.35*Subcontractability+0.20*Margin_Potential+0.15*Fragmentation_Component+0.10*Low_Entry_Burden+\n                 0.10*Value_Fit_Component+0.10*Repeat_Component) Middleman_Score,\n            100*(0.25*(SPM_Opportunity_Score/100)+0.25*Margin_Potential+0.20*coalesce(Native_Currency_20k_100k_Share_Pct/100,0.5)+0.15*Repeat_Component+0.15*Fragmentation_Component) Expected_Profit_Score\n          FROM c\n        )\n        SELECT *,\n"""
new2="""        ), score1 AS (\n          SELECT *,\n            100*(0.12*Volume_Pct+0.10*Buyer_Breadth_Pct+0.12*Repeat_Component+0.10*Fragmentation_Component+\n                 0.08*Competition_Component+0.08*Value_Fit_Component+0.05*Recency_Pct+0.05*Lean_Pct+0.30*Strategic_Heuristic_Component) SPM_Opportunity_Score,\n            100*(0.25*Low_Entry_Burden+0.20*Low_Execution_Pain+0.15*Remote_Feasibility+0.15*Subcontractability+\n                 0.10*Competition_Component+0.10*coalesce(Native_Currency_1k_5k_Share_Pct/100,0.5)+0.05*Repeat_Component) Easiest_Money_Score,\n            100*(0.45*AI_Leverage+0.15*Volume_Pct+0.15*Buyer_Breadth_Pct+0.15*Repeat_Component+0.10*Margin_Potential) AI_Leverage_Score,\n            100*(0.35*Subcontractability+0.20*Margin_Potential+0.15*Fragmentation_Component+0.10*Low_Entry_Burden+\n                 0.10*Value_Fit_Component+0.10*Repeat_Component) Middleman_Score\n          FROM c\n        ), score AS (\n          SELECT *,\n            100*(0.25*(SPM_Opportunity_Score/100)+0.25*Margin_Potential+0.20*coalesce(Native_Currency_20k_100k_Share_Pct/100,0.5)+0.15*Repeat_Component+0.15*Fragmentation_Component) Expected_Profit_Score\n          FROM score1\n        )\n        SELECT *,\n"""
if old2 not in s:
    raise SystemExit('SCORE_ALIAS_PATCH_TARGET_NOT_FOUND')
s=s.replace(old2,new2,1)

s=s.replace('Macro','Macro_Category')
s=s.replace('quantile_cont(Award_Value,0.10)', 'approx_quantile(Award_Value,0.10)')
s=s.replace('quantile_cont(Award_Value,0.25)', 'approx_quantile(Award_Value,0.25)')
s=s.replace('median(Award_Value) Median_Award_Value', 'approx_quantile(Award_Value,0.50) Median_Award_Value')
s=s.replace('quantile_cont(Award_Value,0.75)', 'approx_quantile(Award_Value,0.75)')
s=s.replace('quantile_cont(Award_Value,0.90)', 'approx_quantile(Award_Value,0.90)')
s=s.replace("'Currency-specific values are never summed or averaged across currencies; only within-currency distributions and dimensionless shares are used.',",
            "'Currency-specific values are never summed or averaged across currencies; only within-currency distributions and dimensionless shares are used.',\n            'P10/P25/P50/P75/P90 award-value distributions use bounded-memory approx_quantile over the full matched corpus.',")

start_marker = '''    con.execute(f"""COPY (\n      WITH x AS (\n        SELECT n.Niche,n.Macro_Category,n.Warehouse_Source,n.Country,'''
end_marker = '''\n\n    # Explicit entry-requirement text signals (proxies only).'''
start=s.find(start_marker)
end=s.find(end_marker,start)
if start<0 or end<0:
    raise SystemExit('PRICE_BLOCK_PATCH_TARGET_NOT_FOUND')
price_code = '''    price_pairs=con.execute(f"SELECT DISTINCT Warehouse_Source,Niche FROM read_parquet({q(matched.as_posix())}) ORDER BY 1,2").fetchall()\n    price_parts=[]\n    for ix,(src,niche) in enumerate(price_pairs):\n        part=out/f"_price_part_{ix:04d}.csv"\n        con.execute(f"""COPY (\n          WITH x AS (\n            SELECT n.Niche,n.Macro_Category,n.Warehouse_Source,n.Country,\n                   coalesce(nullif(a.Award_Currency,''),nullif(n.Currency,''),'UNKNOWN') Currency,a.Award_Value,a.Bidder_Count\n            FROM (SELECT Niche,Macro_Category,Warehouse_Source,Historical_Tender_ID,Country,Currency\n                  FROM read_parquet({q(matched.as_posix())})\n                  WHERE Warehouse_Source={q(src)} AND Niche={q(niche)}) n\n            JOIN (SELECT Warehouse_Source,Historical_Tender_ID,Award_Value,Bidder_Count,Award_Currency\n                  FROM award_base WHERE Warehouse_Source={q(src)}) a\n              USING(Warehouse_Source,Historical_Tender_ID)\n            WHERE a.Award_Value IS NOT NULL\n          )\n          SELECT Niche,Macro_Category,Warehouse_Source,Country,Currency,count(*) Known_Value_Awards,\n                 approx_quantile(Award_Value,0.10) P10_Award_Value,approx_quantile(Award_Value,0.25) P25_Award_Value,\n                 approx_quantile(Award_Value,0.50) Median_Award_Value,approx_quantile(Award_Value,0.75) P75_Award_Value,approx_quantile(Award_Value,0.90) P90_Award_Value,\n                 avg(CASE WHEN Bidder_Count IS NOT NULL THEN 1 ELSE 0 END)*100 Bidder_Count_Coverage_Pct,median(Bidder_Count) Median_Bidder_Count\n          FROM x GROUP BY 1,2,3,4,5 HAVING count(*)>=5\n          ORDER BY Known_Value_Awards DESC\n        ) TO {q(part.as_posix())} (HEADER)""")\n        price_parts.append(part)\n    if price_parts:\n        con.execute(f"COPY (SELECT * FROM read_csv_auto({q((out/'_price_part_*.csv').as_posix())},header=true,union_by_name=true)) TO {q((out/'price_distribution_by_niche_currency.csv').as_posix())} (HEADER)")\n        for part in price_parts:\n            part.unlink(missing_ok=True)\n    else:\n        (out/'price_distribution_by_niche_currency.csv').write_text('Niche,Macro_Category,Warehouse_Source,Country,Currency,Known_Value_Awards,P10_Award_Value,P25_Award_Value,Median_Award_Value,P75_Award_Value,P90_Award_Value,Bidder_Count_Coverage_Pct,Median_Bidder_Count\\n',encoding='utf-8')'''
s=s[:start]+price_code+s[end:]

p.write_text(s,encoding='utf-8')
print('SPM_DEEP_V1_RUNTIME_PATCH_PASS')
