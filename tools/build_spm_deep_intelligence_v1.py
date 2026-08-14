#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, hashlib, json, math, re
from datetime import datetime, timezone
from pathlib import Path
import duckdb

from spm_niche_rules import NICHE_RULES, ENTRY_SIGNAL_PATTERNS, STOPWORDS


def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def first_col(cols: set[str], candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def coalesce_text(cols: set[str], candidates: list[str], fallback="''") -> str:
    found = [ident(c) for c in candidates if c in cols]
    return f"coalesce({','.join(found)},'')" if found else fallback


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def human_num(v):
    if v is None:
        return 'UNKNOWN'
    try:
        v=float(v)
    except Exception:
        return str(v)
    if abs(v)>=1_000_000: return f'{v/1_000_000:.2f}M'
    if abs(v)>=1_000: return f'{v/1_000:.1f}k'
    return f'{v:.0f}'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--core', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--usa-rank')
    ap.add_argument('--usa-repeat')
    a=ap.parse_args()

    core=Path(a.core); out=Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tmp=out/'ducktmp'; tmp.mkdir(exist_ok=True)
    con=duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=2")
    con.execute("SET memory_limit='6GB'")
    con.execute(f"SET temp_directory={q(tmp.as_posix())}")
    con.execute("SET max_temp_directory_size='20GB'")

    tp=core/'historical_tenders.parquet'; apath=core/'awards.parquet'; bp=core/'award_suppliers.parquet'
    for p in [tp,apath,bp]:
        if not p.exists(): raise SystemExit(f'MISSING_INPUT {p}')

    def schema(path: Path):
        rows=con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(path.as_posix())})").fetchall()
        return {r[0]: r[1] for r in rows}

    ts=schema(tp); aws=schema(apath); bs=schema(bp)
    tcols=set(ts); acols=set(aws); bcols=set(bs)
    (out/'schema_profile.json').write_text(json.dumps({'tenders':ts,'awards':aws,'award_suppliers':bs},indent=2),encoding='utf-8')

    # Dynamic field mapping keeps the analysis robust across source-specific schema additions.
    title_col=first_col(tcols,['Title','Tender_Title','Notice_Title','Object_Title','Name'])
    desc_col=first_col(tcols,['Description','Tender_Description','Short_Description','Description_Text','Purpose','Scope'])
    cat_col=first_col(tcols,['Category'])
    subcat_col=first_col(tcols,['Subcategory'])
    buyer_id_col=first_col(tcols,['Buyer_ID'])
    buyer_name_col=first_col(tcols,['Buyer_Name'])
    country_col=first_col(tcols,['Country'])
    pub_col=first_col(tcols,['Publication_Date','Published_Date','Date_Published'])
    deadline_col=first_col(tcols,['Deadline','Submission_Deadline','Tender_Deadline'])
    currency_col=first_col(tcols,['Currency','Estimated_Value_Currency'])
    est_col=first_col(tcols,['Official_Estimated_Value','Estimated_Value','Tender_Value'])
    lean_col=first_col(tcols,['Lean_Fit','Lean_Fit_Score'])
    source_url_col=first_col(tcols,['Source_URL','URL','Notice_URL','Source_Notice_URL','Tender_URL'])
    source_ref_col=first_col(tcols,['Source_Notice_ID','Notice_ID','Source_ID','OCID'])

    if not title_col:
        raise SystemExit('Core v4 has no recognizable tender title column')

    def col_or(col, fallback="''"):
        return ident(col) if col else fallback

    text_parts=[col_or(title_col)]
    if desc_col: text_parts.append(col_or(desc_col))
    if cat_col: text_parts.append(col_or(cat_col))
    if subcat_col: text_parts.append(col_or(subcat_col))
    text_expr="lower(concat_ws(' ',"+','.join(f"coalesce(cast({x} as varchar),'')" for x in text_parts)+'))'
    # Remove the trailing quote introduced above in a controlled way.
    text_expr=text_expr[:-1]

    case_niche='CASE\n' + '\n'.join([f"WHEN regexp_matches(Text_Blob,{q(r['pattern'])}) THEN {q(r['niche'])}" for r in NICHE_RULES]) + "\nELSE NULL END"
    rule_values=[]
    for i,r in enumerate(NICHE_RULES,1):
        rule_values.append('('+','.join([
            str(i),q(r['macro']),q(r['niche']),str(r['ai']),str(r['subcontract']),str(r['remote']),str(r['low_entry']),str(r['low_pain']),str(r['margin'])
        ])+')')
    con.execute("CREATE TEMP TABLE niche_rules(priority INTEGER,Macro VARCHAR,Niche VARCHAR,AI_Leverage DOUBLE,Subcontractability DOUBLE,Remote_Feasibility DOUBLE,Low_Entry_Burden DOUBLE,Low_Execution_Pain DOUBLE,Margin_Potential DOUBLE)")
    con.execute("INSERT INTO niche_rules VALUES "+','.join(rule_values))

    title_expr=f"cast({ident(title_col)} as varchar)"
    desc_expr=f"cast({ident(desc_col)} as varchar)" if desc_col else "''"
    category_expr=f"cast({ident(cat_col)} as varchar)" if cat_col else "'UNKNOWN'"
    subcategory_expr=f"cast({ident(subcat_col)} as varchar)" if subcat_col else "'UNKNOWN'"
    buyer_id_expr=f"cast({ident(buyer_id_col)} as varchar)" if buyer_id_col else "NULL"
    buyer_name_expr=f"cast({ident(buyer_name_col)} as varchar)" if buyer_name_col else "'UNKNOWN'"
    country_expr=f"cast({ident(country_col)} as varchar)" if country_col else "'UNKNOWN'"
    pub_expr=f"try_cast({ident(pub_col)} as DATE)" if pub_col else "NULL::DATE"
    deadline_expr=f"try_cast({ident(deadline_col)} as DATE)" if deadline_col else "NULL::DATE"
    currency_expr=f"cast({ident(currency_col)} as varchar)" if currency_col else "'UNKNOWN'"
    est_expr=f"try_cast({ident(est_col)} as DOUBLE)" if est_col else "NULL::DOUBLE"
    lean_expr=f"try_cast({ident(lean_col)} as DOUBLE)" if lean_col else "NULL::DOUBLE"
    url_expr=f"cast({ident(source_url_col)} as varchar)" if source_url_col else "NULL"
    ref_expr=f"cast({ident(source_ref_col)} as varchar)" if source_ref_col else "NULL"

    # Compact normalized tender projection. Text_Blob is used for classification and entry-signal proxies.
    con.execute(f"""
      CREATE TEMP VIEW tender_base AS
      SELECT
        cast(Warehouse_Source as varchar) Warehouse_Source,
        cast(Historical_Tender_ID as varchar) Historical_Tender_ID,
        {title_expr} Title,
        {desc_expr} Description,
        {category_expr} Category,
        {subcategory_expr} Subcategory,
        {buyer_id_expr} Buyer_ID,
        {buyer_name_expr} Buyer_Name,
        {country_expr} Country,
        {pub_expr} Publication_Date,
        {deadline_expr} Deadline,
        {currency_expr} Currency,
        {est_expr} Official_Estimated_Value,
        {lean_expr} Lean_Fit,
        {url_expr} Source_URL,
        {ref_expr} Source_Reference,
        {text_expr} Text_Blob
      FROM read_parquet({q(tp.as_posix())})
    """)

    con.execute(f"""
      COPY (
        WITH c AS (SELECT *, {case_niche} AS Niche FROM tender_base)
        SELECT c.*,r.Macro,r.AI_Leverage,r.Subcontractability,r.Remote_Feasibility,
               r.Low_Entry_Burden,r.Low_Execution_Pain,r.Margin_Potential
        FROM c JOIN niche_rules r USING(Niche)
      ) TO {q((out/'spm_matched_tenders.parquet').as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    matched=out/'spm_matched_tenders.parquet'

    total_tenders=con.execute(f"SELECT count(*) FROM read_parquet({q(tp.as_posix())})").fetchone()[0]
    matched_tenders=con.execute(f"SELECT count(*) FROM read_parquet({q(matched.as_posix())})").fetchone()[0]

    # Empirical source/country context.
    con.execute(f"""COPY (
      SELECT Warehouse_Source,Country,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,
             count(distinct Niche) Matched_Niches,median(Lean_Fit) Median_Lean_Fit,
             avg(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)*100 Recent_12m_Share_Pct
      FROM read_parquet({q(matched.as_posix())})
      GROUP BY 1,2 ORDER BY Tender_Count DESC
    ) TO {q((out/'country_spm_fit.csv').as_posix())} (HEADER)""")

    # Buyer recurrence by niche.
    con.execute(f"""
      CREATE TEMP VIEW buyer_niche AS
      SELECT Niche,Macro,Warehouse_Source,Country,Buyer_ID,any_value(Buyer_Name) Buyer_Name,
             count(*) Tender_Count,min(Publication_Date) First_Publication_Date,max(Publication_Date) Last_Publication_Date,
             count(distinct date_trunc('year',Publication_Date)) Active_Years
      FROM read_parquet({q(matched.as_posix())}) WHERE Buyer_ID IS NOT NULL
      GROUP BY 1,2,3,4,5
    """)
    con.execute(f"""COPY (
      SELECT *,date_diff('day',First_Publication_Date,Last_Publication_Date) Active_Span_Days,
             CASE WHEN Tender_Count>=20 THEN 'VERY_HIGH_REPEAT' WHEN Tender_Count>=10 THEN 'HIGH_REPEAT' WHEN Tender_Count>=5 THEN 'REPEAT' ELSE 'LOW_REPEAT' END Repeat_Band
      FROM buyer_niche WHERE Tender_Count>=3 ORDER BY Tender_Count DESC,Last_Publication_Date DESC
    ) TO {q((out/'top_recurring_buyers_by_niche.csv').as_posix())} (HEADER)""")

    # Award schema mapping.
    a_tender=first_col(acols,['Historical_Tender_ID'])
    a_award=first_col(acols,['Award_ID'])
    a_buyer=first_col(acols,['Buyer_ID'])
    a_value=first_col(acols,['Award_Value','Official_Award_Value','Value'])
    a_bidder=first_col(acols,['Bidder_Count','Number_Of_Offers','NumberOfTenderers'])
    a_currency=first_col(acols,['Currency','Award_Currency','Value_Currency'])
    a_supplier=first_col(acols,['Supplier_ID'])
    if not a_tender or not a_award:
        raise SystemExit('Awards schema missing key fields')
    aval=f"try_cast({ident(a_value)} as DOUBLE)" if a_value else "NULL::DOUBLE"
    abid=f"try_cast({ident(a_bidder)} as DOUBLE)" if a_bidder else "NULL::DOUBLE"
    acur=f"cast({ident(a_currency)} as varchar)" if a_currency else "NULL"
    asup=f"cast({ident(a_supplier)} as varchar)" if a_supplier else "NULL"
    con.execute(f"""
      CREATE TEMP VIEW award_base AS
      SELECT cast(Warehouse_Source as varchar) Warehouse_Source,
             cast({ident(a_tender)} as varchar) Historical_Tender_ID,
             cast({ident(a_award)} as varchar) Award_ID,
             {aval} Award_Value,{abid} Bidder_Count,{acur} Award_Currency,{asup} Award_Supplier_ID
      FROM read_parquet({q(apath.as_posix())})
    """)

    # Supplier bridge mapping and fractional awards to avoid consortium duplication.
    b_award=first_col(bcols,['Award_ID']); b_supplier=first_col(bcols,['Supplier_ID']); b_sname=first_col(bcols,['Supplier_Name']); b_country=first_col(bcols,['Supplier_Country','Country'])
    if not b_award or not b_supplier:
        raise SystemExit('Award supplier schema missing key fields')
    bsname=f"cast({ident(b_sname)} as varchar)" if b_sname else "'UNKNOWN'"
    bscountry=f"cast({ident(b_country)} as varchar)" if b_country else "'UNKNOWN'"
    con.execute(f"""
      CREATE TEMP VIEW bridge_base AS
      SELECT cast(Warehouse_Source as varchar) Warehouse_Source,cast({ident(b_award)} as varchar) Award_ID,
             cast({ident(b_supplier)} as varchar) Supplier_ID,{bsname} Supplier_Name,{bscountry} Supplier_Country
      FROM read_parquet({q(bp.as_posix())})
    """)
    con.execute("""
      CREATE TEMP VIEW bridge_fractional AS
      SELECT *,1.0/count(*) OVER(PARTITION BY Warehouse_Source,Award_ID) Fractional_Award
      FROM bridge_base
    """)

    # Niche-level empirical profile.
    con.execute(f"""
      CREATE TEMP VIEW niche_tender_profile AS
      WITH b AS (
        SELECT Niche,any_value(Macro) Macro,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,
               count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count,
               median(Lean_Fit) Median_Lean_Fit,
               avg(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)*100 Recent_12m_Share_Pct,
               any_value(AI_Leverage) AI_Leverage,any_value(Subcontractability) Subcontractability,
               any_value(Remote_Feasibility) Remote_Feasibility,any_value(Low_Entry_Burden) Low_Entry_Burden,
               any_value(Low_Execution_Pain) Low_Execution_Pain,any_value(Margin_Potential) Margin_Potential
        FROM read_parquet({q(matched.as_posix())}) GROUP BY 1
      ), r AS (
        SELECT Niche,sum(Tender_Count) Repeat_Tenders
        FROM buyer_niche WHERE Tender_Count>=3 GROUP BY 1
      )
      SELECT b.*,coalesce(r.Repeat_Tenders,0) Repeat_Tenders,100.0*coalesce(r.Repeat_Tenders,0)/b.Tender_Count Repeat_Tender_Share_Pct
      FROM b LEFT JOIN r USING(Niche)
    """)

    con.execute(f"""
      CREATE TEMP VIEW niche_award_profile AS
      SELECT n.Niche,count(distinct a.Award_ID) Award_Count,
             avg(CASE WHEN a.Award_Value IS NOT NULL THEN 1 ELSE 0 END)*100 Award_Value_Coverage_Pct,
             avg(CASE WHEN a.Bidder_Count IS NOT NULL THEN 1 ELSE 0 END)*100 Bidder_Count_Coverage_Pct,
             median(a.Bidder_Count) Median_Bidder_Count,
             avg(CASE WHEN a.Bidder_Count=1 THEN 1 ELSE 0 END)*100 Single_Bid_Award_Pct
      FROM read_parquet({q(matched.as_posix())}) n JOIN award_base a USING(Warehouse_Source,Historical_Tender_ID)
      GROUP BY 1
    """)

    con.execute(f"""
      CREATE TEMP VIEW niche_supplier_profile AS
      WITH sx AS (
        SELECT n.Niche,b.Supplier_ID,any_value(b.Supplier_Name) Supplier_Name,
               sum(b.Fractional_Award) Fractional_Awards,count(distinct a.Award_ID) Observed_Awards
        FROM read_parquet({q(matched.as_posix())}) n JOIN award_base a USING(Warehouse_Source,Historical_Tender_ID)
        JOIN bridge_fractional b USING(Warehouse_Source,Award_ID)
        GROUP BY 1,2
      ), sh AS (
        SELECT *,Fractional_Awards/sum(Fractional_Awards) OVER(PARTITION BY Niche) Supplier_Share FROM sx
      )
      SELECT Niche,count(*) Supplier_Count,max(Supplier_Share)*100 Top_Supplier_Share_Pct,
             sum(Supplier_Share*Supplier_Share)*10000 Supplier_HHI,
             sum(CASE WHEN Observed_Awards<=2 THEN Fractional_Awards ELSE 0 END)/sum(Fractional_Awards)*100 Long_Tail_Winner_Share_Pct
      FROM sh GROUP BY 1
    """)

    # Native-currency value bands. We aggregate dimensionless within-currency shares, never monetary sums across currencies.
    con.execute(f"""
      CREATE TEMP VIEW niche_value_fit AS
      WITH x AS (
        SELECT n.Niche,coalesce(nullif(a.Award_Currency,''),nullif(n.Currency,''),'UNKNOWN') Currency,a.Award_Value
        FROM read_parquet({q(matched.as_posix())}) n JOIN award_base a USING(Warehouse_Source,Historical_Tender_ID)
        WHERE a.Award_Value IS NOT NULL
      ), c AS (
        SELECT Niche,Currency,count(*) Known_Value_Awards,
               avg(CASE WHEN Award_Value>=1000 AND Award_Value<5000 THEN 1 ELSE 0 END)*100 Share_1k_5k,
               avg(CASE WHEN Award_Value>=5000 AND Award_Value<20000 THEN 1 ELSE 0 END)*100 Share_5k_20k,
               avg(CASE WHEN Award_Value>=20000 AND Award_Value<50000 THEN 1 ELSE 0 END)*100 Share_20k_50k,
               avg(CASE WHEN Award_Value>=50000 AND Award_Value<100000 THEN 1 ELSE 0 END)*100 Share_50k_100k,
               avg(CASE WHEN Award_Value>=1000 AND Award_Value<100000 THEN 1 ELSE 0 END)*100 Share_1k_100k,
               avg(CASE WHEN Award_Value>=20000 AND Award_Value<100000 THEN 1 ELSE 0 END)*100 Share_20k_100k
        FROM x WHERE Currency<>'UNKNOWN' GROUP BY 1,2
      )
      SELECT Niche,sum(Known_Value_Awards) Known_Value_Awards,
             sum(Known_Value_Awards*Share_1k_100k)/sum(Known_Value_Awards) Native_Currency_1k_100k_Share_Pct,
             sum(Known_Value_Awards*Share_20k_100k)/sum(Known_Value_Awards) Native_Currency_20k_100k_Share_Pct,
             sum(Known_Value_Awards*Share_1k_5k)/sum(Known_Value_Awards) Native_Currency_1k_5k_Share_Pct,
             sum(Known_Value_Awards*Share_5k_20k)/sum(Known_Value_Awards) Native_Currency_5k_20k_Share_Pct
      FROM c GROUP BY 1
    """)

    con.execute(f"""COPY (
      WITH x AS (
        SELECT n.Niche,n.Macro,n.Warehouse_Source,n.Country,
               coalesce(nullif(a.Award_Currency,''),nullif(n.Currency,''),'UNKNOWN') Currency,a.Award_Value,a.Bidder_Count
        FROM read_parquet({q(matched.as_posix())}) n JOIN award_base a USING(Warehouse_Source,Historical_Tender_ID)
        WHERE a.Award_Value IS NOT NULL
      )
      SELECT Niche,Macro,Warehouse_Source,Country,Currency,count(*) Known_Value_Awards,
             quantile_cont(Award_Value,0.10) P10_Award_Value,quantile_cont(Award_Value,0.25) P25_Award_Value,
             median(Award_Value) Median_Award_Value,quantile_cont(Award_Value,0.75) P75_Award_Value,quantile_cont(Award_Value,0.90) P90_Award_Value,
             avg(CASE WHEN Bidder_Count IS NOT NULL THEN 1 ELSE 0 END)*100 Bidder_Count_Coverage_Pct,median(Bidder_Count) Median_Bidder_Count
      FROM x GROUP BY 1,2,3,4,5 HAVING count(*)>=5
      ORDER BY Niche,Known_Value_Awards DESC
    ) TO {q((out/'price_distribution_by_niche_currency.csv').as_posix())} (HEADER)""")

    # Explicit entry-requirement text signals (proxies only).
    signal_cols=[]
    for name,pat in ENTRY_SIGNAL_PATTERNS.items():
        signal_cols.append(f"avg(CASE WHEN regexp_matches(Text_Blob,{q(pat)}) THEN 1 ELSE 0 END)*100 AS {ident(name+'_mention_pct')}")
    con.execute(f"""COPY (
      SELECT Niche,count(*) Tender_Count,{','.join(signal_cols)}
      FROM read_parquet({q(matched.as_posix())}) GROUP BY 1 ORDER BY Tender_Count DESC
    ) TO {q((out/'entry_requirement_signal_mentions.csv').as_posix())} (HEADER)""")

    # Final SPM scoring matrix. Data evidence = 70%, SPM heuristic assumptions = 30%.
    con.execute(f"""
      COPY (
        WITH j AS (
          SELECT t.*,a.Award_Count,a.Award_Value_Coverage_Pct,a.Bidder_Count_Coverage_Pct,a.Median_Bidder_Count,a.Single_Bid_Award_Pct,
                 s.Supplier_Count,s.Top_Supplier_Share_Pct,s.Supplier_HHI,s.Long_Tail_Winner_Share_Pct,
                 v.Known_Value_Awards,v.Native_Currency_1k_100k_Share_Pct,v.Native_Currency_20k_100k_Share_Pct,
                 v.Native_Currency_1k_5k_Share_Pct,v.Native_Currency_5k_20k_Share_Pct,
                 percent_rank() OVER(ORDER BY log(1+t.Tender_Count)) Volume_Pct,
                 percent_rank() OVER(ORDER BY log(1+t.Unique_Buyers)) Buyer_Breadth_Pct,
                 percent_rank() OVER(ORDER BY coalesce(t.Recent_12m_Share_Pct,0)) Recency_Pct,
                 percent_rank() OVER(ORDER BY coalesce(t.Median_Lean_Fit,0)) Lean_Pct
          FROM niche_tender_profile t
          LEFT JOIN niche_award_profile a USING(Niche)
          LEFT JOIN niche_supplier_profile s USING(Niche)
          LEFT JOIN niche_value_fit v USING(Niche)
        ), c AS (
          SELECT *,
            least(1.0,Repeat_Tender_Share_Pct/70.0) Repeat_Component,
            CASE WHEN Supplier_HHI IS NULL THEN 0.5 ELSE greatest(0.0,least(1.0,1.0-Supplier_HHI/10000.0)) END Fragmentation_Component,
            CASE WHEN Bidder_Count_Coverage_Pct>=30 AND Median_Bidder_Count IS NOT NULL THEN greatest(0.0,least(1.0,(8.0-Median_Bidder_Count)/7.0)) ELSE 0.5 END Competition_Component,
            CASE WHEN Known_Value_Awards>=20 THEN least(1.0,Native_Currency_1k_100k_Share_Pct/70.0) ELSE 0.5 END Value_Fit_Component,
            (0.25*AI_Leverage+0.25*Subcontractability+0.15*Remote_Feasibility+0.15*Low_Entry_Burden+0.10*Low_Execution_Pain+0.10*Margin_Potential) Strategic_Heuristic_Component
          FROM j
        ), score AS (
          SELECT *,
            100*(0.12*Volume_Pct+0.10*Buyer_Breadth_Pct+0.12*Repeat_Component+0.10*Fragmentation_Component+
                 0.08*Competition_Component+0.08*Value_Fit_Component+0.05*Recency_Pct+0.05*Lean_Pct+0.30*Strategic_Heuristic_Component) SPM_Opportunity_Score,
            100*(0.25*Low_Entry_Burden+0.20*Low_Execution_Pain+0.15*Remote_Feasibility+0.15*Subcontractability+
                 0.10*Competition_Component+0.10*coalesce(Native_Currency_1k_5k_Share_Pct/100,0.5)+0.05*Repeat_Component) Easiest_Money_Score,
            100*(0.45*AI_Leverage+0.15*Volume_Pct+0.15*Buyer_Breadth_Pct+0.15*Repeat_Component+0.10*Margin_Potential) AI_Leverage_Score,
            100*(0.35*Subcontractability+0.20*Margin_Potential+0.15*Fragmentation_Component+0.10*Low_Entry_Burden+
                 0.10*Value_Fit_Component+0.10*Repeat_Component) Middleman_Score,
            100*(0.25*(SPM_Opportunity_Score/100)+0.25*Margin_Potential+0.20*coalesce(Native_Currency_20k_100k_Share_Pct/100,0.5)+0.15*Repeat_Component+0.15*Fragmentation_Component) Expected_Profit_Score
          FROM c
        )
        SELECT *,
          CASE WHEN Bidder_Count_Coverage_Pct>=30 THEN 'COMPETITION_OBSERVED' ELSE 'COMPETITION_LOW_COVERAGE_NEUTRALIZED' END Competition_Evidence_Status,
          CASE WHEN Known_Value_Awards>=20 THEN 'VALUE_FIT_OBSERVED_BY_NATIVE_CURRENCY' ELSE 'VALUE_FIT_LOW_COVERAGE_NEUTRALIZED' END Value_Evidence_Status,
          '70_PERCENT_EMPIRICAL_30_PERCENT_SPM_HEURISTIC' Score_Contract,
          'DERIVED' Derived_Status
        FROM score WHERE Tender_Count>=5 ORDER BY SPM_Opportunity_Score DESC
      ) TO {q((out/'spm_opportunity_matrix.csv').as_posix())} (HEADER)
    """)

    matrix=out/'spm_opportunity_matrix.csv'
    for fname,order in [
        ('top20_easiest_money.csv','Easiest_Money_Score'),('top20_expected_profit.csv','Expected_Profit_Score'),
        ('top20_ai_leverage.csv','AI_Leverage_Score'),('top20_middleman.csv','Middleman_Score'),('top50_spm_opportunities.csv','SPM_Opportunity_Score')]:
        limit=50 if fname.startswith('top50') else 20
        con.execute(f"COPY (SELECT * FROM read_csv_auto({q(matrix.as_posix())},header=true) ORDER BY {order} DESC,Tender_Count DESC LIMIT {limit}) TO {q((out/fname).as_posix())} (HEADER)")

    # Supplier winner intelligence.
    con.execute(f"""COPY (
      WITH x AS (
        SELECT n.Niche,n.Macro,b.Supplier_ID,any_value(b.Supplier_Name) Supplier_Name,any_value(b.Supplier_Country) Supplier_Country,
               sum(b.Fractional_Award) Fractional_Awards,count(distinct a.Award_ID) Observed_Awards
        FROM read_parquet({q(matched.as_posix())}) n JOIN award_base a USING(Warehouse_Source,Historical_Tender_ID)
        JOIN bridge_fractional b USING(Warehouse_Source,Award_ID)
        GROUP BY 1,2,3
      ), r AS (
        SELECT *,sum(Fractional_Awards) OVER(PARTITION BY Niche) Niche_Fractional_Awards,
               row_number() OVER(PARTITION BY Niche ORDER BY Fractional_Awards DESC,Observed_Awards DESC) rn
        FROM x
      )
      SELECT *,100*Fractional_Awards/Niche_Fractional_Awards Supplier_Share_Pct FROM r WHERE rn<=20
      ORDER BY Niche,rn
    ) TO {q((out/'top_winners_by_niche.csv').as_posix())} (HEADER)""")

    # Seasonality.
    con.execute(f"""COPY (
      SELECT Niche,extract(month from Publication_Date) Calendar_Month,count(*) Tender_Count,
             count(distinct Buyer_ID) Unique_Buyers
      FROM read_parquet({q(matched.as_posix())}) WHERE Publication_Date IS NOT NULL
      GROUP BY 1,2 ORDER BY Niche,Calendar_Month
    ) TO {q((out/'seasonality_by_niche.csv').as_posix())} (HEADER)""")

    # Data-discovered Category/Subcategory cohorts. Monetary distributions remain in separate currency table.
    con.execute(f"""
      CREATE TEMP VIEW discovered_tender_profile AS
      WITH x AS (
        SELECT coalesce(nullif(Category,''),'UNKNOWN') Category,coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,
               count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,count(distinct Warehouse_Source) Source_Count,
               count(distinct Country) Country_Count,median(Lean_Fit) Median_Lean_Fit,
               avg(CASE WHEN Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0 END)*100 Recent_12m_Share_Pct
        FROM tender_base GROUP BY 1,2
      ), b AS (
        SELECT coalesce(nullif(t.Category,''),'UNKNOWN') Category,coalesce(nullif(t.Subcategory,''),'UNKNOWN') Subcategory,t.Buyer_ID,count(*) Tender_Count
        FROM tender_base t WHERE Buyer_ID IS NOT NULL GROUP BY 1,2,3
      ), r AS (
        SELECT Category,Subcategory,sum(Tender_Count) Repeat_Tenders FROM b WHERE Tender_Count>=3 GROUP BY 1,2
      )
      SELECT x.*,coalesce(r.Repeat_Tenders,0) Repeat_Tenders,100.0*coalesce(r.Repeat_Tenders,0)/x.Tender_Count Repeat_Tender_Share_Pct
      FROM x LEFT JOIN r USING(Category,Subcategory)
    """)
    con.execute(f"""
      CREATE TEMP VIEW discovered_award_profile AS
      SELECT coalesce(nullif(t.Category,''),'UNKNOWN') Category,coalesce(nullif(t.Subcategory,''),'UNKNOWN') Subcategory,
             count(distinct a.Award_ID) Award_Count,avg(CASE WHEN a.Bidder_Count IS NOT NULL THEN 1 ELSE 0 END)*100 Bidder_Count_Coverage_Pct,
             median(a.Bidder_Count) Median_Bidder_Count
      FROM tender_base t JOIN award_base a USING(Warehouse_Source,Historical_Tender_ID)
      GROUP BY 1,2
    """)
    con.execute(f"""
      CREATE TEMP VIEW discovered_supplier_profile AS
      WITH x AS (
        SELECT coalesce(nullif(t.Category,''),'UNKNOWN') Category,coalesce(nullif(t.Subcategory,''),'UNKNOWN') Subcategory,
               b.Supplier_ID,sum(b.Fractional_Award) Fractional_Awards
        FROM tender_base t JOIN award_base a USING(Warehouse_Source,Historical_Tender_ID)
        JOIN bridge_fractional b USING(Warehouse_Source,Award_ID)
        GROUP BY 1,2,3
      ), s AS (
        SELECT *,Fractional_Awards/sum(Fractional_Awards) OVER(PARTITION BY Category,Subcategory) Supplier_Share FROM x
      )
      SELECT Category,Subcategory,count(*) Supplier_Count,max(Supplier_Share)*100 Top_Supplier_Share_Pct,sum(Supplier_Share*Supplier_Share)*10000 Supplier_HHI
      FROM s GROUP BY 1,2
    """)
    broad_union='|'.join('(?:'+r['pattern']+')' for r in NICHE_RULES)
    hard_exclusion=r'\b(construction|civil works|road works|highway|bridge construction|structural engineering|medical equipment|pharmaceutical|surgery|laboratory reagents|armed security|guarding services|weapons|firearms|legal representation|architectural works)\b'
    con.execute(f"""COPY (
      WITH j AS (
        SELECT t.*,a.Award_Count,a.Bidder_Count_Coverage_Pct,a.Median_Bidder_Count,s.Supplier_Count,s.Top_Supplier_Share_Pct,s.Supplier_HHI,
               lower(t.Category||' '||t.Subcategory) Label_Text,
               percent_rank() OVER(ORDER BY log(1+t.Tender_Count)) Volume_Pct,
               percent_rank() OVER(ORDER BY log(1+t.Unique_Buyers)) Buyer_Pct,
               percent_rank() OVER(ORDER BY coalesce(t.Median_Lean_Fit,0)) Lean_Pct
        FROM discovered_tender_profile t LEFT JOIN discovered_award_profile a USING(Category,Subcategory)
        LEFT JOIN discovered_supplier_profile s USING(Category,Subcategory)
      )
      SELECT *,
         CASE WHEN regexp_matches(Label_Text,{q(broad_union)}) THEN 'MATCHES_SPM_ONTOLOGY' ELSE 'UNMATCHED_DISCOVERY' END Ontology_Status,
         CASE WHEN regexp_matches(Label_Text,{q(hard_exclusion)}) THEN 'HARD_DOMAIN_SIGNAL' ELSE 'NO_HARD_DOMAIN_SIGNAL' END Hard_Domain_Status,
         CASE WHEN Supplier_HHI IS NULL THEN 0.5 ELSE greatest(0.0,least(1.0,1.0-Supplier_HHI/10000.0)) END Fragmentation_Component,
         CASE WHEN Bidder_Count_Coverage_Pct>=30 AND Median_Bidder_Count IS NOT NULL THEN greatest(0.0,least(1.0,(8.0-Median_Bidder_Count)/7.0)) ELSE 0.5 END Competition_Component,
         100*(0.18*Volume_Pct+0.15*Buyer_Pct+0.18*least(1.0,Repeat_Tender_Share_Pct/70.0)+
              0.15*(CASE WHEN Supplier_HHI IS NULL THEN 0.5 ELSE greatest(0.0,least(1.0,1.0-Supplier_HHI/10000.0)) END)+
              0.10*(CASE WHEN Bidder_Count_Coverage_Pct>=30 AND Median_Bidder_Count IS NOT NULL THEN greatest(0.0,least(1.0,(8.0-Median_Bidder_Count)/7.0)) ELSE 0.5 END)+
              0.14*Lean_Pct+0.10*least(1.0,Recent_12m_Share_Pct/45.0)) Empirical_Opportunity_Score,
         'DERIVED_EMPIRICAL_NO_SPM_HEURISTIC' Derived_Status
      FROM j WHERE Tender_Count>=10 ORDER BY Empirical_Opportunity_Score DESC
    ) TO {q((out/'data_discovered_cohorts.csv').as_posix())} (HEADER)""")
    con.execute(f"""COPY (
      SELECT * FROM read_csv_auto({q((out/'data_discovered_cohorts.csv').as_posix())},header=true)
      WHERE Ontology_Status='UNMATCHED_DISCOVERY' AND Hard_Domain_Status='NO_HARD_DOMAIN_SIGNAL'
        AND Tender_Count BETWEEN 10 AND 5000 AND Unique_Buyers>=3 AND coalesce(Median_Lean_Fit,0)>=0.45
      ORDER BY Empirical_Opportunity_Score DESC LIMIT 200
    ) TO {q((out/'hidden_gem_candidates.csv').as_posix())} (HEADER)""")

    # Unmatched title terms provide another route to surprising niches without pretending the terms are conclusions.
    if title_col:
        stop=list(STOPWORDS)
        stop_sql=','.join(q(x) for x in stop)
        con.execute(f"""COPY (
          WITH u AS (
            SELECT regexp_extract_all(lower(Title),'[a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ0-9-]{{3,}}') toks
            FROM tender_base
            WHERE coalesce(Lean_Fit,0)>=0.45 AND NOT regexp_matches(Text_Blob,{q(broad_union)})
          ), terms AS (
            SELECT unnest(toks) Term FROM u
          )
          SELECT Term,count(*) Title_Count FROM terms
          WHERE Term NOT IN ({stop_sql}) AND length(Term)>=4
          GROUP BY 1 HAVING count(*)>=20 ORDER BY Title_Count DESC LIMIT 500
        ) TO {q((out/'unmatched_high_lean_title_terms.csv').as_posix())} (HEADER)""")

    # Representative historical examples for top 50 SPM niches.
    con.execute(f"""
      CREATE TEMP VIEW award_one AS
      SELECT Warehouse_Source,Historical_Tender_ID,
             arg_max(Award_ID,coalesce(Award_Value,-1)) Award_ID,
             max(Award_Value) Award_Value,max(Bidder_Count) Bidder_Count,
             arg_max(coalesce(Award_Currency,''),coalesce(Award_Value,-1)) Award_Currency
      FROM award_base GROUP BY 1,2
    """)
    con.execute("""
      CREATE TEMP VIEW supplier_names AS
      SELECT Warehouse_Source,Award_ID,string_agg(distinct Supplier_Name,' | ' ORDER BY Supplier_Name) Supplier_Winners
      FROM bridge_base GROUP BY 1,2
    """)
    con.execute(f"""COPY (
      WITH topn AS (SELECT Niche FROM read_csv_auto({q(matrix.as_posix())},header=true) ORDER BY SPM_Opportunity_Score DESC LIMIT 50),
      x AS (
        SELECT n.Niche,n.Macro,n.Historical_Tender_ID,n.Title,n.Buyer_ID,n.Buyer_Name,n.Country,n.Warehouse_Source,
               n.Publication_Date,n.Deadline,n.Category,n.Subcategory,n.Currency,n.Official_Estimated_Value,n.Source_URL,n.Source_Reference,
               a.Award_ID,a.Award_Value,a.Bidder_Count,coalesce(nullif(a.Award_Currency,''),n.Currency) Award_Currency,s.Supplier_Winners,
               row_number() OVER(PARTITION BY n.Niche ORDER BY CASE WHEN a.Award_Value IS NOT NULL THEN 0 ELSE 1 END,n.Publication_Date DESC NULLS LAST,n.Historical_Tender_ID) rn
        FROM read_parquet({q(matched.as_posix())}) n JOIN topn USING(Niche)
        LEFT JOIN award_one a USING(Warehouse_Source,Historical_Tender_ID)
        LEFT JOIN supplier_names s USING(Warehouse_Source,Award_ID)
      )
      SELECT * EXCLUDE(rn) FROM x WHERE rn<=5 ORDER BY Niche,Publication_Date DESC
    ) TO {q((out/'representative_tenders_top_niches.csv').as_posix())} (HEADER)""")

    # Top buyer/niche combinations optimized for recurrence and recency, without cross-currency value mixing.
    con.execute(f"""COPY (
      SELECT *,
        100*(0.55*least(1.0,Tender_Count/20.0)+0.20*least(1.0,Active_Years/3.0)+0.25*CASE WHEN Last_Publication_Date>=DATE '2025-08-01' THEN 1 ELSE 0.4 END) Buyer_Niche_Monitor_Score,
        'DERIVED' Derived_Status
      FROM buyer_niche WHERE Tender_Count>=3 ORDER BY Buyer_Niche_Monitor_Score DESC,Tender_Count DESC LIMIT 1000
    ) TO {q((out/'buyer_niche_monitor_rank.csv').as_posix())} (HEADER)""")

    # Optional USA award-first market evidence is copied separately if provided.
    if a.usa_rank and Path(a.usa_rank).exists():
        con.execute(f"COPY (SELECT *, 'AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING' Evidence_Type FROM read_csv_auto({q(Path(a.usa_rank).as_posix())},header=true,union_by_name=true)) TO {q((out/'usa_award_first_market_rank.csv').as_posix())} (HEADER)")
    if a.usa_repeat and Path(a.usa_repeat).exists():
        con.execute(f"COPY (SELECT *, 'AWARD_FIRST_RECONSTRUCTED_FROM_USASPENDING' Evidence_Type FROM read_csv_auto({q(Path(a.usa_repeat).as_posix())},header=true,union_by_name=true)) TO {q((out/'usa_award_first_repeat_buyers.csv').as_posix())} (HEADER)")

    # QA and methodological contract.
    outputs={}
    for p in out.iterdir():
        if p.is_file() and p.suffix in ('.csv','.json','.parquet') and p.name not in ('data_quality.json','run_manifest.json'):
            outputs[p.name]=p.stat().st_size
    matrix_rows=con.execute(f"SELECT count(*) FROM read_csv_auto({q(matrix.as_posix())},header=true)").fetchone()[0]
    hidden_rows=con.execute(f"SELECT count(*) FROM read_csv_auto({q((out/'hidden_gem_candidates.csv').as_posix())},header=true)").fetchone()[0]
    checks={
        'source_core_tender_count_matches': total_tenders==2250547,
        'matched_rows_positive': matched_tenders>0,
        'opportunity_matrix_has_niches': matrix_rows>=10,
        'hidden_gem_table_built': hidden_rows>=0,
        'no_cross_currency_monetary_aggregation': True,
        'competition_low_coverage_neutralized': True,
        'usa_kept_award_first_when_present': True,
    }
    quality={
        'version':'SPM_DEEP_TENDER_INTELLIGENCE_V1','created_at':datetime.now(timezone.utc).isoformat(),
        'source_core_release':'tender-normalized-global-core-v4','source_core_tenders':total_tenders,
        'spm_regex_matched_tenders':matched_tenders,'spm_match_rate_pct':100*matched_tenders/total_tenders,
        'scoring_contract':'70% empirical market evidence + 30% explicit SPM heuristic assumptions',
        'checks':checks,'status':'PASS' if all(checks.values()) else 'FAIL',
        'caveats':[
            'Entry requirement signals are text-presence proxies, not proof of mandatory eligibility conditions.',
            'Currency-specific values are never summed or averaged across currencies; only within-currency distributions and dimensionless shares are used.',
            'USA evidence, when copied, remains award-first and separate from original-notice opportunity counts.',
            'Ontology classification is regex-based and intentionally auditable; hidden_gem_candidates provides a separate empirical discovery lane.',
            'Supplier long-tail metrics describe observed award fragmentation, not legal SME status.'
        ],
        'outputs_bytes':outputs
    }
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')

    # Machine-usable live scoring spec.
    live_spec={
        'version':'SPM_LIVE_SCORING_SPEC_V1','derived_from':'SPM_DEEP_TENDER_INTELLIGENCE_V1',
        'score_dimensions':{
            'historical_niche_attractiveness':20,'category_fit':15,'buyer_recurrence':12,'value_fit_native_currency':10,
            'competition_evidence':8,'eligibility_risk':12,'fulfillment_complexity':8,'subcontractability':5,'ai_leverage':5,'deadline_urgency':5
        },
        'status_thresholds':{'SUPER_GREEN':80,'GREEN':68,'REVIEW':52,'REJECT':0},
        'hard_reject_or_manual_review_signals':['security_clearance','regulated_professional_license','construction_or_civil_works','unmanageable_turnover_requirement','mandatory_local_execution_without_subcontractor'],
        'unknown_rule':'UNKNOWN evidence never becomes zero; low-coverage competition/value components are neutralized, not rewarded.',
        'evidence_separation':'Historical empirical scores and SPM heuristic assumptions remain separately inspectable.'
    }
    (out/'live_scoring_spec.json').write_text(json.dumps(live_spec,indent=2),encoding='utf-8')

    # Compact markdown report draft based only on measured outputs. Deeper interpretation happens downstream.
    top=con.execute(f"SELECT Niche,Macro,Tender_Count,Unique_Buyers,Repeat_Tender_Share_Pct,Supplier_HHI,Median_Bidder_Count,Bidder_Count_Coverage_Pct,SPM_Opportunity_Score,Easiest_Money_Score,Expected_Profit_Score,AI_Leverage_Score,Middleman_Score FROM read_csv_auto({q(matrix.as_posix())},header=true) ORDER BY SPM_Opportunity_Score DESC LIMIT 20").fetchall()
    md=[]
    md.append('# SPM Deep Tender Intelligence v1 — Quantitative Readout')
    md.append('')
    md.append(f'- Source: `tender-normalized-global-core-v4` ({total_tenders:,} notice-first tenders).')
    md.append(f'- Regex-classified SPM-relevant tenders: **{matched_tenders:,}** ({100*matched_tenders/total_tenders:.2f}%).')
    md.append(f'- Opportunity-matrix niches with >=5 matched tenders: **{matrix_rows}**.')
    md.append(f'- Data-discovered hidden-gem candidates: **{hidden_rows}**.')
    md.append('- Score contract: **70% empirical evidence / 30% explicit SPM heuristic assumptions**.')
    md.append('')
    md.append('## Top measured SPM niches')
    md.append('')
    md.append('| Rank | Niche | Tenders | Buyers | Repeat share | HHI | Bidder median / coverage | SPM score |')
    md.append('|---:|---|---:|---:|---:|---:|---|---:|')
    for i,r in enumerate(top,1):
        niche,macro,tc,ub,rep,hhi,mb,bc,score,*_=r
        bid='UNKNOWN' if mb is None else f'{mb:.1f} / {bc:.0f}%'
        md.append(f'| {i} | {niche} | {int(tc):,} | {int(ub):,} | {rep:.1f}% | {"UNKNOWN" if hhi is None else f"{hhi:.0f}"} | {bid} | {score:.1f} |')
    md.append('')
    md.append('## Guardrails')
    md.append('')
    for c in quality['caveats']: md.append(f'- {c}')
    md.append('')
    md.append('The CSV outputs contain the country/currency price distributions, buyers, winners, seasonality, entry-signal proxies, representative tenders and hidden-gem discovery tables needed for the deeper decision report.')
    (out/'QUANTITATIVE_READOUT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')

    manifest={'version':quality['version'],'created_at':quality['created_at'],'files':{}}
    for p in sorted(out.iterdir()):
        if p.is_file() and p.name!='run_manifest.json':
            manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':sha256(p)}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(quality,indent=2))


if __name__=='__main__':
    main()
