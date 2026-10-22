"""Build the ordered, auditable ``RuleSet`` from the version-controlled backend rule configuration.

``config/rule_config.json`` is the authoritative source of the approved T-number / Site ID rules; users do not
upload rules. Rules the business has not fully approved stay in the configuration with status
``requires_confirmation``: they are reported, never executed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.rules.catalog import MODIFIER_KINDS, REFERENCE_KINDS, RuleKind

ACTIVE = "ACTIVE"
REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
DUPLICATE = "DUPLICATE"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

_COLUMN_LABELS = {
    "VENDOR_SITE_CODE": "VENDOR_SITE_CODE",
    "VENDOR_SITE_CODE_ALT": "VENDOR_SITE_CODE_ALT",
    "VENDOR_SITE": "Vendor Site",
    "T_NUMBER": "T number",
    "SITE_ID": "Site ID",
    "ACCOUNT_NUMBER": "Account Number",
}


class RuleConfigError(ValueError):
    """The rule configuration file is malformed (a deployment error, not a user error)."""


@dataclass
class Rule:
    rule_id: str
    order: int  # position in the configuration
    data_source: str
    column_name: str
    matching_column: str
    description: str
    additional_info: str
    kind: RuleKind | None
    source_column: str | None  # canonical key of the column the rule reads
    priority: int = 0
    status: str = ACTIVE
    status_reason: str = ""
    duplicate_of: str | None = None
    confirmation_note: str = ""  # what the business still has to decide, from the configuration

    @property
    def executable(self) -> bool:
        return self.status == ACTIVE and self.kind is not None and self.kind not in MODIFIER_KINDS

    @property
    def tier(self) -> str:
        return "reference" if self.kind in REFERENCE_KINDS else "pattern"


@dataclass
class RuleSet:
    rules: list[Rule]
    t_digits: tuple[int, int]
    recognised_suffixes: list[str]
    version: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def executable(self) -> list[Rule]:
        return sorted((r for r in self.rules if r.executable), key=lambda r: (r.priority, r.order))

    def by_id(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.rule_id == rule_id), None)


def load_ruleset(rule_config: dict[str, Any]) -> RuleSet:
    entries = rule_config.get("rules")
    if not isinstance(entries, list) or not entries:
        raise RuleConfigError("rule_config.json defines no rules.")

    rules: list[Rule] = []
    for order, e in enumerate(entries):
        try:
            rule_id = str(e["id"]).strip().upper()
            kind = RuleKind(e["kind"])
        except (KeyError, ValueError) as exc:
            raise RuleConfigError(f"Invalid rule entry at position {order + 1} in rule_config.json.") from exc
        column = e.get("column")
        rule = Rule(
            rule_id=rule_id,
            order=order,
            data_source=e.get("data_source", ""),
            column_name=_COLUMN_LABELS.get(column, column or ""),
            matching_column=_COLUMN_LABELS.get(e.get("matching_column"), e.get("matching_column") or ""),
            description=e.get("description", ""),
            additional_info=e.get("additional_info", ""),
            kind=kind,
            source_column=column if column in rule_config["columns"] else None,
            confirmation_note=e.get("confirmation_needed", ""),
        )
        if e.get("status", "approved") != "approved":
            rule.status = REQUIRES_CONFIRMATION
            rule.status_reason = rule.confirmation_note or "Rule is not yet approved by the business; it was not executed."
        rules.append(rule)

    suffixes = [s for s in rule_config.get("recognised_suffixes", {}).get("values", []) if s]
    fmt = rule_config["identifier_formats"]
    has_length_rule = any(r.kind == RuleKind.T_LENGTH and r.status == ACTIVE for r in rules)
    lo, hi = fmt["tnumber_digit_lengths_with_length_rule" if has_length_rule else "tnumber_digit_lengths_default"]

    _validate(rules, suffixes)
    _assign_priority(rules, rule_config.get("derivation", {}))

    return RuleSet(
        rules=rules,
        t_digits=(int(lo), int(hi)),
        recognised_suffixes=suffixes,
        version=str(rule_config.get("version", "")),
    )


def _validate(rules: list[Rule], suffixes: list[str]) -> None:
    seen_ids: set[str] = set()
    seen_logic: dict[tuple, Rule] = {}
    for r in rules:
        if r.rule_id in seen_ids:
            raise RuleConfigError(f"Rule ID {r.rule_id} is defined more than once in rule_config.json.")
        seen_ids.add(r.rule_id)
        if r.status != ACTIVE:
            continue
        if r.kind in MODIFIER_KINDS:
            r.status_reason = "Modifier: T-numbers may contain 4 or 5 digits."
            continue
        if r.kind not in REFERENCE_KINDS and r.source_column is None:
            r.status, r.status_reason = REQUIRES_CONFIRMATION, f"Column '{r.column_name}' is not a configured source column."
            continue
        if r.kind == RuleKind.T_OTHER_SUFFIX and not suffixes:
            r.status, r.status_reason = (
                REQUIRES_CONFIRMATION,
                "No recognised suffixes/delimiters are approved (recognised_suffixes.values), so arbitrary text is not "
                "stripped and the rule was not executed. " + r.confirmation_note,
            )
            continue
        logic = (r.kind, r.source_column)
        if logic in seen_logic:
            first = seen_logic[logic]
            r.status, r.duplicate_of = DUPLICATE, first.rule_id
            r.status_reason = f"Same logic and column as {first.rule_id}; evaluated once under {first.rule_id}."
            continue
        seen_logic[logic] = r


def _assign_priority(rules: list[Rule], derivation_cfg: dict[str, Any]) -> None:
    """Reference look-ups first (if configured), then configuration order; explicit overrides win."""
    ref_first = derivation_cfg.get("reference_rules_first", True)
    overrides = {k.upper(): v for k, v in derivation_cfg.get("priority_overrides", {}).items()}
    ordered = sorted(rules, key=lambda r: ((0 if (ref_first and r.tier == "reference") else 1), r.order))
    for pos, r in enumerate(ordered, start=1):
        r.priority = int(overrides.get(r.rule_id, pos * 10))
