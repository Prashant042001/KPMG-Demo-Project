"""Business-rule behaviour of the T-number / Site ID derivation engine (synthetic data only)."""
from __future__ import annotations

import re

import pytest

from app.derivation.engine import CANNOT_BE_DERIVED
from samples import synthetic as syn


def one(derive, vsc, alt="", **kw):
    res, outs = derive([(vsc, alt)], **kw)
    return outs[0]


def exc_categories(res):
    return {e.category for e in res.result.exceptions}


def test_full_synthetic_sample_matches_expectations(run):
    res = run()
    got = [(r.outcome.tnumber, r.outcome.site_id) for r in res.result.records]
    want = [(t, s) for _, _, t, s in syn.BASE_ROWS]
    assert got == want


def test_r1_direct_reference_mapping(derive):
    o = one(derive, "VS-100", bts_rows=[["VS-100", "T4321", "", "Site"]])
    assert (o.tnumber, o.site_id, o.t_rule, o.t_status) == ("T4321", "4321", "R1", "MAPPED")


def test_r1_uses_bts_site_id_column_when_present(run):
    bts = syn.bts_workbook([["VS-1", "T4321", "4321"]], header=["VENDOR_SITE_CODE", "T number", "Site ID"])
    res = run(source=syn.base_workbook([["I", "VS-1", None, 1, "x"]]), bts=bts, ops=syn.ops_workbook([]))
    o = res.result.records[0].outcome
    assert (o.tnumber, o.site_id, o.site_rule) == ("T4321", "4321", "R1")


def test_r2_t_number(derive):
    o = one(derive, "T6542")
    assert (o.tnumber, o.site_id, o.t_rule) == ("T6542", "6542", "R2")


def test_r9_five_digit_t_numbers_allowed(derive):
    assert one(derive, "T65421").tnumber == "T65421"


def test_without_r9_only_four_digit_t_numbers(derive, config_with):
    cfg = config_with(lambda c: c.update(rules=[r for r in c["rules"] if r["id"] != "R9"]))
    o = one(derive, "T65421", config=cfg)
    assert o.tnumber == CANNOT_BE_DERIVED


def test_r3_digits_followed_by_mtn(derive):
    o = one(derive, "3133MTN")
    assert (o.tnumber, o.site_id, o.t_rule) == ("T3133", "3133", "R3")


def test_r4_x_prefix_validated_against_reference(derive):
    o = one(derive, "X8754", ops_rows=[["ACC-1", "X8754", "Site"]])
    assert (o.tnumber, o.site_id, o.site_rule) == ("X8754", "X8754", "R4")
    assert "without reference validation" not in o.candidates[0][0].audit_flag


def test_r4_x_prefix_unverified_is_mapped_with_audit_flag(derive):
    res, outs = derive([("X8754", "")])
    assert (outs[0].tnumber, outs[0].site_id, outs[0].t_rule) == ("X8754", "X8754", "R4")
    flagged = [e for e in res.result.exceptions if e.category == "UNVERIFIED_IDENTIFIER"]
    assert flagged and flagged[0].severity == "Info"


def test_r4_x_prefix_unverified_is_flagged_not_mapped_when_disabled(derive, config_with):
    cfg = config_with(lambda c: c["x_codes"].update(accept_without_reference=False))
    res, outs = derive([("X8754", "")], config=cfg)
    assert outs[0].tnumber == CANNOT_BE_DERIVED
    assert outs[0].site_id == "" and outs[0].site_status == "UNVERIFIED"
    assert "UNVERIFIED_IDENTIFIER" in exc_categories(res)


def test_r5_elec_suffix(derive):
    o = one(derive, "T8646/ELEC")
    assert (o.tnumber, o.site_id, o.t_rule) == ("T8646", "8646", "R5")


def test_r6_e_suffix(derive):
    o = one(derive, "T7386/E")
    assert (o.tnumber, o.site_id, o.t_rule) == ("T7386", "7386", "R6")


def test_elec_is_not_treated_as_e(derive):
    o = one(derive, "T8646/ELEC")
    rules = {c.rule_id for c, _ in o.candidates}
    assert "R5" in rules and "R6" not in rules


def test_r7_not_executed_without_approved_suffixes(derive):
    res, _ = derive([("T1234#X", "")])
    r7 = res.ruleset.by_id("R7")
    assert r7.status == "REQUIRES_CONFIRMATION"


def test_r8_embedded_t_number(derive):
    o = one(derive, "ABC-T8102-RENT")
    assert (o.tnumber, o.site_id, o.t_rule) == ("T8102", "8102", "R8")


def test_r8_multiple_t_numbers_flagged(derive):
    res, outs = derive([("ABC-T1111-T2222", "")])
    assert outs[0].tnumber == CANNOT_BE_DERIVED and outs[0].conflict
    assert outs[0].candidate_tnumbers == "T1111, T2222"
    assert "MULTIPLE_CANDIDATE_IDENTIFIERS" in exc_categories(res)


@pytest.mark.parametrize(
    "code,site,rule",
    [("4455MTN/S", "4455", "R10"), ("4456MTN/E", "4456", "R11"), ("MTN7788", "7788", "R12"), ("5566-LEASE", "5566", "R13")],
)
def test_site_id_rules(derive, code, site, rule):
    o = one(derive, code)
    assert (o.site_id, o.site_rule) == (site, rule)
    assert o.tnumber == f"T{site}" and o.t_status == "COMPOSED"


def test_r14_leading_zero(derive):
    o = one(derive, "0123")
    assert (o.site_id, o.site_rule) == ("123", "R14")
    assert o.tnumber == CANNOT_BE_DERIVED  # T123 fails the approved T-number format


def test_alternative_vendor_site_code_rules(derive):
    res, outs = derive([("NOMATCH-A", "T2468"), ("NOMATCH-B", "7788MTN/S"), ("NOMATCH-C", "0456")])
    assert [(o.tnumber, o.site_id, o.site_rule) for o in outs] == [
        ("T2468", "2468", "R15"),
        ("T7788", "7788", "R23"),
        (CANNOT_BE_DERIVED, "456", "R27"),
    ]


def test_duplicate_rule_logic_evaluated_once(derive):
    res, outs = derive([("X", "T1234/ELEC")])
    assert res.ruleset.by_id("R19").status == "DUPLICATE"
    assert outs[0].t_rule == "R18"


def test_operational_site_list_matching_including_numeric_accounts(derive):
    res, outs = derive([("ACC-1", ""), ("500123", "")], ops_rows=[["ACC-1", "7001", "a"], [500123, 7002, "b"]])
    assert [(o.site_id, o.site_rule, o.site_status) for o in outs] == [("7001", "R28", "MAPPED"), ("7002", "R28", "MAPPED")]


def test_operational_site_list_conflict_is_flagged(derive):
    res, outs = derive([("ACC-1", "")], ops_rows=[["ACC-1", "7001", "a"], ["ACC-1", "7002", "b"]])
    assert outs[0].site_id == "" and outs[0].conflict
    assert "AMBIGUOUS_REFERENCE_MAPPING" in exc_categories(res)


def test_operational_site_id_with_suffix_is_invalid_not_stripped(derive):
    res, outs = derive([("ACC-1", "")], ops_rows=[["ACC-1", "7001/E", "a"]])
    assert outs[0].site_id == ""
    assert "INVALID_CANDIDATE" in exc_categories(res)


def test_duplicate_agreeing_reference_rows_are_not_conflicts(derive):
    _, outs = derive([("VS-1", "")], bts_rows=[["VS-1", "T4000", "", "a"], ["VS-1", "T4000", "", "a"]])
    assert outs[0].tnumber == "T4000" and not outs[0].conflict


def test_conflicting_reference_rows_are_flagged(derive):
    res, outs = derive([("VS-1", "")], bts_rows=[["VS-1", "T4000", "", "a"], ["VS-1", "T4001", "", "b"]])
    assert outs[0].tnumber == CANNOT_BE_DERIVED and outs[0].conflict
    assert "AMBIGUOUS_REFERENCE_MAPPING" in exc_categories(res)


def test_reference_beats_pattern_and_conflict_is_flagged(derive):
    res, outs = derive([("T5000", "")], bts_rows=[["T5000", "T5001", "", "a"]])
    o = outs[0]
    assert (o.tnumber, o.t_rule, o.conflict) == ("T5001", "R1", True)
    statuses = {c.rule_id: s for c, s in o.candidates}
    assert statuses["R1"] == "SELECTED" and statuses["R2"] == "CONFLICTING"
    assert "CONFLICTING_MAPPING" in exc_categories(res)


def test_strict_matching_withholds_conflicting_values(derive):
    _, outs = derive([("T5000", "")], bts_rows=[["T5000", "T5001", "", "a"]], strict=True)
    assert outs[0].tnumber == CANNOT_BE_DERIVED and outs[0].t_status == "CONFLICT_WITHHELD"


def test_cross_record_conflict_for_same_vendor_site_code(derive):
    res, _ = derive([("SAME", "T1111"), ("SAME", "T2222")])
    assert all(r.conflict for r in res.result.records)
    assert any("across records" in e.detail for e in res.result.exceptions)


def test_cannot_be_derived_exact_text_and_unresolved_site(derive):
    res, outs = derive([("NOTHING-HERE", "")])
    assert outs[0].tnumber == "cannot be derived"
    assert outs[0].site_id == "" and outs[0].site_status == "UNRESOLVED"
    assert {"UNRESOLVED_TNUMBER", "UNRESOLVED_SITE_ID"} <= exc_categories(res)


def test_site_ids_never_carry_prefixes_or_suffixes(run):
    res = run()
    for r in res.result.records:
        s = r.outcome.site_id
        assert s == "" or re.fullmatch(r"\d{3,5}|X\d{3,6}", s), s
        assert not re.search(r"/E|ELEC|MTN|^T", s)


def test_latest_payment_data_optional_and_not_supplied(run):
    res = run()
    assert res.ruleset.by_id("R29") is not None
    assert "OPTIONAL_SOURCE_NOT_USED" in exc_categories(res)


def test_latest_payment_data_as_source_applies_r29(run):
    header = ["INVOICE_NUM", "Vendor Site", "AMOUNT"]
    res = run(source=syn.base_workbook([["I-1", "T7777", 1], ["I-2", "NOPE", 2]], header=header),
              bts=syn.bts_workbook([]), ops=syn.ops_workbook([]))
    o = res.result.records[0].outcome
    assert (o.tnumber, o.site_id) == ("T7777", "7777")
    statuses = {c.rule_id: s for c, s in o.candidates}
    # R2 reads 'Vendor Site' via the configured fallback and wins on priority; R29 agrees.
    assert statuses["R2"] == "SELECTED" and statuses["R29"] == "SUPPORTING"


def test_latest_payment_supplied_as_supporting_is_recorded_not_guessed(run):
    from app.ingest.readers import UploadedFile

    lpd = syn._xlsx({"LPD": [["Vendor Site", "Amount"], ["T1000", 5]]})
    res = run(extra=[UploadedFile("Latest_Payment_Data.xlsx", lpd, "supporting")])
    details = [e.detail for e in res.result.exceptions if e.category == "OPTIONAL_SOURCE_NOT_USED"]
    assert any("join key" in d for d in details)


def test_unapproved_rules_are_reported_not_executed(derive, config_with):
    def change(c):
        next(r for r in c["rules"] if r["id"] == "R2")["status"] = "requires_confirmation"
        c["rules"].append({"id": "R30", "kind": "T_DIRECT", "status": "requires_confirmation", "column": "VENDOR_SITE_CODE",
                           "description": "Pending legacy mapping", "confirmation_needed": "Awaiting business sign-off"})

    res, outs = derive([("T6542", "")], config=config_with(change))
    assert res.ruleset.by_id("R2").status == "REQUIRES_CONFIRMATION"
    assert res.ruleset.by_id("R30").status == "REQUIRES_CONFIRMATION"
    assert outs[0].t_rule == "R8"  # R2 not executed; other approved rules keep working
    flagged = " ".join(res.summary["rules_requiring_confirmation"])
    assert "R2" in flagged and "R30" in flagged
    assert "RULE_REQUIRES_CONFIRMATION" in exc_categories(res)
