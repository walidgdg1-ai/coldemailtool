#!/usr/bin/env python3
"""Patch the Belgium BDA normalizer to the exact public BOSA response fields observed in probes.

This is intentionally a deterministic source rewrite, not a heuristic data transformation. It fixes
localized text selection and field names while preserving the conservative no-fabrication model.
"""
from pathlib import Path

p=Path('tools/tender_normalize_belgium.py')
s=p.read_text(encoding='utf-8')

old="""def pick_i18n(v):
    if v is None:return None
    if isinstance(v,str):return v.strip() or None
    if isinstance(v,list):
        for x in v:
            r=pick_i18n(x)
            if r:return r
        return None
    if isinstance(v,dict):
        for k in ('en','fr','nl','de','EN','FR','NL','DE','value','name','label','title','description'):
            if k in v:
                r=pick_i18n(v[k])
                if r:return r
        for x in v.values():
            r=pick_i18n(x)
            if r:return r
    return str(v) if v not in ('',None) else None
"""
new="""def pick_i18n(v):
    if v is None:return None
    if isinstance(v,str):return v.strip() or None
    if isinstance(v,list):
        # BOSA localized arrays are objects such as {language:'FR', text:'...'}.
        # Prefer the actual text, never the language code.
        for x in v:
            if isinstance(x,dict) and x.get('text') not in (None,''):
                r=pick_i18n(x.get('text'))
                if r:return r
        for x in v:
            r=pick_i18n(x)
            if r:return r
        return None
    if isinstance(v,dict):
        for k in ('text','en','fr','nl','de','EN','FR','NL','DE','value','name','label','title','description'):
            if k in v:
                r=pick_i18n(v[k])
                if r:return r
        for x in v.values():
            r=pick_i18n(x)
            if r:return r
    return str(v) if v not in ('',None) else None
"""
if old not in s:
    raise SystemExit('pick_i18n source block not found; refusing non-deterministic patch')
s=s.replace(old,new,1)

repls={
"org_name=pick_i18n(first(org,'name','names','organisationName','officialName')) or pick_i18n(org)":
"org_name=pick_i18n(first(org,'organisationNames','name','names','organisationName','officialName')) or UNKNOWN",
"title=pick_i18n(first(dossier,'title','titles','name')) or pick_i18n(first(pub,'title','publicationTitle'))":
"title=pick_i18n(first(dossier,'titles','title','name')) or pick_i18n(first(pub,'title','publicationTitle'))",
"description=pick_i18n(first(dossier,'description','descriptions','shortDescription')) or pick_i18n(first(pub,'description'))":
"description=pick_i18n(first(dossier,'descriptions','description','shortDescription')) or pick_i18n(first(pub,'description'))",
"procedure_type=code_value(first(dossier,'procedureType','procedure','procedureTypeCode')) or UNKNOWN":
"procedure_type=code_value(first(dossier,'procurementProcedureType','procedureType','procedure','procedureTypeCode')) or UNKNOWN",
}
for a,b in repls.items():
    if a not in s: raise SystemExit(f'expected source fragment not found: {a}')
    s=s.replace(a,b,1)

# Add transparent coverage metrics if not already present.
needle="'unique_buyers':len(buyers),'exact_ted_reference_links':len(ted_overlap),'tenders_with_exact_ted_reference':sum(1 for x in tenders if x['TED_Overlap_Count']>0),\n        'award_facts_status':'NOT_ASSERTED_FROM_SEARCH_SUMMARY'"
replacement="'unique_buyers':len(buyers),'exact_ted_reference_links':len(ted_overlap),'tenders_with_exact_ted_reference':sum(1 for x in tenders if x['TED_Overlap_Count']>0),\n        'buyer_name_coverage_pct':round(100*sum(x['Buyer_Name']!=UNKNOWN for x in tenders)/max(1,len(tenders)),2),\n        'procedure_type_coverage_pct':round(100*sum(x['Procedure_Type']!=UNKNOWN for x in tenders)/max(1,len(tenders)),2),\n        'title_coverage_pct':round(100*sum(x['Title']!=UNKNOWN for x in tenders)/max(1,len(tenders)),2),\n        'award_facts_status':'NOT_ASSERTED_FROM_SEARCH_SUMMARY'"
if needle in s:
    s=s.replace(needle,replacement,1)

p.write_text(s,encoding='utf-8')
print('BELGIUM_NORMALIZER_RUNTIME_PATCH_APPLIED')
