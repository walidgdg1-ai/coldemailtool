#!/usr/bin/env python3
"""Harvest trusted gallery screenshots for three missing games.

Sources are deliberately fixed and game-specific:
- Ghost Trick: Nintendo Life's 24-image Nintendo DS screenshot gallery.
- Fantasy Life: Nintendo Life's 11-image 3DS gallery plus YouTube's automatic
  in-video frames from two official Nintendo presentations.
- Auto Modellista: MobyGames' 20-image Xbox screenshot gallery.

No general image search, custom YouTube thumbnails, fan art, or unrelated image
aggregators are used. Every output includes a source manifest and contact sheet.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import cv2
import imagehash
import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

import harvest_game_screenshots as base

ROOT = Path(os.environ.get("HARVEST_ROOT", "GAMEPLAY_REFERENCE_BANK")).resolve()
TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))

GHOST_TRICK_IDS = [
    26562, 26563, 26564, 26565, 26566, 26567, 26568, 26569,
    26570, 26571, 26559, 26560, 26561, 25602, 25547, 25548,
    25549, 25550, 25551, 25552, 25553, 25554, 25555, 25556,
]

FANTASY_LIFE_IDS = [61960, 61961, 61962, 61963, 61964, 61954, 61955, 61956, 61957, 61958, 61959]
FANTASY_VIDEO_IDS = ["Gh3CuSGaFRw", "jj9V5-7Vqno"]

CONFIG: dict[int, dict[str, Any]] = {
    8: {
        "game": base.GAMES[7],
        "source_label": "Nintendo Life DS screenshot gallery",
        "gallery_url": "https://www.nintendolife.com/games/ds/ghost_trick_phantom_detective/screenshots",
    },
    9: {
        "game": base.GAMES[8],
        "source_label": "Nintendo Life 3DS gallery and official Nintendo video auto-frames",
        "gallery_url": "https://www.nintendolife.com/games/3ds/fantasy_life/screenshots",
    },
    20: {
        "game": base.GAMES[19],
        "source_label": "MobyGames Auto Modellista Xbox screenshot gallery",
        "gallery_url": "https://www.mobygames.com/game/9950/auto-modellista/screenshots/xbox/",
    },
}


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def get_image(s: requests.Session, urls: list[str]) -> tuple[Image.Image, str] | None:
    for url in urls:
        try:
            response = s.get(url, timeout=30)
        except requests.RequestException:
            continue
        if response.status_code != 200 or len(response.content) < 4_000:
            continue
        content_type = response.headers.get("content-type", "").lower()
        if "image" not in content_type and not response.content.startswith((b"\xff\xd8", b"\x89PNG")):
            continue
        try:
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
            image.load()
        except Exception:
            continue
        if image.width < 240 or image.height < 150:
            continue
        arr = np.asarray(image)
        if float(arr.std()) < 7.0:
            continue
        return image, response.url
    return None


def nintendo_life_candidates(s: requests.Session, ids: list[int], game_key: str) -> list[dict[str, Any]]:
    rows = []
    for screenshot_id in ids:
        variants = [
            f"https://images.nintendolife.com/screenshots/{screenshot_id}/900x.jpg",
            f"https://images.nintendolife.com/screenshots/{screenshot_id}/1280x720.jpg",
            f"https://images.nintendolife.com/screenshots/{screenshot_id}/600x.jpg",
            f"https://images.nintendolife.com/screenshots/{screenshot_id}/300x200.jpg",
        ]
        fetched = get_image(s, variants)
        if not fetched:
            print(f"WARNING: Nintendo Life screenshot {screenshot_id} unavailable", file=sys.stderr)
            continue
        image, resolved = fetched
        rows.append({
            "image": image,
            "source_url": resolved,
            "source_page": CONFIG[8 if game_key == "ghost_trick" else 9]["gallery_url"],
            "source_domain": "images.nintendolife.com",
            "source_type": "curated_game_screenshot_gallery",
            "source_id": str(screenshot_id),
            "version": "Nintendo DS" if game_key == "ghost_trick" else "Nintendo 3DS",
        })
    return rows


def youtube_auto_candidates(s: requests.Session) -> list[dict[str, Any]]:
    rows = []
    for video_id in FANTASY_VIDEO_IDS:
        for position in (1, 2, 3):
            variants = [
                f"https://i.ytimg.com/vi/{video_id}/sd{position}.jpg",
                f"https://i.ytimg.com/vi/{video_id}/hq{position}.jpg",
            ]
            fetched = get_image(s, variants)
            if not fetched:
                continue
            image, resolved = fetched
            rows.append({
                "image": image,
                "source_url": resolved,
                "source_page": f"https://www.youtube.com/watch?v={video_id}",
                "source_domain": "i.ytimg.com",
                "source_type": "youtube_auto_generated_in_video_frame",
                "source_id": f"{video_id}_position_{position}",
                "version": "Nintendo 3DS",
                "custom_uploader_thumbnail": False,
            })
    return rows


def best_src_from_img(img) -> str | None:
    candidates = []
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        value = img.get(attr)
        if value:
            candidates.append(value)
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        for part in srcset.split(","):
            url = part.strip().split(" ")[0]
            if url:
                candidates.append(url)
    candidates = [u for u in candidates if "cdn.mobygames.com" in u and "screenshot" in u.lower()]
    if not candidates:
        return None
    def score(url: str) -> tuple[int, int]:
        nums = [int(x) for x in re.findall(r"(?:^|[-_/])(\d{3,4})(?:x(\d{3,4}))?", url) for x in x if False]
        return (len(url), 1 if "large" in url or "original" in url else 0)
    return max(candidates, key=lambda u: (1 if "original" in u else 0, len(u)))


def mobygames_candidates(s: requests.Session) -> list[dict[str, Any]]:
    gallery = CONFIG[20]["gallery_url"]
    pages: set[str] = set()
    try:
        response = s.get(gallery, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = urljoin(gallery, link["href"])
                if re.search(r"/screenshots/xbox/\d+/?$", href):
                    pages.add(href)
    except requests.RequestException as exc:
        print(f"WARNING: gallery fetch failed: {exc}", file=sys.stderr)

    # Known MobyGames screenshot IDs for the twenty-image Xbox gallery are
    # contiguous. Include them as a robust fallback if gallery pagination is
    # hidden behind client-side markup.
    for screenshot_id in range(124054, 124074):
        pages.add(f"https://www.mobygames.com/game/9950/auto-modellista/screenshots/xbox/{screenshot_id}/")

    rows = []
    seen_urls: set[str] = set()
    for page in sorted(pages):
        try:
            response = s.get(page, timeout=30)
        except requests.RequestException:
            continue
        if response.status_code != 200:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        image_urls = []
        for img in soup.find_all("img"):
            alt = (img.get("alt") or "").lower()
            src = best_src_from_img(img)
            if src and ("auto modellista" in alt or "screenshot" in alt or "screenshots" in src.lower()):
                image_urls.append(urljoin(page, src))
        # Also scan raw HTML because MobyGames occasionally serializes image URLs
        # inside JSON attributes rather than conventional img tags.
        image_urls.extend(re.findall(r'https://cdn\.mobygames\.com/screenshots/[^"\'<>\\ ]+\.(?:png|jpe?g|webp)', response.text, flags=re.I))
        for image_url in image_urls:
            image_url = image_url.replace("&amp;", "&")
            if image_url in seen_urls:
                continue
            fetched = get_image(s, [image_url])
            if not fetched:
                continue
            image, resolved = fetched
            seen_urls.add(resolved)
            rows.append({
                "image": image,
                "source_url": resolved,
                "source_page": page,
                "source_domain": "cdn.mobygames.com",
                "source_type": "curated_game_screenshot_gallery",
                "source_id": re.search(r"/(\d+)/?$", page).group(1) if re.search(r"/(\d+)/?$", page) else page,
                "version": "Xbox",
            })
    return rows


def technical_feature(path: Path) -> dict[str, Any] | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 8 or brightness > 249 or sharpness < 4:
        return None
    hsv = cv2.cvtColor(cv2.resize(bgr, (192, 108)), cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    phash = imagehash.phash(Image.open(path).convert("RGB"), hash_size=12)
    quality = math.log1p(sharpness) - 0.003 * abs(brightness - 128)
    return {"path": path, "quality": quality, "phash": phash, "hist": hist}


def select_diverse(paths: list[Path], target: int) -> list[Path]:
    rows = [item for path in paths if (item := technical_feature(path))]
    rows.sort(key=lambda item: item["quality"], reverse=True)
    unique = []
    for row in rows:
        if any((row["phash"] - kept["phash"]) <= 7 and float(np.dot(row["hist"], kept["hist"])) > 0.93 for kept in unique):
            continue
        unique.append(row)
    if len(unique) <= target:
        return [row["path"] for row in unique]
    qualities = np.array([row["quality"] for row in unique], dtype=np.float32)
    low, high = float(qualities.min()), float(qualities.max())
    for row in unique:
        row["qnorm"] = (row["quality"] - low) / max(high - low, 1e-8)
    selected = [max(unique, key=lambda row: row["qnorm"])]
    remaining = [row for row in unique if row is not selected[0]]
    while remaining and len(selected) < target:
        def score(candidate):
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
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def make_contact_sheet(game: str, rows: list[dict[str, Any]], output: Path) -> None:
    cols = 5
    cell_w, image_h, label_h = 320, 210, 42
    row_count = math.ceil(len(rows) / cols)
    header_h = 62
    canvas = Image.new("RGB", (cols * cell_w, header_h + row_count * (image_h + label_h)), "#101010")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 15), f"{game} — {len(rows)} trusted gallery frames", fill="white", font=load_font(24))
    for idx, row in enumerate(rows):
        r, c = divmod(idx, cols)
        x, y = c * cell_w, header_h + r * (image_h + label_h)
        image = Image.open(row["absolute_path"]).convert("RGB")
        image.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, image_h), "black")
        frame.paste(image, ((cell_w - image.width) // 2, (image_h - image.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + image_h, x + cell_w, y + image_h + label_h), fill="#1d1d1d")
        draw.text((x + 8, y + image_h + 10), f"{idx + 1:02d} · {row['source_domain']} · {row['version']}", fill="white", font=load_font(14))
    output.save(output, quality=92)


def main() -> int:
    index = int(os.environ.get("GAME_INDEX", "0"))
    if index not in CONFIG:
        raise SystemExit(f"GAME_INDEX must be one of {sorted(CONFIG)}")
    config = CONFIG[index]
    game = config["game"]
    slug = base.slugify(game["name"])
    if ROOT.exists():
        shutil.rmtree(ROOT)
    game_dir = ROOT / f"{index:02d}_{slug}"
    candidate_dir = game_dir / "trusted_candidates"
    images_dir = game_dir / "images"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    s = session()

    if index == 8:
        candidates = nintendo_life_candidates(s, GHOST_TRICK_IDS, "ghost_trick")
    elif index == 9:
        candidates = nintendo_life_candidates(s, FANTASY_LIFE_IDS, "fantasy_life") + youtube_auto_candidates(s)
    else:
        candidates = mobygames_candidates(s)

    metadata: dict[str, dict[str, Any]] = {}
    paths = []
    for number, candidate in enumerate(candidates, 1):
        path = candidate_dir / f"candidate_{number:03d}.jpg"
        candidate["image"].save(path, quality=95)
        meta = {key: value for key, value in candidate.items() if key != "image"}
        metadata[str(path)] = meta
        paths.append(path)

    selected_paths = select_diverse(paths, TARGET)
    rows = []
    for rank, source_path in enumerate(selected_paths, 1):
        destination = images_dir / f"{slug}_{rank:03d}_trusted_gallery.jpg"
        shutil.copy2(source_path, destination)
        with Image.open(destination) as image:
            width, height = image.size
        rows.append({
            "game": game["name"],
            "filename": destination.name,
            "relative_path": str(destination.relative_to(ROOT)),
            "absolute_path": str(destination),
            "width": width,
            "height": height,
            "validation_status": "FIXED_TRUSTED_GAME_GALLERY_AND_TECHNICALLY_FILTERED",
            "manual_review_required": True,
            **metadata[str(source_path)],
        })

    contact_sheet = game_dir / f"contact_sheet_{slug}.jpg"
    make_contact_sheet(game["name"], rows, contact_sheet)
    for row in rows:
        row.pop("absolute_path", None)
    manifest = {
        "game": game["name"],
        "target_count": TARGET,
        "selected_count": len(rows),
        "candidate_count": len(candidates),
        "elapsed_seconds": round(time.time() - started, 2),
        "source_label": config["source_label"],
        "gallery_url": config["gallery_url"],
        "method": {
            "general_image_search_used": False,
            "fixed_game_specific_sources_only": True,
            "fan_art_allowed": False,
            "custom_youtube_thumbnails_used": False,
            "deduplication": "perceptual hash plus HSV histogram",
            "manual_review_required": True,
        },
        "images": rows,
    }
    (game_dir / f"manifest_{slug}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (game_dir / "source_candidates.json").write_text(json.dumps([{key: value for key, value in candidate.items() if key != "image"} for candidate in candidates], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if len(rows) >= TARGET else 2


if __name__ == "__main__":
    raise SystemExit(main())
