#!/usr/bin/env python3
"""Extract diverse gameplay frames from YouTube timeline storyboard sheets.

The video IDs below are sourced from game-specific database/editorial pages.
This avoids broad search ambiguity for three niche titles whose YouTube search
results were sparse. yt-dlp fetches the public MHTML storyboard format only;
no video or audio stream is downloaded.
"""

from __future__ import annotations

import email
from email import policy
from email.parser import BytesParser
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import harvest_game_screenshots as base

ROOT = Path(os.environ.get("HARVEST_ROOT", "GAMEPLAY_REFERENCE_BANK")).resolve()
TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))

KNOWN: dict[int, dict[str, Any]] = {
    8: {
        "game": base.GAMES[7],
        "videos": [
            {"id": "2OxMfwK7XKM", "source": "LaunchBox Nintendo DS game entry"},
            {"id": "HEQRtpwP3P0", "source": "Nintendo Life Ghost Trick episode 1"},
            {"id": "zaRpCwS5cA8", "source": "Nintendo Life Ghost Trick episode 2"},
        ],
    },
    9: {
        "game": base.GAMES[8],
        "videos": [
            {"id": "Gh3CuSGaFRw", "source": "Nintendo Treehouse Fantasy Life gameplay"},
            {"id": "jj9V5-7Vqno", "source": "Nintendo E3 Fantasy Life presentation"},
        ],
    },
    20: {
        "game": base.GAMES[19],
        "videos": [
            {"id": "zHk4lOcOqiI", "source": "LaunchBox PlayStation 2 game entry"},
            {"id": "x7JMrJzvaFo", "source": "LaunchBox GameCube game entry"},
            {"id": "bwDiYPvuikE", "source": "LaunchBox Xbox game entry"},
        ],
    },
}


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def parse_json_output(text: str) -> dict[str, Any] | None:
    for start in [i for i, ch in enumerate(text) if ch == "{"]:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            continue
    return None


def get_metadata(video_id: str) -> dict[str, Any]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    proc = run([
        "yt-dlp", "--dump-single-json", "--skip-download", "--no-playlist",
        "--no-warnings", "--js-runtimes", "node", url,
    ], timeout=240)
    data = parse_json_output(proc.stdout)
    if not data:
        raise RuntimeError(f"Could not read metadata for {video_id}: {proc.stdout[-1200:]}")
    return data


def choose_storyboard_format(metadata: dict[str, Any]) -> dict[str, Any]:
    formats = []
    for fmt in metadata.get("formats") or []:
        fmt_id = str(fmt.get("format_id") or "")
        protocol = str(fmt.get("protocol") or "")
        ext = str(fmt.get("ext") or "")
        note = str(fmt.get("format_note") or "").lower()
        if protocol == "mhtml" or ext == "mhtml" or fmt_id.startswith("sb") or "storyboard" in note:
            width = int(fmt.get("width") or 0)
            height = int(fmt.get("height") or 0)
            formats.append((width * height, width, height, fmt))
    if not formats:
        raise RuntimeError("No public storyboard format was exposed")
    formats.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return formats[0][3]


def download_storyboard(video_id: str, format_id: str, work: Path) -> Path:
    url = f"https://www.youtube.com/watch?v={video_id}"
    template = str(work / f"{video_id}.%(ext)s")
    proc = run([
        "yt-dlp", "--no-playlist", "--no-warnings", "--js-runtimes", "node",
        "-f", format_id, "-o", template, url,
    ], timeout=600)
    candidates = list(work.glob(f"{video_id}.*"))
    if not candidates:
        raise RuntimeError(f"Storyboard download failed for {video_id}: {proc.stdout[-1600:]}")
    path = max(candidates, key=lambda p: p.stat().st_size)
    if path.stat().st_size < 10_000:
        raise RuntimeError(f"Storyboard file for {video_id} is suspiciously small")
    return path


def decode_mhtml_images(path: Path) -> list[Image.Image]:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    images: list[Image.Image] = []
    for part in message.walk():
        content_type = part.get_content_type()
        if not content_type.startswith("image/"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        try:
            image = Image.open(io.BytesIO(payload)).convert("RGB")
            image.load()
            images.append(image)
        except Exception:
            continue
    return images


def split_sheet(sheet: Image.Image, tile_width: int, tile_height: int) -> list[Image.Image]:
    if tile_width <= 0 or tile_height <= 0:
        raise RuntimeError("Storyboard metadata lacks tile dimensions")
    cols = max(1, sheet.width // tile_width)
    rows = max(1, sheet.height // tile_height)
    tiles: list[Image.Image] = []
    for row in range(rows):
        for col in range(cols):
            left = col * tile_width
            top = row * tile_height
            tile = sheet.crop((left, top, left + tile_width, top + tile_height)).convert("RGB")
            arr = np.asarray(tile)
            if arr.size == 0 or float(arr.std()) < 7.0 or float(arr.mean()) < 8.0:
                continue
            tiles.append(tile)
    return tiles


def feature(path: Path) -> dict[str, Any] | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 9 or brightness > 248 or sharpness < 5:
        return None
    hsv = cv2.cvtColor(cv2.resize(bgr, (192, 108)), cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    phash = imagehash.phash(Image.open(path).convert("RGB"), hash_size=12)
    quality = math.log1p(sharpness) - 0.003 * abs(brightness - 128)
    return {"path": path, "quality": quality, "phash": phash, "hist": hist}


def select_diverse(paths: list[Path], target: int) -> list[Path]:
    rows = [item for path in paths if (item := feature(path))]
    rows.sort(key=lambda item: item["quality"], reverse=True)
    unique: list[dict[str, Any]] = []
    for row in rows:
        if any(
            (row["phash"] - kept["phash"]) <= 7
            and float(np.dot(row["hist"], kept["hist"])) > 0.93
            for kept in unique
        ):
            continue
        unique.append(row)
    if len(unique) <= target:
        return [row["path"] for row in unique]

    values = np.array([row["quality"] for row in unique], dtype=np.float32)
    low, high = float(values.min()), float(values.max())
    for row in unique:
        row["qnorm"] = (row["quality"] - low) / max(high - low, 1e-8)

    selected = [max(unique, key=lambda row: row["qnorm"])]
    remaining = [row for row in unique if row is not selected[0]]
    while remaining and len(selected) < target:
        def score(candidate: dict[str, Any]) -> float:
            distances = []
            for picked in selected:
                hash_distance = (candidate["phash"] - picked["phash"]) / float(len(candidate["phash"].hash.flatten()))
                hist_distance = max(0.0, 1.0 - float(np.dot(candidate["hist"], picked["hist"])))
                distances.append(0.55 * hist_distance + 0.45 * hash_distance)
            return 0.84 * min(distances) + 0.16 * candidate["qnorm"]
        best = max(remaining, key=score)
        selected.append(best)
        remaining.remove(best)
    return [row["path"] for row in selected]


def load_font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def make_contact_sheet(game: str, rows: list[dict[str, Any]], destination: Path) -> None:
    cols = 5
    cell_w, image_h, label_h = 320, 180, 40
    total_rows = math.ceil(len(rows) / cols)
    header_h = 58
    canvas = Image.new("RGB", (cols * cell_w, header_h + total_rows * (image_h + label_h)), "#101010")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 14), f"{game} — {len(rows)} storyboard gameplay frames", fill="white", font=load_font(24))
    for index, row in enumerate(rows):
        r, c = divmod(index, cols)
        x, y = c * cell_w, header_h + r * (image_h + label_h)
        image = Image.open(row["absolute_path"]).convert("RGB")
        image.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, image_h), "black")
        frame.paste(image, ((cell_w - image.width) // 2, (image_h - image.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + image_h, x + cell_w, y + image_h + label_h), fill="#1d1d1d")
        draw.text((x + 8, y + image_h + 9), f"{index + 1:02d} · {row['video_id']} · tile {row['tile_index']}", fill="white", font=load_font(14))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=92)


def main() -> int:
    index = int(os.environ.get("GAME_INDEX", "0"))
    if index not in KNOWN:
        raise SystemExit(f"GAME_INDEX must be one of {sorted(KNOWN)}")
    record = KNOWN[index]
    game = record["game"]
    slug = base.slugify(game["name"])
    if ROOT.exists():
        shutil.rmtree(ROOT)
    game_dir = ROOT / f"{index:02d}_{slug}"
    images_dir = game_dir / "images"
    candidate_dir = game_dir / "storyboard_candidates"
    images_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    candidate_paths: list[Path] = []
    metadata_by_path: dict[str, dict[str, Any]] = {}
    source_records: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix=f"storyboard_{slug}_") as temp_name:
        work = Path(temp_name)
        for video in record["videos"]:
            video_id = video["id"]
            try:
                metadata = get_metadata(video_id)
                storyboard_format = choose_storyboard_format(metadata)
                format_id = str(storyboard_format.get("format_id"))
                tile_width = int(storyboard_format.get("width") or 0)
                tile_height = int(storyboard_format.get("height") or 0)
                mhtml = download_storyboard(video_id, format_id, work)
                sheets = decode_mhtml_images(mhtml)
                tiles: list[Image.Image] = []
                for sheet in sheets:
                    tiles.extend(split_sheet(sheet, tile_width, tile_height))
                source_records.append({
                    "video_id": video_id,
                    "video_url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": metadata.get("title"),
                    "channel": metadata.get("channel") or metadata.get("uploader"),
                    "duration_seconds": metadata.get("duration"),
                    "database_source": video["source"],
                    "storyboard_format_id": format_id,
                    "tile_width": tile_width,
                    "tile_height": tile_height,
                    "sprite_sheets": len(sheets),
                    "tiles_extracted": len(tiles),
                    "status": "success",
                })
                for tile_index, tile in enumerate(tiles):
                    path = candidate_dir / f"{video_id}_{tile_index:05d}.jpg"
                    # Upscale only for easier inspection; no invented detail filtering.
                    if tile.width < 640:
                        scale = 640 / tile.width
                        tile = tile.resize((640, int(tile.height * scale)), Image.Resampling.NEAREST)
                    tile.save(path, quality=94)
                    candidate_paths.append(path)
                    metadata_by_path[str(path)] = {
                        "video_id": video_id,
                        "video_url": f"https://www.youtube.com/watch?v={video_id}",
                        "video_title": metadata.get("title"),
                        "database_source": video["source"],
                        "tile_index": tile_index,
                    }
            except Exception as exc:
                source_records.append({
                    "video_id": video_id,
                    "video_url": f"https://www.youtube.com/watch?v={video_id}",
                    "database_source": video["source"],
                    "status": "failed",
                    "error": str(exc),
                })
                print(f"WARNING {video_id}: {exc}", file=sys.stderr, flush=True)

    selected_paths = select_diverse(candidate_paths, TARGET)
    rows: list[dict[str, Any]] = []
    for rank, source in enumerate(selected_paths, 1):
        destination = images_dir / f"{slug}_{rank:03d}_storyboard_frame.jpg"
        shutil.copy2(source, destination)
        with Image.open(destination) as image:
            width, height = image.size
        row = {
            "game": game["name"],
            "filename": destination.name,
            "relative_path": str(destination.relative_to(ROOT)),
            "absolute_path": str(destination),
            "width": width,
            "height": height,
            "source_type": "youtube_timeline_storyboard_frame",
            "custom_uploader_thumbnail": False,
            "video_stream_downloaded": False,
            "validation_status": "TRUSTED_VIDEO_ID_AND_TECHNICALLY_FILTERED",
            "manual_review_required": True,
            **metadata_by_path[str(source)],
        }
        rows.append(row)

    contact_sheet = game_dir / f"contact_sheet_{slug}.jpg"
    make_contact_sheet(game["name"], rows, contact_sheet)
    for row in rows:
        row.pop("absolute_path", None)
    manifest = {
        "game": game["name"],
        "target_count": TARGET,
        "selected_count": len(rows),
        "candidate_count": len(candidate_paths),
        "sources": source_records,
        "method": {
            "general_image_search_used": False,
            "video_stream_downloaded": False,
            "source": "YouTube public timeline storyboard MHTML sheets",
            "video_ids_from_game_specific_sources": True,
            "custom_thumbnails_used": False,
            "deduplication": "perceptual hash plus HSV histogram",
            "manual_review_required": True,
        },
        "images": rows,
    }
    (game_dir / f"manifest_{slug}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (game_dir / "source_videos.json").write_text(json.dumps(source_records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if len(rows) >= TARGET else 2


if __name__ == "__main__":
    raise SystemExit(main())
