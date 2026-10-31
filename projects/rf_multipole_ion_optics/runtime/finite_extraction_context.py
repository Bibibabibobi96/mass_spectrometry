"""Project extraction science from frozen resolved facts; never resolve a profile."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from collections.abc import Mapping
from typing import Any

from projects.rf_multipole_ion_optics.core.interface_geometry import (
    transport_numerical_domain, transport_observations,
)


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _section(section: Mapping[str, Any]) -> dict[str, Any]:
    shape = section["shape"]
    if shape == "circle":
        _number(section["radius_mm"], "port radius", positive=True)
    elif shape == "open_rod_envelope":
        _number(section["inscribed_radius_mm"], "open reference envelope", positive=True)
    else:
        raise ValueError("unsupported frozen finite extraction port shape")
    return deepcopy(dict(section))


def project_finite_extraction_science(
    resolved: Mapping[str, Any], numerics: Mapping[str, Any], source_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a JSON-safe science template for normal and saved-solution owners.

    Callers verify frozen file identities. Actual solution/dataset identifiers,
    release mapping, source rows and child output paths are deliberately absent;
    the native owner binds those facts and validates them against the saved model.
    """
    if resolved["role"] != "multipole_resolved_design_do_not_edit":
        raise ValueError("frozen multipole resolved design required")
    if (source_metadata["role"] != "multipole_canonical_particle_source_metadata"
            or source_metadata["parent_resolved_design_sha256"] != resolved["resolved_sha256"]):
        raise ValueError("frozen source is not bound to resolved design")
    count = source_metadata["particle_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("frozen mother count must be positive integer")
    _number(source_metadata["mass_amu"], "source mass", positive=True)
    charge = _number(source_metadata["charge_state"], "source charge")
    if charge == 0 or charge != int(charge) or charge != resolved["particle_source"]["charge_state"]:
        raise ValueError("source charge differs from resolved species")
    if numerics["role"] != "multipole_comsol_solver_numerics":
        raise ValueError("frozen finite COMSOL numerics required")
    steps = _number(numerics["trajectory"]["rf_steps_per_period"], "RF steps", positive=True)
    if steps != int(steps):
        raise ValueError("RF steps must be integer")
    _number(numerics["trajectory"]["maximum_global_time_us"], "global time", positive=True)

    geometry = resolved["geometry_mm"]
    model = geometry["enclosure"]["model"]
    if model not in {"bare", "cylindrical_grounded_shell", "rectangular_reference_enclosure_v1"}:
        raise ValueError("unsupported frozen finite enclosure")
    observations = transport_observations(resolved)
    domain = transport_numerical_domain(resolved)
    d = {"rod_z_min": geometry["rod_z_min"], "rod_z_max": geometry["rod_z_max"],
         "census_plane_z": observations["census_plane_z_mm"],
         "handoff_plane_z": observations["handoff_plane_z_mm"]}
    if model == "rectangular_reference_enclosure_v1":
        entrance, exit_port = resolved["interfaces_mm"]["entrance"], resolved["interfaces_mm"]["exit"]
        d["entrance_port_plane_z"] = entrance["aperture_plate_downstream_face_z_mm"]
        d["exit_port_plane_z"] = exit_port["aperture_crossing_plane_z_mm"]
        sections = [{"shape": "circle", "radius_mm": port["aperture_radius_mm"]}
                    for port in (entrance, exit_port)]
        census_radius = geometry["enclosure"]["physical_detector_radius_mm"]
    else:
        ports = geometry["enclosure_layout"]["ports"]
        entrance, exit_port = ports["mechanical_entrance"], ports["mechanical_exit"]
        d["entrance_port_plane_z"], d["exit_port_plane_z"] = entrance["center_mm"][2], exit_port["center_mm"][2]
        sections = [port["cross_section"] for port in (entrance, exit_port)]
        census_radius = observations["acceptance_radius_mm"]
    for key, value in d.items():
        _number(value, key)
    if d["rod_z_max"] <= d["rod_z_min"]:
        raise ValueError("frozen rod interval is invalid")
    acceptance = {
        "working_region_radius": _number(domain["working_region_radius_mm"], "working radius", positive=True),
        "entrance_interface": {"cross_section": _section(sections[0])},
        "exit_interface": {"cross_section": _section(sections[1])},
    }
    drive = deepcopy(dict(resolved["drive"]))
    _number(drive["frequency_Hz"], "RF frequency", positive=True)
    _number(drive["phase_rad"], "RF phase")
    topology = resolved["axial_drive"]["topology"]
    if topology not in {"none", "segmented_rod_axial_acceleration"}:
        raise ValueError("unsupported frozen finite axial topology")
    primary, control = (("finite_3d_rf_on", "zero_rf_control") if topology == "none"
                        else ("axial_acceleration_rf_on", "zero_axial_drop_rf_on"))
    result = {"geometry": d, "acceptance": acceptance,
              "census_radius_mm": _number(census_radius, "census radius", positive=True),
              "drive": drive, "primary_case_id": primary, "control_case_id": control,
              "resolved_design_sha256": resolved["resolved_sha256"]}
    json.dumps(result, allow_nan=False)
    return result
