#!/usr/bin/env python3
"""Checkpointed anonymous harvester for Belgium's public Bulletin of Tenders UI.

This deliberately drives only the public BDA interface and reads the same public JSON responses
that the page itself renders. It never captures or persists request headers, cookies, storage,
tokens or authenticated browser state.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import date

ENDPOINT_FRAGMENT='/api/sea/search/publications'
BDA_URL='https://www.publicprocurement.be/bda'
PAGE_SIZE=25


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def iso_day(v):
    if not v:return None
    s=str(v)[:10]
    try:return date.fromisoformat(s)
    except:return None


def upload(tag:str,*paths:Path):
    for p in paths:
        subprocess.run(['gh','release','upload',tag,str(p),'--clobber'],check=True)


async def run(args):
    from playwright.async_api import async_playwright
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    cutoff=date.fromisoformat(args.start)
    checkpoint_path=out/'belgium-public-checkpoint.json'
    completed_pages=0
    completed_records=0
    if checkpoint_path.exists():
        cp=json.loads(checkpoint_path.read_text(encoding='utf-8'))
        if int(cp.get('page_size') or PAGE_SIZE)!=PAGE_SIZE:
            raise RuntimeError(f"Belgium checkpoint page size mismatch: {cp.get('page_size')} != {PAGE_SIZE}")
        completed_pages=int(cp.get('completed_pages') or 0)
        completed_records=int(cp.get('records_persisted') or 0)

    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(locale='en-GB',viewport={'width':1440,'height':1100})

        async def next_public_page(expected_page:int,phase:str):
            """Advance only through BOSA's visible public Next control with bounded retry/backoff."""
            last_error=None
            for attempt in range(1,args.max_retries+1):
                try:
                    nxt=page.locator('button[aria-label="pagination.common.nextPage"]')
                    if not await nxt.count() or not await nxt.first.is_enabled():
                        raise RuntimeError('public Next control unavailable')
                    async with page.expect_response(lambda r: ENDPOINT_FRAGMENT in r.url.lower(),timeout=args.response_timeout_ms) as ni:
                        await nxt.first.click(timeout=10000)
                    rr=await ni.value
                    if rr.status==200:
                        data=await rr.json()
                        pubs=data.get('publications') if isinstance(data,dict) else None
                        if not isinstance(pubs,list):raise RuntimeError('HTTP 200 without publications list')
                        return data
                    last_error=RuntimeError(f'HTTP {rr.status}')
                    print('BELGIUM_PAGE_RETRY',phase,expected_page,'attempt',attempt,'status',rr.status,flush=True)
                except Exception as e:
                    last_error=e
                    print('BELGIUM_PAGE_RETRY',phase,expected_page,'attempt',attempt,'error',repr(e),flush=True)
                if attempt<args.max_retries:
                    backoff=min(args.max_backoff_ms,args.retry_base_ms*(2**(attempt-1)))
                    await page.wait_for_timeout(backoff)
            raise RuntimeError(f'BDA {phase} page {expected_page} failed after {args.max_retries} attempts: {last_error!r}')

        # Capture the exact initial anonymous app-generated public search response. The default
        # page size (25) and page-1 request were independently observed in the UI probe.
        async with page.expect_response(lambda r: ENDPOINT_FRAGMENT in r.url.lower(),timeout=90000) as initial_info:
            await page.goto(BDA_URL,wait_until='domcontentloaded',timeout=90000)
        initial=await initial_info.value
        if initial.status!=200:raise RuntimeError(f'BDA initial public search HTTP {initial.status}')
        body=await initial.json()
        current_page=1
        await page.wait_for_timeout(3000)

        pubs0=body.get('publications') or []
        if not isinstance(pubs0,list):raise RuntimeError('BDA initial publications payload is not a list')
        if len(pubs0)>PAGE_SIZE:raise RuntimeError(f'Unexpected Belgium default page size: {len(pubs0)}>{PAGE_SIZE}')

        # Resume by replaying the same public Next control. Replayed pages are not persisted.
        while current_page<=completed_pages:
            body=await next_public_page(current_page+1,'replay')
            current_page+=1
            if current_page%100==1:
                print('BELGIUM_REPLAY_PROGRESS',current_page-1,'of',completed_pages,flush=True)

        done=False
        while not done:
            page_start=current_page
            chunk_path=out/f'belgium-public-pages-{page_start:05d}-{page_start+args.chunk_pages-1:05d}.jsonl.gz'
            rows_written=0;oldest=None;newest=None;page_end=current_page-1
            with gzip.open(chunk_path,'wt',encoding='utf-8',newline='') as f:
                for idx in range(args.chunk_pages):
                    pubs=body.get('publications') or []
                    if not isinstance(pubs,list):raise RuntimeError(f'BDA response publications is {type(pubs)}')
                    for pub in pubs:
                        d=iso_day(pub.get('publicationDate'))
                        if d:
                            oldest=d if oldest is None or d<oldest else oldest
                            newest=d if newest is None or d>newest else newest
                        f.write(json.dumps({'harvest_page':current_page,'publication':pub},ensure_ascii=False,separators=(',',':'))+'\n')
                        rows_written+=1
                    page_end=current_page
                    if oldest and oldest<cutoff:
                        done=True;break
                    # At a chunk boundary, commit first. The next request happens only after the
                    # release asset + checkpoint are durable, so a transient 5xx cannot discard
                    # the 100 pages just harvested.
                    if idx==args.chunk_pages-1:
                        break
                    body=await next_public_page(current_page+1,'harvest')
                    current_page+=1
                    await page.wait_for_timeout(args.delay_ms)

            manifest={
                'source':'Belgium e-Procurement Bulletin of Tenders public BDA',
                'mode':'anonymous_public_ui',
                'endpoint_observed':ENDPOINT_FRAGMENT,
                'page_size':PAGE_SIZE,
                'page_start':page_start,'page_end':page_end,'rows':rows_written,
                'oldest_publication_date':str(oldest) if oldest else None,
                'newest_publication_date':str(newest) if newest else None,
                'canonical_window_start':args.start,'canonical_window_end':args.end,
                'file':chunk_path.name,'bytes':chunk_path.stat().st_size,'sha256':sha256(chunk_path),
                'safety':'No auth headers, cookies, browser storage, tokens or credentials captured or persisted.'
            }
            manifest_path=out/(chunk_path.name+'.manifest.json')
            manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            upload(args.release_tag,chunk_path,manifest_path)
            completed_pages=page_end;completed_records+=rows_written
            checkpoint={
                'source':'BELGIUM_PUBLIC_BDA','status':'COMPLETE' if done else 'READY_TO_CONTINUE',
                'completed_pages':completed_pages,'records_persisted':completed_records,
                'last_chunk':chunk_path.name,'oldest_seen':str(oldest) if oldest else None,
                'window_start':args.start,'window_end':args.end,'page_size':PAGE_SIZE
            }
            checkpoint_path.write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2),encoding='utf-8')
            upload(args.release_tag,checkpoint_path)
            print('BELGIUM_CHUNK_COMMITTED',page_start,page_end,rows_written,'oldest',oldest,'records',completed_records,flush=True)
            if done:break

            await page.wait_for_timeout(args.chunk_pause_ms)
            # Only now request the first page of the next chunk. If all retries fail, the just
            # committed checkpoint remains safe and the next workflow run resumes from it.
            body=await next_public_page(current_page+1,'chunk-boundary')
            current_page+=1

        await browser.close()
    summary={
        'source':'BELGIUM_PUBLIC_BDA','status':'RAW_COMPLETE','completed_pages':completed_pages,
        'records_persisted':completed_records,'window_start':args.start,'window_end':args.end,
        'page_size':PAGE_SIZE,'release':args.release_tag
    }
    sp=out/'belgium-public-summary.json';sp.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');upload(args.release_tag,sp)
    print(json.dumps(summary,indent=2))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default='raw/belgium')
    ap.add_argument('--release-tag',default='tender-raw-belgium-public-v1')
    ap.add_argument('--start',default='2023-08-01')
    ap.add_argument('--end',default='2026-07-31')
    ap.add_argument('--chunk-pages',type=int,default=100)
    ap.add_argument('--delay-ms',type=int,default=100)
    ap.add_argument('--chunk-pause-ms',type=int,default=1500)
    ap.add_argument('--max-retries',type=int,default=7)
    ap.add_argument('--retry-base-ms',type=int,default=1500)
    ap.add_argument('--max-backoff-ms',type=int,default=30000)
    ap.add_argument('--response-timeout-ms',type=int,default=30000)
    args=ap.parse_args()
    asyncio.run(run(args))

if __name__=='__main__':main()
