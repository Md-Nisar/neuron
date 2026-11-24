# Batch fresh-skills-a: owner review

20 questions, 19 agree on every persona, 1 to adjudicate.

## K-FA-01: How many employees hold the Kubernetes Administrator certification?

Reference:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM skills.certifications WHERE name = 'Kubernetes Administrator'
```
Second annotator:
```sql
SELECT COUNT(DISTINCT employee_id) AS employee_count
FROM skills.certifications
WHERE name = 'Kubernetes Administrator'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 5 | yes |
| apac_analyst | employees → 10 | yes |
| global_manager | employees → 21 | yes |

## K-FA-02: How many current employees are Team Leads?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND job_title = 'Team Lead'
```
Second annotator:
```sql
SELECT count(*) AS team_lead_count
FROM skills.employees
WHERE job_title = 'Team Lead'
  AND left_on IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 7 | yes |
| apac_analyst | employees → 11 | yes |
| global_manager | employees → 24 | yes |

## K-FA-03: How many current employees are in the Engineering EMEA department?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees e JOIN skills.departments d ON d.department_id = e.department_id WHERE e.left_on IS NULL AND d.name = 'Engineering EMEA'
```
Second annotator:
```sql
SELECT count(*) AS employee_count
FROM skills.employees e
JOIN skills.departments d ON e.department_id = d.department_id
WHERE d.name = 'Engineering EMEA'
  AND e.left_on IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 15 | yes |
| apac_analyst | employees → 0 | yes |
| global_manager | employees → 15 | yes |

## K-FA-04: What was the average Python score in the 2025-H2 cycle? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s ON s.skill_id = a.skill_id WHERE s.name = 'Python' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
SELECT ROUND(AVG(a.score), 2) AS average_score
FROM skills.assessments a
JOIN skills.skills s ON a.skill_id = s.skill_id
JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
WHERE s.name = 'Python' AND c.name = '2025-H2'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 3.48 | yes |
| apac_analyst | avg_score → 3.35 | yes |
| global_manager | avg_score → 3.46 | yes |

## K-FA-05: How many Security+ certifications were issued in 2025?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications WHERE name = 'Security+' AND issued_on >= DATE '2025-01-01' AND issued_on < DATE '2026-01-01'
```
Second annotator:
```sql
SELECT count(*)
FROM skills.certifications
WHERE name = 'Security+'
  AND EXTRACT(YEAR FROM issued_on) = 2025
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 4 | yes |
| apac_analyst | certifications → 1 | yes |
| global_manager | certifications → 8 | yes |

## K-FA-06: How many people, including those who have left, have worked in the Data departments?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees e JOIN skills.departments d ON d.department_id = e.department_id WHERE d.name LIKE 'Data %'
```
Second annotator:
```sql
SELECT COUNT(*) AS people_count
FROM skills.employees e
JOIN skills.departments d ON e.department_id = d.department_id
WHERE d.name ILIKE '%Data%'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 22 | yes |
| apac_analyst | employees → 23 | yes |
| global_manager | employees → 65 | yes |

## K-FA-07: How many assessments did Fatima Varga carry out as an assessor?

Reference:
```sql
SELECT count(*) AS assessments FROM skills.assessments a JOIN skills.employees e ON e.employee_id = a.assessor_id WHERE e.name = 'Fatima Varga'
```
Second annotator:
```sql
WITH fv AS (
    SELECT employee_id
    FROM skills.employees
    WHERE name = 'Fatima Varga'
)
SELECT COUNT(*) AS assessment_count
FROM skills.assessments a
JOIN fv ON a.assessor_id = fv.employee_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | assessments → 433 | yes |
| apac_analyst | assessments → 0 | yes |
| global_manager | assessments → 433 | yes |

## K-FA-08: How many Engineers have left the company?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE job_title = 'Engineer' AND left_on IS NOT NULL
```
Second annotator:
```sql
SELECT count(*) AS engineer_left_count
FROM skills.employees
WHERE job_title = 'Engineer'
  AND left_on IS NOT NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 6 | yes |
| apac_analyst | employees → 4 | yes |
| global_manager | employees → 13 | yes |

## K-FA-09: How many PMP certifications expired before 2026-11-23?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications WHERE name = 'PMP' AND expires_on < DATE '2026-11-23'
```
Second annotator:
```sql
SELECT count(*)
FROM skills.certifications
WHERE name = 'PMP'
  AND expires_on IS NOT NULL
  AND expires_on < DATE '2026-11-23'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 3 | yes |
| apac_analyst | certifications → 4 | yes |
| global_manager | certifications → 7 | yes |

## K-FA-10: What was the average Stakeholder Management score in the 2025-H1 cycle? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s ON s.skill_id = a.skill_id WHERE s.name = 'Stakeholder Management' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H1')
```
Second annotator:
```sql
WITH skill AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'Stakeholder Management'
),
cycle AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H1'
)
SELECT round(avg(a.score)::numeric, 2) AS average_score
FROM skills.assessments a
JOIN skill s ON a.skill_id = s.skill_id
JOIN cycle c ON a.cycle_id = c.cycle_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 4.5 | yes |
| apac_analyst | avg_score → 4.41 | yes |
| global_manager | avg_score → 4.5 | yes |

## K-FA-11: How many current employees are not Managers?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees WHERE left_on IS NULL AND job_title <> 'Manager'
```
Second annotator:
```sql
SELECT count(*) AS current_non_manager_employees
FROM skills.employees
WHERE left_on IS NULL
  AND job_title <> 'Manager'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 57 | yes |
| apac_analyst | employees → 61 | yes |
| global_manager | employees → 184 | yes |

## K-FA-12: What is the target Negotiation score for Consultants?

Reference:
```sql
SELECT t.target_score FROM skills.role_targets t JOIN skills.skills s ON s.skill_id = t.skill_id WHERE t.job_title = 'Consultant' AND s.name = 'Negotiation'
```
Second annotator:
```sql
WITH neg_skill AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'Negotiation'
)
SELECT rt.target_score
FROM skills.role_targets rt
JOIN neg_skill ns ON rt.skill_id = ns.skill_id
WHERE rt.job_title = 'Consultant'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | target_score → 3 | yes |
| apac_analyst | target_score → 3 | yes |
| global_manager | target_score → 3 | yes |

## K-FA-13: How many employees hold an ITIL certification?

Reference:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM skills.certifications WHERE name LIKE 'ITIL%'
```
Second annotator:
```sql
SELECT COUNT(DISTINCT employee_id)
FROM skills.certifications
WHERE name ILIKE 'ITIL'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 6 | NO: values differ |
| | second: count → 0 | |
| apac_analyst | employees → 7 | NO: values differ |
| | second: count → 0 | |
| global_manager | employees → 19 | NO: values differ |
| | second: count → 0 | |

**Disagreement: owner to adjudicate.**

## K-FA-14: How many current employees report directly to Zoe Schmidt?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees e JOIN skills.employees m ON m.employee_id = e.manager_id WHERE e.left_on IS NULL AND m.name = 'Zoe Schmidt'
```
Second annotator:
```sql
WITH zoe AS (
    SELECT employee_id
    FROM skills.employees
    WHERE name = 'Zoe Schmidt'
      AND left_on IS NULL
)
SELECT COUNT(*) AS direct_reports
FROM skills.employees e
JOIN zoe z ON e.manager_id = z.employee_id
WHERE e.left_on IS NULL
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 14 | yes |
| apac_analyst | employees → 0 | yes |
| global_manager | employees → 14 | yes |

## K-FA-15: What was the average DevOps score of Team Leads in the 2025-H1 cycle? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s ON s.skill_id = a.skill_id JOIN skills.employees e ON e.employee_id = a.employee_id WHERE s.name = 'DevOps' AND e.job_title = 'Team Lead' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H1')
```
Second annotator:
```sql
WITH filtered AS (
    SELECT a.score
    FROM skills.assessments a
    JOIN skills.employees e ON a.employee_id = e.employee_id
    JOIN skills.skills s ON a.skill_id = s.skill_id
    JOIN skills.assessment_cycles c ON a.cycle_id = c.cycle_id
    WHERE e.job_title = 'Team Lead'
      AND s.name = 'DevOps'
      AND c.name = '2025-H1'
)
SELECT round(avg(score)::numeric, 2) AS average_score
FROM filtered
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → None | yes |
| apac_analyst | avg_score → None | yes |
| global_manager | avg_score → None | yes |

## K-FA-16: How many employees are certified Scrum Masters?

Reference:
```sql
SELECT count(DISTINCT employee_id) AS employees FROM skills.certifications WHERE name = 'Scrum Master'
```
Second annotator:
```sql
SELECT count(DISTINCT employee_id) AS certified_scrum_masters
FROM skills.certifications
WHERE name ILIKE '%Scrum Master%'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 3 | yes |
| apac_analyst | employees → 4 | yes |
| global_manager | employees → 15 | yes |

## K-FA-17: How many employees in the Support departments were hired in 2024?

Reference:
```sql
SELECT count(*) AS employees FROM skills.employees e JOIN skills.departments d ON d.department_id = e.department_id WHERE d.name LIKE 'Support %' AND e.hired_on >= DATE '2024-01-01' AND e.hired_on < DATE '2025-01-01'
```
Second annotator:
```sql
SELECT count(*) AS employee_count
FROM skills.employees e
JOIN skills.departments d ON e.department_id = d.department_id
WHERE d.name ILIKE '%support%'
  AND e.hired_on >= DATE '2024-01-01'
  AND e.hired_on < DATE '2025-01-01'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | employees → 5 | yes |
| apac_analyst | employees → 3 | yes |
| global_manager | employees → 9 | yes |

## K-FA-18: How many Cloud Architecture assessments had a score of 5?

Reference:
```sql
SELECT count(*) AS assessments FROM skills.assessments a JOIN skills.skills s ON s.skill_id = a.skill_id WHERE s.name = 'Cloud Architecture' AND a.score = 5
```
Second annotator:
```sql
SELECT COUNT(*) AS cloud_architecture_score_5
FROM skills.assessments a
JOIN skills.skills s ON s.skill_id = a.skill_id
WHERE s.name = 'Cloud Architecture'
  AND a.score = 5
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | assessments → 10 | yes |
| apac_analyst | assessments → 11 | yes |
| global_manager | assessments → 30 | yes |

## K-FA-19: How many certifications are held by people in the Consulting APAC department, including people who have left?

Reference:
```sql
SELECT count(*) AS certifications FROM skills.certifications c JOIN skills.employees e ON e.employee_id = c.employee_id JOIN skills.departments d ON d.department_id = e.department_id WHERE d.name = 'Consulting APAC'
```
Second annotator:
```sql
SELECT COUNT(*) AS certification_count
FROM skills.certifications c
JOIN skills.employees e ON c.employee_id = e.employee_id
JOIN skills.departments d ON e.department_id = d.department_id
WHERE d.name = 'Consulting APAC'
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | certifications → 0 | yes |
| apac_analyst | certifications → 20 | yes |
| global_manager | certifications → 20 | yes |

## K-FA-20: What was the average Data Modelling score of analysts in the 2025-H2 cycle? Round to two decimal places.

Reference:
```sql
SELECT round(avg(a.score), 2) AS avg_score FROM skills.assessments a JOIN skills.skills s ON s.skill_id = a.skill_id JOIN skills.employees e ON e.employee_id = a.employee_id WHERE s.name = 'Data Modelling' AND e.job_title = 'Analyst' AND a.cycle_id = (SELECT cycle_id FROM skills.assessment_cycles WHERE name = '2025-H2')
```
Second annotator:
```sql
WITH analyst_ids AS (
    SELECT employee_id
    FROM skills.employees
    WHERE job_title = 'Analyst'
),
skill_id AS (
    SELECT skill_id
    FROM skills.skills
    WHERE name = 'Data Modelling'
),
cycle_id AS (
    SELECT cycle_id
    FROM skills.assessment_cycles
    WHERE name = '2025-H2'
)
SELECT round(avg(a.score)::numeric, 2) AS average_score
FROM skills.assessments a
JOIN analyst_ids e ON a.employee_id = e.employee_id
JOIN skill_id s ON a.skill_id = s.skill_id
JOIN cycle_id c ON a.cycle_id = c.cycle_id
```
| Persona | Reference answer | Agree |
| --- | --- | --- |
| emea_analyst | avg_score → 3.45 | yes |
| apac_analyst | avg_score → 3.31 | yes |
| global_manager | avg_score → 3.46 | yes |
