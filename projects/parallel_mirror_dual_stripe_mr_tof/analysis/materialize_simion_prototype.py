#!/usr/bin/env python3
"""Materialize a run-local, traceable SIMION prototype from frozen inputs.

This adapter deliberately does not modify the baseline Candidate contract.
It accepts only the analytic L0/L1 receipt as a *3-D-unvalidated* voltage
source and writes both the derived contract and the Lua Fast-Adjust sidecar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.simion.particle_source import render_standard_beams

from common.contracts.file_identity import file_sha256, repository_text_sha256
from projects.orthogonal_accelerator.analysis.component_contract import load_accelerator_dependency

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_stage_2_ring_voltages,
    derive_two_zone_placement,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_l0 import derive_first_prism_l0
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import derive_mirror_boundaries


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze_accelerator_dependency(output_directory: Path) -> dict[str, Any]:
    """Freeze the explicitly declared accelerator API and its source identity."""
    project = Path(__file__).resolve().parents[1]
    repo = project.parents[1]
    declaration = project / "config/accelerator_dependency.json"
    try:
        verified = load_accelerator_dependency(
            repo, declaration, consumer_project_id=project.name, required_variant="two_zone",
        )
    except ValueError as error:
        raise CandidateContractError(f"invalid accelerator dependency: {error}") from error
    sources = [verified["dependency_path"], verified["provider_contract_path"],
               *verified["implementation_sources"]]
    records = []
    for source in sources:
        destination = output_directory / "inputs" / source.relative_to(repo)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        digest = file_sha256(source)
        if file_sha256(destination) != digest:
            raise CandidateContractError("accelerator frozen source differs from provider bytes")
        records.append({"source": source.relative_to(repo).as_posix(),
                        "frozen": destination.relative_to(output_directory).as_posix(),
                        "sha256": digest, "repository_text_sha256": repository_text_sha256(source)})
    return {"provider_project_id": verified["dependency"]["provider_project_id"],
            "api_version": verified["api_version"], "files": records}


def _candidate_voltages(receipt_path: Path) -> list[float]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") == "l0_l1_voltage_candidate_not_3d_validated":
        mapping = receipt.get("mapping")
        voltages = receipt.get("electrode_voltages_v")
    elif receipt.get("status") == "l1_family_continued_to_gamma_target__peak_field_and_3d_validation_pending":
        continuation = receipt.get("gamma_target_continuation")
        convergence = receipt.get("gamma_target_probe_convergence")
        if not isinstance(continuation, dict) or not isinstance(convergence, dict):
            raise CandidateContractError("mirror family receipt omits gamma continuation or probe convergence")
        if continuation.get("status") != "gamma_target_selected_with_probe_convergence__peak_field_and_3d_validation_pending":
            raise CandidateContractError("mirror family receipt has not closed the gamma-selection stage")
        if convergence.get("status") != "pass":
            raise CandidateContractError("mirror family receipt has not passed finite-difference probe convergence")
        l0 = continuation.get("l0_receipt")
        screen = continuation.get("l1_screen")
        if not isinstance(l0, dict) or not isinstance(screen, dict):
            raise CandidateContractError("mirror family receipt omits its selected L0/L1 records")
        mapping = screen.get("nominal_mapping")
        voltages = l0.get("electrode_voltages_v")
        gamma_residual = continuation.get("gamma_residual_degrees")
        gamma_tolerance = continuation.get("maximum_gamma_residual_degrees")
        if (
            not isinstance(gamma_residual, (int, float))
            or not isinstance(gamma_tolerance, (int, float))
            or not math.isfinite(float(gamma_residual))
            or not math.isfinite(float(gamma_tolerance))
            or abs(float(gamma_residual)) > float(gamma_tolerance)
        ):
            raise CandidateContractError("mirror family receipt violates its gamma-target residual gate")
    else:
        raise CandidateContractError("mirror receipt is not an analytic L0/L1 Candidate")
    if not isinstance(mapping, dict) or mapping.get("stable") is not True or mapping.get("gamma_degrees") is None:
        raise CandidateContractError("mirror receipt has not passed the analytic L1 stability/gamma screen")
    if not isinstance(voltages, list) or len(voltages) != 5 or any(not isinstance(value, (int, float)) for value in voltages):
        raise CandidateContractError("mirror receipt must provide five finite electrode voltages")
    result = [float(value) for value in voltages]
    if result[0] != 0.0:
        raise CandidateContractError("prototype mirror A voltage must remain grounded")
    return result


def _finite_number(value: object, label: str) -> float:
    """Return one finite contract scalar or fail before a solver run."""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _particle_fly2(
    particle_source: dict[str, Any], particle_count_key: str, radius_mm: float,
    *, position_override_mm: list[float] | None = None,
    direction_override_project: list[float] | None = None,
    kinetic_energy_override_ev: float | None = None,
) -> str:
    """Render one immutable ideal-source Fly2 from the Candidate contract."""
    species = particle_source.get("species")
    position = particle_source.get("injection_position_mm")
    direction = particle_source.get("injection_direction_project")
    if not isinstance(species, dict) or not isinstance(position, list) or not isinstance(direction, list):
        raise CandidateContractError("particle source requires species, position, and direction")
    if len(position) != 3 or len(direction) != 3:
        raise CandidateContractError("particle source position and direction must each have three coordinates")
    mass_th = _finite_number(species.get("mass_th"), "particle_source.species.mass_th")
    charge_e = _finite_number(species.get("charge_e"), "particle_source.species.charge_e")
    energy_ev = _finite_number(species.get("kinetic_energy_ev"), "particle_source.species.kinetic_energy_ev")
    if position_override_mm is not None:
        position = position_override_mm
    if direction_override_project is not None:
        direction = direction_override_project
    if kinetic_energy_override_ev is not None:
        energy_ev = _finite_number(kinetic_energy_override_ev, "kinetic_energy_override_ev")
    coordinates = [_finite_number(value, "particle_source coordinate") for value in position]
    vector = [_finite_number(value, "particle_source direction") for value in direction]
    count = particle_source.get(particle_count_key)
    if not isinstance(count, int) or count <= 0 or mass_th <= 0.0 or charge_e == 0.0 or energy_ev < 0.0 or radius_mm < 0.0:
        raise CandidateContractError("particle source has an invalid count, species, energy, or radius")
    return (
        "particles {\n"
        "  coordinates = 0,\n"
        "  standard_beam {\n"
        f"    n = {count},\n"
        "    tob = 0,\n"
        f"    mass = {mass_th:.17g},\n"
        f"    charge = {charge_e:.17g},\n"
        f"    ke = {energy_ev:.17g},\n"
        "    cwf = 1,\n"
        "    color = 0,\n"
        f"    direction = vector({vector[0]:.17g}, {vector[1]:.17g}, {vector[2]:.17g}),\n"
        "    position = circle_distribution {\n"
        f"      center = vector({coordinates[0]:.17g}, {coordinates[1]:.17g}, {coordinates[2]:.17g}),\n"
        f"      normal = vector({vector[0]:.17g}, {vector[1]:.17g}, {vector[2]:.17g}),\n"
        f"      radius = {radius_mm:.17g},\n"
        "      fill = true\n"
        "    }\n"
        "  }\n"
        "}\n"
    )


def accelerator_focus_fly2(
    contract: dict[str, Any],
    particle_source: dict[str, Any],
    particle_count_key: str,
    axial_full_width_mm: float,
) -> str:
    """Render a zero-KE release inside zone 1 for the separate focus diagnostic.

    This is deliberately distinct from the 4-keV post-accelerator MR injection
    source.  The analytical two-zone model defines the release plane by its
    distance from the repeller and its potential energy supplies the nominal
    extraction energy at the zero-volt exit grid.
    """
    accelerator = contract.get("accelerator")
    if not isinstance(accelerator, dict):
        raise CandidateContractError("accelerator-focus Fly2 requires an accelerator contract")
    placement = derive_two_zone_placement(contract)
    release = _finite_number(
        accelerator.get("release_position_in_gap_1_mm"),
        "accelerator.release_position_in_gap_1_mm",
    )
    if not 0.0 < release < placement.repeller_z_mm - placement.grid_1_z_mm:
        raise CandidateContractError("accelerator release must remain strictly between repeller and grid1")
    count = particle_source.get(particle_count_key)
    species = particle_source.get("species")
    width = _finite_number(axial_full_width_mm, "accelerator focus axial full width")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise CandidateContractError("accelerator focus particle count must be a positive integer")
    if not isinstance(species, dict):
        raise CandidateContractError("accelerator focus source requires a species contract")
    mass = _finite_number(species.get("mass_th"), "particle_source.species.mass_th")
    charge = _finite_number(species.get("charge_e"), "particle_source.species.charge_e")
    if mass <= 0.0 or charge == 0.0 or width < 0.0:
        raise CandidateContractError("accelerator focus species and axial width are invalid")
    if count == 1:
        offsets = [0.0]
    else:
        if width <= 0.0:
            raise CandidateContractError("multi-particle accelerator focus source needs positive axial width")
        offsets = [-width / 2.0 + width * index / (count - 1) for index in range(count)]
    if release - width / 2.0 <= 0.0 or release + width / 2.0 >= placement.repeller_z_mm - placement.grid_1_z_mm:
        raise CandidateContractError("accelerator focus axial interval must stay strictly inside gap 1")
    beams = [
        {
            "tob": 0,
            "mass": f"{mass:.17g}",
            "charge": f"{charge:.17g}",
            "x": "0",
            "y": f"{placement.focus_y_mm:.17g}",
            "z": f"{placement.repeller_z_mm - release - offset:.17g}",
            "ke": "0",
            "az": "0",
            "el": "-90",
            "cwf": "1",
            "color": "0",
        }
        for offset in offsets
    ]
    return render_standard_beams(beams)


def _first_prism_entry_fly2(prism_l0: Any, particle_source: dict[str, Any]) -> str:
    """Render the one-particle, post-accelerator first-prism L0 diagnostic.

    This source is deliberately not the full MR-TOF injection source.  It
    begins at the frozen two-zone focus and exercises only the static first
    prism reference pass, before finite-3-D shooting supplies the actual
    source-to-analyser handoff and the second-prism return setting.
    """
    return _particle_fly2(
        particle_source,
        "center_particle_count",
        0.0,
        position_override_mm=list(prism_l0.entry_position_project_mm),
        direction_override_project=list(prism_l0.entry_unit_direction_project),
        kinetic_energy_override_ev=prism_l0.total_kinetic_energy_ev,
    )


def _particle_source_record(path: Path, particle_source: dict[str, Any], count_key: str) -> dict[str, Any]:
    """Bind the sole standard-beam source to SIMION's one-based ion identities."""
    count = particle_source[count_key]
    if type(count) is not int or count <= 0:
        raise CandidateContractError("particle source count must be a positive integer")
    particle_ids = list(range(1, count + 1))
    identity = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    return {"filename": path.name, "sha256": _sha256(path),
            "particle_count_contract_key": count_key, "particle_count": count,
            "expected_particle_ids": particle_ids,
            "expected_particle_ids_sha256": hashlib.sha256(identity).hexdigest()}


def _full_path_timeout_us(contract: dict[str, Any], particle_source: dict[str, Any], target_k: int) -> float:
    """Derive a finite diagnostic bound from frozen axial geometry and species."""
    simion = contract["simion"]
    multiplier = _finite_number(
        simion.get("full_path_timeout_axial_path_multiplier"),
        "simion.full_path_timeout_axial_path_multiplier",
    )
    if multiplier <= 1.0:
        raise CandidateContractError("full-path timeout factor must retain more than one axial reference path")
    species = particle_source["species"]
    mass_th = _finite_number(species.get("mass_th"), "particle_source.species.mass_th")
    charge_e = abs(_finite_number(species.get("charge_e"), "particle_source.species.charge_e"))
    energy_ev = _finite_number(species.get("kinetic_energy_ev"), "particle_source.species.kinetic_energy_ev")
    if mass_th <= 0.0 or charge_e <= 0.0 or energy_ev <= 0.0:
        raise CandidateContractError("full-path timeout requires positive species mass, charge, and energy")
    terminal = float(derive_mirror_boundaries(contract["mirror"])["terminal_electrode_plane_z_mm"])
    speed_mm_us = math.sqrt(2.0 * energy_ev * 1.602176634e-19 / (mass_th * 1.66053906660e-27)) * 1e-3
    return multiplier * target_k * (4.0 * terminal) / speed_mm_us


def materialize(contract_path: Path, mirror_receipt_path: Path, output_directory: Path) -> dict[str, Path]:
    """Write a run-local derived contract and sidecar without changing baseline."""
    contract = load_contract(contract_path)
    voltages = _candidate_voltages(mirror_receipt_path)
    stripe = contract.get("dual_stripe")
    accelerator = contract.get("accelerator")
    simion = contract.get("simion")
    if not isinstance(stripe, dict) or not isinstance(accelerator, dict) or not isinstance(simion, dict):
        raise CandidateContractError("prototype requires Stripe, accelerator, and SIMION contracts")
    review_point = stripe.get("geometry_review_visualization")
    if not isinstance(review_point, dict) or review_point.get("status") != "geometry_review_only__not_a_solver_seed":
        raise CandidateContractError("geometry materialization requires an explicitly nonphysical visualization point")
    raw_review_biases = review_point.get("stripe_biases_v")
    if not isinstance(raw_review_biases, list) or len(raw_review_biases) != 2:
        raise CandidateContractError("geometry-review visualization point needs two Stripe biases")
    stripe_biases = [
        _finite_number(value, "geometry-review Stripe bias") for value in raw_review_biases
    ]
    accelerator_voltages = [
        _finite_number(accelerator.get("repeller_v"), "accelerator.repeller_v"),
        _finite_number(accelerator.get("intermediate_grid_v"), "accelerator.intermediate_grid_v"),
        _finite_number(accelerator.get("exit_grid_v"), "accelerator.exit_grid_v"),
    ]
    accelerator_ring_voltages = list(derive_stage_2_ring_voltages(contract))
    trajectory_quality = _finite_number(simion.get("trajectory_quality"), "simion.trajectory_quality")
    maximum_step_us = _finite_number(simion.get("maximum_step_us"), "simion.maximum_step_us")
    nonaccelerator_scale = _finite_number(simion.get("nonaccelerator_scale"), "simion.nonaccelerator_scale")
    if trajectory_quality <= 0.0 or maximum_step_us <= 0.0 or nonaccelerator_scale <= 0.0:
        raise CandidateContractError("SIMION runtime settings must be positive")
    nominal = contract.get("nominal")
    if not isinstance(nominal, dict) or not isinstance(nominal.get("target_oscillation_count"), int):
        raise CandidateContractError("prototype requires an integer nominal.target_oscillation_count")
    target_oscillation_count = int(nominal["target_oscillation_count"])
    if target_oscillation_count <= 0:
        raise CandidateContractError("nominal.target_oscillation_count must be positive")
    particle_source = contract.get("particle_source")
    if not isinstance(particle_source, dict):
        raise CandidateContractError("prototype requires a particle-source contract")
    prism_l0 = derive_first_prism_l0(contract)
    full_path_timeout_us = _full_path_timeout_us(contract, particle_source, target_oscillation_count)
    prism_receipt = prism_l0.receipt()
    bunch_radius = _finite_number(particle_source.get("candidate_bunch_radius_mm"), "particle_source.candidate_bunch_radius_mm")
    center_fly2 = _particle_fly2(particle_source, "center_particle_count", 0.0)
    bunch_fly2 = _particle_fly2(particle_source, "candidate_bunch_particle_count", bunch_radius)
    accelerator_focus_width = _finite_number(
        particle_source.get("accelerator_focus_axial_full_width_mm"),
        "particle_source.accelerator_focus_axial_full_width_mm",
    )
    accelerator_focus_center_fly2 = accelerator_focus_fly2(
        contract, particle_source, "center_particle_count", 0.0,
    )
    accelerator_focus_bunch_fly2 = accelerator_focus_fly2(
        contract,
        particle_source,
        "candidate_bunch_particle_count",
        accelerator_focus_width,
    )
    first_prism_entry_center_fly2 = _first_prism_entry_fly2(prism_l0, particle_source)
    detector = resolve_geometry(contract)["detector"]
    detector_box = detector["box"]
    if detector.get("normal_project") != "+z":
        raise CandidateContractError("prototype requires the resolved +z-facing detector")
    output_directory.mkdir(parents=True, exist_ok=True)
    accelerator_dependency = _freeze_accelerator_dependency(output_directory)
    derived = json.loads(json.dumps(contract))
    mirror = derived["mirror"]
    mirror["design_status"] = "analytic_l0_l1_candidate__3d_unvalidated__pa_build_allowed"
    mirror["prototype_voltage_source"] = {
        "receipt_filename": mirror_receipt_path.name,
        "receipt_sha256": _sha256(mirror_receipt_path),
        "status": "analytic_l0_l1_candidate__3d_unvalidated",
    }
    contract_output = output_directory / "simion_prototype_contract.json"
    contract_output.write_text(json.dumps(derived, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prism_receipt_output = output_directory / "first_prism_l0_receipt.json"
    prism_receipt_output.write_text(json.dumps(prism_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sidecar_output = output_directory / "mrtof_candidate.operating_point.lua"
    sidecar_output.write_text(
        "-- Generated run-local prototype operating point; do not edit.\n"
        f"-- source_receipt_sha256={_sha256(mirror_receipt_path)}\n"
        f"-- first_prism_l0_receipt_sha256={_sha256(prism_receipt_output)}\n"
        "return { qualification = 'geometry_review_only__unsolved_stripe_and_p2', mirror_voltages_v = { " + ", ".join(f"{value:.17g}" for value in voltages)
        + " }, stripe_biases_v = { " + ", ".join(f"{value:.17g}" for value in stripe_biases)
        + " }, prism_voltages_v = { " + ", ".join(f"{value:.17g}" for value in (
            prism_l0.hard_boundary_seed_voltage_v, float(contract["prism_transport"]["second_prism"]["voltage_v"])
        ))
        + " }, accelerator_voltages_v = { " + ", ".join(f"{value:.17g}" for value in accelerator_voltages)
        + " }, accelerator_ring_voltages_v = { " + ", ".join(f"{value:.17g}" for value in accelerator_ring_voltages)
        + " }, first_prism_l0 = { target_plane_z_mm = " + f"{prism_l0.target_plane_z_mm:.17g}"
        + ", target_plane_x_mm = " + f"{prism_l0.target_plane_x_mm:.17g}"
        + ", target_plane_y_acceptance_mm = { " + ", ".join(
            f"{value:.17g}" for value in prism_l0.target_plane_y_acceptance_mm
        ) + " }"
        + " }, detector_box_mm = { " + ", ".join(f"{float(value):.17g}" for value in detector_box)
        + f" }}, detector_normal_project = '+z', trajectory_quality = {trajectory_quality:.17g}, maximum_step_us = {maximum_step_us:.17g}, full_path_timeout_us = {full_path_timeout_us:.17g}, nonaccelerator_scale = {nonaccelerator_scale:.17g}, target_oscillation_count = {target_oscillation_count} }}\n",
        encoding="utf-8",
        newline="\n",
    )
    program_template = Path(__file__).resolve().parents[1] / "simion" / "mrtof_candidate.lua"
    program_output = output_directory / "mrtof_candidate.lua"
    program_output.write_bytes(program_template.read_bytes())
    voltage_map_template = program_template.with_name("candidate_voltage_map.lua")
    voltage_map_output = output_directory / "mrtof_candidate.voltage_map.lua"
    voltage_map_output.write_bytes(voltage_map_template.read_bytes())
    first_prism_program_template = program_template.with_name("mrtof_first_prism_l0.lua")
    first_prism_program_output = output_directory / "mrtof_first_prism_l0.lua"
    first_prism_program_output.write_bytes(first_prism_program_template.read_bytes())
    first_prism_operating_point_output = output_directory / "mrtof_first_prism_l0.operating_point.lua"
    first_prism_operating_point_output.write_bytes(sidecar_output.read_bytes())
    first_prism_voltage_map_output = output_directory / "mrtof_first_prism_l0.voltage_map.lua"
    first_prism_voltage_map_output.write_bytes(voltage_map_output.read_bytes())
    center_fly2_output = output_directory / "mrtof_candidate_center.fly2"
    center_fly2_output.write_text(center_fly2, encoding="utf-8", newline="\n")
    bunch_fly2_output = output_directory / "mrtof_candidate.fly2"
    bunch_fly2_output.write_text(bunch_fly2, encoding="utf-8", newline="\n")
    accelerator_focus_center_output = output_directory / "mrtof_accelerator_focus_center.fly2"
    accelerator_focus_center_output.write_text(accelerator_focus_center_fly2, encoding="utf-8", newline="\n")
    accelerator_focus_bunch_output = output_directory / "mrtof_accelerator_focus.fly2"
    accelerator_focus_bunch_output.write_text(accelerator_focus_bunch_fly2, encoding="utf-8", newline="\n")
    first_prism_entry_center_output = output_directory / "mrtof_first_prism_entry_center.fly2"
    first_prism_entry_center_output.write_text(first_prism_entry_center_fly2, encoding="utf-8", newline="\n")
    # Workbench consumes the Fly2 whose basename matches the diagnostic IOB,
    # while the descriptive entry-source filename remains the provenance key.
    first_prism_iob_fly2_output = output_directory / "mrtof_first_prism_l0.fly2"
    first_prism_iob_fly2_output.write_bytes(first_prism_entry_center_output.read_bytes())
    manifest_output = output_directory / "prototype_input_manifest.json"
    manifest_output.write_text(json.dumps({
        "schema_version": 2,
        "accelerator_dependency": accelerator_dependency,
        "baseline_contract": {"filename": contract_path.name, "sha256": _sha256(contract_path)},
        "analytic_mirror_receipt": {"filename": mirror_receipt_path.name, "sha256": _sha256(mirror_receipt_path)},
        "first_prism_l0_receipt": {"filename": prism_receipt_output.name, "sha256": _sha256(prism_receipt_output)},
        "derived_contract": {"filename": contract_output.name, "sha256": _sha256(contract_output)},
        "operating_point": {"filename": sidecar_output.name, "sha256": _sha256(sidecar_output)},
        "program": {"filename": program_output.name, "sha256": _sha256(program_output)},
        "voltage_map": {"filename": voltage_map_output.name, "sha256": _sha256(voltage_map_output)},
        "first_prism_program": {"filename": first_prism_program_output.name, "sha256": _sha256(first_prism_program_output)},
        "first_prism_operating_point": {"filename": first_prism_operating_point_output.name, "sha256": _sha256(first_prism_operating_point_output)},
        "first_prism_voltage_map": {"filename": first_prism_voltage_map_output.name, "sha256": _sha256(first_prism_voltage_map_output)},
        "center_fly2": _particle_source_record(center_fly2_output, particle_source, "center_particle_count"),
        "candidate_bunch_fly2": _particle_source_record(bunch_fly2_output, particle_source, "candidate_bunch_particle_count"),
        "accelerator_focus_center_fly2": _particle_source_record(accelerator_focus_center_output, particle_source, "center_particle_count"),
        "accelerator_focus_bunch_fly2": _particle_source_record(accelerator_focus_bunch_output, particle_source, "candidate_bunch_particle_count"),
        "first_prism_entry_center_fly2": _particle_source_record(first_prism_entry_center_output, particle_source, "center_particle_count"),
        "first_prism_iob_fly2": _particle_source_record(first_prism_iob_fly2_output, particle_source, "center_particle_count"),
        "status": "geometry_review_only__unsolved_stripe_and_p2__flight_forbidden",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract": contract_output,
        "first_prism_l0_receipt": prism_receipt_output,
        "operating_point": sidecar_output,
        "program": program_output,
        "voltage_map": voltage_map_output,
        "first_prism_program": first_prism_program_output,
        "first_prism_operating_point": first_prism_operating_point_output,
        "first_prism_voltage_map": first_prism_voltage_map_output,
        "center_fly2": center_fly2_output,
        "candidate_bunch_fly2": bunch_fly2_output,
        "accelerator_focus_center_fly2": accelerator_focus_center_output,
        "accelerator_focus_bunch_fly2": accelerator_focus_bunch_output,
        "first_prism_entry_center_fly2": first_prism_entry_center_output,
        "first_prism_iob_fly2": first_prism_iob_fly2_output,
        "manifest": manifest_output,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--mirror-receipt", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    arguments = parser.parse_args()
    outputs = materialize(arguments.contract, arguments.mirror_receipt, arguments.output_directory)
    print("SIMION_PROTOTYPE_INPUT: status=prototype_only contract=" + str(outputs["contract"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
