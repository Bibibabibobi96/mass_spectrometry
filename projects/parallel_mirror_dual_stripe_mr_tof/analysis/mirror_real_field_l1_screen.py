"""Solver-neutral L1 screening on sampled finite-3-D mirror response fields.

The input is a regular project-frame ``x-z`` slice at one frozen ``y`` value.
Each row contains the electrode mask and the potential and three field
components for the standalone B--E responses at one common normalization.
This module never changes candidate voltages, creates operating PAs, or grants
SIMION/Candidate qualification.  Numerical and acceptance controls are
therefore explicit call inputs; the managed runner that will own this module
must obtain them from a frozen project contract.
"""

from __future__ import annotations

import csv
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import RegularGridInterpolator


GROUPS = ("mirror_B", "mirror_C", "mirror_D", "mirror_E")
ELEMENTARY_CHARGE_C = 1.602176634e-19
ATOMIC_MASS_KG = 1.66053906660e-27
# (q_e * e / (mass_Th * u)) * (1 V/mm) converted from m/s^2 to mm/us^2.
ACCELERATION_MM_US2_PER_V_MM = ELEMENTARY_CHARGE_C * 1.0e-6 / ATOMIC_MASS_KG
# sqrt(2*q_e*e*KE_eV/(mass_Th*u)) converted from m/s to mm/us.
SPEED_MM_US_PER_SQRT_EV_PER_TH = math.sqrt(2.0 * ELEMENTARY_CHARGE_C / ATOMIC_MASS_KG) * 1.0e-3


class RealFieldL1Error(ValueError):
    """Raised when a sampled field, candidate, or trajectory is invalid."""


_WORKER_BASIS: ResponseBasis | None = None
_WORKER_ARGUMENTS: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ResponseBasis:
    """Regular sampled B--E response basis at one project-frame y slice."""

    x_mm: np.ndarray
    z_mm: np.ndarray
    potential_v: np.ndarray
    field_v_per_mm: np.ndarray
    electrode_mask: np.ndarray
    normalization_v: float
    probe_y_mm: float

    def __post_init__(self) -> None:
        x = np.asarray(self.x_mm, dtype=float)
        z = np.asarray(self.z_mm, dtype=float)
        potential = np.asarray(self.potential_v, dtype=float)
        field = np.asarray(self.field_v_per_mm, dtype=float)
        mask = np.asarray(self.electrode_mask, dtype=bool)
        expected = (len(x), len(z), len(GROUPS))
        if (
            x.ndim != 1
            or z.ndim != 1
            or len(x) < 2
            or len(z) < 3
            or not np.all(np.isfinite(x))
            or not np.all(np.isfinite(z))
            or not np.all(np.diff(x) > 0.0)
            or not np.all(np.diff(z) > 0.0)
        ):
            raise RealFieldL1Error("response basis axes must be finite, ordered, and nontrivial")
        if potential.shape != expected or field.shape != (*expected, 3) or mask.shape != (len(x), len(z)):
            raise RealFieldL1Error("response basis arrays do not match the regular x-z grid")
        if not np.all(np.isfinite(potential)) or not np.all(np.isfinite(field)):
            raise RealFieldL1Error("response basis contains non-finite field values")
        if not math.isfinite(float(self.normalization_v)) or float(self.normalization_v) == 0.0:
            raise RealFieldL1Error("response normalization must be finite and nonzero")
        if not math.isfinite(float(self.probe_y_mm)):
            raise RealFieldL1Error("response probe y must be finite")


def load_response_basis_csv(
    path: Path,
    *,
    normalization_v: float,
    probe_y_mm: float,
) -> ResponseBasis:
    """Load the canonical regular-grid response CSV.

    Required columns are ``x_mm,z_mm,is_electrode`` followed by
    ``<group>_potential_v`` and ``<group>_e{x,y,z}_v_per_mm`` for every B--E
    group.  Every Cartesian grid point must occur exactly once.
    """

    required = {"x_mm", "z_mm", "is_electrode"}
    for group in GROUPS:
        required.add(f"{group}_potential_v")
        required.update(f"{group}_e{axis}_v_per_mm" for axis in "xyz")
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or set(reader.fieldnames) != required:
                raise RealFieldL1Error("response basis CSV columns differ from the canonical schema")
            raw_rows = list(reader)
    except OSError as exc:
        raise RealFieldL1Error(f"response basis CSV is unreadable: {path}") from exc
    if not raw_rows:
        raise RealFieldL1Error("response basis CSV is empty")

    def finite(text: str, label: str) -> float:
        try:
            value = float(text)
        except (TypeError, ValueError) as exc:
            raise RealFieldL1Error(f"{label} is not numeric") from exc
        if not math.isfinite(value):
            raise RealFieldL1Error(f"{label} is non-finite")
        return value

    parsed: dict[tuple[float, float], tuple[bool, list[list[float]]]] = {}
    for row in raw_rows:
        x = finite(row["x_mm"], "x_mm")
        z = finite(row["z_mm"], "z_mm")
        key = (x, z)
        if key in parsed:
            raise RealFieldL1Error(f"duplicate response grid point: {key}")
        mask_text = row["is_electrode"].strip().lower()
        if mask_text not in {"0", "1", "false", "true"}:
            raise RealFieldL1Error("is_electrode must be 0/1 or false/true")
        values = []
        for group in GROUPS:
            values.append([
                finite(row[f"{group}_potential_v"], f"{group} potential"),
                *(finite(row[f"{group}_e{axis}_v_per_mm"], f"{group} E{axis}") for axis in "xyz"),
            ])
        parsed[key] = (mask_text in {"1", "true"}, values)
    x_values = np.asarray(sorted({key[0] for key in parsed}), dtype=float)
    z_values = np.asarray(sorted({key[1] for key in parsed}), dtype=float)
    if len(parsed) != len(x_values) * len(z_values):
        raise RealFieldL1Error("response basis CSV does not contain a complete regular x-z grid")
    potential = np.empty((len(x_values), len(z_values), len(GROUPS)), dtype=float)
    field = np.empty((*potential.shape, 3), dtype=float)
    mask = np.empty((len(x_values), len(z_values)), dtype=bool)
    for ix, x in enumerate(x_values):
        for iz, z in enumerate(z_values):
            electrode, values = parsed[(float(x), float(z))]
            mask[ix, iz] = electrode
            array = np.asarray(values, dtype=float)
            potential[ix, iz, :] = array[:, 0]
            field[ix, iz, :, :] = array[:, 1:]
    return ResponseBasis(x_values, z_values, potential, field, mask, normalization_v, probe_y_mm)


@dataclass
class CombinedField:
    """One unchanged B--E voltage vector applied to a sampled response basis."""

    basis: ResponseBasis
    voltages_v: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        values = np.asarray(self.voltages_v, dtype=float)
        if values.shape != (4,) or not np.all(np.isfinite(values)):
            raise RealFieldL1Error("combined field requires four finite B--E voltages")
        coefficients = values / float(self.basis.normalization_v)
        self._potential = np.tensordot(self.basis.potential_v, coefficients, axes=(2, 0))
        self._field = np.tensordot(self.basis.field_v_per_mm, coefficients, axes=(2, 0))
        self._potential_interpolator = RegularGridInterpolator(
            (self.basis.x_mm, self.basis.z_mm), self._potential,
            bounds_error=True, method="linear",
        )
        self._field_interpolator = RegularGridInterpolator(
            (self.basis.x_mm, self.basis.z_mm), self._field,
            bounds_error=True, method="linear",
        )

    def _nearest_indices(self, x_mm: float, z_mm: float) -> tuple[int, int]:
        ix = int(np.argmin(np.abs(self.basis.x_mm - x_mm)))
        iz = int(np.argmin(np.abs(self.basis.z_mm - z_mm)))
        return ix, iz

    def sample(self, x_mm: float, z_mm: float, *, reject_electrode: bool) -> tuple[float, np.ndarray]:
        """Return potential and project-frame (Ex,Ey,Ez) at one point."""

        if not math.isfinite(x_mm) or not math.isfinite(z_mm):
            raise RealFieldL1Error("field sample coordinates must be finite")
        ix, iz = self._nearest_indices(x_mm, z_mm)
        if reject_electrode and bool(self.basis.electrode_mask[ix, iz]):
            raise RealFieldL1Error(
                "trajectory entered a sampled electrode cell: "
                f"query_x_mm={x_mm:.17g}, query_z_mm={z_mm:.17g}, "
                f"nearest_x_mm={float(self.basis.x_mm[ix]):.17g}, "
                f"nearest_z_mm={float(self.basis.z_mm[iz]):.17g}, "
                f"grid_index=({ix},{iz})"
            )
        try:
            point = np.asarray([[x_mm, z_mm]], dtype=float)
            potential = float(self._potential_interpolator(point)[0])
            field = np.asarray(self._field_interpolator(point)[0], dtype=float)
        except ValueError as exc:
            raise RealFieldL1Error("trajectory left the sampled response domain") from exc
        return potential, field

    def sampled_peak_field(self) -> dict[str, Any]:
        """Return the largest sampled 3-D field magnitude on non-electrode nodes."""

        magnitude = np.linalg.norm(self._field, axis=2)
        eligible = ~self.basis.electrode_mask
        if not bool(np.any(eligible)):
            raise RealFieldL1Error("sampled response basis has no non-electrode node")
        masked = np.where(eligible, magnitude, -np.inf)
        flat = int(np.argmax(masked))
        ix, iz = np.unravel_index(flat, masked.shape)
        return {
            "magnitude_v_per_mm": float(magnitude[ix, iz]),
            "field_v_per_mm": [float(value) for value in self._field[ix, iz]],
            "position_mm": [
                float(self.basis.x_mm[ix]), float(self.basis.probe_y_mm), float(self.basis.z_mm[iz]),
            ],
            "electrode_nodes_excluded": int(np.count_nonzero(self.basis.electrode_mask)),
            "sampled_non_electrode_nodes": int(np.count_nonzero(eligible)),
        }


@dataclass(frozen=True)
class TraceResult:
    first_return_time_us: float
    full_period_us: float
    first_return_x_mm: float
    first_return_alpha_rad: float
    full_return_x_mm: float
    full_return_alpha_rad: float


def trace_two_mirror_cycle(
    field: CombinedField,
    *,
    energy_per_charge_v: float,
    initial_x_mm: float,
    initial_alpha_rad: float,
    launch_direction: int,
    particle_mass_th: float,
    particle_charge_e: float,
    relative_tolerance: float,
    absolute_tolerance: float,
    maximum_step_us: float,
    maximum_leg_time_us: float,
    central_plane_offset_mm: float,
) -> TraceResult:
    """Trace a positive ion through one reflection and one full mirror cycle."""

    values = (
        energy_per_charge_v, initial_x_mm, initial_alpha_rad, particle_mass_th,
        particle_charge_e, relative_tolerance, absolute_tolerance,
        maximum_step_us, maximum_leg_time_us, central_plane_offset_mm,
    )
    if not all(math.isfinite(float(value)) for value in values):
        raise RealFieldL1Error("trajectory inputs must be finite")
    if launch_direction not in {-1, 1}:
        raise RealFieldL1Error("launch direction must be -1 or +1")
    if (
        particle_mass_th <= 0.0 or particle_charge_e <= 0.0
        or relative_tolerance <= 0.0 or absolute_tolerance <= 0.0
        or maximum_step_us <= 0.0 or maximum_leg_time_us <= 0.0
        or central_plane_offset_mm <= 0.0
    ):
        raise RealFieldL1Error("positive ion and positive trajectory controls are required")
    reference_potential = field.sample(0.0, 0.0, reject_electrode=True)[0]
    initial_potential = field.sample(initial_x_mm, 0.0, reject_electrode=True)[0]
    kinetic_ev = particle_charge_e * (energy_per_charge_v - (initial_potential - reference_potential))
    if kinetic_ev <= 0.0:
        raise RealFieldL1Error("probe has non-positive initial kinetic energy")
    speed = SPEED_MM_US_PER_SQRT_EV_PER_TH * math.sqrt(kinetic_ev / particle_mass_th)
    vz_abs = speed / math.sqrt(1.0 + initial_alpha_rad * initial_alpha_rad)
    vx = initial_alpha_rad * vz_abs
    acceleration_scale = ACCELERATION_MM_US2_PER_V_MM * particle_charge_e / particle_mass_th

    def rhs(_time: float, state: np.ndarray) -> list[float]:
        x, z, local_vx, local_vz = (float(value) for value in state)
        _potential, electric = field.sample(x, z, reject_electrode=True)
        return [local_vx, local_vz, acceleration_scale * electric[0], acceleration_scale * electric[2]]

    def propagate(state: np.ndarray, event_direction: int) -> tuple[float, np.ndarray]:
        def central_crossing(_time: float, current: np.ndarray) -> float:
            return float(current[1])

        central_crossing.direction = event_direction  # type: ignore[attr-defined]
        central_crossing.terminal = True  # type: ignore[attr-defined]
        try:
            solution = solve_ivp(
                rhs, (0.0, maximum_leg_time_us), state, events=central_crossing,
                rtol=relative_tolerance, atol=absolute_tolerance, max_step=maximum_step_us,
            )
        except RealFieldL1Error:
            raise
        if not solution.success or not solution.t_events[0].size:
            raise RealFieldL1Error("trajectory did not return to the central Poincare section")
        return float(solution.t_events[0][0]), np.asarray(solution.y_events[0][0], dtype=float)

    initial = np.asarray([
        initial_x_mm, launch_direction * central_plane_offset_mm,
        vx, launch_direction * vz_abs,
    ], dtype=float)
    first_time, first = propagate(initial, -launch_direction)
    first[1] = -launch_direction * central_plane_offset_mm
    second_time, second = propagate(first, launch_direction)
    first_denominator = -launch_direction * float(first[3])
    second_denominator = launch_direction * float(second[3])
    if first_denominator <= 0.0 or second_denominator <= 0.0:
        raise RealFieldL1Error("central return has the wrong longitudinal direction")
    return TraceResult(
        first_return_time_us=first_time,
        full_period_us=first_time + second_time,
        first_return_x_mm=float(first[0]),
        first_return_alpha_rad=float(first[2]) / first_denominator,
        full_return_x_mm=float(second[0]),
        full_return_alpha_rad=float(second[2]) / second_denominator,
    )


def l1_probe_at_energy(
    field: CombinedField,
    *,
    energy_per_charge_v: float,
    launch_direction: int,
    position_probe_mm: float,
    angle_probe_rad: float,
    trace_controls: Mapping[str, float],
) -> dict[str, Any]:
    """Evaluate one-direction map and full-cycle transverse time coefficient."""

    if position_probe_mm <= 0.0 or angle_probe_rad <= 0.0:
        raise RealFieldL1Error("L1 probes must be positive")

    def trace(label: str, x_mm: float, alpha_rad: float) -> TraceResult:
        try:
            return trace_two_mirror_cycle(
                field, energy_per_charge_v=energy_per_charge_v,
                initial_x_mm=x_mm, initial_alpha_rad=alpha_rad,
                launch_direction=launch_direction,
                particle_mass_th=float(trace_controls["particle_mass_th"]),
                particle_charge_e=float(trace_controls["particle_charge_e"]),
                relative_tolerance=float(trace_controls["relative_tolerance"]),
                absolute_tolerance=float(trace_controls["absolute_tolerance"]),
                maximum_step_us=float(trace_controls["maximum_step_us"]),
                maximum_leg_time_us=float(trace_controls["maximum_leg_time_us"]),
                central_plane_offset_mm=float(trace_controls["central_plane_offset_mm"]),
            )
        except RealFieldL1Error as exc:
            raise RealFieldL1Error(
                "L1 trajectory failed: "
                f"probe={label}, energy_per_charge_v={energy_per_charge_v:.17g}, "
                f"launch_direction_z={launch_direction}; {exc}"
            ) from exc

    center = trace("center", 0.0, 0.0)
    xp = trace("position_positive", position_probe_mm, 0.0)
    xm = trace("position_negative", -position_probe_mm, 0.0)
    ap = trace("angle_positive", 0.0, angle_probe_rad)
    am = trace("angle_negative", 0.0, -angle_probe_rad)
    matrix = np.asarray([
        [
            (xp.first_return_x_mm - xm.first_return_x_mm) / (2.0 * position_probe_mm),
            (ap.first_return_x_mm - am.first_return_x_mm) / (2.0 * angle_probe_rad),
        ],
        [
            (xp.first_return_alpha_rad - xm.first_return_alpha_rad) / (2.0 * position_probe_mm),
            (ap.first_return_alpha_rad - am.first_return_alpha_rad) / (2.0 * angle_probe_rad),
        ],
    ])
    determinant = float(np.linalg.det(matrix))
    trace_half = float(np.trace(matrix) / 2.0)
    stable = abs(trace_half) < 1.0
    gamma = math.degrees(math.acos(max(-1.0, min(1.0, trace_half)))) if stable else None
    t_xx = (xp.full_period_us + xm.full_period_us - 2.0 * center.full_period_us) / (
        2.0 * position_probe_mm * position_probe_mm
    )
    t_aa = (ap.full_period_us + am.full_period_us - 2.0 * center.full_period_us) / (
        2.0 * angle_probe_rad * angle_probe_rad
    )
    f_mm = None
    tbar = None
    if stable and gamma is not None:
        sine = math.sin(math.radians(gamma))
        if abs(sine) > 1e-14:
            candidate_f = float(matrix[0, 1] / sine)
            if math.isfinite(candidate_f) and abs(candidate_f) > 1e-14:
                f_mm = candidate_f
                tbar = 0.5 * (t_xx + t_aa / (candidate_f * candidate_f))
    return {
        "energy_per_charge_v": float(energy_per_charge_v),
        "launch_direction_z": launch_direction,
        "position_probe_mm": float(position_probe_mm),
        "angle_probe_rad": float(angle_probe_rad),
        "matrix": matrix.tolist(),
        "determinant": determinant,
        "reversibility_difference": float(matrix[0, 0] - matrix[1, 1]),
        "trace_half": trace_half,
        "stable": stable,
        "stability_margin": 1.0 - abs(trace_half),
        "gamma_degrees": gamma,
        "full_two_mirror_period_us": center.full_period_us,
        "T_xx_us_per_mm2": t_xx,
        "T_alphaalpha_us_per_rad2": t_aa,
        "f_mm": f_mm,
        "Tbar_xx_us_per_mm2": tbar,
    }


def _relative_change(left: float, right: float, absolute_floor: float) -> float:
    denominator = max(abs(left), abs(right), absolute_floor)
    return abs(left - right) / denominator


def evaluate_member(
    basis: ResponseBasis,
    mirror_voltages_v: Sequence[float],
    *,
    energy_points_v: Sequence[float],
    period_slope_derivative_step_v: float,
    probe_scale_factors: Sequence[float],
    position_probe_mm: float,
    angle_probe_rad: float,
    trace_controls: Mapping[str, float],
    target_gamma_degrees: float,
    maximum_gamma_target_residual_degrees: float,
    maximum_adjacent_gamma_change_degrees: float,
    maximum_adjacent_relative_tbar_change: float,
    tbar_relative_change_absolute_floor_us_per_mm2: float,
    minimum_stability_margin: float,
    maximum_abs_normalized_period_slope_per_v: float,
    gamma_target_is_acceptance_gate: bool = True,
) -> dict[str, Any]:
    """Evaluate one unchanged five-voltage family member at all required gates."""

    voltages = tuple(float(value) for value in mirror_voltages_v)
    energies = tuple(float(value) for value in energy_points_v)
    scales = tuple(float(value) for value in probe_scale_factors)
    controls = (
        period_slope_derivative_step_v, position_probe_mm, angle_probe_rad, target_gamma_degrees,
        maximum_gamma_target_residual_degrees, maximum_adjacent_gamma_change_degrees,
        maximum_adjacent_relative_tbar_change, tbar_relative_change_absolute_floor_us_per_mm2,
        minimum_stability_margin, maximum_abs_normalized_period_slope_per_v,
    )
    if (
        len(voltages) != 5 or voltages[0] != 0.0 or not all(math.isfinite(value) for value in voltages)
        or len(energies) != 3 or tuple(sorted(energies)) != energies
        or len(scales) < 2 or any(not math.isfinite(value) or value <= 0.0 for value in scales)
        or tuple(sorted(scales)) != scales
        or any(not math.isfinite(float(value)) or float(value) < 0.0 for value in controls)
        or period_slope_derivative_step_v <= 0.0 or position_probe_mm <= 0.0 or angle_probe_rad <= 0.0
        or maximum_gamma_target_residual_degrees <= 0.0
        or maximum_adjacent_gamma_change_degrees <= 0.0
        or maximum_adjacent_relative_tbar_change <= 0.0
        or tbar_relative_change_absolute_floor_us_per_mm2 <= 0.0
        or maximum_abs_normalized_period_slope_per_v <= 0.0
        or not 0.0 < target_gamma_degrees < 180.0
    ):
        raise RealFieldL1Error("member voltages, energies, probes, or gates are invalid")
    field = CombinedField(basis, voltages[1:])
    preflight_records = []
    preflight_failures = []
    for direction in (-1, 1):
        record = l1_probe_at_energy(
            field,
            energy_per_charge_v=energies[1],
            launch_direction=direction,
            position_probe_mm=position_probe_mm * scales[-1],
            angle_probe_rad=angle_probe_rad * scales[-1],
            trace_controls=trace_controls,
        )
        preflight_records.append(record)
        if not record["stable"] or record["gamma_degrees"] is None:
            preflight_failures.append(f"nominal_preflight_unstable:direction={direction}")
            continue
        if float(record["stability_margin"]) < minimum_stability_margin:
            preflight_failures.append(
                f"nominal_preflight_stability_margin_failed:direction={direction}"
            )
        gamma_residual = abs(float(record["gamma_degrees"]) - target_gamma_degrees)
        # A member farther away than the target gate plus the maximum allowed
        # adjacent-scale change cannot become acceptable at the next-finer
        # scale without also failing the frozen convergence gate.  Reject it
        # before spending three-energy/three-scale trajectory work.
        if gamma_target_is_acceptance_gate and gamma_residual > (
            maximum_gamma_target_residual_degrees + maximum_adjacent_gamma_change_degrees
        ):
            preflight_failures.append(f"nominal_preflight_gamma_envelope_failed:direction={direction}")
    if preflight_failures:
        peak = field.sampled_peak_field()
        finite_tbars = [
            abs(float(record["Tbar_xx_us_per_mm2"]))
            for record in preflight_records if record["Tbar_xx_us_per_mm2"] is not None
        ]
        finite_margins = [
            float(record["stability_margin"])
            for record in preflight_records if record["stable"]
        ]
        finite_gamma = [
            abs(float(record["gamma_degrees"]) - target_gamma_degrees)
            for record in preflight_records if record["gamma_degrees"] is not None
        ]
        return {
            "status": "screen_fail_diagnostic_only",
            "screen_stage": "nominal_energy_largest_probe_preflight",
            "qualification": "solver_neutral_sampled_0p5mm_field_diagnostic__native_simion_validation_required",
            "mirror_voltages_v": list(voltages),
            "energy_points_v": list(energies),
            "probe_scale_factors": list(scales),
            "gamma_target_is_acceptance_gate": gamma_target_is_acceptance_gate,
            "preflight": preflight_records,
            "directions": {},
            "full_two_mirror_period_us": [],
            "normalized_period_slopes_per_v": [],
            "sampled_peak_field": peak,
            "selection_metrics": {
                "maximum_absolute_Tbar_xx_us_per_mm2": max(finite_tbars) if finite_tbars else None,
                "minimum_transverse_stability_margin": min(finite_margins) if finite_margins else None,
                "sampled_peak_field_v_per_mm": peak["magnitude_v_per_mm"],
                "maximum_absolute_mirror_voltage_v": max(abs(value) for value in voltages[1:]),
                "maximum_gamma_target_residual_degrees": max(finite_gamma) if finite_gamma else None,
            },
            "hard_gate_failures": sorted(set(preflight_failures)),
        }
    screens: dict[str, Any] = {}
    hard_failures: list[str] = []
    minimum_margin = math.inf
    maximum_abs_tbar = 0.0
    maximum_gamma_residual = 0.0
    preflight_by_direction = {
        int(record["launch_direction_z"]): record for record in preflight_records
    }
    for direction in (-1, 1):
        direction_records: dict[str, Any] = {}
        for energy in energies:
            active_scales = scales[:-1] if energy == energies[1] else ()
            scale_records = [
                l1_probe_at_energy(
                    field, energy_per_charge_v=energy, launch_direction=direction,
                    position_probe_mm=position_probe_mm * scale,
                    angle_probe_rad=angle_probe_rad * scale,
                    trace_controls=trace_controls,
                )
                for scale in active_scales
            ]
            if energy == energies[1]:
                scale_records.append(preflight_by_direction[direction])
            else:
                scale_records.append(l1_probe_at_energy(
                    field, energy_per_charge_v=energy, launch_direction=direction,
                    position_probe_mm=position_probe_mm * scales[-1],
                    angle_probe_rad=angle_probe_rad * scales[-1],
                    trace_controls=trace_controls,
                ))
            for record in scale_records:
                if not record["stable"] or record["Tbar_xx_us_per_mm2"] is None:
                    hard_failures.append(f"unstable_or_undefined:direction={direction}:energy={energy}")
            last = scale_records[-1]
            if last["stable"]:
                minimum_margin = min(minimum_margin, float(last["stability_margin"]))
            gamma_change = None
            relative_tbar_change = None
            previous = scale_records[-2] if len(scale_records) >= 2 else None
            if energy == energies[1] and previous is not None and (
                last["gamma_degrees"] is not None and previous["gamma_degrees"] is not None
                and last["Tbar_xx_us_per_mm2"] is not None and previous["Tbar_xx_us_per_mm2"] is not None
            ):
                gamma_change = abs(float(last["gamma_degrees"]) - float(previous["gamma_degrees"]))
                relative_tbar_change = _relative_change(
                    float(last["Tbar_xx_us_per_mm2"]), float(previous["Tbar_xx_us_per_mm2"]),
                    tbar_relative_change_absolute_floor_us_per_mm2,
                )
            gamma_residual = math.inf if last["gamma_degrees"] is None else abs(
                float(last["gamma_degrees"]) - target_gamma_degrees
            )
            # The existing L1 contract uses all three energy nodes for
            # stability, while gamma=90 and the probe-convergence selector are
            # nominal-energy conditions.  Preserve that scope here rather
            # than silently imposing two extra gamma roots.
            if energy == energies[1]:
                if gamma_change is None or gamma_change > maximum_adjacent_gamma_change_degrees:
                    hard_failures.append(f"gamma_probe_not_converged:direction={direction}:energy={energy}")
                if (
                    relative_tbar_change is None
                    or relative_tbar_change > maximum_adjacent_relative_tbar_change
                ):
                    hard_failures.append(f"tbar_probe_not_converged:direction={direction}:energy={energy}")
                maximum_gamma_residual = max(maximum_gamma_residual, gamma_residual)
                if gamma_target_is_acceptance_gate and gamma_residual > maximum_gamma_target_residual_degrees:
                    hard_failures.append(f"gamma_target_failed:direction={direction}:energy={energy}")
                if last["Tbar_xx_us_per_mm2"] is not None:
                    maximum_abs_tbar = max(
                        maximum_abs_tbar, abs(float(last["Tbar_xx_us_per_mm2"])),
                    )
            direction_records[f"{energy:.17g}"] = {
                "scales": scale_records,
                "last_adjacent_gamma_change_degrees": gamma_change,
                "last_adjacent_relative_Tbar_change": relative_tbar_change,
            }
        screens[str(direction)] = direction_records
    if minimum_margin < minimum_stability_margin:
        hard_failures.append("minimum_stability_margin_failed")

    def center_period(energy: float) -> float:
        return trace_two_mirror_cycle(
            field, energy_per_charge_v=energy, initial_x_mm=0.0, initial_alpha_rad=0.0,
            launch_direction=1, particle_mass_th=float(trace_controls["particle_mass_th"]),
            particle_charge_e=float(trace_controls["particle_charge_e"]),
            relative_tolerance=float(trace_controls["relative_tolerance"]),
            absolute_tolerance=float(trace_controls["absolute_tolerance"]),
            maximum_step_us=float(trace_controls["maximum_step_us"]),
            maximum_leg_time_us=float(trace_controls["maximum_leg_time_us"]),
            central_plane_offset_mm=float(trace_controls["central_plane_offset_mm"]),
        ).full_period_us

    slopes = []
    periods = []
    for energy in energies:
        low = center_period(energy - period_slope_derivative_step_v)
        center = center_period(energy)
        high = center_period(energy + period_slope_derivative_step_v)
        slopes.append((high - low) / (2.0 * period_slope_derivative_step_v * center))
        periods.append(center)
    if max(abs(value) for value in slopes) > maximum_abs_normalized_period_slope_per_v:
        hard_failures.append("l0_period_slope_failed")
    peak = field.sampled_peak_field()
    return {
        "status": "screen_pass_diagnostic_only" if not hard_failures else "screen_fail_diagnostic_only",
        "qualification": "solver_neutral_sampled_0p5mm_field_diagnostic__native_simion_validation_required",
        "mirror_voltages_v": list(voltages),
        "energy_points_v": list(energies),
        "probe_scale_factors": list(scales),
        "gamma_target_is_acceptance_gate": gamma_target_is_acceptance_gate,
        "directions": screens,
        "full_two_mirror_period_us": periods,
        "normalized_period_slopes_per_v": slopes,
        "sampled_peak_field": peak,
        "selection_metrics": {
            "maximum_absolute_Tbar_xx_us_per_mm2": maximum_abs_tbar,
            "minimum_transverse_stability_margin": minimum_margin,
            "sampled_peak_field_v_per_mm": peak["magnitude_v_per_mm"],
            "maximum_absolute_mirror_voltage_v": max(abs(value) for value in voltages[1:]),
            "maximum_gamma_target_residual_degrees": maximum_gamma_residual,
        },
        "hard_gate_failures": sorted(set(hard_failures)),
    }


def rank_screened_members(
    reports: Sequence[Mapping[str, Any]],
    *,
    metric_tolerances: Sequence[float],
) -> dict[str, Any]:
    """Apply the contract selection order and retain declared numerical ties."""

    tolerances = tuple(float(value) for value in metric_tolerances)
    if len(tolerances) != 4 or any(not math.isfinite(value) or value < 0.0 for value in tolerances):
        raise RealFieldL1Error("ranking needs four finite nonnegative metric tolerances")
    survivors = [index for index, report in enumerate(reports) if report.get("status") == "screen_pass_diagnostic_only"]
    order = (
        ("maximum_absolute_Tbar_xx_us_per_mm2", False),
        ("minimum_transverse_stability_margin", True),
        ("sampled_peak_field_v_per_mm", False),
        ("maximum_absolute_mirror_voltage_v", False),
    )
    stages = []
    for (name, maximize), tolerance in zip(order, tolerances, strict=True):
        if not survivors:
            break
        values = {index: float(reports[index]["selection_metrics"][name]) for index in survivors}
        if any(not math.isfinite(value) for value in values.values()):
            raise RealFieldL1Error(f"ranking metric is non-finite: {name}")
        best = (max if maximize else min)(values.values())
        survivors = [
            index for index in survivors
            if (best - values[index] <= tolerance if maximize else values[index] - best <= tolerance)
        ]
        stages.append({"metric": name, "maximize": maximize, "best": best, "tolerance": tolerance,
                       "retained_member_indices": survivors.copy()})
    return {
        "status": "selected_for_native_validation_diagnostic_only" if survivors else "no_member_passed_screen",
        "qualification": "ranking_only__not_a_native_simion_or_candidate_qualification",
        "selection_order": [name for name, _maximize in order],
        "stages": stages,
        "selected_member_indices": survivors,
        "primary_member_index": min(survivors) if survivors else None,
        "tie_retained": len(survivors) > 1,
    }


def _initialize_member_worker(
    basis: ResponseBasis, evaluation_arguments: Mapping[str, Any],
) -> None:
    global _WORKER_BASIS, _WORKER_ARGUMENTS
    _WORKER_BASIS = basis
    _WORKER_ARGUMENTS = evaluation_arguments


def _safe_evaluate_member(
    basis: ResponseBasis, voltages: Sequence[float], evaluation_arguments: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        return evaluate_member(basis, voltages, **evaluation_arguments)
    except RealFieldL1Error as exc:
        return {
            "status": "screen_fail_diagnostic_only",
            "screen_stage": "trajectory_exception",
            "qualification": "solver_neutral_sampled_0p5mm_field_diagnostic__native_simion_validation_required",
            "mirror_voltages_v": [float(value) for value in voltages],
            "hard_gate_failures": ["trajectory_or_field_domain_failed"],
            "failure_reason": str(exc),
        }


def _evaluate_member_worker(job: tuple[int, Sequence[float]]) -> tuple[int, dict[str, Any]]:
    source_index, voltages = job
    if _WORKER_BASIS is None or _WORKER_ARGUMENTS is None:
        raise RealFieldL1Error("L1 member worker was not initialized")
    return source_index, _safe_evaluate_member(_WORKER_BASIS, voltages, _WORKER_ARGUMENTS)


def screen_feasible_family(
    family: Mapping[str, Any],
    basis: ResponseBasis,
    *,
    evaluation_arguments: Mapping[str, Any],
    ranking_metric_tolerances: Sequence[float],
    maximum_parallel_workers: int = 1,
) -> dict[str, Any]:
    """Screen exactly the feasible members of one real-3-D L0 family receipt."""

    members = family.get("members")
    if (
        family.get("role") != "mrtof_real_3d_mirror_l0_voltage_family"
        or not isinstance(members, list)
        or int(family.get("feasible_member_count", -1))
        != sum(isinstance(item, Mapping) and item.get("l0_feasible") is True for item in members)
    ):
        raise RealFieldL1Error("L0 family identity or feasible-member count is invalid")
    source_indices = [index for index, item in enumerate(members) if item.get("l0_feasible") is True]
    if maximum_parallel_workers < 1:
        raise RealFieldL1Error("maximum parallel workers must be positive")
    jobs: list[tuple[int, Sequence[float]]] = []
    for source_index in source_indices:
        member = members[source_index]
        voltages = member.get("mirror_voltages_v")
        if not isinstance(voltages, list):
            raise RealFieldL1Error("feasible family member lacks its voltage vector")
        jobs.append((source_index, voltages))
    worker_count = min(len(jobs), maximum_parallel_workers, os.cpu_count() or 1)
    if worker_count > 1:
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_initialize_member_worker,
            initargs=(basis, evaluation_arguments),
        ) as executor:
            evaluated = list(executor.map(_evaluate_member_worker, jobs))
    else:
        evaluated = [
            (source_index, _safe_evaluate_member(basis, voltages, evaluation_arguments))
            for source_index, voltages in jobs
        ]
    reports = []
    for (source_index, voltages), (returned_index, report) in zip(
        jobs, evaluated, strict=True,
    ):
        if returned_index != source_index:
            raise RealFieldL1Error("parallel L1 member ordering changed")
        if report["mirror_voltages_v"] != [float(value) for value in voltages]:
            raise RealFieldL1Error("screening changed a family member voltage")
        report["source_member_index"] = source_index
        reports.append(report)
    ranking = rank_screened_members(reports, metric_tolerances=ranking_metric_tolerances)
    ranking["selected_source_member_indices"] = [
        reports[index]["source_member_index"] for index in ranking["selected_member_indices"]
    ]
    return {
        "schema_version": 1,
        "role": "mrtof_real_3d_mirror_l1_screen",
        "status": "diagnostic_complete__native_validation_pending",
        "qualification": "solver_neutral_sampled_field_screen__not_candidate_qualification",
        "source_family_member_count": len(members),
        "source_feasible_member_count": len(source_indices),
        "actual_parallel_workers": worker_count,
        "screened_source_member_indices": source_indices,
        "members": reports,
        "ranking": ranking,
    }
