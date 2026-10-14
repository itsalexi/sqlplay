# PostgreSQL cheat sheet

Everything you're likely to need for an SQL hands-on activity, with examples on the classic
**bookstore** database (`booksdb`). Every example in this file has been run on that database.

**Contents:**
[0 · psql & setup](#0--psql--setup) ·
[1 · How a query runs](#1--how-a-query-runs) ·
[2 · SELECT basics](#2--select-basics) ·
[3 · WHERE](#3--where-filtering-rows) ·
[4 · Functions](#4--functions) ·
[5 · Aggregates](#5--aggregates) ·
[6 · GROUP BY / HAVING](#6--group-by--having) ·
[7 · Subqueries](#7--subqueries) ·
[8 · Joins](#8--joins) ·
[9 · Set operations](#9--set-operations) ·
[10 · CASE, COALESCE, CTEs, windows](#10--case-coalesce-ctes-window-functions) ·
[11 · Changing data](#11--changing-data-dml) ·
[12 · Tables & constraints](#12--tables--constraints-ddl) ·
[13 · Question → tool](#13--question-words--tool) ·
[14 · Errors decoded](#14--errors-decoded) ·
[15 · Oracle → PostgreSQL](#15--oracle--postgresql) ·
[16 · Bookstore exam patterns](#16--bookstore-exam-patterns)

---

## The bookstore database

```
customer(customerno, lastname, firstname, address, city, state, zip, referredby)
orders(orderno, customerno, orderdate, shipdate, shipstreet, shipcity, shipstate, shipzip)
orderitem(orderno, itemno, isbn, quantity)
book(isbn, title, pubdate, pubid, cost, retail, category)
publisher(pubid, name, contact, phone)
bookauthor(isbn, authorid)
author(authorid, lname, fname)
```

**Join map:**
```
customer -customerno- orders -orderno- orderitem -isbn- book -pubid- publisher
book -isbn- bookauthor -authorid- author
customer.referredby -> customer.customerno          (self-reference)
```

Names and titles are stored in **CAPITALS** (`'BONITA'`, `'HOLY GRAIL OF ORACLE'`). Categories are
mixed case (`'Computer'`, `'Family Life'`).

---

## 0 · psql & setup

| Command | Does |
|---|---|
| `psql -U postgres` | Connect (Windows: open **SQL Shell (psql)** and press Enter for each default) |
| `psql -U postgres -d booksdb` | Connect straight to a database |
| `CREATE DATABASE booksdb;` | Make a database |
| `\c booksdb` | Switch to it. **The prompt must then say `booksdb=#`** |
| `\i path/to/file.sql` | Run a SQL file (Windows: `\i C:/Users/me/file.sql`, with forward slashes) |
| `\l` | List databases |
| `\dt` | List tables |
| `\d book` | Show a table's columns and keys |
| `\dn` · `\df` · `\dv` | Schemas · functions · views |
| `\x` | Toggle expanded (vertical) output |
| `\pset pager off` | Stop the `(END)` pager. If you're stuck in the pager, press `q` |
| `\timing` | Show how long queries take |
| `\e` | Open the last query in an editor |
| `\s` | Show your query history |
| `\?` · `\h SELECT` | psql help · SQL syntax help |
| `\q` | Quit |

**Importing a setup file:** run `CREATE DATABASE booksdb;`, then `\c booksdb`, then `\i file.sql`.
Errors at the top like "does not exist", "cannot drop the currently open database" or "already exists"
are **normal**.

| Prompt | Meaning |
|---|---|
| `booksdb=#` | Ready |
| `booksdb-#` | The query isn't finished: type `;` |
| `booksdb(#` | A `(` is still open: close it, or press Ctrl-C |
| `booksdb'#` / `booksdb"#` | A quote is still open: close it, or press Ctrl-C |

---

## 1 · How a query runs

You **write** a query in this order:

```
SELECT … FROM … JOIN … ON … WHERE … GROUP BY … HAVING … ORDER BY … LIMIT …;
```

Postgres **runs** it in this order:

```
FROM/JOIN → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY → LIMIT
```

What follows from that:
- WHERE can't use a label you made with `AS` (SELECT hasn't run yet), but ORDER BY can.
- WHERE can't use aggregates; use HAVING.
- **WHERE filters rows. SELECT chooses columns. GROUP BY makes piles. HAVING filters piles.**

**Quotes:**
- `'single'` = a **value** (`'FL'`, `'2003-04-01'`).
- `"double"` = a **name or label** (`AS "Customer Name"`).
- Never use curly quotes (`‘ ’ “ ”`).

---

## 2 · SELECT basics

```sql
SELECT * FROM book;                                   -- every column
SELECT title, retail FROM book;                       -- chosen columns
SELECT title AS "Book Title", retail AS "Price" FROM book;   -- labels (double quotes if spaces/caps)
SELECT title, retail - cost AS profit FROM book;      -- calculated column
SELECT title, ROUND(((retail - cost) / cost * 100)::numeric, 1) AS "Markup %" FROM book;  -- real/float needs ::numeric
SELECT DISTINCT category FROM book;                   -- remove duplicate rows
SELECT DISTINCT state, city FROM customer;            -- distinct on the combination
SELECT title FROM book ORDER BY retail DESC;          -- sort, biggest first (ASC is the default)
SELECT title, category, retail FROM book ORDER BY category, retail DESC;   -- tie-breaker
SELECT title, retail FROM book ORDER BY 2 DESC;       -- sort by column position
SELECT title AS "Book" FROM book ORDER BY "Book";     -- sort by a label
SELECT firstname, referredby FROM customer ORDER BY referredby NULLS FIRST;
SELECT title, retail FROM book ORDER BY retail DESC LIMIT 3;          -- top 3
SELECT title, retail FROM book ORDER BY retail DESC LIMIT 3 OFFSET 3; -- the next 3
SELECT title, retail FROM book ORDER BY retail DESC FETCH FIRST 3 ROWS ONLY;  -- standard SQL form
```

**Gluing text together:**
```sql
SELECT CONCAT(firstname, ' ', lastname) AS "Customer Name" FROM customer;
SELECT firstname || ' ' || lastname AS "Customer Name" FROM customer;  -- || gives NULL if any part is NULL
SELECT CONCAT(city, ', ', state) AS "Location" FROM customer;           -- "EASTPOINT, FL"
SELECT CONCAT_WS(' ', firstname, lastname) FROM customer;               -- "with separator"
```

---

## 3 · WHERE (filtering rows)

```sql
SELECT * FROM customer WHERE state = 'FL';
SELECT * FROM book WHERE retail > 50;                       -- = <> != < > <= >=
SELECT * FROM book WHERE category = 'Computer' AND retail > 50;
SELECT * FROM book WHERE category = 'Computer' OR category = 'Cooking';
SELECT * FROM book WHERE NOT category = 'Computer';
SELECT * FROM book WHERE (category = 'Computer' OR category = 'Cooking') AND retail < 30;  -- brackets!
SELECT * FROM book WHERE category IN ('Computer', 'Cooking', 'Fitness');
SELECT * FROM book WHERE category NOT IN ('Computer', 'Cooking');
SELECT * FROM book WHERE retail BETWEEN 20 AND 30;          -- includes 20 and 30
SELECT * FROM orders WHERE orderdate BETWEEN '2003-03-31' AND '2003-04-02';
SELECT * FROM orders WHERE shipdate IS NULL;                -- NEVER  = NULL
SELECT * FROM customer WHERE referredby IS NOT NULL;
```

**Pattern matching:** `%` matches any number of characters and `_` matches exactly one.
```sql
SELECT title FROM book WHERE title LIKE 'THE%';          -- starts with
SELECT title FROM book WHERE title LIKE '%COOK%';        -- contains
SELECT title FROM book WHERE title LIKE '%S';            -- ends with
SELECT lastname FROM customer WHERE lastname LIKE '_A%'; -- 2nd letter A
SELECT title FROM book WHERE title ILIKE '%oracle%';     -- case-insensitive (PostgreSQL only)
SELECT title FROM book WHERE title NOT LIKE '%A%';
SELECT title FROM book WHERE UPPER(title) LIKE '%ORACLE%';  -- portable case-insensitive
SELECT title FROM book WHERE title ~ '^[A-D]';           -- regex: starts with A-D
```

**Dates:**
```sql
SELECT * FROM orders WHERE orderdate = '2003-04-01';
SELECT * FROM orders WHERE orderdate >= '2003-04-01' AND orderdate < '2003-04-03';
SELECT * FROM book WHERE EXTRACT(YEAR FROM pubdate) = 2001;
SELECT orderno FROM orders WHERE shipdate - orderdate > 2;      -- date - date = number of days
SELECT * FROM orders WHERE orderdate > DATE '2003-04-01';
```

**NULL rules:**
- Anything compared to NULL gives NULL, which WHERE treats as "not true", so the row is dropped.
- Use `IS NULL` and `IS NOT NULL`.
- `NOT IN (…)` returns **nothing** if the list contains a NULL. See [section 7](#7--subqueries).

---

## 4 · Functions

**Text:**

| Function | Example | Result |
|---|---|---|
| `UPPER` / `LOWER` | `LOWER('ABC')` | `abc` |
| `INITCAP` | `INITCAP('BONITA MORALES')` | `Bonita Morales` |
| `LENGTH` | `LENGTH('ORACLE')` | `6` |
| `SUBSTRING(s FROM start FOR n)` / `SUBSTR(s, start, n)` | `SUBSTR('BOOKS', 1, 3)` | `BOO` |
| `LEFT` / `RIGHT` | `LEFT(zip, 3)` | first 3 characters |
| `POSITION(sub IN s)` / `STRPOS(s, sub)` | `POSITION('O' IN 'BOOK')` | `2` |
| `TRIM` / `LTRIM` / `RTRIM` | `TRIM('  x  ')` | `x` |
| `REPLACE` | `REPLACE(phone, '-', '')` | `0007148321` |
| `LPAD` / `RPAD` | `LPAD('7', 3, '0')` | `007` |
| `CONCAT`, `\|\|` | | glue text (see section 2) |
| `SPLIT_PART` | `SPLIT_PART('800-555-1211', '-', 1)` | `800` |

**Numbers:**

| Function | Example | Result |
|---|---|---|
| `ROUND(x, n)` | `ROUND(54.567, 2)` | `54.57` |
| `TRUNC(x, n)` | `TRUNC(54.567, 1)` | `54.5` |
| `CEIL` / `FLOOR` | `CEIL(4.1)` | `5` |
| `ABS`, `MOD(a, b)`, `POWER`, `SQRT` | `MOD(10, 3)` | `1` |
| `/` with integers | `7 / 2` | `3` (integer division!). Use `7 / 2.0` or `7::numeric / 2` |

> If a column is `real`/`float` (as in booksdb), `ROUND(x, 2)` needs a cast: `ROUND(AVG(retail)::numeric, 2)`.
> The `numeric` type works without one.

**Dates:**

| Function | Example |
|---|---|
| Today / now | `CURRENT_DATE`, `NOW()`, `CURRENT_TIMESTAMP` |
| Part of a date | `EXTRACT(YEAR FROM pubdate)`, `DATE_PART('month', orderdate)` |
| Cut to month/year | `DATE_TRUNC('month', orderdate)` |
| Add / subtract | `orderdate + 7`, `orderdate + INTERVAL '1 month'` |
| Difference | `shipdate - orderdate` (days), `AGE(shipdate, orderdate)` |
| Format | `TO_CHAR(orderdate, 'Mon DD, YYYY')` → `Mar 31, 2003` |
| Parse | `TO_DATE('31/03/2003', 'DD/MM/YYYY')` |

**Converting types:** `CAST(retail AS integer)`, `retail::numeric`, `'2003-04-01'::date`, `isbn::bigint`,
`TO_CHAR(retail, 'FM$999.00')`.

**NULL helpers:** `COALESCE(shipdate::text, 'not shipped')` gives the first non-NULL value.
`NULLIF(a, b)` gives NULL when `a = b`, which is handy to avoid dividing by 0.

---

## 5 · Aggregates

These squash many rows into **one** value.

```sql
SELECT COUNT(*) FROM book;                         -- counts rows
SELECT COUNT(referredby) FROM customer;            -- counts NON-NULL values only
SELECT COUNT(DISTINCT category) FROM book;         -- counts unique values
SELECT SUM(quantity) FROM orderitem;
SELECT AVG(retail), MIN(retail), MAX(retail) FROM book;
SELECT ROUND(AVG(retail)::numeric, 2) AS "Average Price" FROM book;
SELECT MAX(retail) FROM book WHERE category = 'Computer';   -- WHERE picks which rows get squashed
SELECT MIN(pubdate), MAX(pubdate) FROM book;                -- works on dates and text too
SELECT AVG(retail - cost) AS "Avg Profit" FROM book;        -- aggregate of an expression
SELECT STRING_AGG(title, ', ' ORDER BY title) FROM book WHERE category = 'Computer';
```

Rules:
- Aggregates **ignore NULLs**, except `COUNT(*)`.
- You **can't mix** an aggregate with plain columns unless you GROUP BY them. To find *which row*
  has the max, use a subquery:
  ```sql
  SELECT title, retail FROM book WHERE retail = (SELECT MAX(retail) FROM book);
  ```

---

## 6 · GROUP BY / HAVING

These make one pile per value, then squash each pile separately.

```sql
SELECT category, COUNT(*) AS "Books" FROM book GROUP BY category;
SELECT category, ROUND(AVG(retail)::numeric, 2) AS "Avg Price"
FROM book GROUP BY category ORDER BY 2 DESC;
SELECT category, COUNT(*) FROM book GROUP BY category HAVING COUNT(*) >= 2;   -- filter piles
SELECT category, MAX(retail) FROM book WHERE pubdate > '2001-01-01' GROUP BY category;  -- WHERE first
SELECT state, city, COUNT(*) FROM customer GROUP BY state, city;              -- several columns
SELECT p.name, COUNT(*) AS "Titles"
FROM publisher p JOIN book b ON p.pubid = b.pubid
GROUP BY p.pubid, p.name ORDER BY "Titles" DESC;                              -- with a join
SELECT c.firstname, c.lastname, SUM(oi.quantity * b.retail) AS "Spent"
FROM customer c
JOIN orders o ON c.customerno = o.customerno
JOIN orderitem oi ON o.orderno = oi.orderno
JOIN book b ON oi.isbn = b.isbn
GROUP BY c.customerno, c.firstname, c.lastname
HAVING SUM(oi.quantity * b.retail) > 100;
```

Rules:
- Every **non-aggregate column in SELECT must be in GROUP BY**.
- **WHERE** filters rows *before* grouping. **HAVING** filters groups *after*, and can use aggregates.

---

## 7 · Subqueries

A query inside a query. The inner one runs first.

```sql
-- returns one value: compare with = > < etc.
SELECT title, retail FROM book WHERE retail > (SELECT AVG(retail) FROM book);
SELECT title FROM book WHERE retail = (SELECT MAX(retail) FROM book WHERE category = 'Computer')
  AND category = 'Computer';          -- filter in BOTH places when the max is per-category

-- look something up, instead of hard-coding it
SELECT title FROM book
WHERE pubid = (SELECT pubid FROM book WHERE title = 'BIG BEAR AND LITTLE DOVE');

-- returns a list: use IN / NOT IN
SELECT title FROM book WHERE isbn IN (SELECT isbn FROM orderitem);
SELECT title FROM book WHERE isbn NOT IN (SELECT isbn FROM orderitem WHERE isbn IS NOT NULL);

-- subquery containing a join
SELECT orderno FROM orders
WHERE shipstate IN (SELECT o.shipstate FROM orders o
                    JOIN customer c ON o.customerno = c.customerno
                    WHERE c.lastname = 'SCHELL');

-- nested subqueries
SELECT firstname, lastname FROM customer
WHERE customerno IN (SELECT customerno FROM orders
                     WHERE orderno IN (SELECT orderno FROM orderitem
                                       WHERE isbn = (SELECT isbn FROM book WHERE retail = (SELECT MIN(retail) FROM book))));

-- EXISTS / NOT EXISTS (correlated: the inner query uses the outer row)
SELECT b.title FROM book b
WHERE NOT EXISTS (SELECT 1 FROM orderitem oi WHERE oi.isbn = b.isbn);     -- never ordered

-- correlated: compare each book with the average of ITS OWN category
SELECT b.title, b.category, b.retail FROM book b
WHERE b.retail > (SELECT AVG(b2.retail) FROM book b2 WHERE b2.category = b.category);

-- ANY / ALL
SELECT title FROM book WHERE retail > ALL (SELECT retail FROM book WHERE category = 'Cooking');
SELECT title FROM book WHERE retail = ANY (SELECT retail FROM book WHERE category = 'Children');

-- subquery in FROM (a "derived table": it needs an alias)
SELECT category, avg_price FROM (
  SELECT category, AVG(retail) AS avg_price FROM book GROUP BY category
) t WHERE avg_price > 30;

-- subquery in SELECT (one value per row)
SELECT title, retail, retail - (SELECT AVG(retail) FROM book) AS "vs avg" FROM book;
```

| Error | Fix |
|---|---|
| "more than one row returned by a subquery used as an expression" | Use `IN` instead of `=` |
| `NOT IN` returns nothing | The subquery returned a NULL. Add `WHERE col IS NOT NULL` or use `NOT EXISTS` |

---

## 8 · Joins

These glue rows from two tables wherever the shared column matches.

```sql
-- INNER JOIN: only rows that match on both sides
SELECT b.title, p.name
FROM book b JOIN publisher p ON b.pubid = p.pubid;

-- chain: one JOIN per step along the join map
SELECT DISTINCT b.title
FROM customer c
JOIN orders o     ON c.customerno = o.customerno
JOIN orderitem oi ON o.orderno = oi.orderno
JOIN book b       ON oi.isbn = b.isbn
WHERE c.firstname = 'BONITA' AND c.lastname = 'MORALES';

-- link table (many-to-many)
SELECT a.fname, a.lname, b.title
FROM author a
JOIN bookauthor ba ON a.authorid = ba.authorid
JOIN book b        ON ba.isbn = b.isbn;
```

**Same join, other styles.** They all return the same rows:
```sql
SELECT b.title, p.name FROM book b, publisher p WHERE b.pubid = p.pubid;   -- equijoin, WHERE style
SELECT title, name FROM book NATURAL JOIN publisher;                       -- matches ALL same-named columns
SELECT title, name FROM book JOIN publisher USING (pubid);                 -- you name the shared column
```
- WHERE style: list the tables with commas, and put every link in WHERE. **N tables need N−1 links.**
  Forget one and you get every row paired with every row.
- NATURAL JOIN and USING: don't put a table prefix on the shared column (write `pubid`, not `b.pubid`).

**Outer joins** keep rows that have no match, filling the missing side with NULL:
```sql
SELECT b.title, oi.orderno FROM book b LEFT JOIN orderitem oi ON b.isbn = oi.isbn;   -- all books
SELECT b.title FROM book b LEFT JOIN orderitem oi ON b.isbn = oi.isbn
WHERE oi.isbn IS NULL;                                       -- books NEVER ordered
SELECT c.lastname, o.orderno FROM orders o RIGHT JOIN customer c ON o.customerno = c.customerno;
SELECT c.lastname, o.orderno FROM customer c FULL JOIN orders o ON c.customerno = o.customerno;
```
- **Trap:** a filter on the right-hand table belongs in `ON`, not `WHERE`, or the LEFT JOIN quietly
  becomes an inner join:
  ```sql
  SELECT b.title, COUNT(oi.isbn) FROM book b
  LEFT JOIN orderitem oi ON b.isbn = oi.isbn AND oi.quantity > 1
  GROUP BY b.isbn, b.title;
  ```
- Use `COUNT(column)`, not `COUNT(*)`, after a LEFT JOIN, so unmatched rows count as 0.

**Self-join:** one table used as two copies.
```sql
-- who referred whom
SELECT CONCAT(c.firstname, ' ', c.lastname) AS "Customer",
       CONCAT(r.firstname, ' ', r.lastname) AS "Referred By"
FROM customer c JOIN customer r ON c.referredby = r.customerno;

-- customers who referred someone (each once)
SELECT DISTINCT r.customerno, r.firstname, r.lastname
FROM customer c JOIN customer r ON c.referredby = r.customerno;

-- pairs of books in the same category (a < b avoids duplicates and self-pairs)
SELECT a.title, b.title FROM book a JOIN book b ON a.category = b.category AND a.isbn < b.isbn;
```

**Other joins:**
```sql
SELECT b.title, p.name FROM book b CROSS JOIN publisher p;       -- every combination
SELECT o.orderno, b.title FROM orders o
JOIN orderitem oi ON o.orderno = oi.orderno
JOIN book b ON oi.isbn = b.isbn AND b.retail > 50;               -- non-equi / extra condition
```

| Symptom | Likely cause |
|---|---|
| Too many rows or duplicates | Use `DISTINCT`, or a join condition is missing or wrong |
| Rows missing | An inner join dropped unmatched rows: use `LEFT JOIN` |
| "column reference is ambiguous" | Put the table prefix on it: `c.customerno` |
| "missing FROM-clause entry for table x" | You used `x.` but never gave a table that alias |

---

## 9 · Set operations

These stack results vertically. Both queries need the same number of columns, with compatible types.

```sql
SELECT state FROM customer UNION SELECT shipstate FROM orders;       -- removes duplicates
SELECT state FROM customer UNION ALL SELECT shipstate FROM orders;   -- keeps duplicates
SELECT isbn FROM book INTERSECT SELECT isbn FROM orderitem;          -- in both
SELECT isbn FROM book EXCEPT SELECT isbn FROM orderitem;             -- in the first only (Oracle: MINUS)
SELECT state FROM customer UNION SELECT shipstate FROM orders ORDER BY 1;   -- ORDER BY goes at the very end
```

---

## 10 · CASE, COALESCE, CTEs, window functions

```sql
-- CASE: if / else inside a query
SELECT title, retail,
       CASE WHEN retail >= 50 THEN 'Expensive'
            WHEN retail >= 25 THEN 'Mid'
            ELSE 'Cheap' END AS "Price Band"
FROM book;

-- conditional counting
SELECT COUNT(*) FILTER (WHERE retail > 30) AS "Over 30",
       SUM(CASE WHEN category = 'Computer' THEN 1 ELSE 0 END) AS "Computer books"
FROM book;

-- COALESCE: a fallback for NULL
SELECT orderno, COALESCE(shipdate::text, 'NOT SHIPPED') AS "Shipped" FROM orders;

-- CTE (WITH): a named temporary result
WITH profits AS (
  SELECT title, retail - cost AS profit FROM book
)
SELECT * FROM profits WHERE profit > (SELECT AVG(profit) FROM profits);

-- window functions: a calculation per row WITHOUT squashing the rows
SELECT title, category, retail,
       RANK() OVER (ORDER BY retail DESC) AS "Rank",
       RANK() OVER (PARTITION BY category ORDER BY retail DESC) AS "Rank in Category",
       ROUND(AVG(retail) OVER (PARTITION BY category)::numeric, 2) AS "Category Avg"
FROM book;
-- also: ROW_NUMBER(), DENSE_RANK(), LAG(col), LEAD(col), SUM(col) OVER (ORDER BY …) running total
```

---

## 11 · Changing data (DML)

```sql
INSERT INTO publisher VALUES (6, 'NEW PRESS', 'ANA REYES', '800-555-0000');
INSERT INTO publisher (pubid, name) VALUES (7, 'TINY PRESS');                 -- other columns become NULL
INSERT INTO publisher (pubid, name) VALUES (8, 'A'), (9, 'B');                -- several rows
UPDATE book SET retail = retail * 1.10 WHERE category = 'Computer';           -- ALWAYS use WHERE
UPDATE customer SET city = 'MIAMI', zip = '33101' WHERE customerno = 1001;
DELETE FROM publisher WHERE pubid = 9;                                        -- no WHERE = delete ALL
INSERT INTO publisher (pubid, name) VALUES (10, 'X') RETURNING *;             -- show what changed

BEGIN;                    -- try changes safely
UPDATE book SET retail = 0;
ROLLBACK;                 -- undo   (COMMIT; to keep)
```

---

## 12 · Tables & constraints (DDL)

```sql
CREATE TABLE review (
  reviewid   SERIAL PRIMARY KEY,                                -- auto-number (or: INT GENERATED ALWAYS AS IDENTITY)
  isbn       VARCHAR(10) NOT NULL REFERENCES book(isbn),        -- foreign key
  stars      INT CHECK (stars BETWEEN 1 AND 5),
  reviewer   VARCHAR(50) DEFAULT 'ANONYMOUS',
  reviewed   DATE DEFAULT CURRENT_DATE,
  UNIQUE (isbn, reviewer)
);
ALTER TABLE review ADD COLUMN comment TEXT;
ALTER TABLE review DROP COLUMN comment;
ALTER TABLE review RENAME COLUMN reviewer TO author_name;
ALTER TABLE review ALTER COLUMN stars SET NOT NULL;
ALTER TABLE review ADD CONSTRAINT stars_ok CHECK (stars > 0);
CREATE VIEW cheap_books AS SELECT title, retail FROM book WHERE retail < 25;
SELECT * FROM cheap_books;
CREATE INDEX ON book (category);
DROP VIEW cheap_books;
DROP TABLE review;                 -- add IF EXISTS to avoid errors, CASCADE to also drop dependents
TRUNCATE orderitem;                -- empty a table (fast, no WHERE)
```

| Type | Use for |
|---|---|
| `INT`, `BIGINT`, `SMALLINT` | Whole numbers |
| `NUMERIC(8,2)` / `DECIMAL` | Money (exact) |
| `REAL`, `DOUBLE PRECISION` | Approximate decimals |
| `VARCHAR(n)`, `CHAR(n)`, `TEXT` | Text |
| `DATE`, `TIMESTAMP`, `INTERVAL` | Time |
| `BOOLEAN` | True/false |

---

## 13 · Question words → tool

| The question says… | Use |
|---|---|
| "show / list / which … where …" | `SELECT … FROM … WHERE …` |
| "labelled", "titled", "as" | `AS "Label"` |
| "full name", "combined" | `CONCAT(first, ' ', last)` |
| "each once", "unique", "without duplicates" | `DISTINCT` |
| "sorted", "highest first", "alphabetically" | `ORDER BY … DESC/ASC` |
| "top 3", "first 5" | `ORDER BY … LIMIT 3` |
| "how many", "total", "average", "highest", "lowest" | `COUNT` / `SUM` / `AVG` / `MAX` / `MIN` |
| "for each …", "per …", "by category" | `GROUP BY` |
| "… with more than N …" (about groups) | `HAVING` |
| "the most expensive / cheapest X" | `WHERE col = (SELECT MAX/MIN(col) …)` |
| "more than the average" | `WHERE col > (SELECT AVG(col) …)` |
| "more than the most expensive X in category Y" | `> (SELECT MAX(col) … WHERE category = 'Y')` |
| "same X as Y" | `= (SELECT X … WHERE name = 'Y')`, or `IN (…)` if Y has several |
| "who bought / wrote / published …" | JOIN chain along the join map |
| "who referred / manages / mentors" | Self-join |
| "never", "not … at all", "has no" | `LEFT JOIN … IS NULL`, or `NOT IN` / `NOT EXISTS` |
| "profit", "markup", "difference" | Arithmetic: `retail - cost` |
| "starts with / contains" | `LIKE 'A%'`, `LIKE '%word%'` (`ILIKE` ignores case) |
| "between … and …" | `BETWEEN` (includes both ends) |
| "if … then …" | `CASE WHEN … THEN … ELSE … END` |
| "in either list" / "in both" / "in one but not the other" | `UNION` / `INTERSECT` / `EXCEPT` |

**Building a query step by step:**
1. `SELECT * FROM table;` to look at the data.
2. Add WHERE and check the **rows**.
3. Replace `*` with the columns you need and check the **columns**.
4. Add `AS` labels, then ORDER BY.
5. For a subquery, run the inner query on its own first, hard-code its result, then swap the
   subquery in.

---

## 14 · Errors decoded

| Error | What it means and how to fix it |
|---|---|
| `syntax error at or near "FROM"` | Usually a comma before FROM, or a missing comma between columns |
| `syntax error at or near "SELECT"` | A subquery needs brackets: `(SELECT …)`. One main SELECT per query |
| `syntax error at or near "order"` | `order` is a reserved word; the table is probably `orders` |
| `syntax error at or near "WHERE"` | Clauses are out of order. Use SELECT, FROM, JOIN, WHERE, GROUP BY, HAVING, ORDER BY |
| `column "x" does not exist` | Typo; check with `\d table`. Or you used `"FL"` (a name) where you meant `'FL'` (a value) |
| `relation "x" does not exist` | Wrong table name (check `\dt`), or you're connected to the wrong database (`\c booksdb`) |
| `column "x" must appear in the GROUP BY clause…` | You mixed an aggregate with plain columns. Add GROUP BY, or use a subquery |
| `aggregate functions are not allowed in WHERE` | Use HAVING, or a subquery `(SELECT MAX(…) …)` |
| `column reference "x" is ambiguous` | Two joined tables have this column: add a prefix, `c.customerno` |
| `missing FROM-clause entry for table "x"` | You used `x.` but no table has the alias `x` |
| `more than one row returned by a subquery…` | Use `IN` instead of `=` |
| `operator does not exist: integer = text` | Comparing a number to text. Remove the quotes from numbers, or cast with `::` |
| `invalid input syntax for type …` | A badly formatted value, e.g. a date that isn't `'YYYY-MM-DD'` |
| `unterminated quoted string` | A `'` that was never closed |
| `division by zero` | Use `NULLIF(denominator, 0)` |
| `function round(double precision, integer) does not exist` | Write `ROUND(x::numeric, 2)` |
| `duplicate key value violates unique constraint` | That primary key already exists |
| `violates foreign key constraint` | The parent row doesn't exist, or children still point to it |
| `current transaction is aborted…` | A previous error happened inside BEGIN. Type `ROLLBACK;` |

---

## 15 · Oracle → PostgreSQL

Some textbooks use Oracle syntax. Here are the PostgreSQL equivalents:

| Oracle | PostgreSQL |
|---|---|
| `NVL(a, b)` | `COALESCE(a, b)` |
| `NVL2(a, b, c)` | `CASE WHEN a IS NOT NULL THEN b ELSE c END` |
| `SYSDATE` | `CURRENT_DATE` / `NOW()` |
| `FROM DUAL` | Leave out FROM: `SELECT 1 + 1;` |
| `a.x = b.x(+)` | `LEFT JOIN … ON` |
| `MINUS` | `EXCEPT` |
| `ROWNUM <= 3` | `LIMIT 3` |
| `DECODE(x, 1, 'a', 'b')` | `CASE x WHEN 1 THEN 'a' ELSE 'b' END` |
| `TO_CHAR(date, 'DD-MON-YY')` | Same function; format codes are mostly the same |
| `VARCHAR2`, `NUMBER(p,s)` | `VARCHAR`, `NUMERIC(p,s)` |
| `MONTHS_BETWEEN(a, b)` | `EXTRACT(YEAR FROM AGE(a, b)) * 12 + EXTRACT(MONTH FROM AGE(a, b))` |
| `INSTR`, `SUBSTR` | `STRPOS`, `SUBSTR` / `SUBSTRING` |
| `NATURAL JOIN` with a qualified column (`b.isbn`) is an error | PostgreSQL allows it |

---

## 16 · Bookstore exam patterns

```sql
-- most expensive book in a category, with its publisher
SELECT b.title AS "Title", b.retail AS "Price", p.name AS "Publisher Name"
FROM book b JOIN publisher p ON b.pubid = p.pubid
WHERE b.category = 'Computer'
  AND b.retail = (SELECT MAX(retail) FROM book WHERE category = 'Computer');

-- customers who referred someone
SELECT DISTINCT r.customerno AS "Customer Number",
       CONCAT(r.firstname, ' ', r.lastname) AS "Customer Name"
FROM customer c JOIN customer r ON c.referredby = r.customerno
ORDER BY 1;

-- above-average price, with publisher, highest first
SELECT b.isbn AS "ISBN", b.title AS "Book Title", p.name AS "Publisher", b.retail AS "Retail Price"
FROM book b JOIN publisher p ON b.pubid = p.pubid
WHERE b.retail > (SELECT AVG(retail) FROM book)
ORDER BY b.retail DESC;

-- what a named customer bought (4-table chain)
SELECT DISTINCT b.isbn, b.title, b.retail
FROM customer c
JOIN orders o ON c.customerno = o.customerno
JOIN orderitem oi ON o.orderno = oi.orderno
JOIN book b ON oi.isbn = b.isbn
WHERE c.firstname = 'BONITA' AND c.lastname = 'MORALES';

-- publisher of a named author's books
SELECT b.title, b.category, p.name, p.contact, p.phone
FROM author a
JOIN bookauthor ba ON a.authorid = ba.authorid
JOIN book b ON ba.isbn = b.isbn
JOIN publisher p ON b.pubid = p.pubid
WHERE a.fname = 'TAMARA' AND a.lname = 'KZOCHSKY';

-- same publisher as a named book, profit above average
SELECT isbn, title, category FROM book
WHERE pubid = (SELECT pubid FROM book WHERE title = 'BIG BEAR AND LITTLE DOVE')
  AND (retail - cost) > (SELECT AVG(retail - cost) FROM book);

-- books never ordered
SELECT b.isbn, b.title FROM book b
LEFT JOIN orderitem oi ON b.isbn = oi.isbn
WHERE oi.isbn IS NULL;

-- orders shipped to the same state(s) as a named customer's orders
SELECT o.orderno, o.shipdate, CONCAT(c.firstname, ' ', c.lastname) AS "Customer"
FROM orders o JOIN customer c ON o.customerno = c.customerno
WHERE o.shipstate IN (SELECT o2.shipstate FROM orders o2
                      JOIN customer c2 ON o2.customerno = c2.customerno
                      WHERE c2.firstname = 'STEVE' AND c2.lastname = 'SCHELL');

-- customers who ordered the cheapest book
SELECT DISTINCT CONCAT(c.firstname, ' ', c.lastname) AS "Customer's Name", c.state
FROM customer c
JOIN orders o ON c.customerno = o.customerno
JOIN orderitem oi ON o.orderno = oi.orderno
JOIN book b ON oi.isbn = b.isbn
WHERE b.retail = (SELECT MIN(retail) FROM book);
```

**Before you submit, check:** the right columns, in the right order, with the exact labels (double
quotes); duplicates handled (`DISTINCT`); the sort order asked for; straight quotes; names in CAPITALS.
