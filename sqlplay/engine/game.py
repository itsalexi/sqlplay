"""Game session: the single API both front ends (web, terminal) use."""

from __future__ import annotations

import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import ai, generator, grader, progress, sandbox, worlds
from .db import Database
from .levels import BONUS_TOPIC, CORE_TOPICS, START_DIFFICULTY, TOPICS, Level, level_id
from .validator import WorldSQLError

EXAM_PLAN = [3, 3, 3, 4, 4, 4, 4, 4, 5, 5]
EXAM_TOPICS = ["subqueries", "joins", "selfleft", "subqueries", "joins", "shape", "aggregates", "selfleft",
               "subqueries", "joins"]
PASS_TIP_CHANCE = 0.35
REVIEW_AFTER = 15 * 60      # seconds before a missed level can come back
REVIEW_CHANCE = 0.3

GROUPBY_INTRO = """GROUP BY makes piles, then aggregates squash each pile separately.

  SELECT category, COUNT(*) FROM pizza GROUP BY category;

Without GROUP BY, COUNT(*) squashes the whole table into one number.
With GROUP BY category, you get one row per category, each with its own count.

Rules:
  * Every non-aggregate column in SELECT must also be in GROUP BY.
  * WHERE filters rows BEFORE grouping.  HAVING filters groups AFTER grouping:
      ... GROUP BY category HAVING COUNT(*) >= 2"""


def in_syllabus(sql: str) -> bool:
    """Reject answers using SQL the course doesn't cover (subquery in FROM, CTEs, windows, CASE...)."""
    from pglast import ast, parse_sql
    from pglast.visitors import Visitor

    class V(Visitor):
        bad = False

        def visit_RangeSubselect(self, *_):
            self.bad = True

        def visit_WithClause(self, *_):
            self.bad = True

        def visit_WindowDef(self, *_):
            self.bad = True

        def visit_CaseExpr(self, *_):
            self.bad = True

    try:
        stmts = parse_sql(sandbox.clean_sql(sql))
    except Exception:  # noqa: BLE001
        return False
    if len(stmts) != 1 or not isinstance(stmts[0].stmt, ast.SelectStmt) or stmts[0].stmt.op != 0 and str(stmts[0].stmt.op) != "SetOperation.SETOP_NONE":
        return False
    v = V()
    v(stmts[0])
    return not v.bad and sql.count("\n") <= 16


def preview(columns: list[str], rows: list, n: int = 8) -> str:
    if not columns:
        return "(no result)"
    lines = [" | ".join(columns)]
    lines += [" | ".join("NULL" if v is None else str(v) for v in r) for r in rows[:n]]
    if len(rows) > n:
        lines.append(f"... ({len(rows)} rows total)")
    else:
        lines.append(f"({len(rows)} rows)")
    return "\n".join(lines)


@dataclass
class ExamState:
    world: str
    levels: list[Level]
    answers: dict[int, str] = field(default_factory=dict)
    started: float = field(default_factory=time.time)
    minutes: int | None = None
    exam_id: int | None = None
    results: list[dict] | None = None

    @property
    def remaining(self) -> int | None:
        if not self.minutes:
            return None
        return max(0, int(self.started + self.minutes * 60 - time.time()))


class Game:
    def __init__(self, db: Database | None = None):
        self.db = db or Database()
        self.db.ensure_ready()
        worlds.ensure_builtin(self.db)
        all_worlds = worlds.list_worlds(self.db)
        if not all_worlds:
            raise RuntimeError("No worlds installed")
        slugs = [w["slug"] for w in all_worlds]
        self.world = "pizza" if "pizza" in slugs else slugs[0]
        self.locked: str | None = None
        self.level: Level | None = None
        self.hints_used = 0
        self.finished = False      # passed or gave up on the current level
        self.passed = False
        self.last_topic: str | None = None
        self.exam: ExamState | None = None
        self.rng = random.Random()
        self._prefetching: set[tuple[str, str, int]] = set()
        self._prefetch_lock = threading.Lock()
        self.is_review = False     # current level is a retry of one you missed earlier
        self.session = {"passed": 0, "attempts": 0, "points": 0, "missed": 0, "started": time.time()}

    # ------------------------------------------------------------ status / settings
    def ai_available(self) -> bool:
        return ai.available()

    def setting(self, key: str) -> bool:
        return progress.stats(self.db)[key]

    def set_setting(self, key: str, on: bool) -> None:
        progress.set_setting(self.db, key, on)

    def ai_feedback_on(self) -> bool:
        return self.ai_available() and self.setting("ai_feedback")

    def ai_levels_on(self) -> bool:
        return self.ai_available() and self.setting("ai_levels")

    def status(self) -> dict:
        states = progress.topic_states(self.db)
        unlocked = progress.unlocked_topics(states)
        st = progress.stats(self.db)
        w = worlds.get_world(self.db, self.world) or {}
        return {
            "world": {k: w.get(k) for k in ("slug", "name", "emoji", "blurb", "source")},
            "mode": "topic" if self.locked else "mix",
            "locked": self.locked,
            "score": st["score"],
            "streak": st["streak"],
            "show_expected": st["show_expected"],
            "best_streak": st["best_streak"],
            "ai": self.ai_available(),
            "ai_feedback": self.ai_available() and st["ai_feedback"],
            "ai_levels": self.ai_available() and st["ai_levels"],
            "session": self.session,
            "topics": [
                {
                    "topic": t,
                    "name": TOPICS[t],
                    "difficulty": states[t].difficulty,
                    "passed": states[t].passed,
                    "attempted": states[t].attempted,
                    "unlocked": t in unlocked,
                }
                for t in TOPICS
            ],
        }

    def worlds(self) -> list[dict]:
        return worlds.list_worlds(self.db)

    def schema(self) -> list[dict]:
        return worlds.schema_info(self.db, self.world)

    def world_meta(self) -> dict:
        return (worlds.get_world(self.db, self.world) or {}).get("meta", {})

    def set_world(self, slug: str) -> None:
        if not worlds.get_world(self.db, slug):
            raise ValueError(f"No world called {slug}")
        if self.level and not self.finished:
            self.level = None
        self.world = slug
        self.level = None

    def set_topic(self, topic: str | None) -> None:
        if topic is not None and topic not in TOPICS:
            raise ValueError(f"Unknown topic {topic}. Topics: {', '.join(TOPICS)}")
        self.locked = topic

    def set_difficulty(self, topic: str, difficulty: int) -> None:
        progress.set_difficulty(self.db, topic, difficulty)

    # ------------------------------------------------------------ picking
    def _choose_topic(self, states) -> str:
        unlocked = progress.unlocked_topics(states)
        pool = [t for t in unlocked if t != self.last_topic] or unlocked
        if self.rng.random() < 0.35:
            # focus on the weakest topic (lowest pass rate)
            return min(pool, key=lambda t: (states[t].passed + 1) / (states[t].attempted + 2))
        # otherwise the least recently practised
        epoch = 0.0
        return min(
            pool,
            key=lambda t: (states[t].last_seen.timestamp() if states[t].last_seen else epoch, self.rng.random()),
        )

    def _stored_levels(self, topic: str) -> list[Level]:
        with self.db.app() as conn:
            rows = conn.execute(
                "SELECT data FROM sqlplay.levels WHERE world = %s AND topic = %s", (self.world, topic)
            ).fetchall()
        return [Level.from_dict(r[0]) for r in rows]

    def _save(self, lv: Level) -> None:
        with self.db.app() as conn:
            worlds.save_level(conn, lv)

    def pick(self, topic: str | None = None, difficulty: int | None = None, allow_ai: bool = True,
             exclude: set[str] | None = None, review: bool = True) -> Level:
        states = progress.topic_states(self.db)
        topic = topic or self.locked or self._choose_topic(states)
        diff = difficulty or states[topic].difficulty
        seen_full = progress.seen_levels(self.db, self.world)
        seen = {k: v[0] for k, v in seen_full.items()}
        exclude = exclude or set()
        stored = [lv for lv in self._stored_levels(topic) if lv.id not in exclude]
        source_rank = {"builtin": 0, "ai": 1, "generated": 2}
        self.is_review = False

        # Bring back levels you missed (gave up / skipped) after a break, near your level.
        if review:
            missed = [
                lv for lv in stored
                if lv.id in seen_full and not seen_full[lv.id][0] and seen_full[lv.id][1] > REVIEW_AFTER
                and abs(lv.difficulty - diff) <= 1 and (not self.level or lv.id != self.level.id)
            ]
            if missed and self.rng.random() < REVIEW_CHANCE:
                self.is_review = True
                return self.rng.choice(missed)

        fresh = [lv for lv in stored if lv.id not in seen]
        exact = [lv for lv in fresh if lv.difficulty == diff and lv.source != "generated"]
        if exact:
            return self.rng.choice(exact)
        if allow_ai and self.ai_levels_on():
            # AI levels are slow to write: make one in the background for next time,
            # and serve an instant level now.
            self._prefetch_ai(topic, diff)
        gen = generator.generate(self.db, self.world, topic, diff, avoid=set(seen) | exclude | {l.id for l in stored})
        if gen and gen.difficulty == diff:
            self._save(gen)
            return gen
        fresh_gen = [lv for lv in fresh if lv.difficulty == diff]
        if fresh_gen:
            return self.rng.choice(fresh_gen)
        if fresh:
            return min(fresh, key=lambda lv: (abs(lv.difficulty - diff), source_rank.get(lv.source, 3), self.rng.random()))
        if gen:
            self._save(gen)
            return gen
        not_passed = [lv for lv in stored if not seen.get(lv.id)]
        pool = not_passed or stored
        if pool:
            return min(pool, key=lambda lv: (abs(lv.difficulty - diff), self.rng.random()))
        # nothing at all for this topic in this world: try any topic
        for t in CORE_TOPICS:
            if t != topic:
                lvs = self._stored_levels(t)
                if lvs:
                    return self.rng.choice(lvs)
        raise RuntimeError("No levels available in this world")

    def next_level(self, topic: str | None = None) -> Level:
        if self.level and not self.finished:
            # skipping counts like giving up for difficulty purposes
            progress.record_result(self.db, self.level, passed=False)
            progress.log_attempt(self.db, self.level, "-- skipped", False, self.hints_used, "practice")
            self.session["missed"] += 1
        self.level = self.pick(topic)
        self.last_topic = self.level.topic
        self.hints_used = 0
        self.finished = False
        self.passed = False
        return self.level

    def current(self) -> Level:
        return self.level or self.next_level()

    def expected(self, lv: Level | None = None) -> dict | None:
        """The level's expected output (like the result shown on an HOA handout)."""
        lv = lv or self.current()
        try:
            res = grader.expected_result(self.db, lv)
        except grader.LevelBroken:
            return None
        return {"columns": res.columns, "rows": [list(r) for r in res.display], "numeric": res.numeric}

    def show_expected(self) -> bool:
        return progress.stats(self.db)["show_expected"]

    def set_show_expected(self, on: bool) -> None:
        progress.set_show_expected(self.db, on)

    def needs_groupby_intro(self) -> bool:
        return (
            self.level is not None
            and self.level.topic == BONUS_TOPIC
            and not progress.stats(self.db)["groupby_intro_seen"]
        )

    def groupby_intro(self) -> str:
        progress.mark_groupby_intro_seen(self.db)
        return GROUPBY_INTRO

    # ------------------------------------------------------------ playing
    def hint(self) -> tuple[int, str] | None:
        lv = self.current()
        if self.hints_used >= len(lv.hints):
            return None
        text = lv.hints[self.hints_used]
        self.hints_used += 1
        return self.hints_used, text

    def run(self, sql: str) -> sandbox.QueryResult:
        return sandbox.run(self.db, self.world, sql)

    def submit(self, sql: str) -> dict:
        lv = self.current()
        try:
            v = grader.grade(self.db, lv, sql)
        except grader.LevelBroken as e:
            self._drop_level(lv)
            return {"broken": True, "message": f"This level turned out to be broken and was removed ({e}). Type \\skip."}
        progress.log_attempt(self.db, lv, sql, v.passed, self.hints_used, "practice")
        self.session["attempts"] += 1
        out: dict = {"verdict": v, "outcome": None, "first_pass": False}
        if v.passed and not self.finished:
            out["outcome"] = progress.record_result(self.db, lv, passed=True, hints_used=self.hints_used)
            self.session["passed"] += 1
            self.session["points"] += out["outcome"].points
            out["first_pass"] = True
            self.finished = True
            self.passed = True
        return out

    def tutor(self, sql: str, verdict: grader.Verdict) -> str:
        """AI nudge for a failed attempt (empty string if unavailable)."""
        if not self.ai_feedback_on() or verdict.passed:
            return ""
        lv = self.current()
        exp = grader.expected_result(self.db, lv)
        res = verdict.result
        user_prev = res.error.psql_text(res.sql) if res and not res.ok else preview(res.columns, res.rows) if res else ""
        try:
            return ai.tutor_feedback(
                lv.question, sql, verdict.message, verdict.tip, lv.answer,
                preview(exp.columns, exp.rows), user_prev,
            )
        except ai.AIError:
            return ""

    def pass_tip(self, sql: str) -> str:
        if not self.ai_feedback_on() or self.rng.random() > PASS_TIP_CHANCE:
            return ""
        try:
            return ai.pass_tip(self.current().question, sql, self.current().answer)
        except ai.AIError:
            return ""

    def give_up(self) -> dict:
        lv = self.current()
        if not self.finished:
            progress.record_result(self.db, lv, passed=False)
            progress.log_attempt(self.db, lv, "-- gave up", False, self.hints_used, "practice")
            self.session["missed"] += 1
            self.finished = True
        exp = grader.expected_result(self.db, lv)
        return {"answer": lv.answer.strip(), "explain": lv.explain, "columns": exp.columns,
                "rows": [list(r) for r in exp.display], "numeric": exp.numeric}

    def _drop_level(self, lv: Level) -> None:
        with self.db.app() as conn:
            conn.execute("DELETE FROM sqlplay.levels WHERE id = %s AND source <> 'builtin'", (lv.id,))
        self.level = None

    # ------------------------------------------------------------ AI content
    def _schema_text(self, world: str | None = None) -> str:
        world = world or self.world
        lines = []
        for t in worlds.schema_info(self.db, world):
            cols = ", ".join(
                f"{c['name']} {c['type']}" + (" PK" if c["pk"] else "") + (f" -> {c['fk']}" if c["fk"] else "")
                for c in t["columns"]
            )
            lines.append(f"{t['table']}({cols})  [{t['rows']} rows]")
        meta = (worlds.get_world(self.db, world) or {}).get("meta", {})
        if meta.get("join_map"):
            lines.append("\nJoin map:\n" + meta["join_map"])
        if meta.get("notes"):
            lines.append("\nNotes: " + meta["notes"])
        return "\n".join(lines)

    def _sample_text(self, world: str | None = None, per_table: int = 6) -> str:
        world = world or self.world
        out = []
        for t in worlds.schema_info(self.db, world):
            r = sandbox.run(self.db, world, f'SELECT * FROM "{t["table"]}" LIMIT {per_table}')
            if r.ok:
                out.append(f"-- {t['table']}\n" + preview(r.columns, r.rows, per_table))
        return "\n\n".join(out)

    def _prefetch_ai(self, topic: str, diff: int) -> None:
        key = (self.world, topic, diff)
        with self._prefetch_lock:
            if key in self._prefetching or len(self._prefetching) >= 2:
                return
            self._prefetching.add(key)
        world = self.world
        stored = self._stored_levels(topic)

        def work():
            try:
                self._ai_level(topic, diff, stored, world=world)
            except Exception:  # noqa: BLE001 - background best effort
                pass
            finally:
                with self._prefetch_lock:
                    self._prefetching.discard(key)

        threading.Thread(target=work, daemon=True).start()

    def _example_levels(self, topic: str, diff: int) -> list[dict]:
        with self.db.app() as conn:
            rows = conn.execute(
                """SELECT data FROM sqlplay.levels WHERE source = 'builtin' AND topic = %s
                   ORDER BY abs(difficulty - %s), random() LIMIT 3""",
                (topic, diff),
            ).fetchall()
        return [r[0] for r in rows]

    def _ai_level(self, topic: str, diff: int, stored: list[Level], world: str | None = None) -> Level | None:
        world = world or self.world
        examples = self._example_levels(topic, diff)
        try:
            spec = ai.generate_level(
                self._schema_text(world), self._sample_text(world), topic, diff, examples,
                [lv.question for lv in stored],
            )
            lv = Level(
                id=level_id(world, "ai", spec["question"], spec["answer"]),
                world=world, topic=topic, difficulty=diff,
                question=spec["question"].strip(), answer=spec["answer"].strip(),
                columns=spec.get("columns") or None, ordered=bool(spec.get("ordered")),
                order_note=spec.get("order_note", ""), hints=list(spec.get("hints", []))[:3],
                explain=spec.get("explain", ""), source="ai",
            )
        except (ai.AIError, KeyError, TypeError, ValueError):
            return None
        if len(lv.hints) < 3 or generator.validate_spec(self.db, world, lv) is not None:
            return None
        if not in_syllabus(lv.answer) or len(lv.question) > 600:
            return None
        self._save(lv)
        return lv

    def new_world(self, theme: str | None = None) -> dict:
        """Generate, validate and install an AI world. Returns its listing entry."""
        if not self.ai_available():
            raise ai.AIError("Add OPENAI_API_KEY to .env to generate worlds")
        existing = [w["slug"] for w in self.worlds()]
        last_err = ""
        for _ in range(2):
            spec = ai.generate_world(theme, existing)
            slug = re.sub(r"[^a-z0-9_]", "", str(spec.get("slug", "")).lower())[:20] or "world"
            if not slug[0].isalpha():
                slug = "w" + slug
            base, i = slug, 2
            while slug in existing:
                slug, i = f"{base}{i}", i + 1
            wf = worlds.WorldFiles(
                slug=slug,
                meta={k: spec.get(k, "") for k in ("name", "emoji", "blurb", "join_map", "notes")},
                schema_sql=spec.get("schema_sql", ""),
                data_sql=spec.get("data_sql", ""),
                levels=[],
            )
            try:
                worlds.install(self.db, wf, "ai")
            except (WorldSQLError, ValueError, Exception) as e:  # noqa: BLE001 - any failure rejects the world
                last_err = str(e)[:300]
                worlds.delete_world(self.db, slug)
                continue
            if len(self.schema_for(slug)) < 3:
                worlds.delete_world(self.db, slug)
                last_err = "too few tables"
                continue
            return next(w for w in self.worlds() if w["slug"] == slug)
        raise ai.AIError(f"Could not build a valid world: {last_err}")

    def schema_for(self, slug: str) -> list[dict]:
        return worlds.schema_info(self.db, slug)

    def delete_world(self, slug: str) -> None:
        w = worlds.get_world(self.db, slug)
        if not w or w["source"] == "builtin":
            raise ValueError("Only AI-generated worlds can be deleted")
        worlds.delete_world(self.db, slug)
        if self.world == slug:
            self.world = self.worlds()[0]["slug"]
            self.level = None

    # ------------------------------------------------------------ exam
    def start_exam(self, minutes: int | None = None, use_ai: bool = False) -> ExamState:
        chosen: list[Level] = []
        ids: set[str] = set()
        for diff, topic in zip(EXAM_PLAN, EXAM_TOPICS):
            try:
                lv = self.pick(topic=topic, difficulty=diff, allow_ai=use_ai, exclude=ids, review=False)
            except RuntimeError:
                continue
            chosen.append(lv)
            ids.add(lv.id)
        chosen.sort(key=lambda lv: lv.difficulty)
        self.exam = ExamState(world=self.world, levels=chosen, minutes=minutes)
        return self.exam

    def exam_answer(self, index: int, sql: str) -> sandbox.QueryResult:
        if not self.exam:
            raise RuntimeError("No exam running")
        self.exam.answers[index] = sql
        return sandbox.run(self.db, self.exam.world, sql)

    def exam_submit(self, ai_comments: bool = True) -> dict:
        ex = self.exam
        if not ex:
            raise RuntimeError("No exam running")
        results = []
        score = total = 0
        for i, lv in enumerate(ex.levels):
            sql = ex.answers.get(i, "").strip()
            total += lv.points
            if sql:
                v = grader.grade(self.db, lv, sql)
                progress.log_attempt(self.db, lv, sql, v.passed, 0, "exam")
            else:
                v = grader.Verdict(False, "blank", "No answer given.")
            if v.passed:
                score += lv.points
            results.append({
                "index": i, "question": lv.question, "topic": lv.topic, "difficulty": lv.difficulty,
                "points": lv.points, "sql": sql, "passed": v.passed, "message": v.message, "tip": v.tip,
                "answer": lv.answer.strip(), "explain": lv.explain, "ai_comment": "",
            })
        if ai_comments and self.ai_feedback_on():
            todo = [r for r in results if not r["passed"] and r["sql"]]

            def comment(r):
                try:
                    return ai.exam_comment(r["question"], r["sql"], r["message"], r["answer"])
                except ai.AIError:
                    return ""

            with ThreadPoolExecutor(max_workers=10) as pool:
                for r, text in zip(todo, pool.map(comment, todo)):
                    r["ai_comment"] = text
        elapsed = int(time.time() - ex.started)
        summary = {"score": score, "total": total, "correct": sum(r["passed"] for r in results),
                   "count": len(results), "seconds": elapsed, "results": results}
        from psycopg.types.json import Jsonb

        with self.db.app() as conn:
            conn.execute(
                "INSERT INTO sqlplay.exams (world, data, finished_at) VALUES (%s, %s, now())",
                (ex.world, Jsonb(summary)),
            )
        ex.results = results
        self.exam = None
        return summary
