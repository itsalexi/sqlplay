"""AI paths with a fake provider: no key, no network, no cost."""

import pytest

from sqlplay.engine import ai, worlds
from sqlplay.engine.game import Game, in_syllabus


@pytest.fixture
def game(db):
    for slug in worlds.builtin_slugs():
        worlds.install(db, worlds.read_builtin(slug), "builtin")
    g = Game(db)
    g.set_world("pizza")
    return g


def test_syllabus_guard():
    assert in_syllabus("SELECT a FROM t WHERE x > (SELECT AVG(x) FROM t)")
    assert not in_syllabus("SELECT a FROM (SELECT 1 a) s")
    assert not in_syllabus("WITH c AS (SELECT 1) SELECT * FROM c")
    assert not in_syllabus("SELECT CASE WHEN 1=1 THEN 1 END")


def test_ai_level_accepted(game, monkeypatch):
    monkeypatch.setattr(ai, "generate_level", lambda *a, **k: {
        "question": "Which pizzas cost more than 9? Show the name labelled \"Pizza\", A to Z.",
        "columns": ["Pizza"], "ordered": True, "order_note": "Pizza A-Z",
        "answer": 'SELECT pizzaname AS "Pizza" FROM pizza WHERE cost > 9 ORDER BY 1',
        "hints": ["a", "b", "c"], "explain": "x",
    })
    lv = game._ai_level("select", 2, [])
    assert lv is not None and lv.source == "ai"


def test_ai_level_rejected_when_broken(game, monkeypatch):
    monkeypatch.setattr(ai, "generate_level", lambda *a, **k: {
        "question": "q", "columns": [], "answer": "SELECT nope FROM pizza", "hints": ["a", "b", "c"], "explain": "x",
    })
    assert game._ai_level("select", 2, []) is None


def test_ai_level_rejected_outside_syllabus(game, monkeypatch):
    monkeypatch.setattr(ai, "generate_level", lambda *a, **k: {
        "question": "q", "columns": [], "answer": "SELECT x FROM (SELECT pizzaname x FROM pizza) s",
        "hints": ["a", "b", "c"], "explain": "x",
    })
    assert game._ai_level("select", 2, []) is None


def test_ai_world_rejects_dangerous_sql(game, monkeypatch):
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "generate_world", lambda *a, **k: {
        "slug": "evil", "name": "Evil", "emoji": "x", "blurb": "", "join_map": "", "notes": "",
        "schema_sql": "CREATE TABLE t (i int); DROP SCHEMA sqlplay CASCADE;", "data_sql": "",
    })
    with pytest.raises(ai.AIError):
        game.new_world("evil")
    assert worlds.get_world(game.db, "evil") is None
    with game.db.app() as conn:  # app schema intact
        assert conn.execute("SELECT count(*) FROM sqlplay.levels").fetchone()[0] > 0


def test_ai_world_installs(game, monkeypatch):
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "generate_world", lambda *a, **k: {
        "slug": "tiny", "name": "Tiny", "emoji": "t", "blurb": "b", "join_map": "a -id- b", "notes": "",
        "schema_sql": "CREATE TABLE a (id int PRIMARY KEY, name varchar(10));"
                      "CREATE TABLE b (bid int PRIMARY KEY, id int REFERENCES a(id), qty int);"
                      "CREATE TABLE c (cid int PRIMARY KEY, label varchar(10));",
        "data_sql": "INSERT INTO a VALUES (1,'X'),(2,'Y'); INSERT INTO b VALUES (1,1,3); INSERT INTO c VALUES (1,'Z');",
    })
    w = game.new_world()
    assert w["slug"] == "tiny" and w["source"] == "ai"
    game.delete_world("tiny")
