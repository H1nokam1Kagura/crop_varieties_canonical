**Subject:** Crop variety catalogue — unified dataset ready to use (45k records, 70 countries, Databricks-ready)

---

Hi team,

I've pulled together a single canonical dataset of public crop variety registrations and releases. **45,670 rows across 70 countries and 8 sources, 1935–2026**, deduplicated and normalised to one schema. Cloud-first — no local Python install required.

**TL;DR — what you get:**

- `data/varieties.parquet` — 1.5 MB, the canonical analytics artifact
- Databricks Unity Catalog DDL + load notebook ready to drop in
- Quarterly auto-refresh via GitHub Action (live-API sources only; PDF sources tracked by fingerprint)
- Full provenance per row (`source`, `source_url`, `retrieved_at`)
- QC layer: country inference flags, review-queue codes

**How to access:**

1. **Databricks (recommended)** — run the two notebooks in `databricks/`:
   - `create_table.sql` once per workspace
   - `load_and_explore.py` to load the parquet from the published URL into `agri.variety_catalogues.varieties` (catalog/schema names are customisable)
2. **Direct read from anywhere** —
   ```python
   import pandas as pd
   df = pd.read_parquet("https://raw.githubusercontent.com/gatesfoundation/crop_varieties_canonical/main/data/varieties.parquet")
   ```
3. **CSV fallback** — same data in `data/varieties.csv` (12 MB) if you can't read parquet

**Sources merged:**

| Source | Country/scope | Records |
|---|---|---:|
| PPV&FRA India | India | 21,657 |
| FAO WIEWS Indicator 40 | 70+ countries globally | 16,781 |
| AGRA / CESSA | 10 African countries | 4,605 |
| KEPHIS Kenya 2025 | Kenya | 1,170 |
| NACGRAB Nigeria (Apr 2025) | Nigeria | 811 |
| CIMMYT Maize | 4 multi-country regions | 319 |
| Ghana 2019 catalogue | Ghana | 199 |
| ECOWAS regional 2022 | 9 W. African countries | 128 |

Africa coverage: KEN 2,630 / NGA 1,402 / ETH 658 / ZAF 619 / TZA 449 / GHA 442 / MAR 447 / EGY 402 / and 50+ more. South Asia: IND 21,778 / BGD 340 / PAK 68 / LKA 31.

**Useful queries (Databricks SQL — included in `load_and_explore.py`):**

```sql
-- Fresh releases (2024+) in priority geographies
SELECT country_iso3, crop, variety_name, year_release, breeder
FROM agri.variety_catalogues.varieties
WHERE year_release >= 2024
  AND release_status IN ('released','registered')
  AND country_iso3 IN ('KEN','TZA','ETH','GHA','NGA','SEN','BFA','IND','BGD','PAK','LKA')
ORDER BY year_release DESC, country_iso3;
```

**Method, in short:**

- Each source has a custom adapter (Laravel paginator for AGRA, public Algolia key for CIMMYT, FAO's signed-CSV API for WIEWS, etc.) — I reverse-engineered each one by capturing the actual XHR shape rather than relying on stale documentation. The methodology is captured in the GitHub README so it's reproducible.
- Country normalisation uses ISO 3166-1 alpha-3.
- Crops are normalised to UPPERCASE English (FR→EN, multilingual variants collapsed: `MAÍZ`/`Maïs`/`Maize` → `MAIZE`; `BREAD WHEAT`/`DURUM WHEAT` → `WHEAT`).
- Country inference (705 rows) was applied where source labels were placeholder or missing (e.g. AGRA "TEST" → KEN based on Kenyan-org breeders). Every inferred row carries `country_inferred=True` + `inference_basis` so you can filter or audit.
- 153 rows currently carry `review_flags`. Most are informational. See the review-queue query in the notebook for the full list.

**Known limitations** (also in the README):

- PDF-sourced rows reflect the catalogue edition we last scraped — KEPHIS 2025, NACGRAB Apr 2025, Ghana 2019. The GitHub Action auto-detects new editions via Last-Modified headers but re-parsing is manual.
- WIEWS coverage is reporter-driven; Kenya, Ghana, Burkina Faso submitted zero records for the most recent global reporting cycle.
- Cross-source dedup is variety-name based — same physical variety can appear in multiple sources. The cross-source overlap query in the notebook surfaces likely duplicates for triage.

**Refresh:**

- **Quarterly** — GitHub Action rebuilds the parquet on the 1st of Mar/Jun/Sep/Dec and (optionally) triggers a Databricks job
- **Ad-hoc** — anyone with the repo can run `python scripts/refresh.py --out data/varieties.parquet` and commit the new parquet

**Repository:** `https://github.com/gatesfoundation/crop_varieties_canonical`
**License:** CC-BY-4.0 on the unification work; underlying sources keep their original licenses

Happy to walk anyone through it — drop me a line.

— Neil
