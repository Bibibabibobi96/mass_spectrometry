"""Reduced-order pressure-drag transport through the dual-cone interface.

The model is intentionally a screening model. It consumes a frozen resolved
geometry and explicit provisional gas/electrical assumptions; it does not
solve compressible flow, finite-electrode electrostatics, or discrete collision
cross sections, or diffusion.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.particle_count_policy import validate_positive_particle_count
from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
    mass_to_charge_th,
)
from common.multipole.family_contract import VoltageDrive
from common.multipole.ideal_transport import electric_field_xy_array, rf_waveform_voltage_array
from common.multipole.round_rod_geometry import points_inside_rods


PROJECT_ID = "dual_cone_tandem_quadrupole_ion_interface"
FRAME_ID = "dual_cone_interface_local"
CLOCK_EPOCH_ID = "screening_run_epoch"


@dataclass(frozen=True)
class SimulationResult:
    """Complete in-memory state needed to publish a compact screening run."""

    source_positions_m: np.ndarray
    source_velocities_m_s: np.ndarray
    birth_times_s: np.ndarray
    final_positions_m: np.ndarray
    final_velocities_m_s: np.ndarray
    elapsed_times_s: np.ndarray
    drag_exposure_integrals: np.ndarray
    statuses: np.ndarray
    terminal_reasons: np.ndarray
    traces_mm: dict[int, list[tuple[float, float, float]]]


def load_json(path: Path, role: str) -> dict[str, Any]:
    """Load a version-1 project contract and require its role and identity."""
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document.get("schema_version") != 1 or document.get("role") != role:
        raise ValueError(f"{path}: schema or role differs from {role}")
    if document.get("project_id") != PROJECT_ID:
        raise ValueError(f"{path}: project identity differs")
    return document


def validate_contracts(
    resolved: dict[str, Any], science: dict[str, Any], numerics: dict[str, Any]
) -> None:
    """Fail closed on unsupported physics, coordinates, and numerical values."""
    if resolved.get("role") != "dual_cone_tandem_quadrupole_resolved_geometry":
        raise ValueError("resolved geometry role differs")
    if resolved.get("project_id") != PROJECT_ID:
        raise ValueError("resolved geometry project identity differs")
    if resolved["coordinate_frame"].get("frame_id") != FRAME_ID:
        raise ValueError("resolved geometry frame differs")
    if science.get("model_id") != "pressure_drag_screening_v1":
        raise ValueError("unsupported science model")
    if numerics.get("integrator") != "semi_implicit_euler_with_implicit_drag":
        raise ValueError("unsupported integrator")
    for label, value in (
        ("time step", numerics["time_step_s"]),
        ("maximum elapsed time", numerics["maximum_elapsed_time_s"]),
        ("gas temperature", science["gas"]["temperature_k"]),
        ("ion mass", science["ion"]["mass_amu"]),
        ("reduced mobility", science["ion"]["reduced_mobility_m2_v_s"]),
    ):
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"{label} must be finite and positive")
    if int(science["ion"]["charge_state"]) == 0:
        raise ValueError("ion charge state must be nonzero")
    if science["gas"].get("pressure_interpolation") != "piecewise_log_linear_in_z":
        raise ValueError("unsupported pressure interpolation")
    if science["gas"].get("intercone_pressure_rule") != "geometric_mean_of_endpoint_pressures":
        raise ValueError("unsupported intercone pressure rule")


def make_drive(document: dict[str, Any]) -> VoltageDrive:
    """Adapt one project RF stage to the shared two-group RF voltage contract."""
    return VoltageDrive(
        waveform=str(document["waveform"]),
        rf_amplitude_v_per_group=float(document["rf_amplitude_v_zero_to_peak_per_group"]),
        dc_amplitude_v_per_group=float(document["dc_amplitude_v_per_group"]),
        common_mode_offset_v=float(document["common_mode_offset_v"]),
        frequency_hz=float(document["frequency_hz"]),
        phase_rad=float(document["phase_rad"]),
    )


def pressure_pa(z_m: np.ndarray, resolved: dict[str, Any], science: dict[str, Any]) -> np.ndarray:
    """Return the declared piecewise log-linear screening pressure profile."""
    geometry = resolved["geometry_mm"]
    first_z = float(geometry["first_cone"]["aperture_reference_z_mm"]) * 1e-3
    second_z = float(geometry["second_cone"]["aperture_reference_z_mm"]) * 1e-3
    end_z = float(geometry["low_pressure_enclosure"]["end_z_mm"]) * 1e-3
    upstream = float(science["gas"]["upstream_pressure_pa"])
    downstream = float(science["gas"]["downstream_pressure_pa"])
    middle = math.sqrt(upstream * downstream)
    values = np.full_like(z_m, upstream, dtype=float)
    intercone = (z_m > first_z) & (z_m < second_z)
    fraction = np.clip((z_m[intercone] - first_z) / (second_z - first_z), 0.0, 1.0)
    values[intercone] = np.exp(math.log(upstream) + fraction * math.log(middle / upstream))
    downstream_region = z_m >= second_z
    fraction = np.clip((z_m[downstream_region] - second_z) / (end_z - second_z), 0.0, 1.0)
    values[downstream_region] = np.exp(math.log(middle) + fraction * math.log(downstream / middle))
    return values


def gas_axial_velocity_m_s(
    z_m: np.ndarray, resolved: dict[str, Any], science: dict[str, Any]
) -> np.ndarray:
    """Interpolate the explicit provisional gas-velocity anchors."""
    geometry = resolved["geometry_mm"]
    source_z = float(science["source"]["plane_z_mm"]) * 1e-3
    second_z = float(geometry["second_cone"]["aperture_reference_z_mm"]) * 1e-3
    end_z = float(geometry["low_pressure_enclosure"]["end_z_mm"]) * 1e-3
    anchors = science["gas"]["axial_bulk_velocity_anchors_m_s"]
    return np.interp(
        z_m,
        np.array([source_z, second_z, end_z]),
        np.array([anchors["upstream"], anchors["second_aperture"], anchors["downstream"]]),
    )


def mobility_m2_v_s(pressure: np.ndarray, science: dict[str, Any]) -> np.ndarray:
    """Scale positive reduced mobility with inverse number density."""
    gas = science["gas"]
    ion = science["ion"]
    return (
        float(ion["reduced_mobility_m2_v_s"])
        * float(gas["reference_pressure_pa"])
        / pressure
        * float(gas["temperature_k"])
        / float(gas["reference_temperature_k"])
    )


def _splitmix64(values: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        values = values + np.uint64(0x9E3779B97F4A7C15)
        values = (values ^ (values >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        values = (values ^ (values >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return values ^ (values >> np.uint64(31))


def counter_uniform(seed: int, particle_ids: np.ndarray, step: int, stream: int) -> np.ndarray:
    """Return stateless U(0,1) values keyed by seed, particle, step, and stream."""
    with np.errstate(over="ignore"):
        counter = (
            np.uint64(seed)
            ^ particle_ids.astype(np.uint64) * np.uint64(0xD2B74407B1CE6E93)
            ^ np.uint64(step) * np.uint64(0xCA5A826395121157)
            ^ np.uint64(stream) * np.uint64(0x9E3779B97F4A7C15)
        )
    bits = _splitmix64(counter) >> np.uint64(11)
    return (bits.astype(np.float64) + 0.5) * (1.0 / 9007199254740992.0)


def source_particles(
    particle_count: int, seed: int, resolved: dict[str, Any], science: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate a deterministic-prefix source disk and local gas velocity."""
    validate_positive_particle_count(particle_count)
    particle_ids = np.arange(1, particle_count + 1, dtype=np.uint64)
    source = science["source"]
    radius = float(source["uniform_disk_radius_mm"]) * 1e-3 * np.sqrt(
        counter_uniform(seed, particle_ids, 0, 11)
    )
    azimuth = 2.0 * math.pi * counter_uniform(seed, particle_ids, 0, 12)
    positions = np.zeros((particle_count, 3), dtype=float)
    positions[:, 0] = radius * np.cos(azimuth)
    positions[:, 1] = radius * np.sin(azimuth)
    positions[:, 2] = float(source["plane_z_mm"]) * 1e-3
    drive = make_drive(science["electric_field"]["stage_1"])
    birth_times = counter_uniform(seed, particle_ids, 0, 13) / drive.frequency_hz
    velocities = np.zeros((particle_count, 3), dtype=float)
    velocities[:, 2] += gas_axial_velocity_m_s(positions[:, 2], resolved, science)
    return positions, velocities, birth_times


def _stage_masks(position_m: np.ndarray, resolved: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    geometry = resolved["geometry_mm"]
    stage_1 = geometry["stage_1_elliptical_quadrupole"]
    stage_2 = geometry["stage_2_round_quadrupole"]
    radius_mm = np.hypot(position_m[:, 0], position_m[:, 1]) * 1e3
    second_z = float(geometry["second_cone"]["aperture_reference_z_mm"])
    half_angle = math.radians(float(geometry["second_cone"]["half_angle_deg"]))
    offset = float(stage_1["upstream_end_surface"]["axial_offset_mm"])
    stage_1_start = second_z + offset + radius_mm / math.tan(half_angle)
    z_mm = position_m[:, 2] * 1e3
    mask_1 = (z_mm >= stage_1_start) & (z_mm <= float(stage_1["downstream_flat_end_z_mm"]))
    mask_2 = (z_mm >= float(stage_2["upstream_flat_start_z_mm"])) & (
        z_mm <= float(stage_2["downstream_flat_end_z_mm"])
    )
    return mask_1, mask_2


def electric_field_v_m(
    position_m: np.ndarray,
    absolute_times_s: np.ndarray,
    resolved: dict[str, Any],
    science: dict[str, Any],
) -> np.ndarray:
    """Evaluate uniform axial DC plus ideal time-resolved fields in each rod section."""
    field = np.zeros_like(position_m)
    field[:, 2] = float(science["electric_field"]["axial_dc_field_v_m"])
    masks = _stage_masks(position_m, resolved)
    stages = (
        resolved["geometry_mm"]["stage_1_elliptical_quadrupole"],
        resolved["geometry_mm"]["stage_2_round_quadrupole"],
    )
    for mask, stage_name, stage_geometry in zip(masks, ("stage_1", "stage_2"), stages, strict=True):
        if not np.any(mask):
            continue
        drive = make_drive(science["electric_field"][stage_name])
        voltage = drive.dc_amplitude_v_per_group + rf_waveform_voltage_array(
            drive, absolute_times_s[mask]
        )
        field_x, field_y = electric_field_xy_array(
            2,
            float(stage_geometry["ideal_field_radius_r0_mm"]) * 1e-3,
            voltage,
            position_m[mask, 0],
            position_m[mask, 1],
        )
        field[mask, 0] = field_x
        field[mask, 1] = field_y
    return field


def _inside_stage_1_rods(position_m: np.ndarray, resolved: dict[str, Any]) -> np.ndarray:
    stage = resolved["geometry_mm"]["stage_1_elliptical_quadrupole"]
    active, _ = _stage_masks(position_m, resolved)
    return active & points_inside_rods(position_m[:, :2] * 1e3, stage["rod_array"])


def _inside_stage_2_rods(position_m: np.ndarray, resolved: dict[str, Any]) -> np.ndarray:
    stage = resolved["geometry_mm"]["stage_2_round_quadrupole"]
    _, active = _stage_masks(position_m, resolved)
    return active & points_inside_rods(position_m[:, :2] * 1e3, stage["rod_array"])


def _aperture_losses(
    old_position: np.ndarray, new_position: np.ndarray, resolved: dict[str, Any]
) -> np.ndarray:
    loss = np.zeros(len(old_position), dtype=bool)
    for cone_name in ("first_cone", "second_cone"):
        cone = resolved["geometry_mm"][cone_name]
        plane_m = float(cone["aperture_reference_z_mm"]) * 1e-3
        crossed = (old_position[:, 2] < plane_m) & (new_position[:, 2] >= plane_m)
        denominator = new_position[:, 2] - old_position[:, 2]
        fraction = np.zeros(len(old_position))
        valid = crossed & (np.abs(denominator) > 1e-30)
        fraction[valid] = (plane_m - old_position[valid, 2]) / denominator[valid]
        crossing_x = old_position[:, 0] + fraction * (new_position[:, 0] - old_position[:, 0])
        crossing_y = old_position[:, 1] + fraction * (new_position[:, 1] - old_position[:, 1])
        radius = np.hypot(crossing_x, crossing_y)
        loss |= crossed & (radius > float(cone["aperture_radius_mm"]) * 1e-3)
    return loss


def simulate(
    particle_count: int,
    seed: int,
    resolved: dict[str, Any],
    science: dict[str, Any],
    numerics: dict[str, Any],
) -> SimulationResult:
    """Advance one deterministic-prefix cohort to loss, exit, or timeout."""
    validate_contracts(resolved, science, numerics)
    source_position, source_velocity, birth_times = source_particles(
        particle_count, seed, resolved, science
    )
    position = source_position.copy()
    velocity = source_velocity.copy()
    elapsed = np.zeros(particle_count)
    drag_exposure_integral = np.zeros(particle_count)
    statuses = np.full(particle_count, "alive", dtype=object)
    reasons = np.full(particle_count, "none", dtype=object)
    active = np.ones(particle_count, dtype=bool)
    dt = float(numerics["time_step_s"])
    max_steps = math.ceil(float(numerics["maximum_elapsed_time_s"]) / dt)
    sample_stride = int(numerics["trajectory_sample_stride_steps"])
    display_count = min(int(numerics["trajectory_display_particle_count"]), particle_count)
    traces = {
        particle_id: [(position[particle_id - 1, 2] * 1e3, position[particle_id - 1, 0] * 1e3, position[particle_id - 1, 1] * 1e3)]
        for particle_id in range(1, display_count + 1)
    }
    mass_kg = float(science["ion"]["mass_amu"]) * AMU_KG
    charge_c = int(science["ion"]["charge_state"]) * ELEMENTARY_CHARGE_C
    enclosure = resolved["geometry_mm"]["low_pressure_enclosure"]
    chamber_start_m = float(enclosure["start_z_mm"]) * 1e-3
    chamber_end_m = float(enclosure["end_z_mm"]) * 1e-3
    chamber_radius_m = float(enclosure["radius_mm"]) * 1e-3
    backward_limit_m = (float(science["source"]["plane_z_mm"]) - 0.5) * 1e-3

    for step in range(1, max_steps + 1):
        indices = np.flatnonzero(active)
        if len(indices) == 0:
            break
        old = position[indices].copy()
        local_time = birth_times[indices] + elapsed[indices]
        local_pressure = pressure_pa(old[:, 2], resolved, science)
        local_mobility = mobility_m2_v_s(local_pressure, science)
        gamma = abs(charge_c) / (mass_kg * local_mobility)
        field = electric_field_v_m(old, local_time, resolved, science)
        gas_velocity = np.zeros_like(old)
        gas_velocity[:, 2] = gas_axial_velocity_m_s(old[:, 2], resolved, science)
        numerator = (
            velocity[indices]
            + (charge_c * field / mass_kg + gamma[:, None] * gas_velocity) * dt
        )
        new_velocity = numerator / (1.0 + gamma[:, None] * dt)
        new_position = old + new_velocity * dt
        position[indices] = new_position
        velocity[indices] = new_velocity
        elapsed[indices] += dt
        drag_exposure_integral[indices] += gamma * dt

        local_alive = np.ones(len(indices), dtype=bool)

        def terminate(mask: np.ndarray, status: str, reason: str) -> None:
            selected = indices[local_alive & mask]
            statuses[selected] = status
            reasons[selected] = reason
            active[selected] = False
            local_alive[local_alive & mask] = False

        terminate(_aperture_losses(old, new_position, resolved), "lost", "aperture_interception")
        electrode = _inside_stage_1_rods(new_position, resolved) | _inside_stage_2_rods(new_position, resolved)
        terminate(electrode, "lost", "electrode")
        radial_escape = (new_position[:, 2] >= chamber_start_m) & (
            np.hypot(new_position[:, 0], new_position[:, 1]) > chamber_radius_m
        )
        terminate(radial_escape, "lost", "radial_escape")
        terminate(new_position[:, 2] < backward_limit_m, "lost", "backward_escape")
        transmitted = new_position[:, 2] >= chamber_end_m
        selected_transmitted = indices[local_alive & transmitted]
        if len(selected_transmitted):
            position[selected_transmitted, 2] = chamber_end_m
        terminate(transmitted, "transmitted", "acceptance_surface")

        if step % sample_stride == 0:
            for particle_id in range(1, display_count + 1):
                row = particle_id - 1
                if active[row]:
                    traces[particle_id].append(
                        (position[row, 2] * 1e3, position[row, 0] * 1e3, position[row, 1] * 1e3)
                    )

    if np.any(active):
        statuses[active] = "timeout"
        reasons[active] = "timeout"
        active[:] = False
    for particle_id in range(1, display_count + 1):
        row = particle_id - 1
        final_point = (position[row, 2] * 1e3, position[row, 0] * 1e3, position[row, 1] * 1e3)
        if traces[particle_id][-1] != final_point:
            traces[particle_id].append(final_point)
    return SimulationResult(
        source_positions_m=source_position,
        source_velocities_m_s=source_velocity,
        birth_times_s=birth_times,
        final_positions_m=position,
        final_velocities_m_s=velocity,
        elapsed_times_s=elapsed,
        drag_exposure_integrals=drag_exposure_integral,
        statuses=statuses,
        terminal_reasons=reasons,
        traces_mm=traces,
    )


def _component_state_row(
    particle_id: int,
    position_m: np.ndarray,
    velocity_m_s: np.ndarray,
    birth_time_s: float,
    elapsed_time_s: float,
    science: dict[str, Any],
    state_event: str,
    source_component_id: str,
    target_component_id: str,
) -> dict[str, object]:
    ion = science["ion"]
    drive = make_drive(science["electric_field"]["stage_2"])
    instrument_time_us = (birth_time_s + elapsed_time_s) * 1e6
    phase = (2.0 * math.pi * drive.frequency_hz * (birth_time_s + elapsed_time_s) + drive.phase_rad) % (
        2.0 * math.pi
    )
    mass_amu = float(ion["mass_amu"])
    charge_state = int(ion["charge_state"])
    return {
        "particle_id": particle_id,
        "parent_particle_id": None,
        "generation": 0,
        "species_id": ion["species_id"],
        "particle_weight": 1.0,
        "source_component_id": source_component_id,
        "target_component_id": target_component_id,
        "state_event": state_event,
        "frame_id": FRAME_ID,
        "clock_epoch_id": CLOCK_EPOCH_ID,
        "instrument_time_us": instrument_time_us,
        "lineage_age_us": elapsed_time_s * 1e6,
        "particle_age_us": elapsed_time_s * 1e6,
        "last_component_elapsed_time_us": elapsed_time_s * 1e6,
        "lineage_birth_time_us": birth_time_s * 1e6,
        "particle_birth_time_us": birth_time_s * 1e6,
        "mass_to_charge_Th": mass_to_charge_th(mass_amu, charge_state),
        "mass_amu": mass_amu,
        "charge_state": charge_state,
        "position_x_mm": position_m[0] * 1e3,
        "position_y_mm": position_m[1] * 1e3,
        "position_z_mm": position_m[2] * 1e3,
        "velocity_x_m_s": velocity_m_s[0],
        "velocity_y_m_s": velocity_m_s[1],
        "velocity_z_m_s": velocity_m_s[2],
        "kinetic_energy_eV": kinetic_energy_ev(mass_amu, *velocity_m_s),
        "phase_reference_id": "stage_2_rf",
        "phase_rad": phase,
    }


def write_result_tables(
    output_dir: Path, result: SimulationResult, science: dict[str, Any]
) -> dict[str, object]:
    """Write canonical source/exit states plus project-specific terminal events."""
    source_rows = [
        _component_state_row(
            index + 1,
            result.source_positions_m[index],
            result.source_velocities_m_s[index],
            result.birth_times_s[index],
            0.0,
            science,
            "source_release",
            "electrospray_source",
            PROJECT_ID,
        )
        for index in range(len(result.statuses))
    ]
    source_report = write_component_particle_state_csv(output_dir / "source_particle_state.csv", source_rows)
    transmitted_indices = np.flatnonzero(result.statuses == "transmitted")
    exit_report: dict[str, object] | None = None
    if len(transmitted_indices):
        exit_rows = [
            _component_state_row(
                int(index) + 1,
                result.final_positions_m[index],
                result.final_velocities_m_s[index],
                result.birth_times_s[index],
                result.elapsed_times_s[index],
                science,
                "component_exit",
                PROJECT_ID,
                "downstream_mass_analyzer_pending",
            )
            for index in transmitted_indices
        ]
        exit_report = write_component_particle_state_csv(output_dir / "exit_particle_state.csv", exit_rows)
    event_columns = [
        "particle_id",
        "status",
        "terminal_reason",
        "elapsed_time_us",
        "position_x_mm",
        "position_y_mm",
        "position_z_mm",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "velocity_z_m_s",
        "kinetic_energy_eV",
        "drag_exposure_integral",
    ]
    with (output_dir / "particle_events.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_columns, lineterminator="\n")
        writer.writeheader()
        for index in range(len(result.statuses)):
            writer.writerow(
                {
                    "particle_id": index + 1,
                    "status": result.statuses[index],
                    "terminal_reason": result.terminal_reasons[index],
                    "elapsed_time_us": result.elapsed_times_s[index] * 1e6,
                    "position_x_mm": result.final_positions_m[index, 0] * 1e3,
                    "position_y_mm": result.final_positions_m[index, 1] * 1e3,
                    "position_z_mm": result.final_positions_m[index, 2] * 1e3,
                    "velocity_x_m_s": result.final_velocities_m_s[index, 0],
                    "velocity_y_m_s": result.final_velocities_m_s[index, 1],
                    "velocity_z_m_s": result.final_velocities_m_s[index, 2],
                    "kinetic_energy_eV": kinetic_energy_ev(
                        float(science["ion"]["mass_amu"]), *result.final_velocities_m_s[index]
                    ),
                    "drag_exposure_integral": result.drag_exposure_integrals[index],
                }
            )
    return {"source_state_validation": source_report, "exit_state_validation": exit_report}


def summarize(result: SimulationResult, science: dict[str, Any]) -> dict[str, object]:
    """Compute compact, explicitly non-qualified transport diagnostics."""
    transmitted = result.statuses == "transmitted"
    reason_values, reason_counts = np.unique(result.terminal_reasons, return_counts=True)
    output: dict[str, object] = {
        "particle_count": len(result.statuses),
        "transmitted_count": int(np.count_nonzero(transmitted)),
        "transmission_fraction": float(np.mean(transmitted)),
        "terminal_reason_counts": {
            str(reason): int(count) for reason, count in zip(reason_values, reason_counts, strict=True)
        },
        "mean_drag_exposure_integral": float(np.mean(result.drag_exposure_integrals)),
    }
    if np.any(transmitted):
        exit_radius_mm = np.hypot(
            result.final_positions_m[transmitted, 0], result.final_positions_m[transmitted, 1]
        ) * 1e3
        exit_energy = [
            kinetic_energy_ev(float(science["ion"]["mass_amu"]), *velocity)
            for velocity in result.final_velocities_m_s[transmitted]
        ]
        output.update(
            mean_exit_radius_mm=float(np.mean(exit_radius_mm)),
            mean_exit_kinetic_energy_ev=float(np.mean(exit_energy)),
            mean_residence_time_us=float(np.mean(result.elapsed_times_s[transmitted]) * 1e6),
        )
    else:
        output.update(
            mean_exit_radius_mm=None,
            mean_exit_kinetic_energy_ev=None,
            mean_residence_time_us=None,
        )
    return output


def plot_screening_result(
    destination: Path,
    result: SimulationResult,
    resolved: dict[str, Any],
    science: dict[str, Any],
) -> None:
    """Export a compact report-profile trajectory and pressure diagnostic."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    geometry = resolved["geometry_mm"]
    figure, axes = plt.subplots(2, 1, figsize=(160 / 25.4, 115 / 25.4), constrained_layout=True)
    status_style = {
        "transmitted": ("#0072B2", "-"),
        "lost": ("#E69F00", "--"),
        "timeout": ("#000000", ":"),
    }
    used_labels: set[str] = set()
    for particle_id, points in result.traces_mm.items():
        values = np.asarray(points)
        status = str(result.statuses[particle_id - 1])
        color, line_style = status_style[status]
        label = status if status not in used_labels else None
        axes[0].plot(values[:, 0], values[:, 1], color=color, linestyle=line_style, linewidth=0.8, label=label)
        used_labels.add(status)
    first = geometry["first_cone"]
    second = geometry["second_cone"]
    for cone, label in ((first, "first aperture"), (second, "second aperture")):
        z = float(cone["aperture_reference_z_mm"])
        radius = float(cone["aperture_radius_mm"])
        axes[0].plot([z, z], [-7.5, -radius], color="#000000", linewidth=1.0)
        axes[0].plot([z, z], [radius, 7.5], color="#000000", linewidth=1.0, label=label)
    stage_1 = geometry["stage_1_elliptical_quadrupole"]
    stage_2 = geometry["stage_2_round_quadrupole"]
    axes[0].fill_between(
        [stage_1["axis_upstream_start_z_mm"], stage_1["downstream_flat_end_z_mm"]],
        [stage_1["ideal_field_radius_r0_mm"]] * 2,
        [7.5, 7.5],
        color="#999999",
        alpha=0.18,
    )
    axes[0].fill_between(
        [stage_1["axis_upstream_start_z_mm"], stage_1["downstream_flat_end_z_mm"]],
        [-7.5, -7.5],
        [-stage_1["ideal_field_radius_r0_mm"]] * 2,
        color="#999999",
        alpha=0.18,
        label="projected rod region",
    )
    axes[0].fill_between(
        [stage_2["upstream_flat_start_z_mm"], stage_2["downstream_flat_end_z_mm"]],
        [stage_2["ideal_field_radius_r0_mm"]] * 2,
        [7.5, 7.5],
        color="#777777",
        alpha=0.22,
    )
    axes[0].fill_between(
        [stage_2["upstream_flat_start_z_mm"], stage_2["downstream_flat_end_z_mm"]],
        [-7.5, -7.5],
        [-stage_2["ideal_field_radius_r0_mm"]] * 2,
        color="#777777",
        alpha=0.22,
    )
    axes[0].set(xlabel="Axial z (mm)", ylabel="Transverse x (mm)", ylim=(-7.5, 7.5))
    axes[0].grid(alpha=0.2)
    axes[0].legend(fontsize=7, ncol=3, loc="upper right")
    z_mm = np.linspace(float(science["source"]["plane_z_mm"]), geometry["low_pressure_enclosure"]["end_z_mm"], 600)
    axes[1].plot(z_mm, pressure_pa(z_mm * 1e-3, resolved, science), color="#0072B2", linewidth=1.2)
    axes[1].axvline(float(first["aperture_reference_z_mm"]), color="#000000", linewidth=0.8, linestyle="--")
    axes[1].axvline(float(second["aperture_reference_z_mm"]), color="#000000", linewidth=0.8, linestyle="--")
    axes[1].set(xlabel="Axial z (mm)", ylabel="Prescribed pressure (Pa)", yscale="log")
    axes[1].grid(alpha=0.2, which="both")
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, format="png", dpi=200, facecolor="white")
    plt.close(figure)
