# Batch sales-04: owner review

26 questions, 24 agree on every persona, 2 to adjudicate.

## S-A-075: What was revenue in the first half of 2025, January to June?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2025-07-01'
```
Second annotator:
```sql
SELECT
    SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.order_lines ol
JOIN sales.orders o ON ol.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on <= DATE '2025-06-30'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → 15849439.46 | yes |
| apac_analyst | revenue → 18008659.07 | yes |
| global_manager | revenue → 45518635.06 | yes |

## S-A-076: How many completed orders were placed in the last quarter of 2024?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o WHERE o.status = 'completed' AND o.ordered_on >= DATE '2024-10-01' AND o.ordered_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT COUNT(*)
FROM sales.orders
WHERE status = 'completed'
  AND ordered_on >= DATE '2024-10-01'
  AND ordered_on <= DATE '2024-12-31'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 105 | yes |
| apac_analyst | orders → 96 | yes |
| global_manager | orders → 265 | yes |

## S-A-077: How much revenue came from small and medium business customers in 2025?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND c.segment = 'SMB'
```
Second annotator:
```sql
SELECT
    SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.orders o
JOIN sales.customers c ON c.customer_id = o.customer_id
JOIN sales.order_lines ol ON ol.order_id = o.order_id
WHERE c.segment = 'SMB'
  AND o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → 19330992.47 | yes |
| apac_analyst | revenue → 18155834.13 | yes |
| global_manager | revenue → 55428829.43 | yes |

## S-A-078: How many products are in each category?

Reference:
```sql
SELECT category, count(*) AS products FROM sales.products GROUP BY category
```
Second annotator:
```sql
SELECT
    category,
    COUNT(*) AS product_count
FROM sales.products
GROUP BY category
ORDER BY category
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, products → Accessories, 10; Hardware, 10; Software, 10; Services, 10 | yes |
| apac_analyst | category, products → Accessories, 10; Hardware, 10; Software, 10; Services, 10 | yes |
| global_manager | category, products → Accessories, 10; Hardware, 10; Software, 10; Services, 10 | yes |

## S-A-079: What is the cheapest product by list price, and what does it cost?

Reference:
```sql
SELECT name, list_price FROM sales.products ORDER BY list_price LIMIT 1
```
Second annotator:
```sql
SELECT name, list_price
FROM sales.products
ORDER BY list_price ASC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, list_price → Adapter Pack, 133.99 | yes |
| apac_analyst | name, list_price → Adapter Pack, 133.99 | yes |
| global_manager | name, list_price → Adapter Pack, 133.99 | yes |

## S-A-080: How many orders did each sales rep handle in 2025, whatever their status? Give the rep name and the count.

Reference:
```sql
SELECT r.name, count(*) AS orders FROM sales.orders o JOIN sales.sales_reps r ON r.rep_id = o.rep_id WHERE o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY r.rep_id, r.name
```
Second annotator:
```sql
SELECT sr.name, COUNT(o.order_id) AS order_count
FROM sales.sales_reps sr
JOIN sales.orders o ON o.rep_id = sr.rep_id
WHERE EXTRACT(YEAR FROM o.ordered_on) = 2025
GROUP BY sr.name
ORDER BY sr.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, orders → Casey Iyer, 97; Lena Fischer, 93; Ravi Fischer, 88; Mei Tan, 94; Noor Martin, 93; Sam Okafor, 86 … (+2 rows) | yes |
| apac_analyst | name, orders → Mei Clarke, 95; Casey Novak, 88; Kai Tan, 88; Quinn Iyer, 92; Lena Okafor, 88; Lena Tan, 92 … (+2 rows) | yes |
| global_manager | name, orders → Rowan Larsen, 64; Mei Clarke, 95; Riley Tan, 90; Casey Iyer, 97; Lena Fischer, 93; Casey Novak, 88 … (+18 rows) | yes |

## S-A-081: What percentage of returned units were returned because of late delivery, across all returns? Round to one decimal place.

Reference:
```sql
SELECT round(100.0 * sum(quantity) FILTER (WHERE reason = 'late_delivery') / sum(quantity), 1) AS late_delivery_pct FROM sales.returns
```
Second annotator:
```sql
SELECT round(
    100.0 * sum(CASE WHEN reason = 'late_delivery' THEN quantity ELSE 0 END) 
    / nullif(sum(quantity), 0),
    1
) AS pct_late_delivery
FROM sales.returns
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | late_delivery_pct → 22.9 | yes |
| apac_analyst | late_delivery_pct → 29.9 | yes |
| global_manager | late_delivery_pct → 25.9 | yes |

## S-A-082: What was the average quantity per order line in completed orders? Round to two decimal places.

Reference:
```sql
SELECT round(avg(l.quantity), 2) AS avg_quantity FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed'
```
Second annotator:
```sql
SELECT round(avg(ol.quantity)::numeric, 2) AS avg_quantity
FROM sales.order_lines ol
JOIN sales.orders o ON ol.order_id = o.order_id
WHERE o.status = 'completed'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_quantity → 10.41 | yes |
| apac_analyst | avg_quantity → 10.52 | yes |
| global_manager | avg_quantity → 10.42 | yes |

## S-A-083: Which customer segment had the highest average order value for completed orders in 2025, and what was it? Round to two decimal places.

Reference:
```sql
SELECT segment, round(avg(total), 2) AS avg_order_value FROM (SELECT c.segment, o.order_id, sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS total FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.segment, o.order_id) t GROUP BY segment ORDER BY avg_order_value DESC LIMIT 1
```
Second annotator:
```sql
WITH order_totals AS (
    SELECT
        o.order_id,
        c.segment,
        SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS order_total
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    JOIN sales.customers c ON c.customer_id = o.customer_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY o.order_id, c.segment
),
segment_avg AS (
    SELECT
        segment,
        ROUND(AVG(order_total), 2) AS avg_order_value
    FROM order_totals
    GROUP BY segment
)
SELECT
    segment,
    avg_order_value
FROM segment_avg
ORDER BY avg_order_value DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | segment, avg_order_value → Consumer, 75403.18 | yes |
| apac_analyst | segment, avg_order_value → SMB, 75024.11 | yes |
| global_manager | segment, avg_order_value → Consumer, 73150.1 | yes |

## S-A-084: How many customers are in Germany?

Reference:
```sql
SELECT count(*) AS customers FROM sales.customers c JOIN sales.countries co USING (country_code) WHERE co.name = 'Germany'
```
Second annotator:
```sql
SELECT COUNT(*) FROM sales.customers WHERE country_code = 'DE'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 26 | yes |
| apac_analyst | customers → 0 | yes |
| global_manager | customers → 26 | yes |

## S-A-085: What was revenue from customers in Japan in 2025?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND c.country_code = 'JP'
```
Second annotator:
```sql
SELECT
    SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.customers c
JOIN sales.orders o ON o.customer_id = c.customer_id
JOIN sales.order_lines ol ON ol.order_id = o.order_id
WHERE c.country_code = 'JP'
  AND o.status = 'completed'
  AND EXTRACT(YEAR FROM o.ordered_on) = 2025
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → None | yes |
| apac_analyst | revenue → 13721628.18 | yes |
| global_manager | revenue → 13721628.18 | yes |

## S-A-086: How many different customers did each sales rep serve with completed orders across 2024 and 2025? Give the rep name and count.

Reference:
```sql
SELECT r.name, count(DISTINCT o.customer_id) AS customers FROM sales.orders o JOIN sales.sales_reps r ON r.rep_id = o.rep_id WHERE o.status = 'completed' GROUP BY r.rep_id, r.name
```
Second annotator:
```sql
SELECT
    sr.name,
    COUNT(DISTINCT o.customer_id) AS customer_count
FROM sales.sales_reps sr
JOIN sales.orders o ON sr.rep_id = o.rep_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2024-01-01'
  AND o.ordered_on <= DATE '2025-12-31'
GROUP BY sr.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, customers → Sam Okafor, 69; Mei Tan, 69; Alex Kowalski, 72; Lena Fischer, 63; Casey Iyer, 76; Ravi Fischer, 67 … (+2 rows) | yes |
| apac_analyst | name, customers → Lena Tan, 68; Casey Novak, 68; Lena Okafor, 65; Casey Fischer, 73; Quinn Iyer, 66; Kai Tan, 65 … (+2 rows) | yes |
| global_manager | name, customers → Sam Okafor, 69; Mei Tan, 69; Alex Kowalski, 72; Lena Fischer, 63; Casey Iyer, 76; Ravi Fischer, 67 … (+18 rows) | yes |

## S-A-087: What was the total commission for each year, and the average commission per rep in that year? Round the average to two decimal places.

Reference:
```sql
SELECT year, sum(commission) AS total_commission, round(avg(commission), 2) AS avg_commission FROM sales.rep_compensation GROUP BY year
```
Second annotator:
```sql
SELECT
    year,
    SUM(commission) AS total_commission,
    ROUND(AVG(commission), 2) AS avg_commission
FROM sales.rep_compensation
GROUP BY year
ORDER BY year
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | year, total_commission, avg_commission → 2025, 375528.12, 15647.01; 2024, 435537.65, 18147.4 | yes |

## S-A-088: How many orders have more than 3 lines?

Reference:
```sql
SELECT count(*) AS orders FROM (SELECT order_id FROM sales.order_lines GROUP BY order_id HAVING count(*) > 3) t
```
Second annotator:
```sql
SELECT count(*) AS order_count
FROM (
    SELECT order_id
    FROM sales.order_lines
    GROUP BY order_id
    HAVING count(*) > 3
) AS sub
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 269 | yes |
| apac_analyst | orders → 295 | yes |
| global_manager | orders → 773 | yes |

## S-A-089: What was the total revenue of Services products in 2024?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2024-01-01' AND o.ordered_on < DATE '2025-01-01' AND p.category = 'Services'
```
Second annotator:
```sql
WITH completed_orders_2024 AS (
    SELECT order_id
    FROM sales.orders
    WHERE status = 'completed'
      AND ordered_on >= DATE '2024-01-01'
      AND ordered_on <  DATE '2025-01-01'
),
service_lines AS (
    SELECT ol.quantity,
           ol.unit_price,
           ol.discount_pct
    FROM sales.order_lines ol
    JOIN completed_orders_2024 co ON ol.order_id = co.order_id
    JOIN sales.products p ON ol.product_id = p.product_id
    WHERE p.category = 'Services'
)
SELECT SUM(quantity * unit_price * (1 - discount_pct / 100)) AS total_revenue
FROM service_lines
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → 4180873.05 | yes |
| apac_analyst | revenue → 4176002.73 | yes |
| global_manager | revenue → 11074317.32 | yes |

## S-A-090: Which customer has the oldest account, and when was it opened? Give the name and date.

Reference:
```sql
SELECT name, created_on FROM sales.customers ORDER BY created_on LIMIT 1
```
Second annotator:
```sql
SELECT name, created_on
FROM sales.customers
ORDER BY created_on ASC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, created_on → Coral Foods SA, 2022-02-18 | yes |
| apac_analyst | name, created_on → Green Motors Pty, 2022-01-16 | yes |
| global_manager | name, created_on → Granite Studios Co, 2022-01-03 | yes |

## S-A-091: How many order lines have been returned at least once?

Reference:
```sql
SELECT count(*) AS lines FROM (SELECT DISTINCT order_id, line_no FROM sales.returns) t
```
Second annotator:
```sql
SELECT COUNT(DISTINCT (order_id, line_no)) AS returned_order_lines
FROM sales.returns
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | lines → 122 | yes |
| apac_analyst | lines → 115 | yes |
| global_manager | lines → 325 | yes |

## S-A-092: What was revenue per customer segment as a share of total 2025 revenue, in percent to one decimal place?

Reference:
```sql
SELECT c.segment, round(100 * sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) / sum(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100))) OVER (), 1) AS share_pct FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.segment
```
Second annotator:
```sql
WITH completed_2025 AS (
    SELECT o.order_id, c.segment
    FROM sales.orders o
    JOIN sales.customers c ON o.customer_id = c.customer_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
),
line_revenue AS (
    SELECT co.segment,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS segment_revenue
    FROM completed_2025 co
    JOIN sales.order_lines ol ON co.order_id = ol.order_id
    GROUP BY co.segment
),
total AS (
    SELECT SUM(segment_revenue) AS total_revenue FROM line_revenue
)
SELECT lr.segment,
       round(lr.segment_revenue / t.total_revenue * 100, 1) AS share_percent
FROM line_revenue lr
CROSS JOIN total t
ORDER BY lr.segment
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | segment, share_pct → Enterprise, 14.4; Consumer, 41.7; SMB, 43.9 | yes |
| apac_analyst | segment, share_pct → Consumer, 32.9; Enterprise, 25.1; SMB, 42.0 | yes |
| global_manager | segment, share_pct → Enterprise, 20.6; Consumer, 34.2; SMB, 45.2 | yes |

## S-A-093: In how many 2025 months did revenue exceed 5 million USD?

Reference:
```sql
SELECT count(*) AS months FROM (SELECT extract(month FROM o.ordered_on) AS m FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1 HAVING sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) > 5000000) t
```
Second annotator:
```sql
WITH monthly_rev AS (
    SELECT date_trunc('month', o.ordered_on)::date AS month_start,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY date_trunc('month', o.ordered_on)
)
SELECT COUNT(*) AS months_exceeding_5m
FROM monthly_rev
WHERE revenue > 5000000
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | months → 2 | yes |
| apac_analyst | months → 1 | yes |
| global_manager | months → 12 | yes |

## S-A-094: What is the total number of units sold, in completed orders, of the product named 'Edge Server'?

Reference:
```sql
SELECT sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND p.name = 'Edge Server'
```
Second annotator:
```sql
SELECT SUM(ol.quantity) AS total_units_sold
FROM sales.order_lines ol
JOIN sales.orders o ON o.order_id = ol.order_id
JOIN sales.products p ON p.product_id = ol.product_id
WHERE o.status = 'completed'
  AND p.name = 'Edge Server'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | units → 850 | yes |
| apac_analyst | units → 473 | yes |
| global_manager | units → 1722 | yes |

## S-A-095: How many sales reps have been with the company for more than 5 years as of 1 January 2026?

Reference:
```sql
SELECT count(*) AS reps FROM sales.sales_reps WHERE hired_on < DATE '2021-01-01'
```
Second annotator:
```sql
SELECT count(*) AS rep_count
FROM sales.sales_reps
WHERE hired_on < DATE '2021-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | reps → 3 | yes |
| apac_analyst | reps → 2 | yes |
| global_manager | reps → 6 | yes |

## S-A-096: What was the highest discount given on any order line, and how many lines received it?

Reference:
```sql
SELECT discount_pct, count(*) AS lines FROM sales.order_lines WHERE discount_pct = (SELECT max(discount_pct) FROM sales.order_lines) GROUP BY discount_pct
```
Second annotator:
```sql
WITH max_disc AS (
    SELECT max(discount_pct) AS highest_discount
    FROM sales.order_lines
)
SELECT md.highest_discount, COUNT(*) AS line_count
FROM sales.order_lines ol
JOIN max_disc md ON ol.discount_pct = md.highest_discount
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | discount_pct, lines → 15.0, 442 | NO: rows vs GroupingError |
| | second: refused (GroupingError) | |
| apac_analyst | discount_pct, lines → 15.0, 431 | NO: rows vs GroupingError |
| | second: refused (GroupingError) | |
| global_manager | discount_pct, lines → 15.0, 1216 | NO: rows vs GroupingError |
| | second: refused (GroupingError) | |

**Disagreement: owner to adjudicate.**

## S-A-097: How many pending orders were placed in December 2025?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders WHERE status = 'pending' AND ordered_on >= DATE '2025-12-01' AND ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*) AS pending_orders
FROM sales.orders
WHERE status = 'pending'
  AND ordered_on >= DATE '2025-12-01'
  AND ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 70 | yes |
| apac_analyst | orders → 61 | yes |
| global_manager | orders → 185 | yes |

## S-A-098: What was the revenue from each customer segment in each region in 2025?

Reference:
```sql
SELECT o.region_id AS region, c.segment, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.region_id, c.segment
```
Second annotator:
```sql
WITH completed_orders AS (
    SELECT o.order_id, o.customer_id, o.region_id
    FROM sales.orders o
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
),
order_revenue AS (
    SELECT co.customer_id, co.region_id,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM completed_orders co
    JOIN sales.order_lines ol ON ol.order_id = co.order_id
    GROUP BY co.customer_id, co.region_id
),
customer_segment AS (
    SELECT c.customer_id, c.segment, c.region_id
    FROM sales.customers c
)
SELECT cs.segment,
       r.name AS region,
       SUM(orv.revenue) AS total_revenue
FROM order_revenue orv
JOIN customer_segment cs ON cs.customer_id = orv.customer_id
JOIN sales.regions r ON r.region_id = orv.region_id
GROUP BY cs.segment, r.name
ORDER BY cs.segment, r.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | region, segment, revenue → EMEA, SMB, 19330992.47; EMEA, Enterprise, 6342653.67; EMEA, Consumer, 18398374.94 | NO: values differ |
| | second: segment, region, total_revenue → Consumer, Europe, Middle East and Africa, 18398374.9375; Enterprise, Europe, Middle East and Africa, 6342653.6745; SMB, Europe, Middle East and Africa, 19330992.4655 | |
| apac_analyst | region, segment, revenue → APAC, Consumer, 14194903.44; APAC, Enterprise, 10832125.93; APAC, SMB, 18155834.13 | NO: values differ |
| | second: segment, region, total_revenue → Consumer, Asia Pacific, 14194903.436; Enterprise, Asia Pacific, 10832125.934; SMB, Asia Pacific, 18155834.133 | |
| global_manager | region, segment, revenue → AMER, SMB, 17942002.84; APAC, Consumer, 14194903.44; AMER, Consumer, 9248579.26; EMEA, SMB, 19330992.47; APAC, Enterprise, 10832125.93; EMEA, Enterprise, 6342653.67 … (+3 rows) | NO: values differ |
| | second: segment, region, total_revenue → Consumer, Americas, 9248579.2585; Consumer, Asia Pacific, 14194903.436; Consumer, Europe, Middle East and Africa, 18398374.9375; Enterprise, Americas, 8076205.119; Enterprise, Asia Pacific, 10832125.934; Enterprise, Europe, Middle East and Africa, 6342653.6745 … (+3 rows) | |

**Disagreement: owner to adjudicate.**

## S-A-099: Which return reason accounted for the most returned units in 2025, and how many units?

Reference:
```sql
SELECT reason, sum(quantity) AS units FROM sales.returns WHERE returned_on >= DATE '2025-01-01' AND returned_on < DATE '2026-01-01' GROUP BY reason ORDER BY units DESC LIMIT 1
```
Second annotator:
```sql
WITH yearly_returns AS (
    SELECT
        reason,
        SUM(quantity) AS total_units
    FROM sales.returns
    WHERE EXTRACT(YEAR FROM returned_on) = 2025
    GROUP BY reason
)
SELECT
    reason,
    total_units
FROM yearly_returns
ORDER BY total_units DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | reason, units → damaged, 169 | yes |
| apac_analyst | reason, units → late_delivery, 186 | yes |
| global_manager | reason, units → not_needed, 380 | yes |

## S-A-100: What was the average number of days from customer account opening to that customer's first order, across customers who have ordered? Round to one decimal place.

Reference:
```sql
SELECT round(avg(first_order - created_on), 1) AS avg_days FROM (SELECT c.customer_id, c.created_on, min(o.ordered_on) AS first_order FROM sales.customers c JOIN sales.orders o ON o.customer_id = c.customer_id GROUP BY c.customer_id, c.created_on) t
```
Second annotator:
```sql
WITH first_orders AS (
    SELECT
        c.customer_id,
        c.created_on,
        MIN(o.ordered_on) AS first_order_date
    FROM sales.customers c
    JOIN sales.orders o ON o.customer_id = c.customer_id
    GROUP BY c.customer_id, c.created_on
)
SELECT round(AVG(first_order_date - created_on), 1) AS avg_days
FROM first_orders
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_days → 228.9 | yes |
| apac_analyst | avg_days → 230.8 | yes |
| global_manager | avg_days → 228.0 | yes |
