"""Deterministic branch coverage for the solver-neutral segmented P1/P2 model."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

from scipy.stats import qmc

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.host_resource_python import ensure_heavy_entry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_transport_source import (
    materialize_accelerator_exit_transport_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_mirror_stripe_operating_point import (
    load_fixed_mirror_stripe_operating_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_exact_k_operating_point import (
    ManagedExactKOperatingPoint,
    load_managed_exact_k_operating_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import axial_potential_v
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
    TransportNumerics,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
    RESIDUAL_NAMES,
    natural_two_prism_scales,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_transport import (
    evaluate_two_prism_segmented_voltage_pair,
    two_prism_initial_search_bounds,
    validate_two_prism_voltage_polarity_domain,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_voltage_seed import (
    selected_positive_mirror_turn_identity,
    two_prism_legacy_topology_signature,
    two_prism_topology_signature,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    load_schema5_native_source_state,
)


@dataclass(frozen=True)
class SegmentedOperatingContext:
    """Minimal verified mirror authority consumed by segmented P1/P2 transport."""

    design: MirrorL0Design
    axial_energy_per_charge_v: float
    contract: dict[str, Any]


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


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise CandidateContractError(f"{label} must be a positive integer")
    return value


def _record_named(records: object, filename: str, label: str) -> dict[str, Any]:
    values = records.values() if isinstance(records, dict) else records
    if not isinstance(values, Iterable):
        raise CandidateContractError(f"Stripe manifest lacks {label} records")
    matches = [
        item for item in values
        if isinstance(item, dict) and Path(str(item.get("path", ""))).name == filename
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"Stripe manifest must contain exactly one {label} record")
    return matches[0]


def _load_stripe_seed(
    manifest_path: Path,
    *,
    exact_k_manifest_path: Path,
    managed: ManagedExactKOperatingPoint,
) -> tuple[tuple[float, float], float, float, dict[str, Any]]:
    base = manifest_path.resolve().parent
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateContractError("Stripe run manifest is not readable JSON") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 2
        or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "dual_stripe_exact_k_downstream_seed"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("Stripe run manifest identity or terminal status is invalid")
    try:
        verify_record("run_config", manifest["run_config"], base_dir=base)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"input {name}", record, base_dir=base)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"output {index}", record, base_dir=base)
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(f"Stripe run manifest integrity failed: {error}") from error
    parent = _record_named(manifest.get("inputs"), "parent_exact_k_run_manifest.json", "parent exact-K")
    if str(parent.get("sha256", "")).lower() != file_sha256(exact_k_manifest_path).lower():
        raise CandidateContractError("Stripe run is not descended from the supplied exact-K manifest")
    summary_record = _record_named(manifest.get("outputs"), "summary.json", "summary")
    summary_path = record_path(summary_record, base_dir=base)
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    seed, source_energy = load_schema5_native_source_state(
        summary, managed.contract, managed.axial_energy_per_charge_v,
    )
    biases = seed.get("stripe_biases_v")
    if not isinstance(biases, list) or len(biases) != 2:
        raise CandidateContractError("native Stripe seed must contain two biases")
    angle_degrees = _finite(
        seed.get("nominal_injection_angle_degrees"),
        "native Stripe seed nominal injection angle",
    )
    target_tangent_ratio = math.tan(math.radians(angle_degrees))
    if target_tangent_ratio <= 0.0:
        raise CandidateContractError("native Stripe seed injection angle must be positive")
    return (
        (_finite(biases[0], "Stripe set 1 bias"), _finite(biases[1], "Stripe set 2 bias")),
        source_energy,
        target_tangent_ratio,
        {"manifest_sha256": file_sha256(manifest_path).lower(), "summary_sha256": file_sha256(summary_path).lower()},
    )


def load_segmented_operating_authority(
    *,
    contract_path: Path,
    exact_k_manifest_path: Path | None = None,
    stripe_seed_manifest_path: Path | None = None,
    fixed_mirror_stripe_manifest_path: Path | None = None,
) -> tuple[
    SegmentedOperatingContext, tuple[float, float], float, float,
    dict[str, Any], str, Path,
]:
    """Load either supported upstream authority into one P1/P2 context."""
    fixed_mode = fixed_mirror_stripe_manifest_path is not None
    legacy_mode = exact_k_manifest_path is not None or stripe_seed_manifest_path is not None
    if fixed_mode == legacy_mode:
        raise CandidateContractError(
            "select exactly one fixed-mirror Stripe or legacy exact-K authority"
        )
    if fixed_mode:
        fixed = load_fixed_mirror_stripe_operating_point(
            fixed_mirror_stripe_manifest_path,
            contract_path,
        )
        context = SegmentedOperatingContext(
            design=fixed.mirror_design,
            axial_energy_per_charge_v=fixed.axial_energy_per_charge_v,
            contract=fixed.contract,
        )
        slow_energy = fixed.slow_energy_per_charge_v
        return (
            context,
            fixed.stripe_biases_v,
            slow_energy,
            math.sqrt(slow_energy / fixed.axial_energy_per_charge_v),
            {
                "authority_kind": "fixed_grid_mirror_variable_slow_energy_stripe",
                "manifest_sha256": file_sha256(
                    fixed_mirror_stripe_manifest_path
                ).lower(),
                "source_fixed_grid_run_id": fixed.fixed_grid_run_id,
                "source_stripe_run_id": fixed.stripe_run_id,
            },
            "fixed_grid_mirror_variable_slow_energy_stripe",
            fixed_mirror_stripe_manifest_path,
        )
    if exact_k_manifest_path is None or stripe_seed_manifest_path is None:
        raise CandidateContractError(
            "legacy exact-K mode requires both mirror and Stripe manifests"
        )
    legacy = load_managed_exact_k_operating_point(
        exact_k_manifest_path, contract_path,
    )
    biases, slow_energy, tangent, identity = _load_stripe_seed(
        stripe_seed_manifest_path,
        exact_k_manifest_path=exact_k_manifest_path,
        managed=legacy,
    )
    return (
        SegmentedOperatingContext(
            design=legacy.design,
            axial_energy_per_charge_v=legacy.axial_energy_per_charge_v,
            contract=legacy.contract,
        ),
        biases,
        slow_energy,
        tangent,
        identity,
        "analytic_mirror_exact_k",
        exact_k_manifest_path,
    )
def validate_accelerator_exit_source_binding(
    *, source_receipt_path: Path, source_handoff_receipt: dict[str, Any],
    managed: ManagedExactKOperatingPoint | SegmentedOperatingContext,
) -> dict[str, Any]:
    """Bind source identity and report, without hiding, its measured exact-K mismatch."""
    try:
        expected_sha = source_handoff_receipt["input"]["accelerator_exit_observation"][
            "source_receipt_sha256"
        ]
        expected_mass = source_handoff_receipt["particle_mass_th"]
        expected_charge = source_handoff_receipt["charge_state"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError(
            "accelerator-exit transport-source receipt identity is incomplete"
        ) from error
    actual_sha = file_sha256(source_receipt_path).lower()
    if actual_sha != str(expected_sha).lower():
        raise CandidateContractError(
            "accelerator-exit observation does not identify the supplied source receipt"
        )
    try:
        receipt = json.loads(source_receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateContractError("accelerator-exit source receipt is not readable JSON") from error
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("role") != "mrtof_accelerator_exit_center_source"
        or receipt.get("status") != "materialized"
        or receipt.get("qualification") != "source_to_accelerator_exit_diagnostic_input_only"
    ):
        raise CandidateContractError("accelerator-exit source receipt identity is invalid")
    if (
        _finite(receipt.get("particle_mass_th"), "exit-source particle mass")
        != float(expected_mass)
        or receipt.get("charge_state") != expected_charge
    ):
        raise CandidateContractError("accelerator-exit source receipt species is inconsistent")
    source_energy = _finite(
        receipt.get("selected_axial_energy_per_charge_v"),
        "accelerator-exit source selected axial energy",
    )
    if source_energy != managed.axial_energy_per_charge_v:
        raise CandidateContractError(
            "accelerator-exit source selected axial energy differs from exact-K"
        )
    try:
        position = source_handoff_receipt["position_mm"]
        components = source_handoff_receipt["kinetic_energy_components_ev"]
        charge = int(source_handoff_receipt["charge_state"])
        z_mm = _finite(position[2], "accelerator-exit source z")
        axial_kinetic_per_charge_v = _finite(
            components["z"], "accelerator-exit axial kinetic energy",
        ) / abs(charge)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as error:
        raise CandidateContractError(
            "accelerator-exit transport source lacks its measured axial-energy components"
        ) from error
    mirror_potential_v = axial_potential_v(z_mm, managed.design)
    measured_axial_hamiltonian_v = (
        axial_kinetic_per_charge_v
        + (1.0 if charge > 0 else -1.0) * mirror_potential_v
    )
    return {
        "sha256": actual_sha,
        "selected_axial_energy_per_charge_v": source_energy,
        "measured_axial_kinetic_energy_per_charge_v": axial_kinetic_per_charge_v,
        "mirror_potential_at_source_v": mirror_potential_v,
        "measured_axial_hamiltonian_per_charge_v": measured_axial_hamiltonian_v,
        "measured_minus_selected_axial_energy_v": (
            measured_axial_hamiltonian_v - source_energy
        ),
        "energy_match_qualification": (
            "diagnostic_only__no_user_authorized_acceptance_tolerance"
        ),
    }


def deterministic_sobol_voltage_pairs(
    *, p1_bounds_v: Sequence[float], p2_bounds_v: Sequence[float], sample_count: int,
) -> tuple[tuple[float, float], ...]:
    count = _positive_integer(sample_count, "Sobol sample count")
    if count & (count - 1):
        raise CandidateContractError("Sobol sample count must be a power of two")
    bounds = []
    for label, values in (("P1", p1_bounds_v), ("P2", p2_bounds_v)):
        if len(values) != 2:
            raise CandidateContractError(f"{label} bounds must contain lower and upper values")
        lower, upper = (_finite(values[0], f"{label} lower bound"), _finite(values[1], f"{label} upper bound"))
        if lower >= upper:
            raise CandidateContractError(f"{label} voltage domain must have positive width")
        bounds.append((lower, upper))
    unit = qmc.Sobol(d=2, scramble=False).random_base2(int(math.log2(count)))
    return tuple(
        (bounds[0][0] + row[0] * (bounds[0][1] - bounds[0][0]),
         bounds[1][0] + row[1] * (bounds[1][1] - bounds[1][0]))
        for row in unit
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


_WORKER_CONTEXT: dict[str, Any] = {}


def _initialize_worker(context: dict[str, Any]) -> None:
    global _WORKER_CONTEXT
    _WORKER_CONTEXT = context


def _evaluate_detailed(pair: tuple[float, float]) -> dict[str, Any]:
    """Evaluate one pair and retain its in-process transport diagnostic.

    The diagnostic is intentionally private to a worker process and must be
    removed before JSON publication.  It lets topology-aware downstream
    algorithms reuse the exact same propagation instead of rebuilding it.
    """
    context = _WORKER_CONTEXT
    try:
        result = evaluate_two_prism_segmented_voltage_pair(
            context["contract"], source=context["source"],
            particle_mass_th=context["mass"], charge_state=context["charge"],
            mirror_design=context["mirror_design"],
            selected_axial_energy_per_charge_v=context["axial_energy"],
            target_slow_kinetic_energy_per_charge_v=context["slow_energy"],
            target_p2_reference_tangent_ratio=context["target_tangent_ratio"],
            prism_bias_v_by_electrode_id={context["prism_ids"][0]: pair[0], context["prism_ids"][1]: pair[1]},
            stripe_bias_v_by_set_name={"set_1": context["stripe_biases"][0], "set_2": context["stripe_biases"][1]},
            numerics=context["numerics"],
            stage_a_maximum_reduced_time_mm_per_sqrt_v=context["stage_a"],
            stage_b_maximum_reduced_time_mm_per_sqrt_v=context["stage_b"],
        )
    except CandidateContractError as error:
        return {"prism_voltages_v": list(pair), "status": "invalid_topology", "failure": str(error)}
    residual_map = dict(result.voltage_residuals)
    residuals = [_finite(residual_map[name], name) for name in RESIDUAL_NAMES]
    scaled_norm = math.sqrt(sum((value / scale) ** 2 for value, scale in zip(residuals, context["residual_scales"], strict=True)))
    signature = two_prism_topology_signature(result)
    signature_json = _jsonable(signature)
    signature_id = hashlib.sha256(json.dumps(signature_json, separators=(",", ":")).encode()).hexdigest()
    legacy_signature = two_prism_legacy_topology_signature(result)
    legacy_signature_json = _jsonable(legacy_signature)
    legacy_signature_id = hashlib.sha256(
        json.dumps(legacy_signature_json, separators=(",", ":")).encode()
    ).hexdigest()
    turn_identity = selected_positive_mirror_turn_identity(result)
    return {
        "prism_voltages_v": list(pair), "status": "legal_topology",
        "topology_signature_sha256": signature_id, "topology_signature": signature_json,
        "legacy_topology_signature_sha256": legacy_signature_id,
        "legacy_topology_signature": legacy_signature_json,
        "selected_positive_mirror_turn_identity": _jsonable(turn_identity),
        "residual_vector": residuals, "scaled_residual_norm_2": scaled_norm,
        "transport_diagnostic": result,
    }


def _evaluate(pair: tuple[float, float]) -> dict[str, Any]:
    """Return the compact JSON-safe coverage record for one voltage pair."""
    record = _evaluate_detailed(pair)
    record.pop("transport_diagnostic", None)
    return record


def _summarize(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    failures = Counter(item["failure"] for item in records if item["status"] != "legal_topology")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        if item["status"] == "legal_topology":
            groups[item["topology_signature_sha256"]].append(item)
    branches = []
    for identity, items in sorted(groups.items()):
        p1 = [item["prism_voltages_v"][0] for item in items]
        p2 = [item["prism_voltages_v"][1] for item in items]
        residual_columns = list(zip(*(item["residual_vector"] for item in items), strict=True))
        ranges = [[min(column), max(column)] for column in residual_columns]
        best = min(items, key=lambda item: item["scaled_residual_norm_2"])
        branches.append({
            "topology_signature_sha256": identity,
            "topology_signature": items[0]["topology_signature"],
            "sample_count": len(items),
            "prism_1_voltage_range_v": [min(p1), max(p1)],
            "prism_2_voltage_range_v": [min(p2), max(p2)],
            "residual_ranges": {name: value for name, value in zip(RESIDUAL_NAMES, ranges, strict=True)},
            "residual_zero_enclosed": {name: value[0] <= 0.0 <= value[1] for name, value in zip(RESIDUAL_NAMES, ranges, strict=True)},
            "both_residual_ranges_enclose_zero": all(value[0] <= 0.0 <= value[1] for value in ranges),
            "minimum_scaled_residual_sample": best,
        })
    return {
        "sample_count": len(records),
        "legal_topology_count": sum(item["status"] == "legal_topology" for item in records),
        "invalid_topology_count": sum(item["status"] != "legal_topology" for item in records),
        "failure_counts_by_message": dict(sorted(failures.items())),
        "branches": branches,
    }


def run_coverage(
    *, context: dict[str, Any], sobol_pairs: Sequence[tuple[float, float]],
    local_pairs: Sequence[tuple[float, float]], worker_count: int,
) -> dict[str, Any]:
    workers = _positive_integer(worker_count, "worker count")
    tagged = [("sobol", pair) for pair in sobol_pairs] + [("local", pair) for pair in local_pairs]
    if workers == 1:
        _initialize_worker(context)
        evaluated = [_evaluate(pair) for _, pair in tagged]
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_initialize_worker, initargs=(context,)) as pool:
            evaluated = list(pool.map(_evaluate, (pair for _, pair in tagged)))
    sobol_records = [item for (kind, _), item in zip(tagged, evaluated, strict=True) if kind == "sobol"]
    local_records = [item for (kind, _), item in zip(tagged, evaluated, strict=True) if kind == "local"]
    return {
        "sobol": {**_summarize(sobol_records), "samples": sobol_records},
        "local": {**_summarize(local_records), "samples": local_records},
        "combined": _summarize(evaluated),
    }


def _csv_floats(text: str, label: str) -> tuple[float, ...]:
    if not text.strip():
        return ()
    return tuple(_finite(value.strip(), label) for value in text.split(","))


def main() -> None:
    ensure_heavy_entry(
        "projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage",
        role="GATE", stage="theory_compute",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument("--exact-k-manifest", type=Path)
    authority.add_argument("--fixed-mirror-stripe-manifest", type=Path)
    parser.add_argument("--stripe-seed-manifest", type=Path)
    parser.add_argument("--accelerator-exit-observation", type=Path, required=True)
    parser.add_argument("--accelerator-exit-source-receipt", type=Path, required=True)
    parser.add_argument("--expected-observation-sha256", required=True)
    parser.add_argument("--source-receipt-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--p1-min-v", type=float)
    parser.add_argument("--p1-max-v", type=float)
    parser.add_argument("--p2-min-v", type=float)
    parser.add_argument("--p2-max-v", type=float)
    parser.add_argument("--sobol-sample-count", type=int, required=True)
    parser.add_argument("--local-p1-values-v", required=True)
    parser.add_argument("--local-p2-values-v", required=True)
    parser.add_argument("--worker-count", type=int, required=True)
    parser.add_argument("--relative-tolerance", type=float, required=True)
    parser.add_argument("--absolute-tolerance", type=float, required=True)
    parser.add_argument("--max-step", type=float, required=True)
    parser.add_argument("--event-samples-per-step", type=int, required=True)
    parser.add_argument("--root-time-tolerance", type=float, required=True)
    parser.add_argument("--boundary-root-tolerance", type=float, required=True)
    parser.add_argument("--momentum-tolerance", type=float, required=True)
    parser.add_argument("--normal-energy-tolerance", type=float, required=True)
    parser.add_argument("--maximum-steps", type=int, required=True)
    parser.add_argument("--stage-a-maximum-reduced-time", type=float, required=True)
    parser.add_argument("--stage-b-maximum-reduced-time", type=float, required=True)
    args = parser.parse_args()

    (
        managed, stripe_biases, source_energy, target_tangent_ratio,
        stripe_identity, operating_authority_kind, operating_authority_path,
    ) = load_segmented_operating_authority(
        contract_path=args.contract,
        exact_k_manifest_path=args.exact_k_manifest,
        stripe_seed_manifest_path=args.stripe_seed_manifest,
        fixed_mirror_stripe_manifest_path=args.fixed_mirror_stripe_manifest,
    )
    species = managed.contract.get("particle_source", {}).get("species", {})
    mass = _finite(species.get("mass_th"), "contract particle mass")
    charge = species.get("charge_e")
    if type(charge) is not int or charge == 0:
        raise CandidateContractError("contract particle charge must be a nonzero integer")
    explicit_bounds = (
        args.p1_min_v, args.p1_max_v, args.p2_min_v, args.p2_max_v,
    )
    if all(value is None for value in explicit_bounds):
        p1_bounds, p2_bounds = two_prism_initial_search_bounds(
            managed.contract, charge_state=charge,
        )
        voltage_domain_source = "contract_current_initial_search_window"
    elif any(value is None for value in explicit_bounds):
        raise CandidateContractError(
            "explicit P1/P2 coverage bounds must supply all four endpoints"
        )
    else:
        p1_bounds = (args.p1_min_v, args.p1_max_v)
        p2_bounds = (args.p2_min_v, args.p2_max_v)
        validate_two_prism_voltage_polarity_domain(
            managed.contract,
            charge_state=charge,
            p1_bounds_v=p1_bounds,
            p2_bounds_v=p2_bounds,
        )
        voltage_domain_source = "explicit_signed_override"
    source, source_receipt = materialize_accelerator_exit_transport_source(
        observation_path=args.accelerator_exit_observation,
        expected_observation_sha256=args.expected_observation_sha256,
        expected_particle_mass_th=mass, expected_charge_state=charge,
        receipt_path=args.source_receipt_output,
    )
    source_binding = validate_accelerator_exit_source_binding(
        source_receipt_path=args.accelerator_exit_source_receipt,
        source_handoff_receipt=source_receipt, managed=managed,
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
        "contract": managed.contract, "source": source, "mass": mass, "charge": charge,
        "mirror_design": managed.design, "axial_energy": managed.axial_energy_per_charge_v,
        "slow_energy": source_energy, "stripe_biases": stripe_biases, "prism_ids": prism_ids,
        "target_tangent_ratio": target_tangent_ratio,
        "numerics": numerics, "stage_a": _finite(args.stage_a_maximum_reduced_time, "stage A maximum time"),
        "stage_b": _finite(args.stage_b_maximum_reduced_time, "stage B maximum time"),
        "residual_scales": tuple(residual_scales),
    }
    sobol_pairs = deterministic_sobol_voltage_pairs(
        p1_bounds_v=p1_bounds, p2_bounds_v=p2_bounds,
        sample_count=args.sobol_sample_count,
    )
    local_p1 = _csv_floats(args.local_p1_values_v, "local P1 voltage")
    local_p2 = _csv_floats(args.local_p2_values_v, "local P2 voltage")
    local_pairs = tuple((p1, p2) for p1 in local_p1 for p2 in local_p2)
    coverage = run_coverage(context=context, sobol_pairs=sobol_pairs, local_pairs=local_pairs, worker_count=args.worker_count)
    output = {
        "schema_version": 1,
        "role": "mrtof_two_prism_segmented_voltage_branch_coverage",
        "status": "coverage_complete",
        "qualification": "solver_neutral_topology_coverage_only__not_a_voltage_solution",
        "inputs": {
            "contract_sha256": file_sha256(args.contract).lower(),
            "operating_authority_kind": operating_authority_kind,
            "operating_authority_manifest_sha256": file_sha256(
                operating_authority_path
            ).lower(),
            "stripe_seed": stripe_identity,
            "accelerator_exit_observation_sha256": file_sha256(args.accelerator_exit_observation).lower(),
            "accelerator_exit_source_receipt": source_binding,
            "source_receipt_sha256": file_sha256(args.source_receipt_output).lower(),
        },
        "frozen_state": {
            "particle_mass_th": mass, "charge_state": charge,
            "source": asdict(source), "selected_axial_energy_per_charge_v": managed.axial_energy_per_charge_v,
            "source_slow_energy_per_charge_v": source_energy, "stripe_biases_v": list(stripe_biases),
            "target_p2_reference_tangent_ratio": target_tangent_ratio,
            "source_observation_input": source_receipt["input"],
        },
        "controls": {
            "sobol": {"scramble": False, "sample_count": len(sobol_pairs), "p1_bounds_v": list(p1_bounds), "p2_bounds_v": list(p2_bounds), "voltage_domain_source": voltage_domain_source},
            "local_cartesian_values_v": {"p1": list(local_p1), "p2": list(local_p2)},
            "worker_count": args.worker_count, "transport_numerics": asdict(numerics),
            "stage_a_maximum_reduced_time_mm_per_sqrt_v": args.stage_a_maximum_reduced_time,
            "stage_b_maximum_reduced_time_mm_per_sqrt_v": args.stage_b_maximum_reduced_time,
            "residual_names": list(RESIDUAL_NAMES), "residual_scales": list(residual_scales),
            "residual_scale_authority": "contract_natural_two_prism_scales",
        },
        "coverage": coverage,
        "limitations": [
            "Independent sign enclosure by both residual ranges does not prove a common two-dimensional root.",
            "This hard-boundary two-dimensional diagnostic does not qualify finite-3D fields or a time platform.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "MRTOF_TWO_PRISM_SEGMENTED_COVERAGE_ANALYSIS=PASS "
        f"sobol={len(sobol_pairs)} local={len(local_pairs)}"
    )


if __name__ == "__main__":
    main()
