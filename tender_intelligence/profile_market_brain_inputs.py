#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path("market-intelligence-v3")
OUT = Path("tender_intelligence/market_brain_input_profile.json")


def profile_csv(path: Path) -> dict:
    rows = 0
    samples = []
    columns: list[str] = []
    nullish: dict[str, int] = {}
    uniques: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        uniques = {c: set() for c in columns[:40]}
        nullish = {c: 0 for c in columns[:40]}
        for row in reader:
            rows += 1
            if len(samples) < 3:
                samples.append({k: row.get(k) for k in columns[:25]})
            for c in columns[:40]:
                v = str(row.get(c) or "").strip()
                if not v or v.upper() in {"UNKNOWN", "NULL", "NONE", "N/A"}:
                    nullish[c] += 1
                if len(uniques[c]) < 1000 and v:
                    uniques[c].add(v)
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "rows": rows,
        "columns": columns,
        "nullish_first40": nullish,
        "unique_sample_counts_first40": {k: len(v) for k, v in uniques.items()},
        "samples": samples,
    }


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"Missing {ROOT}")
    files = sorted(ROOT.glob("*.csv"))
    if not files:
        raise SystemExit("No Market Intelligence v3 CSVs downloaded")
    profile = {
        "contract": "TENDER_MARKET_BRAIN_INPUT_PROFILE_V1",
        "source_release": "tender-global-market-intelligence-v3",
        "files": [profile_csv(p) for p in files],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(files), "rows": sum(x["rows"] for x in profile["files"]), "out": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
