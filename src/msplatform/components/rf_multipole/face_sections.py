"""Physical conductor sections at RF mechanical ports, independent of backends."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from msplatform.components.rf_multipole.compile_design_request import validate_resolved_design_contract
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology


@dataclass(frozen=True)
class LocalFaceConductorSection:
    """One physical circle/annulus in the provider's local Cartesian mm frame.

    Member identity is a JSON pointer into the input resolved document; multiple
    members may share a scientific group. Ground means a validated static 0 V
    source, never an RF waveform's instantaneous zero. No native labels occur.
    """

    electrode_group_id: str
    member_ref: str
    role: str
    center_mm: tuple[float, float, float]
    inner_radius_mm: float
    outer_radius_mm: float
    is_grounded: bool


def _member_groups(resolved: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    groups = {}
    for group in build_electrode_topology(resolved):
        for reference in group["member_refs"]:
            if reference in groups:
                raise ValueError("face member belongs to more than one scientific group")
            groups[reference] = group
    return groups


def _section(member: Mapping[str, Any], reference: str, groups: Mapping[str, Any],
             plane: float, *, role: str) -> LocalFaceConductorSection:
    group = groups[reference]
    source = group["voltage_source"]
    # build_electrode_topology has already checked this source's role and value.
    grounded = source == {"kind": "static", "pointer": "/static_electrodes_V/ground_V"}
    rod = role == "rod"
    return LocalFaceConductorSection(
        electrode_group_id=group["electrode_group_id"], member_ref=reference, role=role,
        center_mm=(member["center_x_mm"], member["center_y_mm"], plane) if rod else (0., 0., plane),
        inner_radius_mm=0. if rod else member["inner_radius_mm"],
        outer_radius_mm=member["radius_mm"] if rod else member["outer_radius_mm"], is_grounded=grounded)


def local_face_conductor_sections(resolved: Mapping[str, Any], *, side: str) -> tuple[LocalFaceConductorSection, ...]:
    """Return actual round-rod/annular sections at entrance or exit, without writes.

    The plane is the declared mechanical port, including recessed-rod cases.
    Known resolved3/axial2/array1 and resolved4/axial3/array2 contracts are
    validated explicitly by the existing compiler validator (which reads cached
    package-owned JSON schemas, never author files). Unsupported or
    incomplete contracts raise ValueError/ContractError; input is not modified.
    Inclusive axial boundaries retain the existing physical face-contact rule.
    """
    if side not in ("entrance", "exit"):
        raise ValueError("face side must be entrance or exit")
    validate_resolved_design_contract(resolved)
    groups = _member_groups(resolved)
    geometry = resolved["geometry_mm"]
    plane = geometry["enclosure_layout"]["ports"]["mechanical_" + side]["center_mm"][2]
    segmented = resolved["segmentation"]["segmented_rod_array"]
    rods = segmented["electrodes"] if segmented is not None else geometry["rod_array"]["rods"]
    prefix = "/segmentation/segmented_rod_array/electrodes" if segmented is not None else "/geometry_mm/rod_array/rods"
    sections = []
    for index, rod in enumerate(rods):
        if "radius_mm" not in rod or "semi_major_axis_mm" in rod or "semi_minor_axis_mm" in rod:
            raise ValueError("face sections support round rods only")
        if rod["z_min_mm"] <= plane <= rod["z_max_mm"]:
            sections.append(_section(rod, f"{prefix}/{index}", groups, plane, role="rod"))
    for index, body in enumerate(geometry["enclosure_layout"]["bodies"]):
        if body["z_min_mm"] <= plane <= body["z_max_mm"]:
            reference = f"/geometry_mm/enclosure_layout/bodies/{index}"
            sections.append(_section(body, reference, groups, plane, role=body["role"]))
    return tuple(sections)
