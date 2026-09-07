-- Staging layer: the nested parcel document flattened and typed.
-- Money is DECIMAL(14,2); tax rates are per $100 of value as published, kept
-- at 6 dp because the district quotes them that way.
CREATE SCHEMA IF NOT EXISTS stg;

CREATE OR REPLACE TABLE stg.parcel AS
SELECT
    parcel.account                          AS account,
    parcel.gis_parcel_id                    AS gis_parcel_id,
    parcel.parcel_id                        AS parcel_id,
    parcel.owner_name                       AS owner_name,
    parcel.owner_address                    AS owner_address,
    parcel.situs_address                    AS situs_address,
    parcel.use_code                         AS use_code,
    -- The leading letter of the use code is the Texas state property
    -- category, so the sector comes out of the code rather than a lookup the
    -- district would have to publish separately.
    LEFT(parcel.use_code, 1)                AS use_class,
    CASE LEFT(parcel.use_code, 1)
        WHEN 'A' THEN 'Single-family residential'
        WHEN 'B' THEN 'Multifamily residential'
        WHEN 'C' THEN 'Vacant lots & tracts'
        WHEN 'D' THEN 'Qualified agricultural land'
        WHEN 'E' THEN 'Rural land & improvements'
        WHEN 'F' THEN 'Commercial & industrial'
        WHEN 'G' THEN 'Oil, gas & minerals'
        WHEN 'H' THEN 'Tangible personal property'
        WHEN 'J' THEN 'Utilities'
        WHEN 'L' THEN 'Business personal property'
        WHEN 'M' THEN 'Mobile homes & other tangible'
        WHEN 'N' THEN 'Intangible personal property'
        WHEN 'O' THEN 'Residential inventory'
        WHEN 'S' THEN 'Special inventory'
        WHEN 'X' THEN 'Exempt'
        ELSE 'Unclassified'
    END                                     AS sector,
    parcel.tax_district                     AS tax_district,
    TRY_CAST(parcel.acreage AS DECIMAL(12,4)) AS acreage,
    parcel.subdivision                      AS subdivision,
    parcel.exemptions                       AS exemptions,
    -- Exemptions render as "HS: Homestead (11.13(b))  (100%)"; the code is
    -- everything before the colon.
    list_transform(parcel.exemptions,
                   x -> TRIM(SPLIT_PART(x, ':', 1)))  AS exemption_codes,
    -- The district withholds some exemptions online ("For privacy reasons not
    -- all exemptions are shown"), so FALSE means "not shown", not "none held".
    list_contains(list_transform(parcel.exemptions,
                                 x -> TRIM(SPLIT_PART(x, ':', 1))), 'HS')
                                            AS homestead_shown,
    TRY_CAST(parcel.transfer_date AS DATE)  AS transfer_date,
    parcel.instrument_number                AS instrument_number,
    parcel.legal_description                AS legal_description,
    _staged_at                              AS staged_at
FROM raw.parcel_document;

CREATE OR REPLACE TABLE stg.parcel_value AS
SELECT
    d.parcel.account                                AS account,
    v.tax_year::INTEGER                             AS tax_year,
    TRY_CAST(v.building_value      AS DECIMAL(14,2)) AS building_value,
    TRY_CAST(v.land_value          AS DECIMAL(14,2)) AS land_value,
    TRY_CAST(v.total_property_value AS DECIMAL(14,2)) AS appraised_value,
    TRY_CAST(v.special_use_value   AS DECIMAL(14,2)) AS special_use_value,
    TRY_CAST(v.cap_loss            AS DECIMAL(14,2)) AS cap_loss,
    TRY_CAST(v.net_assessed_value  AS DECIMAL(14,2)) AS assessed_value,
    TRY_CAST(v.total_tax           AS DECIMAL(14,2)) AS total_tax,
    v.use_code                                      AS use_code,
    TRY_CAST(v.acreage             AS DECIMAL(12,4)) AS acreage,
    TRY_CAST(v.main_area_sqft      AS DECIMAL(12,2)) AS main_area_sqft
FROM raw.parcel_document d, UNNEST(d.values) AS t(v);

CREATE OR REPLACE TABLE stg.parcel_jurisdiction AS
SELECT
    d.parcel.account                            AS account,
    j.tax_year::INTEGER                         AS tax_year,
    j.jurisdiction                              AS jurisdiction,
    TRY_CAST(j.taxable_value AS DECIMAL(14,2))  AS taxable_value,
    TRY_CAST(j.tax_rate      AS DECIMAL(12,6))  AS tax_rate,
    TRY_CAST(j.tax_amount    AS DECIMAL(14,2))  AS tax_amount
FROM raw.parcel_document d, UNNEST(d.jurisdictions) AS t(j);
