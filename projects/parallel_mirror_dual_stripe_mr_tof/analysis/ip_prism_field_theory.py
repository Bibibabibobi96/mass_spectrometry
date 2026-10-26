"""Pre-flight linear optics and bounded ordinary-PA drift-path diagnostics.

No particle integrator: exact constant-velocity references ignore conductors.
PA central differences are project diagnostics, not SIMION's Fly force.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path

import numpy as np

from common.analysis.population_moments import population_pair_moments
from common.contracts.particle_physics import charge_to_mass_c_per_kg, kinetic_energy_ev
from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics as local
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import HEADER, read_pa_header


def linear_optics(rows: list[dict]) -> list[dict]:
    """Population slope emittance and centered ideal thin-lens decomposition.

    s increases along -z; x'=vx/(-vz), not a projected arctan angle.
    The thin-lens map x' -> x'-k(x-mean(x)) preserves this RMS emittance.
    """
    result = []
    for axis in "xy":
        x = np.array([r[f"{axis}_mm"] for r in rows], float)
        slope = np.array([r[f"v{axis}_mm_us"] / -r["vz_mm_us"] for r in rows], float)
        moments = population_pair_moments(x, slope)
        variance_x, variance_s = moments["variance_first"], moments["variance_second"]
        covariance = moments["covariance"]
        k = covariance / variance_x if variance_x else None
        waist = -covariance / variance_s if variance_s else None
        epsilon = math.sqrt(max(0., variance_x*variance_s-covariance**2)) if rows else None
        residual = math.sqrt(max(0., variance_s-covariance**2/variance_x)) if variance_x else None
        angle = np.arctan(slope)
        angle_moments = population_pair_moments(x, angle)
        angle_k = angle_moments["covariance"]/variance_x if variance_x else None
        result.append(dict(axis=axis, count=len(rows), sigma_position_mm=float(np.std(x)) if rows else None,
                           sigma_slope=float(np.std(slope)) if rows else None,
                           sigma_projected_angle_rad=float(np.std(angle)) if rows else None,
                           correlation_position_projected_angle=angle_moments["correlation"],
                           projected_angle_regression_residual_rad=math.sqrt(max(0., angle_moments["variance_second"]-angle_moments["covariance"]**2/variance_x)) if variance_x else None,
                           covariance_position_slope_mm=covariance, correlation_position_slope=moments["correlation"],
                           thin_lens_best_k_per_mm=k, residual_slope_lower_bound=residual,
                           thin_lens_angle_regression_rad_per_mm=angle_k,
                           rms_emittance_mm=epsilon, unconstrained_waist_distance_mm=waist,
                           unconstrained_waist_sigma_mm=epsilon/math.sqrt(variance_s) if variance_s else None,
                           interpretation="Centered ideal linear lens, slope coordinates; zero correlation is a waist at this lens plane. Emittance limits simultaneous spot/angular compression, not a prohibition on decorrelation. No voltage realization or cooling claim."))
    return result


def probe_pa(raw: np.ndarray, header, box_mm: list, point_mm: list) -> dict:
    """Nearest-node seven-point central stencil, including exact x reflection.

    Return explicit invalid reasons if any stencil node is outside or electrode.
    No interpolation, nearest-node potential correction or conductor crossing.
    """
    point = np.asarray(point_mm, float)
    if point.shape != (3,) or not np.isfinite(point).all():
        return dict(status="invalid", reason="nonfinite_probe_position")
    origin = np.asarray(box_mm[:3], float)
    pitch = np.array([header.dx_mm, header.dy_mm, header.dz_mm])
    dimensions = np.array([header.nx, header.ny, header.nz])
    mirrored = header.symmetry == 1 and header.raw_mirror & 7 == 1 and origin[0] == 0
    if not mirrored:
        raise ValueError("theory PA probe requires declared planar x mirror")
    if np.any(np.abs(point[:1]) > box_mm[3]) or np.any(point[1:] < origin[1:]) or np.any(point[1:] > box_mm[4:]):
        return dict(status="invalid", reason="probe_outside_pa")
    # Signed x index permits a centered stencil through the x=0 symmetry plane.
    index = np.rint((point-origin)/pitch).astype(int)
    center = origin+index*pitch
    samples = []
    for delta in ([0, 0, 0], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]):
        node = index+delta
        node[0] = abs(node[0])
        if np.any(node < 0) or np.any(node >= dimensions):
            return dict(status="invalid", reason="stencil_outside_pa")
        value = float(raw[node[2], node[1], node[0]])
        if not math.isfinite(value):
            return dict(status="invalid", reason="nonfinite_pa_stencil")
        if value > header.max_voltage:
            return dict(status="invalid", reason="electrode_in_stencil")
        samples.append(value)
    potential = samples[0]
    result = dict(status="valid", reason=None, potential_v=potential)
    for a, axis in enumerate("xyz"):
        plus, minus = samples[1+2*a:3+2*a]
        result[f"e{axis}_v_per_mm"] = -(plus-minus)/(2*pitch[a])
        result[f"d2v_d{axis}2_v_per_mm2"] = (plus-2*potential+minus)/pitch[a]**2
        result[f"node_{axis}_mm"] = float(center[a])
        result[f"node_offset_{axis}_mm"] = float(center[a]-point[a])
    result["laplacian_v_per_mm2"] = sum(result[f"d2v_d{a}2_v_per_mm2"] for a in "xyz")
    return result


def _drift_rows(states: list[dict], planes: list[dict], mass: float) -> tuple[list, list, list]:
    statistics, optics, decisions = [], [], []
    for plane in planes:
        projected = local.project_field_free_births(states, float(plane["z_mm"]))
        rows = projected["crossings"]
        base = dict(plane_name=plane["name"], z_mm=plane["z_mm"], source_count=len(states),
                    missing_ids=projected["missing_ids"], complete_source=len(rows) == len(states))
        statistics.append(dict(base, **local.compute_plane_statistics(rows, mass),
                               **{k: v for k, v in local.compute_arrival_time_energy_correlations(rows, mass).items() if k != "count"}))
        distance = float(plane["z_mm"]-planes[-1]["z_mm"])
        for row in linear_optics(rows):
            k = row["thin_lens_best_k_per_mm"]
            residual = row["residual_slope_lower_bound"]
            optics.append(dict(base, **row, target_z_mm=planes[-1]["z_mm"], target_distance_mm=distance,
                               thin_lens_target_spot_best_k_per_mm=k+1/distance if k is not None and distance > 0 else None,
                               target_spot_lower_bound_mm=distance*residual if residual is not None and distance > 0 else None))
        decisions.extend(dict(plane_name=plane["name"], **r) for r in projected["particle_decisions"])
    return statistics, optics, decisions


def plane_covariances(states: list[dict], planes: list[dict]) -> list[dict]:
    """Upper triangle of paired (t,x,y,vx,vy,vz) at exact drift crossings."""
    keys = ("t_us", "x_mm", "y_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
    result = []
    for plane in planes:
        projection = local.project_field_free_births(states, float(plane["z_mm"]))
        rows = projection["crossings"]
        for i, first in enumerate(keys):
            for second in keys[i:]:
                moments = population_pair_moments(np.array([r[first] for r in rows]), np.array([r[second] for r in rows]))
                result.append(dict(plane_name=plane["name"], z_mm=plane["z_mm"], count=len(rows),
                                   source_count=len(states), complete_source=len(rows) == len(states),
                                   first_quantity=first, second_quantity=second,
                                   covariance=moments["covariance"], correlation=moments["correlation"]))
    return result


def _field_rows(states: list[dict], planes: list[dict], header, raw, box: list, mass: float, charge: int) -> list[dict]:
    probes = []
    acceleration_factor = charge_to_mass_c_per_kg(mass, charge)*1e-6  # V/mm -> mm/us².
    for source in states:
        pid = source["particle_id"]
        birth = probe_pa(raw, header, box, [source[f"{a}_mm"] for a in "xyz"])
        energy = kinetic_energy_ev(mass, *[source[f"v{a}_mm_us"]*1000 for a in "xyz"])
        speed = math.sqrt(sum(source[f"v{a}_mm_us"]**2 for a in "xyz"))
        targets = [("birth", dict(source, propagation_time_us=0.))]
        for plane in planes:
            result = local.project_field_free_births([source], float(plane["z_mm"]))
            if result["crossings"]:
                targets.append((plane["name"], result["crossings"][0]))
            else:
                probes.append(dict(particle_id=pid, plane_name=plane["name"], z_mm=plane["z_mm"],
                                   status="invalid", reason=result["particle_decisions"][0]["reason"]))
        for name, state in targets:
            probe = probe_pa(raw, header, box, [state[f"{a}_mm"] for a in "xyz"])
            record = dict(particle_id=pid, plane_name=name, **{key: state[key] for key in local.STATE_FIELDS if key in state and key != "potential_v"},
                          birth_t_us=source["t_us"], birth_z_mm=source["z_mm"],
                          propagation_time_us=state["propagation_time_us"], birth_kinetic_energy_ev=energy,
                          birth_probe_status=birth["status"], **probe)
            if probe["status"] == "valid" and birth["status"] == "valid":
                delta = charge*(probe["potential_v"]-birth["potential_v"])
                record["delta_potential_energy_ev"] = delta
                record["abs_delta_potential_energy_over_birth_ke"] = abs(delta)/energy if energy else None
            if probe["status"] == "valid":
                kick2 = 0.
                for axis in "xyz":
                    kick = acceleration_factor*probe[f"e{axis}_v_per_mm"]*state["propagation_time_us"]
                    record[f"local_field_hold_kick_v{axis}_mm_us"] = kick
                    kick2 += kick**2
                record["local_field_hold_kick_over_birth_speed"] = math.sqrt(kick2)/speed if speed else None
                kz = kinetic_energy_ev(mass, 0., 0., source["vz_mm_us"]*1000)
                for axis in "xy":
                    slope = source[f"v{axis}_mm_us"]/-source["vz_mm_us"]
                    record[f"drift_path_d{axis}prime_ds_per_mm"] = charge*(probe[f"e{axis}_v_per_mm"]+slope*probe["ez_v_per_mm"])/(2*kz)
            probes.append(record)
    return probes


def _figure(statistics: list[dict], probes: list[dict], owners: list[dict], optics: list[dict]):
    from matplotlib import pyplot as plt

    fig, axes = plt.subplots(len(owners), 5, figsize=(21, max(3, 2.7*len(owners))), squeeze=False, layout="constrained")
    for index, owner in enumerate(owners):
        name = owner["field_case_id"]
        rows = [r for r in statistics if r["field_case_id"] == name]
        rows.sort(key=lambda r: -r["z_mm"])
        z = [-r["z_mm"] for r in rows]
        for axis, color, line, marker in zip("xy", ("#0072B2", "#D55E00"), ("-", "--"), ("o", "s")):
            axes[index, 0].plot(z, [r[f"sigma_{axis}_mm"] for r in rows], label=f"SD {axis}", color=color,
                                linestyle=line, marker=marker, markevery=max(1, len(rows)//12), markersize=3)
            lens = [r for r in optics if r["field_case_id"] == name and r["axis"] == axis and r["residual_slope_lower_bound"] is not None]
            axes[index, 1].plot([r["sigma_position_mm"] for r in lens], [r["residual_slope_lower_bound"] for r in lens], marker, ms=3, label=axis, color=color)
        axes[index, 2].plot(z, [r["time_sigma_ns"] for r in rows], color="#0072B2")
        for col, key in [(3, "abs_delta_potential_energy_over_birth_ke"), (4, "local_field_hold_kick_over_birth_speed")]:
            for plane in rows:
                values = [r[key] for r in probes if r["field_case_id"] == name and r["plane_name"] == plane["plane_name"] and r.get(key) is not None]
                if values:
                    axes[index, col].plot([-plane["z_mm"]]*len(values), values, ".", ms=2, alpha=.3, color="#0072B2")
        for ax, ylabel in zip(axes[index], ("Drift SD position (mm)", "Ideal collimated SD slope", "Drift SD arrival time (ns)", "|q delta V| / birth KE", "Local-field-hold |delta v| / birth speed")):
            ax.set(xlabel="-global z (mm)", ylabel=ylabel)
        axes[index, 1].set(xlabel="Lens-plane SD position (mm)", title="Each dot: declared lens plane")
        axes[index, 0].set_title(f"{name} | source N={owner['source_count']}", loc="left")
        if index == 0:
            axes[index, 0].legend()
            axes[index, 1].legend()
    fig.suptitle("Pre-flight theory: unconstrained straight drift, not actual trajectories\nLocal field scales can flag possible breakdown; small values do NOT prove drift validity. Hold kicks are NOT integrated deflections.", fontsize=11)
    return fig


def _lens_axis_rows(raw: np.ndarray, header, prepared: dict, planes: list[dict], step_mm: float) -> list[dict]:
    """Sample the declared nominal axis; nearest nodes are diagnostics, not Fly forces.

    Keep every requested position, including repeated nearest nodes and invalid
    stencils. The endpoint is included even when the interval is not step-aligned.
    """
    checks = prepared["geometry_checks"]
    start, stop = float(prepared["exit_z_mm"]), float(planes[-1]["z_mm"])
    y = float(checks["nominal_y_mm"])
    if not all(math.isfinite(v) for v in (start, stop, y, step_mm)) or step_mm <= 0 or stop >= start:
        raise ValueError("lens axis requires finite descending endpoints and positive probe_step_mm")
    count = int(math.floor((start-stop)/step_mm))
    z_values = start-np.arange(count+1)*step_mm
    if z_values[-1] > stop:
        z_values = np.append(z_values, stop)
    origin = np.asarray(checks["box_mm"][:3], float)
    pitch = np.array([header.dx_mm, header.dy_mm, header.dz_mm])
    rows = []
    for index, z in enumerate(z_values):
        point = np.array([0., y, float(z)])
        node = origin+np.rint((point-origin)/pitch)*pitch
        row = dict(sample_index=index)
        for axis, value, center in zip("xyz", point, node):
            row[f"requested_{axis}_mm"] = float(value)
            row[f"node_{axis}_mm"] = float(center)
            row[f"node_offset_{axis}_mm"] = float(center-value)
        row.update(probe_pa(raw, header, checks["box_mm"], point.tolist()))
        rows.append(row)
    return rows


def export_field_theory(run: Path) -> dict:
    """Export all unique declared field owners before Fly, without changing PA."""
    run = Path(run).resolve()
    resolved_path = run/"inputs/resolved_study.json"
    study = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
    owners = study["field_owners"]
    planes = study["contract"]["observation_planes"]
    if not owners or len({r["field_case_id"] for r in owners}) != len(owners):
        raise ValueError("nonempty unique field owners required")
    if not planes or len({r["name"] for r in planes}) != len(planes):
        raise ValueError("nonempty unique declared planes required")
    output = run/"results/field_theory"
    output.mkdir(parents=True, exist_ok=False)
    statistics, optics, decisions, probes, records, covariances = [], [], [], [], [], []
    lens_axis = []
    for owner in owners:
        directory = Path(owner["directory"])
        source_path, geometry_path = directory/"source_states.json", directory/"geometry.json"
        states = json.loads(source_path.read_text(encoding="utf-8-sig"))
        source_map = local._unique(states, "theory source")
        census_path = Path(owner["source_census_csv"])
        census = local._unique(local._load_rows(census_path), "theory mother census")
        if len(states) != owner["source_count"] or len(census) != owner["mother_count"] or not source_map.keys() <= census.keys():
            raise ValueError("theory source/mother identity mismatch")
        for state in states:
            if not all(math.isfinite(float(state[k])) for k in local.STATE_FIELDS if k != "potential_v") or state["vz_mm_us"] >= 0:
                raise ValueError("theory requires finite downstream source states")
        prepared = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
        path = Path(owner["field_path"])
        header = read_pa_header(path)
        checks = prepared["geometry_checks"]
        if [header.nx, header.ny, header.nz] != checks["grid_dimensions"] or [header.dx_mm, header.dy_mm, header.dz_mm] != owner["pitch_mm"]:
            raise ValueError("theory PA geometry/pitch mismatch")
        raw = np.memmap(path, dtype="<f8", mode="r", offset=HEADER.size, shape=(header.nz, header.ny, header.nx))
        try:
            s, o, d = _drift_rows(states, planes, owner["mass_u"])
            p = _field_rows(states, planes, header, raw, checks["box_mm"], owner["mass_u"], owner["charge_state"])
            axis_rows = (_lens_axis_rows(raw, header, prepared, planes,
                                        float(study["contract"]["numerics"]["probe_step_mm"]))
                         if prepared.get("geometry", {}).get("lens_electrodes") else [])
        finally:
            raw._mmap.close()
        base = dict(field_case_id=owner["field_case_id"], mother_count=len(census), source_count=len(states))
        lens_axis.extend(dict(base, **row) for row in axis_rows)
        for target, rows in ((statistics, s), (optics, o), (decisions, d), (probes, p)):
            target.extend(dict(base, **r) for r in rows)
        covariances.extend(dict(base, **r) for r in plane_covariances(states, planes))
        records.append(dict(base, source=file_record(source_path), census=file_record(census_path),
                            geometry=file_record(geometry_path), pa_path=str(path), pa_bytes=path.stat().st_size,
                            pa_header=asdict(header), full_pa_hash_performed=False,
                            upstream_not_transferred_ids=sorted(census.keys()-source_map.keys())))
        # The source decomposition is meaningful as a single lens plane only
        # when all frozen birth z coordinates are identical (times may differ).
        if len({r["z_mm"] for r in states}) == 1:
            birth_z = states[0]["z_mm"]
            distance = birth_z-planes[-1]["z_mm"]
            for row in linear_optics(states):
                k, residual = row["thin_lens_best_k_per_mm"], row["residual_slope_lower_bound"]
                optics.append(dict(base, **row, plane_name="birth_surface", z_mm=birth_z,
                                   target_z_mm=planes[-1]["z_mm"], target_distance_mm=distance,
                                   thin_lens_target_spot_best_k_per_mm=k+1/distance if k is not None and distance > 0 else None,
                                   target_spot_lower_bound_mm=distance*residual if residual is not None and distance > 0 else None))
    field_statistics = []
    for owner in owners:
        for name in ["birth", *[p["name"] for p in planes]]:
            group = [r for r in probes if r["field_case_id"] == owner["field_case_id"] and r["plane_name"] == name]
            valid = [r for r in group if r["status"] == "valid"]
            summary = dict(field_case_id=owner["field_case_id"], plane_name=name, source_count=owner["source_count"],
                           valid_count=len(valid), invalid_ids=[r["particle_id"] for r in group if r["status"] != "valid"])
            for key in ["potential_v", *[f"e{a}_v_per_mm" for a in "xyz"], *[f"d2v_d{a}2_v_per_mm2" for a in "xyz"]]:
                values = [r[key] for r in valid]
                summary[f"mean_{key}"] = float(np.mean(values)) if values else None
                summary[f"sigma_{key}"] = float(np.std(values)) if values else None
            field_statistics.append(summary)
    for name, rows in (("source_drift_moments", statistics), ("linear_optics", optics), ("drift_decisions", decisions), ("drift_path_field_probes", probes), ("field_probe_statistics", field_statistics), ("drift_covariances", covariances)):
        local._write_csv(output/f"{name}.csv", rows)
    if lens_axis:
        local._write_csv(output/"lens_axis_field_response.csv", lens_axis)
    figure = _figure(statistics, probes, owners, optics)
    from matplotlib import pyplot as plt
    for extension in ("png", "svg"):
        figure.savefig(output/f"field_theory.{extension}", dpi=160)
    plt.close(figure)
    metadata = dict(schema_version=1, role="ip_prism_preflight_field_theory", resolved=file_record(resolved_path),
                    generator=file_record(Path(__file__)), fields=records, observation_planes=planes,
                    covariance_units="Population covariance in the product of the named quantity units: t_us, x_mm, y_mm, vx/vy/vz_mm_us. Upper triangle, paired identical IDs at each reference plane; missing-ID lists live in drift_decisions and source_drift_moments.",
                    stencil="Nearest signed physical grid node; seven-point axis central differences, actual anisotropic pitch; x mirror restored. Reject entire stencil containing electrode/outside/nonfinite values. A valid stencil does not prove the non-node probe position or intervening path is vacuum. No fractional-boundary interpolation or vendor force claim.",
                    scope="Exact individual birth clocks and 6D states, population moments without tail removal. Surface ensembles are not simultaneous cloud snapshots. Whole declared source and mother mapping retained; incomplete-plane moments describe available mathematical crossings only. Zero-field references ignore all electrodes and terminal survival. Actual PA sampled only along these straight reference paths; no trajectory integration or actual focus prediction.",
                    kick_definition="a_local=q/m E_node, delta_v_hold=a_local*(t_reference-t_birth). Endpoint local field held over elapsed time: a local scale that may flag breakdown, not an integral, bound or predicted real deflection. Small endpoint values cannot establish constant-velocity validity because intervening fields may be strong. Curvature is diagonal potential Hessian; no mixed derivatives or full focusing matrix.",
                    lens_tradeoff="Ideal centered slope lens xprime_new=xprime-k*(x-mean_x), k_col=Cov(x,xprime)/Var(x). Emittance preserved; residual spread=epsilon/sigma_x. Decorrelation places a waist at this lens plane. For the final declared downstream surface at distance L>0, k_spot=1/L+k_col minimizes spot to L*epsilon/sigma_x; not generally a waist at that surface. No voltage feasibility claim. All declared planes have their own k/lower bounds; source residual is not a general lens limit. arctan regression reported separately, not used as exact ray slope.",
                    voltage_sensitivity_limit="One ordinary PA at one voltage working point cannot identify individual-electrode dE/dV. Probes begin at the transferred source surface and cannot predict how changing upstream LP auxiliary voltages changes extraction states; that requires an upstream controlled fast-adjust case and newly generated source states.",
                    minimal_validation="Compare same-ID actual crossings to straight reference at existing declared planes; local field/curvature scales identify regions requiring this comparison, not confirmed trajectory error. Then compare unchanged-source mesh and time-step pairs. A physical lens voltage test requires a new frozen controlled native case, not interpretation of the ideal lens map.",
                    files=[file_record(p) for p in sorted(output.iterdir())])
    if lens_axis:
        metadata["lens_axis_sampling"] = dict(
            file="lens_axis_field_response.csv", sample_count=len(lens_axis),
            probe_step_mm=study["contract"]["numerics"]["probe_step_mm"],
            coordinates="Requested x=0, y=geometry_checks.nominal_y_mm; descending z from exit_z_mm to last declared observation plane, inclusive. Repeated nearest nodes retained.",
            units="Positions mm; potential V; E=-grad(V) V/mm; diagonal potential Hessian and Laplacian V/mm^2.",
            scope="Actual working-point PA only, seven-point nearest-node diagnostic, not vendor trajectory force or an integrated transfer matrix. Invalid stencils retained without physics values. A single PA is not an individual-lens unit-voltage response or dE/dV; compare explicitly bound same-geometry zero/unit-voltage fields separately.")
    (output/"metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return metadata
