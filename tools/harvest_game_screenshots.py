#!/usr/bin/env python3
"""Build a safe, gameplay-video-derived screenshot reference bank.

The pipeline deliberately avoids general image-search scraping. It searches for
public gameplay videos, downloads one bounded section per game, samples frames,
filters unusable frames, removes near-duplicates, selects a diverse set, creates
contact sheets/manifests, and packages everything as a ZIP artifact.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(os.environ.get("HARVEST_ROOT", "GAMEPLAY_REFERENCE_BANK")).resolve()
TARGET_PER_GAME = int(os.environ.get("TARGET_PER_GAME", "15"))
CANDIDATE_INTERVAL_SECONDS = int(os.environ.get("CANDIDATE_INTERVAL_SECONDS", "5"))
MAX_SEGMENT_SECONDS = int(os.environ.get("MAX_SEGMENT_SECONDS", "1500"))
SEARCH_RESULTS = int(os.environ.get("SEARCH_RESULTS", "20"))

BAD_TITLE_TERMS = {
    "review", "reaction", "retrospective", "analysis", "essay", "trailer",
    "teaser", "commercial", "advert", "ost", "soundtrack", "music",
    "comparison", "versus", "vs.", "mod showcase", "speedrun", "world record",
    "ending only", "all cutscenes", "movie", "story explained", "tier list",
    "unboxing", "collection", "ranking", "top 10", "top ten", "podcast",
}

GOOD_TITLE_TERMS = {
    "gameplay": 18,
    "longplay": 20,
    "walkthrough": 12,
    "playthrough": 12,
    "no commentary": 14,
    "full game": 8,
    "ps2": 4,
    "ps3": 4,
    "ps4": 4,
    "wii": 4,
    "3ds": 4,
    "nintendo ds": 4,
}

GAMES: list[dict[str, Any]] = [
    {"name": "Puppeteer", "query": "Puppeteer PS3 gameplay no commentary", "aliases": ["puppeteer"]},
    {"name": "Gravity Rush", "query": "Gravity Rush PS Vita gameplay no commentary", "aliases": ["gravity rush", "gravity daze"], "reject": ["gravity rush 2"]},
    {"name": "Gravity Rush 2", "query": "Gravity Rush 2 PS4 gameplay no commentary", "aliases": ["gravity rush 2", "gravity daze 2"]},
    {"name": "Solatorobo Red the Hunter", "query": "Solatorobo Red the Hunter Nintendo DS gameplay", "aliases": ["solatorobo", "red the hunter"]},
    {"name": "Kirby's Epic Yarn", "query": "Kirby's Epic Yarn Wii gameplay no commentary", "aliases": ["kirby's epic yarn", "kirbys epic yarn"]},
    {"name": "LittleBigPlanet 2", "query": "LittleBigPlanet 2 PS3 gameplay no commentary", "aliases": ["littlebigplanet 2", "little big planet 2", "lbp2"]},
    {"name": "Okami", "query": "Okami PS2 gameplay no commentary", "aliases": ["okami", "ōkami"]},
    {"name": "Ghost Trick Phantom Detective", "query": "Ghost Trick Phantom Detective Nintendo DS gameplay", "aliases": ["ghost trick", "phantom detective"]},
    {"name": "Fantasy Life", "query": "Fantasy Life Nintendo 3DS gameplay no commentary", "aliases": ["fantasy life"], "reject": ["fantasy life i"]},
    {"name": "Yo-kai Watch 2", "query": "Yo-kai Watch 2 Nintendo 3DS gameplay", "aliases": ["yo-kai watch 2", "yokai watch 2", "youkai watch 2"]},
    {"name": "Katamari Damacy", "query": "Katamari Damacy PS2 gameplay no commentary", "aliases": ["katamari damacy"], "reject": ["we love katamari"]},
    {"name": "We Love Katamari", "query": "We Love Katamari PS2 gameplay no commentary", "aliases": ["we love katamari"]},
    {"name": "The World Ends with You", "query": "The World Ends with You Nintendo DS gameplay", "aliases": ["the world ends with you", "twewy"], "reject": ["neo"]},
    {"name": "Muramasa The Demon Blade", "query": "Muramasa The Demon Blade Wii gameplay", "aliases": ["muramasa", "the demon blade"]},
    {"name": "Viewtiful Joe", "query": "Viewtiful Joe PS2 GameCube gameplay no commentary", "aliases": ["viewtiful joe"]},
    {"name": "Sly 2 Band of Thieves", "query": "Sly 2 Band of Thieves PS2 gameplay no commentary", "aliases": ["sly 2", "band of thieves"]},
    {"name": "Dark Chronicle Dark Cloud 2", "query": "Dark Chronicle Dark Cloud 2 PS2 gameplay", "aliases": ["dark chronicle", "dark cloud 2"]},
    {"name": "Rogue Galaxy", "query": "Rogue Galaxy PS2 gameplay no commentary", "aliases": ["rogue galaxy"]},
    {"name": "Klonoa 2 Lunatea's Veil", "query": "Klonoa 2 Lunatea's Veil PS2 gameplay", "aliases": ["klonoa 2", "lunatea's veil", "lunateas veil"]},
    {"name": "Auto Modellista", "query": "Auto Modellista PS2 gameplay no commentary", "aliases": ["auto modellista"]},
    {"name": "No More Heroes", "query": "No More Heroes Wii gameplay no commentary", "aliases": ["no more heroes"], "reject": ["no more heroes 2", "travis strikes again", "no more heroes 3"]},
    {"name": "Fragile Dreams Farewell Ruins of the Moon", "query": "Fragile Dreams Farewell Ruins of the Moon Wii gameplay", "aliases": ["fragile dreams", "farewell ruins of the moon"]},
    {"name": "Bravely Default", "query": "Bravely Default Nintendo 3DS gameplay no commentary", "aliases": ["bravely default"], "reject": ["bravely default 2", "bravely default ii", "bravely second"]},
    {"name": "Ever Oasis", "query": "Ever Oasis Nintendo 3DS gameplay no commentary", "aliases": ["ever oasis"]},
    {"name": "Monster Hunter Stories", "query": "Monster Hunter Stories Nintendo 3DS gameplay", "aliases": ["monster hunter stories"], "reject": ["stories 2"]},
    {"name": "Kirby Planet Robobot", "query": "Kirby Planet Robobot Nintendo 3DS gameplay", "aliases": ["kirby planet robobot", "planet robobot"]},
    {"name": "Killer7", "query": "Killer7 PS2 GameCube gameplay no commentary", "aliases": ["killer7", "killer 7"]},
    {"name": "MadWorld", "query": "MadWorld Wii gameplay no commentary", "aliases": ["madworld", "mad world"]},
    {"name": "Hotel Dusk Room 215", "query": "Hotel Dusk Room 215 Nintendo DS gameplay", "aliases": ["hotel dusk", "room 215"]},
    {"name": "The Unfinished Swan", "query": "The Unfinished Swan PS3 gameplay no commentary", "aliases": ["the unfinished swan", "unfinished swan"]},
    {"name": "Mirror's Edge", "query": "Mirror's Edge 2008 gameplay no commentary", "aliases": ["mirror's edge", "mirrors edge"], "reject": ["catalyst"]},
]


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=check,
    )


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or "game"


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", text).strip()


def search_youtube(game: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target = f"ytsearch{SEARCH_RESULTS}:{game['query']}"
    cmd = [
        "yt-dlp", "--dump-json", "--skip-download", "--flat-playlist",
        "--playlist-end", str(SEARCH_RESULTS), "--no-warnings",
        "--js-runtimes", "node", target,
    ]
    proc = run(cmd, timeout=240, check=False)
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        raise RuntimeError(f"No YouTube search results. yt-dlp output: {proc.stdout[-2000:]}")

    scored: list[tuple[float, dict[str, Any]]] = []
    aliases = [normalized(x) for x in game.get("aliases", [])]
    rejects = [normalized(x) for x in game.get("reject", [])]
    for idx, row in enumerate(rows):
        title = normalized(str(row.get("title") or ""))
        if not title:
            continue
        if rejects and any(term in title for term in rejects):
            continue
        alias_match = any(alias in title for alias in aliases)
        if not alias_match:
            # Fallback: all meaningful words from the shortest alias must appear.
            tokens = [t for t in re.findall(r"[a-z0-9]+", aliases[0] if aliases else "") if len(t) > 2]
            alias_match = bool(tokens) and all(t in title for t in tokens)
        if not alias_match:
            continue
        score = 100.0 - idx * 1.4
        for term, bonus in GOOD_TITLE_TERMS.items():
            if term in title:
                score += bonus
        for term in BAD_TITLE_TERMS:
            if term in title:
                score -= 45
        duration = row.get("duration")
        if isinstance(duration, (int, float)):
            if 480 <= duration <= 7200:
                score += 16
            elif duration < 180:
                score -= 50
            elif duration > 14400:
                score -= 15
        channel = normalized(str(row.get("channel") or row.get("uploader") or ""))
        if any(x in channel for x in ["longplayarchive", "world of longplays", "gameplayarchive", "nintendocomplete"]):
            score += 15
        video_id = row.get("id") or row.get("url")
        if not video_id:
            continue
        row["webpage_url"] = row.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
        scored.append((score, row))

    if not scored:
        raise RuntimeError(f"Search results existed but none matched title aliases for {game['name']}")
    scored.sort(key=lambda x: x[0], reverse=True)

    # Fetch full metadata for the strongest candidates until a usable one is found.
    detailed_candidates: list[dict[str, Any]] = []
    for score, row in scored[:6]:
        url = row["webpage_url"]
        detail_proc = run([
            "yt-dlp", "--dump-single-json", "--skip-download", "--no-playlist",
            "--no-warnings", "--js-runtimes", "node", url,
        ], timeout=180, check=False)
        try:
            detail = json.loads(detail_proc.stdout[detail_proc.stdout.find("{"):])
        except Exception:
            detail = dict(row)
        detail["search_score"] = score
        detail["webpage_url"] = detail.get("webpage_url") or url
        detailed_candidates.append(detail)

    usable = []
    for detail in detailed_candidates:
        duration = detail.get("duration")
        if isinstance(duration, (int, float)) and duration >= 180:
            usability = float(detail.get("search_score", 0))
            if 600 <= duration <= 7200:
                usability += 10
            detail["usability_score"] = usability
            usable.append(detail)
    chosen = max(usable or detailed_candidates, key=lambda x: x.get("usability_score", x.get("search_score", 0)))
    return chosen, detailed_candidates


def choose_segment(duration: float | None) -> tuple[float, float]:
    if not duration or duration <= 0:
        return 60.0, 1260.0
    if duration <= 360:
        return 15.0, max(45.0, duration - 10.0)
    start = max(45.0, min(duration * 0.08, 300.0))
    available = max(120.0, duration - start - 20.0)
    length = min(float(MAX_SEGMENT_SECONDS), available)
    return start, start + length


def download_video_segment(source: dict[str, Any], work: Path) -> Path:
    duration = source.get("duration")
    duration_value = float(duration) if isinstance(duration, (int, float)) else None
    start, end = choose_segment(duration_value)
    output_template = str(work / "source.%(ext)s")
    url = str(source["webpage_url"])
    common = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--js-runtimes", "node",
        "--retries", "5", "--fragment-retries", "5", "--socket-timeout", "30",
        "--format", "bestvideo[height<=720]/best[height<=720]/bestvideo/best",
        "--output", output_template,
    ]
    section = f"*{start:.1f}-{end:.1f}"
    proc = run(common + ["--download-sections", section, url], timeout=1800, check=False)
    candidates = sorted(work.glob("source.*"), key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
    if not candidates:
        print("Section download failed; retrying at <=480p without section. Output:\n", proc.stdout[-3000:], flush=True)
        proc2 = run([
            "yt-dlp", "--no-playlist", "--no-warnings", "--js-runtimes", "node",
            "--retries", "5", "--fragment-retries", "5", "--socket-timeout", "30",
            "--format", "bestvideo[height<=480]/best[height<=480]/bestvideo/best",
            "--max-filesize", "1200M", "--output", output_template, url,
        ], timeout=2400, check=False)
        candidates = sorted(work.glob("source.*"), key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
        if not candidates:
            raise RuntimeError(f"Video download failed.\n{proc.stdout[-1500:]}\n{proc2.stdout[-1500:]}")
    video = candidates[0]
    if video.stat().st_size < 100_000:
        raise RuntimeError(f"Downloaded video is suspiciously small: {video.stat().st_size} bytes")
    return video


def extract_candidates(video: Path, candidate_dir: Path) -> list[Path]:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    out_pattern = str(candidate_dir / "candidate_%05d.jpg")
    vf = f"fps=1/{CANDIDATE_INTERVAL_SECONDS},scale='if(gt(iw,1280),1280,iw)':-2"
    proc = run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", vf, "-q:v", "2", out_pattern,
    ], timeout=1200, check=False)
    frames = sorted(candidate_dir.glob("candidate_*.jpg"))
    if len(frames) < TARGET_PER_GAME:
        raise RuntimeError(f"Only {len(frames)} frames extracted. ffmpeg output: {proc.stdout[-1500:]}")
    return frames


@dataclass
class FrameFeature:
    path: Path
    index: int
    timestamp: float
    brightness: float
    sharpness: float
    colorfulness: float
    phash: imagehash.ImageHash
    hist: np.ndarray
    quality: float


def frame_features(path: Path, index: int) -> FrameFeature | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None
    h, w = bgr.shape[:2]
    if min(h, w) < 180:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    if brightness < 12 or brightness > 246:
        return None
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if sharpness < 12:
        return None
    b, g, r = cv2.split(bgr.astype("float"))
    rg = np.abs(r - g)
    yb = np.abs(0.5 * (r + g) - b)
    colorfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    small = cv2.resize(bgr, (192, 108), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    pil = Image.open(path).convert("RGB")
    ph = imagehash.phash(pil, hash_size=12)
    # Log sharpness stops extremely noisy frames from dominating.
    quality = math.log1p(sharpness) + 0.015 * colorfulness - 0.004 * abs(brightness - 128)
    return FrameFeature(
        path=path,
        index=index,
        timestamp=(index - 1) * CANDIDATE_INTERVAL_SECONDS,
        brightness=brightness,
        sharpness=sharpness,
        colorfulness=colorfulness,
        phash=ph,
        hist=hist,
        quality=quality,
    )


def distance(a: FrameFeature, b: FrameFeature, total_time: float) -> float:
    hist_similarity = float(np.dot(a.hist, b.hist))
    hist_distance = max(0.0, 1.0 - hist_similarity)
    phash_distance = (a.phash - b.phash) / float(len(a.phash.hash.flatten()))
    temporal_distance = min(abs(a.timestamp - b.timestamp) / max(total_time, 1.0), 0.35)
    return 0.55 * hist_distance + 0.35 * phash_distance + 0.10 * temporal_distance


def select_diverse(frames: list[Path], target: int) -> list[FrameFeature]:
    features: list[FrameFeature] = []
    for i, path in enumerate(frames, 1):
        feat = frame_features(path, i)
        if feat:
            features.append(feat)
    if not features:
        return []

    # Remove immediate and global near-duplicates while retaining the sharper frame.
    features.sort(key=lambda x: x.quality, reverse=True)
    unique: list[FrameFeature] = []
    for feat in features:
        duplicate = False
        for kept in unique:
            if (feat.phash - kept.phash) <= 8 and float(np.dot(feat.hist, kept.hist)) > 0.94:
                duplicate = True
                break
        if not duplicate:
            unique.append(feat)
        if len(unique) >= 180:
            break

    if len(unique) <= target:
        return sorted(unique, key=lambda x: x.timestamp)

    qualities = np.array([x.quality for x in unique], dtype=np.float32)
    q_min, q_max = float(qualities.min()), float(qualities.max())
    q_norm = {id(x): (x.quality - q_min) / max(q_max - q_min, 1e-8) for x in unique}
    total_time = max(x.timestamp for x in unique) or 1.0

    # Seed across the timeline rather than always taking the single sharpest frame.
    seed = max(unique, key=lambda x: q_norm[id(x)] + 0.15 * min(x.timestamp / total_time, 1 - x.timestamp / total_time))
    selected = [seed]
    remaining = [x for x in unique if x is not seed]

    while remaining and len(selected) < target:
        def selection_score(candidate: FrameFeature) -> float:
            nearest = min(distance(candidate, picked, total_time) for picked in selected)
            # Mild penalty for being within 15 seconds of an already selected frame.
            close = any(abs(candidate.timestamp - picked.timestamp) < 15 for picked in selected)
            return 0.78 * nearest + 0.22 * q_norm[id(candidate)] - (0.12 if close else 0.0)

        best = max(remaining, key=selection_score)
        selected.append(best)
        remaining.remove(best)

    return sorted(selected, key=lambda x: x.timestamp)


def fit_image(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "#101010")
    copy = img.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    x = (size[0] - copy.width) // 2
    y = (size[1] - copy.height) // 2
    canvas.paste(copy, (x, y))
    return canvas


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def create_contact_sheet(game_name: str, image_rows: list[dict[str, Any]], destination: Path) -> None:
    cols = 5
    rows = math.ceil(len(image_rows) / cols)
    cell_w, image_h, label_h = 320, 180, 38
    header_h = 58
    sheet = Image.new("RGB", (cols * cell_w, header_h + rows * (image_h + label_h)), "#111111")
    draw = ImageDraw.Draw(sheet)
    title_font = load_font(26)
    label_font = load_font(16)
    draw.text((18, 14), f"{game_name} — {len(image_rows)} selected gameplay frames", fill="white", font=title_font)
    for idx, row in enumerate(image_rows):
        r, c = divmod(idx, cols)
        x, y = c * cell_w, header_h + r * (image_h + label_h)
        img = Image.open(row["absolute_path"]).convert("RGB")
        fitted = fit_image(img, (cell_w, image_h))
        sheet.paste(fitted, (x, y))
        draw.rectangle((x, y + image_h, x + cell_w, y + image_h + label_h), fill="#1d1d1d")
        draw.text((x + 8, y + image_h + 8), f"{idx + 1:02d}  t+{row['timestamp_seconds']:.0f}s", fill="white", font=label_font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=92)


def process_game(game: dict[str, Any], ordinal: int) -> dict[str, Any]:
    slug = slugify(game["name"])
    game_dir = ROOT / f"{ordinal:02d}_{slug}"
    images_dir = game_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"harvest_{slug}_") as temp_name:
        work = Path(temp_name)
        print(f"\n===== {ordinal:02d}/{len(GAMES)} {game['name']} =====", flush=True)
        source, candidates = search_youtube(game)
        (game_dir / "source_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        video = download_video_segment(source, work)
        frames = extract_candidates(video, work / "candidates")
        selected = select_diverse(frames, TARGET_PER_GAME)
        if len(selected) < TARGET_PER_GAME:
            print(f"WARNING: only {len(selected)} diverse usable frames selected for {game['name']}", flush=True)

        rows: list[dict[str, Any]] = []
        for i, feat in enumerate(selected, 1):
            filename = f"{slug}_{i:03d}_t{int(feat.timestamp):05d}s.jpg"
            destination = images_dir / filename
            shutil.copy2(feat.path, destination)
            with Image.open(destination) as img:
                width, height = img.size
            rows.append({
                "game": game["name"],
                "filename": filename,
                "relative_path": str(destination.relative_to(ROOT)),
                "absolute_path": str(destination),
                "source_type": "gameplay_video_frame",
                "source_url": source.get("webpage_url"),
                "source_title": source.get("title"),
                "source_channel": source.get("channel") or source.get("uploader"),
                "source_duration_seconds": source.get("duration"),
                "timestamp_seconds": round(feat.timestamp, 2),
                "width": width,
                "height": height,
                "brightness": round(feat.brightness, 3),
                "sharpness": round(feat.sharpness, 3),
                "colorfulness": round(feat.colorfulness, 3),
                "perceptual_hash": str(feat.phash),
                "validation_status": "AUTO_SELECTED_FROM_MATCHED_GAMEPLAY_VIDEO",
                "contains_ui": "unknown",
                "manual_review_required": True,
            })

        contact_sheet = game_dir / f"contact_sheet_{slug}.jpg"
        create_contact_sheet(game["name"], rows, contact_sheet)
        for row in rows:
            row.pop("absolute_path", None)
        manifest = {
            "game": game["name"],
            "query": game["query"],
            "target_count": TARGET_PER_GAME,
            "selected_count": len(rows),
            "source": {
                "url": source.get("webpage_url"),
                "title": source.get("title"),
                "channel": source.get("channel") or source.get("uploader"),
                "duration_seconds": source.get("duration"),
                "video_id": source.get("id"),
            },
            "method": {
                "general_image_search_used": False,
                "source_kind": "public gameplay video",
                "candidate_interval_seconds": CANDIDATE_INTERVAL_SECONDS,
                "near_duplicate_filter": "pHash + HSV histogram",
                "selection": "quality-filtered farthest-first visual diversity",
                "manual_review_required": True,
            },
            "images": rows,
        }
        (game_dir / f"manifest_{slug}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest


def make_master_contact_sheet(manifests: list[dict[str, Any]], destination: Path) -> None:
    thumbs: list[tuple[str, Path]] = []
    for manifest in manifests:
        game_slug = slugify(manifest["game"])
        path = ROOT / f"{GAMES.index(next(g for g in GAMES if g['name'] == manifest['game'])) + 1:02d}_{game_slug}" / f"contact_sheet_{game_slug}.jpg"
        if path.exists():
            thumbs.append((manifest["game"], path))
    if not thumbs:
        return
    cols = 3
    cell_w, cell_h = 520, 330
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "#0d0d0d")
    draw = ImageDraw.Draw(sheet)
    font = load_font(20)
    for i, (name, path) in enumerate(thumbs):
        r, c = divmod(i, cols)
        x, y = c * cell_w, r * cell_h
        img = Image.open(path).convert("RGB")
        img.thumbnail((cell_w, cell_h - 36), Image.Resampling.LANCZOS)
        sheet.paste(img, (x + (cell_w - img.width) // 2, y))
        draw.text((x + 10, y + cell_h - 30), name, fill="white", font=font)
    sheet.save(destination, quality=90)


def main() -> int:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    manifests: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for ordinal, game in enumerate(GAMES, 1):
        try:
            manifests.append(process_game(game, ordinal))
        except Exception as exc:
            print(f"ERROR processing {game['name']}: {exc}", file=sys.stderr, flush=True)
            failures.append({"game": game["name"], "error": str(exc), "query": game["query"]})

    total_images = sum(m.get("selected_count", 0) for m in manifests)
    report = {
        "requested_games": len(GAMES),
        "completed_games": len(manifests),
        "failed_games": len(failures),
        "target_per_game": TARGET_PER_GAME,
        "selected_images": total_images,
        "expected_images_if_complete": len(GAMES) * TARGET_PER_GAME,
        "elapsed_seconds": round(time.time() - started, 2),
        "safety": {
            "general_web_image_scraping": False,
            "method": "frames extracted from gameplay videos whose titles match the requested game",
            "manual_review": "Contact sheets are included; final human approval remains recommended.",
        },
        "games": [
            {
                "game": m["game"],
                "selected_count": m["selected_count"],
                "source_url": m["source"]["url"],
                "source_title": m["source"]["title"],
            }
            for m in manifests
        ],
        "failures": failures,
    }
    (ROOT / "master_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "failed_games.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = f"""# AI Prod Gameplay Screenshot Reference Bank

- Requested games: {len(GAMES)}
- Completed games: {len(manifests)}
- Selected images: {total_images}
- Target: {TARGET_PER_GAME} per game

## Collection method

The pack was derived from matched public gameplay videos, not from unrestricted image-search scraping. Frames were sampled, screened for basic technical quality, deduplicated using perceptual hashes and colour histograms, and selected for visual diversity.

Each game folder includes the selected JPEG files, a contact sheet, candidate-source metadata, and a detailed manifest. Review the contact sheets before using the references in production. Automated selection cannot replace final human visual approval.
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    make_master_contact_sheet(manifests, ROOT / "MASTER_CONTACT_SHEET.jpg")

    archive_base = Path.cwd() / "AI_PROD_GAMEPLAY_REFERENCE_BANK"
    archive = shutil.make_archive(str(archive_base), "zip", ROOT.parent, ROOT.name)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"ARCHIVE={archive}", flush=True)
    # Return success if at least 70% of games completed; artifact remains useful and failures are explicit.
    return 0 if len(manifests) >= math.ceil(len(GAMES) * 0.70) else 2


if __name__ == "__main__":
    raise SystemExit(main())
