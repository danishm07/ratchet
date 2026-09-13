"""Post the synthetic corpus into the real Slack, Linear and GitHub accounts.

The content is invented; the accounts and API calls are real. Run once at setup:

    python -m ratchet.seed
"""

from __future__ import annotations

import json
import sys

import httpx

from .config import FIXTURES, settings
from .sources.base import SourceError

ITEMS = json.loads((FIXTURES / "seed_items.json").read_text())


def seed_slack() -> int:
    n = 0
    for it in [i for i in ITEMS if i["app"] == "slack"]:
        r = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.slack_token}"},
            json={"channel": settings.slack_channel, "text": f"{it['text']}"},
            timeout=30,
        )
        body = r.json()
        if not body.get("ok"):
            raise SourceError(f"slack post: {body.get('error')}")
        n += 1
    return n


def _linear_team_id() -> str:
    r = httpx.post(
        "https://api.linear.app/graphql",
        headers={"Authorization": settings.linear_key},
        json={"query": "{ teams(first: 1) { nodes { id } } }"},
        timeout=30,
    )
    nodes = r.json()["data"]["teams"]["nodes"]
    if not nodes:
        raise SourceError("linear: no team found — create one in the app first")
    return nodes[0]["id"]


def seed_linear() -> int:
    team = _linear_team_id()
    mutation = """
    mutation Create($t: String!, $d: String!, $team: String!) {
      issueCreate(input: {title: $t, description: $d, teamId: $team}) { success }
    }"""
    n = 0
    for it in [i for i in ITEMS if i["app"] == "linear"]:
        title, _, desc = it["text"].partition("\n\n")
        r = httpx.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": settings.linear_key},
            json={"query": mutation, "variables": {"t": title, "d": desc, "team": team}},
            timeout=30,
        )
        body = r.json()
        if "errors" in body:
            raise SourceError(f"linear create: {body['errors'][:1]}")
        n += 1
    return n


def seed_github() -> int:
    """Each commit message becomes a real commit by writing a small log file."""
    import base64
    n = 0
    for it in [i for i in ITEMS if i["app"] == "github" and i["kind"] == "commit"]:
        path = f"changelog/{it['external_id']}.md"
        r = httpx.put(
            f"https://api.github.com/repos/{settings.github_repo}/contents/{path}",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "message": it["text"],
                "content": base64.b64encode(it["text"].encode()).decode(),
            },
            timeout=30,
        )
        if r.status_code not in (200, 201):
            raise SourceError(f"github put {path}: {r.status_code} {r.text[:200]}")
        n += 1
    return n


def main() -> None:
    missing = settings.missing()
    if missing:
        print("missing env: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(1)
    print(f"slack:  posted {seed_slack()} messages")
    print(f"linear: created {seed_linear()} issues")
    print(f"github: created {seed_github()} commits")
    print("\nnote: the GitHub review comment must be added by hand on any PR,")
    print("or it will simply be absent from the corpus — which the run reports.")


if __name__ == "__main__":
    main()
