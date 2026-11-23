# Batch skills-06: owner review

25 questions, 24 agree on every persona, 1 to adjudicate.

## K-U-026: Which employees are likely to leave next year?

- Kind: out_of_range. Why: A prediction, not a fact in the data; forecasting is excluded from the gateway.
- Second annotator: **refuse**: The database contains historical employment and assessment data but no predictive indicators or models to determine which employees are likely to leave next year.
- Expected for every persona: **refuse**

## K-U-027: How many employees work remotely?

- Kind: missing_data. Why: There is no work-location or remote-working data.
- Second annotator: **refuse**: The database does not contain any information about employees' remote work status.
- Expected for every persona: **refuse**

## K-U-028: What is the average time between promotions?

- Kind: missing_data. Why: Only the current level is stored, not its history.
- Second annotator: **refuse**: The database does not store promotion history or level change dates, only current employee level and hire date.
- Expected for every persona: **refuse**

## K-U-029: How many employees passed the Azure Fundamentals certification?

- Kind: nonexistent_entity. Why: There is no certification of that name.
- Second annotator: **answer**: The certifications table stores certification names and employee IDs, so we can count employees with a certification named 'Azure Fundamentals'.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.certifications WHERE name ILIKE '%azure%'` → 0

**Disagreement: owner to adjudicate.**

## K-U-030: What was the average score in 2022?

- Kind: out_of_range. Why: Cycles run from 2024-H1 to 2025-H2.
- Second annotator: **refuse**: The database only contains assessment data from 2024 to 2025, not 2022.
- Expected for every persona: **refuse**
- Evidence (must be 0): `SELECT count(*) FROM skills.assessments WHERE assessed_on < DATE '2024-01-01'` → 0

## K-M-001: How many employees do we have?

- Kind: ambiguous. Why: Current employees only, or everyone in the data including people who have left.
- Second annotator: **clarify**: The question could mean current employees (left_on IS NULL) or all employees ever hired, which would give different counts.
- Expected for every persona: **clarify**

Reading 1, Current employees:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL
```
- emea_analyst: employees → 65
- apac_analyst: employees → 73
- global_manager: employees → 213

Reading 2, Everyone, including leavers:
```sql
SELECT count(*) AS employees FROM skills.employees
```
- emea_analyst: employees → 77
- apac_analyst: employees → 82
- global_manager: employees → 242

## K-M-002: What is the average assessment score?

- Kind: ambiguous. Why: The latest cycle (2025-H2), or all cycles together.
- Second annotator: **clarify**: The question does not specify the grouping, time period, or population (e.g., all assessments, current employees, latest cycle, per skill, per region), so multiple reasonable interpretations exist.
- Expected for every persona: **clarify**

Reading 1, 2025-H2 only:
```sql
SELECT round(avg(score), 2) AS avg_score FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
- emea_analyst: avg_score → 3.8
- apac_analyst: avg_score → 3.8
- global_manager: avg_score → 3.84

Reading 2, All cycles:
```sql
SELECT round(avg(score), 2) AS avg_score FROM skills.assessments
```
- emea_analyst: avg_score → 3.74
- apac_analyst: avg_score → 3.69
- global_manager: avg_score → 3.74

## K-M-003: How many employees are skilled in Python?

- Kind: ambiguous. Why: "Skilled" is not defined: proficient or better (3+), or advanced or better (4+), in the latest cycle.
- Second annotator: **clarify**: The term 'skilled' is ambiguous: it could mean any assessment for Python, a minimum score threshold, a certification, or meeting role targets, and the relevant assessment cycle is not specified.
- Expected for every persona: **clarify**

Reading 1, Score 3 or more in 2025-H2:
```sql
SELECT count(*) AS employees FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE s.name = 'Python' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND a.score >= 3
```
- emea_analyst: employees → 20
- apac_analyst: employees → 16
- global_manager: employees → 60

Reading 2, Score 4 or more in 2025-H2:
```sql
SELECT count(*) AS employees FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE s.name = 'Python' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND a.score >= 4
```
- emea_analyst: employees → 10
- apac_analyst: employees → 9
- global_manager: employees → 33

## K-M-005: What was the average score in H1?

- Kind: ambiguous. Why: The year is missing: 2024-H1 or 2025-H1.
- Second annotator: **clarify**: The question does not specify which year's H1 cycle (e.g., 2024-H1 vs 2025-H1) nor what grouping the average should be computed over (all assessments, per employee, per skill, etc.).
- Expected for every persona: **clarify**

Reading 1, 2024-H1:
```sql
SELECT round(avg(score), 2) AS avg_score FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2024-H1')
```
- emea_analyst: avg_score → 3.65
- apac_analyst: avg_score → 3.55
- global_manager: avg_score → 3.62

Reading 2, 2025-H1:
```sql
SELECT round(avg(score), 2) AS avg_score FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H1')
```
- emea_analyst: avg_score → 3.75
- apac_analyst: avg_score → 3.7
- global_manager: avg_score → 3.77

## K-M-007: How many senior employees are there?

- Kind: ambiguous. Why: "Senior" is not defined: career level 4 or 5, or level 5 only (current employees).
- Second annotator: **clarify**: The term 'senior' is ambiguous: it could refer to career level (e.g., level 4–5), job title (e.g., Team Lead, Manager), or a combination, and the schema does not define a single 'senior' flag.
- Expected for every persona: **clarify**

Reading 1, Level 4 or 5:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND level >= 4
```
- emea_analyst: employees → 28
- apac_analyst: employees → 39
- global_manager: employees → 104

Reading 2, Level 5 only:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND level = 5
```
- emea_analyst: employees → 13
- apac_analyst: employees → 13
- global_manager: employees → 44

## K-M-008: How did Python scores change?

- Kind: ambiguous. Why: Over which period: from the first cycle (2024-H1) or from the previous cycle (2025-H1) to 2025-H2; average change for employees assessed in both.
- Second annotator: **clarify**: The question does not specify over what dimension (time, employee, department, region) or what kind of change (trend, difference from target, distribution shift) is meant by 'how did Python scores change'.
- Expected for every persona: **clarify**

Reading 1, 2024-H1 to 2025-H2:
```sql
SELECT round(avg(b.score - a.score), 2) AS avg_change FROM skills.assessments a JOIN skills.assessments b ON b.employee_id = a.employee_id AND b.skill_id = a.skill_id JOIN skills.skills s ON s.skill_id = a.skill_id WHERE s.name = 'Python' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2024-H1') AND b.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
- emea_analyst: avg_change → 0.31
- apac_analyst: avg_change → 0.47
- global_manager: avg_change → 0.38

Reading 2, 2025-H1 to 2025-H2:
```sql
SELECT round(avg(b.score - a.score), 2) AS avg_change FROM skills.assessments a JOIN skills.assessments b ON b.employee_id = a.employee_id AND b.skill_id = a.skill_id JOIN skills.skills s ON s.skill_id = a.skill_id WHERE s.name = 'Python' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H1') AND b.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
- emea_analyst: avg_change → 0.14
- apac_analyst: avg_change → 0.22
- global_manager: avg_change → 0.16

## K-M-009: How many new hires did we have?

- Kind: ambiguous. Why: Over which period: 2025, or 2024 and 2025.
- Second annotator: **clarify**: The question does not specify a time period for counting new hires (e.g., all time, current year, last assessment cycle), so the answer would vary depending on interpretation.
- Expected for every persona: **clarify**

Reading 1, Hired in 2025:
```sql
SELECT count(*) AS hires FROM skills.employees WHERE hired_on >= DATE '2025-01-01' AND hired_on < DATE '2026-01-01'
```
- emea_analyst: hires → 6
- apac_analyst: hires → 9
- global_manager: hires → 24

Reading 2, Hired in 2024 or 2025:
```sql
SELECT count(*) AS hires FROM skills.employees WHERE hired_on >= DATE '2024-01-01' AND hired_on < DATE '2026-01-01'
```
- emea_analyst: hires → 17
- apac_analyst: hires → 18
- global_manager: hires → 50

## K-M-010: What is the average tenure?

- Kind: ambiguous. Why: Of current employees (to 1 January 2026), or of everyone, counting leavers up to their leaving date. In years.
- Second annotator: **clarify**: The question does not specify which employee population (current, former, or all) or time reference (as of today, at a specific date, or over a period) to use for calculating average tenure, leading to multiple valid interpretations.
- Expected for every persona: **clarify**

Reading 1, Current employees:
```sql
SELECT round(avg((DATE '2026-01-01' - hired_on) / 365.25), 1) AS avg_years FROM skills.employees WHERE left_on IS NULL
```
- emea_analyst: avg_years → 4.8
- apac_analyst: avg_years → 4.9
- global_manager: avg_years → 5.0

Reading 2, Everyone, leavers to their leaving date:
```sql
SELECT round(avg((coalesce(left_on, DATE '2026-01-01') - hired_on) / 365.25), 1) AS avg_years FROM skills.employees
```
- emea_analyst: avg_years → 4.5
- apac_analyst: avg_years → 4.7
- global_manager: avg_years → 4.8

## K-M-011: How many employees are below target?

- Kind: ambiguous. Why: Below target on at least one skill, or below on average across their target skills (current employees, latest scores).
- Second annotator: **clarify**: The question does not specify what 'below target' means for an employee overall (e.g., any skill gap, all skills, average gap, majority of skills) or which assessment cycle to use.
- Expected for every persona: **clarify**

Reading 1, Below on at least one skill:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM (SELECT e.employee_id, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g WHERE gap > 0
```
- emea_analyst: employees → 48
- apac_analyst: employees → 62
- global_manager: employees → 166

Reading 2, Below on average:
```sql
SELECT count(*) AS employees FROM (SELECT employee_id FROM (SELECT e.employee_id, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g GROUP BY employee_id HAVING avg(gap) > 0) t
```
- emea_analyst: employees → 25
- apac_analyst: employees → 27
- global_manager: employees → 72

## K-M-012: How many experts do we have?

- Kind: ambiguous. Why: At least one expert score (5) in 2025-H2, or an average of 4.5 or more across 2025-H2 scores.
- Second annotator: **clarify**: The term 'experts' could refer to employees at career level 5 (principal) or those with assessment scores of 5 (expert), and the question does not specify which definition to use.
- Expected for every persona: **clarify**

Reading 1, At least one score of 5:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND score = 5
```
- emea_analyst: employees → 31
- apac_analyst: employees → 44
- global_manager: employees → 118

Reading 2, Average of 4.5 or more:
```sql
SELECT count(*) AS employees FROM (SELECT employee_id FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY employee_id HAVING avg(score) >= 4.5) t
```
- emea_analyst: employees → 15
- apac_analyst: employees → 14
- global_manager: employees → 46

## K-M-013: What is our attrition rate?

- Kind: ambiguous. Why: 2025 leavers over headcount at the start of 2025, or everyone who has ever left over everyone ever employed. In percent.
- Second annotator: **clarify**: Attrition rate can be calculated in multiple ways (e.g., leavers divided by average headcount, leavers divided by starting headcount) and over different time periods, none of which are specified in the question.
- Expected for every persona: **clarify**

Reading 1, 2025 leavers over headcount on 1 January 2025:
```sql
SELECT round(100.0 * count(*) FILTER (WHERE left_on >= DATE '2025-01-01' AND left_on < DATE '2026-01-01') / count(*) FILTER (WHERE hired_on < DATE '2025-01-01' AND (left_on IS NULL OR left_on >= DATE '2025-01-01')), 1) AS attrition_pct FROM skills.employees
```
- emea_analyst: attrition_pct → 9.2
- apac_analyst: attrition_pct → 5.9
- global_manager: attrition_pct → 6.4

Reading 2, Ever left over ever employed:
```sql
SELECT round(100.0 * count(left_on) / count(*), 1) AS attrition_pct FROM skills.employees
```
- emea_analyst: attrition_pct → 15.6
- apac_analyst: attrition_pct → 11.0
- global_manager: attrition_pct → 12.0

## K-M-014: What is the average career level?

- Kind: ambiguous. Why: Current employees only, or everyone including leavers.
- Second annotator: **clarify**: The question does not specify whether to average over all employees ever hired or only current employees (left_on IS NULL), which would produce different results.
- Expected for every persona: **clarify**

Reading 1, Current employees:
```sql
SELECT round(avg(level), 2) AS avg_level FROM skills.employees WHERE left_on IS NULL
```
- emea_analyst: avg_level → 3.17
- apac_analyst: avg_level → 3.22
- global_manager: avg_level → 3.27

Reading 2, Everyone:
```sql
SELECT round(avg(level), 2) AS avg_level FROM skills.employees
```
- emea_analyst: avg_level → 3.23
- apac_analyst: avg_level → 3.18
- global_manager: avg_level → 3.24

## K-M-015: How many people are in Engineering?

- Kind: ambiguous. Why: The Engineer job title, or the Engineering departments (current employees).
- Second annotator: **clarify**: The question could mean employees with job_title 'Engineer' or employees in a department named 'Engineering', which are different counts.
- Expected for every persona: **clarify**

Reading 1, Job title Engineer:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND job_title = 'Engineer'
```
- emea_analyst: employees → 22
- apac_analyst: employees → 21
- global_manager: employees → 70

Reading 2, Engineering departments:
```sql
SELECT count(*) AS employees FROM skills.employees e JOIN skills.departments d USING (department_id) WHERE e.left_on IS NULL AND d.name LIKE 'Engineering %'
```
- emea_analyst: employees → 15
- apac_analyst: employees → 17
- global_manager: employees → 48

## K-M-016: How many managers are there?

- Kind: ambiguous. Why: The Manager job title, or anyone who line-manages current employees.
- Second annotator: **clarify**: The question could mean either employees with job_title 'Manager' or employees who manage others via manager_id, which may yield different counts.
- Expected for every persona: **clarify**

Reading 1, Job title Manager:
```sql
SELECT count(*) AS managers FROM skills.employees WHERE left_on IS NULL AND job_title = 'Manager'
```
- emea_analyst: managers → 8
- apac_analyst: managers → 12
- global_manager: managers → 29

Reading 2, Anyone with current direct reports:
```sql
SELECT count(DISTINCT manager_id) AS managers FROM skills.employees WHERE left_on IS NULL AND manager_id IS NOT NULL
```
- emea_analyst: managers → 4
- apac_analyst: managers → 4
- global_manager: managers → 12

## K-M-018: How many employees have certifications?

- Kind: ambiguous. Why: Any certification ever, or one still valid on 1 January 2026 (current employees).
- Second annotator: **clarify**: The question does not specify whether to count only current employees (left_on is null), only active certifications (expires_on is null or future), or all historical records, leading to multiple reasonable interpretations.
- Expected for every persona: **clarify**

Reading 1, Any certification:
```sql
SELECT count(DISTINCT c.employee_id) AS employees FROM skills.certifications c JOIN skills.employees e USING (employee_id) WHERE e.left_on IS NULL
```
- emea_analyst: employees → 26
- apac_analyst: employees → 35
- global_manager: employees → 96

Reading 2, A valid certification on 1 January 2026:
```sql
SELECT count(DISTINCT c.employee_id) AS employees FROM skills.certifications c JOIN skills.employees e USING (employee_id) WHERE e.left_on IS NULL AND (c.expires_on IS NULL OR c.expires_on >= DATE '2026-01-01')
```
- emea_analyst: employees → 19
- apac_analyst: employees → 25
- global_manager: employees → 70

## K-M-019: How many Technical assessments scored well in 2025-H2?

- Kind: ambiguous. Why: "Well" is not defined: proficient or better (3+), or advanced or better (4+).
- Second annotator: **clarify**: The phrase 'scored well' is subjective (could mean score ≥4, ≥3, or other thresholds) and '2025-H2' could refer to a cycle name or a date range, leading to multiple reasonable interpretations.
- Expected for every persona: **clarify**

Reading 1, Score 3 or more:
```sql
SELECT count(*) AS assessments FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE s.category = 'Technical' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND a.score >= 3
```
- emea_analyst: assessments → 213
- apac_analyst: assessments → 240
- global_manager: assessments → 710

Reading 2, Score 4 or more:
```sql
SELECT count(*) AS assessments FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE s.category = 'Technical' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND a.score >= 4
```
- emea_analyst: assessments → 149
- apac_analyst: assessments → 166
- global_manager: assessments → 498

## K-M-020: How big is the SQL skill gap?

- Kind: ambiguous. Why: Total shortfall across current employees, or the average gap per employee with a SQL target (latest scores).
- Second annotator: **clarify**: The question does not specify which SQL skill, which job titles, which employees, which assessment cycle, or what aggregation (average, max, distribution) is wanted, so multiple reasonable interpretations would yield different results.
- Expected for every persona: **clarify**

Reading 1, Total shortfall:
```sql
SELECT sum(gap) AS total_gap FROM (SELECT e.employee_id, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g JOIN skills.skills s USING (skill_id) WHERE s.name = 'SQL' AND gap > 0
```
- emea_analyst: total_gap → 60
- apac_analyst: total_gap → 64
- global_manager: total_gap → 172

Reading 2, Average gap:
```sql
SELECT round(avg(gap), 2) AS avg_gap FROM (SELECT e.employee_id, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g JOIN skills.skills s USING (skill_id) WHERE s.name = 'SQL'
```
- emea_analyst: avg_gap → 0.81
- apac_analyst: avg_gap → 0.89
- global_manager: avg_gap → 0.72

## K-M-021: What is our biggest skill weakness?

- Kind: ambiguous. Why: The skill with the lowest average score (2025-H2), or the skill with the largest total shortfall against job-title targets (current employees, latest scores).
- Second annotator: **clarify**: The question does not specify the scope (company, region, department, role), time period (latest cycle, all cycles), or metric (average gap vs target, lowest average score, percentage below target) for defining 'biggest skill weakness'.
- Expected for every persona: **clarify**

Reading 1, Lowest average score in 2025-H2:
```sql
SELECT s.name, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY s.skill_id, s.name ORDER BY avg(a.score) LIMIT 1
```
- emea_analyst: name, avg_score → Education, 2.6
- apac_analyst: name, avg_score → DevOps, 2.85
- global_manager: name, avg_score → Media, 3.19

Reading 2, Largest total shortfall against targets:
```sql
SELECT s.name, sum(g.gap) AS total_gap FROM (SELECT e.employee_id, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g JOIN skills.skills s USING (skill_id) WHERE g.gap > 0 GROUP BY s.skill_id, s.name ORDER BY total_gap DESC LIMIT 1
```
- emea_analyst: name, total_gap → SQL, 60
- apac_analyst: name, total_gap → SQL, 64
- global_manager: name, total_gap → SQL, 172

## K-M-022: How experienced is our workforce?

- Kind: ambiguous. Why: Experience as years of service, or as career level (current employees).
- Second annotator: **clarify**: The question 'How experienced is our workforce?' is ambiguous: it could refer to tenure, career level distribution, skill proficiency scores, certifications, or a combination, each yielding different interpretations.
- Expected for every persona: **clarify**

Reading 1, Average years of service to 1 January 2026:
```sql
SELECT round(avg((DATE '2026-01-01' - hired_on) / 365.25), 1) AS avg_years FROM skills.employees WHERE left_on IS NULL
```
- emea_analyst: avg_years → 4.8
- apac_analyst: avg_years → 4.9
- global_manager: avg_years → 5.0

Reading 2, Average career level:
```sql
SELECT round(avg(level), 2) AS avg_level FROM skills.employees WHERE left_on IS NULL
```
- emea_analyst: avg_level → 3.17
- apac_analyst: avg_level → 3.22
- global_manager: avg_level → 3.27

## K-M-023: Which is our top department?

- Kind: ambiguous. Why: The most current employees, or the highest average score in 2025-H2.
- Second annotator: **clarify**: The question does not specify what metric defines 'top department' (e.g., highest average assessment scores, most certifications, largest headcount, lowest skill gaps), and multiple reasonable interpretations would yield different results.
- Expected for every persona: **clarify**

Reading 1, Most current employees:
```sql
SELECT d.name AS department, count(*) AS employees FROM skills.employees e JOIN skills.departments d USING (department_id) WHERE e.left_on IS NULL GROUP BY d.department_id, d.name ORDER BY employees DESC LIMIT 1
```
- emea_analyst: department, employees → Data EMEA, 20
- apac_analyst: department, employees → Data APAC, 21
- global_manager: department, employees → Consulting AMER, 22

Reading 2, Highest average score in 2025-H2:
```sql
SELECT d.name AS department, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.employee_id JOIN skills.departments d ON d.department_id = e.department_id WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY d.department_id, d.name ORDER BY avg(a.score) DESC LIMIT 1
```
- emea_analyst: department, avg_score → Consulting EMEA, 3.95
- apac_analyst: department, avg_score → Engineering APAC, 3.94
- global_manager: department, avg_score → Engineering AMER, 4.13
