"""Verified, format-independent loading of local research data tables.

No file format implies a real-data provenance claim. The caller must retain the
dataset manifest's source and is_synthetic fields in every research result.
"""
from pathlib import Path
import hashlib
import re
import pandas as pd

TABLE_NAMES = {"prices", "industry_panel", "stock_panel", "membership", "styles"}
FORMATS = {".csv", ".parquet"}


def local_table_path(directory: Path, filename: str) -> Path:
    """Resolve only a local basename; never follow a table outside its dataset."""
    if (not isinstance(filename, str) or not filename or
            filename in {".", ".."} or "/" in filename or "\\" in filename or ":" in filename or
            Path(filename).is_absolute()):
        raise ValueError("Dataset table filenames must be local basenames")
    root = Path(directory).resolve()
    path = root / filename
    if path.suffix.lower() not in FORMATS:
        raise ValueError("Dataset tables must use .csv or .parquet")
    if path.resolve().parent != root:
        raise ValueError("Dataset table path escapes the dataset directory")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Dataset table is missing: {filename}")
    return path


def resolve_table(directory: Path, manifest: dict, name: str) -> Path:
    """Resolve and hash-check the file actually consumed by a research stage.

    Legacy CSV manifests need no mapping. When both formats exist, the manifest
    must explicitly identify which one belongs to each logical table.
    """
    if name not in TABLE_NAMES:
        raise ValueError(f"Unknown logical dataset table: {name}")
    hashes = manifest.get("sha256")
    if not isinstance(hashes, dict):
        raise ValueError("Dataset manifest requires a sha256 mapping")
    mapping = manifest.get("logical_tables", {})
    if not isinstance(mapping, dict):
        raise ValueError("logical_tables must map table names to local filenames")
    if name in mapping:
        filename = mapping[name]
    else:
        candidates = [filename for filename in hashes
                      if isinstance(filename, str) and Path(filename).stem == name
                      and Path(filename).suffix.lower() in FORMATS]
        if not candidates:
            raise ValueError(f"Manifest has no hashed file for logical table: {name}")
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous formats for {name}; set manifest.logical_tables explicitly")
        filename = candidates[0]
    if not isinstance(filename, str) or filename not in hashes:
        raise ValueError(f"Logical table {name} must reference a file covered by sha256")
    path = local_table_path(directory, filename)
    digest = hashes[filename]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        raise ValueError(f"Invalid SHA-256 digest for table: {filename}")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != digest.lower():
        raise ValueError(f"Dataset hash mismatch: {filename}")
    return path


def read_table(path: Path, date_index: bool = False) -> pd.DataFrame:
    """Read CSV/Parquet with the same date and identifier representation."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(path, dtype={"order_book_id": "string", "industry_id": "string"})
    elif suffix == ".parquet":
        try:
            frame = pd.read_parquet(path, engine="pyarrow")
        except ImportError:
            raise RuntimeError("Parquet support requires pyarrow; install the project's locked dependencies") from None
    else:
        raise ValueError("Supported table formats are .csv and .parquet")
    if "date" in frame.index.names:
        if isinstance(frame.index, pd.MultiIndex) or "date" in frame.columns:
            raise ValueError("Ambiguous table date index; export a single date column")
        frame = frame.reset_index()
    if "date" not in frame:
        raise ValueError(f"Table requires a date column or date index: {path.name}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    dates = pd.DatetimeIndex(frame["date"])
    if dates.hasnans or dates.tz is not None or (dates != dates.normalize()).any():
        raise ValueError("Expected nonmissing timezone-naive daily session dates")
    for identifier in ["order_book_id", "industry_id"]:
        if identifier in frame:
            frame[identifier] = frame[identifier].astype("string")
            if frame[identifier].isna().any():
                raise ValueError(f"Missing identifier in column: {identifier}")
    if date_index:
        frame = frame.set_index("date")
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError("Index tables require unique, increasing session dates")
    return frame
