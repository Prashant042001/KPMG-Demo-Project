"""In-memory look-up indexes built from the BTS Site Report Schedule and the Operational Site List Summary."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.text import cell_text, match_key
from app.derivation.identifiers import IdentifierFormats
from app.ingest.readers import Table


@dataclass(frozen=True)
class BtsEntry:
    t_raw: str
    site_raw: str
    alt_raw: str
    file: str
    row: int


@dataclass(frozen=True)
class OpsEntry:
    site_raw: str
    file: str
    row: int


@dataclass
class ReferenceData:
    bts: dict[str, list[BtsEntry]] = field(default_factory=dict)
    ops: dict[str, list[OpsEntry]] = field(default_factory=dict)
    site_ids: set[str] = field(default_factory=set)  # clean Site IDs known to the reference data
    bts_tables: int = 0
    ops_tables: int = 0
    bts_has_alt: bool = False
    bts_has_site: bool = False
    bts_t_header: str = "T number"
    ops_site_header: str = "Site ID"

    @property
    def bts_duplicate_keys(self) -> int:
        return sum(1 for v in self.bts.values() if len(v) > 1)

    @property
    def ops_duplicate_keys(self) -> int:
        return sum(1 for v in self.ops.values() if len(v) > 1)


def _col(table: Table, key: str):
    pos = table.columns.get(key)
    return None if pos is None else table.df[pos]


def build_reference_data(
    bts_tables: list[Table], ops_tables: list[Table], formats: IdentifierFormats, missing_markers: set[str] = frozenset()
) -> ReferenceData:
    """Index the reference datasets. Cells holding a 'no value' marker (e.g. NA, #N/A) are treated as blank."""
    ref = ReferenceData(bts_tables=len(bts_tables), ops_tables=len(ops_tables))

    def text(v: object) -> str:
        t = cell_text(v)
        return "" if match_key(t) in missing_markers else t

    for t in bts_tables:
        keys, tnums = _col(t, "VENDOR_SITE_CODE"), _col(t, "T_NUMBER")
        sites, alts = _col(t, "SITE_ID"), _col(t, "VENDOR_SITE_CODE_ALT")
        ref.bts_has_alt |= alts is not None
        ref.bts_has_site |= sites is not None
        ref.bts_t_header = t.header_of("T_NUMBER") or ref.bts_t_header
        for i in range(t.row_count):
            key = match_key(keys.iat[i])
            if not key:
                continue
            entry = BtsEntry(
                t_raw=text(tnums.iat[i]),
                site_raw=text(sites.iat[i]) if sites is not None else "",
                alt_raw=text(alts.iat[i]) if alts is not None else "",
                file=t.file_name,
                row=t.row_numbers[i],
            )
            ref.bts.setdefault(key, []).append(entry)
            if entry.site_raw:
                site, ok = formats.site_id(entry.site_raw)
                if ok and site:
                    ref.site_ids.add(site)

    for t in ops_tables:
        keys, sites = _col(t, "ACCOUNT_NUMBER"), _col(t, "SITE_ID")
        ref.ops_site_header = t.header_of("SITE_ID") or ref.ops_site_header
        for i in range(t.row_count):
            key = match_key(keys.iat[i])
            if not key:
                continue
            site_raw = text(sites.iat[i])
            ref.ops.setdefault(key, []).append(OpsEntry(site_raw=site_raw, file=t.file_name, row=t.row_numbers[i]))
            site, ok = formats.site_id(site_raw)
            if ok and site:
                ref.site_ids.add(site)
    return ref
