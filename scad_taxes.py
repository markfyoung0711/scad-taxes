"""Evidence-first analysis for Smith County Appraisal District tax changes.

This module is intentionally conservative: it reports only increases that are
large enough to warrant review and that lack supporting documentation.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Iterable, Sequence


def percent_change(previous: float, current: float) -> float:
    """Return the percentage increase between previous and current values."""
    if previous == 0:
        return 0.0 if current == 0 else float("inf")
    return ((current - previous) / abs(previous)) * 100.0


def find_suspicious_increases(
    records: Sequence[dict[str, Any]],
    minimum_increase: float = 20.0,
) -> list[dict[str, Any]]:
    """Return suspicious tax increases that are substantial and unsupported.

    Each record is expected to contain at least: year, taxable_value, and
    supporting_evidence (string or None). Records are evaluated chronologically.
    """
    suspicious: list[dict[str, Any]] = []
    for previous, current in zip(records, records[1:]):
        previous_value = float(previous.get("taxable_value", 0.0))
        current_value = float(current.get("taxable_value", 0.0))
        delta_percent = percent_change(previous_value, current_value)
        evidence = current.get("supporting_evidence")
        if delta_percent >= minimum_increase and not evidence:
            suspicious.append(
                {
                    "previous_year": previous.get("year"),
                    "current_year": current.get("year"),
                    "previous_value": previous_value,
                    "current_value": current_value,
                    "increase_percent": round(delta_percent, 2),
                    "requires_evidence": True,
                }
            )
    return suspicious


def load_records(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "records" in payload:
        return payload["records"]
    if isinstance(payload, list):
        return payload
    raise ValueError("Input JSON must be a list of records or an object with a 'records' array")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report tax appraisal increases that look suspicious and lack supporting evidence. "
            "The tool is intentionally evidence-first and conservative."
        )
    )
    parser.add_argument("path", help="Path to a JSON file containing appraisal records")
    parser.add_argument(
        "--minimum-increase",
        type=float,
        default=20.0,
        help="Minimum percentage increase to flag as suspicious (default: 20)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    records = load_records(args.path)
    findings = find_suspicious_increases(records, minimum_increase=args.minimum_increase)

    result = {
        "suspicious_findings": findings,
        "finding_count": len(findings),
        "minimum_increase": args.minimum_increase,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
