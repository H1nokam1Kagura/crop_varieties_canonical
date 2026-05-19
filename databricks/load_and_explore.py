# Databricks notebook source
# MAGIC %md
# MAGIC # Crop Varieties Canonical — Load & Explore
# MAGIC
# MAGIC One-cell load + a handful of canonical exploration queries.
# MAGIC Run `create_table.sql` first to create `agri.variety_catalogues.varieties`.
# MAGIC
# MAGIC The parquet file is published at the URL below. Override `PARQUET_URL` if
# MAGIC your workspace mirrors it to a UC Volume.

# COMMAND ----------

PARQUET_URL = "https://raw.githubusercontent.com/gatesfoundation/crop_varieties_canonical/main/data/varieties.parquet"
TABLE       = "agri.variety_catalogues.varieties"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load — single cell, no local dependencies
# MAGIC
# MAGIC Reads the parquet artifact directly from GitHub raw, overwrites the Delta
# MAGIC table. Idempotent — safe to re-run.

# COMMAND ----------

import urllib.request, pathlib, tempfile

tmp = pathlib.Path(tempfile.mkdtemp()) / "varieties.parquet"
urllib.request.urlretrieve(PARQUET_URL, tmp)
df = spark.read.parquet(str(tmp))
print(f"Loaded {df.count():,} rows / {len(df.columns)} cols from artifact")
df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TABLE)
print(f"Wrote {TABLE}")

# COMMAND ----------

# MAGIC %md ## Snapshot — what's in here

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT source, COUNT(*) AS n_rows
# MAGIC FROM agri.variety_catalogues.varieties
# MAGIC GROUP BY source
# MAGIC ORDER BY n_rows DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Country coverage (top 25)
# MAGIC SELECT country_iso3, country_name, COUNT(*) AS n
# MAGIC FROM agri.variety_catalogues.varieties
# MAGIC WHERE country_iso3 IS NOT NULL
# MAGIC GROUP BY country_iso3, country_name
# MAGIC ORDER BY n DESC LIMIT 25

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Crop coverage (top 25)
# MAGIC SELECT crop, COUNT(*) AS n, COUNT(DISTINCT country_iso3) AS countries
# MAGIC FROM agri.variety_catalogues.varieties
# MAGIC GROUP BY crop
# MAGIC ORDER BY n DESC LIMIT 25

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Recent releases (2024+) in priority geographies
# MAGIC SELECT country_iso3, crop, variety_name, year_release, breeder, source
# MAGIC FROM agri.variety_catalogues.varieties
# MAGIC WHERE year_release >= 2024
# MAGIC   AND release_status IN ('released','registered')
# MAGIC   AND country_iso3 IN ('KEN','TZA','ETH','GHA','NGA','SEN','BFA','IND','BGD','PAK','LKA','ZAF','MAR','EGY')
# MAGIC ORDER BY year_release DESC, country_iso3, crop

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Cross-source overlap candidates
# MAGIC -- (same variety_name appears across multiple sources)
# MAGIC SELECT
# MAGIC   UPPER(variety_name) AS variety,
# MAGIC   COUNT(DISTINCT source) AS n_sources,
# MAGIC   COLLECT_SET(source) AS sources,
# MAGIC   COLLECT_SET(country_iso3) AS countries,
# MAGIC   MIN(year_release) AS first_year
# MAGIC FROM agri.variety_catalogues.varieties
# MAGIC WHERE variety_name IS NOT NULL AND variety_name <> ''
# MAGIC GROUP BY UPPER(variety_name)
# MAGIC HAVING n_sources > 1
# MAGIC ORDER BY n_sources DESC, first_year
# MAGIC LIMIT 30

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Review queue — rows that need human attention
# MAGIC SELECT review_flags, COUNT(*) AS n
# MAGIC FROM agri.variety_catalogues.varieties
# MAGIC WHERE review_flags IS NOT NULL AND review_flags <> ''
# MAGIC GROUP BY review_flags
# MAGIC ORDER BY n DESC

# COMMAND ----------

# MAGIC %md ## Useful column dimensions
# MAGIC
# MAGIC | column | typical values | use for |
# MAGIC |---|---|---|
# MAGIC | `source` | `agra`, `ppvfra`, `nacgrab`, `ecowas`, `ghana_2019`, `kephis_2025`, `wiews_indicator40`, `cimmyt_maize` | provenance filtering |
# MAGIC | `country_iso3` | ISO3 alpha codes | join key for country reference data |
# MAGIC | `release_status` | `released` `registered` `candidate` `closed` `withdrawn` `unknown` | filter out terminated applications |
# MAGIC | `year_release` | int | freshness / vintage |
# MAGIC | `country_inferred` | bool | trust filter — exclude where True if you want only source-tagged countries |
# MAGIC | `review_flags` | semicolon-separated codes | drop-list when running analyses |
