"""Level model and topic definitions."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

TOPICS: dict[str, str] = {
    "select": "SELECT / WHERE",
    "shape": "AS, CONCAT, ORDER BY, DISTINCT",
    "aggregates": "MAX / MIN / AVG / COUNT",
    "subqueries": "Subqueries",
    "joins": "JOINs",
    "selfleft": "Self-join & LEFT JOIN",
    "groupby": "GROUP BY / HAVING",
}
CORE_TOPICS = ["select", "shape", "aggregates", "subqueries", "joins", "selfleft"]
BONUS_TOPIC = "groupby"
MIN_DIFFICULTY, MAX_DIFFICULTY, START_DIFFICULTY = 1, 5, 3


@dataclass
class Level:
    id: str
    world: str
    topic: str
    difficulty: int
    question: str
    answer: str
    columns: list[str] | None = None
    ordered: bool = False
    order_note: str = ""
    hints: list[str] = field(default_factory=list)
    explain: str = ""
    source: str = "builtin"

    @property
    def points(self) -> int:
        return 5 * self.difficulty

    def to_dict(self) -> dict:
        return asdict(self)

    def public_dict(self) -> dict:
        """What a front end may show before the player gives up."""
        d = self.to_dict()
        d.pop("answer")
        d.pop("explain")
        d.pop("hints")
        d["hint_count"] = len(self.hints)
        d["topic_name"] = TOPICS.get(self.topic, self.topic)
        d["points"] = self.points
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Level":
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in d.items() if k in known}
        if data.get("columns") == []:
            data["columns"] = None
        data["difficulty"] = int(data["difficulty"])
        return cls(**data)


def level_id(world: str, source: str, question: str, answer: str) -> str:
    h = hashlib.sha1(f"{question}\n{answer}".encode()).hexdigest()[:10]
    return f"{world}-{source[:3]}-{h}"
