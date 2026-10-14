"""psql-style plain-text table formatting."""

from __future__ import annotations

from unicodedata import east_asian_width


def _w(s: str) -> int:
    return sum(2 if east_asian_width(c) in "WF" else 1 for c in s)


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}" if abs(v) < 1e15 else str(v)
    return str(v)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def psql_table(columns: list[str], rows: list, truncated: bool = False,
               numeric: list[bool] | None = None) -> str:
    """Render like psql's aligned output, including the (n rows) footer.

    rows may hold raw values or pre-formatted strings (pass `numeric` then).
    """
    cells = [[_cell(v) for v in r] for r in rows]
    widths = [_w(c) for c in columns]
    for r in cells:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], _w(c))
    out = []
    head = []
    for i, c in enumerate(columns):
        pad = widths[i] - _w(c)
        left = pad // 2
        head.append(" " * left + c + " " * (pad - left))
    out.append(" " + " | ".join(head))
    out.append("-" + "-+-".join("-" * w for w in widths) + "-")
    for raw, r in zip(rows, cells):
        parts = []
        for i, c in enumerate(r):
            pad = " " * (widths[i] - _w(c))
            right = numeric[i] if numeric is not None else _is_num(raw[i])
            parts.append(pad + c if right else c + pad)
        out.append(" " + " | ".join(parts).rstrip() if parts else "")
    n = len(rows)
    footer = f"({n} row{'s' if n != 1 else ''}"
    footer += ", showing first 500)" if truncated else ")"
    out.append(footer)
    return "\n".join(out)
