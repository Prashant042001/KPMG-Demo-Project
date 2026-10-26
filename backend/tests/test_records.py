"""Searchable / filterable results table (GET /api/jobs/{job_id}/records)."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.derivation.engine import CANNOT_BE_DERIVED
from app.main import app
from app.services.records import filter_records
from samples import synthetic as syn

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def rows(run):
    return run().records


def test_every_source_row_is_available(run):
    res = run()
    assert len(res.records) == len(syn.BASE_ROWS) == res.result.metrics["input_rows"]


def test_search_by_t_number_vendor_site_code_and_site_id(rows):
    assert {r["vendor_site_code"] for r in filter_records(rows, q="t4908")["rows"]} >= {"4908MTN"}
    assert [r["tnumber"] for r in filter_records(rows, q="3133MTN")["rows"]] == ["T3133"]
    assert all("6542" in (r["site_id"] + r["vendor_site_code"]) for r in filter_records(rows, q="6542")["rows"])


def test_search_ignores_case_and_spacing(rows):
    assert filter_records(rows, q="  t8646 / elec ")["matching_rows"] == 1


def test_search_by_row_number(rows):
    first = rows[0]["row"]
    assert filter_records(rows, q=str(first))["rows"][0]["row"] == first


def test_status_filters(rows):
    unresolved = filter_records(rows, status="tnumber_unresolved", page_size=500)["rows"]
    assert unresolved and all(r["tnumber"] == CANNOT_BE_DERIVED for r in unresolved)
    derived = filter_records(rows, status="tnumber_derived", page_size=500)["rows"]
    assert len(derived) + len(unresolved) == len(rows)
    assert all(r["conflict"] for r in filter_records(rows, status="conflict", page_size=500)["rows"])
    assert all(not r["site_id"] for r in filter_records(rows, status="site_id_unresolved", page_size=500)["rows"])


def test_counts_follow_the_search(rows):
    res = filter_records(rows, q="MTN")
    assert res["counts"]["all"] == res["matching_rows"]
    assert res["counts"]["tnumber_derived"] + res["counts"]["tnumber_unresolved"] == res["counts"]["all"]


def test_rule_filter(rows):
    res = filter_records(rows, rule="r3", page_size=500)
    assert res["rows"] and all("R3" in (r["tnumber_rule"], r["site_id_rule"]) for r in res["rows"])
    assert "R3" in res["rules"]


def test_overridden_filter(derive):
    res, _ = derive([("T5000", ""), ("T6542", "")], bts_rows=[["T5000", "T5001", "", "a"]])
    out = filter_records(res.records, status="overridden")
    assert [r["vendor_site_code"] for r in out["rows"]] == ["T5000"]


def test_pagination(rows):
    p1 = filter_records(rows, page=1, page_size=10)
    p3 = filter_records(rows, page=3, page_size=10)
    assert len(p1["rows"]) == 10 and p1["pages"] == -(-len(rows) // 10)
    assert p3["rows"][0]["row"] == rows[20]["row"]
    assert filter_records(rows, page=999, page_size=10)["page"] == p1["pages"]  # clamped to last page


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


def test_records_endpoint(client):
    job_id = _completed_job(client)
    body = client.get(f"/api/jobs/{job_id}/records", params={"q": "mtn", "status": "tnumber_derived", "page_size": 5}).json()
    assert body["total_rows"] == len(syn.BASE_ROWS)
    assert len(body["rows"]) <= 5 and all(r["tnumber"] != CANNOT_BE_DERIVED for r in body["rows"])
    assert client.get(f"/api/jobs/{job_id}").json()["record_count"] == len(syn.BASE_ROWS)


def test_records_endpoint_validates_parameters(client):
    job_id = _completed_job(client)
    assert client.get(f"/api/jobs/{job_id}/records", params={"status": "bogus"}).status_code == 422
    assert client.get(f"/api/jobs/{job_id}/records", params={"page_size": 5000}).status_code == 422
    assert client.get(f"/api/jobs/{job_id}/records", params={"rule": "R1;DROP"}).status_code == 422


def test_records_not_available_for_unknown_job(client):
    assert client.get("/api/jobs/" + "b" * 32 + "/records").status_code == 404
