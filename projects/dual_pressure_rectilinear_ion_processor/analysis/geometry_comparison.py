"""Compare declared electrode contours using complete recorded mother cohorts.

This analysis launches no solver. Existing verified event/snapshot and bounded
crossing preparation owns canonical states; this module adds y/time moments and
geometry-study presentation without removing tails or selecting successful runs.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import numpy as np

from common.contracts.write_run_manifest import file_record
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.dual_pressure_rectilinear_ion_processor.analysis import beam_focus_diagnostics, aperture_acceptance_diagnostics
from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison import (
    COLORS, MARKERS, VALUES, load_recorded_case, prepare_spatial_crossings, prepare_statistics,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import validate_numerical_boundaries
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection
from projects.dual_pressure_rectilinear_ion_processor.analysis.section_diagnostics import parts, section_centroid

MODES = {"flat", "formed_extraction", "formed_extraction_continuous_aux"}
PARABOLIC_MODE = "formed_extraction_continuous_aux_parabolic_inner"
LINESTYLES = ("-", "--", ":", "-.")
CONFIG_KEYS = ("baseline", "numerics", "source", "coordinate_transform", "native_operating_point",
               "native_timing", "diagnostics", "field_diagnostics", "acceptance")
COHORTS = ("all_available_alive", "own_extracted_ids", "common_extracted_ids")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _declared_configuration(reference: dict, changes: list[dict]) -> dict:
    """Apply exact, nonoverlapping design changes, including explicit absence.

    Paths are RFC6901 object pointers. Arrays are atomic values; source, clocks,
    frame, observation policy and numerics remain comparison invariants.
    """
    if not isinstance(changes, list):
        raise ValueError("configuration_changes must be an explicit list")
    result, paths = copy.deepcopy(reference), []
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "before", "after"}:
            raise ValueError("configuration change requires path/before/after")
        pointer = change["path"]
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("configuration change requires an object JSON pointer")
        tokens = pointer[1:].split("/")
        if any(not t or "~" in t.replace("~1", "").replace("~0", "") for t in tokens):
            raise ValueError("invalid configuration JSON pointer")
        tokens = tuple(t.replace("~1", "/").replace("~0", "~") for t in tokens)
        if not (tokens[0] == "native_operating_point" and len(tokens) > 1 or
                tokens[:2] == ("baseline", "electrode_contours")):
            raise ValueError("configuration changes must name native voltages or electrode contour design fields")
        if any(tokens[:len(p)] == p or p[:len(tokens)] == tokens for p in paths):
            raise ValueError("duplicate or ancestor-conflicting configuration change path")
        paths.append(tokens)
        for state in (change["before"], change["after"]):
            if (not isinstance(state, dict) or type(state.get("exists")) is not bool or
                    set(state) != ({"exists", "value"} if state["exists"] else {"exists"})):
                raise ValueError("change endpoints require explicit exists and value iff present")
            json.dumps(state, allow_nan=False)
        parent = result
        for token in tokens[:-1]:
            if not isinstance(parent, dict) or token not in parent or not isinstance(parent[token], dict):
                raise ValueError("configuration change parent must exist as an object")
            parent = parent[token]
        key = tokens[-1]
        actual = dict(exists=True, value=parent[key]) if key in parent else dict(exists=False)
        if actual != change["before"] or change["before"] == change["after"]:
            raise ValueError("configuration change has wrong before value or is a no-op")
        if change["after"]["exists"]:
            parent[key] = copy.deepcopy(change["after"]["value"])
        else:
            del parent[key]
    return result


def validate_geometry_cases(cases: list[dict], study: dict, *, recorded_author: bool = False) -> None:
    """Validate current declared design comparisons or explicit historical authors."""
    version = study.get("schema_version")
    if type(version) is not int or (version != 2 and not (recorded_author and version == 1)) or study.get("role") != "ion_processor_geometry_control_study":
        raise ValueError("unsupported geometry study contract")
    cells = study["cells"]
    expected_modes = MODES | ({PARABOLIC_MODE} if len(cells) == 4 else set())
    if version == 1 and (len(cases) != len(cells) or len(cases) not in (3, 4) or {c["contour_mode"] for c in cells} != expected_modes):
        raise ValueError("geometry study requires the three original contour modes and optionally one unique parabolic-inner mode")
    if not cases or len(cases) != len(cells) or len(cases) > len(LINESTYLES):
        raise ValueError("design comparison requires one to four declared cases")
    if version == 2:
        fields = {"case_id", "label", "run", "run_id", "contour_mode", "configuration_changes"}
        if any(not isinstance(cell, dict) or set(cell) != fields or
               any(not isinstance(cell[key], str) or not cell[key].strip() for key in fields - {"configuration_changes"})
               for cell in cells) or len({c["case_id"] for c in cells}) != len(cells):
            raise ValueError("complete unique design comparison cells required")
        references = [i for i, c in enumerate(cells) if c["case_id"] == study.get("reference_case_id")]
        if len(references) != 1 or cells[references[0]]["configuration_changes"] != []:
            raise ValueError("reference_case_id must name one unchanged reference")
        reference = {key: cases[references[0]]["config"][key] for key in CONFIG_KEYS}
    else:
        reference = None
    if len({c["label"] for c in cells}) != len(cells) or len({c["run_id"] for c in cells}) != len(cells):
        raise ValueError("duplicate geometry study label or run identity")
    count = study["particle_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("particle_count must be a positive integer")
    births = None
    stages = None
    for case, cell in zip(cases, cells, strict=True):
        path = Path(case["run"]).resolve()
        if path != Path(cell["run"]).resolve() or path.name != cell["run_id"] or case["label"] != cell["label"]:
            raise ValueError("actual case differs from declared run identity")
        config = case["config"]
        contour = config["baseline"].get("electrode_contours")
        if (contour["mode"] if contour else "flat") != cell["contour_mode"]:
            raise ValueError("actual contour mode differs from declaration")
        if config["native_projection"] != native_projection(config["baseline"], config["numerics"]):
            raise ValueError("native projection differs from geometry authority")
        validate_numerical_boundaries(config["numerical_boundaries"], config["native_projection"], recorded=True)
        normalized = copy.deepcopy({key: config[key] for key in CONFIG_KEYS})
        expected = _declared_configuration(reference, cell["configuration_changes"]) if version == 2 else reference
        if version == 1:
            normalized["baseline"].pop("electrode_contours", None)
        if expected is not None and normalized != expected:
            raise ValueError("undeclared scientific or numerical configuration change")
        if version == 1:
            reference = normalized
        ids = set(range(1, count + 1))
        if set(case["sources"]) != ids or set(case["terminals"]) != ids or not set(case["exits"]) <= ids:
            raise ValueError("geometry case lacks complete mother census")
        actual = {r["particle_id"]: tuple(r[k] for k in ("t_us", *VALUES))
                  for r in case["states"] if r["stage"] == "birth"}
        if set(actual) != ids or any(not all(math.isfinite(v) for v in values) for values in actual.values()):
            raise ValueError("birth state lacks complete finite 6D/time")
        if births is not None and actual != births:
            raise ValueError("actual birth states differ")
        births = actual
        if stages is not None and case["stages"] != stages:
            raise ValueError("observation stages differ")
        stages = case["stages"]


def comparison_execution_evidence(cases: list[dict]) -> list[dict]:
    """Bind each actual runtime and observation boundary without causal equivalence.

    Historical and current internal observation contracts may both be read, but
    their difference is retained alongside runtime bytes and original status.
    """
    rows = []
    for case in cases:
        run = Path(case["run"])
        manifest = _json(run/"run_manifest.json")
        path = (run/"simion/runtime.lua").resolve()
        records = [r for r in [*manifest["inputs"].values(), *manifest["outputs"]]
                   if record_path(r, base_dir=run) == path]
        if not records or any((r["sha256"], r["bytes"]) != (records[0]["sha256"], records[0]["bytes"]) for r in records[1:]):
            raise ValueError("comparison runtime lacks an unambiguous manifest-bound identity")
        verify_record("comparison runtime", records[0], base_dir=run)
        rows.append(dict(case=case["label"], source_run_status=manifest["status"],
                         runtime={**records[0], "path": str(path)},
                         numerical_boundaries=case["config"]["numerical_boundaries"],
                         interpretation="Recorded execution identity; differing runtime or observation boundaries prevent an unqualified claim of isolated physical causality."))
    return rows


def extend_statistics(cases: list[dict], statistics: list[dict], common: list[int]) -> list[dict]:
    """Extend existing x/census statistics with population y/time/energy moments.

    RMS y-angle emittance is sqrt(var(y)*var(theta_y)-cov(y,theta_y)^2),
    with theta in mrad and centered population covariance. Plane ensembles use
    each particle's own recorded crossing time, not a simultaneous cloud.
    """
    by_label = {c["label"]: c for c in cases}
    for stat in statistics:
        case = by_label[stat["case"]]
        ids = {"all_available_alive": set(case["sources"]), "own_extracted_ids": set(case["exits"]),
               "common_extracted_ids": set(common)}[stat["cohort"]]
        status = "extracted" if stat["stage"] == "exit_z0" else "alive"
        rows = [r for r in case["states"] if r["stage"] == stat["stage"]
                and r["particle_id"] in ids and r["status"] == status]
        stat["sigma_y_mm"] = float(np.std([r["y_mm"] for r in rows])) if rows else None
        stat["sigma_t_ns"] = float(np.std([r["t_us"] for r in rows])*1000) if rows else None
        stat["sigma_total_energy_eV"] = float(np.std([r["total_energy_eV"] for r in rows])) if rows else None
        directed = [r for r in rows if r["theta_y_deg"] is not None]
        if directed:
            y = np.array([r["y_mm"] for r in directed])
            angle = np.radians([r["theta_y_deg"] for r in directed])*1000
            cov = float(np.mean((y-y.mean())*(angle-angle.mean())))
            stat["cov_y_theta_y_mm_mrad"] = cov
            stat["rms_emittance_y_theta_mm_mrad"] = math.sqrt(max(0., float(y.var()*angle.var()-cov**2)))
        else:
            stat["cov_y_theta_y_mm_mrad"] = None
            stat["rms_emittance_y_theta_mm_mrad"] = None
    return statistics


def loss_evidence(cases: list[dict]) -> tuple[list[dict], list[dict]]:
    """Bind every terminal/loss to its exact raw event line, file record and SHA."""
    census, losses = [], []
    for case in cases:
        path = Path(case["run"])/"simion/events.csv"
        source = next(r for r in case["source_records"] if Path(r["path"]).resolve() == path.resolve())
        terminal_lines = {}
        with path.open("rb") as stream:
            header = next(stream).decode("utf-8-sig").strip()
            for number, raw in enumerate(stream, 2):
                fields = next(csv.DictReader([header, raw.decode("utf-8").strip()]))
                if fields["event"] == "terminal":
                    pid = int(fields["particle_id"])
                    if pid in terminal_lines:
                        raise ValueError("duplicate raw terminal evidence")
                    terminal_lines[pid] = (number, raw)
        if set(terminal_lines) != set(case["sources"]):
            raise ValueError("raw terminal evidence lacks full mother census")
        for pid, row in sorted(case["terminals"].items()):
            line, raw = terminal_lines[pid]
            item = dict(case=case["label"], particle_id=pid, extracted=pid in case["exits"],
                        reason=row["reason"], **{key: row[key] for key in ("t_us", *VALUES)},
                        source_events=str(path), source_events_sha256=source["sha256"], source_events_bytes=source["bytes"],
                        raw_line_number=line, raw_line_sha256=hashlib.sha256(raw).hexdigest().upper(),
                        raw_terminal_line=raw.decode("utf-8").rstrip("\r\n"))
            census.append(item)
            if pid not in case["exits"]:
                losses.append(item)
    return census, losses


def export_recorded_force_budgets(cases: list[dict], output: Path) -> list[dict]:
    """Bind existing audits or recover missing analysis into this new owner run.

    Raw per-step impulses remain immutable in their native source run. A failed
    historical diagnostic does not justify another particle flight or rewriting
    that source. Only declared, manifest-bound force evidence is consumed.
    """
    from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget import export_force_budget
    records=[]
    for index,case in enumerate(cases):
        if "extraction_force_audit" not in case["config"]:
            records.append(dict(case=case["label"],status="not_declared"))
            continue
        source=Path(case["run"])
        manifest=_json(source/"run_manifest.json")
        available=[*manifest["inputs"].values(),*manifest["outputs"]]
        existing=source/"results/extraction_force_budget/budget.json"
        paths=[existing] if existing.is_file() else [source/"simion/extraction_steps.csv",source/"simion/extraction_impulses.csv"]
        bound=[]
        for path in paths:
            matched=[r for r in available if record_path(r,base_dir=source)==path.resolve()]
            if len(matched)!=1:
                raise ValueError("force evidence is not uniquely manifest bound")
            verify_record("geometry force evidence",matched[0],base_dir=source)
            bound.append({**matched[0],"path":str(path.resolve())})
        if existing.is_file():
            records.append(dict(case=case["label"],status="native_audit_retained",records=bound))
        else:
            destination=output/f"recovered_force_budget_{index:02d}"
            metadata=export_force_budget(source,output_directory=destination)
            records.append(dict(case=case["label"],status="recovered_in_new_analysis_run",records=bound,
                                output=str(destination),available_particle_count=metadata["available_particle_count"]))
    return records


def _bounds(values: list[float]) -> tuple[float, float]:
    if not values:
        return -1., 1.
    low, high = min(values), max(values)
    padding = .05*(high-low) if high > low else max(abs(low)*.05, 1.e-6)
    return low-padding, high+padding


def _draw_sections(ax, config: dict, view: str, value: float) -> dict:
    """Draw actual frozen sections; return electrode annotation anchors."""
    from matplotlib.patches import Rectangle, Circle, Polygon
    origin = config["coordinate_transform"]["translation_mm"][2]
    anchors = {}
    for electrode in config["native_projection"]["electrodes"]:
        eid = electrode["electrode_id"]
        if eid not in (5,6,7,8,10,11,14):
            continue
        color = {10:"#E69F00",11:"#0072B2"}.get(eid,"#D9DDE1")
        for kind,p in parts(electrode,view,value,origin):
            style = dict(facecolor=color,edgecolor="#444444",linewidth=.65)
            if kind == "rect":
                ax.add_patch(Rectangle((p[0],p[1]),p[2]-p[0],p[3]-p[1],**style))
            elif kind == "circle":
                ax.add_patch(Circle(p[:2],p[2],**style))
            else:
                ax.add_patch(Polygon(p,closed=True,**style))
            center = section_centroid(kind,p)
            anchors.setdefault(eid,[]).append(center)
    return anchors


def build_electrode_comparison_figures(cases: list[dict]) -> tuple[dict, dict]:
    """Compare equal-scale LP cuts and explicitly cropped auxiliary profiles."""
    if not cases:
        raise ValueError("electrode comparison requires at least one declared case")
    from projects.dual_pressure_rectilinear_ion_processor.analysis.section_diagnostics import world_bounds
    names = {5:"Pull",6:"Push",7:"Upper side",8:"Lower side",10:"Outer auxiliary",11:"Inner auxiliary",14:"LP shield"}
    cross, cross_axes = plt.subplots(1,len(cases),figsize=(5*len(cases),5),squeeze=False,constrained_layout=True)
    auxiliary, aux_axes = plt.subplots(len(cases),2,figsize=(13,3.3*len(cases)),squeeze=False,constrained_layout=True)
    all_bounds, outer_bounds, inner_bounds = [], [], []
    for case in cases:
        config = case["config"]
        origin = config["coordinate_transform"]["translation_mm"][2]
        for electrode in config["native_projection"]["electrodes"]:
            if electrode["electrode_id"] not in names:
                continue
            bounds = [world_bounds(s,origin) for s in electrode["solids"]]
            all_bounds.extend(bounds)
            if electrode["electrode_id"] == 10:
                outer_bounds.extend(bounds)
            if electrode["electrode_id"] == 11:
                inner_bounds.extend(bounds)
    if not outer_bounds or not inner_bounds:
        raise ValueError("frozen geometry requires both outer and inner auxiliary electrodes")
    x_limits = _bounds([p[a][0] for p in all_bounds for a in (0,1)])
    z_limits = _bounds([p[a][2] for p in all_bounds for a in (0,1)])
    outer_y = _bounds([p[a][1] for p in outer_bounds for a in (0,1)])
    inner_y = _bounds([p[a][1] for p in inner_bounds for a in (0,1)])
    planes = []
    for index,case in enumerate(cases):
        config = case["config"]
        center = config["baseline"]["geometry"]["lp_center_mm"]
        origin = config["coordinate_transform"]["translation_mm"][2]
        ax = cross_axes[0,index]
        anchors = _draw_sections(ax,config,"cross",center)
        # Keep one label per electrical group, with sorted anchors to avoid overlap.
        targets = [(eid,max(points,key=lambda p:p[0])) for eid,points in anchors.items()]
        label_margin = .1*(z_limits[1]-z_limits[0])
        label_positions = np.linspace(z_limits[0]+label_margin,z_limits[1]-label_margin,len(targets))
        for (eid,target),z_text in zip(sorted(targets,key=lambda p:p[1][1]),label_positions,strict=True):
            ax.annotate(f"E{eid} {names[eid]}",xy=target,xytext=(x_limits[1]+.7,z_text),fontsize=7,
                        va="center",arrowprops=dict(arrowstyle="-",linewidth=.6,color="#444444"))
        ax.set(xlim=(x_limits[0],x_limits[1]+5),ylim=z_limits,xlabel="x transverse (mm)",ylabel="z extraction (mm)",
               title=f"{case['label']}\nActual section at slow y = {center:g} mm")
        ax.set_aspect("equal")
        for column,limits in enumerate((outer_y,inner_y)):
            ax = aux_axes[index,column]
            aux_anchors = _draw_sections(ax,config,"top",origin)
            annotation_height = x_limits[1]+.15*(x_limits[1]-x_limits[0])
            for eid in (10,11):
                positions = [p for p in aux_anchors.get(eid,[]) if limits[0] <= p[0] <= limits[1]]
                if positions:
                    target = max(positions,key=lambda p:p[1])
                    label_y = limits[0]+(limits[1]-limits[0])*(.25 if eid==10 else .75)
                    label = f"E{eid} {names[eid]}" if column==0 else f"E{eid}"
                    label_height = annotation_height
                    if column==1:
                        label_height += (.07 if eid==10 else -.07)*(x_limits[1]-x_limits[0])
                    ax.annotate(label,xy=target,xytext=(label_y,label_height),ha="center",fontsize=8,
                                arrowprops=dict(arrowstyle="-",linewidth=.6,color="#444444"))
            auxiliary_limits = (x_limits[0],x_limits[1]+.3*(x_limits[1]-x_limits[0]))
            ax.set(xlim=limits,ylim=auxiliary_limits,xlabel="y slow drift (mm)",ylabel="x transverse (mm)",
                   title=f"{case['label']} | Full outer length; stretched scale" if column==0 else "Inner close-up | equal scale")
            ax.set_aspect("auto" if column==0 else "equal")
            ax.grid(alpha=.15)
        planes.append(dict(case=case["label"],cross_slow_y_mm=center,equatorial_z_mm=origin))
    cross.suptitle("LP extraction electrode sections | Gray main conductors; orange E10; blue E11")
    auxiliary.suptitle("Actual equatorial CSG sections | Full outer profile and inner close-up\n"
                       "Views are cropped to auxiliary regions; gray context is intersected metal, not projected bounds")
    metadata = dict(planes=planes,cross_x_limits_mm=list(x_limits),cross_z_limits_mm=list(z_limits),
                    outer_y_limits_mm=list(outer_y),inner_y_limits_mm=list(inner_y),
                    auxiliary_transverse_limits_mm=[x_limits[0],x_limits[1]+.3*(x_limits[1]-x_limits[0])],
                    geometry_scope="Actual frozen CSG plane intersections and cutout subtraction; no bounding boxes substituted for electrodes",
                    scales="Cross sections and inner close-ups equal physical scale; full outer longitudinal profiles explicitly stretched",
                    clipping="Auxiliary-region close-ups only; not a full-apparatus view; all cases use identical limits")
    return {"geometry_main_sections":cross,"geometry_auxiliary_profiles":auxiliary},metadata


def build_geometry_figures(cases: list[dict], plane_statistics: list[dict], planes: list[float], common: list[int]) -> tuple[dict, dict]:
    """Use shared full-range axes and globally fixed bins; display every own exit."""
    exits = [[r for r in c["states"] if r["stage"] == "exit_z0" and r["status"] == "extracted"] for c in cases]
    prepared = []
    for rows in exits:
        times = [r["t_us"] for r in rows]
        center = float(np.mean(times)) if times else 0.
        prepared.append([{**r, "centered_t_ns": (r["t_us"]-center)*1000} for r in rows])
    keys = ("x_mm", "y_mm", "theta_x_deg", "theta_y_deg", "centered_t_ns", "total_energy_eV")
    bounds = {key: _bounds([r[key] for rows in prepared for r in rows]) for key in keys}
    bins = {key: np.linspace(*bounds[key], 21) for key in ("theta_x_deg", "theta_y_deg", "centered_t_ns", "total_energy_eV")}
    phase, axes = plt.subplots(len(cases), 3, figsize=(12, 3.4*len(cases)), squeeze=False, constrained_layout=True)
    pairs = (("x_mm", "theta_x_deg", "x (mm)", "xz angle (deg)"),
             ("y_mm", "theta_y_deg", "y (mm)", "yz angle (deg)"),
             ("centered_t_ns", "total_energy_eV", "Arrival time minus case mean (ns)", "Total kinetic energy (eV)"))
    for index, (case, rows) in enumerate(zip(cases, prepared, strict=True)):
        for ax, (x, y, xlabel, ylabel) in zip(axes[index], pairs, strict=True):
            ax.scatter([r[x] for r in rows], [r[y] for r in rows], s=13, color=COLORS[index], marker=MARKERS[index])
            ax.set(xlim=bounds[x], ylim=bounds[y], xlabel=xlabel, ylabel=ylabel,
                   title=f"{case['label']} | own exits {len(rows)}/{len(case['sources'])}")
            ax.grid(alpha=.2)
    phase.suptitle("Exit z=0 phase space | Individual crossing states; all tails retained")
    distributions, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    for ax, key, label in zip(axes.flat, bins, ("xz angle (deg)", "yz angle (deg)", "Arrival time minus case mean (ns)", "Total kinetic energy (eV)"), strict=True):
        for index, (case, rows) in enumerate(zip(cases, prepared, strict=True)):
            if rows:
                ax.hist([r[key] for r in rows], bins=bins[key], weights=np.ones(len(rows))/len(rows), histtype="step",
                        color=COLORS[index], linestyle=LINESTYLES[index], label=f"{case['label']} N={len(rows)}")
        ax.set(xlabel=label, ylabel="Probability per bin", xlim=bounds[key])
        ax.grid(alpha=.2)
    axes[0, 0].legend(fontsize=8)
    distributions.suptitle("Own-exit distributions | Shared bins; full range; each case normalized by its exit N")
    evolution, axes = plt.subplots(4, 2, figsize=(11, 12), constrained_layout=True)
    cohort = "common_extracted_ids" if common else "all_available_alive"
    metrics = (("sigma_x_mm", "SD x (mm)"), ("sigma_y_mm", "SD y (mm)"),
               ("sigma_theta_x_deg", "SD xz angle (deg)"), ("sigma_theta_y_deg", "SD yz angle (deg)"),
               ("rms_emittance_x_theta_mm_mrad", "RMS x-angle emittance (mm mrad)"),
               ("rms_emittance_y_theta_mm_mrad", "RMS y-angle emittance (mm mrad)"),
               ("sigma_t_ns", "Arrival-time SD (ns)"), ("sigma_total_energy_eV", "Total kinetic energy SD (eV)"))
    for ax, (metric, label) in zip(axes.flat, metrics, strict=True):
        for index, case in enumerate(cases):
            rows = [r for r in plane_statistics if r["case"] == case["label"] and r["cohort"] == cohort]
            observed = [r["observed_count"] for r in rows]
            counts = (f"{observed[0]} at all {len(rows)} planes" if len(set(observed)) == 1
                      else f"{min(observed)}-{max(observed)}; per-plane counts in CSV")
            ax.plot(planes, [np.nan if r[metric] is None else r[metric] for r in rows], color=COLORS[index],
                    marker=MARKERS[index], linestyle=LINESTYLES[index], label=f"{case['label']} | valid N={counts}")
        ax.set(xlabel="Observation z (mm); flight toward decreasing z", ylabel=label)
        ax.invert_xaxis()
        ax.grid(alpha=.2)
    handles,labels = axes[0,0].get_legend_handles_labels()
    evolution.legend(handles,labels,loc="outside upper center",ncol=2,fontsize=8,frameon=False,
                     title=f"Extraction plane evolution\n{cohort}; common exit N={len(common)} | Recorded bounded crossings")
    geometry_figures, geometry_metadata = build_electrode_comparison_figures(cases)
    return {**geometry_figures,"geometry_exit_phase_space": phase, "geometry_exit_distributions": distributions,
            "geometry_plane_evolution": evolution}, dict(bounds=bounds, histogram_bins={k: v.tolist() for k, v in bins.items()},
                                                       histogram_normalization="one case exit ensemble sums to probability one", plane_plot_cohort=cohort,
                                                       geometry_views=geometry_metadata)


def analyze_geometry_study(run: Path) -> dict:
    """Load a registered contour study and publish automatic comparison evidence."""
    run = Path(run).resolve()
    config = _json(run/"run_config.json")
    if config.get("project") != "dual_pressure_rectilinear_ion_processor":
        raise ValueError("geometry comparison project differs")
    study_path = Path(config["inputs"]["study_contract"])
    if not study_path.is_absolute():
        study_path = run/study_path
    study = _json(study_path)
    if study.get("schema_version") != 2 or study.get("role") != "ion_processor_geometry_control_study":
        raise ValueError("unsupported geometry study contract")
    cases = [load_recorded_case(Path(cell["run"]), cell["label"], include_samples=True, allow_failed=True) for cell in study["cells"]]
    validate_geometry_cases(cases, study)
    execution_evidence = comparison_execution_evidence(cases)
    stats, intervals, common = prepare_statistics(cases, allow_empty_common=True)
    extend_statistics(cases, stats, common)
    planes = study["extraction_planes_z_mm"]
    spatial = [{**case, "states": prepare_spatial_crossings(case, planes), "stages": [f"z_{z:g}_mm" for z in planes]} for case in cases]
    plane_stats, _, _ = prepare_statistics(spatial, allow_empty_common=True)
    extend_statistics(spatial, plane_stats, common)
    focus = beam_focus_diagnostics.prepare_focus_diagnostics(spatial, planes, common)
    time_focus = (beam_focus_diagnostics.prepare_time_focus_diagnostics(spatial, planes, common, study["time_focus_diagnostics"])
                  if "time_focus_diagnostics" in study else None)
    aperture = (aperture_acceptance_diagnostics.prepare_aperture_diagnostics(spatial, study["aperture_acceptance"])
                if "aperture_acceptance" in study else None)
    census, losses = loss_evidence(cases)
    output = run/"results/geometry_comparison"
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError("geometry comparison requires fresh outputs")
    force_audits=export_recorded_force_budgets(cases,output)
    _write_csv(output/"stage_particles.csv", [r for c in cases for r in c["states"]])
    _write_csv(output/"stage_statistics.csv", stats)
    _write_csv(output/"stage_variance_budget.csv", intervals, list(intervals[0]) if intervals else ["case", "cohort", "from_stage", "to_stage", "count"])
    _write_csv(output/"plane_particles.csv", [r for c in spatial for r in c["states"]])
    _write_csv(output/"plane_statistics.csv", plane_stats)
    _write_csv(output/"mother_census.csv", census)
    _write_csv(output/"all_losses.csv", losses, list(census[0]))
    for key in ("plane_statistics", "exit_angle_decomposition", "field_free_predictions", "sampled_minima"):
        _write_csv(output/f"beam_focus_{key}.csv", focus[key])
    (output/"beam_focus_diagnostics.json").write_text(json.dumps(focus, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    for role, prepared, tables in (
        ("time_focus", time_focus, ("plane_time_statistics", "plane_drift_predictions", "reference_plane_predictions", "reference_particle_predictions", "sampled_minima", "time_interval_variance_rows")),
        ("aperture_acceptance", aperture, ("summary_rows", "particle_rows", "reference_rows")),
    ):
        if prepared is not None:
            for table in tables:
                _write_csv(output/f"{role}_{table}.csv", prepared[table])
            (output/f"{role}_diagnostics.json").write_text(json.dumps(prepared, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none"}):
        figures, visual = build_geometry_figures(cases, plane_stats, planes, common)
        figures["beam_focus_diagnostics"] = beam_focus_diagnostics.build_focus_figure(focus)
        if time_focus is not None:
            figures["time_focus_diagnostics"] = beam_focus_diagnostics.build_time_focus_figure(time_focus)
        if aperture is not None:
            figures["aperture_acceptance_diagnostics"] = aperture_acceptance_diagnostics.build_aperture_figure(aperture)
        for role, figure in figures.items():
            for extension in ("png", "svg"):
                figure.savefig(output/f"{role}.{extension}", format=extension, dpi=210, facecolor="white")
            plt.close(figure)
    summary = dict(schema_version=1, role="ion_processor_geometry_comparison", status="success", mother_count=study["particle_count"],
                   source_counts={c["label"]: len(c["sources"]) for c in cases}, extracted_counts={c["label"]: len(c["exits"]) for c in cases},
                   source_run_statuses={c["label"]: _json(Path(c["run"])/"run_manifest.json")["status"] for c in cases},
                   common_extracted_ids=common, loss_records=len(losses), all_mother_outcomes_retained=True,
                   reference_case_id=study["reference_case_id"], execution_evidence=execution_evidence,
                   force_audits=force_audits,
                   sampled_envelope_minima=focus["sampled_minima"],
                   exit_statistics=[r for r in stats if r["stage"] == "exit_z0"],
                   qualification=f"Single N={study['particle_count']} per declared design; descriptive population moments; own and common survivors are conditional ensembles. Runtime/boundary differences are recorded, not certified equivalent; no isolated causal, convergence or significance qualification")
    manifest = dict(schema_version=1, role="ion_processor_geometry_figure_sources", study_contract=file_record(study_path),
                    producer=file_record(Path(__file__)), focus_producer=file_record(Path(beam_focus_diagnostics.__file__)),
                    focus_methods=focus["metadata"],
                    time_focus_methods=time_focus["metadata"] if time_focus is not None else None,
                    aperture_methods=aperture["metadata"] if aperture is not None else None,
                    aperture_producer=file_record(Path(aperture_acceptance_diagnostics.__file__)) if aperture is not None else None,
                    cases=[dict(label=c["label"], run=c["run"], source_manifest=file_record(Path(c["run"])/"run_manifest.json"), source_records=c["source_records"]) for c in cases],
                    execution_evidence=execution_evidence, reference_case_id=study["reference_case_id"],
                    frame=cases[0]["config"]["coordinate_transform"], formats=["png", "svg"], png_dpi=210, figures=list(figures), **visual,
                    units=dict(position="mm", velocity="mm/us", angle="degree", energy="eV", time="instrument us; centered time figure ns"),
                    metrics="Population SD (ddof=0); centered population covariance; RMS projected emittance; no Gaussian/FWHM inference",
                    category_styles=[dict(case=c["label"], color=COLORS[i], marker=MARKERS[i], linestyle=LINESTYLES[i]) for i, c in enumerate(cases)],
                    transformations="No particle smoothing, cropping, random selection, outlier removal or extrapolation. Geometry auxiliary views use explicitly declared shared close-up crops. Planes reuse existing bounded first -z crossings; z=0 uses measured events. Histograms use own exits; tables include all/own/common cohorts.",
                    missing_policy="Lost and unavailable crossing states retained with ID/reason; empty cohort metrics null")
    (output/"figure_manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    (output/"comparison_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    (run/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return summary
