"""Materialize and analyze one finite-3D P1/P2 voltage trial.

The trial reuses the reviewed PA geometry.  It combines the independently
derived mirror/Stripe point and the separately calibrated accelerator focus
point, then changes only the two prism voltages.  The source starts in
accelerator gap 1 with the mirror/Stripe-selected near-5-eV slow kinetic energy
in +project-y; the accelerator field supplies the fast -project-z energy.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import nullcontext
from common.simion.scientific_event_io import iter_csv_rows
from common.contracts.write_run_manifest import file_record
import csv
import hashlib
import json
import shutil
import math
from common.paths.workspace_paths import project_native_run_path

from pathlib import Path
from typing import Any


def resolve_trajectory_recording(contract: dict[str, Any]) -> dict[str, Any] | None:
    """Validate callback observation without changing integration or event settings."""
    value = contract["simion"].get("trajectory_recording")
    if value is None:
        return None
    common = {"schema_version", "mode", "retention_class", "reason", "output_budget_bytes"}
    if not isinstance(value, dict) or value.get("mode") not in {"every_step", "fixed_interval"}:
        raise ValueError("trajectory_recording requires every_step or fixed_interval")
    expected = common | ({"interval_us"} if value["mode"] == "fixed_interval" else set())
    if set(value) != expected or value["schema_version"] != 1:
        raise ValueError("trajectory_recording fields differ from its schema 1 sampling mode")
    if value["retention_class"] != "solver_review" or not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ValueError("recorded trajectories require solver_review with a reason")
    if type(value["output_budget_bytes"]) is not int or value["output_budget_bytes"] < 1:
        raise ValueError("trajectory output_budget_bytes must be a positive integer")
    if value["mode"] == "fixed_interval":
        interval = value["interval_us"]
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("trajectory interval_us must be finite and positive")
    return dict(value)


def extract_trajectory_samples(*, log_path: Path, output_path: Path, receipt_path: Path,
                               recording_config: dict[str, Any] | None = None,
                               scientific_event_output: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stream solver callback states into CSV, rejecting incomplete per-ion lifecycles."""
    recording = resolve_trajectory_recording({"simion": {"trajectory_recording": recording_config}})
    mode = recording["mode"] if recording else "every_step"
    columns = ["ion", "phase", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"]
    counts: dict[int, int] = {}
    last: dict[int, tuple[float, str]] = {}
    prior_time: dict[int, float] = {}
    last_state: dict[int, tuple[float, ...]] = {}
    terminal_clock_backsteps = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trajectory_identity = {}
    declared_path = None
    def actual_rows():
        nonlocal declared_path
        if scientific_event_output is not None:
            if not scientific_event_output.get("trajectory_path"):
                raise ValueError("declared trajectory output missing")
            declared_path = Path(scientific_event_output["trajectory_path"])
            yield from iter_csv_rows(declared_path, columns, exact_header=columns, identity_result=trajectory_identity, expected_record=scientific_event_output.get("trajectory_record"))
        else:
            with log_path.open(encoding="utf-8-sig") as source:
                for line in source:
                    if line.startswith("MRTOF_TRAJECTORY "):
                        yield dict(item.split("=", 1) for item in line.split()[1:])
    with (output_path.open("w",encoding="utf-8",newline="") if scientific_event_output is None else nullcontext(None)) as target:
        writer=csv.DictWriter(target,fieldnames=columns) if target is not None else None
        if writer is not None: writer.writeheader()
        for row in actual_rows():
            if set(row) != set(columns):
                raise ValueError("trajectory sample has missing or unknown fields")
            ion, time = int(row["ion"]), float(row["t_us"])
            if ion < 1 or not all(math.isfinite(float(row[key])) for key in columns[2:]):
                raise ValueError("trajectory sample identity or state is invalid")
            phase = row["phase"]
            state = tuple(float(row[key]) for key in columns[3:])
            if phase not in {"birth", "step", "terminal"}:
                raise ValueError("unknown trajectory sample phase")
            if ion not in last:
                if phase != "birth":
                    raise ValueError("trajectory does not start at birth")
            else:
                if phase == "birth" or last[ion][1] == "terminal":
                    raise ValueError("trajectory lifecycle or time order is invalid")
                if time < last[ion][0]:
                    # Native electrode contact can restore the preceding callback
                    # clock at terminate while retaining the last identical state.
                    # Keep both raw records. Every-step recording requires the
                    # exact prior callback clock; sparse recording bounds it by
                    # adjacent observations and does not establish one-step size.
                    clock_matches = time == prior_time.get(ion)
                    if mode == "fixed_interval":
                        clock_matches = prior_time.get(ion, last[ion][0]) <= time < last[ion][0]
                    if phase != "terminal" or not clock_matches or state != last_state[ion]:
                        raise ValueError("trajectory time order is invalid")
                    terminal_clock_backsteps.append({"ion": ion, "backstep_us": last[ion][0] - time})
                prior_time[ion] = last[ion][0]
            last[ion] = (time, phase)
            last_state[ion] = state
            counts[ion] = counts.get(ion, 0) + 1
            if writer is not None: writer.writerow(row)
    if declared_path is not None: output_path=declared_path
    minimum_samples = 2 if mode == "fixed_interval" else 3
    if not counts or any(phase != "terminal" or counts[ion] < minimum_samples for ion, (_, phase) in last.items()):
        raise ValueError("trajectory is empty or lacks steps/terminal state")
    result = {"schema_version": 1, "role": "mrtof_solver_step_trajectory", "status": "success",
              "sampling": ("initialize__first_other_actions_callback_per_absolute_clock_bucket__terminate"
                           if mode == "fixed_interval" else "initialize__every_other_actions_callback__terminate"),
              "sampling_mode": mode, "sampling_interval_us": recording["interval_us"] if mode == "fixed_interval" else None,
              "sampling_grid_origin_us": 0 if mode == "fixed_interval" else None,
              "recording_configuration": recording,
              "interpolated": False, "frame_id": "astral.xyz.reflection_z.drift_y.transverse_x.v2",
              "clock_basis": "instrument_time_us_from_frozen_source_authority",
              "sample_count": sum(counts.values()), "samples_per_particle": counts,
              "terminal_clock_backsteps": terminal_clock_backsteps,
              "record_order": "solver_callback_order__raw_terminal_clock_retained",
              "source_log": str(log_path.resolve()), "source_log_sha256": file_sha256(log_path).lower(),
              "trajectory_csv": str(output_path.resolve()), "trajectory_csv_sha256": trajectory_identity["sha256"] if declared_path is not None else file_sha256(output_path).lower()}
    receipt_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
)
from projects.orthogonal_accelerator.analysis.component_focus_analysis import (
    _component_energy_per_charge_v,
    _target_axial_energy_per_charge_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    load_verified_bunch_source_receipt,
    solver_problem_identity_from_trial_receipt,
    source_cohort_identity,
    validate_fixed_global_pulse_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import (
    _full_path_timeout_us,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_stripe_shape_adapter import (
    native_stripe_geometry_projection_sha256,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import (
    resolve_accelerator_iob_origin, resolve_oa_mr_direct_pose, resolve_static_iob_origins,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    CONVERGING_PRISM_ENERGY_RESIDUAL, converging_design_potential_delta_v,
    resolve_converging_prism_target,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import (
    load_binding, validate_voltages, _lua_vector, _scalar_field_lua_fields,
    _scalar_refinement_windows_lua,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_mirror_voltage_bounds,
    load_contract,
    mirror_power_supply_limits,
    resolve_trajectory_profile,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    summarize_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
    observation_from_simion_events,
    prism_handoff_residuals,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"expected an object in {path}")
    return value


_GLOBAL_PULSE_TIME_BASIS = "ion_time_of_flight_us_from_common_tob_zero_release"


def _collision_geometry_projection(resolved: dict[str, Any]) -> dict[str, Any]:
    """Freeze only the resolved solids needed to name terminal collisions."""
    keys = (
        "mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot",
        "mirror_ground_shields", "mirror_e_closures", "stripe_electrodes",
        "stripe_slot", "central_ground_electrodes", "central_ground_slots",
        "prism_electrodes", "prism_ground_shields",
    )
    return {
        "schema_version": 1,
        "mesh_mm_per_gu": 0.25,
        **{key: copy.deepcopy(resolved[key]) for key in keys},
        **{key: copy.deepcopy(resolved[key]) for key in ("ion_processor_electrodes", "detector") if key in resolved},
    }


def _apply_trajectory_step_scale(
    trajectory_profile: dict[str, Any], trajectory_step_scale: float,
) -> dict[str, Any]:
    scale = _finite(trajectory_step_scale, "trajectory step scale")
    if scale <= 0:
        raise CandidateContractError("trajectory step scale must be positive")
    if scale == 1:
        return trajectory_profile
    profile = dict(trajectory_profile)
    base_profile_id = str(profile["profile_id"])
    base_maximum_step_us = _finite(
        profile["maximum_step_us"], "base maximum trajectory step",
    )
    maximum_step_us = _finite(base_maximum_step_us * scale, "scaled maximum trajectory step")
    if maximum_step_us <= 0:
        raise CandidateContractError("scaled maximum trajectory step must be positive")
    profile.update({
        "profile_id": f"{base_profile_id}__step_scale_{scale:.12g}",
        "base_profile_id": base_profile_id,
        "base_maximum_step_us": base_maximum_step_us,
        "step_scale": scale,
        "maximum_step_us": maximum_step_us,
        "purpose": (
            f"{profile['purpose']}; run-local numerical step scaling "
            "of one frozen source interval"
        ),
    })
    return profile


def _accelerator_energy_binding(
    accelerator: dict[str, Any], analyzer_axial_energy_per_charge_v: float,
) -> dict[str, float]:
    """Validate the calibrated accelerator command against its physical target."""
    analyzer_target = _finite(
        analyzer_axial_energy_per_charge_v, "analyser selected axial energy",
    )
    applied = _finite(
        accelerator.get("energy_per_charge_v"),
        "accelerator applied net-gain parameter",
    )
    target = _finite(
        accelerator.get("target_axial_energy_per_charge_v"),
        "accelerator target axial energy",
    )
    correction = _finite(
        accelerator.get("finite_3d_gain_correction_v"),
        "accelerator finite-3D gain correction",
    )
    if abs(target - analyzer_target) > 1e-9:
        raise CandidateContractError(
            "accelerator target axial energy and analyser selected axial energy differ"
        )
    if abs((applied - correction) - target) > 1e-9:
        raise CandidateContractError(
            "accelerator applied net-gain parameter, finite-3D correction, and "
            "target axial energy are inconsistent"
        )
    return {
        "applied_net_gain_parameter_v": applied,
        "target_axial_energy_per_charge_v": target,
        "finite_3d_gain_correction_v": correction,
    }


def _provider_exit_energy_contract(projection: dict[str, Any]) -> dict[str, Any]:
    """Project only the OA component energy targets needed by MR diagnostics."""
    release = projection.get("accepted_release")
    acceptance = projection.get("provider_exit_energy_acceptance")
    if not isinstance(release, dict) or not isinstance(acceptance, dict):
        raise CandidateContractError("provider receipt lacks exit-energy acceptance")
    center = acceptance.get("center_particle")
    tolerances = acceptance.get("tolerances")
    if acceptance.get("passed") is not True or not isinstance(center, dict) or not isinstance(tolerances, dict):
        raise CandidateContractError("provider exit-energy acceptance is incomplete or failed")
    targets = {
        "Ex": _finite(
            center.get("source_transverse_energy_per_charge_v"),
            "provider target transverse energy",
        ),
        "Ey": _finite(
            release.get("slow_energy_center_per_charge_v"),
            "provider target slow energy",
        ),
        "Ez": _finite(
            acceptance.get("target_axial_energy_per_charge_v"),
            "provider target axial energy",
        ),
    }
    limits = {
        "Ex": _finite(
            tolerances.get("maximum_exit_transverse_energy_error_per_charge_v"),
            "provider transverse-energy tolerance",
        ),
        "Ey": _finite(
            tolerances.get("maximum_exit_slow_energy_error_per_charge_v"),
            "provider slow-energy tolerance",
        ),
        "Ez": _finite(
            tolerances.get("maximum_exit_axial_energy_error_per_charge_v"),
            "provider axial-energy tolerance",
        ),
    }
    velocity_bias_tolerance = _finite(
        tolerances.get("maximum_exit_transverse_velocity_bias_mm_per_us"),
        "provider transverse-velocity bias tolerance",
    )
    if any(value < 0.0 for value in limits.values()) or velocity_bias_tolerance < 0.0:
        raise CandidateContractError("provider exit-energy tolerances must be nonnegative")
    expected_slow = _finite(
        center.get("source_slow_energy_per_charge_v"),
        "provider center source slow energy",
    )
    expected_axial = _finite(
        center.get("expected_exit_axial_energy_per_charge_v"),
        "provider center expected axial energy",
    )
    projection_axial = _finite(
        projection.get("target_axial_energy_per_charge_v"),
        "provider projection target axial energy",
    )
    if abs(expected_slow - targets["Ey"]) > 1e-9:
        raise CandidateContractError("provider slow-energy targets differ")
    if abs(expected_axial - targets["Ez"]) > 1e-9 or abs(projection_axial - targets["Ez"]) > 1e-9:
        raise CandidateContractError("provider axial-energy targets differ")
    return {
        "targets_per_charge_v": targets,
        "absolute_tolerances_per_charge_v": limits,
        "maximum_exit_transverse_velocity_bias_mm_per_us": velocity_bias_tolerance,
        "authority": "orthogonal_accelerator_provider_exit_energy_acceptance",
    }


def _validate_center_view_source(bunch_source: dict[str, Any] | None,
                                bunch_selection: dict[str, Any] | None) -> None:
    """Require every actual initial state on the invariant x symmetry plane."""
    if bunch_selection is not None:
        states = [(float(s["position_workbench_mm"][0]), float(s["direction_workbench"][0]))
                  for s in bunch_selection["states"]]
    elif bunch_source is not None:
        with Path(bunch_source["state_table"]["path"]).open(encoding="utf-8", newline="") as stream:
            states = [(float(s["x_mm"]), float(s["direction_x"])) for s in csv.DictReader(stream)]
    else:
        # The existing analytic centre source emits position x=0, direction x=0.
        states = [(0.0, 0.0)]
    if not states or any(x != 0 or dx != 0 for x, dx in states):
        raise CandidateContractError("x_symmetry_plane consumer view requires every source x=0 and vx=0")


def _source_transverse_reference(
    *, bunch_source: dict[str, Any] | None, bunch_selection: dict[str, Any] | None,
    mass_th: float, charge_state: int, slow_energy_per_charge_v: float,
) -> dict[str, Any]:
    """Freeze only source x/vx statistics required by the assembled safe-exit check."""
    rows: list[tuple[int, float, float]] = []
    if bunch_selection is not None:
        for particle_id, state in zip(
            bunch_selection["particle_ids"], bunch_selection["states"], strict=True,
        ):
            direction = state["direction_workbench"]
            speed = math.sqrt(
                2.0 * float(state["kinetic_energy_ev"]) * ELEMENTARY_CHARGE_C
                / (float(state["mass_th"]) * AMU_KG)
            ) / 1000.0
            rows.append((int(particle_id), float(state["position_workbench_mm"][0]), speed * float(direction[0])))
    elif bunch_source is not None:
        with Path(bunch_source["state_table"]["path"]).open(
            "r", encoding="utf-8", newline="",
        ) as stream:
            for row in csv.DictReader(stream):
                speed = math.sqrt(
                    2.0 * float(row["kinetic_energy_ev"]) * ELEMENTARY_CHARGE_C
                    / (float(row["mass_th"]) * AMU_KG)
                ) / 1000.0
                rows.append((int(row["particle_id"]), float(row["x_mm"]), speed * float(row["direction_x"])))
    else:
        speed = math.sqrt(
            2.0 * slow_energy_per_charge_v * abs(charge_state) * ELEMENTARY_CHARGE_C
            / (mass_th * AMU_KG)
        ) / 1000.0
        rows.append((1, 0.0, speed * 0.0))
    declared_center_particle_id: int | None = 1 if bunch_source is None else None
    if bunch_source is not None and bunch_source.get("center_particle_state") is not None:
        center_particle_id = bunch_source["center_particle_state"].get("particle_id")
        if type(center_particle_id) is not int or center_particle_id <= 0:
            raise CandidateContractError("bunch source center particle identity is invalid")
        declared_center_particle_id = center_particle_id
    center = (
        next((row for row in rows if row[0] == declared_center_particle_id), None)
        if declared_center_particle_id is not None else None
    )
    if not rows:
        raise CandidateContractError("source transverse reference is empty")
    return {
        "particle_count": len(rows),
        "center_particle_id": declared_center_particle_id if center is not None else None,
        "center_x_mm": center[1] if center is not None else None,
        "center_vx_mm_per_us": center[2] if center is not None else None,
        "mean_x_mm": sum(row[1] for row in rows) / len(rows),
        "mean_vx_mm_per_us": sum(row[2] for row in rows) / len(rows),
    }


def _accelerator_geometric_exit_reference(
    *, contract: dict[str, Any], provider_plan: dict[str, Any],
    resolved_campaign: dict[str, Any], bunch_source: dict[str, Any] | None,
    bunch_selection: dict[str, Any] | None, mass_th: float, charge_state: int,
    slow_energy_per_charge_v: float, source_origin_project_mm: tuple[float, float, float],
    composition_plan: dict[str, Any], local_scope: dict[str, Any] | None,
    direct_pose: dict[str, Any], validated_provider_origin: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """Project the OA provider's per-particle geometric-exit targets into MR coordinates."""
    provider_origin = (resolve_accelerator_iob_origin(contract, provider_plan, composition_plan, local_scope=local_scope, direct_pose=direct_pose)
                       if validated_provider_origin is None else validated_provider_origin)
    domain = provider_plan["numerical_domain"]
    local_exit_z_mm = _finite(domain.get("local_exit_z_mm"), "provider local exit z")
    global_exit_z_mm = _finite(direct_pose["exit_project_mm"][2], "composition OA exit z")
    if not math.isclose(
        provider_origin[2] + local_exit_z_mm,
        global_exit_z_mm,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise CandidateContractError("accelerator provider exit-plane mapping differs")
    layout = provider_plan.get("layout")
    if (
        not isinstance(layout, dict)
        or resolved_campaign.get("role") != "orthogonal_accelerator_component_focus_campaign"
        or resolved_campaign.get("geometry_profile_id") != layout.get("geometry_profile_id")
    ):
        raise CandidateContractError("accelerator resolved campaign differs from the provider plan")
    release_spec = resolved_campaign.get("release_spec")
    species = release_spec.get("species") if isinstance(release_spec, dict) else None
    if (
        not isinstance(species, dict)
        or _finite(species.get("mass_amu"), "provider release mass") != mass_th
        or _finite(species.get("charge_state"), "provider release charge") != charge_state
    ):
        raise CandidateContractError("accelerator resolved campaign species differs from the MR source")
    acceptance = resolved_campaign.get("acceptance")
    if not isinstance(acceptance, dict):
        raise CandidateContractError("accelerator resolved campaign lacks exit acceptance")
    tolerances = {
        "Ex": _finite(
            acceptance.get("maximum_exit_transverse_energy_error_per_charge_v"),
            "provider transverse-energy tolerance",
        ),
        "Ey": _finite(
            acceptance.get("maximum_exit_slow_energy_error_per_charge_v"),
            "provider slow-energy tolerance",
        ),
        "Ez": _finite(
            acceptance.get("maximum_exit_axial_energy_error_per_charge_v"),
            "provider axial-energy tolerance",
        ),
    }
    plane_tolerance_mm = _finite(
        acceptance.get("focus_plane_tolerance_mm"), "provider exit-plane tolerance",
    )
    raw_states: list[dict[str, Any]] = []
    if bunch_selection is not None:
        raw_states = [
            {"particle_id": particle_id, **state}
            for particle_id, state in zip(
                bunch_selection["particle_ids"], bunch_selection["states"], strict=True,
            )
        ]
    elif bunch_source is not None:
        raise CandidateContractError(
            "accelerator exit reference requires the existing typed source selection"
        )
    else:
        raw_states = [{
            "particle_id": 1,
            "mass_th": mass_th,
            "charge_e": charge_state,
            "kinetic_energy_ev": slow_energy_per_charge_v * abs(charge_state),
            "position_workbench_mm": list(source_origin_project_mm),
            "direction_workbench": [0.0, 1.0, 0.0],
        }]
    rows: list[dict[str, Any]] = []
    for raw in raw_states:
        if "position_workbench_mm" in raw:
            position = [_finite(value, "source position") for value in raw["position_workbench_mm"]]
            direction = [_finite(value, "source direction") for value in raw["direction_workbench"]]
        else:
            position = [_finite(raw[name], f"source {name}") for name in ("x_mm", "y_mm", "z_mm")]
            direction = [
                _finite(raw[name], f"source {name}")
                for name in ("direction_x", "direction_y", "direction_z")
            ]
        particle_id = int(raw["particle_id"])
        row_mass = _finite(raw.get("mass_th"), "source mass")
        row_charge = _finite(raw.get("charge_e", charge_state), "source charge")
        if row_mass != mass_th or row_charge != charge_state:
            raise CandidateContractError("MR source particle species differs from the trial")
        kinetic_energy = _finite(raw.get("kinetic_energy_ev"), "source kinetic energy")
        speed_m_s = math.sqrt(2.0 * kinetic_energy * ELEMENTARY_CHARGE_C / (row_mass * AMU_KG))
        velocity = [speed_m_s * component for component in direction]
        source_provider = [
            position[0] - float(direct_pose["exit_project_mm"][0]), position[1] - float(direct_pose["exit_project_mm"][1]), position[2] - global_exit_z_mm,
        ]
        source_energy = {
            name: _component_energy_per_charge_v(row_mass, row_charge, velocity[index])
            for index, name in enumerate(("Ex", "Ey", "Ez"))
        }
        expected_exit = {
            "Ex": source_energy["Ex"],
            "Ey": source_energy["Ey"],
            "Ez": (
                _target_axial_energy_per_charge_v(
                    resolved_campaign, source_provider[2],
                )
                + source_energy["Ez"]
            ),
        }
        rows.append({
            "particle_id": particle_id,
            "source_position_provider_mm": source_provider,
            "source_velocity_provider_m_per_s": velocity,
            "source_component_energy_per_charge_v": source_energy,
            "expected_exit_component_energy_per_charge_v": expected_exit,
        })
    expected_ids = [int(row["particle_id"]) for row in rows]
    if len(expected_ids) != len(set(expected_ids)):
        raise CandidateContractError("accelerator exit reference contains duplicate particle identities")
    return {
        "status": "derived",
        "event_kind": "accelerator_geometric_exit",
        "scope": "all_source_particles__not_detector_survivors",
        "source_frame": resolved_campaign["release_spec"]["frame_id"],
        "source_frame_origin_project_mm": list(direct_pose["exit_project_mm"]),
        "exit_plane_project_z_mm": global_exit_z_mm,
        "exit_plane_tolerance_mm": plane_tolerance_mm,
        "expected_particle_ids": expected_ids,
        "absolute_tolerances_per_charge_v": tolerances,
        "particle_rows": rows,
    }


def _accelerator_geometric_exit_validation(
    *, events: list[dict[str, Any]], reference: dict[str, Any] | None,
    expected_particle_ids: list[int], mass_th: float, charge_state: float,
) -> dict[str, Any]:
    """Compare every observed geometric-exit crossing with its frozen OA target."""
    if not isinstance(reference, dict):
        return {"status": "unavailable__geometric_exit_reference_not_frozen", "passed": None}
    reference_rows = reference.get("particle_rows")
    reference_ids = reference.get("expected_particle_ids")
    if (
        not isinstance(reference_rows, list)
        or reference_ids != expected_particle_ids
        or [row.get("particle_id") for row in reference_rows] != expected_particle_ids
    ):
        raise CandidateContractError(
            "accelerator geometric-exit reference differs from the source cohort"
        )
    tolerances = reference.get("absolute_tolerances_per_charge_v")
    if not isinstance(tolerances, dict):
        raise CandidateContractError("accelerator geometric-exit reference lacks tolerances")
    tolerance_by_component = {
        component: _finite(tolerances.get(component), f"geometric-exit {component} tolerance")
        for component in ("Ex", "Ey", "Ez")
    }
    plane_z = _finite(reference.get("exit_plane_project_z_mm"), "geometric-exit plane z")
    plane_tolerance = _finite(
        reference.get("exit_plane_tolerance_mm"), "geometric-exit plane tolerance",
    )
    by_id: dict[int, dict[str, Any]] = {}
    duplicates: list[int] = []
    unknown: list[int] = []
    expected_set = set(expected_particle_ids)
    for event in events:
        if event["kind"] != "accelerator_geometric_exit":
            continue
        particle_id = int(event["ion"])
        if particle_id not in expected_set:
            unknown.append(particle_id)
        elif particle_id in by_id:
            duplicates.append(particle_id)
        else:
            by_id[particle_id] = event
    reference_by_id = {int(row["particle_id"]): row for row in reference_rows}
    rows: list[dict[str, Any]] = []
    for particle_id in expected_particle_ids:
        event = by_id.get(particle_id)
        if event is None:
            continue
        measured = {
            component: _component_energy_per_charge_v(
                mass_th, charge_state, _finite(event[velocity], velocity) * 1000.0,
            )
            for component, velocity in zip(
                ("Ex", "Ey", "Ez"),
                ("vx_mm_us", "vy_mm_us", "vz_mm_us"),
                strict=True,
            )
        }
        expected = reference_by_id[particle_id][
            "expected_exit_component_energy_per_charge_v"
        ]
        residual = {
            component: measured[component] - _finite(
                expected.get(component), f"expected geometric-exit {component}",
            )
            for component in ("Ex", "Ey", "Ez")
        }
        plane_residual = _finite(event.get("z_mm"), "geometric-exit z") - plane_z
        component_passed = {
            component: abs(residual[component]) <= tolerance_by_component[component]
            for component in ("Ex", "Ey", "Ez")
        }
        plane_passed = abs(plane_residual) <= plane_tolerance
        direction_passed = _finite(event.get("vz_mm_us"), "geometric-exit vz") < 0.0
        rows.append({
            "particle_id": particle_id,
            "event_time_us": _finite(event.get("t_us"), "geometric-exit time"),
            "event_position_project_mm": [
                _finite(event.get(name), f"geometric-exit {name}")
                for name in ("x_mm", "y_mm", "z_mm")
            ],
            "measured_component_energy_per_charge_v": measured,
            "expected_component_energy_per_charge_v": expected,
            "residual_per_charge_v": residual,
            "component_within_tolerance": component_passed,
            "exit_plane_residual_mm": plane_residual,
            "exit_plane_within_tolerance": plane_passed,
            "negative_z_direction": direction_passed,
            "passed": all(component_passed.values()) and plane_passed and direction_passed,
        })
    missing = [particle_id for particle_id in expected_particle_ids if particle_id not in by_id]
    complete = not missing and not duplicates and not unknown
    maxima = {
        component: max(
            (abs(row["residual_per_charge_v"][component]) for row in rows),
            default=None,
        )
        for component in ("Ex", "Ey", "Ez")
    }
    exceeded_ids = {
        component: [
            row["particle_id"] for row in rows
            if not row["component_within_tolerance"][component]
        ]
        for component in ("Ex", "Ey", "Ez")
    }
    passed = complete and len(rows) == len(expected_particle_ids) and all(
        row["passed"] for row in rows
    )
    return {
        "status": "passed" if passed else "incomplete" if not complete else "failed",
        "passed": passed,
        "scope": "all_source_particles_at_provider_geometric_exit__not_detector_survivors",
        "surface_note": (
            "provider geometric exit plane; distinct from accelerator_safe_exit at the PA boundary"
        ),
        "exit_plane_project_z_mm": plane_z,
        "exit_plane_tolerance_mm": plane_tolerance,
        "absolute_tolerances_per_charge_v": tolerance_by_component,
        "expected_particle_count": len(expected_particle_ids),
        "observed_particle_count": len(rows),
        "missing_particle_ids": missing,
        "duplicate_particle_ids": sorted(set(duplicates)),
        "unknown_particle_ids": sorted(set(unknown)),
        "maximum_absolute_residual_per_charge_v": maxima,
        "out_of_tolerance_particle_ids": exceeded_ids,
        "particle_rows": rows,
    }


def _resolve_trial_geometry(
    reviewed_geometry_contract: dict[str, Any],
    current_topology_contract: dict[str, Any],
    accelerator_placement_contract: dict[str, Any],
    *, accelerator_assembly: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve reviewed conductors with the two consumed accelerator overrides."""
    resolved_contract = copy.deepcopy(reviewed_geometry_contract)
    reviewed_accelerator = resolved_contract.get("accelerator")
    placement_accelerator = accelerator_placement_contract.get("accelerator")
    if not isinstance(reviewed_accelerator, dict) or not isinstance(
        placement_accelerator, dict,
    ):
        raise CandidateContractError("accelerator geometry projection is unavailable")
    for key in ("component_source_cylinder", "focus_y_anchor"):
        value = placement_accelerator.get(key)
        if not isinstance(value, dict):
            raise CandidateContractError(f"accelerator geometry projection lacks {key}")
        reviewed_accelerator[key] = copy.deepcopy(value)
    return resolve_geometry(
        resolved_contract,
        inherited_dual_stripe_topology_contract=current_topology_contract,
        accelerator_assembly=accelerator_assembly,
    )


def _schema5_native_source_state(
    stripe_summary: dict[str, Any], contract: dict[str, Any], selected_energy_v: float,
) -> tuple[dict[str, Any], float]:
    """Validate the exact-K native materialization that owns the +y source energy."""
    if (
        stripe_summary.get("schema_version") != 5
        or stripe_summary.get("role") != "mrtof_dual_stripe_exact_k_downstream_operating_seed"
        or stripe_summary.get("status")
        != "native_shape_source_energy_inverse_and_stripe_on_exact_k_complete"
    ):
        raise CandidateContractError("P1/P2 source requires the schema-5 native Stripe seed")
    selected = stripe_summary.get("selected_exact_k_operating_point")
    root = stripe_summary.get("native_stripe_spatial_shape_root")
    seed = stripe_summary.get("selected_seed")
    materialized = seed.get("native_spatial_return_materialization") if isinstance(seed, dict) else None
    if not all(isinstance(value, dict) for value in (selected, root, seed, materialized)):
        raise CandidateContractError("schema-5 Stripe seed lacks its selected point, shape, or materialization")
    nominal = contract.get("nominal")
    accelerator_energy = contract.get("accelerator_energy_contract")
    prism_transport = contract.get("prism_transport")
    energy_partition = (
        prism_transport.get("energy_partition")
        if isinstance(prism_transport, dict) else None
    )
    if (
        not isinstance(nominal, dict)
        or not isinstance(accelerator_energy, dict)
        or not isinstance(energy_partition, dict)
    ):
        raise CandidateContractError("MR-TOF contract lacks its fixed axial/source energy authorities")
    materialized_energy = _finite(
        materialized.get("axial_energy_per_charge_v"),
        "native Stripe materialization axial energy",
    )
    stripe_energy = _finite(selected.get("axial_energy_per_charge_v"), "Stripe selected energy")
    reference_energy = _finite(
        accelerator_energy.get("net_gain_reference_center_per_charge_v"),
        "contract net-gain reference centre",
    )
    search_half_range = _finite(
        accelerator_energy.get("net_gain_center_search_half_range_per_charge_v"),
        "contract net-gain search half-range",
    )
    nominal_energy = _finite(nominal.get("energy_per_charge_v"), "contract nominal energy")
    if reference_energy <= 0.0 or search_half_range < 0.0 or nominal_energy != reference_energy:
        raise CandidateContractError("MR-TOF contract net-gain reference authorities differ")
    if not reference_energy - search_half_range <= selected_energy_v <= reference_energy + search_half_range:
        raise CandidateContractError("selected exact-K energy is outside the contract search envelope")
    if any(abs(value - selected_energy_v) > 1e-9 for value in (
        materialized_energy, stripe_energy,
    )):
        raise CandidateContractError("native Stripe and mirror selected energies differ")
    materialized_root = materialized.get("shape_root")
    seed_biases = _vector(seed.get("stripe_biases_v"), 2, "native Stripe seed biases")
    materialized_biases = _vector(
        materialized.get("stripe_biases_v"), 2, "native Stripe materialization biases",
    )
    expected_geometry_identity = (
        "canonical_json_sha256:"
        f"{native_stripe_geometry_projection_sha256(contract)}"
    )
    if (
        materialized_root != root
        or materialized_biases != seed_biases
        or root.get("geometry_input_identity_source") != expected_geometry_identity
        or _finite(seed.get("nominal_kappa_1"), "native Stripe seed kappa")
        != _finite(root.get("kappa_1"), "native Stripe shape kappa")
        or _finite(selected.get("kappa_1"), "Stripe selected-point kappa")
        != _finite(root.get("kappa_1"), "native Stripe shape kappa")
    ):
        raise CandidateContractError("schema-5 Stripe materialization shape identity is inconsistent")
    source_energy = _finite(
        materialized.get("source_slow_energy_per_charge_v"),
        "native Stripe materialization source slow energy",
    )
    contract_source_energy = _finite(
        energy_partition.get("drift_kinetic_energy_ev"),
        "contract source slow energy",
    )
    if source_energy <= 0.0 or source_energy != contract_source_energy:
        raise CandidateContractError("native Stripe source slow energy differs from the fixed source contract")
    return seed, source_energy


def load_schema5_native_source_state(
    stripe_summary: dict[str, Any], contract: dict[str, Any], selected_energy_v: float,
) -> tuple[dict[str, Any], float]:
    """Public strict loader for the contract-bound schema-5 native Stripe source."""
    return _schema5_native_source_state(stripe_summary, contract, selected_energy_v)


def _fixed_mirror_stripe_source_state(
    authority: dict[str, Any],
    mirror_summary: dict[str, Any],
    stripe_summary: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[dict[str, Any], float, float, list[float], float]:
    """Validate the fixed-grid mirror/variable-slow-energy downstream receipt."""
    if (
        authority.get("schema_version") != 1
        or authority.get("role")
        != "mrtof_fixed_mirror_stripe_downstream_operating_authority"
        or authority.get("status") != "success"
    ):
        raise CandidateContractError("fixed mirror/Stripe downstream authority is invalid")
    if (
        mirror_summary.get("schema_version") != 1
        or mirror_summary.get("role") != "mrtof_mirror_turn_fixed_grid_validation"
        or mirror_summary.get("status") != "success"
    ):
        raise CandidateContractError("fixed mirror summary identity is invalid")
    if (
        stripe_summary.get("schema_version") != 3
        or stripe_summary.get("role")
        != "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family"
        or stripe_summary.get("status")
        != "fixed_grid_native_mirror_exact_K_slow_energy_and_spatial_return_inverse_complete"
    ):
        raise CandidateContractError("fixed-mirror Stripe summary identity is invalid")
    seed = stripe_summary.get("selected_seed")
    materialized = (
        seed.get("native_spatial_return_materialization")
        if isinstance(seed, dict) else None
    )
    if not isinstance(seed, dict) or not isinstance(materialized, dict):
        raise CandidateContractError("fixed-mirror Stripe summary lacks its materialization")
    axial = _finite(authority.get("axial_energy_per_charge_v"), "fixed mirror axial energy")
    slow = _finite(authority.get("slow_energy_per_charge_v"), "selected slow energy")
    target_k = _finite(authority.get("target_period_ratio"), "fixed mirror/Stripe target K")
    predicted_k = _finite(
        authority.get("predicted_period_ratio"), "fixed mirror/Stripe predicted K",
    )
    mirror_voltages = _vector(
        authority.get("mirror_voltages_v"), 5, "fixed-grid mirror voltages",
    )
    stripe_biases = _vector(
        authority.get("stripe_biases_v"), 2, "fixed-mirror Stripe biases",
    )
    if slow <= 0.0 or axial <= 0.0 or not math.isclose(
        target_k, predicted_k, rel_tol=0.0, abs_tol=1e-12,
    ):
        raise CandidateContractError("fixed mirror/Stripe energy or K identity is invalid")
    expected = (
        _finite(seed.get("selected_axial_energy_per_charge_v"), "Stripe axial energy"),
        _finite(seed.get("selected_exact_K_slow_energy_per_charge_v"), "Stripe slow energy"),
        _finite(seed.get("target_drift_period_ratio"), "Stripe target K"),
        _finite(seed.get("predicted_continuous_oscillation_count"), "Stripe predicted K"),
    )
    materialized_biases = _vector(
        materialized.get("stripe_biases_v"), 2, "materialized Stripe biases",
    )
    if (
        expected != (axial, slow, target_k, predicted_k)
        or _vector(seed.get("stripe_biases_v"), 2, "Stripe seed biases") != stripe_biases
        or materialized_biases != stripe_biases
        or _finite(materialized.get("axial_energy_per_charge_v"), "materialized axial energy")
        != axial
        or _finite(materialized.get("source_slow_energy_per_charge_v"), "materialized slow energy")
        != slow
    ):
        raise CandidateContractError("fixed mirror/Stripe authority differs from its source summary")
    energy_contract = contract.get("accelerator_energy_contract")
    if not isinstance(energy_contract, dict):
        raise CandidateContractError("MR-TOF contract lacks its accelerator energy envelope")
    reference = _finite(
        energy_contract.get("net_gain_reference_center_per_charge_v"),
        "contract net-gain reference centre",
    )
    half_range = _finite(
        energy_contract.get("net_gain_center_search_half_range_per_charge_v"),
        "contract net-gain search half-range",
    )
    if not reference - half_range <= axial <= reference + half_range:
        raise CandidateContractError("fixed-grid mirror energy is outside the contract search envelope")
    return seed, slow, axial, mirror_voltages, target_k


def _apply_terminal_mirror_variation(
    *, variation: dict[str, Any] | None, base_voltages: list[float],
    contract: dict[str, Any], axial_energy_v: float,
) -> tuple[list[float], dict[str, Any] | None]:
    if variation is None:
        return base_voltages, None
    if (
        variation.get("schema_version") != 1
        or variation.get("role") != "mrtof_terminal_time_mirror_voltage_variation"
        or variation.get("status") != "screening_candidate_materialized"
        or variation.get("qualification") not in {
            "diagnostic_only__complete_3d_detector_response_pending",
            "bare_mirror_prediction_outside_old_zero_slope_budget__complete_system_response_required",
        }
    ):
        raise CandidateContractError("terminal-time mirror variation identity is invalid")
    base = _vector(
        variation.get("base_mirror_voltages_v"), 5,
        "terminal-time variation base mirror voltages",
    )
    target = _vector(
        variation.get("target_mirror_voltages_v"), 5,
        "terminal-time variation target mirror voltages",
    )
    delta = _vector(
        variation.get("voltage_delta_v"), 4,
        "terminal-time variation voltage delta",
    )
    if base != base_voltages or base[0] != 0.0 or target[0] != 0.0:
        raise CandidateContractError(
            "terminal-time mirror variation is not bound to the selected mirror authority"
        )
    if any(
        not math.isclose(target[index + 1] - base[index + 1], delta[index],
                         rel_tol=0.0, abs_tol=1e-9)
        for index in range(4)
    ):
        raise CandidateContractError("terminal-time mirror variation delta is inconsistent")
    lower, upper = derive_mirror_voltage_bounds(contract, selected_center_v=axial_energy_v)
    if any(
        value < low or value > high
        for value, low, high in zip(target[1:], lower, upper, strict=True)
    ):
        raise CandidateContractError("terminal-time mirror variation violates the mirror envelope")
    identity = {
        "mode": variation.get("mode"),
        "coordinate": variation.get("coordinate"),
        "voltage_delta_v": delta,
        "source_seed": variation.get("source_seed"),
    }
    return target, identity


def _p2_handoff_targets(
    seed: dict[str, Any], contract: dict[str, Any],
) -> tuple[float, float, float]:
    """Derive the positive-turn y and low-field angle from Stripe authority."""
    registration = contract.get("dual_stripe_l0", {}).get(
        "theory_function_coordinate_registration"
    )
    if not isinstance(registration, dict):
        raise CandidateContractError("MR-TOF contract lacks the Stripe function registration")
    target_y = _finite(
        registration.get("function_y_zero_project_y_mm"),
        "Stripe function-y origin in project coordinates",
    )
    angle_degrees = _finite(
        seed.get("nominal_injection_angle_degrees"),
        "native Stripe seed nominal injection angle",
    )
    tangent_ratio = math.tan(math.radians(angle_degrees))
    if not math.isfinite(tangent_ratio) or tangent_ratio <= 0.0:
        raise CandidateContractError(
            "native Stripe seed injection angle must give a finite positive vy/vz tangent"
        )
    return target_y, angle_degrees, tangent_ratio


def _single_center_source_fly2(
    *, mass_th: float, charge_state: int, source_slow_energy_per_charge_v: float,
    focus_y_mm: float, release_z_mm: float,
) -> str:
    """Render the real +y slow-energy release used before -z acceleration."""
    return (
        "particles {\n  coordinates = 0,\n  standard_beam {\n"
        f"    n = 1,\n    tob = 0,\n    mass = {mass_th:.17g},\n    charge = {charge_state},\n"
        f"    ke = {source_slow_energy_per_charge_v * abs(charge_state):.17g},\n"
        "    cwf = 1,\n    color = 0,\n"
        "    direction = vector(0, 1, 0),\n"
        "    position = circle_distribution {\n"
        f"      center = vector(0, {focus_y_mm:.17g}, {release_z_mm:.17g}),\n"
        "      normal = vector(0, 0, -1),\n      radius = 0,\n      fill = true\n"
        "    }\n  }\n}\n"
    )


def _load_frozen_accelerator_pulse_schedule(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    schedule = _load(path)
    if (
        schedule.get("schema_version") not in (1, 2)
        or schedule.get("role") != "mrtof_accelerator_global_pulse_schedule"
        or schedule.get("status") != "frozen"
        or schedule.get("mode") != "fixed_global_time"
        or schedule.get("time_basis") != _GLOBAL_PULSE_TIME_BASIS
    ):
        raise CandidateContractError("accelerator pulse schedule identity is invalid")
    pulse_time = _finite(schedule.get("pulse_off_time_us"), "accelerator pulse-off time")
    if pulse_time <= 0:
        raise CandidateContractError("accelerator pulse-off time must be positive")
    if schedule["schema_version"] == 1:
        source = schedule.get("source")
        if not isinstance(source, dict) or any(
            not isinstance(source.get(key), str) or not source[key]
            for key in (
                "center_run_id", "run_manifest_sha256", "trial_receipt_sha256",
                "observation_sha256", "source_fly2_sha256", "accelerator_receipt_sha256",
            )
        ):
            raise CandidateContractError("accelerator pulse schedule has incomplete source identity")
        if source.get("source_particle_count") != 1:
            raise CandidateContractError("legacy pulse schedules must contain one particle")
    else:
        if (
            not isinstance(schedule.get("source_cohort"), dict)
            or not isinstance(schedule.get("solver_problem_identity"), dict)
            or not isinstance(schedule.get("safe_exit_definition"), dict)
        ):
            raise CandidateContractError("bunch pulse schedule has incomplete frozen identities")
    after_state = schedule.get("after_state")
    if (
        not isinstance(after_state, dict)
        or after_state.get("accelerator_electrode_ids") != list(range(1, 10))
        or after_state.get("voltage_v") != 0.0
    ):
        raise CandidateContractError("accelerator pulse schedule has an invalid grounded state")
    return schedule



def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _vector(value: Any, count: int | None, label: str) -> list[float]:
    if not isinstance(value, list) or not value or (count is not None and len(value) != count):
        expected = f"{count} values" if count is not None else "at least one value"
        raise CandidateContractError(f"{label} must contain {expected}")
    return [_finite(item, label) for item in value]


def _accelerator_ring_voltages(
    accelerator: dict[str, Any], provider_geometry: dict[str, Any] | None,
) -> list[float]:
    """Bind the runtime ring vector to the active provider profile."""
    voltages = _vector(accelerator.get("ring_voltages_v"), None, "accelerator ring voltages")
    if provider_geometry is not None:
        ring_count = provider_geometry.get("ring_count")
        if type(ring_count) is not int or ring_count <= 0 or len(voltages) != ring_count:
            raise CandidateContractError(
                "provider accelerator ring voltages differ from its profile ring count"
            )
    return voltages


def _single_center_source_state(trial: dict[str, Any]) -> tuple[ProjectPhaseSpaceState, dict[str, Any]]:
    """Derive the actual N=1 release state from the frozen source authorities."""
    if trial.get("source_particle_count") != 1:
        raise CandidateContractError("single-center trial observation requires source_particle_count=1")
    position = _vector(trial.get("source_position_project_mm"), 3, "source position")
    direction = _vector(trial.get("source_direction_project"), 3, "source direction")
    direction_norm = math.sqrt(sum(value * value for value in direction))
    if direction_norm <= 0.0:
        raise CandidateContractError("source direction must be nonzero")
    direction = [value / direction_norm for value in direction]
    if direction != [0.0, 1.0, 0.0]:
        raise CandidateContractError(
            "single-center source direction must match the Fly2 +project-y release"
        )
    mass = _finite(trial.get("particle_mass_th"), "particle mass")
    charge = trial.get("charge_state")
    if mass <= 0.0 or not isinstance(charge, int) or isinstance(charge, bool) or charge == 0:
        raise CandidateContractError("source species requires positive mass and nonzero integer charge")
    energy_per_charge = _finite(
        trial.get("source_slow_kinetic_energy_per_charge_v"),
        "source slow kinetic energy per charge",
    )
    if energy_per_charge <= 0.0:
        raise CandidateContractError("source slow kinetic energy per charge must be positive")
    energy_ev = energy_per_charge * abs(charge)
    speed_m_s = math.sqrt(2.0 * energy_ev * ELEMENTARY_CHARGE_C / (mass * AMU_KG))
    velocity = tuple(value * speed_m_s / 1000.0 for value in direction)
    derived_energy_ev = kinetic_energy_ev(mass, *(value * 1000.0 for value in velocity))
    if not math.isclose(derived_energy_ev, energy_ev, rel_tol=1e-12, abs_tol=1e-12):
        raise CandidateContractError("derived source velocity does not preserve source kinetic energy")
    state = ProjectPhaseSpaceState(tuple(position), velocity)
    return state, _source_release_record(
        state, mass, charge,
        _finite(trial.get("source_time_of_birth_us"), "source time of birth"),
    )


def _source_release_record(
    state: ProjectPhaseSpaceState, mass: float, charge: int, time_us: float,
) -> dict[str, Any]:
    """Serialize one authoritative release state in the existing canonical units."""
    derived_energy_ev = kinetic_energy_ev(mass, *(value * 1000.0 for value in state.velocity_mm_per_us))
    return {
        "position_mm": list(state.position_mm),
        "velocity_mm_per_us": list(state.velocity_mm_per_us),
        "time_us": time_us,
        "particle_mass_th": mass,
        "charge_state": charge,
        "kinetic_energy_ev": derived_energy_ev,
        "kinetic_energy_per_charge_v": derived_energy_ev / abs(charge),
        "direction_project": list(state.unit_direction_project),
    }


def _bunch_center_source_state(trial: dict[str, Any]) -> ProjectPhaseSpaceState | None:
    """Read the existing frozen particle-1 source in mm and mm/us."""
    frozen = trial.get("source_center_state")
    if frozen is None:
        return None
    if not isinstance(frozen, dict) or frozen.get("particle_id") != 1:
        raise CandidateContractError("bunch centre state must be frozen particle 1")
    position = _vector(frozen.get("position_workbench_mm"), 3, "bunch centre position")
    direction = _vector(frozen.get("direction_workbench"), 3, "bunch centre direction")
    direction_norm = math.sqrt(sum(value * value for value in direction))
    mass = _finite(frozen.get("mass_th"), "bunch centre mass")
    energy = _finite(frozen.get("kinetic_energy_ev"), "bunch centre energy")
    charge = frozen.get("charge_e")
    if (
        direction_norm <= 0.0 or mass <= 0.0 or energy <= 0.0
        or not isinstance(charge, int) or isinstance(charge, bool) or charge == 0
    ):
        raise CandidateContractError("bunch centre state is not physical")
    direction = [value / direction_norm for value in direction]
    speed_m_s = math.sqrt(2.0 * energy * ELEMENTARY_CHARGE_C / (mass * AMU_KG))
    return ProjectPhaseSpaceState(
        tuple(position), tuple(value * speed_m_s / 1000.0 for value in direction),
    )


def _prism_handoff_event_prefix(events: list[dict[str, Any]], *, clean_phase: bool = False) -> list[dict[str, Any]]:
    """Keep the completed particle-1 injection segment, not downstream losses."""
    turns = [
        index for index, event in enumerate(events)
        if event.get("kind") == "pre_origin_positive_mirror_turn" and event.get("ion") == 1
    ]
    if len(turns) != 1:
        raise CandidateContractError("P1/P2 hand-off requires one first positive-mirror turn")
    if clean_phase:
        planes = [index for index, event in enumerate(events)
                  if event.get("ion") == 1 and event.get("kind") == "central_plane_directional"
                  and event.get("n") == 1 and event.get("direction_z") == -1]
        if len(planes) != 1 or planes[0] <= turns[0] or float(events[planes[0]]["t_us"]) <= float(events[turns[0]]["t_us"]):
            raise CandidateContractError("clean P handoff requires one ordered first central n1 -z event")
        return events[:planes[0]+1]
    return events[:turns[0] + 1]


def _static_consumed_analyzer_voltages(binding: dict[str, Any], requested: list[float],
                                      accelerator: list[float], *, pulse_requested: bool) -> list[float]:
    """Bind the record to the field actually consumed after the existing check."""
    validate_voltages(binding, requested, accelerator, pulse_requested=pulse_requested)
    return list(binding['authority']['analyzer_electrode_voltages_v'])


def clean_phase_effective_slow_action(*, state: dict[str, Any], mass_amu: float,
                                     charge_state: int, target: dict[str, Any],
                                     stripe_1_voltage_v: float) -> dict[str, float]:
    """Evaluate the frozen L0 slow-action model on a measured Cartesian state.

    Psi is the design effective potential, not the actual 3D scalar field.
    Spatial applicability and crossing identity remain the caller's checks.
    """
    velocity = _vector(state.get("velocity_mm_per_us"), 3, "clean velocity")
    position = _vector(state.get("position_mm"), 3, "clean position")
    mass, charge = _finite(mass_amu, "particle mass"), _finite(charge_state, "particle charge")
    if mass <= 0 or charge <= 0:
        raise CandidateContractError("clean action requires positive mass and charge")
    ky = 0.5*mass*AMU_KG*(velocity[1]*1000)**2/(ELEMENTARY_CHARGE_C*abs(charge))
    psi = converging_design_potential_delta_v(target, stripe_1_voltage_v, position[1])
    return dict(clean_phase_slow_energy_per_charge_v=ky, design_effective_potential_delta_v=psi,
                **{CONVERGING_PRISM_ENERGY_RESIDUAL: ky+psi-target["slow_energy_reference_per_charge_v"]})


def _converging_prism_energy_observation(events: list[dict[str, Any]], trial: dict[str, Any]) -> dict[str, Any]:
    """Measure reference slow energy at the first clean z=0 plane, not at a mirror turn."""
    target = trial.get("prism_handoff_target")
    if target is None:
        return {}
    prefix = _prism_handoff_event_prefix(events, clean_phase=True)
    event = prefix[-1]
    state = {"position_mm": [_finite(event.get(key), "clean position") for key in ("x_mm", "y_mm", "z_mm")],
             "velocity_mm_per_us": [_finite(event.get(key), "clean velocity") for key in ("vx_mm_us", "vy_mm_us", "vz_mm_us")],
             "t_us": _finite(event.get("t_us"), "clean time"), "event": "central_plane_directional__n1__minus_z"}
    y = state["position_mm"][1]
    vy, vz = state["velocity_mm_per_us"][1:]
    lo, hi = target["clean_y_interval_mm"]
    # The canonical central root assigns z_mm=0; this checks event identity,
    # not a new trajectory-integration tolerance.
    if not lo < y < hi or vy <= 0 or vz >= 0 or state["position_mm"][0] != 0 or state["position_mm"][2] != 0:
        raise CandidateContractError("first clean central phase is outside its vacuum/reference domain")
    mass, charge = _finite(trial.get("particle_mass_th"), "particle mass"), _finite(trial.get("charge_state"), "particle charge")
    source = trial.get("source_center_state")
    if (mass <= 0 or charge <= 0 or trial["stripe_biases_v"][1] != 0 or not isinstance(source, dict)
            or source.get("mass_th") != mass or source.get("charge_e") != charge):
        raise CandidateContractError("clean-phase energy requires valid mass/charge and grounded S2")
    if any(e.get("kind") in {"terminal", "splat"} and e.get("splat", e.get("code")) == -1 for e in prefix):
        raise CandidateContractError("clean phase follows an electrode collision")
    action = clean_phase_effective_slow_action(state=state, mass_amu=mass, charge_state=charge,
                                             target=target, stripe_1_voltage_v=trial["stripe_biases_v"][0])
    # Preserve the historical key for old centre receipts; the shared function
    # deliberately names the effective model term so new consumers cannot
    # confuse it with a measured physical scalar potential.
    return {"first_clean_phase_state": state,
            "clean_phase_slow_energy_per_charge_v": action["clean_phase_slow_energy_per_charge_v"],
            "design_potential_delta_v": action["design_effective_potential_delta_v"],
            CONVERGING_PRISM_ENERGY_RESIDUAL: action[CONVERGING_PRISM_ENERGY_RESIDUAL]}


def _measured_converging_prism_energy_observation(events: list[dict[str, Any]], trial: dict[str, Any]) -> dict[str, Any]:
    """Apply the same frozen L0 model to a declared measured 3D probe state."""
    target=trial.get("prism_handoff_target")
    if target is None:
        return {}
    if trial.get("source_projection") != "measured_exit_centroid" or trial["stripe_biases_v"][1] != 0:
        raise CandidateContractError("Measured clean action requires explicit centroid identity and grounded S2")
    prefix=_prism_handoff_event_prefix(events,clean_phase=True)
    event=prefix[-1]
    state=dict(position_mm=[_finite(event.get(f"{a}_mm"),"measured clean position") for a in "xyz"],
               velocity_mm_per_us=[_finite(event.get(f"v{a}_mm_us"),"measured clean velocity") for a in "xyz"],
               t_us=_finite(event.get("t_us"),"measured clean time"),event="central_plane_directional__n1__minus_z")
    lo,hi=target["clean_y_interval_mm"]
    if (not lo<state["position_mm"][1]<hi or state["position_mm"][2] != 0
            or state["velocity_mm_per_us"][1]<=0 or state["velocity_mm_per_us"][2]>=0):
        raise CandidateContractError("Measured clean phase is outside the declared L0 reference domain")
    if any(e.get("kind") in {"terminal","splat"} and e.get("splat",e.get("code")) == -1 for e in prefix):
        raise CandidateContractError("Measured clean action follows an electrode collision")
    action=clean_phase_effective_slow_action(state=state,mass_amu=trial["particle_mass_th"],charge_state=trial["charge_state"],
        target=target,stripe_1_voltage_v=trial["stripe_biases_v"][0])
    return dict(action,first_clean_phase_state=state,
                model_scope="Measured 3D state with original x/vx; frozen L0 design effective Psi, not physical 3D potential")


def _bunch_center_prism_handoff_validation(
    events: list[dict[str, Any]], trial: dict[str, Any], *, source_state: ProjectPhaseSpaceState | None = None,
) -> dict[str, Any]:
    """Publish the forward P segment without qualifying the full flight."""
    source = _bunch_center_source_state(trial) if source_state is None else source_state
    if source is None:
        return {"status": "not_available__legacy_source_receipt"}
    try:
        observation = observation_from_simion_events(
            _prism_handoff_event_prefix(events, clean_phase=trial.get("prism_handoff_target") is not None), source, ion_number=1,
        )
        residuals = dict(prism_handoff_residuals(
            observation,
            target_positive_mirror_turn_y_mm=float(trial["target_positive_mirror_turn_y_mm"]),
            target_tangent_ratio_vy_over_vz=float(
                trial["target_low_field_tangent_ratio_vy_over_vz"]
            ),
        ))
        energy_observation = (_converging_prism_energy_observation(events, trial) if source_state is None
                              else _measured_converging_prism_energy_observation(events, trial))
        if energy_observation:
            residuals[CONVERGING_PRISM_ENERGY_RESIDUAL] = energy_observation[CONVERGING_PRISM_ENERGY_RESIDUAL]
    except CandidateContractError as error:
        return {"status": "incomplete", "particle_id": 1, "reason": str(error)}
    reference = observation.p2_shield_low_field_reference
    actual_ratio = reference.velocity_mm_per_us[1] / reference.velocity_mm_per_us[2]
    target_ratio = float(trial["target_low_field_tangent_ratio_vy_over_vz"])
    return {
        "status": "observed", "particle_id": 1,
        "p2_low_field_reference_state": {
            "position_mm": reference.position_mm,
            "velocity_mm_per_us": reference.velocity_mm_per_us,
        },
        "positive_mirror_turn_state": {
            "position_mm": observation.positive_mirror_turn.position_mm,
            "velocity_mm_per_us": observation.positive_mirror_turn.velocity_mm_per_us,
        },
        "residuals": residuals,
        **energy_observation,
        "physical_acceptance_residuals": {
            **({CONVERGING_PRISM_ENERGY_RESIDUAL: residuals[CONVERGING_PRISM_ENERGY_RESIDUAL]} if energy_observation else {}),
            "P1_P2_positive_mirror_turn_y_mm": residuals["P1_P2_positive_mirror_turn_y_mm"],
            "P1_P2_P2_shield_low_field_angle_degrees": math.degrees(
                math.atan(actual_ratio) - math.atan(target_ratio)
            ),
        },
    }


def _bunch_center_workpoint_validation(
    events: list[dict[str, Any]], trial: dict[str, Any], *, source_state: ProjectPhaseSpaceState | None = None,
) -> dict[str, Any]:
    """Measure the four existing workpoint residuals on frozen particle 1."""
    source = _bunch_center_source_state(trial) if source_state is None else source_state
    if source is None:
        return {"status": "not_available__legacy_source_receipt"}
    try:
        observation = observation_from_simion_events(events, source, ion_number=1)
        residuals = dict(prism_handoff_residuals(
            observation,
            target_positive_mirror_turn_y_mm=float(trial["target_positive_mirror_turn_y_mm"]),
            target_tangent_ratio_vy_over_vz=float(
                trial["target_low_field_tangent_ratio_vy_over_vz"]
            ),
        ))
        energy_observation = (_converging_prism_energy_observation(events, trial) if source_state is None
                              else _measured_converging_prism_energy_observation(events, trial))
        if energy_observation:
            residuals[CONVERGING_PRISM_ENERGY_RESIDUAL] = energy_observation[CONVERGING_PRISM_ENERGY_RESIDUAL]
        target_ratio = _finite(
            trial["target_low_field_tangent_ratio_vy_over_vz"],
            "target low-field tangent ratio",
        )
        actual_ratio = (
            observation.p2_shield_low_field_reference.velocity_mm_per_us[1]
            / observation.p2_shield_low_field_reference.velocity_mm_per_us[2]
        )
        origins = [
            event for event in events
            if event.get("kind") == "drift_phase_origin" and event.get("ion") == 1
        ]
        if len(origins) != 1:
            raise CandidateContractError("bunch centre requires one drift phase origin")
        origin_time = _finite(origins[0].get("t_us"), "bunch centre phase-origin time")
        slow_turns = [
            event for event in events
            if event.get("kind") == "slow_turn" and event.get("ion") == 1
            and float(event["t_us"]) > origin_time
        ]
        target_k = _finite(trial.get("target_drift_period_ratio"), "target K")
        target_samples = [
            event for event in events
            if event.get("kind") == "target_k_phase_sample" and event.get("ion") == 1
            and float(event["t_us"]) > origin_time
            and float(event["k"]) == target_k
        ]
        if not slow_turns or len(target_samples) != 1:
            raise CandidateContractError(
                "bunch centre requires a slow turn and one exact target-K phase sample"
            )
        residuals.update({
            "Stripe_slow_turn_y_minus_L_mm": (
                _finite(slow_turns[0].get("y_mm"), "bunch centre slow-turn y")
                - _finite(trial.get("target_slow_turn_y_mm"), "target slow-turn y")
            ),
            "Stripe_target_phase_y_minus_origin_mm": (
                _finite(target_samples[0].get("y_mm"), "bunch centre target-phase y")
                - _finite(
                    trial.get("target_positive_mirror_turn_y_mm"),
                    "target phase-origin y",
                )
            ),
        })
    except CandidateContractError as error:
        return {"status": "incomplete", "reason": str(error)}
    return {
        "status": "observed",
        "particle_id": 1,
        "residuals": residuals,
        **energy_observation,
        "physical_acceptance_residuals": {
            **({CONVERGING_PRISM_ENERGY_RESIDUAL: residuals[CONVERGING_PRISM_ENERGY_RESIDUAL]} if energy_observation else {}),
            "P1_P2_positive_mirror_turn_y_mm": residuals[
                "P1_P2_positive_mirror_turn_y_mm"
            ],
            "P1_P2_P2_shield_low_field_angle_degrees": math.degrees(
                math.atan(actual_ratio) - math.atan(target_ratio)
            ),
            "Stripe_slow_turn_y_minus_L_mm": residuals[
                "Stripe_slow_turn_y_minus_L_mm"
            ],
            "Stripe_target_phase_y_minus_origin_mm": residuals[
                "Stripe_target_phase_y_minus_origin_mm"
            ],
        },
    }


def _first_slow_turn_signature(
    events: list[dict[str, Any]], slow: dict[str, Any],
) -> dict[str, Any]:
    """Locate a measured local zero within its observed fast half-cycle."""
    time = _finite(slow.get("t_us"), "first slow-turn time")
    turns = [event for event in events if event.get("ion") == slow.get("ion")
             and event.get("kind") == "fast_turn"]
    before = [event for event in turns if _finite(event.get("t_us"), "fast-turn time") < time]
    after = [event for event in turns if _finite(event.get("t_us"), "fast-turn time") > time]
    if not before or not after:
        return {"status": "unknown", "reason": "first slow turn lacks adjacent fast-turn states"}
    left, right = before[-1], after[0]
    numbers = [_finite(event.get("n"), "fast-turn number") for event in (left, right)]
    central = [event for event in events if event.get("ion") == slow.get("ion")
               and event.get("kind") == "central_plane_directional"
               and left["t_us"] < _finite(event.get("t_us"), "central-plane time") < right["t_us"]]
    if numbers[1] != numbers[0] + 1 or len(central) != 1:
        return {"status": "unknown", "reason": "first slow-turn half-cycle is not uniquely observed"}
    direction = _finite(central[0].get("direction_z"), "central-plane direction")
    velocities = [_finite(event.get("vy_mm_us"), "adjacent fast-turn vy") for event in (left, right)]
    if direction not in (-1, 1) or any(value == 0 for value in velocities):
        return {"status": "unknown", "reason": "first slow-turn adjacent direction is unavailable"}
    return {
        "status": "observed",
        "phase_key": {"fast_turn_numbers": numbers, "direction_z": direction,
                      "sampled_vy_signs": [1 if value > 0 else -1 for value in velocities]},
        "first_slow_turn": dict(slow),
        "adjacent_fast_turns": [dict(left), dict(right)],
        "central_plane": dict(central[0]),
    }


def _bunch_center_stripe_stage_validation(
    events: list[dict[str, Any]], trial: dict[str, Any], *, source_state: ProjectPhaseSpaceState | None = None,
) -> dict[str, Any]:
    """Measure completed origin/slow-turn/target-K events before downstream loss."""
    if source_state is None and _bunch_center_source_state(trial) is None:
        return {"status": "not_available__legacy_source_receipt"}
    try:
        centre = [event for event in events if event.get("ion") == 1]
        target_k = _finite(trial.get("target_drift_period_ratio"), "target K")
        targets = [event for event in centre if event.get("kind") == "target_k_phase_sample"]
        if len(targets) != 1 or _finite(targets[0].get("k"), "stage target K") != target_k:
            raise CandidateContractError("S stage requires one exact target-K sample")
        target = targets[0]
        target_time = _finite(target.get("t_us"), "stage target time")
        cutoff = events.index(target)
        prefix = events[:cutoff + 1]
        before = [event for event in centre
                  if _finite(event.get("t_us"), "stage event time") <= target_time]
        forbidden = {"terminal", "splat", "nonmirror_reversal", "post_return_mirror_turn",
                     "return_origin_mirror_turn", "return_p2_entry", "return_p2_pass",
                     "return_positive_mirror_turn", "return_p1_entry", "return_p1_pass",
                     "detector"}
        if any(event.get("kind") in forbidden for event in before):
            raise CandidateContractError("S stage terminated or entered an invalid branch before target-K")
        origins = [event for event in centre if event.get("kind") == "drift_phase_origin"]
        if len(origins) != 1:
            raise CandidateContractError("S stage requires one phase origin")
        origin=origins[0]
        slow_turns = [event for event in before if event.get("kind") == "slow_turn"
                      and _finite(event.get("t_us"), "stage slow-turn time")
                      > _finite(origin.get("t_us"), "stage origin time")]
        first_slow = ([event for event in before if event.get("kind") == "slow_turn" and event.get("n") == 1]
                      if source_state is None else slow_turns[:1])
        if len(first_slow) != 1:
            raise CandidateContractError("S stage requires one first post-origin slow turn")
        slow=first_slow[0]
        if not slow_turns or slow_turns[0] is not slow:
            raise CandidateContractError("S stage first slow-turn identity is inconsistent")
        if not (_finite(origin.get("t_us"), "stage origin time")
                < _finite(slow.get("t_us"), "stage slow-turn time") < target_time
                and events.index(origin) < events.index(slow) < cutoff):
            raise CandidateContractError("S stage origin/first slow turn/target-K are out of order")
        measured = _bunch_center_workpoint_validation(prefix, trial,source_state=source_state)
        return dict(measured, stage_only=True, full_workpoint_qualified=False,
                    first_slow_turn_signature=_first_slow_turn_signature(prefix, slow))
    except CandidateContractError as error:
        return {"status": "incomplete", "particle_id": 1, "reason": str(error),
                "stage_only": True, "full_workpoint_qualified": False}


def _accelerator_safe_exit_observation(
    events: list[dict[str, Any]], trial: dict[str, Any], *,
    log_path: Path, trial_receipt_path: Path, log_sha256: str | None = None,
) -> dict[str, Any]:
    """Publish one measured accelerator exit, failing closed on invalid state."""
    exits = [event for event in events if event["kind"] == "accelerator_safe_exit"]
    base: dict[str, Any] = {
        "event_count": len(exits),
        "input_log": {"path": str(log_path.resolve()), "sha256": log_sha256 or file_sha256(log_path).lower()},
        "trial_identity": {
            "path": str(trial_receipt_path.resolve()),
            "sha256": file_sha256(trial_receipt_path).lower(),
        },
    }
    if not exits:
        return {**base, "status": "not_observed", "state": None}
    errors: list[str] = []
    if len(exits) != 1:
        errors.append("accelerator_safe_exit_count_must_equal_one")
    event = exits[0]
    try:
        ion = int(event.get("ion"))
        time_us = _finite(event.get("t_us"), "accelerator safe-exit time")
        source_time_us = _finite(
            trial.get("source_time_of_birth_us"), "source time of birth"
        )
        from_instance = int(event.get("from_instance"))
        to_instance = int(event.get("to_instance"))
        position = _vector(
            [event.get(key) for key in ("x_mm", "y_mm", "z_mm")], 3,
            "accelerator safe-exit position",
        )
        velocity = _vector(
            [event.get(key) for key in ("vx_mm_us", "vy_mm_us", "vz_mm_us")], 3,
            "accelerator safe-exit velocity",
        )
        mass = _finite(trial.get("particle_mass_th"), "particle mass")
        charge = trial.get("charge_state")
        accelerator_instance = int(trial.get("accelerator_instance", 3))
        if accelerator_instance != 3:
            errors.append("accelerator_instance_is_invalid")
        if ion != 1:
            errors.append("accelerator_safe_exit_must_belong_to_ion_one")
        if time_us < 0.0:
            errors.append("accelerator_safe_exit_time_must_be_nonnegative")
        if time_us < source_time_us:
            errors.append("accelerator_safe_exit_cannot_precede_source_release")
        if from_instance != accelerator_instance or to_instance == accelerator_instance:
            errors.append("accelerator_safe_exit_instance_transition_is_invalid")
        if velocity[2] >= 0.0:
            errors.append("accelerator_safe_exit_must_travel_toward_negative_project_z")
        if mass <= 0.0 or not isinstance(charge, int) or isinstance(charge, bool) or charge == 0:
            errors.append("accelerator_safe_exit_species_is_invalid")
    except (CandidateContractError, TypeError, ValueError) as error:
        errors.append(str(error))
        position = velocity = []
        time_us = 0.0
        mass = 0.0
        charge = 0
        from_instance = to_instance = 0
    exit_index = next(
        (index for index, candidate in enumerate(events) if candidate is event), -1
    )
    p1_entries = [
        (index, candidate) for index, candidate in enumerate(events)
        if candidate["kind"] == "prism_entry" and candidate.get("n") == 1
    ]
    p1_passes = [
        (index, candidate) for index, candidate in enumerate(events)
        if candidate["kind"] == "prism_pass" and candidate.get("n") == 1
    ]
    if len(p1_entries) > 1:
        errors.append("first_prism_entry_count_exceeds_one")
    elif p1_entries:
        try:
            p1_index, p1_entry = p1_entries[0]
            if (
                p1_index <= exit_index
                or _finite(p1_entry.get("t_us"), "P1 entry time") <= time_us
            ):
                errors.append("accelerator_safe_exit_does_not_precede_P1")
        except CandidateContractError as error:
            errors.append(str(error))
    elif len(p1_passes) > 1:
        errors.append("first_prism_pass_count_exceeds_one")
    elif p1_passes:
        try:
            p1_index, p1_pass = p1_passes[0]
            if (
                p1_index <= exit_index
                or _finite(p1_pass.get("t_us"), "P1 pass time") <= time_us
            ):
                errors.append("accelerator_safe_exit_does_not_precede_P1_pass")
        except CandidateContractError as error:
            errors.append(str(error))
    signed_bias = None
    reference = trial.get("source_transverse_reference")
    exit_contract = trial.get("accelerator_exit_energy_contract")
    if isinstance(reference, dict) and isinstance(exit_contract, dict):
        try:
            tolerance = _finite(
                exit_contract.get("maximum_exit_transverse_velocity_bias_mm_per_us"),
                "accelerator exit transverse-velocity bias tolerance",
            )
            delta_x = position[0] - _finite(reference.get("center_x_mm"), "source center x")
            delta_vx = velocity[0] - _finite(
                reference.get("center_vx_mm_per_us"), "source center vx",
            )
            passed = abs(delta_vx) <= tolerance
            signed_bias = {
                "comparison": "source_to_accelerator_safe_exit",
                "center_delta_x_mm": delta_x,
                "center_delta_vx_mm_per_us": delta_vx,
                "maximum_absolute_velocity_bias_mm_per_us": tolerance,
                "passed": passed,
            }
            if not passed:
                errors.append("accelerator_safe_exit_transverse_velocity_bias_exceeds_provider_tolerance")
        except (CandidateContractError, IndexError) as error:
            errors.append(str(error))
    if errors:
        return {
            **base, "status": "invalid", "state": None, "errors": errors,
            "signed_transverse_bias": signed_bias,
        }
    return {
        **base,
        "status": "observed",
        "state": {
            "ion": 1,
            "time_us": time_us,
            "position_mm": position,
            "velocity_mm_per_us": velocity,
            "particle_mass_th": mass,
            "charge_state": charge,
            "kinetic_energy_ev": kinetic_energy_ev(
                mass, *(value * 1000.0 for value in velocity)
            ),
            "from_instance": from_instance,
            "to_instance": to_instance,
        },
        "signed_transverse_bias": signed_bias,
        "p1_ordering": (
            "verified_safe_exit_before_P1_entry"
            if p1_entries
            else (
                "before_P1_pass_only__P1_entry_not_observed"
                if p1_passes else "P1_entry_and_pass_not_observed"
            )
        ),
    }


_STATIC_RETURN_KINDS = (
    "drift_phase_return",
    "return_p2_entry",
    "return_p2_pass",
    "return_positive_mirror_turn",
    "detector",
)


def _termination_diagnostic(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate physical electrode contact from project-requested SIMION stops."""
    splats = [event for event in events if event["kind"] == "splat"]
    terminals = [event for event in events if event["kind"] == "terminal"]
    if len(splats) != 1 or len(terminals) != 1:
        return {
            "status": "ambiguous",
            "physical_collision": None,
            "splat_count": len(splats),
            "terminal_count": len(terminals),
        }
    code = int(splats[0]["code"])
    kinds = {
        -1: "physical_electrode_collision",
        1: "programmatic_detector_completion",
        2: "programmatic_timeout",
        4: "programmatic_topology_rejection",
        5: "programmatic_diagnostic_stop",
    }
    kind = kinds.get(code, "unclassified_solver_termination")
    diagnostic: dict[str, Any] = {
        "status": "observed",
        "kind": kind,
        "code": code,
        "physical_collision": code == -1,
        "event": splats[0],
    }
    if code == 4:
        diagnostic["explicit_semantics"] = (
            splats[0].get("termination_kind") == kind
            and splats[0].get("physical_collision") == 0
        )
        diagnostic["reason"] = splats[0].get("reason")
    return diagnostic


def _static_return_diagnostic(
    events: list[dict[str, Any]], target_k: float,
) -> dict[str, Any]:
    """Validate the unique P2-to-positive-mirror static return event chain."""
    selected = {kind: [event for event in events if event["kind"] == kind]
                for kind in _STATIC_RETURN_KINDS}
    errors: list[str] = []
    if any(event["kind"] == "prism_voltage_switch" for event in events):
        errors.append("prism_voltage_switch_forbidden")
    if any(event["kind"] in {"return_p1_entry", "return_p1_pass"} for event in events):
        errors.append("return_p1_forbidden__p1_is_injection_only")
    if any(event["kind"] == "nonmirror_reversal" for event in events):
        errors.append("nonmirror_vz_reversal_observed")
    for kind, matches in selected.items():
        if len(matches) != 1:
            errors.append(f"{kind}_count_must_equal_one")
    if all(len(selected[kind]) == 1 for kind in _STATIC_RETURN_KINDS):
        times = [float(selected[kind][0]["t_us"]) for kind in _STATIC_RETURN_KINDS]
        if any(later <= earlier for earlier, later in zip(times, times[1:])):
            errors.append("static_return_events_out_of_order")
        if float(selected["return_p2_entry"][0].get("vz_mm_us", 0.0)) <= 0.0:
            errors.append("return_p2_entry_must_travel_positive_z")
        if float(selected["return_p2_pass"][0].get("vz_mm_us", 0.0)) <= 0.0:
            errors.append("return_p2_pass_must_travel_positive_z")
        positive_turn = selected["return_positive_mirror_turn"][0]
        if (float(positive_turn.get("z_mm", 0.0)) <= 0.0
                or abs(float(positive_turn.get("vz_mm_us", math.inf))) > 1.0e-12):
            errors.append("return_positive_mirror_turn_must_be_positive_z_vz_zero")
        detector = selected["detector"][0]
        if int(detector.get("direction_z", 0)) != -1:
            errors.append("static_detector_hit_must_travel_negative_z")
        if float(detector.get("z_mm", 0.0)) <= 0.0:
            errors.append("static_detector_hit_must_be_in_positive_z_half_space")
    safe_exits = [event for event in events if event["kind"] == "accelerator_safe_exit"]
    inferred_reentry = False
    if len(safe_exits) == 1:
        safe_exit = safe_exits[0]
        accelerator_instance = int(safe_exit["from_instance"])
        inferred_reentry = any(
            event["kind"] == "instance_transition"
            and float(event["t_us"]) > float(safe_exit["t_us"])
            and int(event["instance"]) == accelerator_instance
            for event in events
        )
    if any(event["kind"] == "accelerator_reentry" for event in events) or inferred_reentry:
        errors.append("accelerator_reentry_after_safe_exit_forbidden")
    if any(event["kind"] == "post_return_mirror_turn" for event in events):
        errors.append("legacy_post_return_mirror_turn_forbidden")
    terminals = [event for event in events if event["kind"] == "terminal"]
    splats = [event for event in events if event["kind"] == "splat"]
    if len(terminals) != 1 or int(terminals[0].get("splat", 0)) != 1:
        errors.append("detector_terminal_must_be_unique_splat_one")
    if len(splats) != 1 or int(splats[0].get("code", 0)) != 1:
        errors.append("detector_splat_must_be_unique_code_one")
    event_contract_ok = not errors
    detector_observed = len(selected["detector"]) == 1
    result: dict[str, Any] = {
        "status": "detector_hit" if event_contract_ok else (
            "invalid_static_return" if detector_observed else "detector_not_observed"
        ),
        "event_contract_ok": event_contract_ok,
        "required_event_order": list(_STATIC_RETURN_KINDS),
        "event_counts": {kind: len(matches) for kind, matches in selected.items()},
        "errors": errors,
        "termination": _termination_diagnostic(events),
    }
    if detector_observed:
        result["first_detector_event"] = selected["detector"][0]
    if len(selected["drift_phase_return"]) == 1:
        phase_return = selected["drift_phase_return"][0]
        result["fractional_k"] = phase_return.get("k", phase_return.get("fractional_k"))
        result["fractional_k_minus_target"] = (
            float(result["fractional_k"]) - target_k
            if result["fractional_k"] is not None else None
        )
    return result


def _mirror_regions(resolved: dict[str, Any]) -> dict[str, list[float]]:
    """Project mirror z regions from the already resolved geometry."""
    boxes = [
        item["box"]
        for key in ("mirror_ground_shields", "mirror_electrodes", "mirror_e_closures")
        for item in resolved[key]
    ]
    return {
        "negative": [min(box[2] for box in boxes if box[5] < 0), max(box[5] for box in boxes if box[5] < 0)],
        "positive": [min(box[2] for box in boxes if box[2] > 0), max(box[5] for box in boxes if box[2] > 0)],
    }




def _seed_theory_provenance(
    seed_mirror_voltages_v: tuple[float, ...], seed_stripe_biases_v: tuple[float, ...],
    mirror_voltages_v: list[float], stripe_biases_v: list[float],
) -> dict[str, Any]:
    """Separate initializer lineage from the actual trial's theory qualification."""
    mirror_changed = tuple(mirror_voltages_v) != seed_mirror_voltages_v
    stripe_changed = tuple(stripe_biases_v) != seed_stripe_biases_v
    return {
        "seed_authority_scope": "historical_mirror_stripe_initializer_only",
        "seed_mirror_voltages_v": list(seed_mirror_voltages_v),
        "seed_stripe_biases_v": list(seed_stripe_biases_v),
        "mirror_changed_from_seed": mirror_changed,
        "stripe_changed_from_seed": stripe_changed,
        "actual_theory_qualification": (
            "not_rederived_after_mirror_or_stripe_change"
            if mirror_changed or stripe_changed else
            "seed_initializer_theory_only__finite_3d_and_numerical_qualification_pending"
        ),
    }


def _static_field_receipt(binding: dict[str, Any], path: Path) -> dict[str, Any]:
    """Record the resolved field representation and assets without relabeling its solver."""
    result = {
        "path": str(path.resolve()),
        "mode": binding.get("mode", "comsol_static_scalar_v"),
        "sources": binding["sources"], "records": binding["records"],
        "grid": binding["grid"],
        "refinement_windows": binding.get("refinement_windows", []),
        "gui_field_queries_equivalent": False,
        "representation": binding.get("representation", "single_scalar_v"),
        "response_terms": binding.get("response_terms", []),
        "event_ion_volts_meaning": "collision_array_label_or_interpolation__not_electric_potential",
    }
    if binding.get("mode") == "native_static_pa":
        result["manifest"] = binding["manifest"]
        result["native_solver_numerics"] = copy.deepcopy(binding["native_solver_numerics"])
    if "response_terms" in binding:
        result["response_weight_l1_norm"] = binding["response_weight_l1_norm"]
    return result



def native_corridor_priority_lua(cache_manifest: dict[str, Any] | None) -> str:
    """Render the existing role contract using only this frozen bank's channels."""
    groups = ""
    if cache_manifest is not None:
        try:
            recipes = cache_manifest["identity"]["basis_namespace"]["response_recipe"]["response_recipes"]
        except (KeyError, TypeError) as exc:
            raise CandidateContractError("native bank manifest has no response recipes") from exc
        if not isinstance(recipes, list) or len(recipes) != 8:
            raise CandidateContractError("native bank must declare eight response recipes")
        by_id, used = {}, set()
        for entry in recipes:
            if not isinstance(entry, dict):
                raise CandidateContractError("native bank response recipe must be an object")
            local_id, physical = entry.get("local_id"), entry.get("physical_ids")
            if (type(local_id) is not int or not 1 <= local_id <= 8 or local_id in by_id
                    or not isinstance(physical, list) or not physical
                    or any(type(value) is not int or not 1 <= value <= 20 for value in physical)
                    or len(set(physical)) != len(physical) or used.intersection(physical)):
                raise CandidateContractError("native bank response local IDs or physical groups are invalid or ambiguous")
            by_id[local_id] = physical
            used.update(physical)
        groups = "  corridor_voltage_groups = { " + ", ".join(_lua_vector(by_id[index]) for index in range(1, 9)) + " },\n"
    return (
        "-- Generated run-local Workbench priority contract; do not edit.\n"
        "return {\n  schema_version = 1,\n"
        "  role = 'mrtof_native_corridor_iob_priority_contract',\n"
        "  priority_rule = 'slot_order_is_only_a_build_contract; persisted_priority_is_accepted_only_after_wb_find_at_overlap_probes',\n"
        "  api_note = 'SIMION 2020 has no documented instance.priority setter in the supported Lua API; builder probes candidate fields and otherwise verifies actual winners with wb.find_at',\n"
        "  instances = {\n"
        "    { role = 'global_fallback', priority_number = 1 },\n"
        "    { role = 'native_corridor', priority_number = 2 },\n"
        "    { role = 'accelerator', priority_number = 3 },\n"
        "    { role = 'detector', priority_number = 4 },\n"
        "  },\n" + groups + "}\n"
    )


def materialize_trial(
    *,
    contract_path: Path,
    accelerator_geometry_contract_path: Path,
    trajectory_contract_path: Path,
    reviewed_contract_path: Path,
    mirror_summary_path: Path,
    stripe_summary_path: Path,
    fixed_mirror_stripe_authority_path: Path | None,
    mirror_voltage_variation_path: Path | None = None,
    accelerator_receipt_path: Path,
    prism_1_v: float,
    prism_2_v: float,
    stripe_biases_override_v: tuple[float, float] | None,
    runtime_fast_adjust_enable: bool,
    pulse_accelerator_until_initial_exit: bool,
    accelerator_safe_exit_only: bool,
    accelerator_pulse_schedule_path: Path | None,
    trajectory_profile_id: str | None,
    fly2_path: Path,
    sidecar_path: Path,
    receipt_path: Path,
    bunch_source_receipt_path: Path | None = None,
    bunch_particle_id_min: int | None = None,
    bunch_particle_id_max: int | None = None,
    batch_scientific_event_locators: bool = False,
    accelerator_instance: int = 3,
    trajectory_step_scale: float = 1.0,
    source_y_offset_mm: float = 0.0,
    accelerator_provider_plan_path: Path,
    composition_plan_path: Path,
    local_scope_path: Path | None = None,
    accelerator_resolved_campaign_path: Path | None = None,
    field_binding_path: Path | None = None,
    native_corridor_cache_manifest_path: Path | None = None,
) -> dict[str, Any]:
    if accelerator_instance != 3:
        raise CandidateContractError("workbench accelerator instance must be 3")
    trajectory_contract = load_contract(trajectory_contract_path)
    detector_return_policy = trajectory_contract["accelerator"]["detector_return_path"]
    mirror_supply_limits = mirror_power_supply_limits(trajectory_contract)
    contract = load_contract(
        contract_path, inherited_detector_return_path=detector_return_policy,
        inherited_mirror_power_supply_limits_v=mirror_supply_limits,
    )
    accelerator_geometry_contract = load_contract(
        accelerator_geometry_contract_path,
        inherited_detector_return_path=detector_return_policy,
        inherited_mirror_power_supply_limits_v=mirror_supply_limits,
    )
    reviewed_contract = load_contract(
        reviewed_contract_path, inherited_detector_return_path=detector_return_policy,
        inherited_mirror_power_supply_limits_v=mirror_supply_limits,
    )
    mirror = _load(mirror_summary_path)
    stripe = _load(stripe_summary_path)
    accelerator = _load(accelerator_receipt_path)
    provider_plan = _load(accelerator_provider_plan_path)
    composition_plan = _load(composition_plan_path)
    local_scope = _load(local_scope_path) if local_scope_path is not None else None
    direct_pose = resolve_oa_mr_direct_pose(provider_plan, composition_plan, local_scope=local_scope)
    provider_geometry: dict[str, Any] | None = None
    provider_exit_energy_contract: dict[str, Any] | None = None
    if accelerator.get("role") == "orthogonal_accelerator_mrtof_runtime_receipt":
        if accelerator.get("status") != "published_standalone_response_bank":
            raise CandidateContractError("provider accelerator receipt lacks its published standalone response bank")
        projection = accelerator.get("mrtof_projection")
        if not isinstance(projection, dict):
            raise CandidateContractError("provider accelerator receipt lacks its MR projection")
        provider_geometry = projection.get("geometry")
        if not isinstance(provider_geometry, dict):
            raise CandidateContractError("provider accelerator receipt lacks its geometry projection")
        provider_exit_energy_contract = _provider_exit_energy_contract(projection)
        accelerator = projection
    fixed_authority = (
        _load(fixed_mirror_stripe_authority_path)
        if fixed_mirror_stripe_authority_path is not None else None
    )
    if fixed_authority is not None:
        seed, slow_energy, energy, mirror_voltages, authority_target_k = (
            _fixed_mirror_stripe_source_state(
                fixed_authority, mirror, stripe, contract,
            )
        )
    else:
        if mirror.get("status") not in {"success", "exact_k_operating_point_selected"}:
            # Current exact-K summary uses a richer role-specific status.  Require
            # the selected point below instead of accepting arbitrary summaries.
            if not isinstance(mirror.get("selected_operating_point"), dict):
                raise CandidateContractError("mirror summary has no selected exact-K operating point")
        selected_mirror = mirror.get("selected_operating_point")
        selected_stripe = stripe.get("selected_exact_k_operating_point")
        if not all(isinstance(value, dict) for value in (selected_mirror, selected_stripe)):
            raise CandidateContractError("mirror/Stripe summaries do not expose the selected exact-K point")
        energy = _finite(selected_mirror.get("energy_per_charge_v"), "mirror selected energy")
        seed, slow_energy = _schema5_native_source_state(stripe, contract, energy)
        if abs(
            _finite(selected_stripe.get("axial_energy_per_charge_v"), "Stripe selected energy")
            - energy
        ) > 1e-9:
            raise CandidateContractError("mirror and Stripe selected energies differ")
        mirror_voltages = _vector(
            selected_mirror.get("mirror_voltages_v"), 5, "mirror voltages",
        )
        authority_target_k = None
    seed_mirror_voltages = tuple(mirror_voltages)
    mirror_voltages, mirror_variation = _apply_terminal_mirror_variation(
        variation=(
            _load(mirror_voltage_variation_path)
            if mirror_voltage_variation_path is not None else None
        ),
        base_voltages=mirror_voltages,
        contract=contract,
        axial_energy_v=energy,
    )
    target_turn_y, target_angle_degrees, target_tangent_ratio = (
        _p2_handoff_targets(seed, contract)
    )
    accelerator_energy = _accelerator_energy_binding(accelerator, energy)
    if (
        provider_exit_energy_contract is not None
        and abs(
            float(provider_exit_energy_contract["targets_per_charge_v"]["Ey"])
            - slow_energy
        ) > 1e-9
    ):
        raise CandidateContractError(
            "provider target slow energy and trial release slow energy differ"
        )
    field_binding = load_binding(field_binding_path) if field_binding_path is not None else None
    if field_binding is None and native_corridor_cache_manifest_path is None:
        raise CandidateContractError("native flight requires an explicit frozen native corridor cache manifest")
    if field_binding is not None and native_corridor_cache_manifest_path is not None:
        raise CandidateContractError("static field must not declare an unused native corridor cache manifest")
    priority_lua = native_corridor_priority_lua(
        _load(native_corridor_cache_manifest_path) if native_corridor_cache_manifest_path is not None else None)
    stripe_biases = _vector(seed.get("stripe_biases_v"), 2, "Stripe biases")
    seed_stripe_biases = tuple(stripe_biases)
    if stripe_biases_override_v is None and field_binding is not None:
        # A solved field owns its operating voltages; the historical seed only
        # initializes adjustable flights, not static-field clean-phase checks.
        scale = _finite(contract["simion"]["nonaccelerator_scale"], "nonaccelerator scale")
        values = field_binding["authority"]["analyzer_electrode_voltages_v"]
        stripe_biases = [float(values[10]) / scale, float(values[12]) / scale]
    elif stripe_biases_override_v is not None:
        stripe_biases = [
            _finite(stripe_biases_override_v[0], "Stripe 1 override"),
            _finite(stripe_biases_override_v[1], "Stripe 2 override"),
        ]
    endpoint_voltages = _vector(accelerator.get("endpoint_voltages_v"), 3, "accelerator endpoint voltages")
    ring_voltages = _accelerator_ring_voltages(accelerator, provider_geometry)
    p1 = _finite(prism_1_v, "P1 voltage")
    p2 = _finite(prism_2_v, "P2 voltage")
    phase_contract = resolve_drift_phase_contract(contract)
    target_k = phase_contract.target_period_ratio
    if authority_target_k is not None and not math.isclose(
        authority_target_k, target_k, rel_tol=0.0, abs_tol=1e-12,
    ):
        raise CandidateContractError("fixed mirror/Stripe authority target K differs from the contract")
    pulse_schedule = _load_frozen_accelerator_pulse_schedule(
        accelerator_pulse_schedule_path
    )
    if pulse_accelerator_until_initial_exit and pulse_schedule is not None:
        raise CandidateContractError(
            "event-triggered and fixed-time accelerator pulse modes are mutually exclusive"
        )
    fixed_pulse_off_time = (
        _finite(pulse_schedule["pulse_off_time_us"], "accelerator pulse-off time")
        if pulse_schedule is not None else None
    )
    accelerator_pulse_requested = (
        pulse_accelerator_until_initial_exit or fixed_pulse_off_time is not None
    )
    source_contract = contract["particle_source"]
    species = source_contract["species"]
    bunch_source = (
        load_verified_bunch_source_receipt(bunch_source_receipt_path)
        if bunch_source_receipt_path is not None else None
    )
    if (bunch_particle_id_min is None) != (bunch_particle_id_max is None):
        raise CandidateContractError("bunch particle interval endpoints must be supplied together")
    bunch_selection = None
    if bunch_particle_id_min is not None:
        if bunch_source_receipt_path is None:
            raise CandidateContractError("bunch particle selection requires a frozen source receipt")
        if bunch_particle_id_max < bunch_particle_id_min:
            raise CandidateContractError(
                "managed bunch diagnostics require one or more contiguous particles"
            )
        if pulse_accelerator_until_initial_exit:
            raise CandidateContractError(
                "frozen source interval diagnostics forbid per-particle exit-triggered pulsing"
            )
        bunch_selection = resolve_bunch_source_interval(
            receipt_path=bunch_source_receipt_path,
            particle_id_min=bunch_particle_id_min,
            particle_id_max=bunch_particle_id_max,
        )
    if bunch_source is not None and pulse_accelerator_until_initial_exit:
        raise CandidateContractError(
            "N>1 bunch flights forbid initial_exit_triggered_single_center"
        )
    if bunch_source is not None and abs(
        _finite(bunch_source.get("common_time_of_birth_us"), "bunch common birth time")
    ) > 1.0e-15:
        raise CandidateContractError("MR-TOF batch dispatch requires common tob=0")
    selected_species = bunch_source["species"] if bunch_source is not None else species
    mass = _finite(selected_species.get("mass_th"), "particle mass")
    charge = int(selected_species.get("charge_e"))
    if (
        abs(mass - _finite(species.get("mass_th"), "contract particle mass")) > 1e-12
        or charge != int(species.get("charge_e"))
    ):
        raise CandidateContractError("bunch source species differs from the MR-TOF contract")
    if mass <= 0 or charge == 0 or slow_energy <= 0:
        raise CandidateContractError("P1/P2 source mass, charge, and slow energy must be physical")
    if provider_geometry is None or provider_geometry.get("acceleration_direction") != "-z":
        raise CandidateContractError("provider accelerator must publish negative-z geometry")
    release = _finite(provider_geometry.get("release_position_in_gap_1_mm"), "provider accelerator release")
    repeller_to_exit = _finite(provider_geometry.get("repeller_to_exit_mm"), "provider repeller-to-exit distance")
    aperture_height_y = _finite(provider_geometry.get("aperture_height_y_mm"), "provider accelerator aperture height y")
    source_y_offset = _finite(source_y_offset_mm, "accelerator source y offset")
    aperture_half_y = aperture_height_y / 2.0
    if abs(source_y_offset) >= aperture_half_y:
        raise CandidateContractError("accelerator source y offset must remain inside its aperture")
    if bunch_source is not None and source_y_offset != 0.0:
        raise CandidateContractError("a frozen bunch source already owns its centre; do not apply a second y offset")
    exit_project = direct_pose["exit_project_mm"]
    release_from_exit_z = repeller_to_exit - release
    source_origin_project = (
        float(exit_project[0]), float(exit_project[1]) + source_y_offset,
        float(exit_project[2]) + release_from_exit_z,
    )
    center_fly2 = _single_center_source_fly2(
        mass_th=mass, charge_state=charge,
        source_slow_energy_per_charge_v=slow_energy,
        focus_y_mm=source_origin_project[1], release_z_mm=source_origin_project[2],
    )
    fly2 = (
        bunch_selection["fly2"] if bunch_selection is not None
        else Path(bunch_source["fly2"]["path"]).read_text(encoding="utf-8")
        if bunch_source is not None else center_fly2
    )
    if pulse_schedule is not None and pulse_schedule["schema_version"] == 1:
        if bunch_source is not None:
            raise CandidateContractError(
                "N>1 bunch flights require a schema-2 fixed-global-time schedule"
            )
        source_identity = pulse_schedule["source"]
        generated_fly2_sha256 = hashlib.sha256(fly2.encode("utf-8")).hexdigest()
        if generated_fly2_sha256.lower() != source_identity["source_fly2_sha256"].lower():
            raise CandidateContractError(
                "accelerator pulse schedule was derived from a different particle source"
            )
        if file_sha256(accelerator_receipt_path).lower() != source_identity[
            "accelerator_receipt_sha256"
        ].lower():
            raise CandidateContractError(
                "accelerator pulse schedule was derived from a different accelerator voltage state"
            )
    resolved = _resolve_trial_geometry(
        reviewed_contract,
        # The accelerator voltage trial is an independently versioned voltage
        # receipt and may predate a project-level observation surface.  Bind
        # non-geometric topology/diagnostic authority from the current frozen
        # trajectory contract, as the IOB pose resolver does, while retaining
        # the reviewed contract as the sole physical geometry source.
        trajectory_contract,
        accelerator_geometry_contract,
        accelerator_assembly=(field_binding["authority"].get("assembly") if field_binding is not None else None),
    )
    actual_oa_origin = None
    resolved_iob_pose = None
    if field_binding is not None:
        if field_binding.get("consumer_view"):
            _validate_center_view_source(bunch_source, bunch_selection)
        if provider_plan is None:
            raise CandidateContractError("static field binding requires the frozen OA provider pose")
        # Solved geometry owns static placement and the corresponding clearance checks.
        resolved.update(copy.deepcopy(field_binding["geometry"]))
        actual_oa_origin = resolve_accelerator_iob_origin(
            contract, provider_plan, composition_plan, local_scope=local_scope, direct_pose=direct_pose, resolved_geometry=resolved,
        )
        if list(actual_oa_origin) != field_binding["instances"][2]["origin_mm"]:
            raise CandidateContractError("requested OA placement differs from the static field")
    if provider_plan is not None:
        if field_binding is not None:
            origins = {name: list(field_binding["instances"][index]["origin_mm"])
                       for name, index in (("analyzer", 0), ("accelerator", 2), ("detector", 3))}
            analyzer_authority = field_binding["mode"] + "_frozen_resolved_geometry"
        else:
            # These are distinct authorities: trial geometry uses the accelerator
            # geometry contract; the saved detector uses the active trajectory pose.
            iob_geometry = resolved
            if any(accelerator_geometry_contract["accelerator"][key] != trajectory_contract["accelerator"][key]
                   for key in ("component_source_cylinder", "focus_y_anchor")):
                iob_geometry = _resolve_trial_geometry(reviewed_contract, trajectory_contract, trajectory_contract)
            origins = resolve_static_iob_origins(reviewed_contract, resolved_geometry=iob_geometry)
            actual_oa_origin = resolve_accelerator_iob_origin(
                contract, provider_plan, composition_plan, local_scope=local_scope, direct_pose=direct_pose,
                resolved_geometry=(resolved if contract == reviewed_contract == accelerator_geometry_contract == trajectory_contract else None),
            )
            origins["accelerator"] = (actual_oa_origin if contract == trajectory_contract else
                                     resolve_accelerator_iob_origin(trajectory_contract, provider_plan, composition_plan, local_scope=local_scope, direct_pose=direct_pose))
            analyzer_authority = "reviewed_analyzer_contract"
        resolved_iob_pose = {
            "origins_mm": {key: list(value) for key, value in origins.items()},
            "mesh_mm_per_gu": {
                "analyzer": trajectory_contract["simion"]["component_mesh_mm_per_gu"]["analyzer"],
                "accelerator": provider_plan["numerical_domain"]["mesh_mm_per_gu"],
                "detector": trajectory_contract["simion"]["component_mesh_mm_per_gu"]["detector"],
            },
            "analyzer_geometry_authority": analyzer_authority,
            "accelerator_geometry_authority": "oa_provider_plan__mr_configurable_clearance_gated_y_pose",
            "detector_return_policy_authority": "current_trajectory_contract",
        }
    detector = resolved["detector"]
    prism_target = resolve_converging_prism_target(trajectory_contract, resolved)
    if prism_target is not None and (field_binding is None or stripe_biases[1] != 0.0):
        raise CandidateContractError("clean-phase Prism target requires a frozen static field and grounded S2")
    low_field_reference = resolved["two_prism_low_field_reference_section"]
    if low_field_reference.get("qualification") != "candidate_reference_section__not_a_zero_field_claim":
        raise CandidateContractError("resolved P2 reference plane has an invalid qualification")
    low_field_aperture = low_field_reference.get("transit_aperture_project_mm")
    if not isinstance(low_field_aperture, dict):
        raise CandidateContractError("resolved P2 reference plane lacks its transit aperture")
    regions = _mirror_regions(resolved)
    prism_regions: dict[str, list[float]] = {}
    shields_by_station = {
        item["station"]: item for item in reviewed_contract["prisms"]["ground_shields"]
    }
    for index, electrode in enumerate(reviewed_contract["prisms"]["electrodes"], 1):
        # Use the CAD-derived triangular clearance envelope rather than the
        # complete grounded-shield envelope.  The latter extends to the mirror
        # and would falsely place the P2 pass after the low-field reference.
        shield = shields_by_station[electrode["station"]]
        points = [
            (float(point[0]), float(point[1]))
            for point in shield["prism_clearance_polygon_yz_mm"]
        ]
        prism_regions[f"p{index}"] = [
            min(point[0] for point in points), max(point[0] for point in points),
            min(point[1] for point in points), max(point[1] for point in points),
        ]
    simion = contract["simion"]
    trajectory_profile = resolve_trajectory_profile(
        trajectory_contract, trajectory_profile_id,
    )
    trajectory_profile = _apply_trajectory_step_scale(
        trajectory_profile, trajectory_step_scale,
    )
    trajectory_recording = resolve_trajectory_recording(trajectory_contract)
    timeout = _full_path_timeout_us(contract, source_contract, target_k)
    p1_plane = _finite(contract["prism_transport"]["first_prism"]["target_interface"]["coordinate_mm"], "P1 plane")
    p1_acceptance = contract["prisms"]["ground_shields"][0]["rectangular_slots_mm"][0]["box"][1:5:3]
    accelerator_pulse_mode = "static"
    if pulse_accelerator_until_initial_exit:
        accelerator_pulse_mode = "initial_exit_triggered_single_center"
    elif fixed_pulse_off_time is not None:
        accelerator_pulse_mode = "fixed_global_time"
    accelerator_pulse_time_lua = (
        f"accelerator_pulse_off_time_us = {fixed_pulse_off_time:.17g}, "
        if fixed_pulse_off_time is not None else ""
    )
    if accelerator_resolved_campaign_path is None:
        raise CandidateContractError(
            "accelerator provider plan and resolved campaign must be supplied together"
        )
    accelerator_geometric_exit_reference = None
    exit_source_selection = bunch_selection
    if bunch_source is not None and exit_source_selection is None:
        if bunch_source_receipt_path is None:
            raise CandidateContractError(
                "full bunch exit reference requires its frozen source receipt"
            )
        exit_source_selection = resolve_bunch_source_interval(
            receipt_path=bunch_source_receipt_path,
            particle_id_min=1,
            particle_id_max=int(bunch_source["particle_count"]),
        )
    accelerator_geometric_exit_reference = _accelerator_geometric_exit_reference(
        contract=contract,
        provider_plan=provider_plan,
        resolved_campaign=_load(accelerator_resolved_campaign_path),
        bunch_source=bunch_source,
        bunch_selection=exit_source_selection,
        mass_th=mass,
        charge_state=charge,
        slow_energy_per_charge_v=slow_energy,
        source_origin_project_mm=source_origin_project,
        composition_plan=composition_plan,
        local_scope=local_scope,
        direct_pose=direct_pose,
        validated_provider_origin=actual_oa_origin,
    )
    exit_plane_lua = (
        "accelerator_exit_plane_project_z_mm = "
        f"{accelerator_geometric_exit_reference['exit_plane_project_z_mm']:.17g}, "
        if accelerator_geometric_exit_reference is not None else ""
    )
    analyzer_values = mirror_voltages + mirror_voltages + [
        stripe_biases[0], stripe_biases[0], stripe_biases[1], stripe_biases[1],
        0.0, p1, p2, 0.0, 0.0, 0.0,
    ]
    field_lua = ""
    if field_binding is not None:
        scale = _finite(simion['nonaccelerator_scale'], 'nonaccelerator scale')
        actual_analyzer = _static_consumed_analyzer_voltages(
            field_binding, [v * scale for v in analyzer_values],
            [0.0, *endpoint_voltages, *ring_voltages], pulse_requested=accelerator_pulse_requested)
        # Record the voltages actually consumed, after the existing compatibility
        # check; CLI float formatting must not create a different sealed anchor.
        stripe_biases = [actual_analyzer[10] / scale, actual_analyzer[12] / scale]
        p1, p2 = actual_analyzer[15] / scale, actual_analyzer[16] / scale
        field_lua = (
            "static_field = { "
            f"{_scalar_field_lua_fields(field_binding)}, "
            f"collision_pa_path = {json.dumps(field_binding['instances'][1]['pa_path'], ensure_ascii=False)}, "
            f"refinement_windows = {_scalar_refinement_windows_lua(field_binding.get('refinement_windows', []))}, "
            f"accelerator_front_z_mm = {field_binding['accelerator_front_z_mm']:.17g}, "
            f"analyzer_voltages_v = {_lua_vector(field_binding['authority']['analyzer_electrode_voltages_v'])}, "
            f"accelerator_voltages_v = {_lua_vector([0.0, *endpoint_voltages, *ring_voltages])} }}, "
        )
    scientific_directory = sidecar_path.parent.resolve()
    writer_source = Path(__file__).resolve().parents[3] / "common/simion/scientific_event_csv.lua"
    writer_path = scientific_directory / "scientific_event_csv.lua"
    writer_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(writer_source, writer_path)
    scientific_event_output = dict(events_path=str(scientific_directory / "mrtof_events.csv"),
        trajectory_path=str(scientific_directory / "mrtof_trajectory.csv") if trajectory_recording else None,
        csv_writer_path=str(writer_path), environment_required=batch_scientific_event_locators,
        events_environment_variable="MRTOF_SCIENTIFIC_EVENTS_PATH",
        trajectory_environment_variable="MRTOF_SCIENTIFIC_TRAJECTORY_PATH")
    locator_path = sidecar_path.with_suffix(".obs.lua")
    def locator_value(key, value):
        if value is None: return "nil"
        if isinstance(value,bool): return str(value).lower()
        return json.dumps(project_native_run_path(str(value)).replace(chr(92),"/") if key in {"events_path", "trajectory_path", "csv_writer_path"} else str(value),ensure_ascii=False)
    locator_path.write_text("return {"+",".join(key+"="+locator_value(key, value) for key,value in scientific_event_output.items())+"}\n",encoding="utf-8",newline="\n")
    sidecar = (
        "-- Generated run-local finite-3D P1/P2 voltage trial; do not edit.\n"
        "local point_path=debug.getinfo(1,'S').source:sub(2)\n"
        "local scientific_output=assert(loadfile(point_path:gsub('%.lua$','.obs.lua')))()\n"
        f"return {{ scientific_event_output = scientific_output, "
        f"qualification = 'p1_p2_finite_3d_voltage_trial_only', mirror_voltages_v = {_lua_vector(mirror_voltages)}, "
        f"stripe_biases_v = {_lua_vector(stripe_biases)}, prism_voltages_v = {_lua_vector([p1, p2])}, "
        f"accelerator_voltages_v = {_lua_vector(endpoint_voltages)}, accelerator_ring_voltages_v = {_lua_vector(ring_voltages)}, "
        f"first_prism_l0 = {{ target_plane_z_mm = {p1_plane:.17g}, target_plane_x_mm = 0, target_plane_y_acceptance_mm = {_lua_vector([float(v) for v in p1_acceptance])} }}, "
        f"mirror_regions_project = {{ negative = {{ z_min_mm = {regions['negative'][0]:.17g}, z_max_mm = {regions['negative'][1]:.17g} }}, positive = {{ z_min_mm = {regions['positive'][0]:.17g}, z_max_mm = {regions['positive'][1]:.17g} }} }}, "
        f"prism_regions_project = {{ p1 = {{ y_min_mm = {prism_regions['p1'][0]:.17g}, y_max_mm = {prism_regions['p1'][1]:.17g}, z_min_mm = {prism_regions['p1'][2]:.17g}, z_max_mm = {prism_regions['p1'][3]:.17g} }}, p2 = {{ y_min_mm = {prism_regions['p2'][0]:.17g}, y_max_mm = {prism_regions['p2'][1]:.17g}, z_min_mm = {prism_regions['p2'][2]:.17g}, z_max_mm = {prism_regions['p2'][3]:.17g} }} }}, "
        f"p2_low_field_reference = {{ z_mm = {_finite(low_field_reference['reference_plane_project_z_mm'], 'P2 low-field reference z'):.17g}, x_min_mm = {_finite(low_field_aperture['x_mm'][0], 'P2 low-field x minimum'):.17g}, x_max_mm = {_finite(low_field_aperture['x_mm'][1], 'P2 low-field x maximum'):.17g}, y_min_mm = {_finite(low_field_aperture['y_mm'][0], 'P2 low-field y minimum'):.17g}, y_max_mm = {_finite(low_field_aperture['y_mm'][1], 'P2 low-field y maximum'):.17g} }}, "
        f"phase_origin_mirror_side = {phase_contract.origin_mirror_side}, return_mirror_side = {phase_contract.return_mirror_side}, "
        f"detector_box_mm = {_lua_vector([float(v) for v in detector['box']])}, detector_normal_project = '+z', "
        f"trajectory_quality = {float(trajectory_profile['trajectory_quality']):.17g}, maximum_step_us = {float(trajectory_profile['maximum_step_us']):.17g}, "
        f"trajectory_recording_enabled = {'true' if trajectory_recording else 'false'}, "
        f"trajectory_recording_mode = '{trajectory_recording['mode'] if trajectory_recording else 'every_step'}', "
        f"trajectory_recording_interval_us = {format(trajectory_recording['interval_us'], '.17g') if trajectory_recording and trajectory_recording['mode'] == 'fixed_interval' else 'nil'}, "
        f"full_path_timeout_us = {timeout:.17g}, nonaccelerator_scale = {_finite(simion['nonaccelerator_scale'], 'nonaccelerator scale'):.17g}, "
        f"target_drift_period_ratio = {target_k:.17g}, target_half_oscillation_count = {phase_contract.target_half_oscillation_count}, "
        f"runtime_fast_adjust_enable = {'true' if runtime_fast_adjust_enable else 'false'}, "
        f"accelerator_safe_exit_only = {'true' if accelerator_safe_exit_only else 'false'}, "
        f"{exit_plane_lua}"
        f"runtime_accelerator_field_gate_enable = {'true' if accelerator_pulse_requested else 'false'}, "
        f"accelerator_pulse_mode = '{accelerator_pulse_mode}', "
        f"{accelerator_pulse_time_lua}"
        f"{field_lua}"
        "flight_scope = 'complete_three_dimensional_static_return' }\n"
    )
    fly2_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    fly2_path.write_text(fly2, encoding="utf-8", newline="\n")
    sidecar_path.write_text(sidecar, encoding="utf-8", newline="\n")
    priority_path = sidecar_path.parent / "native_corridor_priority_contract.lua"
    priority_path.write_text(priority_lua, encoding="utf-8", newline="\n")
    if field_binding is not None:
        analyzer_values = list(field_binding['authority']['analyzer_electrode_voltages_v'])
    source_transverse_reference = _source_transverse_reference(
        bunch_source=bunch_source,
        bunch_selection=bunch_selection,
        mass_th=mass,
        charge_state=charge,
        slow_energy_per_charge_v=slow_energy,
    )
    receipt = {
        "schema_version": 1,
        "role": "mrtof_finite_3d_two_prism_voltage_trial",
        "status": "materialized",
        "qualification": (
            "contiguous_frozen_bunch_diagnostic__not_formal"
            if bunch_selection is not None
            else "complete_bunch_pilot_or_fixed_clock_trial__performance_pending"
            if bunch_source is not None else "single_center_trial__not_an_operating_point"
        ),
        "flight_scope": "complete_three_dimensional_static_return",
        "selected_axial_energy_per_charge_v": energy,
        "source_slow_kinetic_energy_per_charge_v": slow_energy,
        "source_position_project_mm": (
            None if bunch_source is not None else [
                *source_origin_project,
            ]
        ),
        "source_y_offset_from_accelerator_axis_mm": (
            None if bunch_source is not None else source_y_offset
        ),
        "source_direction_project": None if bunch_source is not None else [0.0, 1.0, 0.0],
        "source_particle_count": (
            len(bunch_selection["particle_ids"])
            if bunch_selection is not None
            else bunch_source["particle_count"] if bunch_source is not None else 1
        ),
        "source_time_of_birth_us": (
            bunch_source["common_time_of_birth_us"] if bunch_source is not None else 0.0
        ),
        "source_clock_basis": _GLOBAL_PULSE_TIME_BASIS,
        "source_cohort": (
            bunch_selection["source_cohort"]
            if bunch_selection is not None
            else source_cohort_identity(bunch_source) if bunch_source is not None else None
        ),
        "source_center_state": (
            bunch_source.get("center_particle_state")
            if bunch_source is not None else None
        ),
        "peak_analysis_contract": contract["peak_analysis"],
        "source_cohort_role": bunch_source.get("cohort_role") if bunch_source else None,
        "source_transverse_reference": source_transverse_reference,
        "source_expected_particle_ids": (
            bunch_selection["particle_ids"]
            if bunch_selection is not None
            else bunch_source["expected_particle_ids"] if bunch_source is not None else [1]
        ),
        "source_volume_particle_id_min": (
            bunch_source.get("volume_particle_id_min")
            if bunch_source is not None else None
        ),
        "source_selection": (
            bunch_selection["source_cohort"]["selection"]
            if bunch_selection is not None else None
        ),
        "mirror_voltages_v": mirror_voltages,
        "terminal_time_mirror_variation": mirror_variation,
        "stripe_biases_v": stripe_biases,
        "seed_theory_provenance": _seed_theory_provenance(
            seed_mirror_voltages, seed_stripe_biases, mirror_voltages, stripe_biases,
        ),
        "prism_voltages_v": [p1, p2],
        "detector_box_mm": [float(v) for v in detector["box"]],
        "accelerator_endpoint_voltages_v": endpoint_voltages,
        "accelerator_ring_voltages_v": ring_voltages,
        "accelerator_applied_net_gain_parameter_v": accelerator_energy[
            "applied_net_gain_parameter_v"
        ],
        "accelerator_target_axial_energy_per_charge_v": accelerator_energy[
            "target_axial_energy_per_charge_v"
        ],
        "accelerator_finite_3d_gain_correction_v": accelerator_energy[
            "finite_3d_gain_correction_v"
        ],
        "accelerator_exit_energy_contract": provider_exit_energy_contract,
        "accelerator_geometric_exit_reference": accelerator_geometric_exit_reference,
        "analyzer_electrode_voltages_v": analyzer_values,
        **({"resolved_iob_pose": resolved_iob_pose} if resolved_iob_pose is not None else {}),
        "field_binding": None if field_binding is None else _static_field_receipt(field_binding, field_binding_path),
        "target_positive_mirror_turn_y_mm": target_turn_y,
        "prism_handoff_target": prism_target,
        "target_nominal_injection_angle_degrees": target_angle_degrees,
        "target_low_field_tangent_ratio_vy_over_vz": target_tangent_ratio,
        "p2_low_field_reference_section": low_field_reference,
        "drift_phase_contract": phase_contract.as_dict(),
        "p1_p2_handoff_definition": (
            "P1 -> negative-mirror diagnostic turn -> P2 -> low-field Candidate "
            "reference crossing -> first positive-mirror turn"
        ),
        "detector_return_policy_authority": {
            "source": "trajectory_contract",
            "policy": detector_return_policy,
            "legacy_physical_contracts_rebound_without_mutation": True,
        },
        "target_slow_turn_y_mm": _finite(
            contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
            "manufactured drift length",
        ),
        "target_drift_period_ratio": target_k,
        "target_half_oscillation_count": phase_contract.target_half_oscillation_count,
        "runtime_fast_adjust_enable": bool(runtime_fast_adjust_enable),
        "accelerator_instance": accelerator_instance,
        "accelerator_pulse": {
            "mode": accelerator_pulse_mode,
            "pulse_off_time_us": fixed_pulse_off_time,
            "energized_before_initial_exit": (
                True if pulse_accelerator_until_initial_exit else None
            ),
            "grounded_after_initial_exit": (
                True if pulse_accelerator_until_initial_exit else None
            ),
            "fixed_global_time_applied": fixed_pulse_off_time is not None,
            "qualification": (
                "single_center_event_triggered_schedule__must_be_replaced_by_one_frozen_global_time_for_any_bunch"
                if pulse_accelerator_until_initial_exit
                else (
                    "frozen_global_time_single_center_diagnostic__bunch_qualification_pending"
                    if fixed_pulse_off_time is not None else "static_accelerator"
                )
            ),
        },
        "execution_scope": (
            "accelerator_safe_exit_envelope_only"
            if accelerator_safe_exit_only
            else "complete_three_dimensional_static_return"
        ),
        "particle_mass_th": mass,
        "charge_state": charge,
        "trajectory_profile": trajectory_profile,
        "trajectory_recording": trajectory_recording,
        "scientific_event_output": scientific_event_output,
        "scientific_event_locator": file_record(locator_path),
        "scientific_csv_writer": file_record(writer_path),
        "nonaccelerator_mesh_mm_per_gu": list(
            simion["component_mesh_mm_per_gu"]["analyzer"]
        ),
        "collision_geometry": _collision_geometry_projection(resolved),
        "native_corridor_priority_contract": {
            "path": str(priority_path.resolve()), "bytes": priority_path.stat().st_size,
            "sha256": file_sha256(priority_path).lower(),
        },
        "inputs": {
            **({"native_corridor_cache_manifest": {
                "path": str(native_corridor_cache_manifest_path.resolve()),
                "bytes": native_corridor_cache_manifest_path.stat().st_size,
                "sha256": file_sha256(native_corridor_cache_manifest_path).lower(),
            }} if native_corridor_cache_manifest_path is not None else {}),
            "contract_sha256": file_sha256(contract_path).lower(),
            "accelerator_geometry_contract_sha256": file_sha256(
                accelerator_geometry_contract_path
            ).lower(),
            "trajectory_contract_sha256": file_sha256(trajectory_contract_path).lower(),
            "reviewed_contract_sha256": file_sha256(reviewed_contract_path).lower(),
            "mirror_summary_sha256": file_sha256(mirror_summary_path).lower(),
            "stripe_summary_sha256": file_sha256(stripe_summary_path).lower(),
            **({
                "fixed_mirror_stripe_authority_sha256": file_sha256(
                    fixed_mirror_stripe_authority_path
                ).lower(),
            } if fixed_mirror_stripe_authority_path is not None else {}),
            "accelerator_receipt_sha256": file_sha256(accelerator_receipt_path).lower(),
            **({
                "accelerator_pulse_schedule_sha256": file_sha256(
                    accelerator_pulse_schedule_path
                ).lower(),
            } if accelerator_pulse_schedule_path is not None else {}),
            **({
                "bunch_source_receipt_sha256": file_sha256(bunch_source_receipt_path).lower(),
            } if bunch_source_receipt_path is not None else {}),
        },
        "fly2_sha256": file_sha256(fly2_path).lower(),
        "operating_point_lua_sha256": file_sha256(sidecar_path).lower(),
    }
    if pulse_schedule is not None and pulse_schedule["schema_version"] == 2:
        if bunch_source is None:
            raise CandidateContractError("bunch pulse schedule requires a frozen bunch source")
        if pulse_schedule["source_cohort"] != receipt["source_cohort"]:
            raise CandidateContractError("pulse schedule source differs from the flight cohort")
        expected_solver_identity = pulse_schedule["solver_problem_identity"]
        actual_solver_identity = solver_problem_identity_from_trial_receipt(receipt)
        if expected_solver_identity != actual_solver_identity:
            differing_fields = sorted(
                key
                for key in set(expected_solver_identity) | set(actual_solver_identity)
                if expected_solver_identity.get(key) != actual_solver_identity.get(key)
            )
            raise CandidateContractError(
                "pulse schedule solver problem differs from the flight; fields="
                + ",".join(differing_fields)
            )
        receipt["accelerator_pulse"]["qualification"] = (
            "complete_bunch_safe_exit_schedule__numerical_convergence_pending"
        )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _project_selected_center_observation(result: dict[str, Any], trial: dict[str, Any],
                                         events: list[dict[str, Any]]) -> None:
    """Expose existing center residuals only for a declared frozen diagnostic center."""
    selection = trial.get("source_selection") or {}
    center = trial.get("source_center_state") or {}
    if (trial.get("source_cohort_role") != "controlled_diagnostic"
            or selection.get("role") != "contiguous_frozen_source_diagnostic_selection"
            or trial.get("source_expected_particle_ids") != [1]
            or center.get("particle_id") != 1):
        return
    validation = result["center_particle_workpoint_validation"]
    static_return = _static_return_diagnostic(
        events, _finite(trial.get("target_drift_period_ratio"), "target K")
    )
    result["static_return_diagnostic"] = static_return
    result["extraction_diagnostic"] = static_return
    result["termination_diagnostic"] = _termination_diagnostic(events)
    result["qualification"] = "candidate_frozen_center_diagnostic__not_formal"
    if validation.get("status") == "observed":
        result["residuals"] = dict(validation["residuals"])
    if (validation.get("status") == "observed"
            and result["cohort_analysis"]["event_integrity_passed"]
            and static_return["event_contract_ok"]):
        result["status"] = "full_drift_observed"
        result["return_topology"] = "exact_target_k_phase_return"
        result["fractional_k"] = static_return.get("fractional_k")
    else:
        result["status"] = "selected_center_observation_incomplete"


def analyze_trial(*, log_path: Path, trial_receipt_path: Path, output_path: Path, scientific_event_receipt: Path | None = None) -> dict[str, Any]:
    trial = _load(trial_receipt_path)
    if trial.get("prism_switch") is not None:
        raise CandidateContractError(
            "active MR-TOF Candidate observation forbids all P1/P2 voltage switching"
        )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import read_scientific_events
    science = _load(scientific_event_receipt)["scientific_event_output"] if scientific_event_receipt is not None else trial.get("scientific_event_output")
    events, native_completions, _log_identity = read_scientific_events(log_path, scientific_event_output=science)
    if any(event["kind"] == "prism_voltage_switch" for event in events):
        raise CandidateContractError(
            "active MR-TOF Candidate log contains a forbidden P1/P2 voltage switch"
        )
    pulse_contract = trial.get("accelerator_pulse") or {"mode": "static"}
    pulse_mode = pulse_contract.get("mode")
    if pulse_mode not in {
        "static", "initial_exit_triggered_single_center", "fixed_global_time",
    }:
        raise CandidateContractError("trial has an unsupported accelerator pulse mode")
    exit_pulse_events = [
        event for event in events if event["kind"] == "accelerator_pulse_off"
    ]
    global_pulse_events = [
        event for event in events
        if event["kind"] == "accelerator_global_pulse_applied"
    ]
    if pulse_mode == "initial_exit_triggered_single_center":
        safe_exit_only = (
            trial.get("execution_scope") == "accelerator_safe_exit_envelope_only"
        )
        if safe_exit_only and (exit_pulse_events or global_pulse_events):
            raise CandidateContractError(
                "accelerator safe-exit-only trial must stop before pulse-off"
            )
        if not safe_exit_only and (
            len(exit_pulse_events) != 1 or global_pulse_events
        ):
            raise CandidateContractError(
                "initial-exit-triggered accelerator trial must emit exactly one pulse-off event"
            )
        accelerator_instance = int(trial.get("accelerator_instance", 3))
        if accelerator_instance != 3:
            raise CandidateContractError("trial has an invalid native accelerator instance")
        if not safe_exit_only and (
            int(exit_pulse_events[0]["from_instance"]) != accelerator_instance
            or int(exit_pulse_events[0]["to_instance"]) == accelerator_instance
        ):
            raise CandidateContractError(
                "accelerator pulse-off event must be the first exit from the declared accelerator instance"
            )
    elif pulse_mode == "fixed_global_time":
        configured_time = _finite(
            pulse_contract.get("pulse_off_time_us"), "fixed accelerator pulse-off time"
        )
        if configured_time <= 0 or exit_pulse_events:
            raise CandidateContractError(
                "fixed-time accelerator trial must define a positive time and emit no exit-triggered pulse event"
            )
        expected_particle_ids = trial.get("source_expected_particle_ids")
        if expected_particle_ids is None:
            expected_particle_ids = [1]
        pulse_validation = validate_fixed_global_pulse_events(
            events=events,
            expected_particle_ids=expected_particle_ids,
            pulse_off_time_us=configured_time,
            time_tolerance_us=max(1e-9, abs(configured_time) * 1e-9),
            accelerator_instance=int(trial.get("accelerator_instance", 3)),
        )
    elif exit_pulse_events or global_pulse_events:
        raise CandidateContractError("static accelerator trial emitted an unexpected pulse-off event")
    pulse_events = exit_pulse_events + global_pulse_events
    kinds: dict[str, int] = {}
    for event in events:
        kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
    result: dict[str, Any] = {
        "schema_version": 1,
        "role": "mrtof_finite_3d_two_prism_trial_observation",
        "status": "p2_low_field_and_positive_mirror_turn_incomplete",
        "qualification": "single_center_trial__not_an_operating_point",
        "execution_scope": trial.get(
            "execution_scope", "complete_three_dimensional_static_return",
        ),
        "prism_voltages_v": trial["prism_voltages_v"],
        "event_counts": kinds,
        "log_sha256": _log_identity,
        "trial_receipt_sha256": file_sha256(trial_receipt_path).lower(),
        "accelerator_pulse_diagnostic": {
            "mode": pulse_mode,
            "pulse_off_event_count": len(pulse_events),
            "pulse_off_event": pulse_events[0] if pulse_events else None,
            "fixed_global_pulse_validation": (
                pulse_validation if pulse_mode == "fixed_global_time" else None
            ),
            "qualification": pulse_contract.get("qualification"),
        },
    }
    source_particle_count = int(trial.get("source_particle_count", 1))
    source_cohort = trial.get("source_cohort")
    if source_cohort is not None:
        if not isinstance(source_cohort, dict):
            raise CandidateContractError("bunch trial source cohort must be an object")
        expected_ids = trial.get("source_expected_particle_ids")
        if (
            not isinstance(expected_ids, list)
            or len(expected_ids) != source_particle_count
            or any(type(value) is not int for value in expected_ids)
            or expected_ids != list(range(expected_ids[0], expected_ids[0] + source_particle_count))
        ):
            raise CandidateContractError(
                "bunch trial receipt lacks one complete contiguous ordered particle cohort"
            )
        completion_matches = native_completions
        reported_splats = (
            completion_matches[0].splats
            if len(completion_matches) == 1 else None
        )
        exit_energy_contract = trial.get("accelerator_exit_energy_contract")
        exit_energy_contract = (
            exit_energy_contract if isinstance(exit_energy_contract, dict) else {}
        )
        energy_targets = exit_energy_contract.get("targets_per_charge_v")
        energy_targets = energy_targets if isinstance(energy_targets, dict) else {}
        energy_tolerances = exit_energy_contract.get("absolute_tolerances_per_charge_v")
        energy_tolerances = energy_tolerances if isinstance(energy_tolerances, dict) else {}
        charge_state = trial.get("charge_state")
        charge_e = (
            _finite(charge_state, "particle charge state")
            if charge_state is not None else None
        )
        cohort = summarize_events(
            events,
            _finite(trial.get("target_drift_period_ratio"), "target drift period ratio"),
            reported_splats,
            expected_particle_ids=tuple(expected_ids),
            completion_count=len(completion_matches),
            kinetic_energy_ev=_finite(
                trial.get("selected_axial_energy_per_charge_v"),
                "selected axial energy",
            ),
            mass_th=_finite(trial.get("particle_mass_th"), "particle mass"),
            charge_e=charge_e,
            theoretical_transverse_energy_per_charge_v=(
                energy_targets.get("Ex")
            ),
            theoretical_release_slow_energy_per_charge_v=(
                energy_targets.get(
                    "Ey", trial.get("source_slow_kinetic_energy_per_charge_v")
                )
            ),
            theoretical_axial_energy_per_charge_v=(
                energy_targets.get(
                    "Ez", trial.get("accelerator_target_axial_energy_per_charge_v")
                )
            ),
            transverse_energy_tolerance_per_charge_v=energy_tolerances.get("Ex"),
            slow_energy_tolerance_per_charge_v=energy_tolerances.get("Ey"),
            axial_energy_tolerance_per_charge_v=energy_tolerances.get("Ez"),
            source_transverse_reference=trial.get("source_transverse_reference"),
            transverse_velocity_bias_tolerance_mm_per_us=(
                exit_energy_contract.get(
                    "maximum_exit_transverse_velocity_bias_mm_per_us"
                )
            ),
            collision_geometry=trial.get("collision_geometry"),
            volume_particle_id_min=trial.get("source_volume_particle_id_min"),
            peak_analysis_contract=trial.get("peak_analysis_contract"),
            cohort_role=trial.get("source_cohort_role"),
        )
        geometric_exit_reference = trial.get("accelerator_geometric_exit_reference")
        geometric_exit_validation = (
            _accelerator_geometric_exit_validation(
                events=events,
                reference=geometric_exit_reference,
                expected_particle_ids=expected_ids,
                mass_th=_finite(trial.get("particle_mass_th"), "particle mass"),
                charge_state=_finite(trial.get("charge_state"), "particle charge state"),
            )
            if isinstance(geometric_exit_reference, dict)
            else {"status": "unavailable__geometric_exit_reference_not_frozen", "passed": None}
        )
        cohort["accelerator_geometric_exit_validation"] = geometric_exit_validation
        safe_exit_ids = sorted({
            int(event["ion"])
            for event in events if event["kind"] == "accelerator_safe_exit"
        })
        cohort["accelerator_safe_exit_particle_ids"] = safe_exit_ids
        cohort["accelerator_safe_exit_count"] = len(safe_exit_ids)
        cohort["accelerator_safe_exit_fraction"] = (
            len(safe_exit_ids) / source_particle_count
        )
        cohort["accelerator_safe_exit_complete"] = safe_exit_ids == expected_ids
        signed_bias = (
            cohort.get("prism_phase_space_diagnostic", {})
            .get("surfaces", {})
            .get("accelerator_safe_exit", {})
            .get("signed_transverse_bias")
        )
        cohort["accelerator_safe_exit_signed_transverse_bias"] = signed_bias
        signed_bias_required = (
            isinstance(exit_energy_contract, dict)
            and bool(exit_energy_contract)
            and trial.get("source_selection") is None
            and trial.get("source_center_state") is not None
        )
        signed_bias_passed = (
            isinstance(signed_bias, dict) and signed_bias.get("passed") is True
        )
        short_exit_scope = (
            trial.get("execution_scope") == "accelerator_safe_exit_envelope_only"
        )
        if short_exit_scope:
            for key in (
                "detection_rate", "detector_tof_fwhm_us", "detector_tof_mean_us",
                "detector_tof_median_us", "mass_resolution_t_over_2fwhm",
                "target_k_fraction", "target_k_handoff_histogram_half_height_bin_span_us",
                "target_k_handoff_tof_median_us",
            ):
                cohort[key] = None
            if "target_k_handoff_histogram_analysis" in cohort:
                cohort["target_k_handoff_histogram_analysis"]["status"] = (
                    "not_applicable__accelerator_geometric_exit_scope"
                )
            cohort["peak_analysis"] = {
                "status": "not_applicable__accelerator_geometric_exit_scope"
            }
            cohort["volume_only"] = None
            cohort["detector_performance_scope"] = (
                "not_applicable__accelerator_geometric_exit_scope"
            )
        short_exit_passed = (
            short_exit_scope
            and cohort["event_integrity_passed"]
            and geometric_exit_validation.get("passed") is True
        )
        result.update({
            "status": (
                "accelerator_geometric_exit_observed"
                if short_exit_passed
                else "accelerator_geometric_exit_invalid"
                if short_exit_scope
                else "bunch_observed"
                if cohort["event_integrity_passed"]
                and (not signed_bias_required or signed_bias_passed)
                else "bunch_observation_invalid"
            ),
            "qualification": (
                "accelerator_geometric_exit_envelope_accepted"
                if short_exit_passed
                else "accelerator_geometric_exit_envelope_rejected"
                if short_exit_scope
                else "candidate_bunch_selection_diagnostic__not_formal"
                if trial.get("source_selection") is not None
                else "candidate_bunch__not_formal"
            ),
            "cohort_analysis": cohort,
            "accelerator_geometric_exit_validation": geometric_exit_validation,
            "source_release_state": (
                _source_release_record(
                    center_source, trial["source_center_state"]["mass_th"],
                    trial["source_center_state"]["charge_e"],
                    _finite(trial["source_center_state"].get("tob_us"), "bunch centre time of birth"),
                ) if (center_source := _bunch_center_source_state(trial)) is not None else None
            ),
            "center_particle_workpoint_validation": (
                _bunch_center_workpoint_validation(events, trial)
            ),
            "center_particle_prism_handoff_validation": (
                _bunch_center_prism_handoff_validation(events, trial)
            ),
            "center_particle_stripe_stage_validation": (
                _bunch_center_stripe_stage_validation(events, trial)
            ),
            "accelerator_safe_exit_observation": {
                "status": "complete_cohort_observed" if safe_exit_ids == expected_ids else "incomplete_cohort",
                "particle_ids": safe_exit_ids,
                "expected_particle_ids": expected_ids,
            },
            "termination_diagnostic": {
                "status": "cohort",
                "particle_terminal_count": cohort["particle_terminal_count"],
                "splat_code_histogram": cohort["splat_code_histogram"],
                "all_losses_retained": cohort["all_losses_retained"],
            },
        })
        if not short_exit_scope:
            _project_selected_center_observation(result, trial, events)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    source, source_state = _single_center_source_state(trial)
    result["source_release_state"] = source_state
    result["accelerator_safe_exit_observation"] = _accelerator_safe_exit_observation(
        events, trial, log_path=log_path, trial_receipt_path=trial_receipt_path, log_sha256=_log_identity,
    )
    target_k_contract = _finite(trial.get("target_drift_period_ratio"), "target drift period ratio")
    result["termination_diagnostic"] = _termination_diagnostic(events)
    static_return = _static_return_diagnostic(events, target_k_contract)
    result["static_return_diagnostic"] = static_return
    # Keep the runner's established summary field while changing its contents
    # to the only active extraction contract: an unchanged-voltage return.
    result["extraction_diagnostic"] = static_return
    try:
        handoff_events = _prism_handoff_event_prefix(events)
        observation = observation_from_simion_events(handoff_events, source)
        residuals = prism_handoff_residuals(
            observation,
            target_positive_mirror_turn_y_mm=float(
                trial["target_positive_mirror_turn_y_mm"]
            ),
            target_tangent_ratio_vy_over_vz=float(
                trial["target_low_field_tangent_ratio_vy_over_vz"]
            ),
        )
    except CandidateContractError as error:
        result["incomplete_reason"] = str(error)
        terminals = [event for event in events if event["kind"] in {"splat", "terminal"}]
        result["terminal_events"] = terminals
    else:
        result.update({
            "status": "p2_low_field_and_positive_mirror_turn_observed",
            "p1_state": {
                "position_mm": observation.prism_1.position_mm,
                "velocity_mm_per_us": observation.prism_1.velocity_mm_per_us,
            },
            "p2_low_field_reference_state": {
                "position_mm": observation.p2_shield_low_field_reference.position_mm,
                "velocity_mm_per_us": observation.p2_shield_low_field_reference.velocity_mm_per_us,
            },
            "positive_mirror_turn_state": {
                "position_mm": observation.positive_mirror_turn.position_mm,
                "velocity_mm_per_us": observation.positive_mirror_turn.velocity_mm_per_us,
            },
            "residuals": {name: value for name, value in residuals},
        })
        phase_events = [event for event in events if event["kind"] == "drift_phase_origin"]
        if len(phase_events) != 1:
            raise CandidateContractError("complete trial must contain one drift phase origin")
        phase_time = _finite(phase_events[0].get("t_us"), "drift phase-origin time")
        slow_turns = [
            event for event in events
            if event["kind"] == "slow_turn" and float(event["t_us"]) > phase_time
        ]
        coordinate_returns = [
            event for event in events
            if event["kind"] == "drift_coordinate_return" and float(event["t_us"]) > phase_time
        ]
        exact_phase_returns = [
            event for event in events
            if event["kind"] == "drift_phase_return"
            and float(event["t_us"]) > phase_time
            and float(event["k"]) == target_k_contract
        ]
        return_event_valid = len(coordinate_returns) == 1 or (
            not coordinate_returns and len(exact_phase_returns) == 1
        )
        if not slow_turns or not return_event_valid:
            result["status"] = "full_drift_incomplete"
            result["incomplete_reason"] = (
                "complete trial must observe a post-origin slow turn and either "
                "one coordinate return or one exact target-K phase return"
            )
        else:
            slow_turn_y = _finite(slow_turns[0].get("y_mm"), "observed slow turn y")
            if coordinate_returns:
                coordinate_return = coordinate_returns[0]
                # A coordinate return may occur before the requested target
                # mirror phase.  In that case the ion can reach the physical
                # detector before a target-K turn exists, so there is no
                # legitimate target-phase y sample to report.  Preserve the
                # observed fractional-K residual instead of turning a valid
                # flight into a post-processing failure.
                phase_crossing_y = coordinate_return.get("phase_crossing_y_mm")
                if phase_crossing_y is None:
                    # Older flight programs emitted only the preceding
                    # discrete half-cycle.  Recover the same continuous phase
                    # diagnostic from the latest two same-side mirror turns;
                    # this is observation analysis, not a new trajectory.
                    return_time = _finite(coordinate_return.get("t_us"), "coordinate-return time")
                    candidates = [
                        event for event in events
                        if event["kind"] == "drift_phase_candidate"
                        and phase_time < float(event["t_us"]) <= return_time
                    ]
                    if candidates:
                        latest = candidates[-1]
                        latest_side = 1 if _finite(latest.get("z_mm"), "phase-candidate z") > 0 else -1
                        previous_same_side = next((
                            event for event in reversed(candidates[:-1])
                            if (1 if _finite(event.get("z_mm"), "phase-candidate z") > 0 else -1)
                            == latest_side
                        ), None)
                        if previous_same_side is not None:
                            period = _finite(latest.get("t_us"), "latest phase time") - _finite(
                                previous_same_side.get("t_us"), "previous same-side phase time"
                            )
                            elapsed = return_time - _finite(latest.get("t_us"), "latest phase time")
                            if period > 0.0 and elapsed >= 0.0:
                                coordinate_return["phase_crossing_t_us"] = latest["t_us"]
                                coordinate_return["phase_crossing_y_mm"] = latest["y_mm"]
                                coordinate_return["phase_time_residual_us"] = elapsed
                                coordinate_return["phase_period_us"] = period
                                coordinate_return["fractional_k"] = (
                                    _finite(latest.get("k"), "latest phase K") + elapsed / period
                                )
                                phase_crossing_y = latest["y_mm"]
                fractional_k = _finite(
                    coordinate_return.get("fractional_k"), "observed fractional K"
                )
                exact_coordinate_return = (
                    len(exact_phase_returns) == 1
                    and math.isclose(fractional_k, target_k_contract, rel_tol=0.0, abs_tol=1.0e-12)
                )
                preceding_phase_y = (
                    _finite(phase_crossing_y, "preceding phase crossing y")
                    if phase_crossing_y is not None else None
                )
                target_phase_samples = [
                    event for event in events
                    if event["kind"] == "target_k_phase_sample"
                    and float(event["t_us"]) > phase_time
                    and float(event["k"]) == target_k_contract
                ]
                if len(target_phase_samples) > 1:
                    raise CandidateContractError(
                        "coordinate-return flight has multiple target phase samples"
                    )
                observed_target_phase_y = (
                    _finite(target_phase_samples[0].get("y_mm"), "target-phase sample y")
                    if target_phase_samples else None
                )
                target_phase_y = (
                    preceding_phase_y if exact_coordinate_return else observed_target_phase_y
                )
                return_topology = (
                    "exact_target_k_phase_return" if exact_coordinate_return
                    else "coordinate_return_before_target_phase"
                )
            else:
                fractional_k = float(target_k_contract)
                target_phase_samples = [
                    event for event in events
                    if event["kind"] == "target_k_phase_sample"
                    and float(event["t_us"]) > phase_time
                    and float(event["k"]) == target_k_contract
                ]
                if len(target_phase_samples) != 1:
                    raise CandidateContractError(
                        "exact target-K return requires one target phase sample"
                    )
                target_phase_y = _finite(
                    target_phase_samples[0].get("y_mm"), "target-phase sample y"
                )
                return_topology = "exact_target_k_phase_return"
            target_y = _finite(trial.get("target_slow_turn_y_mm"), "target slow turn y")
            target_k = _finite(trial.get("target_drift_period_ratio"), "target K")
            phase_origin_y = _finite(
                trial.get("target_positive_mirror_turn_y_mm"), "target phase-origin y"
            )
            result["status"] = "full_drift_observed"
            result["slow_turn_y_mm"] = slow_turn_y
            result["fractional_k"] = fractional_k
            result["target_phase_y_mm"] = target_phase_y
            if coordinate_returns:
                result["preceding_phase_y_mm"] = preceding_phase_y
            result["return_topology"] = return_topology
            result["residuals"].update({
                "Stripe_slow_turn_y_minus_L_mm": slow_turn_y - target_y,
                "Stripe_fractional_K_minus_target": fractional_k - target_k,
            })
            if target_phase_y is not None:
                result["residuals"]["Stripe_target_phase_y_minus_origin_mm"] = (
                    target_phase_y - phase_origin_y
                )
            elif coordinate_returns and preceding_phase_y is not None:
                result["residuals"]["Stripe_preceding_phase_y_minus_origin_mm"] = (
                    preceding_phase_y - phase_origin_y
                )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--contract", required=True, type=Path)
    materialize.add_argument("--accelerator-geometry-contract", required=True, type=Path)
    materialize.add_argument("--trajectory-contract", required=True, type=Path)
    materialize.add_argument("--reviewed-contract", required=True, type=Path)
    materialize.add_argument("--mirror-summary", required=True, type=Path)
    materialize.add_argument("--stripe-summary", required=True, type=Path)
    materialize.add_argument("--fixed-mirror-stripe-authority", type=Path)
    materialize.add_argument("--mirror-voltage-variation", type=Path)
    materialize.add_argument("--accelerator-receipt", required=True, type=Path)
    materialize.add_argument("--accelerator-provider-plan", required=True, type=Path)
    materialize.add_argument("--composition-plan", required=True, type=Path)
    materialize.add_argument("--local-scope", type=Path)
    materialize.add_argument("--accelerator-resolved-campaign", required=True, type=Path)
    materialize.add_argument("--prism-1-v", required=True, type=float)
    materialize.add_argument("--prism-2-v", required=True, type=float)
    materialize.add_argument("--stripe-1-v", type=float)
    materialize.add_argument("--stripe-2-v", type=float)
    materialize.add_argument("--runtime-fast-adjust-enable", action="store_true")
    materialize.add_argument("--pulse-accelerator-until-initial-exit", action="store_true")
    materialize.add_argument("--accelerator-safe-exit-only", action="store_true")
    materialize.add_argument("--accelerator-pulse-schedule", type=Path)
    materialize.add_argument("--trajectory-profile-id")
    materialize.add_argument("--trajectory-step-scale", type=float, default=1.0)
    materialize.add_argument("--source-y-offset-mm", type=float, default=0.0)
    materialize.add_argument("--bunch-source-receipt", type=Path)
    materialize.add_argument("--bunch-particle-id-min", type=int)
    materialize.add_argument("--bunch-particle-id-max", type=int)
    materialize.add_argument("--workbench-accelerator-instance", required=True, type=int, choices=(2, 3, 7))
    materialize.add_argument("--fly2", required=True, type=Path)
    materialize.add_argument("--sidecar", required=True, type=Path)
    materialize.add_argument("--receipt", required=True, type=Path)
    materialize.add_argument("--batch-scientific-event-locators", action="store_true")
    materialize.add_argument("--field-binding", type=Path)
    materialize.add_argument("--native-corridor-cache-manifest", type=Path)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--trial-receipt", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    analyze.add_argument("--scientific-event-receipt", type=Path)
    recording = sub.add_parser("recording-config")
    recording.add_argument("--contract", required=True, type=Path)
    extract = sub.add_parser("extract-trajectory")
    extract.add_argument("--log", required=True, type=Path)
    extract.add_argument("--output", required=True, type=Path)
    extract.add_argument("--receipt", required=True, type=Path)
    extract.add_argument("--contract", type=Path)
    args = parser.parse_args()
    if args.command == "materialize":
        stripe_override = None
        if (args.stripe_1_v is None) != (args.stripe_2_v is None):
            parser.error("--stripe-1-v and --stripe-2-v must be supplied together")
        if args.stripe_1_v is not None:
            stripe_override = (args.stripe_1_v, args.stripe_2_v)
        result = materialize_trial(
            contract_path=args.contract,
            accelerator_geometry_contract_path=args.accelerator_geometry_contract,
            trajectory_contract_path=args.trajectory_contract,
            reviewed_contract_path=args.reviewed_contract,
            mirror_summary_path=args.mirror_summary,
            stripe_summary_path=args.stripe_summary,
            fixed_mirror_stripe_authority_path=args.fixed_mirror_stripe_authority,
            mirror_voltage_variation_path=args.mirror_voltage_variation,
            accelerator_receipt_path=args.accelerator_receipt,
            accelerator_provider_plan_path=args.accelerator_provider_plan,
            composition_plan_path=args.composition_plan,
            local_scope_path=args.local_scope,
            accelerator_resolved_campaign_path=args.accelerator_resolved_campaign,
            prism_1_v=args.prism_1_v,
            prism_2_v=args.prism_2_v,
            stripe_biases_override_v=stripe_override,
            runtime_fast_adjust_enable=args.runtime_fast_adjust_enable,
            pulse_accelerator_until_initial_exit=args.pulse_accelerator_until_initial_exit,
            accelerator_safe_exit_only=args.accelerator_safe_exit_only,
            accelerator_pulse_schedule_path=args.accelerator_pulse_schedule,
            trajectory_profile_id=args.trajectory_profile_id,
            trajectory_step_scale=args.trajectory_step_scale,
            source_y_offset_mm=args.source_y_offset_mm,
            bunch_source_receipt_path=args.bunch_source_receipt,
            bunch_particle_id_min=args.bunch_particle_id_min,
            bunch_particle_id_max=args.bunch_particle_id_max,
            accelerator_instance=args.workbench_accelerator_instance,
            fly2_path=args.fly2,
            sidecar_path=args.sidecar,
            batch_scientific_event_locators=args.batch_scientific_event_locators,
            receipt_path=args.receipt,
            field_binding_path=args.field_binding,
            native_corridor_cache_manifest_path=args.native_corridor_cache_manifest,
        )
        print(f"MRTOF_TWO_PRISM_TRIAL_MATERIALIZE=PASS P1={result['prism_voltages_v'][0]:.12g} P2={result['prism_voltages_v'][1]:.12g}")
    elif args.command == "analyze":
        result = analyze_trial(log_path=args.log, trial_receipt_path=args.trial_receipt, output_path=args.output, scientific_event_receipt=args.scientific_event_receipt)
        short_exit_failed = (
            result.get("execution_scope") == "accelerator_safe_exit_envelope_only"
            and result.get("status") != "accelerator_geometric_exit_observed"
        )
        print(
            f"MRTOF_TWO_PRISM_TRIAL_ANALYZE={'FAIL' if short_exit_failed else 'PASS'} "
            f"STATUS={result['status']}"
        )
        if short_exit_failed:
            return 1
    elif args.command == "recording-config":
        print(json.dumps(resolve_trajectory_recording(json.loads(args.contract.read_text(encoding="utf-8-sig")))))
    elif args.command == "extract-trajectory":
        recording = resolve_trajectory_recording(json.loads(args.contract.read_text(encoding="utf-8-sig"))) if args.contract else None
        result = extract_trajectory_samples(log_path=args.log, output_path=args.output, receipt_path=args.receipt,
                                            recording_config=recording)
        print(f"MRTOF_TRAJECTORY_EXTRACT=PASS SAMPLES={result['sample_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
