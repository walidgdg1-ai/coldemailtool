#!/usr/bin/env python3
"""Harvest 15 additional high-resolution gameplay frames for one game.

The script searches title-matched gameplay uploads, resolves a real 720p/1080p
video stream (yt-dlp first, Piped/Invidious fallbacks), samples native video
frames, rejects weak/menu-like shots, removes perceptual duplicates and keeps a
visually diverse set. It never uses custom thumbnails or unrestricted image
search results.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote

import cv2
import imagehash
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import harvest_game_screenshots as base

ROOT = Path(os.environ.get("HARVEST_ROOT", "HD_EXTRA_REFERENCE_BANK")).resolve()
TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))
SEARCH_RESULTS = int(os.environ.get("SEARCH_RESULTS", "35"))
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "4"))
SEGMENT_SECONDS = int(os.environ.get("SEGMENT_SECONDS", "420"))
MIN_WIDTH = int(os.environ.get("MIN_WIDTH", "960"))
MIN_HEIGHT = int(os.environ.get("MIN_HEIGHT", "540"))

BAD_TERMS = {
    "review", "reaction", "retrospective", "analysis", "essay", "trailer",
    "teaser", "commercial", "ost", "soundtrack", "music", "comparison",
    "speedrun", "world record", "ending", "all cutscenes", "movie",
    "story explained", "tier list", "unboxing", "podcast", "shorts",
    "livestream", "stream highlights", "mod showcase", "benchmark",
}
GOOD_TERMS = {
    "gameplay": 30, "no commentary": 24, "longplay": 18,
    "walkthrough": 14, "playthrough": 14, "full game": 8,
    "1080p": 16, "1440p": 18, "4k": 20, "60fps": 8, "hd": 8,
}

PIPED_APIS = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.reallyaweso.me",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.drgns.space",
    "https://pipedapi.r4fo.com",
]
INVIDIOUS_APIS = [
    "https://yewtu.be",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.jing.rocks",
]


def run(cmd: list[str], timeout: int = 600, check: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout, check=check)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", text).strip()


def score_search_row(game: dict[str, Any], row: dict[str, Any], rank: int) -> float | None:
    title = norm(str(row.get("title") or ""))
    if not title:
        return None
    rejects = [norm(x) for x in game.get("reject", [])]
    if any(term in title for term in rejects):
        return None
    aliases = [norm(x) for x in game.get("aliases", [])]
    matched = any(alias in title for alias in aliases)
    if not matched and aliases:
        tokens = [t for t in re.findall(r"[a-z0-9]+", aliases[0]) if len(t) > 2]
        matched = bool(tokens) and all(t in title for t in tokens)
    if not matched:
        return None
    score = 100.0 - rank * 1.2
    for term, bonus in GOOD_TERMS.items():
        if term in title:
            score += bonus
    for term in BAD_TERMS:
        if term in title:
            score -= 70
    duration = row.get("duration")
    if isinstance(duration, (int, float)):
        if 600 <= duration <= 10800:
            score += 18
        elif duration < 240:
            score -= 60
        elif duration > 21600:
            score -= 15
    channel = norm(str(row.get("channel") or row.get("uploader") or ""))
    if any(name in channel for name in ["nintendocomplete", "world of longplays", "longplayarchive", "gameplayarchive", "shirrako", "mkiceandfire"]):
        score += 12
    return score


def search_videos(game: dict[str, Any]) -> list[dict[str, Any]]:
    queries = [
        f"{game['name']} 1080p gameplay no commentary",
        f"{game['name']} HD gameplay longplay",
        game["query"],
    ]
    gathered: dict[str, dict[str, Any]] = {}
    for query in queries:
        target = f"ytsearch{SEARCH_RESULTS}:{query}"
        proc = run([
            "yt-dlp", "--dump-json", "--skip-download", "--flat-playlist",
            "--playlist-end", str(SEARCH_RESULTS), "--no-warnings", target,
        ], timeout=300)
        for rank, line in enumerate(proc.stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            video_id = str(row.get("id") or "")
            if not video_id:
                continue
            score = score_search_row(game, row, rank)
            if score is None:
                continue
            row["search_score"] = score
            row["query_used"] = query
            row["webpage_url"] = f"https://www.youtube.com/watch?v={video_id}"
            old = gathered.get(video_id)
            if old is None or score > old.get("search_score", -999):
                gathered[video_id] = row
    rows = sorted(gathered.values(), key=lambda r: r.get("search_score", 0), reverse=True)
    if not rows:
        raise RuntimeError(f"No title-matched gameplay videos found for {game['name']}")
    return rows[:12]


def probe(path: Path) -> dict[str, Any] | None:
    proc = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,avg_frame_rate",
        "-show_entries", "format=duration", "-of", "json", str(path),
    ], timeout=90)
    try:
        data = json.loads(proc.stdout)
        stream = data.get("streams", [{}])[0]
        duration = stream.get("duration") or data.get("format", {}).get("duration")
        return {"width": int(stream.get("width") or 0), "height": int(stream.get("height") or 0),
                "duration": float(duration or 0), "avg_frame_rate": stream.get("avg_frame_rate")}
    except Exception:
        return None


def segment_window(row: dict[str, Any], ordinal: int) -> tuple[float, float]:
    duration = row.get("duration")
    duration = float(duration) if isinstance(duration, (int, float)) else 0.0
    if duration <= SEGMENT_SECONDS + 60:
        return 30.0, max(90.0, duration - 20.0) if duration else float(SEGMENT_SECONDS)
    fractions = [0.08, 0.28, 0.52, 0.70]
    start = min(max(45.0, duration * fractions[ordinal % len(fractions)]), duration - SEGMENT_SECONDS - 20)
    return start, min(float(SEGMENT_SECONDS), duration - start - 10)


def direct_ytdlp(row: dict[str, Any], out: Path, ordinal: int) -> bool:
    start, length = segment_window(row, ordinal)
    template = str(out.with_suffix(".%(ext)s"))
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--retries", "3",
        "--fragment-retries", "3", "--socket-timeout", "30",
        "--extractor-args", "youtube:player_client=tv,web_safari,android_vr",
        "--impersonate", "chrome",
        "--format", "bestvideo[height>=720][height<=1080]/best[height>=720][height<=1080]/bestvideo[height<=1080]/best[height<=1080]",
        "--download-sections", f"*{start:.1f}-{start + length:.1f}",
        "--force-keyframes-at-cuts", "--output", template, row["webpage_url"],
    ]
    proc = run(cmd, timeout=900)
    candidates = sorted(out.parent.glob(out.stem + ".*"), key=lambda p: p.stat().st_size, reverse=True)
    for candidate in candidates:
        if candidate.suffix.lower() in {".part", ".ytdl", ".json"}:
            continue
        info = probe(candidate)
        if info and info["width"] >= MIN_WIDTH and info["height"] >= MIN_HEIGHT and candidate.stat().st_size > 1_000_000:
            candidate.rename(out)
            return True
    print("DIRECT_YTDLP_FAILED", proc.stdout[-1500:], flush=True)
    return False


def stream_score(stream: dict[str, Any]) -> tuple[int, int, int]:
    quality = str(stream.get("quality") or stream.get("qualityLabel") or "")
    m = re.search(r"(\d{3,4})", quality)
    height = int(m.group(1)) if m else int(stream.get("height") or 0)
    mime = str(stream.get("format") or stream.get("type") or stream.get("mimeType") or "")
    mp4 = 1 if "mp4" in mime else 0
    progressive = 1 if stream.get("videoOnly") is False or stream.get("audioQuality") else 0
    return (min(height, 1080), mp4, progressive)


def resolve_piped(video_id: str) -> tuple[str, str] | None:
    headers = {"User-Agent": "Mozilla/5.0"}
    for api in PIPED_APIS:
        try:
            r = requests.get(f"{api}/streams/{video_id}", timeout=18, headers=headers)
            if r.status_code != 200:
                continue
            data = r.json()
            streams = [s for s in data.get("videoStreams", []) if s.get("url")]
            streams.sort(key=stream_score, reverse=True)
            for stream in streams:
                if stream_score(stream)[0] >= 720:
                    return str(stream["url"]), f"piped:{api}"
            hls = data.get("hls")
            if hls:
                return str(hls), f"piped_hls:{api}"
        except Exception as exc:
            print(f"PIPED_FAIL {api}: {exc}")
    return None


def resolve_invidious(video_id: str) -> tuple[str, str] | None:
    headers = {"User-Agent": "Mozilla/5.0"}
    for api in INVIDIOUS_APIS:
        try:
            r = requests.get(f"{api}/api/v1/videos/{video_id}", timeout=18, headers=headers)
            if r.status_code != 200:
                continue
            data = r.json()
            streams = list(data.get("adaptiveFormats", [])) + list(data.get("formatStreams", []))
            streams = [s for s in streams if s.get("url")]
            streams.sort(key=stream_score, reverse=True)
            for stream in streams:
                if stream_score(stream)[0] >= 720:
                    return str(stream["url"]), f"invidious:{api}"
            hls = data.get("hlsUrl")
            if hls:
                return str(hls), f"invidious_hls:{api}"
        except Exception as exc:
            print(f"INVIDIOUS_FAIL {api}: {exc}")
    return None


def ffmpeg_remote_segment(url: str, out: Path, row: dict[str, Any], ordinal: int) -> bool:
    start, length = segment_window(row, ordinal)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-user_agent", "Mozilla/5.0", "-ss", f"{start:.2f}", "-i", url,
        "-t", f"{length:.2f}", "-map", "0:v:0", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", str(out),
    ]
    proc = run(cmd, timeout=900)
    info = probe(out) if out.exists() else None
    if info and info["width"] >= MIN_WIDTH and info["height"] >= MIN_HEIGHT and out.stat().st_size > 1_000_000:
        return True
    print("REMOTE_SEGMENT_FAILED", proc.stdout[-1500:], flush=True)
    out.unlink(missing_ok=True)
    return False


def obtain_segment(row: dict[str, Any], out: Path, ordinal: int) -> tuple[bool, str]:
    if direct_ytdlp(row, out, ordinal):
        return True, "yt-dlp native stream"
    video_id = str(row.get("id") or "")
    for resolver in (resolve_piped, resolve_invidious):
        resolved = resolver(video_id)
        if resolved and ffmpeg_remote_segment(resolved[0], out, row, ordinal):
            return True, resolved[1]
    return False, "unresolved"


def extract_candidates(video: Path, output: Path, source_idx: int) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    info = probe(video) or {}
    duration = float(info.get("duration") or 0)
    interval = max(3.5, duration / 95.0) if duration else 4.0
    pattern = output / f"s{source_idx:02d}_%04d.jpg"
    proc = run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", f"fps=1/{interval:.3f}", "-q:v", "2", str(pattern),
    ], timeout=600)
    return sorted(output.glob(f"s{source_idx:02d}_*.jpg"))


def frame_metrics(path: Path) -> dict[str, Any] | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    if w < MIN_WIDTH or h < MIN_HEIGHT:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 12 or brightness > 245 or contrast < 18 or sharpness < 22:
        return None
    # Reject mostly black/white frames and common loading/fade transitions.
    black_ratio = float((gray < 12).mean())
    white_ratio = float((gray > 245).mean())
    if black_ratio > 0.58 or white_ratio > 0.58:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = float(hsv[:, :, 1].mean())
    colorfulness = float(np.std(bgr[:, :, 0] - bgr[:, :, 1]) + np.std(bgr[:, :, 2] - bgr[:, :, 1]))
    edges = cv2.Canny(gray, 70, 150)
    edge_density = float((edges > 0).mean())
    # Menu/text-heavy frames tend to have excessive uniform micro-edges in strips.
    strip = np.concatenate([edges[: h // 5].ravel(), edges[-h // 5 :].ravel()])
    strip_edges = float((strip > 0).mean())
    menu_penalty = max(0.0, strip_edges - edge_density * 1.6)
    # Reward subject/action around the central 60%, useful for third-person framing.
    center = edges[h // 5 : 4 * h // 5, w // 5 : 4 * w // 5]
    center_activity = float((center > 0).mean())
    entropy_hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).flatten()
    p = entropy_hist / max(float(entropy_hist.sum()), 1.0)
    entropy = float(-(p[p > 0] * np.log2(p[p > 0])).sum())
    quality = (
        1.7 * math.log1p(sharpness) + 0.025 * contrast + 0.008 * saturation
        + 0.012 * colorfulness + 2.2 * entropy + 8.0 * center_activity
        - 18.0 * menu_penalty - 2.0 * abs(brightness - 125) / 125
    )
    small = cv2.resize(hsv, (192, 108))
    hist = cv2.calcHist([small], [0, 1], None, [16, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    phash = imagehash.phash(Image.open(path).convert("RGB"), hash_size=12)
    return {"path": path, "width": w, "height": h, "quality": quality,
            "phash": phash, "hist": hist, "brightness": brightness,
            "sharpness": sharpness, "center_activity": center_activity,
            "menu_penalty": menu_penalty}


def select_diverse(paths: list[Path], target: int) -> list[dict[str, Any]]:
    rows = [r for p in paths if (r := frame_metrics(p))]
    rows.sort(key=lambda r: r["quality"], reverse=True)
    unique: list[dict[str, Any]] = []
    for row in rows:
        duplicate = False
        for kept in unique:
            hash_dist = row["phash"] - kept["phash"]
            hist_sim = float(np.dot(row["hist"], kept["hist"]))
            if hash_dist <= 10 and hist_sim > 0.90:
                duplicate = True
                break
        if not duplicate:
            unique.append(row)
    if len(unique) <= target:
        return unique
    qualities = np.array([r["quality"] for r in unique], dtype=np.float32)
    lo, hi = float(qualities.min()), float(qualities.max())
    for row in unique:
        row["qnorm"] = (row["quality"] - lo) / max(hi - lo, 1e-8)
    selected = [max(unique, key=lambda r: r["qnorm"])]
    remaining = [r for r in unique if r is not selected[0]]
    while remaining and len(selected) < target:
        def score(candidate: dict[str, Any]) -> float:
            distances = []
            for picked in selected:
                hash_dist = (candidate["phash"] - picked["phash"]) / 144.0
                hist_dist = max(0.0, 1.0 - float(np.dot(candidate["hist"], picked["hist"])))
                distances.append(0.55 * hist_dist + 0.45 * hash_dist)
            return 0.76 * min(distances) + 0.24 * candidate["qnorm"]
        chosen = max(remaining, key=score)
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


def font(size: int):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def contact_sheet(game: str, rows: list[dict[str, Any]], output: Path) -> None:
    cols, cell_w, image_h, label_h, header = 5, 360, 220, 42, 70
    row_count = math.ceil(len(rows) / cols)
    canvas = Image.new("RGB", (cols * cell_w, header + row_count * (image_h + label_h)), "#0d0d0d")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 18), f"{game} — {len(rows)} additional HD gameplay frames", fill="white", font=font(25))
    for idx, row in enumerate(rows):
        rr, cc = divmod(idx, cols)
        x, y = cc * cell_w, header + rr * (image_h + label_h)
        image = Image.open(row["output_path"]).convert("RGB")
        image.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, image_h), "black")
        frame.paste(image, ((cell_w - image.width) // 2, (image_h - image.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + image_h, x + cell_w, y + image_h + label_h), fill="#1b1b1b")
        draw.text((x + 8, y + image_h + 10), f"{idx + 16:02d} · {row['width']}×{row['height']}", fill="white", font=font(14))
    canvas.save(output, quality=92)


def main() -> int:
    index = int(os.environ.get("GAME_INDEX", "1"))
    if not 1 <= index <= len(base.GAMES):
        raise SystemExit("GAME_INDEX must be 1..31")
    game = base.GAMES[index - 1]
    slug = base.slugify(game["name"])
    if ROOT.exists():
        shutil.rmtree(ROOT)
    game_dir = ROOT / f"{index:02d}_{slug}"
    image_dir = game_dir / "images_hd_extra"
    candidate_dir = game_dir / "candidates"
    video_dir = game_dir / "source_segments"
    for d in (image_dir, candidate_dir, video_dir):
        d.mkdir(parents=True, exist_ok=True)
    started = time.time()
    videos = search_videos(game)
    sources: list[dict[str, Any]] = []
    candidates: list[Path] = []
    for ordinal, row in enumerate(videos[:MAX_VIDEOS]):
        segment = video_dir / f"source_{ordinal + 1:02d}.mp4"
        ok, method = obtain_segment(row, segment, ordinal)
        source_record = {
            "video_id": row.get("id"), "title": row.get("title"),
            "channel": row.get("channel") or row.get("uploader"),
            "url": row.get("webpage_url"), "query": row.get("query_used"),
            "search_score": row.get("search_score"), "resolution_method": method,
            "downloaded": ok,
        }
        if ok:
            info = probe(segment) or {}
            source_record["segment_info"] = info
            extracted = extract_candidates(segment, candidate_dir, ordinal + 1)
            source_record["candidate_frames"] = len(extracted)
            candidates.extend(extracted)
        sources.append(source_record)
        if len(candidates) >= 150:
            break
    selected = select_diverse(candidates, TARGET)
    if len(selected) < TARGET:
        raise RuntimeError(f"Only {len(selected)} acceptable HD frames selected for {game['name']} from {len(candidates)} candidates")
    image_rows: list[dict[str, Any]] = []
    for number, row in enumerate(selected[:TARGET], 16):
        filename = f"{slug}_{number:03d}_hd_gameplay.jpg"
        destination = image_dir / filename
        shutil.copy2(row["path"], destination)
        image_rows.append({
            "game": game["name"], "filename": filename,
            "relative_path": f"{index:02d}_{slug}/images_hd_extra/{filename}",
            "width": row["width"], "height": row["height"],
            "quality_score": round(float(row["quality"]), 4),
            "brightness": round(float(row["brightness"]), 3),
            "sharpness": round(float(row["sharpness"]), 3),
            "center_activity": round(float(row["center_activity"]), 5),
            "menu_penalty": round(float(row["menu_penalty"]), 5),
            "output_path": str(destination),
        })
    contact_sheet(game["name"], image_rows, game_dir / f"contact_sheet_{slug}_hd_extra.jpg")
    manifest = {
        "game": game["name"], "ordinal": index, "target_count": TARGET,
        "selected_count": len(image_rows), "candidate_count": len(candidates),
        "minimum_resolution": f"{MIN_WIDTH}x{MIN_HEIGHT}",
        "method": {
            "unrestricted_image_search_used": False,
            "custom_thumbnails_used": False,
            "source": "Native frames extracted from title-matched public gameplay video streams",
            "preferred_resolution": "720p to 1080p",
            "selection": "technical quality, central gameplay activity, menu penalty, perceptual deduplication and visual diversity",
            "manual_review_required": True,
        },
        "sources": sources, "elapsed_seconds": round(time.time() - started, 2),
        "images": [{k: v for k, v in row.items() if k != "output_path"} for row in image_rows],
    }
    (game_dir / f"manifest_{slug}_hd_extra.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(candidate_dir, ignore_errors=True)
    shutil.rmtree(video_dir, ignore_errors=True)
    print(json.dumps({"game": game["name"], "selected": len(image_rows), "sources": sources}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
