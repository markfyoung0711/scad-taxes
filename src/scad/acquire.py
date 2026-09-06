"""Data acquisition from Smith CAD's three public surfaces.

1. Advanced search + export  -> parcel roster as JSON (attributes, no values)
2. Parcel detail page (HTML)  -> per-year values and per-jurisdiction tax history
3. Certified appraisal roll   -> full-county bulk CSV, current year only

The parcel page is the only public source carrying multiple years, so it is
what the value/tax trend rests on. The bulk roll is the authoritative
current-year cross-check and the source for county-wide expansion.
"""
from __future__ import annotations

import json
import re

from .config import BULK_BASE, BULK_FILES, SEARCH_BASE
from .http import Client
from .stage import land

_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(text: str) -> str:
    return _SLUG.sub("_", text).strip("_")


# Advanced-search form fields (https://smithcad-search.gsacorp.io/search/adv/r/1),
# mapped from readable keyword arguments. List-valued fields repeat the key.
SEARCH_FIELDS = {
    "owner_name": "query[owner][name]",
    "street_num_min": "query[addr][str_num_min]",
    "street_num_max": "query[addr][str_num_max]",
    "street_name": "query[addr][str_name]",
    "city": "query[addr][city][]",
    "subdivision": "query[parcel][subdiv][]",
    "neighborhood": "query[parcel][nh][]",
    "agent_code": "query[agent][short_cd]",
    "parcel_id_contains": "query[parcel][strap]",
    "parcel_id_min": "query[parcel][strap_min]",
    "parcel_id_max": "query[parcel][strap_max]",
    "tax_district": "query[tax_grp][cd][]",
    "property_use": "query[parcel][use][]",
    "zone": "query[land][zone][]",
    "comm_sqft_min": "query[bld][comm_sqft][min]",
    "comm_sqft_max": "query[bld][comm_sqft][max]",
    "res_sqft_min": "query[bld][res_sqft][min]",
    "res_sqft_max": "query[bld][res_sqft][max]",
    "acreage_min": "query[parcel][acreage_min]",
    "acreage_max": "query[parcel][acreage_max]",
    "constr_yr_min": "query[bld][constr_yr][min]",
    "constr_yr_max": "query[bld][constr_yr][max]",
}


def search_parcels(client: Client, *, label: str | None = None, **criteria) -> list[dict]:
    """Run an advanced parcel search and return the district's JSON export.

    Criteria use the readable names in SEARCH_FIELDS; list values repeat the
    field (the form's Ctrl-click multi-selects). Owner name is matched as a
    prefix on the district's "LAST FIRST" form, so 'young mark' matches and
    'mark young' does not.
    """
    params: list[tuple[str, str]] = [("type", "r"), ("sort", "Property ID")]
    for key, value in criteria.items():
        if value in (None, ""):
            continue
        try:
            field = SEARCH_FIELDS[key]
        except KeyError:
            raise ValueError(f"unknown search field {key!r}; expected one of {sorted(SEARCH_FIELDS)}")
        for item in (value if isinstance(value, (list, tuple)) else [value]):
            params.append((field, str(item)))

    client.get(f"{SEARCH_BASE}/search/adv", params=params)

    # The export re-reads the query from the session cookie set by the search above.
    resp = client.get(
        f"{SEARCH_BASE}/export/adv/r",
        params={"format": "json", "sort": "Property ID"},
    )
    name = label or "_".join(f"{k}-{v}" for k, v in sorted(criteria.items())) or "all"
    land("search_export", f"{_slug(name)}.json", resp.content, url=resp.url,
         meta={"criteria": criteria})
    return json.loads(resp.text)


def fetch_parcel(client: Client, gis_parcel_id: str) -> bytes:
    """Fetch one parcel detail page and land the raw HTML."""
    url = f"{SEARCH_BASE}/parcel/{gis_parcel_id}"
    resp = client.get(url)
    land("parcel_html", f"{_slug(gis_parcel_id)}.html", resp.content, url=url,
         meta={"gis_parcel_id": gis_parcel_id})
    return resp.content


def fetch_bulk_roll(client: Client, year: int, kind: str = "all") -> bytes:
    """Download a certified appraisal roll archive for `year`."""
    name = BULK_FILES[kind].format(year=year)
    url = f"{BULK_BASE}/{year}/{name}"
    resp = client.get(url)
    land("bulk_roll", f"{year}/{name}", resp.content, url=url,
         meta={"year": year, "kind": kind})
    return resp.content
