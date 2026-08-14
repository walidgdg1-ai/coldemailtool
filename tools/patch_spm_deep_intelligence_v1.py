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

# Exact multi-quantile sorting across millions of joined awards spills beyond hosted-runner disk.
# Use bounded-memory approximate quantiles for the descriptive pricing table only.
s=s.replace('quantile_cont(Award_Value,0.10)', 'approx_quantile(Award_Value,0.10)')
s=s.replace('quantile_cont(Award_Value,0.25)', 'approx_quantile(Award_Value,0.25)')
s=s.replace('median(Award_Value) Median_Award_Value', 'approx_quantile(Award_Value,0.50) Median_Award_Value')
s=s.replace('quantile_cont(Award_Value,0.75)', 'approx_quantile(Award_Value,0.75)')
s=s.replace('quantile_cont(Award_Value,0.90)', 'approx_quantile(Award_Value,0.90)')
# Make the contract explicit in persisted QA text.
s=s.replace("'Currency-specific values are never summed or averaged across currencies; only within-currency distributions and dimensionless shares are used.',",
            "'Currency-specific values are never summed or averaged across currencies; only within-currency distributions and dimensionless shares are used.',\n            'P10/P25/P50/P75/P90 award-value distributions use bounded-memory approx_quantile over the full matched corpus.',")

p.write_text(s,encoding='utf-8')
print('SPM_DEEP_V1_RUNTIME_PATCH_PASS')
