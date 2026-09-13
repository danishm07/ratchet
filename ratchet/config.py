"""Single place that reads the environment. Nothing else touches os.environ."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
RUNS = DATA / "runs"
FIXTURES = ROOT / "fixtures"

for _d in (DATA, CACHE, RUNS):
    _d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    """Minimal .env loader; avoids a dependency for six variables."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    # model backend: "cli" (claude code) or "openrouter"
    backend: str = os.environ.get("RATCHET_BACKEND", "cli")
    openrouter_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    model: str = os.environ.get("RATCHET_MODEL", "anthropic/claude-sonnet-4.5")

    slack_token: str = os.environ.get("SLACK_BOT_TOKEN", "")
    slack_channel: str = os.environ.get("SLACK_CHANNEL_ID", "")
    linear_key: str = os.environ.get("LINEAR_API_KEY", "")
    github_token: str = os.environ.get("GITHUB_TOKEN", "")
    github_repo: str = os.environ.get("GITHUB_REPO", "")

    def missing(self) -> list[str]:
        need = {
            "SLACK_BOT_TOKEN": self.slack_token,
            "SLACK_CHANNEL_ID": self.slack_channel,
            "LINEAR_API_KEY": self.linear_key,
            "GITHUB_TOKEN": self.github_token,
            "GITHUB_REPO": self.github_repo,
        }
        return [k for k, v in need.items() if not v]


settings = Settings()
