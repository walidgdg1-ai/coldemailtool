#!/usr/bin/env python3
"""Exact-title public image-result discovery helper.

The helper only returns candidates whose title or source URL independently
identifies the requested game. Downstream code still enforces trusted domains,
image dimensions, gameplay context, technical quality and deduplication.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
)


def _token(text: str) -> str | None:
    for pattern in (
        r'vqd=["\']?([\d-]+)',
        r'vqd\s*[:=]\s*["\']([\d-]+)["\']',
        r'"vqd"\s*:\s*"([\d-]+)"',
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def image_results(query: str, max_pages: int = 3) -> list[dict]:
    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        landing = session.get(
            "https://duckduckgo.com/",
            params={"q": query},
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"IMAGE_SEARCH_LANDING_ERROR {query}: {exc}")
        return []
    token = _token(landing.text)
    if not token:
        print(
            f"IMAGE_SEARCH_NO_TOKEN {query}; status={landing.status_code}; "
            f"prefix={landing.text[:160]!r}"
        )
        return []

    request_headers = {
        **headers,
        "Referer": landing.url,
    }
    params = {
        "l": "us-en",
        "o": "json",
        "q": query,
        "vqd": token,
        "f": ",,,",
        "p": "1",
    }
    endpoint: str | None = "https://duckduckgo.com/i.js"
    rows: list[dict] = []
    for page in range(max_pages):
        try:
            if page == 0:
                response = session.get(
                    endpoint,
                    params=params,
                    headers=request_headers,
                    timeout=35,
                )
            else:
                response = session.get(
                    endpoint,
                    headers=request_headers,
                    timeout=35,
                )
        except requests.RequestException as exc:
            print(f"IMAGE_SEARCH_REQUEST_ERROR {query}: {exc}")
            break
        if response.status_code != 200:
            print(
                f"IMAGE_SEARCH_STATUS {response.status_code} {query}; "
                f"prefix={response.text[:160]!r}"
            )
            break
        try:
            payload = response.json()
        except json.JSONDecodeError:
            print(f"IMAGE_SEARCH_JSON_ERROR {query}; prefix={response.text[:160]!r}")
            break
        batch = payload.get("results") or []
        rows.extend(batch)
        print(f"IMAGE_SEARCH_PAGE {page + 1} {len(batch)} {query}")
        next_value = payload.get("next")
        endpoint = urljoin("https://duckduckgo.com", next_value) if next_value else None
        if not endpoint or not batch:
            break
        time.sleep(0.6)
    return rows
