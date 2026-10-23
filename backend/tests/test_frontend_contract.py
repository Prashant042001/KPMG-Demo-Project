"""Static contract checks between the React front end and the API (no JS test runner is configured)."""
from __future__ import annotations

import re
from pathlib import Path

from app.main import app

SRC = Path(__file__).resolve().parents[2] / "src"


def _read(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def test_ui_has_exactly_two_upload_sections():
    app_jsx = _read("App.jsx")
    titles = re.findall(r"<UploadCard\s+title=\"([^\"]+)\"", app_jsx)
    assert titles == ["Source File", "Supporting Data File(s)"]


def test_ui_never_requests_a_rules_workbook():
    combined = _read("App.jsx") + _read("api.js")
    for forbidden in ("rules_file", "Rules workbook", "T Number Rules workbook", "base_file"):
        assert forbidden not in combined


def test_frontend_form_fields_match_api_parameters():
    api_js = _read("api.js")
    sent = set(re.findall(r'form\.append\("([a-z_]+)"', api_js))
    assert sent == {"source_file", "supporting_files"}
    spec = app.openapi()
    for path in ("/api/validate", "/api/process"):
        ref = spec["paths"][path]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
        params = set(spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]["properties"])
        assert sent <= params, (path, params)
        assert "rules_file" not in params and "base_file" not in params


def test_only_source_file_is_mandatory_in_ui():
    app_jsx = _read("App.jsx")
    check = app_jsx[app_jsx.index("const localCheck"): app_jsx.index("const failRequest")]
    assert "source.length" in check and "support.length" not in check


def test_results_table_uses_records_endpoint_contract():
    from app.services.records import STATUS_FILTERS

    api_js, table = _read("api.js"), _read("ResultsTable.jsx")
    assert "/records?" in api_js
    line = next(ln for ln in api_js.splitlines() if "new URLSearchParams" in ln)
    sent = set(re.findall(r"\b(page_size|page|rule|status|q)\b(?=[,:} ])", line))
    params = {p["name"] for p in app.openapi()["paths"]["/api/jobs/{job_id}/records"]["get"]["parameters"]}
    assert sent == {"q", "status", "rule", "page", "page_size"}
    assert sent <= params
    ui_filters = set(re.findall(r'\["(\w+)", "[^"]+"\]', table))
    assert ui_filters == set(STATUS_FILTERS)
