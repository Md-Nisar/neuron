-- D3 mart, employee skill assessment domain (DG-00.01, owner decision D4). Run as a superuser.
-- Same pattern as `sales`: regional rows carry `region_id`; one manager-only table.

DROP SCHEMA IF EXISTS skills CASCADE;
CREATE SCHEMA skills;
COMMENT ON SCHEMA skills IS 'Employee skill assessments: employees, skills, assessment cycles, scores, targets and certifications, 2024 to 2025.';

CREATE TABLE skills.departments (
  department_id integer PRIMARY KEY,
  name          text NOT NULL,
  region_id     text NOT NULL REFERENCES sales.regions
);
COMMENT ON TABLE skills.departments IS 'Departments. Each sits in one sales region.';

CREATE TABLE skills.employees (
  employee_id   integer PRIMARY KEY,
  name          text NOT NULL,
  department_id integer NOT NULL REFERENCES skills.departments,
  region_id     text NOT NULL REFERENCES sales.regions,
  job_title     text NOT NULL CHECK (job_title IN ('Engineer', 'Analyst', 'Consultant', 'Team Lead', 'Manager')),
  level         integer NOT NULL CHECK (level BETWEEN 1 AND 5),
  manager_id    integer REFERENCES skills.employees,
  hired_on      date NOT NULL,
  left_on       date
);
COMMENT ON TABLE skills.employees IS 'Employees. left_on is set for people who have left; NULL means still employed.';
COMMENT ON COLUMN skills.employees.level IS 'Career level from 1 (junior) to 5 (principal).';
COMMENT ON COLUMN skills.employees.manager_id IS 'Line manager; NULL for department heads.';

CREATE TABLE skills.skills (
  skill_id integer PRIMARY KEY,
  name     text NOT NULL UNIQUE,
  category text NOT NULL CHECK (category IN ('Technical', 'Leadership', 'Communication', 'Domain'))
);
COMMENT ON TABLE skills.skills IS 'Skills that employees are assessed on.';

CREATE TABLE skills.assessment_cycles (
  cycle_id  integer PRIMARY KEY,
  name      text NOT NULL UNIQUE,
  starts_on date NOT NULL,
  ends_on   date NOT NULL
);
COMMENT ON TABLE skills.assessment_cycles IS 'Half-year assessment cycles, for example 2024-H1.';

CREATE TABLE skills.assessments (
  assessment_id integer PRIMARY KEY,
  employee_id   integer NOT NULL REFERENCES skills.employees,
  skill_id      integer NOT NULL REFERENCES skills.skills,
  cycle_id      integer NOT NULL REFERENCES skills.assessment_cycles,
  assessor_id   integer NOT NULL REFERENCES skills.employees,
  region_id     text NOT NULL REFERENCES sales.regions,
  score         integer NOT NULL CHECK (score BETWEEN 1 AND 5),
  assessed_on   date NOT NULL,
  UNIQUE (employee_id, skill_id, cycle_id)
);
COMMENT ON TABLE skills.assessments IS 'One score per employee, skill and cycle, given by an assessor (usually the line manager).';
COMMENT ON COLUMN skills.assessments.score IS '1 = novice, 2 = developing, 3 = proficient, 4 = advanced, 5 = expert.';

CREATE TABLE skills.role_targets (
  job_title    text NOT NULL,
  skill_id     integer NOT NULL REFERENCES skills.skills,
  target_score integer NOT NULL CHECK (target_score BETWEEN 1 AND 5),
  PRIMARY KEY (job_title, skill_id)
);
COMMENT ON TABLE skills.role_targets IS 'Expected score per job title and skill. A skill gap is target_score minus the latest score.';

CREATE TABLE skills.certifications (
  certification_id integer PRIMARY KEY,
  employee_id      integer NOT NULL REFERENCES skills.employees,
  region_id        text NOT NULL REFERENCES sales.regions,
  name             text NOT NULL,
  issued_on        date NOT NULL,
  expires_on       date
);
COMMENT ON TABLE skills.certifications IS 'Professional certifications. expires_on NULL means it does not expire.';

CREATE TABLE skills.assessor_notes (
  assessment_id integer PRIMARY KEY REFERENCES skills.assessments,
  region_id     text NOT NULL REFERENCES sales.regions,
  note          text NOT NULL
);
COMMENT ON TABLE skills.assessor_notes IS 'Confidential. Free-text assessor comments. Managers only.';
