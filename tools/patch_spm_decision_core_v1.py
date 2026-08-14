#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/build_spm_deep_intelligence_v1.py')
s=p.read_text(encoding='utf-8')

# Detailed P10/P25/P50/P75/P90 is an enrichment module, not a prerequisite for
# the main niche ranking (which already uses full-corpus native-currency value bands).
start=s.find('    price_pairs=con.execute(')
end=s.find('\n\n    # Explicit entry-requirement text signals (proxies only).',start)
if start<0 or end<0:
    raise SystemExit('DECISION_CORE_PRICE_BLOCK_NOT_FOUND')
replacement="""    (out/'price_distribution_by_niche_currency.csv').write_text(
        'Niche,Macro_Category,Warehouse_Source,Country,Currency,Known_Value_Awards,P10_Award_Value,P25_Award_Value,Median_Award_Value,P75_Award_Value,P90_Award_Value,Bidder_Count_Coverage_Pct,Median_Bidder_Count\\n',
        encoding='utf-8')
"""
s=s[:start]+replacement+s[end:]

# Full-universe category×supplier HHI is also enrichment-only. Hidden-gem discovery
# still scans all tenders and uses volume, buyer breadth, recurrence, recency, Lean_Fit
# and competition evidence. Supplier fragmentation is neutralized until the targeted drill.
start=s.find('    con.execute(f"""\n      CREATE TEMP VIEW discovered_supplier_profile AS')
end=s.find('\n    broad_union=',start)
if start<0 or end<0:
    raise SystemExit('DECISION_CORE_DISCOVERY_SUPPLIER_BLOCK_NOT_FOUND')
replacement="""    con.execute(\"\"\"
      CREATE TEMP VIEW discovered_supplier_profile AS
      SELECT NULL::VARCHAR Category,NULL::VARCHAR Subcategory,NULL::BIGINT Supplier_Count,
             NULL::DOUBLE Top_Supplier_Share_Pct,NULL::DOUBLE Supplier_HHI WHERE false
    \"\"\")
"""
s=s[:start]+replacement+s[end:]

# Mark the modular contract explicitly.
s=s.replace("'P10/P25/P50/P75/P90 award-value distributions use bounded-memory approx_quantile over the full matched corpus.',",
            "'Detailed price quantiles are deferred to a separate targeted pricing enrichment module in the decision-core pass.',\n            'Hidden-gem full-universe supplier HHI is neutralized pending targeted supplier enrichment.',")
s=s.replace("'version':'SPM_DEEP_TENDER_INTELLIGENCE_V1'", "'version':'SPM_DECISION_CORE_V1'")
s=s.replace("'version':'SPM_LIVE_SCORING_SPEC_V1'", "'version':'SPM_LIVE_SCORING_SPEC_DECISION_CORE_V1'")
s=s.replace("'derived_from':'SPM_DEEP_TENDER_INTELLIGENCE_V1'", "'derived_from':'SPM_DECISION_CORE_V1'")

p.write_text(s,encoding='utf-8')
print('SPM_DECISION_CORE_RUNTIME_PATCH_PASS')
