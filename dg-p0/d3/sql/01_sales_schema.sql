-- D3 mart, sales domain (DG-00.01). Run as a superuser. Recreates schema `sales` from scratch.
-- Every row that belongs to a region carries `region_id` so row-level security stays simple.

DROP SCHEMA IF EXISTS sales CASCADE;
CREATE SCHEMA sales;
COMMENT ON SCHEMA sales IS 'Sales mart: customers, orders, products, returns and sales reps, 2024 to 2025.';

CREATE TABLE sales.regions (
  region_id text PRIMARY KEY,
  name      text NOT NULL
);
COMMENT ON TABLE sales.regions IS 'Sales regions.';

CREATE TABLE sales.countries (
  country_code text PRIMARY KEY,
  name         text NOT NULL,
  region_id    text NOT NULL REFERENCES sales.regions
);
COMMENT ON TABLE sales.countries IS 'Countries and the sales region each belongs to.';
COMMENT ON COLUMN sales.countries.country_code IS 'ISO 3166-1 alpha-2 code.';

CREATE TABLE sales.customers (
  customer_id  integer PRIMARY KEY,
  name         text NOT NULL,
  segment      text NOT NULL CHECK (segment IN ('Enterprise', 'SMB', 'Consumer')),
  country_code text NOT NULL REFERENCES sales.countries,
  region_id    text NOT NULL REFERENCES sales.regions,
  created_on   date NOT NULL
);
COMMENT ON TABLE sales.customers IS 'Customers. One row per customer account.';
COMMENT ON COLUMN sales.customers.segment IS 'Enterprise, SMB (small and medium business) or Consumer.';
COMMENT ON COLUMN sales.customers.created_on IS 'Date the customer account was opened.';

CREATE TABLE sales.products (
  product_id integer PRIMARY KEY,
  name       text NOT NULL,
  category   text NOT NULL CHECK (category IN ('Hardware', 'Software', 'Services', 'Accessories')),
  list_price numeric(12, 2) NOT NULL CHECK (list_price > 0)
);
COMMENT ON TABLE sales.products IS 'Product catalogue. Prices in USD.';
COMMENT ON COLUMN sales.products.list_price IS 'Catalogue price per unit in USD, before discounts.';

CREATE TABLE sales.sales_reps (
  rep_id    integer PRIMARY KEY,
  name      text NOT NULL,
  region_id text NOT NULL REFERENCES sales.regions,
  hired_on  date NOT NULL
);
COMMENT ON TABLE sales.sales_reps IS 'Sales representatives. Each works in one region.';

CREATE TABLE sales.orders (
  order_id    integer PRIMARY KEY,
  customer_id integer NOT NULL REFERENCES sales.customers,
  rep_id      integer NOT NULL REFERENCES sales.sales_reps,
  region_id   text NOT NULL REFERENCES sales.regions,
  ordered_on  date NOT NULL,
  status      text NOT NULL CHECK (status IN ('completed', 'cancelled', 'pending'))
);
COMMENT ON TABLE sales.orders IS 'Sales orders. Only completed orders count as revenue.';
COMMENT ON COLUMN sales.orders.status IS 'completed, cancelled or pending. Cancelled and pending orders are not revenue.';
COMMENT ON COLUMN sales.orders.region_id IS 'Region of the customer, copied from the customer.';

CREATE TABLE sales.order_lines (
  order_id     integer NOT NULL REFERENCES sales.orders,
  line_no      integer NOT NULL,
  product_id   integer NOT NULL REFERENCES sales.products,
  region_id    text NOT NULL REFERENCES sales.regions,
  quantity     integer NOT NULL CHECK (quantity > 0),
  unit_price   numeric(12, 2) NOT NULL CHECK (unit_price > 0),
  discount_pct numeric(5, 2) NOT NULL CHECK (discount_pct >= 0 AND discount_pct < 100),
  PRIMARY KEY (order_id, line_no)
);
COMMENT ON TABLE sales.order_lines IS 'Order lines. Net line amount = quantity * unit_price * (1 - discount_pct / 100).';
COMMENT ON COLUMN sales.order_lines.unit_price IS 'Agreed price per unit in USD, before the line discount.';
COMMENT ON COLUMN sales.order_lines.discount_pct IS 'Line discount in percent (0 to 100).';

CREATE TABLE sales.returns (
  return_id   integer PRIMARY KEY,
  order_id    integer NOT NULL,
  line_no     integer NOT NULL,
  region_id   text NOT NULL REFERENCES sales.regions,
  returned_on date NOT NULL,
  quantity    integer NOT NULL CHECK (quantity > 0),
  reason      text NOT NULL CHECK (reason IN ('damaged', 'wrong_item', 'not_needed', 'late_delivery')),
  FOREIGN KEY (order_id, line_no) REFERENCES sales.order_lines
);
COMMENT ON TABLE sales.returns IS 'Returned units against an order line.';

CREATE TABLE sales.rep_compensation (
  rep_id      integer NOT NULL REFERENCES sales.sales_reps,
  year        integer NOT NULL,
  region_id   text NOT NULL REFERENCES sales.regions,
  base_salary numeric(12, 2) NOT NULL,
  commission  numeric(12, 2) NOT NULL,
  PRIMARY KEY (rep_id, year)
);
COMMENT ON TABLE sales.rep_compensation IS 'Confidential. Yearly pay per sales rep in USD. Managers only.';
