"""Geocode parcels against Smith County's own GIS, not a third-party service.

The county publishes the authoritative parcel polygons, keyed by the same
account numbers the appraisal roll uses, so a parcel's location comes from a
join rather than from address-string matching. Address Points is the fallback
for parcels with no polygon of their own -- improvement-only accounts and
recent splits, which are common enough to matter.
"""
from __future__ import annotations

import json

from .http import Client
from .stage import land

ARCGIS = "https://services5.arcgis.com/KgTmADyzXWOLUPKd/arcgis/rest/services"
PARCELS = f"{ARCGIS}/Parcels/FeatureServer/0/query"
ADDRESS_POINTS = f"{ARCGIS}/Address_Points/FeatureServer/0/query"

CHUNK = 100


def _quote(values) -> str:
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _query(client: Client, url: str, where: str, out_fields: str, *,
           centroid: bool) -> list[dict]:
    params = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "true" if not centroid else "false",
        "outSR": "4326",
        "f": "json",
    }
    if centroid:
        params["returnCentroid"] = "true"
    resp = client.get(url, params=params)
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"ArcGIS error: {payload['error']}")
    return payload.get("features", [])


def from_parcels(client: Client, gis_parcel_ids: list[str]) -> dict[str, dict]:
    """Parcel-polygon centroids keyed by gis_parcel_id (the layer's ACCOUNT)."""
    found: dict[str, dict] = {}
    for i in range(0, len(gis_parcel_ids), CHUNK):
        batch = gis_parcel_ids[i:i + CHUNK]
        feats = _query(client, PARCELS, f"ACCOUNT IN ({_quote(batch)})",
                       "ACCOUNT,PIN,ADDRESS,POSTAL_CITY,ZIPCODE,CALC_ACRE",
                       centroid=True)
        land("geocode_parcels", f"batch_{i // CHUNK:03d}.json",
             json.dumps(feats).encode(), url=PARCELS,
             meta={"ids": batch, "matched": len(feats)})
        for f in feats:
            a, c = f["attributes"], f.get("centroid") or {}
            if c.get("x") is None:
                continue
            found[a["ACCOUNT"]] = {
                "gis_parcel_id": a["ACCOUNT"],
                "account": a.get("PIN"),
                "longitude": c["x"],
                "latitude": c["y"],
                "gis_address": a.get("ADDRESS"),
                "gis_city": a.get("POSTAL_CITY"),
                "gis_zip": str(a["ZIPCODE"]) if a.get("ZIPCODE") else None,
                "gis_acres": a.get("CALC_ACRE"),
                "source": "parcel_centroid",
            }
    return found


def from_address_points(client: Client, addresses: dict[str, str]) -> dict[str, dict]:
    """Fallback: match a situs address to the county's address point layer.

    Keyed by gis_parcel_id -> situs address. Matching is on the full address
    string as the county writes it, uppercased on both sides.
    """
    found: dict[str, dict] = {}
    wanted = {k: v.strip().upper() for k, v in addresses.items() if v and v.strip()}
    if not wanted:
        return found

    unique = sorted(set(wanted.values()))
    points: dict[str, dict] = {}
    for i in range(0, len(unique), CHUNK):
        batch = unique[i:i + CHUNK]
        feats = _query(client, ADDRESS_POINTS,
                       f"UPPER(FullAddr) IN ({_quote(batch)})",
                       "FullAddr,Post_Comm,Post_Code,Long,Lat", centroid=False)
        land("geocode_address_points", f"batch_{i // CHUNK:03d}.json",
             json.dumps(feats).encode(), url=ADDRESS_POINTS,
             meta={"addresses": batch, "matched": len(feats)})
        for f in feats:
            a, g = f["attributes"], f.get("geometry") or {}
            key = (a.get("FullAddr") or "").strip().upper()
            if key and g.get("x") is not None:
                points.setdefault(key, {
                    "longitude": g["x"], "latitude": g["y"],
                    "gis_address": a.get("FullAddr"),
                    "gis_city": a.get("Post_Comm"),
                    "gis_zip": a.get("Post_Code"),
                })

    for gis_id, addr in wanted.items():
        hit = points.get(addr)
        if hit:
            found[gis_id] = {"gis_parcel_id": gis_id, "account": None,
                             "gis_acres": None, "source": "address_point", **hit}
    return found


def locate(client: Client, parcels: list[dict]) -> list[dict]:
    """Geocode `parcels` (dicts with gis_parcel_id and situs_address).

    Polygon centroid where the county has one, address point otherwise.
    """
    ids = [p["gis_parcel_id"] for p in parcels if p.get("gis_parcel_id")]
    located = from_parcels(client, ids)

    missing = {p["gis_parcel_id"]: p.get("situs_address") or ""
               for p in parcels
               if p.get("gis_parcel_id") and p["gis_parcel_id"] not in located}
    located.update(from_address_points(client, missing))

    for p in parcels:
        hit = located.get(p.get("gis_parcel_id"))
        if hit:
            hit.setdefault("account", None)
            hit["account"] = hit["account"] or p.get("account")
    return sorted(located.values(), key=lambda r: r["gis_parcel_id"])
