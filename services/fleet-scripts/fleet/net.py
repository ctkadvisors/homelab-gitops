"""One retrying urlopen for the fleet's in-cluster calls.

2026-09-06: the daily digest had failed every morning since the 4th with
"connection refused" from the workbench. Not the workbench: k3s's network
policy controller on the destination node adds a new pod's IP to the
allow-list a few seconds after the pod starts, and a Job's first request
lands before that. A probe from elitemini2 was refused at t=0 and answered
at t=12s. Connection errors on the first tries are therefore expected and
retried; HTTP errors (4xx/5xx) are not, they mean something.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request

WAIT = float(os.environ.get("NET_RETRY_WAIT", "5"))  # tests set 0


def urlopen_retry(req, timeout: int = 30, tries: int = 8, wait: float | None = None):
    """urllib.request.urlopen that retries connection-level failures."""
    wait = WAIT if wait is None else wait
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            last = e
            if i + 1 < tries:
                print(f"net: {getattr(req, 'full_url', req)}: {type(e).__name__}: {str(e)[:80]}; retry {i + 1}/{tries - 1} in {wait:.0f}s", flush=True)
                time.sleep(wait)
    raise last  # type: ignore[misc]
