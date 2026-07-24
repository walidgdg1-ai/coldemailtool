#!/usr/bin/env python3
"""Run the HD harvester with fast stream-resolution order and bounded fallbacks."""
from __future__ import annotations

from pathlib import Path

import harvest_hd_extra_frames as h


def fast_direct(row, out: Path, ordinal: int) -> bool:
    start, length = h.segment_window(row, ordinal)
    template = str(out.with_suffix(".%(ext)s"))
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--retries", "1",
        "--fragment-retries", "1", "--socket-timeout", "15",
        "--extractor-args", "youtube:player_client=tv,web_safari,android_vr",
        "--impersonate", "chrome",
        "--format", "bestvideo[height>=720][height<=1080]/best[height>=720][height<=1080]/bestvideo[height<=1080]/best[height<=1080]",
        "--download-sections", f"*{start:.1f}-{start + length:.1f}",
        "--force-keyframes-at-cuts", "--output", template, row["webpage_url"],
    ]
    proc = h.run(cmd, timeout=210)
    candidates = sorted(out.parent.glob(out.stem + ".*"), key=lambda p: p.stat().st_size, reverse=True)
    for candidate in candidates:
        if candidate.suffix.lower() in {".part", ".ytdl", ".json"}:
            continue
        info = h.probe(candidate)
        if info and info["width"] >= h.MIN_WIDTH and info["height"] >= h.MIN_HEIGHT and candidate.stat().st_size > 1_000_000:
            if candidate != out:
                candidate.rename(out)
            return True
    print("FAST_DIRECT_FAILED", proc.stdout[-1200:], flush=True)
    return False


def fast_obtain(row, out: Path, ordinal: int):
    video_id = str(row.get("id") or "")
    for resolver in (h.resolve_piped, h.resolve_invidious):
        resolved = resolver(video_id)
        if resolved and h.ffmpeg_remote_segment(resolved[0], out, row, ordinal):
            return True, resolved[1]
    if fast_direct(row, out, ordinal):
        return True, "yt-dlp bounded fallback"
    return False, "unresolved"


h.obtain_segment = fast_obtain
h.MAX_VIDEOS = min(h.MAX_VIDEOS, 3)

if __name__ == "__main__":
    raise SystemExit(h.main())
