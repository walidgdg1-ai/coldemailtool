#!/usr/bin/env python3
from pathlib import Path
import csv,re

ROOT=Path('tender_pipeline/analysis/spm_tender_discovery_v1')
mat=ROOT/'top50_discovery.csv'; ex=ROOT/'representative_tenders.csv'
if not mat.exists() or not ex.exists(): raise SystemExit('DISCOVERY_OUTPUTS_MISSING')

with mat.open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
with ex.open(encoding='utf-8',newline='') as f: examples=list(csv.DictReader(f))
by={}
for r in examples: by.setdefault(r['Niche'],[]).append(r)

# Review signals are deliberately conservative and only flag possible contamination/complexity.
flags=[
 ('ENTERPRISE_SOFTWARE',re.compile(r'\b(erp|sap|oracle|enterprise|platform|système d.information|information system|data center|cloud migration|infrastructure)\b',re.I)),
 ('CONSTRUCTION_ENGINEERING',re.compile(r'\b(construction|works|travaux|engineering|ingénierie|facility|building|road|bridge)\b',re.I)),
 ('MEDICAL_REGULATED',re.compile(r'\b(medical|hospital|healthcare|pharma|clinical|santé|hôpital|hospitalier)\b',re.I)),
 ('AUDIT_LEGAL_FINANCE',re.compile(r'\b(audit|legal|law|financial audit|statutory|accounting|juridique)\b',re.I)),
 ('LARGE_FRAMEWORK',re.compile(r'\b(framework|accord.?cadre|framework agreement|multi.?supplier|dynamic purchasing)\b',re.I)),
 ('ONSITE_PHYSICAL',re.compile(r'\b(on.?site|sur site|installation|delivery and installation|pose|maintenance hardware)\b',re.I)),
]

def review(title):
    hits=[name for name,rx in flags if rx.search(title or '')]
    return '|'.join(hits) if hits else 'NO_OBVIOUS_RED_FLAG'

out=[]
out += ['# SPM Tender Discovery — Review Pack v1','',
        'This pack is generated from the full-corpus tender-only discovery pass. Flags are **review prompts**, not automatic rejections.','']
for i,r in enumerate(rows[:30],1):
    niche=r['Niche']; ers=by.get(niche,[])
    out += [f'## {i}. {niche}', '',
            f"**Discovery score:** {float(r['Discovery_Score']):.1f} · **Tenders:** {int(float(r['Tender_Count'])):,} · **Buyers:** {int(float(r['Unique_Buyers'])):,} · **Repeat share:** {float(r['Repeat_Tender_Share_Pct']):.1f}% · **Recent 12m:** {float(r['Recent_12m_Share_Pct']):.1f}% · **Median Lean_Fit:** {r['Median_Lean_Fit']}", '',
            '| Date | Country | Buyer | Title | Est. value | Review flag |',
            '|---|---|---|---|---:|---|']
    for e in ers[:12]:
        title=(e.get('Title') or '').replace('|','/').replace('\n',' ')
        buyer=(e.get('Buyer_Name') or 'UNKNOWN').replace('|','/').replace('\n',' ')
        val=e.get('Official_Estimated_Value') or 'UNKNOWN'; cur=e.get('Currency') or ''
        out.append(f"| {e.get('Publication_Date') or ''} | {e.get('Country') or ''} | {buyer[:70]} | {title[:180]} | {val} {cur} | {review(title)} |")
    out.append('')

(ROOT/'REVIEW_PACK.md').write_text('\n'.join(out)+'\n',encoding='utf-8')
print('SPM_REVIEW_PACK_PASS',len(rows),len(examples))
