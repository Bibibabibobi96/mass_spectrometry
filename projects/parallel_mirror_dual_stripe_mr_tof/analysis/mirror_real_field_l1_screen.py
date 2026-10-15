"""Solver-neutral L1 probes on sampled finite-3-D mirror response fields.

The input is a regular project-frame ``x-z`` slice at one frozen ``y`` value.
Each row contains the electrode mask and the potential and three field
components for the standalone B--E responses at one common normalization.
This module never changes candidate voltages, creates operating PAs, or grants
SIMION/Candidate qualification.  Numerical and acceptance controls are
therefore explicit call inputs obtained by consumers from a frozen project contract.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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
