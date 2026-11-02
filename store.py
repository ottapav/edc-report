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
import time
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


# ---------------------------------------------------------------------------
# Files prepared for download (the summary export)
# ---------------------------------------------------------------------------

#: a prepared file can be fetched for this long, and at most this many are kept
FILE_TTL_S = 600
FILE_MAX = 20


@dataclass
class File:
    name: str
    content: bytes
    created: float


_FILES: "OrderedDict[str, File]" = OrderedDict()


def put_file(name: str, content: bytes) -> str:
    """Keep a file for download; return its token. The browser fetches it as an ordinary
    link (see ``/export/<token>/<name>`` in app.py), so every browser saves it under its
    name, with the extension; a blob download lost the name on Safari and on phones."""
    token = uuid.uuid4().hex
    now = time.monotonic()
    with _LOCK:
        _FILES[token] = File(name, content, now)
        while _FILES and (len(_FILES) > FILE_MAX
                          or now - next(iter(_FILES.values())).created > FILE_TTL_S):
            _FILES.popitem(last=False)
    return token


def get_file(token: str) -> File | None:
    """The prepared file of ``token``, or None when unknown or expired. It stays available
    until it expires: some browsers fetch a download twice."""
    with _LOCK:
        f = _FILES.get(token)
        if f is None or time.monotonic() - f.created > FILE_TTL_S:
            return None
        return f
