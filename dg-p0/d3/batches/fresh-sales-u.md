# Batch fresh-sales-u: owner review

20 questions, 15 agree on every persona, 5 to adjudicate.

## S-FU-01: How many customers are in Italy?

- Kind: nonexistent_entity. Why: Italy is not a country in the data.
- Second annotator: **answer**: The database contains customers linked to countries via country_code, and Italy exists in the countries table with ISO code 'IT', so the count can be determined directly.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.countries WHERE name ILIKE '%ital%' OR country_code = 'IT'` → 0

**Disagreement: owner to adjudicate.**

## S-FU-02: What was the revenue from the Quantum Firewall product in 2025?

- Kind: nonexistent_entity. Why: There is no product called Quantum Firewall.
- Second annotator: **answer**: The schema contains all necessary tables (products, orders, order_lines, returns) with appropriate date coverage (2024-2025) and a clear revenue definition to compute revenue for a named product in 2025.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.products WHERE name ILIKE '%quantum%'` → 0

**Disagreement: owner to adjudicate.**

## S-FU-03: How many customers are in the Government segment?

- Kind: nonexistent_entity. Why: Segments are Enterprise, SMB and Consumer only.
- Second annotator: **refuse**: The customers table only allows segments 'Enterprise', 'SMB', or 'Consumer'; there is no 'Government' segment in the data.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.customers WHERE segment ILIKE '%gov%'` → 0

## S-FU-04: How many returns were due to a billing error?

- Kind: nonexistent_entity. Why: Billing error is not a return reason in the data.
- Second annotator: **refuse**: The returns table only tracks four reason codes (damaged, wrong_item, not_needed, late_delivery) and does not include a billing error category.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.returns WHERE reason ILIKE '%bill%'` → 0

## S-FU-05: How many orders did the sales rep Priya Raman handle?

- Kind: nonexistent_entity. Why: There is no sales rep called Priya Raman.
- Second annotator: **answer**: The database contains sales_reps with names and orders linked by rep_id, so counting orders for a rep named 'Priya Raman' is directly computable.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.sales_reps WHERE name ILIKE '%raman%' OR name ILIKE 'priya%'` → 0

**Disagreement: owner to adjudicate.**

## S-FU-06: How many orders did Globex Corporation place?

- Kind: nonexistent_entity. Why: There is no customer called Globex Corporation.
- Second annotator: **clarify**: The question does not specify whether to count all orders placed by Globex Corporation or only completed orders, and the schema distinguishes order statuses with a comment that only completed orders count as revenue.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.customers WHERE name ILIKE '%globex%'` → 0

**Disagreement: owner to adjudicate.**

## S-FU-07: What was the revenue from the LATAM region in 2025?

- Kind: nonexistent_entity. Why: Regions are EMEA, APAC and AMER; there is no LATAM region.
- Second annotator: **clarify**: The question does not specify whether 'LATAM' refers to a region_id or region name, nor whether revenue should be gross (completed orders only) or net of returns.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.regions WHERE region_id ILIKE '%latam%' OR name ILIKE '%latin%'` → 0

**Disagreement: owner to adjudicate.**

## S-FU-08: What is the credit limit of each Enterprise customer?

- Kind: missing_data. Why: There is no credit data.
- Second annotator: **refuse**: The database schema does not include a credit limit column or any credit-related data for customers.
- Expected for every persona: **refuse**

## S-FU-09: How much did we spend on marketing in each region in 2025?

- Kind: missing_data. Why: There is no spending or marketing data.
- Second annotator: **refuse**: The database contains no marketing spend data; it only tracks sales orders, returns, products, customers, reps, and rep compensation.
- Expected for every persona: **refuse**

## S-FU-10: How many Edge Servers are in stock?

- Kind: missing_data. Why: There is no inventory data.
- Second annotator: **refuse**: The database does not contain inventory or stock level data; it only tracks sales orders, returns, and product catalogue information.
- Expected for every persona: **refuse**

## S-FU-11: What was the average shipping cost per order in 2025?

- Kind: missing_data. Why: Orders hold no shipping or freight cost.
- Second annotator: **refuse**: The database schema does not contain any shipping cost information in orders, order lines, or any other table.
- Expected for every persona: **refuse**

## S-FU-12: How many sales calls did each sales rep make in 2025?

- Kind: missing_data. Why: There is no activity or call data.
- Second annotator: **refuse**: The database schema contains no table or column for tracking sales calls or rep activities, only orders, order lines, returns, and compensation.
- Expected for every persona: **refuse**

## S-FU-13: Which customers rated our service below 3 out of 5?

- Kind: missing_data. Why: There is no customer rating or satisfaction data.
- Second annotator: **refuse**: The database does not contain any customer service rating data.
- Expected for every persona: **refuse**

## S-FU-14: How many orders were placed in January 2026?

- Kind: out_of_range. Why: Orders end on 31 December 2025.
- Second annotator: **refuse**: The database only contains data from 2024 to 2025, so January 2026 is outside the covered period.
- Expected for every persona: **refuse**

## S-FU-15: What was revenue in the first half of 2022?

- Kind: out_of_range. Why: Orders cover 2024 and 2025 only.
- Second annotator: **refuse**: The sales mart only covers 2024 to 2025, so revenue for the first half of 2022 is outside the period covered by the data.
- Expected for every persona: **refuse**

## S-FU-16: How many returns were processed in 2023?

- Kind: out_of_range. Why: Returns cover 2024 and 2025 only.
- Second annotator: **refuse**: The database only contains data from 2024 to 2025, so it cannot answer questions about 2023.
- Expected for every persona: **refuse**

## S-FU-17: Which products will sell best in 2027?

- Kind: out_of_range. Why: A forecast, not a fact in the data; forecasting is excluded from the gateway.
- Second annotator: **refuse**: The database only contains data from 2024 to 2025 and cannot predict future sales for 2027.
- Expected for every persona: **refuse**

## S-FU-18: Who is our most talented sales rep?

- Kind: subjective. Why: Talent is a judgement; the data holds orders, not talent.
- Second annotator: **refuse**: Talent is subjective and not defined in the database; no objective metric exists to determine the most talented sales rep.
- Expected for every persona: **refuse**

## S-FU-19: Which customer is the most pleasant to work with?

- Kind: subjective. Why: Pleasantness is a judgement the data does not record.
- Second annotator: **refuse**: The database does not contain any measure of customer pleasantness; this is a subjective assessment not captured in the data.
- Expected for every persona: **refuse**

## S-FU-20: What was the euro to US dollar exchange rate on 2025-06-30?

- Kind: outside_database. Why: There is no exchange-rate data; amounts carry no currency conversion.
- Second annotator: **refuse**: The database contains only sales data in USD with no exchange rate tables or currency conversion information.
- Expected for every persona: **refuse**
