"""Practice UX: row diffs, AI settings, review queue, crash recovery."""

from sqlplay.engine import ai, game as game_mod, worlds
from sqlplay.engine.game import Game
from sqlplay.engine.grader import grade


def _game(db):
    for slug in worlds.builtin_slugs():
        worlds.install(db, worlds.read_builtin(slug), "builtin")
    g = Game(db)
    g.set_world("pizza")
    return g


def test_no_diff_when_nothing_matches(db, level):
    v = grade(db, level("never"), "SELECT 'nope'")
    assert not v.passed and not v.missing and not v.extra


def test_same_count_message(db, mini):
    from sqlplay.engine.levels import Level
    lv = Level(id="mini-z", world="mini", topic="select", difficulty=2, question="q",
               answer="SELECT name FROM product WHERE price > 9")
    # expected GADGET, PAN, POT; this returns WIDGET, PAN, POT -> same count, one wrong
    v = grade(db, lv, "SELECT name FROM product WHERE price > 4 AND name <> 'GADGET'")
    assert not v.passed and "1 of them is wrong" in v.message
    assert [list(r) for r in v.missing] == [["GADGET"]] and [list(r) for r in v.extra] == [["WIDGET"]]


def test_ai_feedback_setting_respected(db, monkeypatch):
    g = _game(db)
    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "tutor_feedback", lambda *a, **k: "nudge")
    lv = g.next_level("select")
    v = g.submit("SELECT 1")["verdict"]
    g.set_setting("ai_feedback", False)
    assert g.tutor("SELECT 1", v) == ""
    g.set_setting("ai_feedback", True)
    assert g.tutor("SELECT 1", v) == "nudge"


def test_ai_levels_setting_blocks_prefetch(db, monkeypatch):
    g = _game(db)
    monkeypatch.setattr(ai, "available", lambda: True)
    called = []
    monkeypatch.setattr(g, "_prefetch_ai", lambda *a: called.append(a))
    g.set_setting("ai_levels", False)
    for _ in range(4):
        g.pick(topic="joins", difficulty=5)
    assert not called
    g.set_setting("ai_levels", True)


def test_missed_level_comes_back(db, monkeypatch):
    g = _game(db)
    lv = g.next_level("selfleft")
    g.give_up()
    with db.app() as conn:   # pretend it was an hour ago
        conn.execute("UPDATE sqlplay.attempts SET at = now() - interval '1 hour' WHERE level_id = %s", (lv.id,))
    monkeypatch.setattr(game_mod, "REVIEW_CHANCE", 1.0)
    g.level = None
    back = g.pick(topic="selfleft", difficulty=lv.difficulty)
    seen = __import__("sqlplay.engine.progress", fromlist=["x"]).seen_level_ids(db, "pizza")
    assert g.is_review and back.topic == "selfleft" and seen.get(back.id) is False


def test_restarts_stopped_server(db):
    db.cluster.stop()
    with db.app() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
