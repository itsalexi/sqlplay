"""Load, install and describe worlds (one Postgres schema per world)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

from .db import PLAYER, Database
from .levels import Level, level_id
from .validator import validate

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlds"
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


@dataclass
class WorldFiles:
    slug: str
    meta: dict
    schema_sql: str
    data_sql: str
    levels: list[dict] = field(default_factory=list)

    @property
    def version(self) -> str:
        blob = json.dumps(self.meta, sort_keys=True) + self.schema_sql + self.data_sql
        blob += json.dumps(self.levels, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


def builtin_slugs() -> list[str]:
    return sorted(p.name for p in BUILTIN_DIR.iterdir() if (p / "world.yaml").exists())


def read_builtin(slug: str) -> WorldFiles:
    d = BUILTIN_DIR / slug
    meta = yaml.safe_load((d / "world.yaml").read_text())
    levels_path = d / "levels.yaml"
    levels = yaml.safe_load(levels_path.read_text()) if levels_path.exists() else []
    return WorldFiles(
        slug=slug,
        meta=meta,
        schema_sql=(d / "schema.sql").read_text(),
        data_sql=(d / "data.sql").read_text(),
        levels=levels or [],
    )


def install(db: Database, wf: WorldFiles, source: str = "builtin") -> None:
    """(Re)create the world's schema and register it plus its levels."""
    if not SLUG_RE.match(wf.slug):
        raise ValueError(f"bad world slug {wf.slug!r}")
    validate(wf.schema_sql + "\n" + wf.data_sql)
    schema = db.world_schema(wf.slug)
    with db.builder() as conn:
        with conn.transaction():
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
            conn.execute(f'SET LOCAL search_path = "{schema}"')
            conn.execute(wf.schema_sql)
            conn.execute(wf.data_sql)
            conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{PLAYER}"')
            conn.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{PLAYER}"')
    with db.app() as conn:
        with conn.transaction():
            conn.execute(
                """INSERT INTO sqlplay.worlds (slug, name, emoji, blurb, source, meta, version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, emoji = EXCLUDED.emoji,
                     blurb = EXCLUDED.blurb, source = EXCLUDED.source, meta = EXCLUDED.meta,
                     version = EXCLUDED.version""",
                (
                    wf.slug,
                    wf.meta.get("name", wf.slug),
                    wf.meta.get("emoji", ""),
                    wf.meta.get("blurb", ""),
                    source,
                    Jsonb(wf.meta),
                    wf.version,
                ),
            )
            conn.execute(
                "DELETE FROM sqlplay.levels WHERE world = %s AND source = %s", (wf.slug, source)
            )
            for raw in wf.levels:
                lv = level_from_raw(wf.slug, raw, source)
                save_level(conn, lv)


def level_from_raw(world: str, raw: dict, source: str) -> Level:
    raw = dict(raw)
    raw.setdefault("world", world)
    raw.setdefault("source", source)
    raw["world"] = world
    if "id" not in raw:
        raw["id"] = level_id(world, source, raw["question"], raw["answer"])
    else:
        raw["id"] = f"{world}-{raw['id']}"
    return Level.from_dict(raw)


def save_level(conn, lv: Level) -> None:
    conn.execute(
        """INSERT INTO sqlplay.levels (id, world, topic, difficulty, source, data)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET topic = EXCLUDED.topic,
             difficulty = EXCLUDED.difficulty, source = EXCLUDED.source, data = EXCLUDED.data""",
        (lv.id, lv.world, lv.topic, lv.difficulty, lv.source, Jsonb(lv.to_dict())),
    )


def ensure_builtin(db: Database) -> None:
    """Install or refresh built-in worlds whose files changed."""
    with db.app() as conn:
        installed = dict(
            conn.execute("SELECT slug, version FROM sqlplay.worlds WHERE source = 'builtin'").fetchall()
        )
    for slug in builtin_slugs():
        wf = read_builtin(slug)
        if installed.get(slug) != wf.version:
            install(db, wf, "builtin")


def list_worlds(db: Database) -> list[dict]:
    with db.app() as conn:
        cur = conn.execute(
            """SELECT w.slug, w.name, w.emoji, w.blurb, w.source,
                      (SELECT count(*) FROM sqlplay.levels l WHERE l.world = w.slug)
               FROM sqlplay.worlds w ORDER BY w.source <> 'builtin', w.created_at, w.slug"""
        )
        return [
            dict(slug=s, name=n, emoji=e, blurb=b, source=src, levels=c)
            for s, n, e, b, src, c in cur.fetchall()
        ]


def get_world(db: Database, slug: str) -> dict | None:
    with db.app() as conn:
        row = conn.execute(
            "SELECT slug, name, emoji, blurb, source, meta FROM sqlplay.worlds WHERE slug = %s", (slug,)
        ).fetchone()
    if not row:
        return None
    s, n, e, b, src, meta = row
    return dict(slug=s, name=n, emoji=e, blurb=b, source=src, meta=meta)


def delete_world(db: Database, slug: str) -> None:
    with db.builder() as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{db.world_schema(slug)}" CASCADE')
    with db.app() as conn:
        conn.execute("DELETE FROM sqlplay.worlds WHERE slug = %s", (slug,))


def schema_info(db: Database, slug: str) -> list[dict]:
    """Tables with their columns (name, type, pk/fk info) for \\dt, \\d and the sidebar."""
    schema = db.world_schema(slug)
    with db.builder() as conn:
        cols = conn.execute(
            """SELECT c.table_name, c.column_name,
                      CASE WHEN c.data_type = 'character varying'
                           THEN 'varchar(' || c.character_maximum_length || ')'
                           WHEN c.data_type = 'numeric' AND c.numeric_precision IS NOT NULL
                           THEN 'numeric(' || c.numeric_precision || ',' || c.numeric_scale || ')'
                           ELSE c.data_type END,
                      c.is_nullable = 'YES'
               FROM information_schema.columns c
               WHERE c.table_schema = %s
               ORDER BY c.table_name, c.ordinal_position""",
            (schema,),
        ).fetchall()
        fks = conn.execute(
            """SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name
               FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage kcu
                 ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
               JOIN information_schema.constraint_column_usage ccu
                 ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
               WHERE tc.table_schema = %s AND tc.constraint_type = 'FOREIGN KEY'""",
            (schema,),
        ).fetchall()
        pks = conn.execute(
            """SELECT tc.table_name, kcu.column_name
               FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage kcu
                 ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
               WHERE tc.table_schema = %s AND tc.constraint_type = 'PRIMARY KEY'""",
            (schema,),
        ).fetchall()
        counts = {}
        tables = sorted({t for t, *_ in cols})
        for t in tables:
            counts[t] = conn.execute(f'SELECT count(*) FROM "{schema}"."{t}"').fetchone()[0]
    fk_map = {(t, c): f"{rt}.{rc}" for t, c, rt, rc in fks}
    pk_set = {(t, c) for t, c in pks}
    out: dict[str, dict] = {}
    for t, c, typ, nullable in cols:
        out.setdefault(t, {"table": t, "rows": counts.get(t, 0), "columns": []})
        out[t]["columns"].append(
            {
                "name": c,
                "type": typ,
                "nullable": nullable,
                "pk": (t, c) in pk_set,
                "fk": fk_map.get((t, c)),
            }
        )
    return [out[t] for t in tables]
