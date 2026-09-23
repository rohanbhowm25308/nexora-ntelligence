-- =====================================================================
-- Business Intelligence & Sales Analytics System — SQL Analytics Layer
-- These queries run against the `orders` table (SQLite) and back the
-- Flask API endpoints in app.py. Kept here as documented reference /
-- for reuse in Power BI, Tableau, or a warehouse (Postgres/MySQL) later.
-- =====================================================================

-- 1. Total revenue, profit, orders, AOV
SELECT
    ROUND(SUM(revenue), 2)                         AS total_revenue,
    ROUND(SUM(profit), 2)                          AS total_profit,
    COUNT(DISTINCT order_id)                       AS total_orders,
    ROUND(SUM(revenue) * 1.0 / COUNT(DISTINCT order_id), 2) AS avg_order_value,
    ROUND(SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0), 2) AS profit_margin_pct,
    COUNT(DISTINCT customer_id)                    AS total_customers
FROM orders
WHERE order_status != 'Cancelled';

-- 2. Monthly revenue & profit trend
SELECT
    strftime('%Y-%m', order_date) AS month,
    ROUND(SUM(revenue), 2)        AS revenue,
    ROUND(SUM(profit), 2)         AS profit,
    COUNT(DISTINCT order_id)      AS orders
FROM orders
WHERE order_status != 'Cancelled'
GROUP BY month
ORDER BY month;

-- 3. Top 10 products by revenue
SELECT
    product_name, category,
    ROUND(SUM(revenue), 2) AS revenue,
    ROUND(SUM(profit), 2)  AS profit,
    SUM(quantity)          AS units_sold
FROM orders
WHERE order_status != 'Cancelled'
GROUP BY product_name, category
ORDER BY revenue DESC
LIMIT 10;

-- 4. Top 10 customers by revenue
SELECT
    customer_id, customer_name,
    ROUND(SUM(revenue), 2)   AS total_spent,
    COUNT(DISTINCT order_id) AS total_orders,
    MAX(order_date)          AS last_purchase
FROM orders
WHERE order_status != 'Cancelled'
GROUP BY customer_id, customer_name
ORDER BY total_spent DESC
LIMIT 10;

-- 5. Region-wise performance
SELECT
    region,
    ROUND(SUM(revenue), 2)  AS revenue,
    ROUND(SUM(profit), 2)   AS profit,
    COUNT(DISTINCT order_id) AS orders,
    COUNT(DISTINCT customer_id) AS customers,
    ROUND(SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0), 2) AS margin_pct
FROM orders
WHERE order_status != 'Cancelled'
GROUP BY region
ORDER BY revenue DESC;

-- 6. Average order value
SELECT ROUND(SUM(revenue) * 1.0 / COUNT(DISTINCT order_id), 2) AS aov
FROM orders WHERE order_status != 'Cancelled';

-- 7. Repeat purchase / retention rate
WITH order_counts AS (
    SELECT customer_id, COUNT(DISTINCT order_id) AS n_orders
    FROM orders WHERE order_status != 'Cancelled'
    GROUP BY customer_id
)
SELECT
    COUNT(*)                                            AS total_customers,
    SUM(CASE WHEN n_orders > 1 THEN 1 ELSE 0 END)        AS repeat_customers,
    ROUND(SUM(CASE WHEN n_orders > 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS repeat_rate_pct
FROM order_counts;

-- 8. Month-over-month revenue growth
WITH monthly AS (
    SELECT strftime('%Y-%m', order_date) AS month, SUM(revenue) AS revenue
    FROM orders WHERE order_status != 'Cancelled'
    GROUP BY month
)
SELECT
    month, revenue,
    ROUND((revenue - LAG(revenue) OVER (ORDER BY month)) * 100.0
          / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 2) AS mom_growth_pct
FROM monthly
ORDER BY month;

-- 9. Category performance
SELECT
    category,
    ROUND(SUM(revenue), 2) AS revenue,
    ROUND(SUM(profit), 2)  AS profit,
    SUM(quantity)          AS units_sold
FROM orders
WHERE order_status != 'Cancelled'
GROUP BY category
ORDER BY revenue DESC;

-- 10. Day-of-week demand pattern
SELECT
    CASE CAST(strftime('%w', order_date) AS INTEGER)
        WHEN 0 THEN 'Sunday' WHEN 1 THEN 'Monday' WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday' WHEN 4 THEN 'Thursday' WHEN 5 THEN 'Friday'
        ELSE 'Saturday' END AS day_of_week,
    ROUND(SUM(revenue), 2) AS revenue,
    COUNT(DISTINCT order_id) AS orders
FROM orders
WHERE order_status != 'Cancelled'
GROUP BY day_of_week
ORDER BY revenue DESC;
