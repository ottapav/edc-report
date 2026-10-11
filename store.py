"""In-memory store of the uploaded reports and of what was computed for them.

Each upload gets a random key that the browser keeps; the store holds the newest
``config.CACHE_MAX`` reports and drops the oldest.

ONE PROCESS ONLY. Everything a browser session refers to - its upload, the key estimate,
a running computation and its progress - lives in this process's memory, so every request
of that session must reach this same process. gunicorn runs a single worker with threads
(``gunicorn.conf.py`` pins that). With several workers a request lands in a process that
does not know the upload or the job; that would need a shared store such as Redis, not
more workers.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass

import config
from billing import BillResult
from edc_data import SharingData
from keyfit import KeyFit
from recompute import Recomputed


@dataclass
class Entry:
    """One uploaded report and its results."""

    filename: str
    data: SharingData
    fit: KeyFit | None = None             # allocation keys estimated from the report
    exact: Recomputed | None = None       # recompute with the exact static method
    bill: BillResult | None = None        # billing by the Shapley value


_ENTRIES: "OrderedDict[str, Entry]" = OrderedDict()
_LOCK = threading.Lock()


def put(filename: str, data: SharingData) -> str:
    """Store a parsed upload; return its key. Evicts the oldest beyond CACHE_MAX (their
    running jobs notice and stop, see :func:`jobs.start`)."""
    key = uuid.uuid4().hex
    with _LOCK:
        _ENTRIES[key] = Entry(filename, data)
        while len(_ENTRIES) > config.CACHE_MAX:
            _ENTRIES.popitem(last=False)
    return key


def get(key: str | None) -> Entry | None:
    """The upload of ``key`` (and mark it recently used), or None."""
    if not key:
        return None
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is not None:
            _ENTRIES.move_to_end(key)
        return entry


def contains(key: str | None) -> bool:
    with _LOCK:
        return bool(key) and key in _ENTRIES


def drop(key: str | None) -> None:
    """Forget an upload (its browser replaced it); its running jobs stop."""
    if key:
        with _LOCK:
            _ENTRIES.pop(key, None)


def size() -> int:
    with _LOCK:
        return len(_ENTRIES)
