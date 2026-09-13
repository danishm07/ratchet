"""The Case: a test derived from something a human already said or did."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from typing import Any

from .config import DATA


@dataclass
class Case:
    id: str
    rule: str                  # key into judge.GRADERS
    title: str
    expectation: str
    brief_id: str
    grader: str                # "deterministic" | "llm"
    source_app: str
    source_id: str
    source_text: str           # the human words this came from
    source_author: str = ""    # who wrote them
    source_url: str = ""
    derived_from_fix: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PATH = DATA / "cases.json"


def save(cases: list[Case]) -> None:
    PATH.write_text(json.dumps([c.to_dict() for c in cases], indent=2))


def load() -> list[Case]:
    if not PATH.exists():
        return []
    return [Case(**c) for c in json.loads(PATH.read_text())]
