#!/usr/bin/env python3
"""Supplement strict image discovery by deeply crawling exact-title game galleries."""
from __future__ import annotations

import base64
import html
import json
import re
import time
from collections import deque
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
    "playstationtrophies.org", "xboxachievements.com", "uvlist.net", "exophase.com",
    "psnprofiles.com", "gamersyde.com", "gamekult.com", "gamereactor.eu",
    "gamereactor.com", "neoseeker.com", "gamesdatabase.org", "screenscraper.fr",
    "giantbomb.com", "gamepressure.com", "thegamesdb.net", "launchbox-app.com",
})
h.TRUSTED_IMAGE_DOMAINS.update({
    "playstationtrophies.org", "media.playstationtrophies.org",
    "xboxachievements.com", "media.xboxachievements.com", "images.uvlist.net",
    "cdn.exophase.com", "images.gamersyde.com", "image.jeuxvideo.com",
})

IMAGE_EXT = re.compile(r"\.(?:jpe?g|png|webp)(?:[?#].*)?$", re.I)
BAD_ASSET = re.compile(
    r"(?:avatar|author|profile|logo|icon|badge|rating|score|flag|emoji|advert|"
    r"banner|header|footer|social|share|pixel|spacer|placeholder|cookie|consent)",
    re.I,
)
GALLERY_LINK = re.compile(
    r"(?:screen(?:shot)?s?|gallery|galleries|media|images?|photos?|picture|view-image|"
    r"fullsize|original|lightbox|slideshow|slide|shot)[^\s]*|"
    r"(?:[?&](?:page|p|start|offset)=\d+)|(?:/page/\d+)",
    re.I,
)


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
        r = session.get(
            "https://www.bing.com/search",
            params={"q": query, "count": "50", "setlang": "en-US"},
            timeout=30,
        )
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


def fetch_html(session: requests.Session, page_url: str) -> tuple[str, BeautifulSoup, str] | None:
    try:
        r = session.get(page_url, timeout=35, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"PAGE_ERROR {page_url}: {exc}")
        return None
    ctype = (r.headers.get("Content-Type") or "").lower()
    if r.status_code != 200 or "html" not in ctype:
        return None
    if not h.domain_allowed(r.url, h.TRUSTED_PAGE_DOMAINS):
        return None
    return r.url, BeautifulSoup(r.text, "html.parser"), r.text


def page_identity(soup: BeautifulSoup, final_page: str) -> str:
    bits = [final_page]
    if soup.title:
        bits.append(soup.title.get_text(" ", strip=True))
    for selector in (
        'meta[property="og:title"]', 'meta[name="twitter:title"]',
        'link[rel="canonical"]',
    ):
        for node in soup.select(selector):
            bits.append(node.get("content") or node.get("href") or "")
    return " ".join(bits)


def page_images(
    session: requests.Session,
    page_url: str,
    page_title: str,
    query: str,
) -> list[dict[str, Any]]:
    fetched = fetch_html(session, page_url)
    if not fetched:
        return []
    final_page, soup, raw_html = fetched
    document_title = soup.title.get_text(" ", strip=True) if soup.title else page_title
    identity = page_identity(soup, final_page)
    # Critical anti-contamination lock: the fetched page itself—not the parent
    # query—must identify the requested game.
    if not h.exact_game_match(CURRENT_GAME, identity):
        print(f"PAGE_REJECT_IDENTITY {final_page} | {document_title[:120]}")
        return []
    if h.reject_context(identity):
        return []

    candidates: list[tuple[str, str]] = []
    for meta in soup.select(
        'meta[property="og:image"], meta[name="twitter:image"], '
        'meta[itemprop="image"], meta[property="og:image:secure_url"]'
    ):
        url = meta.get("content")
        if url:
            candidates.append((url, document_title))

    for tag in soup.find_all(["img", "source"]):
        alt = " ".join(
            filter(None, [tag.get("alt"), tag.get("title"), tag.get("aria-label")])
        )
        for attr in (
            "src", "data-src", "data-original", "data-lazy-src", "data-image",
            "data-url", "data-full", "data-full-src", "data-zoom-image",
        ):
            value = tag.get(attr)
            if value:
                candidates.append((value, alt or document_title))
        for attr in ("srcset", "data-srcset"):
            value = tag.get(attr)
            if value:
                candidates.extend((u, alt or document_title) for u in srcset_urls(value))

    for link in soup.find_all("a", href=True):
        href = link.get("href") or ""
        text = " ".join(
            filter(None, [link.get_text(" ", strip=True), link.get("title"), link.get("aria-label")])
        )
        if IMAGE_EXT.search(href):
            candidates.append((href, text or document_title))

    raw = html.unescape(raw_html)
    patterns = [
        r'https?://[^"\'<>\\ ]+\.(?:jpe?g|png|webp)(?:\?[^"\'<>\\ ]*)?',
        r'"(?:contentUrl|image|imageUrl|image_url|src|original|full|fullsize|zoom)"\s*:\s*"([^"\\]+\.(?:jpe?g|png|webp)(?:\?[^"\\]*)?)"',
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
        asset_context = " ".join([identity, context, final_page, url])
        if BAD_ASSET.search(url + " " + context):
            continue
        if h.reject_context(asset_context):
            continue
        rows.append({
            "image_url": url,
            "page_url": final_page,
            "title": context or document_title,
            "query": query,
            "discovery_score": 150.0 + (22.0 if h.gameplay_context(asset_context) else 0.0),
        })
    print(f"PAGE_IMAGES {len(rows)} {final_page}")
    return rows


def gallery_anchor(path: str) -> str:
    lowered = path.lower()
    for marker in ("/screenshots", "/screenshot", "/gallery", "/galleries", "/media", "/images"):
        pos = lowered.find(marker)
        if pos >= 0:
            return path[: pos + len(marker)].rstrip("/")
    return path.rstrip("/")


def related_gallery_pages(
    session: requests.Session,
    page_url: str,
    parent_title: str,
    query: str,
) -> list[dict[str, str]]:
    fetched = fetch_html(session, page_url)
    if not fetched:
        return []
    final_page, soup, _ = fetched
    identity = page_identity(soup, final_page)
    if not h.exact_game_match(CURRENT_GAME, identity):
        return []
    parsed_parent = urlparse(final_page)
    parent_host = parsed_parent.netloc.lower().removeprefix("www.")
    anchor = gallery_anchor(parsed_parent.path)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        raw_href = link.get("href") or ""
        href = urljoin(final_page, raw_href).split("#")[0]
        if not href.startswith("http") or href == final_page or href in seen:
            continue
        if IMAGE_EXT.search(href):
            continue
        parsed_child = urlparse(href)
        child_host = parsed_child.netloc.lower().removeprefix("www.")
        # Do not leave the source site while traversing a gallery.
        if child_host != parent_host:
            continue
        text = " ".join(
            filter(None, [link.get_text(" ", strip=True), link.get("title"), link.get("aria-label")])
        )
        link_context = " ".join([href, text])
        if BAD_ASSET.search(link_context) or not GALLERY_LINK.search(link_context):
            continue
        child_path = parsed_child.path.rstrip("/")
        same_gallery_tree = bool(anchor and child_path.startswith(anchor))
        names_game_itself = h.exact_game_match(CURRENT_GAME, link_context)
        # A child is valid only if it stays under the exact gallery path, or if
        # its own URL/text independently names the game. Parent query/title alone
        # can never authorize an unrelated navigation link.
        if not (same_gallery_tree or names_game_itself):
            continue
        seen.add(href)
        rows.append({"url": href, "title": text or parent_title, "query": query})
        if len(rows) >= 60:
            break
    print(f"RELATED_PAGES {len(rows)} {final_page}")
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
        f'site:playstationtrophies.org "{name}" screenshots',
        f'site:mobygames.com "{name}" screenshots',
        f'site:gamespot.com "{name}" review screenshots',
        f'site:ign.com "{name}" screenshots',
        f'site:nintendolife.com "{name}" screenshots',
        f'site:pushsquare.com "{name}" screenshots',
        f'site:rpgsite.net "{name}" screenshots',
    ]
    seed_pages: dict[str, dict[str, str]] = {}
    for query in queries:
        for row in web_search(session, query):
            url = row["url"].split("#")[0]
            context = " ".join([row["title"], url])
            if h.blocked(url) or not h.domain_allowed(url, h.TRUSTED_PAGE_DOMAINS):
                continue
            if not h.exact_game_match(game, context) or h.reject_context(context):
                continue
            seed_pages.setdefault(url, {"url": url, "title": row["title"], "query": query})
        time.sleep(0.35)
        if len(seed_pages) >= 30:
            break

    print(f"DISCOVERED_PAGES {len(seed_pages)} for {name}")
    queue: deque[tuple[dict[str, str], int]] = deque((page, 0) for page in seed_pages.values())
    visited: set[str] = set()
    while queue and len(visited) < 90 and len(found) < 340:
        page, depth = queue.popleft()
        url = page["url"]
        if url in visited:
            continue
        visited.add(url)
        for row in page_images(session, url, page["title"], page["query"]):
            old = found.get(row["image_url"])
            if old is None or row["discovery_score"] > old.get("discovery_score", 0):
                found[row["image_url"]] = row
        if depth < 2:
            for child in related_gallery_pages(session, url, page["title"], page["query"]):
                if child["url"] not in visited:
                    queue.append((child, depth + 1))
        time.sleep(0.12)

    rows = sorted(found.values(), key=lambda x: x.get("discovery_score", 0), reverse=True)
    print(f"DISCOVERED_IMAGES {len(rows)} for {name}; visited_pages={len(visited)}")
    return rows


CURRENT_GAME: dict[str, Any] = {}
h.discover_original = h.discover
h.discover = discover_pages

if __name__ == "__main__":
    raise SystemExit(h.main())
