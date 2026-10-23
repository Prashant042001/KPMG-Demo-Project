"""GIS view of a completed run: Operational Site List sites linked to the payment rows of the master database.

The link is the derived SITE ID: a master-database row whose SITE ID equals a site's Site ID belongs to that site.
Because the payment side only exists once T-number / Site ID derivation has run, the GIS data is built as part
of every processing job and served per job (GET /api/jobs/{job_id}/gis).
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.core.text import cell_text, match_key
from app.derivation.engine import CANNOT_BE_DERIVED, EngineResult
from app.derivation.identifiers import IdentifierFormats
from app.ingest.readers import Table

MAX_PAYMENTS_RETURNED = 1000
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def site_key(site_id: str) -> str:
    """Comparison key for Site IDs: numeric IDs ignore leading zeros (0123 == 123)."""
    s = match_key(site_id).replace(" ", "")
    return (s.lstrip("0") or "0") if s.isdigit() else s


def _coordinate(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = cell_text(value).replace("−", "-").replace("°", "").strip()
    if re.fullmatch(r"[-+]?\d+,\d+", text):  # decimal comma, e.g. -26,2041
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _valid(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)


def _split_coordinates(value: object) -> tuple[float | None, float | None]:
    nums = _NUM.findall(cell_text(value).replace("−", "-"))
    return (float(nums[0]), float(nums[1])) if len(nums) == 2 else (None, None)


def _display(value: object) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time() else value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    return cell_text(value)


def _amount(text: str) -> float | None:
    t = text.replace(",", "").replace(" ", "")
    neg = t.startswith("(") and t.endswith(")")
    try:
        v = float(t.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


@dataclass
class GisData:
    sites: dict[str, dict[str, Any]] = field(default_factory=dict)  # site key -> site details
    payments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # site key -> payment rows
    fields: dict[str, str | None] = field(default_factory=dict)  # logical field -> source column header
    stats: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def _summary(self, key: str, site: dict[str, Any]) -> dict[str, Any]:
        rows = self.payments.get(key, [])
        amounts = [r["_amount"] for r in rows if r["_amount"] is not None]
        tnums = Counter(r["tnumber"] for r in rows if r["tnumber"] != CANNOT_BE_DERIVED)
        return {
            **site,
            "tnumber": tnums.most_common(1)[0][0] if tnums else None,
            "payment_count": len(rows),
            "payment_total": round(sum(amounts), 2) if amounts else None,
        }

    def summary(self) -> dict[str, Any]:
        sites = [self._summary(k, s) for k, s in self.sites.items()]
        return {"sites": sites, "fields": self.fields, "stats": self.stats, "notes": self.notes}

    def site(self, site_id: str) -> dict[str, Any] | None:
        key = site_key(site_id)
        if key in self.sites:
            site = self._summary(key, self.sites[key])
        elif key in self.payments:  # paid in the master data but absent from the Operational Site List
            site = self._summary(key, {"site_id": site_id, "in_site_list": False, "has_coordinates": False})
        else:
            return None
        rows = self.payments.get(key, [])
        return {
            "site": site,
            "fields": self.fields,
            "payments": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows[:MAX_PAYMENTS_RETURNED]],
            "payments_truncated": len(rows) > MAX_PAYMENTS_RETURNED,
        }


def build_gis(source: Table, ops_tables: list[Table], result: EngineResult, formats: IdentifierFormats) -> GisData:
    gis = GisData()

    # 1. Sites from the Operational Site List Summary
    duplicates = invalid = 0
    for t in ops_tables:
        col = t.columns.get
        for i in range(t.row_count):
            row = t.df.iloc[i]
            raw_id = cell_text(row[col("SITE_ID")])
            site_id, ok = formats.site_id(raw_id)
            if not site_id or not ok:
                invalid += bool(raw_id)
                continue
            lat = _coordinate(row[col("LATITUDE")]) if col("LATITUDE") is not None else None
            lon = _coordinate(row[col("LONGITUDE")]) if col("LONGITUDE") is not None else None
            if not _valid(lat, lon) and col("COORDINATES") is not None:
                lat, lon = _split_coordinates(row[col("COORDINATES")])
            has_xy = _valid(lat, lon)
            site = {
                "site_id": site_id,
                "site_name": cell_text(row[col("SITE_NAME")]) if col("SITE_NAME") is not None else "",
                "region": cell_text(row[col("REGION")]) if col("REGION") is not None else "",
                "property_owner": cell_text(row[col("PROPERTY_OWNER")]) if col("PROPERTY_OWNER") is not None else "",
                "lat": lat if has_xy else None,
                "lon": lon if has_xy else None,
                "has_coordinates": has_xy,
                "in_site_list": True,
                "source_file": t.file_name,
            }
            key = site_key(site_id)
            if key in gis.sites:
                duplicates += 1
                if has_xy and not gis.sites[key]["has_coordinates"]:
                    gis.sites[key].update(lat=site["lat"], lon=site["lon"], has_coordinates=True)
                continue
            gis.sites[key] = site

    # 2. Payment rows from the master data (source rows with a derived SITE ID)
    c = source.columns
    key_col = c.get("VENDOR_SITE_CODE", c.get("VENDOR_SITE"))
    wanted = {"vendor_name": c.get("VENDOR_NAME"), "vendor_site_code": key_col,
              "payment_date": c.get("PAYMENT_DATE"), "payment_amount": c.get("PAYMENT_AMOUNT")}
    gis.fields = {k: (source.headers[p] if p is not None else None) for k, p in wanted.items()}
    for r in result.records:
        if not r.outcome.site_id:
            continue
        values = source.df.iloc[r.row_index]
        pay = {k: (_display(values[p]) if p is not None else "") for k, p in wanted.items()}
        pay.update(row=r.row_number, tnumber=r.outcome.tnumber, site_id=r.outcome.site_id, _amount=_amount(pay["payment_amount"]))
        gis.payments.setdefault(site_key(r.outcome.site_id), []).append(pay)

    # 3. Statistics and explanations
    linked = [k for k in gis.sites if k in gis.payments]
    unlisted = sorted(k for k in gis.payments if k not in gis.sites)
    gis.stats = {
        "sites_in_site_list": len(gis.sites),
        "sites_with_coordinates": sum(s["has_coordinates"] for s in gis.sites.values()),
        "sites_with_payments": len(linked),
        "master_rows_linked_to_listed_sites": sum(len(gis.payments[k]) for k in linked),
        "paid_site_ids_not_in_site_list": len(unlisted),
        "unlisted_site_ids": [gis.payments[k][0]["site_id"] for k in unlisted][:200],
        "duplicate_site_rows": duplicates,
        "invalid_site_ids": invalid,
    }
    if not ops_tables:
        gis.notes.append("No Operational Site List Summary was supplied, so there are no sites to plot.")
    elif not any(s["has_coordinates"] for s in gis.sites.values()):
        gis.notes.append(
            "The Operational Site List Summary has no usable coordinates. Add 'Latitude' and 'Longitude' columns "
            "(decimal degrees) or one 'Coordinates' column ('lat, long') to plot sites on the map."
        )
    missing = [f for f, h in gis.fields.items() if h is None]
    if missing:
        gis.notes.append("Source file columns not found for: " + ", ".join(missing).replace("_", " ") + ".")
    return gis
