#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("HD_EXTRA_REFERENCE_BANK")
ROOT.mkdir(parents=True, exist_ok=True)


def run_game(index: int) -> dict:
    env = os.environ.copy()
    env.update({
        "GAME_INDEX": str(index),
        "TARGET_PER_GAME": "15",
        "MIN_WIDTH": "960",
        "MIN_HEIGHT": "540",
        "PYTHONPATH": "tools",
    })
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import sitecustomize; sitecustomize.fallback()"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1400,
            check=False,
        )
        Path(f"gallery_harvest_{index:02d}.log").write_text(proc.stdout or "", encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        text = exc.stdout if isinstance(exc.stdout, str) else ""
        Path(f"gallery_harvest_{index:02d}.log").write_text(text + "\nTIMEOUT\n", encoding="utf-8")
        return {"index": index, "status": "timeout", "count": 0}

    folders = sorted(ROOT.glob(f"{index:02d}_*"))
    folder = folders[0] if folders else None
    count = len(list((folder / "images_hd_extra").glob("*"))) if folder else 0
    return {
        "index": index,
        "status": "complete" if count == 15 else "partial",
        "count": count,
        "folder": folder.name if folder else None,
    }


def main() -> int:
    # The workflow exports GAME_INDEX=2. Disable the parent's automatic atexit
    # fallback; only the 31 isolated child processes may write game output.
    os.environ["GAME_INDEX"] = "0"
    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(run_game, index): index for index in range(1, 32)}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result), flush=True)
    results.sort(key=lambda row: row["index"])
    summary = {
        "completed_games": sum(row["count"] == 15 for row in results),
        "games_with_any_images": sum(row["count"] > 0 for row in results),
        "total_selected_images": sum(row["count"] for row in results),
        "games": results,
    }
    Path("HD_PARALLEL_GALLERY_SUMMARY.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
