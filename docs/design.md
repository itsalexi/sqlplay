# sqlplay design

Local SQL practice playground for PostgreSQL. Endless HOA-style challenges,
graded by comparing results, playable in a browser or a terminal.

Status: approved 2026-10-15 (sections 1-3 reviewed in chat).

## Goals

- Practice for a hands-on SQL activity (HOA): questions modelled on the HOA,
  at HOA difficulty or harder.
- Fully playable with **no API key**. An OpenAI key is an optional extra that
  unlocks AI-generated worlds and levels.
- Two front ends on one engine: a local web page and a psql-like terminal app.
- Runs only on the player's own machine.

Non-goals: public hosting, accounts, multiplayer.

## Architecture

```
            +-------------------+       +--------------------+
  browser ->| web (FastAPI,     |       | cli (psql-like     |
            | 127.0.0.1 only)   |       | REPL)              |
            +---------+---------+       +---------+----------+
                      \                         /
                       v                       v
                  +-------------------------------+
                  | engine                        |
                  |  worlds  levels  generator    |
                  |  grader  feedback  adaptive   |
                  |  exam    progress  ai (opt.)  |
                  |  sandbox (all SQL goes here)  |
                  +---------------+---------------+
                                  |
                       private Postgres cluster
                (initdb'd by sqlplay, unix socket only)
```

### Private Postgres

sqlplay creates and runs its **own** Postgres cluster using the locally
installed Postgres binaries (found via `SQLPLAY_PG_BIN`, `pg_config`, PATH,
`/Library/PostgreSQL/*/bin`, Postgres.app, Homebrew).

- Data dir: `<project>/.pgdata/` (gitignored).
- Listens on a unix socket only (`listen_addresses = ''`), so nothing on the
  network can connect. No password needed.
- Started on demand by `sqlplay`, stopped with `sqlplay stop`.
- Advanced: `SQLPLAY_DSN` in `.env` points at an existing server instead.

The user's main Postgres server and `booksdb` are never touched.

### Database layout (database `sqlplayground`)

| Schema | Contents | Who can use it |
|---|---|---|
| `world_<slug>` | One per world: its tables and data | player: SELECT only |
| `sqlplay` | worlds registry, levels, progress, attempts, exams | app (owner) only |

Roles:
- `sqlplay_app`: owns `sqlplay` schema. Used for progress and level storage.
- `sqlplay_builder`: owns world schemas. Used only to load worlds.
- `sqlplay_player`: SELECT on world schemas, nothing else. Runs all player SQL
  and level reference queries.

## Worlds

A world = `schema.sql` + `data.sql` + `levels.yaml` + `world.yaml` (name,
emoji, blurb, join map).

Built-in worlds (shipped, tested): **pizza shop**, **school**, **movie
studio**. Each is designed with the same *shapes* as booksdb so HOA skills
transfer:

- a 4-5 table chain (e.g. customer - orders - orderline - pizza - supplier)
- a link-through table (like `bookauthor`)
- a column that references its own table (like `referredby`)
- rows with no match (items never ordered) for LEFT JOIN ... IS NULL
- names stored in CAPITALS, categories in mixed case, money columns for
  computed expressions (profit, markup)

AI worlds (key only): the model returns schema + data; the validator parses
it with the Postgres parser (pglast) and accepts only `CREATE TABLE` and
`INSERT`, max 8 tables and 500 rows, no functions in defaults. Loaded by
`sqlplay_builder` into a fresh `world_<slug>` schema inside a transaction.
Anything that fails is rejected whole.

## Levels

```yaml
id: pizza-q6
topic: subqueries          # select | shape | aggregates | subqueries | joins | selfleft | groupby
difficulty: 4              # 1-5, calibrated to the HOA (see below)
question: >
  Which pizzas made by the supplier of 'HAWAIIAN' earn more profit per
  slice than the average profit of all pizzas?
columns: ["Pizza", "Category"]   # required labels, in order (optional)
ordered: true                    # grade row order? (only if question says sorted)
order_note: "Pizza A -> Z"
answer: |
  SELECT ...
hints:
  - concept nudge
  - skeleton with blanks
  - near-answer
explain: why the answer works (shown after \answer)
```

### Difficulty scale (calibrated to the HOA)

| Level | Meaning | HOA examples |
|---|---|---|
| 1-2 | Warm-up, one skill | Q7 |
| 3 | Typical HOA: two skills, labels, sorting | Q1, Q2, Q3, Q4, Q5, Q8 |
| 4 | Hardest HOA: 3+ skills, lookup subquery | Q6, Q9, Q10 |
| 5 | Beyond the HOA: nested subqueries, LEFT JOIN + filters, computed columns, GROUP BY/HAVING | - |

Players start at level 3 in every topic.

### Level sources

1. **Hand-written** levels per built-in world (all topics, levels 2-5),
   including the 10 HOA questions re-cast for the pizza world.
2. **Pattern generator** (no key): templates that read a world's metadata
   (tables, numeric/text columns, join paths, self-references) and emit a
   question + reference query + hints. Every generated level is validated
   by running its answer (must succeed, return 1..50 rows) before use.
3. **AI levels** (key only): model writes question + answer + hints; same
   validation; rejected if it fails.

### Picking the next level

- Per-topic difficulty 1-5, starting at 3.
- 2 passes in a row in a topic -> difficulty +1. 2 gives/skips in a row -> -1.
- **Mix** (default): choose the topic with the lowest
  (difficulty, recency) score. **Lock**: stay on one topic.
- `groupby` topic unlocks after reaching level 3 in `aggregates` (shows a
  short explainer card first).

## Grading

Both queries run through the sandbox. Checks, in order; first failure wins:

1. **Runs?** Postgres error + plain-English translation for common errors
   (missing column/table, GROUP BY error, syntax near X, ambiguous column,
   unclosed quote/bracket, type mismatch).
2. **Rows** compared as multisets after normalising values (numbers rounded
   to 2 dp, trimmed strings, dates as ISO). Column count mismatch reported
   first. Feedback for too many rows (missing DISTINCT / join condition /
   filter), too few rows (WHERE too strict / inner join dropping rows), same
   count but different values.
3. **Order** (only when `ordered: true`).
4. **Labels** (only when `columns` given): exact, case-sensitive.

Result: PASS / FAIL + one specific feedback message.

## Modes

- **Practice**: one level at a time, 3 hints (each costs points), skip,
  give up -> answer + explanation.
- **Exam**: 10 questions in one world: ~3 at level 3, ~5 at level 4, ~2 at
  level 5, mixed topics. No hints, optional timer, graded at the end with a
  per-question breakdown. Answers can be revised until submit.

Scoring: points = 5 x difficulty, minus 2 per hint used. Streak counter.
Progress is stored in `sqlplay.progress`, shared by web and terminal.

## Sandbox (all SQL execution)

Player SQL and every reference query:
- connection as `sqlplay_player`, `search_path = world_<slug>`
- `BEGIN READ ONLY`, `SET LOCAL statement_timeout = '3s'`, always rolled back
- exactly one statement (parsed with pglast; multiple statements rejected)
- result capped at 500 rows

## Front ends

### Terminal (`sqlplay`)

psql-like REPL: multi-line input until `;`, results as psql-style tables,
commands `\hint \skip \answer \dt \d <table> \topic <t> \mix \exam \world
\score \help \q`. Colour output. Readline history.

### Web (`sqlplay web`)

FastAPI on 127.0.0.1:8000, single static page (no framework): world/topic
pickers, question card, SQL editor textarea (Ctrl+Enter to run), results
table, feedback banner, hint/skip/answer buttons, score + streak, schema
sidebar, exam mode with timer. AI buttons show "add a key to unlock" when no
key is configured.

## Optional AI

`.env`: `OPENAI_API_KEY`, `OPENAI_MODEL`. All provider calls are in
`engine/ai.py` (one function per task: `generate_world`, `generate_level`);
swapping provider only touches that file. The key is never logged, printed,
or sent to the browser. AI output is treated as untrusted and always goes
through the validator / sandbox.

## Testing

All tests run against a throwaway cluster initdb'd under `.pgtest/`.

- grader: order, labels, duplicates, decimals, each feedback branch
- sandbox: writes blocked, timeout, multi-statement rejected, player cannot
  read `sqlplay` schema
- world validator: rejects DROP/DELETE/UPDATE/functions/COPY/DO, size limits
- every built-in level: answer runs, returns rows, labels match `columns`
- generator: produces valid level 3-5 questions for each world
- ai: fake provider responses (no key, no cost)
- calibration: the 10 HOA questions recast in pizza world rate level 3-4

## Files

```
sqlplay/
  pyproject.toml
  .env.example
  sqlplay/
    engine/  db.py pg.py sandbox.py grader.py feedback.py levels.py
             generator.py adaptive.py exam.py worlds.py validator.py
             progress.py ai.py
    worlds/  pizza/ school/ movies/
    web/     app.py static/
    cli/     main.py
  tests/
  docs/design.md
```
