"""Compile scientific assembly content into SIMION GEM specifications only."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import resolve_accelerator_geometry
from msplatform.components.single_reflection_oa_tof.electrode_topology import resolve_frontend_field_domain
from .accelerator_projection import project_side_opening
from .downstream import compile_downstream_specs
from .frontend import native_frontend_instances
from .geometry import compile_frontend_geometry
from .fields import _physical_samples
from .frontend import frontend_electrode_maps


@dataclass(frozen=True)
class CompiledSimionGeometry:
    """One pure compile result; specifications do not imply built PA assets.

    Downstream templates retain the provider's original GEM preprocessing;
    ``template_variables`` is the complete corresponding ``_G.var`` value.
    Only an explicit execution call may materialize or run these inputs.
    """

    frontend_gems: dict[str, str]
    frontend_geometry: dict[str, Any]
    downstream_specs: tuple[dict[str, Any], ...]
    provider_content_identities: dict[str, dict[str, str]]
    components_resolved: dict[str, dict[str, Any]]


def _content_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def compile_geometry(assembly: Mapping[str, Any], *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile frontend plus all three TOF downstream GEM specifications.

    Assembly supplies only ``composition_plan`` and ``components_resolved``.
    Backend numerics supplies ``frontend_domains``, ``geometry_build`` and
    ``detector_marker``. Optional ``electrode_group_native_ids`` is an expert
    backend override; otherwise stable sequential native slots are allocated.
    No source, path, receipt, workspace, process or execution context is used.
    """
    if not isinstance(assembly, Mapping) or set(assembly) != {"composition_plan", "components_resolved"}:
        raise ValueError("SIMION geometry requires a scientific assembly plan and resolved component content only")
    required = {"frontend_domains", "geometry_build", "detector_marker"}
    if (not isinstance(numerics, Mapping) or not required <= set(numerics)
            or set(numerics) - required - {"electrode_group_native_ids"}):
        raise ValueError("SIMION geometry numerics fields differ")
    plan = copy.deepcopy(assembly["composition_plan"])
    if type(plan.get("schema_version")) is not int or plan["schema_version"] != 5:
        raise ValueError("installed scientific geometry compilation requires composition plan5")
    canonical = compile_assembly_layout(plan["recipe"], plan["components"], local_scope=plan.get("local_scope"))
    if {key:value for key,value in plan.items() if key != "input_files"} != canonical:
        raise ValueError("composition plan differs from its canonical mechanical compilation")
    multipoles, tof_id = native_frontend_instances(plan)
    components = assembly["components_resolved"]
    selected = set(plan["scope"]["instance_ids"])
    if not isinstance(components, Mapping) or set(components) != selected:
        raise ValueError("resolved component content must cover exactly the selected assembly instances")
    tof = copy.deepcopy(components[tof_id])
    # Native numerical fields are explicit backend inputs, never inferred from
    # a source or silently inherited from a historical run's solver settings.
    tof["simion_geometry_build"] = copy.deepcopy(numerics["geometry_build"])
    tof["simion_detector_marker"] = copy.deepcopy(numerics["detector_marker"])
    variant = plan["components"][tof_id]["variant_id"]
    projection = resolve_accelerator_geometry(tof, variant_id=variant)
    port = plan["components"][tof_id]["ports"]["side_entry"]
    parent = numerics["frontend_domains"]["parent"]
    project_side_opening(projection.local_region,
        side_opening=dict(center_mm=port["center_mm"], width_mm=port["cross_section"]["width_mm"],
                          height_mm=port["cross_section"]["height_mm"]),
        cell_mm_xyz=parent["cell_mm_xyz"],
        pa_origin_mm={a:parent["pa_bounds_mm"][a+"_min"] for a in "xyz"})
    groups = {instance:[row["electrode_group_id"] for row in build_electrode_topology(components[instance])]
              for instance in multipoles}
    groups[tof_id] = resolve_frontend_field_domain(tof, projection=projection,
        geometry_profile_id=plan["components"][tof_id]["geometry_profile_id"])["electrode_group_ids"]
    maps = numerics.get("electrode_group_native_ids")
    if maps is None:
        maps, next_id = {}, 1
        for instance in sorted(groups):
            maps[instance] = {group:next_id+index for index, group in enumerate(groups[instance])}
            next_id += len(groups[instance])
    elif not isinstance(maps, Mapping) or set(maps) != selected:
        raise ValueError("expert native mappings must cover exactly the selected assembly instances")
    identities = {instance:dict(resolved_content_sha256=_content_sha256(components[instance]),
                                component_interface_sha256=_content_sha256(plan["components"][instance]))
                  for instance in selected}
    gems, geometry = compile_frontend_geometry({instance:components[instance] for instance in multipoles}, tof,
        composition_plan=plan, accelerator_variant=variant,
        numerical_domains=copy.deepcopy(numerics["frontend_domains"]),
        electrode_bindings=copy.deepcopy(maps), provider_inputs=identities)
    rf_maps, oa_map = frontend_electrode_maps(geometry)
    geometry["raw_physical_samples"] = {name:_physical_samples(
        {instance:components[instance] for instance in multipoles}, geometry, domain,
        rf_maps, oa_map, entrance=name == "entrance_refinement")
        for name,domain in geometry["numerical_domains"].items()}
    geometry["downstream_build_contract"] = {key:copy.deepcopy(tof[key]) for key in (
        "geometry_mm", "simion_geometry_build", "simion_detector_marker", "rings", "electrodes_V")}
    return CompiledSimionGeometry(gems, geometry, compile_downstream_specs(tof), identities,
                                  copy.deepcopy(dict(components)))
