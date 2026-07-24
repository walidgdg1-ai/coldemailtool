#!/usr/bin/env python3
"""Harvest additional high-resolution gameplay screenshots from trusted galleries.

Bing Images is used only as a discovery index. Every accepted result must point
to a known gaming/editorial/official domain, match the exact game title, pass
resolution and image-quality checks, avoid artwork/cover/menu terms, and survive
perceptual deduplication. The original source page and image URL are recorded.
"""
from __future__ import annotations

import html
import json
import math
import os
import random
import re
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import imagehash
import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import harvest_game_screenshots as base

ROOT = Path(os.environ.get("HARVEST_ROOT", "HD_EXTRA_REFERENCE_BANK")).resolve()
TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))
MIN_NATIVE_W = int(os.environ.get("MIN_NATIVE_W", "900"))
MIN_NATIVE_H = int(os.environ.get("MIN_NATIVE_H", "500"))
FALLBACK_W = int(os.environ.get("FALLBACK_W", "600"))
FALLBACK_H = int(os.environ.get("FALLBACK_H", "330"))
MAX_BYTES = 20 * 1024 * 1024

TRUSTED_PAGE_DOMAINS = {
    "nintendolife.com", "pushsquare.com", "purexbox.com", "gamespot.com",
    "gamefaqs.gamespot.com", "ign.com", "ignimgs.com", "mobygames.com",
    "steamcommunity.com", "steampowered.com", "playstation.com",
    "blog.playstation.com", "nintendo.com", "xbox.com", "gematsu.com",
    "rpgsite.net", "siliconera.com", "destructoid.com", "gamesradar.com",
    "eurogamer.net", "vg247.com", "polygon.com", "kotaku.com",
    "gameinformer.com", "giantbomb.com", "hardcoregamer.com",
    "gamingbolt.com", "dualshockers.com", "thegamer.com", "gamerant.com",
    "gamepressure.com", "jeuxvideo.com", "nintendoeverything.com",
    "gonintendo.com", "wccftech.com", "rockpapershotgun.com", "pcgamer.com",
    "fandom.com", "wikia.com", "wikimedia.org", "launchbox-app.com",
    "igdb.com", "rawg.io", "thegamesdb.net", "screenscraper.fr",
    "retroplace.com", "racketboy.com", "timeextension.com", "videogameschronicle.com",
}
TRUSTED_IMAGE_DOMAINS = {
    "images.nintendolife.com", "images.pushsquare.com", "images.purexbox.com",
    "cdn.mobygames.com", "steamuserimages-a.akamaihd.net", "steamuserimages.akamaihd.net",
    "shared.akamai.steamstatic.com", "cdn.cloudflare.steamstatic.com",
    "static.wikia.nocookie.net", "vignette.wikia.nocookie.net",
    "images.igdb.com", "media.rawg.io", "image.api.playstation.com",
    "blog.playstation.com", "assets.nintendo.com", "www.gamespot.com",
    "gamespot.com", "assets1.ignimgs.com", "assets2.ignimgs.com",
    "assets-prd.ignimgs.com", "sm.ign.com", "cdn.vox-cdn.com",
    "cdn.mos.cms.futurecdn.net", "assetsio.gnwcdn.com", "cdn.gematsu.com",
    "www.rpgsite.net", "media.rpgsite.net", "www.siliconera.com",
    "static1.thegamerimages.com", "static0.gamerantimages.com",
    "images.gamepressure.com", "image.jeuxvideo.com", "images2.alphacoders.com",
}
BLOCKED_DOMAINS = {
    "pinterest.com", "pinimg.com", "deviantart.com", "artstation.com",
    "tumblr.com", "reddit.com", "redd.it", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "tiktok.com", "rule34", "gelbooru",
    "danbooru", "zerochan", "wallpaper", "wallhaven", "flickr.com",
}
REJECT_TERMS = {
    "box art", "boxart", "cover art", "coverart", "game cover", "poster",
    "wallpaper", "fan art", "fanart", "concept art", "conceptart", "artwork",
    "character render", "character artwork", "key art", "logo", "icon",
    "title screen", "main menu", "inventory", "map screen", "soundtrack",
    "ost", "review score", "tier list", "thumbnail", "banner", "sprite sheet",
    "cosplay", "figurine", "amiibo", "merch", "packaging", "manual scan",
}
GAMEPLAY_TERMS = {
    "gameplay", "screenshot", "screen shot", "in-game", "ingame", "walkthrough",
    "combat", "battle", "exploration", "level", "mission", "game screen",
}

# Games where visible third-person character framing is especially desirable.
THIRD_PERSON_ORDINALS = {
    1, 2, 3, 7, 9, 10, 11, 12, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28,
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", text).strip()


def domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    except Exception:
        return ""


def domain_allowed(url: str, allowed: set[str]) -> bool:
    host = domain(url)
    return any(host == item or host.endswith("." + item) for item in allowed)


def blocked(url: str) -> bool:
    host = domain(url)
    return any(term in host for term in BLOCKED_DOMAINS)


def exact_game_match(game: dict[str, Any], text: str) -> bool:
    text = norm(unquote(text))
    if not text:
        return False
    rejects = [norm(x) for x in game.get("reject", [])]
    if any(term in text for term in rejects):
        return False
    aliases = [norm(x) for x in game.get("aliases", [])]
    if any(alias in text for alias in aliases):
        return True
    if aliases:
        tokens = [t for t in re.findall(r"[a-z0-9]+", aliases[0]) if len(t) > 2]
        return bool(tokens) and all(token in text for token in tokens)
    return False


def reject_context(text: str) -> bool:
    text = norm(text)
    return any(term in text for term in REJECT_TERMS)


def gameplay_context(text: str) -> bool:
    text = norm(text)
    return any(term in text for term in GAMEPLAY_TERMS)


def queries_for(game: dict[str, Any], index: int) -> list[str]:
    name = game["name"]
    queries = [
        f'"{name}" gameplay screenshot 1080p',
        f'"{name}" in-game screenshot HD',
        f'"{name}" gameplay screenshots gallery',
        f'"{name}" no HUD gameplay screenshot',
        f'site:gamespot.com "{name}" gameplay screenshot',
        f'site:ign.com "{name}" screenshots',
        f'site:mobygames.com "{name}" screenshots',
        f'site:nintendolife.com "{name}" screenshots',
        f'site:pushsquare.com "{name}" screenshots',
        f'site:steamcommunity.com "{name}" screenshot',
    ]
    if index in THIRD_PERSON_ORDINALS:
        queries.insert(0, f'"{name}" third person gameplay screenshot HD')
        queries.insert(1, f'"{name}" character visible gameplay screenshot')
    return queries


def bing_results(session: requests.Session, query: str, first: int) -> list[dict[str, Any]]:
    url = "https://www.bing.com/images/search"
    params = {"q": query, "form": "HDRSC3", "first": str(first), "count": "50", "qft": "+filterui:imagesize-large"}
    r = session.get(url, params=params, timeout=30)
    if r.status_code != 200:
        print(f"BING_STATUS {r.status_code} {query}")
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    rows: list[dict[str, Any]] = []
    for node in soup.select("a.iusc"):
        raw = node.get("m")
        if not raw:
            continue
        try:
            item = json.loads(html.unescape(raw))
        except Exception:
            continue
        murl = item.get("murl") or item.get("imgurl")
        purl = item.get("purl") or item.get("surl")
        title = item.get("t") or item.get("turl") or node.get("aria-label") or ""
        if murl:
            rows.append({
                "image_url": str(murl), "page_url": str(purl or ""),
                "title": str(title), "query": query,
                "reported_width": item.get("w"), "reported_height": item.get("h"),
            })
    return rows


def discover(game: dict[str, Any], index: int) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    found: dict[str, dict[str, Any]] = {}
    for qidx, query in enumerate(queries_for(game, index)):
        for first in (1, 51):
            try:
                rows = bing_results(session, query, first)
            except requests.RequestException as exc:
                print(f"BING_ERROR {query}: {exc}")
                continue
            for rank, row in enumerate(rows):
                image_url, page_url = row["image_url"], row["page_url"]
                context = " ".join([row["title"], page_url, image_url, query])
                if blocked(image_url) or blocked(page_url):
                    continue
                if not (domain_allowed(page_url, TRUSTED_PAGE_DOMAINS) or domain_allowed(image_url, TRUSTED_IMAGE_DOMAINS)):
                    continue
                if not exact_game_match(game, context):
                    continue
                if reject_context(context):
                    continue
                score = 100.0 - qidx * 2.0 - rank * 0.08
                if gameplay_context(context):
                    score += 25
                if "1080" in norm(context) or "4k" in norm(context) or "hd" in norm(context):
                    score += 12
                if domain_allowed(image_url, TRUSTED_IMAGE_DOMAINS):
                    score += 8
                row["discovery_score"] = score
                old = found.get(image_url)
                if old is None or score > old.get("discovery_score", -999):
                    found[image_url] = row
            time.sleep(0.35 + random.random() * 0.35)
        if len(found) >= 160:
            break
    rows = sorted(found.values(), key=lambda x: x.get("discovery_score", 0), reverse=True)
    print(f"DISCOVERED {len(rows)} trusted candidates for {game['name']}")
    return rows


def download_image(session: requests.Session, row: dict[str, Any]) -> tuple[Image.Image, str] | None:
    urls = [row["image_url"]]
    # Remove common thumbnail resizing query parameters when safe.
    parsed = urlparse(row["image_url"])
    if parsed.query:
        clean = parsed._replace(query="").geturl()
        if clean != row["image_url"]:
            urls.append(clean)
    for url in urls:
        try:
            with session.get(url, timeout=30, stream=True, allow_redirects=True,
                             headers={"Referer": row.get("page_url") or "https://www.bing.com/"}) as r:
                if r.status_code != 200:
                    continue
                ctype = (r.headers.get("Content-Type") or "").lower()
                if "image" not in ctype and not re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", url, re.I):
                    continue
                total = 0
                chunks = []
                for chunk in r.iter_content(64 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        chunks = []
                        break
                    chunks.append(chunk)
                if not chunks:
                    continue
                from io import BytesIO
                image = Image.open(BytesIO(b"".join(chunks)))
                image.load()
                return ImageOps.exif_transpose(image).convert("RGB"), r.url
        except Exception:
            continue
    return None


def edge_metrics(image: Image.Image, third_person: bool) -> dict[str, Any] | None:
    rgb = np.array(image)
    h, w = rgb.shape[:2]
    if w < FALLBACK_W or h < FALLBACK_H:
        return None
    ratio = w / max(h, 1)
    if not 1.18 <= ratio <= 2.35:
        return None
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 11 or brightness > 246 or contrast < 17 or sharpness < 16:
        return None
    black = float((gray < 10).mean())
    white = float((gray > 247).mean())
    if black > 0.55 or white > 0.55:
        return None
    edges = cv2.Canny(gray, 65, 150)
    edge_density = float((edges > 0).mean())
    center = edges[h // 6 : 5 * h // 6, w // 5 : 4 * w // 5]
    center_activity = float((center > 0).mean())
    border = np.concatenate([
        edges[: h // 7].ravel(), edges[-h // 7 :].ravel(),
        edges[:, : w // 10].ravel(), edges[:, -w // 10 :].ravel(),
    ])
    border_activity = float((border > 0).mean())
    menu_penalty = max(0.0, border_activity - edge_density * 1.65)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = float(hsv[:, :, 1].mean())
    hist_gray = cv2.calcHist([gray], [0], None, [64], [0, 256]).flatten()
    p = hist_gray / max(float(hist_gray.sum()), 1.0)
    entropy = float(-(p[p > 0] * np.log2(p[p > 0])).sum())
    resolution_bonus = min(3.5, math.log2(max((w * h) / (960 * 540), 0.5) + 1))
    third_bonus = 8.0 * center_activity if third_person else 3.0 * center_activity
    quality = (1.6 * math.log1p(sharpness) + 0.028 * contrast + 0.012 * saturation
               + 2.1 * entropy + third_bonus + resolution_bonus - 20 * menu_penalty)
    small = cv2.resize(hsv, (192, 108))
    hist = cv2.calcHist([small], [0, 1], None, [16, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    phash = imagehash.phash(image, hash_size=12)
    return {
        "native_width": w, "native_height": h, "quality": quality,
        "brightness": brightness, "contrast": contrast, "sharpness": sharpness,
        "center_activity": center_activity, "menu_penalty": menu_penalty,
        "hist": hist, "phash": phash,
    }


def prepare_output(image: Image.Image, metrics: dict[str, Any]) -> tuple[Image.Image, bool]:
    w, h = image.size
    native_hd = w >= MIN_NATIVE_W and h >= MIN_NATIVE_H
    if native_hd:
        return image, False
    scale = max(1280 / w, 720 / h)
    new_size = (int(round(w * scale)), int(round(h * scale)))
    out = image.resize(new_size, Image.Resampling.LANCZOS)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.0, percent=65, threshold=3))
    out = ImageEnhance.Contrast(out).enhance(1.025)
    return out, True


def select_diverse(rows: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    native = [r for r in rows if not r["upscaled"]]
    fallback = [r for r in rows if r["upscaled"]]
    pool = sorted(native, key=lambda r: r["quality"], reverse=True)
    if len(pool) < target:
        pool.extend(sorted(fallback, key=lambda r: r["quality"], reverse=True))
    unique: list[dict[str, Any]] = []
    for row in pool:
        duplicate = False
        for kept in unique:
            if (row["phash"] - kept["phash"]) <= 10 and float(np.dot(row["hist"], kept["hist"])) > 0.90:
                duplicate = True
                break
        if not duplicate:
            unique.append(row)
    if len(unique) <= target:
        return unique
    qualities = np.array([r["quality"] for r in unique], dtype=np.float32)
    lo, hi = float(qualities.min()), float(qualities.max())
    for r in unique:
        r["qnorm"] = (r["quality"] - lo) / max(hi - lo, 1e-8)
    selected = [max(unique, key=lambda r: r["qnorm"])]
    remaining = [r for r in unique if r is not selected[0]]
    while remaining and len(selected) < target:
        def score(candidate):
            distances = []
            for picked in selected:
                hd = (candidate["phash"] - picked["phash"]) / 144.0
                cd = max(0.0, 1.0 - float(np.dot(candidate["hist"], picked["hist"])))
                distances.append(0.52 * cd + 0.48 * hd)
            native_bonus = 0.05 if not candidate["upscaled"] else 0.0
            return 0.74 * min(distances) + 0.26 * candidate["qnorm"] + native_bonus
        chosen = max(remaining, key=score)
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


def load_font(size: int):
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def make_contact(game: str, rows: list[dict[str, Any]], output: Path) -> None:
    cols, cw, ih, lh, hh = 5, 360, 220, 48, 70
    canvas = Image.new("RGB", (cols * cw, hh + math.ceil(len(rows) / cols) * (ih + lh)), "#101010")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 18), f"{game} — {len(rows)} additional high-resolution gameplay frames", fill="white", font=load_font(24))
    for idx, row in enumerate(rows):
        rr, cc = divmod(idx, cols)
        x, y = cc * cw, hh + rr * (ih + lh)
        image = Image.open(row["output_path"]).convert("RGB")
        image.thumbnail((cw, ih), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cw, ih), "black")
        frame.paste(image, ((cw - image.width) // 2, (ih - image.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + ih, x + cw, y + ih + lh), fill="#1c1c1c")
        tag = "UP" if row["upscaled"] else "NATIVE"
        draw.text((x + 8, y + ih + 7), f"{idx + 16:02d} · {row['native_width']}×{row['native_height']} · {tag}", fill="white", font=load_font(13))
        draw.text((x + 8, y + ih + 26), domain(row["source_page"] or row["source_url"])[:42], fill="#d3d3d3", font=load_font(12))
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
    output_dir = game_dir / "images_hd_extra"
    temp_dir = game_dir / "downloaded_candidates"
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    candidates = discover(game, index)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"})
    accepted: list[dict[str, Any]] = []
    seen_source_urls: set[str] = set()
    for ordinal, candidate in enumerate(candidates[:260], 1):
        result = download_image(session, candidate)
        if not result:
            continue
        image, resolved = result
        if resolved in seen_source_urls:
            continue
        context = " ".join([candidate.get("title", ""), candidate.get("page_url", ""), resolved])
        if reject_context(context) or not exact_game_match(game, context + " " + candidate.get("query", "")):
            continue
        metrics = edge_metrics(image, index in THIRD_PERSON_ORDINALS)
        if not metrics:
            continue
        output_image, upscaled = prepare_output(image, metrics)
        path = temp_dir / f"candidate_{ordinal:04d}.jpg"
        output_image.save(path, quality=94, subsampling=0)
        accepted.append({
            **metrics, "path": path, "upscaled": upscaled,
            "source_url": resolved, "source_page": candidate.get("page_url", ""),
            "source_title": candidate.get("title", ""), "query": candidate.get("query", ""),
            "discovery_score": candidate.get("discovery_score", 0),
        })
        seen_source_urls.add(resolved)
        if len(accepted) >= 120:
            break

    selected = select_diverse(accepted, TARGET)
    if len(selected) < TARGET:
        raise RuntimeError(f"Only {len(selected)} safe distinct gameplay frames selected for {game['name']} from {len(accepted)} accepted downloads")

    images: list[dict[str, Any]] = []
    for number, row in enumerate(selected[:TARGET], 16):
        filename = f"{slug}_{number:03d}_hd_gameplay.jpg"
        destination = output_dir / filename
        shutil.copy2(row["path"], destination)
        images.append({
            "game": game["name"], "filename": filename,
            "relative_path": f"{index:02d}_{slug}/images_hd_extra/{filename}",
            "width": Image.open(destination).width, "height": Image.open(destination).height,
            "native_width": row["native_width"], "native_height": row["native_height"],
            "upscaled": row["upscaled"], "source_url": row["source_url"],
            "source_page": row["source_page"], "source_title": row["source_title"],
            "query": row["query"], "quality_score": round(float(row["quality"]), 4),
            "output_path": str(destination),
        })
    make_contact(game["name"], images, game_dir / f"contact_sheet_{slug}_hd_extra.jpg")
    manifest = {
        "game": game["name"], "ordinal": index, "target_count": TARGET,
        "selected_count": len(images), "discovered_count": len(candidates),
        "accepted_download_count": len(accepted),
        "native_hd_count": sum(not row["upscaled"] for row in images),
        "upscaled_fallback_count": sum(row["upscaled"] for row in images),
        "method": {
            "discovery": "Bing Images large-image index with exact title and trusted-domain filters",
            "source_domains_whitelisted": True, "unrestricted_sources_accepted": False,
            "rejected_content": sorted(REJECT_TERMS),
            "selection": "resolution, technical quality, gameplay-context terms, central action, menu penalty, perceptual deduplication and visual diversity",
            "manual_review_required": True,
        },
        "elapsed_seconds": round(time.time() - started, 2),
        "images": [{k: v for k, v in row.items() if k != "output_path"} for row in images],
    }
    (game_dir / f"manifest_{slug}_hd_extra.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(temp_dir, ignore_errors=True)
    print(json.dumps({"game": game["name"], "selected": len(images), "native_hd": manifest["native_hd_count"], "upscaled": manifest["upscaled_fallback_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
