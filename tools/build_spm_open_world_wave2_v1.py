#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json
from datetime import datetime, timezone
from pathlib import Path
import duckdb

# Wave 2 is deliberately different from wave 1: concepts below were seeded by recurring
# multi-word signals in Open-World Discovery v2, with emphasis on communications, operations,
# partnerable field services, and software-adjacent markets not already captured. Title-only
# matching preserves the evidence contract used by the source phrase discovery.
CONCEPTS = [
    dict(niche='Communications campaigns & public relations', macro='COMMUNICATIONS', pattern=r'(campagn(e|es) communication|communication campaign|communications campaign|relations publiques|public relations|communication institutionnelle|plan communication|accompagnement communication|strategie communication|communication strategy)', ai=.88, sub=.97, remote=.98, entry=.88, pain=.84, margin=.88),
    dict(niche='Social media management & community', macro='COMMUNICATIONS', pattern=r'(social media (management|services?|campaign)|community management|gestion reseaux sociaux|gestion des reseaux sociaux|media sociaux|reseaux sociaux)', ai=.94, sub=.96, remote=.99, entry=.92, pain=.86, margin=.90),
    dict(niche='LMS / e-learning platforms', macro='LEARNING_TECH', pattern=r'(learning management system|systeme lms|\blms\b|e[- ]?learning platform|elearning platform|plateforme (de )?formation|learning platform)', ai=.82, sub=.90, remote=.99, entry=.68, pain=.72, margin=.90),
    dict(niche='Telephony / VoIP / unified communications', macro='TELECOM_RESALE', pattern=r'(systeme telephonie|telephony system|telephone system|ip telephony|voip|unified communications|fixe mobile|fixed mobile|communications unifiees)', ai=.28, sub=.97, remote=.78, entry=.64, pain=.68, margin=.78),
    dict(niche='Call center / contact center services & platforms', macro='CONTACT_CENTER', pattern=r'(centre appel|centre d appel|call cent(er|re)|contact cent(er|re)|centre de contact|contact center platform|contact centre platform)', ai=.78, sub=.96, remote=.95, entry=.72, pain=.68, margin=.84),
    dict(niche='Data migration services', macro='DATA_SERVICES', pattern=r'(data migration|migration de donnees|migration donnees|migration des donnees|database migration|migration vers (le )?(cloud|saas|microsoft|office|systeme|solution|plateforme))', ai=.90, sub=.90, remote=.99, entry=.66, pain=.72, margin=.92),
    dict(niche='Identity / SSO / access management', macro='IDENTITY_SECURITY', pattern=r'(single sign[- ]?on|identity (and )?access management|identity management|gestion (des )?identites|gestion (des )?identites et acces|access management platform|\bsso\b)', ai=.72, sub=.88, remote=.98, entry=.52, pain=.62, margin=.90),
    dict(niche='Backup / disaster recovery / storage', macro='INFRA_RESALE', pattern=r'(backup solution|backup service|sauvegarde informatique|solution sauvegarde|copias seguridad|disaster recovery|veeam|storage solution|solution stockage|server storage|equipements stockage|data protection platform)', ai=.38, sub=.96, remote=.88, entry=.62, pain=.68, margin=.80),
    dict(niche='GIS / geospatial information systems', macro='GEO_SOFTWARE', pattern=r'(geographic information system|geographical information system|systeme information geographique|systeme d information geographique|information geographique|geospatial platform|geospatial information system)', ai=.78, sub=.88, remote=.96, entry=.54, pain=.62, margin=.88),
    dict(niche='Document management / ECM / GED', macro='DOCUMENT_SOFTWARE', pattern=r'(gestion documental|document management system|electronic document management|gestion electronique (des )?documents|enterprise content management|content management system.{0,20}document|systeme gestion documentaire)', ai=.86, sub=.90, remote=.99, entry=.70, pain=.76, margin=.90),
    dict(niche='CAFM / facilities management software', macro='FACILITY_SOFTWARE', pattern=r'(cafm software|\bcafm\b|computer aided facility management|facilit(y|ies) management (software|system)|facility management platform)', ai=.66, sub=.90, remote=.98, entry=.62, pain=.68, margin=.88),
    dict(niche='HR / workforce / time management software', macro='HR_SOFTWARE', pattern=r'(gestion temps|time management system|workforce management|human resources management system|hr management system|gestion ressources humaines|gestion des ressources humaines|hr software|rh software)', ai=.78, sub=.90, remote=.99, entry=.68, pain=.72, margin=.90),
    dict(niche='Fleet management software & services', macro='FLEET', pattern=r'(gestion flotte|gestion de flotte|fleet management|fleet tracking|vehicle fleet management)', ai=.62, sub=.92, remote=.90, entry=.66, pain=.68, margin=.84),
    dict(niche='Project / portfolio management software', macro='PROJECT_SOFTWARE', pattern=r'(project portfolio management|portefeuille projets|gestion portefeuille projets|project management platform|project management software)', ai=.74, sub=.90, remote=.99, entry=.68, pain=.72, margin=.88),
    dict(niche='Citizen engagement / participation platforms', macro='CIVIC_TECH', pattern=r'(participation citoyenne|citizen engagement|citizen participation|public participation platform|plateforme participation|plateforme de participation|democratie participative)', ai=.82, sub=.92, remote=.99, entry=.78, pain=.78, margin=.88),
    dict(niche='Market research / surveys / data collection', macro='RESEARCH_SERVICES', pattern=r'(market research|etude de marche|collecte donnees|collecte de donnees|data collection services?|survey services?|enquete (de )?(satisfaction|opinion)|opinion poll|customer survey)', ai=.92, sub=.96, remote=.96, entry=.84, pain=.82, margin=.88),
    dict(niche='Press review / clipping services', macro='MONITORING_CONTENT', pattern=r'(revue presse|revue de presse|press review|press clipping|clipping service|press monitoring)', ai=.96, sub=.98, remote=.99, entry=.92, pain=.90, margin=.90),
    dict(niche='E-government / electronic administration platforms', macro='GOVTECH', pattern=r'(sede electronica|administracion electronica|electronic administration|e[- ]?government platform|digital government platform|electronic government|e-services portal|public services portal)', ai=.78, sub=.86, remote=.99, entry=.52, pain=.62, margin=.90),
    dict(niche='Asset management software', macro='ASSET_SOFTWARE', pattern=r'(asset management software|software asset management|enterprise asset management|gestion (des )?actifs|asset management system|eam system)', ai=.72, sub=.88, remote=.98, entry=.60, pain=.66, margin=.88),
    dict(niche='Electronic signature / trust services', macro='TRUST_SERVICES', pattern=r'(electronic signature|digital signature|signature electronique|e[- ]?signature|esignature|electronic seal|cachet electronique)', ai=.62, sub=.94, remote=.99, entry=.72, pain=.78, margin=.84),
    dict(niche='Online payments / payment platforms', macro='PAYMENTS', pattern=r'(payment platform|payment gateway|online payment|paiement en ligne|electronic payment|plateforme paiement|solution de paiement)', ai=.54, sub=.88, remote=.99, entry=.48, pain=.56, margin=.88),
    dict(niche='Mobile application development', macro='SOFTWARE_SERVICES', pattern=r'(mobile application|mobile app|application mobile|applications mobiles|app mobile|developpement application mobile|mobile application development)', ai=.90, sub=.92, remote=.99, entry=.76, pain=.76, margin=.92),
    dict(niche='Procurement / e-sourcing platforms', macro='PROCUREMENT_TECH', pattern=r'(e[- ]?procurement|procurement platform|sourcing platform|source to pay|purchase to pay|procure to pay|electronic procurement|plateforme achats)', ai=.72, sub=.86, remote=.99, entry=.50, pain=.60, margin=.90),
    dict(niche='Ticketing / booking / reservation systems', macro='TRANSACTION_SOFTWARE', pattern=r'(ticketing system|booking system|reservation system|systeme billetterie|gestion billetterie|billetterie en ligne|online booking platform|reservation platform)', ai=.76, sub=.90, remote=.99, entry=.64, pain=.68, margin=.90),
    dict(niche='Structured cabling / network installation', macro='FIELD_SUBCONTRACT', pattern=r'(installation cablage|cablage reseau|structured cabling|network cabling|data cabling|cabling installation|cablage informatique)', ai=.10, sub=.99, remote=.30, entry=.72, pain=.58, margin=.76),
    dict(niche='Access control / intrusion systems', macro='SECURITY_RESALE', pattern=r'(controle acces|controle d acces|access control system|intrusion controle|intrusion detection system|systeme intrusion|access control solution)', ai=.24, sub=.98, remote=.42, entry=.66, pain=.62, margin=.80),
    dict(niche='Topographic / land surveying services', macro='FIELD_SUBCONTRACT', pattern=r'(leves topographiques|leve topographique|topographic survey|topographical survey|land surveying|land survey services|surveying services)', ai=.30, sub=.99, remote=.34, entry=.48, pain=.50, margin=.84),
    dict(niche='Geotechnical investigations & studies', macro='FIELD_SUBCONTRACT', pattern=r'(investigations geotechniques|etudes geotechniques|etude geotechnique|mission etudes geotechniques|geotechnical investigation|geotechnical stud)', ai=.28, sub=.99, remote=.38, entry=.34, pain=.44, margin=.86),
    dict(niche='Environmental studies / contaminated land / GHG', macro='SPECIALIST_CONSULTING', pattern=r'(sites sols pollues|sols pollues|contaminated (land|soil)|environmental assessment|environmental stud|emissions gaz effet|gaz a effet de serre|greenhouse gas|ghg assessment|biodiversity stud)', ai=.48, sub=.98, remote=.62, entry=.36, pain=.50, margin=.86),
    dict(niche='Architectural programming / pre-design studies', macro='SPECIALIST_CONSULTING', pattern=r'(programmation architecturale|architectural programming|etude pre operationnelle|etude pre-operationnelle|pre[- ]?operational stud|etude urbaine|urban stud)', ai=.52, sub=.98, remote=.72, entry=.38, pain=.52, margin=.86),
    dict(niche='Laboratory / hospital information systems', macro='HEALTH_IT', pattern=r'(ris pacs|laboratory information system|hospital information system|health information system|laboratory management system|clinical information system)', ai=.62, sub=.84, remote=.94, entry=.30, pain=.42, margin=.92),
    dict(niche='CRM-adjacent customer service platforms', macro='CUSTOMER_SERVICE_SOFTWARE', pattern=r'(customer service platform|customer experience platform|case management platform|service management platform|client management platform)', ai=.80, sub=.88, remote=.99, entry=.60, pain=.66, margin=.90),
]

def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--core',required=True)
    ap.add_argument('--known-matched',required=True)
    ap.add_argument('--wave1-matched',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--min-concept-volume',type=int,default=20)
    a=ap.parse_args()
    core=Path(a.core); known=Path(a.known_matched); wave1=Path(a.wave1_matched); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    tp=core/'historical_tenders.parquet'
    for p in (tp,known,wave1):
        if not p.exists(): raise SystemExit(f'MISSING_INPUT {p}')
    tmp=out/'ducktmp'; tmp.mkdir(exist_ok=True)
    con=duckdb.connect(); con.execute("SET preserve_insertion_order=false"); con.execute("SET threads=2"); con.execute("SET memory_limit='6GB'"); con.execute(f"SET temp_directory={q(tmp.as_posix())}"); con.execute("SET max_temp_directory_size='18GB'")
    cols={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(tp.as_posix())})").fetchall()}
    def c(n,f): return f'"{n}"' if n in cols else f
    desc=c('Description',"''"); cat=c('Category',"''"); subcat=c('Subcategory',"''"); buyer=c('Buyer_ID','NULL::VARCHAR'); buyer_name=c('Buyer_Name',"'UNKNOWN'"); country=c('Country',"'UNKNOWN'"); pub=c('Publication_Date','NULL::DATE'); deadline=c('Deadline','NULL::DATE'); lean=c('Lean_Fit','NULL::DOUBLE'); url=c('Source_URL','NULL::VARCHAR'); ref=c('Source_Reference','NULL::VARCHAR')
    total=con.execute(f"select count(*) from read_parquet({q(tp.as_posix())})").fetchone()[0]
    known_rows=con.execute(f"select count(*) from read_parquet({q(known.as_posix())})").fetchone()[0]
    wave1_rows=con.execute(f"select count(*) from read_parquet({q(wave1.as_posix())})").fetchone()[0]
    excluded_unique=con.execute(f"""select count(*) from (
      select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(known.as_posix())})
      union
      select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(wave1.as_posix())})
    )""").fetchone()[0]
    residual=out/'residual_after_wave1.parquet'
    con.execute(f"""COPY (
      SELECT t.Warehouse_Source,t.Historical_Tender_ID,cast(t.Title as varchar) Title,cast({desc} as varchar) Description,
             cast({cat} as varchar) Category,cast({subcat} as varchar) Subcategory,cast({buyer} as varchar) Buyer_ID,
             cast({buyer_name} as varchar) Buyer_Name,cast({country} as varchar) Country,try_cast({pub} as date) Publication_Date,
             try_cast({deadline} as date) Deadline,try_cast({lean} as double) Lean_Fit,cast({url} as varchar) Source_URL,cast({ref} as varchar) Source_Reference,
             lower(strip_accents(coalesce(cast(t.Title as varchar),''))) Title_Blob
      FROM read_parquet({q(tp.as_posix())}) t
      ANTI JOIN (
        select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(known.as_posix())})
        union
        select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(wave1.as_posix())})
      ) k USING(Warehouse_Source,Historical_Tender_ID)
    ) TO {q(residual.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    residual_n=con.execute(f"select count(*) from read_parquet({q(residual.as_posix())})").fetchone()[0]
    assert residual_n==total-excluded_unique,(total,excluded_unique,residual_n)

    con.execute("CREATE TEMP TABLE rules(Niche VARCHAR,Macro_Category VARCHAR,Pattern VARCHAR,AI_Leverage DOUBLE,Subcontractability DOUBLE,Remote_Feasibility DOUBLE,Low_Entry_Burden DOUBLE,Low_Execution_Pain DOUBLE,Margin_Potential DOUBLE)")
    for r in CONCEPTS:
        con.execute("INSERT INTO rules VALUES (?,?,?,?,?,?,?,?,?)",[r['niche'],r['macro'],r['pattern'],r['ai'],r['sub'],r['remote'],r['entry'],r['pain'],r['margin']])
    combined='('+'|'.join('(?:'+r['pattern']+')' for r in CONCEPTS)+')'
    candidates=out/'wave2_prefilter_candidates.parquet'
    con.execute(f"""COPY (
      SELECT * FROM read_parquet({q(residual.as_posix())}) WHERE regexp_matches(Title_Blob,{q(combined)})
    ) TO {q(candidates.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    raw=out/'wave2_matches_raw.parquet'
    con.execute(f"""COPY (
      SELECT u.* EXCLUDE(Title_Blob),r.Niche,r.Macro_Category,r.AI_Leverage,r.Subcontractability,r.Remote_Feasibility,
             r.Low_Entry_Burden,r.Low_Execution_Pain,r.Margin_Potential
      FROM read_parquet({q(candidates.as_posix())}) u
      JOIN rules r ON regexp_matches(u.Title_Blob,r.Pattern)
    ) TO {q(raw.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.execute(f"""CREATE TEMP VIEW concept_counts AS
      SELECT Niche,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count
      FROM read_parquet({q(raw.as_posix())}) GROUP BY 1""")
    valid=[r[0] for r in con.execute(f"select Niche from concept_counts where Tender_Count>={a.min_concept_volume} order by Tender_Count desc").fetchall()]
    if not valid: raise SystemExit('NO_VALID_WAVE2_CONCEPTS')
    valid_sql=','.join(q(x) for x in valid)
    matched=out/'matched_tenders.parquet'
    con.execute(f"COPY (SELECT * FROM read_parquet({q(raw.as_posix())}) WHERE Niche IN ({valid_sql})) TO {q(matched.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"""CREATE TEMP VIEW buyer_niche AS
      SELECT Niche,Warehouse_Source,Buyer_ID,count(*) Tender_Count FROM read_parquet({q(matched.as_posix())}) WHERE Buyer_ID IS NOT NULL GROUP BY 1,2,3""")
    matrix=out/'open_world_wave2_matrix.csv'
    con.execute(f"""COPY (
      WITH b AS (
        SELECT Niche,any_value(Macro_Category) Macro_Category,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,
               count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count,median(Lean_Fit) Median_Lean_Fit,
               avg(case when Publication_Date>=DATE '2025-08-01' then 1 else 0 end)*100 Recent_12m_Share_Pct,
               any_value(AI_Leverage) AI_Leverage,any_value(Subcontractability) Subcontractability,any_value(Remote_Feasibility) Remote_Feasibility,
               any_value(Low_Entry_Burden) Low_Entry_Burden,any_value(Low_Execution_Pain) Low_Execution_Pain,any_value(Margin_Potential) Margin_Potential
        FROM read_parquet({q(matched.as_posix())}) GROUP BY 1
      ),r AS (
        SELECT Niche,sum(Tender_Count) FILTER(WHERE Tender_Count>=3) Repeat_Tenders,count(*) FILTER(WHERE Tender_Count>=3) Repeat_Buyers FROM buyer_niche GROUP BY 1
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
        'OPEN_WORLD_WAVE2_EMPIRICAL_PLUS_EXPLICIT_HEURISTICS' Score_Contract,'DERIVED' Derived_Status
      FROM p ORDER BY Discovery_Score DESC
    ) TO {q(matrix.as_posix())} (HEADER)""")
    con.execute(f"""COPY (
      WITH x AS (SELECT *,row_number() over(partition by Niche order by Publication_Date desc nulls last,Historical_Tender_ID) rn FROM read_parquet({q(matched.as_posix())}))
      SELECT * EXCLUDE(rn) FROM x WHERE rn<=12 ORDER BY Niche,Publication_Date DESC
    ) TO {q((out/'representative_tenders_by_concept.csv').as_posix())} (HEADER)""")
    rows=list(csv.DictReader(open(matrix,encoding='utf-8')))
    matched_rows=con.execute(f"select count(*) from read_parquet({q(matched.as_posix())})").fetchone()[0]
    unique_tenders=con.execute(f"select count(distinct Warehouse_Source||'|'||Historical_Tender_ID) from read_parquet({q(matched.as_posix())})").fetchone()[0]
    quality={'status':'PASS' if len(rows)>=10 and unique_tenders>=500 else 'FAIL','generated_at':datetime.now(timezone.utc).isoformat(),'source_core_tenders':total,'known_spm_rows':known_rows,'wave1_match_rows':wave1_rows,'excluded_unique_before_wave2':excluded_unique,'residual_after_wave1':residual_n,'concept_rules':len(CONCEPTS),'retained_concepts':len(rows),'concept_match_rows':matched_rows,'unique_wave2_tenders':unique_tenders,'multi_label_rows':matched_rows-unique_tenders,'min_concept_volume':a.min_concept_volume,'contract':'DATA_DERIVED_OPEN_WORLD_WAVE2_V1: seeded from v2 recurring phrases; original SPM + wave1 anti-joined; title-only; no DCE'}
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    if quality['status']!='PASS': raise SystemExit(f'QA_FAILED {quality}')
    lines=['# SPM Open-World Wave 2 v1','',f'- Residual tenders after original SPM + wave 1 exclusions: **{residual_n:,}**',f'- Wave 2 rules: **{len(CONCEPTS)}**',f'- Retained concepts: **{len(rows)}**',f'- Net-new unique tenders classified: **{unique_tenders:,}**',f'- Multi-label rows: **{matched_rows:,}**','','## Concepts','','|#|Concept|Tenders|Buyers|Sources|Countries|Lean|Discovery|Easy money|Middleman|','|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for i,r in enumerate(sorted(rows,key=lambda x:float(x['Discovery_Score']),reverse=True),1):
        lines.append(f"|{i}|{r['Niche']}|{int(float(r['Tender_Count'])):,}|{int(float(r['Unique_Buyers'])):,}|{r['Source_Count']}|{r['Country_Count']}|{float(r['Median_Lean_Fit'] or 0):.1f}|{float(r['Discovery_Score']):.1f}|{float(r['Easy_Money_Proxy']):.1f}|{float(r['Middleman_Proxy']):.1f}|")
    lines += ['','Wave 2 is net-new against the original SPM ontology and open-world wave 1. Historical scores are priors only; live eligibility/certification/reseller requirements remain unresolved until notice/DCE evaluation.']
    (out/'WAVE2_READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OPEN_WORLD_WAVE2_PASS',json.dumps(quality,sort_keys=True))

if __name__=='__main__': main()
