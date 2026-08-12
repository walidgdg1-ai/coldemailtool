#!/usr/bin/env python3
import argparse, calendar, gzip, hashlib, json, os, re, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = "PublicTenderIntelligenceRelay/1.0 (+official-open-data)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "*/*"})
ROOT = Path(os.environ.get("TENDER_OUT", "relay_out")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
MANIFEST = ROOT / "_manifest.jsonl"


def h256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def log(status, source, url, path=None, **extra):
    rec = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "status": status,
        "source": source,
        "url": url,
    }
    if path and Path(path).exists():
        p = Path(path)
        rec.update({"file": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": h256(p)})
    rec.update(extra)
    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def download(source, url, dest, params=None, method="GET", json_body=None, timeout=900, retries=5, allow_404=False):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for i in range(retries):
        try:
            r = S.request(method, url, params=params, json=json_body, stream=True, timeout=(30, timeout), allow_redirects=True)
            if allow_404 and r.status_code == 404:
                log("not_available", source, r.url, http_status=404)
                return None
            if r.status_code in (429, 502, 503, 504):
                time.sleep(min(90, int(r.headers.get("Retry-After", 3 * (2 ** i)))))
                continue
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
            tmp.replace(dest)
            log("ok", source, r.url, dest, content_type=r.headers.get("content-type"))
            return dest
        except Exception as e:
            if i == retries - 1:
                log("error", source, url, error=repr(e), params=params)
                return None
            time.sleep(min(60, 2 ** (i + 1)))


def months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def run_canada():
    urls = [
        "https://canadabuys.canada.ca/opendata/pub/newTenderNotice-nouvelAvisAppelOffres.csv",
        "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv",
        "https://canadabuys.canada.ca/opendata/pub/tenderNoticeComplete-avisAppelOffresComplet.csv",
        "https://canadabuys.canada.ca/opendata/pub/2009-2022-tenderNoticeHistorical-AvisAppelOffresHistorique.csv",
        "https://canadabuys.canada.ca/opendata/pub/awardNoticeComplete-avisAttributionComplet.csv",
        "https://canadabuys.canada.ca/opendata/pub/2012-2022-awardNoticeHistorical-avisAttributionHistorique.csv",
        "https://canadabuys.canada.ca/opendata/pub/contractHistoryComplete-contratsOctroyesComplet.csv",
        "https://canadabuys.canada.ca/opendata/pub/2009-2023-contractHistoryHistorical-contratsOctroyesHistorique.csv",
    ]
    out = ROOT / "canada"
    for u in urls:
        download("canada", u, out / Path(urlparse(u).path).name)


def run_ted(year):
    start = date(max(2023, year), 8 if year == 2023 else 1, 1)
    end = date(year, 7 if year == 2026 else 12, 31)
    out = ROOT / f"ted_{year}"
    for y, m in months_between(start, end):
        # Official TED direct monthly bulk package endpoint.
        u = f"https://ted.europa.eu/packages/monthly/{y}-{m}"
        download("ted", u, out / f"{y}_{m:02d}.tar.gz", allow_404=True, timeout=1800)


def run_france():
    out = ROOT / "france_boamp"
    base = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/exports/csv"
    start, end = date(2023, 8, 1), date(2026, 7, 31)
    for y, m in months_between(start, end):
        last = calendar.monthrange(y, m)[1]
        a = f"{y}-{m:02d}-01"
        b = (date(y, m, last) + timedelta(days=1)).isoformat()
        where = f"dateparution >= date'{a}' AND dateparution < date'{b}'"
        params = {"where": where, "lang": "fr", "timezone": "Europe/Paris", "use_labels": "false", "delimiter": ";"}
        download("france_boamp", base, out / f"boamp_{y}-{m:02d}.csv", params=params, timeout=1800)


def run_germany():
    out = ROOT / "germany"
    base = "https://oeffentlichevergabe.de/api/notice-exports"
    start, end = date(2023, 8, 1), date(2026, 7, 31)
    for y, m in months_between(start, end):
        params = {"pubMonth": f"{y}-{m:02d}"}
        download("germany", base, out / f"germany_{y}-{m:02d}.zip", params=params, timeout=1800)


def run_quebec():
    out = ROOT / "quebec_seao"
    landing = "https://www.donneesquebec.ca/recherche/dataset/systeme-electronique-dappel-doffres-seao"
    links = {}
    # Crawl resource pages. The portal currently has >400 resources and pagination sorting can be degraded.
    for page in range(1, 55):
        u = landing + f"?res_page={page}"
        try:
            r = S.get(u, timeout=90)
            r.raise_for_status()
        except Exception as e:
            log("error", "quebec_seao_discovery", u, error=repr(e))
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        found = 0
        for a in soup.select("a[href]"):
            x = urljoin(r.url, a.get("href"))
            if "/download/" not in x:
                continue
            fn = Path(urlparse(x).path).name
            low = fn.lower()
            if not (low.endswith(".json") or low.endswith(".zip")):
                continue
            links[fn] = x
            found += 1
        if found == 0 and page > 8:
            # Don't stop too early because the portal has known sorting issues.
            pass
    # Use JSON monthly snapshots without weekly overlap. Keep consolidated JSON archive bridging 2023->2024.
    selected = {}
    for fn, u in links.items():
        low = fn.lower()
        if "hebdo_" in low:
            continue
        if "json_mensuel_20230101_20240430" in low:
            selected[fn] = u
            continue
        mm = re.search(r"mensuel_(20\d{6})_(20\d{6})\.json$", low)
        if mm and mm.group(1) >= "20240501":
            selected[fn] = u
    log("discovered", "quebec_seao", landing, resources=len(links), selected=len(selected), names=sorted(selected))
    for fn, u in sorted(selected.items()):
        download("quebec_seao", u, out / fn, timeout=1800)


def _extract_cursor(obj):
    cur = obj.get("cursor") or obj.get("nextCursor")
    if cur:
        return cur
    links = obj.get("links")
    if isinstance(links, dict):
        v = links.get("nextCursor")
        if v:
            return v
        nxt = links.get("next")
        if isinstance(nxt, str) and "cursor=" in nxt:
            return nxt.split("cursor=", 1)[1].split("&", 1)[0]
    if isinstance(links, list):
        for x in links:
            if isinstance(x, dict) and x.get("rel") in ("next", "nextPage"):
                nxt = x.get("href", "")
                if "cursor=" in nxt:
                    return nxt.split("cursor=", 1)[1].split("&", 1)[0]
    return None


def run_uk_fts(year):
    out = ROOT / f"uk_fts_{year}"
    base = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
    lo = date(year, 8, 1) if year == 2023 else date(year, 1, 1)
    hi = date(year, 7, 31) if year == 2026 else date(year, 12, 31)
    for y, m in months_between(lo, hi):
        last = calendar.monthrange(y, m)[1]
        params = {
            "updatedFrom": f"{y}-{m:02d}-01T00:00:00",
            "updatedTo": f"{y}-{m:02d}-{last:02d}T23:59:59",
            "stages": "planning,tender,award",
            "limit": 100,
        }
        cursor = None
        page = 0
        seen = set()
        while True:
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            try:
                r = S.get(base, params=p, timeout=180)
                if r.status_code in (429, 502, 503, 504):
                    time.sleep(min(60, int(r.headers.get("Retry-After", 10))))
                    continue
                r.raise_for_status()
                obj = r.json()
            except Exception as e:
                log("error", "uk_fts", base, month=f"{y}-{m:02d}", page=page, error=repr(e), params=p)
                break
            path = out / f"{y}-{m:02d}_p{page:05d}.json.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
            log("ok", "uk_fts", r.url, path, month=f"{y}-{m:02d}", page=page, releases=len(obj.get("releases", [])))
            new = _extract_cursor(obj)
            page += 1
            if not new or new in seen:
                break
            seen.add(new)
            cursor = new
            time.sleep(0.08)


def run_usaspending(year):
    out = ROOT / f"usa_usaspending_{year}"
    out.mkdir(parents=True, exist_ok=True)
    base = "https://api.usaspending.gov/api/v2/bulk_download/awards/"
    start = date(year, 8, 1) if year == 2023 else date(year, 1, 1)
    end = date(year, 7, 31) if year == 2026 else date(year, 12, 31)
    payload = {
        "filters": {
            "time_period": [{"start_date": start.isoformat(), "end_date": end.isoformat()}],
            "award_type_codes": ["A", "B", "C", "D"],
        },
        "file_format": "csv",
    }
    try:
        r = S.post(base, json=payload, timeout=180)
        r.raise_for_status()
        obj = r.json()
        (out / "request.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")
        log("requested", "usa_usaspending", base, out / "request.json", year=year)
    except Exception as e:
        log("error", "usa_usaspending", base, year=year, error=repr(e), payload=payload)
        return
    # API versions have returned either status_url, file_url, or a download_request object.
    status_url = obj.get("status_url") or obj.get("file_url")
    dr = obj.get("download_request") if isinstance(obj, dict) else None
    if not status_url and isinstance(dr, dict):
        status_url = dr.get("status_url") or dr.get("file_url")
    if status_url and status_url.startswith("/"):
        status_url = "https://api.usaspending.gov" + status_url
    if not status_url:
        log("blocked", "usa_usaspending", base, year=year, reason="response contained no status/file URL", response=obj)
        return
    if status_url.lower().endswith(".zip"):
        download("usa_usaspending", status_url, out / f"contracts_{year}.zip", timeout=1800)
        return
    for i in range(180):
        try:
            s = S.get(status_url, timeout=90)
            s.raise_for_status()
            st = s.json()
        except Exception as e:
            log("poll_error", "usa_usaspending", status_url, year=year, attempt=i, error=repr(e))
            time.sleep(10)
            continue
        (out / "status_latest.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
        fu = st.get("file_url") or st.get("download_url")
        if fu:
            if fu.startswith("/"):
                fu = "https://api.usaspending.gov" + fu
            download("usa_usaspending", fu, out / f"contracts_{year}.zip", timeout=1800)
            return
        state = str(st.get("status", "")).lower()
        if state in ("failed", "error"):
            log("error", "usa_usaspending", status_url, year=year, response=st)
            return
        time.sleep(10)
    log("timeout", "usa_usaspending", status_url, year=year)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    args = ap.parse_args()
    s = args.source
    try:
        if s == "canada": run_canada()
        elif s == "quebec": run_quebec()
        elif s == "france": run_france()
        elif s == "germany": run_germany()
        elif s.startswith("ted_"): run_ted(int(s.split("_")[1]))
        elif s.startswith("uk_fts_"): run_uk_fts(int(s.rsplit("_", 1)[1]))
        elif s.startswith("usa_"): run_usaspending(int(s.rsplit("_", 1)[1]))
        else: raise SystemExit(f"Unknown source {s}")
    except Exception as e:
        log("fatal", s, "internal", error=repr(e))
        raise

if __name__ == "__main__":
    main()
