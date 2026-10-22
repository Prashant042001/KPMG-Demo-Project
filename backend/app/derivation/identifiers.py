"""Approved identifier formats (T-number, Site ID) and compiled rule patterns."""
from __future__ import annotations

import re
from typing import Any

from app.core.text import match_key
from app.rules.catalog import RuleKind
from app.rules.loader import RuleSet


class IdentifierFormats:
    def __init__(self, ruleset: RuleSet, rule_config: dict[str, Any]):
        lo, hi = ruleset.t_digits
        self.t_quantifier = f"{lo},{hi}"
        self.t_re = re.compile(rf"^T(\d{{{lo},{hi}}})$")
        fmt = rule_config["identifier_formats"]
        self.site_numeric_re = re.compile(fmt["numeric_site_id_pattern"])
        self.site_x_re = re.compile(fmt["x_site_id_pattern"])

    def tnumber(self, raw: object) -> str | None:
        """Normalised T-number if ``raw`` is a valid T-number, else ``None``."""
        s = match_key(raw).replace(" ", "")
        return s if self.t_re.match(s) else None

    def compose_tnumber(self, site_id: str) -> str | None:
        t = f"T{site_id}"
        return t if self.t_re.match(t) else None

    def site_id(self, raw: object) -> tuple[str | None, bool]:
        """Clean a reference Site ID. Returns (value, is_valid); a T-number reduces to its numeric component.

        Values with suffixes or other text are *not* stripped: they are reported as invalid instead.
        """
        s = match_key(raw).replace(" ", "")
        if not s:
            return None, True
        if self.site_numeric_re.match(s) or self.site_x_re.match(s):
            return s, True
        m = self.t_re.match(s)
        if m:
            return m.group(1), True
        return None, False

    def is_numeric_site_id(self, s: str) -> bool:
        return bool(self.site_numeric_re.match(s))

    def is_x_site_id(self, s: str) -> bool:
        return bool(self.site_x_re.match(s))


def compile_patterns(rule_config: dict[str, Any], ruleset: RuleSet, formats: IdentifierFormats) -> dict[RuleKind, re.Pattern[str]]:
    compiled: dict[RuleKind, re.Pattern[str]] = {}
    for name, template in rule_config["patterns"].items():
        if name.startswith("_"):
            continue
        tpl = template.replace("{T}", formats.t_quantifier)
        if "{SUFFIXES}" in tpl:
            if not ruleset.recognised_suffixes:
                continue  # rule stays unconfirmed until suffixes are approved
            tpl = tpl.replace("{SUFFIXES}", "|".join(f"(?:{s})" for s in ruleset.recognised_suffixes))
        compiled[RuleKind(name)] = re.compile(tpl)
    return compiled
