"""Database bootstrap and role-scoped connections.

Roles:
  sqlplay_app      owns the `sqlplay` schema (progress, levels, worlds registry)
  sqlplay_builder  owns world schemas; used only to load worlds
  sqlplay_player   SELECT on world schemas only; runs all player/reference SQL
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from .pg import Cluster, default_cluster

DBNAME = "sqlplayground"
APP, BUILDER, PLAYER = "sqlplay_app", "sqlplay_builder", "sqlplay_player"

APP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sqlplay.worlds (
    slug        text PRIMARY KEY,
    name        text NOT NULL,
    emoji       text NOT NULL DEFAULT '',
    blurb       text NOT NULL DEFAULT '',
    source      text NOT NULL,              -- builtin | ai
    meta        jsonb NOT NULL DEFAULT '{}',
    version     text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sqlplay.levels (
    id          text PRIMARY KEY,
    world       text NOT NULL REFERENCES sqlplay.worlds(slug) ON DELETE CASCADE,
    topic       text NOT NULL,
    difficulty  int  NOT NULL,
    source      text NOT NULL,              -- builtin | generated | ai
    data        jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS levels_pick ON sqlplay.levels (world, topic, difficulty);
CREATE TABLE IF NOT EXISTS sqlplay.topic_state (
    topic        text PRIMARY KEY,
    difficulty   int  NOT NULL DEFAULT 3,
    pass_streak  int  NOT NULL DEFAULT 0,
    fail_streak  int  NOT NULL DEFAULT 0,
    passed       int  NOT NULL DEFAULT 0,
    attempted    int  NOT NULL DEFAULT 0,
    last_seen    timestamptz
);
CREATE TABLE IF NOT EXISTS sqlplay.stats (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS sqlplay.attempts (
    id          bigserial PRIMARY KEY,
    level_id    text NOT NULL,
    sql         text NOT NULL,
    passed      boolean NOT NULL,
    hints_used  int NOT NULL DEFAULT 0,
    mode        text NOT NULL DEFAULT 'practice',
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sqlplay.exams (
    id          bigserial PRIMARY KEY,
    world       text NOT NULL,
    data        jsonb NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
"""


class Database:
    def __init__(self, cluster: Cluster | None = None):
        self.cluster = cluster or default_cluster()
        self._ready = False

    # -- connections -------------------------------------------------------
    def connect(self, role: str, dbname: str = DBNAME, autocommit: bool = True) -> psycopg.Connection:
        return psycopg.connect(self.cluster.conninfo(role, dbname), autocommit=autocommit)

    @contextmanager
    def app(self) -> Iterator[psycopg.Connection]:
        self.ensure_ready()
        with self.connect(APP) as conn:
            yield conn

    @contextmanager
    def builder(self) -> Iterator[psycopg.Connection]:
        self.ensure_ready()
        with self.connect(BUILDER) as conn:
            yield conn

    @contextmanager
    def player(self) -> Iterator[psycopg.Connection]:
        self.ensure_ready()
        with self.connect(PLAYER) as conn:
            yield conn

    # -- bootstrap ---------------------------------------------------------
    def ensure_ready(self) -> None:
        if self._ready:
            return
        self.cluster.start()
        self._bootstrap()
        self._ready = True

    def _bootstrap(self) -> None:
        with psycopg.connect(self.cluster.conninfo("postgres", "postgres"), autocommit=True) as su:
            for role in (APP, BUILDER, PLAYER):
                exists = su.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
                if not exists:
                    su.execute(f'CREATE ROLE "{role}" LOGIN NOINHERIT')
            if not su.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DBNAME,)).fetchone():
                su.execute(f'CREATE DATABASE "{DBNAME}" OWNER "{APP}"')
        with psycopg.connect(self.cluster.conninfo("postgres", DBNAME), autocommit=True) as su:
            su.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            su.execute(f'GRANT CREATE ON DATABASE "{DBNAME}" TO "{BUILDER}"')
            su.execute(f'CREATE SCHEMA IF NOT EXISTS sqlplay AUTHORIZATION "{APP}"')
            su.execute(f'REVOKE ALL ON SCHEMA sqlplay FROM PUBLIC')
            su.execute(f'ALTER ROLE "{PLAYER}" SET statement_timeout = \'5s\'')
        with psycopg.connect(self.cluster.conninfo(APP, DBNAME), autocommit=True) as app:
            app.execute(APP_SCHEMA_SQL)

    def world_schema(self, slug: str) -> str:
        return f"world_{slug}"
