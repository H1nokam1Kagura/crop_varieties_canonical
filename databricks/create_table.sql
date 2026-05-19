-- crop_varieties_canonical — Unity Catalog DDL
-- Run once per workspace to create the catalog/schema/table.
-- Then use load_and_explore.py to populate from the published parquet artifact.

-- Adjust catalog and schema names for your workspace
CREATE CATALOG IF NOT EXISTS agri;
USE CATALOG agri;
CREATE SCHEMA IF NOT EXISTS variety_catalogues
    COMMENT 'Crop variety release records unified from public national, regional, and multilateral catalogues';
USE SCHEMA variety_catalogues;

CREATE TABLE IF NOT EXISTS varieties (
    source              STRING  COMMENT 'agra | ppvfra | nacgrab | ecowas | ghana_2019 | kephis_2025 | wiews_indicator40 | cimmyt_maize',
    source_record_id    STRING  COMMENT 'PK within source — opaque',
    country_iso3        STRING  COMMENT 'ISO 3166-1 alpha-3; null for regional CIMMYT releases',
    country_name        STRING,
    crop                STRING  COMMENT 'Normalised UPPERCASE English crop name',
    crop_latin          STRING  COMMENT 'Botanical name when source provides one',
    variety_name        STRING,
    variety_aliases     STRING  COMMENT 'Semicolon-separated synonyms / national codes / commercial names',
    variety_type        STRING  COMMENT 'hybrid | opv | self_pollinated | vegetative | lineage | new | extant_vck | extant_notified | farmer | edv',
    year_release        INT,
    breeder             STRING,
    maintainer          STRING,
    status              STRING  COMMENT 'Free-text source lifecycle state',
    release_status      STRING  COMMENT 'Enum: released | registered | candidate | closed | withdrawn | unknown',
    ecology             STRING  COMMENT 'Target agro-ecology / altitude / isohyete / AEZ',
    notes               STRING  COMMENT 'Special attributes, DUS, VCU, agronomic traits',
    source_url          STRING  COMMENT 'Endpoint / PDF URL the row came from (provenance)',
    retrieved_at        STRING  COMMENT 'ISO-8601 UTC timestamp of the unification run',
    country_inferred    BOOLEAN COMMENT 'True if country_iso3 was inferred from breeder / variety name',
    inference_basis     STRING  COMMENT 'Prose explanation when country_inferred = true',
    review_flags        STRING  COMMENT 'Semicolon-separated QC codes; empty if row passes all checks',
    _country_iso3_source STRING COMMENT 'Original country_iso3 from source before inference, if overridden'
) USING DELTA
TBLPROPERTIES (
    'delta.feature.allowColumnDefaults' = 'enabled',
    'comment' = '45,670 crop variety release records across 70+ countries and 8 sources, 1935-2026. See README.md in the package for full schema, provenance, and refresh procedure.'
);
