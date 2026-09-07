-- Export view: one row per parcel with everything the homeowner extract needs
-- except the year rows, which are joined on in the exporter.
CREATE OR REPLACE VIEW mart.v_homeowner AS
SELECT
    p.account                                   AS id,
    p.owner_name                                AS name,
    p.situs_address                             AS address,
    COALESCE(l.gis_city, '')                    AS town,
    l.voting_precinct                           AS precinct,
    l.voting_precinct_name                      AS precinct_name,
    l.commissioner_precinct                     AS commissioner_precinct,
    -- The district's own use class decides this: A/B/M are dwellings, D and E
    -- are land. Anything else is neither, and says so rather than guessing.
    CASE
        WHEN p.use_class IN ('A', 'B', 'M') THEN 'house'
        WHEN p.use_class IN ('D', 'E')      THEN 'acreage'
        ELSE 'other'
    END                                         AS property_type,
    p.use_code                                  AS use_code,
    p.sector                                    AS sector,
    p.homestead_shown                           AS homestead_exemption,
    p.gis_parcel_id                             AS gis_parcel_id,
    l.latitude                                  AS latitude,
    l.longitude                                 AS longitude
FROM mart.dim_parcel p
LEFT JOIN mart.dim_parcel_location l ON l.gis_parcel_id = p.gis_parcel_id;
