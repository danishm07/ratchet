"""SourceItem: the only thing an adapter is allowed to return.

Adapters do I/O and nothing else — no LLM calls, no interpretation. That keeps
every source swappable without touching extraction, judging or reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class SourceItem:
    app: str          # "slack" | "linear" | "github"
    kind: str         # "message" | "issue" | "commit" | "review_comment"
    external_id: str
    author: str
    created_at: str
    text: str
    url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceError(RuntimeError):
    """Raised with the app name and enough of the response to debug it."""
