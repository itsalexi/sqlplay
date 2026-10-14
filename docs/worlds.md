# Writing a world

A world is a small themed database plus a set of hand-written levels. Built-in worlds live in
`sqlplay/worlds/<slug>/` and are installed automatically the next time psqlay starts (it notices when the
files change).

```
sqlplay/worlds/pizza/
  world.yaml    name, emoji, blurb, join map, data notes
  schema.sql    CREATE TABLE statements only
  data.sql      INSERT ... VALUES statements only
  levels.yaml   the hand-written levels
```

## world.yaml

```yaml
name: Slice Society
emoji: "🍕"
blurb: A busy pizza chain with customers who refer their friends.
join_map: |
  customer -customerid- orders -orderid- orderline -pizzaid- pizza -supplierid- supplier
  pizza -pizzaid- pizzatopping -toppingid- topping
  customer.referredby -> customer.customerid
notes: |
  Names are stored in CAPITALS. Categories are mixed case ('Classic', 'Vegetarian', ...).
```

The join map uses `a -column- b` for each step and `table.col -> table.col` for a column that points
back to its own table. The web page draws it in the sidebar, and `\map` prints it in the terminal.

## schema.sql and data.sql

These files go through the same validator as AI-generated worlds:

- **schema.sql:** only `CREATE TABLE`, with `PRIMARY KEY`, `REFERENCES` and `CHECK` allowed. No
  schema-qualified names, no functions, no `SERIAL`/identity columns. At most 8 tables.
- **data.sql:** only `INSERT INTO t VALUES (...), (...);` with plain literals. Dates are written as
  `'2024-03-01'`. At most 500 rows in total.

To make questions as rich as the bookstore exam database, include:

- a chain of 4–5 tables (customer → orders → order lines → item → supplier)
- a link table for a many-to-many relationship (like `bookauthor`)
- a column that references its own table (like `referredby`)
- rows with no match (items never ordered, people with no activity) for `LEFT JOIN ... IS NULL`
- two money columns per item (cost and price) for profit questions
- the same person buying the same item twice, so `DISTINCT` matters
- names in CAPITALS and categories in mixed case
- column names chosen so `NATURAL JOIN` doesn't accidentally match extra columns (for example
  `pizzaname` instead of `name` everywhere)

## levels.yaml

```yaml
- id: hoa3                      # unique within the world
  topic: subqueries             # select | shape | aggregates | subqueries | joins | selfleft | groupby
  difficulty: 3                 # 1-5 (see the scale below)
  question: >
    Which pizzas are priced higher than the average price of all pizzas? Show the pizza ID,
    pizza name and price, labelled "Pizza ID", "Pizza" and "Price", highest price first.
  columns: ["Pizza ID", "Pizza", "Price"]   # exact labels, in order; leave out to skip label checks
  ordered: true                 # only if the question asks for an order
  order_note: "Price, highest first"
  answer: |
    SELECT pizzaid AS "Pizza ID", pizzaname AS "Pizza", price AS "Price"
    FROM pizza
    WHERE price > (SELECT AVG(price) FROM pizza)
    ORDER BY price DESC, pizzaid;
  hints:
    - Concept nudge, with no code.
    - Skeleton with ____ blanks.
    - Near-answer, with one small piece left out.
  explain: >
    Two to four sentences for a beginner on why the answer works.
```

Rules that keep grading fair:

- **The question must fully determine the result:** which columns, the exact labels, the full-name
  format, whether duplicates are allowed, and the sort order. Any correct query (JOIN style,
  WHERE-style equijoin, `NATURAL JOIN`, `NOT IN` instead of `LEFT JOIN`) has to return the same rows.
- **Ordered levels:** sort by output columns, and break every tie (add a second sort column).
- **Stay within the syllabus:** no subqueries in `FROM`, no `WITH`, no window functions, no `CASE`.
- **Averages:** use `ROUND(AVG(x), 2)` in the answer and say "rounded to 2 decimals" in the question.

### Difficulty scale

| Level | Meaning |
|---|---|
| 1–2 | Warm-up: a single skill |
| 3 | Typical exam question: two skills combined, labels, sorting |
| 4 | Hardest exam questions: three or more skills, a subquery that looks something up, a long join chain plus an aggregate subquery |
| 5 | Beyond the exam: nested subqueries, `LEFT JOIN` with extra filters, calculated columns, `GROUP BY`/`HAVING` with joins |

## Check your world

```bash
uv run python -m sqlplay.tools.check_world sqlplay/worlds/<slug> --show
```

This installs the world on a throwaway Postgres and checks every level: the answer runs, returns 1–60
rows, has the right labels, has no ties on its sort keys, and passes its own grading. `--show` prints
each answer's rows so you can check them against the question. Then run `uv run pytest`. The test suite
also confirms every built-in level stays within the syllabus.
