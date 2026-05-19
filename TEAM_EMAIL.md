**Subject:** Crop variety catalogue — one table, 45k records, ready to query

---

Hi team,

I pulled together a single table of crop variety registrations and releases from eight public sources — government catalogues, regional bodies, FAO, CIMMYT. **45,670 rows across 70 countries, 1935 to 2026, all in one place.**

## Where it lives

- **Databricks table**: `agri.variety_catalogues.varieties`
- Same data also sits as a parquet file in the GitHub repo if you need it outside Databricks

## How to use it

Easiest path: just ask Claude Code. The table is loaded and column-commented in Databricks, so Claude can write the SQL for you. Some things to try:

- *"Which maize varieties were registered in Kenya since 2023?"*
- *"How many cassava varieties does Nigeria have in this catalogue?"*
- *"List Ethiopia rice releases with year and breeder."*
- *"Compare wheat variety counts across India, Pakistan, and Bangladesh."*
- *"Which CIMMYT maize lines are flagged as drought tolerant for Eastern Africa?"*
- *"Show me variety releases in Ghana from the last five years where the AGRA catalogue and the national Ghana 2019 catalogue disagree."*

Claude will write the query, run it against Databricks, and hand you the result.

## What's in it

| Region | Coverage | Approx records |
|---|---|---:|
| East Africa | Kenya, Tanzania, Ethiopia, Uganda, Rwanda, Malawi, Mozambique, Zambia | 5,400 |
| West Africa | Nigeria, Ghana, Senegal, Burkina Faso, Mali, Gambia, Niger, Togo, Chad | 2,400 |
| North Africa | Morocco, Egypt, Tunisia, Algeria, Sudan | 900 |
| Southern Africa | South Africa + neighbours | 700 |
| South Asia | India, Bangladesh, Pakistan, Sri Lanka, Nepal, Bhutan | 22,200 |
| Latin America, Europe, others | (via the FAO global dataset) | 13,500 |

Major crops: maize, rice, wheat, sorghum, pearl millet, cowpea, common bean, cassava, sweet potato, groundnut, sunflower, tomato, cotton — plus 240+ others.

## Useful columns when filtering

- `country_iso3` — three-letter codes (KEN, NGA, ETH, IND, BGD, PAK, ...)
- `crop` — UPPERCASE English (MAIZE, RICE, SORGHUM, ...)
- `year_release` — when the variety was officially released
- `breeder` — who developed it
- `release_status` — `released`, `registered`, `candidate`, `closed`, `withdrawn`
- `source` — which catalogue this row came from

## Things worth knowing

- **Provenance is preserved.** Every row carries the source URL it came from and a timestamp. No black-box magic.
- **Some country tags are inferred.** About 700 rows had missing or placeholder country fields; I inferred them from the breeder organisation (e.g. "KALRO" → Kenya). Those rows are flagged `country_inferred = true` if you want to filter them out.
- **153 rows have quality flags.** Mostly minor — Indian registry codes that look numeric, a handful of multi-country brands without a single country tag. The `review_flags` column tells you which.
- **PDF-based sources are point-in-time.** Kenya KEPHIS reflects the Feb 2025 edition, Nigeria NACGRAB the April 2025 edition, etc. Live API sources (AGRA, India PPV&FRA, FAO WIEWS, CIMMYT) refresh quarterly.

## Refresh

Auto-refresh runs quarterly via GitHub Action (1st of Mar / Jun / Sep / Dec). The live API sources stay current. PDF-based sources refresh when their publisher posts a new edition.

## Repo

`https://github.com/gatesfoundation/crop_varieties_canonical`

The README in the repo has the long version — schema, methodology, how to add a new country, gotchas per source.

Happy to walk anyone through it.

— Neil
