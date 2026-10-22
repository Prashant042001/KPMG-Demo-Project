"""Configurable, case-insensitive column identification."""
from __future__ import annotations

from typing import Iterable

from app.core.text import norm_header


class ColumnResolver:
    """Maps workbook header text to canonical column keys (``VENDOR_SITE_CODE``, ``T_NUMBER``...)."""

    def __init__(self, aliases: dict[str, list[str]]):
        self._alias_to_key: dict[str, str] = {}
        for key, names in aliases.items():
            for name in [key, *names]:
                self._alias_to_key.setdefault(norm_header(name), key)

    def key_for(self, header: object) -> str | None:
        return self._alias_to_key.get(norm_header(header))

    def resolve(self, headers: Iterable[object]) -> dict[str, int]:
        """Return canonical key -> first column position whose header matches it."""
        found: dict[str, int] = {}
        for pos, header in enumerate(headers):
            key = self.key_for(header)
            if key and key not in found:
                found[key] = pos
        return found
