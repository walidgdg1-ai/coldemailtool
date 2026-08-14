#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json
from datetime import datetime, timezone
from pathlib import Path
import duckdb

# These concepts are not a hand-built replacement for the old ontology: each family below
# is grounded in recurring phrases/cohorts surfaced by Open-World Discovery v2. They are
# intentionally broad enough for historical market sizing, but specific enough to support
# targeted award/competition enrichment. Multi-label assignment is allowed.
CONCEPTS = [
    dict(niche='Software licensing & subscriptions', macro='SOFTWARE_RESALE', pattern=r'(software (licen[cs]e|subscription)|softwarelizenz|software lizenzen|logiciel.{0,20}licen[cs]e|licen[cs]e.{0,20}logiciel|renouvellement.{0,30}licen[cs]e|license renewal|licence renewal)', ai=.15, sub=.98, remote=.98, entry=.72, pain=.88, margin=.72),
    dict(niche='Microsoft licensing & cloud resale', macro='SOFTWARE_RESALE', pattern=r'(microsoft (enterprise|office|azure|unified|365|licen[cs]e)|licen[cs]es? microsoft|microsoft lizenzen|windows server)', ai=.12, sub=.99, remote=.99, entry=.55, pain=.88, margin=.70),
    dict(niche='Adobe / Creative Cloud licensing', macro='SOFTWARE_RESALE', pattern=r'(creative cloud|adobe (licen[cs]e|lizenzen|subscription)|licen[cs]es? adobe)', ai=.12, sub=.99, remote=.99, entry=.58, pain=.90, margin=.68),
    dict(niche='ERP / SAP implementation & support', macro='ENTERPRISE_SOFTWARE', pattern=r'(enterprise resource planning|erp system|sap (hana|hcm|business|s\/4|s4)|\bsap\b.{0,35}(implementation|support|maintenance|migration|system|solution))', ai=.55, sub=.82, remote=.92, entry=.35, pain=.48, margin=.92),
    dict(niche='CRM / Dynamics / Business Central', macro='ENTERPRISE_SOFTWARE', pattern=r'(crm system|microsoft dynamics|business central|customer relationship management|dynamics 365)', ai=.62, sub=.84, remote=.95, entry=.45, pain=.58, margin=.90),
    dict(niche='Cloud infrastructure / VMware', macro='CLOUD_INFRA', pattern=r'(vmware (vsphere|cloud)|private cloud|cloud based|cloud infrastructure|cloud platform|infrastructure as a service|\biaas\b)', ai=.55, sub=.84, remote=.95, entry=.40, pain=.55, margin=.86),
    dict(niche='Cybersecurity / SOC / managed security', macro='CYBER_PARTNERABLE', pattern=r'(security operations cent(re|er)|\bsoc\b.{0,25}(security|service|center|centre)|managed security|palo alto|check point|siem|security monitoring|cyber ?security|cybersecurity)', ai=.65, sub=.86, remote=.95, entry=.38, pain=.50, margin=.92),
    dict(niche='Data platform / warehouse / BI', macro='DATA_SOFTWARE', pattern=r'(data platform|data warehouse|business intelligence|analytics platform|data lake|data mart|etl platform)', ai=.88, sub=.82, remote=.98, entry=.58, pain=.68, margin=.92),
    dict(niche='AI / machine learning solutions', macro='AI_AUTOMATION', pattern=r'(intelligence artificielle|artificial intelligence|machine learning|generative ai|\bgenai\b|\bai platform\b|\bai solution\b|assistant ia|solution ia)', ai=.99, sub=.80, remote=.99, entry=.60, pain=.64, margin=.96),
    dict(niche='Media monitoring / social listening', macro='MONITORING_CONTENT', pattern=r'(media monitoring|social listening|media intelligence|veille mediatique|veille media|monitoring des medias|monitoring media)', ai=.90, sub=.94, remote=.99, entry=.86, pain=.86, margin=.88),
    dict(niche='Audio-visual systems & conferencing', macro='AV_RESALE', pattern=r'(audio video|audio visual|audiovisual|video conferencing|videoconferencing|conference room.{0,20}(audio|video|av)|av equipment)', ai=.32, sub=.98, remote=.58, entry=.72, pain=.72, margin=.82),
    dict(niche='Video surveillance / CCTV', macro='SECURITY_RESALE', pattern=r'(video surveillance|videosurveillance|cctv|camera surveillance|surveillance camera)', ai=.28, sub=.97, remote=.45, entry=.62, pain=.62, margin=.82),
    dict(niche='SaaS business applications', macro='SAAS_SOFTWARE', pattern=r'(mode saas|\bsaas\b|software as a service|solution logicielle|logiciel gestion|solution gestion|business application)', ai=.72, sub=.84, remote=.98, entry=.62, pain=.68, margin=.90),
    dict(niche='Custom software development', macro='SOFTWARE_SERVICES', pattern=r'(software development|application development|developpement logiciel|développement logiciel|developpement applicatif|custom software|custom application|software solution)', ai=.82, sub=.82, remote=.98, entry=.55, pain=.60, margin=.92),
    dict(niche='Managed IT / ICT services', macro='IT_MANAGED', pattern=r'(ict managed|managed it|managed service provider|managed services.{0,20}(ict|it|infrastructure)|it managed services|infogerance|infogérance)', ai=.58, sub=.88, remote=.90, entry=.48, pain=.58, margin=.84),
    dict(niche='Open-source / Red Hat / Linux services', macro='OPEN_SOURCE', pattern=r'(open source|red hat|\blinux\b.{0,30}(support|service|platform|server|subscription)|redhat)', ai=.62, sub=.90, remote=.98, entry=.60, pain=.70, margin=.82),
    dict(niche='IT hardware / laptops / endpoint supply', macro='HARDWARE_RESALE', pattern=r'(hardware software|ordinateurs portables|laptop|notebook computer|desktop computer|workstation|end.?user device|endpoint device)', ai=.08, sub=.99, remote=.80, entry=.78, pain=.82, margin=.58),
    dict(niche='Network / WAN / wireless infrastructure', macro='NETWORK_RESALE', pattern=r'(wide area network|\bwan\b|wireless network|wifi|wi-fi|sans fil|network infrastructure|lan wan)', ai=.20, sub=.96, remote=.65, entry=.58, pain=.64, margin=.78),
    dict(niche='Database / SQL / Oracle services', macro='DATABASE_SOFTWARE', pattern=r'(oracle database|sql server|database management|database platform|database support|database migration)', ai=.68, sub=.86, remote=.98, entry=.50, pain=.62, margin=.90),
    dict(niche='Digital twin solutions', macro='DIGITAL_TWIN', pattern=r'(digital twin|jumeau numerique|jumeau numérique)', ai=.90, sub=.76, remote=.92, entry=.40, pain=.52, margin=.96),
    dict(niche='Technical studies / feasibility studies', macro='PARTNERABLE_STUDIES', pattern=r'(etude faisabilite|étude faisabilité|feasibility stud|bureau etudes|bureau d.etudes|etudes techniques|études techniques|mission etude|mission étude)', ai=.48, sub=.96, remote=.72, entry=.40, pain=.55, margin=.84),
    dict(niche='Graphic design / publishing services', macro='CREATIVE', pattern=r'(conception graphique|graphic design|design publishing|design and publishing|layout design|publication design)', ai=.88, sub=.96, remote=.99, entry=.92, pain=.90, margin=.88),
    dict(niche='Advertising / media placement', macro='MEDIA_BROKERAGE', pattern=r'(espaces publicitaires|advertising space|media placement|media buying|achat media|achat média|publicite digitale|publicité digitale)', ai=.40, sub=.98, remote=.96, entry=.82, pain=.84, margin=.84),
    dict(niche='Information systems implementation', macro='SOFTWARE_SERVICES', pattern=r'(information systems?|information system|systeme information|système information).{0,45}(implementation|moderni[sz]ation|migration|solution|platform|development|developpement)', ai=.72, sub=.82, remote=.95, entry=.52, pain=.62, margin=.88),
]

def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--core',required=True)
    ap.add_argument('--known-matched',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--min-concept-volume',type=int,default=20)
    a=ap.parse_args()
    core=Path(a.core); known=Path(a.known_matched); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    tp=core/'historical_tenders.parquet'
    for p in (tp,known):
        if not p.exists(): raise SystemExit(f'MISSING_INPUT {p}')
    tmp=out/'ducktmp';tmp.mkdir(exist_ok=True)
    con=duckdb.connect();con.execute("SET preserve_insertion_order=false");con.execute("SET threads=2");con.execute("SET memory_limit='6GB'");con.execute(f"SET temp_directory={q(tmp.as_posix())}");con.execute("SET max_temp_directory_size='18GB'")
    cols={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(tp.as_posix())})").fetchall()}
    def c(n,f): return f'"{n}"' if n in cols else f
    desc=c('Description',"''");cat=c('Category',"''");subcat=c('Subcategory',"''");buyer=c('Buyer_ID','NULL::VARCHAR');buyer_name=c('Buyer_Name',"'UNKNOWN'");country=c('Country',"'UNKNOWN'");pub=c('Publication_Date','NULL::DATE');deadline=c('Deadline','NULL::DATE');lean=c('Lean_Fit','NULL::DOUBLE');url=c('Source_URL','NULL::VARCHAR');ref=c('Source_Reference','NULL::VARCHAR')
    total=con.execute(f"select count(*) from read_parquet({q(tp.as_posix())})").fetchone()[0]
    known_n=con.execute(f"select count(*) from read_parquet({q(known.as_posix())})").fetchone()[0]
    residual=out/'residual.parquet'
    con.execute(f"""COPY (
      SELECT t.Warehouse_Source,t.Historical_Tender_ID,cast(t.Title as varchar) Title,cast({desc} as varchar) Description,
             cast({cat} as varchar) Category,cast({subcat} as varchar) Subcategory,cast({buyer} as varchar) Buyer_ID,
             cast({buyer_name} as varchar) Buyer_Name,cast({country} as varchar) Country,try_cast({pub} as date) Publication_Date,
             try_cast({deadline} as date) Deadline,try_cast({lean} as double) Lean_Fit,cast({url} as varchar) Source_URL,cast({ref} as varchar) Source_Reference,
             lower(strip_accents(coalesce(cast(t.Title as varchar),''))) Title_Blob
      FROM read_parquet({q(tp.as_posix())}) t
      ANTI JOIN (select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(known.as_posix())})) k
      USING(Warehouse_Source,Historical_Tender_ID)
    ) TO {q(residual.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    residual_n=con.execute(f"select count(*) from read_parquet({q(residual.as_posix())})").fetchone()[0]
    assert residual_n==total-known_n,(total,known_n,residual_n)

    # Rule table and multi-label matching. Rules are evaluated against title only because v2
    # evidence was title-phrase based; this keeps precision higher than broad description search.
    con.execute("CREATE TEMP TABLE rules(Niche VARCHAR,Macro_Category VARCHAR,Pattern VARCHAR,AI_Leverage DOUBLE,Subcontractability DOUBLE,Remote_Feasibility DOUBLE,Low_Entry_Burden DOUBLE,Low_Execution_Pain DOUBLE,Margin_Potential DOUBLE)")
    for r in CONCEPTS:
        con.execute("INSERT INTO rules VALUES (?,?,?,?,?,?,?,?,?)",[r['niche'],r['macro'],r['pattern'],r['ai'],r['sub'],r['remote'],r['entry'],r['pain'],r['margin']])
    raw=out/'open_world_concept_matches_raw.parquet'
    con.execute(f"""COPY (
      SELECT u.* EXCLUDE(Title_Blob),r.Niche,r.Macro_Category,r.AI_Leverage,r.Subcontractability,r.Remote_Feasibility,
             r.Low_Entry_Burden,r.Low_Execution_Pain,r.Margin_Potential
      FROM read_parquet({q(residual.as_posix())}) u
      JOIN rules r ON regexp_matches(u.Title_Blob,r.Pattern)
    ) TO {q(raw.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")

    con.execute(f"""CREATE TEMP VIEW concept_counts AS
      SELECT Niche,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,count(distinct Warehouse_Source) Source_Count,
             count(distinct Country) Country_Count
      FROM read_parquet({q(raw.as_posix())}) GROUP BY 1""")
    valid=[r[0] for r in con.execute(f"select Niche from concept_counts where Tender_Count>={a.min_concept_volume} order by Tender_Count desc").fetchall()]
    if not valid: raise SystemExit('NO_VALID_CONCEPTS')
    valid_sql=','.join(q(x) for x in valid)
    matched=out/'matched_tenders.parquet'
    con.execute(f"COPY (SELECT * FROM read_parquet({q(raw.as_posix())}) WHERE Niche IN ({valid_sql})) TO {q(matched.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)")

    # Buyer recurrence and concept-level empirical profile.
    con.execute(f"""CREATE TEMP VIEW buyer_niche AS
      SELECT Niche,Warehouse_Source,Buyer_ID,count(*) Tender_Count
      FROM read_parquet({q(matched.as_posix())}) WHERE Buyer_ID IS NOT NULL GROUP BY 1,2,3""")
    matrix=out/'open_world_concept_matrix.csv'
    con.execute(f"""COPY (
      WITH b AS (
        SELECT Niche,any_value(Macro_Category) Macro_Category,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,
               count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count,median(Lean_Fit) Median_Lean_Fit,
               avg(case when Publication_Date>=DATE '2025-08-01' then 1 else 0 end)*100 Recent_12m_Share_Pct,
               any_value(AI_Leverage) AI_Leverage,any_value(Subcontractability) Subcontractability,any_value(Remote_Feasibility) Remote_Feasibility,
               any_value(Low_Entry_Burden) Low_Entry_Burden,any_value(Low_Execution_Pain) Low_Execution_Pain,any_value(Margin_Potential) Margin_Potential
        FROM read_parquet({q(matched.as_posix())}) GROUP BY 1
      ),r AS (
        SELECT Niche,sum(Tender_Count) FILTER(WHERE Tender_Count>=3) Repeat_Tenders,
               count(*) FILTER(WHERE Tender_Count>=3) Repeat_Buyers
        FROM buyer_niche GROUP BY 1
      ),p AS (
        SELECT b.*,coalesce(r.Repeat_Tenders,0) Repeat_Tenders,coalesce(r.Repeat_Buyers,0) Repeat_Buyers,
               100.0*coalesce(r.Repeat_Tenders,0)/nullif(b.Tender_Count,0) Repeat_Tender_Share_Pct,
               100.0*percent_rank() over(order by ln(1+b.Tender_Count)) Volume_Pct,
               100.0*percent_rank() over(order by ln(1+b.Unique_Buyers)) Buyer_Breadth_Pct,
               100.0*percent_rank() over(order by 100.0*coalesce(r.Repeat_Tenders,0)/nullif(b.Tender_Count,0)) Repeat_Pct,
               100.0*percent_rank() over(order by coalesce(b.Recent_12m_Share_Pct,0)) Recency_Pct,
               100.0*percent_rank() over(order by coalesce(b.Median_Lean_Fit,0)) Lean_Pct
        FROM b LEFT JOIN r USING(Niche)
      )
      SELECT *,
        0.24*Volume_Pct+0.18*Buyer_Breadth_Pct+0.20*Repeat_Pct+0.13*Recency_Pct+0.15*Lean_Pct+0.10*(100.0*Margin_Potential) Discovery_Score,
        0.24*Volume_Pct+0.16*Buyer_Breadth_Pct+0.13*Repeat_Pct+0.17*(100.0*Low_Entry_Burden)+0.15*(100.0*Low_Execution_Pain)+0.15*(100.0*Remote_Feasibility) Easy_Money_Proxy,
        0.45*Discovery_Score+0.40*(100.0*AI_Leverage)+0.15*(100.0*Remote_Feasibility) AI_Leverage_Score,
        0.42*Discovery_Score+0.38*(100.0*Subcontractability)+0.10*(100.0*Low_Entry_Burden)+0.10*(100.0*Margin_Potential) Middleman_Proxy,
        'OPEN_WORLD_CONCEPTS_V1_EMPIRICAL_PLUS_EXPLICIT_HEURISTICS' Score_Contract,'DERIVED' Derived_Status
      FROM p ORDER BY Discovery_Score DESC
    ) TO {q(matrix.as_posix())} (HEADER)""")

    # Representative examples per concept for later semantic sanity checks.
    con.execute(f"""COPY (
      WITH x AS (
        SELECT *,row_number() over(partition by Niche order by Publication_Date desc nulls last,Historical_Tender_ID) rn
        FROM read_parquet({q(matched.as_posix())})
      ) SELECT * EXCLUDE(rn) FROM x WHERE rn<=12 ORDER BY Niche,Publication_Date DESC
    ) TO {q((out/'representative_tenders_by_concept.csv').as_posix())} (HEADER)""")

    rows=list(csv.DictReader(open(matrix,encoding='utf-8')))
    matched_rows=con.execute(f"select count(*) from read_parquet({q(matched.as_posix())})").fetchone()[0]
    unique_tenders=con.execute(f"select count(distinct Warehouse_Source||'|'||Historical_Tender_ID) from read_parquet({q(matched.as_posix())})").fetchone()[0]
    quality={'status':'PASS' if len(rows)>=10 and unique_tenders>=500 else 'FAIL','generated_at':datetime.now(timezone.utc).isoformat(),'source_core_tenders':total,'known_spm_rows':known_n,'residual_tenders':residual_n,'concept_rules':len(CONCEPTS),'retained_concepts':len(rows),'concept_match_rows':matched_rows,'unique_residual_tenders_matched':unique_tenders,'multi_label_rows':matched_rows-unique_tenders,'min_concept_volume':a.min_concept_volume,'contract':'DATA_DERIVED_OPEN_WORLD_CONCEPTS_V1: rules consolidated from v2 recurring phrases; title-only matching; known SPM anti-joined; no DCE'}
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    if quality['status']!='PASS': raise SystemExit(f'QA_FAILED {quality}')
    lines=['# SPM Open-World Concepts v1','',f'- Residual tenders scanned: **{residual_n:,}**',f'- Data-derived concept rules: **{len(CONCEPTS)}**',f'- Retained concepts: **{len(rows)}**',f'- Unique residual tenders newly classified: **{unique_tenders:,}**',f'- Multi-label concept rows: **{matched_rows:,}**','','## Concepts','','|#|Concept|Tenders|Buyers|Sources|Countries|Lean|Discovery|Easy money|Middleman|','|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for i,r in enumerate(sorted(rows,key=lambda x:float(x['Discovery_Score']),reverse=True),1):
        lines.append(f"|{i}|{r['Niche']}|{int(float(r['Tender_Count'])):,}|{int(float(r['Unique_Buyers'])):,}|{r['Source_Count']}|{r['Country_Count']}|{float(r['Median_Lean_Fit'] or 0):.1f}|{float(r['Discovery_Score']):.1f}|{float(r['Easy_Money_Proxy']):.1f}|{float(r['Middleman_Proxy']):.1f}|")
    lines += ['','These are historical concept priors, not live bid decisions. Partner/reseller/certification requirements remain unresolved until a specific live tender is evaluated.']
    (out/'CONCEPT_READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OPEN_WORLD_CONCEPTS_PASS',json.dumps(quality,sort_keys=True))

if __name__=='__main__': main()
