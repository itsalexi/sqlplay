CREATE TABLE studio (
  studioid   integer PRIMARY KEY,
  name       varchar(40) NOT NULL,
  contact    varchar(40),
  phone      varchar(15)
);

CREATE TABLE movie (
  movieid     integer PRIMARY KEY,
  title       varchar(40) NOT NULL,
  releasedate date,
  studioid    integer REFERENCES studio (studioid),
  genre       varchar(15),
  runtime     integer CHECK (runtime > 0),
  rating      numeric(3,1),
  budget      numeric(8,2),
  cost        numeric(6,2),
  price       numeric(6,2),
  sequelof    integer REFERENCES movie (movieid)
);

CREATE TABLE member (
  memberid   integer PRIMARY KEY,
  lastname   varchar(20) NOT NULL,
  firstname  varchar(20) NOT NULL,
  address    varchar(40),
  city       varchar(20),
  joindate   date,
  invitedby  integer REFERENCES member (memberid)
);

CREATE TABLE rental (
  rentalid    integer PRIMARY KEY,
  memberid    integer NOT NULL REFERENCES member (memberid),
  rentaldate  date NOT NULL,
  returndate  date,
  branch      varchar(15)
);

CREATE TABLE rentalitem (
  rentalid  integer REFERENCES rental (rentalid),
  itemno    integer,
  movieid   integer NOT NULL REFERENCES movie (movieid),
  days      integer CHECK (days > 0),
  PRIMARY KEY (rentalid, itemno)
);

CREATE TABLE actor (
  actorid    integer PRIMARY KEY,
  lname      varchar(20) NOT NULL,
  fname      varchar(20) NOT NULL,
  birthyear  integer
);

CREATE TABLE movieactor (
  movieid  integer REFERENCES movie (movieid),
  actorid  integer REFERENCES actor (actorid),
  PRIMARY KEY (movieid, actorid)
);
