"""Audit recorded extraction impulses without changing trajectories or balancing errors.

CSV positions are world mm, velocities mm/us, and electric integrals V us/mm.
The exporter consumes stopped producers only and writes fresh run-local evidence.
"""
from __future__ import annotations

import csv
import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import charge_to_mass_c_per_kg
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import to_project_position, to_project_vector
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import shape_bounds

AXES = "xyz"
STEP_COLUMNS = ("particle_id", "step_index", "start_t_us", "end_t_us",
               *(f"{end}_{axis}_mm" for end in ("start", "end") for axis in AXES),
               *(f"{state}_v{axis}_mm_us" for state in ("start_post", "end_pre", "end_post") for axis in AXES),
               "pressure_pa")
IMPULSE_COLUMNS = ("particle_id", "step_index", "electrode_id", "start_t_us", "end_t_us",
                  *(f"integral_e{a}_v_us_per_mm" for a in AXES),
                  *(f"fine_minus_coarse_e{a}_v_us_per_mm" for a in AXES),
                  "max_reconstruction_error_v_per_mm",
                  *(f"unit_integral_e{a}_us_per_mm" for a in AXES))
REGIONS = ("upstream_E5", "E5_slab", "E5_to_E14_gap", "E14_slab", "downstream_E14")
TERMS = tuple(f"E{i}" for i in range(1, 16)) + ("collision", "field_residual")
PRODUCER_SHA256 = file_sha256(Path(__file__))


def _table(path: Path, fields: tuple[str, ...] | None = None) -> Iterable[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if fields is not None and tuple(reader.fieldnames or ()) != fields:
            raise ValueError(f"unsupported force audit columns: {path.name}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"malformed CSV row: {path.name}")
            yield row


def _number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("force audit requires finite values")
    return result


def _index(value: Any) -> int:
    result = _number(value)
    if result < 1 or not result.is_integer():
        raise ValueError("force audit IDs and indices must be positive integers")
    return int(result)


def _vector(row: dict, template: str) -> np.ndarray:
    return np.array([_number(row[template.format(a=a)]) for a in AXES])


def extraction_surfaces(config: dict) -> dict:
    """Derive four axial envelope planes from frozen E5/E14 CSG, not contacts."""
    direction = to_project_vector(config, (0, 1, 0))
    if tuple(direction) != (0.0, 0.0, -1.0):
        raise ValueError("force audit requires declared world -z extraction frame")
    electrodes = {item["electrode_id"]: item for item in config["native_projection"]["electrodes"]}
    slabs = []
    for electrode_id in (5, 14):
        bounds = [shape_bounds(shape) for shape in electrodes[electrode_id]["solids"]]
        positive = [(low,high) for low,high in bounds if low[1] > 0]
        if len(positive) != 1:
            raise ValueError("ambiguous extraction-side E5/E14 slab geometry")
        low,high = positive[0]
        z = [to_project_position(config, corner)[2] for corner in
             itertools.product(*zip(low, high, strict=True))]
        slabs.append(dict(electrode_id=electrode_id, upstream_z_mm=max(z), downstream_z_mm=min(z)))
    planes = [value for slab in slabs for value in (slab["upstream_z_mm"], slab["downstream_z_mm"])]
    if any(left <= right for left, right in zip(planes, planes[1:])):
        raise ValueError("E5/E14 surfaces are not ordered along -z extraction")
    return dict(slabs=slabs, planes_z_mm=planes, region_labels=list(REGIONS),
                interpretation="Axial CSG envelope slabs, not local metal faces or electrode contact tests; formed slopes and frozen cutouts remain geometric boundaries.")


def spatial_fractions(start_z_mm: float, end_z_mm: float, planes_z_mm: list[float]) -> np.ndarray:
    """Split a recorded chord by exact plane parameters, approximating impulse density."""
    def region(z: float) -> int:
        return sum(z < plane for plane in planes_z_mm)
    fractions = np.zeros(5)
    if end_z_mm == start_z_mm:
        fractions[region(start_z_mm)] = 1
        return fractions
    cuts = sorted([0.0, 1.0, *(u for plane in planes_z_mm
                    if 0 < (u := (plane - start_z_mm) / (end_z_mm - start_z_mm)) < 1)])
    for left, right in zip(cuts, cuts[1:]):
        z = start_z_mm + (end_z_mm - start_z_mm) * (left + right) / 2
        fractions[region(z)] += right - left
    return fractions


def _census(events: Iterable[dict], expected: int) -> tuple[dict, dict, dict]:
    sources, terminals, exits = {}, {}, {}
    for line, row in enumerate(events, 2):
        pid = _index(row["particle_id"])
        target = {"source": sources, "terminal": terminals, "extraction_exit": exits}.get(row["event"])
        if target is not None:
            if pid in target:
                raise ValueError("duplicate force audit source/terminal/exit event")
            target[pid] = dict(row, csv_line=line)
    if len(sources) != expected or set(terminals) != set(sources) or not set(exits) <= set(sources):
        raise ValueError("force audit requires complete source and terminal mother census")
    return sources, terminals, exits


def _load_steps(rows: Iterable[dict], source_ids: set[int]) -> dict:
    steps = {}
    previous = {}
    for row in rows:
        pid, index = _index(row["particle_id"]), _index(row["step_index"])
        if pid not in source_ids or (pid, index) in steps:
            raise ValueError("unknown or duplicate audit step identity")
        numeric = {key: _number(row[key]) for key in STEP_COLUMNS[2:]}
        if numeric["end_t_us"] < numeric["start_t_us"] or numeric["pressure_pa"] < 0:
            raise ValueError("invalid audit step time or pressure")
        start, end = _vector(numeric, "start_post_v{a}_mm_us"), _vector(numeric, "end_post_v{a}_mm_us")
        before = previous.get(pid)
        if index != (1 if before is None else before[0] + 1):
            raise ValueError("audit step indices are not contiguous")
        if before is not None and (numeric["start_t_us"] != before[1]
                                   or not np.array_equal(start, before[2])
                                   or not np.array_equal(_vector(numeric, "start_{a}_mm"), before[3])):
            raise ValueError("audit step raw state continuity is broken")
        previous[pid] = index, numeric["end_t_us"], end, _vector(numeric, "end_{a}_mm")
        steps[pid, index] = dict(**numeric, components=np.zeros((15, 3)),
                                quadrature=np.zeros((15, 3)), unit=np.zeros((15, 3)),
                                seen=set(), reconstruction=0.0)
    return steps


def _load_impulses(rows: Iterable[dict], steps: dict, factor: float) -> None:
    for row in rows:
        key = _index(row["particle_id"]), _index(row["step_index"])
        electrode = _index(row["electrode_id"])
        if key not in steps or electrode > 15:
            raise ValueError("impulse has unknown audit step/electrode")
        step = steps[key]
        if electrode in step["seen"]:
            raise ValueError("duplicate electrode impulse within audit step")
        if any(_number(row[f"{end}_t_us"]) != step[f"{end}_t_us"] for end in ("start", "end")):
            raise ValueError("impulse and state clocks differ")
        step["seen"].add(electrode)
        step["components"][electrode-1] = factor * _vector(row, "integral_e{a}_v_us_per_mm")
        step["quadrature"][electrode-1] = factor * _vector(row, "fine_minus_coarse_e{a}_v_us_per_mm")
        step["unit"][electrode-1] = factor * _vector(row, "unit_integral_e{a}_us_per_mm")
        error = _number(row["max_reconstruction_error_v_per_mm"])
        if error < 0:
            raise ValueError("negative reconstruction error")
        step["reconstruction"] = max(step["reconstruction"], error)
    if any(step["seen"] != set(range(1, 16)) for step in steps.values()):
        raise ValueError("audit step lacks one or more of 15 electrode impulses")


def covariance_budget(terms: np.ndarray, names: list[str], final: np.ndarray) -> dict:
    """Return every population xyz/component covariance, including signed cross terms."""
    count = len(terms)
    labels = [f"{name}.{axis}" for name in names for axis in AXES]
    if not count:
        return dict(count=0, labels=labels, matrix_m2_s2=None, final_covariance_m2_s2=None)
    flat = terms.reshape(count, -1)
    centered = flat - flat.mean(axis=0)
    matrix = centered.T @ centered / count
    final_centered = final - final.mean(axis=0)
    actual = final_centered.T @ final_centered / count
    summed = matrix.reshape(len(names), 3, len(names), 3).sum(axis=(0, 2))
    return dict(count=count, labels=labels, matrix_m2_s2=matrix.tolist(),
                means_m_s=flat.mean(axis=0).tolist(), final_covariance_m2_s2=actual.tolist(),
                reconstructed_covariance_m2_s2=summed.tolist(),
                covariance_closure_max_abs_m2_s2=float(np.max(np.abs(actual-summed))),
                definition="Population covariance ddof=0; ordered off-diagonal component pairs each appear once in the full sum. No rescaling.")


def _flat_vector(prefix: str, vector: np.ndarray) -> dict:
    return {f"{prefix}_{axis}_m_s": float(value) for axis, value in zip(AXES, vector, strict=True)}


def variance_terms(covariance: dict) -> list[dict]:
    """Expose Var(final)-Var(initial) as signed diagonal and doubled cross terms."""
    if covariance["matrix_m2_s2"] is None:
        return []
    names = ["initial", *TERMS]
    matrix = np.asarray(covariance["matrix_m2_s2"]).reshape(18, 3, 18, 3)
    rows = []
    for axis_index, axis in enumerate(AXES):
        for left, right in itertools.combinations_with_replacement(range(18), 2):
            multiplier = 1 if left == right else 2
            rows.append(dict(axis=axis, component_a=names[left], component_b=names[right],
                             covariance_m2_s2=float(matrix[left, axis_index, right, axis_index]),
                             multiplier=multiplier,
                             variance_contribution_m2_s2=float(multiplier*matrix[left, axis_index, right, axis_index]),
                             included_in_variance_growth=not (left == right == 0)))
    return rows


def phase_space_statistics(particles: list[dict]) -> dict:
    """Report full mixed-unit 6D covariance and the two signed angles to |vz|."""
    rows = [row for row in particles if row["availability"] == "available"]
    result = {}
    labels = [*(f"{axis}_mm" for axis in AXES), *(f"v{axis}_m_s" for axis in AXES)]
    for name, position_prefix, velocity_prefix in (("audit_start", "audit_start", "initial_v"),
                                                  ("actual_last", "audit_last", "actual_last_v")):
        if not rows:
            result[name] = dict(count=0, labels=labels, covariance=None, angles=None)
            continue
        array = np.array([[*(row[f"{position_prefix}_{a}_mm"] for a in AXES),
                           *(row[f"{velocity_prefix}_{a}_m_s"] for a in AXES)] for row in rows])
        centered = array - array.mean(axis=0)
        usable = array[np.abs(array[:, 5]) > 0]
        angles = np.degrees(np.arctan2(usable[:, 3:5], np.abs(usable[:, 5, None])))
        result[name] = dict(count=len(array), particle_ids=[row["particle_id"] for row in rows], labels=labels,
                            mean=array.mean(axis=0).tolist(), standard_deviation_population=array.std(axis=0).tolist(),
                            covariance=(centered.T @ centered / len(array)).tolist(),
                            covariance_units="Outer product of row/column label units: mm2, mm*m/s, or m2/s2.",
                            angles=dict(count=len(angles), omitted_zero_vz_count=len(array)-len(angles),
                                        labels=["theta_x_deg", "theta_y_deg"],
                                        mean=angles.mean(axis=0).tolist() if len(angles) else None,
                                        standard_deviation_population=angles.std(axis=0).tolist() if len(angles) else None,
                                        definition="atan2(vx or vy, abs(vz)); trapping-start angles are not a paraxial acceptance claim."))
    return result


def _aggregate(steps: dict, sources: dict, terminals: dict, exits: dict, surfaces: dict) -> dict:
    particles, electrodes, spatial, details, all_terms, spatial_terms, finals = [], [], [], [], [], [], []
    for pid in sorted(sources):
        keys = sorted(key for key in steps if key[0] == pid)
        row = dict(particle_id=pid, availability="available" if keys else "not_recorded_in_audit_window",
                   audit_step_count=len(keys), terminal_reason=terminals[pid]["reason"],
                   source_csv_line=sources[pid]["csv_line"], terminal_csv_line=terminals[pid]["csv_line"],
                   terminal_t_us=_number(terminals[pid]["t_us"]),
                   extraction_exit_csv_line=exits[pid]["csv_line"] if pid in exits else None)
        if not keys:
            particles.append(row)
            continue
        first, last = steps[keys[0]], steps[keys[-1]]
        initial, final = _vector(first, "start_post_v{a}_mm_us") * 1000, _vector(last, "end_post_v{a}_mm_us") * 1000
        accum, regional, unit, quadrature = np.zeros((17, 3)), np.zeros((5, 17, 3)), np.zeros((15, 3)), np.zeros((15, 3))
        actual = np.zeros(3)
        maximum_reconstruction = 0.0
        for key in keys:
            step = steps[key]
            electric = 1000 * (_vector(step, "end_pre_v{a}_mm_us") - _vector(step, "start_post_v{a}_mm_us"))
            collision = 1000 * (_vector(step, "end_post_v{a}_mm_us") - _vector(step, "end_pre_v{a}_mm_us"))
            residual = electric - step["components"].sum(axis=0)
            increments = np.vstack((step["components"], collision, residual))
            fractions = spatial_fractions(step["start_z_mm"], step["end_z_mm"], surfaces["planes_z_mm"])
            regional[:, :15] += fractions[:, None, None] * step["components"][None, :, :]
            regional[:, 16] += fractions[:, None] * residual
            endpoint = spatial_fractions(step["end_z_mm"], step["end_z_mm"], surfaces["planes_z_mm"])
            regional[:, 15] += endpoint[:, None] * collision
            actual += electric
            accum += increments
            unit += step["unit"]
            quadrature += step["quadrature"]
            maximum_reconstruction = max(maximum_reconstruction, step["reconstruction"])
            details.append(dict(particle_id=pid, step_index=key[1], start_t_us=step["start_t_us"],
                                end_t_us=step["end_t_us"], start_z_mm=step["start_z_mm"], end_z_mm=step["end_z_mm"],
                                pressure_pa=step["pressure_pa"], crossed_surface_count=int(np.count_nonzero(fractions)-1),
                                max_reconstruction_error_v_per_mm=step["reconstruction"],
                                **_flat_vector("actual_electric_delta_v", electric),
                                **_flat_vector("collision_delta_v", collision),
                                **_flat_vector("field_residual_delta_v", residual),
                                **_flat_vector("signed_5_minus_3_node_delta_v", step["quadrature"].sum(axis=0))))
        row.update(audit_start_t_us=first["start_t_us"], audit_last_t_us=last["end_t_us"],
                   audit_start_x_mm=first["start_x_mm"], audit_start_y_mm=first["start_y_mm"], audit_start_z_mm=first["start_z_mm"],
                   audit_last_x_mm=last["end_x_mm"], audit_last_y_mm=last["end_y_mm"], audit_last_z_mm=last["end_z_mm"],
                   **_flat_vector("initial_v", initial), **_flat_vector("actual_last_v", final),
                   **_flat_vector("actual_electric_delta_v", actual),
                   **_flat_vector("collision_delta_v", accum[15]), **_flat_vector("field_residual_delta_v", accum[16]),
                   **_flat_vector("telescoping_closure", final-initial-accum.sum(axis=0)),
                   max_reconstruction_error_v_per_mm=maximum_reconstruction)
        if pid in exits:
            exit_velocity = 1000 * _vector(exits[pid], "v{a}_mm_us")
            exit_position = _vector(exits[pid], "{a}_mm")
            last_position = _vector(last, "end_{a}_mm")
            row.update(interpolated_exit_t_us=_number(exits[pid]["t_us"]),
                       audit_last_minus_interpolated_exit_us=last["end_t_us"]-_number(exits[pid]["t_us"]),
                       **_flat_vector("interpolated_exit_v", exit_velocity),
                       **_flat_vector("actual_last_minus_interpolated_exit_v", final-exit_velocity))
            row.update({f"interpolated_exit_{a}_mm": float(exit_position[i]) for i, a in enumerate(AXES)})
            row.update({f"actual_last_minus_interpolated_exit_{a}_mm": float(last_position[i]-exit_position[i]) for i, a in enumerate(AXES)})
        particles.append(row)
        all_terms.append(np.vstack((initial, accum)))
        spatial_terms.append(np.vstack((initial, regional.reshape(-1, 3))))
        finals.append(final)
        for electrode in range(15):
            electrodes.append(dict(particle_id=pid, electrode_id=electrode+1,
                                   **_flat_vector("delta_v", accum[electrode]),
                                   **_flat_vector("signed_5_minus_3_node_delta_v", quadrature[electrode]),
                                   **{f"fixed_path_response_{a}_m_s_per_v": float(unit[electrode, i]) for i, a in enumerate(AXES)}))
        for region, increments in zip(REGIONS, regional, strict=True):
            for term, vector in zip(TERMS, increments, strict=True):
                spatial.append(dict(particle_id=pid, region=region, component=term, **_flat_vector("delta_v", vector)))
    names = ["initial", *TERMS]
    region_names = ["initial", *(f"{region}:{term}" for region in REGIONS for term in TERMS)]
    return dict(particles=particles, electrodes=electrodes, spatial=spatial, steps=details,
                covariance=covariance_budget(np.asarray(all_terms), names, np.asarray(finals)),
                spatial_covariance=covariance_budget(np.asarray(spatial_terms), region_names, np.asarray(finals)))


def prepare_force_budget(run: Path) -> dict:
    """Validate both raw audit tables and full census, then calculate unadjusted budgets."""
    run = Path(run)
    paths = [run/p for p in ("inputs/resolved_model.json", "simion/events.csv", "simion/extraction_steps.csv", "simion/extraction_impulses.csv")]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"required extraction force audit input missing: {path}")
    config = json.loads(paths[0].read_text(encoding="utf-8-sig"))
    sources, terminals, exits = _census(_table(paths[1]), config["source"]["particle_count"])
    surfaces = extraction_surfaces(config)
    steps = _load_steps(_table(paths[2], STEP_COLUMNS), set(sources))
    window_start = _number(config["native_timing"]["primary_quench_us"])
    recorded_ids = {pid for pid, _ in steps}
    expected_ids = {pid for pid, row in terminals.items() if _number(row["t_us"]) >= window_start}
    if recorded_ids != expected_ids:
        raise ValueError("audit window availability differs from full terminal census")
    for (pid, _), step in steps.items():
        if step["start_t_us"] < window_start:
            raise ValueError("audit step lies outside its particle extraction window")
    species = config["source"]["species"]
    factor = charge_to_mass_c_per_kg(species["mass_amu"], species["charge_state"]) * 1e-3
    _load_impulses(_table(paths[3], IMPULSE_COLUMNS), steps, factor)
    result = _aggregate(steps, sources, terminals, exits, surfaces)
    result["variance_terms"] = variance_terms(result["covariance"])
    result["phase_space"] = phase_space_statistics(result["particles"])
    result.update(source_count=len(sources), surfaces=surfaces,
                  audit_window_start_us=window_start,
                  source_records=[dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=file_sha256(path)) for path in paths],
                  frame_id=config["coordinate_transform"]["to_frame_id"],
                  losses=[dict(particle_id=pid, reason=row["reason"], t_us=_number(row["t_us"]),
                               event_csv_line=row["csv_line"], source="simion/events.csv")
                          for pid, row in sorted(terminals.items()) if row["reason"] != "acceptance_surface"])
    return result


def build_force_budget_figure(data: dict) -> Figure:
    """Render signed impulses, collision/closure, phase space and covariance with English labels."""
    figure = Figure(figsize=(12, 10), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(3, 2)
    available = [row for row in data["particles"] if row["availability"] == "available"]
    names = [*TERMS]
    for column, axis_name in enumerate("xy"):
        panel = axes[0, column]
        for i, component in enumerate(names):
            values = ([row[f"delta_v_{axis_name}_m_s"] for row in data["electrodes"] if f"E{row['electrode_id']}" == component]
                      if i < 15 else [row[f"{component if i == 15 else 'field_residual'}_delta_v_{axis_name}_m_s"] for row in available])
            if values:
                panel.errorbar(i, np.mean(values), yerr=np.std(values), fmt="o" if i < 15 else "s", color="#0072B2" if i < 15 else "#D55E00", capsize=2)
        panel.axhline(0, color="0.5", linewidth=.6)
        panel.set(xticks=range(17), xticklabels=names, ylabel=f"Delta v{axis_name} (m/s)", title=f"Signed {axis_name} impulse: mean +/- population SD")
        panel.tick_params(axis="x", labelrotation=65, labelsize=7)
    for column, axis_name in enumerate("xy"):
        panel = axes[1, column]
        for prefix, label, marker, color in (("audit_start", "Audit start", "o", "#0072B2"), ("audit_last", "Actual last post-collision", "x", "#D55E00")):
            velocity = "initial_v" if prefix == "audit_start" else "actual_last_v"
            panel.scatter([r[f"{prefix}_{axis_name}_mm"] for r in available], [r[f"{velocity}_{axis_name}_m_s"] for r in available], label=label, marker=marker, color=color, s=16)
        panel.set(xlabel=f"World {axis_name} (mm)", ylabel=f"v{axis_name} (m/s)", title=f"{axis_name} phase space; individual audit endpoints")
        panel.legend(fontsize=8)
    for axis_name, marker, color in zip(AXES, ("o", "s", "^"), ("#0072B2", "#D55E00", "#009E73"), strict=True):
        axes[2, 0].scatter([r["particle_id"] for r in available], [r[f"field_residual_delta_v_{axis_name}_m_s"] for r in available], marker=marker, color=color, label=axis_name, s=14)
    axes[2, 0].set(xlabel="Particle ID", ylabel="Actual electric - 15-electrode sum (m/s)", title="Unassigned field residual (never redistributed)")
    axes[2, 0].legend()
    covariance = data["covariance"]["matrix_m2_s2"]
    if covariance is not None:
        matrix = np.asarray(covariance).reshape(18, 3, 18, 3)[:, 0, :, 0]
        maximum = max(float(np.max(np.abs(matrix))), np.finfo(float).tiny)
        artist = axes[2, 1].imshow(matrix, vmin=-maximum, vmax=maximum, cmap="RdBu_r")
        figure.colorbar(artist, ax=axes[2, 1], label="Cov(vx terms) (m2/s2)")
        axes[2, 1].set(xticks=range(18), yticks=range(18), xticklabels=["initial", *names], yticklabels=["initial", *names], title="All signed vx covariance terms")
        axes[2, 1].tick_params(axis="x", labelrotation=90, labelsize=6)
        axes[2, 1].tick_params(axis="y", labelsize=6)
    else:
        axes[2, 1].text(.5, .5, "No recorded extraction audit states", ha="center", transform=axes[2, 1].transAxes)
    figure.suptitle(f"Extraction force audit: recorded N={len(available)}/{data['source_count']}; losses retained\nActual callback endpoints; interpolated exit events are separate observations", fontsize=12)
    return figure


def _write_csv(path: Path, rows: list[dict], fallback_fields: list[str]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row)) or fallback_fields
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_force_budget(run: Path, *, output_directory: Path | None = None) -> dict:
    """Write a fresh force-budget directory; missing inputs and existing evidence fail closed.

    No old-run auto-discovery, solver call, velocity update or residual normalization.
    Caller owns terminal publication and must include these outputs in its run manifest.
    A separate analysis run may explicitly own output_directory while the source
    run remains immutable; source consumption verification belongs to that caller.
    """
    run = Path(run).resolve()
    output = Path(output_directory).resolve() if output_directory is not None else run/"results/extraction_force_budget"
    if output.exists():
        raise FileExistsError("force audit requires fresh evidence output")
    data = prepare_force_budget(run)
    output.mkdir(parents=True)
    for role in ("particles", "electrodes", "spatial", "steps", "losses", "variance_terms"):
        _write_csv(output/f"{role}.csv", data[role], ["particle_id"])
    metadata = dict(schema_version=1, role="ion_processor_extraction_force_budget", source_run=str(run),
                    source_particle_count=data["source_count"], available_particle_count=data["covariance"]["count"],
                    audit_window_start_us=data["audit_window_start_us"],
                    frame_id=data["frame_id"], source_records=data["source_records"], producer_sha256=PRODUCER_SHA256,
                    surfaces=data["surfaces"], covariance=data["covariance"], spatial_covariance=data["spatial_covariance"],
                    phase_space=data["phase_space"],
                    units=dict(velocity="m/s", position="mm", time="absolute instrument us", covariance="m2/s2"),
                    electric_conversion="charge_to_mass_c_per_kg * 1e-3 * integral[E(V/mm)*dt(us)] -> m/s",
                    electric_identity="actual=end_pre-start_post; collision=end_post-end_pre; field_residual=actual-sum15; no normalization",
                    spatial_approximation="Electric impulses and residuals split uniformly by recorded chord/time fraction across derived slab planes. Collision jumps belong to endpoint slab. No intra-step force localization claim; whole-window sums unchanged.",
                    endpoint_policy="Audit last post-HS1 callback is actual, including the terminal callback. extraction_exit is an interpolated event at a different time; its delta is reported, never forced to match.",
                    window_scope="The final accepted integrator step may extend beyond the interpolated exit plane/time. Entire raw accepted steps are audited; no claim that every final-step impulse occurred upstream of the exit plane. A zero-duration first anchor retains its actual HS1 jump; its start_post/end_pre fields both denote pre-HS1 velocity.",
                    quadrature="Signed five-node minus three-node Simpson difference is an error indicator, not a proven bound; direct reconstruction errors are node-wise max component errors.",
                    response="Unweighted basis integrals give fixed-realized-path d(delta_v)/dV only; no voltage division, trajectory feedback or counterfactual flight.",
                    statistical_scope="All source IDs retained; covariance uses all audit-available IDs (including later losses), ddof=0. No outlier removal, fitting, smoothing or rescaling.",
                    variance_growth="variance_terms.csv sums diagonal variance plus twice each unordered cross covariance; excluding initial-initial yields Var(actual_last)-Var(audit_start). Cross terms can be negative; electrode sigma alone is not a causal ranking.",
                    claim="Attribution along realized trajectories; not an independent field-integrator or counterfactual geometry qualification.")
    (output/"budget.json").write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    figure = build_force_budget_figure(data)
    for extension in ("png", "svg"):
        figure.savefig(output/f"impulse_phase_space.{extension}", format=extension, dpi=180, facecolor="white")
    figure.clear()
    return metadata
