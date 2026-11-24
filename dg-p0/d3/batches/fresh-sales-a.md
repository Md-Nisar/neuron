# Batch fresh-sales-a: owner review

20 questions, 18 agree on every persona, 2 to adjudicate.

## S-FA-01: How many orders did the customer Nova Motors SA place?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id WHERE c.name = 'Nova Motors SA'
```
Second annotator:
```sql
SELECT count(*) AS order_count
FROM sales.orders o
JOIN sales.customers c ON o.customer_id = c.customer_id
WHERE c.name = 'Nova Motors SA'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 10 | yes |
| apac_analyst | orders → 0 | yes |
| global_manager | orders → 10 | yes |

## S-FA-02: How many Docking Stations were sold in completed orders?

Reference:
```sql
SELECT sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o ON o.order_id = l.order_id JOIN sales.products p ON p.product_id = l.product_id WHERE p.name = 'Docking Station' AND o.status = 'completed'
```
Second annotator:
```sql
SELECT SUM(ol.quantity) AS docking_stations_sold
FROM sales.order_lines ol
JOIN sales.orders o ON ol.order_id = o.order_id
JOIN sales.products p ON ol.product_id = p.product_id
WHERE o.status = 'completed'
  AND p.name ILIKE '%Docking Station%'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | units → 590 | yes |
| apac_analyst | units → 824 | yes |
| global_manager | units → 1876 | yes |

## S-FA-03: How many returns were due to late delivery?

Reference:
```sql
SELECT count(*) AS returns FROM sales.returns WHERE reason = 'late_delivery'
```
Second annotator:
```sql
SELECT COUNT(*) FROM sales.returns WHERE reason = 'late_delivery'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | returns → 26 | yes |
| apac_analyst | returns → 31 | yes |
| global_manager | returns → 76 | yes |

## S-FA-04: How many returns had the reason wrong item?

Reference:
```sql
SELECT count(*) AS returns FROM sales.returns WHERE reason = 'wrong_item'
```
Second annotator:
```sql
SELECT count(*) FROM sales.returns WHERE reason = 'wrong_item'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | returns → 26 | yes |
| apac_analyst | returns → 28 | yes |
| global_manager | returns → 83 | yes |

## S-FA-05: How many SMB customers are in Japan?

Reference:
```sql
SELECT count(*) AS customers FROM sales.customers c JOIN sales.countries n ON n.country_code = c.country_code WHERE c.segment = 'SMB' AND n.name = 'Japan'
```
Second annotator:
```sql
SELECT COUNT(*) AS smb_customers_in_japan
FROM sales.customers c
JOIN sales.countries co ON c.country_code = co.country_code
WHERE c.segment = 'SMB' AND co.name = 'Japan'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 0 | yes |
| apac_analyst | customers → 12 | yes |
| global_manager | customers → 12 | yes |

## S-FA-06: How many small and medium business customers are there?

Reference:
```sql
SELECT count(*) AS customers FROM sales.customers WHERE segment = 'SMB'
```
Second annotator:
```sql
SELECT count(*) AS smb_customer_count
FROM sales.customers
WHERE segment = 'SMB'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 50 | yes |
| apac_analyst | customers → 42 | yes |
| global_manager | customers → 134 | yes |

## S-FA-07: How many orders did the sales rep Sam Okafor handle?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o JOIN sales.sales_reps r ON r.rep_id = o.rep_id WHERE r.name = 'Sam Okafor'
```
Second annotator:
```sql
SELECT COUNT(*) AS order_count
FROM sales.orders o
JOIN sales.sales_reps r ON o.rep_id = r.rep_id
WHERE r.name = 'Sam Okafor'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 140 | yes |
| apac_analyst | orders → 0 | yes |
| global_manager | orders → 140 | yes |

## S-FA-08: How many orders placed in 2025 were not cancelled?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o WHERE o.status <> 'cancelled' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*) AS order_count
FROM sales.orders
WHERE ordered_on >= DATE '2025-01-01'
  AND ordered_on < DATE '2026-01-01'
  AND status <> 'cancelled'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 689 | yes |
| apac_analyst | orders → 662 | yes |
| global_manager | orders → 1893 | yes |

## S-FA-09: How many customers are not in the Enterprise segment?

Reference:
```sql
SELECT count(*) AS customers FROM sales.customers WHERE segment <> 'Enterprise'
```
Second annotator:
```sql
SELECT count(*) AS customer_count
FROM sales.customers
WHERE segment <> 'Enterprise'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 88 | yes |
| apac_analyst | customers → 79 | yes |
| global_manager | customers → 231 | yes |

## S-FA-10: What was the revenue from Edge Servers in 2025?

Reference:
```sql
SELECT round(sum(l.quantity * l.unit_price * (1 - l.discount_pct / 100)), 2) AS revenue FROM sales.order_lines l JOIN sales.orders o ON o.order_id = l.order_id JOIN sales.products p ON p.product_id = l.product_id WHERE p.name = 'Edge Server' AND o.status = 'completed' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity * ol.unit_price * (1 - ol.discount_pct / 100)) AS revenue
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
JOIN sales.products p ON p.product_id = ol.product_id
WHERE o.status = 'completed'
  AND p.name = 'Edge Servers'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | revenue → 4911152.93 | NO: values differ |
| | second: revenue → None | |
| apac_analyst | revenue → 2446896.28 | NO: values differ |
| | second: revenue → None | |
| global_manager | revenue → 9556030.94 | NO: values differ |
| | second: revenue → None | |

**Disagreement: owner to adjudicate.**

## S-FA-11: How many customers are in the UAE?

Reference:
```sql
SELECT count(*) AS customers FROM sales.customers c JOIN sales.countries n ON n.country_code = c.country_code WHERE n.name = 'United Arab Emirates'
```
Second annotator:
```sql
SELECT count(*) AS customer_count
FROM sales.customers
WHERE country_code = 'AE'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | customers → 28 | yes |
| apac_analyst | customers → 0 | yes |
| global_manager | customers → 28 | yes |

## S-FA-12: How many orders came from customers in Brazil?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id JOIN sales.countries n ON n.country_code = c.country_code WHERE n.name = 'Brazil'
```
Second annotator:
```sql
SELECT COUNT(o.order_id) AS order_count
FROM sales.orders o
JOIN sales.customers c ON o.customer_id = c.customer_id
JOIN sales.countries co ON c.country_code = co.country_code
WHERE co.name = 'Brazil'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 0 | yes |
| apac_analyst | orders → 0 | yes |
| global_manager | orders → 314 | yes |

## S-FA-13: How many 27-inch monitors were sold in completed orders in 2024?

Reference:
```sql
SELECT sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o ON o.order_id = l.order_id JOIN sales.products p ON p.product_id = l.product_id WHERE p.name = 'Monitor 27in' AND o.status = 'completed' AND o.ordered_on >= DATE '2024-01-01' AND o.ordered_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity) AS total_sold
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
JOIN sales.products p ON p.product_id = ol.product_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2024-01-01'
  AND o.ordered_on < DATE '2025-01-01'
  AND p.name ILIKE '%27-inch%monitor%'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | units → 146 | NO: values differ |
| | second: total_sold → None | |
| apac_analyst | units → 209 | NO: values differ |
| | second: total_sold → None | |
| global_manager | units → 555 | NO: values differ |
| | second: total_sold → None | |

**Disagreement: owner to adjudicate.**

## S-FA-14: How many pending orders does Atlas Analytics SA have?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id WHERE c.name = 'Atlas Analytics SA' AND o.status = 'pending'
```
Second annotator:
```sql
SELECT COUNT(*) AS pending_orders
FROM sales.orders o
JOIN sales.customers c ON o.customer_id = c.customer_id
WHERE c.name = 'Atlas Analytics SA'
  AND o.status = 'pending'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 0 | yes |
| apac_analyst | orders → 0 | yes |
| global_manager | orders → 0 | yes |

## S-FA-15: How many units of Support Plan Premium were sold in completed orders in 2024?

Reference:
```sql
SELECT sum(l.quantity) AS units FROM sales.order_lines l JOIN sales.orders o ON o.order_id = l.order_id JOIN sales.products p ON p.product_id = l.product_id WHERE p.name = 'Support Plan Premium' AND o.status = 'completed' AND o.ordered_on >= DATE '2024-01-01' AND o.ordered_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT SUM(ol.quantity) AS units_sold
FROM sales.orders o
JOIN sales.order_lines ol ON ol.order_id = o.order_id
JOIN sales.products p ON p.product_id = ol.product_id
WHERE o.status = 'completed'
  AND o.ordered_on >= DATE '2024-01-01'
  AND o.ordered_on < DATE '2025-01-01'
  AND p.name = 'Support Plan Premium'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | units → 244 | yes |
| apac_analyst | units → 149 | yes |
| global_manager | units → 435 | yes |

## S-FA-16: Which APAC sales reps were hired in 2024? List their names.

Reference:
```sql
SELECT name FROM sales.sales_reps WHERE region_id = 'APAC' AND hired_on >= DATE '2024-01-01' AND hired_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT sr.name
FROM sales.sales_reps sr
JOIN sales.regions r ON sr.region_id = r.region_id
WHERE r.name = 'APAC'
  AND EXTRACT(YEAR FROM sr.hired_on) = 2024
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name → no rows | yes |
| apac_analyst | name → no rows | yes |
| global_manager | name → no rows | yes |

## S-FA-17: How many orders did Maple Systems Co place in 2025?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o JOIN sales.customers c ON c.customer_id = o.customer_id WHERE c.name = 'Maple Systems Co' AND o.ordered_on >= DATE '2025-01-01' AND o.ordered_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*) AS order_count
FROM sales.orders o
JOIN sales.customers c ON o.customer_id = c.customer_id
WHERE c.name = 'Maple Systems Co'
  AND o.ordered_on >= DATE '2025-01-01'
  AND o.ordered_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 4 | yes |
| apac_analyst | orders → 0 | yes |
| global_manager | orders → 4 | yes |

## S-FA-18: How many Hardware products are in the catalogue?

Reference:
```sql
SELECT count(*) AS products FROM sales.products WHERE category = 'Hardware'
```
Second annotator:
```sql
SELECT count(*) AS hardware_product_count
FROM sales.products
WHERE category = 'Hardware'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | products → 10 | yes |
| apac_analyst | products → 10 | yes |
| global_manager | products → 10 | yes |

## S-FA-19: How many returns were for damaged goods?

Reference:
```sql
SELECT count(*) AS returns FROM sales.returns WHERE reason = 'damaged'
```
Second annotator:
```sql
SELECT count(*) AS damaged_returns_count
FROM sales.returns
WHERE reason = 'damaged'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | returns → 32 | yes |
| apac_analyst | returns → 25 | yes |
| global_manager | returns → 75 | yes |

## S-FA-20: How many orders were handled by sales reps based in the Americas?

Reference:
```sql
SELECT count(*) AS orders FROM sales.orders o JOIN sales.sales_reps r ON r.rep_id = o.rep_id JOIN sales.regions g ON g.region_id = r.region_id WHERE g.name = 'Americas'
```
Second annotator:
```sql
SELECT count(*) AS order_count
FROM sales.orders o
JOIN sales.sales_reps r ON o.rep_id = r.rep_id
JOIN sales.regions reg ON r.region_id = reg.region_id
WHERE reg.name = 'Americas'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | orders → 0 | yes |
| apac_analyst | orders → 0 | yes |
| global_manager | orders → 827 | yes |
