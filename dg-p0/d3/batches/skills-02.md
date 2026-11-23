# Batch skills-02: owner review

25 questions, 24 agree on every persona, 1 to adjudicate.

## K-A-026: How many employees work in each department, counting only current employees?

Reference:
```sql
SELECT d.name AS department, count(*) AS employees FROM skills.employees e JOIN skills.departments d USING (department_id) WHERE e.left_on IS NULL GROUP BY d.name
```
Second annotator:
```sql
SELECT d.name AS department_name,
       COUNT(e.employee_id) AS employee_count
FROM skills.departments d
JOIN skills.employees e
  ON e.department_id = d.department_id
WHERE e.left_on IS NULL
GROUP BY d.name
ORDER BY d.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | department, employees → Support EMEA, 15; Engineering EMEA, 15; Consulting EMEA, 15; Data EMEA, 20 | yes |
| apac_analyst | department, employees → Data APAC, 21; Consulting APAC, 17; Support APAC, 18; Engineering APAC, 17 | yes |
| global_manager | department, employees → Data APAC, 21; Consulting APAC, 17; Data AMER, 18; Engineering AMER, 16; Support EMEA, 15; Support AMER, 19 … (+6 rows) | yes |

## K-A-027: What was the average score in each cycle, in cycle order? Round to two decimal places.

Reference:
```sql
SELECT c.name AS cycle, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.assessment_cycles c USING (cycle_id) GROUP BY c.cycle_id, c.name ORDER BY c.cycle_id
```
Second annotator:
```sql
SELECT
    ac.name AS cycle,
    round(avg(a.score)::numeric, 2) AS average_score
FROM skills.assessments a
JOIN skills.assessment_cycles ac ON a.cycle_id = ac.cycle_id
GROUP BY ac.cycle_id, ac.name, ac.starts_on
ORDER BY ac.starts_on
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cycle, avg_score → 2024-H1, 3.65; 2024-H2, 3.77; 2025-H1, 3.75; 2025-H2, 3.8 | yes |
| apac_analyst | cycle, avg_score → 2024-H1, 3.55; 2024-H2, 3.68; 2025-H1, 3.7; 2025-H2, 3.8 | yes |
| global_manager | cycle, avg_score → 2024-H1, 3.62; 2024-H2, 3.7; 2025-H1, 3.77; 2025-H2, 3.84 | yes |

## K-A-028: How many current employees are at each career level?

Reference:
```sql
SELECT level, count(*) AS employees FROM skills.employees WHERE left_on IS NULL GROUP BY level
```
Second annotator:
```sql
SELECT
    level,
    COUNT(*) AS employee_count
FROM skills.employees
WHERE left_on IS NULL
GROUP BY level
ORDER BY level
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | level, employees → 1, 8; 3, 15; 5, 13; 2, 14; 4, 15 | yes |
| apac_analyst | level, employees → 1, 12; 3, 10; 5, 13; 4, 26; 2, 12 | yes |
| global_manager | level, employees → 1, 25; 3, 44; 5, 44; 2, 40; 4, 60 | yes |

## K-A-029: How many assessments gave a score of 1 (novice) across all cycles?

Reference:
```sql
SELECT count(*) AS assessments FROM skills.assessments WHERE score = 1
```
Second annotator:
```sql
SELECT count(*) AS assessment_count
FROM skills.assessments
WHERE score = 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | assessments → 36 | yes |
| apac_analyst | assessments → 39 | yes |
| global_manager | assessments → 89 | yes |

## K-A-030: How many employees hold each certification?

Reference:
```sql
SELECT name, count(DISTINCT employee_id) AS employees FROM skills.certifications GROUP BY name
```
Second annotator:
```sql
SELECT
    name,
    COUNT(DISTINCT employee_id) AS employee_count
FROM skills.certifications
GROUP BY name
ORDER BY name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, employees → Cloud Practitioner, 7; Data Engineer, 5; ITIL Foundation, 6; Kubernetes Administrator, 5; PMP, 6; Scrum Master, 3 … (+2 rows) | yes |
| apac_analyst | name, employees → Cloud Practitioner, 4; Data Engineer, 9; ITIL Foundation, 7; Kubernetes Administrator, 10; PMP, 5; Scrum Master, 4 … (+2 rows) | yes |
| global_manager | name, employees → Cloud Practitioner, 18; Data Engineer, 15; ITIL Foundation, 19; Kubernetes Administrator, 21; PMP, 14; Scrum Master, 15 … (+2 rows) | yes |

## K-A-031: How many certifications have already expired as of 1 January 2026?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications WHERE expires_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT COUNT(*) AS expired_certifications_count
FROM skills.certifications
WHERE expires_on IS NOT NULL
  AND expires_on < DATE '2026-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 10 | yes |
| apac_analyst | certifications → 17 | yes |
| global_manager | certifications → 38 | yes |

## K-A-032: How many current employees have no certification at all?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees e WHERE e.left_on IS NULL AND NOT EXISTS (SELECT 1 FROM skills.certifications c WHERE c.employee_id = e.employee_id)
```
Second annotator:
```sql
SELECT COUNT(*) AS count
FROM skills.employees e
WHERE e.left_on IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM skills.certifications c
    WHERE c.employee_id = e.employee_id
  )
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 39 | yes |
| apac_analyst | employees → 38 | yes |
| global_manager | employees → 117 | yes |

## K-A-033: What was the average Leadership score of Team Leads in 2025-H2? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.employees e ON e.employee_id = a.employee_id WHERE s.category = 'Leadership' AND e.job_title = 'Team Lead' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH target_cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
leadership_skills AS (
    SELECT skill_id
    FROM skills.skills
    WHERE category = 'Leadership'
),
team_leads AS (
    SELECT employee_id
    FROM skills.employees
    WHERE job_title = 'Team Lead'
)
SELECT round(avg(a.score)::numeric, 2) AS average_leadership_score
FROM skills.assessments a
JOIN target_cycle tc ON a.cycle_id = tc.cycle_id
JOIN leadership_skills ls ON a.skill_id = ls.skill_id
JOIN team_leads tl ON a.employee_id = tl.employee_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 4.11 | yes |
| apac_analyst | avg_score → 4.24 | yes |
| global_manager | avg_score → 4.26 | yes |

## K-A-034: How many skill targets are set for each job title?

Reference:
```sql
SELECT job_title, count(*) AS targets FROM skills.role_targets GROUP BY job_title
```
Second annotator:
```sql
SELECT
    job_title,
    COUNT(*) AS target_count
FROM skills.role_targets
GROUP BY job_title
ORDER BY job_title
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | job_title, targets → Engineer, 6; Manager, 9; Consultant, 8; Analyst, 6; Team Lead, 9 | yes |
| apac_analyst | job_title, targets → Engineer, 6; Manager, 9; Consultant, 8; Analyst, 6; Team Lead, 9 | yes |
| global_manager | job_title, targets → Engineer, 6; Manager, 9; Consultant, 8; Analyst, 6; Team Lead, 9 | yes |

## K-A-035: What is the average target score for Engineers? Round to two decimal places.

Reference:
```sql
SELECT round(avg(target_score), 2) AS avg_target FROM skills.role_targets WHERE job_title = 'Engineer'
```
Second annotator:
```sql
SELECT ROUND(AVG(target_score)::numeric, 2) AS average_target_score
FROM skills.role_targets
WHERE job_title = 'Engineer'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_target → 2.67 | yes |
| apac_analyst | avg_target → 2.67 | yes |
| global_manager | avg_target → 2.67 | yes |

## K-A-036: How many current employees are below their job title's target on at least one skill, using each employee's latest score?

Reference:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM (SELECT e.employee_id, e.name, e.job_title, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g WHERE g.gap > 0
```
Second annotator:
```sql
WITH latest_assessments AS (
    SELECT
        a.employee_id,
        a.skill_id,
        a.score,
        ROW_NUMBER() OVER (PARTITION BY a.employee_id, a.skill_id ORDER BY a.assessed_on DESC) AS rn
    FROM skills.assessments a
    JOIN skills.employees e ON e.employee_id = a.employee_id
    WHERE e.left_on IS NULL
),
current_latest AS (
    SELECT
        la.employee_id,
        la.skill_id,
        la.score,
        e.job_title
    FROM latest_assessments la
    JOIN skills.employees e ON e.employee_id = la.employee_id
    WHERE la.rn = 1
),
below_target AS (
    SELECT DISTINCT cl.employee_id
    FROM current_latest cl
    JOIN skills.role_targets rt
        ON rt.job_title = cl.job_title
       AND rt.skill_id = cl.skill_id
    WHERE cl.score < rt.target_score
)
SELECT COUNT(*) AS below_target_employee_count
FROM below_target
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 48 | yes |
| apac_analyst | employees → 62 | yes |
| global_manager | employees → 166 | yes |

## K-A-037: What is the average skill gap per job title for current employees, counting only skills that have a target and using the latest score? Round to two decimal places.

Reference:
```sql
SELECT job_title, round(avg(gap), 2) AS avg_gap FROM (SELECT e.employee_id, e.name, e.job_title, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g GROUP BY job_title
```
Second annotator:
```sql
WITH latest_assessments AS (
    SELECT
        a.employee_id,
        a.skill_id,
        a.score,
        ROW_NUMBER() OVER (PARTITION BY a.employee_id, a.skill_id ORDER BY a.assessed_on DESC) AS rn
    FROM skills.assessments a
),
current_emp AS (
    SELECT employee_id, job_title
    FROM skills.employees
    WHERE left_on IS NULL
),
gaps AS (
    SELECT
        ce.job_title,
        rt.target_score - la.score AS gap
    FROM latest_assessments la
    JOIN current_emp ce ON ce.employee_id = la.employee_id
    JOIN skills.role_targets rt
        ON rt.job_title = ce.job_title
       AND rt.skill_id = la.skill_id
    WHERE la.rn = 1
)
SELECT
    job_title,
    ROUND(AVG(gap)::numeric, 2) AS average_gap
FROM gaps
GROUP BY job_title
ORDER BY job_title
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | job_title, avg_gap → Analyst, 0.68; Consultant, 0.17; Engineer, -0.72; Manager, -1.0; Team Lead, -0.13 | yes |
| apac_analyst | job_title, avg_gap → Analyst, 0.81; Consultant, 0.2; Engineer, -0.53; Manager, -0.72; Team Lead, -0.15 | yes |
| global_manager | job_title, avg_gap → Analyst, 0.65; Consultant, 0.13; Engineer, -0.72; Manager, -0.86; Team Lead, -0.19 | yes |

## K-A-038: Which skill has the largest total gap across current employees, using latest scores and counting only shortfalls (gaps above 0)?

Reference:
```sql
SELECT s.name, sum(g.gap) AS total_gap FROM (SELECT e.employee_id, e.name, e.job_title, t.skill_id, t.target_score - l.score AS gap FROM skills.employees e JOIN skills.role_targets t ON t.job_title = e.job_title JOIN (SELECT DISTINCT ON (a.employee_id, a.skill_id) a.employee_id, a.skill_id, a.score FROM skills.assessments a ORDER BY a.employee_id, a.skill_id, a.cycle_id DESC) l ON l.employee_id = e.employee_id AND l.skill_id = t.skill_id WHERE e.left_on IS NULL) g JOIN skills.skills s USING (skill_id) WHERE g.gap > 0 GROUP BY s.skill_id, s.name ORDER BY total_gap DESC LIMIT 1
```
Second annotator:
```sql
WITH current_emps AS (
    SELECT employee_id, job_title
    FROM skills.employees
    WHERE left_on IS NULL
),
latest_assessments AS (
    SELECT a.employee_id, a.skill_id, a.score,
           ROW_NUMBER() OVER (PARTITION BY a.employee_id, a.skill_id ORDER BY a.assessed_on DESC) AS rn
    FROM skills.assessments a
    JOIN current_emps ce ON ce.employee_id = a.employee_id
),
latest_scores AS (
    SELECT employee_id, skill_id, score
    FROM latest_assessments
    WHERE rn = 1
),
gaps AS (
    SELECT ls.skill_id,
           GREATEST(rt.target_score - ls.score, 0) AS gap
    FROM latest_scores ls
    JOIN current_emps ce ON ce.employee_id = ls.employee_id
    JOIN skills.role_targets rt ON rt.job_title = ce.job_title AND rt.skill_id = ls.skill_id
)
SELECT s.name
FROM gaps g
JOIN skills.skills s ON s.skill_id = g.skill_id
GROUP BY s.name
ORDER BY SUM(g.gap) DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, total_gap → SQL, 60 | NO: 1 columns vs 2 |
| | second: name → SQL | |
| apac_analyst | name, total_gap → SQL, 64 | NO: 1 columns vs 2 |
| | second: name → SQL | |
| global_manager | name, total_gap → SQL, 172 | NO: 1 columns vs 2 |
| | second: name → SQL | |

**Disagreement: owner to adjudicate.**

## K-A-039: How many employees were assessed in every one of the four cycles?

Reference:
```sql
SELECT count(*) AS employees FROM (SELECT employee_id FROM skills.assessments GROUP BY employee_id HAVING count(DISTINCT cycle_id) = 4) t
```
Second annotator:
```sql
WITH total_cycles AS (
    SELECT count(*) AS cnt
    FROM skills.assessment_cycles
),
emp_cycles AS (
    SELECT employee_id, count(DISTINCT cycle_id) AS cycle_cnt
    FROM skills.assessments
    GROUP BY employee_id
)
SELECT count(*) AS employee_count
FROM emp_cycles, total_cycles
WHERE emp_cycles.cycle_cnt = total_cycles.cnt
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 41 | yes |
| apac_analyst | employees → 45 | yes |
| global_manager | employees → 128 | yes |

## K-A-040: Which assessor gave the most assessments in 2025, and how many? Give the assessor's name.

Reference:
```sql
SELECT e.name, count(*) AS assessments FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.assessor_id WHERE a.assessed_on >= DATE '2025-01-01' AND a.assessed_on < DATE '2026-01-01' GROUP BY e.employee_id, e.name ORDER BY assessments DESC LIMIT 1
```
Second annotator:
```sql
SELECT e.name AS assessor_name, COUNT(*) AS assessment_count
FROM skills.assessments a
JOIN skills.employees e ON e.employee_id = a.assessor_id
WHERE a.assessed_on >= DATE '2025-01-01'
  AND a.assessed_on < DATE '2026-01-01'
GROUP BY e.name
ORDER BY assessment_count DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, assessments → Vera Zhou, 279 | yes |
| apac_analyst | name, assessments → Aria Ibrahim, 316 | yes |
| global_manager | name, assessments → Tara Ibrahim, 329 | yes |

## K-A-041: What was the average score each assessor gave in 2025? Give the assessor's name and the average to two decimal places.

Reference:
```sql
SELECT e.name, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.assessor_id WHERE a.assessed_on >= DATE '2025-01-01' AND a.assessed_on < DATE '2026-01-01' GROUP BY e.employee_id, e.name
```
Second annotator:
```sql
WITH filtered AS (
    SELECT assessor_id, score
    FROM skills.assessments
    WHERE assessed_on >= DATE '2025-01-01'
      AND assessed_on < DATE '2026-01-01'
)
SELECT e.name AS assessor_name,
       ROUND(AVG(f.score)::numeric, 2) AS average_score
FROM filtered f
JOIN skills.employees e ON f.assessor_id = e.employee_id
GROUP BY e.name
ORDER BY e.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, avg_score → Zoe Schmidt, 3.58; Vera Zhou, 3.96; Zoe Lund, 3.91; Fatima Varga, 3.6 | yes |
| apac_analyst | name, avg_score → Zoe Varga, 3.77; Aria Ibrahim, 3.8; Oscar Yilmaz, 3.55; Vera Tanaka, 3.88 | yes |
| global_manager | name, avg_score → Zoe Schmidt, 3.58; Zoe Varga, 3.77; Vera Zhou, 3.96; Nia Zhou, 4.07; Karim Quinn, 4.03; Aria Ibrahim, 3.8 … (+6 rows) | yes |

## K-A-042: How many employees improved their Cloud Architecture score from 2024-H2 to 2025-H2?

Reference:
```sql
SELECT count(*) AS employees FROM skills.assessments a JOIN skills.assessments b ON b.employee_id = a.employee_id AND b.skill_id = a.skill_id JOIN skills.skills s ON s.skill_id = a.skill_id WHERE s.name = 'Cloud Architecture' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2024-H2') AND b.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') AND b.score > a.score
```
Second annotator:
```sql
WITH skill AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'Cloud Architecture'
),
cycle_2024 AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2024-H2'
),
cycle_2025 AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
scores_2024 AS (
    SELECT a.employee_id, a.score
    FROM skills.assessments a
    JOIN skill s ON a.skill_id = s.skill_id
    JOIN cycle_2024 c ON a.cycle_id = c.cycle_id
),
scores_2025 AS (
    SELECT a.employee_id, a.score
    FROM skills.assessments a
    JOIN skill s ON a.skill_id = s.skill_id
    JOIN cycle_2025 c ON a.cycle_id = c.cycle_id
)
SELECT COUNT(DISTINCT s2024.employee_id) AS improved_count
FROM scores_2024 s2024
JOIN scores_2025 s2025 ON s2024.employee_id = s2025.employee_id
WHERE s2025.score > s2024.score
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 1 | yes |
| apac_analyst | employees → 2 | yes |
| global_manager | employees → 3 | yes |

## K-A-043: How many people have left the company in total?

Reference:
```sql
SELECT count(*) AS leavers FROM skills.employees WHERE left_on IS NOT NULL
```
Second annotator:
```sql
SELECT count(*) AS total_left
FROM skills.employees
WHERE left_on IS NOT NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | leavers → 12 | yes |
| apac_analyst | leavers → 9 | yes |
| global_manager | leavers → 29 | yes |

## K-A-044: What is the average number of years of service of current employees as of 1 January 2026? Round to one decimal place.

Reference:
```sql
SELECT round(avg((DATE '2026-01-01' - hired_on) / 365.25), 1) AS avg_years FROM skills.employees WHERE left_on IS NULL
```
Second annotator:
```sql
SELECT round(avg((date '2026-01-01' - hired_on) / 365.25), 1) AS average_years_of_service
FROM skills.employees
WHERE left_on IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_years → 4.8 | yes |
| apac_analyst | avg_years → 4.9 | yes |
| global_manager | avg_years → 5.0 | yes |

## K-A-045: How many direct reports does each line manager have among current employees? Give the manager's name and the count.

Reference:
```sql
SELECT m.name, count(*) AS reports FROM skills.employees e JOIN skills.employees m ON m.employee_id = e.manager_id WHERE e.left_on IS NULL GROUP BY m.employee_id, m.name
```
Second annotator:
```sql
WITH current_emps AS (
    SELECT employee_id, name, manager_id
    FROM skills.employees
    WHERE left_on IS NULL
)
SELECT m.name AS manager_name,
       COUNT(r.employee_id) AS direct_report_count
FROM current_emps m
LEFT JOIN current_emps r ON r.manager_id = m.employee_id
WHERE m.employee_id IN (SELECT DISTINCT manager_id FROM current_emps WHERE manager_id IS NOT NULL)
GROUP BY m.employee_id, m.name
ORDER BY m.name
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | name, reports → Zoe Lund, 14; Vera Zhou, 19; Zoe Schmidt, 14; Fatima Varga, 14 | yes |
| apac_analyst | name, reports → Zoe Varga, 16; Aria Ibrahim, 20; Oscar Yilmaz, 17; Vera Tanaka, 16 | yes |
| global_manager | name, reports → Karim Quinn, 17; Zoe Lund, 14; Zoe Varga, 16; Aria Ibrahim, 20; Zoe Weber, 18; Oscar Yilmaz, 17 … (+6 rows) | yes |

## K-A-046: What was the average score for Domain skills in each cycle, in cycle order? Round to two decimal places.

Reference:
```sql
SELECT c.name AS cycle, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s USING (skill_id) JOIN skills.assessment_cycles c USING (cycle_id) WHERE s.category = 'Domain' GROUP BY c.cycle_id, c.name ORDER BY c.cycle_id
```
Second annotator:
```sql
WITH domain_assessments AS (
    SELECT a.cycle_id, a.score
    FROM skills.assessments a
    JOIN skills.skills s ON a.skill_id = s.skill_id
    WHERE s.category = 'Domain'
)
SELECT c.name AS cycle_name,
       ROUND(AVG(da.score)::numeric, 2) AS average_score
FROM domain_assessments da
JOIN skills.assessment_cycles c ON da.cycle_id = c.cycle_id
GROUP BY c.cycle_id, c.name
ORDER BY c.starts_on
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | cycle, avg_score → 2024-H1, 3.58; 2024-H2, 3.65; 2025-H1, 3.6; 2025-H2, 3.51 | yes |
| apac_analyst | cycle, avg_score → 2024-H1, 3.59; 2024-H2, 3.7; 2025-H1, 3.62; 2025-H2, 3.74 | yes |
| global_manager | cycle, avg_score → 2024-H1, 3.66; 2024-H2, 3.65; 2025-H1, 3.66; 2025-H2, 3.67 | yes |

## K-A-047: How many assessments are dated after the day the employee left (strictly later than their leaving date)?

Reference:
```sql
SELECT count(*) AS assessments FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.employee_id WHERE e.left_on IS NOT NULL AND a.assessed_on > e.left_on
```
Second annotator:
```sql
SELECT count(*)
FROM skills.assessments a
JOIN skills.employees e ON a.employee_id = e.employee_id
WHERE e.left_on IS NOT NULL
  AND a.assessed_on > e.left_on
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | assessments → 56 | yes |
| apac_analyst | assessments → 41 | yes |
| global_manager | assessments → 133 | yes |

## K-A-048: Which department had the highest average score in 2025-H2, and what was it? Round to two decimal places.

Reference:
```sql
SELECT d.name AS department, round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.employee_id JOIN skills.departments d ON d.department_id = e.department_id WHERE a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2') GROUP BY d.department_id, d.name ORDER BY avg(a.score) DESC LIMIT 1
```
Second annotator:
```sql
WITH cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
),
dept_scores AS (
    SELECT d.name AS department_name,
           AVG(a.score)::numeric AS avg_score
    FROM skills.assessments a
    JOIN skills.employees e ON a.employee_id = e.employee_id
    JOIN skills.departments d ON e.department_id = d.department_id
    JOIN cycle c ON a.cycle_id = c.cycle_id
    GROUP BY d.name
)
SELECT department_name,
       ROUND(avg_score, 2) AS average_score
FROM dept_scores
ORDER BY avg_score DESC
LIMIT 1
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | department, avg_score → Consulting EMEA, 3.95 | yes |
| apac_analyst | department, avg_score → Engineering APAC, 3.94 | yes |
| global_manager | department, avg_score → Engineering AMER, 4.13 | yes |

## K-A-049: How many Security+ certifications are held by current employees?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications c JOIN skills.employees e USING (employee_id) WHERE c.name = 'Security+' AND e.left_on IS NULL
```
Second annotator:
```sql
SELECT count(*)
FROM skills.certifications c
JOIN skills.employees e ON e.employee_id = c.employee_id
WHERE e.left_on IS NULL
  AND c.name = 'Security+'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 5 | yes |
| apac_analyst | certifications → 1 | yes |
| global_manager | certifications → 12 | yes |

## K-A-050: How many assessor notes are there for scores of 1 or 2?

Reference:
```sql
SELECT count(*) AS notes FROM skills.assessor_notes n JOIN skills.assessments a USING (assessment_id) WHERE a.score <= 2
```
Second annotator:
```sql
SELECT COUNT(*) AS note_count
FROM skills.assessor_notes an
JOIN skills.assessments a ON a.assessment_id = an.assessment_id
WHERE a.score IN (1, 2)
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | refused (InsufficientPrivilege) | yes |
| apac_analyst | refused (InsufficientPrivilege) | yes |
| global_manager | notes → 42 | yes |
