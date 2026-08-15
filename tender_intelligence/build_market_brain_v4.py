#!/usr/bin/env python3
from __future__ import annotations

"""Build compact historical priors from canonical Global Core v4 with DuckDB.

The output is deliberately compact and evidence-aware. It is NOT a tender verdict.
It summarizes historical market structure so the live engine can prioritize scarce
DCE retrieval compute. Currency values are never aggregated across currencies.
Award-first lanes are excluded from notice/gate opportunity priors.
"""

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

CONTRACT = "TENDER_MARKET_BRAIN_PRIORS_V1"
COUNTRY_CPV_MIN_N = 20
BUYER_MIN_N = 8
MAX_COUNTRY_CPV_BONUS = 8
MAX_BUYER_BONUS = 6


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def choose(cols: set[str], *candidates: str) -> str | None:
    low = {c.casefold(): c for c in cols}
    for cand in candidates:
        if cand.casefold() in low:
            return low[cand.casefold()]
    return None


def norm_bonus(value: float, lo: float, hi: float, span: int) -> int:
    if not math.isfinite(value) or hi <= lo:
        return 0
    x = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return int(round((x * 2 - 1) * span))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--historical", required=True, help="Global Core v4 historical_tenders.parquet")
    ap.add_argument("--award-suppliers", default="", help="Optional award_suppliers.parquet")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hist = Path(args.historical)
    if not hist.is_file():
        raise SystemExit(f"missing {hist}")
    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='5GB'")
    desc = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(hist)]).fetchall()
    cols = {row[0] for row in desc}

    country = choose(cols, "country", "country_code", "buyer_country")
    cpv = choose(cols, "cpv", "cpv_code", "main_cpv", "classification_id")
    buyer = choose(cols, "buyer_name", "buyer", "contracting_authority")
    value = choose(cols, "value", "award_value", "estimated_value")
    currency = choose(cols, "currency", "award_currency")
    evidence = choose(cols, "evidence_grain", "evidence_lane", "grain")
    source = choose(cols, "source", "lane", "source_name", "portal")
    record_id = choose(cols, "record_id", "source_record_id", "notice_id", "id")

    required = {"country": country, "cpv": cpv, "buyer": buyer, "record_id": record_id}
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise SystemExit(json.dumps({"error": "missing_required_columns", "missing": missing, "columns": sorted(cols)}))

    evidence_filter = "TRUE"
    if evidence:
        evidence_filter += f" AND lower(coalesce(cast({ident(evidence)} as varchar),'')) NOT LIKE '%award-first%'"
        evidence_filter += f" AND lower(coalesce(cast({ident(evidence)} as varchar),'')) NOT LIKE '%award_first%'"
    if source:
        evidence_filter += f" AND upper(coalesce(cast({ident(source)} as varchar),'')) NOT IN ('USA','USA_FEDERAL','USASPENDING','AU_AUSTENDER_AWARD_FIRST','AUSTRALIA_AWARD_FIRST')"

    country_expr = f"upper(trim(cast({ident(country)} as varchar)))"
    cpv_expr = f"regexp_extract(cast({ident(cpv)} as varchar), '[0-9]{{2}}', 0)"
    buyer_expr = f"lower(regexp_replace(trim(cast({ident(buyer)} as varchar)), '\\s+', ' ', 'g'))"
    rid_expr = f"cast({ident(record_id)} as varchar)"

    country_cpv_sql = f"""
      SELECT
        {country_expr} country,
        {cpv_expr} cpv_division,
        count(DISTINCT {rid_expr}) sample_size,
        count(DISTINCT {buyer_expr}) unique_buyers,
        count(*) / greatest(count(DISTINCT {buyer_expr}), 1)::DOUBLE notices_per_buyer
      FROM read_parquet(?)
      WHERE {evidence_filter}
        AND {country_expr} <> ''
        AND length({cpv_expr}) = 2
        AND {buyer_expr} <> ''
      GROUP BY 1,2
      HAVING count(DISTINCT {rid_expr}) >= {COUNTRY_CPV_MIN_N}
    """
    cc_rows = con.execute(country_cpv_sql, [str(hist)]).fetchall()

    # Normalize recurrence against the observed distribution; no monetary cross-
    # currency arithmetic is used for this priority signal.
    recurrence = sorted(float(r[4]) for r in cc_rows if r[4] is not None)
    p25 = recurrence[max(0, int(len(recurrence) * .25) - 1)] if recurrence else 1.0
    p75 = recurrence[min(len(recurrence) - 1, int(len(recurrence) * .75))] if recurrence else 1.0

    country_cpv = {}
    for country_v, cpv_v, n, ub, per_buyer in cc_rows:
        bonus = norm_bonus(float(per_buyer or 0), p25, p75, MAX_COUNTRY_CPV_BONUS)
        country_cpv[f"{country_v}|{cpv_v}"] = {
            "sample_size": int(n),
            "unique_buyers": int(ub),
            "notices_per_buyer": round(float(per_buyer or 0), 6),
            "priority_bonus": bonus,
            "signal": "historical demand recurrence only",
        }

    buyer_sql = f"""
      SELECT
        {country_expr} country,
        {buyer_expr} buyer_key,
        count(DISTINCT {rid_expr}) sample_size,
        count(DISTINCT {cpv_expr}) cpv_diversity
      FROM read_parquet(?)
      WHERE {evidence_filter}
        AND {country_expr} <> '' AND {buyer_expr} <> ''
      GROUP BY 1,2
      HAVING count(DISTINCT {rid_expr}) >= {BUYER_MIN_N}
    """
    buyer_rows = con.execute(buyer_sql, [str(hist)]).fetchall()
    counts = sorted(int(r[2]) for r in buyer_rows)
    bp25 = counts[max(0, int(len(counts) * .25) - 1)] if counts else BUYER_MIN_N
    bp75 = counts[min(len(counts) - 1, int(len(counts) * .75))] if counts else BUYER_MIN_N
    buyers = {}
    for country_v, buyer_key, n, cpv_diversity in buyer_rows:
        bonus = norm_bonus(float(n), float(bp25), float(bp75), MAX_BUYER_BONUS)
        buyers[f"{str(country_v).casefold()}|{buyer_key}"] = {
            "sample_size": int(n),
            "repeat_procurements": int(n),
            "cpv_diversity": int(cpv_diversity),
            "priority_bonus": bonus,
            "signal": "historical buyer recurrence only",
        }

    # Currency-preserving descriptive table, useful for analytics but intentionally
    # not consumed by the live priority adapter until explicit currency matching is
    # implemented and validated.
    value_stats = []
    if value and currency:
        value_sql = f"""
          SELECT {country_expr} country, {cpv_expr} cpv_division,
                 upper(trim(cast({ident(currency)} as varchar))) currency,
                 count(*) FILTER (WHERE try_cast({ident(value)} AS DOUBLE) > 1) value_n,
                 median(try_cast({ident(value)} AS DOUBLE)) FILTER (WHERE try_cast({ident(value)} AS DOUBLE) > 1) median_value,
                 quantile_cont(try_cast({ident(value)} AS DOUBLE), .75) FILTER (WHERE try_cast({ident(value)} AS DOUBLE) > 1) p75_value
          FROM read_parquet(?)
          WHERE {evidence_filter} AND {country_expr} <> '' AND length({cpv_expr})=2
          GROUP BY 1,2,3
          HAVING count(*) FILTER (WHERE try_cast({ident(value)} AS DOUBLE) > 1) >= 10
        """
        for row in con.execute(value_sql, [str(hist)]).fetchall():
            value_stats.append({
                "country": row[0], "cpv_division": row[1], "currency": row[2],
                "value_n": int(row[3]), "median_value": float(row[4]), "p75_value": float(row[5]),
            })

    output = {
        "contract": CONTRACT,
        "status": "READY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_release": "tender-normalized-global-core-v4",
        "source_historical_file": hist.name,
        "source_columns": {
            "country": country, "cpv": cpv, "buyer": buyer, "record_id": record_id,
            "value": value, "currency": currency, "evidence": evidence, "source": source,
        },
        "safety": {
            "affects_final_verdict": False,
            "satisfies_dce_gates": False,
            "pre_dce_only": True,
            "max_total_priority_adjustment": 12,
            "cross_currency_aggregation": False,
            "award_first_excluded_from_notice_priors": True,
        },
        "country_cpv": country_cpv,
        "buyers": buyers,
        "currency_preserving_value_stats": value_stats,
        "qa": {
            "country_cpv_cells": len(country_cpv),
            "buyer_priors": len(buyers),
            "value_stat_cells": len(value_stats),
            "country_cpv_min_n": COUNTRY_CPV_MIN_N,
            "buyer_min_n": BUYER_MIN_N,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(output["qa"], indent=2))


if __name__ == "__main__":
    main()
