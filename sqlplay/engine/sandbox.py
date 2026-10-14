"""Run one read-only SELECT as the player role inside a world schema."""

from __future__ import annotations

import datetime as dt
import decimal
from dataclasses import dataclass, field

import psycopg
from pglast import parse_sql
from pglast.parser import ParseError

from .db import Database

ROW_LIMIT = 500
TIMEOUT = "3s"

ALLOWED_STMTS = {"SelectStmt"}


@dataclass
class QueryError:
    message: str            # primary message, e.g. 'column "x" does not exist'
    sqlstate: str = ""
    position: int | None = None   # 1-based char offset into the SQL
    hint: str = ""
    kind: str = "postgres"  # postgres | multi | not_select | empty

    def psql_text(self, sql: str) -> str:
        """Format like psql: ERROR line, then LINE n: context with a caret."""
        out = [f"ERROR:  {self.message}"]
        if self.position:
            upto = sql[: self.position - 1]
            line_no = upto.count("\n") + 1
            line = sql.splitlines()[line_no - 1] if sql.splitlines() else sql
            col = len(upto) - (upto.rfind("\n") + 1)
            prefix = f"LINE {line_no}: "
            out.append(prefix + line)
            out.append(" " * (len(prefix) + col) + "^")
        if self.hint:
            out.append(f"HINT:  {self.hint}")
        return "\n".join(out)


@dataclass
class QueryResult:
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: QueryError | None = None
    truncated: bool = False
    display: list[tuple] = field(default_factory=list)   # psql-formatted strings (None = NULL)
    numeric: list[bool] = field(default_factory=list)    # per column: right-align?

    @property
    def ok(self) -> bool:
        return self.error is None


def clean_sql(sql: str) -> str:
    s = sql.strip()
    while s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def _plain(v):
    """Convert DB values to JSON-friendly Python values."""
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    if isinstance(v, memoryview):
        return bytes(v).hex()
    return v


def _disp(v):
    """Format a value the way psql prints it."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "t" if v else "f"
    if isinstance(v, decimal.Decimal):
        return format(v, "f")
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat(sep=" ") if isinstance(v, dt.datetime) else v.isoformat()
    return str(v)


def check_statement(sql: str) -> QueryError | None:
    """Reject empty input, multiple statements, and non-SELECTs before running.

    Syntax errors are left for Postgres to report, so the message matches psql.
    """
    if not sql.strip():
        return QueryError("Type a query first.", kind="empty")
    try:
        stmts = parse_sql(sql)
    except ParseError:
        return None
    if len(stmts) == 0:
        return QueryError("Type a query first.", kind="empty")
    if len(stmts) > 1:
        return QueryError(
            "Only one statement at a time. Remove the extra ';' or the second query.",
            kind="multi",
        )
    name = type(stmts[0].stmt).__name__
    if name not in ALLOWED_STMTS:
        verb = name.replace("Stmt", "").upper()
        return QueryError(
            f"Only SELECT queries are allowed here (you wrote a {verb} statement).",
            kind="not_select",
        )
    return None


def run(db: Database, world_slug: str, sql: str, limit: int = ROW_LIMIT) -> QueryResult:
    sql = clean_sql(sql)
    result = QueryResult(sql=sql)
    if err := check_statement(sql):
        result.error = err
        return result
    schema = db.world_schema(world_slug)
    with db.player() as conn:
        try:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute(f"SET LOCAL statement_timeout = '{TIMEOUT}'")
                conn.execute(f'SET LOCAL search_path = "{schema}"')
                cur = conn.execute(sql)
                if cur.description is None:
                    result.error = QueryError("That statement returned no rows.", kind="not_select")
                    raise _Rollback
                result.columns = [d.name for d in cur.description]
                rows = cur.fetchmany(limit + 1)
                result.truncated = len(rows) > limit
                rows = rows[:limit]
                result.rows = [tuple(_plain(v) for v in r) for r in rows]
                result.display = [tuple(_disp(v) for v in r) for r in rows]
                result.numeric = [
                    any(isinstance(r[i], (int, float, decimal.Decimal)) and not isinstance(r[i], bool) for r in rows)
                    for i in range(len(result.columns))
                ]
                raise _Rollback
        except _Rollback:
            pass
        except psycopg.errors.QueryCanceled:
            result.error = QueryError(
                f"Query took longer than {TIMEOUT} and was stopped. "
                "Check for a missing join condition (every row paired with every row).",
                sqlstate="57014",
                kind="timeout",
            )
        except psycopg.Error as e:
            diag = e.diag
            pos = int(diag.statement_position) if diag.statement_position else None
            result.error = QueryError(
                message=diag.message_primary or str(e).strip(),
                sqlstate=diag.sqlstate or "",
                position=pos,
                hint=diag.message_hint or "",
            )
    return result


class _Rollback(Exception):
    """Raised inside the transaction block so psycopg always rolls back."""
