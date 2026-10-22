"""Safe reading of XLSX / XLS / CSV uploads into raw worksheet grids, and header-row detection.

Files are read from in-memory bytes only; nothing is written to disk.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass, field

import pandas as pd

from app.core.errors import FileValidationError
from app.core.text import cell_text, safe_filename
from app.ingest.columns import ColumnResolver

log = logging.getLogger(__name__)

XLSX_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# A legitimate workbook rarely inflates beyond ~20x its compressed size; larger ratios suggest a zip bomb.
MAX_INFLATION_RATIO = 50
CSV_ENCODINGS = ("utf-8-sig", "cp1252")


@dataclass
class UploadedFile:
    name: str
    data: bytes
    slot: str  # "base" | "rules" | "supporting" | "local"

    def __post_init__(self) -> None:
        self.name = safe_filename(self.name)

    @property
    def extension(self) -> str:
        dot = self.name.rfind(".")
        return self.name[dot:].lower() if dot >= 0 else ""

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class Table:
    """One worksheet, sliced at its detected header row. ``df`` holds original cell values with positional columns."""

    file_name: str
    sheet_name: str
    header_row: int  # 1-based worksheet row containing the headers
    headers: list[str]
    df: pd.DataFrame
    columns: dict[str, int]  # canonical key -> column position
    row_numbers: list[int] = field(default_factory=list)  # 1-based worksheet row of each df row
    blank_rows_skipped: int = 0

    @property
    def row_count(self) -> int:
        return len(self.df)

    def header_of(self, key: str) -> str | None:
        pos = self.columns.get(key)
        return None if pos is None else self.headers[pos]


def check_extension(f: UploadedFile, allowed: set[str]) -> None:
    if f.extension not in allowed:
        raise FileValidationError(
            f"'{f.name}' has an unsupported file type. Allowed types: {', '.join(sorted(allowed))}."
        )
    if f.size == 0:
        raise FileValidationError(f"'{f.name}' is empty.")


def _check_signature(f: UploadedFile) -> None:
    head = f.data[:8]
    if f.extension == ".xlsx":
        if not head.startswith(XLSX_MAGIC):
            raise FileValidationError(
                f"'{f.name}' is not a valid .xlsx workbook (it may be password-protected or mislabelled)."
            )
        try:
            with zipfile.ZipFile(io.BytesIO(f.data)) as zf:
                names = set(zf.namelist())
                inflated = sum(i.file_size for i in zf.infolist())
        except zipfile.BadZipFile as exc:
            raise FileValidationError(f"'{f.name}' is corrupt and cannot be opened.") from exc
        if "xl/workbook.xml" not in names:
            raise FileValidationError(f"'{f.name}' is not an Excel workbook.")
        if inflated > max(f.size * MAX_INFLATION_RATIO, 50 * 1024 * 1024):
            raise FileValidationError(f"'{f.name}' expands to an unsafe size and was rejected.")
    elif f.extension == ".xls":
        if not head.startswith(OLE_MAGIC):
            raise FileValidationError(f"'{f.name}' is not a valid legacy .xls workbook.")
    elif f.extension == ".csv":
        if b"\x00" in f.data[:8192]:
            raise FileValidationError(f"'{f.name}' does not look like a text CSV file.")


def _read_csv(f: UploadedFile) -> pd.DataFrame:
    text = None
    for enc in CSV_ENCODINGS:
        try:
            text = f.data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise FileValidationError(f"'{f.name}' uses an unsupported text encoding (use UTF-8).")
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    # The csv module tolerates ragged rows (e.g. title lines above the header), unlike pandas' C parser.
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame([r + [""] * (width - len(r)) for r in rows], dtype=object)


def read_raw_sheets(f: UploadedFile, allowed: set[str]) -> dict[str, pd.DataFrame]:
    """Return every worksheet as a header-less grid of original cell values."""
    check_extension(f, allowed)
    _check_signature(f)
    if f.extension == ".csv":
        return {"CSV": _read_csv(f)}
    engine = "openpyxl" if f.extension == ".xlsx" else "xlrd"
    try:
        # openpyxl is opened read-only with cached values: formulas are never evaluated.
        sheets = pd.read_excel(
            io.BytesIO(f.data), sheet_name=None, header=None, dtype=object, engine=engine, na_filter=False
        )
    except ImportError as exc:
        raise FileValidationError(f"Reading {f.extension} files is not available on this server.") from exc
    except Exception as exc:  # noqa: BLE001 - library errors vary widely; never leak their text
        log.warning("Workbook read failed (%s): %s", f.extension, type(exc).__name__)
        raise FileValidationError(f"'{f.name}' could not be read as an Excel workbook.") from exc
    return {str(name): grid for name, grid in sheets.items()}


def detect_header(
    raw: pd.DataFrame, resolver: ColumnResolver, wanted: set[str], scan_rows: int
) -> tuple[int, dict[str, int]]:
    """Find the row (0-based) whose cells match the most wanted column keys. Returns (-1, {}) if none match."""
    best_idx, best_cols, best_score = -1, {}, 0
    for idx in range(min(scan_rows, len(raw))):
        cols = resolver.resolve(cell_text(v) for v in raw.iloc[idx].tolist())
        score = len(wanted.intersection(cols))
        if score > best_score:
            best_idx, best_cols, best_score = idx, cols, score
    return best_idx, best_cols


def _is_blank(v: object) -> bool:
    return cell_text(v) == ""


def build_table(file_name: str, sheet_name: str, raw: pd.DataFrame, header_idx: int, columns: dict[str, int]) -> Table:
    headers = [cell_text(v) for v in raw.iloc[header_idx].tolist()]
    data = raw.iloc[header_idx + 1 :]

    # Drop trailing columns that have neither a header nor any data (unused Excel range).
    width = len(headers)
    while width > 0 and headers[width - 1] == "" and data.iloc[:, width - 1].map(_is_blank).all():
        width -= 1
    headers = headers[:width]
    data = data.iloc[:, :width]

    # Entirely blank lines are not records; they are counted and reported, never silently lost.
    blank = data.map(_is_blank).all(axis=1) if width else pd.Series(True, index=data.index)
    kept = data[~blank]
    df = kept.reset_index(drop=True)
    df.columns = range(width)
    return Table(
        file_name=file_name,
        sheet_name=sheet_name,
        header_row=header_idx + 1,
        headers=headers,
        df=df,
        columns={k: v for k, v in columns.items() if v < width},
        row_numbers=[int(i) + 1 for i in kept.index],
        blank_rows_skipped=int(blank.sum()),
    )
