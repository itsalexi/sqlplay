# psqlay

A SQL practice playground for PostgreSQL that runs on your own machine. It gives you an endless supply of
exam-style challenges and grades each answer by **comparing your results**, so any correct way of
writing the query passes. Play it in the terminal or in the browser.

```
pizza=# SELECT DISTINCT CONCAT(c.firstname, ' ', c.lastname) AS "Customer Name"
pizza-# FROM customer c JOIN orders o ON c.customerid = o.customerid
pizza-# ...;

✗ Too few rows: 4 instead of 6. The rows you have are right, but some are missing.
  ai › Your joins look fine. Check the WHERE: which price are you comparing against?
```

## Features

- **Three built-in worlds:** 🍕 pizza chain, 🏫 school, 🎬 movie rentals. Their tables are shaped like
  the classic bookstore exam database: a long join chain, a link table, a self-reference, and rows
  with no match. The pizza world includes all 10 HOA questions rewritten for pizza.
- **Endless levels without an API key.** The built-in levels come first. After that, a pattern
  generator builds new questions from each world's tables, and every one is checked before you see it.
- **Adaptive difficulty** for each topic, from level 1 to 5. Level 3 is a typical exam question,
  level 4 is the hardest exam questions, and level 5 goes beyond the exam. You can also lock one
  topic to drill it.
- **Expected output shown under every question**, like an HOA handout. You can hide it for harder practice.
- **Expected output** appears under every question, like an HOA handout. You can hide it for harder
  practice.
- **Exam mode:** 10 mixed questions, no hints, an optional timer, and a full breakdown at the end.
- **Feedback that teaches:** plain-English explanations of Postgres errors, plus checks for "too many
  rows: did you forget DISTINCT?", wrong sort order, and wrong labels. When your answer is partly
  right, it shows exactly **which rows are missing and which are extra**.
- **Review:** levels you gave up on or skipped come back later for another try.
- **Try queries freely:** run a query without grading it, use tab completion and query history, and see
  a session summary when you quit.
- **Optional AI** (OpenAI key): a tutor that tells you what to reconsider without giving the answer,
  new AI-written levels, and whole new themed worlds.
- **Safe:** your queries run as a read-only user with a time limit. AI-generated SQL is parsed and
  restricted before it runs.

## Install

You need PostgreSQL installed (psqlay uses its server programs) and
[uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/itsalexi/sqlplay && cd sqlplay
uv tool install -e . --with openai
```

psqlay runs its **own private Postgres** in `~/.sqlplay`. It only accepts connections from your
machine (a local socket, with no network access) and needs no password, so your normal Postgres
server is never touched.

## Play

```bash
psqlay          # terminal
psqlay web      # browser at http://127.0.0.1:8000
```

Terminal commands (psql-style):

| Command | What it does |
|---|---|
| SQL ending in `;` | Run your query and grade it |
| SQL ending in `\g` | Just run it, without grading (for trying things out) |
| `Tab` | Complete table and column names |
| `\hint` | Show the next hint (3 per level, each costs 2 points) |
| `\skip` | Skip to a new question |
| `\answer` | Give up and see the answer with an explanation |
| `\dt` `\d <table>` `\map` | Explore the tables and the join map |
| `\topic joins` / `\mix` | Drill one topic / go back to the mix |
| `\world [name]` | List worlds or switch to one |
| `\newworld [theme]` | Have the AI invent a new world (needs a key) |
| `\exam [minutes]` | Start a mock exam |
| `\score` | Show your progress |
| `\expected on|off` | Show or hide the expected output under each question |
| `\ai`, `\ai feedback on|off`, `\ai levels on|off` | AI settings (saved between sessions) |
| `\q` | Quit (progress is saved) |

In the browser: `⌘↵` runs and grades your query, `⇧⌘↵` just runs it, `⌥↑`/`⌥↓` steps through your past
queries, `⌥H` shows a hint, `⌥A` gives up, `⌥S` skips, and `↵` moves to the next level after you pass.
Click **AI** in the top bar to switch AI feedback or AI-written levels on or off.

Other commands: `psqlay doctor`, `psqlay stop` (stops the private Postgres), `psqlay reset` (clears
your progress).

## Optional: AI

Create a `.env` file in the project folder (it's git-ignored):

```
OPENAI_API_KEY=sk-...
# optional overrides
OPENAI_GEN_MODEL=gpt-6.1-sol        # writes worlds and levels
OPENAI_FEEDBACK_MODEL=gpt-6.1-sol   # tutor feedback (runs with low reasoning effort)
```

Without a key, everything except the AI features still works.

## Development

```bash
uv sync --extra ai
uv run pytest                                              # uses a throwaway Postgres in .pgtest/
uv run python -m sqlplay.tools.check_world sqlplay/worlds/pizza --show
```

The design is described in [docs/design.md](docs/design.md).
