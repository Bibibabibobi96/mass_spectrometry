"""Independent scientific-group SIMION compilation for RF multipole instances."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.rf_multipole.electrode_topology import build_electrode_topology
from .compiler import CompiledSimionGeometry, _content_sha256
from .numerics import normalize_cell_mm_xyz
from .rf_electrode_mapping import build_simion_electrode_map
from .rf_geometry import render_standalone_physical_gem


def compile_independent_multipoles(assembly: Mapping[str, Any], *,
                                   numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile independent RF PA specifications without TOF, source, writes or native actions."""
    if not isinstance(assembly, Mapping) or set(assembly) != {"composition_plan", "components_resolved"}:
        raise ValueError("independent RF compilation requires the complete Assembly snapshot")
    plan = copy.deepcopy(assembly["composition_plan"])
    canonical = compile_assembly_layout(plan["recipe"], plan["components"], local_scope=plan.get("local_scope"))
    if plan != canonical:
        raise ValueError("independent RF composition plan differs from its canonical parent")
    selected = plan["scope"]["instance_ids"]
    if not selected or any(plan["components"][name]["project_id"] != "rf_multipole_ion_optics" for name in selected):
        raise ValueError("independent RF compilation requires only selected RF multipole instances")
    if (not isinstance(numerics, Mapping) or "component_domains" not in numerics
            or set(numerics) - {"component_domains", "electrode_group_native_ids"}):
        raise ValueError("independent RF numerics require component_domains and optional electrode_group_native_ids")
    domains = numerics["component_domains"]
    if not isinstance(domains, Mapping) or set(domains) != set(selected):
        raise ValueError("independent RF component_domains must cover exactly the selected instances")
    requested = numerics.get("electrode_group_native_ids", {})
    if not isinstance(requested, Mapping) or set(requested) - set(selected):
        raise ValueError("independent RF native mappings cannot name unselected instances")
    components = assembly["components_resolved"]
    gems, compiled_domains, bindings, identities = {}, {}, {}, {}
    for name in selected:
        if not isinstance(components.get(name), Mapping):
            raise ValueError(f"{name}: complete RF design is required")
        design = components[name]
        domain = domains[name]
        if not isinstance(domain, Mapping) or set(domain) != {"cell_mm_xyz"}:
            raise ValueError(f"{name}: component domain requires exactly cell_mm_xyz")
        cell = normalize_cell_mm_xyz(domain["cell_mm_xyz"])
        topology = build_electrode_topology(design)
        requested_ids = requested.get(name)
        mapping = build_simion_electrode_map(design, topology, requested_native_ids=requested_ids)
        gems[name] = render_standalone_physical_gem(design, cell, electrode_group_native_ids=mapping)
        bindings[name] = mapping
        geometry = design["geometry_mm"]["numerical_domain"]
        radius = float(geometry["radius_mm"])
        z_min, z_max = float(geometry["z_min_mm"]), float(geometry["z_max_mm"])
        compiled_domains[name] = dict(
            dimensions=dict(nx=math.ceil(2 * radius / cell["x"]) + 1,
                            ny=math.ceil(2 * radius / cell["y"]) + 1,
                            nz=math.ceil((z_max - z_min) / cell["z"]) + 1),
            cell_mm_xyz=cell,
            instance_origin_mm=dict(x=-radius, y=-radius, z=z_min),
            bounds_mm=dict(x_min=-radius, x_max=radius, y_min=-radius, y_max=radius,
                           z_min=z_min, z_max=z_max),
        )
        identities[name] = dict(resolved_content_sha256=_content_sha256(design),
                                component_interface_sha256=_content_sha256(plan["components"][name]))
    frontend = dict(role="simion_independent_rf_geometry", composition_plan=plan,
                    numerical_domains=compiled_domains, electrode_bindings=bindings,
                    raw_physical_samples={})
    return CompiledSimionGeometry(gems, frontend, (), identities, copy.deepcopy(dict(components)))
