"""Diagnose frozen local IP–P1 transport; never infer whole-MR performance.

Canonical CSV velocities are mm/us, positions mm and instrument times us.
All statistics use population moments; no tail rejection or FWHM proxy is used.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from common.analysis.figure_export import export_figures
from common.analysis.population_moments import population_pair_moments

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev


STATE_FIELDS = ("t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us", "potential_v")
PLANES = ("p1_near", "p1_far", "p1_exit")


def _load_rows(path: Path, *, states: bool = False) -> list[dict[str, Any]]:
    payload = path.read_bytes()
    lines = payload.splitlines(keepends=True)
    text = payload.decode("utf-8-sig").splitlines()
    reader = csv.DictReader(text)
    required = {"particle_id", *(STATE_FIELDS if states else ())}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError(f"Missing columns in {path}: {sorted(required)}")
    identity = hashlib.sha256(payload).hexdigest().upper()
    raw_path = str(path.resolve())
    result = []
    for number, row in enumerate(reader, 2):
        row["particle_id"] = int(row["particle_id"])
        if states:
            for key in STATE_FIELDS:
                row[key] = float(row[key])
                if not math.isfinite(row[key]):
                    raise ValueError(f"Nonfinite {key} in {path}:{number}")
        row.update(raw_path=raw_path, raw_sha256=identity, raw_line_number=number,
                   raw_line=lines[number - 1].decode("utf-8-sig").rstrip("\r\n"),
                   raw_line_sha256=hashlib.sha256(lines[number - 1]).hexdigest())
        result.append(row)
    return result


def _unique(rows: list[dict[str, Any]], label: str) -> dict[int, dict[str, Any]]:
    result = {row["particle_id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate particle identity in {label}")
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]], empty_fields: tuple[str, ...] = ("case_id", "particle_id")) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row)) or list(empty_fields)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _quantities(rows: list[dict[str, Any]], mass_u: float) -> dict[str, np.ndarray]:
    values = {key: np.array([row[key] for row in rows], dtype=float) for key in STATE_FIELDS}
    vx, vy, vz = (values[key] for key in ("vx_mm_us", "vy_mm_us", "vz_mm_us"))
    values["theta_x_deg"] = np.degrees(np.arctan2(vx, np.abs(vz)))
    values["theta_y_deg"] = np.degrees(np.arctan2(vy, np.abs(vz)))
    components = []
    for axis in "xyz":
        velocity = values[f"v{axis}_mm_us"] * 1000.0
        component = np.array([kinetic_energy_ev(mass_u, float(v), 0.0, 0.0) for v in velocity])
        values[f"k{axis}_ev"] = component
        components.append(component)
    values["kinetic_energy_ev"] = sum(components)
    return values


def compute_plane_statistics(rows: list[dict[str, Any]], mass_u: float) -> dict[str, Any]:
    """Return full-cohort population moments; empty input has null moments."""
    values = _quantities(rows, mass_u)
    result: dict[str, Any] = {"count": len(rows)}
    for key, array in values.items():
        result[f"mean_{key}"] = float(np.mean(array)) if len(array) else None
        result[f"sigma_{key}"] = float(np.std(array)) if len(array) else None
    result["time_sigma_ns"] = 1000 * float(np.std(values["t_us"])) if rows else None
    result["time_range_ns"] = 1000 * float(np.ptp(values["t_us"])) if rows else None
    for axis in "xy":
        if not rows:
            result[f"emittance_{axis}_mm_mrad"] = None
            continue
        position = values[f"{axis}_mm"]
        angle = np.radians(values[f"theta_{axis}_deg"]) * 1000
        moments = population_pair_moments(position, angle)
        determinant = moments["variance_first"] * moments["variance_second"] - moments["covariance"]**2
        result[f"emittance_{axis}_mm_mrad"] = math.sqrt(max(0.0, determinant))
    return result


def project_field_free_births(rows: list[dict[str, Any]], z_plane_mm: float) -> dict[str, Any]:
    """Project frozen birth states to a future -z plane with constant velocity.

    This counterfactual ignores all fields, electrodes and terminal outcomes.
    Each original instrument clock is retained: dt=(z_plane-z_birth)/vz.
    A uniform zero potential is only the reference gauge; the measured birth
    potential, if supplied, is preserved separately, never propagated as a field.
    Invalid/unreachable states remain explicit decisions in the original census.
    """
    if isinstance(z_plane_mm, bool) or not math.isfinite(z_plane_mm):
        raise ValueError("Finite global z reference plane required")
    _unique(rows, "field-free birth reference")
    crossings, decisions = [], []
    state_keys = ("t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
    for source in rows:
        pid = source["particle_id"]
        try:
            values = {key: float(source[key]) for key in state_keys}
        except (KeyError, TypeError, ValueError):
            values = {}
        reason, dt = None, None
        if len(values) != len(state_keys) or not all(math.isfinite(v) for v in values.values()):
            reason = "missing_or_nonfinite_birth_state"
        elif values["vz_mm_us"] == 0:
            reason = "zero_longitudinal_velocity"
        elif values["vz_mm_us"] > 0:
            reason = "velocity_not_forward_negative_z"
        else:
            dt = (z_plane_mm-values["z_mm"])/values["vz_mm_us"]
            if dt <= 0:
                reason = "plane_not_strictly_future_downstream"
            elif not math.isfinite(dt) or not all(math.isfinite(values[p]+values[v]*dt) for p, v in
                    (("x_mm", "vx_mm_us"), ("y_mm", "vy_mm_us"))) or not math.isfinite(values["t_us"]+dt):
                reason = "nonfinite_projected_state"
        if reason is None:
            row = dict(source, **values)
            row.update(t_us=values["t_us"]+dt, x_mm=values["x_mm"]+values["vx_mm_us"]*dt,
                       y_mm=values["y_mm"]+values["vy_mm_us"]*dt, z_mm=float(z_plane_mm),
                       potential_v=0., birth_potential_v=source.get("potential_v"), birth_t_us=values["t_us"], birth_z_mm=values["z_mm"],
                       propagation_time_us=dt, event="reference_plane", reason="field_free_constant_velocity",
                       qualification="counterfactual_no_field_no_electrode_survival_or_actual_terminal_claim")
            crossings.append(row)
        decisions.append(dict(particle_id=pid, status="reference_crossing" if reason is None else "unreachable_reference_plane",
                              reason=reason, propagation_time_us=dt if dt is not None and math.isfinite(dt) else None,
                              birth_t_us=values.get("t_us") if math.isfinite(values.get("t_us", float("nan"))) else None,
                              birth_z_mm=values.get("z_mm") if math.isfinite(values.get("z_mm", float("nan"))) else None,
                              z_plane_mm=float(z_plane_mm)))
    return dict(crossings=crossings, missing_ids=[r["particle_id"] for r in decisions if r["status"] != "reference_crossing"],
                particle_decisions=decisions, source_count=len(rows), crossing_count=len(crossings),
                z_plane_mm=float(z_plane_mm),
                scope="Zero-field constant-velocity counterfactual from exact individual birth states and clocks; unconstrained by conductors, collisions or actual terminals; invalid/missing input and unreachable reference decisions are not physical losses; no real-field focus claim")


def _validate_lens_contacts(directory: Path, terminals: dict[int, dict]) -> list[dict]:
    """Bind geometry-stop terminals to their exact native-step witnesses.

    The Lua kernel owns intersection geometry. This reader checks identity,
    first-contact interpolation and unmodified incoming native splat flags;
    it does not reinterpret a nearest PA node as a continuous collision.
    """
    path = directory / "lens_contacts.csv"
    expected = {pid for pid, row in terminals.items() if row["reason"] == "lens_contact"}
    if not path.is_file():
        if expected:
            raise ValueError("lens_contact terminal lacks its step-bracket evidence")
        return []
    contacts = _unique(_load_rows(path), "lens contact witnesses")
    if contacts.keys() != expected:
        raise ValueError("lens contact witnesses/terminals disagree")
    if not contacts:
        return []
    prepared = json.loads((directory / "geometry.json").read_text(encoding="utf-8-sig"))
    rods = {int(rod["electrode_id"]): rod for rod in prepared["geometry"]["lens_electrodes"]}
    for pid, row in contacts.items():
        electrode = int(row["electrode_id"])
        if electrode not in rods or row["component_name"] != rods[electrode]["name"]:
            raise ValueError("lens contact component is not in the canonical geometry")
        if int(row["native_splat_before"]) != 0 or row["face"] not in {"side", "cap_start", "cap_end", "initial_inside"}:
            raise ValueError("invalid geometry-stop face or overwritten native splat")
        fraction = float(row["fraction"])
        if not math.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError("invalid contact step fraction")
        for key in STATE_FIELDS[:-1]:
            value = float(row[key])
            if not math.isfinite(value) or value != terminals[pid][key]:
                raise ValueError("contact state differs from terminal")
        if not float(row["t0_us"]) <= float(row["t_us"]) <= float(row["t1_us"]):
            raise ValueError("contact time outside its native step")
        for key in STATE_FIELDS[:-1]:
            stem, unit = (key.split("_", 1))
            first = float(row[f"{stem}0_{unit}"])
            last = float(row[f"{stem}1_{unit}"])
            value = float(row[key])
            expected_value = first + fraction*(last-first)
            serial = 32*np.finfo(float).eps*max(1., abs(first), abs(last), abs(value))
            if not all(math.isfinite(v) for v in (first, last)) or abs(value-expected_value) > serial:
                raise ValueError("contact state is not the declared native-step interpolation")
    return list(contacts.values())


def _load_case(run: Path, case: dict[str, Any], source_count: int, maximum_step_us: float) -> dict[str, Any]:
    directory = run / case["directory"]
    events = _load_rows(directory / "events.csv", states=True)
    samples = _load_rows(directory / "samples.csv", states=True)
    if any(row["event"] not in {"birth", "plane", "terminal"} for row in events):
        raise ValueError(f"Unknown event in {directory}")
    births = _unique([row for row in events if row["event"] == "birth"], "births")
    terminals = _unique([row for row in events if row["event"] == "terminal"], "terminals")
    if len(births) != source_count or births.keys() != terminals.keys():
        raise ValueError(f"Incomplete birth/terminal cohort in {directory}")
    if any(row["reason"] not in {"reached_exit", "solver_stop", "timeout", "lens_contact"} for row in terminals.values()):
        raise ValueError(f"Unknown terminal reason in {directory}")
    _validate_lens_contacts(directory, terminals)
    planes = {plane: _unique([row for row in events if row["event"] == "plane" and row["reason"] == plane], plane)
              for plane in PLANES}
    if any(row["reason"] not in PLANES for row in events if row["event"] == "plane"):
        raise ValueError(f"Unknown plane in {directory}")
    if set(planes["p1_exit"]) != {pid for pid, row in terminals.items() if row["reason"] == "reached_exit"}:
        raise ValueError(f"Exit events disagree with terminal outcomes in {directory}")
    if any(row["vz_mm_us"] >= 0 for plane in planes.values() for row in plane.values()):
        raise ValueError(f"Wrong plane crossing direction in {directory}")
    for row in events:
        pid = row["particle_id"]
        if pid not in births or not births[pid]["t_us"] <= row["t_us"] <= terminals[pid]["t_us"]:
            raise ValueError(f"State outside particle lifetime: {directory}, ID {pid}")
    overshoots = []
    for pid, birth in births.items():
        particle_samples = [row for row in samples if row["particle_id"] == pid]
        if any(row["t_us"] < birth["t_us"] for row in particle_samples):
            raise ValueError(f"Sample before birth in {directory}, ID {pid}")
        terminal = terminals[pid]
        late = [row for row in particle_samples if row["t_us"] > terminal["t_us"]]
        if not late:
            continue
        if len(late) != 1 or terminal["reason"] != "reached_exit":
            raise ValueError(f"Invalid event interpolation halo in {directory}, ID {pid}")
        row = late[0]
        delta_us = row["t_us"] - terminal["t_us"]
        serialization_us = 8 * np.finfo(float).eps * max(abs(row["t_us"]), abs(terminal["t_us"]))
        exit_event = planes["p1_exit"][pid]
        if (row is not particle_samples[-1] or delta_us > maximum_step_us + serialization_us
                or row["vz_mm_us"] >= 0 or row["z_mm"] >= exit_event["z_mm"]
                or terminal["t_us"] != exit_event["t_us"] or terminal["z_mm"] != exit_event["z_mm"]):
            raise ValueError(f"Unbounded or wrong-direction interpolation halo in {directory}, ID {pid}")
        overshoots.append(dict(row, case_id=case["case_id"],
                               terminal_t_us=terminal["t_us"], terminal_z_mm=terminal["z_mm"],
                               delta_after_terminal_us=delta_us,
                               delta_after_exit_z_mm=row["z_mm"] - exit_event["z_mm"],
                               maximum_step_us=maximum_step_us, serialization_bound_us=serialization_us,
                               qualification="last_actual_step_after_interpolated_exit_not_canonical_lifetime"))
    if any(row["particle_id"] not in births for row in samples):
        raise ValueError(f"Sample with unknown identity in {directory}")
    raw_tracks = {pid: [births[pid], *[row for row in samples if row["particle_id"] == pid], terminals[pid]] for pid in births}
    tracks = {pid: [row for row in track if row["t_us"] <= terminals[pid]["t_us"]] for pid, track in raw_tracks.items()}
    for pid, track in tracks.items():
        track.sort(key=lambda row: row["t_us"])
        tracks[pid] = list({row["t_us"]: row for row in track}.values())
    for track in raw_tracks.values():
        track.sort(key=lambda row: row["t_us"])
    return {"case": case, "births": births, "terminals": terminals, "planes": planes, "tracks": tracks,
            "raw_tracks": raw_tracks, "overshoots": overshoots}


def prepare_common_time_snapshots(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interpolate only between saved states at shared, automatically chosen times.

    Five times span the common all-particle birth-to-first-terminal support.
    This keeps actual instrument-clock correlations and never extrapolates.
    """
    lower = max(row["t_us"] for case in cases for row in case["births"].values())
    upper = min(row["t_us"] for case in cases for row in case["terminals"].values())
    if lower > upper:
        return []
    result = []
    for index, time_us in enumerate(np.linspace(lower, upper, 5)):
        for case in cases:
            for pid, track in case["tracks"].items():
                times = np.array([row["t_us"] for row in track])
                if not times[0] <= time_us <= times[-1]:
                    raise ValueError("Snapshot extrapolation forbidden")
                row = {"case_id": case["case"]["case_id"], "snapshot_index": index,
                       "particle_id": pid, "t_us": float(time_us)}
                row.update({key: float(np.interp(time_us, times, [state[key] for state in track])) for key in STATE_FIELDS[1:]})
                result.append(row)
    return result


def _validate_source(cases: list[dict[str, Any]], source: dict[int, dict[str, Any]], mass_u: float) -> int:
    charges = {int(row["charge_state"]) for row in source.values()}
    if len(charges) != 1 or 0 in charges or any(float(row["mass_amu"]) != mass_u for row in source.values()):
        raise ValueError("Source mass/charge mismatch")
    mapping = {"t_us": ("instrument_time_us", 1.0), "x_mm": ("position_x_mm", 1.0),
               "y_mm": ("position_y_mm", 1.0), "vx_mm_us": ("velocity_x_m_s", .001),
               "vy_mm_us": ("velocity_y_m_s", .001), "vz_mm_us": ("velocity_z_m_s", .001)}
    for case in cases:
        if case["births"].keys() != source.keys():
            raise ValueError("Birth identity differs from component source")
        for pid, birth in case["births"].items():
            for key, (source_key, scale) in mapping.items():
                # Decimal CSV round trips can differ at the last binary digit.
                expected = float(source[pid][source_key]) * scale
                if not math.isclose(birth[key], expected, rel_tol=8 * np.finfo(float).eps, abs_tol=0.0):
                    raise ValueError(f"Changed source {key}, ID {pid}")
            expected_z = float(source[pid]["position_z_mm"]) + float(case["case"]["exit_z_mm"])
            if not math.isclose(birth["z_mm"], expected_z, rel_tol=8 * np.finfo(float).eps, abs_tol=0.0):
                raise ValueError(f"Changed source z translation, ID {pid}")
    return charges.pop()


def _energy_drift_rows(cases: list[dict[str, Any]], mass_u: float, charge_state: int) -> list[dict[str, Any]]:
    result = []
    for case in cases:
        for scope, tracks in (("canonical_lifetime", case["tracks"]), ("all_raw_observations_with_interpolation_halo", case["raw_tracks"])):
            for pid, track in tracks.items():
                values = _quantities(track, mass_u)
                energy = values["kinetic_energy_ev"] + charge_state * values["potential_v"]
                difference = energy - energy[0]
                terminal_index = next(index for index, row in enumerate(track) if row["event"] == "terminal")
                result.append({"case_id": case["case"]["case_id"], "particle_id": pid,
                               "observation_scope": scope,
                               "sample_count": len(track), "birth_hamiltonian_ev": float(energy[0]),
                               "terminal_minus_birth_ev": float(difference[terminal_index]),
                               "last_observation_minus_birth_ev": float(difference[-1]),
                               "max_absolute_drift_ev": float(np.max(np.abs(difference))),
                               "drift_sigma_ev": float(np.std(difference)),
                               "drift_range_ev": float(np.ptp(difference)),
                               "qualification": "observed_static_K_plus_qV_drift_no_tolerance_or_pass_claim"})
    return result


def _save_figure(figure: Any, path: Path) -> None:
    from matplotlib import pyplot as plt

    try:
        export_figures({path.with_suffix(""): figure}, formats=("png", "svg"), dpi=200, facecolor="white")
    finally:
        plt.close(figure)


def compute_longitudinal_chirp(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute s=-z, u=-vz covariance and unconstrained free-drift waist.

    tau*=-Cov(s,u)/Var(u) is in us. It minimizes simultaneous spatial
    variance under constant velocities; it is not an in-field arrival-time focus.
    """
    s = np.array([-row["z_mm"] for row in rows], dtype=float)
    u = np.array([-row["vz_mm_us"] for row in rows], dtype=float)
    moments = population_pair_moments(s, u)
    vs, vu, cov = (moments[key] for key in ("variance_first", "variance_second", "covariance"))
    tau = -cov / vu if vu else None
    slope = cov / vs if vs else None
    residual = u - u.mean() - slope * (s - s.mean()) if slope is not None else u - u.mean() if len(u) else u
    minimum_variance = max(0., vs - cov**2 / vu) if vu else vs
    return {"count": len(rows), "mean_z_mm": float(-s.mean()) if rows else None,
            "mean_u_mm_us": float(u.mean()) if rows else None,
            "variance_s_mm2": vs, "variance_u_mm2_us2": vu, "covariance_s_u_mm2_us": cov,
            "correlation_s_u": moments["correlation"], "regression_u_on_s_per_us": slope,
            "regression_u_residual_sigma_mm_us": float(np.std(residual)) if rows else None,
            "ballistic_tau_star_us": tau,
            "ballistic_waist_mean_z_mm": float(-(s.mean() + u.mean() * tau)) if tau is not None else None,
            "ballistic_minimum_sigma_s_mm": math.sqrt(minimum_variance) if minimum_variance is not None else None,
            "interpretation": "unconstrained_local_constant_velocity_spatial_waist_not_actual_in_field_time_focus"}


def compute_arrival_time_energy_correlations(rows: list[dict[str, Any]], mass_u: float) -> dict[str, Any]:
    """Return arrival correlations and mathematical drift-length minimum.

    t(L)=t_exit+L/u; t is us, u mm/us, so L* is mm. A negative L*
    is an upstream mathematical extrapolation, not a physical trajectory.
    """
    values = _quantities(rows, mass_u)
    u = -values["vz_mm_us"]
    if np.any(u <= 0):
        raise ValueError("Arrival drift estimate requires downstream negative vz")
    inverse_u = 1 / u
    time = values["t_us"]
    moments = population_pair_moments(time, inverse_u)
    variance = moments["variance_second"]
    covariance = moments["covariance"]
    distance = -covariance / variance if variance else None
    energy_moments = population_pair_moments(time, values["kinetic_energy_ev"])
    return {"count": len(rows), "correlation_arrival_t_total_k": energy_moments["correlation"],
            "correlation_arrival_t_inverse_u": moments["correlation"],
            "covariance_t_inverse_u_us2_mm": covariance,
            "variance_inverse_u_us2_mm2": variance,
            "ballistic_best_length_mm": distance,
            "ballistic_best_sigma_t_ns": float(np.std(time + distance * inverse_u) * 1000) if distance is not None else None,
            "ballistic_best_mean_z_mm": float(values["z_mm"].mean() - distance) if distance is not None else None,
            "interpretation": "unconstrained_constant_velocity_arrival_minimum_negative_length_is_mathematical_upstream_only"}


def _longitudinal_chirp_rows(cases: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for case in cases:
        case_id = case["case"]["case_id"]
        for index in sorted({row["snapshot_index"] for row in snapshots}):
            rows = [row for row in snapshots if row["case_id"] == case_id and row["snapshot_index"] == index]
            if not rows:
                continue
            chirp = compute_longitudinal_chirp(rows)
            tau = chirp["ballistic_tau_star_us"]
            result.append(dict(case_id=case_id, snapshot_index=index, t_us=rows[0]["t_us"],
                               ballistic_waist_time_us=rows[0]["t_us"] + tau if tau is not None else None,
                               **chirp))
    return result


def build_exit_phase_space_figure(cases: list[dict[str, Any]], mass_u: float) -> Any:
    """Render all P1 exit events in directly comparable case rows."""
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(len(cases), 4, figsize=(14, 3 * len(cases)), squeeze=False,
                                sharex="col", sharey="col", layout="constrained")
    for index, case in enumerate(cases):
        rows = list(case["planes"]["p1_exit"].values())
        values = _quantities(rows, mass_u)
        pairs = [("x_mm", "theta_x_deg", "x (mm)", "xz angle (deg)"),
                 ("y_mm", "theta_y_deg", "y (mm)", "yz angle (deg)"),
                 ("theta_x_deg", "theta_y_deg", "xz angle (deg)", "yz angle (deg)"),
                 ("ky_ev", "kz_ev", "Ky (eV)", "Kz (eV)")]
        for axis, (x, y, xlabel, ylabel) in zip(axes[index], pairs):
            axis.scatter(values[x], values[y], s=13, color="#0072B2", marker="o")
            axis.set(xlabel=xlabel, ylabel=ylabel)
            if not rows:
                axis.text(.5, .5, "No exit events", transform=axis.transAxes, ha="center")
        axes[index, 0].set_title(f"{case['case']['case_id']}: N={len(rows)} (all arrivals)", loc="left")
    figure.suptitle("P1 exit phase space — own cohorts, no tail rejection")
    return figure


def build_time_energy_figure(cases: list[dict[str, Any]], mass_u: float, pulse_time_us: float) -> Any:
    """Show absolute-clock arrival means plus display-only centered widths."""
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(len(cases), 4, figsize=(16, 3 * len(cases)), squeeze=False,
                                sharex="col", sharey="col", layout="constrained")
    arrivals = [list(case["planes"]["p1_exit"].values()) for case in cases]
    centered = [np.array([row["t_us"] for row in rows]) for rows in arrivals]
    centered = [(time - time.mean()) * 1000 if len(time) else time for time in centered]
    all_centered = np.concatenate(centered)
    bins = np.histogram_bin_edges(all_centered, bins="sqrt") if len(all_centered) else np.array([0.0, 1.0])
    for index, case in enumerate(cases):
        rows = arrivals[index]
        values = _quantities(rows, mass_u)
        times = centered[index]
        if rows:
            mean_after_pulse_ns = float((values["t_us"].mean() - pulse_time_us) * 1000)
            sigma_ns = float(np.std(values["t_us"]) * 1000)
            axes[index, 0].errorbar(mean_after_pulse_ns, 0., xerr=sigma_ns, fmt="o", color="#0072B2", capsize=4)
            axes[index, 0].text(.05, .9, f"Mean {mean_after_pulse_ns:.3f} ns\nSD {sigma_ns:.3f} ns", transform=axes[index, 0].transAxes, va="top")
        axes[index, 0].set(xlabel="Mean arrival after common pulse (ns)", ylabel="Mean with population SD")
        axes[index, 0].set_yticks([])
        axes[index, 1].hist(times, bins=bins, weights=np.full(len(rows), 1 / len(rows)) if rows else None,
                            color="#0072B2", histtype="step", linewidth=1.4)
        axes[index, 1].set(xlabel="t - mean(t_case) (ns; display only)", ylabel="Fraction per bin")
        for axis, key, label in zip(axes[index, 2:], ("kinetic_energy_ev", "kz_ev"), ("Total K (eV)", "Kz (eV)")):
            axis.scatter(times, values[key], s=13, color="#E69F00", marker="^")
            axis.set(xlabel="t - mean(t_case) (ns; display only)", ylabel=label)
        axes[index, 0].set_title(f"{case['case']['case_id']}: N={len(rows)}", loc="left")
        if not rows:
            axes[index, 0].text(.5, .5, "No exit events", transform=axes[index, 0].transAxes, ha="center")
    figure.suptitle("P1 exit time and energy — absolute means retained; centered display only, no FWHM assumption")
    return figure


def build_longitudinal_chirp_figure(cases: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> Any:
    """Show middle common-time s/u correlations, centered for display only."""
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(1, len(cases), figsize=(4 * len(cases), 4.5), squeeze=False,
                                sharex=True, sharey=True, layout="constrained")
    indices = sorted({row["snapshot_index"] for row in snapshots})
    middle = indices[len(indices) // 2] if indices else None
    for case, axis in zip(cases, axes[0]):
        rows = [row for row in snapshots if row["case_id"] == case["case"]["case_id"] and row["snapshot_index"] == middle]
        axis.set(xlabel="s - mean(s) (mm; s = -z; display only)", ylabel="u - mean(u) (mm/us; u = -vz)")
        if not rows:
            axis.text(.5, .5, "No shared active-time support", transform=axis.transAxes, ha="center", wrap=True)
            continue
        s = np.array([-row["z_mm"] for row in rows])
        u = np.array([-row["vz_mm_us"] for row in rows])
        chirp = compute_longitudinal_chirp(rows)
        axis.scatter(s - s.mean(), u - u.mean(), s=15, marker="o", color="#0072B2", label=f"All {len(rows)} active ions")
        slope = chirp["regression_u_on_s_per_us"]
        if slope is not None:
            limits = np.array([s.min() - s.mean(), s.max() - s.mean()])
            axis.plot(limits, slope * limits, color="#D55E00", linestyle="--", label="Linear regression")
        axis.set_title(f"{case['case']['case_id']}\nt = {rows[0]['t_us']:.9f} us\nMean z = {-s.mean():.4f} mm", fontsize=10)
        axis.legend(fontsize=8)
    figure.suptitle("Longitudinal chirp at the automatic middle common time — local observations, not an in-field focus")
    return figure


def build_spatial_snapshots_figure(cases: list[dict[str, Any]], snapshots: list[dict[str, Any]], epoch_us: float,
                                   transverse_axis: str = "y") -> Any:
    """Render simultaneous xz or yz locations on common physical axes."""
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(len(cases), 5, figsize=(17, 3 * len(cases)), squeeze=False,
                                sharex=True, sharey=True, layout="constrained")
    for i, case in enumerate(cases):
        for index, axis in enumerate(axes[i]):
            rows = [row for row in snapshots if row["case_id"] == case["case"]["case_id"] and row["snapshot_index"] == index]
            axis.set(xlabel="z (mm)", ylabel=f"{transverse_axis} (mm)", aspect="equal")
            if not rows:
                axis.text(.5, .5, "No shared active-time support", transform=axis.transAxes, ha="center", wrap=True)
                continue
            time_us = rows[0]["t_us"]
            axis.scatter([row["z_mm"] for row in rows], [row[f"{transverse_axis}_mm"] for row in rows], s=10, color="#009E73")
            unborn = sum(row["t_us"] > time_us for row in case["births"].values())
            ended = [row for row in case["terminals"].values() if row["t_us"] < time_us]
            arrived = sum(row["reason"] == "reached_exit" for row in ended)
            axis.set_title(f"{(time_us-epoch_us)*1000:.2f} ns after source epoch\nActive {len(rows)}, unborn {unborn}, exit {arrived}, lost {len(ended)-arrived}", fontsize=9)
        axes[i, 0].set_ylabel(f"{case['case']['case_id']}\n{transverse_axis} (mm)")
    figure.suptitle("Simultaneous packet positions — saved-state interpolation, no extrapolation")
    return figure


def analyze_study(run: Path) -> dict[str, Any]:
    """Write canonical local transport diagnostics under a mutable owning run.

    Raises ValueError on incomplete or inconsistent cohorts. Zero arrivals are
    retained as a failed local transport result rather than a plotting error.
    """
    run = Path(run)
    contract = json.loads((run / "inputs/resolved_study.json").read_text(encoding="utf-8-sig"))
    mass_u = float(contract["mass_u"])
    if not math.isfinite(mass_u) or mass_u <= 0:
        raise ValueError("mass_u must be finite and positive")
    census = _unique(_load_rows(run / "inputs/source_census.csv"), "source census")
    if len(census) != contract["mother_particle_count"]:
        raise ValueError("Mother census count mismatch")
    maximum_step_us = float(contract["contract"]["numerics"]["maximum_step_us"])
    if not math.isfinite(maximum_step_us) or maximum_step_us <= 0:
        raise ValueError("maximum_step_us must be finite and positive")
    cases = [_load_case(run, case, contract["source_count"], maximum_step_us) for case in contract["cases"]]
    if not cases or len({case["case"]["case_id"] for case in cases}) != len(cases):
        raise ValueError("Cases must have unique identities")
    source_ids = cases[0]["births"].keys()
    if not source_ids <= census.keys() or any(case["births"].keys() != source_ids for case in cases):
        raise ValueError("Local source identity mismatch")
    source = _unique(_load_rows(run / "inputs/component_particle_state.csv"), "component source")
    charge_state = _validate_source(cases, source, mass_u)
    result_dir = run / "results/local_diagnostics"
    result_dir.mkdir(parents=True, exist_ok=True)
    statistics, census_rows, losses, particles, arrival_correlations = [], [], [], [], []
    common = {plane: set.intersection(*(set(case["planes"][plane]) for case in cases)) for plane in PLANES}
    for case in cases:
        case_id = case["case"]["case_id"]
        for pid, original in census.items():
            terminal = case["terminals"].get(pid)
            outcome = terminal["reason"] if terminal else "upstream_not_handed_off"
            record = dict(original, case_id=case_id, outcome=outcome)
            if terminal:
                record.update({f"terminal_{key}": value for key, value in terminal.items()})
            census_rows.append(record)
            if outcome != "reached_exit":
                losses.append(record)
        for plane in PLANES:
            own = case["planes"][plane]
            for cohort, ids in (("own", set(own)), ("common", common[plane])):
                rows = [own[pid] for pid in sorted(ids)]
                elapsed_ns = np.array([(own[pid]["t_us"] - case["births"][pid]["t_us"]) * 1000 for pid in sorted(ids)])
                statistics.append(dict(case_id=case_id, plane=plane, cohort=cohort,
                                       distance_mm=case["case"]["distance_mm"],
                                       elapsed_from_birth_sigma_ns=float(np.std(elapsed_ns)) if rows else None,
                                       **compute_plane_statistics(rows, mass_u)))
                arrival_correlations.append(dict(case_id=case_id, plane=plane, cohort=cohort,
                                                 **compute_arrival_time_energy_correlations(rows, mass_u)))
            for pid, row in own.items():
                particles.append(dict(row, case_id=case_id, plane=plane,
                                      elapsed_from_birth_ns=(row["t_us"] - case["births"][pid]["t_us"]) * 1000,
                                      common_cohort=pid in common[plane]))
    snapshots = prepare_common_time_snapshots(cases)
    energy_drift = _energy_drift_rows(cases, mass_u, charge_state)
    overshoots = [row for case in cases for row in case["overshoots"]]
    chirps = _longitudinal_chirp_rows(cases, snapshots)
    for name, rows in (("plane_statistics", statistics), ("mother_census", census_rows), ("all_losses", losses),
                       ("plane_particles", particles), ("simultaneous_positions", snapshots),
                       ("hamiltonian_drift", energy_drift), ("observation_overshoot", overshoots),
                       ("longitudinal_chirp", chirps), ("arrival_time_energy_correlations", arrival_correlations)):
        _write_csv(result_dir / f"{name}.csv", rows)
    _save_figure(build_exit_phase_space_figure(cases, mass_u), result_dir / "exit_phase_space")
    _save_figure(build_time_energy_figure(cases, mass_u, contract["pulse_time_us"]), result_dir / "exit_time_energy")
    _save_figure(build_spatial_snapshots_figure(cases, snapshots, contract["source_epoch_us"]), result_dir / "packet_spatial_evolution")
    _save_figure(build_spatial_snapshots_figure(cases, snapshots, contract["source_epoch_us"], "x"), result_dir / "packet_spatial_evolution_xz")
    _save_figure(build_longitudinal_chirp_figure(cases, snapshots), result_dir / "common_time_longitudinal_chirp")
    summary = {"schema_version": 1, "qualification": "local_ip_p1_transport_only_no_mr_resolution_claim",
               "status": "complete" if all(case["planes"]["p1_exit"] for case in cases) else "no_arrival_in_one_or_more_cases",
               "mother_particle_count": len(census), "source_count": len(source_ids),
               "common_plane_counts": {plane: len(ids) for plane, ids in common.items()},
               "mass_u": mass_u, "charge_state": charge_state,
               "event_interpolation_halo_count": len(overshoots),
               "longitudinal_chirp_estimates": "unconstrained_constant_velocity_only_not_actual_in_field_time_focus",
               "maximum_observed_hamiltonian_drift_ev": max(row["max_absolute_drift_ev"] for row in energy_drift),
               "cases": [{"case_id": case["case"]["case_id"], "distance_mm": case["case"]["distance_mm"],
                          "exit_count": len(case["planes"]["p1_exit"]),
                          "local_loss_count": sum(row["reason"] != "reached_exit" for row in case["terminals"].values())}
                         for case in cases], "statistics_ddof": 0, "fwhm_estimated": False}
    metadata = {"schema_version": 1, "clock": "instrument t_us; one common pulse origin for display only",
                "analysis_code_sha256": file_sha256(Path(__file__)),
                "source_contract_path": str(run / "inputs/resolved_study.json"),
                "source_contract_sha256": file_sha256(run / "inputs/resolved_study.json"),
                "source_inputs": [{"path": str(run / case["case"]["directory"] / name),
                                   "sha256": file_sha256(run / case["case"]["directory"] / name)}
                                  for case in cases for name in ("events.csv", "samples.csv")],
                "statistics": "population SD, projected geometric rms emittance; all tails retained",
                "filters": "own and same-ID intersection both reported; no physical tail rejection",
                "snapshot_policy": "five shared all-active support times; linear saved-state interpolation, no extrapolation",
                "event_interpolation_halo": "single final actual step beyond interpolated reached_exit by at most maximum_step_us plus serialization; preserved separately and in raw Hamiltonian scope, excluded from canonical lifetime interpolation",
                "histogram": "shared sqrt bins in t-mean(t_case), centered for display only; all statistics retain instrument times; fraction per bin; no fit, KDE or FWHM proxy",
                "longitudinal_chirp": "automatic middle shared snapshot; s=-z and u=-vz centered only in display; regression line; CSV retains absolute z/time; unconstrained tau*/L* are mathematical ballistic extrapolations, not actual in-field focusing",
                "rendering": {"formats": ["png", "svg"], "dpi": 200, "shared_axes": True, "language": "English"},
                "qualification": summary["qualification"]}
    for name, value in (("summary", summary), ("figure_metadata", metadata)):
        (result_dir / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary
