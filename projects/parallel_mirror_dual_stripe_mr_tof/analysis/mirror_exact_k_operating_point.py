"""Select an exact-K operating energy on a mirror-theory-qualified branch.

The fixed manufactured mirror has four non-ground voltage coordinates and
three axial L0 equations.  L1 gamma selects one member at each trial energy.
This module then varies only the accelerator net-gain centre within its
declared range.  At every energy it analytically derives the two Stripe
biases from the fixed native spatial-return shape and the declared slow-axis
source energy, then applies the Stripe-on ``T_D/T_0=K`` as the final selector.
Stripe voltages never back-fit the independent mirror equations.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import brentq, least_squares

from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.host_resource_python import ensure_heavy_entry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    NativeStripeSpatialShapeRoot,
    materialize_native_stripe_spatial_return_root,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    StripeHardBoundary,
    classify_constraint_system,
    derive_coupled_drift_state,
    spatial_return_kappa_derivative_residual,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_candidate_receipt import (
    ManagedMirrorRoot,
    load_managed_mirror_candidate,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import (
    derive_mirror_boundaries,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    derive_mirror_l0_slope_tolerance_per_v,
    effective_axial_width_mm,
    reduced_period,
    three_point_report,
    three_point_normalized_period_slopes_per_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l1 import (
    map_at_energy,
    refine_l0_gamma_intersection,
    screen_l1_fixed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_stripe_shape_adapter import (
    build_native_stripe_shape_selection,
    load_native_stripe_shape_selection,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_path_length_evaluator,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_mirror_voltage_bounds,
    derive_operating_energy_envelope,
    load_contract,
)


EXACT_K_SELECTOR_STATUS = (
    "native_fixed_geometry_stripe_on_period_selection_over_mirror_qualified_energy_family"
)
EXACT_K_SUMMARY_STATUS = (
    "native_stripe_on_exact_k_system_point_found__3d_validation_pending"
)


@dataclass(frozen=True)
class ExactKPoint:
    """One gamma-qualified mirror point evaluated at a selected energy."""

    branch_index: int
    energy_per_charge_v: float
    mirror_voltages_v: tuple[float, ...]
    mirror_reduced_period_mm_per_sqrt_v: float
    mirror_axial_width_w_mm: float
    calculated_td_over_t0: float
    exact_k_residual: float
    gamma_degrees: float
    gamma_residual_degrees: float
    normalized_period_slopes_per_v: tuple[float, ...]
    stripe_biases_v: tuple[float, float]
    turning_pseudopotential_v: float
    source_slow_energy_mismatch_v: float
    spatial_return_kappa_prime: float


@dataclass(frozen=True)
class ManagedExactKOperatingPoint:
    """A verified system-level mirror point for downstream analytic seeding."""

    design: MirrorL0Design
    axial_energy_per_charge_v: float
    axial_width_w_mm: float
    native_stripe_spatial_shape_root: NativeStripeSpatialShapeRoot
    stripe_biases_v: tuple[float, float]
    contract: dict[str, Any]
    run_id: str
    manifest_sha256: str
    parent_mirror_manifest_sha256: str

    @property
    def kappa_1(self) -> float:
        """Return kappa from the contract-bound native manufactured shape root."""
        return self.native_stripe_spatial_shape_root.kappa_1


def _evaluate_energy_node_worker(
    payload: tuple[
        dict[str, Any], ManagedMirrorRoot, int, float, NativeStripeSpatialShapeRoot,
    ],
) -> tuple[float, ExactKPoint | None, dict[str, object] | None, str | None]:
    """Evaluate one independent mirror-energy node in a spawn-safe worker."""
    contract, seed, branch_index, energy, shape_root = payload
    try:
        point, receipt = evaluate_branch_at_energy(
            contract,
            seed,
            branch_index,
            energy,
            shape_root,
            None,
        )
        return energy, point, receipt, None
    except Exception as error:  # retried serially with continuation before failure
        return energy, None, None, f"{type(error).__name__}: {error}"


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be numeric") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be a JSON object")
    return value


def _record_named(records: object, filename: str, label: str) -> dict[str, Any]:
    if isinstance(records, dict):
        candidates = records.values()
    elif isinstance(records, list):
        candidates = records
    else:
        raise CandidateContractError(f"exact-K manifest lacks {label} records")
    matches = [
        record for record in candidates
        if isinstance(record, dict) and Path(str(record.get("path", ""))).name == filename
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"exact-K manifest must contain exactly one {label} record")
    return matches[0]


def exact_k_contract_projection(contract: dict[str, Any]) -> dict[str, Any]:
    """Exclude downstream P1/P2 semantics that cannot affect exact-K physics."""
    projection = copy.deepcopy(contract)
    try:
        injection = projection["prism_transport"]["two_prism_injection_l0"]
        voltage_initialization = projection["dual_stripe_l0"][
            "current_fixed_hardware_l0_l1_problem"
        ]["voltage_initialization"]
        full_mrtof_center = projection["particle_source"]["full_mrtof_center"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("exact-K contract projection lacks P1/P2 authority") from error
    injection.pop("voltage_polarity_contract", None)
    authority = injection.get("low_field_angle_and_positive_mirror_turn_authority")
    if not isinstance(authority, dict):
        raise CandidateContractError("exact-K contract projection lacks angle authority")
    authority.pop("direction_condition", None)
    if not isinstance(voltage_initialization, dict) or not isinstance(full_mrtof_center, dict):
        raise CandidateContractError("exact-K contract projection lacks downstream semantics")
    voltage_initialization.pop("semantics", None)
    voltage_initialization.pop("derivation_chain", None)
    full_mrtof_center.pop("required_inputs", None)
    return projection


def load_managed_exact_k_operating_point(
    manifest_path: Path,
    downstream_contract_path: Path | None = None,
) -> ManagedExactKOperatingPoint:
    """Verify an exact-K run before using it as a downstream analytic input."""
    path = manifest_path.resolve()
    manifest_dir = path.parent
    manifest = _load_json(path, "exact-K run manifest")
    if (
        manifest.get("schema_version") != 2
        or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "analytic_mirror_exact_k_operating_point"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("exact-K manifest has the wrong identity or terminal status")
    try:
        verify_record("run_config", manifest["run_config"], base_dir=manifest_dir)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"input {name}", record, base_dir=manifest_dir)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"output {index}", record, base_dir=manifest_dir)
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(f"exact-K manifest integrity failed: {error}") from error
    contract_record = _record_named(
        manifest.get("inputs"), "simion_candidate_two_zone.json", "frozen contract"
    )
    parent_record = _record_named(
        manifest.get("inputs"), "parent_mirror_run_manifest.json", "parent mirror manifest"
    )
    summary_record = _record_named(manifest.get("outputs"), "summary.json", "summary")
    contract = load_contract(record_path(contract_record, base_dir=manifest_dir))
    downstream = (
        load_contract(downstream_contract_path.resolve())
        if downstream_contract_path is not None
        else contract
    )
    if canonical_json_sha256(exact_k_contract_projection(contract)) != canonical_json_sha256(
        exact_k_contract_projection(downstream)
    ):
        raise CandidateContractError("downstream contract changed one or more exact-K inputs")
    summary = _load_json(record_path(summary_record, base_dir=manifest_dir), "exact-K summary")
    if (
        summary.get("schema_version") != 2
        or summary.get("role") != "mrtof_exact_k_mirror_energy_operating_point"
        or summary.get("status") != EXACT_K_SUMMARY_STATUS
        or summary.get("qualification") != "solver_neutral_2d_system_selection__not_simion_voltage_authority"
    ):
        raise CandidateContractError("exact-K summary is not an accepted solver-neutral Candidate")
    identity = summary.get("input")
    if not isinstance(identity, dict):
        raise CandidateContractError("exact-K summary lacks input identity")
    summary_contract = identity.get("contract")
    summary_parent = identity.get("mirror_manifest")
    if not isinstance(summary_contract, dict) or not isinstance(summary_parent, dict):
        raise CandidateContractError("exact-K summary input identity is incomplete")
    if (
        str(summary_contract.get("sha256", "")).upper()
        != str(contract_record.get("sha256", "")).upper()
        or str(summary_parent.get("sha256", "")).upper()
        != str(parent_record.get("sha256", "")).upper()
    ):
        raise CandidateContractError("exact-K summary hash chain differs from its manifest")
    root_index = summary.get("selected_root_index")
    roots = summary.get("roots")
    if not isinstance(root_index, int) or isinstance(root_index, bool) or not isinstance(roots, list):
        raise CandidateContractError("exact-K summary lacks a selected root")
    try:
        selected_root = roots[root_index]
    except IndexError as error:
        raise CandidateContractError("exact-K selected root index is out of range") from error
    if (
        not isinstance(selected_root, dict)
        or selected_root.get("probe_convergence", {}).get("status") != "pass"
        or selected_root.get("definition", {}).get("classification", {}).get("status") != "square_exact"
    ):
        raise CandidateContractError("exact-K selected root lacks convergence or square determination")
    point = summary.get("selected_operating_point")
    if not isinstance(point, dict):
        raise CandidateContractError("exact-K summary lacks selected operating point")
    energy = _finite(point.get("energy_per_charge_v"), "exact-K axial energy")
    voltage_values = point.get("mirror_voltages_v")
    if not isinstance(voltage_values, list) or len(voltage_values) != 5:
        raise CandidateContractError("exact-K point lacks five mirror voltages")
    voltages = tuple(_finite(value, "exact-K mirror voltage") for value in voltage_values)
    if voltages[0] != 0.0:
        raise CandidateContractError("exact-K point must keep A grounded")
    lower, upper = derive_mirror_voltage_bounds(contract, selected_center_v=energy)
    if any(
        not low <= value <= high
        for value, low, high in zip(voltages[1:], lower, upper, strict=True)
    ):
        raise CandidateContractError("exact-K point violates the selected energy voltage envelope")
    target_k = resolve_drift_phase_contract(contract).target_period_ratio
    k_residual = _finite(point.get("exact_k_residual"), "exact-K residual")
    tolerance = _finite(
        contract["mirror"]["theory_requirements"]["exact_k_operating_point_selection"]
        ["maximum_abs_numerical_k_residual"],
        "exact-K residual tolerance",
    )
    if abs(k_residual) > tolerance or abs(
        _finite(point.get("calculated_td_over_t0"), "exact-K ratio") - target_k
    ) > tolerance:
        raise CandidateContractError("exact-K point fails its numerical K residual gate")
    boundaries = derive_mirror_boundaries(contract["mirror"])
    design = MirrorL0Design(
        transverse_half_gap_mm=_finite(
            contract["mirror"]["theory_requirements"]["berdnikov_transverse_half_gap_mm"],
            "Berdnikov transverse half gap",
        ),
        transition_z_mm=tuple(
            _finite(value, "mirror transition")
            for value in boundaries["analytic_transition_z_mm"]
        ),
        electrode_voltages_v=voltages,
        terminal_electrode_plane_z_mm=_finite(
            boundaries["terminal_electrode_plane_z_mm"], "mirror terminal plane"
        ),
        terminal_electrode_voltage_v=voltages[-1],
    )
    width = _finite(point.get("mirror_axial_width_w_mm"), "exact-K axial width")
    if width <= 0.0:
        raise CandidateContractError("exact-K axial width must be positive")
    shape_selection = load_native_stripe_shape_selection(
        summary.get("native_stripe_spatial_shape_selection"), downstream,
    )
    reported_kappa = _finite(point.get("native_kappa_1"), "exact-K native kappa")
    if reported_kappa != shape_selection.shape_root.kappa_1:
        raise CandidateContractError("exact-K point kappa differs from its native shape root")
    stripe_values = point.get("stripe_biases_v")
    if not isinstance(stripe_values, list) or len(stripe_values) != 2:
        raise CandidateContractError("Stripe-on exact-K point lacks two analytically derived biases")
    stripe_biases = tuple(_finite(value, "exact-K Stripe bias") for value in stripe_values)
    reproduced, reproduced_state, reproduced_kappa_prime = _stripe_on_target_state(
        downstream,
        shape_selection.shape_root,
        energy_per_charge_v=energy,
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energy, design),
    )
    if stripe_biases != tuple(reproduced.stripe_biases_v):
        raise CandidateContractError("Stripe-on exact-K biases differ from the contract-derived inverse")
    if abs(reproduced_state.target_oscillation_count_residual) > tolerance:
        raise CandidateContractError("reproduced Stripe-on exact-K state fails its K residual gate")
    if reproduced_kappa_prime != _finite(
        point.get("spatial_return_kappa_prime"), "exact-K spatial return residual"
    ):
        raise CandidateContractError("reproduced Stripe spatial-return residual changed")
    return ManagedExactKOperatingPoint(
        design=design,
        axial_energy_per_charge_v=energy,
        axial_width_w_mm=width,
        native_stripe_spatial_shape_root=shape_selection.shape_root,
        stripe_biases_v=stripe_biases,
        contract=downstream,
        run_id=str(manifest["run_id"]),
        manifest_sha256=file_sha256(path),
        parent_mirror_manifest_sha256=str(parent_record.get("sha256", "")).upper(),
    )


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CandidateContractError(f"{label} must be a positive integer")
    return value


def _drift_inputs(contract: dict[str, Any]) -> tuple[float, float, float]:
    length = _finite(
        contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
        "manufactured drift length L",
    )
    partition = contract["prism_transport"]["energy_partition"]
    drift_energy = _finite(partition["drift_kinetic_energy_ev"], "drift kinetic energy")
    target_k = resolve_drift_phase_contract(contract).target_period_ratio
    if length <= 0.0 or drift_energy <= 0.0:
        raise CandidateContractError("exact-K drift inputs must be positive")
    return length, drift_energy, target_k


def _td_over_t0(
    energy_per_charge_v: float,
    width_mm: float,
    kappa_1: float,
    length_mm: float,
    drift_energy_per_charge_v: float,
) -> float:
    """Return the exact slow-return/axial-period ratio for an axial ``W``.

    ``energy_per_charge_v`` is the fast mirror-axis energy ``E_z`` and
    ``width_mm`` is consequently ``W=T0*v_z/2``.  The injection angle is
    therefore fixed by ``tan(theta)=v_y/v_z=sqrt(E_y/E_z)``.  The paper's
    equivalent ``sin(theta)`` form uses a width built from total kinetic
    energy; mixing that sine with this axial width introduces an implicit
    ``cos(theta) ~= 1`` approximation.
    """
    axial_energy = _finite(energy_per_charge_v, "axial energy per charge")
    width = _finite(width_mm, "mirror axial width W")
    kappa = _finite(kappa_1, "kappa(1)")
    length = _finite(length_mm, "drift length L")
    drift_energy = _finite(drift_energy_per_charge_v, "drift energy per charge")
    if axial_energy <= 0.0 or width <= 0.0 or drift_energy <= 0.0:
        raise CandidateContractError("exact-K ratio needs positive axial energy, drift energy, and axial width")
    theta = math.atan(math.sqrt(drift_energy / axial_energy))
    return kappa * length / (width * math.tan(theta))


def _stripe_on_target_state(
    contract: dict[str, Any],
    shape_root: NativeStripeSpatialShapeRoot,
    *,
    energy_per_charge_v: float,
    mirror_reduced_period_mm_per_sqrt_v: float,
) -> tuple[Any, Any, float]:
    """Eliminate ``v1,v2`` from the 5-eV turn and spatial-return equations.

    The native shape root fixes the relative response needed for
    ``kappa'(1)=0``.  Its closed inverse fixes the response amplitude from the
    declared source slow energy.  The remaining Stripe-on period ratio is
    therefore a scalar function of the mirror-qualified axial energy.
    """
    slow_energy = _finite(
        contract["prism_transport"]["energy_partition"]["drift_kinetic_energy_ev"],
        "source slow energy",
    )
    materialized = materialize_native_stripe_spatial_return_root(
        shape_root,
        source_slow_energy_per_charge_v=slow_energy,
        mirror_reduced_period_mm_per_sqrt_v=mirror_reduced_period_mm_per_sqrt_v,
        axial_energy_per_charge_v=energy_per_charge_v,
    )
    widths = tuple(
        compile_dual_stripe_path_length_evaluator(contract, name)
        for name in ("set_1", "set_2")
    )
    stripes = tuple(
        StripeHardBoundary(bias, width)
        for bias, width in zip(materialized.stripe_biases_v, widths, strict=True)
    )
    target_ratio = resolve_drift_phase_contract(contract).target_period_ratio
    state = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=mirror_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy_per_charge_v,
        target_oscillation_count=target_ratio,
        stripes=stripes,
        entry_y_mm=shape_root.entry_y_mm,
        turning_y_mm=shape_root.turning_y_mm,
    )
    kappa_prime = spatial_return_kappa_derivative_residual(
        mirror_reduced_period_mm_per_sqrt_v=mirror_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy_per_charge_v,
        stripes=stripes,
        entry_y_mm=shape_root.entry_y_mm,
        nominal_turning_y_mm=shape_root.turning_y_mm,
        derivative_step=_finite(
            contract["dual_stripe_l0"]["operating_seed_search"]["kappa_derivative_step"],
            "Stripe kappa derivative step",
        ),
    )
    return materialized, state, kappa_prime


def _slope_tolerance(contract: dict[str, Any], energies: tuple[float, float, float]) -> float:
    budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
    return derive_mirror_l0_slope_tolerance_per_v(
        _finite(budget["minimum_mass_resolution"], "minimum mass resolution"),
        _finite(budget["mirror_time_width_fraction"], "mirror time-width fraction"),
        energies,
    )


def _joint_refine_exact_k(
    contract: dict[str, Any],
    seed: ManagedMirrorRoot,
    approximate: ExactKPoint,
    shape_root: NativeStripeSpatialShapeRoot,
) -> tuple[ExactKPoint, dict[str, object]]:
    """Close three mirror L0, gamma, and Stripe-on exact-K equations."""
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    global_profile = contract["mirror"]["theory_requirements"]["global_l0_search_profile"]
    selector = contract["mirror"]["theory_requirements"]["exact_k_operating_point_selection"]
    reference_envelope = derive_operating_energy_envelope(contract)
    target_gamma = _finite(profile["target_gamma_degrees"], "target gamma")
    gamma_tolerance = _finite(
        profile["maximum_gamma_target_residual_degrees"], "gamma tolerance"
    )
    k_tolerance = _finite(
        selector["maximum_abs_numerical_k_residual"], "K residual tolerance"
    )
    derivative_step = _finite(
        global_profile["period_slope_derivative_step_v"], "period slope derivative step"
    )
    _length, _drift_energy, target_k = _drift_inputs(contract)

    def evaluate(parameters: np.ndarray) -> tuple[
        MirrorL0Design, tuple[float, float, float], tuple[float, ...], float, float, float,
        Any, Any, float,
    ]:
        voltages = tuple(float(value) for value in parameters[:4])
        selected_energy = float(parameters[4])
        local_energy = derive_operating_energy_envelope(
            contract, selected_center_v=selected_energy,
        )
        design = MirrorL0Design(
            seed.design.transverse_half_gap_mm,
            seed.design.transition_z_mm,
            (0.0, *voltages),
            seed.design.terminal_electrode_plane_z_mm,
            voltages[-1],
        )
        slopes = three_point_normalized_period_slopes_per_v(
            design, local_energy.mirror_energy_nodes_v, derivative_step,
        )
        mapping = map_at_energy(
            selected_energy,
            design,
            _finite(profile["position_probe_mm"], "position probe"),
            _finite(profile["angle_probe_rad"], "angle probe"),
        )
        if not mapping.stable or mapping.gamma_degrees is None:
            raise CandidateContractError("joint exact-K solve encountered an unstable mirror map")
        reduced = reduced_period(selected_energy, design)
        width = effective_axial_width_mm(selected_energy, reduced)
        stripe_materialization, stripe_state, kappa_prime = _stripe_on_target_state(
            contract,
            shape_root,
            energy_per_charge_v=selected_energy,
            mirror_reduced_period_mm_per_sqrt_v=reduced,
        )
        ratio = stripe_state.predicted_oscillation_count
        return (
            design,
            local_energy.mirror_energy_nodes_v,
            slopes,
            mapping.gamma_degrees,
            width,
            ratio,
            stripe_materialization,
            stripe_state,
            kappa_prime,
        )

    center = np.asarray([
        *approximate.mirror_voltages_v[1:], approximate.energy_per_charge_v,
    ])
    lower_at_minimum_energy, _ = derive_mirror_voltage_bounds(
        contract, selected_center_v=reference_envelope.net_gain_center_minimum_v,
    )
    _, upper_at_maximum_energy = derive_mirror_voltage_bounds(
        contract, selected_center_v=reference_envelope.net_gain_center_maximum_v,
    )
    lower = np.asarray([
        *lower_at_minimum_energy,
        reference_envelope.net_gain_center_minimum_v,
    ])
    upper = np.asarray([
        *upper_at_maximum_energy,
        reference_envelope.net_gain_center_maximum_v,
    ])
    nominal_energy = derive_operating_energy_envelope(
        contract, selected_center_v=approximate.energy_per_charge_v,
    )
    slope_tolerance = _slope_tolerance(contract, nominal_energy.mirror_energy_nodes_v)

    def scaled_residual(parameters: np.ndarray) -> np.ndarray:
        try:
            _design, _energies, slopes, gamma, _width, ratio, _stripes, _state, _kappa_prime = evaluate(parameters)
        except CandidateContractError:
            return np.full(5, 1e9)
        return np.asarray([
            *(value / slope_tolerance for value in slopes),
            (gamma - target_gamma) / gamma_tolerance,
            (ratio - target_k) / k_tolerance,
        ])

    solution = least_squares(
        scaled_residual,
        center,
        bounds=(lower, upper),
        max_nfev=_positive_integer(
            profile["maximum_local_function_evaluations"], "joint evaluations"
        ),
        x_scale="jac",
        ftol=1e-13,
        xtol=1e-13,
        gtol=1e-13,
    )
    (
        design,
        energies,
        slopes,
        gamma,
        width,
        ratio,
        stripe_materialization,
        stripe_state,
        kappa_prime,
    ) = evaluate(solution.x)
    selected_energy = float(solution.x[4])
    local_lower, local_upper = derive_mirror_voltage_bounds(
        contract, selected_center_v=selected_energy,
    )
    if any(
        not low <= value <= high
        for value, low, high in zip(
            design.electrode_voltages_v[1:], local_lower, local_upper, strict=True,
        )
    ):
        raise CandidateContractError("joint exact-K root violates its energy-dependent voltage envelope")
    gamma_residual = gamma - target_gamma
    if (
        not solution.success
        or any(abs(value) > slope_tolerance for value in slopes)
        or abs(gamma_residual) > gamma_tolerance
        or abs(ratio - target_k) > k_tolerance
    ):
        raise CandidateContractError(
            "joint exact-K solve did not close all five declared residual gates: "
            f"success={solution.success}, max_slope={max(abs(value) for value in slopes):.12g}, "
            f"gamma_residual={gamma_residual:.12g}, K_residual={ratio - target_k:.12g}"
        )
    reduced = reduced_period(selected_energy, design)
    point = ExactKPoint(
        branch_index=approximate.branch_index,
        energy_per_charge_v=selected_energy,
        mirror_voltages_v=design.electrode_voltages_v,
        mirror_reduced_period_mm_per_sqrt_v=reduced,
        mirror_axial_width_w_mm=width,
        calculated_td_over_t0=ratio,
        exact_k_residual=ratio - target_k,
        gamma_degrees=gamma,
        gamma_residual_degrees=gamma_residual,
        normalized_period_slopes_per_v=slopes,
        stripe_biases_v=tuple(stripe_materialization.stripe_biases_v),
        turning_pseudopotential_v=stripe_state.turning_pseudopotential_v,
        source_slow_energy_mismatch_v=stripe_materialization.source_slow_energy_mismatch_v,
        spatial_return_kappa_prime=kappa_prime,
    )
    screen = screen_l1_fixed_geometry(
        design,
        energies,
        _finite(profile["position_probe_mm"], "position probe"),
        _finite(profile["angle_probe_rad"], "angle probe"),
    )
    receipt = {
        "status": "joint_l0_gamma_exact_k_root__probe_and_3d_validation_pending",
        "target_gamma_degrees": target_gamma,
        "gamma_residual_degrees": gamma_residual,
        "optimizer": {
            "success": bool(solution.success),
            "message": str(solution.message),
            "cost": float(solution.cost),
            "function_evaluations": int(solution.nfev),
            "selection_stage": "joint three-mirror-L0 plus gamma plus Stripe-on exact-K solve",
        },
        "l0_receipt": {
            "status": "l0_voltage_slice_member_not_l1_or_3d_validated",
            "geometry_fixed": True,
            "transition_z_mm": list(design.transition_z_mm),
            "transverse_half_gap_mm": design.transverse_half_gap_mm,
            "terminal_electrode_plane_z_mm": design.terminal_electrode_plane_z_mm,
            "electrode_voltages_v": list(design.electrode_voltages_v),
            "three_point": three_point_report(design, energies),
            "normalized_period_slopes_per_v": list(slopes),
            "period_slope_derivative_step_v": derivative_step,
            "maximum_abs_normalized_period_slope_per_v": slope_tolerance,
            "not_evaluated": ["three_dimensional_fields", "simion_pa"],
        },
        "l1_screen": screen,
        "stripe_elimination": {
            "method": "native_shape_closed_inverse_at_declared_source_slow_energy",
            "stripe_biases_v": list(stripe_materialization.stripe_biases_v),
            "turning_pseudopotential_v": stripe_state.turning_pseudopotential_v,
            "source_slow_energy_mismatch_v": stripe_materialization.source_slow_energy_mismatch_v,
            "spatial_return_kappa_prime": kappa_prime,
            "stripe_on_drift_period_ratio": ratio,
        },
    }
    return point, receipt


def evaluate_branch_at_energy(
    contract: dict[str, Any],
    seed: ManagedMirrorRoot,
    branch_index: int,
    energy_per_charge_v: float,
    shape_root: NativeStripeSpatialShapeRoot,
    continuation_point: ExactKPoint | None = None,
) -> tuple[ExactKPoint, dict[str, object]]:
    """Continue one frozen gamma branch to one admissible operating energy."""
    energy = derive_operating_energy_envelope(contract, selected_center_v=energy_per_charge_v)
    energies = energy.mirror_energy_nodes_v
    lower, upper = derive_mirror_voltage_bounds(contract, selected_center_v=energy_per_charge_v)
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    if continuation_point is None:
        reference_energy = derive_operating_energy_envelope(contract).net_gain_reference_center_v
        reference_voltages = seed.design.electrode_voltages_v
    else:
        reference_energy = continuation_point.energy_per_charge_v
        reference_voltages = continuation_point.mirror_voltages_v
    scale = energy_per_charge_v / reference_energy
    scaled_voltages = (0.0, *(value * scale for value in reference_voltages[1:]))
    initial = MirrorL0Design(
        seed.design.transverse_half_gap_mm,
        seed.design.transition_z_mm,
        scaled_voltages,
        seed.design.terminal_electrode_plane_z_mm,
        scaled_voltages[-1],
    )
    refined = refine_l0_gamma_intersection(
        initial,
        lower,
        upper,
        energies,
        _finite(profile["target_gamma_degrees"], "target gamma"),
        _finite(
            contract["mirror"]["theory_requirements"]["global_l0_search_profile"]
            ["period_slope_derivative_step_v"],
            "period slope derivative step",
        ),
        _slope_tolerance(contract, energies),
        _finite(profile["position_probe_mm"], "position probe"),
        _finite(profile["angle_probe_rad"], "angle probe"),
        _finite(profile["maximum_gamma_target_residual_degrees"], "gamma tolerance"),
        _positive_integer(profile["maximum_local_function_evaluations"], "L1 evaluations"),
    )
    l0 = refined["l0_receipt"]
    reduced = _finite(l0["three_point"]["reduced_periods"][1], "mirror reduced period")
    width = effective_axial_width_mm(energy_per_charge_v, reduced)
    _length, _drift_energy, target_k = _drift_inputs(contract)
    stripe_materialization, stripe_state, kappa_prime = _stripe_on_target_state(
        contract,
        shape_root,
        energy_per_charge_v=energy_per_charge_v,
        mirror_reduced_period_mm_per_sqrt_v=reduced,
    )
    ratio = stripe_state.predicted_oscillation_count
    point = ExactKPoint(
        branch_index=branch_index,
        energy_per_charge_v=energy_per_charge_v,
        mirror_voltages_v=tuple(_finite(value, "mirror voltage") for value in l0["electrode_voltages_v"]),
        mirror_reduced_period_mm_per_sqrt_v=reduced,
        mirror_axial_width_w_mm=width,
        calculated_td_over_t0=ratio,
        exact_k_residual=ratio - target_k,
        gamma_degrees=_finite(refined["l1_screen"]["nominal_mapping"]["gamma_degrees"], "gamma"),
        gamma_residual_degrees=_finite(refined["gamma_residual_degrees"], "gamma residual"),
        normalized_period_slopes_per_v=tuple(
            _finite(value, "normalized period slope")
            for value in l0["normalized_period_slopes_per_v"]
        ),
        stripe_biases_v=tuple(stripe_materialization.stripe_biases_v),
        turning_pseudopotential_v=stripe_state.turning_pseudopotential_v,
        source_slow_energy_mismatch_v=stripe_materialization.source_slow_energy_mismatch_v,
        spatial_return_kappa_prime=kappa_prime,
    )
    return point, refined


def _probe_convergence(
    contract: dict[str, Any], point: ExactKPoint, seed: ManagedMirrorRoot,
) -> dict[str, Any]:
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    energy = derive_operating_energy_envelope(
        contract, selected_center_v=point.energy_per_charge_v,
    )
    design = MirrorL0Design(
        seed.design.transverse_half_gap_mm,
        seed.design.transition_z_mm,
        point.mirror_voltages_v,
        seed.design.terminal_electrode_plane_z_mm,
        point.mirror_voltages_v[-1],
    )
    nominal_key = str(float(point.energy_per_charge_v))
    records = []
    for scale_value in profile["probe_convergence_scale_factors"]:
        scale = _finite(scale_value, "probe scale")
        screen = screen_l1_fixed_geometry(
            design,
            energy.mirror_energy_nodes_v,
            _finite(profile["position_probe_mm"], "position probe") * scale,
            _finite(profile["angle_probe_rad"], "angle probe") * scale,
        )
        records.append({
            "scale_factor": scale,
            "gamma_degrees": screen["maps_by_energy_v"][nominal_key]["gamma_degrees"],
            "Tbar_xx": screen["phase_averaged_time_aberration_by_energy_v"][nominal_key]["Tbar_xx"],
        })
    previous, last = records[-2:]
    gamma_change = abs(float(last["gamma_degrees"]) - float(previous["gamma_degrees"]))
    tbar_scale = max(abs(float(last["Tbar_xx"])), abs(float(previous["Tbar_xx"])))
    relative_tbar_change = abs(float(last["Tbar_xx"]) - float(previous["Tbar_xx"])) / tbar_scale
    passed = (
        gamma_change <= _finite(profile["maximum_adjacent_gamma_change_degrees"], "gamma convergence")
        and relative_tbar_change <= _finite(
            profile["maximum_adjacent_relative_Tbar_change"], "Tbar convergence"
        )
    )
    return {
        "status": "pass" if passed else "fail",
        "records": records,
        "last_adjacent_gamma_change_degrees": gamma_change,
        "last_adjacent_relative_Tbar_change": relative_tbar_change,
    }


def _definition_receipt(
    contract: dict[str, Any],
    point: ExactKPoint,
    seed: ManagedMirrorRoot,
    shape_root: NativeStripeSpatialShapeRoot,
) -> dict[str, Any]:
    selector = contract["mirror"]["theory_requirements"]["exact_k_operating_point_selection"]
    energy = derive_operating_energy_envelope(contract, selected_center_v=point.energy_per_charge_v)
    profile = contract["mirror"]["theory_requirements"]["l1_screen_profile"]
    global_profile = contract["mirror"]["theory_requirements"]["global_l0_search_profile"]
    target_gamma_degrees = _finite(profile["target_gamma_degrees"], "target gamma")
    _length, _drift_energy, target_k = _drift_inputs(contract)
    names = ("mirror_B_v", "mirror_C_v", "mirror_D_v", "mirror_E_v", "net_gain_center_v")
    residual_names = (
        "mirror_period_slope_low",
        "mirror_period_slope_center",
        "mirror_period_slope_high",
        "mirror_gamma_target_residual_degrees",
        "stripe_on_T_D_over_T_0_minus_target_K",
    )

    def residual(parameters: np.ndarray) -> np.ndarray:
        voltage_values = tuple(float(value) for value in parameters[:4])
        selected_energy = float(parameters[4])
        local_energy = derive_operating_energy_envelope(contract, selected_center_v=selected_energy)
        design = MirrorL0Design(
            seed.design.transverse_half_gap_mm,
            seed.design.transition_z_mm,
            (0.0, *voltage_values),
            seed.design.terminal_electrode_plane_z_mm,
            voltage_values[-1],
        )
        slopes = three_point_normalized_period_slopes_per_v(
            design,
            local_energy.mirror_energy_nodes_v,
            _finite(global_profile["period_slope_derivative_step_v"], "period derivative step"),
        )
        mapping = map_at_energy(
            selected_energy,
            design,
            _finite(profile["position_probe_mm"], "position probe"),
            _finite(profile["angle_probe_rad"], "angle probe"),
        )
        if not mapping.stable or mapping.gamma_degrees is None:
            raise CandidateContractError("definition Jacobian encountered an unstable mirror map")
        period = reduced_period(selected_energy, design)
        _materialized, stripe_state, _kappa_prime = _stripe_on_target_state(
            contract,
            shape_root,
            energy_per_charge_v=selected_energy,
            mirror_reduced_period_mm_per_sqrt_v=period,
        )
        ratio = stripe_state.predicted_oscillation_count
        return np.asarray([
            *slopes,
            mapping.gamma_degrees - target_gamma_degrees,
            ratio - target_k,
        ])

    center = np.asarray([*point.mirror_voltages_v[1:], point.energy_per_charge_v])
    steps = np.asarray([
        *([_finite(selector["finite_difference_voltage_step_v"], "voltage Jacobian step")] * 4),
        _finite(selector["finite_difference_energy_step_v"], "energy Jacobian step"),
    ])
    columns = []
    for index, step in enumerate(steps):
        upper = center.copy()
        lower = center.copy()
        upper[index] += step
        lower[index] -= step
        columns.append((residual(upper) - residual(lower)) / (2.0 * step))
    jacobian = np.column_stack(columns)
    lower_bounds, upper_bounds = derive_mirror_voltage_bounds(
        contract, selected_center_v=point.energy_per_charge_v,
    )
    parameter_scales = tuple(
        upper - lower for lower, upper in zip(lower_bounds, upper_bounds, strict=True)
    ) + (energy.net_gain_center_maximum_v - energy.net_gain_center_minimum_v,)
    slope_scale = _slope_tolerance(contract, energy.mirror_energy_nodes_v)
    residual_scales = (
        slope_scale,
        slope_scale,
        slope_scale,
        _finite(profile["maximum_gamma_target_residual_degrees"], "gamma tolerance"),
        1.0,
    )
    numerics = contract["dual_stripe_l0"]["determination_numerics"]
    center_residual = residual(center)
    classification = classify_constraint_system(
        names,
        residual_names,
        jacobian_rows=jacobian.tolist(),
        residuals=center_residual.tolist(),
        parameter_scales=parameter_scales,
        residual_scales=residual_scales,
        relative_rank_tolerance=_finite(
            numerics["relative_singular_value_rank_tolerance"], "rank tolerance"
        ),
        compatibility_tolerance=_finite(
            numerics["scaled_irreducible_residual_norm_tolerance"], "compatibility tolerance"
        ),
    )
    return {
        "analytically_eliminated_unknowns": ["stripe_set_1_bias_v", "stripe_set_2_bias_v"],
        "elimination_equations": [
            "turning_pseudopotential_equals_declared_source_slow_energy",
            "spatial_return_kappa_prime_equals_zero",
        ],
        "unknown_names": list(names),
        "residual_names": list(residual_names),
        "raw_residuals": center_residual.tolist(),
        "parameter_scales": list(parameter_scales),
        "residual_scales": list(residual_scales),
        "finite_difference_steps": steps.tolist(),
        "jacobian_rows": jacobian.tolist(),
        "classification": asdict(classification),
    }


def solve_exact_k_operating_point(
    mirror_manifest_path: Path, contract_path: Path,
) -> dict[str, Any]:
    """Find and validate all exact-K roots on the managed gamma branches."""
    contract = load_contract(contract_path)
    managed = load_managed_mirror_candidate(mirror_manifest_path, contract_path)
    shape_selection = build_native_stripe_shape_selection(contract)
    shape_root = shape_selection.shape_root
    kappa_1 = shape_root.kappa_1
    envelope = derive_operating_energy_envelope(contract)
    selector = contract["mirror"]["theory_requirements"].get("exact_k_operating_point_selection")
    if not isinstance(selector, dict) or selector.get("status") != EXACT_K_SELECTOR_STATUS:
        raise CandidateContractError("exact-K operating-point selection contract is incomplete")
    node_count = _positive_integer(selector["energy_bracket_node_count"], "energy bracket nodes")
    if node_count < 2:
        raise CandidateContractError("exact-K energy bracket requires at least two nodes")
    energy_nodes = np.linspace(
        envelope.net_gain_center_minimum_v,
        envelope.net_gain_center_maximum_v,
        node_count,
    )
    requested_workers = _positive_integer(
        selector["maximum_parallel_energy_workers"],
        "maximum parallel energy workers",
    )
    actual_workers = min(node_count, requested_workers, os.cpu_count() or 1)
    roots: list[dict[str, Any]] = []
    branch_audits: list[dict[str, Any]] = []
    for branch_index, seed in enumerate(managed.root_family):
        cache: dict[float, tuple[ExactKPoint, dict[str, object]]] = {}

        def evaluate(value: float) -> tuple[ExactKPoint, dict[str, object]]:
            key = float(value)
            if key not in cache:
                continuation = min(
                    (cached[0] for cached in cache.values()),
                    key=lambda point: abs(point.energy_per_charge_v - key),
                    default=None,
                )
                cache[key] = evaluate_branch_at_energy(
                    contract, seed, branch_index, key, shape_root, continuation,
                )
            return cache[key]

        payloads = [
            (contract, seed, branch_index, float(value), shape_root)
            for value in energy_nodes
        ]
        if actual_workers == 1:
            worker_results = [_evaluate_energy_node_worker(payload) for payload in payloads]
        else:
            with ProcessPoolExecutor(max_workers=actual_workers) as executor:
                worker_results = list(executor.map(_evaluate_energy_node_worker, payloads))
        initial_failures: dict[float, str] = {}
        for energy_value, point, receipt, error in worker_results:
            if point is None or receipt is None:
                initial_failures[energy_value] = error or "unknown independent-node failure"
                continue
            cache[energy_value] = (point, receipt)
        for energy_value in sorted(initial_failures):
            try:
                evaluate(energy_value)
            except Exception as error:
                raise CandidateContractError(
                    "parallel energy node and serial continuation retry both failed at "
                    f"{energy_value:.12g} V: parallel={initial_failures[energy_value]}; "
                    f"serial={type(error).__name__}: {error}"
                ) from error
        sampled = [cache[float(value)][0] for value in energy_nodes]
        brackets = []
        for lower, upper in zip(sampled[:-1], sampled[1:], strict=True):
            if lower.exact_k_residual == 0.0:
                brackets.append((lower.energy_per_charge_v, lower.energy_per_charge_v))
            elif lower.exact_k_residual * upper.exact_k_residual < 0.0:
                brackets.append((lower.energy_per_charge_v, upper.energy_per_charge_v))
        if sampled[-1].exact_k_residual == 0.0:
            brackets.append((sampled[-1].energy_per_charge_v, sampled[-1].energy_per_charge_v))
        branch_audits.append({
            "branch_index": branch_index,
            "source_l0_restart_index": seed.source_l0_restart_index,
            "sampled_points": [asdict(point) for point in sampled],
            "sign_change_brackets_v": [list(bracket) for bracket in brackets],
            "parallel_energy_scan": {
                "requested_workers": requested_workers,
                "actual_workers": actual_workers,
                "independent_node_count": node_count,
                "serial_retry_count": len(initial_failures),
                "serial_retry_initial_errors": initial_failures,
            },
        })
        for lower, upper in brackets:
            if lower == upper:
                selected_energy = lower
            else:
                selected_energy = brentq(
                    lambda value: evaluate(value)[0].exact_k_residual,
                    lower,
                    upper,
                    xtol=_finite(selector["energy_root_absolute_tolerance_v"], "energy root tolerance"),
                    maxiter=_positive_integer(selector["maximum_root_iterations"], "energy root iterations"),
                )
            approximate, _nested_refined = evaluate(selected_energy)
            point, refined = _joint_refine_exact_k(
                contract, seed, approximate, shape_root,
            )
            k_residual_tolerance = _finite(
                selector["maximum_abs_numerical_k_residual"], "K residual tolerance"
            )
            if abs(point.exact_k_residual) > k_residual_tolerance:
                raise CandidateContractError(
                    "exact-K root residual "
                    f"{point.exact_k_residual:.12g} exceeds tolerance {k_residual_tolerance:.12g}"
                )
            convergence = _probe_convergence(contract, point, seed)
            definition = _definition_receipt(contract, point, seed, shape_root)
            roots.append({
                "point": asdict(point),
                "probe_convergence": convergence,
                "definition": definition,
                "refined_mirror_receipt": refined,
            })
    if not roots:
        raise CandidateContractError("no managed mirror branch brackets the target drift-period ratio")
    roots.sort(key=lambda item: (
        abs(float(item["point"]["energy_per_charge_v"]) - envelope.net_gain_reference_center_v),
        max(abs(float(value)) for value in item["point"]["mirror_voltages_v"]),
    ))
    selected = roots[0]
    if selected["probe_convergence"]["status"] != "pass":
        raise CandidateContractError("selected exact-K root failed the declared L1 probe convergence")
    if selected["definition"]["classification"]["status"] != "square_exact":
        raise CandidateContractError("selected exact-K system is not locally square and full rank")
    point = selected["point"]
    mass_th = _finite(contract["particle_source"]["species"]["mass_th"], "ion mass")
    energy_j = float(point["energy_per_charge_v"]) * 1.602176634e-19
    mass_kg = mass_th * 1.66053906660e-27
    period_us = (
        float(point["mirror_axial_width_w_mm"]) * 1.0e-3
        * math.sqrt(2.0 * mass_kg / energy_j) * 1.0e6
    )
    return {
        "schema_version": 2,
        "role": "mrtof_exact_k_mirror_energy_operating_point",
        "status": EXACT_K_SUMMARY_STATUS,
        "qualification": "solver_neutral_2d_system_selection__not_simion_voltage_authority",
        "input": {
            "mirror_manifest": {
                "path": str(mirror_manifest_path.resolve()),
                "sha256": file_sha256(mirror_manifest_path),
                "run_id": managed.run_id,
            },
            "contract": {"path": str(contract_path.resolve()), "sha256": file_sha256(contract_path)},
        },
        "governing_equation": "T_D_stripe_on(E_z,v1(E_z),v2(E_z))/T_0=K",
        "native_stripe_spatial_shape_selection": shape_selection.receipt(),
        "energy_search_interval_per_charge_v": [
            envelope.net_gain_center_minimum_v,
            envelope.net_gain_center_maximum_v,
        ],
        "branch_audits": branch_audits,
        "root_count": len(roots),
        "roots": roots,
        "selected_root_index": 0,
        "selected_operating_point": {
            **point,
            "native_kappa_1": kappa_1,
            "mirror_full_two_mirror_period_T0_us_for_declared_mass": period_us,
            "post_acceleration_total_energy_ev": (
                float(point["energy_per_charge_v"]) + _drift_inputs(contract)[1]
            ),
        },
        "limitations": [
            "The exact-K equation selects among independently mirror-qualified energy points; it is not an extra axial mirror equation.",
            "At each energy, v1 and v2 are analytically eliminated by the declared 5-eV turn and native kappa-prime=0 equations before evaluating the Stripe-on local-period K.",
            "The four time-platform nodes and three full-analyser energy-slope values remain diagnostics of the fixed manufactured curves; they are not duplicated as extra v1/v2 equations.",
            "The printed paper target is only a nonphysical locator for a connected native shape-root branch; it is not the active kappa authority.",
            "This is an ideal two-dimensional analytic result. Peak field, finite slots and covers, PA fields, P1/P2 transport, and SIMION flight remain pending.",
            "No baseline voltage or solver file is modified by this receipt.",
        ],
    }


def main() -> int:
    ensure_heavy_entry(
        "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_exact_k_operating_point"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-manifest", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = solve_exact_k_operating_point(arguments.mirror_manifest, arguments.contract)
    except (CandidateContractError, KeyError, TypeError, ValueError) as error:
        print(f"MRTOF_EXACT_K_OPERATING_POINT=FAIL ERROR={error}")
        return 1
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    point = result["selected_operating_point"]
    print(
        "MRTOF_EXACT_K_OPERATING_POINT=PASS "
        f"ENERGY_V={point['energy_per_charge_v']:.12g} "
        f"K_RESIDUAL={point['exact_k_residual']:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
