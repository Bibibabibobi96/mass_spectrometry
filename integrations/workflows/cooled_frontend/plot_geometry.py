"""Exact frozen HP-conditioner sections for the default shared-clock figure.

The IP provider owns CSG intersections and cutouts. This adapter only places
those sections in native MR axes and adds a labelled transverse reference.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.axes import Axes
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from matplotlib.transforms import Affine2D

from projects.dual_pressure_rectilinear_ion_processor.analysis.section_diagnostics import parts, section


_STYLES = {
    "hp_rf_a": ("HP RF A", "#ABC7D3", "#456D80"),
    "hp_rf_b": ("HP RF B", "#D0B5C5", "#78556B"),
    "hp_auxiliary": ("HP corner auxiliary", "#E4BF76", "#906822"),
    "entrance_gate": ("Entrance gate", "#BCD3B2", "#517844"),
    "hp_shield": ("HP shield", "#D9DDE1", "#666E75"),
    "end_inner_auxiliary": ("Terminal inner auxiliary", "#C8C1E2", "#66568F"),
    "exit_gate": ("Exit gate", "#A5CCBD", "#39785F"),
}
_ROTATION = [[0., 0., -1.], [1., 0., 0.], [0., -1., 0.]]


def _pose(contract: dict[str, Any]) -> np.ndarray:
    if contract.get("role") != "ion_processor_hp_end_buncher_provider" or contract.get("frame_id") != "mrtof_global_cartesian":
        raise ValueError("frozen native-MR conditioner provider required")
    pose = contract["native_to_mr"]
    translation = np.asarray(pose["translation_mm"], dtype=float)
    if pose["rotation"] != _ROTATION or translation.shape != (3,) or not np.isfinite(translation).all():
        raise ValueError("conditioner sections require the certified native-to-MR pose")
    electrodes = contract["native_projection_fragment"]["electrodes"]
    ids = contract["electrode_ids"]
    if set(ids) != set(_STYLES) or len(set(ids.values())) != len(_STYLES) or {e["name"]: e["electrode_id"] for e in electrodes} != ids:
        raise ValueError("conditioner sections require all seven provider electrode identities")
    return translation


def _path(item: tuple, *, hole: bool = False) -> Path:
    """Keep circular cutouts as Bezier curves, never rectangular envelopes."""
    kind, shape = item
    if kind == "circle":
        x, y, radius = shape
        return Affine2D().scale(-radius if hole else radius, radius).translate(x, y).transform_path(Path.unit_circle())
    if kind == "rect":
        a, b, c, d = shape
        points = [(a, b), (c, b), (c, d), (a, d)]
    else:
        points = list(shape)
    area = sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1]))
    if (area < 0) != hole:
        points.reverse()
    return Path([*points, points[0]], [Path.MOVETO, *[Path.LINETO]*(len(points)-1), Path.CLOSEPOLY])


def _section_items(electrode: dict, view: str, value: float, origin_z: float) -> list[tuple]:
    cuts = [section(shape, view, value, origin_z) for shape in electrode["cutouts"]]
    if not any(item is not None and item[0] == "circle" for item in cuts):
        return parts(electrode, view, value, origin_z)
    # The retained finite gates have one wholly-contained circular aperture.
    # Compound winding preserves its exact curved section in the inset too.
    result = []
    for solid in electrode["solids"]:
        item = section(solid, view, value, origin_z)
        if item is None:
            continue
        if item[0] != "rect" or len(cuts) != 1 or cuts[0][0] != "circle":
            raise ValueError("curved conditioner cutout requires a contained circular gate aperture")
        a, b, c, d = item[1]
        x, y, radius = cuts[0][1]
        if not (a <= x-radius < x+radius <= c and b <= y-radius < y+radius <= d):
            raise ValueError("circular gate aperture extends outside its solid section")
        result.append(("path", Path.make_compound_path(_path(item), _path(cuts[0], hole=True))))
    return result


def prepare_conditioner_sections(contract: dict[str, Any], *, transverse: str, cut_mm: float) -> list[dict[str, Any]]:
    """Return actual CSG intersections in (MR z, transverse) mm, without I/O.

    ``transverse=x`` cuts at fixed MR y; ``transverse=y`` at fixed MR x.
    The provider's exact box/convex/cylinder section and subtraction are reused.
    """
    translation = _pose(contract)
    if transverse not in {"x", "y"} or not np.isfinite(cut_mm):
        raise ValueError("conditioner section needs x/y and a finite cut coordinate")
    view = "cross" if transverse == "x" else "long"
    value = cut_mm-translation[1 if transverse == "x" else 0]
    # IP sections produce (x,z) or (y,z) in the same orientation as the MR
    # pose, except for the retained guide's x/y translation.
    transform = Affine2D.from_values(0., 1., 1., 0., 0., translation[0 if transverse == "x" else 1])
    result = []
    for electrode in contract["native_projection_fragment"]["electrodes"]:
        for kind, geometry in _section_items(electrode, view, value, translation[2]):
            path = geometry if kind == "path" else _path((kind, geometry))
            result.append(dict(electrode_id=electrode["electrode_id"], name=electrode["name"],
                               path=transform.transform_path(path)))
    return result


def add_conditioner_section(ax: Axes, contract: dict[str, Any], *, transverse: str, cut_mm: float) -> None:
    """Add finite HP metal with real apertures; particle data are untouched."""
    seen = set()
    for item in prepare_conditioner_sections(contract, transverse=transverse, cut_mm=cut_mm):
        name, fill, edge = _STYLES[item["name"]]
        label = f"E{item['electrode_id']} {name}" if item["name"] not in seen else None
        artist = PathPatch(item["path"], facecolor=fill, edgecolor=edge, linewidth=.6, label=label, zorder=1)
        artist.set_gid(f"conditioner_geometry_{item['electrode_id']}_{item['name']}")
        ax.add_patch(artist)
        seen.add(item["name"])


def add_conditioner_cross_section(ax: Axes, contract: dict[str, Any]) -> Axes:
    """Add one same-figure transverse reference exposing off-plane HP corners."""
    center = contract["geometry"]["trap_center_mr_mm"]
    inset = ax.inset_axes([.04, .46, .42, .4])
    add_conditioner_section(inset, contract, transverse="x", cut_mm=center[1])
    inset.set(xlabel="z (mm)", ylabel="x (mm)", title=f"HP section: y = {center[1]:g} mm")
    inset.set_gid("conditioner_hp_cross_section")
    inset.set_aspect("equal", adjustable="box")
    inset.autoscale_view()
    inset.margins(.05)
    inset.tick_params(labelsize=6)
    inset.xaxis.label.set_size(7)
    inset.yaxis.label.set_size(7)
    inset.title.set_size(7)
    inset.set_zorder(20)
    return inset
