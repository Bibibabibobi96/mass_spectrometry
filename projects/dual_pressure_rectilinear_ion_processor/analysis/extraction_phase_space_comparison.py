"""Compare a registered LP-length/lift-voltage factorial using recorded states.

Called by a manifest-bound analysis run; this module never launches a solver. Trapped
states are diagnosed with x-vx and energy, not a beam angle with near-zero vz.
"""
from __future__ import annotations

import csv
import copy
import json
import math
from pathlib import Path
import subprocess

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import numpy as np

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import derive_numerical_boundaries
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection

PROJECT = "dual_pressure_rectilinear_ion_processor"
VALUES = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
COLORS = ("#0072B2", "#E69F00", "#009E73", "#D55E00")
MARKERS = ("o", "s", "^", "D")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _table(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError(f"empty or malformed table: {path}")
    return rows


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_recorded_case(run: Path, label: str, *, include_samples: bool = False,
                       allow_failed: bool = False) -> dict:
    """Verify only consumed immutable records, keeping raw loss evidence upstream."""
    run = Path(run).resolve()
    require_completed_terminal_publication(run / "run_manifest.json")
    manifest = _json(run / "run_manifest.json")
    allowed_status = {"success", "failed"} if allow_failed else {"success"}
    if manifest.get("status") not in allowed_status or manifest.get("project") != PROJECT or manifest.get("run_id") != run.name:
        raise ValueError("source run identity or status differs")
    records = {}
    for record in [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]:
        path = record_path(record, base_dir=run)
        if run not in path.parents:
            continue
        relative = path.relative_to(run).as_posix()
        if relative in records and any(records[relative][k] != record[k] for k in ("sha256", "bytes")):
            raise ValueError("conflicting consumed record")
        records[relative] = record
    consumed = ("inputs/resolved_model.json", "inputs/diagnostics.json", "simion/events.csv",
                "results/diagnostic_snapshots.csv", "results/diagnostic_losses.csv")
    if include_samples:
        consumed += ("simion/samples.csv",)
    if manifest["status"] == "failed":
        consumed += ("summary.json",)
    for name in consumed:
        if name not in records:
            raise ValueError(f"consumed record not manifest-bound: {name}")
        verify_record(name, records[name], base_dir=run)
    config = _json(run / consumed[0])
    if manifest["status"] == "failed":
        summary = _json(run / "summary.json")
        if summary.get("role") != "ion_processor_functional_summary":
            raise ValueError("failed source lacks a measured physical summary")
    if "coordinate_transform" not in config:
        raise ValueError("comparison requires declared project XYZ frame")
    events = _table(run / "simion/events.csv")
    sources, exits, terminals = {}, {}, {}
    for row in events:
        target = {"source": sources, "extraction_exit": exits, "terminal": terminals}.get(row["event"])
        if target is None:
            continue
        particle = int(row["particle_id"])
        if particle in target:
            raise ValueError("duplicate source/exit/terminal identity")
        target[particle] = row
    if not sources or set(terminals) != set(sources) or not set(exits) <= set(sources):
        raise ValueError("source/terminal/exit census differs")
    if len(sources) != config["source"]["particle_count"]:
        raise ValueError("source census differs from frozen particle count")
    snapshots = _table(run / "results/diagnostic_snapshots.csv")
    stages = [item["label"] for item in _json(run / "inputs/diagnostics.json")["snapshots"] if item["label"] != "source"]
    states = []
    exit_census = [*exits.values(), *[dict(row, status="lost") for pid,row in terminals.items() if pid not in exits]]
    for stage, rows in [("birth", sources.values()), *[(s, [r for r in snapshots if r["snapshot"] == s]) for s in stages], ("exit_z0", exit_census)]:
        seen = set()
        for raw in rows:
            particle = int(raw["particle_id"])
            if particle in seen or particle not in sources:
                raise ValueError("stage identity differs")
            seen.add(particle)
            status = raw.get("status", "extracted" if stage == "exit_z0" else "alive")
            finite = {k: float(raw[k]) if raw[k] not in ("", None) else None for k in ("t_us", *VALUES)}
            if any(v is not None and not math.isfinite(v) for v in finite.values()):
                raise ValueError("nonfinite recorded state")
            if status in {"alive", "extracted"} and any(v is None for v in finite.values()):
                raise ValueError("live state lacks coordinates")
            row = dict(case=label, stage=stage, particle_id=particle, status=status,
                       reason=raw.get("reason", "none"), **finite)
            row["Ex_eV"] = kinetic_energy_ev(config["source"]["species"]["mass_amu"], finite["vx_mm_us"] * 1000, 0, 0) if finite["vx_mm_us"] is not None else None
            row["Ez_eV"] = kinetic_energy_ev(config["source"]["species"]["mass_amu"], 0, 0, finite["vz_mm_us"] * 1000) if finite["vz_mm_us"] is not None else None
            row["total_energy_eV"] = kinetic_energy_ev(config["source"]["species"]["mass_amu"], *(finite[f"v{axis}_mm_us"]*1000 for axis in "xyz")) if all(finite[f"v{axis}_mm_us"] is not None for axis in "xyz") else None
            for axis in "xy":
                # A directed beam angle is reported only after the actual pulse,
                # before termination, with velocity along the extraction direction.
                directed = status == ("extracted" if stage == "exit_z0" else "alive") and finite["t_us"] >= config["native_timing"]["pulse_start_us"] and finite["vz_mm_us"] is not None and finite["vz_mm_us"] < 0
                row[f"theta_{axis}_deg"] = math.degrees(math.atan2(finite[f"v{axis}_mm_us"], abs(finite["vz_mm_us"]))) if directed else None
            states.append(row)
        if seen != set(sources):
            raise ValueError(f"stage census lacks full source identity: {stage}")
    geometry = config["baseline"]["geometry"]
    return dict(label=label, run=str(run), config=config, states=states, stages=["birth", *stages, "exit_z0"],
                sources=sources, exits=exits, terminals=terminals,
                lp_length_mm=geometry["lp_length_mm"], lift_v=config["baseline"]["electric"]["lift_v"],
                source_records=[dict(record, path=str(run / name)) for name, record in records.items() if name in consumed])


def validate_controlled_cases(cases: list[dict], contract: dict) -> None:
    """Reject undeclared scientific/numerical changes before comparing responses."""
    invariant = None
    cells = set()
    for case in cases:
        config = case["config"]
        a, b = case["lp_length_mm"], case["lift_v"]
        if a not in contract["factor_A"]["levels"] or b not in contract["factor_B"]["levels"]:
            raise ValueError("actual factor value is outside registered levels")
        if config["native_operating_point"]["lift_v"] != b:
            raise ValueError("lift authority/projection mismatch")
        if len(case["sources"]) != contract["execution"]["particle_count"]:
            raise ValueError("source count differs from registered cohort")
        if case["stages"] != contract["stages"]:
            raise ValueError("observation stages differ from registered stages")
        if (a,b) in cells:
            raise ValueError("duplicate factorial cell")
        cells.add((a,b))
        if config["native_projection"] != native_projection(config["baseline"], config["numerics"]):
            raise ValueError("native projection differs from authority compilation")
        if config["numerical_boundaries"] != derive_numerical_boundaries(config["native_projection"]):
            raise ValueError("numerical boundaries differ from native geometry derivation")
        normalized = copy.deepcopy({key:config[key] for key in ("baseline", "native_operating_point", "source", "numerics", "coordinate_transform", "native_timing", "diagnostics", "field_diagnostics", "acceptance", "source_profile")})
        del normalized["baseline"]["geometry"]["lp_length_mm"]
        del normalized["baseline"]["electric"]["lift_v"]
        del normalized["native_operating_point"]["lift_v"]
        if invariant is not None and normalized != invariant:
            raise ValueError("undeclared scientific or numerical configuration change")
        invariant = normalized
    expected = {(a,b) for a in contract["factor_A"]["levels"] for b in contract["factor_B"]["levels"]}
    if cells != expected:
        raise ValueError("registered factorial cells are incomplete")


def prepare_statistics(cases: list[dict], *, allow_empty_common: bool = False) -> tuple[list[dict], list[dict], list[int]]:
    """Return full-census and conditional widths, plus same-ID interval budgets."""
    common = set.intersection(*(set(case["exits"]) for case in cases))
    if not common and not allow_empty_common:
        raise ValueError("no common extracted IDs")
    statistics, intervals = [], []
    for case in cases:
        for cohort, ids in (("all_available_alive", set(case["sources"])), ("own_extracted_ids", set(case["exits"])), ("common_extracted_ids", common)):
            previous = None
            for stage in case["stages"]:
                all_rows = [r for r in case["states"] if r["stage"] == stage and r["particle_id"] in ids]
                alive = [r for r in all_rows if r["status"] == ("extracted" if stage == "exit_z0" else "alive")]
                base = dict(case=case["label"], cohort=cohort, stage=stage, source_count=len(case["sources"]), cohort_count=len(ids), observed_count=len(alive),
                            lp_length_mm=case["lp_length_mm"], lift_v=case["lift_v"])
                for status in ("alive", "extracted", "lost", "notborn", "unknown"):
                    base[status + "_count"] = sum(r["status"] == status for r in all_rows)
                x = np.array([r["x_mm"] for r in alive]); vx = np.array([r["vx_mm_us"] * 1000 for r in alive])
                covariance = float(np.mean((x-x.mean()) * (vx-vx.mean()))) if len(x) else None
                base.update(sigma_x_mm=float(x.std()) if len(x) else None, sigma_vx_m_s=float(vx.std()) if len(x) else None,
                            mean_Ex_eV=float(np.mean([r["Ex_eV"] for r in alive])) if len(x) else None,
                            cov_x_vx_mm_m_s=covariance,
                            mean_total_energy_eV=float(np.mean([r["total_energy_eV"] for r in alive])) if len(x) else None,
                            sigma_Ez_eV=float(np.std([r["Ez_eV"] for r in alive])) if len(x) else None,
                            rms_emittance_x_vx_mm_m_s=math.sqrt(max(0, float(x.var()*vx.var()-covariance**2))) if len(x) else None)
                base["r_x_vx"] = covariance/float(x.std()*vx.std()) if len(x) and x.std()>0 and vx.std()>0 else None
                for axis in "xy":
                    angles = [r[f"theta_{axis}_deg"] for r in alive if r[f"theta_{axis}_deg"] is not None]
                    base[f"angle_{axis}_count"] = len(angles)
                    base[f"sigma_theta_{axis}_deg"] = float(np.std(angles)) if angles else None
                directed = [r for r in alive if r["theta_x_deg"] is not None]
                angle_x = np.array([r["x_mm"] for r in directed])
                angle = np.array([math.radians(r["theta_x_deg"])*1000 for r in directed])
                angle_cov = float(np.mean((angle_x-angle_x.mean())*(angle-angle.mean()))) if directed else None
                base.update(cov_x_theta_x_mm_mrad=angle_cov,
                            r_x_theta_x=angle_cov/float(angle_x.std()*angle.std()) if directed and angle_x.std()>0 and angle.std()>0 else None,
                            rms_emittance_x_theta_mm_mrad=math.sqrt(max(0,float(angle_x.var()*angle.var()-angle_cov**2))) if directed else None)
                statistics.append(base)
                current = {r["particle_id"]: r for r in alive}
                if previous is not None:
                    before_stage, before = previous
                    shared = sorted(set(before) & set(current))
                    a = np.array([before[p]["vx_mm_us"] * 1000 for p in shared]); b = np.array([current[p]["vx_mm_us"] * 1000 for p in shared]); delta = b-a
                    if shared:
                        cross = float(2 * np.mean((a-a.mean())*(delta-delta.mean())))
                        intervals.append(dict(case=case["label"], cohort=cohort, from_stage=before_stage, to_stage=stage, count=len(shared),
                                              sigma_vx_before_m_s=float(a.std()), sigma_vx_after_m_s=float(b.std()),
                                              variance_change_m2_s2=float(b.var()-a.var()), twice_cov_before_delta_m2_s2=cross,
                                              variance_delta_m2_s2=float(delta.var()), mean_delta_vx_m_s=float(delta.mean()),
                                              variance_identity_residual_m2_s2=float(b.var()-a.var()-cross-delta.var())))
                previous = (stage, current)
    return statistics, intervals, sorted(common)


def factorial_effects(statistics: list[dict], cases: list[dict]) -> list[dict]:
    """Equal-weight short-minus-long/high-minus-low effects and difference-in-differences."""
    lengths = sorted({c["lp_length_mm"] for c in cases}, reverse=True)
    lifts = sorted({c["lift_v"] for c in cases})
    cells = {(c["lp_length_mm"], c["lift_v"]): c["label"] for c in cases}
    if len(cases) != 4 or len(cells) != 4 or len(lengths) != 2 or len(lifts) != 2:
        raise ValueError("comparison requires a complete two-by-two factorial")
    result = []
    metrics = ("sigma_x_mm", "sigma_vx_m_s", "mean_Ex_eV", "cov_x_vx_mm_m_s", "rms_emittance_x_vx_mm_m_s", "sigma_theta_x_deg", "sigma_theta_y_deg", "mean_total_energy_eV", "sigma_Ez_eV", "cov_x_theta_x_mm_mrad", "r_x_theta_x", "rms_emittance_x_theta_mm_mrad")
    for cohort in ("all_available_alive", "own_extracted_ids", "common_extracted_ids"):
        for stage in cases[0]["stages"]:
            rows = {r["case"]: r for r in statistics if r["stage"] == stage and r["cohort"] == cohort}
            for metric in metrics:
                values = [rows[cells[(a,b)]][metric] for a in lengths for b in lifts]
                if any(v is None for v in values):
                    continue
                ll, lh, sl, sh = values
                result.append(dict(cohort=cohort, stage=stage, metric=metric, long_low=ll, long_high=lh, short_low=sl, short_high=sh,
                                   length_main_effect=((sl-ll)+(sh-lh))/2, lift_main_effect=((lh-ll)+(sh-sl))/2,
                                   length_at_low=sl-ll, length_at_high=sh-lh, lift_at_long=lh-ll, lift_at_short=sh-sl,
                                   interaction=(sh-lh)-(sl-ll)))
    return result


def prepare_velocity_changes(cases: list[dict], common: list[int]) -> tuple[list[dict], list[dict], list[dict]]:
    """Retain same-ion stage kicks, pre-to-exit variance identity and correlations."""
    changes, decompositions, correlations = [], [], []
    for case in cases:
        by_stage = {stage:{r["particle_id"]:r for r in case["states"] if r["stage"] == stage and r["status"] == ("extracted" if stage == "exit_z0" else "alive")} for stage in case["stages"]}
        for before_stage, after_stage in zip(case["stages"], case["stages"][1:]):
            before, after = by_stage[before_stage], by_stage[after_stage]
            for pid in sorted(set(before) & set(after)):
                changes.append(dict(case=case["label"], particle_id=pid, from_stage=before_stage, to_stage=after_stage,
                                    own_extracted_id=pid in case["exits"], common_extracted_id=pid in common,
                                    vx_before_m_s=before[pid]["vx_mm_us"]*1000, vx_after_m_s=after[pid]["vx_mm_us"]*1000,
                                    delta_vx_m_s=(after[pid]["vx_mm_us"]-before[pid]["vx_mm_us"])*1000))
        before, after = by_stage["pre_extraction"], by_stage["exit_z0"]
        for cohort, ids in (("own_extracted_ids", sorted(set(case["exits"]) & set(before))), ("common_extracted_ids", sorted(set(common) & set(before)))):
            if not ids:
                continue
            pre = np.array([before[p]["vx_mm_us"]*1000 for p in ids]); final = np.array([after[p]["vx_mm_us"]*1000 for p in ids]); delta = final-pre
            cross = float(2*np.mean((pre-pre.mean())*(delta-delta.mean())))
            decompositions.append(dict(case=case["label"], cohort=cohort, count=len(ids), variance_pre_m2_s2=float(pre.var()), variance_exit_m2_s2=float(final.var()),
                                       variance_delta_m2_s2=float(delta.var()), twice_cov_pre_delta_m2_s2=cross,
                                       residual_m2_s2=float(final.var()-pre.var()-delta.var()-cross)))
            theta = np.array([after[p]["theta_x_deg"] for p in ids])
            for field in ("x_mm", "vx_mm_us", "z_mm", "vz_mm_us"):
                values = np.array([before[p][field] for p in ids])
                correlation = float(np.corrcoef(values, theta)[0,1]) if len(ids)>1 and values.std()>0 and theta.std()>0 else None
                correlations.append(dict(case=case["label"], cohort=cohort, count=len(ids), upstream_stage="pre_extraction", upstream_field=field,
                                         downstream_stage="exit_z0", downstream_field="theta_x_deg", pearson_r=correlation))
    return changes, decompositions, correlations


def prepare_spatial_crossings(case: dict, planes: list[float]) -> list[dict]:
    """First bounded -z crossings after pulse, without extrapolating terminal states."""
    if not planes or len(set(planes)) != len(planes) or any(not math.isfinite(z) or z < 0 for z in planes) or planes != sorted(planes, reverse=True):
        raise ValueError("spatial planes must be unique finite nonnegative descending z")
    config = case["config"]
    pulse = config["native_timing"]["pulse_start_us"]
    limit = config["diagnostics"]["max_extraction_bracket_us"]
    mass = config["source"]["species"]["mass_amu"]
    previous, crossed = {}, {}
    path = Path(case["run"]) / "simion/samples.csv"
    if not any(Path(record["path"]).resolve() == path.resolve() for record in case["source_records"]):
        raise ValueError("spatial sample table is not a verified consumed record")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"particle_id", "t_us", *VALUES} <= set(reader.fieldnames or []):
            raise ValueError("spatial sample columns missing")
        for line, raw in enumerate(reader, start=2):
            t = float(raw["t_us"])
            if t < pulse:
                continue
            pid = int(raw["particle_id"])
            if pid not in case["sources"]:
                raise ValueError("spatial sample contains unknown particle")
            current = dict(t_us=t, **{key:float(raw[key]) for key in VALUES}, line=line)
            if any(not math.isfinite(current[key]) for key in ("t_us", *VALUES)):
                raise ValueError("nonfinite spatial sample")
            before = previous.get(pid)
            previous[pid] = current
            if before is None:
                continue
            gap = t-before["t_us"]
            if gap <= 0:
                raise ValueError("spatial sample time not increasing for particle")
            if gap > limit+1e-12 or before["vz_mm_us"] >= 0 or current["vz_mm_us"] >= 0:
                continue
            for z in planes:
                if z == 0 or (pid,z) in crossed or not before["z_mm"] >= z >= current["z_mm"] or before["z_mm"] == current["z_mm"]:
                    continue
                alpha = (z-before["z_mm"])/(current["z_mm"]-before["z_mm"])
                state = {key:before[key]+alpha*(current[key]-before[key]) for key in ("t_us", *VALUES)}
                state["z_mm"] = z
                crossed[pid,z] = dict(**state, bracket_start_us=before["t_us"], bracket_end_us=t, bracket_gap_us=gap,
                                      lower_sample_line=before["line"], upper_sample_line=line, interpolation_alpha=alpha, method="bounded_linear_sample_crossing")
    for pid, raw in case["exits"].items():
        state = {key:float(raw[key]) for key in ("t_us", *VALUES)}
        if any(not math.isfinite(value) for value in state.values()) or state["t_us"] < pulse or state["vz_mm_us"] >= 0 or abs(state["z_mm"]) > 1e-10:
            raise ValueError("recorded exit violates spatial crossing contract")
        before = previous.get(pid)
        # The actual exit is a measured upper anchor when sampling stops at z>0.
        # Preserve the same temporal bound; never extrapolate or invent a CSV line.
        if before is not None:
            gap = state["t_us"]-before["t_us"]
            if 0 < gap <= limit+1e-12 and before["vz_mm_us"] < 0 and before["z_mm"] > 0:
                for z in planes:
                    if z == 0 or (pid,z) in crossed or not before["z_mm"] >= z > 0:
                        continue
                    alpha = (z-before["z_mm"])/(state["z_mm"]-before["z_mm"])
                    interpolated = {key:before[key]+alpha*(state[key]-before[key]) for key in ("t_us", *VALUES)}
                    interpolated["z_mm"] = z
                    crossed[pid,z] = dict(**interpolated, bracket_start_us=before["t_us"], bracket_end_us=state["t_us"], bracket_gap_us=gap,
                                          lower_sample_line=before["line"], upper_sample_line=None, interpolation_alpha=alpha,
                                          method="bounded_sample_to_exit_event_crossing")
        if 0 in planes:
            crossed[pid,0] = dict(**state, bracket_start_us=None, bracket_end_us=None, bracket_gap_us=None,
                                  lower_sample_line=None, upper_sample_line=None, interpolation_alpha=None, method="recorded_extraction_exit_event")
    rows = []
    for z in planes:
        for pid in sorted(case["sources"]):
            state = crossed.get((pid,z))
            row = dict(case=case["label"], stage=f"z_{z:g}_mm", plane_z_mm=z, particle_id=pid, status="alive" if state else "unknown",
                       reason="first_negative_z_crossing" if state else "no_valid_recorded_crossing", terminal_reason=case["terminals"][pid]["reason"])
            columns = ("t_us", *VALUES, "bracket_start_us", "bracket_end_us", "bracket_gap_us", "lower_sample_line", "upper_sample_line", "interpolation_alpha", "method")
            row.update({key:state[key] if state else None for key in columns})
            row["time_after_pulse_us"] = state["t_us"]-pulse if state else None
            row["Ex_eV"] = kinetic_energy_ev(mass,state["vx_mm_us"]*1000,0,0) if state else None
            row["Ez_eV"] = kinetic_energy_ev(mass,0,0,state["vz_mm_us"]*1000) if state else None
            row["total_energy_eV"] = kinetic_energy_ev(mass,*(state[f"v{axis}_mm_us"]*1000 for axis in "xyz")) if state else None
            for axis in "xy":
                row[f"theta_{axis}_deg"] = math.degrees(math.atan2(state[f"v{axis}_mm_us"],abs(state["vz_mm_us"]))) if state else None
            rows.append(row)
    return rows


def build_spatial_figures(cases: list[dict], statistics: list[dict], planes: list[float]) -> dict:
    """Render transverse dynamics along actual observation planes, preserving tails."""
    common_count = next(r["cohort_count"] for r in statistics if r["cohort"] == "common_extracted_ids")
    fig, axes = plt.subplots(3,2,figsize=(12,11), constrained_layout=True)
    for ax,(metric,label) in zip(axes.flat,(("sigma_vx_m_s","SD vx (m/s)"),("mean_Ex_eV","Mean Ex (eV)"),("cov_x_vx_mm_m_s","Covariance x,vx (mm m/s)"),("sigma_x_mm","SD x (mm)"),
                                          ("observed_count",f"Valid crossings (of common N={common_count})"),("r_x_vx","Pearson r(x,vx) (dimensionless)"))):
        for index,case in enumerate(cases):
            rows = [r for r in statistics if r["case"] == case["label"] and r["cohort"] == "common_extracted_ids"]
            ax.plot(planes,[r[metric] for r in rows],color=COLORS[index],marker=MARKERS[index],label=case["label"],linewidth=1)
        ax.set(xlabel="Observation plane z (mm); flight toward decreasing z",ylabel=label)
        ax.invert_xaxis()
        ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=8)
    fig.suptitle("Extraction dynamics | First -z crossings after actual pulse; common extracted IDs")
    figures = {"extraction_control__spatial_widths":fig}
    all_rows = [r for case in cases for r in case["states"] if r["status"] == "alive"]
    bounds = {}
    for key,scale in (("x_mm",1),("vx_mm_us",1000)):
        values = [r[key]*scale for r in all_rows]
        if values:
            lo,hi=min(values),max(values)
            pad = (hi-lo)*.05 if hi>lo else max(abs(lo)*.05,1.)
            bounds[key] = (lo-pad,hi+pad)
    for index,case in enumerate(cases):
        fig,axes = plt.subplots(math.ceil(len(planes)/4),4,figsize=(15,10),sharex=True,sharey=True,constrained_layout=True)
        for ax,z in zip(axes.flat,planes):
            rows = [r for r in case["states"] if r["plane_z_mm"] == z and r["status"] == "alive"]
            ax.scatter([r["x_mm"] for r in rows],[r["vx_mm_us"]*1000 for r in rows],s=12,color=COLORS[index],marker=MARKERS[index])
            ax.set(xlabel="x (mm)",ylabel="vx (m/s)",title=f"z={z:g} mm | N={len(rows)}/{len(case['sources'])}")
            if bounds:
                ax.set(xlim=bounds["x_mm"],ylim=bounds["vx_mm_us"])
        for ax in list(axes.flat)[len(planes):]:
            ax.set_visible(False)
        fig.suptitle(f"{case['label']} | Extraction x-vx; all valid crossings, common panel scales")
        figures[f"extraction_control__spatial_phase_space_{index:02d}"] = fig
    return figures


def build_comparison_figures(cases: list[dict], statistics: list[dict]) -> dict:
    """Render full-range common-cohort panels with shared comparison scales."""
    figures = {}
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    metrics = (("sigma_vx_m_s", "SD vx (m/s)"), ("mean_Ex_eV", "Mean Ex (eV)"), ("sigma_x_mm", "SD x (mm)"),
               ("rms_emittance_x_vx_mm_m_s", "RMS emittance x-vx (mm m/s)"), ("sigma_theta_x_deg", "SD theta x, directed states only (deg)"), ("rms_emittance_x_theta_mm_mrad", "RMS emittance x-theta (mm mrad)"))
    for ax, (metric, ylabel) in zip(axes.flat, metrics):
        for index, case in enumerate(cases):
            rows = [r for r in statistics if r["case"] == case["label"] and r["cohort"] == "common_extracted_ids"]
            ax.plot(range(len(rows)), [r[metric] for r in rows], color=COLORS[index], marker=MARKERS[index], label=case["label"], linewidth=1)
        ax.set(ylabel=ylabel, xticks=range(len(cases[0]["stages"])), xticklabels=cases[0]["stages"])
        ax.tick_params(axis="x", rotation=65)
        ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=8)
    fig.suptitle("Stage evolution | Common extracted IDs tracked backward; population SD")
    figures["extraction_control__stage_widths"] = fig
    fig, axes = plt.subplots(4, 3, figsize=(12, 12), sharex="col", sharey="col", constrained_layout=True)
    for index, case in enumerate(cases):
        rows = [r for r in case["states"] if r["stage"] == "exit_z0" and r["status"] == "extracted"]
        for column, (horizontal, vertical, xlabel, ylabel) in enumerate((("x_mm", "vx_mm_us", "x (mm)", "vx (m/s)"), ("x_mm", "theta_x_deg", "x (mm)", "Theta x, xz plane (deg)"), ("y_mm", "theta_y_deg", "y (mm)", "Theta y, yz plane (deg)"))):
            ax = axes[index,column]
            ax.scatter([r[horizontal] for r in rows], [r[vertical] * (1000 if vertical == "vx_mm_us" else 1) for r in rows], color=COLORS[index], marker=MARKERS[index], s=13, alpha=.8)
            ax.set(xlabel=xlabel, ylabel=ylabel, title=f"{case['label']} | N={len(rows)}/{len(case['sources'])}")
    fig.suptitle("Exit phase space | Each ion at its own z=0 crossing, vz<0")
    figures["extraction_control__exit_phase_space"] = fig
    # The original design is defined by the long/low factor cell, never by run name.
    original = min(cases, key=lambda c: (-c["lp_length_mm"], c["lift_v"]))
    stages = [s for s in original["stages"] if s not in {"capture_mid", "transfer_mid", "lift_mid", "extraction_100"}]
    fig, axes = plt.subplots(2, math.ceil(len(stages)/2), figsize=(15, 7), sharex=True, sharey=True, constrained_layout=True)
    ids = set(original["exits"])
    for ax, stage in zip(axes.flat, stages):
        rows = [r for r in original["states"] if r["stage"] == stage and r["particle_id"] in ids and r["status"] == ("extracted" if stage == "exit_z0" else "alive")]
        ax.scatter([r["x_mm"] for r in rows], [r["vx_mm_us"]*1000 for r in rows], s=13, color=COLORS[0])
        ax.set(xlabel="x (mm)", ylabel="vx (m/s)", title=f"{stage} | available N={len(rows)}/{len(ids)}")
    for ax in list(axes.flat)[len(stages):]:
        ax.set_visible(False)
    fig.suptitle("Original design | Own extracted IDs tracked backward; common phase-space scale")
    figures["extraction_control__original_stage_phase_space"] = fig
    return figures


def export_comparison(run_mapping: dict[str, Path], output_directory: Path, study_contract: dict) -> dict:
    """Publish diagnostics into a new parent analysis run's results directory."""
    if study_contract.get("schema_version") != 1 or study_contract.get("role") != "ion_processor_extraction_control_study":
        raise ValueError("unsupported extraction study contract")
    out = Path(output_directory)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise FileExistsError("fresh comparison output directory required")
    planes = study_contract["analysis"].get("extraction_planes_z_mm")
    cases = [load_recorded_case(Path(run), label, include_samples=planes is not None) for label, run in run_mapping.items()]
    registered = {cell["run_id"]: cell for cell in study_contract["cells"]}
    for case in cases:
        cell = registered.get(Path(case["run"]).name)
        if cell is None or (cell["lp_length_mm"], cell["lift_v"]) != (case["lp_length_mm"], case["lift_v"]):
            raise ValueError("actual source factors differ from registered cell")
    cases.sort(key=lambda c: (-c["lp_length_mm"], c["lift_v"]))
    validate_controlled_cases(cases, study_contract)
    if len({tuple(c["stages"]) for c in cases}) != 1 or len({tuple(sorted(c["sources"])) for c in cases}) != 1:
        raise ValueError("stage/source identities differ across factorial cells")
    # Birth state equality is stronger than a shared seed or a shared source name.
    baseline_birth = {r["particle_id"]: r for r in cases[0]["states"] if r["stage"] == "birth"}
    for case in cases[1:]:
        for row in (r for r in case["states"] if r["stage"] == "birth"):
            if any(row[k] != baseline_birth[row["particle_id"]][k] for k in ("t_us", *VALUES)):
                raise ValueError("factorial cells do not share actual birth states")
    stats, intervals, common = prepare_statistics(cases)
    effects = factorial_effects(stats, cases)
    changes, decompositions, correlations = prepare_velocity_changes(cases, common)
    particles = [r for case in cases for r in case["states"]]
    _write_csv(out / "stage_particles.csv", particles)
    _write_csv(out / "stage_statistics.csv", stats)
    _write_csv(out / "stage_variance_budget.csv", intervals)
    _write_csv(out / "factorial_effects.csv", effects)
    _write_csv(out / "stage_particle_velocity_changes.csv", changes)
    _write_csv(out / "pre_exit_velocity_variance_decomposition.csv", decompositions)
    _write_csv(out / "pre_exit_angle_correlations.csv", correlations)
    baseline = {(r["stage"], r["particle_id"]): r for r in cases[0]["states"]}
    differences = []
    for case in cases[1:]:
        for row in case["states"]:
            before = baseline.get((row["stage"], row["particle_id"]))
            if before is None:
                continue
            record = dict(case=case["label"], reference_case=cases[0]["label"], stage=row["stage"], particle_id=row["particle_id"], reference_status=before["status"], status=row["status"], common_exit_id=row["particle_id"] in common)
            valid = row["status"] == before["status"] == ("extracted" if row["stage"] == "exit_z0" else "alive")
            for key in ("t_us", *VALUES, "Ex_eV", "Ez_eV", "total_energy_eV", "theta_x_deg", "theta_y_deg"):
                record["delta_" + key] = row[key]-before[key] if valid and row[key] is not None and before[key] is not None else None
            differences.append(record)
    _write_csv(out / "particle_differences.csv", differences)
    losses = []
    for case in cases:
        for pid, row in case["terminals"].items():
            if pid not in case["exits"]:
                losses.append(dict(case=case["label"], particle_id=pid, reason=row["reason"], **{key: row[key] for key in ("t_us", *VALUES)}, source_events=str(Path(case["run"]) / "simion/events.csv")))
    _write_csv(out / "loss_comparison.csv", losses, ["case", "particle_id", "reason", "t_us", *VALUES, "source_events"])
    with plt.rc_context({"font.family":"DejaVu Sans", "font.size":9, "svg.fonttype":"none"}):
        figures = build_comparison_figures(cases, stats)
        if planes is not None:
            spatial_cases = [{**case, "states":prepare_spatial_crossings(case, planes), "stages":[f"z_{z:g}_mm" for z in planes]} for case in cases]
            spatial_stats, _, _ = prepare_statistics(spatial_cases)
            _write_csv(out / "spatial_plane_particles.csv", [r for case in spatial_cases for r in case["states"]])
            _write_csv(out / "spatial_plane_statistics.csv", spatial_stats)
            figures.update(build_spatial_figures(spatial_cases, spatial_stats, planes))
        for role, fig in figures.items():
            for extension in ("png", "svg"):
                fig.savefig(out / f"{role}.{extension}", format=extension, dpi=210, facecolor="white")
            plt.close(fig)
    repository = Path(__file__).resolve().parents[3]
    git = dict(sha=subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, text=True,
                                  encoding="utf-8", capture_output=True, timeout=10, check=True).stdout.strip(),
               worktree_porcelain=subprocess.run(["git", "status", "--porcelain"], cwd=repository, text=True,
                                                  encoding="utf-8", capture_output=True, timeout=10, check=True).stdout)
    metadata = dict(schema_version=1, role="ion_processor_extraction_factorial_comparison", study_contract=study_contract, git=git,
                    producer=file_record(Path(__file__)), cases=[{k:c[k] for k in ("label", "run", "lp_length_mm", "lift_v", "source_records")} for c in cases],
                    common_extracted_ids=common, frame_id=cases[0]["config"]["coordinate_transform"]["to_frame_id"],
                    units=dict(position="mm", velocity="mm/us in particle CSV; m/s in statistics", angle="degree", time="absolute instrument us"),
                    metrics="Population SD; centered covariance; RMS emittance=sqrt(var(x)*var(vx)-cov(x,vx)^2), or replace vx by theta_x in mrad. Ex includes mean drift. Theta=atan2(vtrans,abs(vz)); only after pulse with vz<0. x-theta moments use exactly the angle-defined subset.",
                    cohorts="all_available_alive uses currently alive snapshot states, own_extracted_ids and common_extracted_ids track exit-selected IDs backward; census retains losses/unknown/notborn/extracted separately. Exit ensemble uses individual crossing times.",
                    transformations="Existing bounded snapshot interpolation unchanged; birth and exit are actual recorded events. No smoothing, fitting, subsampling, outlier exclusion or extrapolation.",
                    spatial_sections="First -z crossing after actual pulse from bounded adjacent sample records; z=0 uses recorded exit. Near pulse and near small vz, theta describes direction only and is not an established paraxial beam. Missing crossings stay unknown with terminal reason. Each plane ensemble has different arrival times.",
                    effects="Equal weights: length=short-minus-long, lift=high-minus-low; interaction=(short_high-long_high)-(short_low-long_low).",
                    inference="Single seed N100 per cell; descriptive functional causal evidence at fixed numerics; no confidence interval, statistical or numerical convergence qualification. Paired ID differences are trajectory sensitivity, not identical collision histories.",
                    figures=[dict(role=k, width_inches=f.get_figwidth(), height_inches=f.get_figheight(), png_dpi=210, formats=["png","svg"]) for k,f in figures.items()])
    (out / "figure_manifest.json").write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    summary = dict(role=metadata["role"], source_counts={c["label"]:len(c["sources"]) for c in cases}, extracted_counts={c["label"]:len(c["exits"]) for c in cases}, common_extracted_ids=common,
                   exit_statistics=[r for r in stats if r["stage"] == "exit_z0"], factorial_exit_effects=[r for r in effects if r["stage"] == "exit_z0"],
                   pre_exit_velocity_variance_decomposition=decompositions, pre_exit_angle_correlations=correlations, qualification=metadata["inference"])
    (out / "comparison_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return summary


def analyze_registered_study(run: Path) -> dict:
    """Consume an existing analysis run's frozen study and explicit source map.

    No solver is started. Results require a fresh directory; lifecycle publication
    remains with the calling public run-package owner.
    """
    run = Path(run).resolve()
    config = _json(run / "run_config.json")
    if config.get("project") != PROJECT or config.get("mode") != "extraction_controlled_phase_space":
        raise ValueError("analysis run project or workflow differs")
    study = _json(Path(config["inputs"]["study_contract"]))
    if study.get("schema_version") != 1 or study.get("role") != "ion_processor_extraction_control_study":
        raise ValueError("unsupported extraction study contract")
    if (study["factor_A"]["field"] != "baseline.geometry.lp_length_mm" or
            study["factor_B"]["authority"] != "baseline.electric.lift_v" or
            study["factor_B"]["derived_projection"] != "native_operating_point.lift_v"):
        raise ValueError("study factor identities differ from LP length and lift voltage")
    planned = config["parameters"]["planned_runs"]
    cells = study["cells"]
    if len(cells) != 4 or len({cell["cell"] for cell in cells}) != 4 or set(planned) != {cell["cell"] for cell in cells}:
        raise ValueError("study requires four unique registered source cells")
    sources = {}
    for cell in cells:
        source = Path(planned[cell["cell"]])
        if source.name != cell["run_id"]:
            raise ValueError("planned source differs from registered run identity")
        label = f"LP {cell['lp_length_mm']:g} mm / {cell['lift_v']:.3f} V"
        sources[label] = source
    result = export_comparison(sources, run / "results", study)
    result.update(schema_version=1, status="success")
    (run / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return result
