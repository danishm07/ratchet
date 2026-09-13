"""Linear adapter — reads issues.

Linear carries bug reports with reproduction steps, which convert into the
highest-fidelity cases because the reporter already did the work of isolating
the failure.
"""

from __future__ import annotations

import httpx

from ..config import settings
from .base import SourceItem, SourceError

API = "https://api.linear.app/graphql"

QUERY = """
query Issues($n: Int!) {
  issues(first: $n, orderBy: updatedAt) {
    nodes {
      id identifier title description url createdAt
      creator { name }
      labels { nodes { name } }
      state { name }
    }
  }
}
"""


def fetch(limit: int = 40) -> list[SourceItem]:
    if not settings.linear_key:
        raise SourceError("linear: LINEAR_API_KEY missing")

    resp = httpx.post(
        API,
        headers={"Authorization": settings.linear_key, "Content-Type": "application/json"},
        json={"query": QUERY, "variables": {"n": limit}},
        timeout=30,
    )
    if resp.status_code != 200:
        raise SourceError(f"linear: HTTP {resp.status_code} {resp.text[:200]}")
    body = resp.json()
    if "errors" in body:
        raise SourceError(f"linear: {body['errors'][:1]}")

    items: list[SourceItem] = []
    for n in body["data"]["issues"]["nodes"]:
        text = n["title"] + (("\n\n" + n["description"]) if n.get("description") else "")
        items.append(
            SourceItem(
                app="linear",
                kind="issue",
                external_id=n["identifier"],
                author=(n.get("creator") or {}).get("name", "unknown"),
                created_at=n["createdAt"],
                text=text,
                url=n["url"],
                meta={
                    "state": (n.get("state") or {}).get("name", ""),
                    "labels": [l["name"] for l in (n.get("labels") or {}).get("nodes", [])],
                },
            )
        )
    return items
