# Batch sales-01: owner review

25 questions, 24 agree on every persona, 1 to adjudicate.

## S-A-001: How many customers are there?

Reference:
```sql
SELECT count(*) AS customers FROM sales.customers
```
Second annotator:
```sql
SELECT COUNT(*) FROM sales.customers
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 107 | yes |
| apac_analyst | customers → 105 | yes |
| global_manager | customers → 300 | yes |

## S-A-002: How many orders were placed in 2025, whatever their status?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders WHERE ordered_on >= DATE '2025-01-01' AND ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*) AS order_count
FROM sales.orders
WHERE ordered_on >= DATE '2025-01-01' AND ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 742 | yes |
| apac_analyst | orders → 723 | yes |
| global_manager | orders → 2065 | yes |

## S-A-003: How many completed orders were there in 2024?

Reference:
```sql
SELECT count(*) AS completed_orders FROM sales.orders WHERE status = 'completed' AND ordered_on >= DATE '2024-01-01' AND ordered_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT count(*) AS completed_orders_2024
FROM sales.orders
WHERE status = 'completed'
  AND ordered_on >= DATE '2024-01-01'
  AND ordered_on < DATE '2025-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | completed_orders → 340 | yes |
| apac_analyst | completed_orders → 311 | yes |
| global_manager | completed_orders → 853 | yes |

## S-A-004: What was total revenue in 2025?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS total_revenue
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → 44072021.08 | yes |
| apac_analyst | revenue → 43182863.5 | yes |
| global_manager | revenue → 122521671.79 | yes |

## S-A-005: What was revenue by product category in 2025, highest first?

Reference:
```sql
SELECT p.category, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY p.category ORDER BY revenue DESC
```
Second annotator:
```sql
WITH completed_orders AS (
    SELECT order_id
    FROM sales.orders
    WHERE status = 'completed'
      AND ordered_on >= DATE '2025-01-01'
      AND ordered_on < DATE '2026-01-01'
)
SELECT p.category,
       SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.order_lines ol
JOIN completed_orders co ON ol.order_id = co.order_id
JOIN sales.products p ON ol.product_id = p.product_id
GROUP BY p.category
ORDER BY revenue DESC
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, revenue → Hardware, 26209063.75; Software, 8969969.28; Services, 8112359.54; Accessories, 780628.51 | yes |
| apac_analyst | category, revenue → Hardware, 24542643.69; Software, 9465646.3; Services, 8315767.54; Accessories, 858805.98 | yes |
| global_manager | category, revenue → Hardware, 71511891.12; Software, 25272238.47; Services, 23559658.19; Accessories, 2177884.01 | yes |

## S-A-006: How many customers are in each segment?

Reference:
```sql
SELECT segment, count(*) AS customers FROM sales.customers GROUP BY segment
```
Second annotator:
```sql
SELECT segment, COUNT(*) AS customer_count
FROM sales.customers
GROUP BY segment
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | segment, customers → Enterprise, 19; Consumer, 38; SMB, 50 | yes |
| apac_analyst | segment, customers → Enterprise, 26; Consumer, 37; SMB, 42 | yes |
| global_manager | segment, customers → Enterprise, 69; Consumer, 97; SMB, 134 | yes |

## S-A-007: What percentage of orders placed in 2025 were cancelled? Round to one decimal place.

Reference:
```sql
SELECT round(100.0 * count(*) FILTER (WHERE status = 'cancelled') / count(*), 1) AS cancelled_pct FROM sales.orders WHERE ordered_on >= DATE '2025-01-01' AND ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT round(100.0 * sum(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) / count(*), 1) AS cancelled_percentage
FROM sales.orders
WHERE ordered_on >= DATE '2025-01-01' AND ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cancelled_pct → 7.1 | yes |
| apac_analyst | cancelled_pct → 8.4 | yes |
| global_manager | cancelled_pct → 8.3 | yes |

## S-A-008: Who are the top 5 customers by total revenue across 2024 and 2025, and how much revenue did each bring?

Reference:
```sql
SELECT c.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' GROUP BY c.customer_id, c.name ORDER BY revenue DESC LIMIT 5
```
Second annotator:
```sql
WITH completed_orders AS (
    SELECT order_id
    FROM sales.orders
    WHERE status = 'completed'
      AND ordered_on >= DATE '2024-01-01'
      AND ordered_on <= DATE '2025-12-31'
),
line_revenue AS (
    SELECT ol.order_id,
           ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100.0) AS net_amount
    FROM sales.order_lines ol
    JOIN completed_orders co ON ol.order_id = co.order_id
)
SELECT c.name AS customer_name,
       SUM(lr.net_amount) AS total_revenue
FROM line_revenue lr
JOIN sales.orders o ON lr.order_id = o.order_id
JOIN sales.customers c ON o.customer_id = c.customer_id
GROUP BY c.name
ORDER BY total_revenue DESC
LIMIT 5
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, revenue → Nova Retail Inc, 1520102.67; Clear Labs Pty, 1431008.49; Granite Foods LLC, 1405428.8; Delta Retail LLC, 1386939.4; Delta Logistics SA, 1262874.89 | yes |
| apac_analyst | name, revenue → Cedar Labs Ltd, 1398153.79; Coral Studios GmbH, 1385343.29; Summit Foods Pty, 1342414.92; Summit Works Co, 1239116.28; Bright Systems Ltd, 1228184.95 | yes |
| global_manager | name, revenue → Nova Retail Inc, 1520102.67; Clear Labs Pty, 1431008.49; Granite Foods LLC, 1405428.8; Cedar Labs Ltd, 1398153.79; Delta Retail LLC, 1386939.4 | yes |

## S-A-009: What was revenue for each month of 2025, in month order?

Reference:
```sql
SELECT extract(month FROM o.ordered_on)::int AS month, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1 ORDER BY 1
```
Second annotator:
```sql
SELECT
    EXTRACT(MONTH FROM o.ordered_on)::int AS month,
    SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
GROUP BY month
ORDER BY month
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | month, revenue → 1, 2353034.52; 2, 2664044.34; 3, 3438073.35; 4, 2244417.8; 5, 2468160.86; 6, 2681708.6 … (+6 rows) | yes |
| apac_analyst | month, revenue → 1, 2177085.78; 2, 2705256.06; 3, 3575591.1; 4, 3066716.18; 5, 3650296.34; 6, 2833713.6 … (+6 rows) | yes |
| global_manager | month, revenue → 1, 6897397.31; 2, 7186880.82; 3, 9522824.51; 4, 6396613.64; 5, 7425802.13; 6, 8089116.66 … (+6 rows) | yes |

## S-A-010: What was the average order value of completed orders in 2025?

Reference:
```sql
SELECT round(avg(t.total), 2) AS avg_order_value FROM (SELECT o.order_id, sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS total FROM sales.orders o JOIN sales.order_lines l USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.order_id) t
```
Second annotator:
```sql
SELECT avg(order_total) AS average_order_value
FROM (
    SELECT o.order_id,
           sum(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS order_total
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY o.order_id
) sub
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_order_value → 71198.74 | yes |
| apac_analyst | avg_order_value → 71851.69 | yes |
| global_manager | avg_order_value → 71734.0 | yes |

## S-A-011: Which product sold the most units in completed orders in 2025, and how many units?

Reference:
```sql
SELECT p.name, sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY p.product_id, p.name ORDER BY units DESC LIMIT 1
```
Second annotator:
```sql
WITH product_units AS (
    SELECT p.name AS product_name,
           SUM(ol.quantity) AS total_units
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    JOIN sales.products p ON p.product_id = ol.product_id
    WHERE o.status = 'completed'
      AND EXTRACT(YEAR FROM o.ordered_on) = 2025
    GROUP BY p.name
)
SELECT product_name, total_units
FROM product_units
ORDER BY total_units DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, units → Edge Server, 600 | yes |
| apac_analyst | name, units → Database License, 632 | yes |
| global_manager | name, units → Design Studio, 1464 | yes |

## S-A-012: How many returns were there for each return reason?

Reference:
```sql
SELECT reason, count(*) AS returns FROM sales.returns GROUP BY reason
```
Second annotator:
```sql
SELECT
    reason,
    COUNT(*) AS returns_count
FROM sales.returns
GROUP BY reason
ORDER BY reason
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | reason, returns → wrong_item, 26; not_needed, 38; late_delivery, 26; damaged, 32 | yes |
| apac_analyst | reason, returns → not_needed, 31; wrong_item, 28; late_delivery, 31; damaged, 25 | yes |
| global_manager | reason, returns → not_needed, 91; wrong_item, 83; late_delivery, 76; damaged, 75 | yes |

## S-A-013: How many units were returned in 2025?

Reference:
```sql
SELECT sum(quantity) AS units_returned FROM sales.returns WHERE returned_on >= DATE '2025-01-01' AND returned_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT SUM(quantity) AS units_returned
FROM sales.returns
WHERE returned_on >= DATE '2025-01-01' AND returned_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | units_returned → 416 | yes |
| apac_analyst | units_returned → 545 | yes |
| global_manager | units_returned → 1273 | yes |

## S-A-014: Across 2024 and 2025, what percentage of units sold in completed orders were returned? Round to two decimal places.

Reference:
```sql
SELECT round(100.0 * (SELECT sum(r.quantity) FROM sales.returns r JOIN sales.orders o USING (order_id) WHERE o.status = 'completed') / (SELECT sum(l.quantity) FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed'), 2) AS return_rate_pct
```
Second annotator:
```sql
WITH sold AS (
    SELECT SUM(ol.quantity) AS total_sold
    FROM sales.order_lines ol
    JOIN sales.orders o ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2024-01-01'
      AND o.ordered_on <= DATE '2025-12-31'
),
returned AS (
    SELECT SUM(r.quantity) AS total_returned
    FROM sales.returns r
    JOIN sales.order_lines ol ON r.order_id = ol.order_id AND r.line_no = ol.line_no
    JOIN sales.orders o ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2024-01-01'
      AND o.ordered_on <= DATE '2025-12-31'
      AND r.returned_on >= DATE '2024-01-01'
      AND r.returned_on <= DATE '2025-12-31'
)
SELECT ROUND(100.0 * COALESCE(r.total_returned, 0) / NULLIF(s.total_sold, 0), 2) AS return_pct
FROM sold s
CROSS JOIN returned r
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | return_rate_pct → 2.6 | yes |
| apac_analyst | return_rate_pct → 2.85 | yes |
| global_manager | return_rate_pct → 2.59 | yes |

## S-A-015: What was revenue by customer country in 2025, highest first?

Reference:
```sql
SELECT co.name AS country, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id JOIN sales.countries co ON co.country_code = c.country_code WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY co.name ORDER BY revenue DESC
```
Second annotator:
```sql
SELECT
    c.name AS country,
    SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
JOIN sales.customers cu ON cu.customer_id = o.customer_id
JOIN sales.countries c ON c.country_code = cu.country_code
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
GROUP BY c.name
ORDER BY revenue DESC
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | country, revenue → United Arab Emirates, 12389350.52; Germany, 12320489.81; France, 11152422.18; United Kingdom, 8209758.57 | yes |
| apac_analyst | country, revenue → Japan, 13721628.18; India, 11038088.21; Singapore, 10049257.96; Australia, 8373889.15 | yes |
| global_manager | country, revenue → Brazil, 13823584.87; Japan, 13721628.18; United Arab Emirates, 12389350.52; Canada, 12338654.21; Germany, 12320489.81; France, 11152422.18 … (+5 rows) | yes |

## S-A-016: Which sales rep brought in the most revenue in 2025, and how much?

Reference:
```sql
SELECT r.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.sales_reps r ON r.rep_id = o.rep_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY r.rep_id, r.name ORDER BY revenue DESC LIMIT 1
```
Second annotator:
```sql
WITH rep_revenue AS (
    SELECT o.rep_id,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS total_revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY o.rep_id
)
SELECT sr.name AS sales_rep,
       rr.total_revenue
FROM rep_revenue rr
JOIN sales.sales_reps sr ON sr.rep_id = rr.rep_id
ORDER BY rr.total_revenue DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, revenue → Avery Haddad, 7743687.28 | yes |
| apac_analyst | name, revenue → Quinn Iyer, 6832289.9 | yes |
| global_manager | name, revenue → Avery Haddad, 7743687.28 | yes |

## S-A-017: How many sales reps work in each region?

Reference:
```sql
SELECT region_id AS region, count(*) AS reps FROM sales.sales_reps GROUP BY region_id
```
Second annotator:
```sql
SELECT r.name AS region,
       COUNT(sr.rep_id) AS sales_rep_count
FROM sales.regions r
LEFT JOIN sales.sales_reps sr ON sr.region_id = r.region_id
GROUP BY r.region_id, r.name
ORDER BY r.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | region, reps → EMEA, 8 | NO: 3 rows vs 1 |
| | second: region, sales_rep_count → Americas, 0; Asia Pacific, 0; Europe, Middle East and Africa, 8 | |
| apac_analyst | region, reps → APAC, 8 | NO: 3 rows vs 1 |
| | second: region, sales_rep_count → Americas, 0; Asia Pacific, 8; Europe, Middle East and Africa, 0 | |
| global_manager | region, reps → APAC, 8; EMEA, 8; AMER, 8 | NO: values differ |
| | second: region, sales_rep_count → Americas, 8; Asia Pacific, 8; Europe, Middle East and Africa, 8 | |

**Disagreement: owner to adjudicate.**

## S-A-018: How many customer accounts were opened in 2025?

Reference:
```sql
SELECT count(*) AS new_customers FROM sales.customers WHERE created_on >= DATE '2025-01-01' AND created_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*) AS customer_accounts_opened_2025
FROM sales.customers
WHERE created_on >= DATE '2025-01-01' AND created_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | new_customers → 28 | yes |
| apac_analyst | new_customers → 31 | yes |
| global_manager | new_customers → 80 | yes |

## S-A-019: What was the average line discount, in percent, on completed orders in 2025? Round to two decimal places.

Reference:
```sql
SELECT round(avg(l.discount_pct), 2) AS avg_discount_pct FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT ROUND(AVG(ol.discount_pct), 2) AS avg_discount_pct
FROM sales.order_lines ol
JOIN sales.orders o ON o.order_id = ol.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_discount_pct → 4.76 | yes |
| apac_analyst | avg_discount_pct → 5.06 | yes |
| global_manager | avg_discount_pct → 4.94 | yes |

## S-A-020: By what percentage did revenue grow from 2024 to 2025? Round to one decimal place.

Reference:
```sql
WITH y AS (SELECT extract(year FROM o.ordered_on)::int AS year, sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' GROUP BY 1) SELECT round(100 * ((SELECT revenue FROM y WHERE year = 2025) / (SELECT revenue FROM y WHERE year = 2024) - 1), 1) AS growth_pct
```
Second annotator:
```sql
WITH line_rev AS (
    SELECT
        EXTRACT(YEAR FROM o.ordered_on)::int AS yr,
        ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100) AS net_amount
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND EXTRACT(YEAR FROM o.ordered_on) IN (2024, 2025)
)
SELECT round(
           (sum(CASE WHEN yr = 2025 THEN net_amount ELSE 0 END) -
            sum(CASE WHEN yr = 2024 THEN net_amount ELSE 0 END))
           / nullif(sum(CASE WHEN yr = 2024 THEN net_amount ELSE 0 END), 0) * 100
       , 1) AS growth_pct
FROM line_rev
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | growth_pct → 85.6 | yes |
| apac_analyst | growth_pct → 116.5 | yes |
| global_manager | growth_pct → 110.0 | yes |

## S-A-021: How many customers placed no completed order in 2025?

Reference:
```sql
SELECT count(*) AS customers FROM sales.customers c WHERE NOT EXISTS (SELECT 1 FROM sales.orders o WHERE o.customer_id = c.customer_id AND o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01')
```
Second annotator:
```sql
SELECT count(*)
FROM sales.customers c
WHERE NOT EXISTS (
    SELECT 1
    FROM sales.orders o
    WHERE o.customer_id = c.customer_id
      AND o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
)
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 2 | yes |
| apac_analyst | customers → 1 | yes |
| global_manager | customers → 3 | yes |

## S-A-022: How many orders are still pending?

Reference:
```sql
SELECT count(*) AS pending_orders FROM sales.orders WHERE status = 'pending'
```
Second annotator:
```sql
SELECT count(*) AS pending_orders
FROM sales.orders
WHERE status = 'pending'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | pending_orders → 70 | yes |
| apac_analyst | pending_orders → 61 | yes |
| global_manager | pending_orders → 185 | yes |

## S-A-023: Which products have a list price above 5,000 USD? Give the name and list price.

Reference:
```sql
SELECT name, list_price FROM sales.products WHERE list_price > 5000
```
Second annotator:
```sql
SELECT name, list_price
FROM sales.products
WHERE list_price > 5000
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, list_price → Edge Server, 9254.29; Storage Array, 10851.79; Network Switch, 8135.8; Workstation, 9903.71; Router, 10355.21; Firewall Appliance, 5152.69 … (+1 rows) | yes |
| apac_analyst | name, list_price → Edge Server, 9254.29; Storage Array, 10851.79; Network Switch, 8135.8; Workstation, 9903.71; Router, 10355.21; Firewall Appliance, 5152.69 … (+1 rows) | yes |
| global_manager | name, list_price → Edge Server, 9254.29; Storage Array, 10851.79; Network Switch, 8135.8; Workstation, 9903.71; Router, 10355.21; Firewall Appliance, 5152.69 … (+1 rows) | yes |

## S-A-024: What was the total commission paid to sales reps in 2025?

Reference:
```sql
SELECT sum(commission) AS total_commission FROM sales.rep_compensation WHERE year = 2025
```
Second annotator:
```sql
SELECT sum(commission) AS total_commission
FROM sales.rep_compensation
WHERE year = 2025
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | total_commission → 375528.12 | yes |

## S-A-025: What was revenue by customer segment for each year, 2024 and 2025?

Reference:
```sql
SELECT c.segment, extract(year FROM o.ordered_on)::int AS year, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' GROUP BY c.segment, 2
```
Second annotator:
```sql
WITH completed_lines AS (
    SELECT
        EXTRACT(YEAR FROM o.ordered_on)::int AS year,
        c.segment,
        ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100) AS net_amount
    FROM sales.orders o
    JOIN sales.customers c ON c.customer_id = o.customer_id
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND EXTRACT(YEAR FROM o.ordered_on) IN (2024, 2025)
)
SELECT
    year,
    segment,
    SUM(net_amount) AS revenue
FROM completed_lines
GROUP BY year, segment
ORDER BY year, segment
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | segment, year, revenue → Consumer, 2025, 18398374.94; Enterprise, 2024, 4261688.68; Consumer, 2024, 8117754.89; Enterprise, 2025, 6342653.67; SMB, 2024, 11369159.19; SMB, 2025, 19330992.47 | yes |
| apac_analyst | segment, year, revenue → Consumer, 2025, 14194903.44; Enterprise, 2024, 4355007.21; Consumer, 2024, 6787344.23; Enterprise, 2025, 10832125.93; SMB, 2024, 8803304.61; SMB, 2025, 18155834.13 | yes |
| global_manager | segment, year, revenue → Consumer, 2025, 41841857.63; Enterprise, 2024, 12503743.02; Consumer, 2024, 19088702.03; Enterprise, 2025, 25250984.73; SMB, 2024, 26751770.32; SMB, 2025, 55428829.43 | yes |
