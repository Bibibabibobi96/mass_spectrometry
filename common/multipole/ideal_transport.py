"""Ideal finite-length RF multipole L1 trajectory reference."""

from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path
from typing import Any

from common.multipole.family_contract import from_high_order_baseline
from common.contracts.particle_count_policy import validate_standard_particle_count


AMU_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19


def validate_contract(contract: dict[str, Any]) -> None:
    operating = from_high_order_baseline(contract)
    multipole = contract["multipole"]
    order = int(multipole["radial_order_n"])
    if order < 3 or int(multipole["electrode_count"]) != 2 * order:
        raise ValueError("high-order multipole requires electrode_count = 2*radial_order_n")
    if contract["field_model_id"] != "multipole.ideal_2n.v1":
        raise ValueError("unsupported field model")
    if contract["trajectory_model_id"] != "multipole.ideal_finite_length.time_domain.v1":
        raise ValueError("unsupported trajectory model")
    if contract["model_level"] != "L1":
        raise ValueError("ideal finite-length transport must declare L1")
    assumptions = contract["assumptions"]
    if any(assumptions[key] != "disabled" for key in (
        "collision_model", "space_charge_model", "magnetic_field_model"
    )):
        raise ValueError("minimal L1 reference requires collisions, space charge and magnetic field disabled")
    geometry = contract["geometry_mm"]
    validate_standard_particle_count(int(contract["particle_source"]["count"]))
    if not 0 < float(geometry["usable_radius"]) < float(geometry["inscribed_radius_r0"]):
        raise ValueError("usable radius must be positive and below r0")
    if not math.isclose(operating.geometry.r0_mm, float(geometry["inscribed_radius_r0"])):
        raise ValueError("normalized family r0 differs from the project baseline")


def potential_spatial(order: int, r0_m: float, x_m: float, y_m: float) -> float:
    """Return the ideal dimensionless spatial potential for unit group voltage."""
    return ((complex(x_m, y_m) / r0_m) ** order).real


def electric_field_xy(
    order: int, r0_m: float, voltage_v: float, x_m: float, y_m: float
) -> tuple[float, float]:
    """Return the instantaneous ideal transverse electric field in V/m."""
    power = complex(x_m, y_m) ** (order - 1)
    scale = order * voltage_v / (r0_m ** order)
    return -scale * power.real, scale * power.imag


def electric_field_series_xy(
    terms: list[tuple[int, float]], r0_m: float, rf_factor: float, x_m: float, y_m: float
) -> tuple[float, float]:
    """Return a transverse field from signed boundary cosine coefficients."""
    field_x = 0.0
    field_y = 0.0
    position = complex(x_m, y_m)
    for order, boundary_coefficient_v in terms:
        power = position ** (order - 1)
        scale = order * boundary_coefficient_v * rf_factor / (r0_m ** order)
        field_x -= scale * power.real
        field_y += scale * power.imag
    return field_x, field_y


def pseudopotential_ev(
    order: int, radius_m: float, r0_m: float, voltage_peak_v: float,
    frequency_hz: float, mass_amu: float, charge_state: int,
) -> float:
    charge = abs(charge_state) * ELEMENTARY_CHARGE_C
    mass = mass_amu * AMU_KG
    omega = 2 * math.pi * frequency_hz
    value_j = charge**2 * order**2 * voltage_peak_v**2 / (4 * mass * omega**2 * r0_m**2)
    value_j *= (radius_m / r0_m) ** (2 * order - 2)
    return value_j / ELEMENTARY_CHARGE_C


def adiabaticity(
    order: int, radius_m: float, r0_m: float, voltage_peak_v: float,
    frequency_hz: float, mass_amu: float, charge_state: int,
) -> float:
    charge = abs(charge_state) * ELEMENTARY_CHARGE_C
    mass = mass_amu * AMU_KG
    omega = 2 * math.pi * frequency_hz
    value = 2 * charge * order * (order - 1) * voltage_peak_v
    value /= mass * omega**2 * r0_m**2
    return value * (radius_m / r0_m) ** (order - 2)


def source_particles(contract: dict[str, Any]) -> list[dict[str, float]]:
    source = contract["particle_source"]
    validate_standard_particle_count(int(source["count"]))
    rng = random.Random(int(source["seed"]))
    mass_kg = float(source["mass_amu"]) * AMU_KG
    speed = math.sqrt(2 * float(source["kinetic_energy_eV"]) * ELEMENTARY_CHARGE_C / mass_kg)
    particles = []
    period_s = 1 / float(contract["rf"]["frequency_Hz"])
    for particle_id in range(1, int(source["count"]) + 1):
        radius = float(source["maximum_source_radius_mm"]) * 1e-3 * math.sqrt(rng.random())
        angle = 2 * math.pi * rng.random()
        cone = math.radians(float(source["maximum_divergence_deg"])) * math.sqrt(rng.random())
        velocity_angle = 2 * math.pi * rng.random()
        particles.append({
            "particle_id": particle_id,
            "birth_time_s": rng.random() * period_s,
            "x_m": radius * math.cos(angle),
            "y_m": radius * math.sin(angle),
            "vx_m_s": speed * math.sin(cone) * math.cos(velocity_angle),
            "vy_m_s": speed * math.sin(cone) * math.sin(velocity_angle),
            "vz_m_s": speed * math.cos(cone),
        })
    return particles


def _derivative(
    time_s: float, state: tuple[float, float, float, float], contract: dict[str, Any],
    field_terms: list[tuple[int, float]], rf_enabled: bool,
) -> tuple[float, float, float, float]:
    x_m, y_m, vx_m_s, vy_m_s = state
    rf = contract["rf"]
    r0_m = float(contract["geometry_mm"]["inscribed_radius_r0"]) * 1e-3
    phase = float(rf["phase_rad"])
    rf_factor = math.cos(2 * math.pi * float(rf["frequency_Hz"]) * time_s + phase) if rf_enabled else 0.0
    field_x, field_y = electric_field_series_xy(field_terms, r0_m, rf_factor, x_m, y_m)
    charge = int(contract["particle_source"]["charge_state"]) * ELEMENTARY_CHARGE_C
    mass = float(contract["particle_source"]["mass_amu"]) * AMU_KG
    return vx_m_s, vy_m_s, charge * field_x / mass, charge * field_y / mass


def _rk4_step(
    time_s: float, state: tuple[float, float, float, float], step_s: float,
    contract: dict[str, Any], field_terms: list[tuple[int, float]], rf_enabled: bool,
) -> tuple[float, float, float, float]:
    def add(base: tuple[float, ...], delta: tuple[float, ...], scale: float) -> tuple[float, ...]:
        return tuple(value + scale * change for value, change in zip(base, delta))

    k1 = _derivative(time_s, state, contract, field_terms, rf_enabled)
    k2 = _derivative(time_s + step_s / 2, add(state, k1, step_s / 2), contract, field_terms, rf_enabled)
    k3 = _derivative(time_s + step_s / 2, add(state, k2, step_s / 2), contract, field_terms, rf_enabled)
    k4 = _derivative(time_s + step_s, add(state, k3, step_s), contract, field_terms, rf_enabled)
    return tuple(
        value + step_s * (a + 2 * b + 2 * c + d) / 6
        for value, a, b, c, d in zip(state, k1, k2, k3, k4)
    )


def _simulate_particle(
    particle: dict[str, float], contract: dict[str, Any],
    field_terms: list[tuple[int, float]], rf_enabled: bool,
) -> dict[str, Any]:
    geometry = contract["geometry_mm"]
    numerics = contract["numerics"]
    length_m = float(geometry["effective_length"]) * 1e-3
    usable_radius_m = float(geometry["usable_radius"]) * 1e-3
    transit_s = length_m / particle["vz_m_s"]
    frequency_hz = float(contract["rf"]["frequency_Hz"])
    base_step_s = 1 / frequency_hz / int(numerics["rf_steps_per_period"])
    state = (particle["x_m"], particle["y_m"], particle["vx_m_s"], particle["vy_m_s"])
    time_s = particle["birth_time_s"]
    end_s = time_s + transit_s
    maximum_radius_m = math.hypot(state[0], state[1])
    status, reason = "transmitted", "ideal_exit"
    while time_s < end_s:
        step_s = min(base_step_s, end_s - time_s)
        state = _rk4_step(time_s, state, step_s, contract, field_terms, rf_enabled)
        time_s += step_s
        radius_m = math.hypot(state[0], state[1])
        maximum_radius_m = max(maximum_radius_m, radius_m)
        if radius_m >= usable_radius_m:
            status, reason = "lost", "usable_radius_exceeded"
            break
    return {
        **particle,
        "status": status,
        "terminal_reason": reason,
        "terminal_time_s": time_s,
        "terminal_x_m": state[0],
        "terminal_y_m": state[1],
        "terminal_vx_m_s": state[2],
        "terminal_vy_m_s": state[3],
        "maximum_radius_m": maximum_radius_m,
    }


def _case_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    transmitted = [row for row in rows if row["status"] == "transmitted"]
    radii_mm = [math.hypot(row["terminal_x_m"], row["terminal_y_m"]) * 1e3 for row in transmitted]
    return {
        "particles": len(rows),
        "transmitted": len(transmitted),
        "transmission_fraction": len(transmitted) / len(rows),
        "exit_rms_radius_mm": math.sqrt(sum(value**2 for value in radii_mm) / len(radii_mm)) if radii_mm else None,
        "maximum_radius_mm": max(row["maximum_radius_m"] for row in rows) * 1e3,
    }


def evaluate_contract(contract: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validate_contract(contract)
    particles = source_particles(contract)
    voltage = float(contract["rf"]["amplitude_V_peak"])
    order = int(contract["multipole"]["radial_order_n"])
    field_terms = [(order, voltage)]
    cases = {}
    all_rows = []
    for case_id, rf_enabled in (("rf_on", True), ("zero_rf_control", False)):
        rows = [_simulate_particle(particle, contract, field_terms, rf_enabled) for particle in particles]
        for row in rows:
            row["case_id"] = case_id
        all_rows.extend(rows)
        cases[case_id] = _case_metrics(rows)
    geometry = contract["geometry_mm"]
    source = contract["particle_source"]
    r0_m = float(geometry["inscribed_radius_r0"]) * 1e-3
    usable_m = float(geometry["usable_radius"]) * 1e-3
    reference = {
        "pseudopotential_at_usable_radius_eV": pseudopotential_ev(
            order, usable_m, r0_m, voltage, float(contract["rf"]["frequency_Hz"]),
            float(source["mass_amu"]), int(source["charge_state"]),
        ),
        "adiabaticity_at_source_radius": adiabaticity(
            order, float(source["maximum_source_radius_mm"]) * 1e-3, r0_m, voltage,
            float(contract["rf"]["frequency_Hz"]), float(source["mass_amu"]),
            int(source["charge_state"]),
        ),
    }
    acceptance = contract["functional_acceptance"]
    improvement = cases["rf_on"]["transmission_fraction"] - cases["zero_rf_control"]["transmission_fraction"]
    checks = {
        "minimum_rf_transmission": cases["rf_on"]["transmission_fraction"] >= float(acceptance["minimum_rf_transmission"]),
        "minimum_improvement_over_zero_rf": improvement >= float(acceptance["minimum_improvement_over_zero_rf"]),
    }
    metrics = {
        "schema_version": 1,
        "role": "ideal_multipole_l1_transport_metrics",
        "project_id": contract["project_id"],
        "model_level": "L1",
        "cases": cases,
        "rf_minus_zero_transmission": improvement,
        "reference": reference,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "claim_limit": "Ideal finite-length transverse field only; no round rods, fringe field, collisions, solver field, CAD or Formal claim.",
    }
    return metrics, all_rows


def evaluate_round_rod_contract(
    contract: dict[str, Any], screen_metrics: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate finite transport in the fitted 2D circular-rod field."""
    validate_contract(contract)
    selected = screen_metrics["selected_candidate"]
    coefficients = selected["boundary_cosine_coefficients_V"]
    source_drive = float(screen_metrics["field_solve_drive_V"])
    scale = float(contract["rf"]["amplitude_V_peak"]) / source_drive
    field_terms = [(int(order), float(value) * scale) for order, value in coefficients.items()]
    particles = source_particles(contract)
    cases: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    for case_id, rf_enabled in (("round_rod_rf_on", True), ("zero_rf_control", False)):
        rows = [_simulate_particle(particle, contract, field_terms, rf_enabled) for particle in particles]
        for row in rows:
            row["case_id"] = case_id
        all_rows.extend(rows)
        cases[case_id] = _case_metrics(rows)
    improvement = cases["round_rod_rf_on"]["transmission_fraction"] - cases["zero_rf_control"]["transmission_fraction"]
    acceptance = contract["functional_acceptance"]
    checks = {
        "minimum_rf_transmission": cases["round_rod_rf_on"]["transmission_fraction"] >= float(acceptance["minimum_rf_transmission"]),
        "minimum_improvement_over_zero_rf": improvement >= float(acceptance["minimum_improvement_over_zero_rf"]),
    }
    metrics = {
        "schema_version": 1,
        "role": "multipole_round_rod_l2_transport_metrics",
        "project_id": contract["project_id"],
        "model_level": "L2",
        "selected_geometry": {
            key: selected[key] for key in (
                "rod_radius_ratio", "rod_radius_mm", "rod_center_radius_mm",
                "minimum_adjacent_surface_gap_mm", "parasitic_harmonic_score",
            )
        },
        "field_terms_boundary_cosine_V": {str(order): value for order, value in field_terms},
        "cases": cases,
        "rf_minus_zero_transmission": improvement,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "claim_limit": "Fitted 2D COMSOL circular-rod field extended uniformly along z; no fringe field, 3D solver tracking, collisions, Candidate or Formal claim.",
    }
    return metrics, all_rows


def write_results(
    metrics: dict[str, Any], rows: list[dict[str, Any]], result_dir: Path,
    metrics_filename: str = "ideal_transport_metrics.json",
) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = result_dir / metrics_filename
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    fields = [
        "case_id", "particle_id", "status", "terminal_reason", "birth_time_s", "terminal_time_s",
        "x_m", "y_m", "vx_m_s", "vy_m_s", "vz_m_s", "terminal_x_m", "terminal_y_m",
        "terminal_vx_m_s", "terminal_vy_m_s", "maximum_radius_m",
    ]
    with (result_dir / "particle_events.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in rows)
    _write_figure(metrics, rows, result_dir / "transport_comparison.png")


def _write_figure(metrics: dict[str, Any], rows: list[dict[str, Any]], path: Path) -> None:
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(10, 4.2), constrained_layout=True)
    rf_case = "round_rod_rf_on" if "round_rod_rf_on" in metrics["cases"] else "rf_on"
    case_ids = ["zero_rf_control", rf_case]
    transmissions = [metrics["cases"][case]["transmission_fraction"] for case in case_ids]
    axes[0].bar(["0 V control", "RF on"], transmissions, color=["#bdbdbd", "#238b45"])
    axes[0].set(ylim=(0, 1.05), ylabel="Transmission fraction", title="Functional transport control")
    colors = {"zero_rf_control": "#969696", rf_case: "#2171b5"}
    for case_id in case_ids:
        selected = [row for row in rows if row["case_id"] == case_id]
        axes[1].scatter(
            [row["terminal_x_m"] * 1e3 for row in selected],
            [row["terminal_y_m"] * 1e3 for row in selected],
            s=18, alpha=0.75, label=case_id, color=colors[case_id],
        )
    axes[1].set(aspect="equal", xlabel="Terminal x (mm)", ylabel="Terminal y (mm)", title="Terminal transverse states")
    axes[1].legend(fontsize=8)
    figure.suptitle(metrics["project_id"] + f" — {metrics['model_level']} transport reference")
    figure.savefig(path, dpi=180)
    plt.close(figure)
