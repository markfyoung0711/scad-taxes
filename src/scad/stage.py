"""Landing zone: raw payloads are written once, verbatim, and never edited.

Every write appends a manifest line so a warehouse row can always be traced
back to the exact bytes and the URL/time they came from.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import RAW

MANIFEST = RAW / "_manifest.jsonl"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def land(source: str, name: str, content: bytes, *, url: str, meta: dict | None = None) -> Path:
    """Write `content` under data/raw/<source>/<name> and record its provenance."""
    path = RAW / source / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "source": source,
        "path": str(path.relative_to(RAW)),
        "url": url,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "fetched_at": utcnow(),
        **(meta or {}),
    }
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return path


def manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def stage_parcel(record: dict) -> Path:
    """Write a parsed parcel record as newline-delimited JSON for the loader.

    Decimals are serialised as strings so the warehouse can cast to DECIMAL
    without a float round-trip.
    """
    from decimal import Decimal

    from .config import STAGED

    account = record["parcel"].get("account") or record["parcel"].get("gis_parcel_id") or "unknown"
    path = STAGED / "parcel" / f"{account}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {**record, "_staged_at": utcnow()},
        default=lambda o: str(o) if isinstance(o, Decimal) else None,
    ))
    return path
