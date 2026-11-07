"""In-memory store of the uploaded reports and of what was computed for them.

Each upload gets a random key that the browser keeps (in the page's memory only); the
store holds the newest ``config.CACHE_MAX`` reports, at most ``config.CACHE_MB`` of them,
and drops the oldest. A report nobody has used for ``config.REPORT_TTL_S`` is deleted.
Nothing is written to disk.

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
from spot import SpotPrices


@dataclass
class Entry:
    """One uploaded report and its results."""

    filename: str
    data: SharingData
    fit: KeyFit | None = None             # allocation keys estimated from the report
    exact: Recomputed | None = None       # recompute with the exact static method
    bill: BillResult | None = None        # billing by the Shapley value
    spot: SpotPrices | None = None        # OTE day-ahead prices of the report's period
    size: int = 0                         # estimated bytes, with room for a recompute
    used: float = 0.0                     # time.monotonic() of the last use


_ENTRIES: "OrderedDict[str, Entry]" = OrderedDict()
_LOCK = threading.Lock()
_janitor: threading.Thread | None = None


def data_bytes(data: SharingData) -> int:
    """Bytes of the report's arrays (the frame and the per-EAN series)."""
    series = [*data.productions.values(), *data.demand.values()]
    if data.production is not None:
        series.append(data.production)
    return int(data.frame.memory_usage(index=True).sum()
               + sum(s.memory_usage(index=False) for s in series))


def _expire(now: float) -> None:
    """Drop the reports unused for REPORT_TTL_S (under the lock)."""
    for key in [k for k, e in _ENTRIES.items() if now - e.used > config.REPORT_TTL_S]:
        del _ENTRIES[key]


def _sweep() -> None:  # pragma: no cover - background thread
    while True:
        time.sleep(60)
        with _LOCK:
            _expire(time.monotonic())
            _expire_files(time.monotonic())


def put(filename: str, data: SharingData) -> str:
    """Store a parsed upload; return its key. Evicts the oldest beyond CACHE_MAX or
    CACHE_MB (their running jobs notice and stop, see :func:`jobs.start`)."""
    global _janitor
    key = uuid.uuid4().hex
    now = time.monotonic()
    # the recompute keeps a second report of the same shape, the views a few series more
    entry = Entry(filename, data, size=3 * data_bytes(data), used=now)
    with _LOCK:
        _expire(now)
        _ENTRIES[key] = entry
        budget = config.CACHE_MB * 2**20
        while len(_ENTRIES) > 1 and (len(_ENTRIES) > config.CACHE_MAX
                                     or sum(e.size for e in _ENTRIES.values()) > budget):
            _ENTRIES.popitem(last=False)
        if _janitor is None:
            _janitor = threading.Thread(target=_sweep, name="store-janitor", daemon=True)
            _janitor.start()
    return key


def get(key: str | None) -> Entry | None:
    """The upload of ``key`` (and mark it recently used), or None."""
    if not key:
        return None
    with _LOCK:
        now = time.monotonic()
        _expire(now)
        entry = _ENTRIES.get(key)
        if entry is not None:
            entry.used = now
            _ENTRIES.move_to_end(key)
        return entry


def contains(key: str | None) -> bool:
    """Whether ``key``'s upload is still here (does not count as a use)."""
    with _LOCK:
        entry = _ENTRIES.get(key) if key else None
        return entry is not None and time.monotonic() - entry.used <= config.REPORT_TTL_S


def drop(key: str | None) -> None:
    """Forget an upload (its browser replaced it); its running jobs stop."""
    if key:
        with _LOCK:
            _ENTRIES.pop(key, None)


def size() -> int:
    with _LOCK:
        _expire(time.monotonic())
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
        while len(_FILES) > FILE_MAX:
            _FILES.popitem(last=False)
        _expire_files(now)
    return token


def _expire_files(now: float) -> None:
    """Drop the prepared files older than FILE_TTL_S (under the lock)."""
    while _FILES and now - next(iter(_FILES.values())).created > FILE_TTL_S:
        _FILES.popitem(last=False)


def get_file(token: str) -> File | None:
    """The prepared file of ``token``, or None when unknown or expired. It stays available
    until it expires: some browsers fetch a download twice."""
    with _LOCK:
        f = _FILES.get(token)
        if f is None or time.monotonic() - f.created > FILE_TTL_S:
            return None
        return f
