"""Model access with two interchangeable backends and a disk cache.

Backends
--------
cli          shells out to `claude -p` (no API key needed)
openrouter   POSTs to OpenRouter, so any model can be swapped in via RATCHET_MODEL

Every call is cached on disk keyed by a hash of (backend, model, prompt). The
suite therefore replays offline, deterministically, in seconds and for free.
That is not an optimisation: iterating on a judge is only possible if re-running
the suite is cheap, and a frozen environment is what makes an eval reproducible
by someone else.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from typing import Any

import httpx

from .config import CACHE, settings

_LOCK = threading.Lock()
_STATS = {"hits": 0, "misses": 0, "errors": 0}


def stats() -> dict[str, int]:
    with _LOCK:
        return dict(_STATS)


def _bump(key: str) -> None:
    with _LOCK:
        _STATS[key] += 1


def _key(prompt: str, model: str, backend: str) -> str:
    raw = f"{backend}\x00{model}\x00{prompt}".encode()
    return hashlib.sha256(raw).hexdigest()[:40]


def _call_cli(prompt: str) -> str:
    proc = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude cli exited {proc.returncode}: {proc.stderr[:300]}")
    return proc.stdout.strip()


def _call_openrouter(prompt: str, model: str) -> str:
    if not settings.openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set but backend is 'openrouter'")
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openrouter_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"openrouter: {resp.status_code} {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"].strip()


def complete(prompt: str, *, model: str | None = None, backend: str | None = None) -> str:
    """One cached completion. Raises with context on failure — never returns junk."""
    backend = backend or settings.backend
    model = model or settings.model
    path = CACHE / f"{_key(prompt, model, backend)}.txt"

    if path.exists():
        _bump("hits")
        return path.read_text()

    _bump("misses")
    try:
        out = _call_cli(prompt) if backend == "cli" else _call_openrouter(prompt, model)
    except Exception:
        _bump("errors")
        raise
    path.write_text(out)
    return out


_FENCE = re.compile(r"^```(?:json)?|```$", re.M)


def complete_json(prompt: str, **kw: Any) -> Any:
    """Completion parsed as JSON. Returns None if the model produced no valid JSON.

    Callers must treat None as a failed extraction and count it, not silently
    skip it — a run with failed parses is a different thing from a clean run.
    """
    raw = _FENCE.sub("", complete(prompt, **kw).strip()).strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = raw.find(opener), raw.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(raw[i : j + 1])
            except json.JSONDecodeError:
                continue
    return None
