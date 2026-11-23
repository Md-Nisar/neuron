# Batch skills-04: owner review

25 questions, 25 agree on every persona, 0 to adjudicate.

## K-A-076: How many current employees are in each region?

Reference:
```sql
SELECT region_id AS region, count(*) AS employees FROM skills.employees WHERE left_on IS NULL GROUP BY region_id
```
Second annotator:
```sql
SELECT
    e.region_id,
    COUNT(*) AS employee_count
FROM skills.employees e
WHERE e.left_on IS NULL
GROUP BY e.region_id
ORDER BY e.region_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | region, employees → EMEA, 65 | yes |
| apac_analyst | region, employees → APAC, 73 | yes |
| global_manager | region, employees → EMEA, 65; APAC, 73; AMER, 75 | yes |

## K-A-077: What was the average 2025-H2 score per region? Round to two decimal places.

Reference:
```sql
SELECT region_id AS region, round(avg(score), 2) AS avg_score FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY region_id
```
Second annotator:
```sql
WITH h2_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
)
SELECT
    a.region_id,
    ROUND(AVG(a.score)::numeric, 2) AS average_score
FROM skills.assessments a
JOIN h2_cycle c ON a.cycle_id = c.cycle_id
GROUP BY a.region_id
ORDER BY a.region_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | region, avg_score → EMEA, 3.8 | yes |
| apac_analyst | region, avg_score → APAC, 3.8 | yes |
| global_manager | region, avg_score → EMEA, 3.8; APAC, 3.8; AMER, 3.93 | yes |

## K-A-078: How many assessments were recorded in total?

Reference:
```sql
SELECT count(*) AS assessments FROM skills.assessments
```
Second annotator:
```sql
SELECT count(*) AS total_assessments
FROM skills.assessments
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | assessments → 1978 | yes |
| apac_analyst | assessments → 2147 | yes |
| global_manager | assessments → 6213 | yes |

## K-A-079: What is the highest career level among current Analysts, and how many Analysts are at it?

Reference:
```sql
SELECT level, count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND job_title = 'Analyst' AND level = (SELECT max(level) FROM skills.employees WHERE left_on IS NULL AND job_title = 'Analyst') GROUP BY level
```
Second annotator:
```sql
SELECT max_level AS highest_level,
       (SELECT count(*)
        FROM skills.employees
        WHERE job_title = 'Analyst'
          AND left_on IS NULL
          AND level = max_level) AS count_at_highest
FROM (SELECT max(level) AS max_level
      FROM skills.employees
      WHERE job_title = 'Analyst'
        AND left_on IS NULL) sub
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | level, employees → 4, 3 | yes |
| apac_analyst | level, employees → 4, 3 | yes |
| global_manager | level, employees → 4, 10 | yes |

## K-A-080: How many employees left during 2024?

Reference:
```sql
SELECT count(*) AS leavers FROM skills.employees WHERE left_on >= DATE '2024-01-01' AND left_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT count(*) AS employees_left_2024
FROM skills.employees
WHERE left_on >= DATE '2024-01-01'
  AND left_on <= DATE '2024-12-31'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | leavers → 3 | yes |
| apac_analyst | leavers → 1 | yes |
| global_manager | leavers → 6 | yes |

## K-A-081: What share of current employees hold at least one certification, in percent? Round to one decimal place.

Reference:
```sql
SELECT round(100.0 * count(*) FILTER (WHERE EXISTS (SELECT 1 FROM skills.certifications c WHERE c.employee_id = e.employee_id)) / count(*), 1) AS pct FROM skills.employees e WHERE e.left_on IS NULL
```
Second annotator:
```sql
SELECT round(100.0 * count(DISTINCT c.employee_id) / count(e.employee_id), 1) AS share_percent
FROM (
    SELECT employee_id
    FROM skills.employees
    WHERE left_on IS NULL
) e
LEFT JOIN (
    SELECT DISTINCT employee_id
    FROM skills.certifications
) c ON e.employee_id = c.employee_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | pct → 40.0 | yes |
| apac_analyst | pct → 47.9 | yes |
| global_manager | pct → 45.1 | yes |

## K-A-082: What was the average Python score in 2025-H2 for employees who hold a Data Engineer certification? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE s.name = 'Python' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND a.employee_id IN (SELECT employee_id FROM skills.certifications WHERE name = 'Data Engineer')
```
Second annotator:
```sql
WITH python_skill AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'Python'
),
cycle_2025_h2 AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
certified_employees AS (
    SELECT DISTINCT employee_id
    FROM skills.certifications
    WHERE name = 'Data Engineer'
)
SELECT round(avg(a.score)::numeric, 2) AS average_python_score
FROM skills.assessments a
JOIN python_skill ps ON a.skill_id = ps.skill_id
JOIN cycle_2025_h2 c ON a.cycle_id = c.cycle_id
JOIN certified_employees ce ON a.employee_id = ce.employee_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 2.0 | yes |
| apac_analyst | avg_score → 3.0 | yes |
| global_manager | avg_score → 2.67 | yes |

## K-A-083: For each job title, how many Technical skills have a target score?

Reference:
```sql
SELECT t.job_title, count(*) AS technical_targets FROM skills.role_targets t JOIN skills.skills s USING (skill_id) WHERE s.category = 'Technical' GROUP BY t.job_title
```
Second annotator:
```sql
SELECT
    rt.job_title,
    COUNT(*) AS technical_skill_target_count
FROM skills.role_targets rt
JOIN skills.skills s ON s.skill_id = rt.skill_id
WHERE s.category = 'Technical'
GROUP BY rt.job_title
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | job_title, technical_targets → Analyst, 4; Consultant, 4; Engineer, 4; Manager, 4; Team Lead, 4 | yes |
| apac_analyst | job_title, technical_targets → Analyst, 4; Consultant, 4; Engineer, 4; Manager, 4; Team Lead, 4 | yes |
| global_manager | job_title, technical_targets → Analyst, 4; Consultant, 4; Engineer, 4; Manager, 4; Team Lead, 4 | yes |

## K-A-084: Which skill was assessed the most times across all cycles, and how many times?

Reference:
```sql
SELECT s.name, count(*) AS assessments FROM skills.assessments a JOIN skills.skills s USING (skill_id) GROUP BY s.skill_id, s.name ORDER BY assessments DESC LIMIT 1
```
Second annotator:
```sql
SELECT s.name AS skill_name,
       COUNT(a.assessment_id) AS assessment_count
FROM skills.skills s
JOIN skills.assessments a ON a.skill_id = s.skill_id
GROUP BY s.name
ORDER BY assessment_count DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, assessments → SQL, 219 | yes |
| apac_analyst | name, assessments → SQL, 222 | yes |
| global_manager | name, assessments → SQL, 686 | yes |

## K-A-085: How many employees in Engineering departments scored 4 or higher in Security Engineering in 2025-H2?

Reference:
```sql
SELECT count(*) AS employees FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.employees e ON e.employee_id = a.employee_id JOIN skills.departments d ON d.department_id = e.department_id WHERE s.name = 'Security Engineering' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND a.score >= 4 AND d.name LIKE 'Engineering %'
```
Second annotator:
```sql
WITH eng_sec AS (
    SELECT e.employee_id
    FROM skills.employees e
    JOIN skills.departments d ON e.department_id = d.department_id
    JOIN skills.assessments a ON a.employee_id = e.employee_id
    JOIN skills.skills s ON a.skill_id = s.skill_id
    JOIN skills.assessment_cycles ac ON a.cycle_id = ac.cycle_id
    WHERE d.name ILIKE '%Engineering%'
      AND s.name = 'Security Engineering'
      AND ac.name = '2025-H2'
      AND a.score >= 4
)
SELECT COUNT(*) FROM eng_sec
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 3 | yes |
| apac_analyst | employees → 8 | yes |
| global_manager | employees → 21 | yes |

## K-A-086: What was the average score given by assessors to employees in a different job title than their own, in 2025? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.employee_id JOIN skills.employees r ON r.employee_id = a.assessor_id WHERE e.job_title <> r.job_title AND a.assessed_on >= DATE '2025-01-01' AND a.assessed_on < DATE '2026-01-01'
```
Second annotator:
```sql
WITH filtered AS (
    SELECT a.score
    FROM skills.assessments a
    JOIN skills.employees e ON a.employee_id = e.employee_id
    JOIN skills.employees m ON a.assessor_id = m.employee_id
    WHERE e.job_title <> m.job_title
      AND a.assessed_on >= DATE '2025-01-01'
      AND a.assessed_on < DATE '2026-01-01'
)
SELECT ROUND(AVG(score)::numeric, 2) AS average_score
FROM filtered
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 3.62 | yes |
| apac_analyst | avg_score → 3.57 | yes |
| global_manager | avg_score → 3.65 | yes |

## K-A-087: How many certifications were issued in each year from 2020 to 2025?

Reference:
```sql
SELECT extract(year FROM issued_on)::int AS year, count(*) AS certifications FROM skills.certifications WHERE issued_on >= DATE '2020-01-01' AND issued_on < DATE '2026-01-01' GROUP BY 1
```
Second annotator:
```sql
WITH yearly AS (
    SELECT EXTRACT(YEAR FROM issued_on)::int AS yr,
           COUNT(*) AS cnt
    FROM skills.certifications
    WHERE issued_on >= DATE '2020-01-01'
      AND issued_on < DATE '2026-01-01'
    GROUP BY yr
)
SELECT gs.yr AS year,
       COALESCE(y.cnt, 0) AS certifications_issued
FROM generate_series(2020, 2025) AS gs(yr)
LEFT JOIN yearly y ON y.yr = gs.yr
ORDER BY gs.yr
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | year, certifications → 2022, 9; 2023, 5; 2025, 13; 2020, 1; 2024, 10; 2021, 3 | yes |
| apac_analyst | year, certifications → 2022, 9; 2023, 4; 2025, 21; 2020, 5; 2024, 9; 2021, 4 | yes |
| global_manager | year, certifications → 2022, 23; 2023, 17; 2025, 52; 2020, 8; 2024, 27; 2021, 11 | yes |

## K-A-088: What was the earliest and latest assessment date in the 2025-H1 cycle?

Reference:
```sql
SELECT min(assessed_on) AS first_assessed, max(assessed_on) AS last_assessed FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H1')
```
Second annotator:
```sql
SELECT min(a.assessed_on) AS earliest_assessment_date,
       max(a.assessed_on) AS latest_assessment_date
FROM skills.assessments a
JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
WHERE c.name = '2025-H1'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | first_assessed, last_assessed → 2025-05-31, 2025-06-30 | yes |
| apac_analyst | first_assessed, last_assessed → 2025-05-31, 2025-06-30 | yes |
| global_manager | first_assessed, last_assessed → 2025-05-31, 2025-06-30 | yes |

## K-A-089: How many current Consultants were assessed on at least one Domain skill in 2025-H2?

Reference:
```sql
SELECT count(DISTINCT a.employee_id) AS employees FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.employees e ON e.employee_id = a.employee_id WHERE s.category = 'Domain' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND e.job_title = 'Consultant' AND e.left_on IS NULL
```
Second annotator:
```sql
SELECT COUNT(DISTINCT e.employee_id) AS consultant_count
FROM skills.employees e
JOIN skills.assessments a ON a.employee_id = e.employee_id
JOIN skills.assessment_cycles ac ON ac.cycle_id = a.cycle_id
JOIN skills.skills s ON s.skill_id = a.skill_id
WHERE e.job_title = 'Consultant'
  AND e.left_on IS NULL
  AND ac.name = '2025-H2'
  AND s.category = 'Domain'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 13 | yes |
| apac_analyst | employees → 15 | yes |
| global_manager | employees → 45 | yes |

## K-A-090: What was the percentage of 2025-H2 assessments at or above the job title's target, counting only skills with a target? Round to one decimal place.

Reference:
```sql
SELECT round(100.0 * count(*) FILTER (WHERE a.score >= t.target_score) / count(*), 1) AS pct FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.employee_id JOIN skills.role_targets t ON t.job_title = e.job_title AND t.skill_id = a.skill_id WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH target_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
relevant_assessments AS (
    SELECT a.score,
           rt.target_score
    FROM skills.assessments a
    JOIN target_cycle tc ON a.cycle_id = tc.cycle_id
    JOIN skills.employees e ON a.employee_id = e.employee_id
    JOIN skills.role_targets rt
      ON rt.job_title = e.job_title
     AND rt.skill_id = a.skill_id
)
SELECT round(100.0 * sum(CASE WHEN score >= target_score THEN 1 ELSE 0 END) / count(*), 1) AS percentage
FROM relevant_assessments
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | pct → 71.8 | yes |
| apac_analyst | pct → 70.2 | yes |
| global_manager | pct → 72.9 | yes |

## K-A-091: How many current employees at career level 1 are there in each department?

Reference:
```sql
SELECT d.name AS department, count(*) AS employees FROM skills.employees e JOIN skills.departments d USING (department_id) WHERE e.left_on IS NULL AND e.level = 1 GROUP BY d.name
```
Second annotator:
```sql
SELECT COUNT(e.employee_id) AS current_level1_employees,
       d.name AS department
FROM skills.departments d
JOIN skills.employees e ON e.department_id = d.department_id
WHERE e.left_on IS NULL
  AND e.level = 1
GROUP BY d.name
ORDER BY d.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | department, employees → Consulting EMEA, 1; Data EMEA, 2; Engineering EMEA, 3; Support EMEA, 2 | yes |
| apac_analyst | department, employees → Consulting APAC, 2; Data APAC, 4; Engineering APAC, 2; Support APAC, 4 | yes |
| global_manager | department, employees → Consulting AMER, 2; Consulting APAC, 2; Consulting EMEA, 1; Data APAC, 4; Data EMEA, 2; Engineering APAC, 2 … (+4 rows) | yes |

## K-A-092: How many different certifications exist in the data?

Reference:
```sql
SELECT count(DISTINCT name) AS certifications FROM skills.certifications
```
Second annotator:
```sql
SELECT COUNT(DISTINCT name) FROM skills.certifications
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 8 | yes |
| apac_analyst | certifications → 8 | yes |
| global_manager | certifications → 8 | yes |

## K-A-093: What was the average number of assessments per assessor in 2025-H2? Round to two decimal places.

Reference:
```sql
SELECT round(count(*)::numeric / count(DISTINCT assessor_id), 2) AS per_assessor FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
assessor_counts AS (
    SELECT assessor_id, COUNT(*) AS cnt
    FROM skills.assessments a
    JOIN cycle c ON a.cycle_id = c.cycle_id
    GROUP BY assessor_id
)
SELECT ROUND(AVG(cnt)::numeric, 2) AS avg_assessments_per_assessor
FROM assessor_counts
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | per_assessor → 120.5 | yes |
| apac_analyst | per_assessor → 146.25 | yes |
| global_manager | per_assessor → 135.58 | yes |

## K-A-094: Which skill category improved the most in average score from 2024-H1 to 2025-H2, and by how much? Round to two decimal places.

Reference:
```sql
SELECT s.category, round(avg(a.score) FILTER (WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')) - avg(a.score) FILTER (WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2024-H1')), 2) AS change FROM skills.assessments a JOIN skills.skills s USING (skill_id) GROUP BY s.category ORDER BY change DESC LIMIT 1
```
Second annotator:
```sql
WITH cycles AS (
    SELECT cycle_id, name
    FROM skills.assessment_cycles
    WHERE name IN ('2024-H1', '2025-H2')
),
avg_scores AS (
    SELECT s.category,
           c.name AS cycle_name,
           AVG(a.score)::numeric AS avg_score
    FROM skills.assessments a
    JOIN skills.skills s ON a.skill_id = s.skill_id
    JOIN cycles c ON a.cycle_id = c.cycle_id
    GROUP BY s.category, c.name
),
pivot AS (
    SELECT category,
           MAX(CASE WHEN cycle_name = '2025-H2' THEN avg_score END) AS avg_2025_H2,
           MAX(CASE WHEN cycle_name = '2024-H1' THEN avg_score END) AS avg_2024_H1
    FROM avg_scores
    GROUP BY category
)
SELECT category,
       ROUND((avg_2025_H2 - avg_2024_H1)::numeric, 2) AS improvement
FROM pivot
WHERE avg_2025_H2 IS NOT NULL
  AND avg_2024_H1 IS NOT NULL
ORDER BY improvement DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, change → Communication, 0.27 | yes |
| apac_analyst | category, change → Technical, 0.28 | yes |
| global_manager | category, change → Communication, 0.29 | yes |

## K-A-095: How many employees have a certification that expired before they left?

Reference:
```sql
SELECT count(DISTINCT e.employee_id) AS employees FROM skills.employees e JOIN skills.certifications c USING (employee_id) WHERE e.left_on IS NOT NULL AND c.expires_on < e.left_on
```
Second annotator:
```sql
SELECT COUNT(DISTINCT e.employee_id)
FROM skills.employees e
JOIN skills.certifications c ON c.employee_id = e.employee_id
WHERE e.left_on IS NOT NULL
  AND c.expires_on IS NOT NULL
  AND c.expires_on < e.left_on
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 1 | yes |
| apac_analyst | employees → 1 | yes |
| global_manager | employees → 2 | yes |

## K-A-096: What is the target score for each Leadership skill for Managers?

Reference:
```sql
SELECT s.name AS skill, t.target_score FROM skills.role_targets t JOIN skills.skills s USING (skill_id) WHERE t.job_title = 'Manager' AND s.category = 'Leadership'
```
Second annotator:
```sql
SELECT rt.target_score, s.name
FROM skills.role_targets rt
JOIN skills.skills s ON s.skill_id = rt.skill_id
WHERE rt.job_title = 'Manager'
  AND s.category = 'Leadership'
ORDER BY s.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | skill, target_score → Conflict Resolution, 5; Decision Making, 4; Coaching, 3 | yes |
| apac_analyst | skill, target_score → Conflict Resolution, 5; Decision Making, 4; Coaching, 3 | yes |
| global_manager | skill, target_score → Conflict Resolution, 5; Decision Making, 4; Coaching, 3 | yes |

## K-A-097: How many assessor notes are attached to 2025-H2 assessments?

Reference:
```sql
SELECT count(*) AS notes FROM skills.assessor_notes n JOIN skills.assessments a USING (assessment_id) WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
SELECT COUNT(*) AS note_count
FROM skills.assessor_notes an
JOIN skills.assessments a ON an.assessment_id = a.assessment_id
JOIN skills.assessment_cycles ac ON a.cycle_id = ac.cycle_id
WHERE ac.name = '2025-H2'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | notes → 110 | yes |

## K-A-098: What was the average Stakeholder Management score in each cycle, in cycle order? Round to two decimal places.

Reference:
```sql
SELECT c.name AS cycle, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.assessment_cycles c ON c.cycle_id = a.cycle_id WHERE s.name = 'Stakeholder Management' GROUP BY c.cycle_id, c.name ORDER BY c.cycle_id
```
Second annotator:
```sql
WITH stakeholder_skill AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'Stakeholder Management'
),
cycle_scores AS (
    SELECT ac.cycle_id,
           ac.name AS cycle_name,
           ac.starts_on,
           a.score
    FROM skills.assessments a
    JOIN skills.assessment_cycles ac ON a.cycle_id = ac.cycle_id
    JOIN stakeholder_skill ss ON a.skill_id = ss.skill_id
)
SELECT cycle_name,
       round(avg(score)::numeric, 2) AS average_score
FROM cycle_scores
GROUP BY cycle_name, starts_on
ORDER BY starts_on
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cycle, avg_score → 2024-H1, 4.54; 2024-H2, 4.47; 2025-H1, 4.5; 2025-H2, 4.54 | yes |
| apac_analyst | cycle, avg_score → 2024-H1, 4.38; 2024-H2, 4.26; 2025-H1, 4.41; 2025-H2, 4.36 | yes |
| global_manager | cycle, avg_score → 2024-H1, 4.46; 2024-H2, 4.4; 2025-H1, 4.5; 2025-H2, 4.5 | yes |

## K-A-099: How many employees who have left were at career level 4 or 5?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NOT NULL AND level >= 4
```
Second annotator:
```sql
SELECT count(*) AS left_level_4_5_count
FROM skills.employees
WHERE left_on IS NOT NULL
  AND level IN (4, 5)
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 8 | yes |
| apac_analyst | employees → 4 | yes |
| global_manager | employees → 12 | yes |

## K-A-100: What is the average number of certifications per current employee, counting employees with none? Round to two decimal places.

Reference:
```sql
SELECT round((SELECT count(*) FROM skills.certifications c JOIN skills.employees e USING (employee_id) WHERE e.left_on IS NULL)::numeric / (SELECT count(*) FROM skills.employees WHERE left_on IS NULL), 2) AS per_employee
```
Second annotator:
```sql
WITH current_emp_certs AS (
    SELECT
        e.employee_id,
        COUNT(c.certification_id) AS cert_count
    FROM skills.employees e
    LEFT JOIN skills.certifications c
        ON e.employee_id = c.employee_id
    WHERE e.left_on IS NULL
    GROUP BY e.employee_id
)
SELECT round(AVG(cert_count), 2) AS average_certifications
FROM current_emp_certs
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | per_employee → 0.45 | yes |
| apac_analyst | per_employee → 0.6 | yes |
| global_manager | per_employee → 0.52 | yes |
