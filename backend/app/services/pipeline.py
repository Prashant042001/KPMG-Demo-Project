"""End-to-end orchestration: validate inputs -> load approved rules -> derive -> build outputs."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.core.errors import FileValidationError
from app.derivation.engine import DerivationEngine, EngineResult
from app.derivation.identifiers import IdentifierFormats
from app.derivation.reference import build_reference_data
from app.ingest.inputs import InputAssembler, InputBundle
from app.ingest.readers import UploadedFile
from app.output import writer
from app.rules.loader import ACTIVE, DUPLICATE, RuleSet, load_ruleset
from app.services.gis import GisData, build_gis
from app.services.records import build_record_rows

log = logging.getLogger(__name__)

PREVIEW_ROWS = 100


@dataclass
class ProcessOptions:
    strict_matching: bool = False
    output_format: str = "xlsx"  # format of the separate mapping / exception reports


@dataclass
class ProcessResult:
    bundle: InputBundle
    ruleset: RuleSet
    result: EngineResult
    summary: dict[str, Any]
    outputs: dict[str, writer.OutputFile]
    preview: list[dict[str, Any]]
    records: list[dict[str, Any]]  # every source record, for the searchable results table
    gis: GisData  # sites linked to master-database payment rows, for the GIS view


def assemble_inputs(rule_config: dict[str, Any], settings, source: UploadedFile | None, supporting: list[UploadedFile]) -> InputBundle:
    assembler = InputAssembler(rule_config, allowed_ext=settings.extensions, scan_rows=settings.header_scan_rows)
    return assembler.assemble(source, supporting)


def describe_rules(ruleset: RuleSet) -> dict[str, Any]:
    by_status: dict[str, list[str]] = {}
    for r in ruleset.rules:
        by_status.setdefault(r.status, []).append(r.rule_id)
    return {
        "source": "backend configuration (config/rule_config.json)",
        "version": ruleset.version,
        "rules_configured": len(ruleset.rules),
        "by_status": by_status,
        "t_number_digits": f"{ruleset.t_digits[0]}-{ruleset.t_digits[1]}",
        "requires_confirmation": [
            {"rule_id": r.rule_id, "status": r.status, "reason": r.status_reason}
            for r in ruleset.rules
            if r.status not in (ACTIVE, DUPLICATE)
        ],
    }


def _assumptions(rule_config: dict[str, Any], ruleset: RuleSet) -> list[str]:
    out = []
    if rule_config.get("derivation", {}).get("compose_tnumber_from_site_id", True):
        out.append(
            "Where a rule yields only a numeric Site ID (NNNNMTN/S, NNNNMTN/E, MTNNNNN, leading-number rules, Operational "
            "Site List), TNUMBER is composed as 'T' + Site ID following the R3 convention, only when it passes the "
            "T-number format (status 'COMPOSED'). An explicitly found T-number always takes precedence over a composed one. "
            "Disable with derivation.compose_tnumber_from_site_id."
        )
    if rule_config.get("source_column_fallbacks", {}).get("VENDOR_SITE_CODE"):
        out.append(
            "When the source file has no VENDOR_SITE_CODE column, the VENDOR_SITE_CODE rules (R2-R14) read its 'Vendor Site' "
            "column, treated as the vendor site code of the base data (R28/R29). Disable via source_column_fallbacks."
        )
    out.append(f"Approved T-number format: 'T' followed by {ruleset.t_digits[0]}-{ruleset.t_digits[1]} digits (R9 applied to all T-number rules).")
    out.append("Leading-number rule (R13/R26) does not apply to values starting with 0; those are governed by the leading-zero rule (R14/R27).")
    x_cfg = rule_config.get("x_codes", {})
    if x_cfg.get("accept_without_reference"):
        out.append(
            "X-codes (R4 on VENDOR_SITE_CODE, then R17 on VENDOR_SITE_CODE_ALT) are mapped per business instruction"
            + (" to TNUMBER and SITE ID" if x_cfg.get("map_to_tnumber") else " to SITE ID")
            + "; codes not found in the reference data carry an Info-level UNVERIFIED_IDENTIFIER note."
        )
    else:
        out.append("X-prefixed candidates (R4/R17) are accepted as Site ID only when found among Site IDs in the supplied reference data.")
    out.append("Reference look-up rules run before pattern rules; within a tier, configuration order applies (derivation.priority_overrides).")
    return out


def run_pipeline(
    rule_config: dict[str, Any],
    settings,
    source: UploadedFile | None,
    supporting: list[UploadedFile],
    options: ProcessOptions,
    stage: Callable[[str, int], None] = lambda s, p: None,
    job_id: str = "",
) -> ProcessResult:
    started = time.time()
    stage("validate", 5)
    bundle = assemble_inputs(rule_config, settings, source, supporting)
    if not bundle.valid:
        raise FileValidationError("Input validation failed. Review the validation messages.", details=bundle.errors)

    stage("load_rules", 15)
    ruleset = load_ruleset(rule_config)

    stage("derive", 20)
    formats = IdentifierFormats(ruleset, rule_config)
    markers = {m.strip().upper() for m in rule_config.get("missing_value_markers", {}).get("values", [])}
    refs = build_reference_data(bundle.references.get("bts", []), bundle.references.get("ops", []), formats, markers)
    engine = DerivationEngine(
        ruleset, rule_config, refs, formats,
        strict=options.strict_matching,
        latest_payment_supplied=bool(bundle.references.get("latest_payment")),
    )
    result = engine.derive(bundle.source, progress=lambda f: stage("derive", 20 + int(55 * f)))

    stage("build_outputs", 80)
    src = bundle.source
    metrics = result.metrics
    summary: dict[str, Any] = {
        "run": {
            "job_id": job_id,
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "strict_matching": options.strict_matching,
            "report_format": options.output_format,
            "scope": "TNUMBER and SITE ID derivation only",
            "rule_configuration": f"config/rule_config.json (version {ruleset.version})",
        },
        "inputs": {
            "file_count": len(bundle.files),
            "source_file": src.file_name,
            "source_sheet": src.sheet_name,
            "source_header_row": src.header_row,
            "input_rows": src.row_count,
            "blank_rows_not_treated_as_records": src.blank_rows_skipped,
            "bts_site_report_schedule": [f"{t.file_name} [{t.sheet_name}] ({t.row_count} rows)" for t in bundle.references.get("bts", [])] or "not supplied",
            "operational_site_list_summary": [f"{t.file_name} [{t.sheet_name}] ({t.row_count} rows)" for t in bundle.references.get("ops", [])] or "not supplied",
            "latest_payment_data": [f"{t.file_name} [{t.sheet_name}]" for t in bundle.references.get("latest_payment", [])] or "not supplied",
        },
        "results": {k: v for k, v in metrics.items() if not isinstance(v, dict)},
        "tnumber_derived_by_rule": metrics["tnumber_derived_by_rule"],
        "site_id_derived_by_rule": metrics["site_id_derived_by_rule"],
        "tnumber_status_counts": metrics["tnumber_status_counts"],
        "site_id_status_counts": metrics["site_id_status_counts"],
        "exception_counts": metrics["exception_counts"],
        "rule_execution": {
            rid: f"evaluated {st.evaluated}, matched {st.matched}, selected TNUMBER {st.selected_t}, selected SITE ID {st.selected_site}, exceptions {st.exceptions}"
            for rid, st in result.rule_stats.items()
            if st.evaluated or st.matched
        },
        "reference_data": {
            "bts_vendor_site_codes": len(refs.bts),
            "bts_codes_with_multiple_rows": refs.bts_duplicate_keys,
            "ops_account_numbers": len(refs.ops),
            "ops_accounts_with_multiple_rows": refs.ops_duplicate_keys,
            "reference_site_ids": len(refs.site_ids),
        },
        "rules_requiring_confirmation": [f"{r['rule_id']} ({r['status']}): {r['reason']}" for r in describe_rules(ruleset)["requires_confirmation"]]
        + [f"{rid} ({st}): {why}" for rid, (st, why) in result.rule_runtime_status.items()],
        "assumptions_requiring_confirmation": _assumptions(rule_config, ruleset),
        "notes": ruleset.notes + result.notes + bundle.warnings,
    }

    master, write_stats = writer.build_master_workbook(src, ruleset, result, summary)
    if any(write_stats.values()):
        log.info("Output write stats: %s", write_stats)
    stage("build_outputs", 92)
    fmt = "csv" if options.output_format == "csv" else "xlsx"
    media = writer.CSV_MEDIA if fmt == "csv" else writer.XLSX_MEDIA
    short = job_id[:8] or "run"
    # The separate reports duplicate sheets of the master workbook, so they are built on first download.
    outputs = {
        "master": writer.OutputFile(f"master_database_{short}.xlsx", writer.XLSX_MEDIA, master),
        "mapping": writer.OutputFile(f"mapping_summary_{short}.{fmt}", media, lambda: writer.build_mapping_report(result, fmt)),
        "exceptions": writer.OutputFile(f"exception_report_{short}.{fmt}", media, lambda: writer.build_exception_report(result, fmt)),
    }

    records = build_record_rows(result)
    gis = build_gis(bundle.source, bundle.references.get("ops", []), result, formats)
    log.info(
        "Job %s processed %d rows in %.1fs (T derived %d, Site derived %d)",
        short, metrics["input_rows"], time.time() - started, metrics["tnumber_derived"], metrics["site_id_derived"],
    )
    return ProcessResult(bundle, ruleset, result, summary, outputs, records[:PREVIEW_ROWS], records, gis)
