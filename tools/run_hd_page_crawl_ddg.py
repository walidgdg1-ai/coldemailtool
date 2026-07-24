#!/usr/bin/env python3
"""Run trusted gameplay-page crawling with DuckDuckGo HTML search."""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

import run_hd_page_crawl as p


def unwrap_ddg(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc:
        value = parse_qs(parsed.query).get("uddg", [""])[0]
        if value:
            return unquote(value)
    return url


def ddg_web_search(session: requests.Session, query: str):
    endpoints = [
        "https://html.duckduckgo.com/html/",
        "https://lite.duckduckgo.com/lite/",
    ]
    for endpoint in endpoints:
        try:
            r = session.post(
                endpoint,
                data={"q": query, "kl": "us-en"},
                timeout=35,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except requests.RequestException as exc:
            print(f"DDG_SEARCH_ERROR {endpoint} {query}: {exc}")
            continue
        if r.status_code != 200:
            print(f"DDG_SEARCH_STATUS {r.status_code} {endpoint} {query}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        rows = []
        selectors = ["a.result__a", "a.result-link", "td.result-link a"]
        seen = set()
        for selector in selectors:
            for node in soup.select(selector):
                link = unwrap_ddg(node.get("href") or "")
                title = node.get_text(" ", strip=True)
                if link.startswith("http") and link not in seen:
                    seen.add(link)
                    rows.append({"url": link, "title": title})
        if rows:
            print(f"DDG_RESULTS {len(rows)} {query}")
            for row in rows[:4]:
                print(f"DDG_ITEM {row['title'][:100]} | {row['url'][:220]}")
            return rows
        print(f"DDG_NO_RESULTS {endpoint} {query}; prefix={r.text[:180]!r}")
    return []


p.web_search = ddg_web_search

if __name__ == "__main__":
    raise SystemExit(p.h.main())
