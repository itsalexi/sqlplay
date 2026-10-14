import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "worlds"


@pytest.fixture(scope="session")
def db():
    from sqlplay.engine.db import Database
    from sqlplay.engine.pg import Cluster

    cluster = Cluster(ROOT / ".pgtest", port=int(os.environ.get("SQLPLAY_TEST_PORT", "54339")))
    database = Database(cluster)
    database.ensure_ready()
    yield database
    cluster.stop()


@pytest.fixture(scope="session")
def mini(db):
    from sqlplay.engine import worlds

    d = FIXTURES / "mini"
    import yaml

    wf = worlds.WorldFiles(
        slug="mini",
        meta=yaml.safe_load((d / "world.yaml").read_text()),
        schema_sql=(d / "schema.sql").read_text(),
        data_sql=(d / "data.sql").read_text(),
        levels=yaml.safe_load((d / "levels.yaml").read_text()),
    )
    worlds.install(db, wf, "builtin")
    return "mini"


@pytest.fixture
def level(db, mini):
    from sqlplay.engine.levels import Level

    def get(short_id):
        with db.app() as conn:
            row = conn.execute("SELECT data FROM sqlplay.levels WHERE id = %s", (f"mini-{short_id}",)).fetchone()
        return Level.from_dict(row[0])

    return get
