# Batch skills-03: owner review

25 questions, 25 agree on every persona, 0 to adjudicate.

## K-A-051: What was the average Technical score of Engineers in each cycle, in cycle order? Round to two decimal places.

Reference:
```sql
SELECT c.name AS cycle, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.employees e ON e.employee_id = a.employee_id JOIN skills.assessment_cycles c ON c.cycle_id = a.cycle_id WHERE s.category = 'Technical' AND e.job_title = 'Engineer' GROUP BY c.cycle_id, c.name ORDER BY c.cycle_id
```
Second annotator:
```sql
WITH filtered AS (
    SELECT a.cycle_id, a.score
    FROM skills.assessments a
    JOIN skills.employees e ON a.employee_id = e.employee_id
    JOIN skills.skills s ON a.skill_id = s.skill_id
    WHERE e.job_title = 'Engineer'
      AND s.category = 'Technical'
)
SELECT ac.name AS cycle_name,
       round(avg(f.score)::numeric, 2) AS avg_technical_score
FROM filtered f
JOIN skills.assessment_cycles ac ON f.cycle_id = ac.cycle_id
GROUP BY ac.cycle_id, ac.name
ORDER BY ac.starts_on
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cycle, avg_score → 2024-H1, 3.32; 2024-H2, 3.5; 2025-H1, 3.38; 2025-H2, 3.36 | yes |
| apac_analyst | cycle, avg_score → 2024-H1, 3.09; 2024-H2, 3.14; 2025-H1, 3.05; 2025-H2, 3.18 | yes |
| global_manager | cycle, avg_score → 2024-H1, 3.28; 2024-H2, 3.33; 2025-H1, 3.35; 2025-H2, 3.39 | yes |

## K-A-052: How many employees were assessed in 2025-H2?

Reference:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
SELECT count(DISTINCT employee_id) AS assessed_employees
FROM skills.assessments
WHERE cycle_id = (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
)
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 60 | yes |
| apac_analyst | employees → 70 | yes |
| global_manager | employees → 199 | yes |

## K-A-053: On average, how many skills was each assessed employee scored on in 2025-H2? Round to two decimal places.

Reference:
```sql
SELECT round(count(*)::numeric / count(DISTINCT employee_id), 2) AS skills_per_employee FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH target_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
employee_skill_counts AS (
    SELECT a.employee_id,
           COUNT(DISTINCT a.skill_id) AS skill_count
    FROM skills.assessments a
    JOIN target_cycle tc ON a.cycle_id = tc.cycle_id
    GROUP BY a.employee_id
)
SELECT ROUND(AVG(skill_count), 2) AS avg_skills
FROM employee_skill_counts
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | skills_per_employee → 8.03 | yes |
| apac_analyst | skills_per_employee → 8.36 | yes |
| global_manager | skills_per_employee → 8.18 | yes |

## K-A-054: How many employees have a certification that never expires?

Reference:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM skills.certifications WHERE expires_on IS NULL
```
Second annotator:
```sql
SELECT COUNT(DISTINCT employee_id) AS employee_count
FROM skills.certifications
WHERE expires_on IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 8 | yes |
| apac_analyst | employees → 13 | yes |
| global_manager | employees → 33 | yes |

## K-A-055: What is the average validity of expiring certifications, from issue to expiry, in days? Round to one decimal place.

Reference:
```sql
SELECT round(avg(expires_on - issued_on), 1) AS avg_days FROM skills.certifications WHERE expires_on IS NOT NULL
```
Second annotator:
```sql
SELECT round(avg(expires_on - issued_on), 1) AS average_validity_days
FROM skills.certifications
WHERE expires_on IS NOT NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_days → 980.9 | yes |
| apac_analyst | avg_days → 871.9 | yes |
| global_manager | avg_days → 910.7 | yes |

## K-A-056: How many current Managers are at career level 5?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND job_title = 'Manager' AND level = 5
```
Second annotator:
```sql
SELECT count(*) AS manager_count
FROM skills.employees
WHERE job_title = 'Manager'
  AND level = 5
  AND left_on IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 7 | yes |
| apac_analyst | employees → 7 | yes |
| global_manager | employees → 22 | yes |

## K-A-057: What was the distribution of scores in 2025-H2: how many assessments gave each score from 1 to 5?

Reference:
```sql
SELECT score, count(*) AS assessments FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY score
```
Second annotator:
```sql
WITH cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
score_counts AS (
    SELECT a.score, COUNT(*) AS cnt
    FROM skills.assessments a
    JOIN cycle c ON a.cycle_id = c.cycle_id
    GROUP BY a.score
)
SELECT s.score, COALESCE(sc.cnt, 0) AS assessment_count
FROM generate_series(1, 5) AS s(score)
LEFT JOIN score_counts sc ON sc.score = s.score
ORDER BY s.score
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | score, assessments → 1, 7; 3, 122; 5, 142; 2, 47; 4, 164 | yes |
| apac_analyst | score, assessments → 1, 9; 3, 142; 5, 174; 2, 62; 4, 198 | yes |
| global_manager | score, assessments → 1, 20; 3, 401; 5, 507; 2, 150; 4, 549 | yes |

## K-A-058: Which job title had the highest average score in 2025-H2, and what was it? Round to two decimal places.

Reference:
```sql
SELECT e.job_title, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.employee_id WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY e.job_title ORDER BY avg(a.score) DESC LIMIT 1
```
Second annotator:
```sql
WITH avg_scores AS (
    SELECT e.job_title,
           round(avg(a.score)::numeric, 2) AS avg_score
    FROM skills.assessments a
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    JOIN skills.employees e ON a.employee_id = e.employee_id
    WHERE c.name = '2025-H2'
    GROUP BY e.job_title
)
SELECT job_title, avg_score
FROM avg_scores
ORDER BY avg_score DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | job_title, avg_score → Manager, 4.76 | yes |
| apac_analyst | job_title, avg_score → Manager, 4.47 | yes |
| global_manager | job_title, avg_score → Manager, 4.61 | yes |

## K-A-059: How many employees joined in each year from 2020 to 2025?

Reference:
```sql
SELECT extract(year FROM hired_on)::int AS year, count(*) AS hires FROM skills.employees WHERE hired_on >= DATE '2020-01-01' AND hired_on < DATE '2026-01-01' GROUP BY 1
```
Second annotator:
```sql
WITH years AS (
    SELECT generate_series(2020, 2025)::int AS year
),
hired AS (
    SELECT EXTRACT(YEAR FROM hired_on)::int AS year, COUNT(*) AS cnt
    FROM skills.employees
    WHERE hired_on >= DATE '2020-01-01'
      AND hired_on < DATE '2026-01-01'
    GROUP BY EXTRACT(YEAR FROM hired_on)
)
SELECT y.year, COALESCE(h.cnt, 0) AS employee_count
FROM years y
LEFT JOIN hired h ON y.year = h.year
ORDER BY y.year
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | year, hires → 2022, 8; 2023, 10; 2025, 6; 2020, 4; 2024, 11; 2021, 11 | yes |
| apac_analyst | year, hires → 2022, 7; 2023, 11; 2025, 9; 2020, 6; 2024, 9; 2021, 9 | yes |
| global_manager | year, hires → 2022, 20; 2023, 26; 2025, 24; 2020, 22; 2024, 26; 2021, 28 | yes |

## K-A-060: What was the overall average score in 2025-H2 compared with 2024-H1? Give both averages to two decimal places.

Reference:
```sql
SELECT round(avg(score) FILTER (WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2024-H1')), 2) AS avg_2024_h1, round(avg(score) FILTER (WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')), 2) AS avg_2025_h2 FROM skills.assessments
```
Second annotator:
```sql
WITH avg_2025 AS (
    SELECT round(avg(a.score)::numeric, 2) AS avg_2025_H2
    FROM skills.assessments a
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE c.name = '2025-H2'
),
avg_2024 AS (
    SELECT round(avg(a.score)::numeric, 2) AS avg_2024_H1
    FROM skills.assessments a
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE c.name = '2024-H1'
)
SELECT avg_2025_H2, avg_2024_H1
FROM avg_2025, avg_2024
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_2024_h1, avg_2025_h2 → 3.65, 3.8 | yes |
| apac_analyst | avg_2024_h1, avg_2025_h2 → 3.55, 3.8 | yes |
| global_manager | avg_2024_h1, avg_2025_h2 → 3.62, 3.84 | yes |

## K-A-061: How many current employees in the Data departments are there?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees e JOIN skills.departments d USING (department_id) WHERE e.left_on IS NULL AND d.name LIKE 'Data %'
```
Second annotator:
```sql
SELECT COUNT(*) AS current_employee_count
FROM skills.employees e
JOIN skills.departments d ON e.department_id = d.department_id
WHERE e.left_on IS NULL
  AND d.name ILIKE '%Data%'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 20 | yes |
| apac_analyst | employees → 21 | yes |
| global_manager | employees → 59 | yes |

## K-A-062: What was the average Communication score of Consultants in 2025-H2? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.employees e ON e.employee_id = a.employee_id WHERE s.category = 'Communication' AND e.job_title = 'Consultant' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH filtered AS (
    SELECT a.score
    FROM skills.assessments a
    JOIN skills.employees e ON a.employee_id = e.employee_id
    JOIN skills.skills s ON a.skill_id = s.skill_id
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE e.job_title = 'Consultant'
      AND s.category = 'Communication'
      AND c.name = '2025-H2'
)
SELECT round(avg(score)::numeric, 2) AS avg_communication_score
FROM filtered
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 4.27 | yes |
| apac_analyst | avg_score → 3.9 | yes |
| global_manager | avg_score → 4.09 | yes |

## K-A-063: How many employees scored lower in 2025-H2 than in 2025-H1 on the same skill? Count each employee once.

Reference:
```sql
SELECT count(DISTINCT a.employee_id) AS employees FROM skills.assessments a JOIN skills.assessments b ON b.employee_id = a.employee_id AND b.skill_id = a.skill_id WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H1') AND b.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND b.score < a.score
```
Second annotator:
```sql
WITH h1 AS (
    SELECT a.employee_id, a.skill_id, a.score
    FROM skills.assessments a
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE c.name = '2025-H1'
),
h2 AS (
    SELECT a.employee_id, a.skill_id, a.score
    FROM skills.assessments a
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE c.name = '2025-H2'
)
SELECT COUNT(DISTINCT h1.employee_id) AS employee_count
FROM h1
JOIN h2
  ON h1.employee_id = h2.employee_id
 AND h1.skill_id = h2.skill_id
WHERE h2.score < h1.score
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 8 | yes |
| apac_analyst | employees → 5 | yes |
| global_manager | employees → 16 | yes |

## K-A-064: How many assessments did employees give to themselves?

Reference:
```sql
SELECT count(*) AS assessments FROM skills.assessments WHERE assessor_id = employee_id
```
Second annotator:
```sql
SELECT count(*) AS self_assessment_count
FROM skills.assessments
WHERE employee_id = assessor_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | assessments → 150 | yes |
| apac_analyst | assessments → 150 | yes |
| global_manager | assessments → 440 | yes |

## K-A-065: How many certifications were issued to employees in each job title?

Reference:
```sql
SELECT e.job_title, count(*) AS certifications FROM skills.certifications c JOIN skills.employees e USING (employee_id) GROUP BY e.job_title
```
Second annotator:
```sql
SELECT
    e.job_title,
    COUNT(*) AS certifications_issued
FROM skills.certifications c
JOIN skills.employees e ON c.employee_id = e.employee_id
GROUP BY e.job_title
ORDER BY e.job_title
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | job_title, certifications → Consultant, 8; Engineer, 16; Team Lead, 5; Manager, 3; Analyst, 9 | yes |
| apac_analyst | job_title, certifications → Consultant, 12; Engineer, 20; Team Lead, 5; Manager, 5; Analyst, 10 | yes |
| global_manager | job_title, certifications → Consultant, 34; Engineer, 49; Team Lead, 17; Manager, 10; Analyst, 28 | yes |

## K-A-066: For each skill category, how many skills have a target for Analysts?

Reference:
```sql
SELECT s.category, count(*) AS targets FROM skills.role_targets t JOIN skills.skills s USING (skill_id) WHERE t.job_title = 'Analyst' GROUP BY s.category
```
Second annotator:
```sql
SELECT
    s.category,
    COUNT(*) AS skill_count
FROM skills.skills s
JOIN skills.role_targets rt ON s.skill_id = rt.skill_id
WHERE rt.job_title = 'Analyst'
GROUP BY s.category
ORDER BY s.category
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | category, targets → Communication, 2; Technical, 4 | yes |
| apac_analyst | category, targets → Communication, 2; Technical, 4 | yes |
| global_manager | category, targets → Communication, 2; Technical, 4 | yes |

## K-A-067: Which skills have a target score of 5 for any job title? List the skill and the job title.

Reference:
```sql
SELECT s.name AS skill, t.job_title FROM skills.role_targets t JOIN skills.skills s USING (skill_id) WHERE t.target_score = 5
```
Second annotator:
```sql
SELECT s.name AS skill, rt.job_title
FROM skills.role_targets rt
JOIN skills.skills s ON s.skill_id = rt.skill_id
WHERE rt.target_score = 5
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | skill, job_title → Networking, Analyst; SQL, Analyst; SQL, Consultant; Networking, Consultant; Presenting, Consultant; Data Modelling, Team Lead … (+4 rows) | yes |
| apac_analyst | skill, job_title → Networking, Analyst; SQL, Analyst; SQL, Consultant; Networking, Consultant; Presenting, Consultant; Data Modelling, Team Lead … (+4 rows) | yes |
| global_manager | skill, job_title → Networking, Analyst; SQL, Analyst; SQL, Consultant; Networking, Consultant; Presenting, Consultant; Data Modelling, Team Lead … (+4 rows) | yes |

## K-A-068: What was the median score in 2025-H2?

Reference:
```sql
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY score) AS median_score FROM skills.assessments WHERE cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
)
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY a.score) AS median_score
FROM skills.assessments a
JOIN cycle c ON a.cycle_id = c.cycle_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | median_score → 4.0 | yes |
| apac_analyst | median_score → 4.0 | yes |
| global_manager | median_score → 4.0 | yes |

## K-A-069: How many employees left within two years of being hired?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NOT NULL AND left_on < hired_on + INTERVAL '2 years'
```
Second annotator:
```sql
SELECT COUNT(*) AS employees_left_within_two_years
FROM skills.employees
WHERE left_on IS NOT NULL
  AND left_on <= hired_on + INTERVAL '2 years'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 6 | yes |
| apac_analyst | employees → 5 | yes |
| global_manager | employees → 12 | yes |

## K-A-070: What was the average score in 2025-H2 for each career level, in level order? Round to two decimal places.

Reference:
```sql
SELECT e.level, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.employee_id WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY e.level ORDER BY e.level
```
Second annotator:
```sql
WITH target_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
)
SELECT
    e.level,
    round(avg(a.score)::numeric, 2) AS average_score
FROM skills.assessments a
JOIN target_cycle tc ON a.cycle_id = tc.cycle_id
JOIN skills.employees e ON a.employee_id = e.employee_id
GROUP BY e.level
ORDER BY e.level
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | level, avg_score → 1, 2.53; 2, 2.97; 3, 3.6; 4, 4.25; 5, 4.77 | yes |
| apac_analyst | level, avg_score → 1, 2.52; 2, 2.91; 3, 3.63; 4, 4.24; 5, 4.6 | yes |
| global_manager | level, avg_score → 1, 2.52; 2, 2.96; 3, 3.64; 4, 4.2; 5, 4.69 | yes |

## K-A-071: How many Kubernetes Administrator certifications will still be valid on 1 January 2027?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications WHERE name = 'Kubernetes Administrator' AND issued_on <= DATE '2027-01-01' AND (expires_on IS NULL OR expires_on > DATE '2027-01-01')
```
Second annotator:
```sql
SELECT count(*) AS valid_kubernetes_admin_certifications
FROM skills.certifications
WHERE name = 'Kubernetes Administrator'
  AND (expires_on IS NULL OR expires_on >= DATE '2027-01-01')
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 3 | yes |
| apac_analyst | certifications → 5 | yes |
| global_manager | certifications → 9 | yes |

## K-A-072: Who is the longest-serving current employee, and when were they hired?

Reference:
```sql
SELECT name, hired_on FROM skills.employees WHERE left_on IS NULL ORDER BY hired_on LIMIT 1
```
Second annotator:
```sql
SELECT name, hired_on
FROM skills.employees
WHERE left_on IS NULL
ORDER BY hired_on ASC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, hired_on → Fatima Varga, 2015-01-15 | yes |
| apac_analyst | name, hired_on → Vera Fong, 2016-01-05 | yes |
| global_manager | name, hired_on → Fatima Varga, 2015-01-15 | yes |

## K-A-073: How many employees were assessed on Negotiation in 2025?

Reference:
```sql
SELECT count(DISTINCT a.employee_id) AS employees FROM skills.assessments a JOIN skills.skills s USING (skill_id) WHERE s.name = 'Negotiation' AND a.assessed_on >= DATE '2025-01-01' AND a.assessed_on < DATE '2026-01-01'
```
Second annotator:
```sql
WITH neg_skill AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'Negotiation'
)
SELECT COUNT(DISTINCT a.employee_id) AS employee_count
FROM skills.assessments a
JOIN neg_skill ns ON a.skill_id = ns.skill_id
WHERE a.assessed_on >= DATE '2025-01-01'
  AND a.assessed_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 55 | yes |
| apac_analyst | employees → 52 | yes |
| global_manager | employees → 170 | yes |

## K-A-074: What is the average length of an assessor note, in characters? Round to one decimal place.

Reference:
```sql
SELECT round(avg(length(note)), 1) AS avg_chars FROM skills.assessor_notes
```
Second annotator:
```sql
SELECT round(avg(length(note))::numeric, 1) AS avg_note_length
FROM skills.assessor_notes
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | avg_chars → 33.8 | yes |

## K-A-075: How many line managers have more than 5 current direct reports?

Reference:
```sql
SELECT count(*) AS managers FROM (SELECT manager_id FROM skills.employees WHERE left_on IS NULL AND manager_id IS NOT NULL GROUP BY manager_id HAVING count(*) > 5) t
```
Second annotator:
```sql
WITH current_emps AS (
    SELECT employee_id, manager_id
    FROM skills.employees
    WHERE left_on IS NULL
)
SELECT count(*) AS manager_count
FROM (
    SELECT manager_id
    FROM current_emps
    WHERE manager_id IS NOT NULL
    GROUP BY manager_id
    HAVING count(*) > 5
) m
JOIN current_emps ce ON ce.employee_id = m.manager_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | managers → 4 | yes |
| apac_analyst | managers → 4 | yes |
| global_manager | managers → 12 | yes |
