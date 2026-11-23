# Batch sales-05: owner review

25 questions, 22 agree on every persona, 3 to adjudicate.

## S-U-001: What was our profit margin in 2025?

- Kind: missing_data. Why: There is no cost data, so profit cannot be computed.
- Second annotator: **refuse**: The database contains revenue data (orders, order_lines) and partial cost data (rep_compensation), but lacks product costs (COGS), overhead, and other expenses needed to calculate profit margin.
- Expected for every persona: **refuse**

## S-U-002: What was the gross margin on Hardware products?

- Kind: missing_data. Why: There is no product cost, so margin cannot be computed.
- Second annotator: **refuse**: The database contains revenue data (unit prices, discounts, quantities) but has no cost of goods sold or product cost information required to calculate gross margin.
- Expected for every persona: **refuse**

## S-U-003: How much did we spend on shipping in 2025?

- Kind: missing_data. Why: There is no shipping or freight data.
- Second annotator: **refuse**: The database schema does not contain any shipping cost data or related tables.
- Expected for every persona: **refuse**

## S-U-004: What is the email address of each Enterprise customer?

- Kind: missing_data. Why: Customers have no contact details.
- Second annotator: **refuse**: The customers table does not contain an email column, so email addresses are not stored in the database.
- Expected for every persona: **refuse**

## S-U-005: Which marketing campaign brought in the most revenue?

- Kind: missing_data. Why: There is no campaign data.
- Second annotator: **refuse**: The database schema contains no marketing campaign tables, campaign attribution data, or any fields linking orders to marketing campaigns.
- Expected for every persona: **refuse**

## S-U-006: Which sales reps hit their 2025 sales target?

- Kind: missing_data. Why: There are no sales targets.
- Second annotator: **refuse**: The database contains sales transactions and rep compensation but does not store sales targets for representatives.
- Expected for every persona: **refuse**

## S-U-007: How many units of each product are in stock?

- Kind: missing_data. Why: There is no inventory data.
- Second annotator: **refuse**: The database tracks sales orders and returns but does not contain inventory or stock level data for products.
- Expected for every persona: **refuse**

## S-U-008: How satisfied were customers with their orders in 2025?

- Kind: missing_data. Why: There are no ratings or survey data.
- Second annotator: **refuse**: The database contains no customer satisfaction data, surveys, ratings, or feedback metrics for any year including 2025.
- Expected for every persona: **refuse**

## S-U-009: Which supplier provides the Edge Server?

- Kind: missing_data. Why: There is no supplier data.
- Second annotator: **refuse**: The database does not contain supplier information for products.
- Expected for every persona: **refuse**

## S-U-010: What was total 2025 revenue in euros?

- Kind: missing_data. Why: Prices are in USD and there are no exchange rates.
- Second annotator: **refuse**: The database stores all monetary values in USD and does not contain exchange rate data to convert 2025 revenue to euros.
- Expected for every persona: **refuse**

## S-U-011: How many website visits turned into orders?

- Kind: missing_data. Why: There is no web traffic data.
- Second annotator: **refuse**: The database contains no website visit or web analytics data, only sales orders, customers, products, and related entities.
- Expected for every persona: **refuse**

## S-U-012: How much sales tax was collected on 2025 orders?

- Kind: missing_data. Why: There is no tax data.
- Second annotator: **refuse**: The schema contains no sales tax fields, tax rates, or tax collection records, so the database cannot answer this question.
- Expected for every persona: **refuse**

## S-U-013: Which industry is each Enterprise customer in?

- Kind: missing_data. Why: Customers have a segment but no industry.
- Second annotator: **refuse**: The database schema does not contain any industry information for customers; only segment, country, region, and creation date are stored.
- Expected for every persona: **refuse**

## S-U-014: Why were orders cancelled in 2025?

- Kind: missing_data. Why: Cancelled orders carry no reason; only returns have reasons.
- Second annotator: **refuse**: The database records order status including 'cancelled' but does not store a reason for cancellation.
- Expected for every persona: **refuse**

## S-U-015: How many sales calls did each rep make in 2025?

- Kind: missing_data. Why: There is no activity or call data.
- Second annotator: **refuse**: The database contains no table or column tracking sales calls or rep activities; only orders, order lines, returns, and compensation are recorded.
- Expected for every persona: **refuse**

## S-U-016: What was revenue in 2023?

- Kind: out_of_range. Why: Orders cover 2024 and 2025 only.
- Second annotator: **refuse**: The sales mart only covers 2024 to 2025, so 2023 revenue data is not available.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.orders WHERE ordered_on < DATE '2024-01-01'` → 0

## S-U-017: How many orders were placed in 2026?

- Kind: out_of_range. Why: Orders end on 31 December 2025.
- Second annotator: **refuse**: The database only covers 2024 to 2025, so it cannot answer questions about 2026.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.orders WHERE ordered_on >= DATE '2026-01-01'` → 0

## S-U-018: What will revenue be in 2026?

- Kind: out_of_range. Why: A forecast, not a fact in the data; forecasting is excluded from the gateway.
- Second annotator: **refuse**: The database only contains data from 2024 to 2025, so it cannot provide revenue for 2026.
- Expected for every persona: **refuse**

## S-U-019: How many orders were placed in March 2020?

- Kind: out_of_range. Why: Orders cover 2024 and 2025 only.
- Second annotator: **refuse**: The sales mart only covers data from 2024 to 2025, so March 2020 is outside the available period.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.orders WHERE ordered_on < DATE '2024-01-01'` → 0

## S-U-020: How much revenue came from customers in Mexico?

- Kind: nonexistent_entity. Why: Mexico is not a country in the data.
- Second annotator: **answer**: The database contains countries (with ISO codes), customers linked to countries, completed orders, and order lines with pricing and discounts needed to calculate revenue for Mexico (country_code 'MX').
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.countries WHERE name ILIKE '%mexico%' OR country_code = 'MX'` → 0

**Disagreement: owner to adjudicate.**

## S-U-021: What was revenue from the Quantum Router in 2025?

- Kind: nonexistent_entity. Why: There is no product of that name.
- Second annotator: **answer**: The schema contains products, order lines with pricing and discounts, orders with dates and status, and returns, enabling a clear revenue calculation for a named product in 2025.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.products WHERE name ILIKE '%quantum%'` → 0

**Disagreement: owner to adjudicate.**

## S-U-022: How many orders did the sales rep John Smith handle?

- Kind: nonexistent_entity. Why: There is no rep of that name.
- Second annotator: **clarify**: The name 'John Smith' may not be unique in sales_reps, so the question is ambiguous about which rep is meant.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.sales_reps WHERE name ILIKE '%john smith%'` → 0

**Disagreement: owner to adjudicate.**

## S-U-023: How much revenue came from Government customers in 2025?

- Kind: nonexistent_entity. Why: Segments are Enterprise, SMB and Consumer only.
- Second annotator: **refuse**: The customers table only has segments Enterprise, SMB, and Consumer; there is no Government segment in the data.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM sales.customers WHERE segment ILIKE '%gov%'` → 0

## S-U-024: Which of our products has the best quality?

- Kind: subjective. Why: Quality is not measured in the data.
- Second annotator: **refuse**: The database does not contain any product quality metrics, ratings, or defect data; 'best quality' is subjective and not defined in the schema.
- Expected for every persona: **refuse**

## S-U-025: How does our 2025 revenue compare with our competitors'?

- Kind: outside_database. Why: There is no competitor data.
- Second annotator: **refuse**: The database contains only internal sales data and has no information about competitors' revenue.
- Expected for every persona: **refuse**
