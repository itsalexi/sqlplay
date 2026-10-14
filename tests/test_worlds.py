"""Every built-in world installs and every level's answer passes its own grading."""

import pytest

from sqlplay.engine import generator, grader, worlds
from sqlplay.engine.game import in_syllabus
from sqlplay.engine.levels import TOPICS


@pytest.fixture(scope="module")
def installed(db):
    for slug in worlds.builtin_slugs():
        worlds.install(db, worlds.read_builtin(slug), "builtin")
    return worlds.builtin_slugs()


def all_levels():
    for slug in worlds.builtin_slugs():
        wf = worlds.read_builtin(slug)
        for raw in wf.levels:
            yield pytest.param(slug, raw, id=f"{slug}-{raw.get('id')}")


def test_three_worlds():
    assert {"pizza", "school", "movies"} <= set(worlds.builtin_slugs())


@pytest.mark.parametrize("slug,raw", list(all_levels()))
def test_level_self_grades(db, installed, slug, raw):
    lv = worlds.level_from_raw(slug, raw, "builtin")
    assert lv.topic in TOPICS
    assert 1 <= lv.difficulty <= 5
    assert len(lv.hints) >= 3 and lv.explain
    assert in_syllabus(lv.answer), "uses SQL outside the course"
    v = grader.grade(db, lv, lv.answer)
    assert v.passed, v.message


def test_pizza_has_all_hoa_recasts():
    ids = {raw["id"] for raw in worlds.read_builtin("pizza").levels}
    assert {f"hoa{i}" for i in range(1, 11)} <= ids


@pytest.mark.parametrize("slug", ["pizza", "school", "movies"])
def test_generator_every_key(db, installed, slug):
    for (topic, diff) in generator.TEMPLATES:
        lv = generator.generate(db, slug, topic, diff, seed=1)
        assert lv is not None, (topic, diff)
        assert generator.validate_spec(db, slug, lv) is None
        assert in_syllabus(lv.answer)
        assert grader.grade(db, lv, lv.answer).passed
