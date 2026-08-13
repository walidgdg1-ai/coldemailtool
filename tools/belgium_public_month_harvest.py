#!/usr/bin/env python3
"""Harvest one Belgium BDA publication month through the anonymous public UI only.

The script drives BOSA's own public date-range picker and visible pagination controls. It never
captures/persists headers, cookies, localStorage, tokens, credentials, or authenticated state.
Every selector is validated from visible UI text at runtime before use.
"""
from __future__ import annotations

import argparse, asyncio, calendar, gzip, hashlib, json, re
from datetime import date
from pathlib import Path

URL='https://www.publicprocurement.be/bda'
API='/api/sea/search/publications'
MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']


def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

async def select_text_button(container,text:str):
    buttons=container.locator('button')
    texts=await buttons.all_inner_texts()
    hits=[i for i,t in enumerate(texts) if t.strip()==text]
    if not hits:
        raise RuntimeError(f'visible picker button {text!r} not found; sample={texts[:30]}')
    await buttons.nth(hits[-1]).click()

async def main(args):
    from playwright.async_api import async_playwright
    year,month=map(int,args.month.split('-'))
    if not (2023<=year<=2026 and 1<=month<=12): raise SystemExit('month outside supported recent-history window')
    first=date(year,month,1)
    last=date(year,month,calendar.monthrange(year,month)[1])
    expected_from=first.isoformat()
    if month==12: expected_to=date(year+1,1,1).isoformat()
    else: expected_to=date(year,month+1,1).isoformat()

    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    raw_path=out/f'belgium-bda-{args.month}.jsonl.gz'
    manifest_path=out/f'belgium-bda-{args.month}.manifest.json'
    rows=0; pages=0; ids=set(); observed_dates=[]; request_bodies=[]

    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(locale='en-GB',viewport={'width':1440,'height':1400})
        page.on('request',lambda req: request_bodies.append(req.post_data) if API in req.url.lower() else None)

        async with page.expect_response(lambda r: API in r.url.lower(),timeout=90000) as initial_info:
            await page.goto(URL,wait_until='domcontentloaded',timeout=90000)
        initial=await initial_info.value
        if initial.status!=200: raise RuntimeError(f'initial BDA search HTTP {initial.status}')
        await page.wait_for_timeout(1000)

        field=page.locator('input').nth(6)
        await field.click()
        dialog=page.locator('[role="dialog"]').last
        await dialog.wait_for(state='visible',timeout=10000)
        await page.wait_for_timeout(400)

        buttons=dialog.locator('button'); texts=await buttons.all_inner_texts()
        year_controls=[(i,t.strip()) for i,t in enumerate(texts) if re.fullmatch(r'20\d\d',t.strip())]
        if not year_controls: raise RuntimeError(f'year control not found: {texts[:15]}')
        await buttons.nth(year_controls[0][0]).click(); await page.wait_for_timeout(300)
        ytexts=await dialog.locator('button').all_inner_texts()
        years={t.strip() for t in ytexts if re.fullmatch(r'\d{4}',t.strip())}
        if str(year) not in years: raise RuntimeError(f'year {year} absent from picker')
        await select_text_button(dialog,str(year)); await page.wait_for_timeout(300)

        texts=await dialog.locator('button').all_inner_texts()
        current_months=[t.strip() for t in texts if t.strip() in MONTHS]
        if not current_months: raise RuntimeError(f'current month control absent after year selection: {texts[:15]}')
        await select_text_button(dialog,current_months[0]); await page.wait_for_timeout(300)
        mtexts=await dialog.locator('button').all_inner_texts()
        available={t.strip() for t in mtexts if t.strip() in MONTHS}
        if set(MONTHS)-available: raise RuntimeError(f'month picker incomplete: {sorted(available)}')
        await select_text_button(dialog,MONTHS[month-1]); await page.wait_for_timeout(300)

        dtexts=await dialog.locator('button').all_inner_texts()
        if MONTHS[month-1] not in [t.strip() for t in dtexts] or str(year) not in [t.strip() for t in dtexts]:
            raise RuntimeError(f'picker did not return to requested date view {args.month}: {dtexts[:15]}')
        await select_text_button(dialog,'1')
        await select_text_button(dialog,str(last.day))

        def filtered_response(r):
            if API not in r.url.lower(): return False
            pd=r.request.post_data or ''
            return 'publicationDateFrom' in pd and expected_from in pd
        async with page.expect_response(filtered_response,timeout=30000) as filtered_info:
            await select_text_button(dialog,'OK')
        filtered=await filtered_info.value
        if filtered.status!=200: raise RuntimeError(f'filtered BDA search HTTP {filtered.status}')
        body=await filtered.json()
        payload=filtered.request.post_data or ''
        try: parsed_payload=json.loads(payload)
        except Exception: parsed_payload={}
        if parsed_payload.get('publicationDateFrom')!=expected_from:
            raise RuntimeError(f'BOSA from mismatch: {parsed_payload}')
        if parsed_payload.get('publicationDateTo')!=expected_to:
            raise RuntimeError(f'BOSA exclusive-to mismatch: expected {expected_to}, got {parsed_payload}')
        if int(parsed_payload.get('page') or 0)!=1 or int(parsed_payload.get('pageSize') or 0)!=25:
            raise RuntimeError(f'BOSA pagination contract mismatch: {parsed_payload}')

        with gzip.open(raw_path,'wt',encoding='utf-8',newline='') as f:
            current=body
            while True:
                pubs=current.get('publications') or []
                if not isinstance(pubs,list): raise RuntimeError('filtered response publications is not a list')
                pages+=1
                for pub in pubs:
                    d=str(pub.get('publicationDate') or '')[:10]
                    if d: observed_dates.append(d)
                    eid=str(pub.get('publicationWorkspaceId') or pub.get('procedureId') or pub.get('referenceNumber') or '')
                    key=(eid,str(pub.get('referenceNumber') or ''),d)
                    if key in ids: continue
                    ids.add(key)
                    f.write(json.dumps({'month':args.month,'page':pages,'publication':pub},ensure_ascii=False,separators=(',',':'))+'\n')
                    rows+=1
                nxt=page.locator('button[aria-label="pagination.common.nextPage"]')
                if not await nxt.count() or not await nxt.first.is_enabled(): break
                next_page=pages+1
                success=False; last_err=None
                for attempt in range(1,args.retries+1):
                    try:
                        async with page.expect_response(lambda r: API in r.url.lower() and 'publicationDateFrom' in (r.request.post_data or ''),timeout=30000) as ni:
                            await nxt.first.click(timeout=10000)
                        rr=await ni.value
                        if rr.status==200:
                            candidate=await rr.json()
                            pp=json.loads(rr.request.post_data or '{}')
                            if pp.get('publicationDateFrom')==expected_from and pp.get('publicationDateTo')==expected_to and int(pp.get('page') or 0)==next_page:
                                current=candidate; success=True; break
                        last_err=RuntimeError(f'HTTP/payload mismatch status={rr.status}')
                    except Exception as e:
                        last_err=e
                    if attempt<args.retries: await page.wait_for_timeout(min(20000,1000*(2**(attempt-1))))
                if not success: raise RuntimeError(f'month {args.month} page {next_page} failed after retries: {last_err!r}')
                await page.wait_for_timeout(args.delay_ms)
        await browser.close()

    bad_dates=[d for d in observed_dates if not (expected_from<=d<expected_to)]
    status='PASS' if rows>0 and pages>0 and not bad_dates else 'FAIL'
    manifest={
        'source':'Belgium e-Procurement Bulletin of Tenders public BDA','mode':'anonymous_public_ui_month_shard',
        'month':args.month,'publicationDateFrom':expected_from,'publicationDateTo_exclusive':expected_to,
        'page_size':25,'pages':pages,'rows':rows,'unique_event_keys':len(ids),
        'observed_min_date':min(observed_dates) if observed_dates else None,'observed_max_date':max(observed_dates) if observed_dates else None,
        'out_of_window_rows':len(bad_dates),'file':raw_path.name,'bytes':raw_path.stat().st_size,'sha256':sha256(raw_path),
        'safety':'Public anonymous UI only; no headers, cookies, browser storage, auth tokens or credentials persisted.',
        'status':status,
    }
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2),flush=True)
    if status!='PASS': raise SystemExit(2)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--month',required=True);ap.add_argument('--out',default='raw/belgium-months');ap.add_argument('--delay-ms',type=int,default=100);ap.add_argument('--retries',type=int,default=5);main(ap.parse_args())
