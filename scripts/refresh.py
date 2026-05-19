"""refresh.py - rebuild data/varieties.parquet from live sources.

Self-contained. No imports from sibling modules. Used by the GitHub Action
quarterly refresh and runnable locally with just pandas+pyarrow installed.

Live sources (re-pulled each run):
  - AGRA / CESSA varietycatalogues.com  (Laravel paginator)
  - PPV&FRA India                       (static JSON file)
  - FAO WIEWS Indicator 40              (POST API -> signed CSV URL)
  - CIMMYT Maize                        (Algolia public search key)

Cached sources (preserved from previous parquet; refresh manually when new
edition is announced):
  - NACGRAB Nigeria, KEPHIS Kenya, Ghana 2019, ECOWAS Regional 2022

Usage:
  python scripts/refresh.py --out data/varieties.parquet
"""
from __future__ import annotations
import argparse, csv, io, json, re, ssl, sys, urllib.request, pathlib
from datetime import datetime, timezone

import pandas as pd

# ============================================================================
# Constants
# ============================================================================

SOURCE_URL = {
    "agra":              "https://varietycatalogues.com/apiv1/public/api/seedcentredata",
    "ppvfra":            "https://plantauthority.gov.in/sites/default/files/cer.json",
    "nacgrab":           "https://www.nacgrab.gov.ng/wp-content/uploads/2025/10/Varieties-Released-Catalogue-updated-April-2025.pdf",
    "ecowas":            "https://ecowap.ecowas.int/media/events/concept/all/Regional_Catalogue_Version.pdf",
    "ghana_2019":        "https://nastag.org/docx/resources/2019%20NATIONAL%20CROP%20VARIETY%20CATALOGUE.pdf",
    "kephis_2025":       "https://www.kephis.go.ke/sites/default/files/2025-02/NATIONAL%20CROP%20VARIETY%20LIST-%202025%20EDITION.pdf",
    "wiews_indicator40": "https://www.fao.org/wiews/data/reporting/en/?indicator=40",
    "cimmyt_maize":      "https://cimmyt.technologypublisher.com/ (Algolia index CIMMYT_product_catalog)",
}

COUNTRY_NAME_TO_ISO3 = {
    "ETHIOPIA": "ETH", "GHANA": "GHA", "KENYA": "KEN", "MALAWI": "MWI",
    "NIGERIA": "NGA", "RWANDA": "RWA", "TANZANIA": "TZA", "UGANDA": "UGA",
    "BURKINA FASO": "BFA", "MALI": "MLI", "SENEGAL": "SEN", "CHAD": "TCD",
    "GAMBIA": "GMB", "INDIA": "IND", "TEST": "TST", "BENIN": "BEN",
    "NIGER": "NER", "TOGO": "TGO", "CÔTE D'IVOIRE": "CIV", "GUINEA": "GIN",
    "SIERRA LEONE": "SLE", "LIBERIA": "LBR", "CABO VERDE": "CPV",
    "GUINEA-BISSAU": "GNB", "MAURITANIA": "MRT",
    "ZAMBIA": "ZMB", "MOZAMBIQUE": "MOZ",
}

# ECOWAS breeder-string patterns -> ISO3 (order matters; first match wins)
ECOWAS_BREEDER_PATTERNS = [
    (r"\b(?:MLI|/Mali|IER)\b", "MLI"),
    (r"\b(?:SEN|ISRA)\b",       "SEN"),
    (r"\b(?:BFA|INERA|SINONIE\-? ?KOOBO|Burkina)\b", "BFA"),
    (r"\b(?:NGA|Nigeria|LCRI|IAR|NRCRI|IITA|WACOT|SAMLAK|Premier Seeds|Goldagric|VALUE SEEDS|BAYER NIGERIA)\b", "NGA"),
    (r"\b(?:TCD|ITRAD|Chad)\b", "TCD"),
    (r"\b(?:CRI GHANA|CSIR\-?(?:SARI|CRI)|GHA|Ghana)\b", "GHA"),
    (r"\b(?:NARI/GMB|GMB|Gambia)\b", "GMB"),
    (r"\b(?:NER|MANOMA|Niger)\b", "NER"),
    (r"\b(?:TGO|ITRA|Togo)\b", "TGO"),
    (r"\bICARDA\b",             "MLI"),
]

GHANA_CODE_CROPS = {
    "Zm": ("MAIZE",       "Zea mays L."),
    "Pg": ("PEARL MILLET","Pennisetum glaucum (L.) R. Br."),
    "Os": ("RICE",        "Oryza sativa L."),
    "Sb": ("SORGHUM",     "Sorghum bicolor (L.) Moench"),
    "Pv": ("BEAN",        "Phaseolus vulgaris L."),
    "Vu": ("COWPEA",      "Vigna unguiculata L. Walp."),
    "Ah": ("GROUNDNUT",   "Arachis hypogaea L."),
    "Gm": ("SOYBEAN",     "Glycine max (L.) Merr."),
    "Cm": ("BAMBARA GROUNDNUT", "Vigna subterranea (L.) Verdc."),
    "Sl": ("TOMATO",      "Solanum lycopersicum L."),
    "Ae": ("OKRA",        "Abelmoschus esculentus (L.) Moench"),
    "Cp": ("PEPPER",      "Capsicum spp."),
    "Cs": ("CASSAVA",     "Manihot esculenta Crantz"),
    "Da": ("YAM",         "Dioscorea alata L."),
    "Dr": ("YAM",         "Dioscorea rotundata Poir."),
    "Ib": ("SWEET POTATO","Ipomoea batatas (L.) Lam."),
    "Mp": ("PLANTAIN",    "Musa paradisiaca L."),
    "Ms": ("BANANA",      "Musa spp."),
    "Hs": ("ROSELLE",     "Hibiscus sabdariffa L."),
    "Sf": ("SHEA",        "Vitellaria paradoxa C.F. Gaertn."),
    "Ec": ("FONIO",       "Digitaria exilis Stapf"),
}
GHANA_CODE_RE = re.compile(r"^GH/([A-Z][a-z])(?:/|$)")

CROP_FR_EN = {
    "ARACHIDE": "GROUNDNUT", "BLÉ": "WHEAT", "COTONNIER": "COTTON",
    "GOMBO": "OKRA", "IGNAME": "YAM", "MAIS": "MAIZE", "MANIOC": "CASSAVA",
    "MIL PÉNICILLAIRE": "PEARL MILLET", "MIL": "PEARL MILLET",
    "NIÉBÉ": "COWPEA", "OIGNON": "ONION", "PATATE DOUCE": "SWEET POTATO",
    "POMME DE TERRE": "POTATO", "RIZ": "RICE", "SOJA": "SOYBEAN",
    "SORGHO": "SORGHUM", "TOMATE": "TOMATO",
}

CROP_ALIAS = {
    "BREAD WHEAT": "WHEAT", "DURUM WHEAT": "WHEAT", "EMMER WHEAT": "WHEAT",
    "BUCK WHEAT": "BUCKWHEAT", "COMMON BEAN": "BEAN",
    "SOYBEAN ": "SOYBEAN", "SUNFLOWER ": "SUNFLOWER",
    "PIGEON PEA": "PIGEONPEA", "BLACK GRAM": "BLACKGRAM",
    "OKRA/LADY'S FINGER": "OKRA", "IRISH POTATO": "POTATO",
    "MAÍZ": "MAIZE", "MAIZ": "MAIZE", "MAÏS": "MAIZE",
    "TRIGO": "WHEAT", "BLÉ TENDRE": "WHEAT", "BLÉ DUR": "WHEAT",
    "SOJA": "SOYBEAN", "SOYBEANS": "SOYBEAN",
    "POTATOES": "POTATO", "TOMATOES": "TOMATO", "GRAPES": "GRAPE",
    "ORNAMENTAL PLANTS": "ORNAMENTAL", "SUGAR BEET": "SUGARBEET",
    "STRAWBERRIES": "STRAWBERRY",
}

VTYPE_MAP = {
    "HYBRID": "hybrid", "HYBRIDE": "hybrid", "OPV": "opv",
    "SELF-POLLINATED": "self_pollinated", "AUTOGAME": "self_pollinated",
    "VEG/CLONALLY PROPAGATED": "vegetative", "VEGCLONALLY-PROPAGATED": "vegetative",
    "LIGNE PURE": "lineage", "LIGNÉE": "lineage", "LIGNEE": "lineage",
    "NEW": "new", "EXTANT (VCK)": "extant_vck",
    "EXTANT (NOTIFIED)": "extant_notified", "FARMER": "farmer", "EDV": "edv",
}

AGRA_STATUS_MAP = {
    "FULL": "released", "LIMITED": "released", "EMERGING": "released",
    "NOT COMMERCIALISED": "registered", "NO DATA": "unknown",
}

PPVFRA_STATUS_MAP = {
    "Registration Certificate Issued": "registered",
    "Application Withdrawn":           "withdrawn",
    "Application Closed":              "closed",
    "Pre-grant opposition invited":    "candidate",
}

CIMMYT_REGION_ISO3 = {
    "Eastern Africa": None, "Southern Africa": None,
    "Latin America": None,  "South Asia": None,
}

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# ---- Country inference patterns (post-extraction) -----------------------

KENYAN_ORG_PATTERNS = [
    r"\bKALRO\b", r"KENYA AGRICULTURAL", r"KENYA SEED COMPANY",
    r"\bCORTEVA AGRISCIENCE KENYA", r"BAYER EAST AFRICA",
    r"\bSEED CO LIMITED\b", r"WESTERN SEED", r"UNIVERSITY OF NAIROBI",
    r"\bSYNGENTA\b", r"EGERTON UNIVERSITY", r"AFRITEC SEEDS",
    r"FRESHCO KENYA", r"HYTECH SEED KENYA", r"NATIONAL IRRIGATION AUTHORITY",
    r"LELDET", r"MASENO UNIVERSITY", r"PEAL AGRO", r"EAST AFRICAN SEED",
    r"RONGO UNIVERSITY", r"AGVENTURE", r"MONSANTO", r"\bKARI\b",
    r"KENYA HIGHLAND", r"AMINIATA", r"KENYA[^A-Z]",
    r"\bADVANTA SEEDS\b", r"SIMLAW SEED", r"LAGROTECH",
    r"HYBRIDS EAST AFRICA", r"UNIVERSITY OF ELDORET", r"OIL CROP DEVELOPMENT",
    r"CROOKHAM", r"DRYLAND SEED", r"AFRICE SEED", r"POP VRIEND",
    r"AGROSOY", r"CULTIVO AFRICA", r"\bKWS\b", r"FARM INPUTS CARE CENTER",
    r"\bFICA SEEDS?\b", r"INTERNATIONAL CENTRE OF INSECT PHYSIOLOGY",
    r"AGRISCOPE AFRICA", r"PURE SEEDS EAST AFRICA",
    r"ELGON SEED", r"STARKE AYRES", r"WAKALA AFRICA",
    r"ICRSAT[/ ]KSCO", r"\bKSCO\b",
]
KENYAN_RE = re.compile("|".join(KENYAN_ORG_PATTERNS), re.IGNORECASE)

UGANDAN_RE = re.compile(
    "|".join([r"NALWEYO", r"NaCRRI", r"NATIONAL CROPS RESOURCES RESEARCH INSTI"]),
    re.IGNORECASE)
TANZANIAN_RE = re.compile(
    "|".join([r"TANZANIA AGRICULTURAL RESEARCH", r"\bTARI\b", r"\bTOSCI\b"]),
    re.IGNORECASE)
ZAMBIAN_RE = re.compile(
    "|".join([r"ZAMBIA SEED", r"\bZAMSEED\b", r"\bZARI\b"]),
    re.IGNORECASE)

ECOWAS_NAME_PATTERNS = [
    (re.compile(r"^ISRIZ",        re.I), "SEN", "ISRA Senegal rice naming"),
    (re.compile(r"^ARICA[- ]IER", re.I), "MLI", "ARICA × IER Mali"),
    (re.compile(r"^GMB[\s\-]LS",  re.I), "GMB", "GMB LS = Gambia LowSubsistence"),
]
MULTI_COUNTRY_BRAND_PATTERNS = [
    re.compile(r"^ARIZE\b", re.I), re.compile(r"^KAFACI", re.I),
    re.compile(r"^ARICA[- ]RP", re.I), re.compile(r"^FENGYOU", re.I),
    re.compile(r"^WINALL", re.I), re.compile(r"^SEMAX", re.I),
    re.compile(r"^DJITABA$", re.I), re.compile(r"^DKA[- ]?M\d", re.I),
]

# ============================================================================
# Helpers
# ============================================================================

RETRIEVED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

def iso3_from_country_name(s):
    if not s: return None
    return COUNTRY_NAME_TO_ISO3.get(s.strip().upper())

def iso3_from_breeder(s):
    if not s: return None
    for pat, code in ECOWAS_BREEDER_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return code
    return None

def ghana_crop_from_code(code):
    if not code: return (None, None)
    m = GHANA_CODE_RE.match(code.strip())
    return GHANA_CODE_CROPS.get(m.group(1), (None, None)) if m else (None, None)

def normalise_crop(s):
    if not s: return ""
    s = s.strip().upper()
    s = CROP_FR_EN.get(s, s)
    return CROP_ALIAS.get(s, s)

def normalise_vtype(s):
    if not s: return ""
    return VTYPE_MAP.get(s.strip().upper(), s.strip().lower())

def parse_year(s):
    if s is None: return None
    m = YEAR_RE.search(str(s))
    return int(m.group(0)) if m else None

# ============================================================================
# Per-source adapters
# ============================================================================

def from_agra(rec):
    cname = (rec.get("seedcountryname") or "").strip()
    commercial = rec.get("seedcommerciallevelsname") or ""
    return {
        "source": "agra",
        "source_record_id": str(rec.get("id","")),
        "country_iso3": iso3_from_country_name(cname),
        "country_name": cname.title(),
        "crop": normalise_crop(rec.get("seedcropname") or ""),
        "crop_latin": None,
        "variety_name": (rec.get("varietyname") or "").strip(),
        "variety_aliases": "; ".join(filter(None, [rec.get("commercialnames"), rec.get("releasingentity")])) or None,
        "variety_type": normalise_vtype(rec.get("seedtypename") or ""),
        "year_release": parse_year(rec.get("yearofrelease")),
        "breeder": rec.get("releasingentity") or None,
        "maintainer": rec.get("maintainer") or None,
        "status": commercial or None,
        "release_status": AGRA_STATUS_MAP.get(commercial.upper(), "unknown"),
        "ecology": rec.get("regions") or None,
        "notes": rec.get("allspecialattributes") or None,
        "source_url": SOURCE_URL["agra"],
        "retrieved_at": RETRIEVED_AT,
    }

def from_ppvfra(rec):
    status_raw = rec.get("PresentStatus") or ""
    return {
        "source": "ppvfra",
        "source_record_id": rec.get("AckNo") or "",
        "country_iso3": "IND", "country_name": "India",
        "crop": normalise_crop(rec.get("CropName") or ""),
        "crop_latin": None,
        "variety_name": (rec.get("Denomination") or "").strip(),
        "variety_aliases": None,
        "variety_type": normalise_vtype(rec.get("TypeVariety") or ""),
        "year_release": parse_year(rec.get("Datefiling")),
        "breeder": rec.get("ApplicantName") or None,
        "maintainer": None,
        "status": status_raw or None,
        "release_status": PPVFRA_STATUS_MAP.get(status_raw, "candidate" if status_raw else "unknown"),
        "ecology": None,
        "notes": rec.get("RemarksforApplicant") or None,
        "source_url": SOURCE_URL["ppvfra"],
        "retrieved_at": RETRIEVED_AT,
    }

def from_wiews(rec):
    iso3 = (rec.get("Country (ISO3)") or "").strip().upper() or None
    yr = parse_year(rec.get("Year of release") or rec.get("Year of registration"))
    cultivar = (rec.get("Cultivar name") or "").strip()
    answer_id = rec.get("Answer ID") or ""
    notes_parts = []
    for k, v in rec.items():
        if k is None or not v: continue
        ks = k.strip()
        if ks in ("Improved variety", "Introduced from abroad", "Farmer variety"):
            notes_parts.append(f"{ks}: {v}")
    return {
        "source": "wiews_indicator40",
        "source_record_id": f"WIEWS#{answer_id or (iso3 or '?')+'#'+cultivar[:30]}",
        "country_iso3": iso3,
        "country_name": (rec.get("Country") or "").strip() or None,
        "crop": normalise_crop(rec.get("Crop name") or ""),
        "crop_latin": (rec.get("Taxon name") or "").strip() or None,
        "variety_name": cultivar,
        "variety_aliases": None,
        "variety_type": None,
        "year_release": yr,
        "breeder": (rec.get("Breeding organization") or rec.get("Breeder person") or "").strip() or None,
        "maintainer": None,
        "status": None,
        "release_status": "released" if yr else "registered",
        "ecology": None,
        "notes": " | ".join(notes_parts) or None,
        "source_url": SOURCE_URL["wiews_indicator40"],
        "retrieved_at": RETRIEVED_AT,
    }

def from_cimmyt(rec):
    facets = {}
    for token in (rec.get("finalPathCategories") or "").split(","):
        token = token.strip()
        if " > " not in token: continue
        k, v = token.split(" > ", 1)
        facets.setdefault(k.strip(), []).append(v.strip())
    region = (facets.get("Region") or [None])[0]
    yr_vals = facets.get("Year announced") or []
    year = parse_year(yr_vals[0]) if yr_vals else None
    ptype = (facets.get("Product Type") or [None])[0]
    vt_map = {"Open-pollinated variety (OPV)": "opv",
              "Single-cross hybrid": "hybrid",
              "Three-way cross hybrid": "hybrid"}
    skip = {"Region", "Year announced", "Product Type", "Germplasm"}
    note_parts = []
    desc = (rec.get("descriptionTruncated") or "").strip()
    if desc: note_parts.append(desc)
    for cat, vals in facets.items():
        if cat in skip: continue
        note_parts.append(f"{cat}: {', '.join(vals)}")
    return {
        "source": "cimmyt_maize",
        "source_record_id": rec.get("techID") or rec.get("objectID") or "?",
        "country_iso3": CIMMYT_REGION_ISO3.get(region) if region else None,
        "country_name": region,
        "crop": "MAIZE", "crop_latin": "Zea mays L.",
        "variety_name": (rec.get("title") or "").strip(),
        "variety_aliases": rec.get("techID") or None,
        "variety_type": vt_map.get(ptype) if ptype else None,
        "year_release": year,
        "breeder": "CIMMYT",
        "maintainer": None,
        "status": None,
        "release_status": "released" if year else "unknown",
        "ecology": region,
        "notes": " | ".join(note_parts) or None,
        "source_url": rec.get("Url") or SOURCE_URL["cimmyt_maize"],
        "retrieved_at": RETRIEVED_AT,
    }

# ============================================================================
# Flag + infer pass
# ============================================================================

def infer_country(rec):
    """Return (iso3, basis) when inference fires; (None, None) otherwise."""
    src = rec.get("source")
    if src == "agra" and rec.get("country_iso3") == "TST":
        text = " ".join(filter(None, [rec.get("breeder"), rec.get("maintainer")]))
        if UGANDAN_RE.search(text):
            return "UGA", "AGRA TEST placeholder; breeder/maintainer is Ugandan (NaCRRI/Nalweyo)"
        if TANZANIAN_RE.search(text):
            return "TZA", "AGRA TEST placeholder; breeder/maintainer is Tanzanian (TARI/TOSCI)"
        if ZAMBIAN_RE.search(text):
            return "ZMB", "AGRA TEST placeholder; breeder/maintainer is Zambian (ZAMSEED/ZARI)"
        if KENYAN_RE.search(text):
            return "KEN", "AGRA TEST placeholder; breeder/maintainer is Kenyan"
    if src == "ecowas" and not rec.get("country_iso3"):
        name = rec.get("variety_name") or ""
        for pat, code, basis in ECOWAS_NAME_PATTERNS:
            if pat.search(name):
                return code, f"variety name '{name}' matches {basis}"
        if (rec.get("breeder") or "").strip().upper() == "CRI":
            return "GHA", "breeder 'CRI' is Ghana Crops Research Institute"
    return None, None

def review_flags(rec):
    flags = []
    src = rec.get("source")
    if src == "agra" and rec.get("country_iso3") == "TST":
        flags.append("agra_test_country")
    if not rec.get("country_iso3"):
        name = rec.get("variety_name") or ""
        if src == "ecowas" and any(p.search(name) for p in MULTI_COUNTRY_BRAND_PATTERNS):
            flags.append("multi_country_brand")
        elif src == "cimmyt_maize":
            flags.append("regional_release")
        else:
            flags.append("no_country")
    if src == "kephis_2025":
        missing = [k for k in ("variety_name","year_release","breeder") if not rec.get(k)]
        if missing:
            flags.append("kephis_partial_extract:" + ",".join(missing))
    vn = (rec.get("variety_name") or "").strip()
    if vn and vn.isdigit():
        flags.append("variety_name_is_digit_only")
    return flags

def apply_flags_and_infer(rows):
    for r in rows:
        iso3, basis = infer_country(r)
        if iso3:
            r["_country_iso3_source"] = r.get("country_iso3")
            r["country_iso3"] = iso3
            if not r.get("country_name"):
                names = {"KEN":"Kenya","SEN":"Senegal","MLI":"Mali",
                         "GMB":"Gambia","GHA":"Ghana","UGA":"Uganda",
                         "TZA":"Tanzania","ZMB":"Zambia"}
                r["country_name"] = names.get(iso3)
            r["country_inferred"] = True
            r["inference_basis"]  = basis
        else:
            r["country_inferred"] = False
            r["inference_basis"]  = None
        r["review_flags"] = ";".join(review_flags(r))

# ============================================================================
# Live source pulls
# ============================================================================

NOAUTH = ssl.create_default_context(); NOAUTH.check_hostname=False; NOAUTH.verify_mode=ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 Chrome/131", "Accept-Language": "en-US,en;q=0.9"}

def _get(url, **kw):
    req = urllib.request.Request(url, headers=UA, **kw)
    with urllib.request.urlopen(req, timeout=60, context=NOAUTH) as r:
        return r.read()

def pull_agra():
    base = "https://varietycatalogues.com/apiv1/public/api"
    rows, page = [], 1
    while True:
        obj = json.loads(_get(f"{base}/seedcentredata?page={page}&perPage=200"))
        p = obj.get("filterdata", {}) or {}
        data = p.get("data", []) or []
        if not data: break
        rows.extend(data)
        if page >= (p.get("last_page") or 1): break
        page += 1
    return rows

def pull_ppvfra():
    return json.loads(_get("https://plantauthority.gov.in/sites/default/files/cer.json"))

def pull_wiews():
    body = json.dumps({"lang":"en","indicator":40,"separator":",",
        "filters":{"region":{"type":"M49","values":["1"]},"iteration":["1"]}}).encode()
    req = urllib.request.Request("https://wiews.fao.org/wiewsIndicatorsRawDownload",
        data=body, method="POST", headers={**UA,
        "Content-Type":"text/plain; charset=UTF-8", "Referer":"https://www.fao.org/"})
    with urllib.request.urlopen(req, timeout=60, context=NOAUTH) as r:
        signed = json.loads(r.read())[0]
    text = _get(signed).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))

def pull_cimmyt():
    APP, KEY = "GGLKL5VA1C", "2d973ad94320e2676f6703c50f20e1d7"
    url = f"https://{APP.lower()}-dsn.algolia.net/1/indexes/CIMMYT_product_catalog/query"
    rows, page = [], 0
    while True:
        body = json.dumps({"params": f"query=&page={page}&hitsPerPage=100&facets=%5B%22*%22%5D"}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            **UA, "X-Algolia-Application-Id": APP,
            "X-Algolia-API-Key": KEY,
            "Content-Type":"application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30, context=NOAUTH) as r:
            resp = json.loads(r.read())
        hits = resp.get("hits", [])
        rows.extend(hits)
        if not hits or len(rows) >= resp.get("nbHits", 0): break
        page += 1
    return rows

# ============================================================================
# Driver
# ============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/varieties.parquet")
    args = ap.parse_args()

    out = pathlib.Path(args.out)

    # Preserve PDF-sourced rows from the previous build (no live API for them)
    preserved = []
    if out.exists():
        prev = pd.read_parquet(out)
        pdf_srcs = {"nacgrab", "kephis_2025", "ghana_2019", "ecowas"}
        preserved = prev[prev["source"].isin(pdf_srcs)].to_dict("records")
        print(f"preserved {len(preserved)} PDF-sourced rows from previous build")

    print("pulling AGRA ...");    agra    = pull_agra();    print(f"  {len(agra)}")
    print("pulling PPV&FRA ..."); ppvfra  = pull_ppvfra();  print(f"  {len(ppvfra)}")
    print("pulling WIEWS ...");   wiews   = pull_wiews();   print(f"  {len(wiews)}")
    print("pulling CIMMYT ...");  cimmyt  = pull_cimmyt();  print(f"  {len(cimmyt)}")

    unified = []
    unified.extend(from_agra(r)    for r in agra)
    unified.extend(from_ppvfra(r)  for r in ppvfra)
    unified.extend(from_wiews(r)   for r in wiews)
    unified.extend(from_cimmyt(r)  for r in cimmyt)
    unified.extend(preserved)

    apply_flags_and_infer(unified)

    df = pd.DataFrame(unified)
    df["year_release"] = pd.to_numeric(df["year_release"], errors="coerce").astype("Int64")
    df["country_inferred"] = df["country_inferred"].fillna(False).astype(bool)

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, compression="snappy", index=False)
    df.to_csv(out.with_suffix(".csv"), index=False, encoding="utf-8")
    print(f"\nwrote {out} ({out.stat().st_size:,} bytes, {len(df):,} rows)")

    by_src = df["source"].value_counts().to_dict()
    print("\nby source:")
    for k, v in sorted(by_src.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<22} {v:>7,}")

if __name__ == "__main__":
    sys.exit(main())
