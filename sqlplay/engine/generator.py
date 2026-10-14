"""Pattern-based level generator (no AI needed).

Reads a world's schema and data, then fills question templates with real
tables, columns and values. Every generated level is validated by running
its answer (must succeed, return 1..40 rows, no ties on sort keys).
"""

from __future__ import annotations

import random
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from . import grader, sandbox
from .db import Database
from .levels import Level, level_id
from .worlds import schema_info

NUMERIC = ("integer", "numeric", "smallint", "bigint", "real", "double precision")
MAX_ROWS = 40


# ------------------------------------------------------------------ context
@dataclass
class Col:
    table: str
    name: str
    type: str
    pk: bool
    fk: str | None

    @property
    def is_key(self) -> bool:
        n = self.name.lower()
        return self.pk or bool(self.fk) or n.endswith("id") or n.endswith("no") or n.endswith("_id")

    @property
    def numeric(self) -> bool:
        return self.type.startswith(NUMERIC) and not self.is_key

    @property
    def text(self) -> bool:
        return (self.type.startswith(("varchar", "character", "text"))) and not self.is_key

    @property
    def date(self) -> bool:
        return self.type == "date"


@dataclass
class Table:
    name: str
    rows: int
    cols: list[Col]

    def col(self, name: str) -> Col | None:
        return next((c for c in self.cols if c.name == name), None)

    @property
    def pk(self) -> Col | None:
        pks = [c for c in self.cols if c.pk]
        return pks[0] if len(pks) == 1 else None

    @property
    def first(self) -> Col | None:
        return next((c for c in self.cols if c.text and re.search(r"first|fname|given", c.name)), None)

    @property
    def last(self) -> Col | None:
        return next((c for c in self.cols if c.text and re.search(r"last|lname|surname|family", c.name)), None)

    @property
    def is_person(self) -> bool:
        return bool(self.first and self.last)

    @property
    def label(self) -> Col | None:
        for pat in (r"^(name|title)$", r"title", r"name"):
            for c in self.cols:
                if c.text and re.search(pat, c.name) and not re.search(r"first|last|fname|lname", c.name):
                    return c
        return None

    @property
    def nums(self) -> list[Col]:
        return [c for c in self.cols if c.numeric]

    @property
    def texts(self) -> list[Col]:
        return [c for c in self.cols if c.text]


@dataclass
class Ctx:
    db: Database
    world: str
    tables: dict[str, Table]
    rng: random.Random
    _cache: dict = field(default_factory=dict)

    def q(self, sql: str) -> list[tuple]:
        if sql not in self._cache:
            r = sandbox.run(self.db, self.world, sql, limit=2000)
            self._cache[sql] = r.rows if r.ok else []
        return self._cache[sql]

    def edges(self) -> list[tuple[str, str, str, str]]:
        """FK edges: (child_table, child_col, parent_table, parent_col)."""
        out = []
        for t in self.tables.values():
            for c in t.cols:
                if c.fk:
                    pt, pc = c.fk.split(".")
                    out.append((t.name, c.name, pt, pc))
        return out

    def categories(self, t: Table) -> list[tuple[Col, list[str]]]:
        """Text columns with 2..8 distinct values that repeat (good for filters/grouping)."""
        out = []
        for c in t.texts:
            if t.label and c.name == t.label.name:
                continue
            if t.is_person and c.name in (t.first.name, t.last.name):
                continue
            vals = [r[0] for r in self.q(f'SELECT DISTINCT "{c.name}" FROM "{t.name}" WHERE "{c.name}" IS NOT NULL')]
            if 2 <= len(vals) <= 8 and len(vals) < t.rows:
                out.append((c, sorted(vals)))
        return out

    def person_name(self, t: Table) -> tuple[str, str] | None:
        rows = self.q(f'SELECT "{t.first.name}", "{t.last.name}" FROM "{t.name}" ORDER BY 1, 2')
        return self.rng.choice(rows) if rows else None


def build_ctx(db: Database, world: str, seed: int | None = None) -> Ctx:
    info = schema_info(db, world)
    tables = {
        t["table"]: Table(
            t["table"],
            t["rows"],
            [Col(t["table"], c["name"], c["type"], c["pk"], c["fk"]) for c in t["columns"]],
        )
        for t in info
    }
    return Ctx(db, world, tables, random.Random(seed))


# ------------------------------------------------------------------ helpers
def noun(t: str) -> str:
    return t.replace("_", " ")


def plural(t: str) -> str:
    n = noun(t)
    if n.endswith(("s", "x")):
        return n
    if n.endswith("y") and n[-2:-1] not in "aeiou":
        return n[:-1] + "ies"
    return n + "s"


def human(col: str) -> str:
    """suppliername -> supplier name, mentorid -> mentor, orderdate -> order date."""
    c = col.replace("_", " ")
    for suffix in ("name", "date", "title"):
        if c.endswith(suffix) and len(c) > len(suffix) and not c.endswith(" " + suffix):
            return c[: -len(suffix)] + " " + suffix
    if c.endswith("id") and len(c) > 2:
        return c[:-2].strip()
    return c


def label(col: str) -> str:
    return human(col).title()


def fullname(alias: str, t: Table) -> str:
    return f"CONCAT({alias}.{t.first.name}, ' ', {alias}.{t.last.name})"


def lit(v) -> str:
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, int) else f"{v:g}"
    return "'" + str(v).replace("'", "''") + "'"


def fmt(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def pick_threshold(ctx: Ctx, t: Table, c: Col, where: str = "") -> float | None:
    vals = sorted(
        r[0] for r in ctx.q(f'SELECT "{c.name}" FROM "{t.name}" {where}') if r[0] is not None
    )
    if len(vals) < 4:
        return None
    v = vals[len(vals) // 2 - 1 + ctx.rng.randint(0, 2)]
    return round(float(v), 2)


Spec = dict  # question, answer, columns, ordered, order_note, hints, explain


# ------------------------------------------------------------------ templates
def t_select_filter(ctx: Ctx) -> Spec | None:
    cands = [t for t in ctx.tables.values() if t.label and t.nums and ctx.categories(t)]
    if not cands:
        return None
    t = ctx.rng.choice(cands)
    cat, vals = ctx.rng.choice(ctx.categories(t))
    v = ctx.rng.choice(vals)
    n = ctx.rng.choice(t.nums)
    x = pick_threshold(ctx, t, n)
    if x is None:
        return None
    return dict(
        question=f"List the {t.label.name} and {n.name} of every {noun(t.name)} whose {cat.name} is "
        f"'{v}' or whose {n.name} is greater than {fmt(x)}.",
        answer=f'SELECT {t.label.name}, {n.name}\nFROM {t.name}\nWHERE {cat.name} = {lit(v)} OR {n.name} > {lit(x)};',
        hints=[
            "Two conditions, and a row only needs to meet one of them. Which keyword joins them?",
            f"SELECT ____, ____ FROM {t.name} WHERE ____ = '____' ____ ____ > ____;",
            f"SELECT {t.label.name}, {n.name} FROM {t.name} WHERE {cat.name} = '{v}' OR ...",
        ],
        explain=f"OR keeps a row if either condition is true. Text values like '{v}' need single quotes "
        "and must match the stored case exactly; numbers don't need quotes.",
    )


def t_select_in(ctx: Ctx) -> Spec | None:
    cands = [t for t in ctx.tables.values() if t.label and t.nums and any(len(v) >= 3 for _, v in ctx.categories(t))]
    if not cands:
        return None
    t = ctx.rng.choice(cands)
    cat, vals = ctx.rng.choice([(c, v) for c, v in ctx.categories(t) if len(v) >= 3])
    chosen = sorted(ctx.rng.sample(vals, 2))
    n = ctx.rng.choice(t.nums)
    x = pick_threshold(ctx, t, n, f"WHERE {cat.name} IN ({lit(chosen[0])}, {lit(chosen[1])})")
    if x is None:
        return None
    return dict(
        question=f"Show the {t.label.name}, {cat.name} and {n.name} of each {noun(t.name)} in the "
        f"'{chosen[0]}' or '{chosen[1]}' {cat.name} with a {n.name} of at most {fmt(x)}. "
        f"Sort by {n.name}, highest first, then {t.label.name} A to Z.",
        answer=f"SELECT {t.label.name}, {cat.name}, {n.name}\nFROM {t.name}\n"
        f"WHERE {cat.name} IN ({lit(chosen[0])}, {lit(chosen[1])}) AND {n.name} <= {lit(x)}\n"
        f"ORDER BY {n.name} DESC, {t.label.name};",
        ordered=True,
        order_note=f"{n.name} highest first, then {t.label.name} A-Z",
        hints=[
            "IN (...) checks against a list of values. 'At most' means <=.",
            f"WHERE {cat.name} IN ('____', '____') AND {n.name} ____ {fmt(x)} ORDER BY ____ DESC, ____",
            f"... WHERE {cat.name} IN ('{chosen[0]}', '{chosen[1]}') AND {n.name} <= {fmt(x)} ORDER BY ...",
        ],
        explain="IN is shorthand for several ORs on the same column. AND then narrows it further. "
        "The second ORDER BY column breaks ties.",
    )


def t_shape_people(ctx: Ctx) -> Spec | None:
    people = [t for t in ctx.tables.values() if t.is_person and t.pk]
    for t in ctx.rng.sample(people, len(people)):
        cats = ctx.categories(t)
        if not cats:
            continue
        cat, vals = ctx.rng.choice(cats)
        counts = ctx.q(f'SELECT "{cat.name}", count(*) FROM "{t.name}" GROUP BY 1 HAVING count(*) >= 2 ORDER BY 1')
        if not counts:
            continue
        v = ctx.rng.choice(counts)[0]
        return dict(
            question=f"Show every {noun(t.name)} whose {cat.name} is '{v}'. Label the {t.pk.name} column "
            f"\"Number\" and put the full name (first name, a space, last name) in one column labelled "
            f"\"Full Name\". Sort by number, largest first.",
            answer=f'SELECT {t.pk.name} AS "Number", CONCAT({t.first.name}, \' \', {t.last.name}) AS "Full Name"\n'
            f"FROM {t.name}\nWHERE {cat.name} = {lit(v)}\nORDER BY {t.pk.name} DESC;",
            columns=["Number", "Full Name"],
            ordered=True,
            order_note="Number, largest first",
            hints=[
                "Glue two columns into one with CONCAT, and rename columns with AS \"...\".",
                f"SELECT ____ AS \"Number\", CONCAT(____, ' ', ____) AS \"Full Name\" FROM {t.name} WHERE ____ ORDER BY ____ DESC;",
                f"SELECT {t.pk.name} AS \"Number\", CONCAT({t.first.name}, ' ', {t.last.name}) AS \"Full Name\" FROM {t.name} WHERE ...",
            ],
            explain="CONCAT builds a new column from pieces; the ' ' adds the space. Double quotes are for "
            "labels with spaces/capitals, single quotes for values.",
        )
    return None


def t_shape_distinct(ctx: Ctx) -> Spec | None:
    cands = [(t, c) for t in ctx.tables.values() if t.nums for c, _ in ctx.categories(t)]
    if not cands:
        return None
    t, cat = ctx.rng.choice(cands)
    n = ctx.rng.choice(t.nums)
    x = pick_threshold(ctx, t, n)
    if x is None:
        return None
    return dict(
        question=f"Which {cat.name} values have at least one {noun(t.name)} with a {n.name} above {fmt(x)}? "
        f"List each {cat.name} once, labelled \"{label(cat.name)}\", sorted A to Z.",
        answer=f'SELECT DISTINCT {cat.name} AS "{label(cat.name)}"\nFROM {t.name}\nWHERE {n.name} > {lit(x)}\nORDER BY 1;',
        columns=[label(cat.name)],
        ordered=True,
        order_note=f"{cat.name} A-Z",
        hints=[
            "'List each once' means duplicates must go. Which keyword removes repeated rows?",
            f"SELECT DISTINCT ____ AS \"{label(cat.name)}\" FROM {t.name} WHERE ____ > ____ ORDER BY ____;",
            f"SELECT DISTINCT {cat.name} AS \"{label(cat.name)}\" FROM {t.name} WHERE {n.name} > {fmt(x)} ORDER BY ...",
        ],
        explain="WHERE first keeps the matching rows, then DISTINCT collapses repeated values into one.",
    )


def t_agg_minmax(ctx: Ctx) -> Spec | None:
    cands = [(t, c, v) for t in ctx.tables.values() if t.nums for c, v in ctx.categories(t)]
    if not cands:
        return None
    t, cat, vals = ctx.rng.choice(cands)
    v = ctx.rng.choice(vals)
    n = ctx.rng.choice(t.nums)
    return dict(
        question=f"For {plural(t.name)} in the '{v}' {cat.name}, find the highest {n.name}, the lowest "
        f"{n.name}, and how many rows there are. Label them \"Highest\", \"Lowest\" and \"How Many\".",
        answer=f'SELECT MAX({n.name}) AS "Highest", MIN({n.name}) AS "Lowest", COUNT(*) AS "How Many"\n'
        f"FROM {t.name}\nWHERE {cat.name} = {lit(v)};",
        columns=["Highest", "Lowest", "How Many"],
        hints=[
            "Aggregates squash many rows into one answer. WHERE decides which rows get squashed.",
            f"SELECT MAX(____) AS \"Highest\", MIN(____) AS \"Lowest\", COUNT(*) AS \"How Many\" FROM {t.name} WHERE ____;",
            f"SELECT MAX({n.name}) AS \"Highest\", MIN({n.name}) AS \"Lowest\", COUNT(*) AS \"How Many\" FROM {t.name} WHERE ...",
        ],
        explain="One query can hold several aggregates separated by commas. They all work on the rows "
        "that survived the WHERE.",
    )


def t_agg_avg(ctx: Ctx) -> Spec | None:
    cands = [t for t in ctx.tables.values() if len(t.nums) >= 1 and t.rows >= 4]
    if not cands:
        return None
    t = ctx.rng.choice(cands)
    n = ctx.rng.choice(t.nums)
    other = ctx.rng.choice(t.nums)
    x = pick_threshold(ctx, t, other)
    if x is None:
        return None
    return dict(
        question=f"Among {plural(t.name)} with a {other.name} of {fmt(x)} or more, what is the average "
        f"{n.name} (rounded to 2 decimals) and the total number of rows? Label them \"Average\" and \"Total\".",
        answer=f'SELECT ROUND(AVG({n.name}), 2) AS "Average", COUNT(*) AS "Total"\nFROM {t.name}\nWHERE {other.name} >= {lit(x)};',
        columns=["Average", "Total"],
        hints=[
            "AVG and COUNT are aggregates; filter first with WHERE. ROUND(value, 2) rounds to 2 decimals.",
            f"SELECT ROUND(AVG(____), 2) AS \"Average\", COUNT(*) AS \"Total\" FROM {t.name} WHERE ____ >= ____;",
            f"SELECT ROUND(AVG({n.name}), 2) AS \"Average\", COUNT(*) AS \"Total\" FROM {t.name} WHERE ...",
        ],
        explain="The WHERE picks which rows go into the average. ROUND(..., 2) keeps two decimals.",
    )


def t_sub_above_avg(ctx: Ctx) -> Spec | None:
    cands = [t for t in ctx.tables.values() if t.label and t.nums]
    if not cands:
        return None
    t = ctx.rng.choice(cands)
    n = ctx.rng.choice(t.nums)
    return dict(
        question=f"Which {plural(t.name)} have a {n.name} higher than the average {n.name} of all "
        f"{plural(t.name)}? Show {t.label.name} and {n.name} labelled \"Name\" and \"{label(n.name)}\", "
        f"highest {n.name} first (ties: Name A to Z).",
        answer=f'SELECT {t.label.name} AS "Name", {n.name} AS "{label(n.name)}"\nFROM {t.name}\n'
        f"WHERE {n.name} > (SELECT AVG({n.name}) FROM {t.name})\nORDER BY 2 DESC, 1;",
        columns=["Name", label(n.name)],
        ordered=True,
        order_note=f"{n.name} highest first, then Name",
        hints=[
            "The average is one number you don't know yet. Compute it with a subquery and compare each row to it.",
            f"WHERE {n.name} > (SELECT ____({n.name}) FROM ____)",
            f"SELECT {t.label.name} AS \"Name\", {n.name} AS \"{label(n.name)}\" FROM {t.name} WHERE {n.name} > (SELECT AVG({n.name}) FROM {t.name}) ORDER BY ...",
        ],
        explain="The subquery runs first and returns the average; the outer WHERE keeps rows above it.",
    )


def t_sub_max_in_cat(ctx: Ctx) -> Spec | None:
    cands = [(t, c, v) for t in ctx.tables.values() if t.label and t.nums for c, v in ctx.categories(t)]
    ctx.rng.shuffle(cands)
    for t, cat, vals in cands:
        n = ctx.rng.choice(t.nums)
        v = ctx.rng.choice(vals)
        fn = ctx.rng.choice(["MAX", "MIN"])
        word = "highest" if fn == "MAX" else "lowest"
        return dict(
            question=f"Which {noun(t.name)} in the '{v}' {cat.name} has the {word} {n.name}? "
            f"Show its {t.label.name} and {n.name}.",
            answer=f"SELECT {t.label.name}, {n.name}\nFROM {t.name}\n"
            f"WHERE {cat.name} = {lit(v)}\n  AND {n.name} = (SELECT {fn}({n.name}) FROM {t.name} WHERE {cat.name} = {lit(v)});",
            hints=[
                f"{fn} gives the {word} value but not which row it came from. Use it in a subquery, then find the row with that value.",
                f"WHERE {cat.name} = '{v}' AND {n.name} = (SELECT {fn}(____) FROM {t.name} WHERE ____)",
                f"... AND {n.name} = (SELECT {fn}({n.name}) FROM {t.name} WHERE {cat.name} = '{v}');",
            ],
            explain=f"The subquery finds the {word} {n.name} inside the category; the outer query finds which "
            "row in that category has it. The category filter is needed in both places.",
        )
    return None


def t_sub_beats_cat(ctx: Ctx) -> Spec | None:
    cands = [(t, c, v) for t in ctx.tables.values() if t.label and t.nums for c, v in ctx.categories(t)]
    if not cands:
        return None
    t, cat, vals = ctx.rng.choice(cands)
    n = ctx.rng.choice(t.nums)
    v = ctx.rng.choice(vals)
    return dict(
        question=f"List the {plural(t.name)} whose {n.name} is greater than the highest {n.name} in the "
        f"'{v}' {cat.name}. Show {t.label.name}, {cat.name} and {n.name}, sorted by {n.name} highest first, "
        f"then {t.label.name} A to Z.",
        answer=f"SELECT {t.label.name}, {cat.name}, {n.name}\nFROM {t.name}\n"
        f"WHERE {n.name} > (SELECT MAX({n.name}) FROM {t.name} WHERE {cat.name} = {lit(v)})\n"
        f"ORDER BY {n.name} DESC, {t.label.name};",
        ordered=True,
        order_note=f"{n.name} highest first, then {t.label.name}",
        hints=[
            "First find one number: the highest value inside that category. Then compare every row to it.",
            f"WHERE {n.name} > (SELECT MAX(____) FROM {t.name} WHERE ____ = '____')",
            f"WHERE {n.name} > (SELECT MAX({n.name}) FROM {t.name} WHERE {cat.name} = '{v}') ORDER BY ...",
        ],
        explain="The subquery has its own WHERE: it only looks at that category. The outer query has no "
        "category filter, so rows from any category can beat it.",
    )


def t_sub_lookup(ctx: Ctx) -> Spec | None:
    cands = [(t, c) for t in ctx.tables.values() if t.label and t.nums for c, _ in ctx.categories(t)]
    if not cands:
        return None
    t, cat = ctx.rng.choice(cands)
    n = ctx.rng.choice(t.nums)
    items = ctx.q(
        f'SELECT {t.label.name} FROM "{t.name}" x WHERE (SELECT count(*) FROM "{t.name}" y '
        f"WHERE y.{cat.name} = x.{cat.name}) >= 3 ORDER BY 1"
    )
    if not items:
        return None
    item = ctx.rng.choice(items)[0]
    if len(ctx.q(f"SELECT 1 FROM {t.name} WHERE {t.label.name} = {lit(item)}")) != 1:
        return None
    return dict(
        question=f"Find the other {plural(t.name)} in the same {cat.name} as '{item}' whose {n.name} is "
        f"above the average {n.name} of ALL {plural(t.name)}. Do not include '{item}' itself. "
        f"Show {t.label.name} and {n.name}, sorted by {t.label.name} A to Z.",
        answer=f"SELECT {t.label.name}, {n.name}\nFROM {t.name}\n"
        f"WHERE {cat.name} = (SELECT {cat.name} FROM {t.name} WHERE {t.label.name} = {lit(item)})\n"
        f"  AND {n.name} > (SELECT AVG({n.name}) FROM {t.name})\n"
        f"  AND {t.label.name} <> {lit(item)}\nORDER BY {t.label.name};",
        ordered=True,
        order_note=f"{t.label.name} A-Z",
        hints=[
            f"Two unknowns: the {cat.name} of '{item}', and the overall average. Each is its own subquery.",
            f"WHERE {cat.name} = (SELECT ____ FROM {t.name} WHERE ____ = '{item}') AND {n.name} > (SELECT AVG(____) FROM ____) AND ____ <> '{item}'",
            f"WHERE {cat.name} = (SELECT {cat.name} FROM {t.name} WHERE {t.label.name} = '{item}') AND {n.name} > (SELECT AVG({n.name}) FROM {t.name}) AND ...",
        ],
        explain="Instead of hard-coding the category, a subquery looks it up from the named row. "
        "A second subquery computes the average. <> means 'not equal'.",
    )


def _two_money(t: Table) -> tuple[Col, Col] | None:
    names = {c.name: c for c in t.nums}
    sell = next((names[k] for k in names if re.search(r"price|retail|fee|rate|sell", k)), None)
    cost = next((names[k] for k in names if re.search(r"cost|budget|wholesale", k)), None)
    if sell and cost and sell.name != cost.name:
        return sell, cost
    return None


def t_sub_profit(ctx: Ctx) -> Spec | None:
    cands = [t for t in ctx.tables.values() if t.label and _two_money(t)]
    if not cands:
        return None
    t = ctx.rng.choice(cands)
    sell, cost = _two_money(t)
    return dict(
        question=f"Profit for a {noun(t.name)} is {sell.name} minus {cost.name}. Which {plural(t.name)} make "
        f"more profit than the average profit? Show {t.label.name} labelled \"Name\" and the profit labelled "
        f"\"Profit\", highest profit first (ties: Name A to Z).",
        answer=f'SELECT {t.label.name} AS "Name", {sell.name} - {cost.name} AS "Profit"\nFROM {t.name}\n'
        f"WHERE {sell.name} - {cost.name} > (SELECT AVG({sell.name} - {cost.name}) FROM {t.name})\nORDER BY 2 DESC, 1;",
        columns=["Name", "Profit"],
        ordered=True,
        order_note="Profit highest first, then Name",
        hints=[
            "You can do maths inside SELECT, WHERE, and even inside AVG(...).",
            f"WHERE ({sell.name} - {cost.name}) > (SELECT AVG(____ - ____) FROM {t.name})",
            f"SELECT {t.label.name} AS \"Name\", {sell.name} - {cost.name} AS \"Profit\" FROM {t.name} WHERE {sell.name} - {cost.name} > (SELECT AVG({sell.name} - {cost.name}) FROM {t.name}) ORDER BY ...",
        ],
        explain="A calculated column is just an expression with a label. AVG can average an expression, "
        "so the subquery returns the average profit.",
    )


def _paths(ctx: Ctx, start: str, max_hops: int = 4) -> list[list[tuple[str, str, str, str]]]:
    """Simple FK paths from start (as undirected walks over FK edges), excluding self-references."""
    edges = [e for e in ctx.edges() if e[0] != e[2]]
    out = []
    dq = deque([(start, [], {start})])
    while dq:
        node, path, seen = dq.popleft()
        if path:
            out.append(path)
        if len(path) >= max_hops:
            continue
        for ct, cc, pt, pc in edges:
            if ct == node and pt not in seen:
                dq.append((pt, path + [(ct, cc, pt, pc)], seen | {pt}))
            elif pt == node and ct not in seen:
                dq.append((ct, path + [(ct, cc, pt, pc)], seen | {ct}))
    return out


def _join_sql(start: str, path) -> tuple[str, dict[str, str]]:
    alias = {start: "t0"}
    lines = [f"FROM {start} t0"]
    for i, (ct, cc, pt, pc) in enumerate(path, 1):
        new = pt if ct in alias else ct
        alias[new] = f"t{i}"
        lines.append(f"JOIN {new} t{i} ON {alias[ct]}.{cc} = {alias[pt]}.{pc}")
    return "\n".join(lines), alias


def t_join_two(ctx: Ctx) -> Spec | None:
    edges = [e for e in ctx.edges() if e[0] != e[2]]
    ctx.rng.shuffle(edges)
    for ct, cc, pt, pc in edges:
        c, p = ctx.tables[ct], ctx.tables[pt]
        clabel = c.label or (c if c.is_person else None)
        plabel = p.label
        if not plabel or not (c.label or c.is_person):
            continue
        cats = ctx.categories(p)
        if not cats:
            continue
        cat, vals = ctx.rng.choice(cats)
        v = ctx.rng.choice(vals)
        csel = f"c.{c.label.name}" if c.label else fullname("c", c)
        cname = c.label.name if c.label else "full name (first name, a space, last name)"
        sql = (
            f'SELECT {csel} AS "{noun(ct).title()}", p.{plabel.name} AS "{noun(pt).title()}"\n'
            f"FROM {ct} c\nJOIN {pt} p ON c.{cc} = p.{pc}\nWHERE p.{cat.name} = {lit(v)}\nORDER BY 1, 2;"
        )
        return dict(
            question=f"For every {noun(ct)} linked to a {noun(pt)} whose {cat.name} is '{v}', show the {noun(ct)}'s "
            f"{cname} labelled \"{noun(ct).title()}\" and the {noun(pt)}'s {plabel.name} labelled "
            f"\"{noun(pt).title()}\". Sort by both columns A to Z.",
            answer=sql,
            columns=[noun(ct).title(), noun(pt).title()],
            ordered=True,
            order_note="first column, then second column",
            hints=[
                f"The two tables share a column: {ct}.{cc} points to {pt}.{pc}. Join on it.",
                f"FROM {ct} c JOIN {pt} p ON c.____ = p.____ WHERE p.____ = '{v}'",
                f"SELECT ... FROM {ct} c JOIN {pt} p ON c.{cc} = p.{pc} WHERE p.{cat.name} = '{v}' ORDER BY 1, 2;",
            ],
            explain="JOIN glues each row to its matching row in the other table using the shared key. "
            "Then WHERE filters on a column from the joined table.",
        )
    return None


def t_join_chain_person(ctx: Ctx) -> Spec | None:
    people = [t for t in ctx.tables.values() if t.is_person]
    ctx.rng.shuffle(people)
    for person in people:
        paths = [p for p in _paths(ctx, person.name) if len(p) >= 2]
        ctx.rng.shuffle(paths)
        for path in paths:
            _, alias = _join_sql(person.name, path)
            end = list(alias)[-1]
            target = ctx.tables[end]
            if not target.label or target.is_person:
                continue
            joins, alias = _join_sql(person.name, path)
            a_end = alias[end]
            names = ctx.q(
                f"SELECT DISTINCT t0.{person.first.name}, t0.{person.last.name} {joins} ORDER BY 1, 2"
            )
            if not names:
                continue
            fn, ln = ctx.rng.choice(names)
            sql = (
                f'SELECT DISTINCT {a_end}.{target.label.name} AS "{label(target.label.name)}"\n{joins}\n'
                f"WHERE t0.{person.first.name} = {lit(fn)} AND t0.{person.last.name} = {lit(ln)}\nORDER BY 1;"
            )
            route = " -> ".join([person.name] + [list(alias)[i] for i in range(1, len(alias))])
            return dict(
                question=f"Follow the links {route}: which {plural(end)} are connected to {noun(person.name)} "
                f"{fn} {ln}? List each {human(target.label.name)} once, labelled "
                f"\"{label(target.label.name)}\", sorted A to Z.",
                answer=sql,
                columns=[label(target.label.name)],
                ordered=True,
                order_note=f"{target.label.name} A-Z",
                hints=[
                    f"Walk the join map one table at a time: {route}. One JOIN per step.",
                    f"FROM {person.name} t0 JOIN ____ t1 ON t0.____ = t1.____ JOIN ... WHERE t0.{person.first.name} = '{fn}' AND ...",
                    sql.split("WHERE")[0].replace(f"SELECT DISTINCT {a_end}", "SELECT DISTINCT ____") + "WHERE ...",
                ],
                explain="Each JOIN takes one step along the join map using the shared column. DISTINCT "
                "removes repeats when the same item is reached more than once.",
            )
    return None


def t_join_extreme(ctx: Ctx) -> Spec | None:
    people = [t for t in ctx.tables.values() if t.is_person]
    ctx.rng.shuffle(people)
    for person in people:
        for path in sorted(_paths(ctx, person.name), key=len, reverse=True):
            if len(path) < 2:
                continue
            joins, alias = _join_sql(person.name, path)
            end = list(alias)[-1]
            target = ctx.tables[end]
            if not target.nums or target.is_person or not target.label:
                continue
            n = ctx.rng.choice(target.nums)
            fn = ctx.rng.choice(["MIN", "MAX"])
            word = "cheapest/lowest" if fn == "MIN" else "highest"
            sql = (
                f'SELECT DISTINCT {fullname("t0", person)} AS "Name"\n{joins}\n'
                f"WHERE {alias[end]}.{n.name} = (SELECT {fn}({n.name}) FROM {end})\nORDER BY 1;"
            )
            return dict(
                question=f"Following the links {' -> '.join(alias)}, which {plural(person.name)} are connected to "
                f"the {noun(end)} with the {'lowest' if fn == 'MIN' else 'highest'} {n.name}? Show each person's full name (first name, "
                f"a space, last name) once, labelled \"Name\", sorted A to Z.",
                answer=sql,
                columns=["Name"],
                ordered=True,
                order_note="Name A-Z",
                hints=[
                    f"Two parts: a JOIN chain from {person.name} to {end}, and a subquery for the {word} {n.name}.",
                    f"... JOIN {end} ... WHERE ____.{n.name} = (SELECT {fn}(____) FROM {end})",
                    sql.split("WHERE")[0] + "WHERE ...",
                ],
                explain="The chain links people to the item; the subquery finds the extreme value; "
                "DISTINCT keeps each person once.",
            )
    return None


def t_left_never(ctx: Ctx) -> Spec | None:
    edges = [e for e in ctx.edges() if e[0] != e[2]]
    ctx.rng.shuffle(edges)
    for ct, cc, pt, pc in edges:
        p = ctx.tables[pt]
        lab = p.label.name if p.label else None
        if not lab and not p.is_person:
            continue
        sel = f"p.{lab}" if lab else fullname("p", p)
        rows = ctx.q(f"SELECT {sel} FROM {pt} p LEFT JOIN {ct} c ON p.{pc} = c.{cc} WHERE c.{cc} IS NULL")
        if not (1 <= len(rows) < p.rows):
            continue
        what = lab or "full name (first name, a space, last name)"
        return dict(
            question=f"Which {plural(pt)} never appear in the {ct} table? Show their {what} labelled \"{noun(pt).title()}\", "
            f"sorted A to Z.",
            answer=f'SELECT {sel} AS "{noun(pt).title()}"\nFROM {pt} p\nLEFT JOIN {ct} c ON p.{pc} = c.{cc}\n'
            f"WHERE c.{cc} IS NULL\nORDER BY 1;",
            columns=[noun(pt).title()],
            ordered=True,
            order_note="A-Z",
            hints=[
                "'Never' means no matching row. LEFT JOIN keeps unmatched rows and fills the other side with NULL.",
                f"FROM {pt} p LEFT JOIN {ct} c ON p.{pc} = c.{cc} WHERE c.____ IS NULL",
                f"SELECT ... FROM {pt} p LEFT JOIN {ct} c ON p.{pc} = c.{cc} WHERE c.{cc} IS NULL ORDER BY 1;",
            ],
            explain="LEFT JOIN keeps every row from the left table. Rows with no match get NULLs on the right, "
            "and IS NULL picks exactly those.",
        )
    return None


def _self_refs(ctx: Ctx) -> list[tuple[Table, Col, str]]:
    out = []
    for t in ctx.tables.values():
        for c in t.cols:
            if c.fk and c.fk.split(".")[0] == t.name and (t.is_person or t.label):
                out.append((t, c, c.fk.split(".")[1]))
    return out


def t_self_referrers(ctx: Ctx) -> Spec | None:
    refs = _self_refs(ctx)
    if not refs:
        return None
    t, c, pk = ctx.rng.choice(refs)
    sel = fullname("a", t) if t.is_person else f"a.{t.label.name}"
    return dict(
        question=f"Which {plural(t.name)} appear as the {human(c.name) + ('' if human(c.name) == c.name else f' ({c.name})')} of at least one other {noun(t.name)}? Show each one once: "
        f"the {pk} labelled \"Number\" and the {'full name (first name, a space, last name)' if t.is_person else t.label.name} "
        f"labelled \"Name\", sorted by Number.",
        answer=f'SELECT DISTINCT a.{pk} AS "Number", {sel} AS "Name"\nFROM {t.name} a\n'
        f"JOIN {t.name} b ON a.{pk} = b.{c.name}\nORDER BY 1;",
        columns=["Number", "Name"],
        ordered=True,
        order_note="Number ascending",
        hints=[
            f"{t.name}.{c.name} points back to the same table. Join {t.name} to itself with two nicknames.",
            f"FROM {t.name} a JOIN {t.name} b ON a.____ = b.____",
            f"SELECT DISTINCT a.{pk} AS \"Number\", ... FROM {t.name} a JOIN {t.name} b ON a.{pk} = b.{c.name} ORDER BY 1;",
        ],
        explain="A self-join treats one table as two copies. b is the row doing the pointing, a is the row "
        "being pointed to. DISTINCT keeps each a once even if several b rows point to it.",
    )


def t_self_pairs(ctx: Ctx) -> Spec | None:
    refs = [r for r in _self_refs(ctx) if r[0].is_person]
    if not refs:
        return None
    t, c, pk = ctx.rng.choice(refs)
    return dict(
        question=f"For every {noun(t.name)} that has a {c.name}, show their full name labelled \"Person\" and the "
        f"full name of the {noun(t.name)} their {c.name} points to, labelled \"{label(c.name)}\". "
        f"Full names are first name, a space, last name. Sort by Person A to Z.",
        answer=f'SELECT {fullname("a", t)} AS "Person", {fullname("b", t)} AS "{label(c.name)}"\n'
        f"FROM {t.name} a\nJOIN {t.name} b ON a.{c.name} = b.{pk}\nORDER BY 1, 2;",
        columns=["Person", label(c.name)],
        ordered=True,
        order_note="Person A-Z",
        hints=[
            "Use two copies of the same table: one for the person, one for who they point to.",
            f"FROM {t.name} a JOIN {t.name} b ON a.{c.name} = b.____",
            f"SELECT CONCAT(a.{t.first.name}, ' ', a.{t.last.name}) AS \"Person\", CONCAT(b...) ... FROM {t.name} a JOIN {t.name} b ON a.{c.name} = b.{pk} ORDER BY 1, 2;",
        ],
        explain="a.{c} = b.{pk} links each person to the row their column points to. People with no value "
        "(NULL) drop out because an inner JOIN needs a match.".replace("{c}", c.name).replace("{pk}", pk),
    )


def t_group_count(ctx: Ctx) -> Spec | None:
    cands = [(t, c) for t in ctx.tables.values() for c, _ in ctx.categories(t)]
    if not cands:
        return None
    t, cat = ctx.rng.choice(cands)
    return dict(
        question=f"How many {plural(t.name)} are there in each {cat.name}? Show the {cat.name} labelled "
        f"\"{label(cat.name)}\" and the count labelled \"How Many\", sorted by {cat.name} A to Z.",
        answer=f'SELECT {cat.name} AS "{label(cat.name)}", COUNT(*) AS "How Many"\nFROM {t.name}\n'
        f"GROUP BY {cat.name}\nORDER BY 1;",
        columns=[label(cat.name), "How Many"],
        ordered=True,
        order_note=f"{cat.name} A-Z",
        hints=[
            "GROUP BY makes one pile per distinct value, then COUNT squashes each pile separately.",
            f"SELECT ____, COUNT(*) FROM {t.name} GROUP BY ____ ORDER BY 1;",
            f"SELECT {cat.name} AS \"{label(cat.name)}\", COUNT(*) AS \"How Many\" FROM {t.name} GROUP BY ... ORDER BY 1;",
        ],
        explain="Without GROUP BY, COUNT gives one number for the whole table. GROUP BY splits rows into "
        "groups first, so you get one row per group. Non-aggregated columns in SELECT must be in GROUP BY.",
    )


def t_group_having(ctx: Ctx) -> Spec | None:
    cands = [(t, c) for t in ctx.tables.values() if t.nums for c, _ in ctx.categories(t)]
    if not cands:
        return None
    t, cat = ctx.rng.choice(cands)
    n = ctx.rng.choice(t.nums)
    return dict(
        question=f"For each {cat.name} that has at least 2 {plural(t.name)}, show the {cat.name} labelled "
        f"\"{label(cat.name)}\" and the average {n.name} rounded to 2 decimals labelled \"Average\". "
        f"Sort by Average, highest first (ties: {cat.name} A to Z).",
        answer=f'SELECT {cat.name} AS "{label(cat.name)}", ROUND(AVG({n.name}), 2) AS "Average"\nFROM {t.name}\n'
        f"GROUP BY {cat.name}\nHAVING COUNT(*) >= 2\nORDER BY 2 DESC, 1;",
        columns=[label(cat.name), "Average"],
        ordered=True,
        order_note="Average highest first",
        hints=[
            "WHERE filters rows before grouping; HAVING filters whole groups after grouping.",
            f"... GROUP BY {cat.name} HAVING COUNT(*) >= ____ ORDER BY ____ DESC, ____;",
            f"SELECT {cat.name} AS \"{label(cat.name)}\", ROUND(AVG({n.name}), 2) AS \"Average\" FROM {t.name} GROUP BY {cat.name} HAVING ... ORDER BY 2 DESC, 1;",
        ],
        explain="GROUP BY makes one group per category; HAVING drops groups that are too small. "
        "You can't use COUNT(*) in WHERE because WHERE runs before the groups exist.",
    )


def t_group_join(ctx: Ctx) -> Spec | None:
    edges = [e for e in ctx.edges() if e[0] != e[2]]
    ctx.rng.shuffle(edges)
    for ct, cc, pt, pc in edges:
        p = ctx.tables[pt]
        if not p.label:
            continue
        counts = ctx.q(f"SELECT count(*) FROM {ct} GROUP BY {cc} HAVING count(*) >= 2")
        if not counts:
            continue
        return dict(
            question=f"Which {plural(pt)} appear in the {ct} table at least twice? Show the {noun(pt)}'s {p.label.name} "
            f"labelled \"{noun(pt).title()}\" and how many times labelled \"Times\". Sort by Times highest first, "
            f"then {noun(pt).title()} A to Z.",
            answer=f'SELECT p.{p.label.name} AS "{noun(pt).title()}", COUNT(*) AS "Times"\nFROM {pt} p\n'
            f"JOIN {ct} c ON p.{pc} = c.{cc}\nGROUP BY p.{pc}, p.{p.label.name}\nHAVING COUNT(*) >= 2\nORDER BY 2 DESC, 1;",
            columns=[noun(pt).title(), "Times"],
            ordered=True,
            order_note="Times highest first, then name",
            hints=[
                "Join first, then GROUP BY the thing you're counting per, then HAVING to keep groups of 2+.",
                f"FROM {pt} p JOIN {ct} c ON p.{pc} = c.{cc} GROUP BY p.____, p.____ HAVING COUNT(*) >= 2",
                f"SELECT p.{p.label.name} AS \"{noun(pt).title()}\", COUNT(*) AS \"Times\" FROM {pt} p JOIN {ct} c ON p.{pc} = c.{cc} GROUP BY ... HAVING COUNT(*) >= 2 ORDER BY 2 DESC, 1;",
            ],
            explain="The JOIN creates one row per appearance; GROUP BY collects them per item; COUNT counts "
            "each pile; HAVING keeps piles of 2 or more.",
        )
    return None


TEMPLATES: dict[tuple[str, int], list[Callable[[Ctx], Spec | None]]] = {
    ("select", 2): [t_select_filter],
    ("select", 3): [t_select_in],
    ("shape", 2): [t_shape_distinct],
    ("shape", 3): [t_shape_people, t_shape_distinct],
    ("aggregates", 2): [t_agg_minmax],
    ("aggregates", 3): [t_agg_avg, t_agg_minmax],
    ("subqueries", 2): [t_sub_beats_cat],
    ("subqueries", 3): [t_sub_above_avg, t_sub_max_in_cat],
    ("subqueries", 4): [t_sub_lookup, t_sub_beats_cat],
    ("subqueries", 5): [t_sub_profit],
    ("joins", 3): [t_join_two],
    ("joins", 4): [t_join_chain_person],
    ("joins", 5): [t_join_extreme],
    ("selfleft", 3): [t_left_never, t_self_referrers],
    ("selfleft", 4): [t_self_pairs],
    ("groupby", 3): [t_group_count],
    ("groupby", 4): [t_group_having],
    ("groupby", 5): [t_group_join],
}


def _nearest_keys(topic: str, difficulty: int) -> list[tuple[str, int]]:
    keys = [k for k in TEMPLATES if k[0] == topic]
    return sorted(keys, key=lambda k: (abs(k[1] - difficulty), -k[1]))


def validate_spec(db: Database, world: str, lv: Level) -> str | None:
    """Return a problem description, or None if the level is usable."""
    res = sandbox.run(db, world, lv.answer)
    if not res.ok:
        return f"answer fails: {res.error.message}"
    if not (1 <= len(res.rows) <= MAX_ROWS):
        return f"answer returns {len(res.rows)} rows"
    if lv.columns and lv.columns != res.columns:
        return "labels mismatch"
    if lv.ordered:
        keys = grader._order_keys(lv.answer, res.columns)
        if keys is None:
            return "sort keys not mappable"
        rows = grader.norm_rows(res.rows)
        ks = [tuple(r[i] for i, _ in keys) for r in rows]
        if len(set(ks)) != len(ks):
            return "ties on sort keys"
    return None


def generate(
    db: Database, world: str, topic: str, difficulty: int, avoid: set[str] | None = None, tries: int = 25,
    seed: int | None = None,
) -> Level | None:
    avoid = avoid or set()
    ctx = build_ctx(db, world, seed)
    for key in _nearest_keys(topic, difficulty):
        for _ in range(tries):
            fn = ctx.rng.choice(TEMPLATES[key])
            try:
                spec = fn(ctx)
            except (KeyError, IndexError, ValueError, AttributeError, TypeError):
                spec = None
            if not spec:
                continue
            lv = Level(
                id=level_id(world, "generated", spec["question"], spec["answer"]),
                world=world,
                topic=key[0],
                difficulty=key[1],
                question=spec["question"],
                answer=spec["answer"],
                columns=spec.get("columns"),
                ordered=spec.get("ordered", False),
                order_note=spec.get("order_note", ""),
                hints=spec["hints"],
                explain=spec["explain"],
                source="generated",
            )
            if lv.id in avoid:
                continue
            if validate_spec(db, world, lv) is None:
                return lv
    return None
