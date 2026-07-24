#!/usr/bin/env python3
"""Run trusted gameplay-page crawling with Bing's stable RSS search endpoint."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

import run_hd_page_crawl as p


def rss_web_search(session: requests.Session, query: str):
    try:
        r = session.get(
            "https://www.bing.com/search",
            params={"q": query, "format": "rss", "count": "50", "setlang": "en-US"},
            timeout=30,
            headers={"Accept": "application/rss+xml, application/xml, text/xml"},
        )
    except requests.RequestException as exc:
        print(f"RSS_SEARCH_ERROR {query}: {exc}")
        return []
    if r.status_code != 200:
        print(f"RSS_SEARCH_STATUS {r.status_code} {query}")
        return []
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as exc:
        print(f"RSS_PARSE_ERROR {query}: {exc}; prefix={r.text[:300]!r}")
        return []
    rows = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        raw_link = (item.findtext("link") or "").strip()
        link = p.decode_bing_url(raw_link)
        if link.startswith("http"):
            rows.append({"url": link, "title": title})
    print(f"RSS_RESULTS {len(rows)} {query}")
    for row in rows[:4]:
        print(f"RSS_ITEM {row['title'][:100]} | {row['url'][:220]}")
    return rows


p.web_search = rss_web_search

if __name__ == "__main__":
    raise SystemExit(p.h.main())
