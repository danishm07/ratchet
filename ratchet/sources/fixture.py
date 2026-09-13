"""Offline source, for development and CI.

Reads the same synthetic items that seed.py posts into the real Slack, Linear
and GitHub accounts, so the pipeline can be exercised end to end without
network access. `--source fixture` is a development convenience; the submitted
demo runs against the live APIs.
"""

from __future__ import annotations

import json

from ..config import FIXTURES
from .base import SourceItem


def fetch(app: str | None = None) -> list[SourceItem]:
    rows = json.loads((FIXTURES / "seed_items.json").read_text())
    items = [SourceItem(**r) for r in rows]
    return [i for i in items if app is None or i.app == app]
