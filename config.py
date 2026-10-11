"""Settings from environment variables (see README, "Configuration").

Modules read them as ``config.NAME`` at call time, so tests can change them.
"""

import os

#: parsed reports kept in memory (~20-25 MB each incl. a recompute; 512 MB instances -> 6)
CACHE_MAX = max(1, int(os.environ.get("EDC_CACHE_MAX", "6")))
#: largest accepted CSV in MB
MAX_UPLOAD_MB = float(os.environ.get("EDC_MAX_UPLOAD_MB", "25"))
#: optional HTTP basic auth for the whole app (both must be set)
AUTH_USER = os.environ.get("BASIC_AUTH_USER", "")
AUTH_PASSWORD = os.environ.get("BASIC_AUTH_PASSWORD", "")
#: computations (key estimation, recompute, billing) running at once; others queue
MAX_JOBS = max(1, int(os.environ.get("EDC_MAX_JOBS", "2")))
#: a key estimate is killed after this many seconds (it stops itself after ~20 s)
FIT_TIMEOUT_S = float(os.environ.get("EDC_FIT_TIMEOUT", "120"))
#: a job nobody has polled for this long (page closed) is cancelled; browsers throttle
#: timers of hidden tabs to once a minute, so keep this well above that
JOB_IDLE_S = float(os.environ.get("EDC_JOB_IDLE_S", "180"))
