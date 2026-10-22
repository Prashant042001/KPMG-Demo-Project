"""Backend rule configuration, input validation and file reading."""
from __future__ import annotations

import pytest

from app.core.errors import FileValidationError
from app.ingest.readers import UploadedFile
from app.rules.catalog import RuleKind
from app.rules.loader import RuleConfigError, load_ruleset
from app.services.pipeline import ProcessOptions, assemble_inputs, run_pipeline
from samples import synthetic as syn
from tests.conftest import make_files


def test_rules_are_loaded_from_backend_configuration(rule_config):
    rs = load_ruleset(rule_config)
    assert [r.rule_id for r in rs.rules] == [f"R{i}" for i in range(1, 30)]
    assert rs.by_id("R3").kind == RuleKind.DIGITS_MTN and rs.by_id("R3").status == "ACTIVE"
    assert rs.t_digits == (4, 5)  # R9 approved
    assert rs.version


def test_rule_configuration_errors_are_detected(rule_config):
    from copy import deepcopy

    bad = deepcopy(rule_config)
    bad["rules"].append(dict(bad["rules"][0]))  # duplicate R1
    with pytest.raises(RuleConfigError):
        load_ruleset(bad)
    bad["rules"] = [{"id": "R1", "kind": "NOT_A_KIND"}]
    with pytest.raises(RuleConfigError):
        load_ruleset(bad)


def test_priority_reference_rules_first(run):
    order = [r.rule_id for r in run().ruleset.executable]
    assert order[:2] == ["R1", "R28"] and order[2] == "R2"


def test_priority_override(config_with):
    cfg = config_with(lambda c: c["derivation"].update(priority_overrides={"R2": 1}))
    assert load_ruleset(cfg).executable[0].rule_id == "R2"


def test_no_rules_workbook_needed_or_accepted_as_role(rule_config, settings):
    assert "rules" not in rule_config["file_roles"]
    source, sup = make_files()
    bundle = assemble_inputs(rule_config, settings, source, sup)
    assert bundle.valid, bundle.errors


def test_valid_inputs_detect_roles_and_header_rows(rule_config, settings):
    bundle = assemble_inputs(rule_config, settings, *make_files())
    assert bundle.valid, bundle.errors
    assert bundle.source.header_row == 3 and bundle.source.row_count == len(syn.BASE_ROWS)
    assert len(bundle.references["bts"]) == 1 and len(bundle.references["ops"]) == 1


def test_source_file_alone_is_valid(rule_config, settings):
    source, _ = make_files()
    bundle = assemble_inputs(rule_config, settings, source, [])
    assert bundle.valid
    assert set(bundle.missing_roles) == {"BTS Site Report Schedule", "Operational Site List Summary", "Latest Payment Data"}


def test_supporting_files_identified_by_columns_not_filename(rule_config, settings):
    # Names deliberately misleading: content decides.
    source, _ = make_files()
    sup = [UploadedFile("operational_site_list.xlsx", syn.bts_workbook(), "supporting"),
           UploadedFile("bts_report.xlsx", syn.ops_workbook(), "supporting")]
    bundle = assemble_inputs(rule_config, settings, source, sup)
    assert bundle.references["bts"][0].file_name == "operational_site_list.xlsx"
    assert bundle.references["ops"][0].file_name == "bts_report.xlsx"


def test_one_workbook_can_hold_several_reference_datasets(rule_config, settings):
    combined = syn._xlsx({"Sites": [syn.BTS_HEADER, *syn.BTS_ROWS], "Ops": [syn.OPS_HEADER, *syn.OPS_ROWS]})
    source, _ = make_files()
    bundle = assemble_inputs(rule_config, settings, source, [UploadedFile("refs.xlsx", combined, "supporting")])
    assert len(bundle.references["bts"]) == 1 and len(bundle.references["ops"]) == 1


def test_missing_required_source_column(rule_config, settings):
    source = syn.base_workbook([["I-1", "x"]], header=["INVOICE_NUM", "SOMETHING_ELSE"])
    bundle = assemble_inputs(rule_config, settings, *make_files(source=source))
    assert not bundle.valid
    assert any("Vendor Site Code" in e for e in bundle.errors)


def test_missing_source_file(rule_config, settings):
    bundle = assemble_inputs(rule_config, settings, None, [])
    assert bundle.errors == ["A source file is required."]


@pytest.mark.parametrize(
    "name,content,message",
    [
        ("report.pdf", b"%PDF-1.7", "unsupported file type"),
        ("report.txt", b"hello", "unsupported file type"),
        ("report.xlsx", b"not a zip at all", "not a valid .xlsx"),
        ("report.xls", b"garbage!", "not a valid legacy .xls"),
        ("report.csv", b"a,b\x00\x00", "does not look like a text CSV"),
        ("empty.csv", b"", "is empty"),
    ],
)
def test_unknown_and_invalid_source_formats(rule_config, settings, name, content, message):
    _, sup = make_files()
    bundle = assemble_inputs(rule_config, settings, UploadedFile(name, content, "source"), sup)
    assert any(message in e for e in bundle.errors), bundle.errors


def test_unreadable_or_unrecognised_supporting_files_do_not_block(rule_config, settings):
    other = UploadedFile("notes.csv", b"colour,size\nred,1\n", "supporting")
    broken = UploadedFile("broken.xlsx", b"PK\x03\x04garbage", "supporting")
    source, sup = make_files()
    bundle = assemble_inputs(rule_config, settings, source, sup + [other, broken])
    assert bundle.valid
    assert any("did not match any supported reference dataset" in w for w in bundle.warnings)
    assert any("corrupt" in w for w in bundle.warnings)


def test_csv_source_with_title_row(rule_config, settings):
    csv_bytes = b"Synthetic export\r\nINVOICE_NUM,vendor site code,Amount\r\nI-1,T6542,10\r\nI-2,3133MTN,20\r\n"
    res = run_pipeline(rule_config, settings, UploadedFile("whatever.csv", csv_bytes, "source"), [], ProcessOptions())
    assert [r.outcome.tnumber for r in res.result.records] == ["T6542", "T3133"]


def test_safe_filename_strips_paths_and_control_chars():
    f = UploadedFile("..\\..\\secret/dir/evil\x00name.xlsx", b"x", "source")
    assert f.name == "evilname.xlsx"


def test_validation_error_carries_details(rule_config, settings):
    with pytest.raises(FileValidationError) as ei:
        run_pipeline(rule_config, settings, None, [], ProcessOptions())
    assert ei.value.details
