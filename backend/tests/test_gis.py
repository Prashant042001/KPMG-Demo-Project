"""GIS view: Operational Site List sites linked to master-database payment rows (synthetic data only)."""
from __future__ import annotations

import datetime as dt
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.gis import _coordinate, _split_coordinates, site_key
from samples import synthetic as syn

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def gis(run):
    return run().gis


def test_sites_come_from_operational_site_list_with_coordinates(gis):
    summary = gis.summary()
    by_id = {s["site_id"]: s for s in summary["sites"]}
    assert set(by_id) == {"6600", "X8754", "9001", "6542", "3133", "8646", "7777", "5555"}
    assert by_id["6542"]["region"] == "Synthetic Coast" and by_id["6542"]["property_owner"] == "Synthetic Owner G"
    assert (by_id["6542"]["lat"], by_id["6542"]["lon"]) == (-29.8587, 31.0218)
    assert by_id["8646"]["lat"] == -33.96  # decimal comma parsed
    assert by_id["5555"]["has_coordinates"] is False and by_id["5555"]["lat"] is None
    assert summary["stats"]["sites_with_coordinates"] == 7


def test_sites_are_linked_to_master_payment_rows_by_site_id(gis):
    detail = gis.site("9001")
    assert detail["site"]["tnumber"] == "T9001"
    assert detail["site"]["payment_count"] == 2  # SYN-001 appears twice in the source
    pay = detail["payments"][0]
    assert set(pay) >= {"vendor_name", "vendor_site_code", "payment_date", "payment_amount", "row", "tnumber"}
    assert pay["vendor_site_code"] == "SYN-001" and pay["vendor_name"].startswith("Synthetic Vendor")
    assert pay["payment_date"].startswith("2025-")
    assert detail["site"]["payment_total"] == round(sum(float(p["payment_amount"]) for p in detail["payments"]), 2)
    assert detail["fields"] == {"vendor_name": "Vendor Name", "vendor_site_code": "VENDOR_SITE_CODE",
                                "payment_date": "Payment Date", "payment_amount": "Payment Amount",
                                "invoice_number": "INVOICE_NUM"}


# ---------------------------------------------------------------- quarterly chart
def test_quarterly_chart_splits_rental_and_electricity(run):
    header = ["Invoice Number", "VENDOR_SITE_CODE", "Vendor Name", "Payment Date", "Payment Amount"]
    rows = [["PN-1", "T6542", "V", dt.date(2025, 1, 15), 100],      # Q1 rental
            ["INV-2", "T6542", "V", "2025-02-01", "50.5"],           # Q1 electricity (text date)
            ["PN-3", "T6542", "V", "15/08/2025", "1,000"],           # Q3 rental (d/m/Y)
            ["INV-4", "3133MTN", "V", dt.date(2025, 12, 31), 7],     # Q4 electricity, another site
            ["PN-5", "T6542", "V", dt.date(2024, 3, 1), 999],        # other year: excluded
            ["INV-6", "T6542", "V", None, 5]]                        # no date: excluded
    gis = run(source=syn.base_workbook(rows, header=header)).gis
    overall = {q["quarter"]: q for q in gis.summary()["chart"]["quarters"]}
    assert (overall["Q1"]["rental"], overall["Q1"]["electricity"]) == (100.0, 50.5)
    assert (overall["Q3"]["rental"], overall["Q4"]["electricity"], overall["Q2"]["rental"]) == (1000.0, 7.0, 0.0)
    site = {q["quarter"]: q for q in gis.site("6542")["chart"]["quarters"]}
    assert site["Q4"]["electricity"] == 0.0 and site["Q3"]["rental_count"] == 1
    assert gis.site("6542")["payments"][0]["payment_type"] == "Rental + Fixed"
    assert gis.summary()["chart"]["year"] == 2025 and gis.summary()["chart"]["has_dates"]


def test_site_without_payments_and_unlisted_paid_sites(gis):
    assert gis.site("7777")["site"]["payment_count"] == 0
    stats = gis.summary()["stats"]
    assert "8102" in stats["unlisted_site_ids"]  # paid (ABC-T8102-RENT) but not in the site list
    unlisted = gis.site("8102")
    assert unlisted["site"]["in_site_list"] is False and unlisted["site"]["payment_count"] == 1
    assert gis.site("424242") is None


def test_site_key_ignores_leading_zeros():
    assert site_key("0123") == site_key("123") and site_key("x8754") == "X8754"


@pytest.mark.parametrize("value,expected", [(-26.2, -26.2), ("-26,2041", -26.2041), ("−26.5", -26.5), ("28.03°", 28.03), ("abc", None)])
def test_coordinate_parsing(value, expected):
    assert _coordinate(value) == expected


def test_combined_coordinates_column(run):
    ops = syn.ops_workbook([["OPS-1", "6542", "Synthetic", "R", "O", "-29.85, 31.02"]],
                           header=["Account Number", "Site ID", "Site Name", "Region", "Property Owner", "Coordinates"])
    site = run(ops=ops).gis.site("6542")["site"]
    assert (site["lat"], site["lon"]) == (-29.85, 31.02)
    assert _split_coordinates("bad") == (None, None)


def test_gps_decimal_columns_are_preferred_over_other_coordinate_columns(run):
    header = ["Account Number", "Site ID", "GPS_LATITUDE", "GPS_LONGITUDE", "GPS_DEC_LATITUDE", "GPS_DEC_LONGITUDE"]
    ops = syn.ops_workbook([["OPS-1", "6542", "29 51 31 S", "31 01 18 E", -29.8587, 31.0218]], header=header)
    gis = run(ops=ops).gis
    assert (gis.site("6542")["site"]["lat"], gis.site("6542")["site"]["lon"]) == (-29.8587, 31.0218)
    assert "GPS_DEC_LATITUDE / GPS_DEC_LONGITUDE" in gis.summary()["stats"]["coordinate_columns"][0]


@pytest.mark.parametrize("value,expected", [("26°12'15\"S", -26.204167), ("S 26 12 15", -26.204167), ("28.03 E", 28.03),
                                            ("18°25'E", 18.416667), ("26 75 00 S", None), ("N 26 S", None)])
def test_dms_coordinate_parsing(value, expected):
    assert _coordinate(value) == expected


def test_no_coordinates_is_explained(run):
    ops = syn.ops_workbook([["OPS-1", "6542", "Synthetic"]], header=["Account Number", "Site ID", "Site Name"])
    notes = " ".join(run(ops=ops).gis.summary()["notes"])
    assert "no usable coordinates" in notes and "Latitude" in notes


def test_no_site_list_is_explained(run):
    summary = run(ops=False).gis.summary()
    assert summary["sites"] == [] and "No Operational Site List Summary" in " ".join(summary["notes"])


def test_missing_payment_columns_are_reported(run):
    source = syn.base_workbook([["I-1", "T6542", 1]], header=["INVOICE_NUM", "VENDOR_SITE_CODE", "AMOUNT"])
    gis = run(source=source).gis
    assert gis.fields["payment_date"] is None and gis.fields["vendor_site_code"] == "VENDOR_SITE_CODE"
    assert "Source file columns not found for: vendor name, payment date, payment amount" in " ".join(gis.summary()["notes"])
    assert gis.site("6542")["site"]["payment_count"] == 1  # the link still works without payment columns


# ---------------------------------------------------------------- API
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _completed_job(client) -> str:
    files = [("source_file", ("src.xlsx", syn.base_workbook(), XLSX)),
             ("supporting_files", ("b.xlsx", syn.bts_workbook(), XLSX)),
             ("supporting_files", ("o.xlsx", syn.ops_workbook(), XLSX))]
    job_id = client.post("/api/process", files=files).json()["job_id"]
    for _ in range(300):
        if client.get(f"/api/jobs/{job_id}").json()["status"] == "completed":
            return job_id
        time.sleep(0.1)
    raise AssertionError("job did not complete")


def test_gis_endpoints(client):
    job_id = _completed_job(client)
    body = client.get(f"/api/jobs/{job_id}/gis").json()
    assert len(body["sites"]) == 8 and body["stats"]["sites_with_payments"] >= 4
    detail = client.get(f"/api/jobs/{job_id}/gis/sites/9001").json()
    assert detail["site"]["site_id"] == "9001" and detail["payments"]
    assert client.get(f"/api/jobs/{job_id}/gis/sites/424242").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/gis/sites/bad%20id").status_code == 422


def test_gis_needs_a_master_database_run(client):
    assert client.get("/api/jobs/" + "c" * 32 + "/gis").status_code == 404


# ---------------------------------------------------------------- without T-number derivation
def _direct(rule_config, settings, payments=None, ops=None):
    from app.ingest.readers import UploadedFile
    from app.services.pipeline import run_gis_direct

    pay = UploadedFile("payments.xlsx", payments, "source") if payments is not None else None
    return run_gis_direct(rule_config, settings, pay, [UploadedFile("sites.xlsx", ops or syn.ops_workbook(), "supporting")])[1]


def test_direct_gis_with_site_list_only(rule_config, settings):
    gis = _direct(rule_config, settings)
    summary = gis.summary()
    assert summary["mode"] == "direct" and len(summary["sites"]) == 8 and summary["stats"]["sites_with_coordinates"] == 7
    assert gis.site("6542")["site"]["payment_count"] == 0 and "site details only" in " ".join(summary["notes"])


def test_direct_gis_links_payments_by_site_id_then_account_number(rule_config, settings):
    header = ["Vendor Name", "VENDOR_SITE_CODE", "Site ID", "T number", "Payment Date", "Payment Amount"]
    rows = [["V1", "anything", "6542", "T6542", "2025-01-01", "100"],
            ["V2", "OPS-9001", None, None, "2025-02-01", "50.5"],   # Account Number of site 9001
            ["V3", "OPS-9001", "", "", "2025-03-01", "49.5"],
            ["V4", "NO-MATCH", None, None, "2025-04-01", "1"]]
    gis = _direct(rule_config, settings, payments=syn.base_workbook(rows, header=header))
    assert gis.site("6542")["site"]["payment_count"] == 1 and gis.site("6542")["site"]["tnumber"] == "T6542"
    site = gis.site("9001")
    assert site["site"]["payment_count"] == 2 and site["site"]["payment_total"] == 100.0 and site["site"]["tnumber"] is None
    stats = gis.summary()["stats"]
    assert (stats["linked_by_site_id"], stats["linked_by_account_number"], stats["unlinked_payment_rows"]) == (1, 2, 1)


def test_direct_gis_requires_a_site_list(rule_config, settings):
    from app.core.errors import FileValidationError

    with pytest.raises(FileValidationError):
        _direct(rule_config, settings, ops=syn.bts_workbook())


def test_direct_gis_endpoint(client):
    files = [("supporting_files", ("o.xlsx", syn.ops_workbook(), XLSX)), ("source_file", ("src.xlsx", syn.base_workbook(), XLSX))]
    res = client.post("/api/gis", files=files)
    assert res.status_code == 200 and res.json()["mode"] == "direct"
    job_id = res.json()["job_id"]
    body = client.get(f"/api/jobs/{job_id}/gis").json()
    assert body["mode"] == "direct" and len(body["sites"]) == 8
    assert client.get(f"/api/jobs/{job_id}/gis/sites/6600").json()["site"]["payment_count"] >= 1  # ACC-500 = source code
    assert client.post("/api/gis", files=[("source_file", ("src.xlsx", syn.base_workbook(), XLSX))]).status_code == 422
