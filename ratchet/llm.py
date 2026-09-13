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

# One lock per cache key, so concurrent callers asking the identical question
# wait for the first answer instead of each buying their own.
#
# Without this the pool stampedes a cold cache: six workers miss the same key at
# the same instant, six real calls go out, and — because the model is not
# deterministic — six *different* answers come back. One wins the write and the
# other five are used anyway by the threads that made them. That was observed,
# not theorised: the same rule ended up graded by a regex on one brief and by an
# LLM rubric on another, inside a single run. A measuring instrument that varies
# with thread scheduling is the rubber ruler CLAUDE.md is about.
_KEY_LOCKS: dict[str, threading.Lock] = {}


def _key_lock(key: str) -> threading.Lock:
    with _LOCK:
        return _KEY_LOCKS.setdefault(key, threading.Lock())


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
    key = _key(prompt, model, backend)
    path = CACHE / f"{key}.txt"

    if path.exists():
        _bump("hits")
        return path.read_text()

    with _key_lock(key):
        # Someone else may have answered this exact question while we waited.
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


def _first_json_value(raw: str) -> str | None:
    """The first complete JSON object or array in `raw`, brace-matched.

    The obvious version — find('[') paired with rfind(']'), then the same for
    braces — silently returns the wrong value for the most ordinary response
    there is:

        {"kind": "llm_rubric", "steps": ["a", "b"], "rationale": "..."}

    find('[') lands on the *steps* array and rfind(']') on its closer, so the
    caller gets `["a", "b"]` and never sees the object that contained it. Four
    fields vanish and the parse looks like it succeeded. That is how every
    generated grader that needed evaluation steps came back empty.

    So: scan from the first opener to its own matching closer, tracking string
    literals and escapes so a brace inside a regex pattern cannot end the value.
    """
    starts = [i for i in (raw.find("{"), raw.find("[")) if i != -1]
    if not starts:
        return None
    i = min(starts)
    opener = raw[i]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for j in range(i, len(raw)):
        ch = raw[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return raw[i : j + 1]
    return None


def complete_json(prompt: str, **kw: Any) -> Any:
    """Completion parsed as JSON. Returns None if the model produced no valid JSON.

    Callers must treat None as a failed extraction and count it, not silently
    skip it — a run with failed parses is a different thing from a clean run.
    """
    raw = _FENCE.sub("", complete(prompt, **kw).strip()).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    span = _first_json_value(raw)
    if span is None:
        return None
    try:
        return json.loads(span)
    except json.JSONDecodeError:
        return None
