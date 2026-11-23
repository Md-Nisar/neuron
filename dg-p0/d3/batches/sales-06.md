# Batch sales-06: owner review

25 questions, 20 agree on every persona, 5 to adjudicate.

## S-U-026: What was the average delivery time for orders in 2025?

- Kind: missing_data. Why: Orders have an order date but no shipping or delivery date.
- Second annotator: **refuse**: The database has no delivery date column; only order date and return date exist, so delivery time cannot be computed.
- Expected for every persona: **refuse**

## S-U-027: How many returns came from customers in Spain?

- Kind: nonexistent_entity. Why: Spain is not a country in the data.
- Second annotator: **clarify**: The phrase 'how many returns' could mean either the count of return records or the sum of returned quantities, which would yield different results.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.countries WHERE name ILIKE '%spain%' OR country_code = 'ES'` → 0

**Disagreement: owner to adjudicate.**

## S-U-028: What was revenue on Black Friday 2023?

- Kind: out_of_range. Why: Orders cover 2024 and 2025 only.
- Second annotator: **refuse**: The sales mart only covers 2024 to 2025, so Black Friday 2023 is outside the period covered by the data.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.orders WHERE ordered_on < DATE '2024-01-01'` → 0

## S-U-029: Which sales rep has the highest customer satisfaction score?

- Kind: missing_data. Why: There are no satisfaction scores.
- Second annotator: **refuse**: The database contains no customer satisfaction scores, surveys, or feedback metrics for sales reps.
- Expected for every persona: **refuse**

## S-U-030: How much revenue came from the Furniture category in 2025?

- Kind: nonexistent_entity. Why: Categories are Hardware, Software, Services and Accessories only.
- Second annotator: **refuse**: The products table only allows categories Hardware, Software, Services, and Accessories; Furniture is not a valid category in the database.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.products WHERE category ILIKE '%furniture%'` → 0

## S-M-001: What were sales last year?

- Kind: ambiguous. Why: "Sales" can mean revenue or a number of orders. Taking last year as 2025 (today is in 2026).
- Second annotator: **clarify**: The question is ambiguous: 'sales' could mean gross revenue, net revenue after returns, or only completed orders; 'last year' could mean calendar 2024, a rolling 12-month window, or a fiscal year, each yielding different results.
- Expected for every persona: **clarify**

Reading 1, Revenue in 2025:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: revenue → 44072021.08
- apac_analyst: revenue → 43182863.5
- global_manager: revenue → 122521671.79

Reading 2, Completed orders in 2025:
```sql
SELECT count(*) AS orders FROM sales.orders o WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: orders → 619
- apac_analyst: orders → 601
- global_manager: orders → 1708

## S-M-002: Who is our best customer?

- Kind: ambiguous. Why: "Best" has no measure: revenue or number of orders; no period given (both readings use 2024 and 2025).
- Second annotator: **clarify**: The term 'best customer' is ambiguous—it could mean highest net revenue, most orders, highest average order value, longest tenure, or other metrics, each yielding a different result.
- Expected for every persona: **clarify**

Reading 1, Highest revenue:
```sql
SELECT c.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' GROUP BY c.customer_id, c.name ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: name, revenue → Nova Retail Inc, 1520102.67
- apac_analyst: name, revenue → Cedar Labs Ltd, 1398153.79
- global_manager: name, revenue → Nova Retail Inc, 1520102.67

Reading 2, Most completed orders:
```sql
SELECT c.name, count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' GROUP BY c.customer_id, c.name ORDER BY orders DESC, c.name LIMIT 1
```
- emea_analyst: name, orders → Clear Labs Pty, 19
- apac_analyst: name, orders → Harbor Works Ltd, 17
- global_manager: name, orders → Clear Labs Pty, 19

## S-M-003: What is our biggest product?

- Kind: ambiguous. Why: "Biggest" can mean revenue or units sold (2024 and 2025, completed orders).
- Second annotator: **clarify**: The term 'biggest' is ambiguous and could mean highest revenue, highest quantity sold, highest list price, or most orders, each yielding a different product.
- Expected for every persona: **clarify**

Reading 1, Highest revenue:
```sql
SELECT p.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' GROUP BY p.product_id, p.name ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: name, revenue → Edge Server, 6963563.47
- apac_analyst: name, revenue → Router, 5383981.24
- global_manager: name, revenue → Storage Array, 17390768.06

Reading 2, Most units sold:
```sql
SELECT p.name, sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' GROUP BY p.product_id, p.name ORDER BY units DESC LIMIT 1
```
- emea_analyst: name, units → Edge Server, 850
- apac_analyst: name, units → Rack Unit, 893
- global_manager: name, units → Database License, 2078

## S-M-004: How many active customers do we have?

- Kind: ambiguous. Why: "Active" is not defined: ordered in the latest year, or ever ordered.
- Second annotator: **clarify**: The database has no 'active' flag or standard definition for active customers; the term could mean customers with recent orders, any completed order, accounts created in a period, etc., each yielding different counts.
- Expected for every persona: **clarify**

Reading 1, A completed order in 2025:
```sql
SELECT count(DISTINCT customer_id) AS customers FROM sales.orders o WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: customers → 105
- apac_analyst: customers → 104
- global_manager: customers → 297

Reading 2, Any completed order ever:
```sql
SELECT count(DISTINCT customer_id) AS customers FROM sales.orders WHERE status = 'completed'
```
- emea_analyst: customers → 106
- apac_analyst: customers → 105
- global_manager: customers → 299

## S-M-005: What was revenue in Q1?

- Kind: ambiguous. Why: The year is missing: Q1 2024 or Q1 2025.
- Second annotator: **clarify**: The question does not specify which year's Q1 (2024 or 2025) nor whether revenue means gross completed order lines, net of discounts, or net of returns.
- Expected for every persona: **clarify**

Reading 1, Q1 2024:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2024-01-01' AND o.ordered_on < DATE '2024-04-01'
```
- emea_analyst: revenue → 3794923.64
- apac_analyst: revenue → 3480883.49
- global_manager: revenue → 9602966.85

Reading 2, Q1 2025:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2025-04-01'
```
- emea_analyst: revenue → 8455152.2
- apac_analyst: revenue → 8457932.94
- global_manager: revenue → 23607102.65

## S-M-006: What is the average order size in 2025?

- Kind: ambiguous. Why: "Size" can mean value or number of units (completed orders).
- Second annotator: **clarify**: The term 'order size' is ambiguous: it could mean average revenue per order, average number of units per order, or average number of line items per order, and it is unclear whether cancelled or pending orders should be included.
- Expected for every persona: **clarify**

Reading 1, Average value:
```sql
SELECT round(avg(t), 2) AS avg_value FROM (SELECT sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) AS t FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.order_id) x
```
- emea_analyst: avg_value → 71198.74
- apac_analyst: avg_value → 71851.69
- global_manager: avg_value → 71734.0

Reading 2, Average units:
```sql
SELECT round(avg(t), 2) AS avg_units FROM (SELECT sum(l.quantity) AS t FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.order_id) x
```
- emea_analyst: avg_units → 26.36
- apac_analyst: avg_units → 27.71
- global_manager: avg_units → 26.53

## S-M-007: Which region performed best in 2025?

- Kind: ambiguous. Why: "Best" can mean the most revenue or the fastest growth over 2024.
- Second annotator: **clarify**: The phrase 'performed best' is ambiguous — it could mean highest revenue, most orders, highest growth, or another metric, and the question does not specify which.
- Expected for every persona: **clarify**

Reading 1, Most revenue in 2025:
```sql
SELECT o.region_id AS region, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY o.region_id ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: region, revenue → EMEA, 44072021.08
- apac_analyst: region, revenue → APAC, 43182863.5
- global_manager: region, revenue → EMEA, 44072021.08

Reading 2, Fastest growth over 2024:
```sql
SELECT o.region_id AS region, round(100 * (sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on >= DATE '2025-01-01') / sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on < DATE '2025-01-01') - 1), 1) AS growth_pct FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' GROUP BY o.region_id ORDER BY growth_pct DESC LIMIT 1
```
- emea_analyst: region, growth_pct → EMEA, 85.6
- apac_analyst: region, growth_pct → APAC, 116.5
- global_manager: region, growth_pct → AMER, 140.7

## S-M-008: What is our return rate?

- Kind: ambiguous. Why: Returned units over units sold, or orders with a return over all orders (completed, 2024 and 2025).
- Second annotator: **clarify**: The question does not specify the time period, granularity (overall, by region, product, etc.), or the definition of return rate (quantity-based, order-based, revenue-based), all of which would produce different results.
- Expected for every persona: **clarify**

Reading 1, Units returned over units sold, percent:
```sql
SELECT round(100.0 * (SELECT sum(r.quantity) FROM sales.returns r JOIN sales.orders o USING (order_id) WHERE o.status = 'completed') / (SELECT sum(l.quantity) FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed'), 2) AS return_rate_pct
```
- emea_analyst: return_rate_pct → 2.6
- apac_analyst: return_rate_pct → 2.85
- global_manager: return_rate_pct → 2.59

Reading 2, Orders with a return over orders, percent:
```sql
SELECT round(100.0 * count(*) FILTER (WHERE EXISTS (SELECT 1 FROM sales.returns r WHERE r.order_id = o.order_id)) / count(*), 2) AS return_rate_pct FROM sales.orders o WHERE o.status = 'completed'
```
- emea_analyst: return_rate_pct → 12.1
- apac_analyst: return_rate_pct → 11.73
- global_manager: return_rate_pct → 12.03

## S-M-009: How much did we discount in 2025?

- Kind: ambiguous. Why: A total in USD or an average percentage (completed orders).
- Second annotator: **clarify**: The question could mean total discount dollars, average discount percentage, or another discount metric, and it's unclear whether to include only completed orders or all orders.
- Expected for every persona: **clarify**

Reading 1, Total discount in USD:
```sql
SELECT round(sum(l.quantity * l.unit_price * l.discount_pct / 100), 2) AS discount_usd FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: discount_usd → 2162417.89
- apac_analyst: discount_usd → 2226676.47
- global_manager: discount_usd → 6234728.59

Reading 2, Average discount percent:
```sql
SELECT round(avg(l.discount_pct), 2) AS avg_discount_pct FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: avg_discount_pct → 4.76
- apac_analyst: avg_discount_pct → 5.06
- global_manager: avg_discount_pct → 4.94

## S-M-010: Who was the top sales rep in 2025?

- Kind: ambiguous. Why: "Top" can mean revenue or number of completed orders.
- Second annotator: **clarify**: The question does not specify the metric for 'top' (e.g., revenue, units sold, commission, number of orders), which could yield different representatives.
- Expected for every persona: **clarify**

Reading 1, Most revenue:
```sql
SELECT r.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.sales_reps r ON r.rep_id = o.rep_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY r.rep_id, r.name ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: name, revenue → Avery Haddad, 7743687.28
- apac_analyst: name, revenue → Quinn Iyer, 6832289.9
- global_manager: name, revenue → Avery Haddad, 7743687.28

Reading 2, Most completed orders:
```sql
SELECT r.name, count(*) AS orders FROM sales.orders o JOIN sales.sales_reps r ON r.rep_id = o.rep_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY r.rep_id, r.name ORDER BY orders DESC, r.name LIMIT 1
```
- emea_analyst: name, orders → Avery Haddad, 96
- apac_analyst: name, orders → Mei Clarke, 88
- global_manager: name, orders → Avery Haddad, 96

## S-M-011: How many orders were there in 2025?

- Kind: ambiguous. Why: All orders, or only completed ones (which are the only ones that count as revenue).
- Second annotator: **answer**: The orders table has an ordered_on date column and the schema covers 2024-2025, so counting orders placed in 2025 is directly supported.
- Expected for every persona: **clarify**

Reading 1, All statuses:
```sql
SELECT count(*) AS orders FROM sales.orders o WHERE o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: orders → 742
- apac_analyst: orders → 723
- global_manager: orders → 2065

Reading 2, Completed only:
```sql
SELECT count(*) AS orders FROM sales.orders o WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: orders → 619
- apac_analyst: orders → 601
- global_manager: orders → 1708

**Disagreement: owner to adjudicate.**

## S-M-012: What were sales in December?

- Kind: ambiguous. Why: The year is missing, and "sales" is taken as revenue.
- Second annotator: **clarify**: The question does not specify which December (2024 or 2025) nor which sales metric (revenue, orders, units) is wanted.
- Expected for every persona: **clarify**

Reading 1, December 2024:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2024-12-01' AND o.ordered_on < DATE '2025-01-01'
```
- emea_analyst: revenue → 2432915.79
- apac_analyst: revenue → 1992577.2
- global_manager: revenue → 6001088.72

Reading 2, December 2025:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-12-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: revenue → 5842265.92
- apac_analyst: revenue → 5011701.37
- global_manager: revenue → 13819868.73

## S-M-013: How much revenue did new customers bring in 2025?

- Kind: ambiguous. Why: "New" can mean the account was opened in 2025, or the first order was in 2025.
- Second annotator: **clarify**: The question does not specify whether revenue should be gross or net of returns, nor whether 'new customers' means accounts created in 2025 or customers making their first purchase in 2025.
- Expected for every persona: **clarify**

Reading 1, Account opened in 2025:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND c.created_on >= DATE '2025-01-01'
```
- emea_analyst: revenue → 15611078.42
- apac_analyst: revenue → 13850072.86
- global_manager: revenue → 41917696.71

Reading 2, First order in 2025:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND o.customer_id NOT IN (SELECT customer_id FROM sales.orders WHERE ordered_on < DATE '2025-01-01')
```
- emea_analyst: revenue → 15611078.42
- apac_analyst: revenue → 15769852.61
- global_manager: revenue → 46750528.85
- **Readings give the same answer for emea_analyst.**

**Disagreement: owner to adjudicate.**

## S-M-014: What is the average price of our products?

- Kind: ambiguous. Why: Catalogue list price, or the unit price actually agreed on order lines.
- Second annotator: **answer**: The products table contains a list_price column representing catalogue prices, so the average product price can be computed directly.
- Expected for every persona: **clarify**

Reading 1, Average list price:
```sql
SELECT round(avg(list_price), 2) AS avg_price FROM sales.products
```
- emea_analyst: avg_price → 2975.11
- apac_analyst: avg_price → 2975.11
- global_manager: avg_price → 2975.11

Reading 2, Average agreed unit price:
```sql
SELECT round(avg(unit_price), 2) AS avg_price FROM sales.order_lines
```
- emea_analyst: avg_price → 2801.75
- apac_analyst: avg_price → 2767.36
- global_manager: avg_price → 2816.52

**Disagreement: owner to adjudicate.**

## S-M-015: Which month had the best sales in 2025?

- Kind: ambiguous. Why: Revenue or number of completed orders.
- Second annotator: **clarify**: The question does not specify whether 'best sales' means highest net revenue, highest gross revenue, most units sold, most orders, or another metric, and it does not clarify whether returns should be netted out.
- Expected for every persona: **clarify**

Reading 1, Most revenue:
```sql
SELECT extract(month FROM o.ordered_on)::int AS month, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1 ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: month, revenue → 12, 5842265.92
- apac_analyst: month, revenue → 12, 5011701.37
- global_manager: month, revenue → 12, 13819868.73

Reading 2, Most completed orders:
```sql
SELECT extract(month FROM o.ordered_on)::int AS month, count(*) AS orders FROM sales.orders o WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY 1 ORDER BY orders DESC, 1 LIMIT 1
```
- emea_analyst: month, orders → 12, 76
- apac_analyst: month, orders → 9, 67
- global_manager: month, orders → 10, 190

## S-M-016: How did revenue change in 2025?

- Kind: ambiguous. Why: A change in USD or in percent, against 2024.
- Second annotator: **clarify**: The question asks how revenue changed in 2025 but does not specify the comparison baseline (e.g., vs. 2024, month-over-month within 2025, quarter-over-quarter, or another period), which leads to multiple reasonable interpretations.
- Expected for every persona: **clarify**

Reading 1, Change in USD:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on >= DATE '2025-01-01') - sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on < DATE '2025-01-01'), 2) AS change_usd FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed'
```
- emea_analyst: change_usd → 20323418.31
- apac_analyst: change_usd → 23237207.46
- global_manager: change_usd → 64177456.42

Reading 2, Change in percent:
```sql
SELECT round(100 * (sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on >= DATE '2025-01-01') / sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on < DATE '2025-01-01') - 1), 1) AS change_pct FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed'
```
- emea_analyst: change_pct → 85.6
- apac_analyst: change_pct → 116.5
- global_manager: change_pct → 110.0

## S-M-017: What is the revenue for Hardware?

- Kind: ambiguous. Why: No period: both years, or only the latest one.
- Second annotator: **answer**: The database contains product categories, order lines with pricing and discounts, and order statuses, allowing calculation of revenue for Hardware from completed orders.
- Expected for every persona: **clarify**

Reading 1, 2024 and 2025:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND p.category = 'Hardware'
```
- emea_analyst: revenue → 40354537.17
- apac_analyst: revenue → 35823259.38
- global_manager: revenue → 106136775.16

Reading 2, 2025 only:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' AND p.category = 'Hardware'
```
- emea_analyst: revenue → 26209063.75
- apac_analyst: revenue → 24542643.69
- global_manager: revenue → 71511891.12

**Disagreement: owner to adjudicate.**

## S-M-018: How many products did we sell in 2025?

- Kind: ambiguous. Why: Units sold, or the number of different products sold (completed orders).
- Second annotator: **clarify**: The question could mean total units sold across all products, the count of distinct products sold, or the number of order lines in 2025, and it is unclear whether only completed orders should be counted.
- Expected for every persona: **clarify**

Reading 1, Units:
```sql
SELECT sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: units → 16317
- apac_analyst: units → 16651
- global_manager: units → 45315

Reading 2, Different products:
```sql
SELECT count(DISTINCT l.product_id) AS products FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: products → 40
- apac_analyst: products → 40
- global_manager: products → 40

## S-M-019: Which customer ordered the most in 2025?

- Kind: ambiguous. Why: Most completed orders, or the most value.
- Second annotator: **clarify**: "Ordered the most" could mean highest revenue, most items, or most orders, each giving potentially different customers.
- Expected for every persona: **clarify**

Reading 1, Most completed orders:
```sql
SELECT c.name, count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.customer_id, c.name ORDER BY orders DESC, c.name LIMIT 1
```
- emea_analyst: name, orders → Atlas Labs GmbH, 14
- apac_analyst: name, orders → Cedar Labs Ltd, 16
- global_manager: name, orders → Cedar Labs Ltd, 16

Reading 2, Most value:
```sql
SELECT c.name, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01' GROUP BY c.customer_id, c.name ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: name, revenue → Granite Foods LLC, 1397227.01
- apac_analyst: name, revenue → Cedar Labs Ltd, 1398153.79
- global_manager: name, revenue → Cedar Labs Ltd, 1398153.79

## S-M-020: What was gross revenue in 2025?

- Kind: ambiguous. Why: Gross can mean before discounts, or before taking off returns.
- Second annotator: **clarify**: Gross revenue could mean before discounts, after discounts but before returns, or after returns; also unclear whether to use order date or return date for 2025 attribution.
- Expected for every persona: **clarify**

Reading 1, Before discounts:
```sql
SELECT round(sum(l.quantity * l.unit_price), 2) AS gross_revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: gross_revenue → 46234438.97
- apac_analyst: gross_revenue → 45409539.97
- global_manager: gross_revenue → 128756400.38

Reading 2, Net of discounts, before returns:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS gross_revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) WHERE o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
- emea_analyst: gross_revenue → 44072021.08
- apac_analyst: gross_revenue → 43182863.5
- global_manager: gross_revenue → 122521671.79
