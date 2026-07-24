#!/usr/bin/env python3
"""Supplement strict image discovery by crawling trusted game review/gallery pages."""
from __future__ import annotations

import base64
import html
import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import harvest_hd_web_frames as h

h.TRUSTED_PAGE_DOMAINS.update({
    "gamesaktuell.de", "digitallydownloaded.net", "jeuxactu.com", "rpgfan.com",
    "cubed3.com", "godisageek.com", "gamingtrend.com", "worthplaying.com",
    "operationrainfall.com", "capsulecomputers.com.au", "gaming-age.com",
    "impulsegamer.com", "gamersheroes.com", "videogamer.com", "gamingnexus.com",
    "nintendoworldreport.com", "rpgamer.com", "psu.com", "playstationlifestyle.net",
})

IMAGE_EXT = re.compile(r"\.(?:jpe?g|png|webp)(?:[?#].*)?$", re.I)
BAD_ASSET = re.compile(r"(?:avatar|author|profile|logo|icon|badge|rating|score|flag|emoji|advert|banner|header|footer|social|share|pixel|spacer|placeholder)", re.I)


def decode_bing_url(url: str) -> str:
    if "bing.com/ck/a" not in url:
        return url
    try:
        value = parse_qs(urlparse(url).query).get("u", [""])[0]
        if value.startswith("a1"):
            value = value[2:]
            value += "=" * (-len(value) % 4)
            return base64.urlsafe_b64decode(value).decode("utf-8", "ignore")
    except Exception:
        pass
    return url


def web_search(session: requests.Session, query: str) -> list[dict[str, str]]:
    try:
        r = session.get("https://www.bing.com/search", params={"q": query, "count": "50", "setlang": "en-US"}, timeout=30)
    except requests.RequestException as exc:
        print(f"WEB_SEARCH_ERROR {query}: {exc}")
        return []
    if r.status_code != 200:
        print(f"WEB_SEARCH_STATUS {r.status_code} {query}")
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    rows = []
    for node in soup.select("li.b_algo h2 a, h2 a"):
        href = decode_bing_url(node.get("href") or "")
        title = node.get_text(" ", strip=True)
        if href.startswith("http"):
            rows.append({"url": href, "title": title})
    return rows


def srcset_urls(value: str) -> list[str]:
    return [part.strip().split(" ")[0] for part in value.split(",") if part.strip()]


def page_images(session: requests.Session, page_url: str, page_title: str, query: str) -> list[dict[str, Any]]:
    try:
        r = session.get(page_url, timeout=35, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"PAGE_ERROR {page_url}: {exc}")
        return []
    if r.status_code != 200 or "html" not in (r.headers.get("Content-Type") or "").lower():
        return []
    final_page = r.url
    if not h.domain_allowed(final_page, h.TRUSTED_PAGE_DOMAINS):
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    document_title = (soup.title.get_text(" ", strip=True) if soup.title else page_title)
    candidates: list[tuple[str, str]] = []

    for meta in soup.select('meta[property="og:image"], meta[name="twitter:image"], meta[itemprop="image"]'):
        url = meta.get("content")
        if url:
            candidates.append((url, document_title))

    for tag in soup.find_all(["img", "source"]):
        alt = " ".join(filter(None, [tag.get("alt"), tag.get("title"), tag.get("aria-label")]))
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-image", "data-url"):
            value = tag.get(attr)
            if value:
                candidates.append((value, alt or document_title))
        for attr in ("srcset", "data-srcset"):
            value = tag.get(attr)
            if value:
                candidates.extend((u, alt or document_title) for u in srcset_urls(value))

    for link in soup.find_all("a", href=True):
        href = link.get("href") or ""
        text = link.get_text(" ", strip=True)
        if IMAGE_EXT.search(href):
            candidates.append((href, text or document_title))

    # Many gaming sites serialize galleries into JSON blobs.
    raw = html.unescape(r.text)
    patterns = [
        r'https?://[^"\'<>\\ ]+\.(?:jpe?g|png|webp)(?:\?[^"\'<>\\ ]*)?',
        r'"(?:contentUrl|image|imageUrl|src|original)"\s*:\s*"([^"\\]+\.(?:jpe?g|png|webp)(?:\?[^"\\]*)?)"',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, raw, flags=re.I):
            url = match if isinstance(match, str) else match[0]
            candidates.append((url.replace("\\/", "/"), document_title))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_url, context in candidates:
        url = urljoin(final_page, html.unescape(raw_url).replace("\\/", "/"))
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        combined = " ".join([document_title, context, final_page, url, query])
        if BAD_ASSET.search(url + " " + context):
            continue
        if h.reject_context(combined) or not h.exact_game_match(CURRENT_GAME, combined):
            continue
        rows.append({
            "image_url": url,
            "page_url": final_page,
            "title": context or document_title,
            "query": query,
            "discovery_score": 145.0 + (20.0 if h.gameplay_context(combined) else 0.0),
        })
    return rows


def discover_pages(game: dict[str, Any], index: int) -> list[dict[str, Any]]:
    global CURRENT_GAME
    CURRENT_GAME = game
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    found: dict[str, dict[str, Any]] = {}
    # Keep any strong direct image hits from the strict image index.
    try:
        for row in h.discover_original(game, index):
            found[row["image_url"]] = row
    except Exception as exc:
        print(f"DIRECT_IMAGE_DISCOVERY_WARNING: {exc}")

    name = game["name"]
    queries = [
        f'"{name}" screenshots gameplay gallery',
        f'"{name}" review gameplay screenshots',
        f'"{name}" HD gameplay screenshots',
        f'site:gamespot.com "{name}" review',
        f'site:ign.com "{name}" screenshots',
        f'site:nintendolife.com "{name}" screenshots',
        f'site:pushsquare.com "{name}" review screenshots',
        f'site:mobygames.com "{name}" screenshots',
        f'site:rpgsite.net "{name}" screenshots',
    ]
    pages: dict[str, dict[str, str]] = {}
    for query in queries:
        for row in web_search(session, query):
            url = row["url"]
            context = " ".join([row["title"], url, query])
            if h.blocked(url) or not h.domain_allowed(url, h.TRUSTED_PAGE_DOMAINS):
                continue
            if not h.exact_game_match(game, context) or h.reject_context(context):
                continue
            pages.setdefault(url.split("#")[0], {"url": url.split("#")[0], "title": row["title"], "query": query})
        time.sleep(0.4)
        if len(pages) >= 28:
            break

    print(f"DISCOVERED_PAGES {len(pages)} for {name}")
    for page in list(pages.values())[:32]:
        for row in page_images(session, page["url"], page["title"], page["query"]):
            old = found.get(row["image_url"])
            if old is None or row["discovery_score"] > old.get("discovery_score", 0):
                found[row["image_url"]] = row
        if len(found) >= 220:
            break
        time.sleep(0.25)
    rows = sorted(found.values(), key=lambda x: x.get("discovery_score", 0), reverse=True)
    print(f"DISCOVERED_IMAGES {len(rows)} for {name}")
    return rows


CURRENT_GAME: dict[str, Any] = {}
h.discover_original = h.discover
h.discover = discover_pages

if __name__ == "__main__":
    raise SystemExit(h.main())
