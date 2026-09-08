-- Raw layer: parsed parcel documents landed as JSON.
-- The table itself is populated by warehouse.load_documents(), in batches --
-- a single read_json across every staged file infers and holds all of their
-- schemas at once, which runs the build out of memory somewhere past thirty
-- thousand parcels.
CREATE SCHEMA IF NOT EXISTS raw;
