-- Mart: the grain the project reports on -- one row per account per tax year,
-- plus the per-jurisdiction detail behind each year's tax bill.
CREATE SCHEMA IF NOT EXISTS mart;

CREATE OR REPLACE TABLE mart.dim_parcel AS
SELECT * FROM stg.parcel;

CREATE OR REPLACE TABLE mart.fact_parcel_year AS
SELECT * FROM stg.parcel_value;

CREATE OR REPLACE TABLE mart.fact_parcel_jurisdiction_year AS
SELECT * FROM stg.parcel_jurisdiction;

-- Year-over-year and since-baseline movement in appraised value and tax.
--
-- Each measure baselines on the first year IT has a figure, not the parcel's
-- first published year: a new build or a split lands on the roll with an
-- appraisal before any levy is calculated, and taking the parcel's first year
-- would baseline the tax on a NULL and null out every percentage after it.
-- The two base years are carried separately because they can differ, and
-- percentages measured from different years are not comparable to each other.
CREATE OR REPLACE VIEW mart.v_parcel_value_change AS
WITH base AS (
    SELECT
        account,
        tax_year,
        market_value,
        assessed_value,
        total_tax,
        LAG(market_value) OVER w AS prev_market_value,
        LAG(total_tax)       OVER w AS prev_total_tax,
        FIRST_VALUE(market_value IGNORE NULLS) OVER w AS first_market_value,
        FIRST_VALUE(total_tax       IGNORE NULLS) OVER w AS first_total_tax,
        FIRST_VALUE(CASE WHEN market_value IS NOT NULL THEN tax_year END
                    IGNORE NULLS) OVER w AS market_base_year,
        FIRST_VALUE(CASE WHEN total_tax IS NOT NULL THEN tax_year END
                    IGNORE NULLS) OVER w AS tax_base_year,
        MIN(tax_year) OVER (PARTITION BY account) AS base_year
    FROM mart.fact_parcel_year
    WINDOW w AS (PARTITION BY account ORDER BY tax_year)
)
SELECT
    account,
    tax_year,
    base_year,
    market_base_year,
    tax_base_year,
    market_value,
    assessed_value,
    total_tax,
    market_value - prev_market_value AS market_change_yoy,
    ROUND(100.0 * (market_value - prev_market_value)
          / NULLIF(prev_market_value, 0), 2) AS market_pct_yoy,
    total_tax - prev_total_tax AS tax_change_yoy,
    ROUND(100.0 * (total_tax - prev_total_tax)
          / NULLIF(prev_total_tax, 0), 2) AS tax_pct_yoy,
    market_value - first_market_value AS market_change_since_base,
    ROUND(100.0 * (market_value - first_market_value)
          / NULLIF(first_market_value, 0), 2) AS market_pct_since_base,
    total_tax - first_total_tax AS tax_change_since_base,
    ROUND(100.0 * (total_tax - first_total_tax)
          / NULLIF(first_total_tax, 0), 2) AS tax_pct_since_base
FROM base;

-- One row per account: the whole published history compressed to a trend.
CREATE OR REPLACE VIEW mart.v_parcel_trend AS
WITH bounds AS (
    SELECT
        account,
        MIN(tax_year) AS first_year,
        MAX(tax_year) AS last_year,
        COUNT(*)      AS years_observed,
        -- Same reasoning as above: the tax span is only the years actually
        -- levied, which can start after the parcel first appears.
        MIN(tax_year) FILTER (WHERE total_tax IS NOT NULL) AS tax_first_year,
        MAX(tax_year) FILTER (WHERE total_tax IS NOT NULL) AS tax_last_year
    FROM mart.fact_parcel_year
    GROUP BY account
)
SELECT
    b.account,
    p.owner_name,
    p.situs_address,
    b.first_year,
    b.last_year,
    b.years_observed,
    f.market_value AS first_market_value,
    l.market_value AS last_market_value,
    b.tax_first_year,
    b.tax_last_year,
    tf.total_tax      AS first_total_tax,
    tl.total_tax      AS last_total_tax,
    ROUND(100.0 * (l.market_value - f.market_value)
          / NULLIF(f.market_value, 0), 2) AS market_pct_total,
    ROUND(100.0 * (tl.total_tax - tf.total_tax)
          / NULLIF(tf.total_tax, 0), 2) AS tax_pct_total,
    -- Compound annual growth over the observed span.
    ROUND(100.0 * (POWER(l.market_value / NULLIF(f.market_value, 0),
                         1.0 / NULLIF(b.last_year - b.first_year, 0)) - 1), 2)
        AS market_cagr_pct,
    ROUND(100.0 * (POWER(tl.total_tax / NULLIF(tf.total_tax, 0),
                         1.0 / NULLIF(b.tax_last_year - b.tax_first_year, 0)) - 1), 2)
        AS tax_cagr_pct
FROM bounds b
JOIN mart.fact_parcel_year f ON f.account = b.account AND f.tax_year = b.first_year
JOIN mart.fact_parcel_year l ON l.account = b.account AND l.tax_year = b.last_year
LEFT JOIN mart.fact_parcel_year tf
       ON tf.account = b.account AND tf.tax_year = b.tax_first_year
LEFT JOIN mart.fact_parcel_year tl
       ON tl.account = b.account AND tl.tax_year = b.tax_last_year
LEFT JOIN mart.dim_parcel p ON p.account = b.account;

-- Which taxing jurisdiction actually drove a year's change.
CREATE OR REPLACE VIEW mart.v_jurisdiction_change AS
SELECT
    account,
    jurisdiction,
    tax_year,
    taxable_value,
    tax_rate,
    tax_amount,
    tax_amount - LAG(tax_amount) OVER w AS tax_change_yoy,
    tax_rate   - LAG(tax_rate)   OVER w AS rate_change_yoy,
    taxable_value - LAG(taxable_value) OVER w AS taxable_value_change_yoy
FROM mart.fact_parcel_jurisdiction_year
WINDOW w AS (PARTITION BY account, jurisdiction ORDER BY tax_year);
