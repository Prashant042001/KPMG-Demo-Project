"""Catalogue of the rule kinds the derivation engine can execute.

Each approved rule in ``config/rule_config.json`` names one of these kinds explicitly, so no free-text
interpretation of rule descriptions takes place at run time.
"""
from __future__ import annotations

from enum import Enum


class RuleKind(str, Enum):
    BTS_REFERENCE = "BTS_REFERENCE"  # look up VENDOR_SITE_CODE in the BTS Site Report Schedule
    OPS_REFERENCE = "OPS_REFERENCE"  # look up Vendor Site Code against Account Number in the Operational Site List
    T_LENGTH = "T_LENGTH"  # modifier: T-numbers may have 4 or 5 digits
    T_DIRECT = "T_DIRECT"  # T6542
    DIGITS_MTN = "DIGITS_MTN"  # 3133MTN
    X_PREFIX = "X_PREFIX"  # X8754 (candidate Site ID, reference-validated)
    T_SUFFIX_ELEC = "T_SUFFIX_ELEC"  # T8646/ELEC
    T_SUFFIX_E = "T_SUFFIX_E"  # T7386/E
    T_OTHER_SUFFIX = "T_OTHER_SUFFIX"  # T1234<approved suffix>
    T_EMBEDDED = "T_EMBEDDED"  # ABC-T8102-RENT
    NUM_MTN_S = "NUM_MTN_S"  # 3133MTN/S
    NUM_MTN_E = "NUM_MTN_E"  # 3133MTN/E
    MTN_PREFIX_NUM = "MTN_PREFIX_NUM"  # MTN3133
    LEADING_NUMERIC = "LEADING_NUMERIC"  # 3133-ANYTHING
    LEADING_ZERO = "LEADING_ZERO"  # 0123


REFERENCE_KINDS = {RuleKind.BTS_REFERENCE, RuleKind.OPS_REFERENCE}
MODIFIER_KINDS = {RuleKind.T_LENGTH}
# Pattern rules whose match is a T-number (Site ID is its numeric component).
T_PATTERN_KINDS = {
    RuleKind.T_DIRECT,
    RuleKind.DIGITS_MTN,
    RuleKind.T_SUFFIX_ELEC,
    RuleKind.T_SUFFIX_E,
    RuleKind.T_OTHER_SUFFIX,
    RuleKind.T_EMBEDDED,
}
# Pattern rules whose match is a Site ID only.
SITE_PATTERN_KINDS = {
    RuleKind.NUM_MTN_S,
    RuleKind.NUM_MTN_E,
    RuleKind.MTN_PREFIX_NUM,
    RuleKind.LEADING_NUMERIC,
    RuleKind.LEADING_ZERO,
}
