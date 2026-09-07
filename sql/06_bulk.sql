-- County-wide layer, from the certified appraisal roll.
--
-- This is one year for every account in the county; the parcel-page tables are
-- many years for a few accounts. They are kept apart deliberately: merging
-- them would hide which source a number came from, and the two disagree in
-- ways worth seeing (the roll is the certified figure, the page is what the
-- district currently shows).
CREATE OR REPLACE TABLE mart.fact_county_parcel_year AS
SELECT
    b.*,
    -- What the owner actually pays per $100 of appraised value, which is not
    -- any single published rate: exemptions and the mix of taxing units both
    -- move it.
    ROUND(100.0 * j.total_tax / NULLIF(b.appraised_value, 0), 4) AS effective_rate,
    j.total_tax                                                  AS total_tax,
    ROUND(b.assessed_value / NULLIF(b.appraised_value, 0), 4)    AS assessed_ratio,
    LEFT(b.use_code, 1)                                          AS use_class
FROM stg.bulk_parcel_year b
LEFT JOIN (
    SELECT account, tax_year, SUM(tax_amount) AS total_tax
    FROM stg.bulk_parcel_jurisdiction_year
    GROUP BY account, tax_year
) j ON j.account = b.account AND j.tax_year = b.tax_year;

CREATE OR REPLACE TABLE mart.fact_county_jurisdiction_year AS
SELECT * FROM stg.bulk_parcel_jurisdiction_year;

CREATE OR REPLACE TABLE mart.fact_county_exemption AS
SELECT * FROM stg.bulk_exemption;

-- Where the two sources overlap, so disagreements are visible rather than
-- silently resolved.
CREATE OR REPLACE VIEW mart.v_source_check AS
SELECT
    p.account,
    p.tax_year,
    -- The page's "Total Property Value" is the market value, not the
    -- appraised value: for an agricultural parcel the roll's APPRAISED VAL is
    -- the productivity figure and is far lower. Compare like with like.
    p.market_value                       AS page_market,
    c.market_value                       AS roll_market,
    p.market_value - c.market_value      AS market_diff,
    c.appraised_value                    AS roll_appraised,
    p.assessed_value                     AS page_assessed,
    c.assessed_value                     AS roll_assessed,
    p.assessed_value - c.assessed_value  AS assessed_diff,
    p.total_tax                          AS page_tax,
    c.total_tax                          AS roll_tax,
    ROUND(p.total_tax - c.total_tax, 2)  AS tax_diff
FROM mart.fact_parcel_year p
JOIN mart.fact_county_parcel_year c
  ON c.account = p.account AND c.tax_year = p.tax_year;
