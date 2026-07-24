#!/usr/bin/env python3
"""Harvest authentic auto-generated frames from title-matched gameplay videos.

YouTube exposes hq1/hq2/hq3 (and sometimes sd1/sd2/sd3) as automatic
frames sampled from the uploaded video itself. Unlike uploader-designed
thumbnails, these are genuine video frames and cannot contain an unrelated
custom thumbnail. This script only searches title-matched gameplay/longplay
videos, downloads those automatic frames from YouTube's public image CDN,
filters technical failures, removes duplicates, and builds a reviewable pack.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import harvest_game_screenshots as base

ROOT = Path(os.environ.get("HARVEST_ROOT", "GAMEPLAY_REFERENCE_BANK")).resolve()
TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))
SEARCH_RESULTS = int(os.environ.get("SEARCH_RESULTS", "60"))
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "24"))

REQUIRED_CONTEXT = {
    "gameplay", "longplay", "walkthrough", "playthrough", "no commentary",
    "full game", "part ", "chapter", "mission", "boss", "let's play",
    "lets play", "complete", "opening", "first look",
}
REJECT_CONTEXT = base.BAD_TITLE_TERMS | {
    "facecam", "livestream", "live stream", "stream highlights", "shorts",
    "tiktok", "meme", "mod", "randomizer", "tas", "tool assisted",
    "cutscene movie", "all cutscenes", "ending", "credits", "ost",
}


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def title_matches(game: dict[str, Any], title: str) -> bool:
    title_n = base.normalized(title)
    aliases = [base.normalized(x) for x in game.get("aliases", [])]
    rejects = [base.normalized(x) for x in game.get("reject", [])]
    if any(term and term in title_n for term in rejects):
        return False
    if any(alias and alias in title_n for alias in aliases):
        return True
    if aliases:
        tokens = [t for t in re.findall(r"[a-z0-9]+", aliases[0]) if len(t) > 2]
        return bool(tokens) and all(token in title_n for token in tokens)
    return False


def search_videos(game: dict[str, Any]) -> list[dict[str, Any]]:
    proc = run([
        "yt-dlp", "--dump-json", "--skip-download", "--flat-playlist",
        "--playlist-end", str(SEARCH_RESULTS), "--no-warnings",
        f"ytsearch{SEARCH_RESULTS}:{game['query']}",
    ])
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = str(row.get("title") or "")
        title_n = base.normalized(title)
        if not title_matches(game, title):
            continue
        if any(term in title_n for term in REJECT_CONTEXT):
            continue
        if not any(term in title_n for term in REQUIRED_CONTEXT):
            continue
        video_id = row.get("id") or row.get("url")
        if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(video_id)):
            continue
        score = 100.0
        for term, bonus in base.GOOD_TITLE_TERMS.items():
            if term in title_n:
                score += float(bonus)
        if "no commentary" in title_n:
            score += 25
        if "longplay" in title_n:
            score += 18
        if "walkthrough" in title_n or "playthrough" in title_n:
            score += 12
        query_platforms = [p for p in ("ps2", "ps3", "ps4", "wii", "3ds", "nintendo ds", "ps vita", "gamecube") if p in base.normalized(game["query"])]
        if query_platforms and any(p in title_n for p in query_platforms):
            score += 12
        duration = row.get("duration")
        if isinstance(duration, (int, float)):
            if duration >= 300:
                score += 8
            if duration < 90:
                score -= 30
        channel = base.normalized(str(row.get("channel") or row.get("uploader") or ""))
        if any(key in channel for key in ("longplayarchive", "world of longplays", "nintendocomplete", "gameplayarchive", "prosafia", "shirrako")):
            score += 14
        row["score"] = score
        row["webpage_url"] = f"https://www.youtube.com/watch?v={video_id}"
        rows.append(row)
    rows.sort(key=lambda x: x.get("score", 0), reverse=True)
    # Dedupe video IDs while retaining ranking.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        video_id = str(row.get("id") or row.get("url"))
        if video_id in seen:
            continue
        seen.add(video_id)
        unique.append(row)
        if len(unique) >= MAX_VIDEOS:
            break
    return unique


def get_image(session: requests.Session, video_id: str, position: int) -> tuple[Image.Image, str] | None:
    # sdN is usually 640x480. hqN is the reliable 480x360 fallback.
    variants = [f"sd{position}.jpg", f"hq{position}.jpg"]
    for variant in variants:
        url = f"https://i.ytimg.com/vi/{video_id}/{variant}"
        try:
            response = session.get(url, timeout=25)
        except requests.RequestException:
            continue
        if response.status_code != 200 or len(response.content) < 4_000:
            continue
        try:
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
            image.load()
        except Exception:
            continue
        if image.width < 320 or image.height < 180:
            continue
        # Reject common blank/placeholder responses.
        arr = np.asarray(image)
        if float(arr.std()) < 8.0:
            continue
        return image, url
    return None


def crop_letterbox(image: Image.Image) -> Image.Image:
    arr = np.asarray(image)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    row_means = gray.mean(axis=1)
    top = 0
    while top < len(row_means) // 4 and row_means[top] < 12:
        top += 1
    bottom = len(row_means)
    while bottom > len(row_means) * 3 // 4 and row_means[bottom - 1] < 12:
        bottom -= 1
    if bottom - top >= image.height * 0.65 and (top > 3 or bottom < image.height - 3):
        return image.crop((0, top, image.width, bottom))
    return image


def candidate_quality(path: Path) -> tuple[float, imagehash.ImageHash, np.ndarray] | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 10 or brightness > 247 or sharpness < 8:
        return None
    hsv = cv2.cvtColor(cv2.resize(bgr, (192, 108)), cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    phash = imagehash.phash(Image.open(path).convert("RGB"), hash_size=12)
    quality = math.log1p(sharpness) - 0.003 * abs(brightness - 128)
    return quality, phash, hist


def select_candidates(paths: list[Path], target: int) -> list[Path]:
    rows = []
    for path in paths:
        result = candidate_quality(path)
        if result:
            quality, phash, hist = result
            rows.append({"path": path, "quality": quality, "phash": phash, "hist": hist})
    rows.sort(key=lambda x: x["quality"], reverse=True)
    unique = []
    for row in rows:
        duplicate = False
        for kept in unique:
            if (row["phash"] - kept["phash"]) <= 8 and float(np.dot(row["hist"], kept["hist"])) > 0.93:
                duplicate = True
                break
        if not duplicate:
            unique.append(row)
    if len(unique) <= target:
        return [x["path"] for x in unique]

    qualities = np.array([x["quality"] for x in unique], dtype=np.float32)
    q_min, q_max = float(qualities.min()), float(qualities.max())
    for row in unique:
        row["qnorm"] = (row["quality"] - q_min) / max(q_max - q_min, 1e-8)

    selected = [max(unique, key=lambda x: x["qnorm"])]
    remaining = [x for x in unique if x is not selected[0]]
    while remaining and len(selected) < target:
        def score(candidate):
            distances = []
            for picked in selected:
                hdist = (candidate["phash"] - picked["phash"]) / float(len(candidate["phash"].hash.flatten()))
                hist_dist = max(0.0, 1.0 - float(np.dot(candidate["hist"], picked["hist"])))
                distances.append(0.55 * hist_dist + 0.45 * hdist)
            return 0.82 * min(distances) + 0.18 * candidate["qnorm"]
        best = max(remaining, key=score)
        selected.append(best)
        remaining.remove(best)
    return [x["path"] for x in selected]


def font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def make_contact_sheet(game: str, rows: list[dict[str, Any]], output: Path) -> None:
    cols = 5
    cell_w, image_h, label_h = 320, 210, 42
    count_rows = math.ceil(len(rows) / cols)
    header_h = 62
    canvas = Image.new("RGB", (cols * cell_w, header_h + count_rows * (image_h + label_h)), "#101010")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 15), f"{game} — {len(rows)} YouTube auto-generated gameplay frames", fill="white", font=font(24))
    for idx, row in enumerate(rows):
        r, c = divmod(idx, cols)
        x, y = c * cell_w, header_h + r * (image_h + label_h)
        image = Image.open(row["absolute_path"]).convert("RGB")
        image.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, image_h), "#000000")
        frame.paste(image, ((cell_w - image.width) // 2, (image_h - image.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + image_h, x + cell_w, y + image_h + label_h), fill="#1d1d1d")
        label = f"{idx + 1:02d}  video {row['video_rank']:02d} · {row['position_percent']}%"
        draw.text((x + 8, y + image_h + 10), label, fill="white", font=font(15))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=92)


def main() -> int:
    raw_index = os.environ.get("GAME_INDEX", "").strip()
    if not raw_index:
        raise SystemExit("GAME_INDEX is required")
    index = int(raw_index)
    if not 1 <= index <= len(base.GAMES):
        raise SystemExit(f"GAME_INDEX must be 1..{len(base.GAMES)}")
    game = base.GAMES[index - 1]
    slug = base.slugify(game["name"])
    if ROOT.exists():
        shutil.rmtree(ROOT)
    game_dir = ROOT / f"{index:02d}_{slug}"
    images_dir = game_dir / "images"
    candidate_dir = game_dir / "candidates"
    images_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    videos = search_videos(game)
    (game_dir / "source_videos.json").write_text(json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8")
    if not videos:
        raise SystemExit(f"No title-matched gameplay videos found for {game['name']}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Referer": "https://www.youtube.com/",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    })

    metadata: dict[str, dict[str, Any]] = {}
    candidate_paths: list[Path] = []
    for video_rank, video in enumerate(videos, 1):
        video_id = str(video.get("id") or video.get("url"))
        for position in (1, 2, 3):
            fetched = get_image(session, video_id, position)
            if not fetched:
                continue
            image, source_url = fetched
            image = crop_letterbox(image)
            path = candidate_dir / f"v{video_rank:02d}_{video_id}_p{position}.jpg"
            image.save(path, quality=95)
            duration = video.get("duration")
            position_percent = position * 25
            estimated_timestamp = round(float(duration) * position_percent / 100.0, 2) if isinstance(duration, (int, float)) else None
            metadata[str(path)] = {
                "video_rank": video_rank,
                "video_id": video_id,
                "video_url": video.get("webpage_url"),
                "video_title": video.get("title"),
                "video_channel": video.get("channel") or video.get("uploader"),
                "video_duration_seconds": duration,
                "position_percent": position_percent,
                "estimated_timestamp_seconds": estimated_timestamp,
                "source_image_url": source_url,
            }
            candidate_paths.append(path)
        if len(candidate_paths) >= TARGET * 3:
            break

    selected_paths = select_candidates(candidate_paths, TARGET)
    rows: list[dict[str, Any]] = []
    for rank, source_path in enumerate(selected_paths, 1):
        meta = metadata[str(source_path)]
        destination = images_dir / f"{slug}_{rank:03d}_auto_frame.jpg"
        shutil.copy2(source_path, destination)
        with Image.open(destination) as image:
            width, height = image.size
        row = {
            "game": game["name"],
            "filename": destination.name,
            "relative_path": str(destination.relative_to(ROOT)),
            "absolute_path": str(destination),
            "width": width,
            "height": height,
            "source_type": "youtube_auto_generated_video_frame",
            "auto_generated_frame": True,
            "custom_uploader_thumbnail": False,
            "validation_status": "TITLE_MATCHED_GAMEPLAY_VIDEO_AND_TECHNICALLY_FILTERED",
            "manual_review_required": True,
            **meta,
        }
        rows.append(row)

    contact_sheet = game_dir / f"contact_sheet_{slug}.jpg"
    make_contact_sheet(game["name"], rows, contact_sheet)
    for row in rows:
        row.pop("absolute_path", None)
    manifest = {
        "game": game["name"],
        "query": game["query"],
        "target_count": TARGET,
        "selected_count": len(rows),
        "candidate_count": len(candidate_paths),
        "videos_considered": len(videos),
        "elapsed_seconds": round(time.time() - started, 2),
        "method": {
            "general_image_search_used": False,
            "video_stream_downloaded": False,
            "source": "YouTube public auto-generated hq1/hq2/hq3 or sd1/sd2/sd3 frames",
            "custom_thumbnails_used": False,
            "title_matching": True,
            "rejected_contexts": sorted(REJECT_CONTEXT),
            "deduplication": "perceptual hash plus HSV histogram",
            "manual_review_required": True,
        },
        "images": rows,
    }
    (game_dir / f"manifest_{slug}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "master_manifest.json").write_text(json.dumps({
        "requested_games": 1,
        "completed_games": 1 if rows else 0,
        "target_per_game": TARGET,
        "selected_images": len(rows),
        "game": game["name"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "README.md").write_text(
        f"# {game['name']} gameplay reference frames\n\n"
        f"Selected: {len(rows)} / {TARGET}. Frames are YouTube's automatic video stills, not uploader-designed thumbnails. "
        "Review the included contact sheet before production use.\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if len(rows) < TARGET:
        print(f"WARNING: selected {len(rows)} of {TARGET}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
