#!/usr/bin/env python3
"""Run the hybrid harvester with gallery-first, gameplay-only selection locks."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import cv2
import numpy as np

import run_hd_hybrid as hybrid


_original_youtube_candidates = hybrid.youtube_candidates
_original_select_diverse = hybrid.h.select_diverse


def video_gameplay_metrics(path) -> dict[str, float] | None:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    edges = cv2.Canny(gray, 70, 150)
    edge_density = float((edges > 0).mean())

    # Dialogue boxes and menu cards are usually large bright, low-saturation
    # rectangles. Small HUD elements remain below these area/shape thresholds.
    white = ((hsv[:, :, 1] < 48) & (hsv[:, :, 2] > 205)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    dialogue_area = 0.0
    menu_card_area = 0.0
    for component in range(1, count):
        x, y, cw, ch, area = stats[component]
        ratio = float(area) / float(w * h)
        if ratio < 0.009:
            continue
        aspect = cw / max(ch, 1)
        rectangular_fill = area / max(float(cw * ch), 1.0)
        if rectangular_fill < 0.60:
            continue
        if cw >= w * 0.18 and ch <= h * 0.34 and aspect >= 1.65:
            dialogue_area += ratio
        if cw >= w * 0.26 and ch >= h * 0.12:
            menu_card_area += ratio

    white_ratio = float(white.mean())
    mean = cv2.blur(gray.astype(np.float32), (15, 15))
    mean_sq = cv2.blur((gray.astype(np.float32) ** 2), (15, 15))
    local_var = np.maximum(0.0, mean_sq - mean ** 2)
    flat_ratio = float((local_var < 18.0).mean())

    center = edges[h // 6 : 5 * h // 6, w // 6 : 5 * w // 6]
    center_activity = float((center > 0).mean()) if center.size else 0.0
    top_bottom = np.concatenate([edges[: h // 5].ravel(), edges[-h // 5 :].ravel()])
    strip_activity = float((top_bottom > 0).mean()) if top_bottom.size else 0.0

    # Hard rejects: comic dialogue pages, maps/menus, promotional title cards.
    reject = False
    if dialogue_area >= 0.055:
        reject = True
    if menu_card_area >= 0.18 or white_ratio >= 0.30:
        reject = True
    if flat_ratio >= 0.73 and center_activity < 0.060:
        reject = True
    if flat_ratio >= 0.62 and strip_activity > edge_density * 1.85:
        reject = True

    score = (
        35.0 * center_activity
        + 6.0 * edge_density
        - 90.0 * dialogue_area
        - 36.0 * menu_card_area
        - 8.0 * white_ratio
        - 5.0 * flat_ratio
        - 8.0 * max(0.0, strip_activity - edge_density * 1.4)
    )
    return {
        "reject": 1.0 if reject else 0.0,
        "gameplay_score": score,
        "dialogue_area": dialogue_area,
        "menu_card_area": menu_card_area,
        "white_ratio": white_ratio,
        "flat_ratio": flat_ratio,
        "center_activity_v2": center_activity,
    }


def filtered_youtube_candidates(game: dict[str, Any], index: int, temp_dir):
    rows = _original_youtube_candidates(game, index, temp_dir)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        metrics = video_gameplay_metrics(row["path"])
        if not metrics:
            continue
        row.update(metrics)
        if metrics["reject"]:
            continue
        # Blend original technical quality with the gameplay-likelihood score.
        row["quality"] = float(row["quality"]) + float(metrics["gameplay_score"])
        grouped[str(row.get("video_id") or row["source_url"])].append(row)

    # Maximum one frame per video. This prevents a single cutscene-heavy upload
    # from dominating the final bank and gives broader scene/location coverage.
    selected_rows = []
    for video_id, video_rows in grouped.items():
        best = max(video_rows, key=lambda row: row["quality"])
        selected_rows.append(best)
    selected_rows.sort(key=lambda row: row["quality"], reverse=True)
    print(
        f"HYBRID_YOUTUBE_GAMEPLAY_FILTER {len(rows)} -> {len(selected_rows)} "
        f"one-per-video candidates for {game['name']}"
    )
    return selected_rows


def is_duplicate(candidate: dict[str, Any], kept: dict[str, Any]) -> bool:
    hash_distance = candidate["phash"] - kept["phash"]
    hist_similarity = float(np.dot(candidate["hist"], kept["hist"]))
    return hash_distance <= 9 and hist_similarity > 0.91


def gallery_first_select(rows: list[dict[str, Any]], target: int):
    gallery = [row for row in rows if row.get("source_kind", "").startswith("trusted_gallery")]
    video = [row for row in rows if row.get("source_kind", "").startswith("youtube_auto")]

    # Keep as many distinct exact-gallery screenshots as possible—even when an
    # older game requires a marked upscale—before admitting any video fallback.
    selected = list(_original_select_diverse(gallery, target))
    if len(selected) >= target:
        return selected[:target]

    video_ranked = list(_original_select_diverse(video, max(target * 3, 30)))
    for candidate in video_ranked:
        if any(is_duplicate(candidate, kept) for kept in selected):
            continue
        selected.append(candidate)
        if len(selected) >= target:
            break

    print(
        f"HYBRID_PRIORITY_SELECTION gallery={len(gallery)} selected_gallery="
        f"{sum(row.get('source_kind', '').startswith('trusted_gallery') for row in selected)} "
        f"video_selected={sum(row.get('source_kind', '').startswith('youtube_auto') for row in selected)}"
    )
    return selected


hybrid.youtube_candidates = filtered_youtube_candidates
hybrid.h.select_diverse = gallery_first_select

if __name__ == "__main__":
    raise SystemExit(hybrid.main())
