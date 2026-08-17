"""Compile and render the single authoritative oaTOF region-field contract."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from common.contracts.file_identity import file_sha256


ROLE = "rf_oatof_resolved_region_field_contract"
SCHEMA_VERSION = 1
THREE_ZONE_SCHEMA_VERSION = 2
THREE_ZONE_PROFILE_ID = "accelerator_ideal_three_zone_real_reflectron"
THREE_ZONE_TOPOLOGY_ID = "three_zone_accelerator_ideal_v1"
FULL_FIELD_NAME = "FULL_DOMAIN_PIECEWISE_IDEAL_FIELD"
MODES = frozenset({"real_pa_field", "analytic_ideal_field", "zero_field"})
REGIONS = (
    "accelerator_stage1",
    "accelerator_stage2",
    "drift",
    "reflectron_stage1",
    "reflectron_stage2",
)
THREE_ZONE_REGIONS = (
    "accelerator_zone1",
    "accelerator_zone2",
    "accelerator_zone3",
    "drift",
    "reflectron_stage1",
    "reflectron_stage2",
)
PROFILE_MODES = {
    "accelerator_real_pa": ("real_pa_field", "real_pa_field"),
    "accelerator_ideal_stage1_real_stage2": ("analytic_ideal_field", "real_pa_field"),
    "accelerator_real_stage1_ideal_stage2": ("real_pa_field", "analytic_ideal_field"),
    "accelerator_ideal_stage1_stage2_real_reflectron": (
        "analytic_ideal_field",
        "analytic_ideal_field",
    ),
}
FULL_ID = "full_domain_piecewise_ideal_field"
FIELD_CONFIGURATION_IDS = {
    "accelerator_real_pa": "REAL_ACCELERATOR_REAL_REFLECTOR_FIELD",
    "accelerator_ideal_stage1_real_stage2": "IDEAL_STAGE1_REAL_STAGE2_REAL_REFLECTOR_FIELD",
    "accelerator_real_stage1_ideal_stage2": "REAL_STAGE1_IDEAL_STAGE2_REAL_REFLECTOR_FIELD",
    "accelerator_ideal_stage1_stage2_real_reflectron": "IDEAL_ACCELERATOR_REAL_REFLECTOR_FIELD",
    FULL_ID: FULL_FIELD_NAME,
    THREE_ZONE_PROFILE_ID: "IDEAL_THREE_ZONE_ACCELERATOR_REAL_REFLECTOR_FIELD",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def semantic_sha256(semantic: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def canonical_profile_id(profile_id: str) -> str:
    """Return an already canonical profile ID; execution aliases are forbidden."""
    if profile_id not in {*PROFILE_MODES, FULL_ID, THREE_ZONE_PROFILE_ID}:
        raise ValueError(f"unsupported accelerator field profile: {profile_id}")
    return profile_id


def _region_modes(profile_id: str) -> dict[str, str]:
    canonical = canonical_profile_id(profile_id)
    if canonical == FULL_ID:
        return {
            "accelerator_stage1": "analytic_ideal_field",
            "accelerator_stage2": "analytic_ideal_field",
            "drift": "zero_field",
            "reflectron_stage1": "analytic_ideal_field",
            "reflectron_stage2": "analytic_ideal_field",
        }
    if canonical not in PROFILE_MODES:
        raise ValueError(f"unsupported accelerator field profile: {profile_id}")
    stage1, stage2 = PROFILE_MODES[canonical]
    return {
        "accelerator_stage1": stage1,
        "accelerator_stage2": stage2,
        "drift": "real_pa_field",
        "reflectron_stage1": "real_pa_field",
        "reflectron_stage2": "real_pa_field",
    }


def build_resolved_region_field_contract(
    resolved_geometry_path: Path,
    output_path: Path,
    profile_id: str,
    *,
    accelerator_topology: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a path-free semantic contract plus separately frozen source identity."""
    geometry = _load(resolved_geometry_path)
    if geometry.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("region field contract requires resolved oaTOF geometry")
    geom = geometry["geometry_mm"]
    voltage = geometry["electrodes_V"]
    canonical = canonical_profile_id(profile_id)
    if accelerator_topology is not None:
        return _build_three_zone_contract(
            resolved_geometry_path,
            output_path,
            geometry,
            canonical,
            accelerator_topology,
        )
    if canonical == THREE_ZONE_PROFILE_ID:
        raise ValueError("three-zone field profile requires accelerator_topology")
    modes = _region_modes(canonical)
    planes = {
        "repeller": float(geom["accelerator_repeller_z"]),
        "grid1": float(geom["accelerator_grid1_z"]),
        "grid2": float(geom["accelerator_grid2_z"]),
        "reflectron_entrance": float(geom["L_flight"]),
        "reflectron_midgrid": float(geom["L_flight"]) + float(geom["L_stage1"]),
        "reflectron_backplate": float(geom["L_flight"])
        + float(geom["L_stage1"])
        + float(geom["L_stage2"]),
    }
    if not (
        planes["repeller"] < planes["grid1"] < planes["grid2"]
        <= planes["reflectron_entrance"] < planes["reflectron_midgrid"]
        < planes["reflectron_backplate"]
    ):
        raise ValueError("resolved region field planes are not ordered")
    fields = {
        "accelerator_stage1": (float(voltage["repeller"]) - float(voltage["grid1"]))
        / (planes["grid1"] - planes["repeller"]),
        "accelerator_stage2": (float(voltage["grid1"]) - float(voltage["grid2"]))
        / (planes["grid2"] - planes["grid1"]),
        "reflectron_stage1": (float(voltage["midgrid"]) - float(voltage["entgrid"]))
        / (planes["reflectron_midgrid"] - planes["reflectron_entrance"]),
        "reflectron_stage2": (float(voltage["backplate"]) - float(voltage["midgrid"]))
        / (planes["reflectron_backplate"] - planes["reflectron_midgrid"]),
    }
    if any(not math.isfinite(value) for value in fields.values()):
        raise ValueError("resolved region field contains a non-finite field")
    finite = geometry["geometry_derivation"]["accelerator"].get(
        "finite_interval_theory"
    )
    if isinstance(finite, Mapping):
        expected = {
            "repeller": float(finite["repeller_v"]),
            "grid1": float(finite["intermediate_v"]),
            "grid2": float(finite["exit_v"]),
        }
        if any(abs(float(voltage[key]) - value) > 1e-8 for key, value in expected.items()):
            raise ValueError("resolved accelerator voltage differs from finite-interval design")
    layout = geometry.get("single_flight_layout_derivation", {})
    semantic = {
        "field_configuration_id": FIELD_CONFIGURATION_IDS[canonical],
        "canonical_profile_id": canonical,
        "region_modes": modes,
        "planes_mm": planes,
        "fields_V_per_mm": fields,
        "effective_domain": {
            "longitudinal": "closed_piecewise_path_repeller_to_reflectron_backplate",
            "transverse": "analytic_field_extends_until_native_pa_geometry_collision",
            "outside_longitudinal_domain": "invalid_trajectory_error",
        },
        "pa_role": "geometry_and_collision_carrier_plus_explicit_real_pa_field_regions",
        "real_pa_field_blending_allowed": False,
        "instance_coordinate_mapping": {
            "accelerator": {
                "accepted_workbench_instances": [3, 5],
                "global_field_axis": "z",
                "local_derivative_axis": "z",
            },
            "reflectron": {
                "workbench_instance": 2,
                "az_deg": -90.0,
                "global_field_axis": "z",
                "local_derivative_axis": "x",
            },
        },
    }
    contract = {
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "layout_geometry": {
            "sha256": file_sha256(resolved_geometry_path),
            "layout_profile_id": layout.get("layout_profile_id"),
            "architecture_generation_id": layout.get("architecture_generation_id"),
        },
        "semantic": semantic,
        "semantic_sha256": semantic_sha256(semantic),
    }
    validate_resolved_region_field_contract(contract)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return contract


def _exact_numeric_mapping(value: object, name: str) -> dict[str, float]:
    keys = {"repeller", "intermediate1", "intermediate2", "exit"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{name} must contain exactly {sorted(keys)}")
    result = {key: float(value[key]) for key in keys}
    if any(not math.isfinite(item) for item in result.values()):
        raise ValueError(f"{name} contains a non-finite value")
    return result


def _build_three_zone_contract(
    resolved_geometry_path: Path,
    output_path: Path,
    geometry: Mapping[str, Any],
    canonical: str,
    accelerator_topology: Mapping[str, Any],
) -> dict[str, Any]:
    if canonical != THREE_ZONE_PROFILE_ID:
        raise ValueError("accelerator_topology is only valid for the three-zone profile")
    if set(accelerator_topology) != {
        "topology_id",
        "planes_global_z_mm",
        "potentials_v",
    }:
        raise ValueError("three-zone accelerator topology fields are incomplete")
    if accelerator_topology.get("topology_id") != THREE_ZONE_TOPOLOGY_ID:
        raise ValueError("unsupported three-zone accelerator topology identity")
    accelerator_planes = _exact_numeric_mapping(
        accelerator_topology["planes_global_z_mm"], "three-zone planes_global_z_mm"
    )
    potentials = _exact_numeric_mapping(
        accelerator_topology["potentials_v"], "three-zone potentials_v"
    )
    electrode_order = ("repeller", "intermediate1", "intermediate2", "exit")
    if not all(
        accelerator_planes[left] < accelerator_planes[right]
        for left, right in zip(electrode_order, electrode_order[1:])
    ):
        raise ValueError("three-zone accelerator planes must increase strictly")
    if not all(
        potentials[left] > potentials[right]
        for left, right in zip(electrode_order, electrode_order[1:])
    ):
        raise ValueError("three-zone accelerator potentials must decrease strictly")

    geom = geometry["geometry_mm"]
    voltage = geometry["electrodes_V"]
    planes = {
        **{key: accelerator_planes[key] for key in electrode_order},
        "reflectron_entrance": float(geom["L_flight"]),
        "reflectron_midgrid": float(geom["L_flight"]) + float(geom["L_stage1"]),
        "reflectron_backplate": float(geom["L_flight"])
        + float(geom["L_stage1"])
        + float(geom["L_stage2"]),
    }
    if not (
        planes["exit"] <= planes["reflectron_entrance"]
        < planes["reflectron_midgrid"]
        < planes["reflectron_backplate"]
    ):
        raise ValueError("three-zone field planes conflict with the reflectron domain")
    fields = {
        "accelerator_zone1": (potentials["repeller"] - potentials["intermediate1"])
        / (planes["intermediate1"] - planes["repeller"]),
        "accelerator_zone2": (
            potentials["intermediate1"] - potentials["intermediate2"]
        )
        / (planes["intermediate2"] - planes["intermediate1"]),
        "accelerator_zone3": (potentials["intermediate2"] - potentials["exit"])
        / (planes["exit"] - planes["intermediate2"]),
        "reflectron_stage1": (float(voltage["midgrid"]) - float(voltage["entgrid"]))
        / (planes["reflectron_midgrid"] - planes["reflectron_entrance"]),
        "reflectron_stage2": (
            float(voltage["backplate"]) - float(voltage["midgrid"])
        )
        / (planes["reflectron_backplate"] - planes["reflectron_midgrid"]),
    }
    layout = geometry.get("single_flight_layout_derivation", {})
    semantic = {
        "field_configuration_id": FIELD_CONFIGURATION_IDS[canonical],
        "canonical_profile_id": canonical,
        "accelerator_topology": {
            "topology_id": THREE_ZONE_TOPOLOGY_ID,
            "planes_global_z_mm": {
                key: accelerator_planes[key] for key in electrode_order
            },
            "potentials_v": {key: potentials[key] for key in electrode_order},
        },
        "region_modes": {
            "accelerator_zone1": "analytic_ideal_field",
            "accelerator_zone2": "analytic_ideal_field",
            "accelerator_zone3": "analytic_ideal_field",
            "drift": "real_pa_field",
            "reflectron_stage1": "real_pa_field",
            "reflectron_stage2": "real_pa_field",
        },
        "planes_mm": planes,
        "fields_V_per_mm": fields,
        "effective_domain": {
            "longitudinal": "closed_piecewise_path_repeller_to_reflectron_backplate",
            "transverse": "analytic_field_extends_until_native_pa_geometry_collision",
            "outside_longitudinal_domain": "invalid_trajectory_error",
        },
        "pa_role": "geometry_and_collision_carrier_plus_explicit_real_pa_field_regions",
        "real_pa_field_blending_allowed": False,
        "instance_coordinate_mapping": {
            "accelerator": {
                "accepted_workbench_instances": [3, 5],
                "global_field_axis": "z",
                "local_derivative_axis": "z",
            },
            "reflectron": {
                "workbench_instance": 2,
                "az_deg": -90.0,
                "global_field_axis": "z",
                "local_derivative_axis": "x",
            },
        },
    }
    contract = {
        "schema_version": THREE_ZONE_SCHEMA_VERSION,
        "role": ROLE,
        "layout_geometry": {
            "sha256": file_sha256(resolved_geometry_path),
            "layout_profile_id": layout.get("layout_profile_id"),
            "architecture_generation_id": layout.get("architecture_generation_id"),
        },
        "semantic": semantic,
        "semantic_sha256": semantic_sha256(semantic),
    }
    validate_resolved_region_field_contract(contract)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return contract


def validate_resolved_region_field_contract(contract: Mapping[str, Any]) -> None:
    schema_version = contract.get("schema_version")
    if schema_version not in {SCHEMA_VERSION, THREE_ZONE_SCHEMA_VERSION} or contract.get("role") != ROLE:
        raise ValueError("unsupported resolved region field contract")
    semantic = contract.get("semantic")
    if not isinstance(semantic, Mapping):
        raise ValueError("resolved region field semantic object is required")
    if semantic_sha256(semantic) != contract.get("semantic_sha256"):
        raise ValueError("resolved region field semantic SHA differs")
    modes = semantic.get("region_modes")
    expected_regions = THREE_ZONE_REGIONS if schema_version == THREE_ZONE_SCHEMA_VERSION else REGIONS
    if not isinstance(modes, Mapping) or set(modes) != set(expected_regions):
        raise ValueError("resolved region field regions are incomplete")
    if any(mode not in MODES for mode in modes.values()):
        raise ValueError("resolved region field contains an unsupported mode")
    if semantic.get("real_pa_field_blending_allowed") is not False:
        raise ValueError("resolved region field must prohibit real-PA blending")
    profile_id = semantic.get("canonical_profile_id")
    if semantic.get("field_configuration_id") != FIELD_CONFIGURATION_IDS.get(profile_id):
        raise ValueError("resolved region field scientific configuration identity differs")
    if schema_version == THREE_ZONE_SCHEMA_VERSION:
        _validate_three_zone_semantic(semantic)
    elif semantic.get("accelerator_topology") is not None or profile_id == THREE_ZONE_PROFILE_ID:
        raise ValueError("schema-v1 cannot declare a three-zone accelerator")
    if profile_id == FULL_ID and any(
        mode == "real_pa_field" for mode in modes.values()
    ):
        raise ValueError("full-domain ideal field cannot contain a real-PA region")
    domain = semantic.get("effective_domain", {})
    if domain.get("outside_longitudinal_domain") != "invalid_trajectory_error":
        raise ValueError("analytic effective-domain escape must fail closed")
    if domain.get("transverse") != "analytic_field_extends_until_native_pa_geometry_collision":
        raise ValueError("analytic field cannot silently fall back outside a bore")


def _validate_three_zone_semantic(semantic: Mapping[str, Any]) -> None:
    if semantic.get("canonical_profile_id") != THREE_ZONE_PROFILE_ID:
        raise ValueError("schema-v2 requires the explicit three-zone profile identity")
    topology = semantic.get("accelerator_topology")
    if not isinstance(topology, Mapping) or set(topology) != {
        "topology_id",
        "planes_global_z_mm",
        "potentials_v",
    }:
        raise ValueError("schema-v2 three-zone accelerator topology is incomplete")
    if topology.get("topology_id") != THREE_ZONE_TOPOLOGY_ID:
        raise ValueError("schema-v2 three-zone topology identity differs")
    planes = _exact_numeric_mapping(
        topology.get("planes_global_z_mm"), "three-zone planes_global_z_mm"
    )
    potentials = _exact_numeric_mapping(
        topology.get("potentials_v"), "three-zone potentials_v"
    )
    electrode_order = ("repeller", "intermediate1", "intermediate2", "exit")
    if not all(
        planes[left] < planes[right]
        for left, right in zip(electrode_order, electrode_order[1:])
    ):
        raise ValueError("three-zone accelerator planes must increase strictly")
    if not all(
        potentials[left] > potentials[right]
        for left, right in zip(electrode_order, electrode_order[1:])
    ):
        raise ValueError("three-zone accelerator potentials must decrease strictly")
    if any(semantic["region_modes"][key] != "analytic_ideal_field" for key in THREE_ZONE_REGIONS[:3]):
        raise ValueError("three-zone accelerator regions must use analytic ideal fields")
    if any(
        semantic["region_modes"][key] != "real_pa_field"
        for key in THREE_ZONE_REGIONS[3:]
    ):
        raise ValueError("three-zone downstream regions must preserve the real PA field")
    published_planes = semantic.get("planes_mm")
    expected_plane_keys = {
        *electrode_order,
        "reflectron_entrance",
        "reflectron_midgrid",
        "reflectron_backplate",
    }
    if not isinstance(published_planes, Mapping) or set(published_planes) != expected_plane_keys or any(
        published_planes.get(key) != planes[key] for key in electrode_order
    ):
        raise ValueError("three-zone topology and published field planes differ")
    if not (
        float(published_planes["exit"])
        <= float(published_planes["reflectron_entrance"])
        < float(published_planes["reflectron_midgrid"])
        < float(published_planes["reflectron_backplate"])
    ):
        raise ValueError("three-zone downstream field planes are not ordered")
    published_fields = semantic.get("fields_V_per_mm")
    accelerator_fields = ("accelerator_zone1", "accelerator_zone2", "accelerator_zone3")
    expected_field_keys = {
        *accelerator_fields,
        "reflectron_stage1",
        "reflectron_stage2",
    }
    if not isinstance(published_fields, Mapping) or set(published_fields) != expected_field_keys:
        raise ValueError("three-zone accelerator fields are incomplete")
    expected_fields = (
        (potentials["repeller"] - potentials["intermediate1"])
        / (planes["intermediate1"] - planes["repeller"]),
        (potentials["intermediate1"] - potentials["intermediate2"])
        / (planes["intermediate2"] - planes["intermediate1"]),
        (potentials["intermediate2"] - potentials["exit"])
        / (planes["exit"] - planes["intermediate2"]),
    )
    if any(
        not math.isclose(float(published_fields[key]), expected, rel_tol=1e-12, abs_tol=1e-12)
        for key, expected in zip(accelerator_fields, expected_fields, strict=True)
    ):
        raise ValueError("three-zone accelerator field sign or magnitude differs")


def resolved_region_field_hook_lua(
    contract: Mapping[str, Any], *, prefix: str = "rrf"
) -> str:
    """Render a callback-neutral integration override for one resolved profile.

    The returned Lua module accepts the project-owned base field result and
    changes it only when the resolved contract selects an analytic or zero
    field for the particle's current longitudinal region.  Real-PA regions
    return the base result unchanged.
    """
    validate_resolved_region_field_contract(contract)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", prefix):
        raise ValueError("Lua prefix must be a lowercase identifier")
    if contract["schema_version"] == THREE_ZONE_SCHEMA_VERSION:
        return _three_zone_region_field_hook_lua(contract, prefix)
    semantic = contract["semantic"]
    p = semantic["planes_mm"]
    f = semantic["fields_V_per_mm"]
    m = semantic["region_modes"]
    mode_codes = {"real_pa_field": 0, "analytic_ideal_field": 1, "zero_field": 2}
    return f"""
local {prefix}={{}}
local {prefix}_repeller={p['repeller']:.17g}
local {prefix}_grid1={p['grid1']:.17g}
local {prefix}_grid2={p['grid2']:.17g}
local {prefix}_entrance={p['reflectron_entrance']:.17g}
local {prefix}_midgrid={p['reflectron_midgrid']:.17g}
local {prefix}_backplate={p['reflectron_backplate']:.17g}
local {prefix}_accel1={f['accelerator_stage1']:.17g}
local {prefix}_accel2={f['accelerator_stage2']:.17g}
local {prefix}_refl1={f['reflectron_stage1']:.17g}
local {prefix}_refl2={f['reflectron_stage2']:.17g}
local {prefix}_m_accel1={mode_codes[m['accelerator_stage1']]}
local {prefix}_m_accel2={mode_codes[m['accelerator_stage2']]}
local {prefix}_m_drift={mode_codes[m['drift']]}
local {prefix}_m_refl1={mode_codes[m['reflectron_stage1']]}
local {prefix}_m_refl2={mode_codes[m['reflectron_stage2']]}
function {prefix}.apply(base,state)
  assert(type(state)=='table' and type(state.z_mm)=='number' and
    type(state.instance_id)=='number' and type(state.instance_dx_mm)=='number' and
    type(state.instance_dz_mm)=='number' and type(state.instance_scale)=='number' and
    type(state.pulse_active)=='boolean','resolved region state is invalid')
  if not state.pulse_active then return base end
  local z=state.z_mm; local mode=nil; local E=0; local family=nil
  if z>={prefix}_repeller and z<{prefix}_grid1 then mode={prefix}_m_accel1; E={prefix}_accel1; family='accelerator'
  elseif z>={prefix}_grid1 and z<{prefix}_grid2 then mode={prefix}_m_accel2; E={prefix}_accel2; family='accelerator'
  elseif z>={prefix}_grid2 and z<{prefix}_entrance then mode={prefix}_m_drift
  elseif z>={prefix}_entrance and z<{prefix}_midgrid then mode={prefix}_m_refl1; E=-{prefix}_refl1; family='reflectron'
  elseif z>={prefix}_midgrid and z<={prefix}_backplate then mode={prefix}_m_refl2; E=-{prefix}_refl2; family='reflectron'
  else error('particle escaped resolved region-field longitudinal domain') end
  if mode==0 then return base end
  if mode==2 then return {{replace_all=true,dvoltsx_gu=0,dvoltsy_gu=0,dvoltsz_gu=0}} end
  if family=='accelerator' then
    assert(state.instance_id==3 or state.instance_id==5,
      'analytic accelerator field requires instance 3 or 5')
    return {{replace_all=true,dvoltsx_gu=0,dvoltsy_gu=0,
      dvoltsz_gu=-E*state.instance_dz_mm*state.instance_scale}}
  end
  assert(state.instance_id==2,'analytic reflectron field requires rotated instance 2')
  return {{replace_all=true,dvoltsx_gu=-E*state.instance_dx_mm*state.instance_scale,
    dvoltsy_gu=0,dvoltsz_gu=0}}
end
return {prefix}
""".strip()


def _three_zone_region_field_hook_lua(
    contract: Mapping[str, Any], prefix: str
) -> str:
    semantic = contract["semantic"]
    planes = semantic["planes_mm"]
    fields = semantic["fields_V_per_mm"]
    return f"""
local {prefix}={{}}
local {prefix}_repeller={planes['repeller']:.17g}
local {prefix}_intermediate1={planes['intermediate1']:.17g}
local {prefix}_intermediate2={planes['intermediate2']:.17g}
local {prefix}_exit={planes['exit']:.17g}
local {prefix}_backplate={planes['reflectron_backplate']:.17g}
local {prefix}_zone1={fields['accelerator_zone1']:.17g}
local {prefix}_zone2={fields['accelerator_zone2']:.17g}
local {prefix}_zone3={fields['accelerator_zone3']:.17g}
function {prefix}.apply(base,state)
  assert(type(state)=='table' and type(state.z_mm)=='number' and
    type(state.instance_id)=='number' and type(state.instance_dx_mm)=='number' and
    type(state.instance_dz_mm)=='number' and type(state.instance_scale)=='number' and
    type(state.pulse_active)=='boolean','resolved region state is invalid')
  if not state.pulse_active then return base end
  local z=state.z_mm; local E=nil
  if z>={prefix}_repeller and z<{prefix}_intermediate1 then E={prefix}_zone1
  elseif z>={prefix}_intermediate1 and z<{prefix}_intermediate2 then E={prefix}_zone2
  elseif z>={prefix}_intermediate2 and z<{prefix}_exit then E={prefix}_zone3
  elseif z>={prefix}_exit and z<={prefix}_backplate then return base
  else error('particle escaped resolved region-field longitudinal domain') end
  assert(state.instance_id==3 or state.instance_id==5,
    'analytic accelerator field requires instance 3 or 5')
  return {{replace_all=true,dvoltsx_gu=0,dvoltsy_gu=0,
    dvoltsz_gu=-E*state.instance_dz_mm*state.instance_scale}}
end
return {prefix}
""".strip()
