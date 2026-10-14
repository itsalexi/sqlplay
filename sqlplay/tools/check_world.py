"""Validate a world directory: install it on a private cluster and run every level.

Usage: python -m sqlplay.tools.check_world <world_dir> [--show]

Checks per level: valid topic/difficulty, >= 3 hints, explain present, answer
runs as the player, returns 1..60 rows (0 allowed only with allow_empty),
labels match `columns`, ordered levels have ORDER BY and no ties on the sort
keys. --show prints each level's result rows.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import yaml

from sqlplay.engine import grader, sandbox, worlds
from sqlplay.engine.db import Database
from sqlplay.engine.levels import MAX_DIFFICULTY, MIN_DIFFICULTY, TOPICS
from sqlplay.engine.pg import Cluster


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("world_dir")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    d = Path(args.world_dir).resolve()
    slug = d.name
    home = Path(os.environ.get("SQLPLAY_CHECK_HOME", f"/tmp/sqlplay-check-{slug}"))
    port = int(os.environ.get("SQLPLAY_CHECK_PORT", str(55000 + sum(map(ord, slug)) % 900)))
    db = Database(Cluster(home, port=port))
    wf = worlds.WorldFiles(
        slug=slug,
        meta=yaml.safe_load((d / "world.yaml").read_text()),
        schema_sql=(d / "schema.sql").read_text(),
        data_sql=(d / "data.sql").read_text(),
        levels=yaml.safe_load((d / "levels.yaml").read_text()) or [],
    )
    worlds.install(db, wf, "builtin")
    print(f"World {slug}: installed OK ({len(wf.levels)} levels)")
    for t in worlds.schema_info(db, slug):
        print(f"  {t['table']}: {t['rows']} rows")

    problems = 0
    by = Counter()
    for raw in wf.levels:
        lv = worlds.level_from_raw(slug, raw, "builtin")
        errs = []
        if lv.topic not in TOPICS:
            errs.append(f"unknown topic {lv.topic}")
        if not (MIN_DIFFICULTY <= lv.difficulty <= MAX_DIFFICULTY):
            errs.append("difficulty out of range")
        if len(lv.hints) < 3:
            errs.append("needs 3 hints")
        if not lv.explain:
            errs.append("missing explain")
        res = sandbox.run(db, slug, lv.answer)
        if not res.ok:
            errs.append(f"answer fails: {res.error.message}")
        else:
            n = len(res.rows)
            if n == 0 and not raw.get("allow_empty"):
                errs.append("answer returns 0 rows")
            if n > 60:
                errs.append(f"answer returns {n} rows (max 60)")
            if lv.columns and lv.columns != res.columns:
                errs.append(f"labels {res.columns} != columns {lv.columns}")
            if lv.ordered:
                keys = grader._order_keys(lv.answer, res.columns)
                if keys is None:
                    errs.append("ordered but sort keys not mappable to output columns (sort by an output column)")
                else:
                    rows = grader.norm_rows(res.rows)
                    ks = [tuple(r[i] for i, _ in keys) for r in rows]
                    if len(set(ks)) != len(ks):
                        errs.append("ties on sort keys: add a tie-breaker column to ORDER BY")
            # self-grade: the answer must pass its own level
            v = grader.grade(db, lv, lv.answer)
            if not v.passed:
                errs.append(f"answer does not pass its own grading: {v.message}")
        by[(lv.topic, lv.difficulty)] += 1
        status = "OK " if not errs else "BAD"
        print(f"[{status}] {lv.id} {lv.topic} d{lv.difficulty} rows={len(res.rows) if res.ok else '-'}")
        for e in errs:
            print(f"        - {e}")
        problems += bool(errs)
        if args.show and res.ok:
            print("        " + " | ".join(res.columns))
            for r in res.rows[:15]:
                print("        " + " | ".join(str(x) for x in r))
    print("\nCoverage (topic: difficulties):")
    for t in TOPICS:
        ds = sorted(d for (tt, d), c in by.items() if tt == t for _ in range(c))
        print(f"  {t:11} {ds}")
    db.cluster.stop()
    print(f"\n{problems} level(s) with problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
