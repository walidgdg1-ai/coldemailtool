#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path("HD_EXTRA_REFERENCE_BANK")
ROOT.mkdir(parents=True, exist_ok=True)
TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))
IDS = json.loads(Path("tools/yt_extra_ids.json").read_text(encoding="utf-8"))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Referer": "https://www.youtube.com/",
}
BAD_IDS = {"3": {"saGarhZXS7Y"}}
POSITIONS = [
    ("maxres1.jpg", 25, "maxres"),
    ("maxres2.jpg", 50, "maxres"),
    ("maxres3.jpg", 75, "maxres"),
    ("sd1.jpg", 25, "sd"),
    ("sd2.jpg", 50, "sd"),
    ("sd3.jpg", 75, "sd"),
    ("hq1.jpg", 25, "hq"),
    ("hq2.jpg", 50, "hq"),
    ("hq3.jpg", 75, "hq"),
]
GALLERY_FALLBACK = {
    8: ("08_ghost_trick_phantom_detective", "Ghost Trick Phantom Detective"),
    9: ("09_fantasy_life", "Fantasy Life"),
    20: ("20_auto_modellista", "Auto Modellista"),
}


def font(size: int):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def metrics(path: Path) -> dict[str, Any] | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    if w < 320 or h < 180:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 10 or brightness > 247 or contrast < 14 or sharpness < 10:
        return None
    if float((gray < 10).mean()) > 0.68 or float((gray > 248).mean()) > 0.68:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    edges = cv2.Canny(gray, 55, 145)
    edge_density = float((edges > 0).mean())
    center = edges[h // 6 : 5 * h // 6, w // 6 : 5 * w // 6]
    center_activity = float((center > 0).mean())
    top_bottom = np.concatenate([
        edges[: max(1, h // 7)].ravel(),
        edges[-max(1, h // 7) :].ravel(),
    ])
    menu_penalty = max(0.0, float((top_bottom > 0).mean()) - edge_density * 1.9)
    sat = float(hsv[:, :, 1].mean())
    score = 1.8 * math.log1p(sharpness) + 0.03 * contrast + 0.009 * sat + 9 * center_activity - 16 * menu_penalty
    small = cv2.resize(hsv, (192, 108))
    hist = cv2.calcHist([small], [0, 1], None, [16, 8], [0, 180, 0, 256]).flatten().astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    return {
        "path": path,
        "source_width": w,
        "source_height": h,
        "score": score,
        "sharpness": sharpness,
        "brightness": brightness,
        "center_activity": center_activity,
        "menu_penalty": menu_penalty,
        "hist": hist,
        "phash": imagehash.phash(Image.open(path).convert("RGB"), hash_size=12),
    }


def choose_diverse(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    rows.sort(key=lambda x: x["score"], reverse=True)
    unique: list[dict[str, Any]] = []
    for row in rows:
        duplicate = False
        for kept in unique:
            if row["phash"] - kept["phash"] <= 9 and float(np.dot(row["hist"], kept["hist"])) > 0.91:
                duplicate = True
                break
        if not duplicate:
            unique.append(row)
    if len(unique) <= count:
        return unique
    vals = np.array([r["score"] for r in unique], dtype=np.float32)
    lo, hi = float(vals.min()), float(vals.max())
    for r in unique:
        r["qnorm"] = (r["score"] - lo) / max(hi - lo, 1e-8)
    chosen = [max(unique, key=lambda r: r["qnorm"])]
    remaining = [r for r in unique if r is not chosen[0]]
    while remaining and len(chosen) < count:
        def rank(c):
            distances = []
            for p in chosen:
                hd = (c["phash"] - p["phash"]) / 144.0
                hs = max(0.0, 1.0 - float(np.dot(c["hist"], p["hist"])))
                distances.append(0.55 * hs + 0.45 * hd)
            return 0.74 * min(distances) + 0.26 * c["qnorm"]
        best = max(remaining, key=rank)
        chosen.append(best)
        remaining.remove(best)
    return chosen


def upscale_and_save(src: Path, dst: Path) -> tuple[int, int, bool]:
    with Image.open(src) as im:
        im = im.convert("RGB")
        sw, sh = im.size
        scale = max(1280 / sw, 720 / sh, 1.0)
        ow, oh = int(round(sw * scale)), int(round(sh * scale))
        if scale > 1.0:
            im = im.resize((ow, oh), Image.Resampling.LANCZOS)
        im.save(dst, "JPEG", quality=95, optimize=True)
        return ow, oh, scale > 1.0


def contact_sheet(game: str, rows: list[dict[str, Any]], out: Path) -> None:
    cols, cw, ih, lh, header = 5, 360, 220, 48, 72
    canvas = Image.new("RGB", (cols * cw, header + math.ceil(len(rows) / cols) * (ih + lh)), "#0c0c0c")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 19), f"{game} — {len(rows)} additional gameplay frames", fill="white", font=font(24))
    for i, row in enumerate(rows):
        rr, cc = divmod(i, cols)
        x, y = cc * cw, header + rr * (ih + lh)
        im = Image.open(row["output_path"]).convert("RGB")
        im.thumbnail((cw, ih), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cw, ih), "black")
        frame.paste(im, ((cw - im.width) // 2, (ih - im.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + ih, x + cw, y + ih + lh), fill="#1b1b1b")
        label = f"{i + 16:02d} · {row['output_width']}×{row['output_height']} · {row['tier']}"
        draw.text((x + 7, y + ih + 12), label, fill="white", font=font(13))
    canvas.save(out, quality=92)


def fetch_image(session: requests.Session, url: str, path: Path) -> bool:
    try:
        r = session.get(url, headers=HEADERS, timeout=22)
        ctype = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200 or "image" not in ctype or len(r.content) < 12_000:
            return False
        path.write_bytes(r.content)
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        path.unlink(missing_ok=True)
        return False


def harvest_youtube(index: int, spec: dict[str, Any]) -> dict[str, Any]:
    folder = spec["folder"]
    game = spec["game"]
    game_dir = ROOT / folder
    image_dir = game_dir / "images_hd_extra"
    candidate_dir = game_dir / "yt_candidates"
    shutil.rmtree(game_dir, ignore_errors=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    candidates: list[dict[str, Any]] = []
    attempted = 0
    for video_id in spec["ids"]:
        if video_id in BAD_IDS.get(str(index), set()):
            continue
        for file_name, percent, tier in POSITIONS:
            attempted += 1
            url = f"https://i.ytimg.com/vi/{video_id}/{file_name}"
            path = candidate_dir / f"{video_id}_{file_name}"
            if not fetch_image(session, url, path):
                continue
            row = metrics(path)
            if not row:
                path.unlink(missing_ok=True)
                continue
            row.update({
                "video_id": video_id,
                "source_url": url,
                "position_percent": percent,
                "tier": tier,
            })
            candidates.append(row)
        if len(candidates) >= 60:
            break

    picked = choose_diverse(candidates, TARGET)
    out_rows: list[dict[str, Any]] = []
    for number, row in enumerate(picked[:TARGET], 16):
        filename = f"{folder[3:]}_{number:03d}_hd_gameplay.jpg"
        dst = image_dir / filename
        ow, oh, upscaled = upscale_and_save(row["path"], dst)
        out_rows.append({
            "game": game,
            "filename": filename,
            "relative_path": f"{folder}/images_hd_extra/{filename}",
            "video_id": row["video_id"],
            "source_url": row["source_url"],
            "position_percent": row["position_percent"],
            "tier": row["tier"],
            "source_width": row["source_width"],
            "source_height": row["source_height"],
            "output_width": ow,
            "output_height": oh,
            "upscaled_to_large_resolution": upscaled,
            "quality_score": round(float(row["score"]), 4),
            "output_path": str(dst),
        })
    if out_rows:
        contact_sheet(game, out_rows, game_dir / f"contact_sheet_{folder[3:]}_hd_extra.jpg")
    manifest = {
        "game": game,
        "ordinal": index,
        "target_count": TARGET,
        "selected_count": len(out_rows),
        "candidate_count": len(candidates),
        "urls_attempted": attempted,
        "method": "title-validated YouTube videos; automatic 25/50/75 percent frames only; no uploader custom thumbnails",
        "output_policy": "preserve aspect ratio; upscale with Lanczos only when source is below 1280x720",
        "manual_review_required": True,
        "images": [{k: v for k, v in r.items() if k != "output_path"} for r in out_rows],
    }
    (game_dir / f"manifest_{folder[3:]}_hd_extra.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(candidate_dir, ignore_errors=True)
    return {"index": index, "folder": folder, "game": game, "status": "complete" if len(out_rows) == TARGET else "partial", "count": len(out_rows), "method": "youtube_auto_frames"}


def run_gallery_fallback(index: int) -> dict[str, Any]:
    folder, game = GALLERY_FALLBACK[index]
    env = os.environ.copy()
    env.update({
        "GAME_INDEX": str(index),
        "TARGET_PER_GAME": str(TARGET),
        "MIN_WIDTH": "960",
        "MIN_HEIGHT": "540",
        "PYTHONPATH": "tools",
    })
    code = "import sitecustomize; sitecustomize.atexit.unregister(sitecustomize.fallback); sitecustomize.fallback()"
    try:
        proc = subprocess.run([sys.executable, "-c", code], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800, check=False)
        Path(f"gallery_harvest_{index:02d}.log").write_text(proc.stdout or "", encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        text = exc.stdout if isinstance(exc.stdout, str) else ""
        Path(f"gallery_harvest_{index:02d}.log").write_text(text + "\nTIMEOUT\n", encoding="utf-8")
    game_dir = ROOT / folder
    count = len(list((game_dir / "images_hd_extra").glob("*"))) if game_dir.exists() else 0
    return {"index": index, "folder": folder, "game": game, "status": "complete" if count == TARGET else "partial", "count": count, "method": "trusted_gallery"}


def run_game(index: int) -> dict[str, Any]:
    try:
        if str(index) in IDS:
            return harvest_youtube(index, IDS[str(index)])
        return run_gallery_fallback(index)
    except Exception as exc:
        Path(f"gallery_harvest_{index:02d}.log").write_text(f"FATAL {type(exc).__name__}: {exc}\n", encoding="utf-8")
        folder, game = GALLERY_FALLBACK.get(index, (f"{index:02d}_unknown", "Unknown"))
        return {"index": index, "folder": folder, "game": game, "status": "error", "count": 0, "error": repr(exc)}


def main() -> int:
    os.environ["GAME_INDEX"] = "0"
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(run_game, index): index for index in range(1, 32)}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    results.sort(key=lambda row: row["index"])
    summary = {
        "completed_games": sum(row["count"] == TARGET for row in results),
        "games_with_any_images": sum(row["count"] > 0 for row in results),
        "total_selected_images": sum(row["count"] for row in results),
        "games": results,
    }
    Path("HD_PARALLEL_GALLERY_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
