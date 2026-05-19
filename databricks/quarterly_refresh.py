# Databricks notebook source
# MAGIC %md
# MAGIC # Crop Varieties Canonical — Quarterly Refresh
# MAGIC
# MAGIC Re-runs the live-API sources (AGRA, PPV&FRA, WIEWS, CIMMYT) and merges new
# MAGIC rows into `agri.variety_catalogues.varieties`. PDF sources (NACGRAB, KEPHIS,
# MAGIC Ghana, ECOWAS) refresh only when the GitHub Action detects a new edition.
# MAGIC
# MAGIC Schedule: quarterly via Databricks Workflows or via the GitHub Action that
# MAGIC builds a fresh `varieties.parquet` and triggers `load_and_explore.py`.
# MAGIC
# MAGIC Runtime: ~3-5 minutes for the four live sources combined.

# COMMAND ----------

%pip install requests pdfplumber --quiet
dbutils.library.restartPython()

# COMMAND ----------

import csv, io, json, ssl, urllib.request, urllib.parse, hashlib, re
from datetime import datetime, timezone
from collections import Counter

TABLE = "agri.variety_catalogues.varieties"
NOAUTH_CTX = ssl.create_default_context(); NOAUTH_CTX.check_hostname=False; NOAUTH_CTX.verify_mode=ssl.CERT_NONE
HDRS = {"User-Agent":"Mozilla/5.0 Chrome/131","Accept-Language":"en-US,en;q=0.9"}
RETRIEVED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

def get_json(url, timeout=60, **kw):
    req = urllib.request.Request(url, headers={**HDRS, "Accept":"application/json"}, **kw)
    with urllib.request.urlopen(req, timeout=timeout, context=NOAUTH_CTX) as r:
        return json.loads(r.read())

# COMMAND ----------

# MAGIC %md ## 1. AGRA / CESSA (Laravel paginator at varietycatalogues.com)

# COMMAND ----------

AGRA_BASE = "https://varietycatalogues.com/apiv1/public/api"
agra_rows = []
page = 1
while True:
    obj = get_json(f"{AGRA_BASE}/seedcentredata?page={page}&perPage=200")
    paginator = obj.get("filterdata", {}) or {}
    data = paginator.get("data", []) or []
    if not data: break
    agra_rows.extend(data)
    if page >= (paginator.get("last_page") or 1): break
    page += 1
print(f"AGRA: {len(agra_rows)} rows")

# COMMAND ----------

# MAGIC %md ## 2. PPV&FRA India (static JSON file)

# COMMAND ----------

ppvfra_rows = get_json("https://plantauthority.gov.in/sites/default/files/cer.json")
print(f"PPV&FRA: {len(ppvfra_rows)} rows")

# COMMAND ----------

# MAGIC %md ## 3. FAO WIEWS Indicator 40 (POST → signed CSV URL → CSV)

# COMMAND ----------

body = json.dumps({"lang":"en","indicator":40,"separator":",",
    "filters":{"region":{"type":"M49","values":["1"]},"iteration":["1"]}}).encode()
req = urllib.request.Request("https://wiews.fao.org/wiewsIndicatorsRawDownload",
    data=body, headers={**HDRS,"Content-Type":"text/plain; charset=UTF-8",
                        "Referer":"https://www.fao.org/"}, method="POST")
with urllib.request.urlopen(req, timeout=60, context=NOAUTH_CTX) as r:
    signed_url = json.loads(r.read())[0]
with urllib.request.urlopen(urllib.request.Request(signed_url, headers=HDRS),
                            timeout=120, context=NOAUTH_CTX) as r:
    wiews_csv_text = r.read().decode("utf-8-sig", errors="replace")
wiews_rows = list(csv.DictReader(io.StringIO(wiews_csv_text)))
print(f"WIEWS: {len(wiews_rows)} rows")

# COMMAND ----------

# MAGIC %md ## 4. CIMMYT maize (Algolia public search-only key)

# COMMAND ----------

ALG_APP = "GGLKL5VA1C"
ALG_KEY = "2d973ad94320e2676f6703c50f20e1d7"
ALG_URL = f"https://{ALG_APP.lower()}-dsn.algolia.net/1/indexes/CIMMYT_product_catalog/query"
cimmyt_rows = []
page = 0
while True:
    body = json.dumps({"params": f"query=&page={page}&hitsPerPage=100&facets=%5B%22*%22%5D"}).encode()
    req = urllib.request.Request(ALG_URL, data=body, method="POST", headers={
        **HDRS, "X-Algolia-Application-Id": ALG_APP,
        "X-Algolia-API-Key": ALG_KEY,
        "Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30, context=NOAUTH_CTX) as r:
        resp = json.loads(r.read())
    hits = resp.get("hits", [])
    cimmyt_rows.extend(hits)
    if not hits or len(cimmyt_rows) >= resp.get("nbHits", 0): break
    page += 1
print(f"CIMMYT: {len(cimmyt_rows)} rows")

# COMMAND ----------

# MAGIC %md ## 5. Normalise + write
# MAGIC
# MAGIC The adapter functions match the canonical schema. PDF sources (NACGRAB,
# MAGIC KEPHIS, Ghana, ECOWAS) keep their existing Delta partitions unchanged —
# MAGIC this notebook only refreshes the four live API sources.

# COMMAND ----------

# Bring in the adapter functions from the repo. For Databricks self-contained
# execution, paste them inline OR install the package. Easiest:
%pip install git+https://github.com/gatesfoundation/crop_varieties_canonical.git@main --quiet
dbutils.library.restartPython()

# COMMAND ----------

from crop_varieties_canonical.adapters import (
    from_agra, from_ppvfra, from_wiews, from_cimmyt
)

unified = []
unified.extend(from_agra(r)    for r in agra_rows)
unified.extend(from_ppvfra(r)  for r in ppvfra_rows)
unified.extend(from_wiews(r)   for r in wiews_rows)
unified.extend(from_cimmyt(r)  for r in cimmyt_rows)
print(f"Total refreshed rows: {len(unified)}")

# COMMAND ----------

import pandas as pd
df = pd.DataFrame(unified)
# Drop raw payload for cloud store
df = df.drop(columns=[c for c in df.columns if c == "raw"], errors="ignore")
df["year_release"] = pd.to_numeric(df["year_release"], errors="coerce").astype("Int64")

# MERGE upsert into the Delta table
spark.createDataFrame(df).createOrReplaceTempView("staged")
spark.sql(f"""
MERGE INTO {TABLE} AS t
USING staged AS s
ON t.source = s.source AND t.source_record_id = s.source_record_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")
print(f"Merged into {TABLE}")

# COMMAND ----------

# MAGIC %sql SELECT source, COUNT(*) FROM agri.variety_catalogues.varieties GROUP BY source ORDER BY 2 DESC
