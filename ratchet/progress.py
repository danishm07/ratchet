"""Progress lines on stderr, so a long run says what it is doing.

Everything here is presentation and none of it computes anything. stdout carries
the result — the counts, the matrix, the path to the report — so progress goes to
stderr and `python -m ratchet run > out.txt` still writes exactly what it wrote
before.

In-place updates need a terminal. When stderr is redirected the carriage returns
would just pile up in the file, so a non-tty gets the per-stage summary lines and
none of the twitching.
"""

from __future__ import annotations

import sys
import time
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")

_width = 0


def _tty() -> bool:
    return bool(getattr(sys.stderr, "isatty", lambda: False)())


def _draw(line: str) -> None:
    """Redraw the current line in place, padded over whatever was longer before."""
    global _width
    if not _tty():
        return
    _width = max(_width, len(line))
    print("\r" + line.ljust(_width), end="", file=sys.stderr, flush=True)


def _clear() -> None:
    global _width
    if _width and _tty():
        print("\r" + " " * _width + "\r", end="", file=sys.stderr, flush=True)
    _width = 0


def note(line: str) -> None:
    """One finished-stage summary, on its own line, after clearing any in-place one."""
    _clear()
    print(line, file=sys.stderr, flush=True)


def track(items: Iterable[T], total: int, label: str, noun: str,
          done: str | None = None) -> Iterator[T]:
    """Yield from `items`, drawing `label: n/total noun` in place as they arrive.

    Wraps the iterator rather than the work, so callers keep their existing loop
    and nothing about the order or the results changes.
    """
    t0 = time.time()
    n = 0
    try:
        for item in items:
            n += 1
            _draw(f"{label}: {n}/{total} {noun}")
            yield item
    finally:
        # Clear first either way: on the happy path the summary replaces the
        # counter, and on an exception a traceback should not land glued to it.
        _clear()
    note(f"{done or label}: {n} {noun} in {time.time() - t0:.1f}s")
