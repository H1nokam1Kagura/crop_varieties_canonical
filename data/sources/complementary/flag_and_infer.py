"""flag_and_infer.py - second pass over unified/varieties.jsonl.

Adds three columns to every record:
  review_flags         list[str]  diagnostic codes; empty if record passes all QC
  country_inferred     bool       True if country_iso3 was guessed rather than taken
                                  literally from the source's country field
  inference_basis      str        short prose explaining the guess (only set when
                                  country_inferred is True)

Rewrites:
  unified/varieties.jsonl         (full fidelity)
  unified/varieties.csv           (flat columns + new fields)
  unified/review_queue.csv        flagged-only subset, sorted by flag

Inference rules
---------------
1. AGRA TST -> KEN:
     The AGRA "TEST" country in CESSA appears to be placeholder data; every
     breeder string examined (n=697) is a Kenyan organisation (KALRO, Kenya
     Seed Co, Corteva Kenya, Bayer East Africa, Western Seed, Egerton Uni,
     etc.). Remap to KEN; basis = "AGRA placeholder; breeder is Kenyan org".

2. ECOWAS variety-name patterns:
     ISRIZ*   -> SEN  (ISRA Senegal rice naming convention)
     ARICA-IER -> MLI (Institut d'Economie Rurale, Mali)
     GMB LS*  -> GMB  (Gambia LowSubsistence rice line)
     CRI breeder (no country) -> GHA (Ghana Crops Research Institute)
     Other multi-country commercial brands (ARIZE/Bayer, KAFACI, FENGYOU,
     ARICA-RP, etc.) -> flagged, country left blank.
"""
from __future__ import annotations
import csv, json, pathlib, re
from collections import Counter

ROOT = pathlib.Path(r"C:\Users\neilha\Downloads\complementary\unified")
SRC  = ROOT / "varieties.jsonl"

KENYAN_ORG_PATTERNS = [
    r"\bKALRO\b", r"KENYA AGRICULTURAL", r"KENYA SEED COMPANY",
    r"\bCORTEVA AGRISCIENCE KENYA", r"BAYER EAST AFRICA",
    r"\bSEED CO LIMITED\b", r"WESTERN SEED", r"UNIVERSITY OF NAIROBI",
    r"\bSYNGENTA\b", r"EGERTON UNIVERSITY", r"AFRITEC SEEDS",
    r"FRESHCO KENYA", r"HYTECH SEED KENYA", r"NATIONAL IRRIGATION AUTHORITY",
    r"LELDET", r"MASENO UNIVERSITY", r"PEAL AGRO", r"EAST AFRICAN SEED",
    r"RONGO UNIVERSITY", r"AGVENTURE", r"MONSANTO", r"\bKARI\b",
    r"KENYA HIGHLAND", r"AMINIATA", r"KENYA[^A-Z]",
    # Round-2 additions (Kenya-resident breeders not picked up by name)
    r"\bADVANTA SEEDS\b", r"SIMLAW SEED", r"LAGROTECH",
    r"HYBRIDS EAST AFRICA", r"UNIVERSITY OF ELDORET", r"OIL CROP DEVELOPMENT",
    r"CROOKHAM", r"DRYLAND SEED", r"AFRICE SEED", r"POP VRIEND",
    r"AGROSOY", r"CULTIVO AFRICA", r"\bKWS\b", r"FARM INPUTS CARE CENTER",
    r"\bFICA SEEDS?\b",                   # FICA Seeds in Kenya context
    # Round-3 additions (Kenya-resident breeders found in holdout pass)
    r"INTERNATIONAL CENTRE OF INSECT PHYSIOLOGY",   # ICIPE — Nairobi HQ
    r"AGRISCOPE AFRICA", r"PURE SEEDS EAST AFRICA",
    r"ELGON SEED", r"STARKE AYRES", r"WAKALA AFRICA",
    r"ICRSAT[/ ]KSCO", r"\bKSCO\b",                 # KSCO = Kenya Seed Co
]
KENYAN_RE = re.compile("|".join(KENYAN_ORG_PATTERNS), re.IGNORECASE)

UGANDAN_ORG_PATTERNS = [
    r"NALWEYO", r"NaCRRI", r"NATIONAL CROPS RESOURCES RESEARCH INSTI",
]
UGANDAN_RE = re.compile("|".join(UGANDAN_ORG_PATTERNS), re.IGNORECASE)

TANZANIAN_ORG_PATTERNS = [
    r"TANZANIA AGRICULTURAL RESEARCH",      # TARI
    r"\bTARI\b", r"\bTOSCI\b",
]
TANZANIAN_RE = re.compile("|".join(TANZANIAN_ORG_PATTERNS), re.IGNORECASE)

ZAMBIAN_ORG_PATTERNS = [
    r"ZAMBIA SEED", r"\bZAMSEED\b", r"\bZARI\b",
]
ZAMBIAN_RE = re.compile("|".join(ZAMBIAN_ORG_PATTERNS), re.IGNORECASE)

# Multi-country / regional commercial brands that can't be pinned to one country
MULTI_COUNTRY_BRAND_PATTERNS = [
    re.compile(r"^ARIZE\b", re.I),         # Bayer hybrid rice — sold across W. Africa
    re.compile(r"^KAFACI", re.I),          # Korea-Africa Food Ag Coop Initiative
    re.compile(r"^ARICA[- ]RP", re.I),     # AfricaRice for plateau, multi-country
    re.compile(r"^FENGYOU", re.I),         # Chinese hybrid rice export
    re.compile(r"^WINALL", re.I),          # Chinese hybrid rice export
    re.compile(r"^SEMAX", re.I),           # SemAfort regional brand
    re.compile(r"^DJITABA$", re.I),        # unknown origin
    re.compile(r"^DKA[- ]?M\d", re.I),     # unknown origin
]

# ECOWAS variety-name -> ISO3 patterns (variety_name)
ECOWAS_NAME_PATTERNS = [
    (re.compile(r"^ISRIZ",         re.I), "SEN", "ISRA Senegal rice naming convention"),
    (re.compile(r"^ARICA[- ]IER",  re.I), "MLI", "ARICA × IER (Institut d'Economie Rurale, Mali)"),
    (re.compile(r"^GMB[\s\-]LS",   re.I), "GMB", "GMB LS prefix = Gambia LowSubsistence rice"),
]

def infer_country(rec: dict) -> tuple[str | None, str | None]:
    """Return (iso3, basis) when inference succeeds; (None, None) otherwise."""
    src = rec.get("source")
    breeder_only = rec.get("breeder") or ""
    name    = rec.get("variety_name") or ""

    # Rule 1: AGRA TST -> country if breeder OR maintainer is identifiable
    if src == "agra" and rec.get("country_iso3") == "TST":
        # Probe breeder + maintainer (some entries cite an international breeder
        # like ICRISAT but a national-company maintainer)
        agra_text = " ".join(filter(None, [rec.get("breeder"), rec.get("maintainer")]))
        if UGANDAN_RE.search(agra_text):
            return "UGA", "AGRA 'TEST' country is placeholder; breeder/maintainer is a Ugandan organisation (NaCRRI/Nalweyo)"
        if TANZANIAN_RE.search(agra_text):
            return "TZA", "AGRA 'TEST' country is placeholder; breeder/maintainer is a Tanzanian organisation (TARI/TOSCI)"
        if ZAMBIAN_RE.search(agra_text):
            return "ZMB", "AGRA 'TEST' country is placeholder; breeder/maintainer is a Zambian organisation (ZAMSEED/ZARI)"
        if KENYAN_RE.search(agra_text):
            return "KEN", "AGRA 'TEST' country is placeholder; breeder/maintainer is a Kenyan organisation"
        return None, None  # leave TST as-is for the very few without matching breeder

    # Rule 2: ECOWAS unmatched
    if src == "ecowas" and not rec.get("country_iso3"):
        # 2a: variety-name pattern
        for pat, code, basis in ECOWAS_NAME_PATTERNS:
            if pat.search(name):
                return code, f"variety name '{name}' matches {basis}"
        # 2b: CRI breeder (Crops Research Institute Ghana)
        if breeder_only.strip().upper() == "CRI":
            return "GHA", "breeder 'CRI' is Ghana Crops Research Institute"

    return None, None

def review_flags(rec: dict) -> list[str]:
    flags: list[str] = []
    src = rec.get("source")
    if src == "agra" and rec.get("country_iso3") == "TST":
        flags.append("agra_test_country")
    if not rec.get("country_iso3"):
        # Distinguish multi-country brands from genuinely unknown
        name = rec.get("variety_name") or ""
        if src == "ecowas" and any(p.search(name) for p in MULTI_COUNTRY_BRAND_PATTERNS):
            flags.append("multi_country_brand")
        elif src == "cimmyt_maize":
            # CIMMYT records are bred for a region, not country-specific
            flags.append("regional_release")
        else:
            flags.append("no_country")
    if src == "kephis_2025":
        core_missing = [k for k in ("variety_name","year_release","breeder")
                        if not rec.get(k)]
        if core_missing:
            flags.append("kephis_partial_extract:" + ",".join(core_missing))
    # Bare-name placeholder catch (variety_name is just a number, e.g. '1')
    # PPV&FRA legitimately files numeric internal codes as denominations
    # — flag them but only as informational
    vn = (rec.get("variety_name") or "").strip()
    if vn and vn.isdigit():
        flags.append("variety_name_is_digit_only")
    return flags

def main():
    recs = []
    with open(SRC, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: recs.append(json.loads(line))
    print(f"loaded {len(recs)} records")

    inferred_count = 0
    flag_counts = Counter()

    for r in recs:
        # Inference: only run if record needs help
        iso3, basis = infer_country(r)
        if iso3:
            # preserve the original
            r["_country_iso3_source"] = r.get("country_iso3")
            r["country_iso3"] = iso3
            if not r.get("country_name"):
                # canonical name for the few we infer
                names = {"KEN":"Kenya","SEN":"Senegal","MLI":"Mali","GMB":"Gambia","GHA":"Ghana"}
                r["country_name"] = names.get(iso3)
            r["country_inferred"] = True
            r["inference_basis"]  = basis
            inferred_count += 1
        else:
            r["country_inferred"] = False
            r["inference_basis"]  = None

        flags = review_flags(r)
        r["review_flags"] = flags
        for fl in flags:
            flag_counts[fl] += 1

    print(f"\ncountry inferences applied: {inferred_count}")
    print(f"\nreview flag counts:")
    for fl, n in flag_counts.most_common():
        print(f"  {n:>5}  {fl}")

    # Write outputs
    OUT_JSONL = ROOT / "varieties.jsonl"
    OUT_CSV   = ROOT / "varieties.csv"
    OUT_QUEUE = ROOT / "review_queue.csv"

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    csv_cols = ["source","source_record_id","country_iso3","country_name",
                "country_inferred","inference_basis","review_flags",
                "crop","crop_latin","variety_name","variety_aliases","variety_type",
                "year_release","release_status","breeder","maintainer",
                "status","ecology","notes","source_url","retrieved_at"]
    def _flat(r):
        row = {k: r.get(k) for k in csv_cols}
        if isinstance(row.get("review_flags"), list):
            row["review_flags"] = ";".join(row["review_flags"])
        if isinstance(row.get("notes"), (list, dict)):
            row["notes"] = json.dumps(row["notes"], ensure_ascii=False)
        return row

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for r in recs: w.writerow(_flat(r))

    queue = [r for r in recs if r.get("review_flags")]
    queue.sort(key=lambda r: (r["review_flags"][0] if r["review_flags"] else "", r["source"]))
    with open(OUT_QUEUE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for r in queue: w.writerow(_flat(r))

    print(f"\nwrote:")
    print(f"  {OUT_JSONL}  ({OUT_JSONL.stat().st_size:,} bytes)")
    print(f"  {OUT_CSV}    ({OUT_CSV.stat().st_size:,} bytes)")
    print(f"  {OUT_QUEUE}  ({OUT_QUEUE.stat().st_size:,} bytes, {len(queue)} rows)")

if __name__ == "__main__":
    main()
