"""Paths and endpoints for the Smith CAD pipeline."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("SCAD_ROOT", Path(__file__).resolve().parents[2]))
RAW = ROOT / "data" / "raw"
STAGED = ROOT / "data" / "staged"
WAREHOUSE = ROOT / "data" / "warehouse" / "scad.duckdb"
SQL = ROOT / "sql"

SEARCH_BASE = "https://smithcad-search.gsacorp.io"
BULK_BASE = "https://www.smithcad.org/data"

# Bulk certified appraisal roll archives. Only the current year is published on
# smithcad.org; prior years require an open-records request to the district.
BULK_FILES = {
    "all": "{year}_All_Property_Certified_AppraisalRoll_cd.zip",
    "real": "{year}_Real_Property_Certifled_AppraisalRoll_cd.zip",  # sic, district typo
    "bpp": "{year}_BPP_Certifled_AppraisalRoll_cd.zip",             # sic
    "mineral": "{year}_Mineral_Certified_AppraisalRoll_cd.zip",
}

USER_AGENT = os.environ.get(
    "SCAD_USER_AGENT",
    "scad-taxes/0.1 (public appraisal data research; contact mark.francis.young@gmail.com)",
)
REQUEST_DELAY_SEC = float(os.environ.get("SCAD_DELAY", "1.0"))
