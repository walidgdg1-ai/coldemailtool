#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

UNKNOWN = "UNKNOWN"
VERSION = "FR_BOAMP_CANONICAL_V1"


def clean(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return str(v)
    if not isinstance(v, str):
        return None
    s = re.sub(r"\s+", " ", v.strip())
    return s or None


def text(v):
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return clean(v) or ""
    if isinstance(v, list):
        return " | ".join(x for x in (text(i) for i in v) if x)
    if isinstance(v, dict):
        preferred = []
        for k in (
            "libelle", "label", "denomination", "nom", "name", "raison_sociale",
            "value", "code", "reference", "id", "nature", "famille",
        ):
            if k in v and v[k] not in (None, "", [], {}):
                t = text(v[k])
                if t:
                    preferred.append(t)
        if preferred:
            return " | ".join(preferred)
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return clean(str(v)) or ""


def norm(v):
    s = clean(v)
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(
        r"\b(sa|sas|sasu|sarl|eurl|scop|association|etablissement|établissement|societe|société|ville|commune|metropole|métropole)\b",
        " ", s,
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def stable(prefix, value):
    return f"{prefix}_" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:20]


def parse_dt(v):
    try:
        return pd.to_datetime(v, errors="coerce", utc=True, dayfirst=True)
    except Exception:
        return pd.NaT


def iso(v):
    d = parse_dt(v)
    return d.strftime("%Y-%m-%d") if pd.notna(d) else None


def as_list(v):
    if v in (None, "", [], {}):
        return []
    return v if isinstance(v, list) else [v]


def walk(v, path=()):
    if isinstance(v, dict):
        for k, x in v.items():
            p = path + (str(k),)
            yield p, x
            yield from walk(x, p)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            p = path + (str(i),)
            yield p, x
            yield from walk(x, p)


def keynorm(k):
    return unicodedata.normalize("NFKD", str(k)).encode("ascii", "ignore").decode().upper().replace("-", "_").replace(" ", "_")


def parse_amount(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return x if math.isfinite(x) and abs(x) < 1e15 else None
    if isinstance(v, dict):
        for k in ("montant", "amount", "value", "valeur"):
            if k in v:
                x = parse_amount(v[k])
                if x is not None:
                    return x
        return None
    if isinstance(v, list):
        return None
    s = str(v).strip()
    if not s:
        return None
    # Ignore obvious identifiers / dates rather than turning them into money.
    if re.fullmatch(r"\d{2,4}[-/]\d{1,2}[-/]\d{1,4}", s):
        return None
    s = s.replace("\u202f", " ").replace("\xa0", " ")
    m = re.search(r"[-+]?\d[\d .,'’]*", s)
    if not m:
        return None
    n = m.group(0).replace(" ", "").replace("'", "").replace("’", "")
    if "," in n and "." in n:
        if n.rfind(",") > n.rfind("."):
            n = n.replace(".", "").replace(",", ".")
        else:
            n = n.replace(",", "")
    elif "," in n:
        tail = n.rsplit(",", 1)[-1]
        n = n.replace(".", "")
        n = n.replace(",", ".") if len(tail) <= 2 else n.replace(",", "")
    elif n.count(".") > 1:
        n = n.replace(".", "")
    try:
        x = float(n)
    except Exception:
        return None
    return x if math.isfinite(x) and abs(x) < 1e15 else None


def currency_from(v):
    s = text(v).upper()
    if "EUR" in s or "€" in s or "EURO" in s:
        return "EUR"
    if "GBP" in s or "£" in s:
        return "GBP"
    if "USD" in s or "$" in s:
        return "USD"
    return None


def find_amount(container, ordered_keys):
    if container in (None, "", [], {}):
        return None, None, None
    wanted = [keynorm(x) for x in ordered_keys]
    candidates = []
    for path, v in walk(container):
        if not path:
            continue
        kn = keynorm(path[-1])
        if kn not in wanted:
            continue
        x = parse_amount(v)
        if x is None or x < 0:
            continue
        candidates.append((wanted.index(kn), len(path), kn, x, currency_from(v) or currency_from(container)))
    if not candidates:
        return None, None, None
    candidates.sort(key=lambda x: (x[0], x[1]))
    best_rank = candidates[0][0]
    same_priority = [x for x in candidates if x[0] == best_rank]
    distinct = sorted({round(x[3], 6) for x in same_priority})
    # If the best semantic field appears several times with different values (e.g. lots),
    # do not silently aggregate or pick one.
    if len(distinct) > 1:
        return None, None, "AMBIGUOUS_MULTIPLE_VALUES"
    c = same_priority[0]
    return c[3], c[4] or "EUR", c[2]


def find_int(container, keys):
    wanted = {keynorm(x) for x in keys}
    vals = []
    for path, v in walk(container):
        if path and keynorm(path[-1]) in wanted:
            x = parse_amount(v)
            if x is not None and 0 <= x <= 1_000_000 and abs(x - round(x)) < 1e-9:
                vals.append(int(round(x)))
    return max(vals) if vals else None


def extract_links(o):
    out = set()
    for field in ("annonce_lie", "annonces_anterieures"):
        v = o.get(field)
        for _, x in walk(v):
            s = clean(x) if isinstance(x, (str, int)) else None
            if not s:
                continue
            for m in re.findall(r"\b\d{2,4}-\d{3,10}\b", s):
                out.add(m)
        s = text(v)
        for m in re.findall(r"\b\d{2,4}-\d{3,10}\b", s):
            out.add(m)
    return sorted(out)


def buyer_name(o):
    for k in ("nomacheteur", "organisme"):
        s = clean(o.get(k))
        if s:
            return s
    d = o.get("donnees") or o.get("DONNEES") or {}
    for path, v in walk(d):
        if path and keynorm(path[-1]) in {"DENOMINATION", "NOM_ACHETEUR", "NOMACHETEUR"}:
            s = clean(v)
            if s:
                return s
    return None


def extract_cpv(o):
    # Prefer explicit CPV fields; fall back to BOAMP class/descripteur codes only as local codes.
    for path, v in walk(o.get("donnees") or o.get("DONNEES") or {}):
        kn = keynorm(path[-1]) if path else ""
        if "CPV" in kn:
            s = text(v)
            m = re.search(r"\b\d{8}(?:-\d)?\b", s)
            if m:
                return m.group(0)
    for k in ("cpv", "dc", "descripteur_code"):
        s = clean(o.get(k))
        if s:
            return s
    return None


def extract_suppliers(o):
    names = []
    countries = {}

    def add_name(name, country=None):
        n = clean(name)
        if not n:
            return
        if len(n) > 300:
            return
        if n not in names:
            names.append(n)
        if country:
            countries[n] = clean(country)

    def parse_block(v):
        if isinstance(v, str):
            add_name(v)
            return
        if isinstance(v, list):
            for x in v:
                parse_block(x)
            return
        if not isinstance(v, dict):
            return
        name = None
        country = None
        for k, x in v.items():
            kn = keynorm(k)
            if kn in {"DENOMINATION", "NOM", "NAME", "RAISON_SOCIALE", "TITULAIRE", "ADJUDICATAIRE"} and not isinstance(x, (dict, list)):
                sx = clean(x)
                if sx and not name:
                    name = sx
            if kn in {"PAYS", "COUNTRY", "COUNTRYNAME"} and not isinstance(x, (dict, list)):
                country = clean(x)
        if name:
            add_name(name, country)
        for k, x in v.items():
            kn = keynorm(k)
            if any(w in kn for w in ("TITULAIRE", "ADJUDICATAIRE", "ATTRIBUTAIRE", "CONTRACTANT")):
                parse_block(x)

    parse_block(o.get("titulaire"))
    parse_block(o.get("marche"))
    d = o.get("donnees") or o.get("DONNEES") or {}
    for path, v in walk(d):
        if path and any(w in keynorm(path[-1]) for w in ("TITULAIRE", "ADJUDICATAIRE", "ATTRIBUTAIRE")):
            parse_block(v)
    return [(n, countries.get(n)) for n in names]


def nature_text(o):
    for k in ("nature_categorise_libelle", "nature_libelle", "nature"):
        s = text(o.get(k))
        if s:
            return s
    ta = o.get("typeavis")
    if ta in (None, ""):
        ta = o.get("type_avis")
    return text(ta)


def is_award_notice(o, suppliers):
    n = norm(nature_text(o))
    cat = norm(o.get("nature_categorise_libelle"))
    if any(x in cat for x in ("resultat de marche", "resultat marche")):
        return True
    if any(x in n for x in ("attribution", "resultat", "avis d attribution")):
        return True
    if suppliers:
        return True
    if o.get("marche") not in (None, "", [], {}):
        return True
    return False


def is_tender_notice(o, award):
    cat = norm(o.get("nature_categorise_libelle"))
    n = norm(nature_text(o))
    if "avis de marche" in cat or "avis de marche" in n or "appel offre" in n:
        return True
    # Rectificatifs / modifications can update a tender but should not themselves become a new opportunity.
    if award:
        return False
    return bool(clean(o.get("datelimitereponse")))


def classify(title, desc, descriptors, type_market):
    t = " ".join(x for x in (clean(title), clean(desc), clean(descriptors), clean(type_market)) if x).lower()
    rules = [
        ("Web", "Website / CMS", 88, [r"site web", r"website", r"\bcms\b", r"portail web", r"refonte.*site", r"developpement web"]),
        ("Document / data", "Digitization / OCR", 92, [r"numeris", r"numéris", r"digitis", r"\bocr\b", r"scan.*document", r"indexation", r"saisie de donnees", r"saisie de données"]),
        ("Language", "Translation / transcription", 90, [r"traduction", r"transcription", r"sous-titr", r"sous titr", r"interpretariat", r"interprétariat", r"relecture"]),
        ("Creative / communications", "Design / publishing", 82, [r"graphisme", r"graphique", r"communication", r"brochure", r"rapport annuel", r"mise en page", r"creation de contenu", r"création de contenu", r"video", r"vidéo", r"edition", r"édition"]),
        ("Printing", "Print / routing", 68, [r"impression", r"imprimerie", r"routage", r"mise sous pli"]),
        ("Automation / software", "Software / automation", 74, [r"logiciel", r"software", r"developpement applicatif", r"développement applicatif", r"automatisation", r"migration de donnees", r"migration de données", r"tableau de bord", r"saas"]),
        ("Monitoring / research", "Monitoring / analysis", 70, [r"veille media", r"veille média", r"monitoring", r"analyse de donnees", r"analyse de données", r"etude", r"étude"]),
    ]
    for cat, sub, score, pats in rules:
        if any(re.search(p, t) for p in pats):
            return cat, sub, score, score
    return "Other", clean(type_market) or UNKNOWN, 20, 15


class DSU:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def add(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x):
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def simplify(o, source_file):
    idweb = clean(o.get("idweb") or o.get("id"))
    if not idweb:
        return None
    date = parse_dt(o.get("dateparution"))
    suppliers = extract_suppliers(o)
    award = is_award_notice(o, suppliers)
    tender = is_tender_notice(o, award)
    donnees = o.get("donnees") or o.get("DONNEES") or {}
    marche = o.get("marche")
    award_value, award_currency, award_value_field = find_amount(
        marche if marche not in (None, "", [], {}) else donnees,
        ["MONTANT_TOTAL", "VALEUR_TOTALE", "MONTANT_MARCHE", "MONTANT_ATTRIBUE", "VALEUR_FINALE", "MONTANT", "VALEUR"],
    )
    estimate, estimate_currency, estimate_field = find_amount(
        donnees,
        ["VALEUR_TOTALE_ESTIMEE", "MONTANT_TOTAL_ESTIME", "MONTANT_ESTIME", "VALEUR_ESTIMEE", "ESTIMATION"],
    )
    bidder_count = find_int(donnees, ["NOMBRE_OFFRES_RECUES", "NB_OFFRES", "NOMBRE_OFFRES", "OFFRES_RECUES", "NOMBRE_CANDIDATS"])
    title = clean(o.get("objet"))
    desc = None
    for path, v in walk(donnees):
        if path and keynorm(path[-1]) in {"OBJET_COMPLET", "DESCRIPTION", "DESCRIPTION_MARCHE", "OBJET"}:
            s = clean(v) if isinstance(v, str) else None
            if s and (desc is None or len(s) > len(desc)):
                desc = s
    return {
        "idweb": idweb,
        "contractfolderid": clean(o.get("contractfolderid")),
        "links": extract_links(o),
        "date": date,
        "deadline": parse_dt(o.get("datelimitereponse")),
        "title": title,
        "desc": desc,
        "buyer": buyer_name(o),
        "procedure": clean(o.get("procedure_categorise") or o.get("procedure_libelle") or o.get("type_procedure")),
        "nature": nature_text(o),
        "state": clean(o.get("etat")),
        "descriptors": clean(o.get("descripteur_libelle")),
        "type_market": clean(o.get("type_marche_facette") or o.get("type_marche")),
        "cpv": extract_cpv(o),
        "source_url": clean(o.get("url_avis")) or f"https://www.boamp.fr/pages/avis/?q=idweb:{idweb}",
        "suppliers": suppliers,
        "award": award,
        "tender": tender,
        "award_value": award_value,
        "award_currency": award_currency or "EUR",
        "award_value_field": award_value_field,
        "estimate": estimate,
        "estimate_currency": estimate_currency or "EUR",
        "estimate_field": estimate_field,
        "bidder_count": bidder_count,
        "source_file": source_file,
    }


def make_analytics(tenders, awards, out):
    if tenders.empty:
        return
    j = tenders[["Historical_Tender_ID", "Category", "Subcategory", "Buyer_ID", "Buyer_Name", "Lean_Fit"]].copy()
    if not awards.empty:
        aj = awards[["Historical_Tender_ID", "Award_ID", "Award_Value", "Bidder_Count"]]
        j = j.merge(aj, on="Historical_Tender_ID", how="left")
    else:
        j["Award_ID"] = None
        j["Award_Value"] = None
        j["Bidder_Count"] = None
    rows = []
    for (cat, sub), g in j.groupby(["Category", "Subcategory"], dropna=False):
        tender_n = g.Historical_Tender_ID.nunique()
        awards_n = g.Award_ID.nunique() if "Award_ID" in g else 0
        med_lean = float(g.Lean_Fit.median()) if g.Lean_Fit.notna().any() else 0.0
        med_val = float(g.Award_Value.median()) if g.Award_Value.notna().any() else None
        med_bid = float(g.Bidder_Count.median()) if g.Bidder_Count.notna().any() else None
        val_cov = float(g.Award_Value.notna().mean()) if len(g) else 0.0
        bid_cov = float(g.Bidder_Count.notna().mean()) if len(g) else 0.0
        value_score = min(100.0, 18.0 * math.log10(max(med_val or 1, 1))) if med_val else 20.0
        competition_score = 50.0 if med_bid is None else max(0.0, 100.0 - min(100.0, med_bid * 12.0))
        volume_score = min(100.0, 18.0 * math.log10(max(tender_n, 1)))
        evidence_score = min(100.0, (val_cov + bid_cov) * 50.0)
        score = round(0.30 * med_lean + 0.25 * value_score + 0.20 * competition_score + 0.15 * volume_score + 0.10 * evidence_score, 2)
        rows.append({
            "Category": cat,
            "Subcategory": sub,
            "Tender_Count": tender_n,
            "Award_Count": awards_n,
            "Median_Lean_Fit": round(med_lean, 2),
            "Median_Award_Value_EUR": med_val,
            "Median_Bidder_Count": med_bid,
            "Award_Value_Coverage_Pct": round(val_cov * 100, 2),
            "Bidder_Count_Coverage_Pct": round(bid_cov * 100, 2),
            "Market_Attractiveness_Score": score,
            "Derived_Status": "DERIVED",
        })
    pd.DataFrame(rows).sort_values(["Market_Attractiveness_Score", "Tender_Count"], ascending=[False, False]).to_csv(out / "market_rank.csv", index=False)

    rb = tenders.groupby(["Buyer_ID", "Buyer_Name", "Category", "Subcategory"], dropna=False).agg(
        Tender_Count=("Historical_Tender_ID", "nunique"),
        Median_Lean_Fit=("Lean_Fit", "median"),
    ).reset_index()
    rb = rb[rb.Tender_Count >= 2].sort_values(["Tender_Count", "Median_Lean_Fit"], ascending=[False, False])
    rb["Derived_Status"] = "DERIVED"
    rb.to_csv(out / "repeat_buyers.csv", index=False)

    if not awards.empty:
        an = awards.merge(tenders[["Historical_Tender_ID", "Title", "Buyer_Name", "Category", "Subcategory", "Lean_Fit"]], on="Historical_Tender_ID", how="left")
        an = an[(an["Lean_Fit"].fillna(0) >= 70) & ((an["Bidder_Count"].fillna(999999) <= 3) | (an["Award_Value"].fillna(0) >= 100000))]
        an = an.sort_values(["Lean_Fit", "Award_Value"], ascending=[False, False]).head(5000)
        an["Derived_Status"] = "DERIVED"
        an.to_csv(out / "historical_anomalies.csv", index=False)


def run(raw_dir, out_dir, start, end):
    raw = Path(raw_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    ingest = datetime.now(timezone.utc).isoformat()

    records = []
    raw_lines = 0
    parse_errors = 0
    out_of_window = 0
    source_files = []

    for p in sorted(raw.glob("boamp_*.csv")):
        source_files.append(p.name)
        with p.open("r", encoding="utf-8-sig", errors="replace") as f:
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
                if pd.isna(r["date"]) or r["date"] < start_ts or r["date"] > end_ts:
                    out_of_window += 1
                    continue
                records.append(r)

    # Exact source-identity dedupe: same BOAMP idweb can reappear across monthly snapshots/rectifications.
    by_id = {}
    for r in records:
        prev = by_id.get(r["idweb"])
        if prev is None or (pd.notna(r["date"]) and (pd.isna(prev["date"]) or r["date"] >= prev["date"])):
            by_id[r["idweb"]] = r
    records = list(by_id.values())

    dsu = DSU()
    known_ids = set(by_id)
    for r in records:
        n = "N:" + r["idweb"]
        dsu.add(n)
        if r["contractfolderid"]:
            c = "C:" + r["contractfolderid"]
            dsu.union(n, c)
    for r in records:
        n = "N:" + r["idweb"]
        for linked in r["links"]:
            if linked in known_ids:
                dsu.union(n, "N:" + linked)

    groups = defaultdict(list)
    for r in records:
        groups[dsu.find("N:" + r["idweb"])].append(r)

    tender_rows = []
    award_rows = []
    bridge_rows = []
    result_only_groups = 0
    explicit_linked_groups = 0

    for root, recs in groups.items():
        recs = sorted(recs, key=lambda r: (pd.Timestamp.max.tz_localize("UTC") if pd.isna(r["date"]) else r["date"], r["idweb"]))
        tender_recs = [r for r in recs if r["tender"] and not r["award"]]
        award_recs = [r for r in recs if r["award"]]
        base = tender_recs[0] if tender_recs else recs[0]
        if not tender_recs and award_recs:
            result_only_groups += 1
        if any(r["links"] for r in recs):
            explicit_linked_groups += 1

        strong_group = next((r["contractfolderid"] for r in recs if r["contractfolderid"]), None)
        group_identity = strong_group or "|".join(sorted(r["idweb"] for r in recs))
        tid = stable("ten", "FR|" + group_identity)

        buyer = next((r["buyer"] for r in tender_recs if r["buyer"]), None) or next((r["buyer"] for r in recs if r["buyer"]), None)
        buyer_id = stable("buy", "FR|" + (norm(buyer) or group_identity))
        title = next((r["title"] for r in tender_recs if r["title"]), None) or next((r["title"] for r in recs if r["title"]), None)
        desc = next((r["desc"] for r in tender_recs if r["desc"]), None) or next((r["desc"] for r in recs if r["desc"]), None)
        descriptors = next((r["descriptors"] for r in tender_recs if r["descriptors"]), None) or next((r["descriptors"] for r in recs if r["descriptors"]), None)
        type_market = next((r["type_market"] for r in tender_recs if r["type_market"]), None) or next((r["type_market"] for r in recs if r["type_market"]), None)
        cpv = next((r["cpv"] for r in tender_recs if r["cpv"]), None) or next((r["cpv"] for r in recs if r["cpv"]), None)
        category, subcategory, automation, lean = classify(title, desc, descriptors, type_market)
        publication = min((r["date"] for r in tender_recs if pd.notna(r["date"])), default=base["date"])
        deadlines = [r["deadline"] for r in tender_recs if pd.notna(r["deadline"])]
        deadline = max(deadlines) if deadlines else base["deadline"]
        estimate_rec = next((r for r in tender_recs if r["estimate"] is not None), None) or next((r for r in recs if r["estimate"] is not None), None)
        estimate = estimate_rec["estimate"] if estimate_rec else None
        estimate_currency = estimate_rec["estimate_currency"] if estimate_rec else "EUR"
        procedure = next((r["procedure"] for r in tender_recs if r["procedure"]), None) or next((r["procedure"] for r in recs if r["procedure"]), None)
        linked_award_ids = []

        for ar in award_recs:
            aid = stable("awd", "FR|" + ar["idweb"])
            linked_award_ids.append(aid)
            sups = ar["suppliers"]
            supplier_count = len(sups) if sups else None
            value_scope = "UNKNOWN"
            if ar["award_value"] is not None:
                if supplier_count == 1:
                    value_scope = "SUPPLIER_ALLOCATED"
                elif supplier_count and supplier_count > 1:
                    value_scope = "GROUP_TOTAL_NOT_ALLOCATED"
                else:
                    value_scope = "TENDER_OR_AWARD_TOTAL"
            first_name, first_country = sups[0] if len(sups) == 1 else (None, None)
            first_sid = stable("sup", "FR|" + norm(first_name)) if first_name else None
            award_rows.append({
                "Award_ID": aid,
                "Historical_Tender_ID": tid,
                "Official_Award_Notice_ID": ar["idweb"],
                "Contract_ID": ar["contractfolderid"],
                "Buyer_ID": buyer_id,
                "Supplier_ID": first_sid,
                "Supplier_Name": first_name,
                "Supplier_Country": first_country or UNKNOWN,
                "Award_Date": iso(ar["date"]),
                "Award_Value": ar["award_value"],
                "Currency": ar["award_currency"] or "EUR",
                "Original_Estimated_Value": estimate,
                "Bidder_Count": ar["bidder_count"],
                "Electronic_Bidder_Count": None,
                "SME_Winner_Status": UNKNOWN,
                "Contract_Duration": None,
                "Renewal_Options": UNKNOWN,
                "Award_Criteria": UNKNOWN,
                "Award_Reason_Summary": None,
                "Primary_Source_URL": ar["source_url"],
                "Verification_Status": "VERIFIED_PRIMARY_BOAMP",
                "Modification_Value": None,
                "Last_Updated_At": ingest,
                "Award_Group_ID": aid,
                "Award_Value_Scope": value_scope,
                "Supplier_Count": supplier_count,
                "Source_Record_Count": 1,
                "Award_Value_Field": ar["award_value_field"],
            })
            for name, country in sups:
                sid = stable("sup", "FR|" + (norm(name) or name))
                bridge_rows.append({
                    "Award_ID": aid,
                    "Supplier_ID": sid,
                    "Supplier_Name": name,
                    "Relationship": "AWARDED_SUPPLIER",
                    "Award_Value_Allocated": ar["award_value"] if len(sups) == 1 else None,
                    "Supplier_Country": country or UNKNOWN,
                    "SME_Status": UNKNOWN,
                })

        source_ids = [r["idweb"] for r in recs]
        tender_rows.append({
            "Historical_Tender_ID": tid,
            "Official_Notice_ID": base["idweb"],
            "Procurement_Reference": strong_group or base["idweb"],
            "Title": title,
            "Buyer_ID": buyer_id,
            "Buyer_Name": buyer,
            "Country": "France",
            "Primary_Source_URL": base["source_url"],
            "Source_Tier": "A",
            "Publication_Date": iso(publication),
            "Deadline": iso(deadline),
            "Category": category,
            "Subcategory": subcategory,
            "CPV_NAICS_or_Local_Code": cpv,
            "Scope_Summary": desc or title,
            "Official_Estimated_Value": estimate,
            "Currency": estimate_currency or "EUR",
            "Contract_Duration": None,
            "Award_Criteria": UNKNOWN,
            "Price_Weight": None,
            "Quality_Weight": None,
            "Minimum_Turnover": UNKNOWN,
            "References_Required": UNKNOWN,
            "Required_Certifications": UNKNOWN,
            "Onsite_Requirement": UNKNOWN,
            "Subcontracting_Status": UNKNOWN,
            "Tender_Document_URLs": "[]",
            "Award_Link_Status": "LINKED" if linked_award_ids else "NOT_FOUND",
            "Linked_Award_ID": " | ".join(linked_award_ids) if linked_award_ids else None,
            "Automation_Potential": automation,
            "Lean_Fit": lean,
            "Evidence_Confidence": 95 if tender_recs else 80,
            "Ingested_At": ingest,
            "Source_Record_Count": len(recs),
            "Source_Platform": "BOAMP",
            "Competition_Type": procedure,
            "Procedure": procedure,
            "Threshold_Level": base.get("nature"),
            "Directive": None,
            "Parent_Agreement_ID": None,
            "Raw_Spend_Category": type_market,
            "Raw_CPV_Description": descriptors,
            "Cancelled_Date": None,
            "BOAMP_ContractFolderID": strong_group,
            "BOAMP_Source_Notice_IDs": " | ".join(sorted(source_ids)),
            "Source_Grain_Status": "TENDER_NOTICE" if tender_recs else "RESULT_ONLY_RECONSTRUCTED",
            "Estimated_Value_Field": estimate_rec["estimate_field"] if estimate_rec else None,
        })

    tenders = pd.DataFrame(tender_rows)
    awards = pd.DataFrame(award_rows)
    bridge = pd.DataFrame(bridge_rows)
    if not tenders.empty:
        tenders = tenders.drop_duplicates("Historical_Tender_ID")
    if not awards.empty:
        awards = awards.sort_values("Award_Date").drop_duplicates("Award_ID", keep="last")
    if not bridge.empty:
        bridge = bridge.drop_duplicates(["Award_ID", "Supplier_ID"])

    buyers = tenders.groupby(["Buyer_ID", "Buyer_Name"], dropna=False).agg(
        Observed_Tenders=("Historical_Tender_ID", "nunique")
    ).reset_index() if not tenders.empty else pd.DataFrame(columns=["Buyer_ID", "Buyer_Name", "Observed_Tenders"])
    if not awards.empty:
        ast = awards.groupby("Buyer_ID").agg(
            Observed_Awards=("Award_ID", "nunique"),
            Observed_Award_Value_Total=("Award_Value", "sum"),
            Median_Award_Value=("Award_Value", "median"),
            Median_Bidder_Count=("Bidder_Count", "median"),
        ).reset_index()
        buyers = buyers.merge(ast, on="Buyer_ID", how="left")
    buyers["Normalized_Name"] = buyers.Buyer_Name.map(norm) if "Buyer_Name" in buyers else None
    buyers["Country"] = "France"
    buyers["Buyer_Type"] = UNKNOWN
    buyers["Primary_Procurement_Portal"] = "BOAMP"
    buyers["Last_Updated_At"] = ingest

    if not bridge.empty:
        suppliers = bridge[["Supplier_ID", "Supplier_Name", "Supplier_Country"]].drop_duplicates("Supplier_ID")
        sst = bridge.groupby("Supplier_ID").agg(
            Observed_Contracts_Won=("Award_ID", "nunique"),
            Observed_Award_Value_Total=("Award_Value_Allocated", "sum"),
            Median_Award_Value=("Award_Value_Allocated", "median"),
        ).reset_index()
        suppliers = suppliers.merge(sst, on="Supplier_ID", how="left")
        suppliers["Normalized_Name"] = suppliers.Supplier_Name.map(norm)
        suppliers["Country"] = suppliers.Supplier_Country
        suppliers["Repeat_Wins"] = suppliers.Observed_Contracts_Won
        suppliers["Last_Updated_At"] = ingest
    else:
        suppliers = pd.DataFrame(columns=["Supplier_ID", "Supplier_Name", "Normalized_Name", "Country", "Observed_Contracts_Won", "Observed_Award_Value_Total", "Median_Award_Value", "Repeat_Wins", "Last_Updated_At"])

    frames = [
        (tenders, "historical_tenders.csv.gz"),
        (awards, "awards.csv.gz"),
        (bridge, "award_suppliers.csv.gz"),
        (buyers, "buyers.csv.gz"),
        (suppliers, "suppliers.csv.gz"),
    ]
    for frame, name in frames:
        frame.to_csv(out / name, index=False, compression="gzip")

    make_analytics(tenders, awards, out)

    q = {
        "version": VERSION,
        "source": "BOAMP official open-data monthly NDJSON snapshots",
        "window_start": start,
        "window_end": end,
        "source_files": source_files,
        "raw_lines": raw_lines,
        "parse_errors": parse_errors,
        "out_of_window_records": out_of_window,
        "unique_source_notices": len(records),
        "canonical_groups": len(groups),
        "normalized_tenders": len(tenders),
        "award_groups": len(awards),
        "award_supplier_links": len(bridge),
        "unique_buyers": int(tenders.Buyer_ID.nunique()) if len(tenders) else 0,
        "unique_suppliers": int(bridge.Supplier_ID.nunique()) if len(bridge) else 0,
        "result_only_reconstructed_groups": result_only_groups,
        "groups_with_explicit_notice_links": explicit_linked_groups,
        "publication_date_coverage_pct": round(tenders.Publication_Date.notna().mean() * 100, 2) if len(tenders) else 0,
        "deadline_coverage_pct": round(tenders.Deadline.notna().mean() * 100, 2) if len(tenders) else 0,
        "estimated_value_coverage_pct": round(tenders.Official_Estimated_Value.notna().mean() * 100, 2) if len(tenders) else 0,
        "award_link_rate_pct": round((tenders.Award_Link_Status == "LINKED").mean() * 100, 2) if len(tenders) else 0,
        "award_value_coverage_pct": round(awards.Award_Value.notna().mean() * 100, 2) if len(awards) else 0,
        "bidder_count_coverage_pct": round(awards.Bidder_Count.notna().mean() * 100, 2) if len(awards) else 0,
        "supplier_coverage_pct": round(awards.Supplier_Count.fillna(0).gt(0).mean() * 100, 2) if len(awards) else 0,
        "integrity": {
            "tender_ids_unique": bool(tenders.Historical_Tender_ID.is_unique) if len(tenders) else True,
            "award_ids_unique": bool(awards.Award_ID.is_unique) if len(awards) else True,
            "bridge_unique": not bridge.duplicated(["Award_ID", "Supplier_ID"]).any() if len(bridge) else True,
            "multi_supplier_group_values_not_allocated": bool(
                bridge.loc[bridge.Award_ID.isin(set(awards.loc[awards.Supplier_Count.fillna(0) > 1, "Award_ID"])), "Award_Value_Allocated"].isna().all()
            ) if len(bridge) and len(awards) else True,
        },
        "notes": [
            "Tender/result entities are joined only by BOAMP contractfolderid and explicit linked-notice identifiers when available.",
            "Result-only groups are retained with Source_Grain_Status=RESULT_ONLY_RECONSTRUCTED rather than discarded.",
            "Ambiguous repeated monetary fields are left null; lot values are never silently summed.",
            "Multi-supplier group totals are stored once on Awards and never copied to supplier bridge rows.",
            "Missing bidder counts remain null/UNKNOWN and are never estimated.",
        ],
    }
    (out / "data_quality.json").write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "version": VERSION,
        "created_at": ingest,
        "window": {"start": start, "end": end},
        "counts": {
            "tenders": len(tenders),
            "awards": len(awards),
            "award_suppliers": len(bridge),
            "buyers": len(buyers),
            "suppliers": len(suppliers),
        },
        "files": {},
    }
    for p in sorted(out.iterdir()):
        if p.is_file() and p.name != "run_manifest.json":
            manifest["files"][p.name] = {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(q, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2023-08-01")
    ap.add_argument("--end", default="2026-07-31")
    a = ap.parse_args()
    run(a.raw_dir, a.out, a.start, a.end)


if __name__ == "__main__":
    main()
