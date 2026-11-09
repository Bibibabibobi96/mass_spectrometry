"""Stream caller-owned scientific CSV tables; no event or particle schema."""
from __future__ import annotations
import csv
import hashlib
from pathlib import Path
from collections.abc import Iterator, Mapping, Sequence


def iter_csv_rows(path: Path, required_columns: Sequence[str], *, exact_header: Sequence[str] | None = None, identity_result: dict | None = None, expected_record: Mapping | None = None) -> Iterator[Mapping[str, str]]:
    """Validate one header and yield rows; callers own types, units and physics."""
    digest = hashlib.sha256() if identity_result is not None or expected_record is not None else None
    byte_count = 0
    with Path(path).open("rb") as stream:
        def lines():
            nonlocal byte_count
            for index, raw in enumerate(stream):
                if digest is not None:
                    digest.update(raw)
                    byte_count += len(raw)
                yield raw.decode("utf-8-sig" if index == 0 else "utf-8")
        reader = csv.DictReader(lines(), strict=True)
        try:
            header = reader.fieldnames or []
        except csv.Error as error:
            raise ValueError(f"malformed scientific CSV header in {path.name}: {error}") from error
        if len(header) != len(set(header)) or not set(required_columns) <= set(header):
            raise ValueError(f"missing or duplicate scientific CSV columns in {path.name}")
        if exact_header is not None and header != list(exact_header):
            raise ValueError(f"scientific CSV header differs in {path.name}")
        def rows():
            try:
                yield from reader
            except csv.Error as error:
                raise ValueError(f"malformed scientific CSV at line {reader.line_num} in {path.name}: {error}") from error
        for row in rows():
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"malformed scientific CSV row in {path.name}")
            yield row
    if expected_record is not None:
        if (Path(expected_record["path"]).resolve()!=Path(path).resolve() or expected_record["bytes"]!=byte_count
                or str(expected_record["sha256"]).lower()!=digest.hexdigest()):
            raise ValueError(f"scientific CSV differs from bound file record: {path}")
    if identity_result is not None:
        identity_result.update(path=str(Path(path).resolve()), bytes=byte_count, sha256=digest.hexdigest())
