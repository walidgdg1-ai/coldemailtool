#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--memory", default="5GB")
    args = ap.parse_args()

    core = Path(args.core)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    q = json.loads((core / "data_quality.json").read_text(encoding="utf-8"))
    assert q.get("status") == "PASS", q
    counts = q.get("counts_notice_first") or q.get("counts") or {}
    assert int(counts.get("historical_tenders") or 0) == 2_250_547, counts
    assert int(counts.get("awards") or 0) == 4_286_784, counts
    assert int(counts.get("award_suppliers") or 0) == 3_937_663, counts

    t = (core / "historical_tenders.parquet").as_posix()
    a = (core / "awards.parquet").as_posix()
    b = (core / "award_suppliers.parquet").as_posix()

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET threads={max(1, args.threads)}")
    con.execute(f"SET memory_limit='{args.memory}'")
    con.execute("SET temp_directory='/tmp/spm_award_intelligence_duckdb'")

    con.execute(f"""
    CREATE TEMP TABLE award_base AS
    SELECT
      aa.Warehouse_Source,
      aa.Award_ID,
      aa.Historical_Tender_ID,
      tt.Buyer_ID,
      tt.Buyer_Name,
      coalesce(nullif(tt.Category,''),'UNKNOWN') AS Category,
      coalesce(nullif(tt.Subcategory,''),'UNKNOWN') AS Subcategory,
      coalesce(nullif(tt.Currency,''),'UNKNOWN') AS Currency,
      try_cast(nullif(aa.Award_Value,'') AS DOUBLE) AS Award_Value,
      try_cast(nullif(aa.Bidder_Count,'') AS DOUBLE) AS Bidder_Count,
      try_cast(tt.Publication_Date AS DATE) AS Procurement_Date,
      try_cast(nullif(tt.Lean_Fit,'') AS DOUBLE) AS Lean_Fit
    FROM read_parquet('{a}') aa
    JOIN read_parquet('{t}') tt
      USING (Warehouse_Source, Historical_Tender_ID)
    WHERE nullif(tt.Buyer_ID,'') IS NOT NULL
    """)

    con.execute(f"""
    CREATE TEMP TABLE bridge_clean AS
    SELECT Warehouse_Source, Award_ID, Supplier_ID
    FROM read_parquet('{b}')
    WHERE nullif(Supplier_ID,'') IS NOT NULL
    GROUP BY 1,2,3
    """)

    con.execute("""
    CREATE TEMP TABLE bridge_stats AS
    SELECT Warehouse_Source, Award_ID,
           count(*) AS Supplier_Count,
           min(Supplier_ID) AS Solo_Supplier_ID
    FROM bridge_clean
    GROUP BY 1,2
    """)

    con.execute("""
    CREATE TEMP TABLE category_value_bench AS
    SELECT Warehouse_Source, Category, Subcategory, Currency,
           median(Award_Value) AS Category_Median_Award_Value
    FROM award_base
    WHERE Award_Value IS NOT NULL
    GROUP BY 1,2,3,4
    """)

    con.execute("""
    CREATE TEMP TABLE buyer_supplier_fractional AS
    WITH x AS (
      SELECT ab.Warehouse_Source, ab.Buyer_ID, ab.Category, ab.Subcategory, ab.Currency,
             bc.Award_ID, bc.Supplier_ID,
             1.0 / count(*) OVER (PARTITION BY bc.Warehouse_Source, bc.Award_ID) AS Fractional_Award
      FROM award_base ab
      JOIN bridge_clean bc USING (Warehouse_Source, Award_ID)
    )
    SELECT Warehouse_Source, Buyer_ID, Category, Subcategory, Currency, Supplier_ID,
           sum(Fractional_Award) AS Fractional_Awards
    FROM x
    GROUP BY 1,2,3,4,5,6
    """)

    con.execute("""
    CREATE TEMP TABLE buyer_supplier_summary AS
    WITH s AS (
      SELECT *,
             Fractional_Awards / nullif(sum(Fractional_Awards) OVER (
               PARTITION BY Warehouse_Source, Buyer_ID, Category, Subcategory, Currency
             ),0) AS Supplier_Share
      FROM buyer_supplier_fractional
    )
    SELECT Warehouse_Source, Buyer_ID, Category, Subcategory, Currency,
           count(*) AS Distinct_Suppliers,
           max(Supplier_Share) * 100 AS Top_Supplier_Share_Pct,
           sum(Supplier_Share * Supplier_Share) * 10000 AS Supplier_HHI
    FROM s
    GROUP BY 1,2,3,4,5
    """)

    con.execute("""
    CREATE TEMP TABLE buyer_supplier_churn AS
    WITH solo AS (
      SELECT ab.Warehouse_Source, ab.Buyer_ID, ab.Category, ab.Subcategory, ab.Currency,
             ab.Award_ID, ab.Procurement_Date, bs.Solo_Supplier_ID AS Supplier_ID
      FROM award_base ab
      JOIN bridge_stats bs USING (Warehouse_Source, Award_ID)
      WHERE bs.Supplier_Count = 1 AND ab.Procurement_Date IS NOT NULL
    ), seq AS (
      SELECT *, lag(Supplier_ID) OVER (
        PARTITION BY Warehouse_Source, Buyer_ID, Category, Subcategory, Currency
        ORDER BY Procurement_Date, Award_ID
      ) AS Previous_Supplier_ID
      FROM solo
    )
    SELECT Warehouse_Source, Buyer_ID, Category, Subcategory, Currency,
           count(*) AS Solo_Supplier_Awards,
           count(Previous_Supplier_ID) AS Comparable_Transitions,
           sum(CASE WHEN Previous_Supplier_ID IS NOT NULL AND Supplier_ID <> Previous_Supplier_ID THEN 1 ELSE 0 END) AS Supplier_Switches,
           100.0 * sum(CASE WHEN Previous_Supplier_ID IS NOT NULL AND Supplier_ID <> Previous_Supplier_ID THEN 1 ELSE 0 END)
             / nullif(count(Previous_Supplier_ID),0) AS Supplier_Switch_Rate_Pct
    FROM seq
    GROUP BY 1,2,3,4,5
    """)

    con.execute("""
    CREATE TEMP TABLE buyer_award_metrics AS
    SELECT
      ab.Warehouse_Source,
      ab.Buyer_ID,
      any_value(ab.Buyer_Name) AS Buyer_Name,
      ab.Category,
      ab.Subcategory,
      ab.Currency,
      count(DISTINCT ab.Historical_Tender_ID) AS Procurement_Count,
      count(DISTINCT ab.Award_ID) AS Award_Count,
      min(ab.Procurement_Date) AS First_Procurement_Date,
      max(ab.Procurement_Date) AS Last_Procurement_Date,
      count(DISTINCT extract(year FROM ab.Procurement_Date)) FILTER (WHERE ab.Procurement_Date IS NOT NULL) AS Active_Calendar_Years,
      count(ab.Bidder_Count) AS Bidder_Evidence_Awards,
      100.0 * count(ab.Bidder_Count) / nullif(count(DISTINCT ab.Award_ID),0) AS Bidder_Coverage_Pct,
      median(ab.Bidder_Count) AS Median_Bidder_Count,
      100.0 * sum(CASE WHEN ab.Bidder_Count = 1 THEN 1 ELSE 0 END) / nullif(count(ab.Bidder_Count),0) AS Single_Bid_Share_Observed_Pct,
      count(ab.Award_Value) AS Value_Evidence_Awards,
      100.0 * count(ab.Award_Value) / nullif(count(DISTINCT ab.Award_ID),0) AS Value_Coverage_Pct,
      median(ab.Award_Value) AS Median_Award_Value,
      quantile_cont(ab.Award_Value, 0.25) AS P25_Award_Value,
      quantile_cont(ab.Award_Value, 0.75) AS P75_Award_Value,
      median(ab.Lean_Fit) AS Median_Lean_Fit,
      100.0 * sum(CASE WHEN ab.Award_Value IS NOT NULL AND ab.Award_Value <= cv.Category_Median_Award_Value THEN 1 ELSE 0 END)
        / nullif(count(ab.Award_Value),0) AS Modest_Value_Share_Pct
    FROM award_base ab
    LEFT JOIN category_value_bench cv
      USING (Warehouse_Source, Category, Subcategory, Currency)
    GROUP BY 1,2,4,5,6
    """)

    con.execute("""
    CREATE TEMP TABLE intelligence AS
    WITH joined AS (
      SELECT m.*,
             ss.Distinct_Suppliers, ss.Top_Supplier_Share_Pct, ss.Supplier_HHI,
             ch.Solo_Supplier_Awards, ch.Comparable_Transitions, ch.Supplier_Switches, ch.Supplier_Switch_Rate_Pct,
             CASE
               WHEN m.First_Procurement_Date IS NULL OR m.Last_Procurement_Date IS NULL THEN NULL
               ELSE greatest(1.0, date_diff('day', m.First_Procurement_Date, m.Last_Procurement_Date) / 365.25 + 1.0)
             END AS Active_Years
      FROM buyer_award_metrics m
      LEFT JOIN buyer_supplier_summary ss
        USING (Warehouse_Source, Buyer_ID, Category, Subcategory, Currency)
      LEFT JOIN buyer_supplier_churn ch
        USING (Warehouse_Source, Buyer_ID, Category, Subcategory, Currency)
    ), features AS (
      SELECT *,
        CASE WHEN Active_Years IS NOT NULL THEN Award_Count / Active_Years ELSE NULL END AS Awards_Per_Year,
        least(1.0, ln(1.0 + Award_Count) / ln(21.0)) AS Repeat_Score,
        CASE WHEN Bidder_Coverage_Pct >= 20 AND Median_Bidder_Count IS NOT NULL
             THEN greatest(0.0, least(1.0, (5.0 - Median_Bidder_Count) / 4.0)) ELSE 0.5 END AS Competition_Score,
        CASE WHEN Top_Supplier_Share_Pct IS NOT NULL
             THEN greatest(0.0, least(1.0, 1.0 - Top_Supplier_Share_Pct / 100.0)) ELSE 0.5 END AS Fragmentation_Score,
        CASE WHEN Comparable_Transitions >= 2 AND Supplier_Switch_Rate_Pct IS NOT NULL
             THEN greatest(0.0, least(1.0, Supplier_Switch_Rate_Pct / 100.0)) ELSE 0.5 END AS Churn_Score,
        CASE WHEN Modest_Value_Share_Pct IS NOT NULL
             THEN greatest(0.0, least(1.0, Modest_Value_Share_Pct / 100.0)) ELSE 0.5 END AS Modest_Value_Score,
        CASE WHEN Median_Lean_Fit IS NOT NULL
             THEN greatest(0.0, least(1.0, Median_Lean_Fit / 100.0)) ELSE 0.5 END AS Lean_Score
      FROM joined
    )
    SELECT *,
      round(100.0 * (
        0.25 * Repeat_Score +
        0.20 * Competition_Score +
        0.15 * Fragmentation_Score +
        0.15 * Churn_Score +
        0.15 * Modest_Value_Score +
        0.10 * Lean_Score
      ), 2) AS Easy_Entry_Repeat_Demand_Score,
      CASE
        WHEN Award_Count >= 10 AND coalesce(Top_Supplier_Share_Pct,0) >= 80 THEN 'HIGH_LOCK_IN'
        WHEN Award_Count >= 5 AND coalesce(Top_Supplier_Share_Pct,0) >= 65 THEN 'LOCK_IN_RISK'
        WHEN Award_Count >= 5 AND coalesce(Supplier_Switch_Rate_Pct,0) >= 50 THEN 'CHURN_OPPORTUNITY'
        WHEN Award_Count >= 5 THEN 'REPEAT_MARKET'
        ELSE 'LOW_SAMPLE'
      END AS Market_Behavior_Band,
      CASE WHEN Bidder_Coverage_Pct >= 20 THEN 'COMPETITION_OBSERVED' ELSE 'COMPETITION_LOW_COVERAGE' END AS Competition_Evidence_Status,
      CASE WHEN Comparable_Transitions >= 2 THEN 'CHURN_OBSERVED' ELSE 'CHURN_LOW_COVERAGE' END AS Churn_Evidence_Status,
      'NOTICE_FIRST_GLOBAL_CORE_V4' AS Evidence_Type,
      'DERIVED_AWARD_BEHAVIOR_V1' AS Derived_Status
    FROM features
    """)

    full_path = (out / "buyer_category_award_intelligence.csv").as_posix()
    con.execute(f"COPY (SELECT * FROM intelligence WHERE Award_Count >= 3 ORDER BY Easy_Entry_Repeat_Demand_Score DESC, Award_Count DESC) TO '{full_path}' (HEADER)")

    con.execute(f"""COPY (
      SELECT * FROM intelligence
      WHERE Award_Count >= 3
        AND Bidder_Coverage_Pct >= 20
        AND Median_Bidder_Count <= 2
      ORDER BY Easy_Entry_Repeat_Demand_Score DESC, Award_Count DESC
    ) TO '{(out/'low_competition_hotspots.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      SELECT * FROM intelligence
      WHERE Award_Count >= 5
        AND Comparable_Transitions >= 2
      ORDER BY Supplier_Switch_Rate_Pct DESC, Award_Count DESC
    ) TO '{(out/'supplier_churn.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      SELECT * FROM intelligence
      WHERE Award_Count >= 5
        AND Modest_Value_Share_Pct >= 60
      ORDER BY Easy_Entry_Repeat_Demand_Score DESC, Award_Count DESC
    ) TO '{(out/'small_repeat_awards.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      SELECT * FROM intelligence
      WHERE Award_Count >= 5
        AND Top_Supplier_Share_Pct >= 65
      ORDER BY Top_Supplier_Share_Pct DESC, Award_Count DESC
    ) TO '{(out/'supplier_lockin_risks.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      SELECT * FROM intelligence
      WHERE Award_Count >= 3
      ORDER BY Easy_Entry_Repeat_Demand_Score DESC, Award_Count DESC
      LIMIT 500
    ) TO '{(out/'buyer_watchlist_top500.csv').as_posix()}' (HEADER)""")

    con.execute(f"""COPY (
      SELECT Warehouse_Source, Category, Subcategory, Currency,
             count(*) FILTER (WHERE Award_Count >= 3) AS Repeat_Buyer_Cohorts,
             sum(Award_Count) AS Award_Count,
             sum(Procurement_Count) AS Procurement_Count,
             median(Median_Bidder_Count) FILTER (WHERE Bidder_Coverage_Pct >= 20) AS Median_Observed_Bidders_Across_Buyers,
             median(Single_Bid_Share_Observed_Pct) FILTER (WHERE Bidder_Coverage_Pct >= 20) AS Median_Single_Bid_Share_Pct,
             median(Top_Supplier_Share_Pct) AS Median_Top_Supplier_Share_Pct,
             median(Supplier_Switch_Rate_Pct) FILTER (WHERE Comparable_Transitions >= 2) AS Median_Supplier_Switch_Rate_Pct,
             median(Modest_Value_Share_Pct) AS Median_Modest_Value_Share_Pct,
             median(Easy_Entry_Repeat_Demand_Score) FILTER (WHERE Award_Count >= 3) AS Median_Easy_Entry_Score,
             max(Easy_Entry_Repeat_Demand_Score) AS Best_Buyer_Cohort_Score,
             'NOTICE_FIRST_GLOBAL_CORE_V4' AS Evidence_Type,
             'DERIVED_AWARD_BEHAVIOR_V1' AS Derived_Status
      FROM intelligence
      GROUP BY 1,2,3,4
      HAVING sum(Award_Count) >= 5
      ORDER BY Median_Easy_Entry_Score DESC NULLS LAST, Award_Count DESC
    ) TO '{(out/'category_award_priors.csv').as_posix()}' (HEADER)""")

    output_counts = {}
    for p in sorted(out.glob("*.csv")):
        output_counts[p.name] = int(con.execute(f"SELECT count(*) FROM read_csv_auto('{p.as_posix()}', header=true)").fetchone()[0])

    top = con.execute("""
      SELECT Warehouse_Source, Buyer_Name, Category, Subcategory, Currency,
             Award_Count, Median_Bidder_Count, Bidder_Coverage_Pct,
             Top_Supplier_Share_Pct, Supplier_Switch_Rate_Pct,
             Median_Award_Value, Easy_Entry_Repeat_Demand_Score
      FROM intelligence
      WHERE Award_Count >= 3
      ORDER BY Easy_Entry_Repeat_Demand_Score DESC, Award_Count DESC
      LIMIT 20
    """).fetchall()

    created = datetime.now(timezone.utc).isoformat()
    quality = {
        "version": "SPM_AWARD_INTELLIGENCE_V1",
        "created_at": created,
        "source_release": "tender-normalized-global-core-v4",
        "source_counts": counts,
        "award_grain": "AWARD counted once; award_supplier bridge used only for supplier behavior and fractional shares",
        "currency_safety": "PASS: monetary quantiles and buyer/category comparisons partitioned by source/category/subcategory/currency; no FX mixing",
        "missing_evidence": "UNKNOWN/neutral in heuristic components; never coerced to zero",
        "outputs": output_counts,
        "score_contract": "DERIVED heuristic for historical targeting only; not live eligibility and never a FINAL_SUPER_GREEN decision",
        "usa_lane": "NOT_INCLUDED_V1; USA award-first must remain separately labelled and will be analyzed in a separate lane",
        "status": "PASS",
    }
    (out / "data_quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")

    lines = [
        "# SPM Award Intelligence v1",
        "",
        f"Generated: {created}",
        "",
        "This pass mines award behavior from Global Core v4 notice-first procurement facts. It does not merge the USA award-first lane.",
        "",
        "## Source facts",
        f"- Historical tenders: {counts.get('historical_tenders')}",
        f"- Awards: {counts.get('awards')}",
        f"- Award-supplier links: {counts.get('award_suppliers')}",
        "",
        "## What is new",
        "- buyer x category repeat award cadence",
        "- observed bidder pressure and single-bid share",
        "- supplier fragmentation / lock-in",
        "- supplier switching among single-supplier awards",
        "- modest-value repeat purchasing relative to the same source/category/currency market",
        "- an evidence-aware easy-entry + repeat-demand historical targeting score",
        "",
        "## Top 20 buyer/category historical targeting cohorts",
        "",
        "|#|Source|Buyer|Category|Subcategory|Currency|Awards|Median bidders|Bidder cov %|Top supplier %|Switch %|Median award|Score|",
        "|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, row in enumerate(top, 1):
        src, buyer, cat, sub, cur, ac, mb, bcov, top_share, sw, mav, score = row
        def fmt(x, digits=1):
            if x is None:
                return "UNKNOWN"
            if isinstance(x, (int, float)):
                return f"{x:.{digits}f}"
            return str(x)
        clean_buyer = str(buyer or "UNKNOWN").replace("|", "/")[:80]
        lines.append(
            f"|{i}|{src}|{clean_buyer}|{cat}|{sub}|{cur}|{ac}|{fmt(mb)}|{fmt(bcov)}|{fmt(top_share)}|{fmt(sw)}|{fmt(mav,0)}|{fmt(score)}|"
        )
    lines += [
        "",
        "## Interpretation guardrails",
        "- This is historical targeting intelligence, not a live bid decision.",
        "- Low bidder counts are only used when coverage is sufficient; otherwise the competition feature is neutral.",
        "- Supplier switching is only used when at least two comparable solo-supplier transitions exist; otherwise churn is neutral.",
        "- Monetary values are never aggregated across currencies.",
        "- A live tender still requires DCE mandatory-gate verification before FINAL_SUPER_GREEN.",
    ]
    (out / "AWARD_INTELLIGENCE_READOUT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest = {"version": quality["version"], "created_at": created, "files": {}}
    for p in sorted(out.iterdir()):
        if p.is_file() and p.name != "run_manifest.json":
            data = p.read_bytes()
            manifest["files"][p.name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(quality, indent=2))


if __name__ == "__main__":
    main()
