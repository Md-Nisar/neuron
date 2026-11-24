# Batch fresh-skills-u: owner review

20 questions, 14 agree on every persona, 6 to adjudicate.

## K-FU-01: How many employees were assessed on Java in the 2025-H2 cycle?

- Kind: nonexistent_entity. Why: Java is not a skill in the data.
- Second annotator: **answer**: The database contains skills, assessment cycles, and assessments tables that can be joined to count employees assessed on Java in the 2025-H2 cycle.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.skills WHERE name ILIKE '%java%'` → 0

**Disagreement: owner to adjudicate.**

## K-FU-02: How many employees hold the AWS Certified Developer certification?

- Kind: nonexistent_entity. Why: There is no certification of that name.
- Second annotator: **clarify**: The question does not specify whether to count only currently valid certifications (expires_on is null or in the future) or all certifications ever issued, and the certifications table includes expiration dates that would change the result.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.certifications WHERE name ILIKE '%aws%' OR name ILIKE '%developer%'` → 0

**Disagreement: owner to adjudicate.**

## K-FU-03: How many current employees work in the Legal department?

- Kind: nonexistent_entity. Why: There is no Legal department.
- Second annotator: **answer**: The schema contains departments with names, employees linked to departments with hire/leave dates, so counting current (left_on IS NULL) employees in the department named 'Legal' is a single well-defined query.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.departments WHERE name ILIKE '%legal%'` → 0

**Disagreement: owner to adjudicate.**

## K-FU-04: How many employees have the job title Director?

- Kind: nonexistent_entity. Why: Job titles are Engineer, Analyst, Consultant, Team Lead and Manager.
- Second annotator: **answer**: The employees table has a job_title column with a CHECK constraint limiting values to Engineer, Analyst, Consultant, Team Lead, Manager; Director is not a permitted value, so the count is zero and the database can answer definitively.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.employees WHERE job_title ILIKE '%director%'` → 0

**Disagreement: owner to adjudicate.**

## K-FU-05: How many employees report directly to Maria Gonzalez?

- Kind: nonexistent_entity. Why: There is no employee called Maria Gonzalez.
- Second annotator: **clarify**: The name "Maria Gonzalez" may not be unique in the employees table, so the question is ambiguous without further identification such as employee_id or department.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.employees WHERE name ILIKE '%gonzalez%' OR name ILIKE 'maria %'` → 0

**Disagreement: owner to adjudicate.**

## K-FU-06: What was the average score in the 2023-H2 assessment cycle?

- Kind: nonexistent_entity. Why: There is no 2023-H2 cycle; cycles run from 2024-H1 to 2025-H2.
- Second annotator: **refuse**: The database only covers assessment cycles from 2024 to 2025, so 2023-H2 is outside the period covered.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.assessment_cycles WHERE name ILIKE '2023%'` → 0

## K-FU-07: How many employees hold the CompTIA Network+ certification?

- Kind: nonexistent_entity. Why: There is no certification of that name.
- Second annotator: **answer**: The certifications table stores certification names and employee_id, so a count of distinct employees with name = 'CompTIA Network+' can be computed directly.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.certifications WHERE name ILIKE '%comptia%' OR name ILIKE '%network+%'` → 0

**Disagreement: owner to adjudicate.**

## K-FU-08: What bonus did each Manager receive in 2025?

- Kind: missing_data. Why: The skills data holds no pay or bonus.
- Second annotator: **refuse**: The database schema contains no tables or columns related to employee bonuses or compensation.
- Expected for every persona: **refuse**

## K-FU-09: How many days of annual leave did each employee take in 2025?

- Kind: missing_data. Why: There is no leave or absence data.
- Second annotator: **refuse**: The database schema contains no tables or columns for tracking employee leave or vacation days.
- Expected for every persona: **refuse**

## K-FU-10: Which languages does each employee speak?

- Kind: missing_data. Why: Languages are not recorded; no skill is a language.
- Second annotator: **refuse**: The database schema contains no tables or columns for employee spoken languages or language proficiency.
- Expected for every persona: **refuse**

## K-FU-11: How many hours did Consultants bill to clients in 2025?

- Kind: missing_data. Why: There is no time or billing data.
- Second annotator: **refuse**: The database tracks employee skill assessments and certifications, not billable hours or client billing data.
- Expected for every persona: **refuse**

## K-FU-12: How many employees completed the mandatory compliance training?

- Kind: missing_data. Why: There is no training data.
- Second annotator: **refuse**: The database schema contains no tables or columns related to compliance training or training completion records.
- Expected for every persona: **refuse**

## K-FU-13: What is the home city of each current employee?

- Kind: missing_data. Why: Employees have a region, not a city.
- Second annotator: **refuse**: The database schema contains no city column for employees; only region_id is stored, and the referenced sales.regions table is not defined here.
- Expected for every persona: **refuse**

## K-FU-14: How many assessments were carried out in 2023?

- Kind: out_of_range. Why: Assessments run from May 2024 to December 2025.
- Second annotator: **refuse**: The database only covers assessment cycles from 2024 to 2025, so it cannot answer questions about 2023.
- Expected for every persona: **refuse**

## K-FU-15: How many people were hired in 2014?

- Kind: out_of_range. Why: Hiring dates start in January 2015.
- Second annotator: **refuse**: The database covers assessment cycles from 2024 to 2025 and may not contain complete hiring records for 2014, which is outside the stated period.
- Expected for every persona: **refuse**

## K-FU-16: What will the average DevOps score be in 2026-H2?

- Kind: out_of_range. Why: A forecast, not a fact in the data; forecasting is excluded from the gateway.
- Second annotator: **refuse**: The database only covers assessment cycles from 2024 to 2025 and cannot predict future scores for 2026-H2.
- Expected for every persona: **refuse**

## K-FU-17: How many employees were assessed in 2027?

- Kind: out_of_range. Why: Assessments end in December 2025.
- Second annotator: **refuse**: The database only covers assessment data from 2024 to 2025, so it cannot answer questions about 2027.
- Expected for every persona: **refuse**

## K-FU-18: Which employee has the most leadership potential?

- Kind: subjective. Why: Potential is a judgement; the data holds skill scores.
- Second annotator: **refuse**: Leadership potential is a subjective judgment not directly stored or defined in the database.
- Expected for every persona: **refuse**

## K-FU-19: Which department has the best team spirit?

- Kind: subjective. Why: Team spirit is not recorded in the data.
- Second annotator: **refuse**: Team spirit is a subjective opinion not captured by any metric in the database.
- Expected for every persona: **refuse**

## K-FU-20: How many employees does our largest competitor have?

- Kind: outside_database. Why: There is no competitor data.
- Second annotator: **refuse**: The database only contains internal employee skill assessment data and has no information about competitors or their employee counts.
- Expected for every persona: **refuse**
