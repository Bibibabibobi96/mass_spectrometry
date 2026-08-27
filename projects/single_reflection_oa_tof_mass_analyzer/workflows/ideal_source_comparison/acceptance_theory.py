"""Theory-first acceptance mode of the existing ideal-source public entrypoint."""

from __future__ import annotations

import csv
import itertools
import time
import traceback
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.machine_contracts import load_json
from common.contracts.particle_count_policy import validate_positive_particle_count
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_design import DesignDomainError, prepare_source_quadrature
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_experiment import (
    accepted, exact_population_moments, midpoint_population, source_at_point,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_linear_design import (
    solve_linear_third_order_design, find_fixed_length_designs,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_theory import coefficient_report
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    NumericalSourceSpec, build_numerical_source, propagate_ideal_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_experiment import _keys, _numbers
from projects.single_reflection_oa_tof_mass_analyzer.workflows.ideal_source_comparison.run_comparison import (
    PROJECT_ROOT, _prepare_run, _publish_manifest, _settings, _working_points, _write_json,
)


def validate_theory_config(config: dict[str, Any]) -> None:
    """Validate scientific choices and explicit numerical limits before writing."""
    _keys(config, "schema_version role reference_config residual_sigma_m_per_s minimum_resolution design full_widths_mm numerics sampling scope", "acceptance theory")
    if config["schema_version"] != 1 or config["role"] != "ideal_acceptance_theory":
        raise ValueError("unsupported acceptance theory schema")
    if config["reference_config"] != "config/experiments/ideal_source_comparison.json":
        raise ValueError("reference must be the canonical ideal-source comparison config")
    _numbers([config["residual_sigma_m_per_s"]], "residual")
    _numbers([config["minimum_resolution"]], "resolution", positive=True)
    design = config["design"]
    fixed_length = design.get("total_acceleration_length_mm")
    optional = " total_acceleration_length_mm" if "total_acceleration_length_mm" in design else ""
    optional += " screened_per_width" if "screened_per_width" in design else ""
    _keys(design, "field1_v_per_mm center_to_grid1_mm grid2_voltage_fraction reflectron_stage1_energy_fraction source_center_policy selection selected_per_width"+optional, "design")
    if fixed_length is not None:
        _numbers([fixed_length], "fixed acceleration length", positive=True)
    for name in ("field1_v_per_mm", "center_to_grid1_mm", "grid2_voltage_fraction", "reflectron_stage1_energy_fraction"):
        _numbers(design[name], name, positive=True)
        if len(set(design[name])) != len(design[name]):
            raise ValueError(f"duplicate controls: {name}")
    if max(design["grid2_voltage_fraction"]+design["reflectron_stage1_energy_fraction"]) >= 1:
        raise ValueError("voltage fractions must be less than one")
    if design["source_center_policy"] != "symmetric_first_field_zone" or design["selection"] != "lowest_exact_population_relative_time_variance_per_width":
        raise ValueError("unsupported theory family or candidate-selection policy")
    validate_positive_particle_count(design["selected_per_width"])
    if "screened_per_width" in design:
        validate_positive_particle_count(design["screened_per_width"])
        if design["screened_per_width"] < design["selected_per_width"]:
            raise ValueError("screened_per_width cannot be below selected_per_width")
    _numbers(config["full_widths_mm"], "widths", positive=True)
    if config["full_widths_mm"] != sorted(set(config["full_widths_mm"])):
        raise ValueError("widths must increase strictly")
    numerics = config["numerics"]
    extra = " root_xtol_v length_tolerance_mm" if fixed_length is not None else ""
    extra += " density" if "density" in numerics else ""
    _keys(numerics, "condition_limit coefficient_tolerance_ns coefficient_order position_order residual_order envelope_sigma population_orders population_resolution_relative_tolerance"+extra, "numerics")
    if fixed_length is not None:
        _numbers([numerics["root_xtol_v"], numerics["length_tolerance_mm"]], "length root tolerances", positive=True)
    for name in ("condition_limit", "coefficient_tolerance_ns", "envelope_sigma", "population_resolution_relative_tolerance"):
        _numbers([numerics[name]], name, positive=True)
    if "density" in numerics:
        density = numerics["density"]
        _keys(density, "envelope_sigma root_iterations residual_tolerance_m_per_s monotonicity_subdivisions probability_integration_tolerance", "density")
        _numbers([density["envelope_sigma"], density["residual_tolerance_m_per_s"], density["probability_integration_tolerance"]], "density tolerances", positive=True)
        for name in ("root_iterations", "monotonicity_subdivisions"):
            validate_positive_particle_count(density[name])
            if density[name] < 2:
                raise ValueError(f"density {name} must be >=2")
    for name in ("coefficient_order", "position_order", "residual_order"):
        validate_positive_particle_count(numerics[name])
        if numerics[name] < 4:
            raise ValueError(f"{name} must be >=4")
    sizes = []
    for orders in numerics["population_orders"]:
        if len(orders) != 2:
            raise ValueError("population orders require position and residual order")
        for order in orders:
            validate_positive_particle_count(order)
            if order < 2:
                raise ValueError("population order must be >=2")
        sizes.append(orders[0]*orders[1])
    if len(sizes) < 2 or sizes != sorted(set(sizes)):
        raise ValueError("at least two increasing population resolutions are required")
    _keys(config["sampling"], "particle_count replicate_count", "sampling")
    for value in config["sampling"].values():
        validate_positive_particle_count(value)
    if config["sampling"]["particle_count"] < 3 or not config["scope"]:
        raise ValueError("insufficient particles or missing scope")


def _select(config: dict[str, Any], baseline: dict[str, Any], reference: Any,
            spec: NumericalSourceSpec, result_dir: Path) -> dict[float, list[dict[str, Any]]]:
    design, num = config["design"], config["numerics"]
    widths = config["full_widths_mm"]
    quadratures = {w: prepare_source_quadrature(spec, full_width_mm=w,
        residual_sigma_m_per_s=config["residual_sigma_m_per_s"], position_order=num["position_order"],
        residual_order=num["residual_order"]) for w in widths}
    selected: dict[float, list[dict[str, Any]]] = {w: [] for w in widths}
    counts: Counter[str] = Counter()
    axes = [design[k] for k in ("field1_v_per_mm", "center_to_grid1_mm", "grid2_voltage_fraction", "reflectron_stage1_energy_fraction")]
    fixed_length = design.get("total_acceleration_length_mm")
    if fixed_length is not None:
        axes[-1] = [None]
    total = int(np.prod([len(axis) for axis in axes]))
    with (result_dir / "all_theory_equations.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["design_id", "field1_v_per_mm", "center_to_grid1_mm", "grid2_fraction", "mirror1_fraction", "status", "reason"])
        for index, (field, distance, fraction, mirror_fraction) in enumerate(itertools.product(*axes), 1):
            candidate_id = f"theory_{index:06d}"
            try:
                controls = dict(
                    field1_v_per_mm=field, center_to_grid1_mm=distance, grid2_voltage_fraction=fraction,
                    nominal_energy_per_charge_v=baseline["outer"]["nominal_energy_per_charge_v"],
                    focus_drift_mm=baseline["focus_drift_mm"], characteristic_half_width_mm=widths[0]/2,
                    condition_limit=num["condition_limit"], coefficient_tolerance_ns=num["coefficient_tolerance_ns"],
                    order=num["coefficient_order"])
                if fixed_length is None:
                    solutions = [solve_linear_third_order_design(replace(spec, center_x_mm=distance), reference.reflectron,
                        **controls, reflectron_stage1_voltage_v=mirror_fraction*baseline["outer"]["nominal_energy_per_charge_v"])]
                else:
                    solutions = find_fixed_length_designs(replace(spec, center_x_mm=distance), reference.reflectron,
                        **controls, total_accel_length_mm=fixed_length,
                        stage1_voltage_grid_v=[v*baseline["outer"]["nominal_energy_per_charge_v"] for v in design["reflectron_stage1_energy_fraction"]],
                        length_tolerance_mm=num["length_tolerance_mm"], root_xtol_v=num["root_xtol_v"])
                    if not solutions:
                        raise ValueError("NO_FIXED_LENGTH_POSITIVE_ROOT_IN_DECLARED_BRACKETS")
            except ValueError as error:
                counts[str(error)] += 1
                writer.writerow([candidate_id, field, distance, fraction, mirror_fraction, "REJECTED", str(error)])
                continue
            for branch, solution in enumerate(solutions):
                counts["positive_third_order_solution"] += 1
                root_id = candidate_id if fixed_length is None else f"{candidate_id}_r{branch+1:02d}"
                mirror_fraction = solution.point.inner.stage1_voltage_drop_v/baseline["outer"]["nominal_energy_per_charge_v"]
                writer.writerow([root_id, field, distance, fraction, mirror_fraction, "POSITIVE_SOLUTION", ""])
                for width in widths:
                    try:
                        moments = exact_population_moments(spec, solution.point, quadratures[width], envelope_sigma=num["envelope_sigma"])
                    except ValueError:
                        continue
                    entry = {"design_id": root_id, "point": solution.point, "theory": solution.report,
                             "moments": moments, "controls": {"field1_v_per_mm": field, "center_to_grid1_mm": distance,
                             "grid2_voltage_fraction": fraction, "reflectron_stage1_energy_fraction": mirror_fraction}}
                    selected[width].append(entry)
                    selected[width].sort(key=lambda item: item["moments"]["relative_variance"])
                    del selected[width][design.get("screened_per_width", design["selected_per_width"]):]
            if index % (len(axes[2])*len(axes[3])) == 0:
                print(f"ACCEPTANCE_THEORY EVENT=EQUATIONS DONE={index}/{total} POSITIVE={counts['positive_third_order_solution']}", flush=True)
    _write_json(result_dir / "equation_summary.json", {"attempts": total, "counts": dict(counts),
                "scope": "discrete theoretical control domain; rejected roots are not global impossibility proofs"})
    _write_json(result_dir / "screened_designs.json", {str(w): [{**{k:v for k,v in item.items() if k != "point"},
                "point": item["point"].to_dict()} for item in rows] for w, rows in selected.items()})
    return selected


def _confirm(config: dict[str, Any], spec: NumericalSourceSpec, point: Any, *, width: float,
             design_id: str, seed: int, result_dir: Path, include_particles: bool = True) -> dict[str, Any]:
    spec = source_at_point(spec, point)
    settings, num = _settings(), config["numerics"]
    population = []
    for nx, nv in num["population_orders"]:
        if "density" in num:
            from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_density import compute_population_density
            try:
                density_inputs = {key: value for key, value in num["density"].items()
                                  if key != "probability_integration_tolerance"}
                result = compute_population_density(spec, point, full_width_mm=width,
                    residual_sigma_m_per_s=config["residual_sigma_m_per_s"], position_order=nx,
                    grid_points=nv, **density_inputs)
            except DesignDomainError as error:
                population.append({"orders": [nx, nv], "method": "exact_population_pushforward",
                    "status": "POPULATION_DOMAIN_UNSUPPORTED", "reason": str(error),
                    "resolution_mass": None, "finite_envelope_reachable": None,
                    "event_interpretation": "method_not_certified_not_particle_loss"})
                continue
            density_path = result_dir / f"{design_id}__w{width:g}__population{nx}_{nv}.csv"
            with density_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["time_us", "density_per_us", "mass_da", "density_per_da"])
                writer.writerows(zip(result.time_grid_us, result.time_density_per_us, result.mass_grid_da, result.mass_density_per_da))
            population.append({"orders": [nx, nv], "method": "exact_population_pushforward",
                               "density_path": density_path.name, **result.summary})
        else:
            source = midpoint_population(spec, full_width_mm=width, residual_sigma_m_per_s=config["residual_sigma_m_per_s"],
                                          position_order=nx, residual_order=nv)
            result = propagate_ideal_source(source, point, settings=settings)
            population.append({"orders": [nx, nv], "method": "equal_probability_midpoint_kde", **result.summary})
    resolutions = [_population_resolution(item) for item in population]
    changes = [abs(current/previous-1) if current and previous else None
               for previous, current in zip(resolutions, resolutions[1:])]
    difference = max((value for value in changes if value is not None), default=None)
    density_probability_ok = all(abs(item.get("probability_integration_error", 0.0)) <= num["density"]["probability_integration_tolerance"]
                               for item in population if item.get("method") == "exact_population_pushforward")
    converged = difference is not None and difference <= num["population_resolution_relative_tolerance"] and density_probability_ok
    records = []
    for replicate in range(config["sampling"]["replicate_count"] if include_particles else 0):
        source = build_numerical_source(spec, particle_count=config["sampling"]["particle_count"], seed=seed+replicate,
                   full_width_mm=width, residual_sigma_m_per_s=config["residual_sigma_m_per_s"])
        result = propagate_ideal_source(source, point, settings=settings)
        records.append({"seed": seed+replicate, **result.summary})
        with (result_dir / f"{design_id}__w{width:g}__seed{seed+replicate}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["particle_id", "x_mm", "velocity_m_per_s", "classification", "tof_us"])
            for index, particle_id in enumerate(source.particle_id):
                tof = result.tof_us[index]
                writer.writerow([int(particle_id), source.source_x_mm[index], source.velocity_z_m_per_s[index],
                                 result.classification[index], float(tof) if np.isfinite(tof) else ""])
    report = {"design_id": design_id, "full_width_mm": width, "point": point.to_dict(),
              "population": population, "population_resolution_relative_change": difference,
              "population_converged": converged, "population_resolution_relative_changes": changes,
              "population_probability_integration_ok": density_probability_ok,
              "theoretical_population_pass": bool(converged and all(_population_accepted(r, config["minimum_resolution"]) for r in population[-2:])),
              "independent_particle_pass": (all(accepted(r, config["minimum_resolution"]) for r in records) if include_particles else None),
              "particle_replicates": records, "particle_confirmation_performed": include_particles,
              "uncertainty": "independent source seed range, not a confidence interval"}
    _write_json(result_dir / f"{design_id}__w{width:g}.json", report)
    print(f"ACCEPTANCE_THEORY EVENT=CONFIRMED DESIGN={design_id} WIDTH_MM={width} POPULATION_PASS={report['theoretical_population_pass']} PARTICLE_PASS={report['independent_particle_pass']}", flush=True)
    return report


def _population_resolution(item: dict[str, Any]) -> float | None:
    if item.get("method") == "exact_population_pushforward":
        return item["resolution_mass"]
    return (item.get("peak_metrics") or {}).get("mass_resolution")


def _population_accepted(item: dict[str, Any], minimum_resolution: float) -> bool:
    if item.get("method") == "exact_population_pushforward":
        return bool(item["finite_envelope_reachable"] is True and item["resolution_mass"] is not None
                    and item["resolution_mass"] >= minimum_resolution)
    return accepted(item, minimum_resolution)


def execute_theory(config_path: Path, *, seed: int, run_id: str, resume_from: Path | None,
                    artifact_root: Path) -> Path:
    config = load_json(config_path)
    validate_theory_config(config)
    if resume_from is not None:
        raise ValueError("theory redesign does not reuse selected designs from prior evidence; run a new frozen theory calculation")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    baseline_path = PROJECT_ROOT / config["reference_config"]
    baseline = load_json(baseline_path)
    names = ["ideal_acceptance_theory", "ideal_acceptance_design", "ideal_acceptance_linear_design", "ideal_acceptance_experiment"]
    if "density" in config["numerics"]:
        names.append("ideal_acceptance_density")
    run_dir, identity = _prepare_run(config_path, seed=seed, run_id=run_id, resume_from=None,
        artifact_root=artifact_root, mode="ideal_acceptance_theory", extra_inputs={"theory_workflow": Path(__file__),
        "reference_config": baseline_path, **{name: PROJECT_ROOT / "analysis" / (name+".py") for name in names}})
    started, status, error = time.perf_counter(), "success", None
    reports = []
    stage = "baseline_theory_audit"
    try:
        spec = NumericalSourceSpec(**baseline["source"])
        point = _working_points(baseline)["three_zone_matched"]
        _write_json(run_dir / "results/reference_theory.json", {"point": point.to_dict(), "widths": [
            coefficient_report(point, full_width_mm=w, residual_sigma_m_per_s=config["residual_sigma_m_per_s"],
            order=config["numerics"]["coefficient_order"], position_order=config["numerics"]["position_order"])
            for w in config["full_widths_mm"] if w < 2*min(spec.center_x_mm, point.state.zone1_length_mm-spec.center_x_mm)]})
        stage = "theory_linear_equations"
        screened = _select(config, baseline, point, spec, run_dir / "results")
        stage = "independent_confirmation"
        for width in config["full_widths_mm"]:
            if width < 2*min(spec.center_x_mm, point.state.zone1_length_mm-spec.center_x_mm):
                reports.append(_confirm(config, spec, point, width=width, design_id="original_design", seed=seed, result_dir=run_dir / "results"))
            population_screen = [_confirm(config, spec, item["point"], width=width, design_id=item["design_id"]+"__screen", seed=seed, result_dir=run_dir / "results", include_particles=False)
                                 for item in screened[width]]
            qualifying = [(item, result) for item, result in zip(screened[width], population_screen)
                          if result["theoretical_population_pass"]]
            qualifying.sort(key=lambda pair: _population_resolution(pair[1]["population"][-1]) or -np.inf, reverse=True)
            winners = qualifying[:config["design"]["selected_per_width"]]
            _write_json(run_dir / "results" / f"w{width:g}__selection.json", {
                "screened_by": config["design"]["selection"], "screened_count": len(screened[width]),
                "population_fwhm_selection": "highest direct population mass resolution among theory-pass screened candidates",
                "selected_design_ids": [item["design_id"] for item, _ in winners],
                "rejected_population_records": population_screen})
            for item, _ in winners:
                reports.append(_confirm(config, spec, item["point"], width=width, design_id=item["design_id"], seed=seed, result_dir=run_dir / "results"))
    except (Exception, KeyboardInterrupt) as exc:
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        error = f"{type(exc).__name__}: {exc}"
        (run_dir / "logs/failure.log").write_text(traceback.format_exc(), encoding="utf-8")
    new = [r for r in reports if r["design_id"] != "original_design"]
    maximum = lambda key: max((r["full_width_mm"] for r in new if r[key]), default=None)
    jointly_verified = max((r["full_width_mm"] for r in new
                            if r["theoretical_population_pass"]
                            and r["independent_particle_pass"] is True), default=None)
    summary = {"status": status, "numerical_identity": identity, "elapsed_s": time.perf_counter()-started,
               "completed_confirmations": len(reports), "failure_stage": stage if error else None, "failure_reason": error,
               "largest_verified_population_width_mm": maximum("theoretical_population_pass"),
               "largest_verified_independent_particle_width_mm": maximum("independent_particle_pass"),
               "largest_jointly_verified_width_mm": jointly_verified,
               "global_maximum_proved": False, "formal_gate_passed": False,
               "scope": config["scope"], "next_action": "inspect verified widths, rejected equations and search boundary before expanding theory family"}
    _write_json(run_dir / "summary.json", summary)
    lines = ["# Theory-first ideal-field acceptance", "", config["scope"], "", f"Execution: {status}; failure: {error}", "",
             "|Design|Width mm|Population R (last grid)|Population convergence|All particle seeds pass|Particle R range|",
             "|---|---:|---:|---|---|---|"]
    for report in reports:
        rs = [(item.get("peak_metrics") or {}).get("mass_resolution") for item in report["particle_replicates"]]
        rs = [r for r in rs if r is not None]
        pop = _population_resolution(report["population"][-1])
        lines.append(f"|{report['design_id']}|{report['full_width_mm']}|{pop}|{report['population_converged']}|{report['independent_particle_pass']}|{min(rs) if rs else None} – {max(rs) if rs else None}|")
    (run_dir / "results/report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    _publish_manifest(run_dir, status)
    print(f"ACCEPTANCE_THEORY STATUS={status} RUN={run_dir} REASON={error or 'theory and independent confirmation completed'}", flush=True)
    return run_dir
