"""Assemble uploaded files into role-assigned tables and validate them.

There are exactly two kinds of upload:

* the **source file** – the dataset whose rows are processed and retained in the output (any filename);
* zero or more **supporting files** – optional reference data. Each worksheet is identified from its columns
  (BTS Site Report Schedule, Operational Site List Summary, Latest Payment Data); the filename is only a
  tie-breaker between roles a worksheet already qualifies for. A missing supporting dataset never blocks
  processing: the derivation steps that need it are skipped and reported.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.errors import FileValidationError
from app.core.text import norm_header
from app.ingest.columns import ColumnResolver
from app.ingest.readers import Table, UploadedFile, build_table, detect_header, read_raw_sheets

log = logging.getLogger(__name__)

SOURCE_ROLE = "source"
SUPPORTING_ROLES = ("bts", "ops", "latest_payment")


@dataclass
class SheetReport:
    sheet: str
    role: str | None
    header_row: int | None = None
    rows: int | None = None
    matched_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)


@dataclass
class FileReport:
    name: str
    slot: str  # "source" | "supporting"
    size_bytes: int
    status: str = "ok"  # ok | error | ignored
    role: str | None = None
    sheets: list[SheetReport] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


@dataclass
class InputBundle:
    source: Table | None = None
    references: dict[str, list[Table]] = field(default_factory=dict)  # role -> tables
    files: list[FileReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)  # labels of supporting datasets not supplied

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "files": [asdict(f) for f in self.files],
            "source_rows": self.source.row_count if self.source else None,
            "supporting_datasets": {r: len(t) for r, t in self.references.items()},
            "missing_supporting_datasets": self.missing_roles,
        }


class RoleSpec:
    def __init__(self, role: str, spec: dict[str, Any]):
        self.role = role
        self.label: str = spec.get("label", role)
        self.required: list[str] = spec.get("required", [])
        self.required_any: list[list[str]] = spec.get("required_any", [])
        self.optional: list[str] = spec.get("optional", [])
        self.hints: list[str] = [norm_header(h) for h in spec.get("filename_hints", [])]

    @property
    def keys(self) -> set[str]:
        return set(self.required) | set(self.optional) | {k for g in self.required_any for k in g}

    def missing(self, cols: dict[str, int]) -> list[str]:
        out = [k for k in self.required if k not in cols]
        out += [" or ".join(g) for g in self.required_any if not any(k in cols for k in g)]
        return out

    def score(self, cols: dict[str, int], file_name: str) -> float | None:
        """None unless every required column is present. The filename hint only breaks ties."""
        if self.missing(cols):
            return None
        hit = sum(k in cols for k in self.required) + len(self.required_any)
        hit += 0.5 * sum(k in cols for k in self.optional)
        if any(h and h in norm_header(file_name) for h in self.hints):
            hit += 0.25
        return hit


class InputAssembler:
    def __init__(self, rule_config: dict[str, Any], *, allowed_ext: set[str], scan_rows: int):
        self.resolver = ColumnResolver(rule_config["columns"])
        self.roles = {r: RoleSpec(r, s) for r, s in rule_config["file_roles"].items() if not r.startswith("_")}
        self.allowed_ext = allowed_ext
        self.scan_rows = scan_rows

    def label(self, role: str) -> str:
        return self.roles[role].label if role in self.roles else role

    def _source_sheet(self, f: UploadedFile, report: FileReport) -> Table | None:
        """Pick the worksheet of the source file that best satisfies the source role."""
        spec = self.roles[SOURCE_ROLE]
        best: tuple[float, int, Table] | None = None
        for sheet, raw in read_raw_sheets(f, self.allowed_ext).items():
            idx, cols = detect_header(raw, self.resolver, spec.keys, self.scan_rows)
            score = spec.score(cols, f.name) if idx >= 0 else None
            sr = SheetReport(sheet=sheet, role=None, missing_columns=spec.missing(cols))
            if score is not None:
                table = build_table(f.name, sheet, raw, idx, cols)
                sr.role, sr.header_row, sr.rows = SOURCE_ROLE, table.header_row, table.row_count
                sr.matched_columns = [table.headers[p] for p in sorted(cols.values()) if p < len(table.headers)]
                if best is None or (score, table.row_count) > (best[0], best[1]):
                    best = (score, table.row_count, table)
            report.sheets.append(sr)
        if best is None:
            return None
        chosen = best[2]
        for sr in report.sheets:  # only the chosen sheet keeps the role
            if sr.role and sr.sheet != chosen.sheet_name:
                sr.role = None
                report.messages.append(f"Worksheet '{sr.sheet}' also qualifies but was not used; '{chosen.sheet_name}' was selected.")
        return chosen

    def _classify_supporting(self, f: UploadedFile, report: FileReport) -> list[tuple[str, Table]]:
        found: list[tuple[str, Table]] = []
        for sheet, raw in read_raw_sheets(f, self.allowed_ext).items():
            best: tuple[float, str, int, dict[str, int]] | None = None
            for role in SUPPORTING_ROLES:
                spec = self.roles[role]
                idx, cols = detect_header(raw, self.resolver, spec.keys, self.scan_rows)
                score = spec.score(cols, f.name) if idx >= 0 else None
                if score is not None and (best is None or score > best[0]):
                    best = (score, role, idx, cols)
            if best is None:
                report.sheets.append(SheetReport(sheet=sheet, role=None))
                continue
            _, role, idx, cols = best
            table = build_table(f.name, sheet, raw, idx, cols)
            report.sheets.append(
                SheetReport(
                    sheet=sheet,
                    role=role,
                    header_row=table.header_row,
                    rows=table.row_count,
                    matched_columns=[table.headers[p] for p in sorted(cols.values()) if p < len(table.headers)],
                )
            )
            found.append((role, table))
        return found

    def assemble(self, source: UploadedFile | None, supporting: list[UploadedFile]) -> InputBundle:
        bundle = InputBundle(references={r: [] for r in SUPPORTING_ROLES})

        # 1. Source file (the only mandatory input)
        if source is None:
            bundle.errors.append("A source file is required.")
        else:
            rep = FileReport(source.name, "source", source.size, role=SOURCE_ROLE)
            bundle.files.append(rep)
            try:
                bundle.source = self._source_sheet(source, rep)
                if bundle.source is None:
                    rep.status = "error"
                    msg = (
                        f"'{source.name}': no worksheet contains a Vendor Site Code column "
                        "(VENDOR_SITE_CODE or Vendor Site)."
                    )
                    rep.messages.append(msg)
                    bundle.errors.append(msg)
                elif bundle.source.row_count == 0:
                    rep.status = "error"
                    msg = f"'{source.name}': the selected worksheet has no data rows."
                    rep.messages.append(msg)
                    bundle.errors.append(msg)
            except FileValidationError as exc:
                rep.status = "error"
                rep.messages.append(exc.message)
                bundle.errors.append(exc.message)

        # 2. Optional supporting files, identified by their columns
        for f in supporting:
            rep = FileReport(f.name, "supporting", f.size)
            bundle.files.append(rep)
            try:
                found = self._classify_supporting(f, rep)
            except FileValidationError as exc:
                # An unreadable supporting file is reported but does not stop the run.
                rep.status = "error"
                rep.messages.append(exc.message)
                bundle.warnings.append(f"{exc.message} It will not be used.")
                continue
            if not found:
                rep.status = "ignored"
                msg = (
                    f"'{f.name}' did not match any supported reference dataset (expected the columns of a "
                    "BTS Site Report Schedule, Operational Site List Summary or Latest Payment Data); it will not be used."
                )
                rep.messages.append(msg)
                bundle.warnings.append(msg)
                continue
            rep.role = ", ".join(sorted({r for r, _ in found}))
            for role, table in found:
                bundle.references[role].append(table)

        # 3. Report (but never require) supporting datasets that were not supplied
        for role, tables in bundle.references.items():
            if not tables:
                label = self.label(role)
                bundle.missing_roles.append(label)
                bundle.warnings.append(
                    f"No {label} was supplied; the derivation steps that need it will be skipped and reported per record."
                )
        return bundle
