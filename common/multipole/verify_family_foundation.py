"""Fail-closed gate for the frozen RF multipole family foundation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.multipole.family_contract import from_high_order_baseline, from_quadrupole_contract
from common.multipole.axial_acceleration import resolve_axial_acceleration
from common.multipole.resolve_finite_3d_contract import resolve_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SPECS = {
    "rf_quadrupole_collision_cooling": (2, 4),
    "rf_hexapole_ion_guide": (3, 6),
    "rf_octupole_ion_guide": (4, 8),
}
FOUNDATION_SCOPE = {
    "solver_neutral_round_rod_array",
    "alternating_two_group_rf_dc_drive",
    "finite_3d_axial_interfaces",
    "zero_or_positive_grounded_connectors",
    "canonical_particle_state",
    "comsol_and_simion_functional_transport_adapters",
    "segmented_rod_axial_acceleration_comsol_adapter",
}


def load_json(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON contract."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, message: str) -> None:
    """Raise a stable gate error when one family invariant fails."""
    if not condition:
        raise ValueError(message)


def validate_family_identity() -> dict[str, Any]:
    """Validate the frozen family identity, consumers, and capability boundary."""
    family = load_json(REPO_ROOT / "common" / "multipole" / "family_contract.json")
    foundation = family.get("foundation", {})
    require(family.get("schema_version") == 2, "family contract schema_version must be 2")
    require(family.get("role") == "rf_multipole_family_contract", "family contract role differs")
    require(family.get("supported_radial_orders") == [2, 3, 4], "supported radial orders differ")
    require(foundation.get("status") == "frozen_functional_baseline", "foundation is not frozen")
    require(set(foundation.get("consumers", [])) == set(PROJECT_SPECS), "family consumers differ")
    require(set(foundation.get("scope", [])) == FOUNDATION_SCOPE, "frozen foundation scope differs")
    require(bool(foundation.get("change_control", "").strip()), "family change control is empty")
    return family


def validate_project_identity(project_id: str, order: int, electrode_count: int) -> None:
    """Validate one project's registry metadata and normalized operating identity."""
    root = REPO_ROOT / "projects" / project_id
    project = load_json(root / "config" / "project.json")
    baseline = load_json(root / "config" / "baseline.json")
    require(project.get("project_id") == project_id, f"{project_id} project identity differs")
    require(project.get("family_id") == "rf_multipole_ion_optics", f"{project_id} family differs")
    require("simion" in project.get("toolchains", []), f"{project_id} omits its SIMION adapter")
    require(
        baseline.get("multipole", {}).get("radial_order_n") == order
        and baseline.get("multipole", {}).get("electrode_count") == electrode_count,
        f"{project_id} baseline multipole identity differs",
    )
    axial = load_json(root / "config" / "modes" / "axial_acceleration_reference.json")
    require(axial.get("project_id") == project_id, f"{project_id} axial-acceleration identity differs")
    if order == 2:
        resolved_geometry = load_json(root / "config" / "resolved_geometry.json")
        first_rod = resolved_geometry["rod_array_mm"]["rods"][0]
        source_energy = 2.0
        charge_state = 1
    else:
        first_rod = {
            "z_min_mm": 0.0,
            "z_max_mm": baseline["geometry_mm"]["effective_length"],
        }
        source_energy = baseline["particle_source"]["kinetic_energy_eV"]
        charge_state = baseline["particle_source"]["charge_state"]
    acceleration = resolve_axial_acceleration(
        axial,
        rod_z_min_mm=first_rod["z_min_mm"],
        rod_z_max_mm=first_rod["z_max_mm"],
        source_kinetic_energy_ev=source_energy,
        charge_state=charge_state,
    )
    require(acceleration["derived"]["predicted_output_energy_eV"] == 5.0, f"{project_id} energy target differs")
    if order == 2:
        modes = root / "config" / "modes"
        for mode_name in ("transport_no_collision.json", "mass_filter_reference.json"):
            operating = from_quadrupole_contract(baseline, load_json(modes / mode_name))
            require(operating.identity.radial_order_n == order, "quadrupole operating order differs")
        builder = (root / "comsol" / "ms_rf_quadrupole_no_collision.m").read_text(encoding="utf-8")
        require("create_multipole_segmented_round_rods" in builder, "quadrupole COMSOL bypasses segmented rods")
        require("family_operating_contract" in builder, "quadrupole COMSOL bypasses the shared drive")
    else:
        operating = from_high_order_baseline(baseline)
        require(operating.identity.electrode_count == electrode_count, f"{project_id} drive identity differs")
        finite_3d = load_json(root / "config" / "finite_3d_transport.json")
        resolved = resolve_contract(baseline, finite_3d)
        require(resolved["multipole"] == finite_3d["multipole"], f"{project_id} L3 identity differs")
        wrapper = (root / "analysis" / "run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        require("common\\multipole\\run_finite_3d_transport.ps1" in wrapper, f"{project_id} L3 runner is duplicated")
        finite_capability = next(
            capability for capability in project["capabilities"] if capability["capability_id"].endswith("finite_3d_transport")
        )
        variables = set(finite_capability.get("design_variables", []))
        require(
            {"entrance_connector_length", "exit_connector_length"} <= variables,
            f"{project_id} does not expose the shared connector variables",
        )


def validate_shared_implementations() -> None:
    """Ensure production adapters retain complete drive and connector semantics."""
    multipole = REPO_ROOT / "common" / "multipole"
    solver = (multipole / "solve_finite_3d_transport.m").read_text(encoding="utf-8")
    for token in ("V_rf", "V_dc", "V_axis", "phi_rf", "rf.waveform", "connIn", "connOut"):
        require(token in solver, f"shared COMSOL solver omits {token}")
    for token in ("MULTIPOLE_L3_AXIAL_ACCELERATION", "create_multipole_segmented_round_rods", "zero_axial_drop_rf_on"):
        require(token in solver, f"shared COMSOL acceleration adapter omits {token}")
    simion = (multipole / "simion_transport.lua").read_text(encoding="utf-8")
    for token in ("transport_rf_peak_v", "transport_dc_amplitude_v", "transport_axis_voltage_v"):
        require(token in simion, f"shared SIMION runtime omits {token}")


def validate_family_foundation() -> None:
    """Validate all frozen family consumers and production implementation boundaries."""
    validate_family_identity()
    for project_id, identity in PROJECT_SPECS.items():
        validate_project_identity(project_id, *identity)
    validate_shared_implementations()


def main() -> int:
    """Run the family foundation gate."""
    validate_family_foundation()
    print("MULTIPOLE_FAMILY_FOUNDATION=PASS PROJECTS=3 ORDERS=2,3,4 STATUS=frozen_functional_baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
