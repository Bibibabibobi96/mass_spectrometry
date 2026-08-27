"""Paired numerical-source experiments using the existing exact axial oracle.

This is a policy-free analysis boundary: no solver launch, source fitting, files,
or experiment selection. Coordinates are mm, velocities m/s and TOFs microseconds
from the common ideal instantaneous extraction pulse. Transverse acceptance,
fringe fields and detector response are outside this one-dimensional model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtri

from common.analysis.peak_metrics import AnalysisSettings, compute_peak_metrics
from projects.single_reflection_oa_tof_mass_analyzer.analysis.oatof_oaaccelerator_coupling import (
    CoupledReflectronSolution,
    solve_coupled_reflectron_from_accelerator_derivatives,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    ThreeZoneState,
    compute_time_derivatives,
    derive_three_zone_state,
    exact_total_normalized_time_from_state,
)


@dataclass(frozen=True)
class NumericalSourceSpec:
    """Prescribed axial conditional mean; no detector-dependent fit is made."""

    mass_to_charge_th: float
    center_x_mm: float
    center_velocity_m_per_s: float
    velocity_slope_m_per_s_per_mm: float
    velocity_quadratic_m_per_s_per_mm2: float = 0.0

    def __post_init__(self) -> None:
        if not all(np.isfinite(value) for value in asdict(self).values()):
            raise ValueError("source parameters must be finite")
        if self.mass_to_charge_th <= 0:
            raise ValueError("mass_to_charge_th must be positive")

    def affine(self, slope: float | None = None) -> AffineSource:
        """Return the center tangent used by the existing linear working-point law."""

        return AffineSource.from_velocity(
            mass_to_charge_th=self.mass_to_charge_th,
            center_x_mm=self.center_x_mm,
            center_velocity_m_per_s=self.center_velocity_m_per_s,
            velocity_slope_m_per_s_per_mm=(
                self.velocity_slope_m_per_s_per_mm if slope is None else slope
            ),
        )


@dataclass(frozen=True)
class AxialParticleSource:
    """Complete finite mother cohort, also usable for externally frozen axial states."""

    particle_id: NDArray[np.int64]
    source_x_mm: NDArray[np.float64]
    velocity_z_m_per_s: NDArray[np.float64]
    residual_m_per_s: NDArray[np.float64]
    mass_to_charge_th: float

    def __post_init__(self) -> None:
        ids = np.asarray(self.particle_id)
        if ids.ndim != 1 or not ids.size or not np.issubdtype(ids.dtype, np.integer):
            raise ValueError("particle_id must be a nonempty integer vector")
        if np.any(ids <= 0) or np.unique(ids).size != ids.size:
            raise ValueError("particle_id must be positive and unique")
        if not np.isfinite(self.mass_to_charge_th) or self.mass_to_charge_th <= 0:
            raise ValueError("mass_to_charge_th must be positive and finite")
        for name in ("source_x_mm", "velocity_z_m_per_s", "residual_m_per_s"):
            values = np.asarray(getattr(self, name), dtype=float)
            if values.shape != ids.shape or not np.all(np.isfinite(values)):
                raise ValueError(f"{name} must be finite and match particle_id")
            values = values.copy()
            values.setflags(write=False)
            object.__setattr__(self, name, values)
        ids = ids.astype(np.int64, copy=True)
        ids.setflags(write=False)
        object.__setattr__(self, "particle_id", ids)


def build_numerical_source(
    spec: NumericalSourceSpec,
    *,
    particle_count: int,
    seed: int,
    full_width_mm: float,
    residual_sigma_m_per_s: float,
) -> AxialParticleSource:
    """Generate uniform positions and independent Gaussian velocity residuals.

The same seed fixes two random variates per particle, so changing sample count
preserves prefixes and changing width or residual amplitude preserves pairing.
Residuals are not recentered, normalized, clipped or fitted to the sample.
"""

    if isinstance(particle_count, bool) or not isinstance(particle_count, int) or particle_count < 1:
        raise ValueError("particle_count must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    for name, value in (("full_width_mm", full_width_mm), ("residual_sigma_m_per_s", residual_sigma_m_per_s)):
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    uniforms = np.random.default_rng(seed).random((particle_count, 2))
    offset = (uniforms[:, 0] - 0.5) * full_width_mm
    # Map the finite RNG interval into (0, 1) so inverse-normal endpoints cannot
    # create infinities. This numerical conversion does not rescale the sample.
    probability = (uniforms[:, 1] * (1.0 - np.finfo(float).eps)) + np.finfo(float).eps / 2.0
    residual = ndtri(probability) * residual_sigma_m_per_s
    velocity = (
        spec.center_velocity_m_per_s
        + spec.velocity_slope_m_per_s_per_mm * offset
        + spec.velocity_quadratic_m_per_s_per_mm2 * offset**2
        + residual
    )
    return AxialParticleSource(
        particle_id=np.arange(1, particle_count + 1, dtype=np.int64),
        source_x_mm=spec.center_x_mm + offset,
        velocity_z_m_per_s=velocity,
        residual_m_per_s=residual,
        mass_to_charge_th=spec.mass_to_charge_th,
    )


@dataclass(frozen=True)
class IdealWorkingPoint:
    """Fixed geometry and electrode settings; a reference plane is not a moving focus."""

    design_source: AffineSource
    state: ThreeZoneState
    reflectron: ReflectronGeometry
    inner: InnerSolution
    focus_drift_mm: float
    reflectron_solution: CoupledReflectronSolution

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe voltages, fixed lengths, and the analytic closure receipt."""

        result = asdict(self)
        result["accelerator_exit_to_reflectron_mm"] = self.focus_drift_mm + self.reflectron.upstream_drift_mm
        result["reflectron_backplate_voltage_v"] = (
            self.inner.stage1_voltage_drop_v
            + self.inner.stage2_field_v_per_mm * self.reflectron.stage2_length_mm
        )
        result["working_point_policy"] = "fixed_accelerator_and_geometry_recompute_two_reflectron_fields"
        result["source_model_for_design"] = "prescribed_center_tangent_not_detector_fit"
        result["derivative_reference"] = "fixed_reference_plane_not_relocated_accelerator_focus"
        return result


def build_working_point(
    spec: NumericalSourceSpec,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    *,
    design_velocity_slope_m_per_s_per_mm: float,
    eta: float,
    focus_drift_mm: float,
) -> IdealWorkingPoint:
    """Match the existing affine-source law by changing only mirror voltages.

All physical lengths and accelerator fields remain fixed across design slopes.
The core derivative API derives an accelerator focus; its drift contribution is
translated analytically to the caller's *fixed* reference plane before matching.
The quadratic source term is deliberately not included in this affine law.
"""

    if not np.isfinite(focus_drift_mm) or focus_drift_mm < 0:
        raise ValueError("focus_drift_mm must be finite and nonnegative")
    source = spec.affine(design_velocity_slope_m_per_s_per_mm)
    state = derive_three_zone_state(source, outer, eta)
    # Only accelerator_components are consumed; this positive interior mirror is
    # a disposable derivative argument, never a candidate or propagation setting.
    temporary = InnerSolution(state.center_energy_per_charge_v / 2.0, 1.0, eta)
    derivatives = compute_time_derivatives(source, state, reflectron, temporary)
    delta_drift = focus_drift_mm - derivatives.focus_drift_after_exit_mm
    energy = state.center_energy_per_charge_v
    first = derivatives.accelerator_components[0] - delta_drift / (2.0 * energy**1.5)
    second = derivatives.accelerator_components[1] + 3.0 * delta_drift / (4.0 * energy**2.5)
    third = derivatives.accelerator_components[2] - 15.0 * delta_drift / (8.0 * energy**3.5)
    solution = solve_coupled_reflectron_from_accelerator_derivatives(
        energy,
        reflectron.stage1_length_mm,
        reflectron.upstream_drift_mm,
        reflectron.downstream_drift_mm,
        first,
        second,
        accelerator_third_derivative=third,
    )
    inner = InnerSolution(solution.stage1_voltage_drop_v, solution.stage2_field_v_per_mm, eta)
    return IdealWorkingPoint(source, state, reflectron, inner, focus_drift_mm, solution)


@dataclass(frozen=True)
class IdealPropagationResult:
    """Full mother-cohort outcomes; non-arrivals have NaN TOF, never fabricated times."""

    particle_id: NDArray[np.int64]
    classification: NDArray[np.str_]
    tof_us: NDArray[np.float64]
    summary: dict[str, Any]


def _classify_source(source: AxialParticleSource, point: IdealWorkingPoint) -> tuple[NDArray[np.str_], NDArray[np.float64]]:
    """Classify mutually exclusive physical/model-domain outcomes before square roots."""

    state, inner = point.state, point.inner
    chi = source.velocity_z_m_per_s * point.design_source.time_scale_s_per_mm_sqrt_v * 1.0e3
    energy = state.repeller_v - state.field1_v_per_mm * source.source_x_mm + chi**2
    classes = np.full(source.particle_id.size, "detector_arrival", dtype="U64")
    conditions = (
        ("source_outside_first_acceleration_zone", (source.source_x_mm <= 0) | (source.source_x_mm >= state.zone1_length_mm)),
        ("repeller_collision", (chi < 0) & (source.source_x_mm - chi**2 / state.field1_v_per_mm <= 0)),
        ("accelerator_grid1_unreachable", energy <= state.grid1_v),
        ("reflectron_stage1_turn_model_unsupported", energy <= inner.stage1_voltage_drop_v),
        ("reflectron_backplate_collision", (energy - inner.stage1_voltage_drop_v) / inner.stage2_field_v_per_mm >= point.reflectron.stage2_length_mm),
    )
    for label, mask in conditions:
        classes[(classes == "detector_arrival") & mask] = label
    return classes, chi


def _peak_summary(times: NDArray[np.float64], mass: float, settings: AnalysisSettings) -> dict[str, Any]:
    """Represent no-hit and singular peaks explicitly without inventing finite R."""

    if times.size < 3:
        return {"status": "NO_ARRIVALS" if not times.size else "INSUFFICIENT_ARRIVALS", "reason": "Canonical KDE requires at least three arrivals.", "peak_metrics": None}
    if np.ptp(times) <= 32.0 * np.spacing(float(np.max(times))):
        return {"status": "SINGULAR_OR_NUMERICALLY_UNRESOLVED_PEAK", "reason": "Arrival spread is at most 32 float64 spacings; no finite FWHM or resolution is claimed.", "peak_metrics": None}
    try:
        metrics, _ = compute_peak_metrics(times, mass, settings)
    except (ValueError, np.linalg.LinAlgError) as error:
        return {"status": "PEAK_METRICS_FAILED", "reason": str(error), "peak_metrics": None}
    if not all(np.isfinite(value) for value in metrics.values()):
        return {"status": "PEAK_METRICS_FAILED", "reason": "Canonical metrics contain a non-finite value.", "peak_metrics": None}
    quantiles = np.quantile(times, (0.01, 0.05, 0.95, 0.99))
    return {
        "status": "SUCCESS", "reason": None, "peak_metrics": metrics,
        "quantile_width_90_ns": float((quantiles[2] - quantiles[1]) * 1.0e3),
        "quantile_width_98_ns": float((quantiles[3] - quantiles[0]) * 1.0e3),
        "arrival_time_span_ns": float(np.ptp(times) * 1.0e3),
    }


def propagate_ideal_source(
    source: AxialParticleSource,
    working_point: IdealWorkingPoint,
    *,
    settings: AnalysisSettings,
) -> IdealPropagationResult:
    """Compute exact pulse-relative TOFs and canonical peaks for all valid particles.

No common-hit intersection or post-hoc filtering is applied. Stage-one mirror
turns are explicitly outside the reused two-stage formula, not asserted physical
losses. The returned fraction is axial model reachability, not 3D collection.
"""

    expected_scale = AffineSource.from_velocity(
        mass_to_charge_th=source.mass_to_charge_th, center_x_mm=0.0,
        center_velocity_m_per_s=0.0, velocity_slope_m_per_s_per_mm=0.0,
    ).time_scale_s_per_mm_sqrt_v
    if expected_scale != working_point.design_source.time_scale_s_per_mm_sqrt_v:
        raise ValueError("source and working point mass-to-charge identities differ")
    classification, chi = _classify_source(source, working_point)
    hit = classification == "detector_arrival"
    times = np.full(source.particle_id.size, np.nan, dtype=float)
    if np.any(hit):
        times[hit] = np.asarray(exact_total_normalized_time_from_state(
            working_point.state, working_point.reflectron, working_point.inner,
            source.source_x_mm[hit], chi[hit], working_point.focus_drift_mm,
        )) * expected_scale * 1.0e6
        if np.any(~np.isfinite(times[hit])) or np.any(times[hit] <= 0):
            raise ArithmeticError("exact axial oracle returned invalid pulse-relative TOF")
    summary = {
        "mother_particle_count": int(source.particle_id.size),
        "detector_arrival_count": int(np.count_nonzero(hit)),
        "axial_model_reachability_fraction": float(np.mean(hit)),
        "full_cohort_reachable": bool(np.all(hit)),
        "classification_counts": dict(sorted(Counter(classification.tolist()).items())),
        "time_basis": "elapsed_since_ideal_instantaneous_extraction_pulse_us",
        "scope": "one_dimensional_ideal_field_no_transverse_collection_claim",
        "nominal_mass_convention": "singly_charged_mass_Da_equals_mass_to_charge_Th",
        **_peak_summary(times[hit], source.mass_to_charge_th, settings),
    }
    return IdealPropagationResult(source.particle_id.copy(), classification, times, summary)
