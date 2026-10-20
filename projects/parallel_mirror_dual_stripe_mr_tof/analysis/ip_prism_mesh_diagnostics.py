"""Bounded ordinary-PA node flags versus continuous IP CSG sections.

Reuses the installed-SL format boundary in standalone_pa_composition. No full
PA load/hash, field reconstruction, refinement, trajectory or GUI operation.
"""
from __future__ import annotations

import csv
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from common.contracts.write_run_manifest import file_record
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import convex_planes, convex_section
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import _bounds
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import HEADER, PaHeader, read_pa_header


def _mask(shape: dict, xyz: list[np.ndarray]) -> np.ndarray:
    """Evaluate actual primitives at supplied coordinates, not their AABBs."""
    if shape["shape"] == "box":
        return np.logical_and.reduce([(p >= lo) & (p <= hi) for p, lo, hi in zip(xyz, shape["min_mm"], shape["max_mm"])])
    if shape["shape"] == "convex_polyhedron":
        mask = np.ones(xyz[0].shape, bool)
        for plane in convex_planes(shape):
            mask &= sum(plane[a]*xyz[a] for a in range(3))+plane[3] <= 0
        return mask
    if shape["shape"] != "cylinder3d":
        raise ValueError("unsupported assembled CSG primitive")
    a, b = np.asarray(shape["endpoints_mm"], float)
    direction = b-a
    length2 = float(direction@direction)
    if length2 <= 0:
        raise ValueError("degenerate cylinder")
    fraction = sum((xyz[k]-a[k])*direction[k] for k in range(3))/length2
    radial2 = sum((xyz[k]-a[k]-fraction*direction[k])**2 for k in range(3))
    return (fraction >= 0) & (fraction <= 1) & (radial2 <= shape["radius_mm"]**2)


def _metal(electrodes: list[dict], xyz: list[np.ndarray]) -> np.ndarray:
    metal = np.zeros(xyz[0].shape, bool)
    for electrode in electrodes:
        body = np.zeros_like(metal)
        for solid in electrode["solids"]:
            body |= _mask(solid, xyz)
        for cut in electrode["cutouts"]:
            body &= ~_mask(cut, xyz)
        metal |= body
    return metal


def _section_shapes(shape: dict, fixed: int, value: float, axes: tuple[int, int]) -> list[tuple[str, list]]:
    """Exact polygon or circle section; no AABB substitution for convex solids."""
    kind = shape["shape"]
    if kind in {"box", "convex_polyhedron"}:
        vertices = convex_section(shape, fixed, value) if kind == "convex_polyhedron" else []
        if kind == "box":
            low, high = shape["min_mm"], shape["max_mm"]
            if low[fixed] <= value <= high[fixed]:
                h, v = axes
                return [("polygon", [[low[h], low[v]], [high[h], low[v]], [high[h], high[v]], [low[h], high[v]]])]
        return [("polygon", [[p[a] for a in axes] for p in vertices])] if len(vertices) >= 3 else []
    a, b = np.asarray(shape["endpoints_mm"], float)
    varying = np.flatnonzero(a != b)
    if len(varying) != 1:
        raise ValueError("section display requires axis-aligned cylinder")
    axis, radius = int(varying[0]), shape["radius_mm"]
    if axis == fixed:
        return [("circle", [a[axes[0]], a[axes[1]], radius])] if min(a[fixed], b[fixed]) <= value <= max(a[fixed], b[fixed]) else []
    delta = value-a[fixed]
    if abs(delta) >= radius:
        return []
    half = float(np.sqrt(radius**2-delta**2))
    low, high = a.copy(), a.copy()
    low[axis], high[axis] = min(a[axis], b[axis]), max(a[axis], b[axis])
    other = next(k for k in axes if k != axis)
    low[other], high[other] = a[other]-half, a[other]+half
    h, v = axes
    return [("polygon", [[low[h], low[v]], [high[h], low[v]], [high[h], high[v]], [low[h], high[v]]])]


def _node_plan(name: str, fixed: int, requested: float, axes: tuple, low: np.ndarray,
               high: np.ndarray, box: np.ndarray, pitch: np.ndarray, dimensions: list) -> dict:
    index = int(np.rint((requested-box[fixed])/pitch[fixed]))
    if index < 0 or index >= dimensions[fixed]:
        raise ValueError("requested mesh plane outside PA")
    grids, indices = [], []
    for axis in axes:
        ii = np.arange(dimensions[axis])
        values = box[axis]+pitch[axis]*ii
        if axis == 0:
            ii = np.concatenate((ii[:0:-1], ii))
            values = np.concatenate((-values[:0:-1], values))
        keep = (values >= low[axis]) & (values <= high[axis])
        if not keep.any():
            raise ValueError("display crop contains no PA nodes")
        grids.append(values[keep]); indices.append(ii[keep])
    return dict(name=name, fixed_axis=fixed, requested_mm=float(requested),
                actual_mm=float(box[fixed]+index*pitch[fixed]), fixed_index=index,
                axes=axes, grids=grids, indices=indices,
                display_bounds_mm=[float(low[a]) for a in axes]+[float(high[a]) for a in axes])


def _lens_slice_plans(prepared: dict) -> list[dict]:
    """Three nearest-node views per finite lens; crop margin is one actual cell."""
    checks = prepared["geometry_checks"]
    box, pitch = np.array(checks["box_mm"], float), np.array(checks["pitch_mm"], float)
    groups = {}
    for electrode in prepared["geometry"].get("lens_electrodes", []):
        groups.setdefault(electrode["element_name"], []).append(electrode)
    plans = []
    for name, electrodes in groups.items():
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in name):
            raise ValueError("lens element name must be a path-safe identifier")
        spec = electrodes[0]["specification"]
        if any(e["specification"] != spec for e in electrodes):
            raise ValueError("lens element must share one frozen specification")
        bounds = np.array([_bounds(s) for e in electrodes for s in e["solids"]])
        low = np.maximum(bounds[:, :3].min(0)-pitch, [-box[3], box[1], box[2]])
        high = np.minimum(bounds[:, 3:].max(0)+pitch, box[3:])
        pairs = "; ".join(f"{pair} rods {next(e['voltage_v'] for e in electrodes if e['pair'] == pair):+g} V"
                          for pair in ("x", "y"))
        for view, fixed, axes in (("xy_center", 2, (0, 1)), ("xz_center_y", 1, (0, 2)), ("yz_center_x", 0, (1, 2))):
            plan = _node_plan(f"lens_{name}_{view}", fixed, spec["center_mm"][fixed], axes,
                              low, high, box, pitch, checks["grid_dimensions"])
            plan.update(lens_element_name=name, lens_description=f"{name}: finite quadrupole rods; {pairs}")
            plans.append(plan)
    return plans


def _slice_plan(prepared: dict, header: PaHeader) -> list[dict]:
    checks = prepared["geometry_checks"]
    box, pitch = np.array(checks["box_mm"], float), np.array(checks["pitch_mm"], float)
    dimensions = [header.nx, header.ny, header.nz]
    if header.symmetry != 1 or header.raw_mirror & 7 != 1 or box[0] != 0:
        raise ValueError("mesh display requires declared planar x=0 mirror")
    if dimensions != checks["grid_dimensions"] or list(pitch) != [header.dx_mm, header.dy_mm, header.dz_mm]:
        raise ValueError("mesh header differs from frozen geometry")
    if not np.allclose((np.array(dimensions)-1)*pitch, box[3:]-box[:3], rtol=0, atol=1e-9):
        raise ValueError("mesh physical extent differs from frozen box")
    electrodes = prepared["geometry"]["ion_processor_electrodes"]
    selected = [e for e in electrodes if e["electrode_id"] in {5, 6, 11, 14}]
    if {e["electrode_id"] for e in selected} != {5, 6, 11, 14}:
        raise ValueError("E5/E6/E11/E14 required for geometry-derived displays")
    bounds = np.array([_bounds(s) for e in selected for s in e["solids"]])
    low, high = bounds[:, :3].min(axis=0), bounds[:, 3:].max(axis=0)
    low = np.maximum(low, [-box[3], box[1], box[2]])
    high = np.minimum(high, box[3:])
    inner = np.array([_bounds(s) for e in selected if e["electrode_id"] == 11 for s in e["solids"]])
    inner_z = float((inner[:, 2].min()+inner[:, 5].max())/2)
    plans = []
    for name, fixed, requested, axes in (("xz_at_nominal_y", 1, checks["nominal_y_mm"], (0, 2)),
                                         ("xy_at_inner_center_z", 2, inner_z, (0, 1))):
        plans.append(_node_plan(name, fixed, requested, axes, low, high, box, pitch, dimensions))
    # The beam-axis YZ view exposes slit/window end walls missed by the central
    # XZ view. Geometry-derived side views expose RF slopes and auxiliary depth;
    # no assumed manufacturer dimensions or new physical sampling parameters.
    plans.append(_node_plan("yz_at_beam_axis", 0, 0., (1, 2), low, high, box, pitch, dimensions))
    for electrode in electrodes:
        if electrode["electrode_id"] not in {7, 8, 10, 11}:
            continue
        positive = [_bounds(s) for s in electrode["solids"] if _bounds(s)[0] >= 0 and _bounds(s)[3] > 0]
        if not positive:
            raise ValueError("side electrode requires a positive-x body for its YZ node section")
        body = min(positive, key=lambda b: b[0])
        plane_x = (body[0]+body[3])/2
        plans.append(_node_plan(f"yz_at_e{electrode['electrode_id']:02d}_body_center", 0, plane_x,
                                (1, 2), low, high, box, pitch, dimensions))
    for i, aperture in enumerate(prepared["geometry"].get("aperture_electrodes", [])):
        spec = aperture["specification"]
        if spec["shape"] not in {"circle", "y_slit"} or spec["normal"] not in ([0, 0, 1], [0, 0, -1]):
            raise ValueError("mesh aperture requires declared world-z circular or y-slit plate")
        bounds = np.array([_bounds(s) for s in aperture["solids"]])
        low, high = bounds[:, :3].min(0), bounds[:, 3:].max(0)
        # One actual cell on either side shows the surrounding vacuum and
        # the complete plate thickness; this is a display-only extension.
        low, high = low-pitch, high+pitch
        low = np.maximum(low, [-box[3], box[1], box[2]])
        high = np.minimum(high, box[3:])
        for name, fixed, axes in (("xy_center", 2, (0, 1)), ("xz_thickness", 1, (0, 2))):
            view_low, view_high = low.copy(), high.copy()
            if name == "xz_thickness":
                holes = np.array([_bounds(s) for s in aperture["cutouts"]])
                view_low[0] = max(low[0], holes[:, 0].min()-pitch[0])
                view_high[0] = min(high[0], holes[:, 3].max()+pitch[0])
            plan = _node_plan(f"aperture_{i:02d}_{name}", fixed, spec["center_mm"][fixed], axes,
                              view_low, view_high, box, pitch, dimensions)
            plan["aperture_index"] = i
            plan["aperture_description"] = f"Physical {spec['shape']} aperture; plate thickness={spec['thickness_mm']:g} mm"
            plans.append(plan)
    return plans + _lens_slice_plans(prepared)


def _closed_slab_layers(origin: float, pitch: float, count: int, lower: float, upper: float) -> np.ndarray:
    """Closed slab node indices, snapping only grid-coordinate roundoff.

    Compute in grid coordinates so aligned faces survive subtraction/addition
    cancellation, e.g. -120+1002*.1 > -19.8 in binary64. Eight machine epsilons
    cover the conversion's subtraction and division, scaled by its operands;
    this is a floating-point predicate budget, not a physical thickness margin.
    """
    limits = (np.array([lower, upper])-origin)/pitch
    nearest = np.rint(limits)
    error = 8*np.finfo(float).eps*max(1., abs(origin/pitch), abs(lower/pitch), abs(upper/pitch))
    limits = np.where(np.abs(limits-nearest) <= error, nearest, limits)
    first, last = max(0, int(np.ceil(limits[0]))), min(count-1, int(np.floor(limits[1])))
    return np.arange(first, last+1, dtype=int)


def _aperture_topology(raw: np.memmap, header: PaHeader, prepared: dict, aperture: dict,
                       index: int, output: Path, stem: str) -> dict:
    """Record straight world-z sampled node columns, not a continuous bore proof."""
    spec = aperture["specification"]
    checks = prepared["geometry_checks"]
    box, pitch = np.array(checks["box_mm"]), np.array(checks["pitch_mm"])
    bounds = np.array([_bounds(s) for s in aperture["solids"]])
    low, high = bounds[:, :3].min(0), bounds[:, 3:].max(0)
    plan = _node_plan("aperture_columns", 2, spec["center_mm"][2], (0, 1), low, high,
                      box, pitch, [header.nx, header.ny, header.nz])
    x, y = np.meshgrid(*plan["grids"], indexing="xy")
    ix, iy = np.meshgrid(*plan["indices"], indexing="xy")
    zs = box[2]+np.arange(header.nz)*pitch[2]
    layers = _closed_slab_layers(box[2], pitch[2], header.nz, low[2], high[2])
    xyz = [x, y, np.full(x.shape, spec["center_mm"][2])]
    hole = np.zeros(x.shape, bool)
    for cut in aperture["cutouts"]:
        hole |= _mask(cut, xyz)
    body = np.zeros_like(hole)
    for solid in aperture["solids"]:
        body |= _mask(solid, xyz)
    candidates = hole & body
    blocked = np.zeros_like(hole)
    metal_count = missing_count = represented_count = 0
    node_path = output/f"{stem}__aperture_{index:02d}_through_nodes.csv"
    with node_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["x_mm", "y_mm", "z_mm", "pa_ix", "pa_iy", "pa_iz", "raw_value", "pa_electrode_flag", "aperture_csg_metal"])
        for iz in layers:
            xyz[2] = np.full(x.shape, zs[iz])
            values = np.asarray(raw[iz, iy, ix])
            if not np.isfinite(values).all():
                raise ValueError("nonfinite aperture thickness node")
            flags = values > header.max_voltage
            blocked |= flags
            metal = _metal([aperture], xyz)
            metal_count += int(metal.sum())
            represented_count += int((metal & flags).sum())
            missing_count += int((metal & ~flags).sum())
            writer.writerows(zip(x.ravel(), y.ravel(), xyz[2].ravel(), ix.ravel(), iy.ravel(),
                                 np.full(x.size, iz), values.ravel(), flags.astype(int).ravel(), metal.astype(int).ravel()))
    opened = candidates & ~blocked if len(layers) else np.zeros_like(hole)
    column_path = output/f"{stem}__aperture_{index:02d}_columns.csv"
    with column_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["x_mm", "y_mm", "pa_ix", "pa_iy", "hole_candidate", "any_raw_electrode_in_thickness", "through_open", "status"])
        for r, c in np.ndindex(x.shape):
            status = "unresolved_no_z_layers" if not len(layers) else "open" if opened[r, c] else "blocked" if candidates[r, c] else "outside_nominal_hole"
            writer.writerow([x[r, c], y[r, c], ix[r, c], iy[r, c], int(candidates[r, c]), int(blocked[r, c]), int(opened[r, c]), status])
    reason = ("no_node_layers_in_plate" if not len(layers) else "no_nodes_in_nominal_hole" if not candidates.any()
              else "all_hole_columns_blocked" if not opened.any() else "no_sampled_plate_metal" if not metal_count
              else "plate_metal_not_represented" if not represented_count else None)
    widths = [2*spec["radius_mm"]]*2 if spec["shape"] == "circle" else [2*w for w in spec["half_widths_mm"]]
    return dict(aperture_index=index, specification=spec, status="FAIL" if reason else "PASS_sampled_z_node_columns",
        failure_reason=reason, fly_permitted_by_this_check=reason is None,
        plate_thickness_mm=spec["thickness_mm"], plate_thickness_gu=spec["thickness_mm"]/pitch[2],
        opening_widths_xy_mm=widths, opening_widths_xy_gu=[w/p for w, p in zip(widths, pitch)],
        slab_bounds_mm=[float(low[2]), float(high[2])], actual_z_layers_mm=zs[layers].tolist(),
        layer_boundary_policy="Closed mechanical slab; grid-coordinate integer snap only within 8 binary64 eps scaled by coordinate-conversion operands; no thickness expansion",
        hole_candidate_columns=int(candidates.sum()), open_columns=int(opened.sum()),
        blocked_hole_columns=int((candidates & blocked).sum()),
        outside_hole_expected_metal_nodes=metal_count, represented_metal_nodes=represented_count,
        missing_metal_nodes=missing_count, nodes=file_record(node_path), columns=file_record(column_path),
        scope="All signed physical x/y columns (negative x mirrors positive PA index); any electrode flag through actual slab node layers blocks that column. Not oblique/continuous acceptance, fractional collision validation or the public PA-x rectangular topology test.")


def _sample_section(raw: np.memmap, header: PaHeader, plan: dict, electrodes: list[dict]) -> dict:
    h, v = np.meshgrid(*plan["grids"], indexing="xy")
    ih, iv = np.meshgrid(*plan["indices"], indexing="xy")
    xyz, ijk = [None]*3, [None]*3
    xyz[plan["fixed_axis"]] = np.full(h.shape, plan["actual_mm"])
    ijk[plan["fixed_axis"]] = np.full(h.shape, plan["fixed_index"], int)
    for axis, values, indices in zip(plan["axes"], (h, v), (ih, iv)):
        xyz[axis], ijk[axis] = values, indices
    values = np.asarray(raw[ijk[2], ijk[1], ijk[0]])
    if not np.isfinite(values).all():
        raise ValueError("nonfinite raw PA slice")
    flags = values > header.max_voltage
    return dict(xyz=xyz, ijk=ijk, raw=values, flags=flags, metal=_metal(electrodes, xyz))


def _figure(plan: dict, sampled: dict, electrodes: list[dict], case: str, pitch: list):
    from matplotlib import pyplot as plt
    from matplotlib.patches import Circle, Polygon

    fig, axes = plt.subplots(1, 3, figsize=(15, 6), sharex=True, sharey=True)
    h, v = (sampled["xyz"][a] for a in plan["axes"])
    for ax, mask, title in zip(axes, (sampled["flags"], sampled["metal"], sampled["flags"] != sampled["metal"]),
                               ("Actual PA electrode nodes", "CSG membership at identical nodes", "Node flags differ from CSG")):
        ax.scatter(h.ravel(), v.ravel(), c=np.where(mask, "#222222", "#dfdfdf").ravel(), marker="s", s=3, linewidths=0, rasterized=True)
        ax.set(title=title, xlabel=f"MR {'xyz'[plan['axes'][0]]} (mm)", ylabel=f"MR {'xyz'[plan['axes'][1]]} (mm)", aspect="equal")
        ax.set_xlim(plan["display_bounds_mm"][0], plan["display_bounds_mm"][2])
        ax.set_ylim(plan["display_bounds_mm"][1], plan["display_bounds_mm"][3])
    for e in electrodes:
        for role in ("solids", "cutouts"):
            for shape in e[role]:
                for kind, section in _section_shapes(shape, plan["fixed_axis"], plan["actual_mm"], plan["axes"]):
                    for ax in axes[:2]:
                        style = dict(fill=False, edgecolor="#0072B2" if role == "solids" else "#D55E00", linewidth=.65,
                                     linestyle="-" if role == "solids" else "--")
                        ax.add_patch(Circle(section[:2], section[2], **style) if kind == "circle" else Polygon(section, closed=True, **style))
    description = f"{plan['aperture_description']}\n" if "aperture_description" in plan else ""
    if "lens_description" in plan:
        description = plan["lens_description"]+"\n"
        for electrode in electrodes:
            if electrode.get("element_name") != plan["lens_element_name"]:
                continue
            for shape in electrode["solids"]:
                for kind, points in _section_shapes(shape, plan["fixed_axis"], plan["actual_mm"], plan["axes"]):
                    center = points[:2] if kind == "circle" else np.mean(points, axis=0)
                    axes[1].annotate(electrode["name"], center, ha="center", va="center", fontsize=7,
                                     bbox=dict(facecolor="white", edgecolor="none", alpha=.8, pad=1))
    fig.suptitle(f"{case} | Pitch {pitch} mm | {plan['name']}\n{description}Requested {'xyz'[plan['fixed_axis']]}={plan['requested_mm']:.6g}; actual node plane={plan['actual_mm']:.6g} mm\n"
                 "Blue solid: CSG solid boundary; orange dashed: cutout boundary. Display crop only.\nFractional data assist Refine; these flags are not a continuous Fly collision boundary.", fontsize=10)
    if "lens_description" in plan:
        # Equal-aspect XY crops need explicit room below the shared node panels.
        fig.subplots_adjust(left=.065, right=.985, bottom=.14, top=.72, wspace=.22)
    else:
        fig.tight_layout(rect=(0, 0, 1, .80 if description else .86))
    return fig


def export_mesh_diagnostics(run: Path) -> dict:
    """Publish bounded node CSVs, exact section outlines and geometric gu spans.

    Called only after the parent's full native payload validation. Parent manifest
    owns full PA SHA; this function records path/header/bytes and hashes only small
    geometry inputs. Primitive section spans are not net metal thicknesses or a
    thin-feature completeness test. No threshold constitutes accuracy acceptance.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    run = Path(run).resolve()
    resolved_path = run/"inputs/resolved_study.json"
    resolved = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
    owners = resolved["field_owners"]
    if not owners or len({r["field_case_id"] for r in owners}) != len(owners):
        raise ValueError("nonempty unique field build owners required")
    output = run/"results/mesh_diagnostics"
    output.mkdir(parents=True, exist_ok=False)
    records, feature_rows, failed_apertures = [], [], []
    for owner_index, owner in enumerate(owners):
        path = Path(owner["field_path"])
        geometry_path = Path(owner["directory"])/"geometry.json"
        prepared = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
        header = read_pa_header(path)
        plans = _slice_plan(prepared, header)
        apertures = prepared["geometry"].get("aperture_electrodes", [])
        lenses = prepared["geometry"].get("lens_electrodes", [])
        electrodes = prepared["geometry"]["ion_processor_electrodes"]+apertures+lenses
        raw = np.memmap(path, dtype="<f8", mode="r", offset=HEADER.size, shape=(header.nz, header.ny, header.nx))
        record = dict(field_case_id=owner["field_case_id"], pa_path=str(path.resolve()), pa_header=asdict(header),
                      pa_bytes=path.stat().st_size, full_pa_hash_performed=False, geometry=file_record(geometry_path),
                      sections=[], aperture_topology=[])
        try:
            for plan in plans:
                sampled = _sample_section(raw, header, plan, electrodes)
                stem = f"field_{owner_index:02d}__{plan['name']}"
                csv_path = output/f"{stem}.csv"
                with csv_path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["x_mm", "y_mm", "z_mm", "pa_ix", "pa_iy", "pa_iz", "raw_value", "pa_electrode_flag", "csg_metal"])
                    writer.writerows(zip(*(a.ravel() for a in sampled["xyz"]), *(a.ravel() for a in sampled["ijk"]),
                                         sampled["raw"].ravel(), sampled["flags"].astype(int).ravel(), sampled["metal"].astype(int).ravel()))
                figure = _figure(plan, sampled, electrodes, owner["field_case_id"], prepared["geometry_checks"]["pitch_mm"])
                assets = []
                for extension in ("png", "svg"):
                    destination = output/f"{stem}.{extension}"
                    figure.savefig(destination, dpi=180, facecolor="white"); assets.append(file_record(destination))
                plt.close(figure)
                section = {k: v for k, v in plan.items() if k not in {"grids", "indices"}}
                section.update(node_count=int(sampled["raw"].size), flag_count=int(sampled["flags"].sum()),
                               csg_metal_count=int(sampled["metal"].sum()), mismatch_count=int(np.count_nonzero(sampled["flags"] != sampled["metal"])),
                               coordinates=file_record(csv_path), figures=assets)
                record["sections"].append(section)
                for e in electrodes:
                    if e.get("electrode_id") not in {5, 6, 11, 14} and e.get("namespace") != "quadrupole_lens":
                        continue
                    for role in ("solids", "cutouts"):
                        for index, shape in enumerate(e[role]):
                            for kind, points in _section_shapes(shape, plan["fixed_axis"], plan["actual_mm"], plan["axes"]):
                                spans = np.ptp(points, axis=0) if kind == "polygon" else [2*points[2]]*2
                                for axis, span in zip(plan["axes"], spans):
                                    row = dict(field_case_id=owner["field_case_id"], section=plan["name"], electrode_id=e["electrode_id"],
                                        primitive_role=role, primitive_index=index, axis="xyz"[axis], span_mm=float(span),
                                        span_gu=float(span/prepared["geometry_checks"]["pitch_mm"][axis]))
                                    if e.get("namespace") == "quadrupole_lens":
                                        row.update(namespace=e["namespace"], element_name=e["element_name"],
                                                   electrode_name=e["name"], pair=e["pair"], voltage_v=e["voltage_v"])
                                    feature_rows.append(row)
            for index, aperture in enumerate(apertures):
                topology = _aperture_topology(raw, header, prepared, aperture, index, output, f"field_{owner_index:02d}")
                record["aperture_topology"].append(topology)
                if topology["status"] == "FAIL":
                    failed_apertures.append(dict(field_case_id=owner["field_case_id"], aperture_index=index,
                                                 reason=topology["failure_reason"]))
        finally:
            del raw
        records.append(record)
    feature_path = output/"primitive_section_spans.csv"
    with feature_path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["field_case_id", "section", "electrode_id", "primitive_role", "primitive_index", "axis", "span_mm", "span_gu"]
        if any("element_name" in row for row in feature_rows):
            fields += ["namespace", "element_name", "electrode_name", "pair", "voltage_v"]
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(feature_rows)
    metadata = dict(schema_version=1, role="ip_prism_ordinary_pa_mesh_sections", status="FAIL" if failed_apertures else "success",
        failed_apertures=failed_apertures, fields=records, source=file_record(resolved_path),
        generator=file_record(Path(__file__)), primitive_section_spans=file_record(feature_path),
        selection="Every unique build owner; nearest node plane (numpy ties-to-even), requested/actual coordinates retained. Full negative-x display mirrors raw positive-x indices; CSG evaluated at signed physical x.",
        crop="IP views: display-only union bounds of E5/E6/E11/E14. YZ views include x=0 and the nearest positive-x solid's bounding-box center for E7/E8/E10/E11, exposing axial end walls and side-electrode depth; requested and nearest actual node planes are explicit. Aperture xy: plate bounds plus one grid cell; aperture xz: hole x bounds and full plate thickness plus one grid cell, all clipped to PA. Thickness-node/column CSVs retain the entire plate footprint. Negative x restored by mirror; no interpolation.",
        format="Official ordinary PA format via standalone_pa_composition.read_pa_header, HEADER.size56, little-endian doubles [nz,ny,nx], flag iff raw>max_voltage.",
        scope="Node/CSG sections include IP, declared physical aperture and optional finite quadrupole lens metal; P1 solids are not included in these CSG membership masks. Mismatch can include P1 metal, PA boundary electrodes and boundary conventions. Fractional Refine assistance is not a continuous Fly collision boundary. Aperture check addresses sampled straight-z columns, not the public PA-x rectangular gate.",
        limitations="Primitive section spans include cutouts separately; not net remaining metal widths or complete thin-feature detection. No accuracy threshold, convergence, manufacturer CAD or trajectory qualification. PA full SHA belongs to parent manifest.")
    if any("lens_element_name" in section for record in records for section in record["sections"]):
        metadata["crop"] += " Lens views: each element's finite rod union plus one actual PA cell, clipped to the field box; XY center and XZ/YZ center planes expose both rod pairs."
    target = output/"metadata.json"
    target.write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if failed_apertures:
        raise ValueError(f"physical aperture node topology FAIL; Fly prohibited; diagnostics retained at {target}")
    return dict(status="success", output_directory=str(output), metadata=file_record(target), field_count=len(records))
