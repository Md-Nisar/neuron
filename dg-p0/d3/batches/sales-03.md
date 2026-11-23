# Batch sales-03: owner review

25 questions, 22 agree on every persona, 3 to adjudicate.

## S-A-047: How many order lines in completed 2025 orders had a discount of 10 percent or more?

Reference:
```sql
SELECT count(*) AS lines FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND l.discount_pct >= 10
```
Second annotator:
```sql
SELECT count(*) AS order_line_count
FROM sales.order_lines ol
JOIN sales.orders o ON ol.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
  AND ol.discount_pct >= 10
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | lines → 504 | yes |
| apac_analyst | lines → 540 | yes |
| global_manager | lines → 1452 | yes |

## S-A-051: What was the median value of completed orders in 2025? Round to two decimal places.

Reference:
```sql
SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY t.total)::numeric, 2) AS median_order_value FROM (SELECT o.order_id, sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS total FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.order_id) t
```
Second annotator:
```sql
WITH order_totals AS (
    SELECT o.order_id,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100.0)) AS order_total
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY o.order_id
)
SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY order_total)::numeric, 2) AS median_value
FROM order_totals
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | median_order_value → 51382.84 | yes |
| apac_analyst | median_order_value → 53208.42 | yes |
| global_manager | median_order_value → 51738.29 | yes |

## S-A-052: For each region, what was revenue in 2024 and in 2025?

Reference:
```sql
SELECT o.region_id AS region, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on < DATE '2025-01-01'), 2) AS revenue_2024, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on >= DATE '2025-01-01'), 2) AS revenue_2025 FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' GROUP BY o.region_id
```
Second annotator:
```sql
WITH completed_orders AS (
    SELECT order_id, region_id, ordered_on
    FROM sales.orders
    WHERE status = 'completed'
      AND EXTRACT(YEAR FROM ordered_on) IN (2024, 2025)
),
line_revenue AS (
    SELECT o.region_id,
           EXTRACT(YEAR FROM o.ordered_on)::int AS yr,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM completed_orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    GROUP BY o.region_id, EXTRACT(YEAR FROM o.ordered_on)
)
SELECT r.name AS region,
       COALESCE(SUM(CASE WHEN lr.yr = 2024 THEN lr.revenue END), 0) AS revenue_2024,
       COALESCE(SUM(CASE WHEN lr.yr = 2025 THEN lr.revenue END), 0) AS revenue_2025
FROM sales.regions r
LEFT JOIN line_revenue lr ON lr.region_id = r.region_id
GROUP BY r.name
ORDER BY r.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | region, revenue_2024, revenue_2025 → EMEA, 23748602.76, 44072021.08 | NO: 3 rows vs 1 |
| | second: region, revenue_2024, revenue_2025 → Americas, 0.0, 0.0; Asia Pacific, 0.0, 0.0; Europe, Middle East and Africa, 23748602.764, 44072021.0775 | |
| apac_analyst | region, revenue_2024, revenue_2025 → APAC, 19945656.05, 43182863.5 | NO: 3 rows vs 1 |
| | second: region, revenue_2024, revenue_2025 → Americas, 0.0, 0.0; Asia Pacific, 19945656.047, 43182863.503; Europe, Middle East and Africa, 0.0, 0.0 | |
| global_manager | region, revenue_2024, revenue_2025 → EMEA, 23748602.76, 44072021.08; APAC, 19945656.05, 43182863.5; AMER, 14649956.56, 35266787.21 | NO: values differ |
| | second: region, revenue_2024, revenue_2025 → Americas, 14649956.56, 35266787.213; Asia Pacific, 19945656.047, 43182863.503; Europe, Middle East and Africa, 23748602.764, 44072021.0775 | |

**Disagreement: owner to adjudicate.**

## S-A-053: Which product category had the highest return rate across 2024 and 2025, measured as returned units over units sold in completed orders, and what was the rate in percent to two decimal places?

Reference:
```sql
WITH sold AS (SELECT p.category, sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' GROUP BY p.category), ret AS (SELECT p.category, sum(r.quantity) AS units FROM sales.returns r JOIN sales.orders o USING (order_id) JOIN sales.order_lines l ON l.order_id = r.order_id AND l.line_no = r.line_no JOIN sales.products p ON p.product_id = l.product_id WHERE o.status = 'completed' GROUP BY p.category) SELECT s.category, round(100.0 * r.units / s.units, 2) AS return_rate_pct FROM sold s JOIN ret r USING (category) ORDER BY return_rate_pct DESC LIMIT 1
```
Second annotator:
```sql
WITH sold AS (
    SELECT p.category,
           SUM(ol.quantity) AS units_sold
    FROM sales.order_lines ol
    JOIN sales.orders o ON ol.order_id = o.order_id
    JOIN sales.products p ON ol.product_id = p.product_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2024-01-01'
      AND o.ordered_on <= DATE '2025-12-31'
    GROUP BY p.category
),
returned AS (
    SELECT p.category,
           SUM(r.quantity) AS units_returned
    FROM sales.returns r
    JOIN sales.order_lines ol ON r.order_id = ol.order_id AND r.line_no = ol.line_no
    JOIN sales.orders o ON ol.order_id = o.order_id
    JOIN sales.products p ON ol.product_id = p.product_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2024-01-01'
      AND o.ordered_on <= DATE '2025-12-31'
    GROUP BY p.category
)
SELECT s.category,
       ROUND((COALESCE(r.units_returned, 0)::numeric / NULLIF(s.units_sold, 0)) * 100, 2) AS return_rate_pct
FROM sold s
LEFT JOIN returned r ON s.category = r.category
ORDER BY return_rate_pct DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, return_rate_pct → Services, 2.83 | yes |
| apac_analyst | category, return_rate_pct → Hardware, 3.57 | yes |
| global_manager | category, return_rate_pct → Hardware, 2.95 | yes |

## S-A-054: What was cumulative revenue at the end of each month of 2025, in month order?

Reference:
```sql
SELECT month, round(sum(revenue) OVER (ORDER BY month), 2) AS cumulative_revenue FROM (SELECT extract(month FROM o.ordered_on)::int AS month, sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1) m ORDER BY month
```
Second annotator:
```sql
WITH monthly AS (
    SELECT date_trunc('month', o.ordered_on)::date AS month_start,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS month_revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY 1
),
cum AS (
    SELECT month_start,
           SUM(month_revenue) OVER (ORDER BY month_start ROWS UNBOUNDED PRECEDING) AS cumulative_revenue
    FROM monthly
)
SELECT month_start AS month, cumulative_revenue
FROM cum
ORDER BY month_start
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | month, cumulative_revenue → 1, 2353034.52; 2, 5017078.86; 3, 8455152.2; 4, 10699570.0; 5, 13167730.87; 6, 15849439.46 … (+6 rows) | NO: values differ |
| | second: month, cumulative_revenue → 2025-01-01, 2353034.5175; 2025-02-01, 5017078.8555; 2025-03-01, 8455152.2015; 2025-04-01, 10699570.0025; 2025-05-01, 13167730.8665; 2025-06-01, 15849439.463 … (+6 rows) | |
| apac_analyst | month, cumulative_revenue → 1, 2177085.78; 2, 4882341.84; 3, 8457932.94; 4, 11524649.12; 5, 15174945.46; 6, 18008659.07 … (+6 rows) | NO: values differ |
| | second: month, cumulative_revenue → 2025-01-01, 2177085.7795; 2025-02-01, 4882341.841; 2025-03-01, 8457932.9375; 2025-04-01, 11524649.12; 2025-05-01, 15174945.4615; 2025-06-01, 18008659.065 … (+6 rows) | |
| global_manager | month, cumulative_revenue → 1, 6897397.31; 2, 14084278.14; 3, 23607102.65; 4, 30003716.28; 5, 37429518.41; 6, 45518635.06 … (+6 rows) | NO: values differ |
| | second: month, cumulative_revenue → 2025-01-01, 6897397.3145; 2025-02-01, 14084278.1355; 2025-03-01, 23607102.646; 2025-04-01, 30003716.2825; 2025-05-01, 37429518.408; 2025-06-01, 45518635.0635 … (+6 rows) | |

**Disagreement: owner to adjudicate.**

## S-A-055: How many sales reps had higher revenue in 2025 than in 2024?

Reference:
```sql
SELECT count(*) AS reps FROM (SELECT o.rep_id FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' GROUP BY o.rep_id HAVING sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on >= DATE '2025-01-01') > coalesce(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on < DATE '2025-01-01'), 0)) t
```
Second annotator:
```sql
WITH rep_rev AS (
    SELECT
        o.rep_id,
        EXTRACT(YEAR FROM o.ordered_on)::int AS yr,
        SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100.0)) AS revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND EXTRACT(YEAR FROM o.ordered_on) IN (2024, 2025)
    GROUP BY o.rep_id, EXTRACT(YEAR FROM o.ordered_on)
),
pivot AS (
    SELECT
        rep_id,
        MAX(CASE WHEN yr = 2024 THEN revenue END) AS rev_2024,
        MAX(CASE WHEN yr = 2025 THEN revenue END) AS rev_2025
    FROM rep_rev
    GROUP BY rep_id
)
SELECT COUNT(*) AS higher_revenue_reps
FROM pivot
WHERE rev_2025 > rev_2024
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | reps → 8 | yes |
| apac_analyst | reps → 8 | yes |
| global_manager | reps → 24 | yes |

## S-A-056: What was the average number of completed orders per active customer in 2025, counting only customers with at least one completed order that year? Round to two decimal places.

Reference:
```sql
SELECT round(count(*)::numeric / count(DISTINCT customer_id), 2) AS orders_per_customer FROM sales.orders o WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
WITH cust_orders AS (
    SELECT customer_id, COUNT(*) AS order_cnt
    FROM sales.orders
    WHERE status = 'completed'
      AND ordered_on >= DATE '2025-01-01'
      AND ordered_on < DATE '2026-01-01'
    GROUP BY customer_id
)
SELECT ROUND(AVG(order_cnt)::numeric, 2) AS avg_completed_orders_per_active_customer
FROM cust_orders
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders_per_customer → 5.9 | yes |
| apac_analyst | orders_per_customer → 5.78 | yes |
| global_manager | orders_per_customer → 5.75 | yes |

## S-A-057: Which country had the most cancelled orders across 2024 and 2025, and how many?

Reference:
```sql
SELECT co.name AS country, count(*) AS cancelled_orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id JOIN sales.countries co ON co.country_code = c.country_code WHERE o.status = 'cancelled' GROUP BY co.name ORDER BY cancelled_orders DESC LIMIT 1
```
Second annotator:
```sql
SELECT c.name AS country, COUNT(o.order_id) AS cancelled_orders
FROM sales.orders o
JOIN sales.customers cu ON o.customer_id = cu.customer_id
JOIN sales.countries c ON cu.country_code = c.country_code
WHERE o.status = 'cancelled'
  AND o.ordered_on >= DATE '2024-01-01'
  AND o.ordered_on <= DATE '2025-12-31'
GROUP BY c.name
ORDER BY cancelled_orders DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | country, cancelled_orders → United Arab Emirates, 27 | yes |
| apac_analyst | country, cancelled_orders → India, 25 | yes |
| global_manager | country, cancelled_orders → Brazil, 33 | yes |

## S-A-058: What was revenue per sales rep in 2025, averaged over all reps? Round to two decimal places.

Reference:
```sql
SELECT round(avg(rev), 2) AS avg_revenue_per_rep FROM (SELECT r.rep_id, coalesce(sum(t.revenue), 0) AS rev FROM sales.sales_reps r LEFT JOIN (SELECT o.rep_id, sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.rep_id) t ON t.rep_id = r.rep_id GROUP BY r.rep_id) x
```
Second annotator:
```sql
WITH rep_rev AS (
    SELECT o.rep_id,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY o.rep_id
)
SELECT round(AVG(COALESCE(r.revenue, 0))::numeric, 2) AS avg_revenue_per_rep
FROM sales.sales_reps s
LEFT JOIN rep_rev r ON r.rep_id = s.rep_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_revenue_per_rep → 5509002.63 | yes |
| apac_analyst | avg_revenue_per_rep → 5397857.94 | yes |
| global_manager | avg_revenue_per_rep → 5105069.66 | yes |

## S-A-059: How many returns were filed within 30 days of the order date?

Reference:
```sql
SELECT count(*) AS returns FROM sales.returns r JOIN sales.orders o USING (order_id) WHERE r.returned_on - o.ordered_on <= 30
```
Second annotator:
```sql
SELECT count(*)
FROM sales.returns r
JOIN sales.orders o ON r.order_id = o.order_id
WHERE r.returned_on <= o.ordered_on + interval '30 days'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | returns → 68 | yes |
| apac_analyst | returns → 60 | yes |
| global_manager | returns → 172 | yes |

## S-A-060: In 2025, what was revenue from each product category within each customer segment?

Reference:
```sql
SELECT c.segment, p.category, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id JOIN sales.products p ON p.product_id = l.product_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.segment, p.category
```
Second annotator:
```sql
WITH completed_orders AS (
    SELECT order_id, customer_id
    FROM sales.orders
    WHERE status = 'completed'
      AND ordered_on >= DATE '2025-01-01'
      AND ordered_on < DATE '2026-01-01'
),
line_revenue AS (
    SELECT
        p.category,
        c.segment,
        (ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS line_rev
    FROM sales.order_lines ol
    JOIN completed_orders co ON ol.order_id = co.order_id
    JOIN sales.products p ON ol.product_id = p.product_id
    JOIN sales.customers c ON co.customer_id = c.customer_id
)
SELECT
    category,
    segment,
    SUM(line_rev) AS revenue
FROM line_revenue
GROUP BY category, segment
ORDER BY category, segment
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | segment, category, revenue → Consumer, Hardware, 11145391.9; SMB, Accessories, 373261.96; Enterprise, Services, 1283978.33; Consumer, Accessories, 292637.32; Enterprise, Accessories, 114729.23; SMB, Services, 3467898.77 … (+6 rows) | yes |
| apac_analyst | segment, category, revenue → Consumer, Hardware, 7702447.13; SMB, Accessories, 358381.4; Enterprise, Services, 2008440.07; Consumer, Accessories, 317798.96; Enterprise, Accessories, 182625.62; SMB, Services, 3325511.8 … (+6 rows) | yes |
| global_manager | segment, category, revenue → Consumer, Hardware, 24490452.2; SMB, Accessories, 976622.75; Enterprise, Services, 5312125.33; Consumer, Accessories, 781102.4; Enterprise, Accessories, 420158.86; SMB, Services, 10328099.44 … (+6 rows) | yes |

## S-A-061: What was the month-over-month change in revenue, in USD, for each month from February to December 2025?

Reference:
```sql
SELECT month, round(revenue - lag(revenue) OVER (ORDER BY month), 2) AS change_usd FROM (SELECT extract(month FROM o.ordered_on)::int AS month, sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1) m ORDER BY month OFFSET 1
```
Second annotator:
```sql
WITH monthly AS (
    SELECT date_trunc('month', o.ordered_on)::date AS month_start,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY 1
),
changes AS (
    SELECT month_start,
           revenue - LAG(revenue) OVER (ORDER BY month_start) AS revenue_change
    FROM monthly
)
SELECT month_start AS month,
       revenue_change
FROM changes
WHERE month_start >= DATE '2025-02-01'
  AND month_start <= DATE '2025-12-01'
ORDER BY month_start
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | month, change_usd → 2, 311009.82; 3, 774029.01; 4, -1193655.55; 5, 223743.06; 6, 213547.73; 7, 1808503.49 … (+5 rows) | NO: values differ |
| | second: month, revenue_change → 2025-02-01, 311009.8205; 2025-03-01, 774029.008; 2025-04-01, -1193655.545; 2025-05-01, 223743.063; 2025-06-01, 213547.7325; 2025-07-01, 1808503.487 … (+5 rows) | |
| apac_analyst | month, change_usd → 2, 528170.28; 3, 870335.04; 4, -508874.91; 5, 583580.16; 6, -816582.74; 7, 1297434.43 … (+5 rows) | NO: values differ |
| | second: month, revenue_change → 2025-02-01, 528170.282; 2025-03-01, 870335.035; 2025-04-01, -508874.914; 2025-05-01, 583580.159; 2025-06-01, -816582.738; 2025-07-01, 1297434.427 … (+5 rows) | |
| global_manager | month, change_usd → 2, 289483.51; 3, 2335943.69; 4, -3126210.87; 5, 1029188.49; 6, 663314.53; 7, 4303484.74 … (+5 rows) | NO: values differ |
| | second: month, revenue_change → 2025-02-01, 289483.5065; 2025-03-01, 2335943.6895; 2025-04-01, -3126210.874; 2025-05-01, 1029188.489; 2025-06-01, 663314.53; 2025-07-01, 4303484.7385 … (+5 rows) | |

**Disagreement: owner to adjudicate.**

## S-A-062: How many customers spent more than 500,000 USD in completed orders across 2024 and 2025?

Reference:
```sql
SELECT count(*) AS customers FROM (SELECT o.customer_id FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' GROUP BY o.customer_id HAVING sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) > 500000) t
```
Second annotator:
```sql
WITH customer_revenue AS (
    SELECT o.customer_id,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS total_revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2024-01-01'
      AND o.ordered_on <= DATE '2025-12-31'
    GROUP BY o.customer_id
)
SELECT COUNT(*) AS customer_count
FROM customer_revenue
WHERE total_revenue > 500000
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 62 | yes |
| apac_analyst | customers → 64 | yes |
| global_manager | customers → 173 | yes |

## S-A-063: Which sales rep had the highest share of cancelled orders among the orders they handled across 2024 and 2025? Give the name and the share in percent to one decimal place.

Reference:
```sql
SELECT r.name, round(100.0 * count(*) FILTER (WHERE o.status = 'cancelled') / count(*), 1) AS cancelled_pct FROM sales.orders o JOIN sales.sales_reps r ON r.rep_id = o.rep_id GROUP BY r.rep_id, r.name ORDER BY cancelled_pct DESC LIMIT 1
```
Second annotator:
```sql
WITH rep_stats AS (
    SELECT
        sr.rep_id,
        sr.name,
        COUNT(o.order_id) AS total_orders,
        COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancelled_orders
    FROM sales.sales_reps sr
    JOIN sales.orders o ON o.rep_id = sr.rep_id
    WHERE o.ordered_on >= DATE '2024-01-01'
      AND o.ordered_on <= DATE '2025-12-31'
    GROUP BY sr.rep_id, sr.name
)
SELECT
    name,
    ROUND(100.0 * cancelled_orders / NULLIF(total_orders, 0), 1) AS cancelled_share_pct
FROM rep_stats
WHERE total_orders > 0
ORDER BY cancelled_share_pct DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, cancelled_pct → Casey Iyer, 9.3 | yes |
| apac_analyst | name, cancelled_pct → Kai Tan, 13.4 | yes |
| global_manager | name, cancelled_pct → Kai Tan, 13.4 | yes |

## S-A-064: What was the total quantity ordered for each product in 2025 completed orders, for products in the Accessories category?

Reference:
```sql
SELECT p.name, sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND p.category = 'Accessories' GROUP BY p.product_id, p.name
```
Second annotator:
```sql
WITH completed_2025 AS (
    SELECT order_id
    FROM sales.orders
    WHERE status = 'completed'
      AND ordered_on >= DATE '2025-01-01'
      AND ordered_on < DATE '2026-01-01'
)
SELECT p.name AS product,
       SUM(ol.quantity) AS total_quantity
FROM sales.order_lines ol
JOIN completed_2025 c ON ol.order_id = c.order_id
JOIN sales.products p ON ol.product_id = p.product_id
WHERE p.category = 'Accessories'
GROUP BY p.name
ORDER BY total_quantity DESC
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, units → Cable Kit, 460; Power Supply, 441; Mounting Rail, 214; Keyboard, 491; Docking Station, 359; Monitor 27in, 459 … (+4 rows) | yes |
| apac_analyst | name, units → Cable Kit, 283; Power Supply, 293; Mounting Rail, 394; Keyboard, 431; Docking Station, 490; Monitor 27in, 363 … (+4 rows) | yes |
| global_manager | name, units → Cable Kit, 928; Power Supply, 1061; Mounting Rail, 861; Keyboard, 1239; Docking Station, 1141; Monitor 27in, 1098 … (+4 rows) | yes |

## S-A-065: What was the average unit price paid, before discounts, as a percentage of list price, across all order lines? Round to two decimal places.

Reference:
```sql
SELECT round(100 * avg(l.unit_price / p.list_price), 2) AS avg_price_pct_of_list FROM sales.order_lines l JOIN sales.products p USING (product_id)
```
Second annotator:
```sql
SELECT round(avg(ol.unit_price / p.list_price * 100), 2) AS avg_unit_price_pct_of_list
FROM sales.order_lines ol
JOIN sales.products p ON ol.product_id = p.product_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_price_pct_of_list → 92.6 | yes |
| apac_analyst | avg_price_pct_of_list → 92.43 | yes |
| global_manager | avg_price_pct_of_list → 92.5 | yes |

## S-A-066: How many customer accounts were opened in each year?

Reference:
```sql
SELECT extract(year FROM created_on)::int AS year, count(*) AS customers FROM sales.customers GROUP BY 1
```
Second annotator:
```sql
SELECT
    EXTRACT(YEAR FROM created_on)::int AS year,
    COUNT(*) AS customer_accounts_opened
FROM sales.customers
GROUP BY year
ORDER BY year
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | year, customers → 2022, 25; 2025, 28; 2024, 27; 2023, 27 | yes |
| apac_analyst | year, customers → 2022, 26; 2025, 31; 2024, 28; 2023, 20 | yes |
| global_manager | year, customers → 2022, 71; 2025, 80; 2024, 84; 2023, 65 | yes |

## S-A-067: What was revenue in 2025 from customers whose accounts were opened in 2025?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND c.created_on >= DATE '2025-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.customers c
JOIN sales.orders o ON o.customer_id = c.customer_id
JOIN sales.order_lines ol ON ol.order_id = o.order_id
WHERE c.created_on >= DATE '2025-01-01'
  AND c.created_on < DATE '2026-01-01'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
  AND o.status = 'completed'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → 15611078.42 | yes |
| apac_analyst | revenue → 13850072.86 | yes |
| global_manager | revenue → 41917696.71 | yes |

## S-A-068: How many orders contained at least one Hardware product, across all statuses and years?

Reference:
```sql
SELECT count(DISTINCT l.order_id) AS orders FROM sales.order_lines l JOIN sales.products p USING (product_id) WHERE p.category = 'Hardware'
```
Second annotator:
```sql
SELECT COUNT(DISTINCT o.order_id) AS order_count
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
JOIN sales.products p ON p.product_id = ol.product_id
WHERE p.category = 'Hardware'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 557 | yes |
| apac_analyst | orders → 545 | yes |
| global_manager | orders → 1528 | yes |

## S-A-069: What is the total pay, base salary plus commission, for each year?

Reference:
```sql
SELECT year, sum(base_salary + commission) AS total_pay FROM sales.rep_compensation GROUP BY year
```
Second annotator:
```sql
SELECT
    year,
    SUM(base_salary + commission) AS total_pay
FROM sales.rep_compensation
GROUP BY year
ORDER BY year
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | year, total_pay → 2025, 2362424.7; 2024, 2442387.79 | yes |

## S-A-070: Which 3 customers had the most units returned across 2024 and 2025, and how many units each?

Reference:
```sql
SELECT c.name, sum(r.quantity) AS units_returned FROM sales.returns r JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id GROUP BY c.customer_id, c.name ORDER BY units_returned DESC LIMIT 3
```
Second annotator:
```sql
WITH customer_returns AS (
    SELECT
        c.customer_id,
        c.name,
        SUM(r.quantity) AS total_returned_units
    FROM sales.returns r
    JOIN sales.order_lines ol
        ON r.order_id = ol.order_id
        AND r.line_no = ol.line_no
    JOIN sales.orders o
        ON ol.order_id = o.order_id
    JOIN sales.customers c
        ON o.customer_id = c.customer_id
    WHERE r.returned_on >= DATE '2024-01-01'
      AND r.returned_on < DATE '2026-01-01'
    GROUP BY c.customer_id, c.name
)
SELECT
    customer_id,
    name,
    total_returned_units
FROM customer_returns
ORDER BY total_returned_units DESC
LIMIT 3
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, units_returned → Iron Partners Pty, 27; Clear Energy SA, 27; Iron Partners Ltd, 24 | yes |
| apac_analyst | name, units_returned → Bright Systems Ltd, 56; Maple Foods Inc, 39; Coral Studios GmbH, 37 | yes |
| global_manager | name, units_returned → Bright Systems Ltd, 56; Maple Foods Inc, 39; Coral Studios GmbH, 37 | yes |

## S-A-071: What was the net revenue of 2025 after subtracting the value of units returned in 2025? Value returned units at the order line's net unit price.

Reference:
```sql
SELECT round((SELECT sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01') - (SELECT sum(r.quantity * l.unit_price * (1 - l.discount_pct / 100)) FROM sales.returns r JOIN sales.order_lines l ON l.order_id = r.order_id AND l.line_no = r.line_no WHERE r.returned_on >= DATE '2025-01-01' AND r.returned_on < DATE '2026-01-01'), 2) AS net_of_returns
```
Second annotator:
```sql
WITH rev AS (
    SELECT SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
),
ret AS (
    SELECT SUM(r.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS returned_value
    FROM sales.returns r
    JOIN sales.order_lines ol ON ol.order_id = r.order_id AND ol.line_no = r.line_no
    JOIN sales.orders o ON o.order_id = ol.order_id
    WHERE r.returned_on >= DATE '2025-01-01'
      AND r.returned_on < DATE '2026-01-01'
      AND o.status = 'completed'
)
SELECT (rev.revenue - COALESCE(ret.returned_value, 0)) AS net_revenue
FROM rev, ret
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | net_of_returns → 43042109.56 | yes |
| apac_analyst | net_of_returns → 41423490.74 | yes |
| global_manager | net_of_returns → 118881943.98 | yes |

## S-A-072: How many distinct products did each customer segment buy in completed 2025 orders?

Reference:
```sql
SELECT c.segment, count(DISTINCT l.product_id) AS products FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.segment
```
Second annotator:
```sql
SELECT
    c.segment,
    COUNT(DISTINCT ol.product_id) AS distinct_product_count
FROM sales.orders o
JOIN sales.customers c ON o.customer_id = c.customer_id
JOIN sales.order_lines ol ON o.order_id = ol.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
GROUP BY c.segment
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | segment, products → Consumer, 40; Enterprise, 40; SMB, 40 | yes |
| apac_analyst | segment, products → Consumer, 40; Enterprise, 40; SMB, 40 | yes |
| global_manager | segment, products → Consumer, 40; Enterprise, 40; SMB, 40 | yes |

## S-A-073: On which weekday were the most orders placed across 2024 and 2025, and how many? Name the weekday in English.

Reference:
```sql
SELECT trim(to_char(ordered_on, 'Day')) AS weekday, count(*) AS orders FROM sales.orders GROUP BY 1 ORDER BY orders DESC LIMIT 1
```
Second annotator:
```sql
WITH filtered AS (
    SELECT ordered_on
    FROM sales.orders
    WHERE ordered_on >= DATE '2024-01-01'
      AND ordered_on < DATE '2026-01-01'
)
SELECT trim(to_char(ordered_on, 'Day')) AS weekday,
       COUNT(*) AS order_count
FROM filtered
GROUP BY weekday
ORDER BY order_count DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | weekday, orders → Monday, 171 | yes |
| apac_analyst | weekday, orders → Tuesday, 163 | yes |
| global_manager | weekday, orders → Monday, 458 | yes |

## S-A-074: What was the first order date and the last order date in the data?

Reference:
```sql
SELECT min(ordered_on) AS first_order, max(ordered_on) AS last_order FROM sales.orders
```
Second annotator:
```sql
SELECT
    MIN(ordered_on) AS first_order_date,
    MAX(ordered_on) AS last_order_date
FROM sales.orders
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | first_order, last_order → 2024-01-01, 2025-12-31 | yes |
| apac_analyst | first_order, last_order → 2024-01-01, 2025-12-31 | yes |
| global_manager | first_order, last_order → 2024-01-01, 2025-12-31 | yes |
