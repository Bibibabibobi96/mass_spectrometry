"""Bind the native Stripe spatial-shape solve to the frozen MR contract.

The underlying shape solve is mirror-, energy-, and voltage-independent.
This adapter supplies only the manufactured path functions, coordinate/L
registration, a paper-neighbourhood branch locator, explicit numerical
controls, and a narrow geometry identity.  The paper locator never supplies
the resulting kappa or a Stripe voltage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from common.contracts.file_identity import canonical_json_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    ManufacturedStripeBasisPathScales,
    NativeStripeSpatialReturnNumerics,
    NativeStripeSpatialShapeRoot,
    derive_native_stripe_branch_validation_sample_count,
    endpoint_regularized_kappa,
    identify_manufactured_basis_path_scales,
    kappa_derivative_at_turn,
    project_y_from_theory_drift_mm,
    solve_native_stripe_spatial_shape_branch,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_path_length_evaluator,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


NATIVE_SHAPE_BRANCH_STATUS = "native_geometry_spatial_return_branch"
NATIVE_SHAPE_REFERENCE_AUTHORITY = (
    "manufactured_geometry_lambda_1_over_lambda_2__paper_branch_locator_only"
)


@dataclass(frozen=True)
class NativeStripeShapeSelection:
    """One contract-bound native shape root and its nonphysical branch locator."""

    shape_root: NativeStripeSpatialShapeRoot
    geometry_projection_sha256: str
    reference_basis_sha256: str
    basis_path_scales: ManufacturedStripeBasisPathScales
    numerics: NativeStripeSpatialReturnNumerics
    maximum_abs_kappa_prime_numerical_residual: float

    def receipt(self) -> dict[str, Any]:
        """Return the complete JSON-safe receipt consumed by exact-K downstream."""
        return {
            "schema_version": 1,
            "status": NATIVE_SHAPE_BRANCH_STATUS,
            "qualification": "native_geometry_spatial_shape_root__not_voltage_or_3d_authority",
            "geometry_projection_identity": {
                "algorithm": "canonical_json_sha256",
                "sha256": self.geometry_projection_sha256,
            },
            "branch_locator": {
                "authority": NATIVE_SHAPE_REFERENCE_AUTHORITY,
                "basis_coefficients_source": (
                    "dual_stripe_l0.dimensionless_paper_target."
                    "published_printed_reference_c0_to_c5"
                ),
                "basis_coefficients_sha256": self.reference_basis_sha256,
                "basis_path_scales": asdict(self.basis_path_scales),
                "semantics": (
                    "The printed paper branch locates one connected native root only; "
                    "the native path functions determine r, kappa, and kappa-prime."
                ),
            },
            "numerics": {
                **asdict(self.numerics),
                "kappa_derivative_step_source": (
                    "dual_stripe_l0.operating_seed_search.kappa_derivative_step"
                ),
                "branch_validation_sample_count_source": (
                    "native B-spline spans times sampling_per_nonzero_knot_span "
                    "times turning_search_sampling_multiplier"
                ),
            },
            "spatial_shape_root": asdict(self.shape_root),
            "kappa_prime_numerical_gate": {
                "maximum_abs_residual": self.maximum_abs_kappa_prime_numerical_residual,
                "actual_abs_residual": abs(self.shape_root.kappa_prime),
                "passed": (
                    abs(self.shape_root.kappa_prime)
                    <= self.maximum_abs_kappa_prime_numerical_residual
                ),
                "source": "dual_stripe_l0.operating_seed_search.residual_tolerances[1]",
                "semantics": "float64 root residual control; not a physical acceptance tolerance",
            },
        }


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be numeric") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CandidateContractError(f"{label} must be a positive integer")
    return value


def _geometry_projection(contract: dict[str, Any]) -> dict[str, Any]:
    """Return exactly the contract fields defining native paths and y/L registration."""
    try:
        stripe_l0 = contract["dual_stripe_l0"]
        return {
            "schema_version": 1,
            "theory_profile": contract["dual_stripe"]["theory_profile"],
            "coordinate_mapping": stripe_l0["coordinate_mapping"],
            "theory_function_coordinate_registration": stripe_l0[
                "theory_function_coordinate_registration"
            ],
            "manufactured_design_abs_drift_length_L_mm": stripe_l0[
                "manufactured_design_abs_drift_length_L_mm"
            ],
        }
    except (KeyError, TypeError) as error:
        raise CandidateContractError("native Stripe geometry identity projection is incomplete") from error


def native_stripe_geometry_projection_sha256(contract: dict[str, Any]) -> str:
    """Hash the sole contract projection that defines native Stripe geometry."""
    return canonical_json_sha256(_geometry_projection(contract))


def _reference_coefficients(contract: dict[str, Any]) -> tuple[float, ...]:
    try:
        values = contract["dual_stripe_l0"]["dimensionless_paper_target"][
            "published_printed_reference_c0_to_c5"
        ]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("native Stripe branch locator lacks its paper reference") from error
    if not isinstance(values, (list, tuple)) or len(values) != 6:
        raise CandidateContractError("native Stripe paper branch locator requires c0..c5")
    return tuple(_finite(value, "native Stripe branch reference coefficient") for value in values)


def _settings(contract: dict[str, Any]) -> dict[str, Any]:
    block = contract.get("dual_stripe_l0")
    settings = block.get("native_spatial_shape_branch") if isinstance(block, dict) else None
    if not isinstance(settings, dict) or settings.get("status") != NATIVE_SHAPE_BRANCH_STATUS:
        raise CandidateContractError("native Stripe spatial-shape branch contract is incomplete")
    if settings.get("reference_ratio_authority") != NATIVE_SHAPE_REFERENCE_AUTHORITY:
        raise CandidateContractError("native Stripe branch reference-ratio authority is unsupported")
    return settings


def _numerics(contract: dict[str, Any], settings: dict[str, Any]) -> NativeStripeSpatialReturnNumerics:
    try:
        profile = contract["dual_stripe_l0"]["operating_seed_search"]
        return NativeStripeSpatialReturnNumerics(
            kappa_derivative_step=_finite(profile["kappa_derivative_step"], "kappa derivative step"),
            initial_ratio_half_width=_finite(settings["initial_ratio_half_width"], "ratio half-width"),
            search_expansion_factor=_finite(settings["search_expansion_factor"], "ratio expansion factor"),
            maximum_search_expansions=_positive_integer(
                settings["maximum_search_expansions"], "ratio search expansions"
            ),
            branch_validation_sample_count=derive_native_stripe_branch_validation_sample_count(contract),
            root_absolute_tolerance=_finite(
                settings["root_absolute_tolerance"], "ratio root absolute tolerance"
            ),
            root_relative_tolerance=_finite(
                settings["root_relative_tolerance"], "ratio root relative tolerance"
            ),
            maximum_root_iterations=_positive_integer(
                settings["maximum_root_iterations"], "ratio root iterations"
            ),
        )
    except (KeyError, TypeError) as error:
        raise CandidateContractError(
            "native Stripe spatial-shape numerical controls are incomplete"
        ) from error


def _kappa_prime_tolerance(contract: dict[str, Any]) -> float:
    values = contract["dual_stripe_l0"]["operating_seed_search"].get("residual_tolerances")
    if not isinstance(values, list) or len(values) != 2:
        raise CandidateContractError("Stripe seed residual tolerances must identify K and kappa-prime")
    tolerance = _finite(values[1], "native Stripe kappa-prime numerical tolerance")
    if tolerance <= 0.0:
        raise CandidateContractError("native Stripe kappa-prime numerical tolerance must be positive")
    return tolerance


def _evaluate_native_shape(
    contract: dict[str, Any],
    *,
    entry_y_mm: float,
    turning_y_mm: float,
    relative_action_weight_ratio: float,
    kappa_derivative_step: float,
) -> tuple[float, float, tuple[float, float]]:
    """Evaluate, but do not re-solve, one serialized native shape ratio."""
    paths = tuple(
        compile_dual_stripe_path_length_evaluator(contract, name)
        for name in ("set_1", "set_2")
    )
    direction_length = turning_y_mm - entry_y_mm
    entry_paths = tuple(path(entry_y_mm) for path in paths)

    def delta(index: int, eta: float) -> float:
        coordinate = entry_y_mm + direction_length * eta
        return paths[index](coordinate) - entry_paths[index]

    deltas = (delta(0, 1.0), delta(1, 1.0))
    denominator = deltas[0] + relative_action_weight_ratio * deltas[1]
    if denominator == 0.0:
        raise CandidateContractError("native Stripe serialized ratio has zero normalization")

    def profile(eta: float) -> float:
        return (
            delta(0, eta) + relative_action_weight_ratio * delta(1, eta)
        ) / denominator

    return (
        endpoint_regularized_kappa(profile),
        kappa_derivative_at_turn(profile, 1.0, step=kappa_derivative_step),
        deltas,
    )


def build_native_stripe_shape_selection(contract: dict[str, Any]) -> NativeStripeShapeSelection:
    """Solve the contract-bound native spatial shape once, before mirror exact-K."""
    settings = _settings(contract)
    coefficients = _reference_coefficients(contract)
    scales = identify_manufactured_basis_path_scales(
        contract, basis_coefficients_c0_to_c5=coefficients,
    )
    geometry_sha = native_stripe_geometry_projection_sha256(contract)
    numerics = _numerics(contract, settings)
    entry = project_y_from_theory_drift_mm(contract, 0.0)
    turning = project_y_from_theory_drift_mm(contract, scales.drift_length_l_mm)
    direction = 1.0 if turning > entry else -1.0
    root = solve_native_stripe_spatial_shape_branch(
        tuple(
            compile_dual_stripe_path_length_evaluator(contract, name)
            for name in ("set_1", "set_2")
        ),
        entry_y_mm=entry,
        drift_length_l_mm=scales.drift_length_l_mm,
        drift_direction_sign=direction,
        reference_relative_action_weight_ratio=(
            scales.reference_relative_action_weight_ratio
        ),
        geometry_input_identity_source=f"canonical_json_sha256:{geometry_sha}",
        numerics=numerics,
    )
    tolerance = _kappa_prime_tolerance(contract)
    if abs(root.kappa_prime) > tolerance:
        raise CandidateContractError(
            "native Stripe spatial-shape root exceeds its kappa-prime numerical gate"
        )
    return NativeStripeShapeSelection(
        shape_root=root,
        geometry_projection_sha256=geometry_sha,
        reference_basis_sha256=canonical_json_sha256({"c0_to_c5": list(coefficients)}),
        basis_path_scales=scales,
        numerics=numerics,
        maximum_abs_kappa_prime_numerical_residual=tolerance,
    )


def load_native_stripe_shape_selection(
    value: object, contract: dict[str, Any],
) -> NativeStripeShapeSelection:
    """Load and validate one serialized shape selection against its contract."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CandidateContractError("native Stripe shape receipt must use schema version 1")
    if value.get("status") != NATIVE_SHAPE_BRANCH_STATUS:
        raise CandidateContractError("native Stripe shape receipt has the wrong status")
    settings = _settings(contract)
    coefficients = _reference_coefficients(contract)
    scales = identify_manufactured_basis_path_scales(
        contract, basis_coefficients_c0_to_c5=coefficients,
    )
    geometry_sha = native_stripe_geometry_projection_sha256(contract)
    geometry_identity = value.get("geometry_projection_identity")
    branch_locator = value.get("branch_locator")
    serialized_scales = (
        branch_locator.get("basis_path_scales")
        if isinstance(branch_locator, dict)
        else None
    )
    if (
        not isinstance(geometry_identity, dict)
        or geometry_identity.get("algorithm") != "canonical_json_sha256"
        or geometry_identity.get("sha256") != geometry_sha
        or not isinstance(branch_locator, dict)
        or branch_locator.get("authority") != NATIVE_SHAPE_REFERENCE_AUTHORITY
        or branch_locator.get("basis_coefficients_sha256")
        != canonical_json_sha256({"c0_to_c5": list(coefficients)})
        or not isinstance(serialized_scales, dict)
        or canonical_json_sha256(serialized_scales)
        != canonical_json_sha256(asdict(scales))
    ):
        raise CandidateContractError("native Stripe shape geometry or branch-locator identity changed")

    numerics = _numerics(contract, settings)
    numerics_receipt = value.get("numerics")
    if not isinstance(numerics_receipt, dict) or any(
        numerics_receipt.get(name) != expected
        for name, expected in asdict(numerics).items()
    ):
        raise CandidateContractError("native Stripe shape numerical controls differ from the contract")
    root_value = value.get("spatial_shape_root")
    if not isinstance(root_value, dict):
        raise CandidateContractError("native Stripe shape receipt lacks its solved root")

    def pair(name: str) -> tuple[float, float]:
        items = root_value.get(name)
        if not isinstance(items, (list, tuple)) or len(items) != 2:
            raise CandidateContractError(f"native Stripe shape root {name} must have two values")
        return tuple(_finite(item, f"native Stripe shape root {name}") for item in items)

    root = NativeStripeSpatialShapeRoot(
        geometry_input_identity_source=str(root_value.get("geometry_input_identity_source", "")),
        entry_y_mm=_finite(root_value.get("entry_y_mm"), "native Stripe shape entry"),
        turning_y_mm=_finite(root_value.get("turning_y_mm"), "native Stripe shape turn"),
        drift_length_l_mm=_finite(root_value.get("drift_length_l_mm"), "native Stripe shape L"),
        drift_direction_sign=_finite(root_value.get("drift_direction_sign"), "native Stripe shape direction"),
        reference_relative_action_weight_ratio=_finite(
            root_value.get("reference_relative_action_weight_ratio"), "native Stripe reference ratio"
        ),
        reference_kappa_prime=_finite(root_value.get("reference_kappa_prime"), "native Stripe reference kappa-prime"),
        relative_action_weight_ratio=_finite(
            root_value.get("relative_action_weight_ratio"), "native Stripe solved ratio"
        ),
        kappa_1=_finite(root_value.get("kappa_1"), "native Stripe kappa"),
        kappa_prime=_finite(root_value.get("kappa_prime"), "native Stripe kappa-prime"),
        delta_path_lengths_at_turn_mm=pair("delta_path_lengths_at_turn_mm"),
        root_bracket=pair("root_bracket"),
        searched_parameter_range=pair("searched_parameter_range"),
        validated_branch_sample_range=pair("validated_branch_sample_range"),
        validated_branch_sample_count=_positive_integer(
            root_value.get("validated_branch_sample_count"), "native Stripe validated samples"
        ),
    )
    entry = project_y_from_theory_drift_mm(contract, 0.0)
    turning = project_y_from_theory_drift_mm(contract, scales.drift_length_l_mm)
    direction = 1.0 if turning > entry else -1.0
    tolerance = _kappa_prime_tolerance(contract)
    evaluated_kappa, evaluated_kappa_prime, evaluated_deltas = _evaluate_native_shape(
        contract,
        entry_y_mm=entry,
        turning_y_mm=turning,
        relative_action_weight_ratio=root.relative_action_weight_ratio,
        kappa_derivative_step=numerics.kappa_derivative_step,
    )
    _, evaluated_reference_kappa_prime, _ = _evaluate_native_shape(
        contract,
        entry_y_mm=entry,
        turning_y_mm=turning,
        relative_action_weight_ratio=root.reference_relative_action_weight_ratio,
        kappa_derivative_step=numerics.kappa_derivative_step,
    )
    close = lambda left, right: math.isclose(  # noqa: E731
        left,
        right,
        rel_tol=numerics.root_relative_tolerance,
        abs_tol=numerics.root_absolute_tolerance,
    )
    if (
        root.geometry_input_identity_source != f"canonical_json_sha256:{geometry_sha}"
        or root.entry_y_mm != entry
        or root.turning_y_mm != turning
        or root.drift_length_l_mm != scales.drift_length_l_mm
        or root.drift_direction_sign != direction
        or root.reference_relative_action_weight_ratio
        != scales.reference_relative_action_weight_ratio
        or root.kappa_1 <= 0.0
        or abs(root.kappa_prime) > tolerance
        or not close(root.kappa_1, evaluated_kappa)
        or not close(root.kappa_prime, evaluated_kappa_prime)
        or not close(root.reference_kappa_prime, evaluated_reference_kappa_prime)
        or any(
            not close(serialized, evaluated)
            for serialized, evaluated in zip(
                root.delta_path_lengths_at_turn_mm,
                evaluated_deltas,
                strict=True,
            )
        )
        or not root.root_bracket[0] <= root.relative_action_weight_ratio <= root.root_bracket[1]
    ):
        raise CandidateContractError("native Stripe shape root conflicts with its contract or numerical gate")
    gate = value.get("kappa_prime_numerical_gate")
    if (
        not isinstance(gate, dict)
        or gate.get("maximum_abs_residual") != tolerance
        or gate.get("actual_abs_residual") != abs(root.kappa_prime)
        or gate.get("passed") is not True
        or gate.get("source")
        != "dual_stripe_l0.operating_seed_search.residual_tolerances[1]"
    ):
        raise CandidateContractError("native Stripe shape receipt lacks its kappa-prime gate")
    return NativeStripeShapeSelection(
        shape_root=root,
        geometry_projection_sha256=geometry_sha,
        reference_basis_sha256=canonical_json_sha256({"c0_to_c5": list(coefficients)}),
        basis_path_scales=scales,
        numerics=numerics,
        maximum_abs_kappa_prime_numerical_residual=tolerance,
    )
