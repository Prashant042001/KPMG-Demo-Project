"""Column layout of the Master Database sheet.

Each output column has one of these sources:

* ``derived``     – TNUMBER / SITE ID from the derivation engine (``NA`` when no T-number could be derived);
* ``base``        – copied unchanged from the source (base payment data) column with a matching header;
* ``operational`` – looked up in the Operational Site List Summary by the derived SITE ID (``NA`` when not found);
* ``random``      – synthetic demo values. They are generated deterministically from the vendor (vendor-level fields)
                    or the vendor site code (site / lease-level fields), so a vendor keeps the same details on every
                    row and in every run.
* ``rule``        – computed from other columns (Payment Type, Bank Account Name).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import random
import re
from typing import Any, Iterator

from app.core.text import cell_text, norm_header
from app.derivation.engine import CANNOT_BE_DERIVED, EngineResult
from app.ingest.readers import Table
from app.services.gis import payment_type, site_key

NA = "NA"

# (output header, source, extra source-header aliases for base columns)
MASTER_COLUMNS: list[tuple[str, str, tuple[str, ...]]] = [
    ("TNUMBER", "derived", ()),
    ("SITE ID", "derived", ()),
    ("Vendor Name", "base", ("suppliername",)),
    ("Vendor Site Code", "base", ("vendorsite",)),
    ("Vendor_Site_ID", "random", ()),
    ("Vendor ID", "random", ()),
    ("Payment Type", "rule", ()),
    ("Vat Registration Num", "random", ()),
    ("Bank Name", "random", ()),
    ("Bank Num", "random", ()),
    ("Bank Account Num", "random", ()),
    ("Bank Account Name", "rule", ()),
    ("Frequency Code", "random", ()),
    ("Payment Term Type Code", "random", ()),
    ("Rental RateFinal", "random", ()),
    ("Electricity", "random", ()),
    ("Escalation", "random", ()),
    ("VENDOR_NUMBER", "random", ()),
    ("COMPANY_REG", "random", ()),
    ("VENDOR_TYPE_LOOKUP_CODE", "random", ()),
    ("START_DATE_ACTIVE", "random", ()),
    ("END_DATE_ACTIVE", "random", ()),
    ("E-mail ID", "random", ()),
    ("Address", "random", ()),
    ("City", "random", ()),
    ("ZIP (4 Digit Only)", "random", ()),
    ("Province", "random", ()),
    ("Country", "random", ()),
    ("Phone", "random", ()),
    ("Lease Number", "random", ()),
    ("Lease Name", "random", ()),
    ("Lease Execution date", "random", ()),
    ("Lease start date", "random", ()),
    ("Termination Date", "random", ()),
    ("Invoice Number", "base", ("invoicenum", "invoiceno", "invoice")),
    ("Creation Date", "base", ()),
    ("Invoice Date", "base", ()),
    ("Invoice Amount", "base", ()),
    ("Invoice Currency Code", "base", ()),
    ("Payment Amount", "base", ("amountpaid",)),
    ("Payment Due Date", "base", ()),
    ("Rate Used On Payment Date", "base", ()),
    ("Rate Used On Invoice Date", "base", ()),
    ("Calculated Payment Amount ZAR", "base", ()),
    ("Payment Currency Code", "base", ()),
    ("Check Number", "base", ()),
    ("Payment Date", "base", ("checkdate", "paiddate")),
    ("Payment Process Request", "base", ()),
    ("Status Lookup Code", "base", ()),
    ("Status Date", "base", ()),
    ("Cleared Date", "base", ()),
    ("Payment Profile Name", "base", ()),
    ("PONum Approval Date", "base", ()),
    ("Pay Group", "base", ()),
    ("Concat", "base", ()),
    ("Release status", "base", ()),
    ("Release days from payment date", "base", ()),
    ("Payment analysis", "base", ()),
    ("Historical years payments released in current year", "base", ()),
    ("Site Status", "operational", ()),
    ("Site Name", "operational", ()),
    ("Site Owner", "operational", ()),
    ("Latitude", "operational", ()),
    ("Longitude", "operational", ()),
]
MASTER_HEADERS = [h for h, _, _ in MASTER_COLUMNS]
# Site-list field behind each operational column (see services/gis.py).
OPERATIONAL_FIELDS = {"Site Status": "site_status", "Site Name": "site_name", "Site Owner": "property_owner",
                      "Latitude": "lat", "Longitude": "lon"}

# ------------------------------------------------------------------------------------- synthetic value pools
BANKS = [("ABSA Bank", "632005"), ("Standard Bank", "051001"), ("First National Bank", "250655"), ("Nedbank", "198765"),
         ("Capitec Bank", "470010"), ("Investec Bank", "580105"), ("African Bank", "430000"), ("TymeBank", "678910")]
CITIES = [("Johannesburg", "Gauteng", "011"), ("Pretoria", "Gauteng", "012"), ("Cape Town", "Western Cape", "021"),
          ("Stellenbosch", "Western Cape", "021"), ("Durban", "KwaZulu-Natal", "031"), ("Pietermaritzburg", "KwaZulu-Natal", "033"),
          ("Gqeberha", "Eastern Cape", "041"), ("East London", "Eastern Cape", "043"), ("Bloemfontein", "Free State", "051"),
          ("Polokwane", "Limpopo", "015"), ("Mbombela", "Mpumalanga", "013"), ("Rustenburg", "North West", "014"),
          ("Kimberley", "Northern Cape", "053")]
STREETS = ["Main", "Church", "Station", "Voortrekker", "Long", "Market", "Jan Smuts", "Oak", "Kerk", "Beach", "Hill", "Park"]
STREET_TYPES = ["Road", "Street", "Avenue", "Drive", "Lane"]
PAYMENT_TERMS = ["IMMEDIATE", "NET 7", "NET 15", "NET 30", "NET 45", "NET 60"]
VENDOR_TYPES = ["LANDLORD", "VENDOR", "SUPPLIER", "UTILITY"]


def _rng(*parts: str) -> random.Random:
    """Deterministic random generator for a key (stable across runs, unlike ``hash()``)."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _date(r: random.Random, start: dt.date, end: dt.date) -> dt.date:
    return start + dt.timedelta(days=r.randint(0, (end - start).days))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", text.lower()).strip(".")[:30] or "vendor"


def vendor_values(vendor: str) -> dict[str, Any]:
    """Vendor-level synthetic fields: the same vendor always gets the same values."""
    r = _rng("vendor", vendor)
    bank, branch = r.choice(BANKS)
    city, province, area = r.choice(CITIES)
    active = _date(r, dt.date(2005, 1, 1), dt.date(2020, 12, 31))
    return {
        "Vendor ID": r.randint(100000, 999999),
        "Vat Registration Num": f"4{r.randint(0, 999_999_999):09d}",
        "Bank Name": bank,
        "Bank Num": branch,
        "Bank Account Num": f"{r.randint(10**9, 10**11 - 1)}",
        "VENDOR_NUMBER": r.randint(10000, 99999),
        "COMPANY_REG": f"{r.randint(1990, 2022)}/{r.randint(0, 999999):06d}/{r.choice(['07', '06', '21', '23'])}",
        "VENDOR_TYPE_LOOKUP_CODE": r.choice(VENDOR_TYPES),
        "START_DATE_ACTIVE": active,
        "END_DATE_ACTIVE": active + dt.timedelta(days=365 * r.randint(10, 25)),
        "E-mail ID": f"{_slug(vendor)}@example.com",
        "Address": f"{r.randint(1, 250)} {r.choice(STREETS)} {r.choice(STREET_TYPES)}",
        "City": city,
        "ZIP (4 Digit Only)": f"{r.randint(1, 9999):04d}",
        "Province": province,
        "Country": "South Africa",
        "Phone": f"+27 {area[1:]} {r.randint(100, 999)} {r.randint(1000, 9999)}",
    }


def site_values(site_code: str, lease_label: str) -> dict[str, Any]:
    """Vendor-site / lease-level synthetic fields: the same vendor site code always gets the same values."""
    r = _rng("site", site_code)
    execution = _date(r, dt.date(2008, 1, 1), dt.date(2022, 12, 31))
    start = execution + dt.timedelta(days=r.randint(15, 120))
    return {
        "Vendor_Site_ID": r.randint(1_000_000, 9_999_999),
        "Frequency Code": r.choice(["Monthly", "Annually"]),
        "Payment Term Type Code": r.choice(PAYMENT_TERMS),
        "Rental RateFinal": round(r.uniform(2_500, 65_000), 2),
        "Electricity": round(r.uniform(500, 18_000), 2),
        "Escalation": f"{r.choice([5, 6, 7, 7.5, 8, 9, 10])}%",
        "Lease Number": f"LSE-{r.randint(0, 999999):06d}",
        "Lease Name": f"{lease_label} Lease",
        "Lease Execution date": execution,
        "Lease start date": start,
        "Termination Date": start + dt.timedelta(days=365 * r.choice([5, 9, 10, 15, 20])),
    }


def _base_positions(source: Table) -> dict[str, int]:
    """Output header -> source column position, matched case- and punctuation-insensitively."""
    by_norm: dict[str, int] = {}
    for pos, h in enumerate(source.headers):
        by_norm.setdefault(norm_header(h), pos)
    found = {}
    for header, kind, aliases in MASTER_COLUMNS:
        if kind != "base":
            continue
        for name in (header, *aliases):
            if norm_header(name) in by_norm:
                found[header] = by_norm[norm_header(name)]
                break
    # Fall back to the resolved canonical columns (e.g. VENDOR_SITE_CODE, Vendor Site).
    canon = {"Vendor Name": "VENDOR_NAME", "Vendor Site Code": "VENDOR_SITE_CODE", "Payment Date": "PAYMENT_DATE",
             "Payment Amount": "PAYMENT_AMOUNT"}
    for header, key in canon.items():
        if header not in found:
            pos = source.columns.get(key, source.columns.get("VENDOR_SITE") if key == "VENDOR_SITE_CODE" else None)
            if pos is not None:
                found[header] = pos
    return found


def missing_base_columns(source: Table) -> list[str]:
    found = _base_positions(source)
    return [h for h, kind, _ in MASTER_COLUMNS if kind == "base" and h not in found]


def master_layout_rows(source: Table, result: EngineResult, sites: dict[str, dict[str, Any]]) -> Iterator[list[Any]]:
    """Rows of the Master Database sheet in ``MASTER_HEADERS`` order. ``sites`` is keyed by ``site_key``."""
    base = _base_positions(source)
    for values, rec in zip(source.df.itertuples(index=False, name=None), result.records):
        o = rec.outcome
        vendor = cell_text(values[base["Vendor Name"]]) if "Vendor Name" in base else ""
        code = rec.vendor_site_code or ""
        site = sites.get(site_key(o.site_id)) if o.site_id else None
        v = vendor_values(vendor or code)
        s = site_values(code or vendor, (site or {}).get("site_name") or code or vendor or "Site")
        row: list[Any] = []
        for header, kind, _ in MASTER_COLUMNS:
            if header == "TNUMBER":
                row.append(NA if o.tnumber == CANNOT_BE_DERIVED else o.tnumber)
            elif header == "SITE ID":
                row.append(o.site_id or None)
            elif kind == "base":
                row.append(values[base[header]] if header in base else None)
            elif kind == "operational":
                value = site.get(OPERATIONAL_FIELDS[header]) if site else None
                row.append(NA if value in (None, "") else value)
            elif header == "Payment Type":
                row.append(payment_type(values[base["Invoice Number"]]) if "Invoice Number" in base else None)
            elif header == "Bank Account Name":
                row.append(vendor or None)
            else:
                row.append(v[header] if header in v else s[header])
        yield row
