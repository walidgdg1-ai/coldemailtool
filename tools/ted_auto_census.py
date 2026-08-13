#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

API = "https://api.ted.europa.eu/v3/notices/search"
QUERY = "form-type = result AND publication-date >= 20230811 AND publication-date <= 20260811 SORT BY publication-date DESC"
QUERY_FP = "sha256:7c0e5ee5be6ec4b1c81d1c67f2318056c8ffe86897d114707c40f488e32c8cd5"
FULL_FIELDS = [
    "publication-number", "publication-date", "notice-identifier", "notice-title", "form-type", "notice-type",
    "procedure-identifier", "procedure-type", "buyer-name", "buyer-country", "classification-cpv",
    "title-proc", "description-proc", "estimated-value-proc", "estimated-value-cur-proc",
    "result-lot-identifier", "result-value-lot", "result-value-cur-lot", "result-value-notice", "result-value-cur-notice",
    "tender-identifier", "tender-lot-identifier", "tender-value", "tender-value-cur",
    "winner-name", "winner-country", "winner-identifier", "winner-decision-date", "winner-selection-status",
    "received-submissions-type-code", "received-submissions-type-val",
]
MINIMAL_FIELDS = ["publication-number", "publication-date", "notice-identifier", "form-type", "notice-type"]


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cell(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def request(token: str, limit: int, fields: list[str], retries: int = 8) -> dict:
    payload = {
        "query": QUERY,
        "fields": fields,
        "paginationMode": "ITERATION",
        "limit": limit,
        "iterationNextToken": token,
    }
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            API,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=150) as r:
                obj = json.loads(r.read())
                if r.status != 200:
                    raise RuntimeError(f"HTTP {r.status}")
                return obj
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                try:
                    delay = float(retry_after)
                except Exception:
                    delay = min(60.0, 2.0 ** attempt)
                delay = max(2.0, delay)
                print("TED_HTTP_RETRY", e.code, "attempt", attempt + 1, "sleep", delay, flush=True)
                time.sleep(delay)
                continue
            raise RuntimeError(f"TED HTTP {e.code}: {msg[:4000]}")
        except Exception as e:
            if attempt < retries - 1:
                delay = min(60.0, 2.0 ** attempt)
                print("TED_NETWORK_RETRY", repr(e), "attempt", attempt + 1, "sleep", delay, flush=True)
                time.sleep(delay)
                continue
            raise


def unique_limits(desired: int) -> list[int]:
    vals = [desired, min(desired, 100), min(desired, 50), min(desired, 25), min(desired, 10), min(desired, 5), 1]
    out = []
    for x in vals:
        x = max(1, int(x))
        if x not in out:
            out.append(x)
    return out


def fetch_resilient(token: str, desired: int) -> tuple[list[dict], str | None, int | None, str, int]:
    """Return records, next token, total, field status, actual limit.

    TED occasionally returns HTTP 200 + notices=[] + timedOut=true for a complex 250-record page.
    We retry the exact same cursor at progressively smaller limits. This never advances the cursor
    until records have actually been materialized.
    """
    for limit in unique_limits(desired):
        for empty_attempt in range(3):
            obj = request(token, limit, FULL_FIELDS)
            batch = obj.get("notices") or []
            timed_out = bool(obj.get("timedOut"))
            if batch:
                print("TED_BATCH", "wanted", desired, "actual_limit", limit, "records", len(batch), "timedOut", timed_out, flush=True)
                time.sleep(0.9)
                return batch, obj.get("iterationNextToken"), obj.get("totalNoticeCount"), "FULL", limit
            if timed_out:
                print("TED_TIMEOUT_DOWNSHIFT", "limit", limit, "attempt", empty_attempt + 1, flush=True)
                time.sleep(1.5 + empty_attempt)
                break
            delay = 2.0 * (empty_attempt + 1)
            print("TED_EMPTY_RETRY", "limit", limit, "attempt", empty_attempt + 1, "sleep", delay, flush=True)
            time.sleep(delay)

    # Last-resort identity-preserving crossing for a single pathological notice. The record is
    # explicitly flagged for later enrichment instead of silently creating a census hole.
    for attempt in range(5):
        obj = request(token, 1, MINIMAL_FIELDS)
        batch = obj.get("notices") or []
        if batch:
            for notice in batch:
                if isinstance(notice, dict):
                    notice["_ptie_field_status"] = "MINIMAL_DUE_TED_TIMEOUT"
            print("TED_MINIMAL_FALLBACK", "records", len(batch), flush=True)
            time.sleep(1.0)
            return batch, obj.get("iterationNextToken"), obj.get("totalNoticeCount"), "MINIMAL_DUE_TED_TIMEOUT", 1
        delay = min(30.0, 3.0 * (2 ** attempt))
        print("TED_MINIMAL_EMPTY_RETRY", attempt + 1, "sleep", delay, flush=True)
        time.sleep(delay)
    raise RuntimeError("TED cursor could not be materialized even with limit=1 minimal fields")


def upload(tag: str, *paths: pathlib.Path):
    for p in paths:
        subprocess.run(["gh", "release", "upload", tag, str(p), "--clobber"], check=True)


def run(checkpoint_path: pathlib.Path, out_dir: pathlib.Path, release_tag: str, max_records: int):
    cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if cp.get("query_fingerprint") != QUERY_FP:
        raise RuntimeError("Checkpoint query fingerprint mismatch")
    if cp.get("status") == "CENSUS_COMPLETE":
        result = {"status": "ALREADY_COMPLETE", "checkpoint": cp}
        p = out_dir / "ted-result-continuation-summary.json"
        out_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        upload(release_tag, p)
        return
    if cp.get("status") != "READY_TO_CONTINUE":
        raise RuntimeError(f"Unexpected checkpoint status: {cp.get('status')}")

    token = cp.get("iteration_next_token")
    if not token:
        raise RuntimeError("Incomplete checkpoint is missing ITERATION token")
    base = int(cp["cumulative_archived_records"])
    snapshot_total = int(cp.get("source_total_notice_count") or 0)
    out_dir.mkdir(parents=True, exist_ok=True)

    pre_batch, _, live_total, _, _ = fetch_resilient(token, 1)
    if not pre_batch:
        raise RuntimeError("TED preflight unexpectedly returned no record")
    total = max(snapshot_total, int(live_total or 0))
    if base >= total:
        raise RuntimeError(f"Checkpoint says incomplete but base {base} >= total {total}")
    target = min(max_records, total - base)
    print("TED_CENSUS_START", "base", base, "total", total, "target", target, flush=True)

    committed = 0
    block_seen: set[str] = set()
    degraded_count = 0
    request_count = 0

    while committed < target:
        shard_target = min(5000, target - committed)
        shard_records: list[dict] = []
        shard_start_token = token
        shard_degraded = 0

        while len(shard_records) < shard_target:
            desired = min(250, shard_target - len(shard_records))
            batch, nxt, observed_total, field_status, actual_limit = fetch_resilient(token, desired)
            request_count += 1
            if observed_total:
                total = max(total, int(observed_total))
            if not batch:
                raise RuntimeError("Resilient fetch returned empty batch")
            if len(batch) > actual_limit:
                raise RuntimeError(f"TED returned {len(batch)} records > requested {actual_limit}")
            if not nxt and base + committed + len(shard_records) + len(batch) < total:
                raise RuntimeError("TED omitted next token before census completion")

            for notice in batch:
                if not isinstance(notice, dict):
                    raise RuntimeError("TED returned a non-object notice")
                pn = notice.get("publication-number")
                if isinstance(pn, list):
                    pn = pn[0] if pn else None
                if not pn:
                    raise RuntimeError("TED notice missing publication-number")
                pn = str(pn)
                if pn in block_seen:
                    raise RuntimeError(f"Duplicate publication-number inside continuation block: {pn}")
                block_seen.add(pn)
                if field_status != "FULL":
                    notice["_ptie_field_status"] = field_status
                    shard_degraded += 1
                shard_records.append(notice)
            token = nxt

        record_start = base + committed + 1
        record_end = base + committed + len(shard_records)
        stem = f"ted-result-r{record_start:07d}-r{record_end:07d}"
        rawp = out_dir / f"{stem}.raw.jsonl.gz"
        normp = out_dir / f"{stem}.normalized.csv.gz"
        manp = out_dir / f"{stem}.manifest.json"
        cpp = out_dir / "ted-result-checkpoint.json"

        with gzip.open(rawp, "wt", encoding="utf-8", newline="") as f:
            for n in shard_records:
                f.write(json.dumps(n, ensure_ascii=False, separators=(",", ":")) + "\n")

        normalized_fields = FULL_FIELDS + ["source_urls_json", "census_field_status"]
        with gzip.open(normp, "wt", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=normalized_fields, extrasaction="ignore")
            w.writeheader()
            for n in shard_records:
                row = {k: cell(n.get(k)) for k in FULL_FIELDS}
                row["source_urls_json"] = cell(n.get("links") or n.get("urls") or n.get("_links"))
                row["census_field_status"] = n.get("_ptie_field_status") or "FULL"
                w.writerow(row)

        degraded_count += shard_degraded
        status = "CENSUS_COMPLETE" if record_end >= total else "READY_TO_CONTINUE"
        manifest = {
            "schema_version": "TED_AUTO_CENSUS_V3",
            "source": "TED Search API v3",
            "query": QUERY,
            "query_fingerprint": QUERY_FP,
            "window_start": "2023-08-11",
            "window_end": "2026-08-11",
            "pagination_mode": "ITERATION",
            "record_start": record_start,
            "record_end": record_end,
            "source_record_count": len(shard_records),
            "normalized_row_count": len(shard_records),
            "duplicate_count": 0,
            "minimal_fallback_records": shard_degraded,
            "source_total_notice_count": total,
            "base_archived_before_block": base,
            "cumulative_archived_after_shard": record_end,
            "raw_file": {"name": rawp.name, "bytes": rawp.stat().st_size, "sha256": sha256_file(rawp)},
            "normalized_file": {"name": normp.name, "bytes": normp.stat().st_size, "sha256": sha256_file(normp)},
            "start_token_sha256": hashlib.sha256(shard_start_token.encode()).hexdigest(),
            "next_token": token,
            "status": "COMPLETE",
        }
        manp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        checkpoint = {
            "source": "TED",
            "phase": "AWARD_NOTICE_UNIVERSE",
            "query": QUERY,
            "query_fingerprint": QUERY_FP,
            "window_start": "2023-08-11",
            "window_end": "2026-08-11",
            "pagination_mode": "ITERATION",
            "iteration_next_token": token,
            "cumulative_archived_records": record_end,
            "source_total_notice_count": total,
            "last_committed_shard": stem,
            "minimal_fallback_records_in_block": degraded_count,
            "status": status,
        }
        cpp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        upload(release_tag, rawp, normp, manp, cpp)
        committed += len(shard_records)
        print("TED_SHARD_COMMITTED", stem, "degraded", shard_degraded, "cumulative", base + committed, "/", total, flush=True)

    final = {
        "new_records_committed": committed,
        "base_records": base,
        "cumulative_records": base + committed,
        "source_total_notice_count": total,
        "minimal_fallback_records": degraded_count,
        "request_batches": request_count,
        "next_token": token,
        "query_fingerprint": QUERY_FP,
        "status": "CENSUS_COMPLETE" if base + committed >= total else "READY_TO_CONTINUE",
        "release": release_tag,
    }
    sp = out_dir / "ted-result-continuation-summary.json"
    sp.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    upload(release_tag, sp)
    print(json.dumps(final, ensure_ascii=False, indent=2), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--release-tag", required=True)
    ap.add_argument("--max-records", type=int, default=50000)
    args = ap.parse_args()
    run(pathlib.Path(args.checkpoint), pathlib.Path(args.out), args.release_tag, args.max_records)


if __name__ == "__main__":
    main()
