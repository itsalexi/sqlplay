"""Plain-English explanations for common Postgres errors."""

from __future__ import annotations

import re

from .sandbox import QueryError

CURLY = "‘’“”"


def explain_error(err: QueryError, sql: str) -> str:
    """Return a short tutor-style tip for an error (may be empty)."""
    msg = err.message
    low = msg.lower()
    state = err.sqlstate

    if any(c in sql for c in CURLY):
        return (
            "Your query contains curly quotes (‘ ’ or “ ”). SQL only understands straight "
            "quotes: ' for values and \" for labels. Retype them directly in the editor."
        )
    if err.kind in ("multi", "not_select", "empty", "timeout"):
        return ""

    if state == "42703" or "does not exist" in low and "column" in low:
        m = re.search(r'column "?([\w.]+)"? does not exist', msg)
        name = m.group(1) if m else "that"
        bare = name.split(".")[-1]
        if re.search(r'"' + re.escape(bare) + r'"', sql, re.I) and not re.search(
            r'as\s+"' + re.escape(bare) + r'"', sql, re.I
        ):
            return (
                f'"{bare}" in double quotes is read as a column name. For a value '
                f"(text you are matching), use single quotes: '{bare}'."
            )
        if "." in name:
            return (
                f"The table you prefixed has no column {bare}. Check the real column names "
                "with \\d <table> (or the schema sidebar). Spelling must be exact."
            )
        return (
            f"No table in your FROM/JOIN has a column called {bare}. Check spelling with "
            "\\d <table>. Remember: a label made with AS can't be used in WHERE."
        )
    if state == "42P01":
        m = re.search(r'missing FROM-clause entry for table "(\w+)"', msg)
        if m:
            return (
                f'You used "{m.group(1)}." as a prefix but never gave a table that nickname. '
                f"Add it after the table name in FROM/JOIN (e.g. FROM customer {m.group(1)})."
            )
        m = re.search(r'relation "([\w.]+)" does not exist', msg)
        name = m.group(1) if m else "that table"
        return f"There's no table called {name}. Run \\dt to list the tables (watch for plurals)."
    if state == "42803":
        return (
            "You mixed a squashed value (MAX/MIN/AVG/COUNT) with normal per-row columns. "
            "One aggregate gives one row, but the other column has many. To find which "
            "row has the max/min, put the aggregate in a subquery: WHERE col = (SELECT MAX(col) FROM ...)."
        )
    if state == "42702":
        m = re.search(r'column reference "(\w+)" is ambiguous', msg)
        col = m.group(1) if m else "that column"
        return (
            f"More than one joined table has a column called {col}. Put the table nickname "
            f"in front, e.g. c.{col}."
        )
    if state == "21000":
        return (
            "Your subquery returned more than one row, but = needs exactly one value. "
            "Use IN (...) instead of =, or make the subquery return one row (MAX/MIN/AVG or a tighter WHERE)."
        )
    if state in ("42883", "22P02", "42804"):
        if "operator does not exist" in low or "invalid input syntax" in low:
            return (
                "You're comparing different types, like a number column with text. "
                "Numbers don't need quotes (retail > 20); text does ('FL'). Dates look like '2003-04-01'."
            )
        if "argument of where must be type boolean" in low:
            return "WHERE needs a true/false condition, like col = value. Did you leave out the comparison?"
        if "function" in low and "does not exist" in low:
            return "That function name isn't recognised. Check spelling: MAX, MIN, AVG, COUNT, CONCAT, ROUND, UPPER."
    if state == "42601" or "syntax error" in low:
        if "unterminated quoted string" in low:
            return "A ' quote was opened but never closed. Every text value needs a quote on both sides: 'FL'."
        if "unterminated quoted identifier" in low:
            return 'A " quote was opened but never closed. Labels need a quote on both sides: "Customer Name".'
        m = re.search(r'at or near "([^"]*)"', msg)
        near = (m.group(1) if m else "").lower()
        if near == "from":
            return (
                "Something is off just before FROM. Usually a trailing comma after the last "
                "column, or a missing comma between columns."
            )
        if near == "select":
            return (
                "A second SELECT appeared where SQL didn't expect it. A subquery must be wrapped "
                "in brackets: col > (SELECT AVG(col) FROM t). And a query has only one main SELECT."
            )
        if near == "order":
            return (
                "\"order\" is a reserved word (ORDER BY). If you meant the table, check its exact name "
                "with \\dt (often orders)."
            )
        if near in ("where", "join", "on", "group", "having"):
            return (
                "Clauses must be written in this order: SELECT ... FROM ... JOIN ... ON ... "
                "WHERE ... GROUP BY ... HAVING ... ORDER BY ..."
            )
        if near == "":
            return "The query ended too early. Check for an unclosed bracket ( or a missing part after a keyword."
        if near == ")" or near == "(":
            return "Check your brackets: count every ( and make sure each has a matching )."
        if re.match(r"^\w+$", near) and re.search(r"\bas\s+" + re.escape(near), sql, re.I):
            return 'Labels with spaces or capitals need double quotes: AS "Customer Name".'
        return (
            "SQL couldn't read the query at that spot. Check commas between columns, quotes, "
            "brackets, and clause order (SELECT, FROM, JOIN, WHERE, ORDER BY)."
        )
    return ""
