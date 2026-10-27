"""GIS view: Operational Site List sites linked to payment rows.

Two modes, both served per job (GET /api/jobs/{job_id}/gis):

* ``derived`` – built as part of every T-number / Site ID derivation job. A master-database row whose derived
  SITE ID equals a site's Site ID belongs to that site.
* ``direct`` – built without derivation (POST /api/gis) from a site list and an optional payment file. A payment
  row belongs to a site when its own Site ID column matches, or else when its Vendor Site Code equals the site's
  Account Number in the Operational Site List.
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
DERIVED, DIRECT = "derived", "direct"
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
# Degrees-minutes-seconds or decimal degrees with a hemisphere letter: 26°12'15.5"S, S 26 12 15, 28.03 E
_DMS = re.compile(
    r"([NSEW])?\s*([-+]?\d+(?:\.\d+)?)\s*(?:[°º:]|\s)\s*(?:(\d+(?:\.\d+)?)\s*(?:['′:]|\s)\s*)?"
    r"(?:(\d+(?:\.\d+)?)\s*(?:\"|″|'')?\s*)?([NSEW])?",
    re.IGNORECASE,
)
_HEMI = re.compile(r"\s*([-+]?\d+(?:\.\d+)?)\s*([NSEW])\s*", re.IGNORECASE)


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
        pass
    return _dms(cell_text(value).replace("−", "-"))


def _dms(text: str) -> float | None:
    m = _HEMI.fullmatch(text) or _DMS.fullmatch(text.strip())
    if not m:
        return None
    if m.re is _HEMI:
        deg, mins, secs, hemi = m.group(1), None, None, m.group(2)
    else:
        if m.group(1) and m.group(5):
            return None
        deg, mins, secs, hemi = m.group(2), m.group(3), m.group(4), m.group(1) or m.group(5)
    mins_f, secs_f = float(mins or 0), float(secs or 0)
    if mins_f >= 60 or secs_f >= 60:
        return None
    sign = -1 if deg.startswith("-") else 1
    value = abs(float(deg)) + mins_f / 60 + secs_f / 3600
    if hemi and hemi.upper() in "SW":
        sign = -1
    return round(sign * value, 6)


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


RENTAL, ELECTRICITY = "Rental + Fixed", "Variable Electricity"


def payment_type(invoice_number: object) -> str:
    """Business rule: invoice numbers starting with PN are rental + fixed payments, all others variable electricity."""
    return RENTAL if match_key(invoice_number).startswith("PN") else ELECTRICITY


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d/%m/%y")


def _date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 20000 < value < 80000:  # Excel serial date
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(value))
    text = cell_text(value)[:19].split("T")[0].split(" 00:00")[0]
    for f in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, f).date()
        except ValueError:
            continue
    return None


CHART_YEAR = 2025


def quarterly(rows: list[dict[str, Any]], year: int = CHART_YEAR) -> list[dict[str, Any]]:
    """Payment totals per quarter of ``year``, split into rental and electricity (rows need _date/_amount/payment_type)."""
    out = [{"quarter": f"Q{q}", "rental": 0.0, "electricity": 0.0, "rental_count": 0, "electricity_count": 0} for q in range(1, 5)]
    for r in rows:
        d, amount = r["_date"], r["_amount"]
        if d is None or amount is None or d.year != year:
            continue
        kind = "rental" if r["payment_type"] == RENTAL else "electricity"
        bucket = out[(d.month - 1) // 3]
        bucket[kind] = round(bucket[kind] + amount, 2)
        bucket[f"{kind}_count"] += 1
    return out


@dataclass
class GisData:
    sites: dict[str, dict[str, Any]] = field(default_factory=dict)  # site key -> site details
    payments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # site key -> payment rows
    fields: dict[str, str | None] = field(default_factory=dict)  # logical field -> source column header
    stats: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    mode: str = DERIVED
    payment_file: str | None = None
    all_payments: list[dict[str, Any]] = field(default_factory=list)  # every payment row, linked or not (overall chart)

    def chart(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {"year": CHART_YEAR, "quarters": quarterly(rows),
                "has_dates": self.fields.get("payment_date") is not None, "has_invoice": self.fields.get("invoice_number") is not None}

    def _summary(self, key: str, site: dict[str, Any]) -> dict[str, Any]:
        rows = self.payments.get(key, [])
        amounts = [r["_amount"] for r in rows if r["_amount"] is not None]
        tnums = Counter(r["tnumber"] for r in rows if r["tnumber"] and r["tnumber"] != CANNOT_BE_DERIVED)
        return {
            **site,
            "tnumber": tnums.most_common(1)[0][0] if tnums else None,
            "payment_count": len(rows),
            "payment_total": round(sum(amounts), 2) if amounts else None,
        }

    def summary(self) -> dict[str, Any]:
        sites = [self._summary(k, s) for k, s in self.sites.items()]
        return {"mode": self.mode, "payment_file": self.payment_file, "sites": sites, "fields": self.fields,
                "stats": self.stats, "notes": self.notes, "chart": self.chart(self.all_payments)}

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
            "chart": self.chart(rows),
        }


def _load_sites(gis: GisData, ops_tables: list[Table], formats: IdentifierFormats) -> dict[str, set[str]]:
    """Fill ``gis.sites`` from the Operational Site List Summary; return its Account Number -> site keys index."""
    duplicates = invalid = 0
    accounts: dict[str, set[str]] = {}
    coordinate_columns: list[str] = []
    for t in ops_tables:
        col = t.columns.get
        used = [t.header_of(k) for k in ("LATITUDE", "LONGITUDE", "COORDINATES") if col(k) is not None]
        coordinate_columns.append(f"{t.file_name} [{t.sheet_name}]: " + (" / ".join(used) if used else "none found"))
        for i in range(t.row_count):
            row = t.df.iloc[i]
            raw_id = cell_text(row[col("SITE_ID")])
            site_id, ok = formats.site_id(raw_id)
            if not site_id or not ok:
                invalid += bool(raw_id)
                continue
            key = site_key(site_id)
            account = match_key(row[col("ACCOUNT_NUMBER")]) if col("ACCOUNT_NUMBER") is not None else ""
            if account:
                accounts.setdefault(account, set()).add(key)
            lat = _coordinate(row[col("LATITUDE")]) if col("LATITUDE") is not None else None
            lon = _coordinate(row[col("LONGITUDE")]) if col("LONGITUDE") is not None else None
            if not _valid(lat, lon) and col("COORDINATES") is not None:
                lat, lon = _split_coordinates(row[col("COORDINATES")])
            has_xy = _valid(lat, lon)
            site = {
                "site_id": site_id,
                "site_name": cell_text(row[col("SITE_NAME")]) if col("SITE_NAME") is not None else "",
                "site_status": cell_text(row[col("SITE_STATUS")]) if col("SITE_STATUS") is not None else "",
                "region": cell_text(row[col("REGION")]) if col("REGION") is not None else "",
                "property_owner": cell_text(row[col("PROPERTY_OWNER")]) if col("PROPERTY_OWNER") is not None else "",
                "lat": lat if has_xy else None,
                "lon": lon if has_xy else None,
                "has_coordinates": has_xy,
                "in_site_list": True,
                "source_file": t.file_name,
            }
            if key in gis.sites:
                duplicates += 1
                if has_xy and not gis.sites[key]["has_coordinates"]:
                    gis.sites[key].update(lat=site["lat"], lon=site["lon"], has_coordinates=True)
                continue
            gis.sites[key] = site
    gis.stats.update(duplicate_site_rows=duplicates, invalid_site_ids=invalid, coordinate_columns=coordinate_columns)
    return accounts


def _payment_fields(gis: GisData, source: Table | None) -> dict[str, int | None]:
    c = source.columns if source is not None else {}
    wanted = {"vendor_name": c.get("VENDOR_NAME"), "vendor_site_code": c.get("VENDOR_SITE_CODE", c.get("VENDOR_SITE")),
              "payment_date": c.get("PAYMENT_DATE"), "payment_amount": c.get("PAYMENT_AMOUNT"),
              "invoice_number": c.get("INVOICE_NUMBER")}
    gis.fields = {k: (source.headers[p] if p is not None else None) for k, p in wanted.items()}
    return wanted


def _payment(values, wanted: dict[str, int | None], row: int, tnumber: str, site_id: str) -> dict[str, Any]:
    pay = {k: (_display(values[p]) if p is not None else "") for k, p in wanted.items()}
    date_pos = wanted["payment_date"]
    pay.update(row=row, tnumber=tnumber, site_id=site_id, payment_type=payment_type(pay["invoice_number"]),
               _amount=_amount(pay["payment_amount"]), _date=_date(values[date_pos]) if date_pos is not None else None)
    return pay


def _finish(gis: GisData, ops_tables: list[Table], source: Table | None) -> GisData:
    """Statistics and explanations shared by both modes."""
    linked = [k for k in gis.sites if k in gis.payments]
    unlisted = sorted(k for k in gis.payments if k not in gis.sites)
    gis.stats.update({
        "sites_in_site_list": len(gis.sites),
        "sites_with_coordinates": sum(s["has_coordinates"] for s in gis.sites.values()),
        "sites_with_payments": len(linked),
        "master_rows_linked_to_listed_sites": sum(len(gis.payments[k]) for k in linked),
        "paid_site_ids_not_in_site_list": len(unlisted),
        "unlisted_site_ids": [gis.payments[k][0]["site_id"] for k in unlisted][:200],
    })
    if not ops_tables:
        gis.notes.append("No Operational Site List Summary was supplied, so there are no sites to plot.")
    elif not any(s["has_coordinates"] for s in gis.sites.values()):
        gis.notes.append(
            "The Operational Site List Summary has no usable coordinates. Add latitude and longitude columns "
            "(e.g. 'Latitude'/'Longitude' or 'GPS_DEC_LATITUDE'/'GPS_DEC_LONGITUDE', decimal degrees or DMS) or one "
            "'Coordinates' column ('lat, long') to plot sites on the map. Coordinate columns found: "
            + "; ".join(gis.stats["coordinate_columns"]) + "."
        )
    if source is not None:
        missing = [f for f, h in gis.fields.items() if h is None]
        if missing:
            label = "Source file" if gis.mode == DERIVED else "Payment file"
            gis.notes.append(f"{label} columns not found for: " + ", ".join(missing).replace("_", " ") + ".")
    return gis


def build_gis(source: Table, ops_tables: list[Table], result: EngineResult, formats: IdentifierFormats) -> GisData:
    """GIS data for a derivation job: master-database rows are linked to sites by their derived SITE ID."""
    gis = GisData(mode=DERIVED, payment_file=source.file_name)
    _load_sites(gis, ops_tables, formats)
    wanted = _payment_fields(gis, source)
    for r in result.records:
        pay = _payment(source.df.iloc[r.row_index], wanted, r.row_number, r.outcome.tnumber, r.outcome.site_id)
        gis.all_payments.append(pay)
        if r.outcome.site_id:
            gis.payments.setdefault(site_key(r.outcome.site_id), []).append(pay)
    return _finish(gis, ops_tables, source)


def build_gis_direct(source: Table | None, ops_tables: list[Table], formats: IdentifierFormats) -> GisData:
    """GIS data without T-number derivation.

    A payment row is linked to a site by its own Site ID column when present and valid, otherwise when its
    Vendor Site Code equals exactly one site's Account Number in the Operational Site List. The T-number shown
    is the payment file's own T-number column, if it has one.
    """
    gis = GisData(mode=DIRECT, payment_file=source.file_name if source is not None else None)
    accounts = _load_sites(gis, ops_tables, formats)
    wanted = _payment_fields(gis, source)
    if source is None:
        gis.notes.append("No payment file was supplied, so the map shows site details only.")
        return _finish(gis, ops_tables, source)

    c = source.columns
    site_col, code_col, t_col = c.get("SITE_ID"), c.get("VENDOR_SITE_CODE", c.get("VENDOR_SITE")), c.get("T_NUMBER")
    by_site_id = by_account = ambiguous = unlinked = 0
    for i in range(source.row_count):
        values = source.df.iloc[i]
        key = site_id = ""
        if site_col is not None:
            site_id, ok = formats.site_id(cell_text(values[site_col]))
            key = site_key(site_id) if site_id and ok else ""
            by_site_id += bool(key)
        if not key and code_col is not None:
            hits = accounts.get(match_key(values[code_col]), set())
            if len(hits) == 1:
                key = next(iter(hits))
                site_id = gis.sites[key]["site_id"]
                by_account += 1
            elif hits:
                ambiguous += 1
        tnumber = match_key(values[t_col]) if t_col is not None else ""
        pay = _payment(values, wanted, source.row_numbers[i], tnumber, site_id if key else "")
        gis.all_payments.append(pay)
        if not key:
            unlinked += 1
            continue
        gis.payments.setdefault(key, []).append(pay)
    gis.stats.update(payment_rows=source.row_count, linked_by_site_id=by_site_id, linked_by_account_number=by_account,
                     ambiguous_account_numbers=ambiguous, unlinked_payment_rows=unlinked)
    gis.notes.append(
        f"Without T-number derivation: {by_site_id + by_account} of {source.row_count} payment row(s) linked to a site "
        f"({by_site_id} by Site ID, {by_account} by Vendor Site Code = Account Number); {unlinked} not linked."
        + (f" {ambiguous} row(s) match an Account Number listed under several Site IDs and were not linked." if ambiguous else "")
    )
    return _finish(gis, ops_tables, source)
