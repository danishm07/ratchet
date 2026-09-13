"""Slack adapter — reads channel history.

Slack carries the informal complaints. They are the majority of real failure
reports and the ones that never get filed anywhere, which is precisely why they
never become tests.
"""

from __future__ import annotations

import httpx

from ..config import settings
from .base import SourceItem, SourceError

API = "https://slack.com/api"


def _get(method: str, params: dict) -> dict:
    resp = httpx.get(
        f"{API}/{method}",
        params=params,
        headers={"Authorization": f"Bearer {settings.slack_token}"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise SourceError(f"slack {method}: HTTP {resp.status_code} {resp.text[:200]}")
    body = resp.json()
    if not body.get("ok"):
        raise SourceError(f"slack {method}: {body.get('error')} — check scopes and that the bot is in the channel")
    return body


def fetch(limit: int = 60) -> list[SourceItem]:
    if not settings.slack_token or not settings.slack_channel:
        raise SourceError("slack: SLACK_BOT_TOKEN or SLACK_CHANNEL_ID missing")

    body = _get("conversations.history", {"channel": settings.slack_channel, "limit": limit})
    users: dict[str, str] = {}

    def name(uid: str) -> str:
        if uid not in users:
            try:
                users[uid] = _get("users.info", {"user": uid})["user"]["name"]
            except SourceError:
                users[uid] = uid
        return users[uid]

    items: list[SourceItem] = []
    for m in body.get("messages", []):
        if m.get("subtype") or not m.get("text"):
            continue
        items.append(
            SourceItem(
                app="slack",
                kind="message",
                external_id=m["ts"],
                author=name(m.get("user", "?")),
                created_at=m["ts"],
                text=m["text"],
                url=f"slack://channel/{settings.slack_channel}/{m['ts']}",
                meta={"channel": settings.slack_channel},
            )
        )
    return items
