"""Per-topic difficulty, streaks and score (shared by web and terminal)."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg.types.json import Jsonb

from .db import Database
from .levels import (
    BONUS_TOPIC,
    CORE_TOPICS,
    MAX_DIFFICULTY,
    MIN_DIFFICULTY,
    START_DIFFICULTY,
    TOPICS,
    Level,
)

HINT_COST = 2
PASSES_TO_LEVEL_UP = 2
GIVEUPS_TO_LEVEL_DOWN = 2
GROUPBY_UNLOCK_PASSES = 3   # aggregates passes needed to unlock GROUP BY


@dataclass
class TopicState:
    topic: str
    difficulty: int = START_DIFFICULTY
    pass_streak: int = 0
    fail_streak: int = 0
    passed: int = 0
    attempted: int = 0
    last_seen: object = None


@dataclass
class Outcome:
    points: int = 0
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    difficulty_before: int = START_DIFFICULTY
    difficulty_after: int = START_DIFFICULTY
    unlocked: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def topic_states(db: Database) -> dict[str, TopicState]:
    with db.app() as conn:
        rows = conn.execute(
            "SELECT topic, difficulty, pass_streak, fail_streak, passed, attempted, last_seen FROM sqlplay.topic_state"
        ).fetchall()
    states = {t: TopicState(t) for t in TOPICS}
    for r in rows:
        if r[0] in states:
            states[r[0]] = TopicState(*r)
    return states


def _save_state(conn, s: TopicState) -> None:
    conn.execute(
        """INSERT INTO sqlplay.topic_state (topic, difficulty, pass_streak, fail_streak, passed, attempted, last_seen)
           VALUES (%s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (topic) DO UPDATE SET difficulty = EXCLUDED.difficulty,
             pass_streak = EXCLUDED.pass_streak, fail_streak = EXCLUDED.fail_streak,
             passed = EXCLUDED.passed, attempted = EXCLUDED.attempted, last_seen = now()""",
        (s.topic, s.difficulty, s.pass_streak, s.fail_streak, s.passed, s.attempted),
    )


def stats(db: Database) -> dict:
    with db.app() as conn:
        rows = dict(conn.execute("SELECT key, value FROM sqlplay.stats").fetchall())
    return {
        "score": int(rows.get("score", 0)),
        "streak": int(rows.get("streak", 0)),
        "best_streak": int(rows.get("best_streak", 0)),
        "groupby_intro_seen": bool(rows.get("groupby_intro_seen", False)),
        "show_expected": bool(rows.get("show_expected", True)),
        "ai_feedback": bool(rows.get("ai_feedback", True)),
        "ai_levels": bool(rows.get("ai_levels", True)),
    }


def _set_stat(conn, key: str, value) -> None:
    conn.execute(
        """INSERT INTO sqlplay.stats (key, value) VALUES (%s, %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (key, Jsonb(value)),
    )


SETTINGS = ("show_expected", "ai_feedback", "ai_levels")


def set_setting(db: Database, key: str, on: bool) -> None:
    if key not in SETTINGS:
        raise ValueError(f"Unknown setting {key}")
    with db.app() as conn:
        _set_stat(conn, key, bool(on))


def set_show_expected(db: Database, on: bool) -> None:
    set_setting(db, "show_expected", on)


def mark_groupby_intro_seen(db: Database) -> None:
    with db.app() as conn:
        _set_stat(conn, "groupby_intro_seen", True)


def unlocked_topics(states: dict[str, TopicState]) -> list[str]:
    topics = list(CORE_TOPICS)
    if states["aggregates"].passed >= GROUPBY_UNLOCK_PASSES or states[BONUS_TOPIC].attempted > 0:
        topics.append(BONUS_TOPIC)
    return topics


def log_attempt(db: Database, level: Level, sql: str, passed: bool, hints: int, mode: str) -> None:
    with db.app() as conn:
        conn.execute(
            "INSERT INTO sqlplay.attempts (level_id, sql, passed, hints_used, mode) VALUES (%s, %s, %s, %s, %s)",
            (level.id, sql, passed, hints, mode),
        )


def record_result(db: Database, level: Level, *, passed: bool, hints_used: int = 0) -> Outcome:
    """Record a finished level: passed=True, or passed=False for give-up/skip.

    Failed attempts before a pass don't count against the player; exploring
    with test queries is free.
    """
    states = topic_states(db)
    before_unlocked = set(unlocked_topics(states))
    s = states[level.topic]
    st = stats(db)
    out = Outcome(difficulty_before=s.difficulty)
    s.attempted += 1
    if passed:
        s.passed += 1
        s.pass_streak += 1
        s.fail_streak = 0
        out.points = max(1, level.points - HINT_COST * hints_used)
        st["score"] += out.points
        st["streak"] += 1
        if s.pass_streak >= PASSES_TO_LEVEL_UP and level.difficulty >= s.difficulty:
            s.difficulty = min(MAX_DIFFICULTY, s.difficulty + 1)
            s.pass_streak = 0
    else:
        s.fail_streak += 1
        s.pass_streak = 0
        st["streak"] = 0
        if s.fail_streak >= GIVEUPS_TO_LEVEL_DOWN:
            s.difficulty = max(MIN_DIFFICULTY, s.difficulty - 1)
            s.fail_streak = 0
    st["best_streak"] = max(st["best_streak"], st["streak"])
    with db.app() as conn:
        with conn.transaction():
            _save_state(conn, s)
            for k in ("score", "streak", "best_streak"):
                _set_stat(conn, k, st[k])
    states[level.topic] = s
    newly = set(unlocked_topics(states)) - before_unlocked
    out.unlocked = next(iter(newly), None)
    out.score, out.streak, out.best_streak = st["score"], st["streak"], st["best_streak"]
    out.difficulty_after = s.difficulty
    return out


def set_difficulty(db: Database, topic: str, difficulty: int) -> None:
    states = topic_states(db)
    s = states[topic]
    s.difficulty = max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, difficulty))
    s.pass_streak = s.fail_streak = 0
    with db.app() as conn:
        _save_state(conn, s)


def reset(db: Database) -> None:
    with db.app() as conn:
        with conn.transaction():
            conn.execute("DELETE FROM sqlplay.topic_state")
            conn.execute("DELETE FROM sqlplay.stats")
            conn.execute("DELETE FROM sqlplay.attempts")


def seen_level_ids(db: Database, world: str) -> dict[str, bool]:
    """level id -> passed-ever, for levels in this world the player has finished or tried."""
    return {k: v[0] for k, v in seen_levels(db, world).items()}


def seen_levels(db: Database, world: str) -> dict[str, tuple[bool, float]]:
    """level id -> (passed-ever, seconds since last attempt)."""
    with db.app() as conn:
        rows = conn.execute(
            """SELECT a.level_id, bool_or(a.passed), extract(epoch FROM now() - max(a.at))
               FROM sqlplay.attempts a
               JOIN sqlplay.levels l ON l.id = a.level_id
               WHERE l.world = %s GROUP BY a.level_id""",
            (world,),
        ).fetchall()
    return {lid: (bool(passed), float(ago)) for lid, passed, ago in rows}
