"""Generate the master workbook and the separate mapping / exception reports.

Formula-injection protection:
* XLSX: every text cell is written with an explicit string type, so values such as ``=HYPERLINK(...)``
  are stored and displayed literally and never evaluated. The original text is preserved exactly.
* CSV: text beginning with ``= + - @`` (or tab / carriage return) is prefixed with an apostrophe, as
  recommended by OWASP, because spreadsheet applications interpret CSV cells on open.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import threading
from typing import Any, Callable, Iterable, Iterator

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.derivation.engine import EngineResult, RecordResult
from app.ingest.readers import Table
from app.output.master_layout import MASTER_COLUMNS, MASTER_HEADERS, master_layout_rows
from app.rules.loader import RuleSet

EXCEL_MAX_ROWS = 1_048_576

# Derived fields and traceability fields, written per source row to the Derivation Trace sheet.
DERIVED_COLUMNS = [
    "TNUMBER",
    "SITE ID",
    "Original Vendor Site Code",
    "Original VENDOR_SITE_CODE_ALT",
    "Candidate T-number(s)",
    "T-number Rule ID",
    "Site ID Rule ID",
    "T-number Derivation Source",
    "Site ID Derivation Source",
    "T-number Derivation Status",
    "Site ID Derivation Status",
    "Conflict Indicator",
    "Exception Reason",
]
TRACE_COLUMNS = ["Source Row", *DERIVED_COLUMNS]
TRACE_WIDTHS = [10, 18, 12, 24, 24, 20, 12, 12, 48, 48, 20, 20, 10, 70]
MAPPING_COLUMNS = [
    "Source Row", "Source Dataset", "Source File", "Source Field", "Original Source Value", "Matching Key",
    "Derived T-number", "Derived Site ID", "Rule ID", "Mapping Status", "Derivation Source", "Note",
]
EXCEPTION_COLUMNS = [
    "Category", "Severity", "Source Row", "Rule ID", "Source File", "Field", "Original Value", "Detail",
]
RULE_AUDIT_COLUMNS = [
    "Rule ID", "Rule Description", "Data Source", "Column Name", "Matching Column", "Engine Rule Kind", "Priority",
    "Records Evaluated", "Successful Matches", "Selected for TNUMBER", "Selected for SITE ID", "Exceptions",
    "Confirmation Status", "Status Detail", "Additional Info",
]

HEADER_FILL = PatternFill("solid", fgColor="00338D")  # KPMG blue
DERIVED_FILL = PatternFill("solid", fgColor="0091DA")
HEADER_FONT = Font(bold=True, color="FFFFFF")


class OutputFile:
    """A downloadable output. Content can be supplied eagerly or built lazily on first access (then cached)."""

    def __init__(self, filename: str, media_type: str, content: bytes | Callable[[], bytes]):
        self.filename = filename
        self.media_type = media_type
        self._content = content
        self._lock = threading.Lock()

    @property
    def content(self) -> bytes:
        with self._lock:
            if callable(self._content):
                self._content = self._content()
            return self._content


XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MEDIA = "text/csv"


class _Sanitiser:
    def __init__(self) -> None:
        self.illegal_chars_removed = 0

    def xlsx(self, ws, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        if isinstance(value, (int, float, bool, dt.datetime, dt.date, dt.time)):
            return value
        text = str(value)
        if ILLEGAL_CHARACTERS_RE.search(text):
            self.illegal_chars_removed += 1
            text = ILLEGAL_CHARACTERS_RE.sub("", text)
        if not text.startswith("="):
            return text  # openpyxl stores any other text as a plain string
        cell = WriteOnlyCell(ws, value=text)
        cell.data_type = "s"  # never a formula
        return cell


def _header_row(ws, headers: list[str], derived: set[int] | None = None) -> list:
    cells = []
    for i, h in enumerate(headers):
        c = WriteOnlyCell(ws, value=h)
        c.data_type = "s"
        c.font = HEADER_FONT
        c.fill = DERIVED_FILL if derived and i in derived else HEADER_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
        cells.append(c)
    return cells


def _sheet(wb: Workbook, title: str, headers: list[str], widths: list[int], derived: set[int] | None = None):
    ws = wb.create_sheet(title)
    ws.freeze_panes = "A2"
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    if headers:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
    ws.append(_header_row(ws, headers, derived))
    return ws


def _write_rows(ws, rows: Iterable[list[Any]], san: _Sanitiser, limit: int = EXCEL_MAX_ROWS - 1) -> int:
    written = 0
    for row in rows:
        if written >= limit:
            break
        ws.append([san.xlsx(ws, v) for v in row])
        written += 1
    return written


# ----------------------------------------------------------------------------------------------- row builders
def derived_values(r: RecordResult) -> list[Any]:
    o = r.outcome
    return [
        o.tnumber,
        o.site_id or None,
        r.vendor_site_code or None,
        r.vendor_site_code_alt or None,
        o.candidate_tnumbers or None,
        o.t_rule or None,
        o.site_rule or None,
        o.t_source or None,
        o.site_source or None,
        o.t_status,
        o.site_status,
        "Y" if r.conflict else "N",
        r.exception_reason or None,
    ]


def trace_rows(result: EngineResult) -> Iterator[list[Any]]:
    for rec in result.records:
        yield [rec.row_number, *derived_values(rec)]


def mapping_rows(result: EngineResult) -> Iterator[list[Any]]:
    for rec in result.records:
        for c, status in rec.outcome.candidates:
            yield [
                rec.row_number, c.dataset, c.source_file, c.source_field, c.original_value, c.matching_key,
                c.tnumber, c.site_id, c.rule_id, status,
                c.source + (" (T + Site ID)" if c.t_composed else ""), c.note or None,
            ]
        if not rec.outcome.candidates:
            yield [rec.row_number, "Source file", "", "VENDOR_SITE_CODE", rec.vendor_site_code, "", None, None, "",
                   "NO MATCH", "", "No configured rule matched this record"]


def exception_rows(result: EngineResult) -> Iterator[list[Any]]:
    for e in result.exceptions:
        yield [e.category, e.severity, e.row_number, e.rule_id or None, e.source_file or None,
               e.field or None, e.original_value or None, e.detail]


def rule_audit_rows(ruleset: RuleSet, result: EngineResult) -> Iterator[list[Any]]:
    for rule in sorted(ruleset.rules, key=lambda r: (r.priority, r.order)):
        st = result.rule_stats.get(rule.rule_id)
        status, reason = result.rule_runtime_status.get(rule.rule_id, (rule.status, rule.status_reason))
        confirmation = {
            "ACTIVE": "Confirmed - executed",
            "DUPLICATE": "Duplicate - not executed separately",
        }.get(status, "Requires business confirmation" if status != "SOURCE_UNAVAILABLE" else "Confirmed - source unavailable")
        yield [
            rule.rule_id, rule.description or None, rule.data_source or None, rule.column_name or None,
            rule.matching_column or None, rule.kind.value if rule.kind else "UNRECOGNISED", rule.priority,
            st.evaluated if st else 0, st.matched if st else 0, st.selected_t if st else 0,
            st.selected_site if st else 0, st.exceptions if st else 0, confirmation,
            f"{status}: {reason}" if reason else status, rule.additional_info or None,
        ]


def summary_rows(summary: dict[str, Any]) -> Iterator[list[Any]]:
    for section, items in summary.items():
        yield [section.upper(), None]
        if isinstance(items, dict):
            for k, v in items.items():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        yield [f"{k}: {k2}", v2]
                else:
                    yield [k, v if not isinstance(v, list) else "; ".join(map(str, v))]
        elif isinstance(items, list):
            for v in items:
                yield [None, v if not isinstance(v, dict) else ", ".join(f"{a}={b}" for a, b in v.items())]
        yield [None, None]


# ----------------------------------------------------------------------------------------------- builders
def build_master_workbook(
    source: Table, ruleset: RuleSet, result: EngineResult, summary: dict[str, Any], sites: dict[str, dict[str, Any]]
) -> tuple[bytes, dict[str, int]]:
    """``sites``: Operational Site List sites keyed by ``site_key`` (from the GIS build), for the operational columns."""
    san = _Sanitiser()
    wb = Workbook(write_only=True)
    truncated: dict[str, int] = {}

    widths = [min(max(len(h) + 4, 12), 40) for h in MASTER_HEADERS]
    derived = {i for i, (_, kind, _) in enumerate(MASTER_COLUMNS) if kind == "derived"}
    ws = _sheet(wb, "Master Database", MASTER_HEADERS, widths, derived)
    _write_rows(ws, master_layout_rows(source, result, sites), san)
    ws = _sheet(wb, "Derivation Trace", TRACE_COLUMNS, TRACE_WIDTHS, set(range(1, 3)))
    _write_rows(ws, trace_rows(result), san)

    n_map = sum(max(len(r.outcome.candidates), 1) for r in result.records)
    ws = _sheet(wb, "Mapping Summary", MAPPING_COLUMNS, [10, 26, 30, 34, 26, 20, 16, 14, 9, 28, 60, 60])
    if _write_rows(ws, mapping_rows(result), san) < n_map:
        truncated["Mapping Summary"] = n_map
    ws = _sheet(wb, "Exceptions", EXCEPTION_COLUMNS, [30, 10, 10, 9, 30, 30, 26, 90])
    if _write_rows(ws, exception_rows(result), san) < len(result.exceptions):
        truncated["Exceptions"] = len(result.exceptions)

    ws = _sheet(wb, "Processing Summary", ["Metric", "Value"], [48, 80])
    _write_rows(ws, summary_rows(summary), san)
    ws = _sheet(wb, "Rule Audit", RULE_AUDIT_COLUMNS, [8, 70, 26, 22, 22, 18, 9, 10, 10, 10, 10, 10, 30, 70, 50])
    _write_rows(ws, rule_audit_rows(ruleset, result), san)

    buf = io.BytesIO()
    wb.save(buf)
    stats = {"illegal_characters_removed": san.illegal_chars_removed, **{f"truncated_{k}": v for k, v in truncated.items()}}
    return buf.getvalue(), stats


def build_single_sheet(title: str, headers: list[str], widths: list[int], rows: Iterable[list[Any]], fmt: str) -> bytes:
    if fmt == "csv":
        return to_csv(headers, rows)
    san = _Sanitiser()
    wb = Workbook(write_only=True)
    ws = _sheet(wb, title, headers, widths)
    _write_rows(ws, rows, san)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_CSV_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_CSV_TRIGGERS):
        try:
            float(value)  # plain negative/positive numbers are harmless
            return value
        except ValueError:
            return "'" + value
    return value


def to_csv(headers: list[str], rows: Iterable[list[Any]]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(headers)
    for row in rows:
        w.writerow([_csv_safe(v) for v in row])
    return buf.getvalue().encode("utf-8-sig")


def build_mapping_report(result: EngineResult, fmt: str) -> bytes:
    return build_single_sheet("Mapping Summary", MAPPING_COLUMNS, [10, 26, 30, 34, 26, 20, 16, 14, 9, 28, 60, 60],
                              mapping_rows(result), fmt)


def build_exception_report(result: EngineResult, fmt: str) -> bytes:
    return build_single_sheet("Exceptions", EXCEPTION_COLUMNS, [30, 10, 10, 9, 30, 30, 26, 90],
                              exception_rows(result), fmt)
