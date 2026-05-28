# Crop Variety Catalogue Unification — Access Patterns & Replay Guide

A working reference for harvesting national / regional / multilateral crop variety
catalogues into a single canonical schema. Captures *what we did*, *why each path
worked*, and *what to try first* when adding a new country or source.

Current state of the unified store (`unified/`):

| Metric | Value |
|---|---:|
| Total rows | 45,351 |
| Sources | 7 |
| Distinct countries | 70 |
| Year span | 1935 – 2026 |
| Files | `varieties.jsonl` (full), `varieties.csv` (flat), `schema.md`, `review_queue.csv` |

---

## Source-by-source playbook

For each source: the URL/endpoint that actually works, what the access mode is,
and the gotcha that took the longest to solve.

### 1. AGRA / CESSA varietycatalogues.com

| | |
|---|---|
| Access mode | Public REST API (Laravel paginator) |
| Endpoint | `https://varietycatalogues.com/apiv1/public/api/seedcentredata?page=N&perPage=200` |
| Lookups | `/apiv1/public/api/seedcentre` (crops, countries, seedtypes, licences) |
| Records | 4,605 |
| Reverse-engineering path | (1) probed for JSON backends — found none on `/wp-json/...`, (2) Playwright recon captured `/apiv1/public/api/visits/stats`, (3) `_nuxt/f4bacaa.js` bundle search for `seedcentre` revealed `seedcentredata` is the listing endpoint, (4) verified with 5-line `requests.get` |
| Gotcha | Catalogue is a Nuxt SPA — all `/wp-json/...` paths return the SPA shell (200 text/html), masquerading as WordPress. Don't trust path patterns; inspect the actual Nuxt JS bundles. |
| Scraper | `Downloads/varietycatalogues_scrape.py` |
| Adapter | `from_agra` in `unify_varieties.py` |

### 2. PPV&FRA India

| | |
|---|---|
| Access mode | Static JSON file behind DataTables.js |
| Endpoint | `https://plantauthority.gov.in/sites/default/files/cer.json` |
| Records | 21,657 (224 crops, 2007–2026, incl. 13,119 farmer varieties) |
| Reverse-engineering path | (1) DataTables JS on `/node/3044` has `url: 'cer.json'`, (2) grep page HTML for `url:` strings, (3) fetch URL directly |
| Gotcha | The HTML page itself is 9.3 MB and contains the table built client-side, but the data lives in a separate static file. Don't try to scrape the table — fetch the JSON. |
| Adapter | `from_ppvfra` in `unify_varieties.py` |

### 3. NACGRAB Nigeria (national catalogue)

| | |
|---|---|
| Access mode | PDF download |
| URL | `https://www.nacgrab.gov.ng/wp-content/uploads/2025/10/Varieties-Released-Catalogue-updated-April-2025.pdf` |
| Records | 811 (45 crops, 1937–2025) |
| Gotcha | Site has anti-bot — first download attempt got `RemoteDisconnected`. Fix: full browser headers including `Accept-Language` and `Referer: https://www.nacgrab.gov.ng/`. |
| Parser | `pdfplumber.extract_tables()` works well; tables repeat header on every page (filter rows where S/N is digit) |
| Adapter | `from_nacgrab` in `unify_varieties.py` |

### 4. ECOWAS / CEDEAO–UEMOA–CILSS regional catalogue 2022

| | |
|---|---|
| Access mode | PDF download |
| URL | `https://ecowap.ecowas.int/media/events/concept/all/Regional_Catalogue_Version.pdf` |
| Records | 128 (16 crops, mostly 2022; breeders from MLI/SEN/BFA/NGA/GHA/TCD/NER/TGO/GMB) |
| Gotcha | Two URL versions live on ecowap.ecowas.int — `Regional_Catalogue_Version_1.pdf` (2008, 1.9 MB) and the unversioned newest (2022, 5.4 MB). Other mirrors (wakatsera, doc-developpement-durable, insah) 404 or 403. |
| Parser | `pdfplumber` extracts per-crop tables; section headings detected via regex `^\d+\. ([A-Z][a-zA-Zé...]+) \(([^)]+)\)` |
| Country inference | Pattern-match against `Obtenteur/Pays` field (IER→MLI, ISRA→SEN, INERA→BFA, CRI→GHA, etc.) |
| Adapter | `from_ecowas` in `unify_varieties.py` |

### 5. Ghana 2019 National Crop Variety Catalogue

| | |
|---|---|
| Access mode | PDF download |
| URL | `https://nastag.org/docx/resources/2019%20NATIONAL%20CROP%20VARIETY%20CATALOGUE.pdf` |
| Records | 199 |
| Gotcha | The PDF's crop section headings (e.g. "Maize - Species: Zea mays L.") only appear on the first page of each crop section, NOT on subsequent pages. My first parser assumed every page would carry the heading and mis-labeled everything as the last seen crop. **Fix: derive crop from the National Code prefix instead** — `GH/Zm/` → Maize, `GH/Vu/` → Cowpea, etc. The code prefix is on every row. |
| Parser | `pdfplumber.extract_tables()`; 11-column uniform table per crop |
| Adapter | `from_ghana` in `unify_varieties.py` |

### 6. KEPHIS Kenya 2025 (National Crop Variety List)

| | |
|---|---|
| Access mode | PDF download |
| URL | `https://www.kephis.go.ke/sites/default/files/2025-02/NATIONAL%20CROP%20VARIETY%20LIST-%202025%20EDITION.pdf` |
| Records | 1,170 (30+ crop sections, 232 pages, 96% complete) |
| Gotcha | PDF text-wrapping fragments column headers into many variants: `"Variety name/code"`, `"Variety testing name/cod e"`, `"Year of rele ase"`, `"Year of releas e"`. Initial parser missed 40% of rows. **Fix: fuzzy column matching** — match by substring (`variety`, `year of rel`, `owner`, `mainta`) rather than exact strings. |
| Parser | `pdfplumber.extract_tables()`, multi-line cell merge via continuation detection (empty first cell = append to previous record) |
| Adapter | `from_kephis` in `unify_varieties.py` |

### 7. FAO WIEWS Indicator 40 (multilateral, 70+ countries)

| | |
|---|---|
| Access mode | Documented-by-network-trace POST API |
| Endpoint | `https://wiews.fao.org/wiewsIndicatorsRawDownload` (POST), returns a signed CSV URL on `storage.googleapis.com` |
| Records | 16,781 (1935–2020) |
| Required headers | `Content-Type: text/plain; charset=UTF-8`, `Referer: https://www.fao.org/`, `Accept: application/json, text/javascript, */*; q=0.01` |
| Request body | `{"lang":"en","indicator":40,"separator":",","filters":{"region":{"type":"M49","values":["1"]},"iteration":["1"]}}` (M49 code `1` = World) |
| Response | `["https://storage.googleapis.com/fao-wiews-export-bucket/Wiews_Indicator_<timestamp>.csv"]` — fetch that URL for the CSV |
| CSV encoding | UTF-8 with BOM — open with `encoding="utf-8-sig"` |
| Reverse-engineering path | (1) old script URL `/wiews/data/reporting/en/?indicator=40` returns 404 (FAO restructured), (2) correct landing is `/wiews/data/domains/detail/en/?code=40`, (3) page loads a JS widget from `storage.googleapis.com/fao-wiews-frontend-bucket/indicators/wiews-ui.indicators.min.js`, (4) Playwright with `on_request` listener captured the POST body, (5) replay with plain `requests.post()` works without auth |
| Gotcha #1 | Without `Referer: https://www.fao.org/` the endpoint may 500. |
| Gotcha #2 | `list_of_countries=true` does NOT give a per-country breakdown — that path returns aggregate-only data. The **`wiewsIndicatorsRawDownload`** endpoint (different URL) is what gives per-variety records. |
| Gotcha #3 | The CSV has more cells per row than headers in some lines — `csv.DictReader` produces `None` keys. Adapter must skip `if k is None`. |
| Gotcha #4 | Crop names arrive in multiple languages: `Maize`, `Maíz`, `Maiz`, `Maïs`. Crop alias map needs Spanish/French/Portuguese variants. |
| Adapter | `from_wiews` in `unify_varieties.py` |
| Coverage caveat | Reporter-driven (NFP submissions). Kenya/Ghana/Burkina Faso submitted **zero** records. Strong for South Africa, Morocco, Egypt, Ethiopia, Tanzania, Bangladesh. |

---

## HTTP diagnostic ladder (use BEFORE deciding to use Playwright)

Don't escalate to browser-driven scraping by reflex. Classify the failure mode first:

| Symptom | What it is | Bypass |
|---|---|---|
| `SSL: CERTIFICATE_VERIFY_FAILED` | Local cert chain — corporate proxy / managed Windows | Point `requests` at `certifi.where()`; fall back to `verify=False` with warning |
| 401 Unauthorized | API requires auth; website does not | Playwright fallback — drive the public site, no API auth needed |
| 403 Forbidden with HTML response | Cloudflare / WAF challenge | `cloudscraper` lib, or Playwright with stealth plugin |
| 403 with JSON error | Explicit IP / origin block | Different egress (residential proxy / mobile tether), then Playwright |
| 404 on all probes | No API exists; SPA only | DOM scrape via Playwright headed, OR find the bundle JS and grep for the real endpoint |
| 429 Too Many Requests | Rate limit | Slow down, honour `Retry-After`, rotate UA |
| 200 but empty payload | Tier-gated, mid-migration, or auth-walled | Inspect site in browser; usually means UI has data → Playwright |
| Returns HTML challenge page | JS challenge | Playwright (executes JS), or `curl_cffi` (TLS fingerprinting) |
| `URLError [Errno 11001] getaddrinfo failed` | DNS dead / site moved | WebSearch for current URL |
| `RemoteDisconnected` | Server closed connection — often anti-bot | Add browser-like `Accept-Language`, `Referer`, full UA |
| 500 with valid-looking body | Missing/invalid required header (often `Referer`, `Content-Type`) | Capture a real browser request via Playwright `on_request` and replay exact headers |
| Site uses `__NUXT__` shell on every wp-json path | Nuxt SPA masquerading as WP | Grep JS bundles for actual API base, NOT the URL patterns |

---

## How to add a new country / source

1. **Find the catalogue.** Web search "<country> national variety catalogue", "<country> seed registration list", "<crop> variety register <country>".
2. **Probe the candidate URL.**
   - If it's a website with a search/filter UI, run Playwright in headed mode and watch the Network tab for XHRs to JSON endpoints.
   - If it's a static PDF, just download it.
   - If it's a portal that requires login, document this as a hard stop and move on.
3. **Reverse-engineer the access path.** Common patterns:
   - REST API with paginator → `?page=N&perPage=N`
   - DataTables-style JS table → grep the page HTML for `url:` strings
   - SPA with API → grep the main JS bundle for `/api/`, `fetch(`, axios calls
   - PDF → use `pdfplumber.extract_tables()`
4. **Identify the per-variety field set** in the source. Map to canonical:

   | Canonical column | Common source labels |
   |---|---|
   | `variety_name` | Variety, Cultivar, Denomination, Hybrid name, Variety name/code |
   | `year_release` | Year of release, Date d'inscription, Datefiling, Released year |
   | `breeder` | Breeder, Obtenteur, Releasing entity, Applicant, Developing Institute |
   | `crop` | Crop, Species, Crop name, Cropname |
   | `crop_latin` | Species, Botanical name, Taxon name |
   | `country_iso3` | Derived from breeder pattern or source country field |
   | `release_status` | Status, PresentStatus, Commercial level — map to released / registered / candidate |

5. **Add an adapter** `from_<source>(rec) -> dict` in `unify_varieties.py`. Required output fields are documented in `unified/schema.md`. Make sure to set `source_url` and `retrieved_at`.
6. **Add the source to the load loop** in `main()` of `unify_varieties.py`.
7. **Update `SOURCE_URL`** dict with the provenance URL.
8. **Re-run the pipeline:**
   ```powershell
   py unify_varieties.py
   py flag_and_infer.py
   ```
9. **Inspect `review_queue.csv`** — any new flags? Common ones to expect:
   - `no_country` — breeder string doesn't match any country inference pattern → add to the pattern list
   - `variety_name_is_digit_only` — informational, usually fine
   - `<source>_partial_extract:...` — parser missed a column → fuzzy-match strategy

10. **Add country normalisation patterns** if the source uses unusual breeder organisation names. See `KENYAN_ORG_PATTERNS` etc. in `flag_and_infer.py`.

---

## Files in `complementary/`

```
complementary/
├── README.md                    ← this file
├── unify_varieties.py           ← canonical unification pipeline
├── flag_and_infer.py            ← QC pass + country inference
├── parse_ghana_2019.py          ← Ghana 2019 PDF parser
├── parse_kephis_2025.py         ← KEPHIS Kenya 2025 PDF parser
├── ppvfra_cer.json              ← PPV&FRA raw download (9.4 MB)
├── ppvfra_cer.csv               ← PPV&FRA flat CSV (4.8 MB)
├── wiews_indicator40_raw.csv    ← FAO WIEWS raw export (4.6 MB)
├── ECOWAS_Regional_Catalogue_unversioned.pdf
├── ECOWAS_Regional_Catalogue_v1.pdf
├── Ghana_2019_NationalCropVarietyCatalogue.pdf
├── KEPHIS_Kenya_VarietyList_2025.pdf
├── NACGRAB_Nigeria_VarietiesReleased_2025-04.pdf
├── NACGRAB_Nigeria_Guidelines_2025.pdf
├── Ethiopia_TASAI_CountryReport_2021.pdf
├── Senegal_CatalogueVarietal_seysoo.pdf
├── Benin_CaBEV_2ndEdition.pdf        (bonus)
├── Burundi_CatalogueNational_2020.pdf (bonus)
├── ecowas/                      ← parsed ECOWAS records
├── nacgrab/                     ← parsed NACGRAB records
├── ghana_2019/                  ← parsed Ghana records
├── kephis_2025/                 ← parsed KEPHIS records
├── senegal/                     ← extracted Senegal text (font-fix applied)
└── unified/                     ← final unified table
    ├── varieties.jsonl
    ├── varieties.csv
    ├── schema.md
    └── review_queue.csv
```

---

## Sources documented but currently unreachable

- **CIMMYT Maize Catalog** (`maizecatalog.cimmyt.org`) — SSL cert issue locally (fixed in `african_variety_aux/scripts/cimmyt_maize.py` with certifi fallback); site is live in browser
- **CGIAR GLOMIP** (`glomip.cgiar.org/product-catalog`) — "Database update in progress" notice; re-probe periodically
- **Burkina Faso 2014 catalogue** — original mirror at `doc-developpement-durable.org` returns 403; `fagri-burkina.com` DNS dead; Wayback machine has no copy; partial coverage via ECOWAS regional rows
- **Ethiopia EAA Crop Variety Register** issues 22+ — referenced in academic literature but no direct PDF URL found on `moa.gov.et` / `eaa.gov.et`. Only 2016 issue on Scribd
- **Genesys PGR API** (`api.genesys-pgr.org`) — OAuth required; credentials issued by helpdesk@genesys-pgr.org (multi-day human loop); valuable for germplasm passport data but not a variety release source

## Aggregators considered (out of scope for canonical schema)

These index *documents about* variety releases, not structured per-variety records. Use only as a discovery feeder:

- **CGSpace** (`cgspace.cgiar.org/server/api`, `/server/oai/request`) — DSpace 7, full CGIAR institutional repository, anonymous
- **AGRIS** (FAO, `agris.fao.org/agris-search`) — global ag literature
- **OpenAlex**, **Zenodo**, **CORE**, **DataCite** — academic / open data
- **Wayback CDX** — historical URL snapshots

## TASAI / African Seed Access Index

Country-level aggregate scorecards only; no per-variety CSV exposed. Useful for cross-validating record counts but doesn't add rows to the canonical table.

---

---

## Quarterly maintenance — catching novel releases

The unification is **not idempotent across time**. Sources publish new varieties on different cadences; the canonical store needs periodic refresh. Recommended cadence and change-detection patterns:

### Update cadence per source

| Source | Refresh cadence | Why this cadence | What changes between runs |
|---|---|---|---|
| AGRA / CESSA | **Monthly** | Live Laravel DB, breeders push updates as they happen. Stats endpoint shows `total` count — diff it to detect new rows | New varieties appended; some `seedmaintenancestatus` flips active→retired |
| PPV&FRA India | **Quarterly** | `cer.json` is regenerated server-side on registry meetings (every 1–3 months) | New `AckNo` entries, `PresentStatus` flips on existing entries |
| NACGRAB Nigeria | **Annually (Jan/Feb)** | Catalogue is republished after NVRC year-end meetings | Append-only — new section per registration year |
| ECOWAS regional | **Biennial** (2008 → 2016 → 2022) | Per-country submissions aggregated and re-issued; expect next around 2024–2025 | Mostly append; some breeder name normalisation |
| Ghana 2019 | **Static** (next edition not yet announced) | Standalone publication; watch CSIR-CRI / NASTAG for new editions | n/a until new edition |
| KEPHIS Kenya | **Annually (Feb)** | "2025 edition" pattern suggests yearly republish | Append-only by section |
| FAO WIEWS Indicator 40 | **Every reporting iteration (~3 years)** | NFP submissions happen on global reporting cycles, not continuous | `iteration` parameter increments; iteration `1` = Jan 2012–Jun 2014; future iterations append |

**Practical schedule:** run the full pipeline every quarter. Most sources won't have changed in a 3-month window — diff logic below catches the ones that did, cheaply.

### Change detection — three layers

**Layer 1: source-level "did anything change at all"** — fingerprint each source before re-extracting:

```python
# Stamp source fingerprints; refuse to re-ingest sources whose fingerprint matches last run
import hashlib, json, pathlib, urllib.request

FINGERPRINTS = pathlib.Path(r"C:\Users\neilha\Downloads\complementary\unified\source_fingerprints.json")

CHECKS = {
    # url, what-to-fingerprint
    "agra":   ("https://varietycatalogues.com/apiv1/public/api/visits/stats", "json:total"),
    "ppvfra": ("https://plantauthority.gov.in/sites/default/files/cer.json", "sha256:full"),
    "wiews":  ("https://wiews.fao.org/wiewsIndicatorsSearch",  "json:NumberOfNewVarieties"),
    # PDFs: HEAD request, compare Last-Modified or Content-Length
    "nacgrab":     ("https://www.nacgrab.gov.ng/wp-content/uploads/2025/10/Varieties-Released-Catalogue-updated-April-2025.pdf", "head:Last-Modified"),
    "kephis_2025": ("https://www.kephis.go.ke/sites/default/files/2025-02/NATIONAL%20CROP%20VARIETY%20LIST-%202025%20EDITION.pdf", "head:Last-Modified"),
}
# Run before unification. If fingerprints unchanged, skip that source.
```

For AGRA specifically, the `/api/visits/stats` endpoint returns `{"total": N, "varieties": M}` — just compare the `varieties` field against the previous run. Same one-liner check for PPV&FRA via the JSON file size + last 256 bytes.

**Layer 2: row-level delta** — after unification, diff against the previous unified table:

```sql
-- Find net-new variety records since last run
WITH prev AS (SELECT * FROM read_csv_auto('unified/varieties.PREV.csv')),
     curr AS (SELECT * FROM read_csv_auto('unified/varieties.csv'))
SELECT curr.*
FROM curr
LEFT JOIN prev USING (source, source_record_id)
WHERE prev.source_record_id IS NULL;
```

The `source_record_id` is per-source-stable for AGRA (numeric `id`) and PPV&FRA (`AckNo`). For WIEWS it's `Answer ID` (also stable). For PDF sources (NACGRAB, Ghana, KEPHIS) it's `<crop>#<S/N>` which is also stable. So this diff is reliable.

**Layer 3: schema drift detection** — sources sometimes silently change column names mid-cycle (e.g. `Year of release` → `Year of release name`):

```python
# In each adapter, log when a fuzzy match fires instead of an exact match
# Or: after extraction, assert that 95%+ of rows have a populated variety_name
```

### Suggested quarterly workflow

```powershell
# 0. Stamp previous outputs for diff
$d = Get-Date -Format "yyyy-MM-dd"
Copy-Item C:\Users\neilha\Downloads\complementary\unified\varieties.csv `
          C:\Users\neilha\Downloads\complementary\unified\varieties.$d.csv

# 1. Fingerprint check (15 sec)
# (one-shot script that diffs fingerprints; flags which sources changed)

# 2. Re-extract changed sources only:
#    - AGRA: re-run varietycatalogues_scrape.py
#    - PPV&FRA: re-download cer.json
#    - WIEWS: re-issue the wiewsIndicatorsRawDownload POST
#    - For PDFs: re-download and re-parse only if Last-Modified changed

# 3. Re-unify + flag
py C:\Users\neilha\Downloads\complementary\unify_varieties.py
py C:\Users\neilha\Downloads\complementary\flag_and_infer.py

# 4. Compute delta against snapshotted .$d.csv (DuckDB query above)
# 5. Inspect review_queue.csv for new flags
# 6. If counts dropped unexpectedly → schema drift; inspect source HTML
```

### Expected breakage points (what to fix when something fails)

| Source | Breakage expected when | Fix |
|---|---|---|
| AGRA | Nuxt bundle hash rotates (`/_nuxt/f4bacaa.js` → new hash) | Hash changes don't affect the API endpoint — `seedcentredata?page=N&perPage=200` is stable. Re-confirm only if the API itself starts 404'ing |
| PPV&FRA | DSP/Drupal upgrade on `plantauthority.gov.in` | Check `/node/3044` HTML for new `url:` JS string. Static JSON file may move to `/sites/default/files/<new>.json` |
| NACGRAB | New annual catalogue uploaded under a new filename | Grep nacgrab.gov.ng homepage for `wp-content/uploads/<yyyy>/.../Varieties-Released-Catalogue-*.pdf` |
| KEPHIS | New annual edition under new path | Grep kephis.go.ke for `NATIONAL CROP VARIETY LIST-YYYY` PDF |
| WIEWS | FAO reorgs the WIEWS site (already happened once: `/wiews/data/reporting/...` → `/wiews/data/domains/detail/...?code=40`) | The API endpoint `wiews.fao.org/wiewsIndicatorsRawDownload` has been stable through site reorgs; only the landing page URL changes |
| WIEWS body shape | M49 region codes / `iteration` parameter values change | Worst case: re-run a Playwright session against the landing page with `on_request` listener; capture the new body |
| ECOWAS | New PDF published with different table column count | pdfplumber auto-detects per-crop schema; failures usually look like "0 rows from crop N" — re-inspect that page's table layout |
| All PDF parsers | Source switches from text-extractable PDF to image-only (scanned) | Add OCR pass via `pytesseract` or `pdf2image` + Tesseract. Heuristic detection: `len(page.extract_text()) / page.width < 0.5` |

### Catching novel releases (use case: alerts)

After diff, what counts as "novel and worth attention":

| Filter | Why |
|---|---|
| `release_year >= year(now)-1` | Releases from the current or previous year — the freshest |
| `country_iso3 IN ('KEN','TZA','ETH','GHA','NGA','SEN','BFA','IND','BGD','PAK','LKA')` | Your priority geographies |
| `crop IN ('MAIZE','RICE','SORGHUM','PEARL MILLET','COWPEA','BEAN','GROUNDNUT','CASSAVA','SWEET POTATO','WHEAT')` | Staples |
| Filter out `release_status IN ('closed','withdrawn')` | Skip terminated PPV&FRA applications |

A canonical "watch query":

```sql
SELECT country_iso3, crop, variety_name, year_release, breeder, source
FROM read_csv_auto('unified/varieties.csv')
WHERE year_release >= 2025
  AND release_status IN ('released','registered')
  AND country_iso3 IN ('KEN','TZA','ETH','GHA','NGA','SEN','BFA','IND','BGD','PAK','LKA')
ORDER BY year_release DESC, country_iso3;
```

---

## Re-run cheatsheet

```powershell
# Full rebuild from existing source files
py C:\Users\neilha\Downloads\complementary\unify_varieties.py
py C:\Users\neilha\Downloads\complementary\flag_and_infer.py

# Re-download WIEWS (raw bytes change with each request; record-set may not)
py -c "
import urllib.request, json, ssl, pathlib
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
hdrs = {'User-Agent':'Mozilla/5.0','Content-Type':'text/plain; charset=UTF-8','Referer':'https://www.fao.org/'}
body = json.dumps({'lang':'en','indicator':40,'separator':',','filters':{'region':{'type':'M49','values':['1']},'iteration':['1']}}).encode()
req = urllib.request.Request('https://wiews.fao.org/wiewsIndicatorsRawDownload', data=body, headers=hdrs, method='POST')
with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
    url = json.loads(r.read())[0]
with urllib.request.urlopen(url, context=ctx, timeout=120) as r:
    pathlib.Path(r'C:\Users\neilha\Downloads\complementary\wiews_indicator40_raw.csv').write_bytes(r.read())
"
```
