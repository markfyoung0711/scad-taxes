"""Parse a Smith CAD parcel detail page into a flat, year-keyed record.

The page is the only public source that carries more than one year, so this is
where the appraisal and tax trend actually comes from. Layout, as of the 2026
roll:

  section.value-summary  two transposed tables - "Preliminary Values" (current
                         year) then "Value History" (prior years); rows are
                         metrics, columns are years
  section.juris          one row per taxing jurisdiction, one column per year,
                         each cell "<tax value><br><rate><br><tax>"
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from lxml import html as lxml_html

YEAR = re.compile(r"\b(19|20)\d{2}\b")
_CURRENCY = re.compile(r"[$,\s]")

VALUE_METRICS = {
    "Total Building Value": "building_value",
    "Total Land Value": "land_value",
    "Total Property Value": "total_property_value",
    "Special Use Appraisal": "special_use_value",
    "Cap Loss": "cap_loss",
    "Net Assessed Value": "net_assessed_value",
    "Use Code": "use_code",
    "Acreage": "acreage",
    "Block": "block",
    "Lot": "lot",
    "Main Area Sq Ft": "main_area_sqft",
}
NUMERIC_METRICS = {
    "building_value", "land_value", "total_property_value", "special_use_value",
    "cap_loss", "net_assessed_value", "acreage", "main_area_sqft",
}


def money(text: str | None) -> Decimal | None:
    """'$342,325' -> Decimal('342325'); blank or non-numeric -> None."""
    if not text:
        return None
    cleaned = _CURRENCY.sub("", text)
    if not cleaned or cleaned in {"-", "N/A"}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content()).strip()


def _lines(el) -> list[str]:
    """text_content() collapses <br>; these blocks are line-structured, so split on it."""
    parts = re.split(r"<br\s*/?>", lxml_html.tostring(el, encoding="unicode"), flags=re.I)
    out = []
    for part in parts:
        line = _text(lxml_html.fromstring(f"<div>{part}</div>"))
        if line:
            out.append(line)
    return out


def _years(table) -> list[int]:
    return [int(m.group()) for th in table.xpath(".//thead//th")
            if (m := YEAR.search(_text(th)))]


def _transposed(table) -> dict[int, dict]:
    """Read a metric-rows x year-columns table into {year: {metric: value}}."""
    years = _years(table)
    out: dict[int, dict] = {y: {} for y in years}
    for row in table.xpath(".//tbody/tr"):
        label = _text(row.xpath("./th")[0]) if row.xpath("./th") else ""
        field = VALUE_METRICS.get(label)
        if not field:
            continue
        for year, cell in zip(years, row.xpath("./td")):
            raw = _text(cell)
            out[year][field] = money(raw) if field in NUMERIC_METRICS else (raw or None)
    return out


def _summary(doc) -> dict:
    summary = {}
    for row in doc.xpath("//section[@class='parcel-info']//table[contains(@class,'grid-1d')]/tr"):
        keys, vals = row.xpath("./th"), row.xpath("./td")
        if keys and vals:
            summary[_text(keys[0])] = _lines(vals[0])
    return summary


def _first(summary: dict, key: str) -> str | None:
    lines = summary.get(key) or []
    return lines[0] if lines else None


def parse_parcel(content: bytes | str, *, gis_parcel_id: str | None = None) -> dict:
    """Return {parcel, values: [...per year], jurisdictions: [...per year]}."""
    doc = lxml_html.fromstring(content)
    summary = _summary(doc)

    owners = doc.xpath("//div[@class='ownership']/div")
    owner_lines = _lines(owners[0]) if owners else []

    parcel_id = None
    heading = doc.xpath("//h1|//h2[contains(text(),'Parcel')]")
    for el in heading:
        m = re.search(r"Parcel\s+(\S+)", _text(el))
        if m:
            parcel_id = m.group(1)
            break

    # Two transposed tables: current-year preliminary, then prior-year history.
    by_year: dict[int, dict] = {}
    for table in doc.xpath("//section[contains(@class,'value-summary')]//table[contains(@class,'grid-transposed')]"):
        for year, metrics in _transposed(table).items():
            by_year.setdefault(year, {}).update(metrics)

    juris: list[dict] = []
    total_tax: dict[int, Decimal | None] = {}
    for table in doc.xpath("//section[contains(@class,'juris')]//table"):
        years = _years(table)
        for row in table.xpath(".//tbody/tr"):
            cells = row.xpath("./td")
            if len(cells) < 2:
                continue
            name = _text(cells[0].xpath("./div/div")[0]) if cells[0].xpath("./div/div") else _text(cells[0])
            name = re.sub(r"\s*(Tax Value|Tax Rate|Tax)\s*$", "", name).strip()

            if name.upper().startswith("TOTAL CALCULATED TAX"):
                for year, cell in zip(years, cells[1:]):
                    total_tax[year] = money(_text(cell))
                continue

            for year, cell in zip(years, cells[1:]):
                # Each cell stacks three <br>-separated numbers.
                parts = [p.strip() for p in cell.xpath(".//text()") if p.strip()]
                if len(parts) < 3:
                    continue
                juris.append({
                    "tax_year": year,
                    "jurisdiction": name,
                    "taxable_value": money(parts[0]),
                    "tax_rate": money(parts[1]),
                    "tax_amount": money(parts[2]),
                })

    values = [{"tax_year": year, **metrics, "total_tax": total_tax.get(year)}
              for year, metrics in sorted(by_year.items())]

    return {
        "parcel": {
            "gis_parcel_id": gis_parcel_id,
            "parcel_id": parcel_id,
            "account": _first(summary, "PIN"),
            "owner_name": owner_lines[0] if owner_lines else None,
            "owner_address": " ".join(owner_lines[1:]) or None,
            "situs_address": _first(summary, "Location"),
            "use_code": _first(summary, "Use Code"),
            "tax_district": _first(summary, "Tax District"),
            "acreage": money(_first(summary, "Acreage")),
            "subdivision": _first(summary, "Subdivision"),
            # The district hides some exemptions online; the trailing privacy
            # note is a sibling line, not an exemption.
            "exemptions": [x for x in summary.get("Exemptions", [])
                           if not x.startswith("*For privacy")],
            "transfer_date": _first(summary, "Transfer Date"),
            "instrument_number": _first(summary, "Instrument Number"),
            "legal_description": re.sub(
                r"^Legal Description\s*", "",
                " ".join(line for e in doc.xpath("//section[@class='legal']")
                         for line in _lines(e))).strip() or None,
        },
        "values": values,
        "jurisdictions": sorted(juris, key=lambda r: (-r["tax_year"], r["jurisdiction"])),
    }
