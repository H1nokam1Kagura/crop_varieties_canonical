# Databricks notebook source
# MAGIC %md
# MAGIC # Crop Varieties Canonical — Quarterly Refresh
# MAGIC
# MAGIC Re-runs the live-API sources (AGRA, PPV&FRA, WIEWS, CIMMYT) and merges new
# MAGIC rows into `ggo_agdev.agdev.ref_varieties`. PDF sources (NACGRAB, KEPHIS,
# MAGIC Ghana, ECOWAS) are preserved from the previous build of `varieties.parquet`.
# MAGIC
# MAGIC Runtime: ~3-5 minutes for the four live sources combined.
# MAGIC
# MAGIC ## Deployment
# MAGIC - This notebook runs the self-contained refresh script that lives in the
# MAGIC   `ggo_agdev.agdev.staging` UC Volume alongside the parquet.
# MAGIC - No `pip install` from GitHub is required — everything needed is on the
# MAGIC   Volume, so the notebook works regardless of GitHub state.

# COMMAND ----------

import sys, types, pathlib, tempfile, subprocess
from datetime import datetime, timezone

VOLUME_DIR   = "/Volumes/ggo_agdev/agdev/staging/crop_varieties_canonical"
SCRIPT_PATH  = f"{VOLUME_DIR}/refresh.py"
PARQUET_PATH = f"{VOLUME_DIR}/varieties.parquet"
TABLE        = "ggo_agdev.agdev.ref_varieties"

# COMMAND ----------

# MAGIC %md ## 1. Run the refresh script
# MAGIC
# MAGIC `refresh.py` is self-contained — it pulls live sources, preserves PDF rows
# MAGIC from the previous parquet, and writes a fresh `varieties.parquet`. We run it
# MAGIC into a temp path and atomically promote on success.

# COMMAND ----------

%pip install pandas pyarrow --quiet

# COMMAND ----------

# Run refresh.py into a staging path, then promote on success.
staging_parquet = pathlib.Path(tempfile.mkdtemp()) / "varieties.parquet"

# Seed the staging file with the current parquet so refresh.py can read its
# previous-build PDF rows. (refresh.py preserves PDF sources from the file it's
# about to overwrite.)
import shutil
shutil.copy(PARQUET_PATH, staging_parquet)

result = subprocess.run(
    [sys.executable, SCRIPT_PATH, "--out", str(staging_parquet)],
    capture_output=True, text=True, timeout=600
)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr)
    raise RuntimeError(f"refresh.py exited {result.returncode}")

# COMMAND ----------

# MAGIC %md ## 2. Promote the new parquet to the Volume + merge into Delta

# COMMAND ----------

# Atomically swap the Volume parquet
shutil.copy(staging_parquet, PARQUET_PATH)
print(f"Promoted {staging_parquet} -> {PARQUET_PATH}")

# COMMAND ----------

# MERGE upsert into Delta
df = spark.read.parquet(PARQUET_PATH)
print(f"Refreshed parquet has {df.count():,} rows / {len(df.columns)} cols")

df.createOrReplaceTempView("staged_varieties")
spark.sql(f"""
MERGE INTO {TABLE} AS t
USING staged_varieties AS s
  ON  t.source           = s.source
  AND t.source_record_id = s.source_record_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")
print(f"Merged into {TABLE}")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT source, COUNT(*) AS n_rows
# MAGIC FROM ggo_agdev.agdev.ref_varieties
# MAGIC GROUP BY source
# MAGIC ORDER BY n_rows DESC
