"""Private Postgres cluster: find binaries, initdb, start, stop.

sqlplay runs its own cluster on a unix socket only, so it needs no password
and never touches the user's main Postgres server.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config

config.load()   # so SQLPLAY_PG_BIN / SQLPLAY_HOME / SQLPLAY_PORT can live in .env

PORT = int(os.environ.get("SQLPLAY_PORT", "54329"))


class PgError(RuntimeError):
    pass


def home_dir() -> Path:
    return Path(os.environ.get("SQLPLAY_HOME", Path.home() / ".sqlplay"))


def find_bin_dir() -> Path:
    """Locate a directory containing initdb, pg_ctl and postgres."""
    candidates: list[str] = []
    if env := os.environ.get("SQLPLAY_PG_BIN"):
        candidates.append(env)
    if pg_config := shutil.which("pg_config"):
        try:
            out = subprocess.run(
                [pg_config, "--bindir"], capture_output=True, text=True, check=True
            ).stdout.strip()
            candidates.append(out)
        except (subprocess.CalledProcessError, OSError):
            pass
    if initdb := shutil.which("initdb"):
        candidates.append(str(Path(initdb).parent))
    candidates += sorted(glob.glob("/Library/PostgreSQL/*/bin"), reverse=True)
    candidates += sorted(
        glob.glob("/Applications/Postgres.app/Contents/Versions/*/bin"), reverse=True
    )
    candidates += sorted(glob.glob("/opt/homebrew/opt/postgresql*/bin"), reverse=True)
    candidates += sorted(glob.glob("/usr/local/opt/postgresql*/bin"), reverse=True)
    candidates += sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)
    for c in candidates:
        p = Path(c)
        if all((p / exe).exists() for exe in ("initdb", "pg_ctl", "postgres")):
            return p
    raise PgError(
        "Could not find PostgreSQL server binaries (initdb, pg_ctl).\n"
        "Install PostgreSQL, or set SQLPLAY_PG_BIN to its bin directory."
    )


@dataclass
class Cluster:
    """A private Postgres cluster living under a base directory."""

    base: Path
    port: int = PORT

    @property
    def data_dir(self) -> Path:
        return self.base / "pgdata"

    @property
    def socket_dir(self) -> Path:
        return self.base / "run"

    @property
    def log_file(self) -> Path:
        return self.base / "postgres.log"

    def conninfo(self, user: str, dbname: str) -> str:
        return f"host={self.socket_dir} port={self.port} user={user} dbname={dbname}"

    def _bin(self, name: str) -> str:
        return str(find_bin_dir() / name)

    def initialized(self) -> bool:
        return (self.data_dir / "PG_VERSION").exists()

    def running(self) -> bool:
        if not self.initialized():
            return False
        r = subprocess.run(
            [self._bin("pg_ctl"), "status", "-D", str(self.data_dir)],
            capture_output=True,
            text=True,
        )
        return r.returncode == 0

    def init(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [
                self._bin("initdb"),
                "-D", str(self.data_dir),
                "-U", "postgres",
                "--auth=trust",
                "--encoding=UTF8",
                "--locale=C",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise PgError(f"initdb failed:\n{r.stderr or r.stdout}")
        conf = self.data_dir / "postgresql.conf"
        with conf.open("a") as f:
            f.write(
                "\n# sqlplay: unix socket only, nothing on the network\n"
                "listen_addresses = ''\n"
                f"port = {self.port}\n"
                f"unix_socket_directories = '{self.socket_dir}'\n"
                "max_connections = 30\n"
                "shared_buffers = 32MB\n"
                "fsync = off\n"
                "synchronous_commit = off\n"
                "full_page_writes = off\n"
            )

    def start(self) -> None:
        if not self.initialized():
            self.init()
        if self.running():
            return
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [
                self._bin("pg_ctl"),
                "start",
                "-D", str(self.data_dir),
                "-l", str(self.log_file),
                "-w",
                "-t", "30",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            tail = ""
            if self.log_file.exists():
                tail = "\n".join(self.log_file.read_text().splitlines()[-15:])
            raise PgError(f"Could not start Postgres:\n{r.stderr or r.stdout}\n{tail}")

    def stop(self) -> None:
        if self.running():
            subprocess.run(
                [self._bin("pg_ctl"), "stop", "-D", str(self.data_dir), "-m", "fast", "-w"],
                capture_output=True,
                text=True,
            )

    def destroy(self) -> None:
        self.stop()
        shutil.rmtree(self.base, ignore_errors=True)


def default_cluster() -> Cluster:
    return Cluster(home_dir())
