"""Output workbook structure, preservation of source data and formula-injection protection."""
from __future__ import annotations

import datetime as dt
import io

from openpyxl import load_workbook

from app.output.writer import DERIVED_COLUMNS, to_csv
from samples import synthetic as syn

SHEETS = ["Master Database", "Mapping Summary", "Exceptions", "Processing Summary", "Rule Audit"]


def _master(res):
    return load_workbook(io.BytesIO(res.outputs["master"].content))


def test_output_worksheet_names(run):
    assert _master(run()).sheetnames == SHEETS


def test_headers_frozen_and_derived_columns_in_order(run):
    ws = _master(run())["Master Database"]
    header = [c.value for c in ws[1]]
    assert ws.freeze_panes == "A2"
    assert header == syn.BASE_HEADER + DERIVED_COLUMNS


def test_all_source_rows_and_values_preserved(run):
    res = run()
    ws = _master(res)["Master Database"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    source = syn.base_rows_for_sheet()
    assert len(rows) == len(source) == res.summary["results"]["output_rows"]
    as_excel = lambda v: dt.datetime(v.year, v.month, v.day) if type(v) is dt.date else v  # Excel stores dates as datetimes
    for out, src in zip(rows, source):
        assert list(out[: len(src)]) == [as_excel(v) for v in src]


def test_derived_values_in_master(run):
    ws = _master(run())["Master Database"]
    n = len(syn.BASE_HEADER)
    got = [(r[n], r[n + 1] or "") for r in ws.iter_rows(min_row=2, values_only=True)]
    assert got == [(t, s) for _, _, t, s in syn.BASE_ROWS]


def test_formula_text_is_stored_as_text_not_formula(run):
    ws = _master(run())["Master Database"]
    cell = ws["E2"]
    assert cell.value.startswith("=HYPERLINK") and cell.data_type == "s"


def test_csv_reports_neutralise_formulas():
    out = to_csv(["a", "b", "c"], [["=1+1", "-12.5", "@cmd"]]).decode("utf-8-sig")
    assert "'=1+1" in out and ",-12.5," in out and "'@cmd" in out


def test_csv_report_format(run):
    res = run(fmt="csv")
    assert res.outputs["mapping"].filename.endswith(".csv")
    assert res.outputs["exceptions"].content.decode("utf-8-sig").startswith("Category,Severity")
    assert res.outputs["master"].filename.endswith(".xlsx")


def test_rule_audit_and_summary_content(run):
    wb = _master(run())
    audit = {r[0]: r for r in wb["Rule Audit"].iter_rows(min_row=2, values_only=True)}
    assert audit["R7"][12] == "Requires business confirmation"
    assert audit["R2"][8] >= 1  # successful matches
    metrics = {r[0]: r[1] for r in wb["Processing Summary"].iter_rows(min_row=2, values_only=True) if r[0]}
    assert metrics["input_rows"] == len(syn.BASE_ROWS)
    assert "tnumber_match_rate_pct" in metrics


def test_exceptions_sheet_lists_unresolved_records(run):
    wb = _master(run())
    cats = {r[0] for r in wb["Exceptions"].iter_rows(min_row=2, values_only=True)}
    assert {
        "UNRESOLVED_TNUMBER", "UNRESOLVED_SITE_ID", "AMBIGUOUS_REFERENCE_MAPPING", "MULTIPLE_CANDIDATE_IDENTIFIERS",
        "RESOLVED_BY_PRIORITY", "UNVERIFIED_IDENTIFIER", "RULE_REQUIRES_CONFIRMATION",
    } <= cats


def test_no_banking_or_vendor_enrichment_columns(run):
    header = [c.value for c in _master(run())["Master Database"][1]]
    for banned in ("Bank Name", "Bank Num", "Bank Account Num", "Bank Account Name"):
        assert banned not in header
