"""REST endpoints consumed by the React front end."""
from __future__ import annotations

import logging
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings, load_rule_config
from app.core.errors import FileTooLargeError, FileValidationError, JobNotFoundError, JobNotReadyError
from app.core.text import safe_filename
from app.ingest.readers import UploadedFile, check_extension
from app.rules.loader import load_ruleset
from app.services.jobs import COMPLETED, Job, JobStore
from app.services.pipeline import ProcessOptions, assemble_inputs, describe_rules, run_pipeline
from app.services.records import MAX_PAGE_SIZE, STATUS_FILTERS, filter_records

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

CHUNK = 1024 * 1024
JobId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$", description="Job identifier returned by POST /api/process")]

_store: JobStore | None = None


def get_store() -> JobStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = JobStore(ttl_seconds=s.job_ttl_minutes * 60, max_jobs=s.max_jobs_in_memory, workers=s.worker_threads)
    return _store


async def _read_upload(up: UploadFile | None, slot: str, settings: Settings) -> UploadedFile | None:
    """Read an upload into memory, enforcing extension and size limits before the whole file is buffered."""
    if up is None or not up.filename:
        return None
    name = safe_filename(up.filename)
    try:
        check_extension(UploadedFile(name, b"x", slot), settings.extensions)
        buf = bytearray()
        while chunk := await up.read(CHUNK):
            buf.extend(chunk)
            if len(buf) > settings.max_file_size_bytes:
                raise FileTooLargeError(f"'{name}' exceeds the {settings.max_file_size_mb} MB file size limit.")
    finally:
        await up.close()  # removes any spooled temporary file
    return UploadedFile(name, bytes(buf), slot)


async def _read_all(source_file, supporting_files, settings: Settings):
    supporting_files = [f for f in (supporting_files or []) if f is not None and f.filename]
    if len(supporting_files) > settings.max_supporting_files:
        raise FileValidationError(f"At most {settings.max_supporting_files} supporting files can be uploaded at once.")
    source = await _read_upload(source_file, "source", settings)
    supporting = [await _read_upload(f, "supporting", settings) for f in supporting_files]
    return source, [s for s in supporting if s is not None]


@router.get("/health", summary="Backend status")
def health(settings: Settings = Depends(get_settings)):
    return {"status": "ok", "service": settings.app_name, "version": settings.api_version}


@router.get("/config", summary="Required files, expected columns and processing options")
def config(settings: Settings = Depends(get_settings)):
    rc = load_rule_config(settings.rule_config_path)
    roles = {
        role: {
            "label": spec.get("label", role),
            "upload": "source_file" if role == "source" else "supporting_files (optional)",
            "required_columns": spec.get("required", []),
            "required_any_of": spec.get("required_any", []),
            "optional_columns": spec.get("optional", []),
        }
        for role, spec in rc["file_roles"].items()
        if not role.startswith("_")
    }
    return {
        "scope": ["TNUMBER", "SITE ID"],
        "uploads": {"source_file": "required, one file", "supporting_files": "optional, zero or more files"},
        "datasets": roles,
        "rules": describe_rules(load_ruleset(rc)),
        "column_aliases": {k: v for k, v in rc["columns"].items()},
        "allowed_extensions": sorted(settings.extensions),
        "max_file_size_mb": settings.max_file_size_mb,
        "max_supporting_files": settings.max_supporting_files,
        "options": {
            "strict_matching": "When true, a record with conflicting or ambiguous results has the affected value withheld instead of keeping the highest-priority result.",
            "output_format": ["xlsx", "csv"],
        },
        "unresolved_tnumber_text": "cannot be derived",
    }


@router.post("/validate", summary="Validate uploaded files, worksheets and columns without generating output")
async def validate(
    source_file: UploadFile | None = File(None, description="Source file to process (XLSX/XLS/CSV, any filename)"),
    supporting_files: list[UploadFile] | None = File(None, description="Optional reference files, identified by their columns"),
    settings: Settings = Depends(get_settings),
):
    source, supporting = await _read_all(source_file, supporting_files, settings)
    rc = load_rule_config(settings.rule_config_path)

    def work():
        body = assemble_inputs(rc, settings, source, supporting).to_dict()
        body["rules"] = describe_rules(load_ruleset(rc))
        return body

    return await run_in_threadpool(work)


@router.post("/process", status_code=202, summary="Start the T-number and Site ID derivation workflow")
async def process(
    source_file: UploadFile | None = File(None, description="Source file to process (XLSX/XLS/CSV, any filename)"),
    supporting_files: list[UploadFile] | None = File(None, description="Optional reference files, identified by their columns"),
    strict_matching: bool = Form(False),
    output_format: Literal["xlsx", "csv"] = Form("xlsx"),
    settings: Settings = Depends(get_settings),
):
    source, supporting = await _read_all(source_file, supporting_files, settings)
    rc = load_rule_config(settings.rule_config_path)  # approved rules, reloaded for every job
    store = get_store()
    job = store.create()
    options = ProcessOptions(strict_matching=strict_matching, output_format=output_format)

    def stage(name: str, pct: int) -> None:
        job.stage, job.progress = name, max(job.progress, min(pct, 99))

    def work(j: Job) -> None:
        try:
            res = run_pipeline(rc, settings, source, supporting, options, stage, job_id=j.id)
        except FileValidationError as exc:
            j.validation = {"valid": False, "errors": exc.details or [exc.message]}
            raise
        j.validation = res.bundle.to_dict()
        j.validation["rules"] = describe_rules(res.ruleset)
        j.summary, j.metrics, j.preview, j.outputs = res.summary, res.result.metrics, res.preview, res.outputs
        j.records, j.gis = res.records, res.gis

    store.submit(job, work)
    log.info("Job %s queued (%d supporting file(s))", job.id[:8], len(supporting))
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}", summary="Processing status and summary")
def job_status(job_id: JobId):
    return get_store().get(job_id).public()


@router.get("/jobs/{job_id}/records", summary="Search, filter and page through the derived rows of a completed job")
def job_records(
    job_id: JobId,
    q: str = Query("", max_length=100, description="Text to find in Vendor Site Code, ALT, TNUMBER, SITE ID, candidates or reason; or a row number"),
    status: Literal[tuple(STATUS_FILTERS)] = Query("all", description="Quick filter"),
    rule: str = Query("", max_length=10, pattern=r"^[A-Za-z0-9]*$", description="Rule ID used for TNUMBER or SITE ID, e.g. R1"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
):
    job = get_store().get(job_id)
    if job.status != COMPLETED:
        raise JobNotReadyError("Rows are available only after processing completes successfully.")
    return filter_records(job.records, q=q, status=status, rule=rule, page=page, page_size=page_size)


def _completed_job(job_id: str) -> Job:
    job = get_store().get(job_id)
    if job.status != COMPLETED:
        raise JobNotReadyError("Available only after the master database has been generated successfully.")
    return job


@router.get("/jobs/{job_id}/gis", summary="Sites from the Operational Site List, linked to the run's master-database payments")
def job_gis(job_id: JobId):
    return _completed_job(job_id).gis.summary()


@router.get("/jobs/{job_id}/gis/sites/{site_id}", summary="One site's details and its master-database payment rows")
def job_gis_site(job_id: JobId, site_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9]{1,20}$")]):
    detail = _completed_job(job_id).gis.site(site_id)
    if detail is None:
        raise JobNotFoundError("Site not found in this run.")
    return detail


def _download(job_id: str, name: str) -> Response:
    out = get_store().output(job_id, name)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", out.filename)
    return Response(
        content=out.content,
        media_type=out.media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "no-store"},
    )


@router.get("/jobs/{job_id}/download/master", summary="Download the master output workbook")
def download_master(job_id: JobId):
    return _download(job_id, "master")


@router.get("/jobs/{job_id}/download/mapping", summary="Download the mapping summary")
def download_mapping(job_id: JobId):
    return _download(job_id, "mapping")


@router.get("/jobs/{job_id}/download/exceptions", summary="Download the exception report")
def download_exceptions(job_id: JobId):
    return _download(job_id, "exceptions")
