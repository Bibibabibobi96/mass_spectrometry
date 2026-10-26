"""Build the continuous SIMION Program from frozen oaTOF and multipole contracts."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from common.contracts.rigid_transform import FramedPosition, RigidTransform, relative_transform
from projects.rf_multipole_ion_optics.simion.simion_geometry import segmented_rod_electrode_ids
from integrations.runtime.single_flight_source import canonical_clock_lua, lua_number as _lua_number, lua_value as _lua_value
from integrations.runtime.single_flight_electrode_contract import (
    ROD_ELECTRODE_IDS,
    THREE_ZONE_BARE_VARIANT,
    TWO_ZONE_BARE_VARIANT,
    project_pa_plus_mode_voltages,
    physical_multipole_voltages,
    require_pa_plus_solution_model,
)
from integrations.runtime.pure_boundary_validator import (
    validate_pure_lua_component_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_electrical import resolve_accelerator_electrical_design
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import derive_simion_geometry

_DIAGNOSTIC_RETURN_PLANE_Z_MM = 20.5
_SUCCESSOR_DIAGNOSTICS = {"post_pulse_observation_window_us": 90.0, "log_stride": 1000}


STANDALONE_DYNAMIC_FIELD_BANK_ROLE = (
    "rf_oatof_simion_standalone_dynamic_field_bank"
)
STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION = 2
STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION = (
    "standalone_operating_pa_explicit_dynamic_v1"
)
DOWNSTREAM_STATIC_ASSET_ROLE = "single_reflection_downstream_static_assets"
DOWNSTREAM_STATIC_ASSET_REPRESENTATION = "run_private_native_surface_and_standalone_static_v1"
_DOWNSTREAM_STATIC_ROLES = {
    "flight_tube",
    "reflectron",
    "detector",
}


def _ordinary_standalone_pa_basename(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or re.fullmatch(r"[^/\\]+\.[pP][aA]", value) is None
    ):
        raise ValueError(f"{label} must be one ordinary standalone .pa basename")
    return value


def _resolve_standalone_dynamic_field_bank(
    contract: dict[str, Any], expected_role_indices: dict[str, int], *, requires_rf: bool = True,
) -> list[dict[str, Any]]:
    """Validate one explicit standalone field bank against the active IOB roles."""

    if set(contract) != {
        "schema_version",
        "role",
        "runtime_representation",
        "dynamic_roles",
    } or (
        contract.get("schema_version") != STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION
        or contract.get("role") != STANDALONE_DYNAMIC_FIELD_BANK_ROLE
        or contract.get("runtime_representation")
        != STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION
    ):
        raise ValueError("standalone dynamic field bank identity differs")
    rows = contract.get("dynamic_roles")
    if not isinstance(rows, list) or not rows:
        raise ValueError("standalone dynamic field bank roles are missing")
    normalized: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    seen_indices: set[int] = set()
    seen_basenames: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not {
            "role",
            "instance_index",
            "carrier_pa_basename",
        }.issubset(row) or not set(row).issubset(
            {
                "role",
                "instance_index",
                "carrier_pa_basename",
                "rf_differential_pa_basenames",
                "pulse_delta_pa_basename",
                "rf_reference_voltage_v",
            }
        ):
            raise ValueError("standalone dynamic field bank role fields differ")
        role = row["role"]
        index = row["instance_index"]
        if (
            not isinstance(role, str)
            or role not in expected_role_indices
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index != expected_role_indices[role]
            or role in seen_roles
            or index in seen_indices
        ):
            raise ValueError("standalone dynamic field bank role/index differs")
        carrier = _ordinary_standalone_pa_basename(
            row["carrier_pa_basename"], f"standalone {role} carrier"
        )
        rf_members = row.get("rf_differential_pa_basenames", [])
        if not isinstance(rf_members, list):
            raise ValueError("standalone RF responses must be an ordered basename list")
        rf_differential = [_ordinary_standalone_pa_basename(value,
            f"standalone {role} RF differential") for value in rf_members]
        if requires_rf != bool(rf_differential):
            raise ValueError("standalone dynamic field bank RF response differs from its active scope")
        raw_pulse_delta = row.get("pulse_delta_pa_basename")
        pulse_delta = (
            None
            if raw_pulse_delta is None
            else _ordinary_standalone_pa_basename(
                raw_pulse_delta, f"standalone {role} pulse delta"
            )
        )
        if not rf_differential and "rf_reference_voltage_v" in row:
            raise ValueError("RF-free field bank cannot declare an RF reference")
        reference = row.get("rf_reference_voltage_v") if rf_differential else None
        if rf_differential and (isinstance(reference, bool) or not isinstance(reference, (int, float))
                or not math.isfinite(reference) or reference <= 0):
            raise ValueError("standalone RF reference voltage must be finite and positive")
        basenames = [carrier, *rf_differential, *([pulse_delta] if pulse_delta else [])]
        if len(set(basenames)) != len(basenames) or any(
            basename in seen_basenames for basename in basenames
        ):
            raise ValueError("standalone dynamic field bank PA basenames are not unique")
        seen_roles.add(role)
        seen_indices.add(index)
        seen_basenames.update(basenames)
        normalized.append(
            {
                "role": role,
                "instance_index": index,
                "carrier_pa_basename": carrier,
                **({"rf_differential_pa_basenames":rf_differential,"rf_reference_voltage_v":float(reference)}
                   if rf_differential else {}),
                "pulse_delta_pa_basename": pulse_delta,
            }
        )
    if seen_roles != set(expected_role_indices):
        raise ValueError("standalone dynamic field bank active roles differ")
    return sorted(normalized, key=lambda row: int(row["instance_index"]))


def _resolve_downstream_static_assets(contract: dict[str, Any], expected_role_indices: dict[str, int]) -> list[dict[str, Any]]:
    """Consume receipt-derived assets; the runtime owns receipt and payload I/O.

    Native surface families must have been built fresh in this run. Published
    cache-family copies are not admissible: their provenance is established by
    the publishing receipt, never by a filename or this pure Program builder.
    """
    if (set(contract) != {"schema_version", "role", "runtime_representation", "receipt", "static_roles"}
            or contract["schema_version"] != 1 or contract["role"] != DOWNSTREAM_STATIC_ASSET_ROLE
            or contract["runtime_representation"] != DOWNSTREAM_STATIC_ASSET_REPRESENTATION):
        raise ValueError("downstream static asset contract identity differs")
    receipt = contract["receipt"]
    if (not isinstance(receipt, dict) or set(receipt) != {"path", "bytes", "sha256"}
            or not isinstance(receipt["path"], str) or not receipt["path"]
            or isinstance(receipt["bytes"], bool) or not isinstance(receipt["bytes"], int) or receipt["bytes"] <= 0
            or not isinstance(receipt["sha256"], str) or re.fullmatch(r"[0-9A-Fa-f]{64}", receipt["sha256"]) is None):
        raise ValueError("downstream static assets require their publishing receipt file record")
    rows = contract["static_roles"]
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("downstream static assets require exactly three roles")
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not {"role", "instance_index", "representation", "carrier_pa_basename"}.issubset(row):
            raise ValueError("downstream static asset fields differ")
        role = row["role"]
        index = row["instance_index"]
        if (not isinstance(role, str) or role not in expected_role_indices or role in seen
                or isinstance(index, bool) or not isinstance(index, int) or index != expected_role_indices[role]):
            raise ValueError("downstream static asset role/index differs")
        if role == "reflectron":
            if (set(row) != {"role", "instance_index", "representation", "carrier_pa_basename"}
                    or row["representation"] != "standalone_voltageized_static_pa"):
                raise ValueError("reflectron requires its standalone voltageized static PA")
            _ordinary_standalone_pa_basename(row["carrier_pa_basename"], "reflectron carrier")
        else:
            if (set(row) != {"role", "instance_index", "representation", "carrier_pa_basename", "family_members"}
                    or row["representation"] != "run_private_native_static_family"):
                raise ValueError("surface asset requires a fresh run-private native static family")
            carrier = row["carrier_pa_basename"]
            if not isinstance(carrier, str) or re.fullmatch(r"[^/\\]+\.pa0", carrier) is None:
                raise ValueError("native static carrier must be a .pa0 basename")
            stem = carrier[:-1]
            members = row["family_members"]
            # These actual providers each have one grounded electrode, so the
            # complete family is PA#, PA0, PA1 and fractional-surface metadata.
            if (not isinstance(members, list) or len(members) != 4
                    or any(not isinstance(name, str) for name in members)
                    or set(members) != {stem+"#", stem+"0", stem+"1", stem+"-surf"}):
                raise ValueError("native static family requires its complete same-stem PA and surface members")
        normalized.append(dict(row))
        seen.add(role)
    if seen != _DOWNSTREAM_STATIC_ROLES:
        raise ValueError("downstream static asset active roles differ")
    return sorted(normalized, key=lambda row: row["instance_index"])


def _upstream_rod_drive(upstream: Mapping[str, Any]) -> dict[str, Any]:
    """Project declared segmented or continuous rods to the same RF kernel input.

    Bare-guide rods are individual physical rods, never fictitious axial
    segments. This projection does not create shields or entrance electrodes.
    """
    if upstream.get("role") == "ion_processor_bare_guide_interface":
        if upstream.get("schema_version") != 1:
            raise ValueError("unsupported bare-guide interface schema")
        drive = upstream["drive"]
        group_dc = [float(value) for value in drive["group_dc_v"]]
        if (len(group_dc) != 2 or not all(math.isfinite(value) for value in group_dc)
                or group_dc[1] != -group_dc[0]
                or drive["group_polarities"] != {"1": 1, "2": -1}):
            raise ValueError("bare-guide RF group drive is unsupported")
        rows = [{"electrode_id": int(row["physical_electrode_id"]),
                 "electrode_group": int(row["electrode_group"])}
                for row in upstream["rod_array"]["rods"]]
        common = {row["electrode_id"]: float(drive["common_mode_v"]) for row in rows}
        projected = {
            "waveform": drive["waveform"], "frequency_Hz": float(drive["frequency_hz"]),
            "phase_rad": float(drive["phase_rad"]),
            "rf_amplitude_V_zero_to_peak_per_group": float(drive["rf_amplitude_v"]),
            "dc_amplitude_V_per_group": group_dc[0],
        }
    elif upstream.get("role") == "multipole_resolved_design_do_not_edit":
        projected = dict(upstream["drive"])
        rods = upstream["segmentation"]["segmented_rod_array"]
        if not isinstance(rods, Mapping):
            raise ValueError("single-flight multipole requires an explicit segmented electrical topology")
        segmented_rod_electrode_ids(rods)
        # The existing downstream-terminal design publishes axial_dc as its
        # voltage authority. Standalone segmented providers publish each
        # group's common mode on their physical pieces, as consumed by the
        # native multipole runner. These are distinct current design contracts.
        axial = upstream.get("axial_dc")
        common = {}
        if axial is not None:
            for row in axial["rod_electrodes"]:
                eid = int(row["electrode_id"])
                if eid in common:
                    raise ValueError(f"duplicate axial-DC electrode {eid}")
                common[eid] = float(row["potential_V"])
        electrical: dict[int, dict[str, int]] = {}
        for row in rods["electrodes"]:
            eid, group = int(row["electrode_id"]), int(row["electrode_group"])
            if axial is None:
                if "common_mode_V" not in row:
                    raise ValueError(f"segmented electrode {eid} lacks common_mode_V")
                value = float(row["common_mode_V"])
                if eid in common and common[eid] != value:
                    raise ValueError(f"segmented electrode {eid} has conflicting common-mode voltage")
                common[eid] = value
            if eid in electrical and electrical[eid]["electrode_group"] != group:
                raise ValueError(f"segmented electrode {eid} has conflicting RF group")
            electrical[eid] = dict(electrode_id=eid, electrode_group=group)
        rows = [electrical[eid] for eid in sorted(electrical)]
    else:
        raise ValueError("unsupported single-flight upstream rod interface")
    ids = [int(row["electrode_id"]) for row in rows]
    if (sorted(ids) != list(ROD_ELECTRODE_IDS) or set(common) != set(ROD_ELECTRODE_IDS)
            or any(int(row["electrode_group"]) not in {1, 2} for row in rows)
            or any(not math.isfinite(value) for value in common.values())):
        raise ValueError("single-flight rod IDs, RF groups or DC potentials differ")
    return {"drive": projected, "electrodes": rows, "common_potentials_v": common}


def _rf_kernel_electrodes(rod_drive: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use one physical-rod-to-common-RF-kernel projection in both scopes."""
    rows = {int(row["electrode_id"]): row for row in rod_drive["electrodes"]}
    return [{"electrode_id": eid, "electrode_group": int(rows[eid]["electrode_group"]),
             "polarity": 1 if int(rows[eid]["electrode_group"]) == 1 else -1,
             "common_mode_v": rod_drive["common_potentials_v"][eid]}
            for eid in ROD_ELECTRODE_IDS]


def resolve_standalone_dynamic_operating_coefficients(
    pa_plus_model: Mapping[str, Any],
    upstream: Mapping[str, Any],
    *,
    accelerator_off_physical_voltages_v: Mapping[int, float],
    accelerator_on_physical_voltages_v: Mapping[int, float],
) -> dict[str, Any]:
    """Project frozen operating states onto the declared PA+ response modes.

    The off carrier includes the rods' common-mode and group-DC voltages.  The
    RF vector is normalized per volt returned by ``differential_at(time)``;
    the pulse vector is the exact on-minus-off difference.
    """

    pa_plus_model = require_pa_plus_solution_model(pa_plus_model)
    mode_ids = pa_plus_model["mode_ids"]
    differential_id = next(mode["mode_id"] for mode in pa_plus_model["modes"]
                           if mode["name"] == "rod_differential")
    try:
        rod_drive = _upstream_rod_drive(upstream)
        rod_rows = rod_drive["electrodes"]
        group_dc = float(rod_drive["drive"]["dc_amplitude_V_per_group"])
        groups = {
            int(item["electrode_id"]): int(item["electrode_group"])
            for item in rod_rows
        }
        common = rod_drive["common_potentials_v"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "standalone dynamic operating rod contract is incomplete"
        ) from error
    rod_ids = set(ROD_ELECTRODE_IDS)
    if (
        set(groups) != rod_ids
        or set(common) != rod_ids
        or any(group not in {1, 2} for group in groups.values())
        or not math.isfinite(group_dc)
        or any(not math.isfinite(value) for value in common.values())
    ):
        raise ValueError("standalone dynamic operating rod contract differs")

    try:
        required_physical_ids = {
            int(electrode_id)
            for mode in pa_plus_model["modes"]
            for electrode_id in mode["physical_electrode_coefficients"]
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "standalone dynamic operating PA+ model is incomplete"
        ) from error
    nonrod_ids = required_physical_ids - rod_ids
    ground_ids = set(pa_plus_model["grounded_physical_electrode_ids"])

    def finite_plan(
        raw: Mapping[int, float], label: str
    ) -> dict[int, float]:
        try:
            plan = {int(key): float(value) for key, value in raw.items()}
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} physical voltage plan is invalid") from error
        if set(plan) - ground_ids != nonrod_ids or any(
            not math.isfinite(value) for value in plan.values()
        ):
            raise ValueError(f"{label} physical voltage plan differs")
        if any(plan[eid] != 0. for eid in ground_ids & set(plan)):
            raise ValueError(f"{label} ground voltage must be zero under the PA+ model")
        # These zeros are fixed by the model, not additional author voltages.
        return {**dict.fromkeys(ground_ids, 0.), **plan}

    off_nonrod = finite_plan(
        accelerator_off_physical_voltages_v, "accelerator off"
    )
    on_nonrod = finite_plan(
        accelerator_on_physical_voltages_v, "accelerator on"
    )
    rod_static = {
        electrode_id: common[electrode_id]
        + (group_dc if groups[electrode_id] == 1 else -group_dc)
        for electrode_id in ROD_ELECTRODE_IDS
    }
    off_physical = {**rod_static, **off_nonrod}
    on_physical = {**rod_static, **on_nonrod}
    rf_physical = {
        electrode_id: (
            1.0 if groups[electrode_id] == 1 else -1.0
        )
        for electrode_id in ROD_ELECTRODE_IDS
    }
    rf_physical.update({electrode_id: 0.0 for electrode_id in nonrod_ids | ground_ids})

    off_modes = project_pa_plus_mode_voltages(pa_plus_model, off_physical)
    on_modes = project_pa_plus_mode_voltages(pa_plus_model, on_physical)
    rf_modes = project_pa_plus_mode_voltages(pa_plus_model, rf_physical)
    if any(
        not math.isclose(value, 0.0, abs_tol=1e-12)
        for mode_id, value in rf_modes.items()
        if mode_id != differential_id
    ) or not math.isclose(abs(rf_modes[differential_id]), 1.0, abs_tol=1e-12):
        raise ValueError("PA+ rod differential normalization differs")
    return {
        "schema_version": 1,
        "role": "rf_oatof_standalone_dynamic_operating_coefficients",
        "pa_plus_model_id": pa_plus_model["model_id"],
        "mode_ids": list(mode_ids),
        "carrier_off_mode_coefficients_v": {
            str(mode_id): off_modes[mode_id] for mode_id in mode_ids
        },
        "rf_differential_mode_coefficients_per_v": {
            str(mode_id): rf_modes[mode_id] for mode_id in mode_ids
        },
        "pulse_delta_mode_coefficients_v": {
            str(mode_id): on_modes[mode_id] - off_modes[mode_id]
            for mode_id in mode_ids
        },
    }


def load_initial_state(path: Path) -> tuple[list[float], list[int], list[list[float]]]:
    """Load canonical clocks, retained row IDs and velocities in mm/us.

    A restart can reindex its SIMION rows while preserving the mother-cohort
    identity in the separate row map.  The state-file ID is therefore only
    validated locally; the row map is the authority for source IDs.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("single-flight initial state is empty")
    id_column = (
        "particle_id" if "particle_id" in rows[0] else "simulation_particle_id"
    )
    actual_ids = [int(row[id_column]) for row in rows]
    if any(value <= 0 for value in actual_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ValueError("single-flight initial-state particle IDs must be unique and positive")
    values = [float(row["instrument_time_us"]) for row in rows]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("single-flight birth times must be non-negative")
    velocities = [
        [float(row[f"velocity_{axis}_m_s"]) / 1000.0 for axis in "xyz"]
        for row in rows
    ]
    if any(not math.isfinite(value) for velocity in velocities for value in velocity):
        raise ValueError("single-flight initial velocities must be finite")
    return values, actual_ids, velocities


_SUCCESSOR_CALLBACKS = (
    "load",
    "initialize_run",
    "efield_adjust",
    "instance_adjust",
    "initialize",
    "tstep_adjust",
    "other_actions",
    "terminate",
)


def _bind_standalone_dynamic_field_paths(
    specs: list[dict[str, Any]], paths: dict[str, dict[str, Any]],
) -> None:
    """Bind verified transport paths to each logical response, without file I/O."""
    if not isinstance(paths, dict) or set(paths) != {row["role"] for row in specs}:
        raise ValueError("standalone dynamic field paths must bind every actual role")

    def absolute_path(value: object, basename: str) -> str:
        if (not isinstance(value, str) or not Path(value).is_absolute()
                or Path(value).name != basename):
            raise ValueError("standalone response path must be absolute and match its bank basename")
        return Path(value).as_posix()

    for row in specs:
        selected = paths[row["role"]]
        expected = {"rf_differential_pa_paths"} | ({"pulse_delta_pa_path"} if row.get("pulse_delta_pa_basename") else set())
        if not isinstance(selected, dict) or set(selected) != expected:
            raise ValueError("standalone dynamic field transport fields differ")
        rf_paths = selected["rf_differential_pa_paths"]
        basenames = row.get("rf_differential_pa_basenames", [])
        if not isinstance(rf_paths, list) or len(rf_paths) != len(basenames):
            raise ValueError("standalone RF paths must match the ordered bank responses")
        row["rf_differential_pa_paths"] = [absolute_path(path, name)
            for path, name in zip(rf_paths, basenames, strict=True)]
        if row.get("pulse_delta_pa_basename"):
            row["pulse_delta_pa_path"] = absolute_path(selected["pulse_delta_pa_path"], row["pulse_delta_pa_basename"])


def _standalone_dynamic_field_lua(specs: list[dict[str, Any]]) -> str:
    """Share exact sidecar validation and RF/pulse field composition glue."""
    standalone_dynamic_specs_lua = _lua_value(specs)
    return f"""local function single_flight_exact_basename(value,label)
  assert(type(value)=='string',label..' filename must be a string')
  local basename=value:gsub('\\\\','/'):match('([^/]+)$')
  assert(basename and basename~='',label..' basename is missing')
  return basename
end
local single_flight_standalone_dynamic_specs={standalone_dynamic_specs_lua}
local single_flight_standalone_dynamic_by_instance={{}}
local function single_flight_is_standalone_dynamic_instance(index)
  return single_flight_standalone_dynamic_by_instance[index]~=nil
end
local function single_flight_assert_matching_response(carrier,response,label)
  local source=carrier.pa
  assert(response.nx==source.nx and response.ny==source.ny and response.nz==source.nz,
    label..' dimensions differ from carrier')
  assert(response.dx_mm==source.dx_mm and response.dy_mm==source.dy_mm and
    response.dz_mm==source.dz_mm,label..' grid spacing differs from carrier')
  assert(response.symmetry==source.symmetry,label..' symmetry differs from carrier')
  assert(response.potential_type==source.potential_type,
    label..' potential type differs from carrier')
end
local function single_flight_initialize_standalone_dynamic_fields()
  for _,spec in ipairs(single_flight_standalone_dynamic_specs) do
    assert(single_flight_standalone_dynamic_by_instance[spec.instance_index]==nil,
      'standalone dynamic field instance is duplicated')
    local carrier=assert(simion.wb.instances[spec.instance_index],
      'standalone dynamic field carrier instance is missing')
    assert(single_flight_exact_basename(carrier.filename,spec.role)==spec.carrier_pa_basename,
      'standalone dynamic field carrier filename differs for '..spec.role)
    -- SIMION pa.filename is a basename; pa.path is the loaded PA's full path.
    assert(single_flight_exact_basename(carrier.pa.path,spec.role)==spec.carrier_pa_basename,
      'standalone dynamic field carrier path differs for '..spec.role)
    spec.rf_differential_pas=spec.rf_differential_pas or {{}}
    for index,path in ipairs(spec.rf_differential_pa_paths) do
    local response=spec.rf_differential_pas[index] or assert(simion.pas:open(path),
      'cannot open RF differential standalone PA for '..spec.role)
    single_flight_assert_matching_response(carrier,response,
      spec.role..' RF differential response')
    spec.rf_differential_pas[index]=response
    end
    if spec.pulse_delta_pa_basename~=nil then
      spec.pulse_delta_pa=spec.pulse_delta_pa or assert(simion.pas:open(spec.pulse_delta_pa_path),
        'cannot open pulse-delta standalone PA for '..spec.role)
      single_flight_assert_matching_response(carrier,spec.pulse_delta_pa,
        spec.role..' pulse-delta response')
    end
    single_flight_standalone_dynamic_by_instance[spec.instance_index]=spec
  end
end
local function single_flight_apply_standalone_dynamic_field(instance,time)
  local spec=single_flight_standalone_dynamic_by_instance[ion_instance]
  if spec==nil then return end
  local x,y,z=instance:wb_to_pa_coords(ion_px_mm,ion_py_mm,ion_pz_mm)
  local ex,ey,ez
  for index,response in ipairs(spec.rf_differential_pas) do
  ex,ey,ez=response:field_vc(x,y,z)
  assert(ex~=nil and ey~=nil and ez~=nil,
    'RF differential standalone field is undefined for '..spec.role)
  local coefficient=single_flight_rf_drives[index].differential_at(time)/spec.rf_reference_voltage_v
  ion_dvoltsx_gu=ion_dvoltsx_gu-coefficient*ex
  ion_dvoltsy_gu=ion_dvoltsy_gu-coefficient*ey
  ion_dvoltsz_gu=ion_dvoltsz_gu-coefficient*ez
  end
  if spec.pulse_delta_pa~=nil and single_flight_pulse.is_active_at(time) then
    ex,ey,ez=spec.pulse_delta_pa:field_vc(x,y,z)
    assert(ex~=nil and ey~=nil and ez~=nil,
      'pulse-delta standalone field is undefined for '..spec.role)
    ion_dvoltsx_gu=ion_dvoltsx_gu-ex
    ion_dvoltsy_gu=ion_dvoltsy_gu-ey
    ion_dvoltsz_gu=ion_dvoltsz_gu-ez
  end
end
"""


def _canonical_bare_runtime_projection(
    frontend: Mapping[str, Any], *, acceleration_direction: int = 1,
) -> dict[str, Any]:
    """Validate actual bare-provider geometry for the zero-exit pulse API.

    The Analyzer component supports uniformly spaced rings, zero ON exit and
    uniform zero OFF voltage. More general PA+ models are not a flight claim.
    """
    local = frontend["accelerator_local_region"]
    electrodes = frontend["electrodes"]
    model = require_pa_plus_solution_model(local["pa_plus_solution_model"])
    if model != frontend["pa_plus_solution_model"]:
        raise ValueError("canonical frontend and local PA+ models differ")
    planes = local["planes"]
    three_zone = "accelerator_intermediate2_id" in electrodes
    plane_names = ["repeller", "grid1"] + (["intermediate2"] if three_zone else []) + ["exit"]
    if set(planes) != set(plane_names):
        raise ValueError("canonical accelerator actual planes differ from its topology")
    planes = {k: float(v) for k, v in planes.items()}
    if (acceleration_direction not in (-1, 1) or not all(math.isfinite(v) for v in planes.values())
            or any(acceleration_direction * planes[a] >= acceleration_direction * planes[b]
                   for a, b in zip(plane_names, plane_names[1:]))):
        raise ValueError("canonical accelerator planes are invalid")
    ring_z = [float(v) for v in local["ring_z_mm"]]
    ring_ids = electrodes["accelerator_ring_ids"]
    if len(ring_z) != len(ring_ids) or any(not math.isfinite(v) for v in ring_z):
        raise ValueError("canonical ring positions differ from physical IDs")
    # The older two-zone Analyzer protocol derives ring voltages from index.
    # Sectioned three-zone uses explicit positions and its PA+ interpolation;
    # its physical rings need not be uniform within either interval.
    if not three_zone:
        for i, actual in enumerate(ring_z, 1):
            expected = planes["grid1"] + (planes["exit"] - planes["grid1"]) * i / (len(ring_z) + 1)
            if not math.isclose(actual, expected, rel_tol=0., abs_tol=1e-9):
                raise ValueError("canonical accelerator requires uniform rings within each actual interval")
    if any(not acceleration_direction * planes["grid1"] < acceleration_direction * z < acceleration_direction * planes["exit"]
           or (three_zone and z == planes["intermediate2"]) for z in ring_z):
        raise ValueError("canonical ring lies outside a physical drift interval")
    on = {int(k): float(v) for k, v in local["operating_voltages_v"].items()}
    off = {int(k): float(v) for k, v in local["off_voltages_v"].items()}
    required = {electrodes[k] for k in ("grounded_shield_id", "accelerator_repeller_id", "accelerator_grid1_id", "accelerator_grid2_id")} | set(ring_ids)
    if three_zone:
        required.add(electrodes["accelerator_intermediate2_id"])
    if set(on) != required or set(off) != required or any(not math.isfinite(v) for v in [*on.values(), *off.values()]):
        raise ValueError("canonical accelerator requires complete finite ON/OFF voltages")
    if local["pulse_voltage_policy_id"] != "all_accelerator_electrodes_zero_before_pulse_v1" or any(v != 0. for v in off.values()):
        raise ValueError("existing two-zone Analyzer requires zero OFF voltages")
    if on[electrodes["accelerator_grid2_id"]] != 0.:
        raise ValueError("existing two-zone Analyzer requires zero ON exit voltage")
    project_pa_plus_mode_voltages(model, {**on, **{i: 0. for i in ROD_ELECTRODE_IDS}})
    translation = local["accelerator_component"]["transform"]["translation_mm"]
    bounds = {k: float(v) for k, v in local["actual_bounds_mm"].items()}
    if set(bounds) != {f"{a}_{side}" for a in "xyz" for side in ("min", "max")} or any(not math.isfinite(v) for v in bounds.values()):
        raise ValueError("canonical actual bounds are invalid")
    if len(translation) != 3 or any(not math.isfinite(float(v)) for v in translation):
        raise ValueError("canonical axis translation is invalid")
    return {"planes": planes, "bounds": bounds, "axis": [float(v) for v in translation], "on": on}


def _native_field_analyzer_config(multipoles: dict[str, dict], design: dict, geometry: dict, oatof: dict) -> tuple[dict, dict]:
    """Project the actual four-instance field design without legacy geometry."""
    from integrations.runtime.single_flight_frontend import frontend_electrode_maps, native_frontend_instances

    plan = geometry["composition_plan"]
    upstream_ids, downstream_id = native_frontend_instances(plan)
    local_oatof = not upstream_ids
    if set(multipoles) != set(upstream_ids):
        raise ValueError("native Program providers differ from its selected instances")
    if (design.get("schema_version") != 3
            or design.get("scope") != ("accelerator_domain_only" if local_oatof else "coupled_multipole_accelerator_domain_only")
            ):
        raise ValueError("native flight requires its actual selected-scope field design")
    has_pulse = any(point['kind'] == 'pulse_delta' for point in design['working_points'])
    kinds = ["carrier_off", *(["rf_reference"] * len(upstream_ids)), *(["pulse_delta"] if has_pulse else [])]
    if "pa_plus_solution_model" in geometry:
        raise ValueError("native physical fields cannot contain a PA+ mode model")
    domains = design["domains"]
    names = [domain["domain_id"] for domain in domains]
    if (names not in (["parent"], ["parent", "entrance_refinement"]) or set(geometry["numerical_domains"]) != set(names)
            or (local_oatof and names != ["parent"])):
        raise ValueError("native field requires parent and optional entrance_refinement domains")
    for domain in domains:
        numerical = geometry["numerical_domains"][domain["domain_id"]]
        if any(domain[key] != numerical[key] for key in ("dimensions", "cell_mm_xyz", "instance_origin_mm", "bounds_mm")):
            raise ValueError("native field design numerical domain differs from its geometry")
        fine = domain["domain_id"] == "entrance_refinement"
        if domain["boundary_policy"] != ("parent_dirichlet" if fine else "native_zero_neumann"):
            raise ValueError("native field domain boundary policy differs")
        if fine and (domain.get("parent_domain_id") != "parent" or domain["active_bounds_mm"] != numerical["active_bounds_mm"]):
            raise ValueError("native refinement requires its parent and actual active bounds")
        convergence = domain["refine_convergence_v"]
        if set(convergence) != set(kinds) or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
                for value in convergence.values()):
            raise ValueError("native working field requires explicit positive Refine convergence")
    parent = geometry["numerical_domains"]["parent"]
    electrical = resolve_accelerator_electrical_design(oatof, variant_id="three_zone_square")
    g, voltage = geometry["accelerator_projection"], electrical["operating_voltages_v"]
    multipole_ids, accelerator_ids = frontend_electrode_maps(geometry)
    electrodes = dict(accelerator_ids)
    if electrical["ring_z_mm"] != g["ring_z_mm"]:
        raise ValueError("native full flight physical electrical mapping differs")
    plane_keys = dict(repeller="repeller_front_z_mm",grid1="grid1_z_mm",intermediate2="intermediate2_z_mm",grid2="grid2_z_mm")
    if any(electrical["planes_z_mm"][role] != g[key] for role,key in plane_keys.items()):
        raise ValueError("native frontend planes differ from final provider geometry")
    states = design["accelerator_voltage_states"]
    expected_on = {electrodes[f"accelerator_{role}_id"]: voltage[role]
                   for role in ("repeller", "grid1", "intermediate2", "grid2")}
    expected_on.update(zip(electrodes["accelerator_ring_ids"], voltage["rings"], strict=True))
    expected_on[electrodes["grounded_shield_id"]] = 0.
    if (states.get("pulse_voltage_policy_id") != "all_accelerator_electrodes_zero_before_pulse_v1"
            or {int(k):v for k,v in states["operating_voltages_v"].items()} != expected_on
            or {int(k):v for k,v in states["off_voltages_v"].items()} != {key:0. for key in expected_on}):
        raise ValueError("native full flight voltages differ from provider ON and explicit OFF policy")
    points = design["working_points"]
    if not isinstance(points, list) or [p["kind"] for p in points] != kinds:
        raise ValueError("native design requires its ordered selected-scope working fields")
    carrier = {key: 0. for key in expected_on}
    groups = {}
    for instance_id in upstream_ids:
        values, groups[instance_id] = physical_multipole_voltages(multipoles[instance_id], multipole_ids[instance_id])
        carrier.update(values)
    rf_instances = sorted(upstream_ids, key=lambda instance: tuple(sorted(multipole_ids[instance].values())))
    if local_oatof and "rf_reference_voltage_v" in design:
        raise ValueError("local[oatof] has no RF reference")
    expected_points = [carrier]
    if not local_oatof:
        reference = design["rf_reference_voltage_v"]
        if (isinstance(reference, bool) or not isinstance(reference, (int, float)) or not math.isfinite(reference) or reference <= 0):
            raise ValueError("native RF reference voltage must be finite and positive")
        for instance in rf_instances:
            values = {key: 0. for key in carrier}
            values.update({electrode: reference if group == 1 else -reference
                           for electrode, group in groups[instance].items()})
            expected_points.append(values)
        electrodes["multipole_rod_ids"] = sorted(electrode for group in groups.values() for electrode in group)
    if has_pulse:
        expected_points.append({key: expected_on.get(key, 0.) for key in carrier})
    if any({int(k): value for k, value in point["electrode_voltages_v"].items()} != expected
           for point, expected in zip(points, expected_points, strict=True)):
        raise ValueError("native working fields differ from physical static, independent RF, or pulse voltages")
    frontend = dict(electrodes=electrodes, instance_origin_mm=parent["instance_origin_mm"],accelerator_local_region=g)
    if not local_oatof:
        edge = next(edge for edge in plan["recipe"]["connections"]
                    if edge["upstream"]["instance_id"] in upstream_ids
                    and edge["downstream"]["instance_id"] == downstream_id)
        poses = {row['instance_id']: RigidTransform.from_contract(row['transform'])
                 for row in plan['recipe']['instances']}
        upstream_id = edge['upstream']['instance_id']
        interface = plan['components'][upstream_id]
        pose = relative_transform(poses[upstream_id], poses[downstream_id])
        exit_point = pose.transform_position(FramedPosition(interface['local_frame_id'],
            interface['ports'][edge['upstream']['port_id']]['center_mm'])).coordinates_mm
        frontend["source_exit_center_mm"] = dict(zip("xyz",exit_point,strict=True))
    physical, coordinate, marker = oatof["geometry_mm"], oatof["coordinate_convention"], oatof["simion_detector_marker"]
    provider = derive_simion_geometry(geometry=physical,coordinate=coordinate,
        build=oatof["simion_geometry_build"],marker=marker,source=oatof["particle_source"])
    expected = {row["role"]:row for row in provider["simion_instances"] if row["role"] != "accelerator"}
    downstream = {row["role"]:row for row in geometry["downstream_pa_instances"]}
    if set(downstream) != set(expected) or any(
            any(downstream[role].get(key) != value for key,value in row.items()) for role,row in expected.items()):
        raise ValueError("native downstream PA descriptions differ from the final provider design")
    placements = {}
    for role,row in downstream.items():
        name = "flight_tube" if role == "flight_tube_shield" else role
        placements[name] = dict(x_mm=row["x_mm"],y_mm=row["y_mm"],z_mm=row["z_mm"],
                                az_deg=row["az_deg"],el_deg=0.,rt_deg=0.,scale=1.)
    placements["accelerator"] = dict(x_mm=parent["instance_origin_mm"]["x"],y_mm=parent["instance_origin_mm"]["y"],
        z_mm=parent["instance_origin_mm"]["z"],az_deg=0.,el_deg=0.,rt_deg=0.,scale=1.)
    analyzer_geometry = dict(accelerator_axis_x_mm=g["axis_x_mm"],accelerator_axis_y_mm=g["axis_y_mm"],
        accelerator_instance_z_mm=placements["accelerator"]["z_mm"],accelerator_repeller_front_z_mm=g["repeller_front_z_mm"],
        accelerator_grid1_z_mm=g["grid1_z_mm"],accelerator_intermediate2_z_mm=g["intermediate2_z_mm"],
        accelerator_grid2_z_mm=g["grid2_z_mm"],accelerator_ring_z_mm=g["ring_z_mm"],
        reflectron_axis_x_mm=coordinate["reflectron_axis"][0],reflectron_axis_y_mm=coordinate["reflectron_axis"][1],
        reflectron_entgrid_z_mm=physical["L_flight"],reflectron_midgrid_z_mm=physical["L_flight"]+physical["L_stage1"],
        reflectron_backplate_z_mm=physical["L_flight"]+physical["L_reflectron"],
        detector_x_mm=coordinate["detector_x"],detector_y_mm=0.,detector_z_mm=marker["active_plane_z_mm"],
        detector_radius_mm=marker["active_radius_mm"],detector_marker_front_margin_z_mm=marker["front_margin_z_mm"],
        detector_marker_back_margin_z_mm=marker["back_margin_z_mm"],
        detector_marker_absorber_thickness_mm=marker["absorber_thickness_mm"],diagnostic_return_plane_z_mm=_DIAGNOSTIC_RETURN_PLANE_Z_MM,
        flight_tube_near_outer_z_mm=physical["shield_outer_z_min"],flight_tube_far_outer_z_mm=physical["shield_outer_z_max"])
    config = dict(accelerator_topology_id="three_zone_frontend_contract_derived_v1",
        instance_roles=dict(flight_tube=1,reflectron=2,accelerator=3,detector=4),
        instance_filenames=dict(flight_tube="flight_tube_ground.pa0",reflectron="reflectron.pa0",
                                accelerator="accelerator.pa0",detector="detector_ground.pa0"),
        provider_placements=placements,geometry=analyzer_geometry,
        field_modes={key:False for key in ("ideal_accelerator","ideal_accelerator_axial","ideal_drift_axial",
            "ideal_reflectron_stage1","ideal_reflectron_stage1_axial","ideal_reflectron_stage2","ideal_reflectron_stage2_axial")},
        voltages=dict(repeller_v=voltage["repeller"],grid1_v=voltage["grid1"],intermediate2_v=voltage["intermediate2"],
            exit_v=voltage["grid2"],mid_v=oatof["electrodes_V"]["midgrid"],backplate_v=oatof["electrodes_V"]["backplate"]),
        accelerator_ring_count=len(g["ring_z_mm"]),
        electrode_ids=dict(repeller=electrodes["accelerator_repeller_id"],grid1=electrodes["accelerator_grid1_id"],
            intermediate2=electrodes["accelerator_intermediate2_id"],grid2=electrodes["accelerator_grid2_id"],
            rings=electrodes["accelerator_ring_ids"]),
        detector=dict(tstep_enabled=True,capture_arm_distance_mm=marker["capture_arm_distance_mm"],
            capture_depth_mm=marker["capture_depth_mm"],marker_absorber_thickness_mm=marker["absorber_thickness_mm"]),
        diagnostics=dict(_SUCCESSOR_DIAGNOSTICS))
    return frontend, config


def validate_native_flight(flight: Mapping[str, Any] | None, *, requires_rf: bool = True,
                           allow_discovery: bool = False) -> dict[str, Any]:
    """Validate author discovery explicitly; native execution accepts actual pulses only."""
    fields = {"pulse", "maximum_flight_us", "maximum_step_us", "trajectory_quality"}
    if requires_rf: fields.add("rf_steps_per_period")
    if isinstance(flight, Mapping) and "observation_times_us" in flight:
        if allow_discovery:
            raise ValueError("author flight cannot contain derived observation times")
        fields.add("observation_times_us")
    if not isinstance(flight, Mapping) or set(flight) != fields:
        raise ValueError("native flight requires pulse and four explicit flight inputs")
    pulse = flight["pulse"]
    if not isinstance(pulse, Mapping) or pulse.get("mode") not in (("timed", "held_off", "discover") if allow_discovery else ("timed", "held_off")):
        raise ValueError("native flight pulse requires timed or held_off mode")
    expected = ({"mode", "time_us", "width_us"} if pulse["mode"] == "timed" else
                {"mode", "width_us", "candidate_times_us"} if pulse["mode"] == "discover" else {"mode"})
    if set(pulse) != expected:
        raise ValueError("native flight pulse fields must match its mode")
    for key in ("maximum_flight_us", "maximum_step_us"):
        value = flight[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"native flight {key} must be finite and positive")
    if pulse["mode"] == "timed":
        for key in ("time_us", "width_us"):
            value = pulse[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or (key == "width_us" and value <= 0)):
                raise ValueError(f"native pulse {key} must be finite" + (" and positive" if key == "width_us" else ""))
        end = pulse["time_us"] + pulse["width_us"]
        if not math.isfinite(end) or end <= pulse["time_us"]:
            raise ValueError("native pulse end must be finite and later than its start")
    if pulse["mode"] == "discover":
        width = pulse["width_us"]
        if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0:
            raise ValueError("discovery pulse width_us must be finite and positive")
    for key, times in ([('candidate_times_us', pulse['candidate_times_us'])] if pulse['mode'] == 'discover' else []) + (
            [('observation_times_us', flight['observation_times_us'])] if 'observation_times_us' in flight else []):
        if (not isinstance(times, list) or not times
                or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in times)
                or any(a >= b for a, b in zip(times, times[1:]))):
            raise ValueError(f"native flight {key} must be nonempty, finite and strictly increasing")
        if key == 'candidate_times_us' and any(not math.isfinite(t + width) or t + width <= t for t in times):
            raise ValueError("discovery pulse end must be finite and later than each candidate")
    if pulse['mode'] == 'discover' and 'observation_times_us' in flight:
        raise ValueError("author discovery cannot contain derived observation times")
    for key, upper in [("trajectory_quality",500)]+([("rf_steps_per_period",None)] if requires_rf else []):
        value = flight[key]
        if type(value) is not int or value < 1 or (upper is not None and value > upper):
            raise ValueError(f"native flight {key} must be a positive integer" + (" within 1..500" if upper else ""))
    return dict(flight)


def build_successor_program(
    multipoles_by_instance: dict[str, dict],
    frontend: dict[str, Any],
    oatof: dict[str, Any],
    *,
    frontend_geometry: dict[str, Any],
    flight: Mapping[str, Any],
    birth_times_us: list[float],
    particle_ids: list[int] | None = None,
    initial_velocities_mm_per_us: list[list[float]],
    analyzer_component_source: str,
    pulse_hook_source: str,
    frontend_hook_source: str,
    rf_drive_kernel_source: str,
    voltage_waveforms_source: str,
    standalone_dynamic_field_bank: dict[str, Any],
    standalone_dynamic_field_paths: dict[str, dict[str, Any]],
    downstream_static_fields: dict[str, Any],
    build_metadata: dict[str, Any] | None = None,
) -> str:
    """Assemble native full-flight callbacks from frozen source and field contracts."""
    from integrations.runtime.single_flight_frontend import frontend_electrode_maps

    if frontend.get("role") != "frontend_native_field_design":
        raise ValueError("single-flight Program requires a native frontend field design")
    native_design = frontend
    native_local_oatof = not any(point['kind'] == 'rf_reference' for point in native_design['working_points'])
    flight = validate_native_flight(flight, requires_rf=not native_local_oatof)
    pulse_response_required = any(point['kind'] == 'pulse_delta' for point in native_design['working_points'])
    if flight['pulse']['mode'] != 'held_off' and not pulse_response_required:
        raise ValueError('armed native flight requires the prepared OA pulse response')
    rf_steps_per_period = flight.get("rf_steps_per_period")
    if frontend_geometry is None:
        raise ValueError("native field design requires its explicit frontend_geometry")
    if standalone_dynamic_field_bank is None or downstream_static_fields is None:
        raise ValueError("native full flight requires explicit frontend and downstream standalone field assets")
    frontend, native_analyzer_config = _native_field_analyzer_config(multipoles_by_instance, native_design, frontend_geometry, oatof)
    if not birth_times_us or any(isinstance(item, bool) or not isinstance(item, (int, float))
            or not math.isfinite(item) for item in birth_times_us):
        raise ValueError("canonical instrument clock requires finite absolute birth times")
    if any(
            not math.isfinite(birth + flight["maximum_flight_us"]) for birth in birth_times_us):
        raise ValueError("native flight age horizon is non-finite")
    if particle_ids is None:
        particle_ids = list(range(1, len(birth_times_us) + 1))
    if (
        len(particle_ids) != len(birth_times_us)
        or any(item <= 0 for item in particle_ids)
        or len(set(particle_ids)) != len(particle_ids)
    ):
        raise ValueError("single-flight canonical particle IDs are invalid")
    if (
        not isinstance(initial_velocities_mm_per_us, list)
        or len(initial_velocities_mm_per_us) != len(birth_times_us)
        or any(not isinstance(vector, list) or len(vector) != 3
               or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector)
               for vector in initial_velocities_mm_per_us)
    ):
        raise ValueError("single-flight source requires one finite initial velocity vector per row")
    rf_enabled = not native_local_oatof
    if rf_enabled and (isinstance(rf_steps_per_period, bool) or not isinstance(rf_steps_per_period, int) or rf_steps_per_period <= 0):
        raise ValueError("RF steps per period must be one positive integer")
    sample_times_us = []
    grid_origin_us = 0.0
    grid_step_us = 1.0
    sources = {
        "analyzer component": analyzer_component_source,
        "pulse hook": pulse_hook_source,
        "frontend hook": frontend_hook_source,
        "RF drive kernel": rf_drive_kernel_source,
        "voltage waveforms": voltage_waveforms_source,
    }
    normalized = {
        name: validate_pure_lua_component_source(
            source.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n"), name
        )
        for name, source in sources.items()
    }
    region_hook = validate_pure_lua_component_source(
        ("return {apply=function(base) return base end}"),
        "resolved region field hook",
    )
    bindings, _ = frontend_electrode_maps(frontend_geometry)
    rf_instances = sorted(multipoles_by_instance, key=lambda instance: tuple(sorted(bindings[instance].values())))
    rf_configs = []
    for instance in rf_instances:
        drive = multipoles_by_instance[instance]["drive"]
        if drive["waveform"] not in {"sine", "cosine"}:
            raise ValueError("single-flight Program RF waveform must be sine or cosine")
        rf_configs.append(dict(waveform=drive["waveform"], frequency_hz=drive["frequency_Hz"],
            phase_rad=drive["phase_rad"], rf_amplitude_v=drive["rf_amplitude_V_zero_to_peak_per_group"],
            rf_scale=1., rf_steps_per_period=rf_steps_per_period))
    analyzer_config = native_analyzer_config
    analyzer_config["diagnostics"]["post_pulse_observation_window_us"] = False
    analyzer_config["domain_split"] = False
    overlay_specs: list[dict[str, Any]] = []
    if "entrance_refinement" in frontend_geometry["numerical_domains"]:
        fine = frontend_geometry["numerical_domains"]["entrance_refinement"]
        overlay_specs.append(dict(role="entrance_refinement", instance_index=5,
            filename="frontend_entrance_refinement.carrier_off.pa",
            origin_mm=fine["instance_origin_mm"], bounds_mm=fine["active_bounds_mm"],
            dimensions=fine["dimensions"], cell_mm_xyz=fine["cell_mm_xyz"]))
    overlay_roles = {
        str(item["role"]): int(item["instance_index"])
        for item in overlay_specs
    }
    domain_active_roles = ["accelerator", *overlay_roles]
    expected_role_indices = {"accelerator_main":3, **overlay_roles}
    standalone_dynamic_specs = _resolve_standalone_dynamic_field_bank(
        standalone_dynamic_field_bank, expected_role_indices, requires_rf=not native_local_oatof,
    )
    for row in standalone_dynamic_field_bank["dynamic_roles"]:
        if bool(row.get("pulse_delta_pa_basename")) != pulse_response_required:
            raise ValueError("native bank pulse response differs from its prepared working fields")
        if native_local_oatof:
            if "rf_differential_pa_basenames" in row or "rf_reference_voltage_v" in row:
                raise ValueError("local[oatof] bank cannot contain an RF response")
        elif (len(row.get("rf_differential_pa_basenames", [])) != len(rf_instances) or "rf_reference_voltage_v" not in row
              or row["rf_reference_voltage_v"] != native_design["rf_reference_voltage_v"]):
            raise ValueError("native bank must explicitly match the prepared RF reference voltage")
    _bind_standalone_dynamic_field_paths(standalone_dynamic_specs, standalone_dynamic_field_paths)
    standalone_carriers = {
        str(item["role"]): str(item["carrier_pa_basename"])
        for item in standalone_dynamic_specs
    }
    expected_downstream_indices = {
        role: int(analyzer_config["instance_roles"][role])
        for role in _DOWNSTREAM_STATIC_ROLES
    }
    downstream_static_specs = _resolve_downstream_static_assets(downstream_static_fields, expected_downstream_indices)
    if {row["role"] for row in downstream_static_specs} != _DOWNSTREAM_STATIC_ROLES:
        raise ValueError("native full flight requires all three receipt-bound downstream static assets")
    downstream_static_carriers = {
        str(item["role"]): str(item["carrier_pa_basename"])
        for item in downstream_static_specs
    }
    for role, filename in downstream_static_carriers.items():
        analyzer_config["instance_filenames"][role] = filename
    overlay_filenames = {
        str(item["role"]): str(item["filename"])
        for item in overlay_specs
    }
    domain_accelerator_filename = standalone_carriers["accelerator_main"]
    # The analyzer component validates the physical Workbench payload before
    # the Program's separate role map is consulted.  Keep both views derived
    # from the same resolved domain contract.
    analyzer_config["instance_filenames"]["accelerator"] = (
        domain_accelerator_filename
    )
    formal_iob_config = {
        "instance_roles": {"flight_tube": 1, "reflectron": 2, "accelerator": 3, "detector": 4, **overlay_roles},
        "instance_filenames": {
            "flight_tube": downstream_static_carriers["flight_tube"],
            "reflectron": downstream_static_carriers["reflectron"],
            "accelerator": domain_accelerator_filename,
            "detector": downstream_static_carriers["detector"],
            **overlay_filenames,
        },
        "pre_pulse_active_roles": domain_active_roles,
        "accelerator_overlays": [
            {"role": str(item["role"]), "instance_index": int(item["instance_index"]), "filename": str(item["filename"])}
            for item in overlay_specs
        ],
    }
    formal_iob_config_lua = _lua_value(formal_iob_config)
    if build_metadata is not None:
        build_metadata["instance_roles"] = dict(formal_iob_config["instance_roles"])
        build_metadata["physical_frontend_topology_id"] = native_analyzer_config["accelerator_topology_id"]
        build_metadata["provider_placements"] = analyzer_config["provider_placements"]
        build_metadata["physical_rod_piece_count"] = sum(len(provider["segmentation"]["segmented_rod_array"]["electrodes"])
                                                         for provider in multipoles_by_instance.values())
        build_metadata["rf_instance_order"] = rf_instances
        build_metadata["runtime_representation"] = STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION
        build_metadata["standalone_dynamic_field_roles"] = [
            str(item["role"]) for item in standalone_dynamic_specs
        ]
        build_metadata["downstream_static_roles"] = [
            str(item["role"]) for item in downstream_static_specs
        ]
        build_metadata["downstream_static_runtime_representation"] = downstream_static_fields["runtime_representation"]
        build_metadata["downstream_static_asset_receipt"] = dict(downstream_static_fields["receipt"])
        build_metadata["downstream_static_assets"] = downstream_static_specs
    analyzer_config_static = dict(analyzer_config)
    analyzer_config_static.pop("diagnostics")
    analyzer_config_lua = _lua_value(analyzer_config_static)[:-1] + (
        ",diagnostics={post_pulse_observation_window_us="
        + "false," +
        "log_stride=trajectory_log_stride}}"
    )
    geometry = analyzer_config["geometry"]
    three_zone = "accelerator_intermediate2_id" in frontend["electrodes"]
    pulse_voltage_lua = (
        "{pre_all_v=handoff_pulse_pre_all_v,repeller_v=V_repeller,"
        "grid1_v=V_grid1,intermediate2_v=V_intermediate2,exit_v=V_exit}"
        if three_zone
        else "{pre_all_v=handoff_pulse_pre_all_v,repeller_v=V_repeller,grid1_v=V_grid1}"
    )
    three_zone_adjustables = (
        f"adjustable V_intermediate2={_lua_number(analyzer_config['voltages']['intermediate2_v'])}\n"
        f"adjustable V_exit={_lua_number(analyzer_config['voltages']['exit_v'])}\n"
        if three_zone
        else ""
    )
    intermediate2_local = (
        "local accelerator_intermediate2_z_mm="
        f"{_lua_number(geometry['accelerator_intermediate2_z_mm'])}\n"
        if three_zone
        else ""
    )
    accelerator_planes_lua = (
        "{accelerator_grid1_z_mm,accelerator_intermediate2_z_mm,"
        "accelerator_grid2_z_mm}"
        if three_zone
        else "{accelerator_grid1_z_mm,accelerator_grid2_z_mm}"
    )
    state_precision = ("%.17g")
    intermediate2_crossing_lua = (
        "  _,tc,xc,yc,vxc,vyc,vzc=crossing(accelerator_intermediate2_z_mm,1)\n"
        "  if tc and not reported.intermediate2 then reported.intermediate2=true\n"
        f"    if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_intermediate2_forward ion=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision}',ion_number,tc,xc,yc,accelerator_intermediate2_z_mm,vxc,vyc,vzc)) end\n"
        "  end\n"
        if three_zone
        else ""
    )
    electrodes = frontend["electrodes"]
    accelerator_instance_index = 3
    active_field_instance_indices = (
        ([3, *[int(item["instance_index"]) for item in overlay_specs]])
    )
    pre_pulse_scope_instance_indices = (
        (active_field_instance_indices)
    )
    native_overlay_check_lua = ("""      assert(oi.x==overlay.origin_mm.x and oi.y==overlay.origin_mm.y and oi.z==overlay.origin_mm.z and
        oi.az==0 and oi.el==0 and oi.rt==0 and oi.scale==1,'native refinement placement differs')
      for _,axis in ipairs({'x','y','z'}) do
        assert(oi.pa['n'..axis]==overlay.dimensions['n'..axis] and
          oi.pa['d'..axis..'_mm']==overlay.cell_mm_xyz[axis],'native refinement grid differs')
      end
""")
    overlay_specs_lua = _lua_value(overlay_specs)
    standalone_dynamic_field_lua = _standalone_dynamic_field_lua(standalone_dynamic_specs)
    active_field_instance_indices_lua = _lua_value(active_field_instance_indices)
    pre_pulse_scope_instance_indices_lua = _lua_value(pre_pulse_scope_instance_indices)
    time_origin_table = "{" + ",".join(
        f"[{index}]={_lua_number(value)}"
        for index, value in enumerate(birth_times_us, start=1)
    ) + "}"
    particle_id_table = "{" + ",".join(
        f"[{index}]={value}" for index, value in enumerate(particle_ids, start=1)
    ) + "}"
    source_velocity_table = _lua_value(initial_velocities_mm_per_us)
    screening_sample_table = "{" + ",".join(
        f"[{index}]={_lua_number(value)}"
        for index, value in enumerate(sample_times_us, start=1)
    ) + "}"
    embedded_components = [
        ("single_flight_analyzer_component", normalized["analyzer component"]),
        ("single_flight_pulse_component", normalized["pulse hook"]),
        ("single_flight_voltage_waveforms", normalized["voltage waveforms"]),
        ("single_flight_frontend_component", normalized["frontend hook"]),
    ]
    if rf_enabled:
        embedded_components.append(
            ("single_flight_rf_kernel", normalized["RF drive kernel"])
        )
    embedded_components.append(("single_flight_region_field", region_hook))
    embedded = "\n".join(
        f"local {name}=(function()\n{source}\nend)()"
        for name, source in embedded_components
    )
    rf_grid_lua = "" if native_local_oatof else f"local single_flight_continuous_rf_grid_step_us={_lua_number(min(1.0e6 / config['frequency_hz'] / rf_steps_per_period for config in rf_configs))}"
    screening_rf_assert = (
        ("")
    )
    rf_initializer = (f"    single_flight_rf_drives={{}}\n    for index,config in ipairs({_lua_value(rf_configs)}) do\n"
                      "      single_flight_rf_drives[index]=single_flight_rf_kernel.new_differential(config)\n    end\n") if rf_enabled else ""
    global_setup = (
        ("\nsimion.early_access(8.2)\nsim_segment_global=1")
    )
    clock_lua = canonical_clock_lua()
    exit_stop_action_lua = (
        ("")
    )
    exit_stop_terminal_lua = (
        ("")
    )
    placement_initialization_lua = """  for role,placement in pairs(analyzer_config.provider_placements) do
    local instance=assert(simion.wb.instances[analyzer_config.instance_roles[role]])
    assert(instance.x==placement.x_mm and instance.y==placement.y_mm and instance.z==placement.z_mm
      and instance.az==placement.az_deg and instance.el==placement.el_deg and instance.rt==placement.rt_deg
      and instance.scale==placement.scale,'native provider placement differs for '..role)
  end
"""
    native_observation_lua = ""
    native_observation_initialize_lua = ""
    native_observation_step_lua = ""
    native_observation_actual_lua = ""
    if flight.get("observation_times_us"):
        native_observation_lua = f"""local single_flight_observation_times={_lua_value(flight['observation_times_us'])}
local single_flight_observation_indices={{}}
local function single_flight_observe_actual(time)
  local index=single_flight_observation_indices[ion_number]
  while single_flight_observation_times[index] do
    local target=single_flight_observation_times[index]
    local _,exponent=math.frexp(math.max(1,math.abs(time),math.abs(target)))
    if math.abs(time-target)<=32*2^(exponent-53) then
      local energy=0.0051821348263402529*ion_mass*(ion_vx_mm^2+ion_vy_mm^2+ion_vz_mm^2)
      single_flight_write_trace(string.format('TRACE: native_shared_time ion=%d particle_id=%d candidate_time_us=%.17g instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g kinetic_energy_eV=%.17g instance=%d',
        ion_number,single_flight_canonical_particle_id(),target,time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,energy,ion_instance))
    elseif time>target then
      print(string.format('DIAG: native_shared_time_missing particle_id=%d candidate_time_us=%.17g actual_instrument_time_us=%.17g',
        single_flight_canonical_particle_id(),target,time))
    else break end
    index=index+1
  end
  single_flight_observation_indices[ion_number]=index
end
"""
        native_observation_initialize_lua = """  local observation_index=1
  while single_flight_observation_times[observation_index] and single_flight_observation_times[observation_index]<time do
    observation_index=observation_index+1
  end
  single_flight_observation_indices[ion_number]=observation_index
  single_flight_observe_actual(time)
"""
        native_observation_step_lua = """  local observation_time=single_flight_observation_times[single_flight_observation_indices[ion_number]]
  if observation_time then
    local observation_remaining=observation_time-single_flight_instrument_time_us()
    if observation_remaining>0 then ion_time_step=math.min(ion_time_step,observation_remaining) end
  end
"""
        native_observation_actual_lua = "  single_flight_observe_actual(time)\n"
    native_step_limits_lua = f"""  ion_time_step=math.min(ion_time_step,{_lua_number(flight['maximum_step_us'])})
  local remaining_age={_lua_number(flight['maximum_flight_us'])}-ion_time_of_flight
  if remaining_age>0 and ion_time_step>remaining_age then ion_time_step=remaining_age end
"""
    native_age_limit_lua = f"""  -- Observe the complete accepted step before deciding the age limit.
  local state=single_flight_require_particle_state()
  if state.flight_timeout then return end
  state.maximum_z_mm=math.max(state.maximum_z_mm or (p and p.z or ion_pz_mm),ion_pz_mm)
  if ion_splat~=0 then return end
  if ion_time_of_flight>={_lua_number(flight['maximum_flight_us'])} then
    state.flight_timeout=true
    single_flight_write_trace(string.format('TRACE: handoff_terminal_raw ion=%d instance=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g',
      ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))
    single_flight_write_trace(string.format('TRACE: timeout_splat ion=%d instance=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g zmax_mm=%.17g particle_id=%d particle_age_us=%.17g',
      ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,state.maximum_z_mm,single_flight_canonical_particle_id(),ion_time_of_flight))
    ion_splat=1
    return
  end
"""
    native_timeout_terminate_lua = """  local state=single_flight_particle_state[ion_number]
  if state and state.flight_timeout then return end
"""
    diagnostic_adjustable_lua = ("")
    observation_step_lua = ("")
    # A pulse observation needs a real state at/before the edge. The equal
    # endpoint retains the actual birth state when birth coincides with it.
    pulse_observation_guard_lua = ("p and p.t<=handoff_pulse_time_us and ")
    pulse_interpolation_comparison = ("<=")
    held_off = flight["pulse"]["mode"] == "held_off"
    pulse_controls_lua = ("local handoff_pulse_mode=2\n" if held_off else
        f"adjustable handoff_pulse_mode={(1)}\n"
        f"adjustable handoff_pulse_time_us={(_lua_number(flight['pulse']['time_us']))}\n"
        f"adjustable handoff_pulse_width_us={(_lua_number(flight['pulse']['width_us']))}\n")
    pulse_config_lua = "" if held_off else "pulse_time_us=handoff_pulse_time_us,pulse_width_us=handoff_pulse_width_us,"
    pre_on_lua = "true" if held_off else "time<handoff_pulse_time_us"
    pulse_elapsed_lua = "false" if held_off else "time-handoff_pulse_time_us"
    terminal_log_lua = ("true")
    terminate_after_lua = "" if held_off else " or (single_flight_terminate_after_pulse~=0 and time>=handoff_pulse_time_us)"
    checkpoint_relative_format = "" if held_off else f" tof_since_pulse_us={state_precision}"
    checkpoint_relative_arg = "" if held_off else ",t-handoff_pulse_time_us"
    pulse_observations_lua = "" if held_off else f"""  if p and not reported.pre_pulse and p.t<handoff_pulse_time_us and time>=handoff_pulse_time_us then
    local f=(handoff_pulse_time_us-p.t)/(time-p.t)
    reported.pre_pulse=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: pre_pulse_state ion=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision}',
      ion_number,handoff_pulse_time_us,p.x+f*(ion_px_mm-p.x),p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),ion_vx_mm,ion_vy_mm,ion_vz_mm)) end
  end
  if handoff_pulse_mode==1 and not reported.pulse and {pulse_observation_guard_lua}time>=handoff_pulse_time_us then
    local pulse_x,pulse_y,pulse_z=ion_px_mm,ion_py_mm,ion_pz_mm
    local pulse_vx,pulse_vy,pulse_vz=ion_vx_mm,ion_vy_mm,ion_vz_mm
    if p and p.t{pulse_interpolation_comparison}handoff_pulse_time_us and time>p.t then
      local f=(handoff_pulse_time_us-p.t)/(time-p.t)
      pulse_x=p.x+f*(ion_px_mm-p.x); pulse_y=p.y+f*(ion_py_mm-p.y); pulse_z=p.z+f*(ion_pz_mm-p.z)
      pulse_vx=p.vx+f*(ion_vx_mm-p.vx); pulse_vy=p.vy+f*(ion_vy_mm-p.vy); pulse_vz=p.vz+f*(ion_vz_mm-p.vz)
    end
    reported.pulse=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: handoff_pulse_on ion=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision}',
      ion_number,handoff_pulse_time_us,pulse_x,pulse_y,pulse_z,pulse_vx,pulse_vy,pulse_vz)) end
  end
"""
    actual = frontend["accelerator_local_region"]
    incident_planes = ([] if native_local_oatof else [
        {"event":"single_flight_handoff", "x_mm":frontend["source_exit_center_mm"]["x"]}]) + [
        {"event":"accelerator_sidewall_inner_forward", "x_mm":actual["accelerator_port_aperture_discretization"]["flange_max_mm"]},
        {"event":"accelerator_axis_forward", "x_mm":actual["axis_x_mm"]},
    ]
    incident_x_observations_lua = f"""  -- Passive native accepted-step brackets; states are interpolation estimates,
  -- not exact solver landings or aperture/transmission acceptance claims.
  if p and time>p.t then
    for _,plane in ipairs({_lua_value(incident_planes)}) do
      if not reported[plane.event] and p.x<plane.x_mm and ion_px_mm>=plane.x_mm and ion_vx_mm>0 then
        local f=(plane.x_mm-p.x)/(ion_px_mm-p.x)
        reported[plane.event]=true
        local bracket=string.format(' step_start_instrument_time_us=%.17g step_end_instrument_time_us=%.17g step_start_x_mm=%.17g step_end_x_mm=%.17g',
          p.t,time,p.x,ion_px_mm)
        single_flight_trace_checkpoint(plane.event,p.t+f*(time-p.t),plane.x_mm,
          p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),
          p.vx+f*(ion_vx_mm-p.vx),p.vy+f*(ion_vy_mm-p.vy),p.vz+f*(ion_vz_mm-p.vz),bracket)
      end
    end
  end
"""
    # Full-flight controls consume only the frozen source and field contracts.
    particle_offset_lua = ("0")
    accelerator_override_lua = ("nil")
    trace_path_lua = ("nil")
    load_report_lua = ("nil")
    program = f"""simion.workbench_program(){global_setup}
{embedded}
adjustable V_repeller={_lua_number(analyzer_config['voltages']['repeller_v'])}
adjustable V_grid1={_lua_number(analyzer_config['voltages']['grid1_v'])}
{three_zone_adjustables}adjustable V_mid={_lua_number(oatof['electrodes_V']['midgrid'])}
adjustable V_backplate={_lua_number(oatof['electrodes_V']['backplate'])}
adjustable trajectory_quality={(flight['trajectory_quality'])}
adjustable trajectory_log_enable={(1)}
adjustable trajectory_log_stride=1000
{diagnostic_adjustable_lua}{pulse_controls_lua}adjustable handoff_pulse_pre_all_v=0
adjustable single_flight_enable=1
local accelerator_repeller_front_z_mm={_lua_number(geometry['accelerator_repeller_front_z_mm'])}
local accelerator_grid1_z_mm={_lua_number(geometry['accelerator_grid1_z_mm'])}
{intermediate2_local}local accelerator_grid2_z_mm={_lua_number(geometry['accelerator_grid2_z_mm'])}
local reflectron_entgrid_z_mm={_lua_number(geometry['reflectron_entgrid_z_mm'])}
local reflectron_midgrid_z_mm={_lua_number(geometry['reflectron_midgrid_z_mm'])}
local reflectron_backplate_z_mm={_lua_number(geometry['reflectron_backplate_z_mm'])}
local single_flight_time_origin_us={time_origin_table}
local single_flight_source_velocity_mm_per_us={source_velocity_table}
local single_flight_source_particle_id={particle_id_table}
local single_flight_particle_id_offset={particle_offset_lua}
local single_flight_terminate_after_pulse={(0)}
local single_flight_pre_pulse_time_series={(0)}
local single_flight_pre_pulse_natural_archive={(0)}
local single_flight_pre_pulse_sample_times_us={screening_sample_table}
local single_flight_pre_pulse_next_sample={{}}
local single_flight_pre_pulse_grid_origin_us={_lua_number(grid_origin_us)}
local single_flight_pre_pulse_grid_step_us={_lua_number(grid_step_us)}
local single_flight_continuous_rf_next_sample={{}}
{rf_grid_lua}
  local single_flight_overlay_enabled={1 if overlay_specs else 0}
  local single_flight_overlays={overlay_specs_lua}
local single_flight_active_field_instances={active_field_instance_indices_lua}
local single_flight_pre_pulse_scope_instances={pre_pulse_scope_instance_indices_lua}
local single_flight_domain_split_enabled={(0)}
local single_flight_pre_pulse_collision_only={(0)}
local single_flight_pre_pulse_accelerator_zero_field={(0)}
local single_flight_accelerator_instance_index={accelerator_instance_index}
local single_flight_flight_tube_instance_index={int(analyzer_config['instance_roles']['flight_tube'])}
local single_flight_reflectron_instance_index={int(analyzer_config['instance_roles']['reflectron'])}
local single_flight_detector_instance_index={int(analyzer_config['instance_roles']['detector'])}
local single_flight_post_pulse_handoff_minimal={(0)}
local single_flight_analyzer=nil
local single_flight_pulse=nil
local single_flight_frontend=nil
local single_flight_rf=false
local single_flight_rf_drives={{}}
local single_flight_particle_state={{}}
local single_flight_analyzer_initialized={{}}
local single_flight_previous={{}}
local single_flight_reported={{}}
local single_flight_accelerator_pa_override={accelerator_override_lua}
local single_flight_accelerator_pa_override_loaded=false
{clock_lua}{standalone_dynamic_field_lua}
local single_flight_trace_path={trace_path_lua}
local single_flight_trace_stream=nil
if single_flight_trace_path~=nil and single_flight_trace_path~='' then
  single_flight_trace_stream=assert(io.open(single_flight_trace_path,'w'))
end
local function single_flight_write_trace(record)
  if single_flight_trace_stream~=nil then
    single_flight_trace_stream:write(record,'\\n')
  else
    print(record)
  end
end
local function single_flight_trace_checkpoint(event,t,x,y,z,vx,vy,vz,bracket_suffix)
  if trajectory_log_enable==0 then return end
  local particle_id=single_flight_canonical_particle_id()
  local energy=0.0051821348263402529*ion_mass*(vx*vx+vy*vy+vz*vz)
  single_flight_write_trace(string.format('TRACE: %s ion=%d particle_id=%d instrument_time_us={state_precision}{checkpoint_relative_format} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision} kinetic_energy_eV={state_precision} survival_status=alive%s',
    event,ion_number,particle_id,t{checkpoint_relative_arg},x,y,z,vx,vy,vz,energy,bracket_suffix or ''))
end
{native_observation_lua}local function single_flight_require_analyzer_particle(elapsed)
  if not single_flight_analyzer_initialized[ion_number] then
    single_flight_analyzer.initialize_particle{{particle_id=single_flight_canonical_particle_id(),elapsed_us=elapsed,
      x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm}}
    single_flight_analyzer_initialized[ion_number]=true
  end
end
local function single_flight_require_particle_state()
  local state=single_flight_particle_state[ion_number]
  if state==nil then
    local time=single_flight_instrument_time_us()
    state={{frontend=single_flight_frontend.initialize_particle(ion_pz_mm),
      previous={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}}}
    single_flight_particle_state[ion_number]=state
  end
  return state
end
local function single_flight_assert_formal_iob_roles(config)
  if single_flight_pre_pulse_time_series~=0 then
    for _,role in ipairs(config.pre_pulse_active_roles) do
      local index=config.instance_roles[role]
      local item=assert(simion.wb.instances[index],
        'pre-pulse screening '..role..' instance is missing')
      assert(single_flight_exact_basename(item.filename,
        'formal IOB role '..role)==config.instance_filenames[role],
        'formal IOB role '..role..' filename differs')
    end
    return
  end
  local role_count=0
  for _ in pairs(config.instance_roles) do role_count=role_count+1 end
  assert(#simion.wb.instances==role_count,
    'formal single-flight IOB instance count differs')
  for role,index in pairs(config.instance_roles) do
    assert(single_flight_exact_basename(simion.wb.instances[index].filename,
      'formal IOB role '..role)==config.instance_filenames[role],
      'formal IOB role '..role..' filename differs')
  end
end
local function single_flight_overlay_for_instance(instance_index)
  for _,overlay in ipairs(single_flight_overlays) do
    if overlay.instance_index==instance_index then return overlay end
  end
  return nil
end
local function single_flight_is_overlay_instance(instance_index)
  return single_flight_overlay_for_instance(instance_index)~=nil
end
local function single_flight_is_active_field_instance(instance_index)
  for _,index in ipairs(single_flight_active_field_instances) do
    if index==instance_index then return true end
  end
  return false
end
local function single_flight_is_pre_pulse_scope_instance(instance_index)
  for _,index in ipairs(single_flight_pre_pulse_scope_instances) do
    if index==instance_index then return true end
  end
  return false
end
local function single_flight_instance_state(instance)
  return {{filename=instance.filename,nx=instance.pa.nx,ny=instance.pa.ny,
    nz=instance.pa.nz,dx_mm=instance.pa.dx_mm,dy_mm=instance.pa.dy_mm,
    dz_mm=instance.pa.dz_mm,scale=instance.scale}}
end
local function single_flight_workbench_state(active_scope)
  if active_scope=='pre_pulse_frontend_accelerator' then
    return {{active_scope=active_scope,instances={{
      [single_flight_accelerator_instance_index]=single_flight_instance_state(assert(simion.wb.instances[single_flight_accelerator_instance_index],
        'pre-pulse screening accelerator instance is missing'))}}}}
  end
  local instances={{}}
  for index=1,#simion.wb.instances do
    local instance=simion.wb.instances[index]
    instances[index]=single_flight_instance_state(instance)
  end
  return {{instances=instances}}
end
local function single_flight_project_electrode_plan()
  return {{apply_at=function(_,pulse_state,setter)
    setter({int(electrodes['grounded_shield_id'])},0)
    local plan=single_flight_analyzer.accelerator_electrode_write_plan(
      pulse_state.active and 'on' or 'off',
      {pulse_voltage_lua})
    for _,item in ipairs(plan) do setter(item.electrode_id,item.voltage_v) end
  end}}
end
local function single_flight_initialize_rf_drives()
{rf_initializer}end
function segment.load()
  sim_trajectory_quality=trajectory_quality
  local path={load_report_lua}
  if path and path~='' then local report=assert(io.open(path,'w')); report:write(string.format('TRAJECTORY_QUALITY=%g\\nSTATUS=PASS\\n',sim_trajectory_quality)); report:close() end
end
function segment.initialize_run()
  assert(single_flight_enable~=0,'single-flight Program requires explicit enable')
  if single_flight_pre_pulse_time_series~=0 then
    assert(handoff_pulse_mode==2,
      'pre-pulse time-series screening requires the existing held-off pulse mode')
{screening_rf_assert}
  end
  sim_trajectory_quality=trajectory_quality
  local analyzer_config={analyzer_config_lua}
  local formal_iob_config={formal_iob_config_lua}
  single_flight_assert_formal_iob_roles(formal_iob_config)
  single_flight_standalone_dynamic_by_instance={{}}
  single_flight_initialize_standalone_dynamic_fields()
  local ai=simion.wb.instances[analyzer_config.instance_roles.accelerator]
  if single_flight_domain_split_enabled~=0 then
    assert(not single_flight_accelerator_pa_override or
      single_flight_accelerator_pa_override=='',
      'domain-split Program must use its accelerator-main PA, not a monolithic override')
  elseif single_flight_accelerator_pa_override and single_flight_accelerator_pa_override~='' and
      not single_flight_accelerator_pa_override_loaded then
    ai.pa:load(single_flight_accelerator_pa_override)
    ai:_debug_update_size()
    single_flight_accelerator_pa_override_loaded=true
  end
  if single_flight_domain_split_enabled==0 and single_flight_accelerator_pa_override and
      single_flight_accelerator_pa_override~='' then
    assert(single_flight_exact_basename(single_flight_accelerator_pa_override,
      'accelerator override')=='frontend.pa0',
      'accelerator override payload basename differs')
    analyzer_config.instance_filenames.accelerator='frontend.pa0'
  end
  single_flight_analyzer=single_flight_analyzer_component.new(analyzer_config)
  local active_scope=single_flight_pre_pulse_time_series~=0 and
    'pre_pulse_frontend_accelerator' or 'full_flight'
  single_flight_analyzer.initialize_workbench(
    single_flight_workbench_state(active_scope))
{placement_initialization_lua}
  single_flight_initialize_rf_drives()
    single_flight_pulse=single_flight_pulse_component.new{{canonical_clock=single_flight_instrument_time_us,voltage_waveforms=single_flight_voltage_waveforms,
      {pulse_config_lua}pulse_mode=function() return handoff_pulse_mode end}}
    single_flight_frontend=single_flight_frontend_component.new{{rf_drive=false,pulse_hook=single_flight_pulse,
      electrode_plan=single_flight_project_electrode_plan(),planes_z_mm={accelerator_planes_lua}}}
    for _,overlay in ipairs(single_flight_overlays) do
      local oi=assert(simion.wb.instances[overlay.instance_index],
        'accelerator overlay instance is missing')
      assert(single_flight_exact_basename(oi.filename,
        overlay.role)==overlay.filename,
        'accelerator overlay filename differs')
{native_overlay_check_lua}    end
  single_flight_particle_state={{}}
  single_flight_analyzer_initialized={{}}
  single_flight_previous={{}}
  single_flight_reported={{}}
end
function segment.efield_adjust()
  -- Global segments intentionally continue a natural pre-pulse trajectory
  -- through vacuum outside every finite PA.  There is no local field or
  -- active-scope instance to validate in that native SIMION state.
  local instance=simion.wb.instances[ion_instance]
  if instance==nil then return end
  if single_flight_pre_pulse_time_series~=0 and single_flight_pre_pulse_collision_only==0 then
    assert(single_flight_is_pre_pulse_scope_instance(ion_instance),
      'pre-pulse screening particle escaped its frontend/accelerator active scope')
  end
  local time=single_flight_instrument_time_us()
  single_flight_apply_standalone_dynamic_field(instance,time)
  local state={{z_mm=ion_pz_mm,instance_id=ion_instance,instance_dx_mm=instance.pa.dx_mm,
    instance_dz_mm=instance.pa.dz_mm,instance_scale=instance.scale}}
  local base=single_flight_analyzer.efield_adjust(state)
  state.pulse_active=single_flight_pulse.is_active_at(time)
  local result=single_flight_region_field.apply(base,state)
  if result then
    if result.replace_all then ion_dvoltsx_gu=0; ion_dvoltsy_gu=0; ion_dvoltsz_gu=0 end
    if result.dvoltsx_gu~=nil then ion_dvoltsx_gu=result.dvoltsx_gu end
    if result.dvoltsy_gu~=nil then ion_dvoltsy_gu=result.dvoltsy_gu end
    if result.dvoltsz_gu~=nil then ion_dvoltsz_gu=result.dvoltsz_gu end
  end
end
function segment.instance_adjust()
  -- Suppress only the numerical detector marker before reflectron entry.
  -- Official instance_adjust uses ion_instance=0 to select the next PA;
  -- do not move the ion or assume velocity is available in this callback.
  -- SIMION also selects an instance before initialize_run creates the
  -- analyzer. No particle has entered the reflectron at that point.
  local detector_active=single_flight_analyzer and
    single_flight_analyzer.detector_marker_active(single_flight_canonical_particle_id())
  if single_flight_pre_pulse_time_series==0 and
      ion_instance==single_flight_detector_instance_index and
      not detector_active then
    ion_instance=0
    return
  end
  local overlay=single_flight_overlay_for_instance(ion_instance)
  if overlay==nil then return end
  local b=overlay.bounds_mm
  if single_flight_pre_pulse_time_series~=0 then
    if ion_px_mm<=b.x_min or ion_px_mm>=b.x_max or
        ion_py_mm<=b.y_min or ion_py_mm>=b.y_max or
        ion_pz_mm<=b.z_min or ion_pz_mm>=b.z_max then ion_instance=0 end
    return
  end
  local detector=simion.wb.instances[single_flight_detector_instance_index]
  if (detector_active and
      detector:inside_wc(ion_px_mm,ion_py_mm,ion_pz_mm)) or
      ion_px_mm<=b.x_min or ion_px_mm>=b.x_max or
      ion_py_mm<=b.y_min or ion_py_mm>=b.y_max or
      ion_pz_mm<=b.z_min or ion_pz_mm>=b.z_max then ion_instance=0 end
end
function segment.initialize()
  -- Official SIMION2020 initialize permits direct velocity assignment (see
  -- examples/random/random.lua). Avoid the tiny FLY2 velocity round-trip
  -- change at an explicit source boundary. Never assign ion_ke afterwards.
  if single_flight_source_velocity_mm_per_us and single_flight_particle_state[ion_number]==nil then
    single_flight_restore_source_velocity(single_flight_source_velocity_mm_per_us)
  end
  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series==0 then
    single_flight_require_analyzer_particle(ion_time_of_flight)
  end
  single_flight_particle_state[ion_number]={{frontend=single_flight_frontend.initialize_particle(ion_pz_mm),
    previous={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}}}
  single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
    vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
  single_flight_reported[ion_number]={{}}
  single_flight_pre_pulse_next_sample[ion_number]=1
  single_flight_continuous_rf_next_sample[ion_number]=1
  single_flight_write_trace(string.format('TRACE: source_release ion=%d particle_id=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g simion_native_kinetic_energy_eV=%.17g source_instance=%d',ion_number,single_flight_canonical_particle_id(),time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_ke,ion_instance))
{native_observation_initialize_lua}end
function segment.tstep_adjust()
{native_step_limits_lua}{native_observation_step_lua}  local analyzer_dt=nil
  if single_flight_pre_pulse_time_series==0 then
    analyzer_dt=single_flight_analyzer.tstep_adjust{{x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
      vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,
      detector_cell_dx_mm=simion.wb.instances[single_flight_detector_instance_index].pa.dx_mm}}
  end
  if analyzer_dt and ion_time_step>analyzer_dt then ion_time_step=analyzer_dt end
  local time=single_flight_instrument_time_us()
{observation_step_lua}  if single_flight_pre_pulse_time_series~=0 then
    local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
    local next_time=nil
    if single_flight_pre_pulse_natural_archive~=0 then
      -- The release position is recorded separately by initialize().  Start
      -- grid states at the next RF tick, then advance only from the persisted
      -- discrete index below.  Re-deriving this from a binary float on every
      -- SIMION step can skip a tick after accumulated roundoff.
      if next_index==1 then next_index=2 end
      next_time=single_flight_pre_pulse_grid_origin_us+(next_index-1)*single_flight_pre_pulse_grid_step_us
    else
      next_time=single_flight_pre_pulse_sample_times_us[next_index]
    end
    if next_time and time<next_time and ion_time_step>next_time-time then
      ion_time_step=next_time-time
    end
  end
  -- A continuous comparator must integrate the same pre-pulse RF waveform on
  -- the same absolute native grid as its handoff producer.  Merely capping the
  -- maximum step permits SIMION's adaptive trajectory step to drift between
  -- RF nodes and changes which ions reach the aperture.  Persist the next
  -- discrete index per ion; derive it from floating point time only once at
  -- release, then advance monotonically at exact landings.
  if #single_flight_rf_drives>0 and single_flight_pre_pulse_time_series==0 and
      {pre_on_lua} then
    local next_index=single_flight_continuous_rf_next_sample[ion_number] or 1
    if next_index==1 then
      next_index=math.floor(time/single_flight_continuous_rf_grid_step_us)+2
    end
    local next_time=(next_index-1)*single_flight_continuous_rf_grid_step_us
    local tolerance=1e-9*math.max(1,math.abs(next_time))
    while next_time<=time+tolerance do
      next_index=next_index+1
      next_time=(next_index-1)*single_flight_continuous_rf_grid_step_us
    end
    single_flight_continuous_rf_next_sample[ion_number]=next_index
    if ion_time_step>next_time-time then ion_time_step=next_time-time end
  end
  local pulse_capped=single_flight_pulse.cap_timestep_at(time,ion_time_step)
  if ion_time_step>pulse_capped then ion_time_step=pulse_capped end
  if single_flight_is_active_field_instance(ion_instance) then
    for _,drive in ipairs(single_flight_rf_drives) do
      if ion_time_step>drive.timestep_cap_us then ion_time_step=drive.timestep_cap_us end
    end
    local state=single_flight_require_particle_state()
    local capped=single_flight_frontend.cap_timestep_at(time,ion_pz_mm,ion_vz_mm,ion_time_step,state.frontend)
    if ion_time_step>capped then ion_time_step=capped end
  end
end
function segment.other_actions()
  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series==0 then
    single_flight_require_analyzer_particle(ion_time_of_flight)
  end
  local state=single_flight_require_particle_state()
  local current={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}
  single_flight_frontend.observe_step(state.previous,current,state.frontend)
  state.previous=current
  local p=single_flight_previous[ion_number]
    if single_flight_pre_pulse_time_series~=0 then
      local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
      local sample_time=nil
      if single_flight_pre_pulse_natural_archive~=0 then
      -- The persisted index, rather than the nearest current clock node, is
      -- authoritative.  Re-rounding a stalled SIMION clock to its previous
      -- node lets this callback emit an unlimited sequence of fictitious
      -- later samples while physical time has not advanced.  The t=0 source
      -- release is stored by initialize(), so the first native grid state is
      -- index 2.
      if next_index==1 then next_index=2 end
      sample_time=single_flight_pre_pulse_grid_origin_us+(next_index-1)*single_flight_pre_pulse_grid_step_us
    else
      sample_time=single_flight_pre_pulse_sample_times_us[next_index]
    end
    while sample_time and time>=sample_time do
      local x,y,z,vx,vy,vz=ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm
      -- SIMION may shorten a final step to resolve a geometry collision.  That
      -- endpoint is a terminal observation, not a state on the native RF grid:
      -- retain it through segment.terminate and do not relabel it as a grid
      -- sample.  All emitted time-series rows therefore remain native-grid
      -- states; no interpolated state is ever manufactured here.  Keep the
      -- historic finite-window contract strict, since its scheduled samples
      -- are required landings rather than a natural trajectory archive.
      if single_flight_pre_pulse_natural_archive~=0 and
          math.abs(time-sample_time)>1e-9*math.max(1,math.abs(sample_time)) then break end
      -- Lua doubles and SIMION's time accumulator can differ by a few ULP at
      -- a requested RF landing.  This is still the same native grid event;
      -- keep the stored canonical grid time and retain the actual clock in
      -- its separate column.  The tolerance matches the preceding guard so
      -- a genuine shortened collision endpoint is never relabelled.
      assert(math.abs(time-sample_time)<=1e-9*math.max(1,math.abs(sample_time)),
        'pre-pulse time-series sample did not land on its native SIMION timestep')
      local energy=0.0051821348263402529*ion_mass*(vx*vx+vy*vy+vz*vz)
      if trajectory_log_enable~=0 then
        single_flight_write_trace(string.format('TRACE: pre_pulse_time_series_state ion=%d particle_id=%d sample_index=%d instrument_time_us=%.17g actual_instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g kinetic_energy_eV=%.17g survival_status=alive',
          ion_number,single_flight_canonical_particle_id(),next_index,sample_time,time,x,y,z,vx,vy,vz,energy))
      end
      next_index=next_index+1
      single_flight_pre_pulse_next_sample[ion_number]=next_index
      if single_flight_pre_pulse_natural_archive~=0 then
        sample_time=nil
      else
        sample_time=single_flight_pre_pulse_sample_times_us[next_index]
      end
    end
    single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
      vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
    if single_flight_pre_pulse_natural_archive==0 and next_index>#{screening_sample_table} then ion_splat=1 end
    return
  end
  local reported=single_flight_reported[ion_number] or {{}}
  single_flight_reported[ion_number]=reported
  local function crossing(plane,direction)
    if not p then return nil end
    local crossed=direction>0 and p.z<plane and ion_pz_mm>=plane and ion_vz_mm>0 or
      direction<0 and p.z>plane and ion_pz_mm<=plane and ion_vz_mm<0
    if not crossed then return nil end
    local fraction=(plane-p.z)/(ion_pz_mm-p.z)
    return fraction,p.t+fraction*(time-p.t),p.x+fraction*(ion_px_mm-p.x),
      p.y+fraction*(ion_py_mm-p.y),p.vx+fraction*(ion_vx_mm-p.vx),
      p.vy+fraction*(ion_vy_mm-p.vy),p.vz+fraction*(ion_vz_mm-p.vz)
  end
{pulse_observations_lua}{incident_x_observations_lua}  local _,tc,xc,yc,vxc,vyc,vzc=crossing(accelerator_grid1_z_mm,1)
  if tc and not reported.grid1 then reported.grid1=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_grid1_forward ion=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision}',ion_number,tc,xc,yc,accelerator_grid1_z_mm,vxc,vyc,vzc)) end
  end
{intermediate2_crossing_lua}  _,tc,xc,yc,vxc,vyc,vzc=crossing(accelerator_grid2_z_mm,1)
  if tc and not reported.local_exit then reported.local_exit=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: local_accelerator_exit ion=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision}',ion_number,tc,xc,yc,accelerator_grid2_z_mm,vxc,vyc,vzc)) end
{exit_stop_action_lua}  end
  local focus_z=accelerator_grid2_z_mm+{_lua_number(oatof['geometry_derivation']['accelerator']['focus_drift_after_grid2_mm'])}
  _,tc,xc,yc,vxc,vyc,vzc=crossing(focus_z,1)
  if tc and not reported.focus then reported.focus=true
    if trajectory_log_enable~=0 then print(string.format('TRACE: accelerator_focus_forward ion=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision}',ion_number,tc,xc,yc,focus_z,vxc,vyc,vzc)) end
  end
  _,tc,xc,yc,vxc,vyc,vzc=crossing(reflectron_entgrid_z_mm,1)
  if tc and not reported.reflectron_entrance then reported.reflectron_entrance=true
    single_flight_trace_checkpoint('reflectron_entrance_forward',tc,xc,yc,reflectron_entgrid_z_mm,vxc,vyc,vzc)
  end
  _,tc,xc,yc,vxc,vyc,vzc=crossing(reflectron_midgrid_z_mm,1)
  if tc and reported.reflectron_entrance and not reported.reflectron_midgrid then reported.reflectron_midgrid=true
    single_flight_trace_checkpoint('reflectron_midgrid_forward',tc,xc,yc,reflectron_midgrid_z_mm,vxc,vyc,vzc)
  end
  if p and reported.reflectron_midgrid and not reported.reflectron_turning and p.vz>0 and ion_vz_mm<=0 then
    local f=p.vz/(p.vz-ion_vz_mm); reported.reflectron_turning=true
    single_flight_trace_checkpoint('reflectron_turning_point',p.t+f*(time-p.t),
      p.x+f*(ion_px_mm-p.x),p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),
      p.vx+f*(ion_vx_mm-p.vx),p.vy+f*(ion_vy_mm-p.vy),0)
  end
  _,tc,xc,yc,vxc,vyc,vzc=crossing(reflectron_entgrid_z_mm,-1)
  if tc and reported.reflectron_turning and not reported.reflectron_exit then reported.reflectron_exit=true
    single_flight_trace_checkpoint('reflectron_exit_return',tc,xc,yc,reflectron_entgrid_z_mm,vxc,vyc,vzc)
  end
  single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
    vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
  local result=single_flight_analyzer.other_actions{{particle_id=single_flight_canonical_particle_id(),elapsed_us=ion_time_of_flight,pulse_elapsed_us={pulse_elapsed_lua},x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,vz_mm_per_us=ion_vz_mm}}
  if trajectory_log_enable~=0 then
    for _,event in ipairs(result.events) do
      if event.kind=='diagnostic_return_plane' then
        print(string.format('TRACE: diagnostic_return_plane ion=%d t={state_precision} x={state_precision} y={state_precision} z={state_precision} vz={state_precision} zmax={state_precision}',
          ion_number,event.elapsed_us,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vz_mm,event.max_z_mm))
      end
    end
  end
  if result.splat{terminate_after_lua} then ion_splat=1 end
{native_observation_actual_lua}{native_age_limit_lua}
end
function segment.terminate()
{native_timeout_terminate_lua}{exit_stop_terminal_lua}  local time=single_flight_instrument_time_us()
  if single_flight_pre_pulse_time_series~=0 then
    if trajectory_log_enable~=0 then
      local next_index=single_flight_pre_pulse_next_sample[ion_number] or 1
      local terminal_reason=(single_flight_pre_pulse_natural_archive~=0 and
        (ion_instance==0 and 'outside_pa_termination' or 'geometry_collision')) or
        (next_index>#{screening_sample_table} and 'window_complete' or 'splat')
      single_flight_write_trace(string.format('TRACE: pre_pulse_screening_terminal ion=%d particle_id=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g terminal_reason=%s',
        ion_number,single_flight_canonical_particle_id(),time,ion_px_mm,ion_py_mm,ion_pz_mm,
        ion_vx_mm,ion_vy_mm,ion_vz_mm,terminal_reason))
    end
    return
  end
  if {terminal_log_lua} and trajectory_log_enable~=0 then
    print(string.format('TRACE: handoff_terminal_raw ion=%d instance=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} vx_mm_per_us={state_precision} vy_mm_per_us={state_precision} vz_mm_per_us={state_precision}',
      ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))
  end
  single_flight_require_analyzer_particle(ion_time_of_flight)
  local result=single_flight_analyzer.terminate{{particle_id=single_flight_canonical_particle_id(),instance_id=ion_instance,
    elapsed_us=ion_time_of_flight,x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
    vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,
    detector_cell_dx_mm=simion.wb.instances[single_flight_detector_instance_index].pa.dx_mm}}
  if trajectory_log_enable~=0 and result then
    if result.kind=='detector_crossing' then
      print(string.format('TRACE: detector_crossing ion=%d t={state_precision} x={state_precision} y={state_precision} z={state_precision} r={state_precision} zmax={state_precision}',
        ion_number,result.elapsed_us,result.x_mm,result.y_mm,result.z_mm,result.radius_mm,result.max_z_mm))
      print(string.format('TRACE: detector_hit_entity ion=%d instance=%d',
        ion_number,single_flight_detector_instance_index))
    elseif result.kind=='timeout_splat' then
      print(string.format('TRACE: timeout_splat ion=%d instance=%d instrument_time_us={state_precision} x_mm={state_precision} y_mm={state_precision} z_mm={state_precision} zmax_mm={state_precision}',
        ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,result.max_z_mm))
    elseif result.kind=='non_detector_splat' then
      print(string.format('TRACE: non_detector_splat ion=%d instance=%d t={state_precision} x={state_precision} y={state_precision} z={state_precision} zmax={state_precision}',
        ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,result.max_z_mm))
    end
  end
end
"""
    if program.count("simion.workbench_program()") != 1:
        raise ValueError("combined single-flight Program must declare one workbench")
    for callback in _SUCCESSOR_CALLBACKS:
        count = len(re.findall(rf"function\s+segment\.{callback}\s*\(", program))
        if count != 1:
            raise ValueError(f"combined single-flight Program callback {callback} count is {count}")
    return program


def build_local_frontend_program(
    upstream: dict[str, Any], frontend: dict[str, Any], *,
    birth_times_us: list[float], particle_ids: list[int],
    initial_velocities_mm_per_us: list[list[float]], pulse_time_us: float,
    pulse_width_us: float, maximum_flight_us: float, maximum_step_us: float,
    shared_times_us: list[float], trajectory_cadence_us: float,
    standalone_dynamic_field_bank: dict[str, Any],
    standalone_dynamic_field_paths: dict[str, dict[str, Any]],
    rf_drive_kernel_source: str, pulse_hook_source: str, frontend_hook_source: str,
    voltage_waveforms_source: str,
    rf_steps_per_period: int, trajectory_quality: int, pulse_mode: int = 1,
) -> str:
    """Assemble one real frontend carrier with existing RF/pulse response glue.

    This scope ends at the actual forward OA exit, a native loss or timeout.
    It contains no analyzer/reflectron geometry, integration or source generator.
    Shared-time rows contain active native states only; the complete mother
    census supplies not-born and already-terminal statuses downstream.
    """
    if frontend.get("frontend_variant") not in {TWO_ZONE_BARE_VARIANT, THREE_ZONE_BARE_VARIANT}:
        raise ValueError("local frontend requires a supported canonical bare variant")
    if frontend.get("native_frame_id") != "mrtof_global_cartesian" or frontend.get("slow_axis") != "y" or frontend.get("acceleration_direction") != -1:
        raise ValueError("local frontend requires native MR coordinates, slow +y and acceleration -z")
    actual = _canonical_bare_runtime_projection(frontend, acceleration_direction=-1)
    port = frontend["accelerator_local_region"]["port"]
    if port["normal_axis"] != "y":
        raise ValueError("local aperture checkpoints require physical +y entry")
    aperture_planes = [port["flange_min_mm"], port["flange_max_mm"]]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in aperture_planes) or aperture_planes[0] >= aperture_planes[1]:
        raise ValueError("local aperture checkpoints require finite increasing physical wall faces")
    rod_drive = _upstream_rod_drive(upstream)
    count = len(birth_times_us)
    if not count or len(particle_ids) != count or len(set(particle_ids)) != count or any(
        isinstance(i, bool) or not isinstance(i, int) or i < 1 for i in particle_ids
    ):
        raise ValueError("local frontend requires complete unique source IDs")
    if any(not math.isfinite(t) or t < 0 for t in birth_times_us):
        raise ValueError("local frontend birth clocks are invalid")
    if len(initial_velocities_mm_per_us) != count or any(
        len(v) != 3 or any(not math.isfinite(x) for x in v) for v in initial_velocities_mm_per_us
    ):
        raise ValueError("local frontend requires exact finite source velocities")
    numeric = (pulse_time_us, pulse_width_us, maximum_flight_us, maximum_step_us, trajectory_cadence_us)
    if any(isinstance(v, bool) or not math.isfinite(v) for v in numeric) or pulse_time_us < 0 or min(numeric[1:]) <= 0:
        raise ValueError("local frontend time contract is invalid")
    if type(pulse_mode) is not int or pulse_mode not in (1, 2):
        raise ValueError("local pulse mode must be timed ON or held OFF")
    if pulse_mode == 1 and pulse_time_us + pulse_width_us < max(birth_times_us) + maximum_flight_us:
        raise ValueError("local frontend pulse must stay ON throughout the declared flight horizon")
    if not shared_times_us or any(not math.isfinite(t) or t < 0 for t in shared_times_us) or shared_times_us != sorted(set(shared_times_us)):
        raise ValueError("local shared times must be explicit, unique and increasing")
    if isinstance(rf_steps_per_period, bool) or not isinstance(rf_steps_per_period, int) or rf_steps_per_period < 1:
        raise ValueError("local RF steps per period must be positive")
    if type(trajectory_quality) is not int or not 1 <= trajectory_quality <= 500:
        raise ValueError("local frontend requires explicit positive integer trajectory quality within SIMION range 1..500")
    specs = _resolve_standalone_dynamic_field_bank(
        standalone_dynamic_field_bank, {"coarse_frontend": 1},
    )
    _bind_standalone_dynamic_field_paths(specs, standalone_dynamic_field_paths)
    if len(specs) != 1 or len(specs[0].get("rf_differential_pa_basenames", [])) != 1 or specs[0]["pulse_delta_pa_basename"] is None:
        raise ValueError("local frontend requires the carrier, RF and pulse-delta fields")
    components = {
        "single_flight_rf_kernel": rf_drive_kernel_source,
        "single_flight_pulse_component": pulse_hook_source,
        "single_flight_voltage_waveforms": voltage_waveforms_source,
        "single_flight_frontend_component": frontend_hook_source,
    }
    embedded = "\n".join(
        f"local {name}=(function()\n{validate_pure_lua_component_source(source, name)}\nend)()"
        for name, source in components.items()
    )
    drive = rod_drive["drive"]
    rf_electrodes = _rf_kernel_electrodes(rod_drive)
    origin = frontend["instance_origin_mm"]
    planes = actual["planes"]
    pa_downstream_z = frontend["instance_bounds_mm"]["z_min"]
    if isinstance(pa_downstream_z, bool) or not isinstance(pa_downstream_z, (int, float)) or not math.isfinite(pa_downstream_z):
        raise ValueError("local numerical stop requires a finite downstream PA boundary")
    numerical_stop_z = pa_downstream_z + (planes["exit"] - pa_downstream_z) / 2
    if not pa_downstream_z < numerical_stop_z < planes["exit"]:
        raise ValueError("local numerical stop requires representable downstream PA padding")
    post_exit_step_distance = (planes["exit"] - pa_downstream_z) / 4
    crossing_planes = [planes["grid1"]] + ([planes["intermediate2"]] if "intermediate2" in planes else []) + [planes["exit"]]
    crossing_planes_lua = ",".join(_lua_number(z) for z in crossing_planes)
    crossing_event_lua = f"plane=={_lua_number(planes['exit'])} and 'local_accelerator_exit' or 'accelerator_grid1_forward'"
    if "intermediate2" in planes:
        crossing_event_lua = (f"plane=={_lua_number(planes['exit'])} and 'local_accelerator_exit' or "
                              f"(plane=={_lua_number(planes['intermediate2'])} and 'accelerator_intermediate2_forward' or 'accelerator_grid1_forward')")
    return f"""-- Local canonical frontend only; generated by the existing Program assembler.
simion.workbench_program()
-- Official global callback scope retains actual terminal observations outside the PA.
-- Field, step control and trajectory observations below remain carrier-local.
sim_segment_global=1
{embedded}
local single_flight_time_origin_us={_lua_value(birth_times_us)}
local single_flight_source_particle_id={_lua_value(particle_ids)}
local single_flight_particle_id_offset=assert(tonumber(os.getenv('OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET') or '0'),'invalid single-flight particle ID offset')
{canonical_clock_lua()}
local source_velocities={_lua_value(initial_velocities_mm_per_us)}
local shared_times={_lua_value(shared_times_us)}
-- Numerical stopping lies inside existing PA padding; the scientific exit stays unchanged.
local numerical_stop_z_mm={_lua_number(numerical_stop_z)}
local post_exit_step_distance_mm={_lua_number(post_exit_step_distance)}
local single_flight_rf,single_flight_pulse,frontend_hook,aperture_hook
local single_flight_rf_drives={{}}
{_standalone_dynamic_field_lua(specs)}
local states={{}}
local field_query_outside_logged={{}}
local function emit(event,t,x,y,z,vx,vy,vz,requested,source_instance)
  print(string.format('TRACE: %s ion=%d particle_id=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g requested_time_us=%.17g source_instance=%d',
    event,ion_number,single_flight_canonical_particle_id(),t,x,y,z,vx,vy,vz,requested or t,source_instance or ion_instance))
end
local function emit_actual(event,requested)
  emit(event,single_flight_instrument_time_us(),ion_px_mm,ion_py_mm,ion_pz_mm,
    ion_vx_mm,ion_vy_mm,ion_vz_mm,requested)
end
-- Freeze numerical quality; trajectory retention belongs to the native CLI/IOB.
-- Do not override scheduled Fly's --retain-trajectories 0 (SIMION 2020).
function segment.load()
  sim_trajectory_quality={trajectory_quality}
end
function segment.initialize_run()
  sim_trajectory_quality={trajectory_quality}
  print(string.format('LOCAL_DISPLAY_CONTROL: sim_trajectory_image_control=%s',tostring(sim_trajectory_image_control)))
  assert(#simion.wb.instances==1,'local frontend requires one actual carrier instance')
  local carrier=simion.wb.instances[1]
  assert(carrier.x=={_lua_number(origin['x'])} and carrier.y=={_lua_number(origin['y'])}
    and carrier.z=={_lua_number(origin['z'])} and carrier.scale==1
    and carrier.az==0 and carrier.el==0 and carrier.rt==0,'local frontend carrier transform differs')
  states={{}}; field_query_outside_logged={{}}; single_flight_standalone_dynamic_by_instance={{}}
  single_flight_initialize_standalone_dynamic_fields()
  single_flight_rf=single_flight_rf_kernel.new{{waveform={json.dumps(drive['waveform'])},
    frequency_hz={_lua_number(drive['frequency_Hz'])},phase_rad={_lua_number(drive['phase_rad'])},
    rf_amplitude_v={_lua_number(drive['rf_amplitude_V_zero_to_peak_per_group'])},rf_scale=1,common_mode_scale=1,
    group_dc_v={{[1]={_lua_number(drive['dc_amplitude_V_per_group'])},[2]={_lua_number(-drive['dc_amplitude_V_per_group'])}}},
    rf_steps_per_period={rf_steps_per_period},electrodes={_lua_value(rf_electrodes)}}}
  single_flight_rf_drives[1]=single_flight_rf
  single_flight_pulse=single_flight_pulse_component.new{{canonical_clock=single_flight_instrument_time_us,voltage_waveforms=single_flight_voltage_waveforms,
    pulse_time_us={_lua_number(pulse_time_us)},pulse_width_us={_lua_number(pulse_width_us)},pulse_mode=function() return {pulse_mode} end}}
  frontend_hook=single_flight_frontend_component.new{{rf_drive=single_flight_rf,pulse_hook=single_flight_pulse,
    electrode_plan={{apply_at=function() end}},planes_z_mm={_lua_value([-z for z in crossing_planes])}}}
  -- Plane observations must also land during the held-OFF discovery flight.
  -- This adapter only caps observation steps; it never applies any electrode drive.
  aperture_hook=single_flight_frontend_component.new{{rf_drive=false,
    pulse_hook={{state_at=single_flight_pulse.state_at,is_active_at=function() return true end,
      cap_timestep_at=single_flight_pulse.cap_timestep_at,diagnostics_at=single_flight_pulse.diagnostics_at}},
    electrode_plan={{apply_at=function() end}},planes_z_mm={_lua_value(aperture_planes)}}}
end
function segment.initialize()
  assert(ion_instance==1,'local source must initialize inside the actual carrier')
  local carrier=assert(simion.wb.instances[1],'local source carrier missing')
  local x,y,z=carrier:wb_to_pa_coords(ion_px_mm,ion_py_mm,ion_pz_mm)
  assert(carrier.pa:inside_vc(x,y,z),'local source lies outside the actual carrier')
  single_flight_restore_source_velocity(source_velocities)
  local t=single_flight_instrument_time_us()
  local index=1
  while shared_times[index] and shared_times[index]<t do index=index+1 end
  states[ion_number]={{previous={{t=t,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
    vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm,instance=ion_instance}},shared=index,next_track=t+{_lua_number(trajectory_cadence_us)},
    planes=frontend_hook.initialize_particle(-ion_pz_mm),
    aperture_planes=aperture_hook.initialize_particle(ion_py_mm)}}
  emit_actual('source_release',t)
  if shared_times[index]==t then emit_actual('local_shared_time',t);states[ion_number].shared=index+1 end
end
function segment.efield_adjust()
  local instance=simion.wb.instances[ion_instance]
  if instance==nil then return end
  local x,y,z=instance:wb_to_pa_coords(ion_px_mm,ion_py_mm,ion_pz_mm)
  -- Official inside_vc uses the same mirrored PA grid coordinates as field_vc.
  -- A native field trial can leave the PA before an accepted particle state does.
  -- Leave the native gradient and termination mechanism untouched for that query.
  if not instance.pa:inside_vc(x,y,z) then
    if not field_query_outside_logged[ion_number] then
      print(string.format('FIELD_QUERY_OUTSIDE: basis=query_only particle_id=%d ion=%d instance=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g x_gu=%.17g y_gu=%.17g z_gu=%.17g',
        single_flight_canonical_particle_id(),ion_number,ion_instance,single_flight_instrument_time_us(),
        ion_px_mm,ion_py_mm,ion_pz_mm,x,y,z))
      field_query_outside_logged[ion_number]=true
    end
    return
  end
  single_flight_apply_standalone_dynamic_field(instance,single_flight_instrument_time_us())
end
function segment.tstep_adjust()
  if ion_instance==0 then return end
  local state=assert(states[ion_number],'local particle state missing')
  local t=single_flight_instrument_time_us()
  local dt=math.min(ion_time_step,{_lua_number(maximum_step_us)})
  if state.exit_observed and ion_vz_mm~=0 then
    dt=math.min(dt,post_exit_step_distance_mm/math.abs(ion_vz_mm))
  end
  dt=frontend_hook.cap_timestep_at(t,-ion_pz_mm,-ion_vz_mm,dt,state.planes)
  dt=aperture_hook.cap_timestep_at(t,ion_py_mm,ion_vy_mm,dt,state.aperture_planes)
  local deadline=single_flight_time_origin_us[single_flight_source_row_index()]+{_lua_number(maximum_flight_us)}
  for _,target in ipairs({{shared_times[state.shared] or math.huge,state.next_track,deadline}}) do
    if target>t then dt=math.min(dt,target-t) end
  end
  ion_time_step=dt
end
function segment.other_actions()
  if ion_instance==0 then return end
  local state=assert(states[ion_number],'local particle state missing')
  if state.terminal then return end
  local t=single_flight_instrument_time_us()
  local p=state.previous
  -- SIMION may retain the preceding accepted state when ion_splat is set here.
  -- Stop before publishing this callback as a trajectory/shared-time observation.
  if state.exit_observed and ion_pz_mm<=numerical_stop_z_mm and ion_vz_mm<0 then
    print(string.format('LOCAL_NUMERICAL_STOP: basis=callback_before_splat_override particle_id=%d ion=%d instance=%d instrument_time_us=%.17g z_mm=%.17g numerical_stop_z_mm=%.17g native_ion_splat=%.17g',
      single_flight_canonical_particle_id(),ion_number,ion_instance,t,ion_pz_mm,numerical_stop_z_mm,ion_splat))
    state.terminal='accelerator_exit_stop';ion_splat=1;return
  end
  local tolerance=32*2.2204460492503131e-16*math.max(1,math.abs(t))
  -- Timeout splats can also return the preceding native state at terminate.
  -- Decide before publishing any observations from this stopping callback.
  if ion_time_of_flight>={_lua_number(maximum_flight_us)}-tolerance then
    state.terminal='local_timeout';ion_splat=1;return
  end
  frontend_hook.observe_step({{time_us=p.t,position_z_mm=-p.z,velocity_z_mm_per_us=-p.vz}},
    {{time_us=t,position_z_mm=-ion_pz_mm,velocity_z_mm_per_us=-ion_vz_mm}},state.planes)
  local aperture_events=aperture_hook.observe_step(
    {{time_us=p.t,position_z_mm=p.y,velocity_z_mm_per_us=p.vy}},
    {{time_us=t,position_z_mm=ion_py_mm,velocity_z_mm_per_us=ion_vy_mm}},state.aperture_planes)
  for _,crossing in ipairs(aperture_events) do
    local event=crossing.plane_index==1 and 'local_aperture_pre' or 'local_aperture_post'
    local plane=crossing.plane_z_mm
    -- Preserve the actual native step endpoints; only the checkpoint is interpolated.
    emit(event..'_step_before',p.t,p.x,p.y,p.z,p.vx,p.vy,p.vz,nil,p.instance)
    emit_actual(event..'_step_after')
    if t>p.t and p.y<plane and ion_py_mm>=plane then
      local f=(plane-p.y)/(ion_py_mm-p.y)
      assert(f>=0 and f<=1 and ion_vy_mm>0,'aperture crossing must bracket a forward step')
      local vy=p.vy+f*(ion_vy_mm-p.vy)
      assert(vy>0,'interpolated aperture crossing must be forward')
      emit(event,p.t+f*(t-p.t),p.x+f*(ion_px_mm-p.x),plane,p.z+f*(ion_pz_mm-p.z),
        p.vx+f*(ion_vx_mm-p.vx),vy,p.vz+f*(ion_vz_mm-p.vz))
    else
      -- Zero-step confirmations have no bracket: retain the actual state, never extrapolate.
      local _,exponent=math.frexp(math.max(1,math.abs(plane),math.abs(ion_py_mm)))
      assert(t==p.t and ion_px_mm==p.x and ion_py_mm==p.y and ion_pz_mm==p.z and
        ion_vx_mm==p.vx and ion_vy_mm==p.vy and ion_vz_mm==p.vz and ion_vy_mm>0 and
        math.abs(ion_py_mm-plane)<=32*2^(exponent-53),
        'aperture confirmation lacks a bracket or actual state within 32 ULP')
      emit_actual(event)
    end
  end
  -- A backward passage rearms future forward observations, without dropping raw recrossings.
  for _,plane in ipairs({_lua_value(aperture_planes)}) do
    if p.y>=plane and ion_py_mm<plane then
      state.aperture_planes=aperture_hook.initialize_particle(ion_py_mm);break
    end
  end
  local shared_target=shared_times[state.shared]
  if shared_target then
    -- Match the analysis binary64 allowance; an early state keeps this target pending.
    local _,exponent=math.frexp(math.max(1,math.abs(t),math.abs(shared_target)))
    if math.abs(t-shared_target)<=32*2^(exponent-53) then
      emit_actual('local_shared_time',shared_target);state.shared=state.shared+1
    end
  end
  if t>=state.next_track-tolerance then
    emit_actual('local_trajectory',state.next_track)
    state.next_track=state.next_track+{_lua_number(trajectory_cadence_us)}
  end
  for _,plane in ipairs({{{crossing_planes_lua}}}) do
    if p.z>plane and ion_pz_mm<=plane and ion_vz_mm<0 and
      (plane~={_lua_number(planes['exit'])} or not state.exit_observed) then
      local f=(plane-p.z)/(ion_pz_mm-p.z)
      if plane=={_lua_number(planes['exit'])} then
        -- Preserve callback endpoints independently of any later native splat localization.
        emit('local_accelerator_exit_step_before',p.t,p.x,p.y,p.z,p.vx,p.vy,p.vz,nil,p.instance)
        emit_actual('local_accelerator_exit_step_after')
        print(string.format('LOCAL_EXIT_OBSERVER: basis=callback_before_splat_override particle_id=%d ion=%d instance=%d instrument_time_us=%.17g ion_time_step_us=%.17g native_ion_splat=%.17g interpolation_fraction=%.17g',
          single_flight_canonical_particle_id(),ion_number,ion_instance,t,ion_time_step,ion_splat,f))
      end
      emit({crossing_event_lua},
        p.t+f*(t-p.t),p.x+f*(ion_px_mm-p.x),p.y+f*(ion_py_mm-p.y),plane,
        p.vx+f*(ion_vx_mm-p.vx),p.vy+f*(ion_vy_mm-p.vy),p.vz+f*(ion_vz_mm-p.vz))
      if plane=={_lua_number(planes['exit'])} then state.exit_observed=true end
    end
  end
  state.previous={{t=t,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm,instance=ion_instance}}
end
function segment.terminate()
  local state=assert(states[ion_number],'local terminal state missing')
  if not state.logged then
    state.logged=true;emit_actual(state.terminal or 'local_native_stop')
  end
end
"""
