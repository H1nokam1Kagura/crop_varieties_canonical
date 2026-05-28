"""
unify_varieties.py - merge AGRA + PPV&FRA + NACGRAB + ECOWAS into one schema.

Output:
  unified/varieties.jsonl  one record per line (full fidelity, includes raw)
  unified/varieties.csv    flat CSV of the unified columns (no raw)
  unified/schema.md        schema doc + counts per source
"""
from __future__ import annotations
import csv
import json
import pathlib
import re
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(r"C:\Users\neilha\Downloads")
OUT  = ROOT / "complementary" / "unified"
OUT.mkdir(exist_ok=True)

# Per-source provenance URLs (recorded against every row from that source)
SOURCE_URL = {
    "agra":        "https://varietycatalogues.com/apiv1/public/api/seedcentredata",
    "ppvfra":      "https://plantauthority.gov.in/sites/default/files/cer.json",
    "nacgrab":     "https://www.nacgrab.gov.ng/wp-content/uploads/2025/10/Varieties-Released-Catalogue-updated-April-2025.pdf",
    "ecowas":      "https://ecowap.ecowas.int/media/events/concept/all/Regional_Catalogue_Version.pdf",
    "ghana_2019":  "https://nastag.org/docx/resources/2019%20NATIONAL%20CROP%20VARIETY%20CATALOGUE.pdf",
    "kephis_2025": "https://www.kephis.go.ke/sites/default/files/2025-02/NATIONAL%20CROP%20VARIETY%20LIST-%202025%20EDITION.pdf",
    "wiews_indicator40": "https://www.fao.org/wiews/data/reporting/en/?indicator=40",
    "cimmyt_maize":      "https://cimmyt.technologypublisher.com/ (Algolia index CIMMYT_product_catalog)",
}

# CIMMYT regions → ISO3 best-effort. Many varieties are bred for a region, not
# tied to a single country; record region in ecology and leave iso3 null when
# the region maps to multiple countries.
CIMMYT_REGION_ISO3 = {
    "Eastern Africa": None,    # KEN, TZA, UGA, ETH, RWA
    "Southern Africa": None,   # ZWE, ZMB, MWI, MOZ, ZAF
    "Latin America": None,     # multi
    "South Asia": None,        # IND, PAK, BGD, NPL
}

# AGRA seedcommerciallevelsname -> release_status enum
AGRA_STATUS_MAP = {
    "FULL":          "released",
    "LIMITED":       "released",
    "EMERGING":      "released",
    "NOT COMMERCIALISED": "registered",
    "NO DATA":       "unknown",
}

# PPV&FRA PresentStatus -> release_status enum
PPVFRA_STATUS_MAP = {
    "Registration Certificate Issued": "registered",
    "Application Withdrawn":           "withdrawn",
    "Application Closed":              "closed",
    "Pre-grant opposition invited":    "candidate",
}

RETRIEVED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

# ----- Country normalisation -----
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
    (r"\bICARDA\b",             "MLI"),  # ICARDA collaborates with country institutes; default to Mali base in ECOWAS context — but the row usually has another country tag too
]

# Ghana 2019 National Code prefix -> (crop, latin)
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

def ghana_crop_from_code(code: str):
    if not code: return (None, None)
    m = GHANA_CODE_RE.match(code.strip())
    if not m: return (None, None)
    return GHANA_CODE_CROPS.get(m.group(1), (None, None))

def iso3_from_country_name(s: str) -> str | None:
    if not s: return None
    s = s.strip().upper()
    return COUNTRY_NAME_TO_ISO3.get(s)

def iso3_from_breeder(s: str) -> str | None:
    if not s: return None
    for pat, code in ECOWAS_BREEDER_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return code
    return None

# ----- Crop normalisation (FR -> EN, plus upper-casing) -----
CROP_FR_EN = {
    "ARACHIDE": "GROUNDNUT",
    "BLÉ": "WHEAT",
    "COTONNIER": "COTTON",
    "GOMBO": "OKRA",
    "IGNAME": "YAM",
    "MAIS": "MAIZE",
    "MANIOC": "CASSAVA",
    "MIL PÉNICILLAIRE": "PEARL MILLET",
    "MIL": "PEARL MILLET",
    "NIÉBÉ": "COWPEA",
    "OIGNON": "ONION",
    "PATATE DOUCE": "SWEET POTATO",
    "POMME DE TERRE": "POTATO",
    "RIZ": "RICE",
    "SOJA": "SOYBEAN",
    "SORGHO": "SORGHUM",
    "TOMATE": "TOMATO",
}

# Per-source quirky crop name normalisation
CROP_ALIAS = {
    "BREAD WHEAT": "WHEAT",
    "DURUM WHEAT": "WHEAT",
    "EMMER WHEAT": "WHEAT",
    "BUCK WHEAT": "BUCKWHEAT",
    "COMMON BEAN": "BEAN",
    "SOYBEAN ": "SOYBEAN",       # AGRA has trailing space
    "SUNFLOWER ": "SUNFLOWER",
    "PIGEON PEA": "PIGEONPEA",
    "BLACK GRAM": "BLACKGRAM",
    "OKRA/LADY'S FINGER": "OKRA",
    "PEARL MILLET": "PEARL MILLET",
    "IRISH POTATO": "POTATO",
    # WIEWS multilingual variants (FAO submissions arrive in EN/ES/FR/PT)
    "MAÍZ": "MAIZE", "MAIZ": "MAIZE", "MAÏS": "MAIZE",
    "TRIGO": "WHEAT", "BLÉ TENDRE": "WHEAT", "BLÉ DUR": "WHEAT",
    "SOJA": "SOYBEAN", "SOYBEANS": "SOYBEAN",
    "POTATOES": "POTATO",
    "TOMATOES": "TOMATO",
    "GRAPES": "GRAPE",
    "ORNAMENTAL PLANTS": "ORNAMENTAL",
    "SUGAR BEET": "SUGARBEET",
    "STRAWBERRIES": "STRAWBERRY",
}

def normalise_crop(s: str) -> str:
    if not s: return ""
    s = s.strip().upper()
    s = CROP_FR_EN.get(s, s)
    s = CROP_ALIAS.get(s, s)
    return s

# ----- Variety type normalisation -----
VTYPE_MAP = {
    "HYBRID": "hybrid", "HYBRIDE": "hybrid",
    "OPV": "opv",
    "SELF-POLLINATED": "self_pollinated", "AUTOGAME": "self_pollinated",
    "VEG/CLONALLY PROPAGATED": "vegetative", "VEGCLONALLY-PROPAGATED": "vegetative",
    "LIGNE PURE": "lineage", "LIGNÉE": "lineage", "LIGNEE": "lineage",
    "NEW": "new", "EXTANT (VCK)": "extant_vck", "EXTANT (NOTIFIED)": "extant_notified",
    "FARMER": "farmer", "EDV": "edv",
}
def normalise_vtype(s: str) -> str:
    if not s: return ""
    return VTYPE_MAP.get(s.strip().upper(), s.strip().lower())

# ----- Year parsing -----
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
def parse_year(s) -> int | None:
    if s is None: return None
    s = str(s)
    m = YEAR_RE.search(s)
    return int(m.group(0)) if m else None

# ----- Adapters per source -----
def from_agra(rec: dict) -> dict:
    cname = (rec.get("seedcountryname") or "").strip()
    commercial = rec.get("seedcommerciallevelsname") or ""
    return {
        "source": "agra",
        "source_record_id": str(rec.get("id", "")),
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
        "raw": rec,
    }

def from_ppvfra(rec: dict) -> dict:
    status_raw = rec.get("PresentStatus") or ""
    return {
        "source": "ppvfra",
        "source_record_id": rec.get("AckNo") or "",
        "country_iso3": "IND",
        "country_name": "India",
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
        "raw": rec,
    }

def from_nacgrab(rec: dict) -> dict:
    crop = rec.get("Crop_Name") or ""
    name = rec.get("Variety Name") or ""
    orig = rec.get("Original Name") or ""
    code = rec.get("National Code") or ""
    aliases = "; ".join(filter(None, [orig, code]))
    year = parse_year(rec.get("Year of Release")) or parse_year(rec.get("Year of Registry"))
    notes = rec.get("Outstanding Characteristics/ Potential Yields") or None
    breeder = " | ".join(filter(None, [
        rec.get("Developing Institute"),
        rec.get("Collaborating Institute"),
        rec.get("Breeder/ Collaborating Scientists"),
    ])) or None
    return {
        "source": "nacgrab",
        "source_record_id": f"{crop}#{rec.get('S/N','')}",
        "country_iso3": "NGA",
        "country_name": "Nigeria",
        "crop": normalise_crop(crop),
        "crop_latin": None,
        "variety_name": name.strip(),
        "variety_aliases": aliases or None,
        "variety_type": None,  # not present in NACGRAB
        "year_release": year,
        "breeder": breeder,
        "maintainer": None,
        "status": None,
        "release_status": "released" if year else "unknown",
        "ecology": rec.get("Agro- Ecological Zones") or None,
        "notes": notes,
        "source_url": SOURCE_URL["nacgrab"],
        "retrieved_at": RETRIEVED_AT,
        "raw": rec,
    }

def from_ghana(rec: dict) -> dict:
    code = rec.get("National Code") or ""
    crop, latin = ghana_crop_from_code(code)
    name = rec.get("Name of Variety") or ""
    breeder = rec.get("Breeder (s)/ Institution") or rec.get("Applicant") or None
    dus = rec.get("Distinctness Uniformity and Stability (DUS)") or ""
    vcu = rec.get("Value for Cultivation and Use (VCU)") or ""
    notes_parts = [s for s in (dus, vcu) if s]   # ecology now promoted to its own column
    notes = " | ".join(notes_parts) or None
    yr = parse_year(rec.get("Year of Release")) or parse_year(rec.get("Year of Registry"))
    pedigree = rec.get("Pedigree/ Line") or None
    return {
        "source": "ghana_2019",
        "source_record_id": code or name,
        "country_iso3": "GHA",
        "country_name": "Ghana",
        "crop": crop or "",
        "crop_latin": latin,
        "variety_name": name.strip(),
        "variety_aliases": "; ".join(filter(None, [code, pedigree])) or None,
        "variety_type": None,
        "year_release": yr,
        "breeder": breeder,
        "maintainer": None,
        "status": None,
        "release_status": "registered" if yr else "unknown",
        "ecology": rec.get("Preferred Ecology") or None,
        "notes": notes,
        "source_url": SOURCE_URL["ghana_2019"],
        "retrieved_at": RETRIEVED_AT,
        "raw": rec,
    }

# KEPHIS column variants -> canonical (fuzzy due to PDF text-wrapping fragmentation)
def _find_key(rec, *substrings, exclude=()):
    """Return value of first record key matching ANY of the substrings (case-insensitive,
    whitespace-collapsed). Skips keys matching any exclude substring."""
    for k in rec.keys():
        if not k: continue
        kk = " ".join(k.lower().split())
        if any(ex in kk for ex in exclude):
            continue
        for s in substrings:
            if s in kk:
                v = rec.get(k)
                if v and str(v).strip():
                    return str(v).strip()
    return None

def from_kephis(rec: dict) -> dict:
    section = rec.get("_section") or ""
    # _species was sometimes captured with following header text; trim at newline
    species_raw = rec.get("_species")
    species = (species_raw or "").split("\n", 1)[0].strip() or None
    # Variety name: prefer "Official Release Name" (most canonical), fall back to "Variety name"
    name = (_find_key(rec, "official release name", "official rele ase nam")
            or _find_key(rec, "variety name", "variety name/code", "variety name/cod",
                         "variety testing name", "variety / hybrid name", "variety/hybrid name")
            or _find_key(rec, "variety", exclude=("testing",)))
    name = (name or "").lstrip("0123456789. ").strip()  # strip leading "1." etc.

    yr_raw = _find_key(rec, "year of rel", "year of releas")  # catches all wrapped variants
    year   = parse_year(yr_raw)

    owner = _find_key(rec, "owner", "licensee")
    maint = _find_key(rec, "mainta", "maint ainer", "maint aine")  # 'Maintaine r' edge case
    attrs = _find_key(rec, "special attribut")
    yld   = _find_key(rec, "yield")
    alt   = _find_key(rec, "altitude")
    dur   = _find_key(rec, "duration to mat", "maturit")

    notes_parts = [s for s in (attrs, alt and f"Alt(masl): {alt}",
                               dur and f"Maturity: {dur}", yld and f"Yield: {yld}")
                   if s]
    notes = " | ".join(notes_parts) or None
    sn = (rec.get("") or "").strip() or None
    return {
        "source": "kephis_2025",
        "source_record_id": f"{section}#{sn or name[:30]}",
        "country_iso3": "KEN",
        "country_name": "Kenya",
        "crop": normalise_crop(section),
        "crop_latin": species,
        "variety_name": (name or "").strip(),
        "variety_aliases": None,
        "variety_type": None,
        "year_release": year,
        "breeder": owner,
        "maintainer": maint,
        "status": None,
        "release_status": "released" if year else "unknown",
        "ecology": alt and f"altitude_masl: {alt}",
        "notes": notes,
        "source_url": SOURCE_URL["kephis_2025"],
        "retrieved_at": RETRIEVED_AT,
        "raw": rec,
    }

def from_cimmyt(rec: dict) -> dict:
    """Adapter for CIMMYT maize catalog (Algolia index CIMMYT_product_catalog).

    Source: POST https://gglkl5va1c-dsn.algolia.net/1/indexes/CIMMYT_product_catalog/query
    (public search-only API key embedded in cimmyt.technologypublisher.com).
    Each hit has techID, title, descriptionTruncated, Url, finalPathCategories.
    Region/Year/Type/etc. are concatenated in finalPathCategories as
      "<facet> > <value>, <facet> > <value>, ..."
    """
    # Parse facets
    facets: dict[str, list[str]] = {}
    cats = rec.get("finalPathCategories") or ""
    for token in cats.split(","):
        token = token.strip()
        if " > " not in token: continue
        k, v = token.split(" > ", 1)
        facets.setdefault(k.strip(), []).append(v.strip())

    region = (facets.get("Region") or [None])[0]
    iso3 = CIMMYT_REGION_ISO3.get(region) if region else None
    year = None
    yr_vals = facets.get("Year announced") or []
    if yr_vals: year = parse_year(yr_vals[0])

    ptype = (facets.get("Product Type") or [None])[0]
    # Map CIMMYT product types to canonical variety_type
    vt_map = {"Open-pollinated variety (OPV)": "opv",
              "Single-cross hybrid": "hybrid",
              "Three-way cross hybrid": "hybrid"}
    variety_type = vt_map.get(ptype) if ptype else None

    # Trait notes — merge all category facets except those promoted to columns
    skip_cats = {"Region", "Year announced", "Product Type", "Germplasm"}
    note_parts = []
    for cat, vals in facets.items():
        if cat in skip_cats: continue
        note_parts.append(f"{cat}: {', '.join(vals)}")
    desc = (rec.get("descriptionTruncated") or "").strip()
    if desc: note_parts.insert(0, desc)
    notes = " | ".join(note_parts) or None

    return {
        "source": "cimmyt_maize",
        "source_record_id": rec.get("techID") or rec.get("objectID") or "?",
        "country_iso3": iso3,         # None for regional releases
        "country_name": region,        # the breeding-target region
        "crop": "MAIZE",
        "crop_latin": "Zea mays L.",
        "variety_name": (rec.get("title") or "").strip(),
        "variety_aliases": rec.get("techID") or None,
        "variety_type": variety_type,
        "year_release": year,
        "breeder": "CIMMYT",
        "maintainer": None,
        "status": None,
        "release_status": "released" if year else "unknown",
        "ecology": region,
        "notes": notes,
        "source_url": (rec.get("Url") or SOURCE_URL["cimmyt_maize"]),
        "retrieved_at": RETRIEVED_AT,
        "raw": rec,
    }


def from_wiews(rec: dict) -> dict:
    """Adapter for FAO WIEWS Indicator 40 raw CSV export.

    Source: POST https://wiews.fao.org/wiewsIndicatorsRawDownload (anon).
    Schema (CSV columns):
      Period(ID), Period, Country (ISO3), Country, Stakeholder (Instcode),
      Stakeholder, Answer ID, Taxon (ID), Taxon name, Crop(ID), Crop name,
      Cultivar(ID), Cultivar name, Year of release, Year of registration,
      Breeding organization(ID), Breeding organization, Breeding organization*,
      Breeder person(ID), Breeder person, ..., (notes columns past 20)
    """
    iso3 = (rec.get("Country (ISO3)") or "").strip().upper() or None
    yr = parse_year(rec.get("Year of release") or rec.get("Year of registration"))
    cultivar = (rec.get("Cultivar name") or "").strip()
    answer_id = rec.get("Answer ID") or ""
    period = rec.get("Period") or ""

    # WIEWS exposes "Improved variety" / "Introduced from abroad" / "Farmer variety"
    # in the columns after the breeder block. Capture them as notes.
    notes_parts: list[str] = []
    for k, v in rec.items():
        if k is None or not v: continue
        ks = k.strip()
        if ks in ("Improved variety", "Introduced from abroad", "Farmer variety"):
            notes_parts.append(f"{ks}: {v}")
    notes = " | ".join(notes_parts) or None

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
        "notes": notes,
        "source_url": SOURCE_URL["wiews_indicator40"],
        "retrieved_at": RETRIEVED_AT,
        "raw": rec,
    }


def from_ecowas(rec: dict) -> dict:
    crop_fr = rec.get("crop_name_fr") or ""
    crop_latin = rec.get("crop_latin") or None
    breeder = (rec.get("Obtenteur/ Pays") or rec.get("Obtenteur / Pays")
               or rec.get("Obtenteur/ pays") or "")
    iso3 = iso3_from_breeder(breeder)
    ord_key = "No d'ordre"
    yr = parse_year(rec.get("Date d'inscription"))
    isohyete = rec.get("Isohyète") or rec.get("Isohyète (mm)") or None
    return {
        "source": "ecowas",
        "source_record_id": f"{rec.get('crop_number')}#{rec.get(ord_key, '')}",
        "country_iso3": iso3,
        "country_name": None,
        "crop": normalise_crop(crop_fr),
        "crop_latin": crop_latin,
        "variety_name": (rec.get("Dénomination") or "").strip(),
        "variety_aliases": None,
        "variety_type": normalise_vtype(rec.get("Nature Génétique") or rec.get("Nature génétique") or ""),
        "year_release": yr,
        "breeder": breeder or None,
        "maintainer": rec.get("Mainteneur") or None,
        "status": None,
        "release_status": "registered" if yr else "unknown",  # ECOWAS = harmonised registration
        "ecology": isohyete and f"isohyete_mm: {isohyete}",
        "notes": None,
        "source_url": SOURCE_URL["ecowas"],
        "retrieved_at": RETRIEVED_AT,
        "raw": rec,
    }

# ----- Drivers -----
def load_jsonl(p: pathlib.Path):
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def load_json(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))

def main():
    agra_src    = ROOT / "scrape" / "varieties.jsonl"
    ppvfra_src  = ROOT / "complementary" / "ppvfra_cer.json"
    nacgrab_src = ROOT / "complementary" / "nacgrab" / "records.jsonl"
    ecowas_src  = ROOT / "complementary" / "ecowas" / "records.jsonl"

    unified = []
    counts = {}

    print("Loading AGRA ...")
    n = 0
    for r in load_jsonl(agra_src):
        unified.append(from_agra(r)); n += 1
    counts["agra"] = n; print(f"  {n}")

    print("Loading PPV&FRA ...")
    n = 0
    for r in load_json(ppvfra_src):
        unified.append(from_ppvfra(r)); n += 1
    counts["ppvfra"] = n; print(f"  {n}")

    print("Loading NACGRAB ...")
    n = 0
    for r in load_jsonl(nacgrab_src):
        unified.append(from_nacgrab(r)); n += 1
    counts["nacgrab"] = n; print(f"  {n}")

    print("Loading ECOWAS ...")
    n = 0
    for r in load_jsonl(ecowas_src):
        unified.append(from_ecowas(r)); n += 1
    counts["ecowas"] = n; print(f"  {n}")

    ghana_src  = ROOT / "complementary" / "ghana_2019"  / "records.jsonl"
    kephis_src = ROOT / "complementary" / "kephis_2025" / "records.jsonl"

    print("Loading Ghana 2019 ...")
    n = 0
    for r in load_jsonl(ghana_src):
        unified.append(from_ghana(r)); n += 1
    counts["ghana_2019"] = n; print(f"  {n}")

    print("Loading KEPHIS 2025 ...")
    n = 0
    for r in load_jsonl(kephis_src):
        unified.append(from_kephis(r)); n += 1
    counts["kephis_2025"] = n; print(f"  {n}")

    # CIMMYT maize — Algolia API pull (319 records)
    cimmyt_src = ROOT / "complementary" / "cimmyt_maize_algolia.json"
    if cimmyt_src.exists():
        print("Loading CIMMYT maize ...")
        n = 0
        for r in load_json(cimmyt_src):
            unified.append(from_cimmyt(r)); n += 1
        counts["cimmyt_maize"] = n; print(f"  {n}")

    # WIEWS Indicator 40 — raw FAO CSV from wiewsIndicatorsRawDownload
    wiews_src = ROOT / "complementary" / "wiews_indicator40_raw.csv"
    if wiews_src.exists():
        print("Loading WIEWS Indicator 40 ...")
        n = 0
        # encoding='utf-8-sig' strips the BOM that FAO emits
        with open(wiews_src, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                unified.append(from_wiews(r)); n += 1
        counts["wiews_indicator40"] = n; print(f"  {n}")
    else:
        print(f"WIEWS CSV not yet produced — skipping ({wiews_src})")

    total = len(unified)
    print(f"\nTotal unified rows: {total}")

    # Diagnostics
    by_country = Counter(r.get("country_iso3") or "?" for r in unified)
    by_crop    = Counter(r.get("crop") or "?" for r in unified)
    by_year    = Counter(r.get("year_release") for r in unified if r.get("year_release"))
    by_type    = Counter(r.get("variety_type") or "?" for r in unified)
    print(f"\nDistinct countries: {len(by_country)}  Top:")
    for k, v in by_country.most_common(15): print(f"  {v:>6}  {k}")
    print(f"\nDistinct crops (after norm): {len(by_crop)}  Top:")
    for k, v in by_crop.most_common(15): print(f"  {v:>6}  {k}")
    if by_year:
        ys = sorted(by_year.keys())
        print(f"\nYear span: {ys[0]} - {ys[-1]}")

    # Write outputs
    jsonl_path = OUT / "varieties.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in unified:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    csv_path = OUT / "varieties.csv"
    fieldnames = [
        "source","source_record_id","country_iso3","country_name",
        "crop","crop_latin","variety_name","variety_aliases","variety_type",
        "year_release","release_status","breeder","maintainer",
        "status","ecology","notes","source_url","retrieved_at",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in unified:
            row = {k: r.get(k) for k in fieldnames}
            # Flatten notes if list
            if isinstance(row.get("notes"), (list, dict)):
                row["notes"] = json.dumps(row["notes"], ensure_ascii=False)
            w.writerow(row)

    # Schema doc
    schema_md = OUT / "schema.md"
    schema_md.write_text(f"""# Unified Variety Schema

Total rows: **{total:,}**

## Sources merged
| Source | Rows | Notes |
|---|---:|---|
| agra        | {counts['agra']:>6,} | AGRA / CESSA varietycatalogues.com Laravel API (10 African countries) |
| ppvfra      | {counts['ppvfra']:>6,} | India PPV&FRA cer.json (applications + certificates + farmer varieties) |
| nacgrab     | {counts['nacgrab']:>6,} | Nigeria NACGRAB official catalogue (Apr 2025 edition, parsed from PDF) |
| ecowas      | {counts['ecowas']:>6,} | ECOWAS-UEMOA-CILSS regional catalogue 2022 (parsed from PDF) |
| ghana_2019  | {counts['ghana_2019']:>6,} | Ghana 2019 National Crop Variety Catalogue (parsed from PDF; crop derived from National Code prefix) |
| kephis_2025 | {counts['kephis_2025']:>6,} | Kenya KEPHIS 2025 National Crop Variety List (parsed from PDF; 30+ crop sections) |

## Columns

| Field | Type | Description |
|---|---|---|
| `source` | enum | `agra` \\| `ppvfra` \\| `nacgrab` \\| `ecowas` |
| `source_record_id` | str | Primary key within source — opaque, format varies |
| `country_iso3` | str | ISO 3166-1 alpha-3 (e.g. KEN, IND, NGA, BFA). Null if source did not bind to a single country |
| `country_name` | str | Human-readable country (may be null when iso3 inferred from breeder org) |
| `crop` | str | Normalised crop name in UPPERCASE English (FR→EN map applied for ECOWAS; alias map collapses BREAD WHEAT/DURUM WHEAT → WHEAT, IRISH POTATO → POTATO, etc.) |
| `crop_latin` | str | Botanical/Latin name where the source provides one (ECOWAS only currently) |
| `variety_name` | str | Primary denomination from the source |
| `variety_aliases` | str | Other names / synonyms / national codes / commercial names, semicolon-separated |
| `variety_type` | enum | `hybrid` \\| `opv` \\| `self_pollinated` \\| `vegetative` \\| `lineage` \\| `new` \\| `extant_vck` \\| `extant_notified` \\| `farmer` \\| `edv` \\| free text |
| `year_release` | int | Parsed from source year-of-release / date-of-filing / date-of-inscription |
| `breeder` | str | Releasing entity / applicant / obtenteur / developing institute |
| `maintainer` | str | Maintainer (mainteneur) where present |
| `status` | str | Commercial level / present status / lifecycle state |
| `release_status` | enum | `released` \\| `registered` \\| `candidate` \\| `closed` \\| `withdrawn` \\| `unknown` — derived from source's lifecycle field |
| `ecology` | str | Target agro-ecology / production zone (altitude, isohyete, AEZ name) — extracted from source-specific fields where available |
| `notes` | str | Free-text characteristics, special attributes, DUS/VCU, remarks |
| `source_url` | str | Endpoint or PDF URL the row was harvested from (provenance) |
| `retrieved_at` | str | ISO-8601 UTC timestamp of the unification run |
| `raw` | object | Full source record (JSONL only — not in CSV for size reasons) |

## Cross-schema bridge — `african-variety-aux` skill

The skill at `Downloads/african_variety_aux/` produces a 12-column CSV that maps cleanly into this schema:

| Skill column | This schema | Transform |
|---|---|---|
| `source` | `source` | direct |
| `country_iso3` | `country_iso3` | direct |
| `crop` (lowercase) | `crop` (UPPERCASE) | `.upper()` + apply `CROP_ALIAS` map |
| `variety_name` | `variety_name` | direct |
| `release_year` | `year_release` | rename |
| `release_status` | `release_status` | direct |
| `breeder_org` | `breeder` | rename |
| `traits` | `notes` | merge into notes |
| `ecology` | `ecology` | direct |
| `source_url` | `source_url` | direct |
| `retrieved_at` | `retrieved_at` | direct |
| `raw_record` (str) | `raw` (obj) | `json.loads()` |

To ingest skill output: add a `from_aux(rec)` adapter in `unify_varieties.py` reading the skill's CSV via `csv.DictReader` and applying the transforms above. Country inference + flag pass downstream handles the rest unchanged.

## Top countries (after normalisation)
| ISO3 | Rows |
|---|---:|
""" + "\n".join(f"| {k} | {v:,} |" for k, v in by_country.most_common(15)) + f"""

## Top crops (after normalisation)
| Crop | Rows |
|---|---:|
""" + "\n".join(f"| {k} | {v:,} |" for k, v in by_crop.most_common(20)) + f"""

## Year coverage
{min(by_year):d} – {max(by_year):d}

## Files
- `varieties.jsonl` — full fidelity (includes `raw`)
- `varieties.csv`   — flat columns only
""", encoding="utf-8")

    print(f"\nWrote:")
    print(f"  {jsonl_path}  ({jsonl_path.stat().st_size:,} bytes)")
    print(f"  {csv_path}    ({csv_path.stat().st_size:,} bytes)")
    print(f"  {schema_md}")

if __name__ == "__main__":
    main()
