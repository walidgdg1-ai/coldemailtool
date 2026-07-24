#!/usr/bin/env python3
"""Build 15 additional gameplay references per game with a safe hybrid method.

Priority order:
1. Exact-title trusted galleries and review pages, preserving native HD files.
2. YouTube's automatic in-video frames (sd1/sd2/sd3 or hq fallbacks) from
   title-matched gameplay uploads, never uploader-designed thumbnails.

All candidates pass exact-title checks, technical screening, menu/artwork
rejection, perceptual deduplication and visual-diversity selection. Low-resolution
in-video frames are explicitly marked and upscaled for production convenience.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import harvest_game_screenshots as base
import harvest_hd_web_frames as h
import harvest_youtube_auto_frames as yt
import run_hd_images_plus_pages as combined

ROOT = Path(os.environ.get("HARVEST_ROOT", "HD_EXTRA_REFERENCE_BANK")).resolve()
TARGET = int(os.environ.get("TARGET_PER_GAME", "15"))
YT_MAX_VIDEOS = int(os.environ.get("YT_MAX_VIDEOS", "36"))


def font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def upscale_video_frame(image: Image.Image) -> Image.Image:
    image = yt.crop_letterbox(ImageOps.exif_transpose(image).convert("RGB"))
    # Preserve the authentic gameplay aspect ratio. Make the longest practical
    # production dimension at least 1280×720-equivalent without inventing crop.
    scale = max(1280 / image.width, 720 / image.height)
    output = image.resize(
        (int(round(image.width * scale)), int(round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    output = output.filter(ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=3))
    output = ImageEnhance.Contrast(output).enhance(1.02)
    return output


def gallery_candidates(game: dict[str, Any], index: int, temp_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    session = h.requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    discovered = h.discover(game, index)
    seen_urls: set[str] = set()
    for ordinal, candidate in enumerate(discovered[:320], 1):
        result = h.download_image(session, candidate)
        if not result:
            continue
        image, resolved = result
        if resolved in seen_urls:
            continue
        context = " ".join([
            candidate.get("title", ""), candidate.get("page_url", ""),
            resolved, candidate.get("query", ""),
        ])
        if h.reject_context(context) or not h.exact_game_match(game, context):
            continue
        metrics = h.edge_metrics(image, index in h.THIRD_PERSON_ORDINALS)
        if not metrics:
            continue
        prepared, upscaled = h.prepare_output(image, metrics)
        path = temp_dir / f"gallery_{ordinal:04d}.jpg"
        prepared.save(path, quality=95, subsampling=0)
        rows.append({
            **metrics,
            "path": path,
            "upscaled": upscaled,
            "source_kind": "trusted_gallery_native" if not upscaled else "trusted_gallery_upscaled",
            "source_url": resolved,
            "source_page": candidate.get("page_url", ""),
            "source_title": candidate.get("title", ""),
            "query": candidate.get("query", ""),
            "video_id": None,
            "video_title": None,
            "video_channel": None,
            "position": None,
        })
        seen_urls.add(resolved)
        if len(rows) >= 140:
            break
    print(f"HYBRID_GALLERY_ACCEPTED {len(rows)} {game['name']}")
    return rows


def youtube_candidates(game: dict[str, Any], index: int, temp_dir: Path) -> list[dict[str, Any]]:
    yt.MAX_VIDEOS = YT_MAX_VIDEOS
    yt.SEARCH_RESULTS = max(80, YT_MAX_VIDEOS * 3)
    videos = yt.search_videos(game)
    session = yt.requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    rows: list[dict[str, Any]] = []
    for video_rank, video in enumerate(videos, 1):
        video_id = str(video.get("id") or video.get("url") or "")
        for position in (1, 2, 3):
            fetched = yt.get_image(session, video_id, position)
            if not fetched:
                continue
            image, source_url = fetched
            prepared = upscale_video_frame(image)
            path = temp_dir / f"youtube_{video_rank:03d}_{position}.jpg"
            prepared.save(path, quality=95, subsampling=0)
            metrics = h.edge_metrics(prepared, index in h.THIRD_PERSON_ORDINALS)
            if not metrics:
                path.unlink(missing_ok=True)
                continue
            rows.append({
                **metrics,
                "path": path,
                "upscaled": True,
                "source_kind": "youtube_auto_generated_in_video_frame_upscaled",
                "source_url": source_url,
                "source_page": video.get("webpage_url", ""),
                "source_title": video.get("title", ""),
                "query": game.get("query", ""),
                "video_id": video_id,
                "video_title": video.get("title"),
                "video_channel": video.get("channel") or video.get("uploader"),
                "position": position,
            })
        if len(rows) >= 105:
            break
    print(f"HYBRID_YOUTUBE_ACCEPTED {len(rows)} {game['name']} from {len(videos)} videos")
    return rows


def make_contact(game: str, rows: list[dict[str, Any]], output: Path) -> None:
    cols, cell_w, image_h, label_h, header_h = 5, 360, 220, 54, 72
    canvas = Image.new(
        "RGB",
        (cols * cell_w, header_h + math.ceil(len(rows) / cols) * (image_h + label_h)),
        "#101010",
    )
    draw = ImageDraw.Draw(canvas)
    native_count = sum(row["source_kind"] == "trusted_gallery_native" for row in rows)
    draw.text(
        (18, 16),
        f"{game} — 15 additional frames · {native_count} native HD · {len(rows) - native_count} marked fallback",
        fill="white",
        font=font(23),
    )
    for idx, row in enumerate(rows):
        rr, cc = divmod(idx, cols)
        x, y = cc * cell_w, header_h + rr * (image_h + label_h)
        image = Image.open(row["output_path"]).convert("RGB")
        image.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, image_h), "black")
        frame.paste(image, ((cell_w - image.width) // 2, (image_h - image.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + image_h, x + cell_w, y + image_h + label_h), fill="#1c1c1c")
        kind = "NATIVE" if row["source_kind"] == "trusted_gallery_native" else "UP"
        domain = h.domain(row.get("source_page") or row.get("source_url") or "")
        draw.text(
            (x + 8, y + image_h + 7),
            f"{idx + 16:02d} · {row['native_width']}×{row['native_height']} · {kind}",
            fill="white",
            font=font(13),
        )
        draw.text(
            (x + 8, y + image_h + 29),
            domain[:45],
            fill="#d0d0d0",
            font=font(12),
        )
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
    temp_dir = game_dir / "hybrid_candidates"
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    gallery_rows: list[dict[str, Any]] = []
    gallery_error: str | None = None
    try:
        gallery_rows = gallery_candidates(game, index, temp_dir)
    except Exception as exc:
        gallery_error = repr(exc)
        print(f"HYBRID_GALLERY_WARNING {game['name']}: {exc}")

    # Always collect video-frame candidates: even games with 15 gallery shots
    # benefit from a larger diversity pool before final selection.
    video_rows: list[dict[str, Any]] = []
    video_error: str | None = None
    try:
        video_rows = youtube_candidates(game, index, temp_dir)
    except Exception as exc:
        video_error = repr(exc)
        print(f"HYBRID_YOUTUBE_WARNING {game['name']}: {exc}")

    all_rows = gallery_rows + video_rows
    selected = h.select_diverse(all_rows, TARGET)
    if len(selected) < TARGET:
        raise RuntimeError(
            f"Only {len(selected)} safe distinct frames selected for {game['name']} "
            f"from {len(gallery_rows)} gallery and {len(video_rows)} video candidates"
        )

    images: list[dict[str, Any]] = []
    for number, row in enumerate(selected[:TARGET], 16):
        filename = f"{slug}_{number:03d}_hd_gameplay.jpg"
        destination = output_dir / filename
        shutil.copy2(row["path"], destination)
        final_image = Image.open(destination)
        images.append({
            "game": game["name"],
            "filename": filename,
            "relative_path": f"{index:02d}_{slug}/images_hd_extra/{filename}",
            "width": final_image.width,
            "height": final_image.height,
            "native_width": row["native_width"],
            "native_height": row["native_height"],
            "upscaled": bool(row["upscaled"]),
            "source_kind": row["source_kind"],
            "source_url": row["source_url"],
            "source_page": row["source_page"],
            "source_title": row["source_title"],
            "query": row["query"],
            "video_id": row.get("video_id"),
            "video_title": row.get("video_title"),
            "video_channel": row.get("video_channel"),
            "video_auto_frame_position": row.get("position"),
            "quality_score": round(float(row["quality"]), 4),
            "output_path": str(destination),
        })

    make_contact(game["name"], images, game_dir / f"contact_sheet_{slug}_hd_extra.jpg")
    source_counts: dict[str, int] = {}
    for row in images:
        source_counts[row["source_kind"]] = source_counts.get(row["source_kind"], 0) + 1
    manifest = {
        "game": game["name"],
        "ordinal": index,
        "target_count": TARGET,
        "selected_count": len(images),
        "candidate_counts": {
            "trusted_gallery": len(gallery_rows),
            "youtube_auto_generated": len(video_rows),
            "total": len(all_rows),
        },
        "selected_source_counts": source_counts,
        "native_hd_count": source_counts.get("trusted_gallery_native", 0),
        "marked_upscaled_fallback_count": len(images) - source_counts.get("trusted_gallery_native", 0),
        "gallery_error": gallery_error,
        "youtube_error": video_error,
        "method": {
            "priority": "native trusted gallery screenshots first; auto-generated in-video frames as fallback",
            "custom_youtube_thumbnails_used": False,
            "unrestricted_sources_accepted": False,
            "exact_game_title_validation": True,
            "technical_and_perceptual_deduplication": True,
            "manual_review_required": True,
        },
        "elapsed_seconds": round(time.time() - started, 2),
        "images": [{k: v for k, v in row.items() if k != "output_path"} for row in images],
    }
    (game_dir / f"manifest_{slug}_hd_extra.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.rmtree(temp_dir, ignore_errors=True)
    print(json.dumps({
        "game": game["name"],
        "selected": len(images),
        "source_counts": source_counts,
        "candidate_counts": manifest["candidate_counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
