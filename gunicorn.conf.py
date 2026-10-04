"""Gunicorn settings (loaded automatically from the working directory).

The app keeps uploads, key estimates and running jobs in the memory of ONE
process, so every request of a browser session must reach that process:

* ``workers = 1`` - on purpose, and not taken from WEB_CONCURRENCY. With more
  workers the progress polls of a job, or the plots of an upload, would land in
  a process that never saw them (robopid-simulator hit exactly this with its
  per-process job cache). More users are served by threads, not workers.
* ``max_requests = 0`` - never recycle the worker; a recycled worker would drop
  every upload and job in flight.
* Heavy work (key estimation, the rozdel() loop) runs in forked child processes
  (procjob.py), so request threads stay free for progress polls and a job can be
  cancelled. Capacity is EDC_MAX_JOBS (jobs at once) and EDC_THREADS (requests).
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8050')}"
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("EDC_THREADS", "8"))
timeout = 120
graceful_timeout = 30
max_requests = 0
preload_app = False
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")


def on_starting(server):  # pragma: no cover - log only
    wc = os.environ.get("WEB_CONCURRENCY")
    if wc and wc != "1":
        server.log.warning(
            "WEB_CONCURRENCY=%s ignored: this app must run with one worker "
            "(in-memory uploads and jobs); scale with EDC_THREADS instead.", wc)
