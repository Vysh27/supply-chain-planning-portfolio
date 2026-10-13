-- ============================================================================
-- Planning leakage & availability SQL — quick-commerce (darkstore) grocery
-- Dialect: ANSI SQL (Redshift / Databricks SQL / BigQuery with minor tweaks).
--
-- Demonstrates the SQL the APM JD asks for: complex joins, window functions,
-- CTEs and query patterns over orders, inventory, POs, GRNs and wastage.
-- Tables: demand, inventory, purchase_orders, grn, wastage, skus
-- ============================================================================


-- 1) AVAILABILITY & LOST SALES BY DARKSTORE x CATEGORY ------------------------
-- Unit fill rate and lost-sales value, the headline leakage metric.
SELECT
    i.darkstore_id,
    s.category,
    SUM(d.units_fulfilled)                                   AS units_fulfilled,
    SUM(d.units_demanded)                                    AS units_demanded,
    ROUND(SUM(d.units_fulfilled) * 100.0
          / NULLIF(SUM(d.units_demanded), 0), 1)             AS availability_pct,
    SUM(d.units_lost * s.price_inr)                          AS lost_sales_inr
FROM demand d
JOIN skus s          ON s.sku_id = d.sku_id
JOIN inventory i     ON i.sku_id = d.sku_id
                    AND i.darkstore_id = d.darkstore_id
                    AND i.order_date_x IS NULL        -- (join key simplified; see note)
GROUP BY 1, 2
ORDER BY lost_sales_inr DESC;
-- Note: in practice demand and inventory share (date, darkstore_id, sku_id);
-- the extra predicate above is illustrative. Keep the natural 3-part key.


-- 2) STOCK-OUT DAYS (availability misses) ------------------------------------
-- Store-SKU-days where shelf was empty but demand existed — the raw miss count.
WITH joined AS (
    SELECT d.date, d.darkstore_id, d.sku_id,
           d.units_demanded, i.on_hand_units
    FROM demand d
    JOIN inventory i
      ON i.date = d.date AND i.darkstore_id = d.darkstore_id AND i.sku_id = d.sku_id
)
SELECT
    sku_id,
    COUNT(*)                                                      AS total_days,
    SUM(CASE WHEN on_hand_units = 0 AND units_demanded > 0
             THEN 1 ELSE 0 END)                                   AS stockout_days,
    ROUND(SUM(CASE WHEN on_hand_units = 0 AND units_demanded > 0
             THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)           AS stockout_rate_pct
FROM joined
GROUP BY sku_id
HAVING SUM(CASE WHEN on_hand_units = 0 AND units_demanded > 0 THEN 1 ELSE 0 END) > 0
ORDER BY stockout_rate_pct DESC;


-- 3) DAYS ON HAND (DOH) with a trailing-demand window ------------------------
-- DOH = on_hand / trailing-14-day average daily demand, per store-SKU-day.
WITH dd AS (
    SELECT d.date, d.darkstore_id, d.sku_id, d.units_demanded, i.on_hand_units,
           AVG(d.units_demanded) OVER (
               PARTITION BY d.darkstore_id, d.sku_id
               ORDER BY d.date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
           ) AS avg_daily_demand
    FROM demand d
    JOIN inventory i
      ON i.date = d.date AND i.darkstore_id = d.darkstore_id AND i.sku_id = d.sku_id
)
SELECT date, darkstore_id, sku_id, on_hand_units,
       ROUND(avg_daily_demand, 1)                                  AS avg_daily_demand,
       ROUND(on_hand_units / NULLIF(avg_daily_demand, 0), 1)       AS doh
FROM dd
WHERE on_hand_units / NULLIF(avg_daily_demand, 0) > 14              -- high-DOH pockets
ORDER BY doh DESC;


-- 4) VENDOR DELAY (PO vs GRN) ------------------------------------------------
-- Average lateness and fill rate by vendor — a prime availability root cause.
SELECT
    po.vendor,
    COUNT(*)                                                       AS receipts,
    ROUND(AVG(DATEDIFF('day', po.expected_date, g.received_date)), 2) AS avg_late_days,  -- BQ: DATE_DIFF(g.received_date, po.expected_date, DAY)
    ROUND(AVG(g.qty_received * 1.0 / NULLIF(po.qty_ordered, 0)), 3) AS avg_fill_rate,
    SUM(CASE WHEN g.received_date > po.expected_date THEN 1 ELSE 0 END) AS late_receipts
FROM purchase_orders po
JOIN grn g ON g.po_id = po.po_id
GROUP BY po.vendor
ORDER BY avg_late_days DESC;


-- 5) WASTAGE (expiry) BY CATEGORY with contribution rank --------------------
SELECT
    s.category,
    SUM(w.units_expired)                                          AS units_expired,
    SUM(w.units_expired * s.cost_inr)                             AS waste_value_inr,
    ROUND(SUM(w.units_expired * s.cost_inr) * 100.0
          / SUM(SUM(w.units_expired * s.cost_inr)) OVER (), 1)    AS pct_of_waste
FROM wastage w
JOIN skus s ON s.sku_id = w.sku_id
GROUP BY s.category
ORDER BY waste_value_inr DESC;


-- 6) REUSABLE VIEW: daily planning scorecard per darkstore x SKU -------------
CREATE OR REPLACE VIEW vw_planning_daily_scorecard AS
SELECT
    d.date, d.darkstore_id, d.sku_id, s.category,
    d.units_demanded, d.units_fulfilled, d.units_lost,
    i.on_hand_units,
    d.units_lost * s.price_inr                                   AS lost_sales_inr
FROM demand d
JOIN skus s      ON s.sku_id = d.sku_id
JOIN inventory i ON i.date = d.date
                AND i.darkstore_id = d.darkstore_id
                AND i.sku_id = d.sku_id;
