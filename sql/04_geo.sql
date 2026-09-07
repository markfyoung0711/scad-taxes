-- Geocoding layer: parcel locations from Smith County's own GIS, joined on the
-- account number rather than matched on address text. Built only when
-- data/staged/geocode exists, so the warehouse is usable before geocoding runs.
CREATE OR REPLACE TABLE raw.parcel_location AS
SELECT * FROM read_json($geocode_glob, union_by_name := true);

CREATE OR REPLACE TABLE stg.parcel_location AS
SELECT
    l.gis_parcel_id                    AS gis_parcel_id,
    l.account                          AS account,
    TRY_CAST(l.latitude  AS DOUBLE)    AS latitude,
    TRY_CAST(l.longitude AS DOUBLE)    AS longitude,
    l.gis_address                      AS gis_address,
    l.gis_city                         AS gis_city,
    l.gis_zip                          AS gis_zip,
    TRY_CAST(l.gis_acres AS DOUBLE)    AS gis_acres,
    -- 'parcel_centroid' is the polygon's own centre; 'address_point' is the
    -- fallback for improvement-only accounts and recent splits with no polygon.
    l.source                           AS location_source,
    -- Districts the centroid falls inside; resolved by point-in-polygon,
    -- since those layers carry no account key.
    l.voting_precinct                  AS voting_precinct,
    l.voting_precinct_name             AS voting_precinct_name,
    l.commissioner_precinct            AS commissioner_precinct,
    l.commissioner_precinct_name       AS commissioner_precinct_name,
    d._staged_at                       AS staged_at
FROM raw.parcel_location d, UNNEST(d.locations) AS t(l);

CREATE OR REPLACE TABLE mart.dim_parcel_location AS
SELECT * FROM stg.parcel_location;

-- One row per account per year with a location on it: the grain a map reads.
CREATE OR REPLACE VIEW mart.v_parcel_map AS
SELECT
    p.account,
    p.owner_name,
    p.situs_address,
    p.gis_parcel_id,
    p.use_code,
    p.sector,
    l.latitude,
    l.longitude,
    l.gis_city,
    l.location_source,
    c.tax_year,
    c.appraised_value,
    c.assessed_value,
    c.total_tax,
    c.appraised_pct_yoy,
    c.tax_pct_yoy,
    c.base_year,
    c.appraised_pct_since_base,
    c.tax_pct_since_base
FROM mart.dim_parcel p
JOIN mart.dim_parcel_location l ON l.gis_parcel_id = p.gis_parcel_id
JOIN mart.v_parcel_value_change c ON c.account = p.account;
