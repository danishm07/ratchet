"""GitHub adapter — reads commits and pull-request review comments.

GitHub carries the strongest signal of the three. A fix is a complaint with the
answer already attached: at the moment of the fix the author knows what the
input was, what came out, why it was wrong and what right looks like — and it is
exactly the moment nobody writes a test, because they are relieved and moving on.
"""

from __future__ import annotations

import httpx

from ..config import settings
from .base import SourceItem, SourceError

API = "https://api.github.com"


def _get(path: str, params: dict | None = None) -> list[dict]:
    resp = httpx.get(
        f"{API}{path}",
        params=params or {},
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise SourceError(f"github {path}: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.json()


def fetch(limit: int = 40) -> list[SourceItem]:
    if not settings.github_token or not settings.github_repo:
        raise SourceError("github: GITHUB_TOKEN or GITHUB_REPO missing")
    repo = settings.github_repo
    items: list[SourceItem] = []

    for c in _get(f"/repos/{repo}/commits", {"per_page": limit}):
        msg = (c.get("commit") or {}).get("message", "")
        if not msg:
            continue
        items.append(
            SourceItem(
                app="github",
                kind="commit",
                external_id=c["sha"][:9],
                author=((c.get("commit") or {}).get("author") or {}).get("name", "unknown"),
                created_at=((c.get("commit") or {}).get("author") or {}).get("date", ""),
                text=msg,
                url=c.get("html_url", ""),
                meta={"is_fix": msg.lower().startswith(("fix", "bug"))},
            )
        )

    try:
        for rc in _get(f"/repos/{repo}/pulls/comments", {"per_page": limit}):
            items.append(
                SourceItem(
                    app="github",
                    kind="review_comment",
                    external_id=str(rc["id"]),
                    author=(rc.get("user") or {}).get("login", "unknown"),
                    created_at=rc.get("created_at", ""),
                    text=rc.get("body", ""),
                    url=rc.get("html_url", ""),
                    meta={"path": rc.get("path", "")},
                )
            )
    except SourceError:
        pass  # a repo with no PRs is fine; commits alone still carry fixes

    return [i for i in items if i.text.strip()]
