"""Whole-cohort diagnostics from recorded states; never simulate missing motion."""
from __future__ import annotations

from bisect import bisect_left
import csv
from itertools import chain
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle
import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from common.multipole.exit_state_plot import prepare_visual_style_map
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import to_project_position
# Top-level imports are deliberate: prepare() freezes loaded repository modules
# before Fly, so these mandatory default producers travel with the same run.
from projects.dual_pressure_rectilinear_ion_processor.analysis.section_diagnostics import export_sections
from projects.dual_pressure_rectilinear_ion_processor.analysis.post_extraction_diagnostics import export_post_extraction

PRODUCER_SOURCE_SHA256 = file_sha256(Path(__file__))

STATES = ("alive", "extracted", "lost", "notborn", "unknown")
VALUES = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")


def coordinate_axes(data: dict) -> tuple[str, str, str]:
    """Return slow, extraction and transverse axes in recorded coordinates."""
    return ("y", "z", "x") if "coordinate_transform" in data["config"] else ("x", "y", "z")


def project_geometry(config: dict) -> dict:
    """Rotate frozen local-solid bounds for the declared diagnostic frame."""
    projection = config["native_projection"]
    if "coordinate_transform" not in config:
        return projection
    electrodes = []
    for electrode in projection["electrodes"]:
        solids = []
        for shape in electrode["solids"]:
            if shape["shape"] == "box":
                low, high = shape["min_mm"], shape["max_mm"]
            else:
                r = shape["radius_mm"]
                low = [shape["x_min_mm"], shape["center_y_mm"]-r, shape["center_z_mm"]-r]
                high = [shape["x_max_mm"], shape["center_y_mm"]+r, shape["center_z_mm"]+r]
            corners = [to_project_position(config, (x,y,z)) for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])]
            solids.append(dict(shape="box", min_mm=[min(p[i] for p in corners) for i in range(3)], max_mm=[max(p[i] for p in corners) for i in range(3)]))
        electrodes.append({**electrode, "solids": solids})
    return {**projection, "electrodes": electrodes, "frame_id": config["coordinate_transform"]["to_frame_id"]}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _iter_csv(path: Path, required: set[str]):
    """Validate the header once and stream each actual recorded row."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"missing diagnostic columns in {path.name}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"malformed diagnostic row in {path.name}")
            yield row


def _csv(path: Path, required: set[str]) -> list[dict]:
    rows = list(_iter_csv(path, required))
    if not rows:
        raise ValueError(f"empty diagnostic input {path.name}")
    return rows


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)



def validate_diagnostics_config(config: dict) -> None:
    """Validate the complete diagnostic author contract before solver startup."""
    contract = config
    expected = {"schema_version", "role", "max_ordinary_bracket_us", "max_extraction_bracket_us", "evolution_interval_us", "png_dpi", "snapshots", "stage_labels"}
    if set(contract) != expected or contract["schema_version"] != 1 or contract["role"] != "ion_processor_diagnostics":
        raise ValueError("unsupported diagnostics contract")
    for key in ("max_ordinary_bracket_us", "max_extraction_bracket_us", "evolution_interval_us", "png_dpi"):
        if isinstance(contract[key], bool) or not isinstance(contract[key], (int, float)) or not math.isfinite(contract[key]) or contract[key] <= 0:
            raise ValueError(f"invalid diagnostics {key}")
    if contract["png_dpi"] < 180:
        raise ValueError("diagnostic PNG requires at least 180 DPI")
    labels = []
    allowed_anchors = {"epoch_us", "capture_end_us", "transfer_end_us", "lift_end_us", "extraction_start_us", "terminal_us", "primary_quench_us", "pulse_start_us"}
    if not isinstance(contract["snapshots"], list) or not contract["snapshots"]:
        raise ValueError("diagnostic snapshots must be nonempty")
    for item in contract["snapshots"]:
        if not isinstance(item, dict) or set(item) != {"label", "anchor", "offset_us"}:
            raise ValueError("snapshot must declare label/anchor/offset")
        if not isinstance(item["label"], str) or not item["label"] or item["anchor"] not in allowed_anchors:
            raise ValueError("invalid snapshot label or schedule anchor")
        if isinstance(item["offset_us"], bool) or not isinstance(item["offset_us"], (int,float)) or not math.isfinite(item["offset_us"]):
            raise ValueError("snapshot offset must be finite numeric")
        labels.append(item["label"])
    if len(set(labels)) != len(labels) or not isinstance(contract["stage_labels"], list) or not contract["stage_labels"] or not set(contract["stage_labels"]) <= set(labels):
        raise ValueError("duplicate or missing diagnostic stage label")


def pulse_timing_context(data: dict) -> dict:
    """Describe frozen quench and actual pulse timing without a new authority."""
    b = data["config"]["baseline"]
    timing = data["config"].get("native_timing")
    if timing is not None:
        return dict(quench_start_us=timing["primary_quench_us"], pulse_start_us=timing["pulse_start_us"],
                    requested_quench_us=timing["requested_quench_us"], timing_policy=timing["policy"],
                    meaning="frozen native_timing actual author-selected quench and pulse; snapshot offsets reference their explicitly named anchor")
    quench = b["schedule"]["extraction_start_us"]
    electric = b.get("electric", {})
    if not {"rf_quench_delay_cycles", "rf_frequency_hz"} <= set(electric):
        return dict(quench_start_us=quench, pulse_start_us=None, timing_policy="legacy_requested_quench", meaning="historical frozen input: requested extraction_start_us was the actual non-aligned RF quench; pulse delay unavailable")
    delay = electric["rf_quench_delay_cycles"] / electric["rf_frequency_hz"] * 1e6
    return dict(quench_start_us=quench, pulse_start_us=quench+delay, timing_policy="legacy_requested_quench", rf_quench_delay_cycles=electric["rf_quench_delay_cycles"], meaning="historical frozen input: extraction_start_us was actual non-aligned RF quench; snapshot offsets reference quench start; no new zero alignment applied")


def prepare_data(run: Path) -> dict[str, Any]:
    """Normalize actual samples/events and retain complete source/terminal IDs."""
    c = _json(run / "inputs/resolved_model.json")
    contract = _json(run / "inputs/diagnostics.json")
    validate_diagnostics_config(contract)
    events = _iter_csv(run / "simion/events.csv", {"particle_id", "event", "reason", "t_us", *VALUES})
    samples = _iter_csv(run / "simion/samples.csv", {"particle_id", "t_us", *VALUES})
    canonical = _csv(run / "results/particle_state.csv", {"particle_id", "event", "status"})
    sources, terminals, tracks = {}, {}, {}
    mass = c["source"]["species"]["mass_amu"]
    for raw in chain(samples, events):
        particle = int(raw["particle_id"])
        row = {key: float(raw[key]) for key in ("t_us", *VALUES)}
        if any(not math.isfinite(value) for value in row.values()):
            raise ValueError("nonfinite diagnostic state")
        row["kinetic_energy_ev"] = kinetic_energy_ev(mass, *(row[key] * 1000 for key in VALUES[3:]))
        tracks.setdefault(particle, {})[row["t_us"]] = row
        if raw.get("event") == "source":
            if particle in sources:
                raise ValueError("duplicate source ID")
            sources[particle] = row
        if raw.get("event") == "terminal":
            if particle in terminals:
                raise ValueError("duplicate terminal ID")
            terminals[particle] = {**row, "reason": raw["reason"], "electrode_id": raw.get("electrode_id") or "unknown"}
    if not sources or set(tracks) != set(sources) or not set(terminals) <= set(sources):
        raise ValueError("sample/event particle IDs do not match source")
    if {int(row["particle_id"]) for row in canonical if row["event"] == "source"} != set(sources):
        raise ValueError("canonical source membership differs")
    ordered = {}
    for particle, table in tracks.items():
        death = terminals.get(particle, {}).get("t_us", math.inf)
        rows = [row for time, row in sorted(table.items()) if time <= death]
        if any(row["t_us"] < sources[particle]["t_us"] for row in rows):
            raise ValueError("recorded state precedes particle birth")
        ordered[particle] = rows
    b = c["baseline"]
    snapshots = []
    for item in contract["snapshots"]:
        if set(item) != {"label", "anchor", "offset_us"}:
            raise ValueError("snapshot must declare label/anchor/offset")
        if item["anchor"] in {"primary_quench_us", "pulse_start_us"}:
            anchor = c["native_timing"][item["anchor"]]
        else:
            anchor = b["clock"]["epoch_us"] if item["anchor"] == "epoch_us" else b["schedule"][item["anchor"]]
        time = anchor + item["offset_us"]
        if not math.isfinite(time) or not b["clock"]["epoch_us"] <= time <= b["schedule"]["terminal_us"]:
            raise ValueError("snapshot time outside declared clock")
        snapshots.append((item["label"], time))
    if len({label for label, _ in snapshots}) != len(snapshots) or not set(contract["stage_labels"]) <= {label for label, _ in snapshots}:
        raise ValueError("duplicate or missing diagnostic stage label")
    return dict(config=c, contract=contract, sources=sources, terminals=terminals, tracks=ordered,
                times={particle: [row["t_us"] for row in rows] for particle, rows in ordered.items()}, snapshots=snapshots)


def state_at(data: dict, particle: int, time: float) -> dict:
    """Classify first; interpolate only observed adjacent points within limits."""
    source = data["sources"][particle]
    base = dict(particle_id=particle, t_us=time, status="unknown", reason="missing_bracket", electrode_id="unknown", bracket_start_us=None, bracket_end_us=None, bracket_gap_us=None, **{key: None for key in (*VALUES, "kinetic_energy_ev")})
    if time < source["t_us"]:
        return {**base, "status": "notborn", "reason": "not_yet_born"}
    terminal = data["terminals"].get(particle)
    if terminal and time >= terminal["t_us"]:
        # These coordinates are explicitly the LAST state, not a live cloud.
        return {**base, **{key: terminal[key] for key in (*VALUES, "kinetic_energy_ev")}, "status": "extracted" if terminal["reason"] == "acceptance_surface" else "lost", "reason": terminal["reason"], "electrode_id": terminal["electrode_id"]}
    times = data["times"][particle]
    index = bisect_left(times, time)
    if index < len(times) and abs(times[index] - time) <= 1e-9:
        row = data["tracks"][particle][index]
        return {**base, **row, "status": "alive", "reason": "exact_record", "bracket_start_us": row["t_us"], "bracket_end_us": row["t_us"], "bracket_gap_us": 0}
    if index == 0 or index == len(times):
        return base
    left, right = data["tracks"][particle][index-1:index+1]
    gap = right["t_us"] - left["t_us"]
    extraction = pulse_timing_context(data)["quench_start_us"]
    limit = data["contract"]["max_extraction_bracket_us" if right["t_us"] >= extraction else "max_ordinary_bracket_us"]
    bracket = dict(bracket_start_us=left["t_us"], bracket_end_us=right["t_us"], bracket_gap_us=gap)
    if gap > limit + 1e-12:
        return {**base, **bracket, "reason": "bracket_exceeds_limit"}
    u = (time-left["t_us"])/gap
    row = {key: left[key] + u*(right[key]-left[key]) for key in VALUES}
    row["kinetic_energy_ev"] = kinetic_energy_ev(data["config"]["source"]["species"]["mass_amu"], *(row[key]*1000 for key in VALUES[3:]))
    return {**base, **row, **bracket, "status": "alive", "reason": "linear_display_interpolation"}


def lp_members(data: dict, rows: list[dict]) -> list[dict] | None:
    """Declare LP conditioning spatially; never use final detector outcome."""
    g=data["config"]["baseline"].get("geometry",{})
    if not {"guide_length_mm","hp_length_mm","lp_length_mm"} <= set(g):
        return None
    start=g["guide_length_mm"]+g["hp_length_mm"]
    slow, _, _ = coordinate_axes(data)
    return [row for row in rows if row["status"]=="alive" and start<row[slow+"_mm"]<start+g["lp_length_mm"]]


def census(data: dict, time: float) -> tuple[dict, list[dict]]:
    rows = [state_at(data, particle, time) for particle in sorted(data["sources"])]
    counts = {state: sum(row["status"] == state for row in rows) for state in STATES}
    if sum(counts.values()) != len(data["sources"]):
        raise AssertionError("diagnostic census does not close")
    alive = [row for row in rows if row["status"] == "alive"]
    lp=lp_members(data,rows)
    slow, _, _ = coordinate_axes(data)
    spread=float(np.std([row[slow+"_mm"] for row in alive])) if alive else None
    lp_spread=float(np.std([row[slow+"_mm"] for row in lp])) if lp else None
    result=dict(t_us=time, source_count=len(rows), **counts, sigma_slow_mm=spread, sigma_axis=slow,
                lp_alive_count=None if lp is None else len(lp), lp_sigma_slow_mm=lp_spread)
    if "coordinate_transform" not in data["config"]:
        result.update(sigma_x_mm=spread, lp_sigma_x_mm=lp_spread)
    return result, rows


def add_geometry(axis, projection: dict, horizontal: str, vertical: str) -> None:
    """Project the frozen solids; cutout detail stays in semantic provenance."""
    hi, vi = "xyz".index(horizontal), "xyz".index(vertical)
    for electrode in projection["electrodes"]:
        first = True
        for solid in electrode["solids"]:
            if solid["shape"] == "box":
                low, high = solid["min_mm"], solid["max_mm"]
            else:
                radius = solid["radius_mm"]
                low = [solid["x_min_mm"], solid["center_y_mm"]-radius, solid["center_z_mm"]-radius]
                high = [solid["x_max_mm"], solid["center_y_mm"]+radius, solid["center_z_mm"]+radius]
            axis.add_patch(Rectangle((low[hi], low[vi]), high[hi]-low[hi], high[vi]-low[vi], facecolor="none", edgecolor="#777777", linewidth=.5, alpha=.45, label=f"E{electrode['electrode_id']} {electrode['name']}" if first else None))
            first = False
    axis.set(xlabel=f"{horizontal} (mm)", ylabel=f"{vertical} (mm)")
    axis.set_aspect("equal", adjustable="datalim")


def display_bounds(data: dict) -> dict:
    """Use declared apparatus/domain extents with explicit display-only margins."""
    b = data["config"]["baseline"]
    projection = data["config"]["native_projection"]
    g = b.get("geometry", {})
    if {"guide_length_mm", "hp_length_mm", "lp_length_mm"} <= set(g):
        x_range = (-5.0, sum(g[key] for key in ("guide_length_mm", "hp_length_mm", "lp_length_mm")) + 5.0)
    else:
        x_range = (projection.get("origin_mm", [-1,-4,-4])[0]-4, projection.get("maximum_mm", [4,10,4])[0]+3)
    n = b.get("native_geometry", {})
    y_min = n.get("domain_min_y_mm", projection.get("origin_mm", [-1,-4,-4])[1])
    y_max = n.get("domain_max_y_mm", projection.get("maximum_mm", [4,10,4])[1])
    margin = .03*(y_max-y_min)
    center = g.get("lp_center_mm", (x_range[0]+x_range[1])/2)
    half = g.get("extraction_slit_length_mm", 8)/2
    full_vertical=(y_min-margin,y_max+margin)
    local_vertical=(-1,y_max+margin)
    if "coordinate_transform" in data["config"]:
        full_vertical=tuple(sorted(to_project_position(data["config"],(0,value,0))[2] for value in full_vertical))
        local_vertical=tuple(sorted(to_project_position(data["config"],(0,value,0))[2] for value in local_vertical))
    return dict(full_x_mm=x_range, full_y_mm=full_vertical,
                local_x_mm=(center-half,center+half), local_y_mm=local_vertical,
                display_axes=coordinate_axes(data),
                aspect="auto; axial and transverse display scales differ", local_policy="LP extraction zoom only; particles outside shown in full-range timed_clouds and counted explicitly")


def _shared_legend(figure, axis) -> None:
    handles, labels = axis.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    if unique:
        figure.legend(unique.values(), unique.keys(), loc="outside lower center", ncol=4, fontsize=6, frameon=False)


def build_figures(data: dict, snapshot_rows: list[dict], evolution: list[dict], *, include_projected_geometry: bool = True) -> dict:
    """Render full-cohort views plus explicitly conditional LP/cooling panels."""
    styles = prepare_visual_style_map(list(STATES))
    projection = project_geometry(data["config"])
    slow, fast, transverse = coordinate_axes(data)
    figures = {}
    bounds = display_bounds(data)
    quench = pulse_timing_context(data)["quench_start_us"]
    if include_projected_geometry:
        figure, axes = plt.subplots(2, 1, figsize=(13, 7), constrained_layout=True)
        for axis, vertical in zip(axes, (fast, transverse)):
            add_geometry(axis, projection, slow, vertical)
            lines = [np.array([[row[slow+"_mm"], row[vertical+"_mm"]] for row in track]) for track in data["tracks"].values()]
            axis.add_collection(LineCollection(lines, colors="#0072B2", linewidths=.7, alpha=.65, label="all recorded particle tracks"))
            for state in ("lost", "extracted"):
                terminals = [row for row in data["terminals"].values() if (row["reason"] == "acceptance_surface") == (state == "extracted")]
                if terminals:
                    axis.scatter([row[slow+"_mm"] for row in terminals], [row[vertical+"_mm"] for row in terminals], color=styles[state]["color"], marker=styles[state]["marker"], label=state+" last positions", zorder=5)
            axis.autoscale_view()
            axis.set_title("Recorded trajectories with projected electrode outlines")
        _shared_legend(figure, axes[0])
        figures["trajectory_geometry"] = figure
        columns = 3
        figure, axes = plt.subplots(math.ceil(len(data["snapshots"])/columns), columns, figsize=(14, 11), constrained_layout=True)
        for axis, (label, time) in zip(np.asarray(axes).flat, data["snapshots"]):
            rows = [row for row in snapshot_rows if row["snapshot"] == label]
            add_geometry(axis, projection, slow, fast)
            axis.set_aspect("auto")
            axis.set(xlim=bounds["full_x_mm"], ylim=bounds["full_y_mm"])
            for state in ("alive", "lost", "extracted"):
                selected = [row for row in rows if row["status"] == state]
                axis.scatter([row[slow+"_mm"] for row in selected], [row[fast+"_mm"] for row in selected], color=styles[state]["color"], marker=styles[state]["marker"], s=12, label=state if state == "alive" else state+" last")
            counts = {state: sum(row["status"] == state for row in rows) for state in STATES}
            snapshot_spec = next(item for item in data["contract"]["snapshots"] if item["label"] == label)
            anchor_label = {"extraction_start_us":"requested_quench" if "native_timing" in data["config"] else "legacy_quench", "primary_quench_us":"quench_start", "pulse_start_us":"pulse_start"}.get(snapshot_spec["anchor"])
            display_label = f"{anchor_label}{snapshot_spec['offset_us']:+g} us" if anchor_label else label
            axis.set_title(f"{display_label} t={time:g} us\n" + ", ".join(f"{state}={n}" for state, n in counts.items()), fontsize=8)
        for axis in list(np.asarray(axes).flat)[len(data["snapshots"]):]:
            axis.set_visible(False)
        _shared_legend(figure, np.asarray(axes).flat[0])
        pulse_context = pulse_timing_context(data)
        pulse_label = "unavailable in frozen input" if pulse_context["pulse_start_us"] is None else f"{pulse_context['pulse_start_us']:.8g} us"
        figure.suptitle(f"Full apparatus: axial/transverse display scales differ; quench offsets, pulse starts {pulse_label}", fontsize=10)
        figures["timed_clouds"] = figure
        extraction_snapshots = [(label,time) for label,time in data["snapshots"] if time >= quench]
        if extraction_snapshots:
            figure, axes = plt.subplots(math.ceil(len(extraction_snapshots)/3),3,figsize=(14,6),squeeze=False,constrained_layout=True)
            for axis,(label,time) in zip(axes.flat,extraction_snapshots):
                add_geometry(axis,projection,slow,fast)
                axis.set_aspect("auto")
                axis.set(xlim=bounds["local_x_mm"],ylim=bounds["local_y_mm"])
                rows=[row for row in snapshot_rows if row["snapshot"]==label]
                for state in ("alive","lost","extracted"):
                    selected=[row for row in rows if row["status"]==state]
                    axis.scatter([row[slow+"_mm"] for row in selected],[row[fast+"_mm"] for row in selected],color=styles[state]["color"],marker=styles[state]["marker"],s=18,label=state if state=="alive" else state+" last")
                alive=[row for row in rows if row["status"]=="alive"]
                outside=sum(not(bounds["local_x_mm"][0]<=row[slow+"_mm"]<=bounds["local_x_mm"][1] and bounds["local_y_mm"][0]<=row[fast+"_mm"]<=bounds["local_y_mm"][1]) for row in alive)
                axis.set_title(f"quench_start{time-quench:+g} us\nalive outside zoom={outside}/{len(alive)}",fontsize=8)
            for axis in list(axes.flat)[len(extraction_snapshots):]:
                axis.set_visible(False)
            _shared_legend(figure,axes.flat[0])
            figure.suptitle("LP extraction zoom: HP/outside particles remain in full apparatus view; scales differ",fontsize=10)
            figures["extraction_local_clouds"]=figure

    labels = data["contract"]["stage_labels"]
    figure, axes = plt.subplots(2, len(labels), figsize=(13, 7), squeeze=False, constrained_layout=True)
    for index, label in enumerate(labels):
        rows = [row for row in snapshot_rows if row["snapshot"] == label and row["status"] == "alive"]
        if include_projected_geometry:
            add_geometry(axes[0,index], projection, fast, transverse)
        else:
            axes[0,index].set(xlabel=f"{fast} (mm)", ylabel=f"{transverse} (mm)")
        axes[0,index].scatter([row[fast+"_mm"] for row in rows], [row[transverse+"_mm"] for row in rows], marker="o", color="#0072B2", label="alive")
        axes[1,index].scatter([row[slow+"_mm"] for row in rows], [row["v"+slow+"_mm_us"]*1000 for row in rows], marker="s", color="#0072B2")
        lp=lp_members(data,rows)
        all_sigma=float(np.std([row[slow+"_mm"] for row in rows])) if rows else None
        if lp is not None:
            axes[0,index].scatter([row[fast+"_mm"] for row in lp],[row[transverse+"_mm"] for row in lp],marker="s",facecolors="none",edgecolors="#D55E00",label="LP subset of alive")
            axes[1,index].scatter([row[slow+"_mm"] for row in lp],[row["v"+slow+"_mm_us"]*1000 for row in lp],marker="o",facecolors="none",edgecolors="#D55E00",label="LP subset of alive")
        lp_sigma=float(np.std([row[slow+"_mm"] for row in lp])) if lp else None
        sigma_text=lambda value:"n/a" if value is None else f"{value:.4g}"
        lp_text="unavailable" if lp is None else str(len(lp))
        axes[0,index].set_title(f"{label}: all alive={len(rows)}, LP={lp_text}\nsigma_{slow} all={sigma_text(all_sigma)}, LP={sigma_text(lp_sigma)} mm",fontsize=9)
        axes[1,index].set(xlabel=f"{slow} (mm)", ylabel=f"v{slow} (m/s)")
    _shared_legend(figure,axes[0,0])
    figures["stage_phase_space"] = figure
    cooling_stages = [("source (individual birth)", [dict(particle_id=p, **row) for p,row in sorted(data["sources"].items())])]
    cooling_stages.extend((label, [row for row in snapshot_rows if row["snapshot"]==label and row["status"]=="alive"]) for label in labels)
    figure, axes = plt.subplots(3,len(cooling_stages),figsize=(16,10),squeeze=False,constrained_layout=True)
    mass = data["config"]["source"]["species"]["mass_amu"]
    source_energy = sorted(row["kinetic_energy_ev"] for row in data["sources"].values())
    for column,(label,rows) in enumerate(cooling_stages):
        axis = axes[0,column]
        axis.scatter([row["particle_id"] for row in rows],[row["kinetic_energy_ev"] for row in rows],marker="o",color="#0072B2",label="observed alive")
        energy = sorted(row["kinetic_energy_ev"] for row in rows)
        stats = "no observed alive states" if not energy else f"mean={np.mean(energy):.4g}, std={np.std(energy):.4g} eV"
        axis.set(xlabel="Particle ID",ylabel="Total kinetic energy (eV)",title=f"{label}: N={len(rows)}/{len(data['sources'])}\n{stats}")
        distribution = axes[1,column]
        distribution.step(source_energy,np.arange(1,len(source_energy)+1)/len(source_energy),where="post",color="#777777",linestyle=":",label="all initial IDs")
        if energy:
            distribution.step(energy,np.arange(1,len(energy)+1)/len(energy),where="post",color="#0072B2",label="stage alive")
            matched = sorted(data["sources"][row["particle_id"]]["kinetic_energy_ev"] for row in rows)
            distribution.step(matched,np.arange(1,len(matched)+1)/len(matched),where="post",color="#D55E00",linestyle="--",label="same IDs at birth")
        distribution.set(xlabel="Total kinetic energy (eV)",ylabel="Conditional empirical CDF")
        distribution.legend(fontsize=7)
        component = axes[2,column]
        for coordinate,color,style in (("x","#0072B2","-"),("y","#D55E00","--"),("z","#009E73",":")):
            values = sorted(kinetic_energy_ev(mass,row[f"v{coordinate}_mm_us"]*1000,0,0) for row in rows)
            if values:
                component.step(values,np.arange(1,len(values)+1)/len(values),where="post",color=color,linestyle=style,label=f"E{coordinate}")
        component.set(xlabel="Directional kinetic energy (eV)",ylabel="Alive empirical CDF")
        if rows:
            component.legend(fontsize=7)
    for axis in axes.flat:
        axis.grid(alpha=.16)
    figure.suptitle("Cooling: initial versus observed alive states; N uses full source denominator\nDirectional energies include drift and RF micromotion; instantaneous snapshots are not equilibrium temperatures",fontsize=10)
    figures["cooling_stage_energy"]=figure

    figure, axes = plt.subplots(2, 3, figsize=(14, 8), constrained_layout=True)
    for particle, rows in data["tracks"].items():
        axes[0,0].plot([row["t_us"] for row in rows], [row["kinetic_energy_ev"] for row in rows], linewidth=.6, label=f"ID {particle}")
        axes[0,1].plot([row["t_us"] for row in rows], [row[slow+"_mm"] for row in rows], linewidth=.6)
    axes[0,0].set(xlabel="Instrument time (us)", ylabel="Kinetic energy (eV)", title="All recorded IDs; lines join recorded samples")
    axes[0,1].set(xlabel="Instrument time (us)", ylabel=f"{slow} (mm)")
    for state in STATES:
        axes[0,2].plot([row["t_us"] for row in evolution], [row[state] for row in evolution], color=styles[state]["color"], marker=styles[state]["marker"], markevery=max(1,len(evolution)//12), markersize=3, label=state)
    axes[0,2].set(xlabel="Instrument time (us)", ylabel="Particle count (full source denominator)")
    axes[0,2].legend(fontsize=7)
    axes[1,0].plot([row["t_us"] for row in evolution], [np.nan if row["sigma_slow_mm"] is None else row["sigma_slow_mm"] for row in evolution], color="#0072B2", marker="o", markevery=max(1,len(evolution)//12), markersize=3)
    axes[1,0].lines[0].set_label("all observed alive (includes HP)")
    axes[1,0].plot([row["t_us"] for row in evolution],[np.nan if row.get("lp_sigma_slow_mm") is None else row["lp_sigma_slow_mm"] for row in evolution],color="#D55E00",linestyle="--",marker="s",markevery=max(1,len(evolution)//12),markersize=3,label="LP-conditioned alive")
    axes[1,0].set(xlabel="Instrument time (us)", ylabel=f"sigma_{slow} (mm)", title="All alive versus LP-conditioned spread")
    axes[1,0].legend(fontsize=6)
    energy = sorted(row["kinetic_energy_ev"] for row in data["terminals"].values() if row["reason"] == "acceptance_surface")
    if energy:
        axes[1,1].step(energy, np.arange(1,len(energy)+1)/len(energy), where="post", marker="o", color="#0072B2", label=f"extracted N={len(energy)}")
        axes[1,1].legend(fontsize=7)
    axes[1,1].set(xlabel="Extraction energy (eV)", ylabel="Conditional ECDF")
    losses = [row for row in data["terminals"].values() if row["reason"] != "acceptance_surface"]
    axes[1,2].scatter([row["t_us"]-quench for row in losses], [row[slow+"_mm"] for row in losses], marker="x", color=styles["lost"]["color"])
    axes[1,2].set(xlabel="Loss time - RF quench start (us)", ylabel=f"Terminal {slow} (mm)", title="Loss positions (entity unknown unless logged)")
    for axis in axes.flat:
        axis.grid(alpha=.16)
    figures["population_evolution"] = figure
    return figures


def cooling_statistics(data: dict, snapshots: list[dict]) -> dict:
    """Keep full-source and matched-birth cohorts beside each stage distribution."""
    mass = data["config"]["source"]["species"]["mass_amu"]
    def describe(rows):
        distributions = {"total": [row["kinetic_energy_ev"] for row in rows]}
        distributions.update((axis, [kinetic_energy_ev(mass,row[f"v{axis}_mm_us"]*1000,0,0) for row in rows]) for axis in "xyz")
        return {axis: dict(count=len(values),mean_ev=float(np.mean(values)) if values else None,
                          std_ev=float(np.std(values)) if values else None,
                          quantiles_10_50_90_ev=[float(value) for value in np.quantile(values,[.1,.5,.9])] if values else None)
                for axis,values in distributions.items()}
    stages = {}
    for label in data["contract"]["stage_labels"]:
        rows = [row for row in snapshots if row["snapshot"]==label]
        alive = [row for row in rows if row["status"]=="alive"]
        stages[label] = dict(census={state:sum(row["status"]==state for row in rows) for state in STATES},
                             alive_particle_ids=[row["particle_id"] for row in alive],
                             alive=describe(alive),same_ids_at_birth=describe([data["sources"][row["particle_id"]] for row in alive]))
    return dict(schema_version=1,role="ion_processor_cooling_distributions",source_count=len(data["sources"]),
                source=describe(list(data["sources"].values())),stages=stages,
                interpretation="Instantaneous kinetic energies include drift and RF micromotion, not equilibrium temperatures. Alive distributions are conditional; matched initial IDs and full census disclose survivor selection. No no-collision counterfactual is implied.",
                standard_deviation="population, ddof=0; finite source samples are not recentered to configured distribution parameters")


def export_diagnostics(run: Path, output_directory: Path | None = None) -> dict:
    """Automatically export English sections, statistics and packet evidence."""
    run = run.resolve()
    data = prepare_data(run)
    results = run / "results" if output_directory is None else Path(output_directory).resolve()
    roles = ("structure_sections", "timed_clouds_sections", "extraction_clouds_sections",
             "stage_phase_space", "cooling_stage_energy", "population_evolution", "post_extraction_packet")
    if any((results/f"{role}.{extension}").exists() for role in roles for extension in ("png", "svg", "metadata.json")):
        raise FileExistsError("diagnostics require a fresh run output; refusing evidence overwrite")
    results.mkdir(parents=True, exist_ok=True)
    snapshots, census_rows = [], []
    maximum_used_gap = 0.0
    for label, time in data["snapshots"]:
        _, rows = census(data,time)
        snapshots.extend(dict(snapshot=label,**row) for row in rows)
    interval = data["contract"]["evolution_interval_us"]
    last = data["config"]["baseline"]["schedule"]["terminal_us"]
    times = sorted({*(float(t) for t in np.arange(0,last,interval)), last, *(time for _,time in data["snapshots"])})
    for time in times:
        counts,states = census(data,time)
        maximum_used_gap = max(maximum_used_gap, max((row["bracket_gap_us"] or 0 for row in states if row["status"] == "alive"), default=0))
        census_rows.append(counts)
    snapshot_fields = ["snapshot", "particle_id", "t_us", "status", "reason", "electrode_id", "bracket_start_us", "bracket_end_us", "bracket_gap_us", *VALUES, "kinetic_energy_ev"]
    _write_csv(results / "diagnostic_snapshots.csv",snapshots,snapshot_fields)
    _write_csv(results / "diagnostic_census.csv",census_rows,list(census_rows[0]))
    losses = [dict(particle_id=particle,**row) for particle,row in sorted(data["terminals"].items()) if row["reason"] != "acceptance_surface"]
    _write_csv(results / "diagnostic_losses.csv",losses,["particle_id","t_us",*VALUES,"kinetic_energy_ev","reason","electrode_id"])
    (results / "cooling_distributions.json").write_text(json.dumps(cooling_statistics(data,snapshots),indent=2,allow_nan=False)+"\n",encoding="utf-8")
    repo = Path(__file__).resolve().parents[3]
    context_path=run/"inputs/source_context.json"
    if context_path.is_file():
        context=_json(context_path)
        git=dict(sha=context.get("git_sha",context.get("sha","unavailable")),worktree=context.get("worktree_porcelain",context.get("worktree","unavailable")),source="frozen inputs/source_context.json",source_sha256=file_sha256(context_path))
    else:
        git = {}
        for key,args in (("sha",["rev-parse","HEAD"]),("worktree",["status","--porcelain"])):
            result = subprocess.run(["git","-C",str(repo),*args],capture_output=True,text=True,encoding="utf-8",errors="replace",check=False,cwd=repo,timeout=10)
            git[key] = result.stdout.strip() if result.returncode == 0 else "unavailable"
        git["source"]="live repository fallback; frozen source context absent"
    source_paths = [run/relative for relative in ("inputs/resolved_model.json","inputs/diagnostics.json","simion/events.csv","simion/samples.csv","results/particle_state.csv")]
    if context_path.is_file():
        source_paths.append(context_path)
    metadata = dict(schema_version=1, role="ion_processor_diagnostic_figure", source_run=str(run), source_profile=data["config"].get("source_profile"), source_particle_count=len(data["sources"]), displayed_particle_ids=sorted(data["sources"]), source_records=[dict(path=str(path),sha256=file_sha256(path),bytes=path.stat().st_size) for path in source_paths], git=git, code_sha256=PRODUCER_SOURCE_SHA256, frame_id=data["config"].get("coordinate_transform", {}).get("to_frame_id",data["config"]["baseline"]["clock"]["frame_id"]), coordinate_transform=data["config"].get("coordinate_transform"), sigma_csv_compatibility="new frames use sigma_slow_mm/lp_sigma_slow_mm with explicit sigma_axis; sigma_x aliases exist only for legacy local-axis runs", units=dict(position="mm",velocity="mm/us in CSV; m/s phase-space display",time="instrument absolute us",energy="eV"), selection="full-range views preserve all source IDs; explicitly conditional LP zoom and per-stage alive energy details accompany full-cohort views; no KDE, smoothing, fitting or subsampling", display_bounds=display_bounds(data), interpolation="display only; linear between adjacent recorded positions/velocities within frozen bracket limit; energy recomputed from interpolated velocity", maximum_used_interpolation_gap_us=maximum_used_gap, pulse_timing=pulse_timing_context(data), snapshot_census=[dict(label=label,**census(data,time)[0]) for label,time in data["snapshots"]], lp_conditioning="alive with guide_length+hp_length < slow_coordinate < guide_length+hp_length+lp_length; slow=project y for transformed runs, local x for legacy; no detector-outcome selection; global sigma includes HP-retained ions", geometry_provenance="statistical panels contain no projected electrode boxes; separate section panels consume frozen CSG solids/cutouts and declare any projected E9 footprints explicitly", geometry_sha256=file_sha256(run/"inputs/resolved_model.json"), display_claim="all recorded trajectories and bounded display interpolation, not every integration step; lost/extracted points are last positions, never alive clouds", uncertainty="none; N10 exploration or N100 functional only", numerical_or_GUI_qualification=False)
    figures = build_figures(data,snapshots,census_rows,include_projected_geometry=False)
    output_roles = []
    for role,figure in figures.items():
        outputs = []
        for extension in ("png","svg"):
            path = results / f"{role}.{extension}"
            if path.exists():
                raise FileExistsError("refuse to overwrite published diagnostic figure")
            temporary = path.with_suffix(path.suffix+".tmp")
            figure.savefig(temporary,format=extension,dpi=data["contract"]["png_dpi"],facecolor="white")
            temporary.replace(path)
            outputs.append(dict(path=str(path),sha256=file_sha256(path),format=extension))
        figure_metadata = {**metadata,"figure_role":role,"size_inches":list(figure.get_size_inches()),"dpi":data["contract"]["png_dpi"],"outputs":outputs}
        (results/f"{role}.metadata.json").write_text(json.dumps(figure_metadata,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        plt.close(figure)
        output_roles.append(role)
    # Mandatory default panels consume the just-written common snapshot table
    # and this run's actual events/samples. No task wrapper or fixed timestamp.
    export_sections(run, results)
    export_post_extraction(run, results)
    for role in ("structure_sections", "timed_clouds_sections", "extraction_clouds_sections", "post_extraction_packet"):
        for extension in ("png", "svg", "metadata.json"):
            if not (results / f"{role}.{extension}").is_file():
                raise ValueError(f"mandatory default diagnostic output missing: {role}.{extension}")
        output_roles.append(role)
    packet_statistics = _json(results / "post_extraction_statistics.json")
    packet_status = packet_statistics.get("packet_status", packet_statistics.get("status"))
    if not isinstance(packet_status, str) or not packet_status:
        raise ValueError("post-extraction diagnostics must declare meaningful availability status")
    for filename in ("post_extraction_plane_states.csv", "post_extraction_common_time_states.csv"):
        if not (results / filename).is_file():
            raise ValueError(f"required post-extraction table missing: {filename}")
    summary=dict(schema_version=1,role="ion_processor_diagnostics_summary",post_extraction_status=packet_status,source_particle_count=len(data["sources"]),figure_roles=output_roles,all_recorded_particle_ids=True,snapshot_count=len(data["snapshots"]),census_rows=len(census_rows),loss_count=len(losses),qualification="diagnostic_only_no_physics_or_GUI_pass",maximum_used_interpolation_gap_us=metadata["maximum_used_interpolation_gap_us"])
    (results/"diagnostics_summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    return summary
