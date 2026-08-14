#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/build_spm_deep_intelligence_v1.py')
s=p.read_text(encoding='utf-8')

def replace_block(start_marker,end_marker,replacement,label):
    global s
    start=s.find(start_marker)
    end=s.find(end_marker,start)
    if start<0 or end<0:
        raise SystemExit(f'{label}_NOT_FOUND')
    s=s[:start]+replacement+s[end:]

# Decision-core contract: rank niches from the complete tender universe first.
# Award/value/supplier/competition enrichments are deliberately deferred and neutralized.
replace_block(
    '    con.execute(f"""\n      CREATE TEMP VIEW niche_award_profile AS',
    '\n    con.execute(f"""\n      CREATE TEMP VIEW niche_supplier_profile AS',
    '''    con.execute("""\n      CREATE TEMP VIEW niche_award_profile AS\n      SELECT NULL::VARCHAR Niche,NULL::BIGINT Award_Count,NULL::DOUBLE Award_Value_Coverage_Pct,\n             NULL::DOUBLE Bidder_Count_Coverage_Pct,NULL::DOUBLE Median_Bidder_Count,NULL::DOUBLE Single_Bid_Award_Pct\n      WHERE false\n    """)\n''',
    'NICHE_AWARD_PROFILE_BLOCK')

replace_block(
    '    con.execute(f"""\n      CREATE TEMP VIEW niche_supplier_profile AS',
    '\n    # Native-currency value bands.',
    '''    con.execute("""\n      CREATE TEMP VIEW niche_supplier_profile AS\n      SELECT NULL::VARCHAR Niche,NULL::BIGINT Supplier_Count,NULL::DOUBLE Top_Supplier_Share_Pct,\n             NULL::DOUBLE Supplier_HHI,NULL::DOUBLE Long_Tail_Winner_Share_Pct\n      WHERE false\n    """)\n''',
    'NICHE_SUPPLIER_PROFILE_BLOCK')

replace_block(
    '    # Native-currency value bands.',
    '\n    con.execute(f"""COPY (',
    '''    # Native-currency value bands deferred to targeted top-niche enrichment.\n    con.execute("""\n      CREATE TEMP VIEW niche_value_fit AS\n      SELECT NULL::VARCHAR Niche,NULL::BIGINT Known_Value_Awards,\n             NULL::DOUBLE Native_Currency_1k_100k_Share_Pct,NULL::DOUBLE Native_Currency_20k_100k_Share_Pct,\n             NULL::DOUBLE Native_Currency_1k_5k_Share_Pct,NULL::DOUBLE Native_Currency_5k_20k_Share_Pct\n      WHERE false\n    """)\n''',
    'NICHE_VALUE_FIT_BLOCK')

# Detailed price table becomes an explicit empty enrichment placeholder.
start=s.find('    price_pairs=con.execute(')
if start>=0:
    end=s.find('\n\n    # Explicit entry-requirement text signals (proxies only).',start)
    if end<0: raise SystemExit('PRICE_END_NOT_FOUND')
    repl="""    (out/'price_distribution_by_niche_currency.csv').write_text(\n        'Niche,Macro_Category,Warehouse_Source,Country,Currency,Known_Value_Awards,P10_Award_Value,P25_Award_Value,Median_Award_Value,P75_Award_Value,P90_Award_Value,Bidder_Count_Coverage_Pct,Median_Bidder_Count\\n',\n        encoding='utf-8')\n"""
    s=s[:start]+repl+s[end:]
else:
    start=s.find('    con.execute(f"""COPY (\n      WITH x AS (\n        SELECT n.Niche,n.Macro_Category,n.Warehouse_Source,n.Country,')
    if start>=0:
        end=s.find('\n\n    # Explicit entry-requirement text signals (proxies only).',start)
        repl="""    (out/'price_distribution_by_niche_currency.csv').write_text(\n        'Niche,Macro_Category,Warehouse_Source,Country,Currency,Known_Value_Awards,P10_Award_Value,P25_Award_Value,Median_Award_Value,P75_Award_Value,P90_Award_Value,Bidder_Count_Coverage_Pct,Median_Bidder_Count\\n',\n        encoding='utf-8')\n"""
        s=s[:start]+repl+s[end:]

# Winner intelligence is enrichment-only in decision core.
start=s.find('    # Supplier winner intelligence.')
end=s.find('\n    # Seasonality.',start)
if start<0 or end<0: raise SystemExit('WINNER_BLOCK_NOT_FOUND')
s=s[:start]+'''    # Supplier winner intelligence deferred to targeted enrichment.\n    (out/'top_winners_by_niche.csv').write_text(\n        'Niche,Macro_Category,Supplier_ID,Supplier_Name,Supplier_Country,Fractional_Awards,Observed_Awards,Niche_Fractional_Awards,rn,Supplier_Share_Pct\\n',\n        encoding='utf-8')\n'''+s[end:]

# Hidden-gem award/supplier joins are deferred. Keep a lightweight explicit placeholder lane.
start=s.find('    # Data-discovered Category/Subcategory cohorts.')
end=s.find('\n    # Representative historical examples for top 50 SPM niches.',start)
if start<0 or end<0: raise SystemExit('DISCOVERY_BLOCK_NOT_FOUND')
s=s[:start]+'''    # Hidden-gem discovery deferred to a separate tender-only discovery module.\n    (out/'data_discovered_cohorts.csv').write_text(\n        'Category,Subcategory,Tender_Count,Unique_Buyers,Source_Count,Country_Count,Median_Lean_Fit,Recent_12m_Share_Pct,Repeat_Tenders,Repeat_Tender_Share_Pct,Ontology_Status,Hard_Domain_Status,Empirical_Opportunity_Score,Derived_Status\\n',\n        encoding='utf-8')\n    (out/'hidden_gem_candidates.csv').write_text(\n        'Category,Subcategory,Tender_Count,Unique_Buyers,Source_Count,Country_Count,Median_Lean_Fit,Recent_12m_Share_Pct,Repeat_Tenders,Repeat_Tender_Share_Pct,Ontology_Status,Hard_Domain_Status,Empirical_Opportunity_Score,Derived_Status\\n',\n        encoding='utf-8')\n    (out/'unmatched_high_lean_title_terms.csv').write_text('Term,Title_Count\\n',encoding='utf-8')\n'''+s[end:]

# Representative examples: tender-side only; no award join in decision core.
start=s.find('    # Representative historical examples for top 50 SPM niches.')
end=s.find('\n    # Top buyer/niche combinations optimized for recurrence and recency',start)
if start<0 or end<0: raise SystemExit('REPRESENTATIVE_BLOCK_NOT_FOUND')
s=s[:start]+'''    # Representative historical examples for top 50 SPM niches (tender-side only).\n    con.execute(f"""COPY (\n      WITH topn AS (SELECT Niche FROM read_csv_auto({q(matrix.as_posix())},header=true) ORDER BY SPM_Opportunity_Score DESC LIMIT 50),\n      x AS (\n        SELECT n.Niche,n.Macro_Category,n.Historical_Tender_ID,n.Title,n.Buyer_ID,n.Buyer_Name,n.Country,n.Warehouse_Source,\n               n.Publication_Date,n.Deadline,n.Category,n.Subcategory,n.Currency,n.Official_Estimated_Value,n.Source_URL,n.Source_Reference,\n               row_number() OVER(PARTITION BY n.Niche ORDER BY n.Publication_Date DESC NULLS LAST,n.Historical_Tender_ID) rn\n        FROM read_parquet({q(matched.as_posix())}) n JOIN topn USING(Niche)\n      )\n      SELECT * EXCLUDE(rn) FROM x WHERE rn<=5 ORDER BY Niche,Publication_Date DESC\n    ) TO {q((out/'representative_tenders_top_niches.csv').as_posix())} (HEADER)""")\n'''+s[end:]

# Correct the analytical contract: tender-side empirical + explicit heuristics; award dimensions neutralized.
s=s.replace("'version':'SPM_DEEP_TENDER_INTELLIGENCE_V1'", "'version':'SPM_DECISION_CORE_V1'")
s=s.replace("'version':'SPM_LIVE_SCORING_SPEC_V1'", "'version':'SPM_LIVE_SCORING_SPEC_DECISION_CORE_V1'")
s=s.replace("'derived_from':'SPM_DEEP_TENDER_INTELLIGENCE_V1'", "'derived_from':'SPM_DECISION_CORE_V1'")
s=s.replace("'scoring_contract':'70% empirical market evidence + 30% explicit SPM heuristic assumptions'", "'scoring_contract':'44% tender-side empirical evidence + 30% explicit SPM heuristics + 26% neutralized pending award/value/supplier enrichment'")
s=s.replace("'Supplier long-tail metrics describe observed award fragmentation, not legal SME status.'", "'Award/value/supplier/competition dimensions are neutralized in decision core and must be enriched only for shortlisted niches.'")
s=s.replace("'P10/P25/P50/P75/P90 award-value distributions use bounded-memory approx_quantile over the full matched corpus.',", "'Detailed price quantiles are deferred to targeted top-niche enrichment.',")

p.write_text(s,encoding='utf-8')
print('SPM_DECISION_CORE_RUNTIME_PATCH_PASS')
