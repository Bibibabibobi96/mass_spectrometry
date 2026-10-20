"""Export bounded IP/P1 geometry sections and native nominal-axis field probes.

Geometry is rasterized from the actual frozen CSG at an explicitly off-axis
x section. Field profiles are fixed-axis probes, never particle-force samples.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from common.contracts.write_run_manifest import file_record


def _shape_mask(shape: dict, x: float, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    if shape["shape"] == "convex_polyhedron":
        from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import convex_planes
        mask = np.ones(np.broadcast(x, y, z).shape, dtype=bool)
        for a, b, c, d in convex_planes(shape):
            mask &= a*x+b*y+c*z+d <= 0
        return mask
    if shape["shape"] == "box":
        low, high = shape["min_mm"], shape["max_mm"]
        return ((low[0] <= x <= high[0]) & (y >= low[1]) & (y <= high[1])
                & (z >= low[2]) & (z <= high[2]))
    a, b = np.asarray(shape["endpoints_mm"], float)
    direction = b - a
    length2 = float(direction @ direction)
    if length2 <= 0:
        raise ValueError("degenerate CSG cylinder")
    fraction = ((x-a[0])*direction[0] + (y-a[1])*direction[1] + (z-a[2])*direction[2])/length2
    distance2 = ((x-a[0]-fraction*direction[0])**2 + (y-a[1]-fraction*direction[1])**2
                 + (z-a[2]-fraction*direction[2])**2)
    return (fraction >= 0) & (fraction <= 1) & (distance2 <= shape["radius_mm"]**2)


def _polygon_mask(part: dict, x: float, points: np.ndarray, shape: tuple) -> np.ndarray:
    from matplotlib.path import Path as PlotPath
    if not part["x"][0] <= x <= part["x"][1]:
        return np.zeros(shape, bool)
    return PlotPath(part["polygon_yz_mm"]).contains_points(points).reshape(shape)


def _section(geometry: dict, x: float, box: list, pixel_mm: float) -> tuple[np.ndarray, list]:
    """Evaluate CSG at pixel centres; resolution is a declared display control."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import _bounds
    ny, nz = [int(np.ceil((box[a+3]-box[a])/pixel_mm)) for a in (1, 2)]
    ys = box[1] + (np.arange(ny)+0.5)*(box[4]-box[1])/ny
    zs = box[2] + (np.arange(nz)+0.5)*(box[5]-box[2])/nz
    image = np.zeros((ny, nz), np.uint8)
    for electrode in geometry["ion_processor_electrodes"]:
        for solid in electrode["solids"]:
            bounds = _bounds(solid)
            if not bounds[0] <= x <= bounds[3]:
                continue
            yi = np.flatnonzero((ys >= bounds[1]) & (ys <= bounds[4]))
            zi = np.flatnonzero((zs >= bounds[2]) & (zs <= bounds[5]))
            if not len(yi) or not len(zi):
                continue
            y, z = np.meshgrid(ys[yi], zs[zi], indexing="ij")
            mask = _shape_mask(solid, x, y, z)
            for hole in electrode["cutouts"]:
                mask &= ~_shape_mask(hole, x, y, z)
            region = image[np.ix_(yi, zi)]
            region[mask] = 2 if electrode["electrode_id"] == 14 else 1
            image[np.ix_(yi, zi)] = region
    y, z = np.meshgrid(ys, zs, indexing="ij")
    points = np.column_stack((y.ravel(), z.ravel()))
    for shield in geometry["prism_ground_shields"]:
        mask = np.zeros(image.shape, bool)
        for body in shield["body_sections"]:
            mask |= _polygon_mask(body, x, points, image.shape)
        mask &= ~_polygon_mask(dict(x=shield["x"], polygon_yz_mm=shield["prism_clearance_polygon_yz_mm"]), x, points, image.shape)
        for slot in shield["rectangular_slots_mm"]:
            mask &= ~_shape_mask(dict(shape="box", min_mm=slot[:3], max_mm=slot[3:]), x, y, z)
        image[mask] = 3
    for electrode in geometry["prism_electrodes"]:
        for part in electrode["parts"]:
            image[_polygon_mask(part, x, points, image.shape)] = 4
    return image, [box[2], box[5], box[1], box[4]]


def _geometry_figure(cases: list, box: list, section_x: float, pixel: float):
    from matplotlib import pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    colors = ["white", "#b9b9b9", "#444444", "#56B4E9", "#E69F00"]
    rows = (len(cases)+1)//2
    figure, axes = plt.subplots(rows, 2, figsize=(16, 5*rows), sharex=True, sharey=True, squeeze=False)
    for ax, case in zip(axes.flat, cases):
        prepared = case["prepared"]
        image, extent = _section(prepared["geometry"], section_x, box, pixel)
        ax.imshow(image, origin="lower", extent=extent, interpolation="nearest",
                  cmap=ListedColormap(colors), vmin=0, vmax=4, aspect="equal")
        exit_z = prepared["exit_z_mm"]
        nominal_y = prepared["geometry_checks"]["nominal_y_mm"]
        shield = prepared["geometry"]["prism_ground_shields"][0]
        front = shield["extension_to_accelerator_exit"]["resolved_end_z_mm"]
        ax.axvline(exit_z, color="black", linewidth=1)
        ax.text(exit_z+1, box[4]-2, f"Source plane\nz={exit_z:.3f} mm", va="top", fontsize=8)
        near_z = prepared["projected_near_z_mm"]
        ax.plot(near_z, nominal_y, marker="+", color="black", markersize=7)
        ax.text(near_z-2, nominal_y+2, f"Near edge\nz={near_z:.3f}", ha="right", fontsize=7,
                bbox=dict(facecolor="white", alpha=0.8, edgecolor="none", pad=1))
        ax.annotate("E14 to shield: 1 mm", xy=(front+0.5, nominal_y-16),
                    xytext=(exit_z+12, box[1]+8), fontsize=8,
                    arrowprops=dict(arrowstyle="->", color="#444444"))
        ax.annotate("P1", xy=(-65, -47), xytext=(-86, -29), fontsize=9,
                    arrowprops=dict(arrowstyle="->", color="black"))
        ax.annotate("Ground shield", xy=(-95, -75), xytext=(-118, -91), fontsize=8,
                    arrowprops=dict(arrowstyle="->", color="black"))
        ax.set_title(f"D = {case['distance_mm']:.3f} mm; equal physical scale", fontsize=11)
        ax.set_xlim(box[2], box[5]);ax.set_ylim(box[1], box[4])
        ax.set_xlabel("MR z (mm); forward flight toward -z")
        ax.set_ylabel("MR y (mm)")
    for ax in axes.flat[len(cases):]:
        ax.set_visible(False)
    figure.suptitle(f"Actual CSG YZ section at x = +{section_x:g} mm (off-axis)\n"
                   "Source and P1-distance references belong to the beam axis x = 0", fontsize=13)
    figure.legend(handles=[Patch(facecolor=colors[k], edgecolor="black", label=label) for k, label in
                           ((1, "IP conductors"), (2, "E14 LP shield"), (3, "P1 ground shield"), (4, "P1 biased side electrode"))],
                  loc="lower center", ncol=4, frameon=False)
    figure.tight_layout(rect=(0, 0.05, 1, 0.92))
    return figure


def _field_figure(cases: list):
    from matplotlib import pyplot as plt
    figure, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    styles = [("#000000", "-", "o"), ("#0072B2", "--", "s"),
              ("#D55E00", ":", "^"), ("#009E73", "-.", "D")]
    quantities = [("potential_v", "Potential (V)"), ("ey_v_per_mm", "Ey (V/mm)"), ("ez_v_per_mm", "Ez (V/mm)")]
    for index, case in enumerate(cases):
        color, line, marker = styles[index % len(styles)]
        distance = np.array([case["prepared"]["exit_z_mm"]-r["z_mm"] for r in case["axis"]])
        for ax, (key, label) in zip(axes, quantities):
            values = [r[key] for r in case["axis"]]
            ax.plot(distance, values, color=color, linestyle=line, marker=marker,
                    markevery=max(1, len(distance)//14), markersize=3, linewidth=1.3,
                    label=f"D = {case['distance_mm']:.3f} mm")
            ax.set_ylabel(label);ax.grid(alpha=0.2)
        axes[-1].annotate(f"{case['distance_mm']:.3f} mm", xy=(distance[-1], case["axis"][-1]["ez_v_per_mm"]),
                          xytext=(3, 7), textcoords="offset points", fontsize=8, color=color)
    axes[0].legend(loc="best", ncol=2, frameon=False)
    axes[-1].set_xlim(0, max(c["prepared"]["exit_z_mm"]-c["axis"][-1]["z_mm"] for c in cases)*1.08)
    axes[-1].set_xlabel("Forward distance from relocated source plane (mm)")
    figure.suptitle("Native nominal-axis field probes: x = 0, y = source nominal y\n"
                   "Actual finite fields; these are not trajectory-force samples or sharp field-entry boundaries", fontsize=12)
    figure.tight_layout(rect=(0, 0, 1, 0.93))
    return figure


def export_field_diagnostics(run: Path) -> dict:
    """Write English PNG/SVG and source-bound metadata into the analysis run.

    Consumes frozen geometry and native axis CSV only; no solver, GUI, source
    edits, interpolation, smoothing, trajectory filtering or field inference.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    run = Path(run).resolve()
    resolved_path = run/"inputs/resolved_study.json"
    resolved = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
    if not resolved["cases"]:
        raise ValueError("at least one declared distance case required for the comparison figure")
    output = run/"results/local_field_diagnostics"
    output.mkdir(parents=True, exist_ok=True)
    cases, sources = [], [file_record(resolved_path)]
    required = {"z_mm", "potential_v", "ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm", "electrode"}
    for case in resolved["cases"]:
        directory = Path(case["directory"])
        geometry_path, axis_path = directory/"geometry.json", directory/"axis_field.csv"
        prepared = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
        with axis_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if set(reader.fieldnames or ()) != required:
                raise ValueError("native axis field columns differ")
            rows = [{key: float(value) for key, value in row.items()} for row in reader]
        if len(rows) < 2 or not all(np.isfinite(v) for row in rows for v in row.values()):
            raise ValueError("axis profile needs finite native samples")
        if any(a["z_mm"] <= b["z_mm"] for a, b in zip(rows, rows[1:])):
            raise ValueError("axis samples must follow negative-z flight")
        cases.append(dict(case, prepared=prepared, axis=rows))
        sources.extend((file_record(geometry_path), file_record(axis_path)))
    box = resolved["contract"]["numerics"]["box_mm"]
    pitch = resolved["contract"]["numerics"]["pitch_mm"]
    positive_parts = [p for p in cases[0]["prepared"]["geometry"]["prism_electrodes"][0]["parts"] if p["x"][0] > 0]
    section_x = min(p["x"][0] for p in positive_parts)+pitch[0]
    pixel = min(pitch)
    figures = {"local_geometry_yz_sections": _geometry_figure(cases, box, section_x, pixel),
               "nominal_axis_field_profiles": _field_figure(cases)}
    assets = []
    for name, figure in figures.items():
        for extension in ("png", "svg"):
            destination = output/f"{name}.{extension}"
            figure.savefig(destination, dpi=200, facecolor="white")
            assets.append(file_record(destination))
        plt.close(figure)
    metadata = dict(schema_version=1, role="ip_p1_local_geometry_field_diagnostics", source_run=run.name,
                    sources=sources, generator=file_record(Path(__file__)), figures=assets,
                    frame="MR instrument frame; z acceleration, y slow drift, x transverse", units="mm, V, V/mm",
                    section_x_mm=section_x, geometry_display_pixel_mm=pixel,
                    geometry_scope="Pixel-centre evaluation of actual frozen CSG at the stated off-axis x; no projection or CAD qualification",
                    field_scope="Native fixed-axis potential_vc/field_vc probes; not particle forces",
                    transform="Forward distance_mm = relocated_exit_z_mm - native_probe_z_mm",
                    clipping="Common local PA box for all panels; IP conductors outside it are excluded; negative-x half represented by symmetry",
                    filtering="No axis samples removed; no smoothing, interpolation or extrapolation",
                    geometry_gap_mm=[c["prepared"]["gap_mm"] for c in cases],
                    source_feedback_validated=False, full_analyzer_flight_executed=False, gui_executed=False,
                    dpi=200, geometry_size_inches=[16,5*((len(cases)+1)//2)], field_size_inches=[12,10])
    metadata_path = output/"figure_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return dict(status="success", output_directory=str(output), metadata=file_record(metadata_path), figures=assets)
