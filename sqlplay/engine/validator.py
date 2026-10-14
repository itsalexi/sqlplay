"""Validate world SQL (schema + data) before it is executed.

World SQL may come from an AI model, so it is treated as untrusted: only
CREATE TABLE and INSERT ... VALUES are allowed, with no function calls, no
schema-qualified names, and size limits.
"""

from __future__ import annotations

from dataclasses import dataclass

from pglast import ast, parse_sql
from pglast.parser import ParseError
from pglast.visitors import Visitor

MAX_TABLES = 8
MAX_ROWS = 500

# Functions a world may use in literals/defaults (pure, harmless).
SAFE_FUNCS = {"date", "make_date"}


class WorldSQLError(ValueError):
    pass


@dataclass
class WorldStats:
    tables: list[str]
    rows: int


class _Checker(Visitor):
    def __init__(self):
        super().__init__()
        self.problems: list[str] = []

    def visit_FuncCall(self, ancestors, node):
        name = ".".join(getattr(n, "sval", "") for n in node.funcname).lower()
        if name not in SAFE_FUNCS:
            self.problems.append(f"function call {name}() is not allowed")

    def visit_RangeVar(self, ancestors, node):
        if node.schemaname or node.catalogname:
            self.problems.append(
                f"schema-qualified name {node.schemaname}.{node.relname} is not allowed"
            )

    def visit_SubLink(self, ancestors, node):
        self.problems.append("subqueries are not allowed in world SQL")


def validate(sql: str) -> WorldStats:
    try:
        stmts = parse_sql(sql)
    except ParseError as e:
        raise WorldSQLError(f"SQL does not parse: {e}") from e

    tables: list[str] = []
    rows = 0
    for raw in stmts:
        stmt = raw.stmt
        if isinstance(stmt, ast.CreateStmt):
            if stmt.inhRelations or stmt.partspec or stmt.tablespacename or stmt.ofTypename:
                raise WorldSQLError("CREATE TABLE options (INHERITS/PARTITION/TABLESPACE/OF) are not allowed")
            if stmt.relation.relpersistence not in ("p", None):
                raise WorldSQLError("only permanent tables are allowed")
            tables.append(stmt.relation.relname)
        elif isinstance(stmt, ast.InsertStmt):
            sel = stmt.selectStmt
            if not isinstance(sel, ast.SelectStmt) or not sel.valuesLists:
                raise WorldSQLError("INSERT must use VALUES (...)")
            if stmt.onConflictClause or getattr(stmt, "returningClause", None) or getattr(stmt, "returningList", None) or stmt.withClause:
                raise WorldSQLError("INSERT options (ON CONFLICT/RETURNING/WITH) are not allowed")
            rows += len(sel.valuesLists)
        else:
            kind = type(stmt).__name__.replace("Stmt", "").upper()
            raise WorldSQLError(f"{kind} statements are not allowed (only CREATE TABLE and INSERT)")

        checker = _Checker()
        checker(raw)
        if checker.problems:
            raise WorldSQLError("; ".join(sorted(set(checker.problems))))

    if not tables:
        raise WorldSQLError("no CREATE TABLE statements found")
    if len(tables) > MAX_TABLES:
        raise WorldSQLError(f"too many tables ({len(tables)} > {MAX_TABLES})")
    if rows > MAX_ROWS:
        raise WorldSQLError(f"too many rows ({rows} > {MAX_ROWS})")
    if len(set(tables)) != len(tables):
        raise WorldSQLError("duplicate table names")
    return WorldStats(tables=tables, rows=rows)
