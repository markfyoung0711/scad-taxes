import json
import os

from scad_taxes import find_suspicious_increases, load_records, percent_change


def test_percent_change() -> None:
    assert percent_change(100, 125) == 25.0
    assert percent_change(100, 100) == 0.0
    assert percent_change(0, 0) == 0.0


def test_find_suspicious_increases_flags_unsupported_growth() -> None:
    records = [
        {"year": 2021, "taxable_value": 200000, "supporting_evidence": "market study"},
        {"year": 2022, "taxable_value": 260000, "supporting_evidence": None},
        {"year": 2023, "taxable_value": 280000, "supporting_evidence": "reappraisal memo"},
    ]

    findings = find_suspicious_increases(records, minimum_increase=20.0)

    assert len(findings) == 1
    assert findings[0]["current_year"] == 2022
    assert findings[0]["increase_percent"] == 30.0


def test_load_records_accepts_list_or_wrapper() -> None:
    payload = [{"year": 2024, "taxable_value": 100000, "supporting_evidence": "record"}]
    path = "/tmp/scad-records.json"

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    try:
        loaded = load_records(path)
    finally:
        os.remove(path)

    assert loaded == payload
