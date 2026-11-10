"""Validate a COMSOL axisymmetric gas-field export before SIMION consumption."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from msplatform.contracts.gas_field import GasFieldData, read_gas_field_data


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


def validate_gas_field_data(data: GasFieldData) -> dict[str, Any]:
    """Apply the original dual-cone research acceptance to one actual scan."""
    documents = data.documents
    science, numerics, metadata = (documents[name] for name in ("science", "numerics", "metadata"))
    for name, role in (
        ("science", SCIENCE_ROLE), ("numerics", NUMERICS_ROLE),
        ("geometry", "dual_cone_tandem_quadrupole_resolved_geometry"),
        ("metadata", METADATA_ROLE),
    ):
        value = documents[name]
        if value.get("schema_version") != 1 or value.get("role") != role:
            raise ValueError(f"{name} is not a supported {role} contract")
        if value.get("project_id") != PROJECT_ID:
            raise ValueError(f"{name} has the wrong project identity")
    model_id = science["model_id"]
    if numerics.get("model_id") != model_id or metadata.get("model_id") != model_id:
        raise ValueError("gas-flow model identities disagree")
    if metadata.get("claim_scope") != science["claim_scope"]:
        raise ValueError("gas-field claim scope disagrees with science contract")
    gas = science["physics"]["gas_species"]
    density_factor = gas["molar_mass_kg_per_mol"] / gas[
        "universal_gas_constant_j_per_mol_k"
    ]
    density_tolerance = float(numerics["validation"]["ideal_gas_relative_tolerance"])
    if (not math.isfinite(density_factor) or density_factor <= 0.0
            or not math.isfinite(density_tolerance) or density_tolerance < 0.0):
        raise ValueError("gas-field density validation inputs must be finite and physical")
    fluid_count = 0
    max_knudsen = 0.0
    max_mach = 0.0
    required_fields = numerics["validation"]["required_fields"]
    for index, fluid_mask in enumerate(data.fluid_mask):
        if fluid_mask == 0:
            continue
        values = {field: data.columns[field][index] for field in required_fields}
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
    terminal_diffusion = float(
        numerics["study"]["accepted_terminal_isotropic_diffusion"]
    )
    if float(solution["accepted_isotropic_diffusion"]) != terminal_diffusion:
        raise ValueError("COMSOL export did not record the governed terminal stabilization")
    reject_knudsen = science["continuum_scope"][
        "reject_quantitative_use_knudsen_number"
    ]
    return {
        "schema_version": 1,
        "role": "dual_cone_axisymmetric_gas_field_validation",
        "project_id": PROJECT_ID,
        "model_id": model_id,
        "status": "PASS",
        "row_count": data.row_count,
        "fluid_row_count": fluid_count,
        "maximum_mach": max_mach,
        "maximum_knudsen_aperture": max_knudsen,
        "mass_balance_relative_error": mass_error,
        "accepted_isotropic_diffusion": terminal_diffusion,
        "quantitative_continuum_claim_allowed": max_knudsen <= reject_knudsen,
        "claim_scope": science["claim_scope"],
    }


def validate_gas_field(
    csv_path: Path,
    metadata_path: Path,
    science_path: Path,
    numerics_path: Path,
    geometry_path: Path,
) -> dict[str, Any]:
    """Validate explicit producer files before publication or Lua materialization."""
    # Preserve the original role/project failures before scanning producer data.
    _load_json(science_path, SCIENCE_ROLE)
    _load_json(numerics_path, NUMERICS_ROLE)
    _load_json(geometry_path, "dual_cone_tandem_quadrupole_resolved_geometry")
    _load_json(metadata_path, METADATA_ROLE)
    return validate_gas_field_data(read_gas_field_data(
        csv_path, metadata_path, science_path, numerics_path, geometry_path
    ))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--science", type=Path, required=True)
    parser.add_argument("--numerics", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
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
