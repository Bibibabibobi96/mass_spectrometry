"""Parallel topology-aware P1 slices for analytic P2 angle predictions."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_angle_slice import (
    AngleSliceControls,
    solve_p2_angle_slice_from_legal_anchor,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage import (
    _evaluate_detailed,
    _initialize_worker,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_transport import (
    predict_p2_ideal_bias_for_reference_tangent_ratio,
    validate_two_prism_voltage_polarity_domain,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_voltage_continuation import (
    ContinuationControls,
    solve_adaptive_position_domain_slice,
    solve_position_domain_slice,
)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CandidateContractError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def validate_discovery_polarity_domain(
    contract: Mapping[str, Any],
    *,
    charge_state: int,
    p1_bounds_v: tuple[float, float],
    p2_bounds_v: tuple[float, float],
) -> dict[str, Any]:
    """Validate live polarity authority or an explicit historical signed domain."""
    authority = (
        contract.get("prism_transport", {})
        .get("two_prism_injection_l0", {})
        .get("voltage_polarity_contract")
    )
    if authority is not None:
        return validate_two_prism_voltage_polarity_domain(
            contract,
            charge_state=charge_state,
            p1_bounds_v=p1_bounds_v,
            p2_bounds_v=p2_bounds_v,
        )
    if type(charge_state) is not int or charge_state == 0:
        raise CandidateContractError("particle charge must be a nonzero integer")
    p1_lower, p1_upper = p1_bounds_v
    p2_lower, p2_upper = p2_bounds_v
    if charge_state > 0:
        valid = 0.0 < p1_lower < p1_upper and p2_lower < p2_upper < 0.0
        signs = ("positive", "negative")
    else:
        valid = p1_lower < p1_upper < 0.0 and 0.0 < p2_lower < p2_upper
        signs = ("negative", "positive")
    if not valid:
        raise CandidateContractError(
            "historical two-prism discovery requires an explicit charge-consistent signed domain"
        )
    return {
        "authority": "explicit_historical_run_domain__contract_predates_polarity_field",
        "charge_state": charge_state,
        "p1_required_sign": signs[0],
        "p2_required_sign": signs[1],
        "p1_bounds_v": list(p1_bounds_v),
        "p2_bounds_v": list(p2_bounds_v),
    }


def _coverage_legal_samples(coverage: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        blocks = coverage["coverage"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("coverage summary lacks coverage blocks") from error
    records: dict[tuple[float, float], dict[str, Any]] = {}
    for name in ("sobol", "local"):
        block = blocks.get(name, {}) if isinstance(blocks, Mapping) else {}
        samples = block.get("samples", []) if isinstance(block, Mapping) else []
        if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
            raise CandidateContractError(f"coverage {name} samples must be a sequence")
        for item in samples:
            if not isinstance(item, Mapping) or item.get("status") != "legal_topology":
                continue
            pair = item.get("prism_voltages_v")
            residuals = item.get("residual_vector")
            signature = item.get("topology_signature_sha256")
            if (
                not isinstance(pair, Sequence) or len(pair) != 2
                or not isinstance(residuals, Sequence) or len(residuals) != 2
                or not isinstance(signature, str) or not signature
            ):
                raise CandidateContractError("legal coverage sample is incomplete")
            key = (_finite(pair[0], "coverage P1"), _finite(pair[1], "coverage P2"))
            records[key] = {
                "prism_voltages_v": list(key),
                "residual_vector": [
                    _finite(residuals[0], "coverage turn-y residual"),
                    _finite(residuals[1], "coverage angle residual"),
                ],
                "topology_signature_sha256": signature,
            }
    if not records:
        raise CandidateContractError("coverage contains no legal P1/P2 samples")
    return list(records.values())


def select_parallel_p1_anchors(
    coverage: Mapping[str, Any],
    *,
    p1_bounds_v: tuple[float, float],
    requested_anchor_count: int,
    preferred_residual_index: int = 1,
    p2_bounds_v: tuple[float, float] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Select residual-close anchors across every observed topology and P1 span."""
    lower, upper = (_finite(value, "P1 discovery bound") for value in p1_bounds_v)
    if lower >= upper:
        raise CandidateContractError("P1 discovery bounds must have positive width")
    if type(requested_anchor_count) is not int or requested_anchor_count <= 0:
        raise CandidateContractError("requested P1 anchor count must be a positive integer")
    if preferred_residual_index not in (0, 1):
        raise CandidateContractError("preferred residual index must be zero or one")
    if p2_bounds_v is not None:
        p2_lower, p2_upper = (_finite(value, "P2 discovery bound") for value in p2_bounds_v)
        if p2_lower >= p2_upper:
            raise CandidateContractError("P2 discovery bounds must have positive width")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in _coverage_legal_samples(coverage):
        p1_value, p2_value = item["prism_voltages_v"]
        if (
            lower <= p1_value <= upper
            and (p2_bounds_v is None or p2_lower <= p2_value <= p2_upper)
        ):
            grouped.setdefault(item["topology_signature_sha256"], []).append(item)
    if not grouped:
        raise CandidateContractError("P1 discovery domain contains no legal coverage sample")
    signatures = sorted(grouped)
    base, remainder = divmod(requested_anchor_count, len(signatures))
    allocations = {
        signature: base + (1 if index < remainder else 0)
        for index, signature in enumerate(signatures)
    }
    if base == 0:
        allocations = {
            signature: 1 if index < requested_anchor_count else 0
            for index, signature in enumerate(signatures)
        }
    selected: list[dict[str, Any]] = []
    for signature in signatures:
        candidates = sorted(grouped[signature], key=lambda item: item["prism_voltages_v"][0])
        count = min(allocations[signature], len(candidates))
        if count == 0:
            continue
        p1_min = candidates[0]["prism_voltages_v"][0]
        p1_max = candidates[-1]["prism_voltages_v"][0]
        if count == 1 or p1_min == p1_max:
            selected.append(min(
                candidates,
                key=lambda item: abs(item["residual_vector"][preferred_residual_index]),
            ))
            continue
        used: set[tuple[float, float]] = set()
        targets = [
            p1_min + index * (p1_max - p1_min) / (count - 1)
            for index in range(count)
        ]
        for target_index, target in enumerate(targets):
            available = [
                item for item in candidates
                if tuple(item["prism_voltages_v"]) not in used
            ]
            if not available:
                break
            position_bin = available
            is_endpoint = target_index in (0, count - 1)
            if preferred_residual_index == 0 and not is_endpoint:
                lower_edge = 0.5 * (targets[target_index - 1] + target)
                upper_edge = 0.5 * (target + targets[target_index + 1])
                position_bin = [
                    item for item in available
                    if lower_edge <= item["prism_voltages_v"][0] <= upper_edge
                ] or available
            chosen = min(
                position_bin,
                key=(
                    lambda item: (
                        (
                            abs(item["prism_voltages_v"][0] - target)
                            if is_endpoint
                            else abs(item["residual_vector"][0])
                        ),
                        (
                            abs(item["residual_vector"][0])
                            if is_endpoint
                            else abs(item["prism_voltages_v"][0] - target)
                        ),
                        abs(item["residual_vector"][1]),
                    )
                    if preferred_residual_index == 0
                    else (
                        abs(item["prism_voltages_v"][0] - target),
                        abs(item["residual_vector"][1]),
                        abs(item["residual_vector"][0]),
                    )
                ),
            )
            key = tuple(chosen["prism_voltages_v"])
            selected.append(chosen)
            used.add(key)
    return tuple(sorted(
        selected,
        key=lambda item: (item["topology_signature_sha256"], item["prism_voltages_v"][0]),
    ))


def _compact_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "transport_diagnostic"}


_DISCOVERY_WORKER_CONTEXT: dict[str, Any] = {}


def _initialize_discovery_worker(context: dict[str, Any]) -> None:
    global _DISCOVERY_WORKER_CONTEXT
    _DISCOVERY_WORKER_CONTEXT = context
    _initialize_worker(context)


def _solve_worker(payload: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    anchor, controls_payload = payload
    objective = controls_payload.get("primary_objective", "angle")
    context = _DISCOVERY_WORKER_CONTEXT
    if not context:
        raise CandidateContractError("parallel angle-discovery worker was not initialized")
    cache: dict[tuple[float, float], dict[str, Any]] = {}
    prediction_receipt: dict[str, Any] = {}

    def evaluate(candidate: tuple[float, float]) -> Mapping[str, Any]:
        if candidate not in cache:
            cache[candidate] = _evaluate_detailed(candidate)
        return cache[candidate]

    def predict(record: Mapping[str, Any]) -> float:
        diagnostic = record.get("transport_diagnostic")
        if diagnostic is None:
            raise CandidateContractError("analytic P2 prediction requires a legal transport diagnostic")
        prediction = predict_p2_ideal_bias_for_reference_tangent_ratio(
            context["contract"], diagnostic,
            mirror_design=context["mirror_design"],
            charge_state=context["charge"],
            target_reference_tangent_ratio=context["target_tangent_ratio"],
        )
        prediction_receipt.update(asdict(prediction))
        return prediction.predicted_prism_bias_v

    try:
        if objective == "angle":
            signature = anchor["topology_signature_sha256"]
            pair = tuple(float(value) for value in anchor["prism_voltages_v"])
            controls = AngleSliceControls(**controls_payload["slice_controls"])
            result = solve_p2_angle_slice_from_legal_anchor(
                evaluate,
                predict,
                legal_anchor_pair_v=pair,
                expected_signature_sha256=signature,
                controls=controls,
            )
        elif objective in ("position", "position_adaptive"):
            controls = ContinuationControls(**controls_payload["slice_controls"])
            kwargs = {
                "p1_v": float(anchor["p1_voltage_v"]),
                "allowed_signature_sha256": anchor["allowed_topology_signatures_sha256"],
                "p2_scan_count": int(controls_payload["p2_scan_count"]),
                "controls": controls,
            }
            if objective == "position_adaptive":
                result = solve_adaptive_position_domain_slice(
                    evaluate,
                    refinement_levels=int(controls_payload["adaptive_refinement_levels"]),
                    refinement_candidate_count=int(controls_payload["adaptive_candidate_count"]),
                    **kwargs,
                )
            else:
                result = solve_position_domain_slice(evaluate, **kwargs)
        else:
            raise CandidateContractError("parallel discovery primary objective is invalid")
    except CandidateContractError as error:
        return {
            "status": "slice_failed",
            "anchor": anchor,
            "failure": str(error),
        }
    result["anchor"] = anchor
    result["ideal_p2_prediction"] = prediction_receipt or None
    result["evaluations"] = [_compact_record(item) for item in cache.values()]
    return result


def discover_parallel_p1_angle_slices(
    coverage: Mapping[str, Any],
    *,
    worker_context: dict[str, Any],
    p1_bounds_v: tuple[float, float],
    requested_anchor_count: int,
    worker_count: int,
    slice_controls: AngleSliceControls | ContinuationControls,
    primary_objective: str = "angle",
    p2_scan_count: int = 17,
    adaptive_refinement_levels: int = 6,
    adaptive_candidate_count: int = 3,
) -> dict[str, Any]:
    """Run independent topology-preserving P1 slices in a process pool."""
    if type(worker_count) is not int or worker_count <= 0:
        raise CandidateContractError("worker count must be a positive integer")
    if primary_objective not in ("angle", "position", "position_adaptive"):
        raise CandidateContractError("primary objective must be angle, position, or position_adaptive")
    if primary_objective == "angle":
        anchors = select_parallel_p1_anchors(
            coverage,
            p1_bounds_v=p1_bounds_v,
            requested_anchor_count=requested_anchor_count,
            preferred_residual_index=1,
            p2_bounds_v=slice_controls.p2_bounds_v,
        )
    else:
        signatures = sorted({
            item["topology_signature_sha256"]
            for item in _coverage_legal_samples(coverage)
        })
        if requested_anchor_count == 1:
            p1_values = [0.5 * (p1_bounds_v[0] + p1_bounds_v[1])]
        else:
            p1_values = [
                p1_bounds_v[0]
                + index * (p1_bounds_v[1] - p1_bounds_v[0]) / (requested_anchor_count - 1)
                for index in range(requested_anchor_count)
            ]
        anchors = tuple({
            "p1_voltage_v": value,
            "allowed_topology_signatures_sha256": signatures,
        } for value in p1_values)
    payload = {
        "primary_objective": primary_objective,
        "slice_controls": asdict(slice_controls),
        "p2_scan_count": p2_scan_count,
        "adaptive_refinement_levels": adaptive_refinement_levels,
        "adaptive_candidate_count": adaptive_candidate_count,
    }
    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=_initialize_discovery_worker,
        initargs=(worker_context,),
    ) as executor:
        results = list(executor.map(_solve_worker, ((anchor, payload) for anchor in anchors)))
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "qualification": f"parallel_solver_neutral_p1_{primary_objective}_slice_discovery_only",
        "primary_objective": primary_objective,
        "p1_discovery_bounds_v": list(p1_bounds_v),
        "requested_anchor_count": requested_anchor_count,
        "selected_anchor_count": len(anchors),
        "worker_count": worker_count,
        "p2_scan_count": p2_scan_count if primary_objective != "angle" else None,
        "adaptive_refinement_levels": (
            adaptive_refinement_levels if primary_objective == "position_adaptive" else None
        ),
        "adaptive_candidate_count": (
            adaptive_candidate_count if primary_objective == "position_adaptive" else None
        ),
        "status_counts": counts,
        "anchors": list(anchors),
        "slices": results,
    }


def main() -> None:
    from common.contracts.file_identity import file_sha256
    from common.host_resource_python import ensure_heavy_entry
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_transport_source import (
        materialize_accelerator_exit_transport_source,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_exact_k_operating_point import (
        load_managed_exact_k_operating_point,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
        TransportNumerics,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
        natural_two_prism_scales,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage import (
        _load_stripe_seed,
        validate_accelerator_exit_source_binding,
    )

    ensure_heavy_entry(
        "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
        "two_prism_parallel_angle_discovery",
        role="GATE", stage="theory_compute",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--primary-objective", choices=("angle", "position", "position_adaptive"), default="angle",
    )
    for name in (
        "contract", "exact-k-manifest", "stripe-seed-manifest",
        "accelerator-exit-observation", "accelerator-exit-source-receipt",
        "coverage-summary", "source-receipt-output", "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--expected-observation-sha256", required=True)
    for name in (
        "p1-min-v", "p1-max-v", "p2-min-v", "p2-max-v",
        "angle-ratio-root-tolerance",
        "p2-root-tolerance-v", "topology-boundary-tolerance-v",
        "positive-turn-y-tolerance-mm", "p2-initial-half-width-v",
        "p2-bracket-expansion-factor",
        "relative-tolerance", "absolute-tolerance", "max-step",
        "root-time-tolerance", "boundary-root-tolerance",
        "momentum-tolerance", "normal-energy-tolerance",
        "stage-a-maximum-reduced-time", "stage-b-maximum-reduced-time",
    ):
        parser.add_argument(f"--{name}", type=float, required=True)
    for name in (
        "anchor-count", "worker-count", "maximum-slice-evaluations",
        "p2-bracket-maximum-expansions", "maximum-inner-iterations",
        "p2-scan-count",
        "adaptive-refinement-levels", "adaptive-candidate-count",
        "event-samples-per-step", "maximum-steps",
    ):
        parser.add_argument(f"--{name}", type=int, required=True)
    args = parser.parse_args()

    try:
        coverage = json.loads(args.coverage_summary.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateContractError("coverage summary is not readable JSON") from error
    if (
        not isinstance(coverage, dict)
        or coverage.get("schema_version") != 1
        or coverage.get("role") != "mrtof_two_prism_segmented_voltage_branch_coverage"
        or coverage.get("status") != "coverage_complete"
    ):
        raise CandidateContractError("coverage summary identity is invalid")
    expected_inputs = coverage.get("inputs", {})
    for label, path, expected in (
        ("contract", args.contract, expected_inputs.get("contract_sha256")),
        ("exact-K manifest", args.exact_k_manifest, expected_inputs.get("exact_k_manifest_sha256")),
        ("Stripe manifest", args.stripe_seed_manifest, expected_inputs.get("stripe_seed", {}).get("manifest_sha256")),
        ("accelerator exit observation", args.accelerator_exit_observation, expected_inputs.get("accelerator_exit_observation_sha256")),
        ("accelerator exit source receipt", args.accelerator_exit_source_receipt, expected_inputs.get("accelerator_exit_source_receipt", {}).get("sha256")),
    ):
        if file_sha256(path).lower() != str(expected).lower():
            raise CandidateContractError(f"{label} differs from the coverage input")

    managed = load_managed_exact_k_operating_point(args.exact_k_manifest, args.contract)
    species = managed.contract.get("particle_source", {}).get("species", {})
    mass = _finite(species.get("mass_th"), "particle mass")
    charge = species.get("charge_e")
    if type(charge) is not int or charge == 0:
        raise CandidateContractError("contract particle charge must be a nonzero integer")
    source, source_receipt = materialize_accelerator_exit_transport_source(
        observation_path=args.accelerator_exit_observation,
        expected_observation_sha256=args.expected_observation_sha256,
        expected_particle_mass_th=mass,
        expected_charge_state=charge,
        receipt_path=args.source_receipt_output,
    )
    source_binding = validate_accelerator_exit_source_binding(
        source_receipt_path=args.accelerator_exit_source_receipt,
        source_handoff_receipt=source_receipt,
        managed=managed,
    )
    stripe_biases, slow_energy, target_ratio, stripe_identity = _load_stripe_seed(
        args.stripe_seed_manifest,
        exact_k_manifest_path=args.exact_k_manifest,
        managed=managed,
    )
    prism_ids = (
        int(managed.contract["prism_transport"]["first_prism"]["electrode_id"]),
        int(managed.contract["prism_transport"]["second_prism"]["electrode_id"]),
    )
    numerics = TransportNumerics(
        args.relative_tolerance, args.absolute_tolerance, args.max_step,
        args.event_samples_per_step, args.root_time_tolerance,
        args.boundary_root_tolerance, args.momentum_tolerance,
        args.normal_energy_tolerance, args.maximum_steps,
    )
    _, residual_scales = natural_two_prism_scales(managed.contract)
    context = {
        "contract": managed.contract,
        "source": source,
        "mass": mass,
        "charge": charge,
        "mirror_design": managed.design,
        "axial_energy": managed.axial_energy_per_charge_v,
        "slow_energy": slow_energy,
        "stripe_biases": stripe_biases,
        "prism_ids": prism_ids,
        "target_tangent_ratio": target_ratio,
        "numerics": numerics,
        "stage_a": args.stage_a_maximum_reduced_time,
        "stage_b": args.stage_b_maximum_reduced_time,
        "residual_scales": tuple(residual_scales),
    }
    total_energy = managed.axial_energy_per_charge_v + slow_energy
    p2_bounds = (args.p2_min_v, args.p2_max_v)
    if not -total_energy <= p2_bounds[0] < p2_bounds[1] <= total_energy:
        raise CandidateContractError("P2 discovery bounds exceed the natural energy domain")
    polarity_receipt = validate_discovery_polarity_domain(
        managed.contract,
        charge_state=charge,
        p1_bounds_v=(args.p1_min_v, args.p1_max_v),
        p2_bounds_v=p2_bounds,
    )
    if args.primary_objective == "angle":
        slice_controls: AngleSliceControls | ContinuationControls = AngleSliceControls(
            p2_bounds_v=p2_bounds,
            angle_ratio_root_tolerance=args.angle_ratio_root_tolerance,
            p2_root_tolerance_v=args.p2_root_tolerance_v,
            topology_boundary_tolerance_v=args.topology_boundary_tolerance_v,
            maximum_evaluations=args.maximum_slice_evaluations,
        )
    else:
        slice_controls = ContinuationControls(
            p1_bounds_v=(args.p1_min_v, args.p1_max_v),
            p2_bounds_v=p2_bounds,
            angle_ratio_tolerance=args.angle_ratio_root_tolerance,
            positive_turn_y_tolerance_mm=args.positive_turn_y_tolerance_mm,
            p2_root_tolerance_v=args.p2_root_tolerance_v,
            initial_p1_step_v=1.0,
            minimum_p1_step_v=1.0,
            maximum_p1_step_v=1.0,
            p1_step_growth_factor=1.0,
            p2_initial_half_width_v=args.p2_initial_half_width_v,
            p2_bracket_expansion_factor=args.p2_bracket_expansion_factor,
            p2_bracket_maximum_expansions=args.p2_bracket_maximum_expansions,
            maximum_inner_iterations=args.maximum_inner_iterations,
            maximum_outer_iterations=1,
            maximum_transport_evaluations=args.maximum_slice_evaluations,
            maximum_nodes_per_direction=1,
        )
    discovery = discover_parallel_p1_angle_slices(
        coverage,
        worker_context=context,
        p1_bounds_v=(args.p1_min_v, args.p1_max_v),
        requested_anchor_count=args.anchor_count,
        worker_count=args.worker_count,
        slice_controls=slice_controls,
        primary_objective=args.primary_objective,
        p2_scan_count=args.p2_scan_count,
        adaptive_refinement_levels=args.adaptive_refinement_levels,
        adaptive_candidate_count=args.adaptive_candidate_count,
    )
    output_role = (
        "mrtof_two_prism_parallel_analytic_p2_angle_discovery"
        if args.primary_objective == "angle"
        else "mrtof_two_prism_parallel_p2_position_discovery"
    )
    output = {
        "schema_version": 1,
        "role": output_role,
        "status": "discovery_complete",
        "qualification": (
            f"solver_neutral_parallel_{args.primary_objective}_branch_discovery_only"
            "__not_a_3d_voltage_solution"
        ),
        "inputs": {
            "coverage_summary_sha256": file_sha256(args.coverage_summary).lower(),
            "contract_sha256": file_sha256(args.contract).lower(),
            "exact_k_manifest_sha256": file_sha256(args.exact_k_manifest).lower(),
            "stripe_seed": stripe_identity,
            "accelerator_exit_source_receipt": source_binding,
            "materialized_source_receipt_sha256": file_sha256(args.source_receipt_output).lower(),
        },
        "frozen_state": {
            "particle_mass_th": mass,
            "charge_state": charge,
            "selected_axial_energy_per_charge_v": managed.axial_energy_per_charge_v,
            "source_slow_energy_per_charge_v": slow_energy,
            "target_p2_reference_tangent_ratio": target_ratio,
            "stripe_biases_v": list(stripe_biases),
            "prism_voltage_polarity": polarity_receipt,
        },
        "controls": {
            "p1_discovery_bounds_v": [args.p1_min_v, args.p1_max_v],
            "p2_natural_energy_bounds_v": [-total_energy, total_energy],
            "p2_discovery_bounds_v": list(p2_bounds),
            "anchor_count": args.anchor_count,
            "worker_count": args.worker_count,
            "primary_objective": args.primary_objective,
            "p2_scan_count": args.p2_scan_count if args.primary_objective != "angle" else None,
            "adaptive_refinement_levels": (
                args.adaptive_refinement_levels
                if args.primary_objective == "position_adaptive" else None
            ),
            "adaptive_candidate_count": (
                args.adaptive_candidate_count
                if args.primary_objective == "position_adaptive" else None
            ),
            "slice": asdict(slice_controls),
            "transport_numerics": asdict(numerics),
        },
        "discovery": discovery,
        "limitations": [
            "P1 anchors are selected only from legal topologies observed by the parent coverage.",
            (
                "The ideal P2 solve omits the mirror gradient inside P2 and must be verified "
                "by segmented transport."
                if args.primary_objective == "angle"
                else "Each position root remains a solver-neutral segmented-transport result."
            ),
            "This projected y-z result does not qualify finite-three-dimensional transmission or resolution.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "MRTOF_TWO_PRISM_PARALLEL_DISCOVERY=PASS "
        f"objective={args.primary_objective} "
        f"anchors={discovery['selected_anchor_count']} workers={args.worker_count}"
    )


if __name__ == "__main__":
    main()
