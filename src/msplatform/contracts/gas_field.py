"""Read the recorded rectilinear gas export without project acceptance policy."""

from __future__ import annotations

from array import array
from collections.abc import Mapping, Sequence
import copy
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

from msplatform.io.file_identity import file_sha256


@dataclass(frozen=True, init=False)
class GasFieldData:
    """Actual source documents and compact immutable columns read in one scan.

    This is a data snapshot, not permission to consume later modified files.
    Artifact records and native input guards retain their existing authority.
    Axes are the recorded local r/z coordinates in mm; column names retain the
    source export's Pa, K, m/s, kg/m3 and dimensionless Mach/Kn units. No world
    pose, gas-axis regularization, new EOS or scientific qualification is applied.
    """

    _documents: dict[str, Any]
    columns: Mapping[str, memoryview]
    fluid_mask: bytes
    r_values_mm: tuple[float, ...]
    z_values_mm: tuple[float, ...]

    def __init__(
        self,
        documents: Mapping[str, Any],
        columns: Mapping[str, array],
        fluid_mask: bytes | bytearray,
        r_values: Sequence[float],
        z_values: Sequence[float],
    ) -> None:
        object.__setattr__(self, "_documents", copy.deepcopy(documents))
        object.__setattr__(self, "columns", MappingProxyType({
            field: memoryview(values.tobytes()).cast("d") for field, values in columns.items()
        }))
        object.__setattr__(self, "fluid_mask", bytes(fluid_mask))
        object.__setattr__(self, "r_values_mm", tuple(r_values))
        object.__setattr__(self, "z_values_mm", tuple(z_values))

    @property
    def row_count(self) -> int:
        return len(self.fluid_mask)

    @property
    def documents(self) -> dict[str, Any]:
        return copy.deepcopy(self._documents)


def _finite_float(row: dict[str, str], field: str, fluid: bool) -> float:
    try:
        value = float(row[field])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid numeric field {field}") from exc
    if fluid and not math.isfinite(value):
        raise ValueError(f"fluid row contains nonfinite {field}")
    return value


def read_gas_field_data(
    csv_path: Path,
    metadata_path: Path,
    science_path: Path,
    numerics_path: Path,
    geometry_path: Path,
) -> GasFieldData:
    """Read original format, provenance, finite values and mask/order semantics."""
    documents = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in (
            ("science", science_path), ("numerics", numerics_path),
            ("geometry", geometry_path), ("metadata", metadata_path),
        )
    }
    science, numerics, metadata = (documents[name] for name in ("science", "numerics", "metadata"))
    if metadata.get("field_csv_sha256") != file_sha256(csv_path).lower():
        raise ValueError("gas-field CSV SHA-256 does not match metadata")
    source_hashes = metadata.get("source_contract_sha256", {})
    expected_source_hashes = {
        "gas_flow_science": file_sha256(science_path).lower(),
        "comsol_solver_numerics": file_sha256(numerics_path).lower(),
        "resolved_geometry": file_sha256(geometry_path).lower(),
    }
    for source_name, expected_hash in expected_source_hashes.items():
        if source_hashes.get(source_name) != expected_hash:
            raise ValueError(f"gas-field source hash mismatch for {source_name}")

    export = science["export_contract"]
    if metadata.get("field_schema_id") != export["schema_id"]:
        raise ValueError("gas-field schema identity mismatch")
    if metadata.get("coordinate_order") != export["coordinate_order"]:
        raise ValueError("gas-field coordinate order mismatch")
    grid = metadata["grid"]
    r_values = [float(value) for value in grid["r_values_mm"]]
    z_values = [float(value) for value in grid["z_values_mm"]]
    if not r_values or not z_values:
        raise ValueError("gas-field grid axes must be nonempty")
    if any(not math.isfinite(value) for value in [*r_values, *z_values]):
        raise ValueError("gas-field grid axes must be finite")
    if any(b <= a for a, b in zip(r_values, r_values[1:], strict=False)):
        raise ValueError("radial grid must be strictly increasing")
    if any(b <= a for a, b in zip(z_values, z_values[1:], strict=False)):
        raise ValueError("axial grid must be strictly increasing")

    expected_columns = export["columns"]
    coordinate_tolerance = float(numerics["validation"][
        "grid_coordinate_absolute_tolerance_mm"
    ])
    if not math.isfinite(coordinate_tolerance) or coordinate_tolerance < 0.0:
        raise ValueError("gas-field coordinate tolerance must be finite and nonnegative")
    required_fields = numerics["validation"]["required_fields"]
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_columns:
            raise ValueError("gas-field CSV columns or order violate the export contract")
        rows = list(reader)
    expected_count = len(r_values) * len(z_values)
    if len(rows) != expected_count or metadata.get("row_count") != expected_count:
        raise ValueError("gas-field row count does not match its rectilinear grid")

    columns = {field: array("d") for field in required_fields}
    masks = bytearray()
    for linear_index, row in enumerate(rows):
        expected_z_index, expected_r_index = divmod(linear_index, len(r_values))
        try:
            z_index = int(row["z_index"])
            r_index = int(row["r_index"])
            fluid_mask = int(row["fluid_mask"])
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid gas-field index or mask") from exc
        if (z_index, r_index) != (expected_z_index, expected_r_index):
            raise ValueError("gas-field rows are not ordered z-major then r-minor")
        if fluid_mask not in (0, 1):
            raise ValueError("fluid_mask must be 0 or 1")
        z_mm = _finite_float(row, "z_mm", True)
        r_mm = _finite_float(row, "r_mm", True)
        if abs(z_mm - z_values[z_index]) > coordinate_tolerance:
            raise ValueError("gas-field z coordinate disagrees with metadata")
        if abs(r_mm - r_values[r_index]) > coordinate_tolerance:
            raise ValueError("gas-field r coordinate disagrees with metadata")
        values = {field: _finite_float(row, field, fluid_mask == 1) for field in required_fields}
        masks.append(fluid_mask)
        for field, value in values.items():
            columns[field].append(value)
        if fluid_mask == 0:
            if any(not math.isnan(value) for value in values.values()):
                raise ValueError("outside-domain gas fields must be NaN")
            continue
    return GasFieldData(documents, columns, masks, r_values, z_values)
