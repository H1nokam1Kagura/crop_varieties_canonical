# Crop Varieties Canonical

A unified, deduplicated, country-tagged catalogue of crop variety registrations and releases assembled from 8 public sources covering 70 countries, 1935–2026.

| | |
|---|---:|
| Rows | **45,670** |
| Countries | 70 |
| Crops (normalised) | 254 |
| Sources | 8 |
| Year coverage | 1935 – 2026 |
| Recent (2024+) releases | ~2,200 |

## What's in the box

```
crop_varieties_canonical/
├── data/
│   ├── varieties.parquet           ← 1.5 MB, canonical analytics format
│   └── varieties.csv               ← 12 MB, compatibility
├── databricks/
│   ├── create_table.sql            ← Unity Catalog DDL
│   ├── load_and_explore.py         ← one-cell load + sample queries
│   └── quarterly_refresh.py        ← live-source refresh notebook
├── scripts/
│   └── refresh.py                  ← used by the GH Action runner
├── .github/workflows/
│   └── quarterly_refresh.yml       ← scheduled refresh + auto-commit
├── README.md
└── LICENSE                         ← CC-BY-4.0
```

## Quick start — Databricks

```sql
-- 1. Create the table (once per workspace)
%run ./databricks/create_table.sql
```

```python
# 2. Load the data from the published parquet
%run ./databricks/load_and_explore.py
```

That's it. The notebook reads `varieties.parquet` from the `ggo_agdev.agdev.staging` UC Volume and writes to `ggo_agdev.agdev.ref_varieties`. No local Python install, no PDF parsers, no scrapers.

> **Deployment pattern (BMGF Databricks):** parquet is hosted in the `ggo_agdev.agdev.staging` UC Volume at `crop_varieties_canonical/varieties.parquet`. The `quarterly_refresh.py` notebook re-pulls live sources and merges into `ggo_agdev.agdev.ref_varieties` in place. The GitHub Action keeps the GitHub copy and the Volume copy in sync for downstream consumers.

## Quick start — anywhere else

```python
import pandas as pd
df = pd.read_parquet("https://raw.githubusercontent.com/gatesfoundation/crop_varieties_canonical/main/data/varieties.parquet")
# 45,670 rows, 22 cols
```

## Schema

22 columns. Key ones:

| column | type | meaning |
|---|---|---|
| `source` | enum | which catalogue the row came from |
| `country_iso3` | string | ISO 3166-1 alpha-3 |
| `crop` | string | UPPERCASE normalised English crop name |
| `variety_name` | string | as published |
| `year_release` | int | parsed year |
| `breeder` | string | releasing entity / applicant |
| `release_status` | enum | `released` \| `registered` \| `candidate` \| `closed` \| `withdrawn` \| `unknown` |
| `country_inferred` | bool | True if we filled in country from breeder pattern |
| `inference_basis` | string | how the inference was made |
| `review_flags` | string | QC codes; empty = clean |
| `source_url` | string | provenance |

See `databricks/create_table.sql` for the full column list with comments and `data/varieties.parquet` schema for types.

## Sources

| Source | Country/scope | Records | Access |
|---|---|---:|---|
| AGRA / CESSA | 10 African countries | 4,605 | Public REST API |
| PPV&FRA India | India | 21,657 | Static JSON file |
| NACGRAB Nigeria | Nigeria | 811 | PDF (Apr 2025 edition) |
| ECOWAS regional 2022 | 9 W. African countries | 128 | PDF |
| Ghana 2019 | Ghana | 199 | PDF |
| KEPHIS Kenya 2025 | Kenya | 1,170 | PDF |
| FAO WIEWS Indicator 40 | Global (70+ countries) | 16,781 | POST API → signed CSV |
| CIMMYT Maize | 4 multi-country regions | 319 | Algolia public key |

## Refresh cadence

| Source | Cadence | Mechanism |
|---|---|---|
| AGRA, PPV&FRA, WIEWS, CIMMYT | **Quarterly** via GH Action | Live API pull |
| NACGRAB, KEPHIS, ECOWAS, Ghana | **Annual / biennial / static** | PDF re-download when HEAD `Last-Modified` shifts |

The quarterly GitHub Action (`.github/workflows/quarterly_refresh.yml`) runs on the 1st of Mar/Jun/Sep/Dec, rebuilds the parquet, commits if anything changed, and optionally pings a Databricks job to reload the Delta table.

## Provenance & QC

Every row has:
- `source_url` — the exact endpoint / PDF URL it came from
- `retrieved_at` — when this run pulled it
- `country_inferred` + `inference_basis` — when we inferred country from breeder string rather than reading it from the source's country field (e.g. AGRA's "TEST" placeholder remapped to KEN based on Kenyan-org breeders)
- `review_flags` — diagnostic codes for rows that need human attention (PPV&FRA digit-only variety codes, KEPHIS partial PDF extracts, CIMMYT regional releases without a single country, etc.)

153 rows currently carry review flags. Most are informational (CIMMYT regional, PPV&FRA digit-only). Roughly 50 need human disambiguation.

## License

CC-BY-4.0 on the **unification + normalisation work**. Underlying source data remains under its original licenses (FAO open data, AGRA open access, government catalogues in respective domains). Attribute this dataset + the underlying sources when redistributing.

## Limitations

- **PDF-sourced rows are point-in-time** — they reflect the catalogue edition we scraped, not the live state. Re-run when source publishes a new edition.
- **Country inference is heuristic** for AGRA-TST and ECOWAS rows. Trust `country_inferred=False` rows more than `country_inferred=True` rows.
- **WIEWS coverage is reporter-driven** — Kenya, Ghana, Burkina Faso submitted zero records for Indicator 40 iteration 1 (Jan 2012 – Jun 2014). Their coverage in this dataset comes from other sources.
- **Cross-source dedup is variety-name based** — see the cross-source overlap query in `load_and_explore.py` for known multi-source hits.

## Acknowledgement

Built atop the open variety registration catalogues maintained by: AGRA/CESSA, PPV&FRA Authority (India), NACGRAB (Nigeria), ECOWAS-UEMOA-CILSS, CSIR-CRI (Ghana), KEPHIS (Kenya), FAO WIEWS, and CIMMYT.
