"""Materialize and analyze one finite-3D P1/P2 voltage trial.

The trial reuses the reviewed PA geometry.  It combines the independently
derived exact-K mirror/Stripe point and the separately calibrated accelerator
focus point, then changes only the two prism voltages.  The source starts in
accelerator gap 1 with the user-declared 5 eV slow kinetic energy in +project-y;
the accelerator field supplies the fast -project-z energy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import (
    _full_path_timeout_us,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_two_zone_placement,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _vector(value: Any, count: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != count:
        raise CandidateContractError(f"{label} must contain {count} values")
    return [_finite(item, label) for item in value]


def _lua_vector(values: list[float]) -> str:
    return "{ " + ", ".join(f"{value:.17g}" for value in values) + " }"


def _lua_prism_switch(value: dict[str, Any] | None) -> str:
    if value is None:
        return ""
    fields = [
        "enabled = true",
        f"electrode_id = {int(value['electrode_id'])}",
        f"time_us = {value['time_us']:.17g}",
        f"injection_voltage_v = {value['injection_voltage_v']:.17g}",
        f"extraction_voltage_v = {value['extraction_voltage_v']:.17g}",
    ]
    if "prism_1_extraction_voltage_v" in value:
        fields.append(
            "prism_1_extraction_voltage_v = "
            f"{value['prism_1_extraction_voltage_v']:.17g}"
        )
    return "prism_switch = { " + ", ".join(fields) + " }, "


def _distance_to_interval(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return value - lower
    if value > upper:
        return value - upper
    return 0.0


def _extraction_diagnostic(
    events: list[dict[str, Any]],
    switch_contract: dict[str, Any],
    detector_box_mm: list[float],
) -> dict[str, Any]:
    """Reduce a switched center flight to detector-plane residual evidence."""
    box = _vector(detector_box_mm, 6, "detector box")
    switch_time = _finite(switch_contract.get("time_us"), "prism switch time")
    expected = {17: _finite(switch_contract.get("extraction_voltage_v"), "P2 extraction voltage")}
    if "prism_1_extraction_voltage_v" in switch_contract:
        expected[16] = _finite(
            switch_contract["prism_1_extraction_voltage_v"], "P1 extraction voltage"
        )
    switch_events = [event for event in events if event["kind"] == "prism_voltage_switch"]
    observed_ids = [int(event["electrode"]) for event in switch_events]
    event_contract_ok = sorted(observed_ids) == sorted(expected)
    if event_contract_ok:
        for event in switch_events:
            electrode = int(event["electrode"])
            if not math.isclose(float(event["t_us"]), switch_time, rel_tol=1e-9, abs_tol=1e-9):
                event_contract_ok = False
            if not math.isclose(float(event["to_v"]), expected[electrode], rel_tol=1e-9, abs_tol=1e-9):
                event_contract_ok = False

    planes = [
        event for event in events
        if event["kind"] == "detector_plane" and float(event["t_us"]) >= switch_time
    ]
    incoming = [event for event in planes if int(event["direction_z"]) == -1]
    scored: list[tuple[float, dict[str, Any], float, float]] = []
    for event in incoming:
        dx = _distance_to_interval(float(event["x_mm"]), box[0], box[3])
        dy = _distance_to_interval(float(event["y_mm"]), box[1], box[4])
        scored.append((math.hypot(dx, dy), event, dx, dy))
    nearest = min(scored, key=lambda item: (item[0], float(item[1]["t_us"]))) if scored else None
    detector_events = [
        event for event in events
        if event["kind"] == "detector" and float(event["t_us"]) >= switch_time
    ]
    terminals = [event for event in events if event["kind"] in {"splat", "terminal"}]
    post_return_turns = [
        event for event in events
        if event["kind"] == "post_return_mirror_turn" and float(event["t_us"]) > switch_time
    ]
    earliest_causal: tuple[dict[str, Any], int] | None = None
    for event in incoming:
        turns_before = sum(
            float(turn["t_us"]) <= float(event["t_us"])
            for turn in post_return_turns
        )
        # The first incoming crossing occurs while the returned ion is merely
        # leaving the positive mirror and precedes either prism.  Require at
        # least two subsequent mirror turns before treating a detector-plane
        # sample as causally affected by the extraction fields.
        if turns_before >= 2:
            earliest_causal = (event, turns_before)
            break
    result: dict[str, Any] = {
        "status": "detector_hit" if detector_events else "detector_not_observed",
        "event_contract_ok": event_contract_ok,
        "expected_switched_electrodes": sorted(expected),
        "observed_switched_electrodes": observed_ids,
        "switch_time_us": switch_time,
        "post_switch_detector_plane_count": len(planes),
        "post_switch_incoming_detector_plane_count": len(incoming),
        "post_return_mirror_turn_count": len(post_return_turns),
        "detector_center_xy_mm": [(box[0] + box[3]) / 2, (box[1] + box[4]) / 2],
        "detector_active_xy_bounds_mm": [box[0], box[3], box[1], box[4]],
    }
    if incoming:
        result["first_incoming_plane"] = incoming[0]
    if earliest_causal is not None:
        event, turns_before = earliest_causal
        result["earliest_causally_extractable_incoming_plane"] = event
        result["mirror_turns_before_earliest_causal_plane"] = turns_before
        result["earliest_causal_center_residual_xy_mm"] = [
            float(event["x_mm"]) - result["detector_center_xy_mm"][0],
            float(event["y_mm"]) - result["detector_center_xy_mm"][1],
        ]
        result["earliest_causal_rectangle_residual_xy_mm"] = [
            _distance_to_interval(float(event["x_mm"]), box[0], box[3]),
            _distance_to_interval(float(event["y_mm"]), box[1], box[4]),
        ]
    if nearest is not None:
        distance, event, dx, dy = nearest
        result["nearest_incoming_plane"] = event
        result["nearest_rectangle_residual_xy_mm"] = [dx, dy]
        result["nearest_rectangle_distance_mm"] = distance
    if detector_events:
        result["first_detector_event"] = detector_events[0]
        result["post_switch_time_to_detector_us"] = (
            float(detector_events[0]["t_us"]) - switch_time
        )
    if terminals:
        result["terminal_event"] = terminals[-1]
    return result


def _mirror_regions(contract: dict[str, Any]) -> dict[str, list[float]]:
    resolved = resolve_geometry(contract)
    boxes = [
        item["box"]
        for key in ("mirror_ground_shields", "mirror_electrodes", "mirror_e_closures")
        for item in resolved[key]
    ]
    return {
        "negative": [min(box[2] for box in boxes if box[5] < 0), max(box[5] for box in boxes if box[5] < 0)],
        "positive": [min(box[2] for box in boxes if box[2] > 0), max(box[5] for box in boxes if box[2] > 0)],
    }


def materialize_trial(
    *,
    contract_path: Path,
    reviewed_contract_path: Path,
    mirror_summary_path: Path,
    stripe_summary_path: Path,
    accelerator_receipt_path: Path,
    prism_1_v: float,
    prism_2_v: float,
    stripe_biases_override_v: tuple[float, float] | None,
    continue_main_drift: bool,
    runtime_fast_adjust_enable: bool,
    prism_2_extraction_v: float | None,
    prism_1_extraction_v: float | None,
    prism_switch_time_us: float | None,
    reference_transport_receipt_path: Path | None,
    reference_transport_log_path: Path | None,
    constrain_x_symmetry_plane: bool,
    fly2_path: Path,
    sidecar_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    reviewed_contract = load_contract(reviewed_contract_path)
    mirror = _load(mirror_summary_path)
    stripe = _load(stripe_summary_path)
    accelerator = _load(accelerator_receipt_path)
    if mirror.get("status") != "success" and mirror.get("status") != "exact_k_operating_point_selected":
        # Current exact-K summary uses a richer role-specific status.  Require
        # the selected point below instead of accepting arbitrary summaries.
        if not isinstance(mirror.get("selected_operating_point"), dict):
            raise CandidateContractError("mirror summary has no selected exact-K operating point")
    selected_mirror = mirror.get("selected_operating_point")
    selected_stripe = stripe.get("selected_exact_k_operating_point")
    seed = stripe.get("selected_seed")
    if not all(isinstance(value, dict) for value in (selected_mirror, selected_stripe, seed)):
        raise CandidateContractError("mirror/Stripe summaries do not expose the selected exact-K point")
    energy = _finite(selected_mirror.get("energy_per_charge_v"), "mirror selected energy")
    if abs(_finite(selected_stripe.get("axial_energy_per_charge_v"), "Stripe selected energy") - energy) > 1e-9:
        raise CandidateContractError("mirror and Stripe selected energies differ")
    if abs(_finite(accelerator.get("energy_per_charge_v"), "accelerator selected energy") - energy) > 1e-9:
        raise CandidateContractError("accelerator and analyser selected energies differ")
    mirror_voltages = _vector(selected_mirror.get("mirror_voltages_v"), 5, "mirror voltages")
    stripe_biases = _vector(seed.get("stripe_biases_v"), 2, "Stripe biases")
    if stripe_biases_override_v is not None:
        stripe_biases = [
            _finite(stripe_biases_override_v[0], "Stripe 1 override"),
            _finite(stripe_biases_override_v[1], "Stripe 2 override"),
        ]
    endpoint_voltages = _vector(accelerator.get("endpoint_voltages_v"), 3, "accelerator endpoint voltages")
    ring_voltages = _vector(accelerator.get("ring_voltages_v"), 5, "accelerator ring voltages")
    p1 = _finite(prism_1_v, "P1 voltage")
    p2 = _finite(prism_2_v, "P2 voltage")
    prism_switch: dict[str, Any] | None = None
    if prism_2_extraction_v is not None:
        if runtime_fast_adjust_enable:
            raise CandidateContractError(
                "prism extraction switching cannot be combined with full analyser Fast Adjust"
            )
        if reference_transport_receipt_path is None or reference_transport_log_path is None:
            raise CandidateContractError(
                "prism extraction requires one verified reference transport receipt and log"
            )
        reference = _load(reference_transport_receipt_path)
        if reference.get("role") != "mrtof_finite_3d_two_prism_voltage_trial":
            raise CandidateContractError("reference transport receipt has the wrong role")
        reference_prisms = _vector(reference.get("prism_voltages_v"), 2, "reference prism voltages")
        reference_stripes = _vector(reference.get("stripe_biases_v"), 2, "reference Stripe biases")
        if any(not math.isclose(value, reference_value, rel_tol=1e-12, abs_tol=1e-12)
               for value, reference_value in zip((p1, p2), reference_prisms)):
            raise CandidateContractError("injection P1/P2 do not match the reference transport")
        if stripe_biases_override_v is not None and any(
            not math.isclose(value, reference_value, rel_tol=1e-12, abs_tol=1e-12)
            for value, reference_value in zip(stripe_biases, reference_stripes)
        ):
            raise CandidateContractError("Stripe override does not match the reference transport")
        stripe_biases = reference_stripes
        reference_events = parse_events(reference_transport_log_path.read_text(encoding="utf-8"))
        coordinate_returns = [
            event for event in reference_events if event["kind"] == "drift_coordinate_return"
        ]
        if len(coordinate_returns) != 1:
            raise CandidateContractError(
                "reference transport must contain exactly one drift-coordinate return"
            )
        derived_switch_time = _finite(
            coordinate_returns[0].get("t_us"), "reference drift-coordinate return time"
        )
        if prism_switch_time_us is not None and not math.isclose(
            _finite(prism_switch_time_us, "prism switch time"),
            derived_switch_time,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise CandidateContractError(
                "supplied prism switch time does not match the reference coordinate return"
            )
        switch_time = derived_switch_time
        if switch_time <= 0:
            raise CandidateContractError("prism switch time must be positive")
        prism_switch = {
            "enabled": True,
            "electrode_id": 17,
            "time_us": switch_time,
            "injection_voltage_v": p2,
            "extraction_voltage_v": _finite(
                prism_2_extraction_v, "P2 extraction voltage"
            ),
        }
        if prism_1_extraction_v is not None:
            prism_switch["prism_1_extraction_voltage_v"] = _finite(
                prism_1_extraction_v, "P1 extraction voltage"
            )
    elif prism_1_extraction_v is not None:
        raise CandidateContractError(
            "P1 extraction voltage requires the P2 extraction-switch contract"
        )
    elif prism_switch_time_us is not None:
        raise CandidateContractError("prism switch time requires an extraction voltage")
    elif reference_transport_receipt_path is not None or reference_transport_log_path is not None:
        raise CandidateContractError("reference transport inputs are only valid for extraction")
    source_contract = contract["particle_source"]
    species = source_contract["species"]
    mass = _finite(species.get("mass_th"), "particle mass")
    charge = int(species.get("charge_e"))
    slow_energy = _finite(seed.get("derived_drift_kinetic_energy_per_charge_v"), "slow energy")
    if mass <= 0 or charge == 0 or slow_energy <= 0:
        raise CandidateContractError("P1/P2 source mass, charge, and slow energy must be physical")
    # Voltage calibration changes the analytic focus equation but must never
    # translate the already reviewed accelerator PA/IOB.  Resolve every
    # physical placement from the frozen geometry-review contract.
    placement = derive_two_zone_placement(reviewed_contract)
    release = _finite(contract["accelerator"].get("release_position_in_gap_1_mm"), "accelerator release")
    release_z = placement.repeller_z_mm - release
    fly2 = (
        "particles {\n  coordinates = 0,\n  standard_beam {\n"
        f"    n = 1,\n    tob = 0,\n    mass = {mass:.17g},\n    charge = {charge},\n"
        f"    ke = {slow_energy * abs(charge):.17g},\n    cwf = 1,\n    color = 0,\n"
        "    direction = vector(0, 1, 0),\n"
        "    position = circle_distribution {\n"
        f"      center = vector(0, {placement.focus_y_mm:.17g}, {release_z:.17g}),\n"
        "      normal = vector(0, 0, -1),\n      radius = 0,\n      fill = true\n"
        "    }\n  }\n}\n"
    )
    resolved = resolve_geometry(reviewed_contract)
    detector = resolved["detector"]
    regions = _mirror_regions(reviewed_contract)
    prism_regions: dict[str, list[float]] = {}
    shields_by_station = {
        item["station"]: item for item in reviewed_contract["prisms"]["ground_shields"]
    }
    for index, electrode in enumerate(reviewed_contract["prisms"]["electrodes"], 1):
        # A trajectory reverses in the finite field inside the grounded station,
        # not inside the solid triangular electrode.  Use the station shield's
        # complete y-z envelope for event classification.
        shield = shields_by_station[electrode["station"]]
        points = [(float(point[0]), float(point[1])) for point in shield["outer_polygon_yz_mm"]]
        prism_regions[f"p{index}"] = [
            min(point[0] for point in points), max(point[0] for point in points),
            min(point[1] for point in points), max(point[1] for point in points),
        ]
    simion = contract["simion"]
    target_k = int(contract["nominal"]["target_oscillation_count"])
    timeout = _full_path_timeout_us(contract, source_contract, target_k)
    p1_plane = _finite(contract["prism_transport"]["first_prism"]["target_interface"]["coordinate_mm"], "P1 plane")
    p1_acceptance = contract["prisms"]["ground_shields"][0]["rectangular_slots_mm"][0]["box"][1:5:3]
    prism_switch_lua = _lua_prism_switch(prism_switch)
    sidecar = (
        "-- Generated run-local finite-3D P1/P2 voltage trial; do not edit.\n"
        f"return {{ qualification = 'p1_p2_finite_3d_voltage_trial_only', mirror_voltages_v = {_lua_vector(mirror_voltages)}, "
        f"stripe_biases_v = {_lua_vector(stripe_biases)}, prism_voltages_v = {_lua_vector([p1, p2])}, "
        f"accelerator_voltages_v = {_lua_vector(endpoint_voltages)}, accelerator_ring_voltages_v = {_lua_vector(ring_voltages)}, "
        f"first_prism_l0 = {{ target_plane_z_mm = {p1_plane:.17g}, target_plane_x_mm = 0, target_plane_y_acceptance_mm = {_lua_vector([float(v) for v in p1_acceptance])} }}, "
        f"mirror_regions_project = {{ negative = {{ z_min_mm = {regions['negative'][0]:.17g}, z_max_mm = {regions['negative'][1]:.17g} }}, positive = {{ z_min_mm = {regions['positive'][0]:.17g}, z_max_mm = {regions['positive'][1]:.17g} }} }}, "
        f"prism_regions_project = {{ p1 = {{ y_min_mm = {prism_regions['p1'][0]:.17g}, y_max_mm = {prism_regions['p1'][1]:.17g}, z_min_mm = {prism_regions['p1'][2]:.17g}, z_max_mm = {prism_regions['p1'][3]:.17g} }}, p2 = {{ y_min_mm = {prism_regions['p2'][0]:.17g}, y_max_mm = {prism_regions['p2'][1]:.17g}, z_min_mm = {prism_regions['p2'][2]:.17g}, z_max_mm = {prism_regions['p2'][3]:.17g} }} }}, "
        "phase_origin_mirror_side = 1, "
        f"detector_box_mm = {_lua_vector([float(v) for v in detector['box']])}, detector_normal_project = '+z', "
        f"trajectory_quality = {_finite(simion['trajectory_quality'], 'trajectory quality'):.17g}, maximum_step_us = {_finite(simion['maximum_step_us'], 'maximum step'):.17g}, "
        f"full_path_timeout_us = {timeout:.17g}, nonaccelerator_scale = {_finite(simion['nonaccelerator_scale'], 'nonaccelerator scale'):.17g}, "
        f"target_oscillation_count = {target_k}, stop_at_drift_phase_origin = {'false' if continue_main_drift else 'true'}, "
        f"runtime_fast_adjust_enable = {'true' if runtime_fast_adjust_enable else 'false'}, "
        "runtime_fast_adjust_accelerator_enable = false, "
        f"{prism_switch_lua}"
        f"constrain_x_symmetry_plane = {'true' if constrain_x_symmetry_plane else 'false'} }}\n"
    )
    fly2_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    fly2_path.write_text(fly2, encoding="utf-8", newline="\n")
    sidecar_path.write_text(sidecar, encoding="utf-8", newline="\n")
    analyzer_values = (
        mirror_voltages
        + mirror_voltages
        + [stripe_biases[0], stripe_biases[0], stripe_biases[1], stripe_biases[1], 0.0, p1, p2, 0.0, 0.0, 0.0]
    )
    receipt = {
        "schema_version": 1,
        "role": "mrtof_finite_3d_two_prism_voltage_trial",
        "status": "materialized",
        "qualification": "single_center_trial__not_an_operating_point",
        "x_symmetry_plane_constraint": bool(constrain_x_symmetry_plane),
        "selected_axial_energy_per_charge_v": energy,
        "source_slow_kinetic_energy_per_charge_v": slow_energy,
        "source_position_project_mm": [0.0, placement.focus_y_mm, release_z],
        "source_direction_project": [0.0, 1.0, 0.0],
        "mirror_voltages_v": mirror_voltages,
        "stripe_biases_v": stripe_biases,
        "prism_voltages_v": [p1, p2],
        "detector_box_mm": [float(v) for v in detector["box"]],
        "accelerator_endpoint_voltages_v": endpoint_voltages,
        "accelerator_ring_voltages_v": ring_voltages,
        "analyzer_electrode_voltages_v": analyzer_values,
        "target_turn_y_mm": 0.0,
        "phase_origin_mirror_side": 1,
        "phase_origin_side_derivation": "P2 is exited along +project-z; the first post-P2 Stripe-on mirror turn is therefore the positive mirror",
        "target_slow_kinetic_energy_per_charge_v": slow_energy,
        "target_slow_turn_y_mm": _finite(
            contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
            "manufactured drift length",
        ),
        "target_oscillation_count": target_k,
        "continue_main_drift": bool(continue_main_drift),
        "runtime_fast_adjust_enable": bool(runtime_fast_adjust_enable),
        "prism_switch": prism_switch,
        "particle_mass_th": mass,
        "charge_state": charge,
        "inputs": {
            "contract_sha256": _sha256(contract_path),
            "reviewed_contract_sha256": _sha256(reviewed_contract_path),
            "mirror_summary_sha256": _sha256(mirror_summary_path),
            "stripe_summary_sha256": _sha256(stripe_summary_path),
            "accelerator_receipt_sha256": _sha256(accelerator_receipt_path),
            **({
                "reference_transport_receipt_sha256": _sha256(reference_transport_receipt_path),
                "reference_transport_log_sha256": _sha256(reference_transport_log_path),
            } if reference_transport_receipt_path is not None else {}),
        },
        "fly2_sha256": _sha256(fly2_path),
        "operating_point_lua_sha256": _sha256(sidecar_path),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def analyze_trial(*, log_path: Path, trial_receipt_path: Path, output_path: Path) -> dict[str, Any]:
    trial = _load(trial_receipt_path)
    events = parse_events(log_path.read_text(encoding="utf-8"))
    kinds: dict[str, int] = {}
    for event in events:
        kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
    result: dict[str, Any] = {
        "schema_version": 1,
        "role": "mrtof_finite_3d_two_prism_trial_observation",
        "status": "transport_incomplete",
        "qualification": "single_center_trial__not_an_operating_point",
        "prism_voltages_v": trial["prism_voltages_v"],
        "event_counts": kinds,
        "log_sha256": _sha256(log_path),
        "trial_receipt_sha256": _sha256(trial_receipt_path),
    }
    if isinstance(trial.get("prism_switch"), dict):
        result["extraction_diagnostic"] = _extraction_diagnostic(
            events,
            trial["prism_switch"],
            trial.get("detector_box_mm"),
        )
    source = ProjectPhaseSpaceState(
        tuple(float(v) for v in trial["source_position_project_mm"]),
        (0.0, 1.0, 0.0),
    )
    try:
        handoff_events = events
        if trial.get("continue_main_drift") is True:
            phase_indices = [
                index for index, event in enumerate(events)
                if event["kind"] == "drift_phase_origin"
            ]
            if len(phase_indices) == 1:
                # The P1/P2 handoff is complete at phase origin.  A later
                # full-drift collision is a downstream residual/failure, not
                # evidence that the already observed handoff never occurred.
                handoff_events = events[: phase_indices[0] + 1] + [
                    {"kind": "terminal", "ion": 1, "splat": 5}
                ]
        observation = observation_from_simion_events(handoff_events, source)
        residuals = prism_handoff_residuals(
            observation,
            target_turn_y_mm=float(trial["target_turn_y_mm"]),
            target_slow_kinetic_energy_per_charge_v=float(trial["target_slow_kinetic_energy_per_charge_v"]),
            particle_mass_th=float(trial["particle_mass_th"]),
            charge_state=int(trial["charge_state"]),
        )
    except CandidateContractError as error:
        result["incomplete_reason"] = str(error)
        terminals = [event for event in events if event["kind"] in {"splat", "terminal"}]
        result["terminal_events"] = terminals
    else:
        result.update({
            "status": "phase_origin_observed",
            "p1_state": {
                "position_mm": observation.prism_1.position_mm,
                "velocity_mm_per_us": observation.prism_1.velocity_mm_per_us,
            },
            "drift_phase_origin_state": {
                "position_mm": observation.drift_phase_origin.position_mm,
                "velocity_mm_per_us": observation.drift_phase_origin.velocity_mm_per_us,
            },
            "residuals": {name: value for name, value in residuals},
        })
        if trial.get("continue_main_drift") is True:
            phase_events = [event for event in events if event["kind"] == "drift_phase_origin"]
            if len(phase_events) != 1:
                raise CandidateContractError("continued trial must contain one drift phase origin")
            phase_time = _finite(phase_events[0].get("t_us"), "drift phase-origin time")
            slow_turns = [
                event for event in events
                if event["kind"] == "slow_turn" and float(event["t_us"]) > phase_time
            ]
            coordinate_returns = [
                event for event in events
                if event["kind"] == "drift_coordinate_return" and float(event["t_us"]) > phase_time
            ]
            if not slow_turns or not coordinate_returns:
                result["status"] = "full_drift_incomplete"
                result["incomplete_reason"] = (
                    "continued trial must observe a post-origin slow turn and coordinate return"
                )
            else:
                slow_turn_y = _finite(slow_turns[0].get("y_mm"), "observed slow turn y")
                fractional_k = _finite(
                    coordinate_returns[0].get("fractional_k"), "observed fractional K"
                )
                target_y = _finite(trial.get("target_slow_turn_y_mm"), "target slow turn y")
                target_k = _finite(trial.get("target_oscillation_count"), "target K")
                result["status"] = "full_drift_observed"
                result["slow_turn_y_mm"] = slow_turn_y
                result["fractional_k"] = fractional_k
                result["residuals"].update({
                    "Stripe_slow_turn_y_minus_L_mm": slow_turn_y - target_y,
                    "Stripe_fractional_K_minus_target": fractional_k - target_k,
                })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--contract", required=True, type=Path)
    materialize.add_argument("--reviewed-contract", required=True, type=Path)
    materialize.add_argument("--mirror-summary", required=True, type=Path)
    materialize.add_argument("--stripe-summary", required=True, type=Path)
    materialize.add_argument("--accelerator-receipt", required=True, type=Path)
    materialize.add_argument("--prism-1-v", required=True, type=float)
    materialize.add_argument("--prism-2-v", required=True, type=float)
    materialize.add_argument("--stripe-1-v", type=float)
    materialize.add_argument("--stripe-2-v", type=float)
    materialize.add_argument("--continue-main-drift", action="store_true")
    materialize.add_argument("--runtime-fast-adjust-enable", action="store_true")
    materialize.add_argument("--prism-2-extraction-v", type=float)
    materialize.add_argument("--prism-1-extraction-v", type=float)
    materialize.add_argument("--prism-switch-time-us", type=float)
    materialize.add_argument("--reference-transport-receipt", type=Path)
    materialize.add_argument("--reference-transport-log", type=Path)
    materialize.add_argument("--constrain-x-symmetry-plane", action="store_true")
    materialize.add_argument("--fly2", required=True, type=Path)
    materialize.add_argument("--sidecar", required=True, type=Path)
    materialize.add_argument("--receipt", required=True, type=Path)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--trial-receipt", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "materialize":
        stripe_override = None
        if (args.stripe_1_v is None) != (args.stripe_2_v is None):
            parser.error("--stripe-1-v and --stripe-2-v must be supplied together")
        if args.stripe_1_v is not None:
            stripe_override = (args.stripe_1_v, args.stripe_2_v)
        result = materialize_trial(
            contract_path=args.contract,
            reviewed_contract_path=args.reviewed_contract,
            mirror_summary_path=args.mirror_summary,
            stripe_summary_path=args.stripe_summary,
            accelerator_receipt_path=args.accelerator_receipt,
            prism_1_v=args.prism_1_v,
            prism_2_v=args.prism_2_v,
            stripe_biases_override_v=stripe_override,
            continue_main_drift=args.continue_main_drift,
            runtime_fast_adjust_enable=args.runtime_fast_adjust_enable,
            prism_2_extraction_v=args.prism_2_extraction_v,
            prism_1_extraction_v=args.prism_1_extraction_v,
            prism_switch_time_us=args.prism_switch_time_us,
            reference_transport_receipt_path=args.reference_transport_receipt,
            reference_transport_log_path=args.reference_transport_log,
            constrain_x_symmetry_plane=args.constrain_x_symmetry_plane,
            fly2_path=args.fly2,
            sidecar_path=args.sidecar,
            receipt_path=args.receipt,
        )
        print(f"MRTOF_TWO_PRISM_TRIAL_MATERIALIZE=PASS P1={result['prism_voltages_v'][0]:.12g} P2={result['prism_voltages_v'][1]:.12g}")
    else:
        result = analyze_trial(log_path=args.log, trial_receipt_path=args.trial_receipt, output_path=args.output)
        print(f"MRTOF_TWO_PRISM_TRIAL_ANALYZE=PASS STATUS={result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
