#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json
from datetime import datetime, timezone
from pathlib import Path
import duckdb

# Wave 3 targets two gaps exposed by Open-World Discovery v2 after waves 1/2:
# (1) recurring non-English procurement language missed by EN/FR-heavy rules, and
# (2) high-repeat specialist/middleman cohorts with clear multi-word title signals.
CONCEPTS = [
    dict(niche='Multilingual information systems & modernization', macro='SOFTWARE_SERVICES', pattern=r'(sistemas? informacion|sistema informativo|sistemi informativi|informacniho systemu|informacneho systemu|sistemului informatic|sistem informatic|informacijas sistemas|systemu informatycznego|systemu informacyjnego)', ai=.78, sub=.86, remote=.97, entry=.54, pain=.62, margin=.90),
    dict(niche='Multilingual software maintenance & support', macro='SOFTWARE_SERVICES', pattern=r'(soporte mantenimiento|mantenimiento software|assistenza manutenzione|manutenzione software|asysty technicznej|wsparcia technicznego|wsparciem technicznym|supporto manutenzione|soporte tecnico software|mantenimiento aplicacion)', ai=.76, sub=.90, remote=.98, entry=.60, pain=.66, margin=.88),
    dict(niche='Multilingual software implementation & development', macro='SOFTWARE_SERVICES', pattern=r'(desarrollo implantacion|diseno desarrollo|diseño desarrollo|wdrozenie rozwiazan|zakup wdrozenie|dostawa wdrozenie|leveren implementeren|implementacao sistema|implementacion sistema|implementazione sistema|desenvolvimento implementacao)', ai=.84, sub=.90, remote=.97, entry=.56, pain=.62, margin=.90),
    dict(niche='Multilingual software licences & subscriptions', macro='SOFTWARE_RESALE', pattern=r'(aquisicao licenciamento|aquisicao de licenciamento|licenciamento microsoft|suscripcion licencias|adquisicion licencias|renovacao licenciamento|programines irangos licenciju|licenciju nuoma|dostawa subskrypcji|zakup subskrypcji|licencias software|licencias de software)', ai=.14, sub=.99, remote=.99, entry=.70, pain=.88, margin=.72),
    dict(niche='Multilingual SaaS / cloud services', macro='SAAS_SOFTWARE', pattern=r'(solutions infonuagiques|infonuagiques solutions|saas reliees|paas saas|solutions iaas paas|modalita saas|solucao saas|solucao em saas|plataforma saas|servico saas|servico em nuvem)', ai=.66, sub=.88, remote=.99, entry=.58, pain=.68, margin=.88),
    dict(niche='Multilingual business management software', macro='BUSINESS_SOFTWARE', pattern=r'(progiciel gestion|software gestion|sistemas? gestion|sistemas? gestao|logiciels gestion|solution integree|systeme integre gestion|outil gestion|plataforma gestao|plateforme gestion|aplicacion gestion)', ai=.76, sub=.88, remote=.98, entry=.62, pain=.70, margin=.90),
    dict(niche='Multilingual IT equipment & infrastructure supply', macro='HARDWARE_RESALE', pattern=r'(equipement informatique|equipements informatiques|echipamente hardware|accessoires informatiques|strojne opreme|dostawa infrastruktury|server hardware|gpu server|sprzet komputerowy|equipos informaticos)', ai=.10, sub=.99, remote=.76, entry=.76, pain=.78, margin=.60),
    dict(niche='Google Workspace licensing & services', macro='SOFTWARE_RESALE', pattern=r'(google workspace|google cloud workspace|workspace licences|workspace licenses)', ai=.18, sub=.98, remote=.99, entry=.62, pain=.84, margin=.70),
    dict(niche='Autodesk / CAD licensing & services', macro='SOFTWARE_RESALE', pattern=r'(licences autodesk|autodesk licen[cs]e|autodesk subscription|autocad licen[cs]e|autocad subscription)', ai=.22, sub=.98, remote=.99, entry=.60, pain=.82, margin=.72),
    dict(niche='Citrix / VDI / virtual desktop', macro='ENDPOINT_CLOUD', pattern=r'(citrix lizenzen|citrix licen[cs]e|citrix virtual|omnissa horizon|virtual desktop infrastructure|\bvdi\b.{0,25}(solution|platform|service))', ai=.50, sub=.92, remote=.98, entry=.50, pain=.60, margin=.84),
    dict(niche='EDR / XDR / endpoint security', macro='CYBER_PARTNERABLE', pattern=r'(edr xdr|endpoint protection|endpoint security|extended detection response|endpoint detection response|xdr solution|edr solution)', ai=.68, sub=.90, remote=.97, entry=.50, pain=.60, margin=.88),
    dict(niche='Cybersecurity awareness & training', macro='CYBER_TRAINING', pattern=r'(security awareness|cybersecurity awareness|cyber awareness|phishing simulation|awareness training|sensibilisation cyber|formation cybersecurite)', ai=.88, sub=.96, remote=.99, entry=.82, pain=.80, margin=.90),
    dict(niche='Data processing / analytics services', macro='DATA_SERVICES', pattern=r'(traitement donnees|traitement de donnees|analyse donnees|analyse de donnees|data processing services?|data analytics services?|analytics services)', ai=.96, sub=.92, remote=.99, entry=.76, pain=.72, margin=.92),
    dict(niche='Reporting / dashboard systems', macro='DATA_SOFTWARE', pattern=r'(reporting system|reporting platform|dashboard platform|dashboard solution|business reporting|systeme reporting|outil reporting)', ai=.90, sub=.90, remote=.99, entry=.72, pain=.72, margin=.90),
    dict(niche='Communication materials & campaign support', macro='CREATIVE_MIDDLEMAN', pattern=r'(supports communication|supports de communication|communication materials|campagne publicitaire|campagnes publicitaires|advertising campaign materials|materiels? promotionnels)', ai=.82, sub=.98, remote=.92, entry=.90, pain=.86, margin=.86),
    dict(niche='Employer branding / recruitment marketing', macro='COMMUNICATIONS', pattern=r'(marque employeur|employer brand|employer branding|recruitment marketing|campagne recrutement|recruitment campaign)', ai=.92, sub=.96, remote=.99, entry=.90, pain=.86, margin=.90),
    dict(niche='Video capture / webcast / event AV', macro='MEDIA_PRODUCTION', pattern=r'(captation video|sonorisation video|video capture|event video|webcast service|webcasting|live streaming service|livestreaming service)', ai=.86, sub=.98, remote=.72, entry=.82, pain=.72, margin=.88),
    dict(niche='Hydrology / flood / water studies', macro='SPECIALIST_CONSULTING', pattern=r'(etude hydrologique|etudes hydrologiques|etudes hydrauliques|etude hydraulique|risques inondation|risque inondation|bassins versants|zones humides|flood risk study|hydrological study|hydraulic study)', ai=.46, sub=.99, remote=.64, entry=.34, pain=.46, margin=.86),
    dict(niche='Mobility / traffic studies', macro='SPECIALIST_CONSULTING', pattern=r'(etude circulation|etude mobilite|etudes mobilite|traffic study|traffic studies|mobility study|mobility studies|transport study|transport planning study)', ai=.56, sub=.99, remote=.72, entry=.38, pain=.50, margin=.86),
    dict(niche='Climate / energy planning studies', macro='SPECIALIST_CONSULTING', pattern=r'(climat air energie|air energie|climate energy plan|climate action plan|energy planning study|etude energetique|etudes energetiques|plan climat|strategie climat)', ai=.58, sub=.99, remote=.76, entry=.38, pain=.50, margin=.88),
    dict(niche='Master plans / strategic planning studies', macro='SPECIALIST_CONSULTING', pattern=r'(schema directeur|master plan study|master planning study|strategic master plan|elaboration schema directeur)', ai=.54, sub=.99, remote=.74, entry=.34, pain=.50, margin=.86),
    dict(niche='Urban planning / local planning studies', macro='SPECIALIST_CONSULTING', pattern=r'(plan local urbanisme|local urbanisme|urban planning study|urban planning services|etude urbanisme|etudes urbanisme|planification urbaine)', ai=.52, sub=.99, remote=.72, entry=.32, pain=.48, margin=.86),
    dict(niche='Strategic / diagnostic / evaluation studies', macro='SPECIALIST_CONSULTING', pattern=r'(etude strategique|etude diagnostique|etude evaluation|etude potentiel|strategic study|diagnostic study|evaluation study|feasibility assessment)', ai=.62, sub=.99, remote=.84, entry=.44, pain=.56, margin=.88),
    dict(niche='Financial analysis / advisory studies', macro='SPECIALIST_CONSULTING', pattern=r'(analyse financiere|financial analysis|financial advisory study|financial feasibility|etude financiere|financial modelling)', ai=.74, sub=.98, remote=.94, entry=.46, pain=.58, margin=.90),
    dict(niche='Mobile device / endpoint management', macro='ENDPOINT_CLOUD', pattern=r'(mobile device management|mobile device|endpoint management|unified endpoint management|\buem\b.{0,20}(platform|solution|service)|device management platform)', ai=.58, sub=.92, remote=.97, entry=.56, pain=.64, margin=.84),
    dict(niche='Broadband / gigabit network consulting', macro='TELECOM_PARTNERABLE', pattern=r'(gigabit netzes|eines gigabit netzes|telekommunikationsdienste unterversorgten|communications electroniques|broadband network consulting|gigabit network planning)', ai=.24, sub=.98, remote=.58, entry=.32, pain=.44, margin=.82),
]

def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--core',required=True)
    ap.add_argument('--known-matched',required=True)
    ap.add_argument('--wave1-matched',required=True)
    ap.add_argument('--wave2-matched',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--min-concept-volume',type=int,default=20)
    a=ap.parse_args()
    core=Path(a.core); known=Path(a.known_matched); w1=Path(a.wave1_matched); w2=Path(a.wave2_matched); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    tp=core/'historical_tenders.parquet'
    for p in (tp,known,w1,w2):
        if not p.exists(): raise SystemExit(f'MISSING_INPUT {p}')
    tmp=out/'ducktmp'; tmp.mkdir(exist_ok=True)
    con=duckdb.connect(); con.execute("SET preserve_insertion_order=false"); con.execute("SET threads=2"); con.execute("SET memory_limit='6GB'"); con.execute(f"SET temp_directory={q(tmp.as_posix())}"); con.execute("SET max_temp_directory_size='18GB'")
    cols={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(tp.as_posix())})").fetchall()}
    def c(n,f): return f'"{n}"' if n in cols else f
    desc=c('Description',"''"); cat=c('Category',"''"); subcat=c('Subcategory',"''"); buyer=c('Buyer_ID','NULL::VARCHAR'); buyer_name=c('Buyer_Name',"'UNKNOWN'"); country=c('Country',"'UNKNOWN'"); pub=c('Publication_Date','NULL::DATE'); deadline=c('Deadline','NULL::DATE'); lean=c('Lean_Fit','NULL::DOUBLE'); url=c('Source_URL','NULL::VARCHAR'); ref=c('Source_Reference','NULL::VARCHAR')
    total=con.execute(f"select count(*) from read_parquet({q(tp.as_posix())})").fetchone()[0]
    excluded_unique=con.execute(f"""select count(*) from (
      select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(known.as_posix())})
      union select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(w1.as_posix())})
      union select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(w2.as_posix())})
    )""").fetchone()[0]
    residual=out/'residual_after_wave2.parquet'
    con.execute(f"""COPY (
      SELECT t.Warehouse_Source,t.Historical_Tender_ID,cast(t.Title as varchar) Title,cast({desc} as varchar) Description,
             cast({cat} as varchar) Category,cast({subcat} as varchar) Subcategory,cast({buyer} as varchar) Buyer_ID,
             cast({buyer_name} as varchar) Buyer_Name,cast({country} as varchar) Country,try_cast({pub} as date) Publication_Date,
             try_cast({deadline} as date) Deadline,try_cast({lean} as double) Lean_Fit,cast({url} as varchar) Source_URL,cast({ref} as varchar) Source_Reference,
             lower(strip_accents(coalesce(cast(t.Title as varchar),''))) Title_Blob
      FROM read_parquet({q(tp.as_posix())}) t
      ANTI JOIN (
        select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(known.as_posix())})
        union select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(w1.as_posix())})
        union select distinct Warehouse_Source,Historical_Tender_ID from read_parquet({q(w2.as_posix())})
      ) k USING(Warehouse_Source,Historical_Tender_ID)
    ) TO {q(residual.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    residual_n=con.execute(f"select count(*) from read_parquet({q(residual.as_posix())})").fetchone()[0]
    assert residual_n==total-excluded_unique,(total,excluded_unique,residual_n)
    con.execute("CREATE TEMP TABLE rules(Niche VARCHAR,Macro_Category VARCHAR,Pattern VARCHAR,AI_Leverage DOUBLE,Subcontractability DOUBLE,Remote_Feasibility DOUBLE,Low_Entry_Burden DOUBLE,Low_Execution_Pain DOUBLE,Margin_Potential DOUBLE)")
    for r in CONCEPTS:
        con.execute("INSERT INTO rules VALUES (?,?,?,?,?,?,?,?,?)",[r['niche'],r['macro'],r['pattern'],r['ai'],r['sub'],r['remote'],r['entry'],r['pain'],r['margin']])
    combined='('+'|'.join('(?:'+r['pattern']+')' for r in CONCEPTS)+')'
    candidates=out/'wave3_prefilter_candidates.parquet'
    con.execute(f"COPY (SELECT * FROM read_parquet({q(residual.as_posix())}) WHERE regexp_matches(Title_Blob,{q(combined)})) TO {q(candidates.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)")
    raw=out/'wave3_matches_raw.parquet'
    con.execute(f"""COPY (
      SELECT u.* EXCLUDE(Title_Blob),r.Niche,r.Macro_Category,r.AI_Leverage,r.Subcontractability,r.Remote_Feasibility,
             r.Low_Entry_Burden,r.Low_Execution_Pain,r.Margin_Potential
      FROM read_parquet({q(candidates.as_posix())}) u JOIN rules r ON regexp_matches(u.Title_Blob,r.Pattern)
    ) TO {q(raw.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.execute(f"CREATE TEMP VIEW concept_counts AS SELECT Niche,count(*) Tender_Count,count(distinct Buyer_ID) Unique_Buyers,count(distinct Warehouse_Source) Source_Count,count(distinct Country) Country_Count FROM read_parquet({q(raw.as_posix())}) GROUP BY 1")
    valid=[r[0] for r in con.execute(f"select Niche from concept_counts where Tender_Count>={a.min_concept_volume} order by Tender_Count desc").fetchall()]
    if not valid: raise SystemExit('NO_VALID_WAVE3_CONCEPTS')
    valid_sql=','.join(q(x) for x in valid)
    matched=out/'matched_tenders.parquet'
    con.execute(f"COPY (SELECT * FROM read_parquet({q(raw.as_posix())}) WHERE Niche IN ({valid_sql})) TO {q(matched.as_posix())} (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"CREATE TEMP VIEW buyer_niche AS SELECT Niche,Warehouse_Source,Buyer_ID,count(*) Tender_Count FROM read_parquet({q(matched.as_posix())}) WHERE Buyer_ID IS NOT NULL GROUP BY 1,2,3")
    matrix=out/'open_world_wave3_matrix.csv'
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
        'OPEN_WORLD_WAVE3_MULTILINGUAL_EMPIRICAL_PLUS_HEURISTICS' Score_Contract,'DERIVED' Derived_Status
      FROM p ORDER BY Discovery_Score DESC
    ) TO {q(matrix.as_posix())} (HEADER)""")
    con.execute(f"""COPY (
      WITH x AS (SELECT *,row_number() over(partition by Niche order by Publication_Date desc nulls last,Historical_Tender_ID) rn FROM read_parquet({q(matched.as_posix())}))
      SELECT * EXCLUDE(rn) FROM x WHERE rn<=12 ORDER BY Niche,Publication_Date DESC
    ) TO {q((out/'representative_tenders_by_concept.csv').as_posix())} (HEADER)""")
    rows=list(csv.DictReader(open(matrix,encoding='utf-8')))
    matched_rows=con.execute(f"select count(*) from read_parquet({q(matched.as_posix())})").fetchone()[0]
    unique_tenders=con.execute(f"select count(distinct Warehouse_Source||'|'||Historical_Tender_ID) from read_parquet({q(matched.as_posix())})").fetchone()[0]
    quality={'status':'PASS' if len(rows)>=8 and unique_tenders>=300 else 'FAIL','generated_at':datetime.now(timezone.utc).isoformat(),'source_core_tenders':total,'excluded_unique_before_wave3':excluded_unique,'residual_after_wave2':residual_n,'concept_rules':len(CONCEPTS),'retained_concepts':len(rows),'concept_match_rows':matched_rows,'unique_wave3_tenders':unique_tenders,'multi_label_rows':matched_rows-unique_tenders,'min_concept_volume':a.min_concept_volume,'contract':'DATA_DERIVED_OPEN_WORLD_WAVE3_V1: multilingual + specialist cohorts seeded from v2 recurring phrases; original SPM + waves1/2 anti-joined; title-only; no DCE'}
    (out/'data_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    if quality['status']!='PASS': raise SystemExit(f'QA_FAILED {quality}')
    lines=['# SPM Open-World Wave 3 v1','',f'- Residual tenders after original SPM + waves 1/2 exclusions: **{residual_n:,}**',f'- Wave 3 rules: **{len(CONCEPTS)}**',f'- Retained concepts: **{len(rows)}**',f'- Net-new unique tenders classified: **{unique_tenders:,}**',f'- Multi-label rows: **{matched_rows:,}**','','## Concepts','','|#|Concept|Tenders|Buyers|Sources|Countries|Lean|Discovery|Easy money|Middleman|','|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for i,r in enumerate(sorted(rows,key=lambda x:float(x['Discovery_Score']),reverse=True),1):
        lines.append(f"|{i}|{r['Niche']}|{int(float(r['Tender_Count'])):,}|{int(float(r['Unique_Buyers'])):,}|{r['Source_Count']}|{r['Country_Count']}|{float(r['Median_Lean_Fit'] or 0):.1f}|{float(r['Discovery_Score']):.1f}|{float(r['Easy_Money_Proxy']):.1f}|{float(r['Middleman_Proxy']):.1f}|")
    lines += ['','Wave 3 is net-new against original SPM plus waves 1 and 2. Scores are historical priors only; live eligibility, certifications, local professional requirements, and reseller authorizations must be verified per notice/DCE.']
    (out/'WAVE3_READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('OPEN_WORLD_WAVE3_PASS',json.dumps(quality,sort_keys=True))

if __name__=='__main__': main()
