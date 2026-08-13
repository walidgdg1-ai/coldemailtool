#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/tender_normalize_france.py')
s=p.read_text(encoding='utf-8')
s=s.replace('import argparse\n', 'import argparse\nimport csv\nimport sys\n', 1)
s=s.replace('UNKNOWN = "UNKNOWN"\n', 'UNKNOWN = "UNKNOWN"\ncsv.field_size_limit(min(sys.maxsize, 2**31-1))\n', 1)
old="""    for p in sorted(raw.glob(\"boamp_*.csv\")):
        source_files.append(p.name)
        with p.open(\"r\", encoding=\"utf-8-sig\", errors=\"replace\") as f:
            for line in f:
                if not line.strip():
                    continue
                raw_lines += 1
                try:
                    o = json.loads(line)
                except Exception:
                    parse_errors += 1
                    continue
                if not isinstance(o, dict):
                    parse_errors += 1
                    continue
                r = simplify(o, p.name)
                if not r:
                    continue
                if pd.isna(r[\"date\"]) or r[\"date\"] < start_ts or r[\"date\"] > end_ts:
                    out_of_window += 1
                    continue
                records.append(r)
"""
new="""    embedded_json_errors = 0
    for p in sorted(raw.glob(\"boamp_*.csv\")):
        source_files.append(p.name)
        with p.open(\"r\", encoding=\"utf-8-sig\", errors=\"replace\", newline=\"\") as f:
            reader = csv.DictReader(f, delimiter=\";\", quotechar='\\\"')
            for row in reader:
                raw_lines += 1
                if not isinstance(row, dict) or not row.get('idweb'):
                    parse_errors += 1
                    continue
                o = dict(row)
                # BOAMP bulk CSV stores rich source payloads as JSON strings inside cells.
                for fld in ('donnees','gestion'):
                    rawv = o.get(fld)
                    if rawv:
                        try:
                            o[fld] = json.loads(rawv)
                        except Exception:
                            embedded_json_errors += 1
                            o[fld] = {}
                    else:
                        o[fld] = {}
                # Preserve compatibility with the heterogeneous historical parser.
                o['typeavis'] = o.get('type_avis') or o.get('typeavis')
                o['nature_libelle'] = o.get('nature_libelle') or o.get('nature_categorise_libelle')
                r = simplify(o, p.name)
                if not r:
                    continue
                if pd.isna(r[\"date\"]) or r[\"date\"] < start_ts or r[\"date\"] > end_ts:
                    out_of_window += 1
                    continue
                records.append(r)
"""
if old not in s:
    raise SystemExit('BOAMP input block not found; refusing unsafe patch')
s=s.replace(old,new)
# Namespace-prefixed eForms keys should behave like their local names.
old2="""def keynorm(k):
    return unicodedata.normalize(\"NFKD\", str(k)).encode(\"ascii\", \"ignore\").decode().upper().replace(\"-\", \"_\").replace(\" \", \"_\")
"""
new2="""def keynorm(k):
    s = unicodedata.normalize(\"NFKD\", str(k)).encode(\"ascii\", \"ignore\").decode().upper().replace(\"-\", \"_\").replace(\" \", \"_\")
    return s.split(':')[-1]
"""
if old2 not in s:
    raise SystemExit('keynorm block not found')
s=s.replace(old2,new2)
# XML-to-JSON scalar values use #text.
s=s.replace("""    if isinstance(v, dict):
        for k in (\"montant\", \"amount\", \"value\", \"valeur\"):
""","""    if isinstance(v, dict):
        if '#text' in v:
            x = parse_amount(v.get('#text'))
            if x is not None:
                return x
        for k in (\"montant\", \"amount\", \"value\", \"valeur\"):
""",1)
# Add eForms monetary semantics without treating arbitrary numeric IDs as values.
s=s.replace("""[\"MONTANT_TOTAL\", \"VALEUR_TOTALE\", \"MONTANT_MARCHE\", \"MONTANT_ATTRIBUE\", \"VALEUR_FINALE\", \"MONTANT\", \"VALEUR\"],""","""[\"MONTANT_TOTAL\", \"VALEUR_TOTALE\", \"MONTANT_MARCHE\", \"MONTANT_ATTRIBUE\", \"VALEUR_FINALE\", \"PAYABLEAMOUNT\", \"TOTALAMOUNT\", \"MAXIMUMVALUEAMOUNT\", \"MONTANT\", \"VALEUR\"],""",1)
s=s.replace("""[\"VALEUR_TOTALE_ESTIMEE\", \"MONTANT_TOTAL_ESTIME\", \"MONTANT_ESTIME\", \"VALEUR_ESTIMEE\", \"ESTIMATION\"],""","""[\"VALEUR_TOTALE_ESTIMEE\", \"MONTANT_TOTAL_ESTIME\", \"MONTANT_ESTIME\", \"VALEUR_ESTIMEE\", \"ESTIMATEDVALUEAMOUNT\", \"VALUEAMOUNT\", \"ESTIMATION\"],""",1)
# Expose embedded JSON health in QA.
s=s.replace("""        \"parse_errors\": parse_errors,
""","""        \"parse_errors\": parse_errors,
        \"embedded_json_errors\": embedded_json_errors,
""",1)
p.write_text(s,encoding='utf-8')
print('France semicolon-CSV runtime patch applied with raised field limit')
