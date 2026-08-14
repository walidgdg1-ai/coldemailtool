#!/usr/bin/env python3
from pathlib import Path

p = Path('tools/build_spm_open_world_wave3_v1.py')
s = p.read_text(encoding='utf-8')
marker = "    dict(niche='Broadband / gigabit network consulting', macro='TELECOM_PARTNERABLE', pattern=r'(gigabit netzes|eines gigabit netzes|telekommunikationsdienste unterversorgten|communications electroniques|broadband network consulting|gigabit network planning)', ai=.24, sub=.98, remote=.58, entry=.32, pain=.44, margin=.82),\n"
if marker not in s:
    if "Multilingual CCTV / video protection" in s:
        print('WAVE3_EXPANSION_ALREADY_PRESENT')
        raise SystemExit(0)
    raise SystemExit('WAVE3_EXPANSION_MARKER_NOT_FOUND')
extra = marker + """    dict(niche='Multilingual CCTV / video protection', macro='SECURITY_RESALE', pattern=r'(supraveghere video|monitoringu wizyjnego|dispositif video protection|videoprotection|video protection|monitorizare video|video nadzor|nadzor wizyjny)', ai=.18, sub=.99, remote=.42, entry=.68, pain=.62, margin=.80),
    dict(niche='Clinical records / EHR / medical-data systems', macro='HEALTH_IT', pattern=r'(historia clinica|danych medycznych|patient journal|electronic health record|electronic medical record|ehr system|emr system|systemu szpitalnego|medical data system)', ai=.66, sub=.86, remote=.94, entry=.28, pain=.40, margin=.92),
    dict(niche='Cadastral / geodetic data modernization', macro='GEO_DATA', pattern=r'(baz danych egib|bdot gesut|geodezyjnego wojewodztwa|modernizacja ewidencji|cadastral database|cadastral data|land registry data|geodetic database|geospatial database modernization)', ai=.76, sub=.96, remote=.92, entry=.48, pain=.56, margin=.88),
    dict(niche='Electronic case / records management', macro='DOCUMENT_SOFTWARE', pattern=r'(arendehanteringssystem|dokument och arendehanteringssystem|case management system|records management system|electronic records management|document and case management)', ai=.82, sub=.90, remote=.99, entry=.62, pain=.68, margin=.90),
    dict(niche='Photography / documentary reporting', macro='CREATIVE_SERVICES', pattern=r'(reportages photographiques|reportage photographique|photographic reporting|photography services|photographic services|photo reportage|event photography)', ai=.86, sub=.99, remote=.72, entry=.92, pain=.86, margin=.88),
    dict(niche='Technical documentation / manuals', macro='DOCUMENT_CONTENT', pattern=r'(technical documentation|documentation technique|technical manuals|technical manual|user manuals|user manual|manuel utilisateur|manuels utilisateurs)', ai=.96, sub=.96, remote=.99, entry=.90, pain=.86, margin=.92),
    dict(niche='Digital signage / display systems', macro='SIGNAGE_MIDDLEMAN', pattern=r'(carteleria digital|digital signage|digital display system|electronic signage|affichage dynamique|systeme affichage dynamique)', ai=.58, sub=.99, remote=.70, entry=.72, pain=.66, margin=.82),
    dict(niche='Legal / professional information subscriptions', macro='INFO_SUBSCRIPTIONS', pattern=r'(informacji prawnej|legal information service|legal information database|professional information database|banca dati giuridica|legal database subscription)', ai=.24, sub=.94, remote=.99, entry=.54, pain=.76, margin=.72),
"""
s = s.replace(marker, extra, 1)
p.write_text(s, encoding='utf-8')
print('WAVE3_EXPANSION_PATCH_PASS')
