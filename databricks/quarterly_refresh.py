# Databricks notebook source
# MAGIC %md
# MAGIC # Crop Varieties Canonical — Quarterly Refresh
# MAGIC
# MAGIC Re-runs the live-API sources (AGRA, PPV&FRA, WIEWS, CIMMYT) and merges new
# MAGIC rows into `ggo_agdev.agdev.ref_varieties`. PDF sources (NACGRAB, KEPHIS,
# MAGIC Ghana, ECOWAS) are preserved from the existing parquet in the Volume.
# MAGIC
# MAGIC Runtime: ~3-5 minutes for the four live sources combined.
# MAGIC
# MAGIC ## Pattern
# MAGIC The self-contained `refresh.py` lives in the `ggo_agdev.agdev.staging` Volume.
# MAGIC We `exec()` it to load its pull + adapter functions into the notebook
# MAGIC namespace, then drive the refresh from here. No subprocess, no pip install
# MAGIC from GitHub — the Volume is the source of truth at runtime.

# COMMAND ----------

VOLUME_DIR   = "/Volumes/ggo_agdev/agdev/staging/crop_varieties_canonical"
SCRIPT_PATH  = f"{VOLUME_DIR}/refresh.py"
PARQUET_PATH = f"{VOLUME_DIR}/varieties.parquet"
TABLE        = "ggo_agdev.agdev.ref_varieties"

# COMMAND ----------

%pip install pandas pyarrow --quiet

# COMMAND ----------

# Load refresh.py functions into this notebook's namespace.
# Use runpy with a non-"__main__" run_name so refresh.py's argparse entrypoint
# (its `if __name__ == "__main__"` block) doesn't fire.
import runpy
_refresh_ns = runpy.run_path(SCRIPT_PATH, run_name="__refresh_module__")

needed = ["pull_agra", "pull_ppvfra", "pull_wiews", "pull_cimmyt",
          "from_agra", "from_ppvfra", "from_wiews", "from_cimmyt",
          "apply_flags_and_infer"]
missing = [n for n in needed if n not in _refresh_ns]
assert not missing, f"refresh.py missing expected functions: {missing}"

# Bind the functions into globals so subsequent cells can call them
for _name in needed:
    globals()[_name] = _refresh_ns[_name]
print(f"Loaded {len(needed)} functions from refresh.py")

# COMMAND ----------

# MAGIC %md ## 1. Pull live sources

# COMMAND ----------

print("AGRA / CESSA ..."); agra    = pull_agra();    print(f"  {len(agra):>6,} rows")
print("PPV&FRA India..."); ppvfra  = pull_ppvfra();  print(f"  {len(ppvfra):>6,} rows")
print("FAO WIEWS .....");  wiews   = pull_wiews();   print(f"  {len(wiews):>6,} rows")
print("CIMMYT maize ..."); cimmyt  = pull_cimmyt();  print(f"  {len(cimmyt):>6,} rows")

# COMMAND ----------

# MAGIC %md ## 2. Normalise + preserve PDF rows

# COMMAND ----------

import pandas as pd

prev = pd.read_parquet(PARQUET_PATH)
pdf_srcs = {"nacgrab", "kephis_2025", "ghana_2019", "ecowas"}
preserved_df = prev[prev["source"].isin(pdf_srcs)]
# Convert pd.NA / NaN -> None so the truthy checks in refresh.py work
# (otherwise apply_flags_and_infer hits "boolean value of NA is ambiguous")
preserved_df = preserved_df.astype(object).where(preserved_df.notna(), None)
preserved = preserved_df.to_dict("records")
print(f"Preserved {len(preserved):,} PDF-sourced rows from existing parquet")

unified = []
unified.extend(from_agra(r)    for r in agra)
unified.extend(from_ppvfra(r)  for r in ppvfra)
unified.extend(from_wiews(r)   for r in wiews)
unified.extend(from_cimmyt(r)  for r in cimmyt)
unified.extend(preserved)
print(f"Unified row count (pre-flag): {len(unified):,}")

apply_flags_and_infer(unified)

df = pd.DataFrame(unified)
df["year_release"]     = pd.to_numeric(df["year_release"], errors="coerce").astype("Int64")
df["country_inferred"] = df["country_inferred"].fillna(False).astype(bool)
print(f"Unified DF: {len(df):,} rows / {len(df.columns)} cols")

# COMMAND ----------

# MAGIC %md ## 3. Promote the refreshed parquet to the Volume

# COMMAND ----------

df.to_parquet(PARQUET_PATH, compression="snappy", index=False)
print(f"Wrote {PARQUET_PATH}")

# COMMAND ----------

# MAGIC %md ## 4. Reload Delta from the refreshed parquet
# MAGIC
# MAGIC `refresh.py` produces a full rebuild of `varieties.parquet` (live sources
# MAGIC re-pulled + PDF rows preserved). `INSERT OVERWRITE` matches that semantic:
# MAGIC the parquet IS the source of truth for each run. MERGE would require
# MAGIC dedup logic that the source script doesn't enforce.

# COMMAND ----------

sdf = spark.createDataFrame(df)
sdf.createOrReplaceTempView("staged_varieties")
spark.sql(f"INSERT OVERWRITE {TABLE} SELECT * FROM staged_varieties")
print(f"Overwrote {TABLE} with {sdf.count():,} rows")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT source, COUNT(*) AS n_rows
# MAGIC FROM ggo_agdev.agdev.ref_varieties
# MAGIC GROUP BY source
# MAGIC ORDER BY n_rows DESC
