#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def q(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def first_col(cols: set[str], candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in cols}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def schema(con: duckdb.DuckDBPyConnection, path: Path) -> dict[str, str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(path.as_posix())})").fetchall()
    return {r[0]: r[1] for r in rows}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fnum(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matched", required=True, help="SPM discovery matched_tenders.parquet")
    parser.add_argument("--matrix", required=True, help="SPM tender-only discovery matrix CSV")
    parser.add_argument("--awards", required=True, help="Global Core v4 awards.parquet")
    parser.add_argument("--suppliers", required=True, help="Global Core v4 award_suppliers.parquet")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    matched = Path(args.matched)
    matrix = Path(args.matrix)
    awards = Path(args.awards)
    suppliers = Path(args.suppliers)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    temp_dir = out / "ducktmp"
    temp_dir.mkdir(exist_ok=True)

    for path in (matched, matrix, awards, suppliers):
        if not path.exists():
            raise SystemExit(f"MISSING_INPUT {path}")

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=2")
    con.execute("SET memory_limit='4GB'")
    con.execute(f"SET temp_directory={q(temp_dir.as_posix())}")
    con.execute("SET max_temp_directory_size='12GB'")

    matched_schema = schema(con, matched)
    award_schema = schema(con, awards)
    supplier_schema = schema(con, suppliers)
    mcols, acols, scols = set(matched_schema), set(award_schema), set(supplier_schema)

    m_source = first_col(mcols, ["Warehouse_Source"])
    m_tender = first_col(mcols, ["Historical_Tender_ID"])
    m_niche = first_col(mcols, ["Niche"])
    if not m_source or not m_tender or not m_niche:
        raise SystemExit("MATCHED_TENDERS_MISSING_KEYS")

    a_source = first_col(acols, ["Warehouse_Source"])
    a_tender = first_col(acols, ["Historical_Tender_ID"])
    a_award = first_col(acols, ["Award_ID"])
    a_value = first_col(acols, ["Award_Value", "Official_Award_Value", "Value"])
    a_bidder = first_col(acols, ["Bidder_Count", "Number_Of_Offers", "NumberOfTenderers"])
    a_currency = first_col(acols, ["Award_Currency", "Currency", "Value_Currency"])
    if not a_source or not a_tender or not a_award:
        raise SystemExit("AWARDS_MISSING_KEYS")

    s_source = first_col(scols, ["Warehouse_Source"])
    s_award = first_col(scols, ["Award_ID"])
    s_supplier = first_col(scols, ["Supplier_ID"])
    s_name = first_col(scols, ["Supplier_Name"])
    s_country = first_col(scols, ["Supplier_Country", "Country"])
    if not s_source or not s_award or not s_supplier:
        raise SystemExit("AWARD_SUPPLIERS_MISSING_KEYS")

    profile = {
        "matched": matched_schema,
        "awards": award_schema,
        "award_suppliers": supplier_schema,
        "resolved_columns": {
            "matched": {"source": m_source, "tender": m_tender, "niche": m_niche},
            "awards": {
                "source": a_source,
                "tender": a_tender,
                "award": a_award,
                "value": a_value,
                "bidder_count": a_bidder,
                "currency": a_currency,
            },
            "award_suppliers": {
                "source": s_source,
                "award": s_award,
                "supplier": s_supplier,
                "name": s_name,
                "country": s_country,
            },
        },
    }
    (out / "schema_profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")

    # Materialize only the tiny SPM keyset once. All expensive work below is a semi-join
    # against these already-classified tenders; no full-corpus regex/classification rerun.
    con.execute(f"""
        CREATE TEMP TABLE spm_keys AS
        SELECT DISTINCT
            cast({ident(m_source)} as varchar) AS Warehouse_Source,
            cast({ident(m_tender)} as varchar) AS Historical_Tender_ID,
            cast({ident(m_niche)} as varchar) AS Niche
        FROM read_parquet({q(matched.as_posix())})
        WHERE {ident(m_niche)} IS NOT NULL
    """)

    aval = f"try_cast(a.{ident(a_value)} AS DOUBLE)" if a_value else "NULL::DOUBLE"
    abid = f"try_cast(a.{ident(a_bidder)} AS DOUBLE)" if a_bidder else "NULL::DOUBLE"
    acur = f"cast(a.{ident(a_currency)} AS varchar)" if a_currency else "NULL::VARCHAR"

    filtered_awards = out / "spm_awards.parquet"
    con.execute(f"""
        COPY (
            SELECT
                k.Niche,
                cast(a.{ident(a_source)} as varchar) AS Warehouse_Source,
                cast(a.{ident(a_tender)} as varchar) AS Historical_Tender_ID,
                cast(a.{ident(a_award)} as varchar) AS Award_ID,
                {aval} AS Award_Value,
                {abid} AS Bidder_Count,
                coalesce(nullif({acur}, ''), 'UNKNOWN') AS Award_Currency
            FROM read_parquet({q(awards.as_posix())}) a
            JOIN spm_keys k
              ON cast(a.{ident(a_source)} as varchar)=k.Warehouse_Source
             AND cast(a.{ident(a_tender)} as varchar)=k.Historical_Tender_ID
        ) TO {q(filtered_awards.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    sname = f"cast(s.{ident(s_name)} AS varchar)" if s_name else "'UNKNOWN'"
    scountry = f"cast(s.{ident(s_country)} AS varchar)" if s_country else "'UNKNOWN'"
    filtered_suppliers = out / "spm_award_suppliers.parquet"
    con.execute(f"""
        COPY (
            SELECT DISTINCT
                a.Niche,
                cast(s.{ident(s_source)} as varchar) AS Warehouse_Source,
                cast(s.{ident(s_award)} as varchar) AS Award_ID,
                cast(s.{ident(s_supplier)} as varchar) AS Supplier_ID,
                {sname} AS Supplier_Name,
                {scountry} AS Supplier_Country
            FROM read_parquet({q(suppliers.as_posix())}) s
            JOIN (
                SELECT DISTINCT Niche, Warehouse_Source, Award_ID
                FROM read_parquet({q(filtered_awards.as_posix())})
            ) a
              ON cast(s.{ident(s_source)} as varchar)=a.Warehouse_Source
             AND cast(s.{ident(s_award)} as varchar)=a.Award_ID
            WHERE s.{ident(s_supplier)} IS NOT NULL
        ) TO {q(filtered_suppliers.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    # Coverage and competition. UNKNOWN bidder count stays UNKNOWN and is not turned into zero.
    competition_csv = out / "competition_by_niche.csv"
    con.execute(f"""
        COPY (
            WITH tender_counts AS (
                SELECT Niche, count(*) AS Matched_Tenders
                FROM spm_keys GROUP BY 1
            ), award_stats AS (
                SELECT
                    Niche,
                    count(DISTINCT Award_ID) AS Award_Count,
                    count(DISTINCT Historical_Tender_ID) AS Tenders_With_Award,
                    count(DISTINCT CASE WHEN Award_Value IS NOT NULL AND Award_Value>0 THEN Award_ID END) AS Awards_With_Value,
                    count(DISTINCT CASE WHEN Bidder_Count IS NOT NULL THEN Award_ID END) AS Awards_With_Bidder_Count,
                    median(Bidder_Count) FILTER (WHERE Bidder_Count IS NOT NULL) AS Median_Bidder_Count,
                    avg(CASE WHEN Bidder_Count=1 THEN 1.0 ELSE 0.0 END)
                        FILTER (WHERE Bidder_Count IS NOT NULL) * 100 AS Single_Bid_Share_Pct
                FROM read_parquet({q(filtered_awards.as_posix())})
                GROUP BY 1
            )
            SELECT
                t.Niche,
                t.Matched_Tenders,
                coalesce(a.Award_Count,0) AS Award_Count,
                coalesce(a.Tenders_With_Award,0) AS Tenders_With_Award,
                100.0*coalesce(a.Tenders_With_Award,0)/nullif(t.Matched_Tenders,0) AS Tender_Award_Linkage_Pct,
                100.0*coalesce(a.Awards_With_Value,0)/nullif(a.Award_Count,0) AS Award_Value_Coverage_Pct,
                100.0*coalesce(a.Awards_With_Bidder_Count,0)/nullif(a.Award_Count,0) AS Bidder_Count_Coverage_Pct,
                a.Median_Bidder_Count,
                a.Single_Bid_Share_Pct,
                CASE
                    WHEN a.Median_Bidder_Count IS NULL THEN 50.0
                    ELSE least(100.0, greatest(0.0,
                        0.70*(100.0 - 15.0*greatest(a.Median_Bidder_Count-1.0,0.0))
                        + 0.30*coalesce(a.Single_Bid_Share_Pct,50.0)
                    ))
                END AS Competition_Opportunity_Score
            FROM tender_counts t LEFT JOIN award_stats a USING(Niche)
            ORDER BY Competition_Opportunity_Score DESC, t.Matched_Tenders DESC
        ) TO {q(competition_csv.as_posix())} (HEADER)
    """)

    # Monetary values are never summed or compared raw across currencies. Quantiles are
    # computed per currency; the cross-currency score is an average of within-currency
    # percentile ranks, weighted only by log observation count.
    value_csv = out / "award_value_by_niche_currency.csv"
    con.execute(f"""
        COPY (
            WITH x AS (
                SELECT Niche, Award_Currency AS Currency, Award_Value
                FROM read_parquet({q(filtered_awards.as_posix())})
                WHERE Award_Value IS NOT NULL AND Award_Value>0
                  AND Award_Currency IS NOT NULL AND Award_Currency<>'UNKNOWN'
            )
            SELECT
                Niche, Currency, count(*) AS Known_Value_Awards,
                approx_quantile(Award_Value,0.10) AS P10_Award_Value,
                approx_quantile(Award_Value,0.25) AS P25_Award_Value,
                approx_quantile(Award_Value,0.50) AS Median_Award_Value,
                approx_quantile(Award_Value,0.75) AS P75_Award_Value,
                approx_quantile(Award_Value,0.90) AS P90_Award_Value
            FROM x GROUP BY 1,2
            ORDER BY Niche, Known_Value_Awards DESC
        ) TO {q(value_csv.as_posix())} (HEADER)
    """)

    con.execute(f"""
        CREATE TEMP VIEW niche_value_relative AS
        WITH c AS (
            SELECT * FROM read_csv_auto({q(value_csv.as_posix())}, header=true)
            WHERE Known_Value_Awards>=3 AND Median_Award_Value>0
        ), ranked AS (
            SELECT *, 100.0*percent_rank() OVER(PARTITION BY Currency ORDER BY ln(Median_Award_Value)) AS Currency_Value_Percentile
            FROM c
        )
        SELECT
            Niche,
            sum(Currency_Value_Percentile*ln(1+Known_Value_Awards))/nullif(sum(ln(1+Known_Value_Awards)),0) AS Relative_Value_Score,
            sum(Known_Value_Awards) AS Known_Value_Awards,
            count(*) AS Currency_Cohorts
        FROM ranked GROUP BY 1
    """)

    # Supplier fragmentation is calculated only on the shortlisted award bridge.
    # Fractional award weights prevent a consortium award from being multiplied by supplier count.
    supplier_csv = out / "supplier_fragmentation_by_niche.csv"
    winners_csv = out / "top_winners_by_niche.csv"
    con.execute(f"""
        CREATE TEMP TABLE supplier_fractional AS
        WITH d AS (
            SELECT DISTINCT Niche,Warehouse_Source,Award_ID,Supplier_ID,Supplier_Name,Supplier_Country
            FROM read_parquet({q(filtered_suppliers.as_posix())})
        )
        SELECT *, 1.0/count(*) OVER(PARTITION BY Warehouse_Source,Award_ID) AS Fractional_Award
        FROM d
    """)
    con.execute(f"""
        COPY (
            WITH sx AS (
                SELECT Niche,Supplier_ID,any_value(Supplier_Name) AS Supplier_Name,
                       any_value(Supplier_Country) AS Supplier_Country,
                       sum(Fractional_Award) AS Fractional_Awards,
                       count(DISTINCT Award_ID) AS Observed_Awards
                FROM supplier_fractional GROUP BY 1,2
            ), totals AS (
                SELECT Niche,sum(Fractional_Awards) AS Niche_Fractional_Awards FROM sx GROUP BY 1
            ), ranked AS (
                SELECT sx.*,t.Niche_Fractional_Awards,
                       100.0*sx.Fractional_Awards/nullif(t.Niche_Fractional_Awards,0) AS Supplier_Share_Pct,
                       row_number() OVER(PARTITION BY sx.Niche ORDER BY sx.Fractional_Awards DESC,sx.Supplier_ID) AS rn
                FROM sx JOIN totals t USING(Niche)
            )
            SELECT * FROM ranked WHERE rn<=25 ORDER BY Niche,rn
        ) TO {q(winners_csv.as_posix())} (HEADER)
    """)
    con.execute(f"""
        COPY (
            WITH sx AS (
                SELECT Niche,Supplier_ID,sum(Fractional_Award) AS Fractional_Awards
                FROM supplier_fractional GROUP BY 1,2
            ), shares AS (
                SELECT Niche,Supplier_ID,Fractional_Awards,
                       Fractional_Awards/nullif(sum(Fractional_Awards) OVER(PARTITION BY Niche),0) AS share
                FROM sx
            )
            SELECT
                Niche,
                count(*) AS Observed_Suppliers,
                100.0*max(share) AS Top_Supplier_Share_Pct,
                sum(share*share) AS Supplier_HHI,
                least(100.0,greatest(0.0,
                    0.5*(100.0-100.0*max(share)) + 0.5*(100.0*(1.0-sum(share*share)))
                )) AS Supplier_Fragmentation_Score
            FROM shares GROUP BY 1
            ORDER BY Supplier_Fragmentation_Score DESC
        ) TO {q(supplier_csv.as_posix())} (HEADER)
    """)

    enriched_csv = out / "spm_enriched_matrix.csv"
    con.execute(f"""
        COPY (
            WITH d AS (
                SELECT * FROM read_csv_auto({q(matrix.as_posix())}, header=true)
            ), c AS (
                SELECT * FROM read_csv_auto({q(competition_csv.as_posix())}, header=true)
            ), s AS (
                SELECT * FROM read_csv_auto({q(supplier_csv.as_posix())}, header=true)
            ), joined AS (
                SELECT
                    d.*,
                    c.Award_Count,
                    c.Tender_Award_Linkage_Pct,
                    c.Award_Value_Coverage_Pct,
                    c.Bidder_Count_Coverage_Pct,
                    c.Median_Bidder_Count,
                    c.Single_Bid_Share_Pct,
                    coalesce(c.Competition_Opportunity_Score,50.0) AS Competition_Opportunity_Score,
                    v.Known_Value_Awards,
                    v.Currency_Cohorts,
                    coalesce(v.Relative_Value_Score,50.0) AS Relative_Value_Score,
                    s.Observed_Suppliers,
                    s.Top_Supplier_Share_Pct,
                    s.Supplier_HHI,
                    coalesce(s.Supplier_Fragmentation_Score,50.0) AS Supplier_Fragmentation_Score,
                    least(100.0,greatest(0.0,
                        0.40*coalesce(c.Tender_Award_Linkage_Pct,0.0)
                       +0.30*coalesce(c.Award_Value_Coverage_Pct,0.0)
                       +0.30*coalesce(c.Bidder_Count_Coverage_Pct,0.0)
                    )) AS Award_Evidence_Score
                FROM d
                LEFT JOIN c USING(Niche)
                LEFT JOIN niche_value_relative v USING(Niche)
                LEFT JOIN s USING(Niche)
            )
            SELECT *,
                0.50*Discovery_Score
               +0.20*Competition_Opportunity_Score
               +0.15*Relative_Value_Score
               +0.10*Supplier_Fragmentation_Score
               +0.05*Award_Evidence_Score AS Enriched_Opportunity_Score,
                0.55*Easy_Money_Proxy
               +0.20*Competition_Opportunity_Score
               +0.15*Supplier_Fragmentation_Score
               +0.10*Award_Evidence_Score AS Easy_Money_Enriched_Score,
                0.35*Easy_Money_Proxy
               +0.25*Relative_Value_Score
               +0.15*Competition_Opportunity_Score
               +0.15*(100.0*Margin_Potential)
               +0.10*Supplier_Fragmentation_Score AS Expected_Profit_Proxy,
                0.70*AI_Leverage_Score
               +0.15*Relative_Value_Score
               +0.10*Competition_Opportunity_Score
               +0.05*Award_Evidence_Score AS AI_Leverage_Enriched_Score,
                0.65*Middleman_Proxy
               +0.15*Relative_Value_Score
               +0.10*Supplier_Fragmentation_Score
               +0.10*Award_Evidence_Score AS Middleman_Enriched_Score,
                'TARGETED_AWARD_ENRICHMENT_V1' AS Enrichment_Contract,
                'DERIVED' AS Enriched_Status
            FROM joined
            ORDER BY Enriched_Opportunity_Score DESC
        ) TO {q(enriched_csv.as_posix())} (HEADER)
    """)

    ranking_specs = {
        "top20_enriched_opportunities.csv": "Enriched_Opportunity_Score",
        "top20_easiest_money_enriched.csv": "Easy_Money_Enriched_Score",
        "top20_expected_profit_proxy.csv": "Expected_Profit_Proxy",
        "top20_ai_leverage_enriched.csv": "AI_Leverage_Enriched_Score",
        "top20_middleman_enriched.csv": "Middleman_Enriched_Score",
        "top20_low_competition.csv": "Competition_Opportunity_Score",
    }
    for filename, score in ranking_specs.items():
        con.execute(f"""
            COPY (
                SELECT * FROM read_csv_auto({q(enriched_csv.as_posix())},header=true)
                ORDER BY {ident(score)} DESC, Tender_Count DESC LIMIT 20
            ) TO {q((out/filename).as_posix())} (HEADER)
        """)

    enriched_rows = read_csv_rows(enriched_csv)
    priors = {
        "version": "SPM_LIVE_SCORING_PRIORS_TARGETED_AWARD_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": {
            "historical_notice_scope": "SPM-matched tenders from full Core v4 discovery",
            "award_enrichment": "semi-join only on matched Historical_Tender_ID + Warehouse_Source",
            "money_rule": "raw award values are never aggregated across currencies; Relative_Value_Score uses within-currency percentile ranks",
            "missing_rule": "missing bidder/value/supplier evidence remains missing; neutral score 50 is used only inside derived ranking components",
            "dce_rule": "DCE is not required for historical ranking; use it only to validate mandatory gates on shortlisted live tenders",
            "expected_profit_warning": "Expected_Profit_Proxy is a ranking proxy, not a forecast of actual profit",
        },
        "niches": {},
    }
    for row in enriched_rows:
        niche = row.get("Niche")
        if not niche:
            continue
        priors["niches"][niche] = {
            "tender_count": int(fnum(row.get("Tender_Count"), 0)),
            "unique_buyers": int(fnum(row.get("Unique_Buyers"), 0)),
            "discovery_score": fnum(row.get("Discovery_Score"), 50),
            "enriched_opportunity_score": fnum(row.get("Enriched_Opportunity_Score"), 50),
            "easy_money_score": fnum(row.get("Easy_Money_Enriched_Score"), 50),
            "expected_profit_proxy": fnum(row.get("Expected_Profit_Proxy"), 50),
            "ai_leverage_score": fnum(row.get("AI_Leverage_Enriched_Score"), 50),
            "middleman_score": fnum(row.get("Middleman_Enriched_Score"), 50),
            "competition_score": fnum(row.get("Competition_Opportunity_Score"), 50),
            "relative_value_score": fnum(row.get("Relative_Value_Score"), 50),
            "supplier_fragmentation_score": fnum(row.get("Supplier_Fragmentation_Score"), 50),
            "award_evidence_score": fnum(row.get("Award_Evidence_Score"), 0),
            "median_bidder_count": None if row.get("Median_Bidder_Count") in (None, "") else fnum(row.get("Median_Bidder_Count")),
            "single_bid_share_pct": None if row.get("Single_Bid_Share_Pct") in (None, "") else fnum(row.get("Single_Bid_Share_Pct")),
        }
    (out / "live_scoring_priors.json").write_text(json.dumps(priors, indent=2), encoding="utf-8")

    counts = {
        "spm_matched_tenders": con.execute("SELECT count(*) FROM spm_keys").fetchone()[0],
        "spm_niches": con.execute("SELECT count(DISTINCT Niche) FROM spm_keys").fetchone()[0],
        "linked_awards": con.execute(f"SELECT count(DISTINCT Award_ID) FROM read_parquet({q(filtered_awards.as_posix())})").fetchone()[0],
        "award_supplier_rows": con.execute(f"SELECT count(*) FROM read_parquet({q(filtered_suppliers.as_posix())})").fetchone()[0],
        "enriched_niches": len(enriched_rows),
    }
    quality = {
        "status": "PASS" if counts["spm_matched_tenders"] >= 60000 and counts["spm_niches"] >= 40 else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "source_contract": "Global Core v4 awards + award_suppliers joined only to successful SPM Tender Discovery v1 matches",
        "currency_safety": "PASS: no raw cross-currency monetary aggregation in scoring",
        "dce_dependency": "NONE_FOR_HISTORICAL_RANKING",
    }
    (out / "data_quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
    if quality["status"] != "PASS":
        raise SystemExit(f"QA_FAILED {quality}")

    top_enriched = sorted(enriched_rows, key=lambda r: fnum(r.get("Enriched_Opportunity_Score")), reverse=True)[:20]
    top_easy = sorted(enriched_rows, key=lambda r: fnum(r.get("Easy_Money_Enriched_Score")), reverse=True)[:10]
    top_profit = sorted(enriched_rows, key=lambda r: fnum(r.get("Expected_Profit_Proxy")), reverse=True)[:10]

    def md_table(rows: list[dict[str, str]], score_col: str) -> str:
        lines = ["|#|Niche|Tenders|Score|Median bidders|Award evidence|", "|---:|---|---:|---:|---:|---:|"]
        for idx, row in enumerate(rows, 1):
            mb = row.get("Median_Bidder_Count") or "UNKNOWN"
            ev = fnum(row.get("Award_Evidence_Score"))
            lines.append(f"|{idx}|{row.get('Niche','')}|{int(fnum(row.get('Tender_Count'))):,}|{fnum(row.get(score_col)):.1f}|{mb}|{ev:.1f}%|")
        return "\n".join(lines)

    readout = f"""# SPM Targeted Award Enrichment v1

This stage **does not retrieve historical DCEs**. It reuses the successful full-corpus tender classification, then semi-joins award and supplier facts only for the SPM-matched tender keyset.

## QA

- SPM matched tenders analyzed: **{counts['spm_matched_tenders']:,}**
- SPM niches: **{counts['spm_niches']:,}**
- Linked awards: **{counts['linked_awards']:,}**
- Linked award-supplier rows: **{counts['award_supplier_rows']:,}**
- Historical DCE dependency: **none**
- Raw cross-currency monetary aggregation: **forbidden / not used**

## Top enriched opportunities

{md_table(top_enriched, 'Enriched_Opportunity_Score')}

## Top easiest-money proxy

{md_table(top_easy, 'Easy_Money_Enriched_Score')}

## Top expected-profit proxy

{md_table(top_profit, 'Expected_Profit_Proxy')}

## Interpretation

`Expected_Profit_Proxy` is a prioritization score, not a profit forecast. Award values are compared only within their own currency via percentile ranks before being collapsed into a dimensionless score. Missing bidder/value/supplier evidence is retained as missing and receives a neutral prior only inside derived scoring components.

For live tenders, use `live_scoring_priors.json` as historical priors. Retrieve/read a DCE only after a live opportunity survives notice-level scoring and when mandatory eligibility, deliverables, or commercial gates remain unresolved.
"""
    (out / "QUANTITATIVE_READOUT.md").write_text(readout, encoding="utf-8")

    # The two filtered parquet files are useful for audit/debugging but should not be committed.
    print("SPM_TARGETED_AWARD_ENRICHMENT_PASS", json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
