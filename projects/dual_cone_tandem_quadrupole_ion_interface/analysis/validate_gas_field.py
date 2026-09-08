"""Validate a COMSOL axisymmetric gas-field export before SIMION consumption."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ID = "dual_cone_tandem_quadrupole_ion_interface"
SCIENCE_ROLE = "dual_cone_axisymmetric_gas_flow_science_contract"
NUMERICS_ROLE = "dual_cone_axisymmetric_gas_flow_comsol_numerics"
METADATA_ROLE = "dual_cone_axisymmetric_gas_field_metadata"


def _load_json(path: Path, role: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("role") != role:
        raise ValueError(f"{path} is not a supported {role} contract")
    if value.get("project_id") != PROJECT_ID:
        raise ValueError(f"{path} has the wrong project identity")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_float(row: dict[str, str], field: str, fluid: bool) -> float:
    try:
        value = float(row[field])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid numeric field {field}") from exc
    if fluid and not math.isfinite(value):
        raise ValueError(f"fluid row contains nonfinite {field}")
    return value


def validate_gas_field(
    csv_path: Path,
    metadata_path: Path,
    science_path: Path,
    numerics_path: Path,
    geometry_path: Path | None = None,
) -> dict[str, Any]:
    """Return a fail-closed validation summary for one rectilinear r-z field."""
    science = _load_json(science_path, SCIENCE_ROLE)
    numerics = _load_json(numerics_path, NUMERICS_ROLE)
    if geometry_path is None:
        geometry_path = science_path.parent / "resolved_geometry.json"
    _load_json(
        geometry_path, "dual_cone_tandem_quadrupole_resolved_geometry"
    )
    metadata = _load_json(metadata_path, METADATA_ROLE)
    model_id = science["model_id"]
    if numerics.get("model_id") != model_id or metadata.get("model_id") != model_id:
        raise ValueError("gas-flow model identities disagree")
    if metadata.get("claim_scope") != science["claim_scope"]:
        raise ValueError("gas-field claim scope disagrees with science contract")
    if metadata.get("field_csv_sha256") != _sha256(csv_path):
        raise ValueError("gas-field CSV SHA-256 does not match metadata")
    source_hashes = metadata.get("source_contract_sha256", {})
    expected_source_hashes = {
        "gas_flow_science": _sha256(science_path),
        "comsol_solver_numerics": _sha256(numerics_path),
        "resolved_geometry": _sha256(geometry_path),
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
    if any(b <= a for a, b in zip(r_values, r_values[1:], strict=False)):
        raise ValueError("radial grid must be strictly increasing")
    if any(b <= a for a, b in zip(z_values, z_values[1:], strict=False)):
        raise ValueError("axial grid must be strictly increasing")

    expected_columns = export["columns"]
    coordinate_tolerance = numerics["validation"][
        "grid_coordinate_absolute_tolerance_mm"
    ]
    gas = science["physics"]["gas_species"]
    density_factor = gas["molar_mass_kg_per_mol"] / gas[
        "universal_gas_constant_j_per_mol_k"
    ]
    density_tolerance = numerics["validation"]["ideal_gas_relative_tolerance"]
    required_fields = numerics["validation"]["required_fields"]
    fluid_count = 0
    max_knudsen = 0.0
    max_mach = 0.0
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_columns:
            raise ValueError("gas-field CSV columns or order violate the export contract")
        rows = list(reader)
    expected_count = len(r_values) * len(z_values)
    if len(rows) != expected_count or metadata.get("row_count") != expected_count:
        raise ValueError("gas-field row count does not match its rectilinear grid")

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
        if fluid_mask == 0:
            if any(math.isfinite(value) for value in values.values()):
                raise ValueError("outside-domain gas fields must be NaN")
            continue
        fluid_count += 1
        if values["p_pa"] <= 0.0 or values["temperature_k"] <= 0.0:
            raise ValueError("fluid pressure and temperature must be positive")
        if values["rho_kg_per_m3"] <= 0.0 or values["mach"] < 0.0:
            raise ValueError("fluid density and Mach number are outside their domains")
        if values["knudsen_aperture"] < 0.0:
            raise ValueError("Knudsen number cannot be negative")
        expected_density = density_factor * values["p_pa"] / values["temperature_k"]
        relative_error = abs(values["rho_kg_per_m3"] - expected_density) / expected_density
        if relative_error > density_tolerance:
            raise ValueError("gas density violates the declared ideal-gas equation")
        max_knudsen = max(max_knudsen, values["knudsen_aperture"])
        max_mach = max(max_mach, values["mach"])

    if fluid_count < numerics["validation"]["minimum_fluid_row_count"]:
        raise ValueError("gas-field export contains too few fluid samples")
    solution = metadata["solution_summary"]
    mass_error = float(solution["mass_balance_relative_error"])
    if not math.isfinite(mass_error) or mass_error < 0.0:
        raise ValueError("invalid mass-balance error")
    if mass_error > numerics["validation"]["maximum_mass_balance_relative_error"]:
        raise ValueError("COMSOL gas-flow solution fails the mass-balance contract")
    target_outlet = science["boundary_conditions"]["outlet"]["static_pressure_pa"]
    if float(solution["requested_outlet_static_pressure_pa"]) != target_outlet:
        raise ValueError("COMSOL export did not consume the requested outlet pressure")
    reject_knudsen = science["continuum_scope"][
        "reject_quantitative_use_knudsen_number"
    ]
    return {
        "schema_version": 1,
        "role": "dual_cone_axisymmetric_gas_field_validation",
        "project_id": PROJECT_ID,
        "model_id": model_id,
        "status": "PASS",
        "row_count": len(rows),
        "fluid_row_count": fluid_count,
        "maximum_mach": max_mach,
        "maximum_knudsen_aperture": max_knudsen,
        "mass_balance_relative_error": mass_error,
        "quantitative_continuum_claim_allowed": max_knudsen <= reject_knudsen,
        "claim_scope": science["claim_scope"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument(
        "--science",
        type=Path,
        default=project_root / "config" / "gas_flow_science.json",
    )
    parser.add_argument(
        "--numerics",
        type=Path,
        default=project_root / "config" / "comsol_solver_numerics.json",
    )
    parser.add_argument(
        "--geometry",
        type=Path,
        default=project_root / "config" / "resolved_geometry.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = validate_gas_field(
        args.csv, args.metadata, args.science, args.numerics, args.geometry
    )
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
