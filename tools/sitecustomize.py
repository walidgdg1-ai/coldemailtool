"""Automatic trusted-gallery fallback for the temporary AI Prod HD harvester.

Python imports sitecustomize before executing tools/tmp_ai_prod_hd_harvest.py.
This module registers an atexit handler that runs only when the native-video
harvester did not produce 15 images. It searches Bing for exact-title gameplay
screenshots, accepts only whitelisted gaming/editorial domains, validates real
image bytes and resolution, rejects artwork/cover/menu-like candidates, removes
near-duplicates, and writes the same folder/contact-sheet/manifest structure.
"""
from __future__ import annotations

import atexit
import html
import json
import math
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    import cv2
    import imagehash
    import numpy as np
    import requests
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    cv2 = imagehash = np = requests = Image = ImageDraw = ImageFont = None

TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))
MIN_WIDTH = int(os.environ.get("MIN_WIDTH", "960"))
MIN_HEIGHT = int(os.environ.get("MIN_HEIGHT", "540"))
ROOT = Path(os.environ.get("HARVEST_ROOT", "HD_EXTRA_REFERENCE_BANK")).resolve()

GAMES = [
    ("Puppeteer", ["puppeteer ps3", "puppeteer"]),
    ("Gravity Rush", ["gravity rush", "gravity daze"]),
    ("Gravity Rush 2", ["gravity rush 2", "gravity daze 2"]),
    ("Solatorobo Red the Hunter", ["solatorobo", "red the hunter"]),
    ("Kirby's Epic Yarn", ["kirby's epic yarn", "kirbys epic yarn"]),
    ("LittleBigPlanet 2", ["littlebigplanet 2", "little big planet 2", "lbp2"]),
    ("Okami", ["okami hd", "okami"]),
    ("Ghost Trick Phantom Detective", ["ghost trick", "phantom detective"]),
    ("Fantasy Life", ["fantasy life 3ds", "fantasy life"]),
    ("Yo-kai Watch 2", ["yo-kai watch 2", "yokai watch 2"]),
    ("Katamari Damacy", ["katamari damacy reroll", "katamari damacy"]),
    ("We Love Katamari", ["we love katamari reroll", "we love katamari"]),
    ("The World Ends with You", ["the world ends with you final remix", "twewy"]),
    ("Muramasa The Demon Blade", ["muramasa rebirth", "muramasa the demon blade"]),
    ("Viewtiful Joe", ["viewtiful joe"]),
    ("Sly 2 Band of Thieves", ["sly 2 band of thieves", "sly 2"]),
    ("Dark Chronicle Dark Cloud 2", ["dark cloud 2", "dark chronicle"]),
    ("Rogue Galaxy", ["rogue galaxy"]),
    ("Klonoa 2 Lunatea's Veil", ["klonoa 2", "lunatea's veil"]),
    ("Auto Modellista", ["auto modellista"]),
    ("No More Heroes", ["no more heroes hd", "no more heroes wii"]),
    ("Fragile Dreams Farewell Ruins of the Moon", ["fragile dreams", "farewell ruins of the moon"]),
    ("Bravely Default", ["bravely default 3ds", "bravely default"]),
    ("Ever Oasis", ["ever oasis"]),
    ("Monster Hunter Stories", ["monster hunter stories 3ds", "monster hunter stories"]),
    ("Kirby Planet Robobot", ["kirby planet robobot", "planet robobot"]),
    ("Killer7", ["killer7 hd", "killer 7"]),
    ("MadWorld", ["madworld wii", "mad world wii"]),
    ("Hotel Dusk Room 215", ["hotel dusk room 215", "hotel dusk"]),
    ("The Unfinished Swan", ["the unfinished swan"]),
    ("Mirror's Edge", ["mirror's edge 2008", "mirrors edge 2008"]),
]

TRUSTED = {
    "nintendolife.com", "images.nintendolife.com", "pushsquare.com", "images.pushsquare.com",
    "gamespot.com", "gamefaqs.gamespot.com", "static.gamespot.com", "ign.com", "assets-prd.ignimgs.com",
    "mobygames.com", "cdn.mobygames.com", "playstation.com", "gmedia.playstation.com",
    "nintendo.com", "assets.nintendo.com", "xbox.com", "store-images.s-microsoft.com",
    "steamcommunity.com", "steamuserimages-a.akamaihd.net", "steamstatic.com", "cdn.akamai.steamstatic.com",
    "rpgsite.net", "images.rpgsite.net", "rpgfan.com", "rpgfan.com", "gematsu.com", "image.gematsu.com",
    "siliconera.com", "www.siliconera.com", "eurogamer.net", "assetsio.reedpopcdn.com",
    "vg247.com", "assetsio.reedpopcdn.com", "gamepressure.com", "images.gamepressure.com",
    "neoseeker.com", "cdn.neoseeker.com", "hardcoregamer.com", "gamingtrend.com",
    "destructoid.com", "www.destructoid.com", "dualshockers.com", "static0.gamerantimages.com",
    "thegamesdb.net", "cdn.thegamesdb.net", "giantbomb.com", "www.giantbomb.com",
    "wikimedia.org", "upload.wikimedia.org", "fandom.com", "static.wikia.nocookie.net",
}

BAD_URL_WORDS = {
    "cover", "boxart", "box-art", "poster", "logo", "icon", "avatar", "banner", "header",
    "wallpaper", "fanart", "fan-art", "concept-art", "concept_art", "keyart", "key-art",
    "character-art", "render-png", "transparent", "amiibo", "merch", "figurine", "cosplay",
    "review-score", "metacritic", "trophy", "achievement", "soundtrack", "album", "map-only",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()).strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(text)).strip("_")


def domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""


def trusted(url: str) -> bool:
    d = domain(url)
    return any(d == x or d.endswith("." + x) for x in TRUSTED)


def alias_match(text: str, aliases: list[str]) -> bool:
    n = norm(text)
    for alias in aliases:
        a = norm(alias)
        if a in n:
            return True
        tokens = [t for t in re.findall(r"[a-z0-9]+", a) if len(t) > 2]
        if tokens and all(t in n for t in tokens):
            return True
    return False


def bing_results(query: str, session) -> list[dict]:
    url = "https://www.bing.com/images/search?q=" + quote(query) + "&form=HDRSC2&first=1&count=150"
    try:
        r = session.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            print("FALLBACK_BING_STATUS", r.status_code, query, flush=True)
            return []
        out = []
        for raw in re.findall(r'<a[^>]+class="[^"]*iusc[^"]*"[^>]+m="([^"]+)"', r.text):
            try:
                item = json.loads(html.unescape(raw))
            except Exception:
                continue
            murl = item.get("murl") or item.get("m")
            purl = item.get("purl") or item.get("p")
            title = item.get("t") or item.get("desc") or ""
            if murl and purl:
                out.append({"image_url": murl, "page_url": purl, "title": title, "query": query})
        print("FALLBACK_BING_RESULTS", len(out), query, flush=True)
        return out
    except Exception as exc:
        print("FALLBACK_BING_ERROR", repr(exc), query, flush=True)
        return []


def download_candidate(item: dict, path: Path, session) -> bool:
    try:
        r = session.get(item["image_url"], headers={**HEADERS, "Referer": item["page_url"]}, timeout=25, stream=True)
        ctype = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200 or "image" not in ctype:
            return False
        data = bytearray()
        for chunk in r.iter_content(65536):
            data.extend(chunk)
            if len(data) > 18_000_000:
                return False
        if len(data) < 45_000:
            return False
        path.write_bytes(data)
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        path.unlink(missing_ok=True)
        return False


def image_metrics(path: Path):
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    if w < MIN_WIDTH or h < MIN_HEIGHT:
        return None
    ratio = w / max(h, 1)
    if ratio < 0.72 or ratio > 2.45:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 12 or brightness > 245 or contrast < 17 or sharpness < 20:
        return None
    if float((gray < 10).mean()) > .62 or float((gray > 248).mean()) > .62:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    edges = cv2.Canny(gray, 65, 155)
    edge_density = float((edges > 0).mean())
    center = edges[h // 6: 5 * h // 6, w // 6: 5 * w // 6]
    center_activity = float((center > 0).mean())
    strip = np.concatenate([edges[: max(1, h // 7)].ravel(), edges[-max(1, h // 7):].ravel()])
    strip_edges = float((strip > 0).mean())
    menu_penalty = max(0.0, strip_edges - edge_density * 1.8)
    sat = float(hsv[:, :, 1].mean())
    score = 1.9 * math.log1p(sharpness) + .03 * contrast + .01 * sat + 10 * center_activity - 20 * menu_penalty
    small = cv2.resize(hsv, (192, 108))
    hist = cv2.calcHist([small], [0, 1], None, [16, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    phash = imagehash.phash(Image.open(path).convert("RGB"), hash_size=12)
    return {"path": path, "width": w, "height": h, "score": score, "sharpness": sharpness,
            "brightness": brightness, "center_activity": center_activity, "menu_penalty": menu_penalty,
            "hist": hist, "phash": phash}


def select(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda x: x["score"], reverse=True)
    unique = []
    for row in rows:
        dup = False
        for kept in unique:
            if row["phash"] - kept["phash"] <= 10 and float(np.dot(row["hist"], kept["hist"])) > .90:
                dup = True
                break
        if not dup:
            unique.append(row)
    if len(unique) <= TARGET:
        return unique
    scores = np.array([r["score"] for r in unique], dtype=np.float32)
    lo, hi = float(scores.min()), float(scores.max())
    for row in unique:
        row["q"] = (row["score"] - lo) / max(hi - lo, 1e-8)
    chosen = [max(unique, key=lambda r: r["q"])]
    remaining = [r for r in unique if r is not chosen[0]]
    while remaining and len(chosen) < TARGET:
        def rank(c):
            distances = []
            for p in chosen:
                hd = (c["phash"] - p["phash"]) / 144.0
                hs = max(0.0, 1.0 - float(np.dot(c["hist"], p["hist"])))
                distances.append(.55 * hs + .45 * hd)
            return .72 * min(distances) + .28 * c["q"]
        best = max(remaining, key=rank)
        chosen.append(best)
        remaining.remove(best)
    return chosen


def font(size: int):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def contact_sheet(game: str, rows: list[dict], out: Path):
    cols, cw, ih, lh, header = 5, 360, 220, 42, 70
    canvas = Image.new("RGB", (cols * cw, header + math.ceil(len(rows) / cols) * (ih + lh)), "#0d0d0d")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 18), f"{game} — {len(rows)} trusted-gallery HD gameplay frames", fill="white", font=font(24))
    for i, row in enumerate(rows):
        rr, cc = divmod(i, cols)
        x, y = cc * cw, header + rr * (ih + lh)
        im = Image.open(row["output_path"]).convert("RGB")
        im.thumbnail((cw, ih), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cw, ih), "black")
        frame.paste(im, ((cw - im.width) // 2, (ih - im.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + ih, x + cw, y + ih + lh), fill="#1b1b1b")
        draw.text((x + 8, y + ih + 10), f"{i + 16:02d} · {row['width']}×{row['height']}", fill="white", font=font(14))
    canvas.save(out, quality=92)


def fallback():
    if None in (cv2, imagehash, np, requests, Image):
        return
    try:
        index = int(os.environ.get("GAME_INDEX", "0"))
    except Exception:
        return
    if not 1 <= index <= len(GAMES):
        return
    game, aliases = GAMES[index - 1]
    slug = slugify(game)
    game_dir = ROOT / f"{index:02d}_{slug}"
    image_dir = game_dir / "images_hd_extra"
    existing = list(image_dir.glob("*")) if image_dir.exists() else []
    if len(existing) >= TARGET:
        print("FALLBACK_SKIP_NATIVE_COMPLETE", game, len(existing), flush=True)
        return
    print("FALLBACK_START", game, "native_count", len(existing), flush=True)
    shutil.rmtree(game_dir, ignore_errors=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    cand_dir = game_dir / "trusted_candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    source_groups = [
        "site:nintendolife.com OR site:pushsquare.com OR site:gamespot.com OR site:ign.com",
        "site:mobygames.com OR site:gamefaqs.gamespot.com OR site:neoseeker.com",
        "site:rpgsite.net OR site:rpgfan.com OR site:gematsu.com OR site:siliconera.com",
        "site:steamcommunity.com OR site:playstation.com OR site:nintendo.com OR site:xbox.com",
        "site:eurogamer.net OR site:vg247.com OR site:gamepressure.com OR site:giantbomb.com",
    ]
    items = []
    seen_urls = set()
    for alias in aliases[:2]:
        for group in source_groups:
            q = f'"{alias}" gameplay screenshot HD {group}'
            for item in bing_results(q, session):
                key = item["image_url"].split("?")[0]
                text = " ".join([item.get("title", ""), item.get("page_url", ""), item.get("image_url", "")])
                if key in seen_urls or not trusted(item["page_url"]):
                    continue
                if not alias_match(text, aliases):
                    continue
                lower = norm(text)
                if any(word in lower for word in BAD_URL_WORDS):
                    continue
                seen_urls.add(key)
                items.append(item)
            if len(items) >= 180:
                break
        if len(items) >= 180:
            break
    print("FALLBACK_TRUSTED_ITEMS", game, len(items), flush=True)
    rows = []
    metadata = {}
    for idx, item in enumerate(items[:240], 1):
        suffix = Path(urlparse(item["image_url"]).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".img"
        path = cand_dir / f"candidate_{idx:04d}{suffix}"
        if not download_candidate(item, path, session):
            continue
        row = image_metrics(path)
        if not row:
            path.unlink(missing_ok=True)
            continue
        metadata[str(path)] = item
        rows.append(row)
        if len(rows) >= 90:
            break
    picked = select(rows)
    print("FALLBACK_VALID", game, len(rows), "SELECTED", len(picked), flush=True)
    if len(picked) < TARGET:
        # Keep the honest partial result; package summary will flag it.
        target_rows = picked
    else:
        target_rows = picked[:TARGET]
    out_rows = []
    for number, row in enumerate(target_rows, 16):
        filename = f"{slug}_{number:03d}_hd_gameplay.jpg"
        dst = image_dir / filename
        with Image.open(row["path"]) as im:
            im.convert("RGB").save(dst, "JPEG", quality=95, optimize=True)
        item = metadata.get(str(row["path"]), {})
        rec = {
            "game": game, "filename": filename,
            "relative_path": f"{index:02d}_{slug}/images_hd_extra/{filename}",
            "width": row["width"], "height": row["height"],
            "quality_score": round(float(row["score"]), 4),
            "sharpness": round(float(row["sharpness"]), 3),
            "brightness": round(float(row["brightness"]), 3),
            "center_activity": round(float(row["center_activity"]), 5),
            "menu_penalty": round(float(row["menu_penalty"]), 5),
            "source_url": item.get("page_url"), "image_url": item.get("image_url"),
            "source_domain": domain(item.get("page_url", "")), "query": item.get("query"),
            "output_path": str(dst),
        }
        out_rows.append(rec)
    if out_rows:
        contact_sheet(game, out_rows, game_dir / f"contact_sheet_{slug}_hd_extra.jpg")
    manifest = {
        "game": game, "ordinal": index, "target_count": TARGET, "selected_count": len(out_rows),
        "minimum_resolution": f"{MIN_WIDTH}x{MIN_HEIGHT}",
        "method": "exact-title Bing image discovery restricted to trusted gaming/editorial domains",
        "native_video_harvest_incomplete": True,
        "manual_review_required": True,
        "images": [{k: v for k, v in r.items() if k != "output_path"} for r in out_rows],
        "generated_at_unix": time.time(),
    }
    (game_dir / f"manifest_{slug}_hd_extra.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(cand_dir, ignore_errors=True)


atexit.register(fallback)
