"""Small, dependency-free normalisation helpers shared by readers, rules and the derivation engine."""
from __future__ import annotations

import datetime as _dt
import math
import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def norm_header(value: object) -> str:
    """Canonical form for comparing column headers: lower-case, alphanumerics only."""
    if value is None:
        return ""
    return _NON_ALNUM.sub("", str(value).lower())


def cell_text(value: object) -> str:
    """Render a source cell as text for matching, without altering the source data itself.

    Excel numerics that are whole numbers (``1234.0``) are rendered as ``1234`` so that
    account numbers and site codes stored as numbers still match their text equivalents.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


# Invisible characters that commonly survive Excel/CSV exports: zero-width space/joiners, word joiner,
# byte-order mark and soft hyphen. str.split() does not treat them as whitespace.
_INVISIBLE = re.compile("[​‌‍⁠﻿­]")


def match_key(value: object) -> str:
    """Comparison form of a value, used for look-ups and rule patterns (the source value itself is never changed).

    Unicode NFKC normalisation folds full-width digits/letters, non-breaking spaces and similar look-alikes to
    their plain forms; invisible characters and control characters are removed; the result is trimmed,
    upper-cased and has internal whitespace collapsed to single spaces.
    """
    text = unicodedata.normalize("NFKC", cell_text(value))
    text = _CONTROL.sub(" ", _INVISIBLE.sub("", text))
    return " ".join(text.upper().split())


def safe_filename(name: str | None, *, max_len: int = 120) -> str:
    """Display-safe base filename: no directories, no control characters, bounded length."""
    if not name:
        return "unnamed"
    name = unicodedata.normalize("NFKC", name)
    name = name.replace("\\", "/").split("/")[-1]
    name = _CONTROL.sub("", name).strip().strip(".")
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: max_len - len(ext) - 1] + dot + ext) if dot and len(ext) <= 8 else name[:max_len]
    return name or "unnamed"
