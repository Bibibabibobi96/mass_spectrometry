"""Load a verified fixed-grid native mirror result for the Stripe seed."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_operating_seed import FixedHardwareMirrorPoint
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import derive_mirror_boundaries
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design, derive_mirror_l0_slope_tolerance_per_v
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError, derive_mirror_voltage_bounds, derive_operating_energy_envelope, load_contract

_PROJECT = "parallel_mirror_dual_stripe_mr_tof"
_MODE = "mirror_turn_fixed_operating_grid_validation"
_AMU_KG = 1.66053906660e-27
_E_C = 1.602176634e-19

def _obj(path: Path, label: str) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc: raise CandidateContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict): raise CandidateContractError(f"{label} must be an object")
    return value

def _record(records: object, name: str) -> dict[str, Any]:
    values = records.values() if isinstance(records, dict) else records if isinstance(records, list) else []
    found = [r for r in values if isinstance(r, dict) and Path(str(r.get("path", ""))).name == name]
    if len(found) != 1: raise CandidateContractError(f"fixed-grid manifest must bind exactly one {name}")
    return found[0]

def _remove_path(value: dict[str, Any], *path: str) -> None:
    parent: Any = value
    for key in path[:-1]:
        if not isinstance(parent, dict):
            return
        parent = parent.get(key)
    if isinstance(parent, dict):
        parent.pop(path[-1], None)


def _same_mirror_physics(
    fixed_contract_path: Path, downstream_contract_path: Path,
) -> bool:
    """Compare only contract fields that can invalidate frozen mirror evidence.

    Accelerator geometry/source acceptance and run-time source distributions are
    downstream consumers of the mirror result.  They must not invalidate a
    measured fixed-mirror voltage point when mirror physics is unchanged.
    """
    fixed = deepcopy(_obj(fixed_contract_path, "fixed-grid frozen contract"))
    downstream = deepcopy(_obj(downstream_contract_path, "downstream contract"))
    try:
        fixed_partition = fixed["prism_transport"]["energy_partition"]
        downstream_partition = downstream["prism_transport"]["energy_partition"]
        fixed_policy = fixed_partition.pop("candidate_operating_partition")
        downstream_policy = downstream_partition.pop("candidate_operating_partition")
    except (KeyError, TypeError) as exc:
        raise CandidateContractError("slow-energy policy fields are incomplete") from exc

    for contract in (fixed, downstream):
        contract.pop("accelerator", None)
        contract.pop("particle_source", None)
        contract.pop("downstream_fixed_grid_workpoint_profile", None)
        _remove_path(contract, "prism_transport", "first_prism", "entry_reference")
        _remove_path(contract, "simion", "accelerator_pa_span_mm")
        _remove_path(contract, "simion", "analyzer_spatial_convergence")
        _remove_path(contract, "simion", "native_corridor")
        _remove_path(
            contract,
            "simion",
            "numerical_profiles",
            "geometry_review_isotropic",
            "purpose",
        )
    return (
        fixed_policy
        == "fixed nominal input for analytic initialization; measured or simulated source spread is added later without replacing this centre"
        and downstream_policy
        == "5 eV is the nominal adjustable slow-axis source seed, not a fixed equality. For a qualified fixed mirror, the native Stripe spatial-return inverse and T_D/T_0=K analytically select the nearby slow-energy centre and both Stripe biases; measured or simulated source spread is added around that selected centre."
        and fixed == downstream
    )

def load_fixed_grid_mirror_point(manifest_path: Path, downstream_contract: Path) -> FixedHardwareMirrorPoint:
    """Fail closed unless the native r130-style fixed-grid evidence is complete."""
    manifest_path = manifest_path.resolve(); manifest = _obj(manifest_path, "fixed-grid manifest")
    if manifest.get("schema_version") != 2 or manifest.get("project") != _PROJECT or manifest.get("mode") != _MODE or manifest.get("status") != "success":
        raise CandidateContractError("fixed-grid manifest has wrong schema, project, mode, or status")
    try:
        verify_record("run_config", manifest["run_config"], base_dir=manifest_path.parent)
        for name, value in manifest.get("inputs", {}).items(): verify_record(name, value, base_dir=manifest_path.parent)
        for value in manifest.get("outputs", []): verify_record("output", value, base_dir=manifest_path.parent)
    except (AssertionError, KeyError, TypeError, ValueError) as exc: raise CandidateContractError("fixed-grid manifest integrity failed") from exc
    point_rec = _record(manifest["outputs"], "fixed_grid_voltage_point.json")
    period_rec = _record(manifest["outputs"], "mirror_real_field_period_comparison.json")
    native_rec = _record(manifest["outputs"], "native_transverse_l1.json")
    probe_rec = _record(manifest["outputs"], "native_transverse_l1_probe_contract.json")
    contract = load_contract(downstream_contract)
    point, period, native, probe = (_obj(record_path(r, base_dir=manifest_path.parent), label) for r, label in ((point_rec,"point"),(period_rec,"period"),(native_rec,"native L1"),(probe_rec,"native probe")))
    source_contract_sha = str(point.get("source_contract_sha256", "")).upper()
    if file_sha256(downstream_contract.resolve()) != source_contract_sha:
        fixed_contract_path = (
            record_path(manifest["run_config"], base_dir=manifest_path.parent).parent
            / "inputs" / "simion_candidate_two_zone.json"
        )
        if (
            not fixed_contract_path.is_file()
            or file_sha256(fixed_contract_path) != source_contract_sha
            or not _same_mirror_physics(
                fixed_contract_path, downstream_contract.resolve(),
            )
        ):
            raise CandidateContractError(
                "downstream contract changes more than the explicit slow-energy policy"
            )
    if point.get("role") != "mrtof_fixed_grid_mirror_voltage_point" or period.get("role") != "mrtof_bare_mirror_real_field_period_comparison" or native.get("role") != "mrtof_native_simion_transverse_l1_analysis" or probe.get("role") != "mrtof_native_simion_transverse_l1_probe":
        raise CandidateContractError("fixed-grid evidence roles differ")
    if native.get("source_native_l1_probe_contract_sha256") != str(probe_rec["sha256"]).upper(): raise CandidateContractError("native L1 does not bind its probe")
    voltages = tuple(float(v) for v in point.get("mirror_voltages_v", [])); energies = tuple(float(v) for v in period.get("energy_centers_ev", []))
    if len(voltages) != 5 or voltages[0] != 0.0 or len(energies) != 3 or tuple(sorted(energies)) != energies: raise CandidateContractError("fixed-grid voltage or energy vector is invalid")
    derived_energies = derive_operating_energy_envelope(contract, selected_center_v=energies[1]).mirror_energy_nodes_v
    if energies != derived_energies:
        raise CandidateContractError("fixed-grid energy nodes differ from the selected-center physical envelope")
    low, high = derive_mirror_voltage_bounds(contract, selected_center_v=energies[1])
    if any(v < lo or v > hi for v,lo,hi in zip(voltages[1:],low,high,strict=True)) or voltages[-1] <= max(energies): raise CandidateContractError("fixed-grid voltages violate envelope")
    budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
    tolerance = derive_mirror_l0_slope_tolerance_per_v(float(budget["minimum_mass_resolution"]), float(budget["mirror_time_width_fraction"]), energies)
    slopes = tuple(float(v) for v in period.get("simion_normalized_period_slopes_per_v", []))
    if len(slopes) != 3 or any(abs(v) > tolerance for v in slopes): raise CandidateContractError("fixed-grid period slopes fail physical gate")
    directions = native.get("directions")
    if not isinstance(directions, dict) or set(directions) != {"-1", "1"}: raise CandidateContractError("native L1 directions are incomplete")
    values = [directions[key] for key in ("-1","1")]
    if any(item.get("stable") is not True or abs(float(item.get("gamma_degrees", math.inf))-90.0) > 0.01 for item in values): raise CandidateContractError("native L1 stability or gamma physical gate fails")
    full_us = sum(float(item["full_two_mirror_period_us"]) for item in values) / 2.0
    mass = float(probe["particle_mass_th"]); energy = float(probe["nominal_energy_ev"])
    if mass <= 0.0 or energy <= 0.0 or not math.isfinite(full_us): raise CandidateContractError("native period mass or energy is invalid")
    reduced = full_us * 1e-3 / math.sqrt(2.0 * mass * _AMU_KG / _E_C)
    width = reduced * math.sqrt(energy)
    boundaries = derive_mirror_boundaries(contract["mirror"])
    design = MirrorL0Design(float(contract["mirror"]["theory_requirements"]["berdnikov_transverse_half_gap_mm"]), tuple(float(x) for x in boundaries["analytic_transition_z_mm"]), voltages, float(boundaries["terminal_electrode_plane_z_mm"]), voltages[-1])
    return FixedHardwareMirrorPoint(design=design, energy_points_v=energies, nominal_energy_per_charge_v=energy, nominal_reduced_period_mm_per_sqrt_v=reduced, nominal_axial_width_w_mm=width, contract=contract)
