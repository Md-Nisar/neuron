# DG-00.05 Ossie round trip

```json
{
 "ao_export_validates_as_exported": "failed: Semantic checks skipped until schema errors are fixed.",
 "ao_export_validates_after_to03": "passed",
 "hand_validates": "passed",
 "hand_import_as_d3": "500: duplicate key uq_catalog_database_name (recorded, not retried)",
 "relationships_not_importable": [
  "assessments_to_assessor"
 ],
 "hand_import": {
  "success": true,
  "summary": {
   "database_ids": [
    "14a90512-dee7-40df-8d74-1a2fd268d5a5"
   ],
   "created": {
    "databases": 0,
    "schemas": 0,
    "tables": 0,
    "columns": 0,
    "terms": 0,
    "column_attributes": 0,
    "sql_attributes": 0,
    "custom_analyses": 0
   },
   "skipped": {
    "databases": 1,
    "schemas": 2,
    "tables": 15,
    "columns": 76,
    "terms": 15,
    "column_attributes": 75,
    "sql_attributes": 2,
    "custom_analyses": 3
   },
   "replace": true,
   "terms": 15,
   "column_attributes": 75,
   "semantic_fks": 20,
   "sql_attributes": 2,
   "custom_analyses": 3,
   "pending_embed": {
    "data_rows": 0,
    "semantic_rows": 0
   },
   "format": "ossie",
   "embeddings": {
    "skipped": false,
    "data_rows": 0,
    "semantic_rows": 0
   }
  }
 },
 "hand_back_validates": "passed",
 "hand_certified_after_import": {
  "terms": 15,
  "terms_name_certified": 0,
  "sql_attributes": 2,
  "sql_attributes_certified": 0
 },
 "a2_import": {
  "success": true,
  "summary": {
   "database_ids": [
    "3548e520-b5ec-49c5-93f2-a2ab9e319949"
   ],
   "created": {
    "databases": 0,
    "schemas": 0,
    "tables": 0,
    "columns": 0,
    "terms": 0,
    "column_attributes": 0,
    "sql_attributes": 0,
    "custom_analyses": 0
   },
   "skipped": {
    "databases": 1,
    "schemas": 3,
    "tables": 16,
    "columns": 77,
    "terms": 16,
    "column_attributes": 51,
    "sql_attributes": 13,
    "custom_analyses": 0
   },
   "replace": true,
   "terms": 16,
   "column_attributes": 51,
   "semantic_fks": 26,
   "sql_attributes": 13,
   "custom_analyses": 0,
   "pending_embed": {
    "data_rows": 0,
    "semantic_rows": 0
   },
   "format": "ossie",
   "embeddings": {
    "skipped": false,
    "data_rows": 0,
    "semantic_rows": 0
   }
  }
 },
 "a2_back_validates": "passed",
 "a2_certified_after_import": {
  "terms": 16,
  "terms_name_certified": 0,
  "sql_attributes": 13,
  "sql_attributes_certified": 0
 },
 "hand_roundtrip": {
  "fields kept": 77,
  "metrics kept": 3,
  "metrics lost": 9
 },
 "ao_roundtrip": {
  "fields kept": 90
 }
}
```

## Hand-written D3 model -> Auto Ontology -> Ossie

| Kind | Table | Name | Outcome | Source expression | Came back as |
| --- | --- | --- | --- | --- | --- |
| field | sales.countries | country_code | kept | `country_code` | `country_code` |
| field | sales.countries | country_name | kept | `name` | `name` |
| field | sales.countries | region_id | kept | `region_id` | `region_id` |
| field | sales.customers | country_code | kept | `country_code` | `country_code` |
| field | sales.customers | created_on | kept | `created_on` | `created_on` |
| field | sales.customers | customer_id | kept | `customer_id` | `customer_id` |
| field | sales.customers | customer_name | kept | `name` | `name` |
| field | sales.customers | region_id | kept | `region_id` | `region_id` |
| field | sales.customers | segment | kept | `segment` | `segment` |
| field | sales.order_lines | discount_pct | kept | `discount_pct` | `discount_pct` |
| field | sales.order_lines | line_no | kept | `line_no` | `line_no` |
| field | sales.order_lines | net_amount | kept | `quantity * unit_price *(1 - discount_pct / 100)` | `quantity * unit_price *(1 - discount_pct / 100)` |
| field | sales.order_lines | order_id | kept | `order_id` | `order_id` |
| field | sales.order_lines | product_id | kept | `product_id` | `product_id` |
| field | sales.order_lines | quantity | kept | `quantity` | `quantity` |
| field | sales.order_lines | region_id | kept | `region_id` | `region_id` |
| field | sales.order_lines | unit_price | kept | `unit_price` | `unit_price` |
| field | sales.orders | customer_id | kept | `customer_id` | `customer_id` |
| field | sales.orders | order_id | kept | `order_id` | `order_id` |
| field | sales.orders | ordered_on | kept | `ordered_on` | `ordered_on` |
| field | sales.orders | region_id | kept | `region_id` | `region_id` |
| field | sales.orders | rep_id | kept | `rep_id` | `rep_id` |
| field | sales.orders | status | kept | `status` | `status` |
| field | sales.products | category | kept | `category` | `category` |
| field | sales.products | list_price | kept | `list_price` | `list_price` |
| field | sales.products | product_id | kept | `product_id` | `product_id` |
| field | sales.products | product_name | kept | `name` | `name` |
| field | sales.regions | region_id | kept | `region_id` | `region_id` |
| field | sales.regions | region_name | kept | `name` | `name` |
| field | sales.returns | line_no | kept | `line_no` | `line_no` |
| field | sales.returns | order_id | kept | `order_id` | `order_id` |
| field | sales.returns | reason | kept | `reason` | `reason` |
| field | sales.returns | region_id | kept | `region_id` | `region_id` |
| field | sales.returns | return_id | kept | `return_id` | `return_id` |
| field | sales.returns | returned_on | kept | `returned_on` | `returned_on` |
| field | sales.returns | returned_quantity | kept | `quantity` | `quantity` |
| field | sales.sales_reps | hired_on | kept | `hired_on` | `hired_on` |
| field | sales.sales_reps | region_id | kept | `region_id` | `region_id` |
| field | sales.sales_reps | rep_id | kept | `rep_id` | `rep_id` |
| field | sales.sales_reps | rep_name | kept | `name` | `name` |
| field | skills.assessment_cycles | cycle_id | kept | `cycle_id` | `cycle_id` |
| field | skills.assessment_cycles | cycle_name | kept | `name` | `name` |
| field | skills.assessment_cycles | ends_on | kept | `ends_on` | `ends_on` |
| field | skills.assessment_cycles | starts_on | kept | `starts_on` | `starts_on` |
| field | skills.assessments | assessed_on | kept | `assessed_on` | `assessed_on` |
| field | skills.assessments | assessment_id | kept | `assessment_id` | `assessment_id` |
| field | skills.assessments | assessor_id | kept | `assessor_id` | `assessor_id` |
| field | skills.assessments | cycle_id | kept | `cycle_id` | `cycle_id` |
| field | skills.assessments | employee_id | kept | `employee_id` | `employee_id` |
| field | skills.assessments | region_id | kept | `region_id` | `region_id` |
| field | skills.assessments | score | kept | `score` | `score` |
| field | skills.assessments | skill_id | kept | `skill_id` | `skill_id` |
| field | skills.certifications | certification_id | kept | `certification_id` | `certification_id` |
| field | skills.certifications | certification_name | kept | `name` | `name` |
| field | skills.certifications | employee_id | kept | `employee_id` | `employee_id` |
| field | skills.certifications | expires_on | kept | `expires_on` | `expires_on` |
| field | skills.certifications | issued_on | kept | `issued_on` | `issued_on` |
| field | skills.certifications | region_id | kept | `region_id` | `region_id` |
| field | skills.departments | department_id | kept | `department_id` | `department_id` |
| field | skills.departments | department_name | kept | `name` | `name` |
| field | skills.departments | region_id | kept | `region_id` | `region_id` |
| field | skills.employees | department_id | kept | `department_id` | `department_id` |
| field | skills.employees | employee_id | kept | `employee_id` | `employee_id` |
| field | skills.employees | employee_name | kept | `name` | `name` |
| field | skills.employees | hired_on | kept | `hired_on` | `hired_on` |
| field | skills.employees | is_current | kept | `left_on is null` | `left_on is null` |
| field | skills.employees | job_title | kept | `job_title` | `job_title` |
| field | skills.employees | left_on | kept | `left_on` | `left_on` |
| field | skills.employees | level | kept | `level` | `level` |
| field | skills.employees | manager_id | kept | `manager_id` | `manager_id` |
| field | skills.employees | region_id | kept | `region_id` | `region_id` |
| field | skills.role_targets | job_title | kept | `job_title` | `job_title` |
| field | skills.role_targets | skill_id | kept | `skill_id` | `skill_id` |
| field | skills.role_targets | target_score | kept | `target_score` | `target_score` |
| field | skills.skills | skill_category | kept | `category` | `category` |
| field | skills.skills | skill_id | kept | `skill_id` | `skill_id` |
| field | skills.skills | skill_name | kept | `name` | `name` |
| metric | (model) | average_order_value | kept | `sum(order_lines.net_amount)filter(where orders.status = 'completed')/ count(dist` | `sum(order_lines.net_amount)filter(where orders.status = 'completed')/ count(dist` |
| metric | (model) | revenue | kept | `sum(order_lines.net_amount)filter(where orders.status = 'completed')` | `sum(order_lines.net_amount)filter(where orders.status = 'completed')` |
| metric | (model) | units_sold | kept | `sum(order_lines.quantity)filter(where orders.status = 'completed')` | `sum(order_lines.quantity)filter(where orders.status = 'completed')` |
| metric | sales.customers | customer_count | lost | `count(customer_id)` | `` |
| metric | sales.orders | completed_order_count | lost | `count(order_id)filter(where status = 'completed')` | `` |
| metric | sales.orders | order_count | lost | `count(order_id)` | `` |
| metric | sales.returns | returned_units | lost | `sum(returned_quantity)` | `` |
| metric | skills.assessments | assessment_count | lost | `count(assessment_id)` | `` |
| metric | skills.assessments | average_score | lost | `avg(score)` | `` |
| metric | skills.certifications | certification_count | lost | `count(certification_id)` | `` |
| metric | skills.employees | headcount | lost | `count(employee_id)filter(where is_current)` | `` |
| metric | skills.employees | leavers | lost | `count(employee_id)filter(where not is_current)` | `` |

## Auto Ontology A2 -> Ossie 0.3 -> Auto Ontology -> Ossie

| Kind | Table | Name | Outcome | Source expression | Came back as |
| --- | --- | --- | --- | --- | --- |
| field | app.role_regions | region_id | kept | `region_id` | `region_id` |
| field | app.role_regions | role_name | kept | `role_name` | `role_name` |
| field | sales.countries | country_code | kept | `country_code` | `country_code` |
| field | sales.countries | country_name | kept | `name` | `name` |
| field | sales.countries | region_id | kept | `region_id` | `region_id` |
| field | sales.customers | country_code | kept | `country_code` | `country_code` |
| field | sales.customers | created_on | kept | `created_on` | `created_on` |
| field | sales.customers | customer_count | kept | `count(c.customer_id)` | `count(c.customer_id)` |
| field | sales.customers | customer_id | kept | `customer_id` | `customer_id` |
| field | sales.customers | name | kept | `name` | `name` |
| field | sales.customers | region_id | kept | `region_id` | `region_id` |
| field | sales.customers | segment | kept | `segment` | `segment` |
| field | sales.order_lines | discount_percentage | kept | `discount_pct` | `discount_pct` |
| field | sales.order_lines | line_number | kept | `line_no` | `line_no` |
| field | sales.order_lines | net_amount | kept | `l.quantity * l.unit_price *(1 - l.discount_pct / 100)` | `l.quantity * l.unit_price *(1 - l.discount_pct / 100)` |
| field | sales.order_lines | order_id | kept | `order_id` | `order_id` |
| field | sales.order_lines | product_id | kept | `product_id` | `product_id` |
| field | sales.order_lines | quantity | kept | `quantity` | `quantity` |
| field | sales.order_lines | region_id | kept | `region_id` | `region_id` |
| field | sales.order_lines | unit_price | kept | `unit_price` | `unit_price` |
| field | sales.order_lines | units_sold | kept | `sum(l.quantity)` | `sum(l.quantity)` |
| field | sales.orders | average_order_value | kept | `sum(l.quantity * l.unit_price *(1 - l.discount_pct / 100))/ count(distinct o.ord` | `sum(l.quantity * l.unit_price *(1 - l.discount_pct / 100))/ count(distinct o.ord` |
| field | sales.orders | completed_order_count | kept | `count(o.order_id)` | `count(o.order_id)` |
| field | sales.orders | customer_id | kept | `customer_id` | `customer_id` |
| field | sales.orders | order_count | kept | `count(o.order_id)` | `count(o.order_id)` |
| field | sales.orders | order_id | kept | `order_id` | `order_id` |
| field | sales.orders | ordered_on | kept | `ordered_on` | `ordered_on` |
| field | sales.orders | region_id | kept | `region_id` | `region_id` |
| field | sales.orders | rep_id | kept | `rep_id` | `rep_id` |
| field | sales.orders | revenue | kept | `sum(l.quantity * l.unit_price *(1 - l.discount_pct / 100))` | `sum(l.quantity * l.unit_price *(1 - l.discount_pct / 100))` |
| field | sales.orders | status | kept | `status` | `status` |
| field | sales.products | category | kept | `category` | `category` |
| field | sales.products | list_price | kept | `list_price` | `list_price` |
| field | sales.products | name | kept | `name` | `name` |
| field | sales.products | product_id | kept | `product_id` | `product_id` |
| field | sales.regions | region_id | kept | `region_id` | `region_id` |
| field | sales.regions | region_name | kept | `name` | `name` |
| field | sales.returns | line_no | kept | `line_no` | `line_no` |
| field | sales.returns | order_id | kept | `order_id` | `order_id` |
| field | sales.returns | quantity | kept | `quantity` | `quantity` |
| field | sales.returns | reason | kept | `reason` | `reason` |
| field | sales.returns | region_id | kept | `region_id` | `region_id` |
| field | sales.returns | return_id | kept | `return_id` | `return_id` |
| field | sales.returns | returned_on | kept | `returned_on` | `returned_on` |
| field | sales.returns | returned_units | kept | `sum(r.quantity)` | `sum(r.quantity)` |
| field | sales.sales_reps | hired_on | kept | `hired_on` | `hired_on` |
| field | sales.sales_reps | name | kept | `name` | `name` |
| field | sales.sales_reps | region_id | kept | `region_id` | `region_id` |
| field | sales.sales_reps | rep_id | kept | `rep_id` | `rep_id` |
| field | skills.assessment_cycles | cycle_id | kept | `cycle_id` | `cycle_id` |
| field | skills.assessment_cycles | ends_on | kept | `ends_on` | `ends_on` |
| field | skills.assessment_cycles | name | kept | `name` | `name` |
| field | skills.assessment_cycles | starts_on | kept | `starts_on` | `starts_on` |
| field | skills.assessments | assessed_on | kept | `assessed_on` | `assessed_on` |
| field | skills.assessments | assessment_count | kept | `count(a.assessment_id)` | `count(a.assessment_id)` |
| field | skills.assessments | assessment_id | kept | `assessment_id` | `assessment_id` |
| field | skills.assessments | assessor_id | kept | `assessor_id` | `assessor_id` |
| field | skills.assessments | average_score | kept | `avg(a.score)` | `avg(a.score)` |
| field | skills.assessments | cycle_id | kept | `cycle_id` | `cycle_id` |
| field | skills.assessments | employee_id | kept | `employee_id` | `employee_id` |
| field | skills.assessments | region_id | kept | `region_id` | `region_id` |
| field | skills.assessments | score | kept | `score` | `score` |
| field | skills.assessments | skill_id | kept | `skill_id` | `skill_id` |
| field | skills.certifications | certification_count | kept | `count(c.certification_id)` | `count(c.certification_id)` |
| field | skills.certifications | certification_id | kept | `certification_id` | `certification_id` |
| field | skills.certifications | employee_id | kept | `employee_id` | `employee_id` |
| field | skills.certifications | expires_on | kept | `expires_on` | `expires_on` |
| field | skills.certifications | issued_on | kept | `issued_on` | `issued_on` |
| field | skills.certifications | name | kept | `name` | `name` |
| field | skills.certifications | region_id | kept | `region_id` | `region_id` |
| field | skills.departments | department_id | kept | `department_id` | `department_id` |
| field | skills.departments | department_name | kept | `name` | `name` |
| field | skills.departments | region_id | kept | `region_id` | `region_id` |
| field | skills.employees | department_id | kept | `department_id` | `department_id` |
| field | skills.employees | employee_id | kept | `employee_id` | `employee_id` |
| field | skills.employees | headcount | kept | `count(e.employee_id)` | `count(e.employee_id)` |
| field | skills.employees | hired_on | kept | `hired_on` | `hired_on` |
| field | skills.employees | job_title | kept | `job_title` | `job_title` |
| field | skills.employees | leavers | kept | `count(e.employee_id)` | `count(e.employee_id)` |
| field | skills.employees | left_on | kept | `left_on` | `left_on` |
| field | skills.employees | level | kept | `level` | `level` |
| field | skills.employees | manager_id | kept | `manager_id` | `manager_id` |
| field | skills.employees | name | kept | `name` | `name` |
| field | skills.employees | region_id | kept | `region_id` | `region_id` |
| field | skills.role_targets | job_title | kept | `job_title` | `job_title` |
| field | skills.role_targets | skill_id | kept | `skill_id` | `skill_id` |
| field | skills.role_targets | target_score | kept | `target_score` | `target_score` |
| field | skills.skills | skill_category | kept | `category` | `category` |
| field | skills.skills | skill_id | kept | `skill_id` | `skill_id` |
| field | skills.skills | skill_name | kept | `name` | `name` |
