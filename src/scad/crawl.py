"""Resumable, rate-limited crawl of parcel pages.

Tyler alone is 58,716 parcels, and each one is a page fetch, so this has to
survive being interrupted and has to stay polite. Workers each hold their own
session but share one token bucket, so concurrency raises throughput without
any worker ignoring the rate limit.

Already-staged accounts are skipped, which is what makes a re-run a resume
rather than a restart.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import acquire, parse, stage
from .config import STAGED
from .http import Client


class RateLimiter:
    """One shared bucket: `rate` requests per second across every worker."""

    def __init__(self, rate: float):
        self._min_gap = 1.0 / rate if rate > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._min_gap
        if wait:
            time.sleep(wait)


@dataclass
class Progress:
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, ok: bool, key: str) -> tuple[int, int]:
        with self._lock:
            if ok:
                self.done += 1
            else:
                self.failed.append(key)
            return self.done, len(self.failed)


def staged_accounts() -> set[str]:
    return {p.stem for p in (STAGED / "parcel").glob("*.json")}


def staged_gis_ids() -> set[str]:
    """Accounts already staged, keyed by the id the roster carries."""
    ids = set()
    for p in (STAGED / "parcel").glob("*.json"):
        try:
            ids.add(json.loads(p.read_text())["parcel"]["gis_parcel_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return ids


def crawl(criteria: dict, *, workers: int = 3, rate: float = 3.0,
          limit: int | None = None, label: str | None = None,
          log: Path | None = None) -> Progress:
    """Fetch, parse and stage every parcel matching `criteria`."""
    roster = acquire.search_parcels(Client(), label=label, **criteria)
    have = staged_gis_ids()
    todo = [r for r in roster if r.get("gis_parcel_id") not in have]
    # Count what the resume skipped before --limit trims the batch, or a small
    # test run reports the entire county as already held.
    already = len(roster) - len(todo)
    if limit:
        todo = todo[:limit]

    progress = Progress(total=len(todo), skipped=already)
    limiter = RateLimiter(rate)
    local = threading.local()

    def client() -> Client:
        if not hasattr(local, "client"):
            # Delay lives in the shared bucket, not the per-worker session.
            local.client = Client(delay=0)
        return local.client

    def fetch(row: dict) -> tuple[bool, str]:
        gis_id = row["gis_parcel_id"]
        try:
            limiter.acquire()
            content = acquire.fetch_parcel(client(), gis_id)
            record = parse.parse_parcel(content, gis_parcel_id=gis_id)
            if not record["values"]:
                return False, gis_id
            stage.stage_parcel(record)
            return True, gis_id
        except Exception:
            return False, gis_id

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch, row) for row in todo]
        for n, future in enumerate(as_completed(futures), start=1):
            ok, key = future.result()
            done, failed = progress.record(ok, key)
            if log and n % 100 == 0:
                elapsed = time.monotonic() - started
                remaining = (len(todo) - n) * elapsed / max(n, 1)
                log.write_text(
                    f"{done}/{len(todo)} staged, {failed} failed, "
                    f"{progress.skipped} already held, "
                    f"{elapsed/60:.0f}m elapsed, ~{remaining/60:.0f}m left\n")
    return progress
