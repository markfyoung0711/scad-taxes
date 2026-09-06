"""Polite HTTP session: one shared cookie jar, fixed delay, bounded retries.

The search app keeps the active query in the session cookie, so the export
endpoint only returns rows when it shares a session with the search that
produced them. That is why callers must reuse a single Client.
"""
from __future__ import annotations

import time

import requests

from .config import REQUEST_DELAY_SEC, USER_AGENT


class Client:
    def __init__(self, delay: float = REQUEST_DELAY_SEC):
        self.delay = delay
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url: str, *, params=None, tries: int = 3, **kw) -> requests.Response:
        for attempt in range(tries):
            self._wait()
            try:
                r = self.session.get(url, params=params, timeout=60, **kw)
                r.raise_for_status()
                return r
            except requests.RequestException:
                if attempt == tries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")
