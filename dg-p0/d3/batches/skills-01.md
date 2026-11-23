# Batch skills-01: owner review

25 questions, 24 agree on every persona, 1 to adjudicate.

## K-A-001: How many employees are in the data, including people who have left?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees
```
Second annotator:
```sql
SELECT count(*) AS employee_count
FROM skills.employees
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 77 | yes |
| apac_analyst | employees → 82 | yes |
| global_manager | employees → 242 | yes |

## K-A-002: How many people are currently employed?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL
```
Second annotator:
```sql
SELECT count(*) AS currently_employed
FROM skills.employees
WHERE left_on IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 65 | yes |
| apac_analyst | employees → 73 | yes |
| global_manager | employees → 213 | yes |

## K-A-003: How many current employees are there in each job title?

Reference:
```sql
SELECT job_title, count(*) AS employees FROM skills.employees WHERE left_on IS NULL GROUP BY job_title
```
Second annotator:
```sql
SELECT
    job_title,
    COUNT(*) AS employee_count
FROM skills.employees
WHERE left_on IS NULL
GROUP BY job_title
ORDER BY job_title
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | job_title, employees → Consultant, 15; Engineer, 22; Team Lead, 7; Manager, 8; Analyst, 13 | yes |
| apac_analyst | job_title, employees → Consultant, 16; Engineer, 21; Team Lead, 11; Manager, 12; Analyst, 13 | yes |
| global_manager | job_title, employees → Consultant, 49; Engineer, 70; Team Lead, 24; Manager, 29; Analyst, 41 | yes |

## K-A-004: How many employees left during 2025?

Reference:
```sql
SELECT count(*) AS leavers FROM skills.employees WHERE left_on >= DATE '2025-01-01' AND left_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*)
FROM skills.employees
WHERE left_on IS NOT NULL
  AND EXTRACT(YEAR FROM left_on) = 2025
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | leavers → 6 | yes |
| apac_analyst | leavers → 4 | yes |
| global_manager | leavers → 13 | yes |

## K-A-005: How many departments are there?

Reference:
```sql
SELECT count(*) AS departments FROM skills.departments
```
Second annotator:
```sql
SELECT count(*) AS department_count FROM skills.departments
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | departments → 4 | yes |
| apac_analyst | departments → 4 | yes |
| global_manager | departments → 12 | yes |

## K-A-006: What was the average assessment score in the 2025-H2 cycle? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH target_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
)
SELECT round(avg(a.score), 2) AS average_score
FROM skills.assessments a
JOIN target_cycle tc ON a.cycle_id = tc.cycle_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 3.8 | yes |
| apac_analyst | avg_score → 3.8 | yes |
| global_manager | avg_score → 3.84 | yes |

## K-A-007: What was the average score for each skill category in 2025-H2? Round to two decimal places.

Reference:
```sql
SELECT s.category, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY s.category
```
Second annotator:
```sql
WITH target_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
)
SELECT
    sk.category,
    round(avg(a.score)::numeric, 2) AS average_score
FROM skills.assessments a
JOIN skills.skills sk ON sk.skill_id = a.skill_id
JOIN target_cycle tc ON tc.cycle_id = a.cycle_id
GROUP BY sk.category
ORDER BY sk.category
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, avg_score → Domain, 3.51; Leadership, 4.51; Communication, 3.83; Technical, 3.78 | yes |
| apac_analyst | category, avg_score → Domain, 3.74; Leadership, 4.36; Communication, 3.79; Technical, 3.69 | yes |
| global_manager | category, avg_score → Domain, 3.67; Leadership, 4.46; Communication, 3.85; Technical, 3.79 | yes |

## K-A-008: How many assessments were recorded in each cycle?

Reference:
```sql
SELECT c.name AS cycle, count(*) AS assessments FROM skills.assessments a JOIN skills.assessment_cycles c USING (cycle_id) GROUP BY c.name
```
Second annotator:
```sql
SELECT cycle_id, COUNT(*) AS assessment_count
FROM skills.assessments
GROUP BY cycle_id
ORDER BY cycle_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cycle, assessments → 2025-H1, 538; 2024-H2, 499; 2025-H2, 482; 2024-H1, 459 | NO: values differ |
| | second: cycle_id, assessment_count → 1, 459; 2, 499; 3, 538; 4, 482 | |
| apac_analyst | cycle, assessments → 2025-H1, 574; 2024-H2, 523; 2025-H2, 585; 2024-H1, 465 | NO: values differ |
| | second: cycle_id, assessment_count → 1, 465; 2, 523; 3, 574; 4, 585 | |
| global_manager | cycle, assessments → 2025-H1, 1657; 2024-H2, 1533; 2025-H2, 1627; 2024-H1, 1396 | NO: values differ |
| | second: cycle_id, assessment_count → 1, 1396; 2, 1533; 3, 1657; 4, 1627 | |

**Disagreement: owner to adjudicate.**

## K-A-009: Which skill had the highest average score in 2025-H2, and what was it? Round to two decimal places.

Reference:
```sql
SELECT s.name, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY s.skill_id, s.name ORDER BY avg(a.score) DESC LIMIT 1
```
Second annotator:
```sql
WITH target_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
skill_avg AS (
    SELECT s.name AS skill_name,
           ROUND(AVG(a.score)::numeric, 2) AS avg_score
    FROM skills.assessments a
    JOIN target_cycle tc ON a.cycle_id = tc.cycle_id
    JOIN skills.skills s ON a.skill_id = s.skill_id
    GROUP BY s.name
)
SELECT skill_name, avg_score
FROM skill_avg
ORDER BY avg_score DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, avg_score → Decision Making, 5.0 | yes |
| apac_analyst | name, avg_score → Conflict Resolution, 4.5 | yes |
| global_manager | name, avg_score → Decision Making, 4.67 | yes |

## K-A-010: How many employees hold at least one certification?

Reference:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM skills.certifications
```
Second annotator:
```sql
SELECT COUNT(DISTINCT employee_id) FROM skills.certifications
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 35 | yes |
| apac_analyst | employees → 42 | yes |
| global_manager | employees → 117 | yes |

## K-A-011: How many certifications expire during 2026?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications WHERE expires_on >= DATE '2026-01-01' AND expires_on < DATE '2027-01-01'
```
Second annotator:
```sql
SELECT count(*)
FROM skills.certifications
WHERE expires_on >= DATE '2026-01-01'
  AND expires_on < DATE '2027-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 7 | yes |
| apac_analyst | certifications → 7 | yes |
| global_manager | certifications → 21 | yes |

## K-A-012: How many certifications were issued in 2025?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications WHERE issued_on >= DATE '2025-01-01' AND issued_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*) AS certifications_issued_2025
FROM skills.certifications
WHERE EXTRACT(YEAR FROM issued_on) = 2025
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 13 | yes |
| apac_analyst | certifications → 21 | yes |
| global_manager | certifications → 52 | yes |

## K-A-013: What percentage of 2025-H2 scores were advanced or expert (4 or 5)? Round to one decimal place.

Reference:
```sql
SELECT round(100.0 * count(*) FILTER (WHERE a.score >= 4) / count(*), 1) AS pct FROM skills.assessments a WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
SELECT round(100.0 * count(*) FILTER (WHERE a.score >= 4) / count(*), 1) AS percentage
FROM skills.assessments a
JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
WHERE c.name = '2025-H2'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | pct → 63.5 | yes |
| apac_analyst | pct → 63.6 | yes |
| global_manager | pct → 64.9 | yes |

## K-A-014: What is the average career level of current employees in each job title? Round to two decimal places.

Reference:
```sql
SELECT job_title, round(avg(level), 2) AS avg_level FROM skills.employees WHERE left_on IS NULL GROUP BY job_title
```
Second annotator:
```sql
SELECT
    job_title,
    ROUND(AVG(level)::numeric, 2) AS avg_level
FROM skills.employees
WHERE left_on IS NULL
GROUP BY job_title
ORDER BY job_title
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | job_title, avg_level → Consultant, 3.6; Engineer, 2.5; Team Lead, 3.86; Manager, 4.88; Analyst, 2.38 | yes |
| apac_analyst | job_title, avg_level → Consultant, 3.44; Engineer, 2.38; Team Lead, 4.09; Manager, 4.58; Analyst, 2.31 | yes |
| global_manager | job_title, avg_level → Consultant, 3.67; Engineer, 2.56; Team Lead, 4.13; Manager, 4.76; Analyst, 2.46 | yes |

## K-A-015: How many employees were hired in 2024?

Reference:
```sql
SELECT count(*) AS hires FROM skills.employees WHERE hired_on >= DATE '2024-01-01' AND hired_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT count(*) AS hired_in_2024
FROM skills.employees
WHERE EXTRACT(YEAR FROM hired_on) = 2024
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | hires → 11 | yes |
| apac_analyst | hires → 9 | yes |
| global_manager | hires → 26 | yes |

## K-A-016: Which department has the most current employees, and how many?

Reference:
```sql
SELECT d.name AS department, count(*) AS employees FROM skills.employees e JOIN skills.departments d USING (department_id) WHERE e.left_on IS NULL GROUP BY d.department_id, d.name ORDER BY employees DESC LIMIT 1
```
Second annotator:
```sql
SELECT d.name AS department, COUNT(e.employee_id) AS current_employee_count
FROM skills.departments d
JOIN skills.employees e ON e.department_id = d.department_id
WHERE e.left_on IS NULL
GROUP BY d.name
ORDER BY current_employee_count DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | department, employees → Data EMEA, 20 | yes |
| apac_analyst | department, employees → Data APAC, 21 | yes |
| global_manager | department, employees → Consulting AMER, 22 | yes |

## K-A-017: How many employees were rated expert in Python in 2025-H2?

Reference:
```sql
SELECT count(*) AS employees FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND s.name = 'Python' AND a.score = 5
```
Second annotator:
```sql
SELECT COUNT(*) AS expert_count
FROM skills.assessments a
JOIN skills.skills s ON a.skill_id = s.skill_id
JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
WHERE s.name = 'Python'
  AND c.name = '2025-H2'
  AND a.score = 5
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 5 | yes |
| apac_analyst | employees → 2 | yes |
| global_manager | employees → 10 | yes |

## K-A-018: What was the average SQL score in each cycle, in cycle order? Round to two decimal places.

Reference:
```sql
SELECT c.name AS cycle, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.assessment_cycles c USING (cycle_id) WHERE s.name = 'SQL' GROUP BY c.cycle_id, c.name ORDER BY c.cycle_id
```
Second annotator:
```sql
WITH sql_skill AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'SQL'
)
SELECT
    ac.name AS cycle_name,
    round(avg(a.score), 2) AS average_sql_score
FROM skills.assessments a
JOIN sql_skill s ON a.skill_id = s.skill_id
JOIN skills.assessment_cycles ac ON a.cycle_id = ac.cycle_id
GROUP BY ac.cycle_id, ac.name
ORDER BY ac.starts_on
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cycle, avg_score → 2024-H1, 3.45; 2024-H2, 3.63; 2025-H1, 3.55; 2025-H2, 3.8 | yes |
| apac_analyst | cycle, avg_score → 2024-H1, 3.3; 2024-H2, 3.41; 2025-H1, 3.44; 2025-H2, 3.54 | yes |
| global_manager | cycle, avg_score → 2024-H1, 3.47; 2024-H2, 3.57; 2025-H1, 3.65; 2025-H2, 3.76 | yes |

## K-A-019: How many current employees have no line manager?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND manager_id IS NULL
```
Second annotator:
```sql
SELECT count(*) AS current_employees_without_manager
FROM skills.employees
WHERE left_on IS NULL
  AND manager_id IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 4 | yes |
| apac_analyst | employees → 4 | yes |
| global_manager | employees → 12 | yes |

## K-A-020: How many different skills were assessed in 2025-H1?

Reference:
```sql
SELECT count(DISTINCT a.skill_id) AS skills FROM skills.assessments a JOIN skills.assessment_cycles c USING (cycle_id) WHERE c.name = '2025-H1'
```
Second annotator:
```sql
SELECT count(DISTINCT a.skill_id) AS skill_count
FROM skills.assessments a
WHERE a.cycle_id = (
    SELECT c.cycle_id
    FROM skills.assessment_cycles c
    WHERE c.name = '2025-H1'
)
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | skills → 28 | yes |
| apac_analyst | skills → 28 | yes |
| global_manager | skills → 28 | yes |

## K-A-021: What is the target score for Team Leads in Coaching?

Reference:
```sql
SELECT t.target_score FROM skills.role_targets t JOIN skills.skills s USING (skill_id) WHERE t.job_title = 'Team Lead' AND s.name = 'Coaching'
```
Second annotator:
```sql
SELECT rt.target_score
FROM skills.role_targets rt
JOIN skills.skills s ON s.skill_id = rt.skill_id
WHERE rt.job_title = 'Team Lead'
  AND s.name = 'Coaching'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | target_score → 4 | yes |
| apac_analyst | target_score → 4 | yes |
| global_manager | target_score → 4 | yes |

## K-A-022: How many skills are in each category?

Reference:
```sql
SELECT category, count(*) AS skills FROM skills.skills GROUP BY category
```
Second annotator:
```sql
SELECT
    category,
    COUNT(*) AS skill_count
FROM skills.skills
GROUP BY category
ORDER BY category
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, skills → Domain, 11; Leadership, 6; Communication, 5; Technical, 8 | yes |
| apac_analyst | category, skills → Domain, 11; Leadership, 6; Communication, 5; Technical, 8 | yes |
| global_manager | category, skills → Domain, 11; Leadership, 6; Communication, 5; Technical, 8 | yes |

## K-A-023: How many assessor notes were written on assessments made in 2025?

Reference:
```sql
SELECT count(*) AS notes FROM skills.assessor_notes n JOIN skills.assessments a USING (assessment_id) WHERE a.assessed_on >= DATE '2025-01-01' AND a.assessed_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT COUNT(*) AS note_count
FROM skills.assessor_notes an
JOIN skills.assessments a ON an.assessment_id = a.assessment_id
WHERE a.assessed_on >= DATE '2025-01-01'
  AND a.assessed_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | notes → 196 | yes |

## K-A-024: How many employees hold more than one certification?

Reference:
```sql
SELECT count(*) AS employees FROM (SELECT employee_id FROM skills.certifications GROUP BY employee_id HAVING count(*) > 1) t
```
Second annotator:
```sql
WITH cert_counts AS (
    SELECT employee_id
    FROM skills.certifications
    GROUP BY employee_id
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS employee_count
FROM cert_counts
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 6 | yes |
| apac_analyst | employees → 10 | yes |
| global_manager | employees → 21 | yes |

## K-A-025: For employees assessed in Python in both 2024-H1 and 2025-H2, what was the average change in score? Round to two decimal places.

Reference:
```sql
SELECT round(avg(b.score - a.score), 2) AS avg_change FROM skills.assessments a JOIN skills.assessments b ON b.employee_id = a.employee_id AND b.skill_id = a.skill_id JOIN skills.skills s ON s.skill_id = a.skill_id WHERE s.name = 'Python' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2024-H1') AND b.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH python_2024 AS (
    SELECT a.employee_id, a.score
    FROM skills.assessments a
    JOIN skills.skills s ON a.skill_id = s.skill_id
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE s.name = 'Python' AND c.name = '2024-H1'
),
python_2025 AS (
    SELECT a.employee_id, a.score
    FROM skills.assessments a
    JOIN skills.skills s ON a.skill_id = s.skill_id
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE s.name = 'Python' AND c.name = '2025-H2'
)
SELECT round(avg(p2025.score - p2024.score), 2) AS average_change
FROM python_2024 p2024
JOIN python_2025 p2025 ON p2024.employee_id = p2025.employee_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_change → 0.31 | yes |
| apac_analyst | avg_change → 0.47 | yes |
| global_manager | avg_change → 0.38 | yes |
