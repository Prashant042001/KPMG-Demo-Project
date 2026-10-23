"""T-number and Site ID derivation engine.

For every source record the engine evaluates all executable rules in priority order and collects *candidates*
(one per rule that produced something). Resolution then picks, independently for TNUMBER and SITE ID, the
highest-priority valid candidate; any other valid candidate with a different value is a conflict and is
flagged, never silently substituted. Every candidate is kept for the Mapping Summary.

Precedence for TNUMBER: a T-number found explicitly (BTS look-up or a T-number pattern) always outranks a
T-number *composed* from a Site ID ('T' + Site ID), whatever the rule priorities; composition is an inference
and must not overwrite an explicit result.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.text import cell_text, match_key
from app.derivation.identifiers import IdentifierFormats, compile_patterns
from app.derivation.reference import ReferenceData
from app.ingest.readers import Table
from app.rules.catalog import SITE_PATTERN_KINDS, T_PATTERN_KINDS, RuleKind
from app.rules.loader import REQUIRES_CONFIRMATION, SOURCE_UNAVAILABLE, Rule, RuleSet

log = logging.getLogger(__name__)

CANNOT_BE_DERIVED = "cannot be derived"

SOURCE_DATASET = "Source file"
BTS_DATASET = "BTS Site Report Schedule"
OPS_DATASET = "Operational Site List Summary"

# Candidate statuses
MATCHED = "MATCHED"
AMBIGUOUS = "AMBIGUOUS"
INVALID = "INVALID"
UNVERIFIED = "UNVERIFIED"

# Exception categories
EX_UNRESOLVED_T = "UNRESOLVED_TNUMBER"
EX_UNRESOLVED_SITE = "UNRESOLVED_SITE_ID"
EX_MISSING_SOURCE_VALUE = "MISSING_SOURCE_VALUE"
EX_MISSING_REFERENCE = "MISSING_REFERENCE_DATA"
EX_AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE_MAPPING"
EX_MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATE_IDENTIFIERS"
EX_CONFLICT = "CONFLICTING_MAPPING"
EX_RESOLVED = "RESOLVED_BY_PRIORITY"
EX_INVALID = "INVALID_CANDIDATE"
EX_UNVERIFIED = "UNVERIFIED_IDENTIFIER"
EX_MISSING_COLUMN = "MISSING_COLUMN"
EX_RULE_CONFIRMATION = "RULE_REQUIRES_CONFIRMATION"
EX_OPTIONAL_SOURCE = "OPTIONAL_SOURCE_NOT_USED"
EX_DATA_QUALITY = "DATA_QUALITY"


@dataclass(frozen=True)
class Candidate:
    rule_id: str
    priority: int
    tier: str
    dataset: str  # SOURCE_DATASET / BTS_DATASET / OPS_DATASET
    source_file: str
    source_field: str
    original_value: str
    matching_key: str
    tnumber: str | None = None
    site_id: str | None = None
    t_composed: bool = False
    affects_t: bool = True
    status: str = MATCHED
    note: str = ""
    options: tuple[str, ...] = ()  # competing identifiers behind an AMBIGUOUS status
    audit_flag: str = ""  # informational exception raised when this candidate is selected

    @property
    def source(self) -> str:
        return f"{self.dataset}: {self.source_file} | {self.source_field}"


@dataclass(frozen=True)
class ExceptionItem:
    category: str
    severity: str
    row_number: int | None
    rule_id: str
    source_file: str
    field: str
    original_value: str
    detail: str


@dataclass
class Outcome:
    """Resolution of one distinct combination of source values (shared by every record carrying them)."""

    tnumber: str = CANNOT_BE_DERIVED
    site_id: str = ""
    t_rule: str = ""
    site_rule: str = ""
    t_source: str = ""
    site_source: str = ""
    t_status: str = "NOT_DERIVED"
    site_status: str = "UNRESOLVED"
    conflict: bool = False
    candidate_tnumbers: str = ""
    candidates: list[tuple[Candidate, str]] = field(default_factory=list)  # (candidate, mapping status)
    issues: list[tuple[str, str, str, str, str]] = field(default_factory=list)  # (category, severity, rule, field, detail)
    evaluated: tuple[str, ...] = ()


@dataclass
class RecordResult:
    row_index: int
    row_number: int
    vendor_site_code: str
    vendor_site_code_alt: str
    outcome: Outcome
    cross_reasons: list[str] = field(default_factory=list)

    @property
    def conflict(self) -> bool:
        return self.outcome.conflict or bool(self.cross_reasons)

    @property
    def exception_reason(self) -> str:
        reasons = [detail for _, _, _, _, detail in self.outcome.issues] + self.cross_reasons
        return "; ".join(dict.fromkeys(reasons))


@dataclass
class RuleStats:
    evaluated: int = 0
    matched: int = 0
    selected_t: int = 0
    selected_site: int = 0
    exceptions: int = 0


@dataclass
class EngineResult:
    records: list[RecordResult]
    exceptions: list[ExceptionItem]
    rule_stats: dict[str, RuleStats]
    rule_runtime_status: dict[str, tuple[str, str]]  # rule_id -> (status, reason) decided at run time
    metrics: dict[str, Any]
    notes: list[str]


class DerivationEngine:
    def __init__(
        self,
        ruleset: RuleSet,
        rule_config: dict[str, Any],
        references: ReferenceData,
        formats: IdentifierFormats,
        *,
        strict: bool = False,
        latest_payment_supplied: bool = False,
    ):
        self.ruleset = ruleset
        self.refs = references
        self.fmt = formats
        self.strict = strict
        self.latest_payment_supplied = latest_payment_supplied
        self.patterns = compile_patterns(rule_config, ruleset, formats)
        self.compose = bool(rule_config.get("derivation", {}).get("compose_tnumber_from_site_id", True))
        deriv = rule_config.get("derivation", {})
        self.authoritative = str(deriv.get("authoritative_rule", "R1")).upper()
        self.flag_resolved_conflicts = bool(deriv.get("flag_resolved_conflicts", False))
        x_cfg = rule_config.get("x_codes", {})
        self.x_accept_unverified = bool(x_cfg.get("accept_without_reference", False))
        self.x_to_tnumber = bool(x_cfg.get("map_to_tnumber", False))
        self.fallbacks: dict[str, list[str]] = {
            k: v for k, v in rule_config.get("source_column_fallbacks", {}).items() if not k.startswith("_")
        }
        self.missing_references: dict[str, list[str]] = {}  # dataset label -> rule IDs that could not run
        self.fallback_used: dict[str, list[str]] = {}  # fallback column -> rule IDs reading it

    # ------------------------------------------------------------------ rule binding
    def _bind_rules(self, source: Table, global_ex: list[ExceptionItem]) -> tuple[list[tuple[Rule, str]], dict[str, tuple[str, str]]]:
        """Decide, per executable rule, where its input comes from: 'source', 'bts_alt' or 'reference'."""
        bound: list[tuple[Rule, str]] = []
        runtime: dict[str, tuple[str, str]] = {}
        has_key = self._key_pos(source) is not None

        def unavailable(rule: Rule, reason: str, category: str = EX_MISSING_COLUMN, severity: str = "Medium"):
            runtime[rule.rule_id] = (SOURCE_UNAVAILABLE, reason)
            global_ex.append(ExceptionItem(category, severity, None, rule.rule_id, source.file_name, rule.column_name, "", reason))

        for rule in self.ruleset.rules:
            if rule.status == REQUIRES_CONFIRMATION:
                global_ex.append(ExceptionItem(EX_RULE_CONFIRMATION, "Medium", None, rule.rule_id, "", rule.column_name, "",
                                               f"Not executed - requires business confirmation: {rule.status_reason}"))

        for rule in self.ruleset.executable:
            kind = rule.kind
            if kind in (RuleKind.BTS_REFERENCE, RuleKind.OPS_REFERENCE):
                label = BTS_DATASET if kind == RuleKind.BTS_REFERENCE else OPS_DATASET
                supplied = self.refs.bts_tables if kind == RuleKind.BTS_REFERENCE else self.refs.ops_tables
                if not supplied:
                    self.missing_references.setdefault(label, []).append(rule.rule_id)
                    unavailable(rule, f"{label} not supplied; {rule.rule_id} could not be checked for any record.",
                                EX_MISSING_REFERENCE, "Info")
                elif not has_key:
                    unavailable(rule, "Source file has no Vendor Site Code column to match on.")
                else:
                    bound.append((rule, "reference"))
                continue
            if kind not in self.patterns:
                runtime[rule.rule_id] = (REQUIRES_CONFIRMATION, "No approved pattern is configured for this rule.")
                global_ex.append(
                    ExceptionItem(EX_RULE_CONFIRMATION, "Medium", None, rule.rule_id, "", rule.column_name, "",
                                  "No approved pattern is configured for this rule; it was not executed.")
                )
                continue
            column = self._source_column_for(rule, source)
            if column:
                bound.append((rule, f"source:{column}"))
                if column != rule.source_column:
                    self.fallback_used.setdefault(column, []).append(rule.rule_id)
            elif rule.source_column == "VENDOR_SITE_CODE_ALT" and self.refs.bts_has_alt and has_key:
                bound.append((rule, "bts_alt"))
            elif rule.source_column == "VENDOR_SITE" and self.latest_payment_supplied:
                unavailable(
                    rule,
                    "Latest Payment Data was supplied as a supporting file, but no join key to the source records is "
                    "confirmed; upload it as the source file to apply this rule.",
                    EX_OPTIONAL_SOURCE,
                    "Info",
                )
            elif rule.source_column == "VENDOR_SITE":
                unavailable(rule, "Column 'Vendor Site' (Latest Payment Data) is not in the source file; rule not executed.",
                            EX_OPTIONAL_SOURCE, "Info")
            else:
                unavailable(rule, f"Column '{rule.column_name}' not found in the source file or reference data; rule not executed.")
        return bound, runtime

    def _source_column_for(self, rule: Rule, source: Table) -> str | None:
        """The rule's own column if the source has it, otherwise the first configured fallback that is present."""
        if rule.source_column in source.columns:
            return rule.source_column
        return next((c for c in self.fallbacks.get(rule.source_column, []) if c in source.columns), None)

    @staticmethod
    def _key_pos(source: Table) -> int | None:
        pos = source.columns.get("VENDOR_SITE_CODE")
        return pos if pos is not None else source.columns.get("VENDOR_SITE")

    # ------------------------------------------------------------------ candidate producers
    def _bts_candidates(self, rule: Rule, key: str, original: str) -> list[Candidate]:
        entries = self.refs.bts.get(key)
        if not entries:
            return []
        files = ", ".join(sorted({e.file for e in entries}))
        field_name = f"{self.refs.bts_t_header} (matched on VENDOR_SITE_CODE)"
        common = dict(rule_id=rule.rule_id, priority=rule.priority, tier="reference", dataset=BTS_DATASET,
                      source_file=files, source_field=field_name, original_value=original, matching_key=key)
        by_t: dict[str, list] = defaultdict(list)
        invalid = []
        for e in entries:
            t = self.fmt.tnumber(e.t_raw)
            if t:
                by_t[t].append(e)
            elif e.t_raw:
                invalid.append(e.t_raw)
        if len(by_t) > 1:
            return [Candidate(**common, status=AMBIGUOUS, options=tuple(sorted(by_t)),
                              note=f"Vendor Site Code maps to conflicting T-numbers in the BTS Site Report Schedule: {', '.join(sorted(by_t))}")]
        if not by_t:
            if invalid:
                return [Candidate(**common, status=INVALID,
                                  note="BTS Site Report Schedule T-number does not match the approved T-number format")]
            return []
        t, rows = next(iter(by_t.items()))
        out: list[Candidate] = []
        sites = {s for s, ok in (self.fmt.site_id(e.site_raw) for e in rows if e.site_raw) if ok and s}
        note = f"{len(rows)} agreeing reference rows" if len(rows) > 1 else ""
        if len(sites) == 1:
            site = next(iter(sites))
        elif len(sites) > 1:
            site = None
            out.append(Candidate(**common, affects_t=False, status=AMBIGUOUS, options=tuple(sorted(sites)),
                                 note=f"Conflicting Site IDs in the BTS Site Report Schedule: {', '.join(sorted(sites))}"))
        else:
            site = t[1:]
        out.insert(0, Candidate(**common, tnumber=t, site_id=site, note=note))
        return out

    def _ops_candidates(self, rule: Rule, key: str, original: str) -> list[Candidate]:
        entries = self.refs.ops.get(key)
        if not entries:
            return []
        files = ", ".join(sorted({e.file for e in entries}))
        common = dict(rule_id=rule.rule_id, priority=rule.priority, tier="reference", dataset=OPS_DATASET,
                      source_file=files, source_field=f"{self.refs.ops_site_header} (matched on Account Number)",
                      original_value=original, matching_key=key, affects_t=False)
        sites, invalid = set(), []
        for e in entries:
            s, ok = self.fmt.site_id(e.site_raw)
            if ok and s:
                sites.add(s)
            elif not ok:
                invalid.append(e.site_raw)
        if len(sites) > 1:
            return [Candidate(**common, status=AMBIGUOUS, options=tuple(sorted(sites)),
                              note=f"Account Number maps to conflicting Site IDs in the Operational Site List Summary: {', '.join(sorted(sites))}")]
        if not sites:
            if invalid:
                return [Candidate(**common, status=INVALID,
                                  note="Operational Site List Summary Site ID does not match the approved Site ID format")]
            return []
        site = next(iter(sites))
        t = self.fmt.compose_tnumber(site) if self.compose and self.fmt.is_numeric_site_id(site) else None
        note = f"{len(entries)} agreeing reference rows" if len(entries) > 1 else ""
        return [Candidate(**common, tnumber=t, site_id=site, t_composed=t is not None, note=note)]

    def _pattern_candidates(self, rule: Rule, value: str, dataset: str, source_file: str, source_field: str) -> list[Candidate]:
        up = match_key(value)
        if not up:
            return []
        kind, rx = rule.kind, self.patterns[rule.kind]
        common = dict(rule_id=rule.rule_id, priority=rule.priority, tier="pattern", dataset=dataset,
                      source_file=source_file, source_field=source_field, original_value=value)

        if kind == RuleKind.T_EMBEDDED:
            # An all-zero number (e.g. the 'T0000' in 'T0000-1234') is a placeholder, not an identifier.
            nums = list(dict.fromkeys(m.group("num") for m in rx.finditer(up) if m.group("num").strip("0")))
            if not nums:
                return []
            if len(nums) > 1:
                ts = tuple("T" + n for n in nums)
                return [Candidate(**common, matching_key=up, status=AMBIGUOUS, options=ts,
                                  note=f"Multiple T-numbers found in one field: {', '.join(ts)}")]
            return [Candidate(**common, matching_key=f"T{nums[0]}", tnumber=f"T{nums[0]}", site_id=nums[0])]

        if kind == RuleKind.X_PREFIX:
            m = rx.match(up)  # 'begins with X followed by a numeric identifier'; trailing text is allowed
            if not m or not m.group("num").strip("0"):
                return []  # no X-code, or an all-zero placeholder such as X000
            code = f"X{m.group('num')}"
            if not self.fmt.is_x_site_id(code):
                return [Candidate(**common, matching_key=code, affects_t=False, status=INVALID,
                                  note="X-prefixed code does not match the approved Site ID format")]
            t = code if self.x_to_tnumber else None
            if code in self.refs.site_ids:
                return [Candidate(**common, matching_key=code, tnumber=t, site_id=code, affects_t=t is not None,
                                  note="X-code validated against reference Site IDs")]
            if self.x_accept_unverified:
                return [Candidate(**common, matching_key=code, tnumber=t, site_id=code, affects_t=t is not None,
                                  note="X-code mapped per business instruction; not found in reference Site IDs",
                                  audit_flag=f"X-code {code} mapped without reference validation (x_codes.accept_without_reference)")]
            return [Candidate(**common, matching_key=code, affects_t=False, status=UNVERIFIED,
                              note="X-prefixed candidate not found in reference Site IDs (may be a RAN/transmission reference)")]

        m = rx.search(up)
        if not m:
            return []
        num = m.group("num")
        if kind in T_PATTERN_KINDS:
            if not num.strip("0"):
                return []  # all-zero placeholder, not a T-number
            return [Candidate(**common, matching_key=m.group(0), tnumber=f"T{num}", site_id=num)]
        if kind in SITE_PATTERN_KINDS:
            if not self.fmt.is_numeric_site_id(num):
                return [Candidate(**common, matching_key=m.group(0), affects_t=False, status=INVALID,
                                  note=f"Extracted value '{num}' does not match the approved Site ID format")]
            t = self.fmt.compose_tnumber(num) if self.compose else None
            return [Candidate(**common, matching_key=m.group(0), tnumber=t, site_id=num, t_composed=t is not None)]
        return []

    # ------------------------------------------------------------------ resolution
    def _resolve(self, cands: list[Candidate]) -> Outcome:
        """Pick TNUMBER and SITE ID.

        1. The authoritative rule (R1, BTS look-up) wins whenever it produced a valid T-number; any other rule that
           disagrees is overridden and noted (Info), not flagged as a conflict.
        2. Otherwise the highest-priority rule wins (VENDOR_SITE_CODE rules before VENDOR_SITE_CODE_ALT rules). A
           T-number composed from a reference Site ID (R28) is used only when no pattern rule found one. Lower-priority
           disagreements are noted (Info), or flagged as conflicts if derivation.flag_resolved_conflicts is true.
        Unresolvable ambiguity (several values from one rule) is always flagged unless R1 overrides it.
        """
        out = Outcome()
        matched = [c for c in cands if c.status == MATCHED]
        ambiguous = [c for c in cands if c.status == AMBIGUOUS]
        auth = next((c for c in matched if c.rule_id == self.authoritative and c.tnumber), None)

        def t_rank(c: Candidate) -> tuple:
            return (c is not auth, c.t_composed and c.tier == "reference", c.priority)

        t_cands = sorted((c for c in matched if c.tnumber), key=t_rank)
        t_sel = t_cands[0] if t_cands else None
        # SITE ID comes from the same rule as the selected T-number whenever that rule supplies one, so the output
        # never pairs a T-number from one rule with a Site ID from another. Otherwise: reference data, then patterns.
        paired = [t_sel] if t_sel is not None and t_sel.site_id else []
        site_ref = [c for c in matched if c.site_id and c.tier == "reference" and c not in paired]
        site_pat = [c for c in matched if c.site_id and c.tier != "reference" and c not in paired]
        s_cands = paired + site_ref + site_pat
        s_sel = s_cands[0] if s_cands else None

        t_diff = [c for c in t_cands if t_sel and c.tnumber != t_sel.tnumber]
        s_diff = [c for c in s_cands if s_sel and c.site_id != s_sel.site_id]
        overridden_amb = [c for c in ambiguous if auth is not None and c.rule_id != auth.rule_id]
        open_amb = [c for c in ambiguous if c not in overridden_amb]
        flag_diffs = self.flag_resolved_conflicts and auth is None
        withhold_t = self.strict and t_sel is not None and t_sel is not auth and (
            t_diff or any(c.affects_t for c in open_amb))
        withhold_s = self.strict and s_sel is not None and s_sel is not auth and (s_diff or open_amb)
        out.conflict = bool(open_amb) or (flag_diffs and bool(t_diff or s_diff))
        out.candidate_tnumbers = ", ".join(dict.fromkeys(
            [c.tnumber for c in t_cands] + [o for c in ambiguous if c.affects_t for o in c.options if o.startswith("T")]
        ))

        if t_sel and not withhold_t:
            out.tnumber, out.t_rule = t_sel.tnumber, t_sel.rule_id
            out.t_source = t_sel.source + (" (T + Site ID)" if t_sel.t_composed else "")
            out.t_status = "COMPOSED" if t_sel.t_composed else ("MAPPED" if t_sel.tier == "reference" else "DERIVED")
        elif withhold_t:
            out.t_status = "CONFLICT_WITHHELD"
        if s_sel and not withhold_s:
            out.site_id, out.site_rule, out.site_source = s_sel.site_id, s_sel.rule_id, s_sel.source
            out.site_status = "MAPPED" if s_sel.tier == "reference" else "DERIVED"
        elif withhold_s:
            out.site_status = "CONFLICT_WITHHELD"
        elif any(c.status == UNVERIFIED for c in cands):
            out.site_status = "UNVERIFIED"

        overridden = f"OVERRIDDEN BY {auth.rule_id}" if auth else "OVERRIDDEN (LOWER PRIORITY)"
        for c in cands:
            if c in overridden_amb:
                status = f"{c.status}; {overridden}"
            elif c.status != MATCHED:
                status = c.status
            elif (c is t_sel and not withhold_t) and (c is s_sel and not withhold_s):
                status = "SELECTED"
            elif c is t_sel and not withhold_t:
                status = "SELECTED (TNUMBER)"
            elif c is s_sel and not withhold_s:
                status = "SELECTED (SITE ID)"
            elif c in t_diff or c in s_diff:
                status = "CONFLICTING" if flag_diffs else overridden
            elif c is t_sel or c is s_sel:
                status = "WITHHELD (CONFLICT)"
            else:
                status = "SUPPORTING"
            out.candidates.append((c, status))

        issues = out.issues
        winner = (f"{auth.rule_id} (authoritative)" if auth else "rule priority")
        for c in cands:
            if c in overridden_amb:
                issues.append((EX_RESOLVED, "Info", c.rule_id, c.source_field, f"{c.note} - overridden by {auth.rule_id}"))
            elif c.status == AMBIGUOUS:
                category = EX_AMBIGUOUS_REFERENCE if c.tier == "reference" else EX_MULTIPLE_CANDIDATES
                issues.append((category, "High", c.rule_id, c.source_field, c.note))
            elif c.status == INVALID:
                issues.append((EX_INVALID, "Medium", c.rule_id, c.source_field, c.note))
            elif c.status == UNVERIFIED:
                issues.append((EX_UNVERIFIED, "Medium", c.rule_id, c.source_field, c.note))
            elif c.audit_flag and (c is t_sel or c is s_sel):
                issues.append((EX_UNVERIFIED, "Info", c.rule_id, c.source_field, c.audit_flag))
        for c in t_diff:
            if flag_diffs:
                issues.append((EX_CONFLICT, "High", c.rule_id, "TNUMBER",
                               f"Conflicting T-numbers: {t_sel.rule_id} gives {t_sel.tnumber}, {c.rule_id} gives {c.tnumber}"))
            else:
                issues.append((EX_RESOLVED, "Info", c.rule_id, "TNUMBER",
                               f"T-number {t_sel.tnumber} from {t_sel.rule_id} kept by {winner}; {c.rule_id} gave {c.tnumber}"))
        for c in s_diff:
            if flag_diffs:
                issues.append((EX_CONFLICT, "High", c.rule_id, "SITE ID",
                               f"Conflicting Site IDs: {s_sel.rule_id} gives {s_sel.site_id}, {c.rule_id} gives {c.site_id}"))
            else:
                issues.append((EX_RESOLVED, "Info", c.rule_id, "SITE ID",
                               f"Site ID {s_sel.site_id} from {s_sel.rule_id} kept by {winner}; {c.rule_id} gave {c.site_id}"))
        if out.tnumber == CANNOT_BE_DERIVED:
            why = "withheld because of conflicting results (strict matching)" if withhold_t else "no configured rule produced a valid T-number"
            issues.append((EX_UNRESOLVED_T, "Medium", "", "TNUMBER", f"T-number cannot be derived: {why}"))
        if not out.site_id:
            if withhold_s:
                why = "withheld because of conflicting results (strict matching)"
            elif out.site_status == "UNVERIFIED":
                why = "only an unverified candidate was found"
            else:
                why = "no configured rule or reference produced a valid Site ID"
            issues.append((EX_UNRESOLVED_SITE, "Medium", "", "SITE ID", f"Site ID unresolved: {why}"))
        return out

    def _record_limitations(self, out: Outcome, has_source_value: bool) -> None:
        """Explain, against the record, why an unresolved value could not be established."""
        unresolved = out.tnumber == CANNOT_BE_DERIVED or not out.site_id
        if not unresolved:
            return
        if not has_source_value:
            out.issues.insert(0, (EX_MISSING_SOURCE_VALUE, "Medium", "", "VENDOR_SITE_CODE",
                                  "Source record has no Vendor Site Code value to derive from"))
            return
        for label, rule_ids in self.missing_references.items():
            out.issues.append((EX_MISSING_REFERENCE, "Info", ", ".join(rule_ids), label,
                               f"Not checked against the {label} ({', '.join(rule_ids)}) because it was not supplied"))

    # ------------------------------------------------------------------ main entry point
    def derive(self, source: Table, progress: Callable[[float], None] | None = None) -> EngineResult:
        global_ex: list[ExceptionItem] = []
        self.missing_references = {}
        self.fallback_used: dict[str, list[str]] = {}  # fallback column -> rule IDs reading it
        bound, runtime = self._bind_rules(source, global_ex)
        key_pos = self._key_pos(source)
        vsc_pos = source.columns.get("VENDOR_SITE_CODE")
        alt_pos = source.columns.get("VENDOR_SITE_CODE_ALT")
        source_cols = {k: (pos, source.headers[pos]) for k, pos in source.columns.items()}
        value_keys = [k for k in ("VENDOR_SITE_CODE", "VENDOR_SITE_CODE_ALT", "VENDOR_SITE") if k in source_cols]
        bts_alt_field = "VENDOR_SITE_CODE_ALT (matched on VENDOR_SITE_CODE)"

        def evaluate(values: tuple[str, ...]) -> Outcome:
            row = dict(zip(col_keys, values))
            key_text = values[0]
            key = match_key(key_text)
            cands: list[Candidate] = []
            evaluated: list[str] = []
            for rule, src in bound:
                if src == "reference":
                    if not key:
                        continue
                    evaluated.append(rule.rule_id)
                    producer = self._bts_candidates if rule.kind == RuleKind.BTS_REFERENCE else self._ops_candidates
                    cands.extend(producer(rule, key, key_text))
                elif src.startswith("source:"):
                    column = src.split(":", 1)[1]
                    value = row.get(column, "")
                    if not value:
                        continue
                    evaluated.append(rule.rule_id)
                    cands.extend(self._pattern_candidates(rule, value, SOURCE_DATASET, source.file_name,
                                                          source_cols[column][1]))
                else:  # bts_alt
                    entries = self.refs.bts.get(key, []) if key else []
                    alts = list(dict.fromkeys(e.alt_raw for e in entries if e.alt_raw))
                    if not alts:
                        continue
                    evaluated.append(rule.rule_id)
                    files = ", ".join(sorted({e.file for e in entries}))
                    for alt in alts:
                        cands.extend(self._pattern_candidates(rule, alt, BTS_DATASET, files, bts_alt_field))
            out = self._resolve(cands)
            out.evaluated = tuple(evaluated)
            self._record_limitations(out, any(match_key(row.get(k, "")) for k in value_keys))
            return out

        # Distinct value combinations are evaluated once; identical records share the outcome.
        col_keys = ["__KEY__"] + list(source_cols)
        positions = [key_pos] + [source_cols[k][0] for k in col_keys[1:]]
        frame = source.df
        texts = [[cell_text(v) for v in frame[p].tolist()] if p is not None else [""] * len(frame) for p in positions]
        combos = list(zip(*texts)) if texts else []
        counts = Counter(combos)
        cache: dict[tuple[str, ...], Outcome] = {}
        total = max(len(counts), 1)
        for n, combo in enumerate(counts, start=1):
            cache[combo] = evaluate(combo)
            if progress and n % 500 == 0:
                progress(n / total)
        if progress:
            progress(1.0)

        stats: dict[str, RuleStats] = {r.rule_id: RuleStats() for r in self.ruleset.rules}
        for combo, mult in counts.items():
            out = cache[combo]
            for rid in out.evaluated:
                stats[rid].evaluated += mult
            for c, status in out.candidates:
                st = stats[c.rule_id]
                if c.status == MATCHED:
                    st.matched += mult
                else:
                    st.exceptions += mult
                if status.startswith("SELECTED"):
                    if c.rule_id == out.t_rule and c.tnumber == out.tnumber:
                        st.selected_t += mult
                    if c.rule_id == out.site_rule and c.site_id == out.site_id:
                        st.selected_site += mult

        vsc_idx = col_keys.index("VENDOR_SITE_CODE") if vsc_pos is not None else 0
        alt_idx = col_keys.index("VENDOR_SITE_CODE_ALT") if alt_pos is not None else None
        records = [
            RecordResult(
                row_index=i,
                row_number=source.row_numbers[i],
                vendor_site_code=combo[vsc_idx],
                vendor_site_code_alt=combo[alt_idx] if alt_idx is not None else "",
                outcome=cache[combo],
            )
            for i, combo in enumerate(combos)
        ]
        self._cross_record_conflicts(records)

        exceptions = list(global_ex)
        for r in records:
            for category, severity, rule_id, fld, detail in r.outcome.issues:
                exceptions.append(ExceptionItem(category, severity, r.row_number, rule_id, source.file_name,
                                                fld, r.vendor_site_code, detail))
            for detail in r.cross_reasons:
                exceptions.append(ExceptionItem(EX_CONFLICT, "High", r.row_number, "", source.file_name,
                                                "VENDOR_SITE_CODE", r.vendor_site_code, detail))
        if source.blank_rows_skipped:
            exceptions.append(ExceptionItem(EX_DATA_QUALITY, "Info", None, "", source.file_name, "", "",
                                            f"{source.blank_rows_skipped} completely blank row(s) in the source worksheet were not treated as records."))

        notes = []
        if vsc_pos is None and key_pos is not None:
            notes.append("Source file has no VENDOR_SITE_CODE column; 'Vendor Site' was used as the matching key.")
        for column, rule_ids in self.fallback_used.items():
            notes.append(
                f"Source file has no column for {', '.join(rule_ids)}; they read '{source_cols[column][1]}' "
                "instead (source_column_fallbacks in rule_config.json)."
            )
        return EngineResult(
            records=records,
            exceptions=exceptions,
            rule_stats=stats,
            rule_runtime_status=runtime,
            metrics=self._metrics(records, exceptions),
            notes=notes,
        )

    @staticmethod
    def _cross_record_conflicts(records: list[RecordResult]) -> None:
        """The same Vendor Site Code must not resolve to different T-numbers / Site IDs across records."""
        groups: dict[str, list[RecordResult]] = defaultdict(list)
        for r in records:
            key = match_key(r.vendor_site_code)
            if key:
                groups[key].append(r)
        for group in groups.values():
            if len(group) < 2:
                continue
            ts = sorted({r.outcome.tnumber for r in group if r.outcome.tnumber != CANNOT_BE_DERIVED})
            ss = sorted({r.outcome.site_id for r in group if r.outcome.site_id})
            reasons = []
            if len(ts) > 1:
                reasons.append(f"Same Vendor Site Code resolves to different T-numbers across records: {', '.join(ts)}")
            if len(ss) > 1:
                reasons.append(f"Same Vendor Site Code resolves to different Site IDs across records: {', '.join(ss)}")
            if reasons:
                for r in group:
                    r.cross_reasons.extend(reasons)

    @staticmethod
    def _metrics(records: list[RecordResult], exceptions: list[ExceptionItem]) -> dict[str, Any]:
        n = len(records)
        t_ok = sum(r.outcome.tnumber != CANNOT_BE_DERIVED for r in records)
        s_ok = sum(bool(r.outcome.site_id) for r in records)
        pct = (lambda x: round(100.0 * x / n, 2) if n else 0.0)
        return {
            "input_rows": n,
            "output_rows": n,
            "tnumber_derived": t_ok,
            "tnumber_unresolved": n - t_ok,
            "site_id_derived": s_ok,
            "site_id_unresolved": n - s_ok,
            "conflicting_records": sum(r.conflict for r in records),
            "tnumber_match_rate_pct": pct(t_ok),
            "site_id_match_rate_pct": pct(s_ok),
            "tnumber_derived_by_rule": dict(Counter(r.outcome.t_rule for r in records if r.outcome.t_rule)),
            "site_id_derived_by_rule": dict(Counter(r.outcome.site_rule for r in records if r.outcome.site_rule)),
            "tnumber_status_counts": dict(Counter(r.outcome.t_status for r in records)),
            "site_id_status_counts": dict(Counter(r.outcome.site_status for r in records)),
            "exception_counts": dict(Counter(e.category for e in exceptions)),
        }
