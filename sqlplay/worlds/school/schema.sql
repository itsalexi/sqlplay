CREATE TABLE department (
  deptid    varchar(4) PRIMARY KEY,
  deptname  varchar(30) NOT NULL,
  building  varchar(20),
  phone     varchar(12)
);

CREATE TABLE teacher (
  teacherid  integer PRIMARY KEY,
  lastname   varchar(20) NOT NULL,
  firstname  varchar(20) NOT NULL,
  homedept   varchar(4) REFERENCES department,
  hiredate   date,
  headid     integer REFERENCES teacher
);

CREATE TABLE course (
  courseid  varchar(6) PRIMARY KEY,
  title     varchar(40) NOT NULL,
  category  varchar(12),
  units     integer CHECK (units BETWEEN 1 AND 5),
  matcost   numeric(6,2),
  fee       numeric(6,2),
  deptid    varchar(4) REFERENCES department
);

CREATE TABLE courseteacher (
  courseid   varchar(6) REFERENCES course,
  teacherid  integer REFERENCES teacher,
  PRIMARY KEY (courseid, teacherid)
);

CREATE TABLE student (
  studentid   integer PRIMARY KEY,
  lastname    varchar(20) NOT NULL,
  firstname   varchar(20) NOT NULL,
  city        varchar(20),
  gradelevel  integer CHECK (gradelevel BETWEEN 9 AND 12),
  birthdate   date,
  mentorid    integer REFERENCES student
);

CREATE TABLE section (
  sectionid  integer PRIMARY KEY,
  courseid   varchar(6) REFERENCES course,
  term       varchar(11),
  room       varchar(5),
  capacity   integer,
  startdate  date
);

CREATE TABLE enrollment (
  studentid   integer REFERENCES student,
  sectionid   integer REFERENCES section,
  enrolldate  date,
  grade       numeric(6,2) CHECK (grade BETWEEN 0 AND 100),
  PRIMARY KEY (studentid, sectionid)
);
