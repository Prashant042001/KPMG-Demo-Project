from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import get_settings, load_rule_config  # noqa: E402
from app.ingest.readers import UploadedFile  # noqa: E402
from app.services.pipeline import ProcessOptions, run_pipeline  # noqa: E402
from samples import synthetic as syn  # noqa: E402


@pytest.fixture(scope="session")
def rule_config():
    return load_rule_config()


@pytest.fixture(scope="session")
def settings():
    return get_settings()


def make_files(source=None, bts=None, ops=None, extra=None):
    """Source file plus optional supporting files. Pass ``bts=False`` / ``ops=False`` to omit one."""
    source_f = UploadedFile("Any_Name_Source.xlsx", source if source is not None else syn.base_workbook(), "source")
    supporting = []
    if bts is not False:
        supporting.append(UploadedFile("reference_a.xlsx", bts if bts is not None else syn.bts_workbook(), "supporting"))
    if ops is not False:
        supporting.append(UploadedFile("reference_b.xlsx", ops if ops is not None else syn.ops_workbook(), "supporting"))
    supporting += extra or []
    return source_f, supporting


@pytest.fixture
def run(rule_config, settings):
    """Run the full pipeline on (optionally customised) synthetic inputs."""

    def _run(*, strict=False, fmt="xlsx", config=None, **files):
        source, supporting = make_files(**files)
        return run_pipeline(config or rule_config, settings, source, supporting, ProcessOptions(strict, fmt), job_id="0" * 32)

    return _run


@pytest.fixture
def derive(run):
    """Derive (TNUMBER, SITE ID, outcome) for a list of (vendor site code, alt) pairs."""

    def _derive(codes, *, bts_rows=None, ops_rows=None, strict=False, config=None, bts=None, ops=None):
        rows = [[f"INV-{i}", vsc, alt or None, 1, "x"] for i, (vsc, alt) in enumerate(codes)]
        res = run(
            source=syn.base_workbook(rows),
            bts=bts if bts is not None else syn.bts_workbook(bts_rows if bts_rows is not None else []),
            ops=ops if ops is not None else syn.ops_workbook(ops_rows if ops_rows is not None else []),
            strict=strict,
            config=config,
        )
        return res, [r.outcome for r in res.result.records]

    return _derive


@pytest.fixture
def config_with(rule_config):
    """Return a modified deep copy of the rule configuration."""

    def _with(fn):
        cfg = deepcopy(rule_config)
        fn(cfg)
        return cfg

    return _with
