# Unified Variety Schema

Total rows: **45,670**

## Sources merged
| Source | Rows | Notes |
|---|---:|---|
| agra        |  4,605 | AGRA / CESSA varietycatalogues.com Laravel API (10 African countries) |
| ppvfra      | 21,657 | India PPV&FRA cer.json (applications + certificates + farmer varieties) |
| nacgrab     |    811 | Nigeria NACGRAB official catalogue (Apr 2025 edition, parsed from PDF) |
| ecowas      |    128 | ECOWAS-UEMOA-CILSS regional catalogue 2022 (parsed from PDF) |
| ghana_2019  |    199 | Ghana 2019 National Crop Variety Catalogue (parsed from PDF; crop derived from National Code prefix) |
| kephis_2025 |  1,170 | Kenya KEPHIS 2025 National Crop Variety List (parsed from PDF; 30+ crop sections) |

## Columns

| Field | Type | Description |
|---|---|---|
| `source` | enum | `agra` \| `ppvfra` \| `nacgrab` \| `ecowas` |
| `source_record_id` | str | Primary key within source — opaque, format varies |
| `country_iso3` | str | ISO 3166-1 alpha-3 (e.g. KEN, IND, NGA, BFA). Null if source did not bind to a single country |
| `country_name` | str | Human-readable country (may be null when iso3 inferred from breeder org) |
| `crop` | str | Normalised crop name in UPPERCASE English (FR→EN map applied for ECOWAS; alias map collapses BREAD WHEAT/DURUM WHEAT → WHEAT, IRISH POTATO → POTATO, etc.) |
| `crop_latin` | str | Botanical/Latin name where the source provides one (ECOWAS only currently) |
| `variety_name` | str | Primary denomination from the source |
| `variety_aliases` | str | Other names / synonyms / national codes / commercial names, semicolon-separated |
| `variety_type` | enum | `hybrid` \| `opv` \| `self_pollinated` \| `vegetative` \| `lineage` \| `new` \| `extant_vck` \| `extant_notified` \| `farmer` \| `edv` \| free text |
| `year_release` | int | Parsed from source year-of-release / date-of-filing / date-of-inscription |
| `breeder` | str | Releasing entity / applicant / obtenteur / developing institute |
| `maintainer` | str | Maintainer (mainteneur) where present |
| `status` | str | Commercial level / present status / lifecycle state |
| `release_status` | enum | `released` \| `registered` \| `candidate` \| `closed` \| `withdrawn` \| `unknown` — derived from source's lifecycle field |
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
| IND | 21,778 |
| BRA | 3,496 |
| NLD | 2,748 |
| KEN | 1,936 |
| NGA | 1,438 |
| ARG | 1,336 |
| ESP | 1,090 |
| ETH | 836 |
| TST | 697 |
| DEU | 687 |
| PRT | 681 |
| ZAF | 619 |
| BLR | 611 |
| TZA | 570 |
| MEX | 501 |

## Top crops (after normalisation)
| Crop | Rows |
|---|---:|
| RICE | 8,339 |
| MAIZE | 6,671 |
| WHEAT | 1,538 |
| TETRAPLOID COTTON | 1,239 |
| SORGHUM | 1,174 |
| TOMATO | 1,167 |
| SOYBEAN | 1,004 |
| POTATO | 820 |
| PEARL MILLET | 576 |
| CHILLI | 548 |
| ORNAMENTAL | 525 |
| SUNFLOWER | 523 |
| BRINJAL | 505 |
| BEAN | 471 |
| APPLE | 465 |
| PIGEONPEA | 450 |
| STRAWBERRY | 446 |
| MANGO | 443 |
| GROUNDNUT | 361 |
| GRAPE | 357 |

## Year coverage
1935 – 2026

## Files
- `varieties.jsonl` — full fidelity (includes `raw`)
- `varieties.csv`   — flat columns only
