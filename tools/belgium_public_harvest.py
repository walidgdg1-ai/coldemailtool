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
        completed_pages=int(cp.get('completed_pages') or 0)
        completed_records=int(cp.get('records_persisted') or 0)

    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(locale='en-GB',viewport={'width':1440,'height':1100})
        await page.goto(BDA_URL,wait_until='domcontentloaded',timeout=90000)
        await page.wait_for_timeout(6000)

        page_size_select=None
        for i in range(await page.locator('select').count()):
            sel=page.locator('select').nth(i)
            vals=await sel.locator('option').evaluate_all("els=>els.map(o=>o.value)")
            if {'10','25','50','100'}.issubset(set(vals)):
                page_size_select=sel;break
        if page_size_select is None:raise RuntimeError('Public BDA 10/25/50/100 page-size selector not found')

        async with page.expect_response(lambda r: ENDPOINT_FRAGMENT in r.url.lower(),timeout=30000) as info:
            await page_size_select.select_option('100')
        resp=await info.value
        if resp.status!=200:raise RuntimeError(f'BDA page-size request HTTP {resp.status}')
        body=await resp.json()
        current_page=1

        # Resume by replaying public Next actions. After this loop, body/current_page point to
        # the first page not yet checkpointed. Replayed responses are never persisted twice.
        while current_page<=completed_pages:
            nxt=page.locator('button[aria-label="pagination.common.nextPage"]')
            if not await nxt.count() or not await nxt.first.is_enabled():raise RuntimeError('Cannot replay to saved Belgium checkpoint')
            async with page.expect_response(lambda r: ENDPOINT_FRAGMENT in r.url.lower(),timeout=30000) as ni:
                await nxt.first.click()
            rr=await ni.value
            if rr.status!=200:raise RuntimeError(f'BDA replay page {current_page+1} HTTP {rr.status}')
            body=await rr.json();current_page+=1

        done=False
        while not done:
            page_start=current_page
            chunk_path=out/f'belgium-public-pages-{page_start:05d}-{page_start+args.chunk_pages-1:05d}.jsonl.gz'
            rows_written=0;oldest=None;newest=None;page_end=current_page-1
            with gzip.open(chunk_path,'wt',encoding='utf-8',newline='') as f:
                for i in range(args.chunk_pages):
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
                    nxt=page.locator('button[aria-label="pagination.common.nextPage"]')
                    if not await nxt.count() or not await nxt.first.is_enabled():
                        done=True;break
                    # Do not prefetch a page that belongs to the next chunk after the final row
                    # unless we preserve its body/current_page as the next chunk start.
                    async with page.expect_response(lambda r: ENDPOINT_FRAGMENT in r.url.lower(),timeout=30000) as ni:
                        await nxt.first.click()
                    rr=await ni.value
                    if rr.status!=200:raise RuntimeError(f'BDA page {current_page+1} HTTP {rr.status}')
                    body=await rr.json();current_page+=1
                    await page.wait_for_timeout(args.delay_ms)

            manifest={
                'source':'Belgium e-Procurement Bulletin of Tenders public BDA',
                'mode':'anonymous_public_ui',
                'endpoint_observed':ENDPOINT_FRAGMENT,
                'page_size':100,
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
                'window_start':args.start,'window_end':args.end,'page_size':100
            }
            checkpoint_path.write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2),encoding='utf-8')
            upload(args.release_tag,checkpoint_path)
            print('BELGIUM_CHUNK_COMMITTED',page_start,page_end,rows_written,'oldest',oldest,'records',completed_records,flush=True)
            if done:break
            # body/current_page already point to the next unpersisted page because the final
            # iteration prefetched it. Do not increment here or a page will be skipped.

        await browser.close()
    summary={
        'source':'BELGIUM_PUBLIC_BDA','status':'RAW_COMPLETE','completed_pages':completed_pages,
        'records_persisted':completed_records,'window_start':args.start,'window_end':args.end,
        'page_size':100,'release':args.release_tag
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
    ap.add_argument('--delay-ms',type=int,default=150)
    args=ap.parse_args()
    asyncio.run(run(args))

if __name__=='__main__':main()
