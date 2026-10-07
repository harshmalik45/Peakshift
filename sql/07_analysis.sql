-- Step 7: SQL analysis. When do homes use electricity, and who drives the evening peak?
-- Each query block begins with a name line. src/07_analysis.py runs the blocks in order
-- and saves each result to reports/analysis/<name>.csv (blocks named setup... only run).

-- name: setup
-- Each reading is the energy used in the 30 minutes BEFORE its timestamp (the data's
-- daily blocks run 00:30 -> 00:00), so for time-of-day questions we label a reading by
-- the START of its half-hour. Days stay as cleaned in Step 5 (48 readings each).
CREATE OR REPLACE VIEW r AS
SELECT household_id,
       tariff_group,
       kwh,
       CAST(ts AS DATE)                              AS day,
       month(ts)                                     AS month,
       isodow(ts) IN (6, 7)                          AS is_weekend,     -- Saturday, Sunday
       hour(ts - INTERVAL 30 MINUTE)
         + minute(ts - INTERVAL 30 MINUTE) / 60.0    AS hour_of_day     -- 0.0, 0.5 ... 23.5
FROM 'data/clean/readings_2013_final.parquet';

-- name: setup_slot_shares
-- Share of each home's electricity in J&K's ToD slots: solar 09:00-17:00 (20% off),
-- peak 06:00-09:00 and 17:00-22:00 (10% extra), normal = the rest. Used by Q7, Q8 and Step 9.
CREATE OR REPLACE VIEW slot_shares AS
SELECT household_id,
       tariff_group,
       SUM(kwh) FILTER (WHERE hour_of_day >= 9 AND hour_of_day < 17) / SUM(kwh)     AS solar_share,
       SUM(kwh) FILTER (WHERE (hour_of_day >= 6 AND hour_of_day < 9)
                           OR (hour_of_day >= 17 AND hour_of_day < 22)) / SUM(kwh)  AS peak_share,
       SUM(kwh) FILTER (WHERE hour_of_day >= 22 OR hour_of_day < 6) / SUM(kwh)      AS normal_share
FROM r
GROUP BY household_id, tariff_group;

-- name: overview
-- Q1. How much electricity does a typical home use? ROLLUP adds an "All homes" row.
WITH per_home AS (
    SELECT household_id, tariff_group,
           SUM(kwh) / COUNT(DISTINCT day) AS daily_kwh
    FROM r
    GROUP BY household_id, tariff_group
)
SELECT COALESCE(tariff_group, 'All homes')   AS tariff_group,
       COUNT(*)                              AS homes,
       ROUND(MEDIAN(daily_kwh), 2)           AS median_daily_kwh,
       ROUND(AVG(daily_kwh), 2)              AS mean_daily_kwh,
       ROUND(MEDIAN(daily_kwh) * 365)        AS median_yearly_kwh
FROM per_home
GROUP BY ROLLUP (tariff_group)
ORDER BY tariff_group;

-- name: daily_curve
-- Q2. At what time of day do homes use the most? Average kW per home (kWh per half hour x 2).
SELECT hour_of_day,
       ROUND(AVG(kwh) * 2, 3)                                 AS all_days_kw,
       ROUND(AVG(kwh) FILTER (WHERE NOT is_weekend) * 2, 3)   AS weekday_kw,
       ROUND(AVG(kwh) FILTER (WHERE is_weekend) * 2, 3)       AS weekend_kw,
       RANK() OVER (ORDER BY AVG(kwh) DESC)                   AS busiest_rank
FROM r
GROUP BY hour_of_day
ORDER BY hour_of_day;

-- name: monthly
-- Q3. How does use change through the year? LAG() fetches the previous month's value.
WITH by_month AS (
    SELECT month,
           SUM(kwh) / (COUNT(*) / 48.0) AS daily_kwh      -- 48 readings = one home-day
    FROM r
    GROUP BY month
)
SELECT month,
       ROUND(daily_kwh, 2)                                                        AS avg_daily_kwh,
       ROUND(100 * (daily_kwh / LAG(daily_kwh) OVER (ORDER BY month) - 1), 1)     AS change_vs_prev_month_pct
FROM by_month
ORDER BY month;

-- name: load_factor
-- Q4. How "peaky" is a home? Load factor = average demand / peak demand (1.0 = perfectly flat).
WITH per_home AS (
    SELECT household_id, tariff_group,
           AVG(kwh) * 2 AS avg_kw,
           MAX(kwh) * 2 AS peak_kw
    FROM r
    GROUP BY household_id, tariff_group
)
SELECT COALESCE(tariff_group, 'All homes')    AS tariff_group,
       ROUND(MEDIAN(avg_kw), 2)               AS median_avg_kw,
       ROUND(MEDIAN(peak_kw), 2)              AS median_peak_kw,
       ROUND(MEDIAN(avg_kw / peak_kw), 3)     AS median_load_factor
FROM per_home
GROUP BY ROLLUP (tariff_group)
ORDER BY tariff_group;

-- name: peak_drivers
-- Q5. Do a few homes drive the evening peak (17:00-22:00)?
-- NTILE(10) splits homes into 10 equal groups, heaviest evening users first.
-- SUM(SUM(x)) OVER () is the grand total across all groups, so share = group sum / total.
WITH evening AS (
    SELECT household_id,
           SUM(kwh) FILTER (WHERE hour_of_day >= 17 AND hour_of_day < 22)
             / COUNT(DISTINCT day)                                  AS evening_kwh_per_day
    FROM r
    GROUP BY household_id
),
deciles AS (
    SELECT evening_kwh_per_day,
           NTILE(10) OVER (ORDER BY evening_kwh_per_day DESC)       AS decile
    FROM evening
)
SELECT decile,
       COUNT(*)                                                     AS homes,
       ROUND(AVG(evening_kwh_per_day), 2)                           AS avg_evening_kwh_per_day,
       ROUND(100 * SUM(evening_kwh_per_day)
             / SUM(SUM(evening_kwh_per_day)) OVER (), 1)            AS share_pct,
       ROUND(100 * SUM(SUM(evening_kwh_per_day)) OVER (ORDER BY decile)
             / SUM(SUM(evening_kwh_per_day)) OVER (), 1)            AS cumulative_share_pct
FROM deciles
GROUP BY decile
ORDER BY decile;

-- name: top_homes
-- Q6. Which 5 homes use the most, compared with the typical (median) home?
WITH per_home AS (
    SELECT household_id, tariff_group,
           SUM(kwh) / COUNT(DISTINCT day) AS daily_kwh
    FROM r
    GROUP BY household_id, tariff_group
),
typical AS (
    SELECT MEDIAN(daily_kwh) AS median_kwh FROM per_home
),
ranked AS (
    SELECT *, RANK() OVER (ORDER BY daily_kwh DESC) AS rnk FROM per_home
)
SELECT rnk                                AS rank,
       household_id,
       tariff_group,
       ROUND(daily_kwh, 1)                AS daily_kwh,
       ROUND(daily_kwh / median_kwh, 1)   AS times_median_home
FROM ranked CROSS JOIN typical
WHERE rnk <= 5
ORDER BY rnk;

-- name: tod_slot_shares
-- Q7. Each home's split across J&K's ToD slots (saved for Step 9).
SELECT household_id,
       tariff_group,
       ROUND(solar_share, 4)   AS solar_share,
       ROUND(peak_share, 4)    AS peak_share,
       ROUND(normal_share, 4)  AS normal_share
FROM slot_shares
ORDER BY household_id;

-- name: tod_slot_summary
-- Q8. Across homes: the typical split, and how many homes use more in peak than in solar hours.
-- Each slot is 8 hours long, so a perfectly flat home would put 33.3% in each.
SELECT COALESCE(tariff_group, 'All homes')                                     AS tariff_group,
       ROUND(100 * MEDIAN(solar_share), 1)                                     AS median_solar_pct,
       ROUND(100 * MEDIAN(peak_share), 1)                                      AS median_peak_pct,
       ROUND(100 * MEDIAN(normal_share), 1)                                    AS median_normal_pct,
       ROUND(100 * AVG(CASE WHEN peak_share > solar_share THEN 1 ELSE 0 END), 1) AS pct_homes_peak_over_solar
FROM slot_shares
GROUP BY ROLLUP (tariff_group)
ORDER BY tariff_group;


-- name: diversity
-- Q9. Homes don't all peak at the same moment (an EE idea: "diversity").
-- Diversity factor = the average home's OWN yearly peak / the group's highest half-hour
-- of the year (per home). Well above 1 means individual peaks are spread out in time.
WITH own_peaks AS (
    SELECT household_id, MAX(kwh) * 2 AS own_peak_kw
    FROM r
    GROUP BY household_id
),
group_demand AS (                       -- all homes together, at each half-hour of the year
    SELECT day, hour_of_day, AVG(kwh) * 2 AS kw_per_home
    FROM r
    GROUP BY day, hour_of_day
),
group_peak AS (
    SELECT * FROM group_demand ORDER BY kw_per_home DESC LIMIT 1
)
SELECT ROUND((SELECT AVG(own_peak_kw) FROM own_peaks), 2)                 AS avg_own_peak_kw,
       ROUND(kw_per_home, 2)                                              AS group_peak_kw_per_home,
       day                                                                AS group_peak_day,
       hour_of_day                                                        AS group_peak_starts,
       ROUND((SELECT AVG(own_peak_kw) FROM own_peaks) / kw_per_home, 1)   AS diversity_factor
FROM group_peak;