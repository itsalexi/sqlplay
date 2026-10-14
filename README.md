# psqlay

**Endless SQL practice for PostgreSQL, in your terminal or browser.**

psqlay gives you exam-style SQL questions and grades your answers by **comparing results, not query
text**. Any correct way of writing a query passes. It runs entirely on your machine, works without
an API key, and can use OpenAI for tutor feedback and new content if you want.

![psqlay in the browser](docs/img/web-dark.png)

```
  ●●●○○  level 3 · self-join & left join · 15 pts

  Which pizzas have never been ordered? Show the pizza ID and pizza name,
  labelled "Pizza ID" and "Pizza".

pizza=# SELECT p.pizzaid AS "Pizza ID", p.pizzaname AS "Pizza"
pizza-# FROM pizza p JOIN orderline ol ON p.pizzaid = ol.pizzaid;

✗ Way too many rows: 34 instead of 4.
  Either rows are being paired wrongly (check each JOIN's ON a.col = b.col, one per table
  after the first), or you're selecting a different set of rows than the question asks for.
  ai › Your inner JOIN keeps only pizzas that DO appear in orderline. Think about which
       kind of join keeps pizzas with no matching order, and how to pick out just those.
```

---

## Quick start

### Option A: let an AI agent set it up

Paste the prompt from **[docs/AGENT_SETUP.md](docs/AGENT_SETUP.md)** into Claude Code, Codex, Cursor or
any other coding agent. It checks for PostgreSQL and uv, installs psqlay, runs the one-time setup, and
never asks for your API key in chat.

### Option B: by hand

You need **PostgreSQL 14+** (the server programs: `initdb`, `pg_ctl`, `postgres`), **[uv](https://docs.astral.sh/uv/)**
and **git**. Supported on macOS and Linux; on Windows, use WSL.

```bash
git clone https://github.com/itsalexi/sqlplay ~/psqlay
cd ~/psqlay
uv tool install -e . --with openai
psqlay setup
```

Install PostgreSQL with `brew install postgresql@17` on macOS or `sudo apt install postgresql` on
Debian/Ubuntu. If `psqlay doctor` can't find it, add `SQLPLAY_PG_BIN=/path/to/postgres/bin` to
`~/psqlay/.env`.

Then:

```bash
psqlay        # play in the terminal
psqlay web    # play in the browser at http://127.0.0.1:8000
```

---

## What's inside

- **Three built-in worlds with 82 hand-written levels:** 🍕 a pizza chain, 🏫 a school and 🎬 a movie
  rental shop. Each is shaped like the classic "bookstore" exam database: a long join chain, a link
  table, a self-reference, and rows with no match. The pizza world includes the ten classic bookstore
  exam questions rewritten for pizza.
- **Questions that don't run out.** Once you've done the hand-written levels, a pattern generator builds
  new questions from the world's tables. Every one is checked against the real data before you see it.
  With a key, the AI also writes new levels in the background.
- **Adaptive difficulty** for each topic: SELECT/WHERE · AS/CONCAT/ORDER BY/DISTINCT · aggregates ·
  subqueries · JOINs · self-join & LEFT JOIN · GROUP BY/HAVING (unlocked as you go). You start at
  level 3, a typical exam question. Two passes in a row move you up a level, and two skips move you
  down. You can also lock one topic to drill it.
- **Expected output** appears under each question, like an exam handout. You can hide it for harder
  practice.
- **Feedback that teaches:**
  - Postgres errors explained in plain English (`column does not exist`, the GROUP BY error, curly
    quotes, unclosed brackets, and more)
  - Row-count diagnosis: "did you forget DISTINCT?", "your WHERE is too strict", "a join condition is
    missing"
  - When you're partly right, the exact **missing rows** and **extra rows**
  - Checks for sort order and column labels
- **Review:** levels you skipped or gave up on come back later for another try.
- **Exam mode:** 10 mixed questions (three at level 3, five at level 4, two at level 5), no hints, an
  optional timer, and a graded report at the end.
- **Freedom to experiment:** run any query without grading, use tab completion and query history, and
  explore with `\dt` and `\d`, just like in psql.

## Playing

### Terminal

| Input | What it does |
|---|---|
| SQL ending in `;` | Run your query and grade it |
| SQL ending in `\g` | Just run it, without grading |
| `Tab` / `↑` | Complete table and column names / previous queries |
| `\hint` | Next hint (3 per level, each costs 2 points) |
| `\skip` | New question (counts as a skip) |
| `\answer` | Give up and see the answer with an explanation |
| `\dt` · `\d <table>` · `\map` | List tables, describe a table, show the join map |
| `\topic <name>` · `\mix` | Lock to one topic / go back to the mix |
| `\level <topic> <1-5>` | Set your difficulty in a topic |
| `\world [name]` | List worlds / switch world |
| `\exam [minutes]` | Start a mock exam (`\next`, `\prev`, `\submit` inside it) |
| `\expected on\|off` | Show or hide the expected output |
| `\ai` · `\ai feedback on\|off` · `\ai levels on\|off` | AI settings |
| `\newworld [theme]` | Have the AI invent a new world |
| `\score` · `\help` · `\q` | Stats, help, quit |

### Browser

| Key | What it does |
|---|---|
| `⌘↵` / `Ctrl+↵` | Run and grade |
| `⇧⌘↵` | Just run (Try) |
| `⌥↑` / `⌥↓` | Step through past queries |
| `⌥H` · `⌥A` · `⌥S` | Hint · give up · skip |
| `↵` | Next level, after you pass |

Click a column in the schema sidebar to insert its name. Click **AI** in the top bar to turn AI
features on or off. The page follows your system's light/dark setting.

### Other commands

```bash
psqlay setup    # one-time init (safe to re-run)
psqlay doctor   # check Postgres, data folder and AI key
psqlay stop     # stop psqlay's private Postgres
psqlay reset    # clear your progress
```

## AI (optional)

Create `~/psqlay/.env` (start from `.env.example`). It's git-ignored:

```bash
OPENAI_API_KEY=sk-...
# optional
OPENAI_GEN_MODEL=gpt-6.1-sol        # writes levels (medium reasoning) and worlds (high reasoning)
OPENAI_FEEDBACK_MODEL=gpt-6.1-sol   # tutor feedback (low reasoning)
```

| Feature | When it runs | Rough cost |
|---|---|---|
| Tutor feedback | Each wrong answer: names what to rethink, never the answer | ~$0.001 |
| Tips | About 1 in 3 correct answers | ~$0.001 |
| AI-written levels | In the background, once the hand-written levels at your level run out | ~$0.01 each |
| Exam comments | Wrong answers in the exam report | ~$0.01 per exam |
| New world | When you ask for one (`\newworld`, or **New world** in the browser) | ~$0.10–0.25 |

A typical hour of practice costs about **$0.10–0.30**. You can switch each feature off with `\ai` or the
**AI** toggle, and you can set a hard spending limit in your OpenAI dashboard. Without a key, everything
else still works.

## How it works

- **Private Postgres.** psqlay uses your installed PostgreSQL programs to create its own database
  server in `~/.sqlplay`. It only listens on a local socket (no network port), needs no password,
  starts when you open psqlay, and restarts itself if it's stopped. Your own Postgres server is never
  touched.
- **Each world is its own schema**, in a `sqlplayground` database.
- **Sandboxed queries.** Your SQL runs as a read-only role inside a read-only transaction, with a
  3-second time limit, a 500-row cap, and one statement at a time. That role can't see the progress
  tables.
- **Grading** runs the level's answer and your query, then compares the rows as multisets. Numbers are
  rounded to 2 decimal places and text is trimmed. Order and labels are only checked when the question
  asks for them.
- **AI output is untrusted.** Generated worlds are parsed with the real Postgres parser, and only
  `CREATE TABLE` and `INSERT ... VALUES` are allowed, with no functions and size limits. Generated
  levels must run, return a sensible number of rows, have no ties in their sort order, and stay within
  the syllabus. Anything that fails is thrown away.

The full design is in [docs/design.md](docs/design.md).

## Make your own world

See **[docs/worlds.md](docs/worlds.md)** for the file format, the difficulty scale, and how to check
your levels.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Could not find PostgreSQL server binaries` | Install PostgreSQL, or set `SQLPLAY_PG_BIN` in `~/psqlay/.env` |
| `initdb: cannot be run as root` | Run psqlay as a normal user |
| Port 54329 is busy | Set `SQLPLAY_PORT=54331` in `.env` |
| `psqlay: command not found` | Run `uv tool update-shell`, then open a new terminal |
| Something else | `psqlay doctor`, then check `~/.sqlplay/postgres.log` |

## Development

```bash
uv sync --extra ai
uv run pytest -q                                         # uses a throwaway Postgres in .pgtest/
uv run python -m sqlplay.tools.check_world sqlplay/worlds/pizza --show
```

```
sqlplay/
  engine/   pg (private server) · db · sandbox · grader · feedback · generator · game · ai · validator
  cli/      terminal app (prompt_toolkit + rich)
  web/      FastAPI server + one static page (no framework)
  worlds/   built-in worlds
tests/
docs/       design, agent setup prompt, world format
```
