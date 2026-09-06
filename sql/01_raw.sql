-- Raw layer: parsed parcel documents landed as JSON, one row per parcel page.
-- Reloaded wholesale on every run; the landing zone under data/raw is the
-- system of record, this is only its queryable mirror.
CREATE SCHEMA IF NOT EXISTS raw;

CREATE OR REPLACE TABLE raw.parcel_document AS
SELECT * FROM read_json($staged_glob, union_by_name := true);
