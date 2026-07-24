#!/usr/bin/env python3
"""Combine exact-title image discovery with exact-gallery page crawling."""
from __future__ import annotations

import re
import time

import ddg_image_discovery
import run_hd_page_crawl_ddg as runner


def discover_images(game: dict, index: int) -> list[dict]:
    helper = runner.p.h
    found: dict[str, dict] = {}
    queries = [
        f'"{game["name"]}" gameplay screenshot',
        f'"{game["name"]}" in-game screenshot HD',
    ]
    for query_number, query in enumerate(queries):
        results = ddg_image_discovery.image_results(query, max_pages=3)
        for rank, item in enumerate(results):
            image_url = str(item.get("image") or "")
            page_url = str(item.get("url") or item.get("source") or "")
            title = str(item.get("title") or "")
            if not image_url.startswith("http"):
                continue
            context = " ".join([title, page_url, image_url])
            if helper.blocked(image_url) or helper.blocked(page_url):
                continue
            if not helper.exact_game_match(game, context):
                continue
            if helper.reject_context(context):
                continue
            if not (
                helper.domain_allowed(page_url, helper.TRUSTED_PAGE_DOMAINS)
                or helper.domain_allowed(image_url, helper.TRUSTED_IMAGE_DOMAINS)
            ):
                continue
            try:
                width = int(item.get("width") or 0)
                height = int(item.get("height") or 0)
            except (TypeError, ValueError):
                width, height = 0, 0
            score = 180.0 - query_number * 4.0 - rank * 0.04
            if width >= 1280 and height >= 720:
                score += 24
            elif width >= 900 and height >= 500:
                score += 14
            if helper.gameplay_context(context):
                score += 20
            row = {
                "image_url": image_url,
                "page_url": page_url,
                "title": title,
                "query": query,
                "reported_width": width,
                "reported_height": height,
                "discovery_score": score,
            }
            previous = found.get(image_url)
            if previous is None or score > previous.get("discovery_score", -999):
                found[image_url] = row
        time.sleep(0.8)
    rows = sorted(found.values(), key=lambda row: row.get("discovery_score", 0), reverse=True)
    print(f"EXACT_IMAGE_RESULTS {len(rows)} for {game['name']}")
    return rows


# DuckDuckGo reliably serves roughly two HTML searches before throttling a
# runner. Use them for the broad gallery query and an exact LaunchBox query,
# because LaunchBox labels every asset and exposes high-resolution gameplay
# screenshots directly. Later lower-priority queries may be throttled safely.
base_web_search = runner.p.web_search
boost_used = False


def boosted_web_search(session, query: str):
    global boost_used
    rows = list(base_web_search(session, query))
    if not boost_used:
        match = re.search(r'"([^"]+)"', query)
        if match:
            game_name = match.group(1)
            launchbox_query = (
                f'site:gamesdb.launchbox-app.com/games/images "{game_name}" '
                '"Screenshot - Gameplay"'
            )
            rows.extend(base_web_search(session, launchbox_query))
        boost_used = True
    unique = {}
    for row in rows:
        unique.setdefault(row.get("url", ""), row)
    return [row for url, row in unique.items() if url]


runner.p.web_search = boosted_web_search
runner.p.h.discover_original = discover_images

if __name__ == "__main__":
    raise SystemExit(runner.p.h.main())
