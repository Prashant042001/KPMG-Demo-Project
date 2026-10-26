"""Row-level results view for the UI: one compact dict per source record, with server-side search and filters."""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.core.text import match_key
from app.derivation.engine import CANNOT_BE_DERIVED, EngineResult

# Status filters offered by GET /api/jobs/{job_id}/records (and shown as quick filters in the UI).
STATUS_FILTERS = {
    "all": lambda r: True,
    "tnumber_derived": lambda r: r["tnumber"] != CANNOT_BE_DERIVED,
    "tnumber_unresolved": lambda r: r["tnumber"] == CANNOT_BE_DERIVED,
    "site_id_unresolved": lambda r: not r["site_id"],
    "conflict": lambda r: r["conflict"],
    "overridden": lambda r: r["overridden"],
}
# Fields searched by the free-text box.
SEARCH_FIELDS = ("vendor_site_code", "vendor_site_code_alt", "tnumber", "site_id", "candidate_tnumbers", "exception_reason")
MAX_PAGE_SIZE = 500


def build_record_rows(result: EngineResult) -> list[dict[str, Any]]:
    rows = []
    for r in result.records:
        o = r.outcome
        rows.append(
            {
                "row": r.row_number,
                "vendor_site_code": r.vendor_site_code,
                "vendor_site_code_alt": r.vendor_site_code_alt,
                "candidate_tnumbers": o.candidate_tnumbers,
                "tnumber": o.tnumber,
                "site_id": o.site_id,
                "tnumber_rule": o.t_rule,
                "site_id_rule": o.site_rule,
                "tnumber_status": o.t_status,
                "site_id_status": o.site_status,
                "conflict": r.conflict,
                "overridden": any(status.startswith("OVERRIDDEN") or "; OVERRIDDEN" in status for _, status in o.candidates),
                "exception_reason": r.exception_reason,
            }
        )
    return rows


def filter_records(
    rows: list[dict[str, Any]],
    *,
    q: str = "",
    status: str = "all",
    rule: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Search (case-, spacing- and punctuation-tolerant substring), filter and paginate the result rows."""
    keep = STATUS_FILTERS.get(status, STATUS_FILTERS["all"])
    needle = match_key(q)
    needle_compact = needle.replace(" ", "")
    rule = rule.strip().upper()

    def matches_text(r: dict[str, Any]) -> bool:
        if not needle:
            return True
        if str(r["row"]) == needle:
            return True
        for f in SEARCH_FIELDS:
            hay = match_key(r[f])
            if needle in hay or (needle_compact and needle_compact in hay.replace(" ", "")):
                return True
        return False

    def matches_rule(r: dict[str, Any]) -> bool:
        return not rule or rule in (r["tnumber_rule"], r["site_id_rule"])

    searched = [r for r in rows if matches_text(r) and matches_rule(r)]
    counts = {name: sum(1 for r in searched if fn(r)) for name, fn in STATUS_FILTERS.items()}
    selected = [r for r in searched if keep(r)]

    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    pages = max(1, -(-len(selected) // page_size))
    page = max(1, min(int(page), pages))
    start = (page - 1) * page_size
    return {
        "total_rows": len(rows),
        "matching_rows": len(selected),
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "counts": counts,  # per status filter, after search and rule filter
        "rules": sorted(
            Counter(x for r in rows for x in {r["tnumber_rule"], r["site_id_rule"]} if x),
            key=lambda x: (len(x), x),
        ),
        "rows": selected[start : start + page_size],
    }
