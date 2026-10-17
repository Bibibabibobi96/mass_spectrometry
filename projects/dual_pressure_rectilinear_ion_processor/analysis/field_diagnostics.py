"""Analyze read-only native PA samples; fits diagnose fields and never replace them."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import (
    to_project_position, to_project_vector, transform_from_config,
)


NUMERIC_COLUMNS = ("t_us", "x_mm", "y_mm", "z_mm", "potential_v", "ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm")
PRODUCER_SOURCE_PATH = Path(__file__).resolve()
# Capture at module import: a later worktree edit must not relabel the source
# that this process actually loaded as though it were the newly edited file.
PRODUCER_SOURCE_SHA256 = file_sha256(PRODUCER_SOURCE_PATH)


def source_context(run: Path) -> dict[str, Any]:
    """Read frozen repository context, or report a bounded live Git observation."""
    path = run/"inputs/source_context.json"
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if "git_sha" not in value or "worktree_dirty" not in value:
            raise ValueError("frozen source_context lacks Git identity fields")
        return {**value, "origin": "frozen_inputs_source_context", "available": bool(value["git_sha"])}
    root = PRODUCER_SOURCE_PATH.parents[3]
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                  text=True, timeout=10, check=False)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True,
                                text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"origin": "live_git_fallback", "available": False, "git_sha": None,
                "worktree_dirty": None, "unavailable_reason": str(error)}
    if revision.returncode != 0 or status.returncode != 0:
        return {"origin": "live_git_fallback", "available": False, "git_sha": None,
                "worktree_dirty": None, "unavailable_reason": "Git identity unavailable at executing module root"}
    return {"origin": "live_git_fallback", "available": True, "git_sha": revision.stdout.strip(),
            "worktree_dirty": bool(status.stdout.strip())}


def producer_identity(run: Path) -> dict[str, Any]:
    """Separate actually imported producer identity from its frozen run copy."""
    relative = Path("inputs/code/projects/dual_pressure_rectilinear_ion_processor/analysis/field_diagnostics.py")
    frozen = run/relative
    frozen_hash = file_sha256(frozen) if frozen.is_file() else None
    return {"actual_source_path": str(PRODUCER_SOURCE_PATH), "actual_source_sha256": PRODUCER_SOURCE_SHA256,
            "actual_source_capture": "module_import", "frozen_source_path": relative.as_posix(),
            "frozen_source_sha256": frozen_hash,
            "matches_frozen": frozen_hash == PRODUCER_SOURCE_SHA256 if frozen_hash is not None else None}


def validate_field_diagnostics_config(config: dict[str, Any]) -> None:
    """Reject unknown sampling controls, nonfinite inputs and unsupported stages."""
    keys = {"schema_version", "epsilon_us", "stages", "sections", "section_radius_scale", "fit_radius_scale",
            "section_grid_multiple", "axial_grid_multiple", "orthogonal_grid_multiple", "quiver_stride",
            "maximum_samples", "figure_width_mm", "figure_height_mm", "dpi"}
    if set(config) != keys or config["schema_version"] != 1:
        raise ValueError("unsupported field diagnostics schema/fields")
    for key in keys - {"schema_version", "stages", "sections"}:
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"field diagnostics {key} must be positive and finite")
    for key in ("section_grid_multiple", "axial_grid_multiple", "orthogonal_grid_multiple", "quiver_stride", "maximum_samples", "dpi"):
        if int(config[key]) != config[key]:
            raise ValueError(f"field diagnostics {key} must be integer")
    if config["fit_radius_scale"] >= config["section_radius_scale"]:
        raise ValueError("fit radius must lie inside sampled cross sections")
    seen = set()
    for stage in config["stages"]:
        if set(stage) != {"stage_id", "time_ref", "component"} or not stage["stage_id"] or stage["stage_id"] in seen:
            raise ValueError("invalid/duplicate field stage")
        seen.add(stage["stage_id"])
        if stage["time_ref"] not in {"capture_mid", "transfer_mid", "pre_extraction", "quench_mid", "pulse_after"}:
            raise ValueError("unsupported field time reference")
        if stage["component"] not in {"dc", "rf_only_peak", "total"}:
            raise ValueError("unsupported native field component")
    if not seen:
        raise ValueError("field stages cannot be empty")
    seen = set()
    for section in config["sections"]:
        expected = {"section_id", "position_ref"}
        if section.get("position_ref") == "hp_fraction":
            expected.add("fraction")
            fraction = section["fraction"]
            if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 < fraction < 1:
                raise ValueError("HP section fraction must be in (0,1)")
        elif section.get("position_ref") != "lp_center":
            raise ValueError("unsupported native field section")
        if set(section) != expected or not section["section_id"] or section["section_id"] in seen:
            raise ValueError("invalid/duplicate field section")
        seen.add(section["section_id"])
    if not seen:
        raise ValueError("field sections cannot be empty")


def field_gu_to_v_per_mm(field_v_per_gu: np.ndarray, grid_mm: float) -> np.ndarray:
    """Convert official negative-gradient field components once, preserving sign."""
    if not math.isfinite(grid_mm) or grid_mm <= 0:
        raise ValueError("grid_mm must be positive and finite")
    field = np.asarray(field_v_per_gu, dtype=float)
    if not np.isfinite(field).all():
        raise ValueError("nonfinite native electric field")
    return field / grid_mm


def fit_transverse_quadratic(rows: list[dict], radius_mm: float) -> dict[str, Any]:
    """Fit phi=a0+ay*y+az*z+ayy*y²+ayz*y*z+azz*z² inside a circle.

    Input potentials are native PA samples [V], positions [mm]. Electrode nodes
    remain recorded but are excluded from this diagnostic least-squares fit.
    No threshold or convergence classification is attached to the residual.
    """
    selected = [r for r in rows if not r["electrode"] and math.hypot(r["y_mm"], r["z_mm"]) <= radius_mm + 1e-12]
    if len(selected) < 6:
        raise ValueError("quadratic fit needs at least six vacuum samples")
    y = np.array([r["y_mm"] for r in selected]); z = np.array([r["z_mm"] for r in selected])
    potential = np.array([r["potential_v"] for r in selected])
    matrix = np.column_stack((np.ones_like(y), y, z, y*y, y*z, z*z))
    if not np.isfinite(matrix).all() or not np.isfinite(potential).all():
        raise ValueError("nonfinite quadratic fit input")
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, potential, rcond=None)
    if rank != 6:
        raise ValueError("quadratic fit sample geometry is rank deficient")
    residual = potential - matrix @ coefficients
    return {"sample_count": len(selected), "radius_mm": radius_mm,
            "phi0_v": float(coefficients[0]), "linear_y_v_per_mm": float(coefficients[1]),
            "linear_z_v_per_mm": float(coefficients[2]),
            "curvature_yy_v_per_mm2": float(2*coefficients[3]),
            "mixed_yz_v_per_mm2": float(coefficients[4]),
            "curvature_zz_v_per_mm2": float(2*coefficients[5]),
            "residual_rms_v": float(np.sqrt(np.mean(residual**2))), "qualification": "diagnostic_only_no_pass_threshold"}


def read_field_samples(path: Path, config: dict) -> list[dict]:
    """Read the canonical native-field CSV, refusing invalid or foreign samples."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {"stage_id", "section_id", "sample_kind", "electrode", *NUMERIC_COLUMNS}
        if set(reader.fieldnames or []) != expected:
            raise ValueError("native field sample columns differ")
        raw = list(reader)
    if not raw or len(raw) > config["maximum_samples"]:
        raise ValueError("empty or over-budget native field samples")
    stages = {r["stage_id"] for r in config["stages"]}
    sections = {r["section_id"] for r in config["sections"]}
    rows, seen = [], set()
    for row in raw:
        if row["stage_id"] not in stages or row["sample_kind"] not in {"axial", "orthogonal", "cross_section"}:
            raise ValueError("unknown native field stage/sample kind")
        if row["section_id"] not in sections | {"axis", "lp_exit"}:
            raise ValueError("unknown native field section")
        parsed = {**row, **{key: float(row[key]) for key in NUMERIC_COLUMNS}}
        if not all(math.isfinite(parsed[key]) for key in NUMERIC_COLUMNS) or row["electrode"] not in {"0", "1"}:
            raise ValueError("nonfinite field sample or invalid electrode mask")
        parsed["electrode"] = int(row["electrode"])
        identity = tuple(parsed[key] for key in ("stage_id", "section_id", "sample_kind", "x_mm", "y_mm", "z_mm"))
        if identity in seen:
            raise ValueError("duplicate native field sample")
        seen.add(identity); rows.append(parsed)
    return rows


def project_field_rows(rows: list[dict], config: dict) -> list[dict]:
    """Rotate native sample positions and E vectors; potential/time/mask are scalars."""
    transformed = []
    for row in rows:
        xyz = to_project_position(config, [row[key] for key in ("x_mm", "y_mm", "z_mm")])
        field = to_project_vector(config, [row[key] for key in ("ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm")])
        transformed.append({**row, **dict(zip(("x_mm", "y_mm", "z_mm"), xyz)),
                            **dict(zip(("ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm"), field))})
    return transformed


def build_line_figure(rows: list[dict], config: dict, kind: str) -> tuple[Any, Any]:
    """Plot actual PA potential and field samples; metal nodes are visible gaps."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure = Figure(figsize=(config["figure_width_mm"]/25.4, config["figure_height_mm"]/25.4), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 1, sharex=True)
    project = config.get("_project_coordinates", False)
    if project:
        coordinate, component = ("y_mm", "ey_v_per_mm") if kind == "axial" else ("z_mm", "ez_v_per_mm")
    else:
        coordinate, component = ("x_mm", "ex_v_per_mm") if kind == "axial" else ("y_mm", "ey_v_per_mm")
    styles = ("-", "--", "-.", ":")
    colors = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#CC79A7", "#000000")
    for index, stage in enumerate(config["stages"]):
        group = sorted([r for r in rows if r["stage_id"] == stage["stage_id"] and r["sample_kind"] == kind], key=lambda r: r[coordinate])
        if not group:
            raise ValueError(f"missing native line samples: {stage['stage_id']} {kind}")
        x = [r[coordinate] for r in group]
        for ax, key in zip(axes, ("potential_v", component)):
            values = [np.nan if r["electrode"] else r[key] for r in group]
            ax.plot(x, values, label=stage["stage_id"], color=colors[index % len(colors)], linestyle=styles[index % len(styles)], linewidth=1)
    axes[0].set_ylabel("Potential (V)"); axes[1].set_ylabel(f"E_{coordinate[0]} (V/mm)")
    axes[1].set_xlabel(f"{coordinate[0]} (mm)")
    axes[0].legend(fontsize=7, ncol=2, loc="best")
    axes[0].set_title(f"Native electrode field: {kind} cut", fontsize=10)
    return figure, axes


def build_transfer_line_figure(rows: list[dict], config: dict, baseline: dict) -> tuple[Any, Any]:
    """Show capture/transfer DC on the HP and first 15 mm of LP, without rebasing.

    The 15 mm extension is the requested diagnostic display window only; it
    changes no scientific input, sampled potential, field, or fit definition.
    """
    lower = baseline["geometry"]["guide_length_mm"]
    upper = lower + baseline["geometry"]["hp_length_mm"] + 15
    subset_config = {**config, "stages": [stage for stage in config["stages"]
                                         if stage["stage_id"] in {"capture_dc", "transfer_dc"}]}
    if len(subset_config["stages"]) != 2:
        raise ValueError("transfer detail requires capture_dc and transfer_dc stages")
    coordinate = "y_mm" if config.get("_project_coordinates") else "x_mm"
    component = "ey_v_per_mm" if config.get("_project_coordinates") else "ex_v_per_mm"
    subset = [row for row in rows if row["sample_kind"] == "axial" and lower <= row[coordinate] <= upper]
    figure, axes = build_line_figure(subset, subset_config, "axial")
    selected_ids = {stage["stage_id"] for stage in subset_config["stages"]}
    visible = [row for row in subset if row["stage_id"] in selected_ids and not row["electrode"]]
    for ax, key in zip(axes, ("potential_v", component)):
        values = [row[key] for row in visible]
        if not values:
            raise ValueError("transfer detail has no vacuum samples inside its viewport")
        minimum, maximum = min(values), max(values)
        margin = .05*(maximum-minimum) if maximum > minimum else .05*max(abs(maximum),1)
        ax.set_ylim(minimum-margin,maximum+margin)
        ax.set_xlim(lower,upper)
    axes[0].set_title(f"Capture/transfer DC; {coordinate[0]}={lower:g} to {upper:g} mm (cropped)", fontsize=10)
    return figure, axes


def section_metal_rectangles(electrode: dict, x_mm: float) -> list[tuple[float, float, float, float]]:
    """Slice box solids and subtract box apertures before drawing metal outlines."""
    rectangles = []
    for shape in electrode["solids"]:
        if shape["shape"] != "box" or not shape["min_mm"][0] <= x_mm <= shape["max_mm"][0]:
            continue
        lo, hi = shape["min_mm"], shape["max_mm"]
        pieces = [(lo[1], lo[2], hi[1], hi[2])]
        for cut in electrode["cutouts"]:
            if cut["shape"] != "box" or not cut["min_mm"][0] <= x_mm <= cut["max_mm"][0]:
                continue
            next_pieces = []
            for y0, z0, y1, z1 in pieces:
                cy0, cz0 = max(y0, cut["min_mm"][1]), max(z0, cut["min_mm"][2])
                cy1, cz1 = min(y1, cut["max_mm"][1]), min(z1, cut["max_mm"][2])
                if cy0 >= cy1 or cz0 >= cz1:
                    next_pieces.append((y0, z0, y1, z1)); continue
                candidates = [(y0,z0,cy0,z1),(cy1,z0,y1,z1),(cy0,z0,cy1,cz0),(cy0,cz1,cy1,z1)]
                next_pieces.extend(r for r in candidates if r[2] > r[0] and r[3] > r[1])
            pieces = next_pieces
        rectangles.extend(pieces)
    return sorted(set(rectangles))


def add_electrode_outlines(ax: Any, projection: dict, x_mm: float, transform_config: dict | None = None) -> None:
    """Overlay actual cross-section metal rectangles with electrode ID labels."""
    from matplotlib.patches import Rectangle
    for electrode in projection["electrodes"]:
        for y0, z0, y1, z1 in section_metal_rectangles(electrode, x_mm):
            if transform_config is not None:
                corners = [to_project_position(transform_config, (x_mm,y,z)) for y,z in ((y0,z0),(y1,z1))]
                y0,y1 = sorted(point[2] for point in corners)
                z0,z1 = sorted(point[0] for point in corners)
            ax.add_patch(Rectangle((y0,z0), y1-y0, z1-z0, fill=False, edgecolor="black", linewidth=.7))
            ax.text((y0+y1)/2, (z0+z1)/2, str(electrode["electrode_id"]), fontsize=7, ha="center", va="center", clip_on=True)


def build_section_figure(rows: list[dict], config: dict, projection: dict, stage_id: str,
                         limit_v: float, quiver_scale_v_per_mm: float | None = None) -> tuple[Any, Any]:
    """Render equal-aspect cross sections with one shared symmetric color scale."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import Normalize
    figure = Figure(figsize=(config["figure_width_mm"]/25.4, config["figure_height_mm"]/25.4), layout="constrained")
    FigureCanvasAgg(figure)
    axes = np.atleast_1d(figure.subplots(1, len(config["sections"]), sharex=True, sharey=True))
    project = config.get("_project_coordinates", False)
    horizontal, vertical = ("z_mm", "x_mm") if project else ("y_mm", "z_mm")
    horizontal_field, vertical_field = ("ez_v_per_mm", "ex_v_per_mm") if project else ("ey_v_per_mm", "ez_v_per_mm")
    norm = Normalize(vmin=-limit_v, vmax=limit_v)
    arrow_scale = limit_v if quiver_scale_v_per_mm is None else quiver_scale_v_per_mm
    for ax, section in zip(axes, config["sections"]):
        group = [r for r in rows if r["stage_id"] == stage_id and r["sample_kind"] == "cross_section" and r["section_id"] == section["section_id"]]
        if not group:
            raise ValueError("missing native cross section")
        ys, zs = sorted({r[horizontal] for r in group}), sorted({r[vertical] for r in group})
        if len(group) != len(ys)*len(zs):
            raise ValueError("native cross section is not a complete rectangular sample grid")
        lookup = {(r[horizontal], r[vertical]): r for r in group}
        arrays = {key: np.array([[np.nan if lookup[y,z]["electrode"] else lookup[y,z][key] for y in ys] for z in zs])
                  for key in ("potential_v", horizontal_field, vertical_field)}
        image = ax.pcolormesh(ys, zs, arrays["potential_v"], shading="nearest", cmap="RdBu_r", norm=norm)
        stride = config["quiver_stride"]
        yy, zz = np.meshgrid(ys, zs)
        ax.quiver(yy[::stride,::stride], zz[::stride,::stride], arrays[horizontal_field][::stride,::stride], arrays[vertical_field][::stride,::stride],
                  angles="xy", scale_units="xy", scale=arrow_scale, width=.005, color="black")
        ax.quiverkey(ax.collections[-1], .5, -.35, arrow_scale/2, f"{arrow_scale/2:.2g} V/mm", coordinates="axes", fontproperties={"size":7})
        local_x = group[0]["y_mm"] if project else group[0]["x_mm"]
        add_electrode_outlines(ax, projection, local_x, config.get("_transform_config"))
        ax.set_xlim(ys[0], ys[-1]); ax.set_ylim(zs[0], zs[-1]); ax.set_aspect("equal")
        ax.set_xlabel(f"{horizontal[0]} (mm)")
        section_axis = "y" if project else "x"
        ax.set_title(f"{section['section_id']}\n{section_axis}={local_x:g} mm", fontsize=8)
    axes[0].set_ylabel(f"{vertical[0]} (mm)")
    figure.colorbar(image, ax=list(axes), label="Native potential (V)", shrink=.7)
    figure.suptitle(stage_id, fontsize=10)
    return figure, axes


def export_field_diagnostics(run: Path, output_directory: Path | None = None) -> dict[str, Any]:
    """Export diagnostic PNG/SVG/JSON from frozen native CSV and config, no solver.

    The caller owns run lifecycle and must include outputs in its final manifest.
    Existing diagnostic metadata is refused to avoid overwriting published plots.
    """
    c = json.loads((run/"inputs/resolved_model.json").read_text(encoding="utf-8"))
    config = c["field_diagnostics"]
    validate_field_diagnostics_config(config)
    output = run/"results" if output_directory is None else Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata_path = output/"field_diagnostics.json"
    if metadata_path.exists():
        raise FileExistsError("native field diagnostics already exported; use a new run")
    source = run/"simion/native_field_samples.csv"
    rows = read_field_samples(source, config)
    fits = []
    rf_stages = {r["stage_id"] for r in config["stages"] if r["component"] == "rf_only_peak"}
    components = {stage["stage_id"]: stage["component"] for stage in config["stages"]}
    component_limits, arrow_scales = {}, {}
    for component in set(components.values()):
        subset = [r for r in rows if r["sample_kind"] == "cross_section" and not r["electrode"] and components[r["stage_id"]] == component]
        maximum = max((abs(r["potential_v"]) for r in subset), default=0)
        component_limits[component] = maximum if maximum > 0 else 1.0
        field_max = max((math.hypot(r["ey_v_per_mm"], r["ez_v_per_mm"]) for r in subset), default=0)
        arrow_scales[component] = field_max if field_max > 0 else 1.0
    outputs = []
    plot_rows, plot_config = rows, config
    if "coordinate_transform" in c:
        plot_rows = project_field_rows(rows, c)
        plot_config = {**config, "_project_coordinates": True, "_transform_config": c}
        project_csv = output/"native_field_samples_project.csv"
        with project_csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(plot_rows[0]))
            writer.writeheader(); writer.writerows(plot_rows)
        outputs.append({"path": str(project_csv.relative_to(run)) if project_csv.is_relative_to(run) else str(project_csv), "sha256": file_sha256(project_csv)})

    def save(figure: Any, name: str) -> None:
        from matplotlib import pyplot as plt
        for extension in ("png", "svg"):
            path = output/(name+"."+extension)
            figure.savefig(path, format=extension, dpi=config["dpi"], facecolor="white")
            outputs.append({"path": str(path.relative_to(run)) if path.is_relative_to(run) else str(path), "sha256": file_sha256(path)})
        plt.close(figure)

    for kind in ("axial", "orthogonal"):
        figure, _ = build_line_figure(plot_rows, plot_config, kind)
        save(figure, "native-field__"+kind)
    if {"capture_dc", "transfer_dc"} <= {stage["stage_id"] for stage in config["stages"]}:
        figure, _ = build_transfer_line_figure(plot_rows, plot_config, c["baseline"])
        save(figure, "native-field__axial-transfer")
    scales = {}
    for stage in config["stages"]:
        stage_id = stage["stage_id"]
        group = [r for r in rows if r["stage_id"] == stage_id and r["sample_kind"] == "cross_section"]
        limit = component_limits[stage["component"]]
        scales[stage_id] = [-limit, limit]
        figure, _ = build_section_figure(plot_rows, plot_config, c["native_projection"], stage_id, limit, arrow_scales[stage["component"]])
        save(figure, "native-field__"+stage_id)
        if stage_id in rf_stages:
            for section in config["sections"]:
                subset = [r for r in group if r["section_id"] == section["section_id"]]
                fits.append({"stage_id": stage_id, "section_id": section["section_id"],
                             **fit_transverse_quadratic(subset, config["fit_radius_scale"]*c["baseline"]["geometry"]["r0_mm"])})
    context = source_context(run)
    native = Path(c["native_field"]["directory"])/"processor.pa0"
    face_y = c["baseline"]["geometry"]["extraction_end_y_mm"]
    face_samples = [{key: row[key] for key in ("t_us","x_mm","y_mm","z_mm","potential_v","ey_v_per_mm","electrode")}
                    for row in rows if row["stage_id"] == "pulse_total" and row["sample_kind"] == "orthogonal"
                    and abs(row["y_mm"]-face_y) <= 1e-9]
    metadata = {"schema_version": 1, "role": "native_field_diagnostics", "run_id": run.name,
                "qualification": "native_PA_sampling_and_local_fit_not_convergence_or_performance",
                "git_sha": context["git_sha"], "worktree_dirty": context["worktree_dirty"],
                "source_context": context, "producer": producer_identity(run),
                "frame_id": transform_from_config(c).to_frame_id,
                "local_frame_id": c["baseline"]["clock"]["frame_id"],
                "raw_sample_frame_id": c["baseline"]["clock"]["frame_id"],
                "project_transform": c.get("coordinate_transform"),
                "plot_frame_id": transform_from_config(c).to_frame_id,
                "fit_coordinate_system": {"frame_id": c["baseline"]["clock"]["frame_id"],
                                          "variables": ["local_y_mm", "local_z_mm"],
                                          "project_basis_mapping": {"local_y": list(to_project_vector(c,(0,1,0))),
                                                                    "local_z": list(to_project_vector(c,(0,0,1)))},
                                          "coefficient_axis_mapping": {"linear_y_v_per_mm": "local_y",
                                                                       "linear_z_v_per_mm": "local_z",
                                                                       "curvature_yy_v_per_mm2": "local_y,local_y",
                                                                       "mixed_yz_v_per_mm2": "local_y,local_z",
                                                                       "curvature_zz_v_per_mm2": "local_z,local_z"},
                                          "coefficient_names_use_local_axes": True},
                "units": {"position": "mm", "time": "us", "potential": "V", "electric_field": "V/mm"},
                "sample_count": len(rows), "electrode_samples_masked": sum(r["electrode"] for r in rows),
                "raw_samples_sha256": file_sha256(source), "native_pa0_sha256": file_sha256(native),
                "resolved_config_sha256": file_sha256(run/"inputs/resolved_model.json"),
                "native_field_identity": c["native_field"], "sampling_and_plot_config": config,
                "native_timing": c.get("native_timing", {"policy":"legacy_requested_quench", "scope":"historical frozen native query; no zero alignment retroactively applied"}),
                "field_units_conversion": "field_vc negative gradient V/GU divided by grid_mm; sign retained",
                "transformations": "nearest-node electrode mask; cross-section crop to configured radius scale; declared rigid position/vector transform for project plots/CSV; no smoothing/interpolation/extrapolation; unweighted quadratic vacuum fit in local_y-local_z circle",
                "color_comparison_groups": "shared limits across all stages with the same native field component: dc, rf_only_peak, total",
                "quiver_scales_v_per_mm": arrow_scales,
                "postpulse_measurement_face": {"frame_id": c["baseline"]["clock"]["frame_id"], "requested_local_y_mm": face_y, "requested_y_mm": face_y,
                                               "status": "exact_raw_samples" if face_samples else "not_sampled_no_interpolation",
                                               "samples": face_samples},
                "transfer_viewport": {"axis": "project_y" if "coordinate_transform" in c else "local_x", "stages": ["capture_dc","transfer_dc"],
                                      "x_min_mm": c["baseline"]["geometry"]["guide_length_mm"],
                                      "x_max_mm": c["baseline"]["geometry"]["guide_length_mm"]+c["baseline"]["geometry"]["hp_length_mm"]+15,
                                      "display_only": True, "potential_rebased": False},
                "fits": fits, "symmetric_color_limits_v": scales, "outputs": outputs}
    metadata_path.write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return metadata
