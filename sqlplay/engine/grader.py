"""Grade a player's query by comparing its results to the level's answer."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pglast import ast, enums, parse_sql
from pglast.parser import ParseError

from . import sandbox
from .db import Database
from .feedback import explain_error
from .levels import Level
from .sandbox import QueryResult


class LevelBroken(RuntimeError):
    """The level's own answer query failed; the level should be discarded."""


@dataclass
class Verdict:
    passed: bool
    kind: str            # pass | error | columns | rows | order | labels
    message: str         # one-line headline
    tip: str = ""        # tutor-style nudge
    result: QueryResult | None = None
    expected_columns: list[str] = field(default_factory=list)
    expected_rows: int = 0

    def to_dict(self) -> dict:
        r = self.result
        return {
            "passed": self.passed,
            "kind": self.kind,
            "message": self.message,
            "tip": self.tip,
            "expected_columns": self.expected_columns,
            "expected_rows": self.expected_rows,
            "result": None
            if r is None
            else {
                "columns": r.columns,
                "rows": [list(x) for x in r.display],
                "numeric": r.numeric,
                "truncated": r.truncated,
                "error": None if r.ok else r.error.psql_text(r.sql),
            },
        }


def norm_value(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    if isinstance(v, str):
        return v.strip()
    return v


def norm_rows(rows) -> list[tuple]:
    return [tuple(norm_value(v) for v in r) for r in rows]


# ---------------------------------------------------------------- order keys
def _order_keys(answer_sql: str, out_cols: list[str]) -> list[tuple[int, bool]] | None:
    """Work out which output columns the answer sorts by: [(index, descending)].

    Returns None when the sort keys can't be mapped to output columns; callers
    then fall back to exact order comparison.
    """
    try:
        stmt = parse_sql(sandbox.clean_sql(answer_sql))[0].stmt
    except (ParseError, IndexError):
        return None
    if not isinstance(stmt, ast.SelectStmt) or not stmt.sortClause:
        return None
    targets = stmt.targetList or ()
    lower_out = [c.lower() for c in out_cols]
    keys: list[tuple[int, bool]] = []
    for sb in stmt.sortClause:
        desc = sb.sortby_dir == enums.SortByDir.SORTBY_DESC
        node = sb.node
        idx = None
        if isinstance(node, ast.A_Const) and isinstance(node.val, ast.Integer):
            idx = node.val.ival - 1
        elif isinstance(node, ast.ColumnRef):
            name = getattr(node.fields[-1], "sval", None)
            if name is None:
                return None
            if name.lower() in lower_out:
                idx = lower_out.index(name.lower())
            else:
                for i, t in enumerate(targets):
                    v = t.val
                    if isinstance(v, ast.ColumnRef) and getattr(v.fields[-1], "sval", "").lower() == name.lower():
                        if [getattr(f, "sval", None) for f in v.fields] == [
                            getattr(f, "sval", None) for f in node.fields
                        ] or len(node.fields) == 1 or len(v.fields) == 1:
                            idx = i
                            break
        if idx is None or not (0 <= idx < len(out_cols)):
            return None
        keys.append((idx, desc))
    return keys


def _sort_key(v):
    # None sorts last ascending (Postgres default).
    return (v is None, v if v is not None else 0)


def _is_sorted(rows: list[tuple], keys: list[tuple[int, bool]]) -> bool:
    for a, b in zip(rows, rows[1:]):
        for idx, desc in keys:
            ka, kb = _sort_key(a[idx]), _sort_key(b[idx])
            try:
                if ka == kb:
                    continue
                if (ka < kb) != desc:
                    break
                return False
            except TypeError:
                return False
        # all keys equal -> tie, fine
    return True


# ---------------------------------------------------------------- diagnosis
def _shape(sql: str) -> dict:
    """Rough facts about a SELECT: does it join, aggregate, filter?"""
    out = {"joins": False, "aggregate": False, "where": False, "distinct": False}
    try:
        stmt = parse_sql(sandbox.clean_sql(sql))[0].stmt
    except (ParseError, IndexError):
        return out
    if not isinstance(stmt, ast.SelectStmt):
        return out
    frm = stmt.fromClause or ()
    out["joins"] = len(frm) > 1 or any(isinstance(f, ast.JoinExpr) for f in frm)
    out["where"] = stmt.whereClause is not None
    out["distinct"] = stmt.distinctClause is not None
    out["aggregate"] = bool(stmt.groupClause) or any(
        isinstance(t.val, ast.FuncCall)
        and getattr(t.val.funcname[-1], "sval", "").lower() in ("count", "sum", "avg", "min", "max")
        for t in (stmt.targetList or ())
    )
    return out


def _row_feedback(user: list[tuple], exp: list[tuple], user_sql: str = "") -> tuple[str, str]:
    cu, ce = Counter(user), Counter(exp)
    nu, ne = len(user), len(exp)
    shape = _shape(user_sql)
    if ne == 1 and nu > 1 and not shape["aggregate"]:
        return (
            f"The answer is a single row; you returned {nu}.",
            "This question wants a summary. Use aggregates like COUNT, SUM, AVG, MIN or MAX "
            "to squash the matching rows into one.",
        )
    if nu == 0:
        return (
            f"Your query returned no rows; expected {ne}.",
            "Your WHERE is filtering everything out. Check the values you compare against "
            "(CAPITALS for names? exact category spelling?) and that your join conditions link the right columns.",
        )
    if nu > ne:
        if set(cu) == set(ce):
            return (
                f"Too many rows: {nu} instead of {ne}. The extra rows are duplicates.",
                "The same row shows up more than once (often because of a JOIN). Try SELECT DISTINCT.",
            )
        if ne and nu >= ne * 3 and not (set(ce) <= set(cu)) and shape["joins"]:
            return (
                f"Way too many rows: {nu} instead of {ne}.",
                "Rows are being paired with rows they shouldn't be. Check that every joined table "
                "has a correct link (ON a.col = b.col), one per table after the first.",
            )
        if set(ce) <= set(cu):
            return (
                f"Too many rows: {nu} instead of {ne}. All the right rows are there, plus extras.",
                "Your filter is too loose. Re-read the question for a condition you haven't added yet.",
            )
        return (
            f"Too many rows: {nu} instead of {ne}, and some values differ.",
            "Check both the filter (WHERE) and which columns you are selecting.",
        )
    if nu < ne:
        if set(cu) <= set(ce):
            return (
                f"Too few rows: {nu} instead of {ne}. The rows you have are right, but some are missing.",
                "Your WHERE may be too strict (> vs >=? the right comparison value?), or an inner JOIN "
                "is dropping rows that have no match (LEFT JOIN keeps them).",
            )
        return (
            f"Too few rows: {nu} instead of {ne}, and some values differ.",
            "Check the filter and which columns you're selecting.",
        )
    # same count, different content
    ncols = len(exp[0]) if exp else 0
    for i in range(ncols):
        if Counter(r[i] for r in user) != Counter(r[i] for r in exp):
            # swapped columns?
            for j in range(ncols):
                if j != i and Counter(r[j] for r in user) == Counter(r[i] for r in exp):
                    return (
                        f"Right number of rows ({nu}), but columns {i + 1} and {j + 1} look swapped.",
                        "Put the columns in the order the question lists them.",
                    )
            return (
                f"Right number of rows ({nu}), but the values in column {i + 1} don't match.",
                "That column holds the wrong data or the wrong rows were kept. Check which "
                "column/calculation it should be, and your WHERE.",
            )
    return (
        f"Right number of rows ({nu}), but the rows don't match.",
        "Each column looks plausible on its own, but they're combined wrongly. Check your join conditions.",
    )


# ---------------------------------------------------------------- main entry
_expected_cache: dict[str, QueryResult] = {}


def expected_result(db: Database, level: Level) -> QueryResult:
    key = f"{level.id}:{hash(level.answer)}"
    if key not in _expected_cache:
        res = sandbox.run(db, level.world, level.answer)
        if not res.ok:
            raise LevelBroken(f"{level.id}: answer fails: {res.error.message}")
        _expected_cache[key] = res
    return _expected_cache[key]


def grade(db: Database, level: Level, user_sql: str) -> Verdict:
    exp = expected_result(db, level)
    res = sandbox.run(db, level.world, user_sql)
    base = dict(result=res, expected_columns=level.columns or exp.columns, expected_rows=len(exp.rows))

    if not res.ok:
        tip = explain_error(res.error, res.sql)
        return Verdict(False, "error", res.error.message, tip, **base)

    if len(res.columns) != len(exp.columns):
        want = len(exp.columns)
        listing = ", ".join(f'"{c}"' for c in (level.columns or exp.columns))
        return Verdict(
            False,
            "columns",
            f"You returned {len(res.columns)} column{'s' * (len(res.columns) != 1)}; the question wants {want}.",
            f"Expected columns: {listing}. Combine or drop columns to match.",
            **base,
        )

    u, e = norm_rows(res.rows), norm_rows(exp.rows)
    if Counter(u) != Counter(e):
        if res.truncated:
            msg, tip = "Too many rows (over 500).", "Check your join conditions: every row is pairing with every row."
        else:
            msg, tip = _row_feedback(u, e, user_sql)
        return Verdict(False, "rows", msg, tip, **base)

    if level.ordered:
        keys = _order_keys(level.answer, exp.columns)
        ok = _is_sorted(u, keys) if keys is not None else u == e
        if not ok:
            if u == list(reversed(e)):
                tip = "Your order is exactly reversed. Swap ASC/DESC."
            else:
                tip = f"Add or fix ORDER BY. The question wants: {level.order_note or 'see the question'}."
            return Verdict(False, "order", "Right rows, wrong order.", tip, **base)

    if level.columns:
        for i, (got, want) in enumerate(zip(res.columns, level.columns)):
            if got != want:
                tip = f'Use AS "{want}" for column {i + 1}.'
                if got.lower() == want.lower() or got == want.lower().replace(" ", ""):
                    tip += " Labels with capitals or spaces need double quotes."
                return Verdict(
                    False,
                    "labels",
                    f'Right rows! But column {i + 1} is labelled "{got}"; it should be "{want}".',
                    tip,
                    **base,
                )

    return Verdict(True, "pass", "Correct!", "", **base)
