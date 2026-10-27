"""Configurable, case-insensitive column identification."""
from __future__ import annotations

from typing import Iterable

from app.core.text import norm_header


class ColumnResolver:
    """Maps workbook header text to canonical column keys (``VENDOR_SITE_CODE``, ``T_NUMBER``...)."""

    def __init__(self, aliases: dict[str, list[str]]):
        # normalised alias -> (key, rank); a lower rank is a more preferred alias for that key
        self._alias_to_key: dict[str, tuple[str, int]] = {}
        for key, names in aliases.items():
            for rank, name in enumerate([*names, key]):
                self._alias_to_key.setdefault(norm_header(name), (key, rank))

    def key_for(self, header: object) -> str | None:
        hit = self._alias_to_key.get(norm_header(header))
        return hit[0] if hit else None

    def resolve(self, headers: Iterable[object]) -> dict[str, int]:
        """Return canonical key -> column position whose header matches it.

        When several columns match one key, the column with the earliest-listed alias wins; ties keep the first column.
        """
        found: dict[str, tuple[int, int]] = {}  # key -> (rank, position)
        for pos, header in enumerate(headers):
            hit = self._alias_to_key.get(norm_header(header))
            if hit and (hit[0] not in found or hit[1] < found[hit[0]][0]):
                found[hit[0]] = (hit[1], pos)
        return {key: pos for key, (_, pos) in found.items()}
