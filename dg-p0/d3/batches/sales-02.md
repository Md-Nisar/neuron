# Batch sales-02: owner review

25 questions, 24 agree on every persona, 1 to adjudicate.

## S-A-026: What was revenue in each quarter of 2025, in quarter order?

Reference:
```sql
SELECT extract(quarter FROM o.ordered_on)::int AS quarter, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1 ORDER BY 1
```
Second annotator:
```sql
WITH completed_lines AS (
    SELECT
        ol.quantity,
        ol.unit_price,
        ol.discount_pct,
        o.ordered_on
    FROM sales.order_lines ol
    JOIN sales.orders o ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
)
SELECT
    EXTRACT(QUARTER FROM ordered_on)::int AS quarter,
    SUM(quantity * unit_price * (1 - discount_pct / 100.0)) AS revenue
FROM completed_lines
GROUP BY quarter
ORDER BY quarter
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | quarter, revenue → 1, 8455152.2; 2, 7394287.26; 3, 12844944.93; 4, 15377636.68 | yes |
| apac_analyst | quarter, revenue → 1, 8457932.94; 2, 9550726.13; 3, 12189264.33; 4, 12984940.11 | yes |
| global_manager | quarter, revenue → 1, 23607102.65; 2, 21911532.42; 3, 36859772.88; 4, 40143263.85 | yes |

## S-A-027: How many orders were placed in each status in 2025?

Reference:
```sql
SELECT status, count(*) AS orders FROM sales.orders WHERE ordered_on >= DATE '2025-01-01' AND ordered_on < DATE '2026-01-01' GROUP BY status
```
Second annotator:
```sql
SELECT
    status,
    COUNT(*) AS order_count
FROM sales.orders
WHERE EXTRACT(YEAR FROM ordered_on) = 2025
GROUP BY status
ORDER BY status
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | status, orders → completed, 619; cancelled, 53; pending, 70 | yes |
| apac_analyst | status, orders → completed, 601; pending, 61; cancelled, 61 | yes |
| global_manager | status, orders → completed, 1708; pending, 185; cancelled, 172 | yes |

## S-A-028: How much revenue did each sales rep bring in during 2024? Give the rep name and revenue.

Reference:
```sql
SELECT r.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.sales_reps r ON r.rep_id = o.rep_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2024-01-01' AND o.ordered_on < DATE '2025-01-01' GROUP BY r.rep_id, r.name
```
Second annotator:
```sql
WITH rep_rev AS (
    SELECT
        sr.name AS rep_name,
        SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM sales.sales_reps sr
    JOIN sales.orders o ON o.rep_id = sr.rep_id
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2024-01-01'
      AND o.ordered_on < DATE '2025-01-01'
    GROUP BY sr.name
)
SELECT rep_name, revenue
FROM rep_rev
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, revenue → Casey Iyer, 2658985.75; Lena Fischer, 2054560.34; Ravi Fischer, 2522890.52; Mei Tan, 2924713.79; Noor Martin, 2804357.52; Sam Okafor, 2901280.33 … (+2 rows) | yes |
| apac_analyst | name, revenue → Mei Clarke, 2465122.15; Casey Novak, 2721054.64; Kai Tan, 2050688.38; Quinn Iyer, 3116467.54; Lena Okafor, 2016513.13; Lena Tan, 2418966.94 … (+2 rows) | yes |
| global_manager | name, revenue → Rowan Larsen, 1296841.41; Mei Clarke, 2465122.15; Riley Tan, 332594.22; Casey Iyer, 2658985.75; Lena Fischer, 2054560.34; Casey Novak, 2721054.64 … (+18 rows) | yes |

## S-A-029: What was the total value of discounts given on completed orders in 2025, in USD?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * l.discount_pct / 100), 2) AS discount_usd FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity * ol.unit_price * (ol.discount_pct / 100)) AS total_discount_usd
FROM sales.orders o
JOIN sales.order_lines ol ON o.order_id = ol.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | discount_usd → 2162417.89 | yes |
| apac_analyst | discount_usd → 2226676.47 | yes |
| global_manager | discount_usd → 6234728.59 | yes |

## S-A-030: What was the gross value, before discounts, of completed orders in 2025?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price), 2) AS gross_usd FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity * ol.unit_price) AS gross_value
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | gross_usd → 46234438.97 | yes |
| apac_analyst | gross_usd → 45409539.97 | yes |
| global_manager | gross_usd → 128756400.38 | yes |

## S-A-031: How many units were returned for each product category across 2024 and 2025?

Reference:
```sql
SELECT p.category, sum(r.quantity) AS units_returned FROM sales.returns r JOIN sales.order_lines l ON l.order_id = r.order_id AND l.line_no = r.line_no JOIN sales.products p ON p.product_id = l.product_id GROUP BY p.category
```
Second annotator:
```sql
SELECT
    p.category,
    SUM(r.quantity) AS returned_units
FROM sales.returns r
JOIN sales.order_lines ol
    ON r.order_id = ol.order_id
   AND r.line_no = ol.line_no
JOIN sales.products p
    ON ol.product_id = p.product_id
WHERE r.returned_on >= DATE '2024-01-01'
  AND r.returned_on <= DATE '2025-12-31'
GROUP BY p.category
ORDER BY p.category
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, units_returned → Accessories, 141; Hardware, 164; Services, 167; Software, 178 | yes |
| apac_analyst | category, units_returned → Accessories, 127; Hardware, 221; Services, 154; Software, 201 | yes |
| global_manager | category, units_returned → Accessories, 373; Hardware, 519; Services, 418; Software, 433 | yes |

## S-A-032: Which 3 products brought in the most revenue in 2025, and how much each?

Reference:
```sql
SELECT p.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY p.product_id, p.name ORDER BY revenue DESC LIMIT 3
```
Second annotator:
```sql
WITH completed_lines AS (
    SELECT
        ol.product_id,
        ol.quantity,
        ol.unit_price,
        ol.discount_pct
    FROM sales.order_lines ol
    JOIN sales.orders o ON o.order_id = ol.order_id
    WHERE o.status = 'completed'
      AND EXTRACT(YEAR FROM o.ordered_on) = 2025
)
SELECT
    p.name AS product_name,
    SUM(cl.quantity * cl.unit_price * (1 - cl.discount_pct / 100)) AS revenue
FROM completed_lines cl
JOIN sales.products p ON p.product_id = cl.product_id
GROUP BY p.name
ORDER BY revenue DESC
LIMIT 3
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, revenue → Edge Server, 4911152.93; Storage Array, 4039431.34; Workstation, 3470101.62 | yes |
| apac_analyst | name, revenue → Workstation, 3777333.65; Router, 3735052.8; Network Switch, 3504342.3 | yes |
| global_manager | name, revenue → Storage Array, 11556951.1; Router, 10987013.87; Workstation, 10342060.34 | yes |

## S-A-033: How many distinct customers placed at least one completed order in 2025?

Reference:
```sql
SELECT count(DISTINCT customer_id) AS active_customers FROM sales.orders WHERE status = 'completed' AND ordered_on >= DATE '2025-01-01' AND ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(DISTINCT o.customer_id)
FROM sales.orders o
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | active_customers → 105 | yes |
| apac_analyst | active_customers → 104 | yes |
| global_manager | active_customers → 297 | yes |

## S-A-034: What was the average number of lines per order, across all orders? Round to two decimal places.

Reference:
```sql
SELECT round(count(*)::numeric / count(DISTINCT order_id), 2) AS avg_lines FROM sales.order_lines
```
Second annotator:
```sql
SELECT ROUND(
    (SELECT COUNT(*) FROM sales.order_lines)::numeric /
    NULLIF((SELECT COUNT(*) FROM sales.orders), 0),
    2
) AS avg_lines_per_order
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_lines → 2.51 | yes |
| apac_analyst | avg_lines → 2.54 | yes |
| global_manager | avg_lines → 2.52 | yes |

## S-A-035: How many customers are there in each country?

Reference:
```sql
SELECT co.name AS country, count(*) AS customers FROM sales.customers c JOIN sales.countries co USING (country_code) GROUP BY co.name
```
Second annotator:
```sql
SELECT
    c.name AS country,
    COUNT(cu.customer_id) AS customer_count
FROM sales.countries c
LEFT JOIN sales.customers cu ON cu.country_code = c.country_code
GROUP BY c.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | country, customers → United Kingdom, 24; Germany, 26; France, 29; United Arab Emirates, 28 | NO: 11 rows vs 4 |
| | second: country, customer_count → Singapore, 0; France, 29; United States, 0; Australia, 0; United Arab Emirates, 28; United Kingdom, 24 … (+5 rows) | |
| apac_analyst | country, customers → Singapore, 25; India, 33; Japan, 25; Australia, 22 | NO: 11 rows vs 4 |
| | second: country, customer_count → Singapore, 25; France, 0; United States, 0; Australia, 22; United Arab Emirates, 0; United Kingdom, 0 … (+5 rows) | |
| global_manager | country, customers → United Kingdom, 24; Germany, 26; Singapore, 25; Canada, 33; India, 33; France, 29 … (+5 rows) | yes |

**Disagreement: owner to adjudicate.**

## S-A-036: What was the revenue from Enterprise customers in 2025?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND c.segment = 'Enterprise' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.orders o
JOIN sales.customers c ON o.customer_id = c.customer_id
JOIN sales.order_lines ol ON o.order_id = ol.order_id
WHERE o.status = 'completed'
  AND c.segment = 'Enterprise'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → 6342653.67 | yes |
| apac_analyst | revenue → 10832125.93 | yes |
| global_manager | revenue → 25250984.73 | yes |

## S-A-037: In which month of 2025 was revenue highest, and what was it?

Reference:
```sql
SELECT extract(month FROM o.ordered_on)::int AS month, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1 ORDER BY revenue DESC LIMIT 1
```
Second annotator:
```sql
WITH monthly_rev AS (
    SELECT date_trunc('month', o.ordered_on) AS month_start,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY date_trunc('month', o.ordered_on)
)
SELECT EXTRACT(MONTH FROM month_start)::int AS month,
       revenue
FROM monthly_rev
ORDER BY revenue DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | month, revenue → 12, 5842265.92 | yes |
| apac_analyst | month, revenue → 12, 5011701.37 | yes |
| global_manager | month, revenue → 12, 13819868.73 | yes |

## S-A-038: What was the value of cancelled orders in 2025, at net line amounts?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS cancelled_value FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'cancelled' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT
    SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS cancelled_order_value
FROM sales.orders o
JOIN sales.order_lines ol ON o.order_id = ol.order_id
WHERE o.status = 'cancelled'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cancelled_value → 4011984.71 | yes |
| apac_analyst | cancelled_value → 4681490.26 | yes |
| global_manager | cancelled_value → 12051451.71 | yes |

## S-A-039: How many sales reps were hired before 2022?

Reference:
```sql
SELECT count(*) AS reps FROM sales.sales_reps WHERE hired_on < DATE '2022-01-01'
```
Second annotator:
```sql
SELECT count(*) AS sales_reps_hired_before_2022
FROM sales.sales_reps
WHERE hired_on < DATE '2022-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | reps → 3 | yes |
| apac_analyst | reps → 4 | yes |
| global_manager | reps → 9 | yes |

## S-A-040: What is the average list price of products in each category? Round to two decimal places.

Reference:
```sql
SELECT category, round(avg(list_price), 2) AS avg_list_price FROM sales.products GROUP BY category
```
Second annotator:
```sql
SELECT
    category,
    ROUND(AVG(list_price), 2) AS average_list_price
FROM sales.products
GROUP BY category
ORDER BY category
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, avg_list_price → Accessories, 232.45; Hardware, 6905.12; Software, 2344.05; Services, 2418.85 | yes |
| apac_analyst | category, avg_list_price → Accessories, 232.45; Hardware, 6905.12; Software, 2344.05; Services, 2418.85 | yes |
| global_manager | category, avg_list_price → Accessories, 232.45; Hardware, 6905.12; Software, 2344.05; Services, 2418.85 | yes |

## S-A-041: Which customer placed the most orders in 2025, whatever their status, and how many?

Reference:
```sql
SELECT c.name, count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.customer_id, c.name ORDER BY orders DESC LIMIT 1
```
Second annotator:
```sql
SELECT
    c.name AS customer,
    COUNT(o.order_id) AS order_count
FROM sales.orders o
JOIN sales.customers c ON c.customer_id = o.customer_id
WHERE EXTRACT(YEAR FROM o.ordered_on) = 2025
GROUP BY c.name
ORDER BY order_count DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, orders → Atlas Labs GmbH, 15 | yes |
| apac_analyst | name, orders → Cedar Labs Ltd, 19 | yes |
| global_manager | name, orders → Cedar Labs Ltd, 19 | yes |

## S-A-042: What was the average number of days between an order and its return, across all returns? Round to one decimal place.

Reference:
```sql
SELECT round(avg(r.returned_on - o.ordered_on), 1) AS avg_days FROM sales.returns r JOIN sales.orders o USING (order_id)
```
Second annotator:
```sql
SELECT round(avg(r.returned_on - o.ordered_on)::numeric, 1) AS avg_days_between_order_and_return
FROM sales.returns r
JOIN sales.orders o ON r.order_id = o.order_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_days → 30.5 | yes |
| apac_analyst | avg_days → 30.4 | yes |
| global_manager | avg_days → 30.7 | yes |

## S-A-043: What share of 2025 revenue came from Software, in percent? Round to one decimal place.

Reference:
```sql
SELECT round(100 * sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE p.category = 'Software') / sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 1) AS software_share_pct FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT ROUND(
    100.0 * SUM(
        CASE WHEN p.category = 'Software'
             THEN ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)
             ELSE 0
        END
    ) / NULLIF(
        SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)),
        0
    ),
    1
) AS software_share_pct
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
JOIN sales.products p ON p.product_id = ol.product_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | software_share_pct → 20.4 | yes |
| apac_analyst | software_share_pct → 21.9 | yes |
| global_manager | software_share_pct → 20.6 | yes |

## S-A-044: How many returns were made because the item was damaged in 2025?

Reference:
```sql
SELECT count(*) AS returns FROM sales.returns WHERE reason = 'damaged' AND returned_on >= DATE '2025-01-01' AND returned_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*) AS damaged_returns_2025
FROM sales.returns
WHERE reason = 'damaged'
  AND EXTRACT(YEAR FROM returned_on) = 2025
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | returns → 23 | yes |
| apac_analyst | returns → 18 | yes |
| global_manager | returns → 55 | yes |

## S-A-045: What was the largest single completed order in 2025 by net value? Give the order id and its value.

Reference:
```sql
SELECT o.order_id, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS order_value FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.order_id ORDER BY order_value DESC LIMIT 1
```
Second annotator:
```sql
WITH order_net AS (
    SELECT o.order_id,
           SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS net_value
    FROM sales.orders o
    JOIN sales.order_lines ol ON ol.order_id = o.order_id
    WHERE o.status = 'completed'
      AND o.ordered_on >= DATE '2025-01-01'
      AND o.ordered_on < DATE '2026-01-01'
    GROUP BY o.order_id
)
SELECT order_id, net_value
FROM order_net
ORDER BY net_value DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | order_id, order_value → 1743, 367370.57 | yes |
| apac_analyst | order_id, order_value → 2243, 362367.62 | yes |
| global_manager | order_id, order_value → 1743, 367370.57 | yes |

## S-A-046: How many completed orders did each customer segment place in 2025?

Reference:
```sql
SELECT c.segment, count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.segment
```
Second annotator:
```sql
SELECT
    c.segment,
    COUNT(o.order_id) AS completed_orders
FROM sales.orders o
JOIN sales.customers c ON o.customer_id = c.customer_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
GROUP BY c.segment
ORDER BY c.segment
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | segment, orders → Enterprise, 93; Consumer, 244; SMB, 282 | yes |
| apac_analyst | segment, orders → Consumer, 203; Enterprise, 156; SMB, 242 | yes |
| global_manager | segment, orders → Enterprise, 369; Consumer, 572; SMB, 767 | yes |

## S-A-047: How many order lines, in orders of any status, have a unit price below the product's list price?

Reference:
```sql
SELECT count(*) AS lines FROM sales.order_lines l JOIN sales.products p USING (product_id) WHERE l.unit_price < p.list_price
```
Second annotator:
```sql
SELECT count(*) AS order_lines_below_list_price
FROM sales.order_lines ol
JOIN sales.products p ON ol.product_id = p.product_id
WHERE ol.unit_price < p.list_price
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | lines → 2798 | yes |
| apac_analyst | lines → 2684 | yes |
| global_manager | lines → 7549 | yes |

## S-A-048: What was the average base salary of sales reps in 2025? Round to two decimal places.

Reference:
```sql
SELECT round(avg(base_salary), 2) AS avg_base_salary FROM sales.rep_compensation WHERE year = 2025
```
Second annotator:
```sql
SELECT ROUND(AVG(base_salary), 2) AS average_base_salary
FROM sales.rep_compensation
WHERE year = 2025
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | avg_base_salary → 82787.36 | yes |

## S-A-049: How many units of Hardware were sold in completed orders in each year, 2024 and 2025?

Reference:
```sql
SELECT extract(year FROM o.ordered_on)::int AS year, sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND p.category = 'Hardware' GROUP BY 1
```
Second annotator:
```sql
WITH completed_orders AS (
    SELECT order_id, ordered_on
    FROM sales.orders
    WHERE status = 'completed'
),
hardware_lines AS (
    SELECT ol.quantity, co.ordered_on
    FROM sales.order_lines ol
    JOIN completed_orders co ON ol.order_id = co.order_id
    JOIN sales.products p ON ol.product_id = p.product_id
    WHERE p.category = 'Hardware'
)
SELECT EXTRACT(YEAR FROM ordered_on)::int AS year,
       SUM(quantity) AS units_sold
FROM hardware_lines
WHERE EXTRACT(YEAR FROM ordered_on) IN (2024, 2025)
GROUP BY EXTRACT(YEAR FROM ordered_on)
ORDER BY year
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | year, units → 2024, 2274; 2025, 4288 | yes |
| apac_analyst | year, units → 2024, 1926; 2025, 4261 | yes |
| global_manager | year, units → 2024, 5784; 2025, 11826 | yes |

## S-A-050: How many customers placed completed orders in both 2024 and 2025?

Reference:
```sql
SELECT count(*) AS customers FROM (SELECT customer_id FROM sales.orders WHERE status = 'completed' GROUP BY customer_id HAVING bool_or(ordered_on < DATE '2025-01-01') AND bool_or(ordered_on >= DATE '2025-01-01')) t
```
Second annotator:
```sql
SELECT count(*) FROM (
    SELECT customer_id FROM sales.orders
    WHERE status = 'completed' AND EXTRACT(YEAR FROM ordered_on) = 2024
    INTERSECT
    SELECT customer_id FROM sales.orders
    WHERE status = 'completed' AND EXTRACT(YEAR FROM ordered_on) = 2025
) AS both_years
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 78 | yes |
| apac_analyst | customers → 69 | yes |
| global_manager | customers → 206 | yes |
