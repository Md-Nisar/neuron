# Batch sales-06b: owner review

3 questions, 3 agree on every persona, 0 to adjudicate.

## S-M-021: Which product category grew the most in 2025?

- Kind: ambiguous. Why: Growth in USD or in percent, against 2024.
- Second annotator: **clarify**: The question does not specify the growth metric (revenue, units, orders), the comparison baseline (year-over-year vs. within 2025), or whether growth is absolute or percentage, leading to multiple reasonable interpretations.
- Expected for every persona: **clarify**

Reading 1, Largest growth in USD:
```sql
SELECT p.category, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on >= DATE '2025-01-01') - sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on < DATE '2025-01-01'), 2) AS growth_usd FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' GROUP BY p.category ORDER BY growth_usd DESC LIMIT 1
```
- emea_analyst: category, growth_usd → Hardware, 12063590.33
- apac_analyst: category, growth_usd → Hardware, 13262027.99
- global_manager: category, growth_usd → Hardware, 36887007.09

Reading 2, Largest growth in percent:
```sql
SELECT p.category, round(100 * (sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on >= DATE '2025-01-01') / sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) FILTER (WHERE o.ordered_on < DATE '2025-01-01') - 1), 1) AS growth_pct FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.products p USING (product_id) WHERE o.status = 'completed' GROUP BY p.category ORDER BY growth_pct DESC LIMIT 1
```
- emea_analyst: category, growth_pct → Services, 94.0
- apac_analyst: category, growth_pct → Software, 131.4
- global_manager: category, growth_pct → Software, 118.1

## S-M-022: Which country is our largest market?

- Kind: ambiguous. Why: Largest by revenue, or by number of completed orders (2024 and 2025).
- Second annotator: **clarify**: The question does not specify the metric for 'largest market' (e.g., revenue, customers, orders, units), and different metrics could yield different countries.
- Expected for every persona: **clarify**

Reading 1, Most revenue:
```sql
SELECT co.name AS country, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id JOIN sales.countries co ON co.country_code = c.country_code WHERE o.status = 'completed' GROUP BY co.name ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: country, revenue → Germany, 19963026.6
- apac_analyst: country, revenue → Japan, 18120119.83
- global_manager: country, revenue → Germany, 19963026.6

Reading 2, Most completed orders:
```sql
SELECT co.name AS country, count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id JOIN sales.countries co ON co.country_code = c.country_code WHERE o.status = 'completed' GROUP BY co.name ORDER BY orders DESC LIMIT 1
```
- emea_analyst: country, orders → Germany, 260
- apac_analyst: country, orders → India, 264
- global_manager: country, orders → Brazil, 269

## S-M-023: Which customer segment is the most valuable?

- Kind: ambiguous. Why: Most total revenue, or most revenue per customer (2024 and 2025).
- Second annotator: **clarify**: The term 'most valuable' is ambiguous: it could mean highest total revenue, highest average revenue per customer, highest revenue net of returns, or another metric, and no time period is specified.
- Expected for every persona: **clarify**

Reading 1, Most total revenue:
```sql
SELECT c.segment, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' GROUP BY c.segment ORDER BY revenue DESC LIMIT 1
```
- emea_analyst: segment, revenue → SMB, 30700151.66
- apac_analyst: segment, revenue → SMB, 26959138.74
- global_manager: segment, revenue → SMB, 82180599.76

Reading 2, Most revenue per customer:
```sql
SELECT c.segment, round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)) / count(DISTINCT c.customer_id), 2) AS revenue_per_customer FROM sales.order_lines l JOIN sales.orders o USING (order_id) JOIN sales.customers c ON c.customer_id = o.customer_id WHERE o.status = 'completed' GROUP BY c.segment ORDER BY revenue_per_customer DESC LIMIT 1
```
- emea_analyst: segment, revenue_per_customer → Consumer, 716652.16
- apac_analyst: segment, revenue_per_customer → SMB, 641884.26
- global_manager: segment, revenue_per_customer → Consumer, 634693.33
