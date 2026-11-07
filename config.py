"""Settings from environment variables (see README, "Configuration").

Modules read them as ``config.NAME`` at call time, so tests can change them.
"""

import os

#: parsed reports kept in memory at most (~20-25 MB each incl. a recompute)
CACHE_MAX = max(1, int(os.environ.get("EDC_CACHE_MAX", "6")))
#: ... and at most this many MB of them (estimated); the oldest go first. With the
#: server's own ~110 MB and PARSE_MB this fits a 512 MB instance.
CACHE_MB = float(os.environ.get("EDC_CACHE_MB", "150"))
#: a report nobody has used for this long is deleted from memory (seconds)
REPORT_TTL_S = float(os.environ.get("EDC_REPORT_TTL_S", "3600"))
#: largest accepted CSV in MB
MAX_UPLOAD_MB = float(os.environ.get("EDC_MAX_UPLOAD_MB", "25"))
#: memory (MB) the parsing of one upload may take; a file that needs more is refused
#: (a year of 15-min data for ~100 members needs ~250 MB, for 30 members ~60 MB)
PARSE_MB = float(os.environ.get("EDC_PARSE_MB", "200"))
#: an upload waits this long (s) for another one's parsing, and may take this long itself
PARSE_WAIT_S = float(os.environ.get("EDC_PARSE_WAIT_S", "30"))
PARSE_TIMEOUT_S = float(os.environ.get("EDC_PARSE_TIMEOUT_S", "60"))
#: optional HTTP basic auth for the whole app (both must be set)
AUTH_USER = os.environ.get("BASIC_AUTH_USER", "")
AUTH_PASSWORD = os.environ.get("BASIC_AUTH_PASSWORD", "")
#: computations (key estimation, recompute, billing) running at once; others queue
MAX_JOBS = max(1, int(os.environ.get("EDC_MAX_JOBS", "2")))
#: unfinished computations (running, queued, spot price fetches) at most; more are
#: refused with "server busy" (one report has one of each kind at a time)
MAX_PENDING = max(1, int(os.environ.get("EDC_MAX_PENDING", "12")))
#: any job (recompute, billing, …) is stopped after this many seconds of work
JOB_TIMEOUT_S = float(os.environ.get("EDC_JOB_TIMEOUT_S", "1800"))
#: a key estimate is killed after this many seconds (it stops itself after ~20 s)
FIT_TIMEOUT_S = float(os.environ.get("EDC_FIT_TIMEOUT", "120"))
#: a job nobody has polled for this long (page closed) is cancelled; browsers throttle
#: timers of hidden tabs to once a minute, so keep this well above that
JOB_IDLE_S = float(os.environ.get("EDC_JOB_IDLE_S", "180"))
