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
-- Baseline is each account's own earliest published year, which varies by
-- parcel, so it is carried as a column rather than assumed.
CREATE OR REPLACE VIEW mart.v_parcel_value_change AS
WITH base AS (
    SELECT
        account,
        tax_year,
        appraised_value,
        assessed_value,
        total_tax,
        LAG(appraised_value) OVER w AS prev_appraised_value,
        LAG(total_tax)       OVER w AS prev_total_tax,
        FIRST_VALUE(appraised_value) OVER w AS first_appraised_value,
        FIRST_VALUE(total_tax)       OVER w AS first_total_tax,
        MIN(tax_year) OVER (PARTITION BY account) AS base_year
    FROM mart.fact_parcel_year
    WINDOW w AS (PARTITION BY account ORDER BY tax_year)
)
SELECT
    account,
    tax_year,
    base_year,
    appraised_value,
    assessed_value,
    total_tax,
    appraised_value - prev_appraised_value AS appraised_change_yoy,
    ROUND(100.0 * (appraised_value - prev_appraised_value)
          / NULLIF(prev_appraised_value, 0), 2) AS appraised_pct_yoy,
    total_tax - prev_total_tax AS tax_change_yoy,
    ROUND(100.0 * (total_tax - prev_total_tax)
          / NULLIF(prev_total_tax, 0), 2) AS tax_pct_yoy,
    appraised_value - first_appraised_value AS appraised_change_since_base,
    ROUND(100.0 * (appraised_value - first_appraised_value)
          / NULLIF(first_appraised_value, 0), 2) AS appraised_pct_since_base,
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
        COUNT(*)      AS years_observed
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
    f.appraised_value AS first_appraised_value,
    l.appraised_value AS last_appraised_value,
    f.total_tax       AS first_total_tax,
    l.total_tax       AS last_total_tax,
    ROUND(100.0 * (l.appraised_value - f.appraised_value)
          / NULLIF(f.appraised_value, 0), 2) AS appraised_pct_total,
    ROUND(100.0 * (l.total_tax - f.total_tax)
          / NULLIF(f.total_tax, 0), 2) AS tax_pct_total,
    -- Compound annual growth over the observed span.
    ROUND(100.0 * (POWER(l.appraised_value / NULLIF(f.appraised_value, 0),
                         1.0 / NULLIF(b.last_year - b.first_year, 0)) - 1), 2)
        AS appraised_cagr_pct,
    ROUND(100.0 * (POWER(l.total_tax / NULLIF(f.total_tax, 0),
                         1.0 / NULLIF(b.last_year - b.first_year, 0)) - 1), 2)
        AS tax_cagr_pct
FROM bounds b
JOIN mart.fact_parcel_year f ON f.account = b.account AND f.tax_year = b.first_year
JOIN mart.fact_parcel_year l ON l.account = b.account AND l.tax_year = b.last_year
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
