# Batch skills-05: owner review

25 questions, 21 agree on every persona, 4 to adjudicate.

## K-U-001: What is the average salary of Engineers?

- Kind: missing_data. Why: The skills data holds no pay; only sales reps' pay exists, in another table.
- Second annotator: **refuse**: The database schema contains no salary or compensation data for employees.
- Expected for every persona: **refuse**

## K-U-002: How many training hours did each employee complete in 2025?

- Kind: missing_data. Why: There is no training data.
- Second annotator: **refuse**: The database schema does not contain any table or column tracking employee training hours.
- Expected for every persona: **refuse**

## K-U-003: What is the age distribution of current employees?

- Kind: missing_data. Why: Employees have no birth date or age.
- Second annotator: **refuse**: The database does not contain employee birth dates or ages, only hire dates.
- Expected for every persona: **refuse**

## K-U-004: What is the gender split in each department?

- Kind: missing_data. Why: Employees have no gender recorded.
- Second annotator: **refuse**: The database schema does not include a gender column in any table, so gender split cannot be determined.
- Expected for every persona: **refuse**

## K-U-005: When was each employee last promoted?

- Kind: missing_data. Why: Only the current level is stored, not its history.
- Second annotator: **refuse**: The database stores only current job_title and level with no history of when promotions occurred.
- Expected for every persona: **refuse**

## K-U-006: How many sick days did employees take in 2025?

- Kind: missing_data. Why: There is no absence data.
- Second annotator: **refuse**: The database does not contain any sick leave or attendance data to answer this question.
- Expected for every persona: **refuse**

## K-U-007: What was the employee engagement score in 2025?

- Kind: missing_data. Why: There is no engagement survey data.
- Second annotator: **refuse**: The database contains skill assessment scores but no employee engagement scores or engagement survey data.
- Expected for every persona: **refuse**

## K-U-008: Which projects is each Consultant assigned to?

- Kind: missing_data. Why: There is no project data.
- Second annotator: **refuse**: The database schema contains no tables or columns related to projects or project assignments for consultants.
- Expected for every persona: **refuse**

## K-U-009: How many billable hours did Consultants log in 2025?

- Kind: missing_data. Why: There is no time-tracking data.
- Second annotator: **refuse**: The database schema contains no tables or columns for tracking billable hours, time logs, or project work; it only covers skill assessments, employees, certifications, and related metadata.
- Expected for every persona: **refuse**

## K-U-010: Which city does each employee work in?

- Kind: missing_data. Why: Employees have a region, not a city.
- Second annotator: **refuse**: The database schema contains no city information for employees; only region_id references exist, with no city column in any table.
- Expected for every persona: **refuse**

## K-U-011: Why did employees leave in 2025?

- Kind: missing_data. Why: Leavers have a leaving date but no reason.
- Second annotator: **refuse**: The database tracks when employees left (left_on date) but does not store any reason or cause for departure.
- Expected for every persona: **refuse**

## K-U-012: How much did the company spend on certifications in 2025?

- Kind: missing_data. Why: Certifications have no cost.
- Second annotator: **refuse**: The certifications table tracks issuance and expiration dates but contains no cost or spending data.
- Expected for every persona: **refuse**

## K-U-013: Which languages does each employee speak?

- Kind: missing_data. Why: There is no language data.
- Second annotator: **refuse**: The database schema contains no tables or columns for employee spoken languages or language proficiency.
- Expected for every persona: **refuse**

## K-U-014: What were the average scores in the 2023 assessment cycles?

- Kind: out_of_range. Why: Cycles run from 2024-H1 to 2025-H2.
- Second annotator: **refuse**: The database only contains assessment cycles from 2024 to 2025, not 2023.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.assessment_cycles WHERE starts_on < DATE '2024-01-01'` → 0

## K-U-015: What were the results of the 2026-H1 assessments?

- Kind: out_of_range. Why: Cycles end with 2025-H2.
- Second annotator: **refuse**: The schema comment states data covers 2024 to 2025, so 2026-H1 assessments are outside the period covered.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.assessment_cycles WHERE starts_on >= DATE '2026-01-01'` → 0

## K-U-016: What scores will employees get in the next cycle?

- Kind: out_of_range. Why: A forecast, not a fact in the data; forecasting is excluded from the gateway.
- Second annotator: **refuse**: The database only contains historical assessment scores up to 2025 and does not store future or predicted scores for upcoming cycles.
- Expected for every persona: **refuse**

## K-U-017: How many employees were hired in 2026?

- Kind: out_of_range. Why: Hiring dates end in 2025.
- Second annotator: **refuse**: The schema comment states the data covers 2024 to 2025, so 2026 hires are outside the period covered.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.employees WHERE hired_on >= DATE '2026-01-01'` → 0

## K-U-018: How many employees were assessed on Rust in 2025?

- Kind: nonexistent_entity. Why: Rust is not a skill in the data.
- Second annotator: **answer**: The schema contains skills, assessments, and assessment_cycles tables with all necessary columns to count employees assessed on a specific skill during a specific year.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.skills WHERE name ILIKE '%rust%'` → 0

**Disagreement: owner to adjudicate.**

## K-U-019: How many people work in the Marketing department?

- Kind: nonexistent_entity. Why: There is no Marketing department.
- Second annotator: **clarify**: The question does not specify whether to count only current employees (left_on IS NULL) or all employees ever assigned, and it assumes a department named 'Marketing' exists in the skills.departments table.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.departments WHERE name ILIKE '%marketing%'` → 0

**Disagreement: owner to adjudicate.**

## K-U-020: How many employees hold a CISSP certification?

- Kind: nonexistent_entity. Why: CISSP is not a certification in the data.
- Second annotator: **answer**: The certifications table contains a name column that can be filtered for 'CISSP' and linked to employees, allowing a direct count of distinct employees holding that certification.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.certifications WHERE name ILIKE '%cissp%'` → 0

**Disagreement: owner to adjudicate.**

## K-U-021: What were Jane Doe's scores in 2025-H2?

- Kind: nonexistent_entity. Why: There is no employee of that name.
- Second annotator: **answer**: The database contains employees, assessment cycles, assessments, and skills tables, allowing retrieval of Jane Doe's scores for the 2025-H2 cycle if she exists and the cycle exists.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.employees WHERE name ILIKE '%jane doe%'` → 0

**Disagreement: owner to adjudicate.**

## K-U-022: How many Directors are there?

- Kind: nonexistent_entity. Why: Job titles are Engineer, Analyst, Consultant, Team Lead and Manager only.
- Second annotator: **refuse**: The employees table only defines job titles Engineer, Analyst, Consultant, Team Lead, and Manager; there is no Director role in the data.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.employees WHERE job_title ILIKE '%director%'` → 0

## K-U-023: Who is our most talented engineer?

- Kind: subjective. Why: Talent is a judgement; the data holds skill scores, not talent.
- Second annotator: **refuse**: The question asks for a subjective judgment ('most talented') with no defined metric in the database, making it a matter of opinion rather than a query the data can answer.
- Expected for every persona: **refuse**

## K-U-024: Which skill matters most to the company?

- Kind: subjective. Why: Importance is a judgement the data does not record.
- Second annotator: **refuse**: The database contains skill definitions, assessments, and role targets but no data indicating business importance, strategic priority, or any objective measure to determine which skill matters most to the company.
- Expected for every persona: **refuse**

## K-U-025: How do our engineers' Python skills compare with the industry average?

- Kind: outside_database. Why: There is no external benchmark data.
- Second annotator: **refuse**: The database contains internal skill assessments and role targets but has no industry average benchmarks or external comparison data.
- Expected for every persona: **refuse**
