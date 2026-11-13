"""Build the continuous SIMION Program from frozen oaTOF and multipole contracts."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from msplatform.contracts.rigid_transform import FramedPosition, PlaneSurface, RigidTransform, relative_transform
from msplatform.backends.simion.rf_geometry import segmented_rod_electrode_ids
from msplatform.backends.simion.source import validate_native_particle_ids, canonical_clock_lua, lua_number as _lua_number, lua_value as _lua_value
from msplatform.backends.simion.electrode_contract import (
    ROD_ELECTRODE_IDS,
    project_pa_plus_mode_voltages,
    physical_multipole_voltages,
    scientific_multipole_voltages,
    scientific_multipole_rod_pieces,
    multipole_rod_pieces,
    require_pa_plus_solution_model,
)
class BoundaryContractError(ValueError):
    """Raised when a pure integration boundary is incomplete or ambiguous."""

_FORBIDDEN_LUA_PATTERNS = {
    "simion.workbench_program": re.compile(r"(?<![\w.])simion\s*\.\s*workbench_program\b"),
    "segment.": re.compile(r"(?<!\w)segment\s*\."),
    "adj_elect": re.compile(r"(?<!\w)adj_elect(?!\w)"),
    "ion_time_of_birth": re.compile(r"(?<!\w)ion_time_of_birth(?!\w)"),
    "ion_time_of_flight": re.compile(r"(?<!\w)ion_time_of_flight(?!\w)"),
    "simion.wb": re.compile(r"(?<![\w.])simion\s*\.\s*wb\b"),
    "os.clock": re.compile(r"(?<![\w.])os\s*\.\s*clock\b"),
}

def validate_pure_lua_component_source(source: str, name: str) -> str:
    """Reject callback, electrode, native-clock, and Workbench ownership in Lua.

    The returned source is unchanged.  This validator is the single Python
    boundary used before callback-neutral Lua is embedded into a SIMION Program.
    """
    if not isinstance(source, str) or not source.strip():
        raise BoundaryContractError(f"{name} must be non-empty Lua source")
    if not isinstance(name, str) or not name.strip():
        raise BoundaryContractError("pure Lua component name must be non-empty")
    violations = [
        token for token, pattern in _FORBIDDEN_LUA_PATTERNS.items() if pattern.search(source)
    ]
    if violations:
        raise BoundaryContractError(
            f"{name} is not callback-neutral; forbidden tokens: {', '.join(violations)}"
        )
    return source
from msplatform.components.single_reflection_oa_tof.accelerator_electrical import resolve_accelerator_electrical_design
from msplatform.backends.simion.tof_geometry import derive_simion_geometry, resolve_physical_geometry

_DIAGNOSTIC_RETURN_PLANE_Z_MM = 20.5
_SUCCESSOR_DIAGNOSTICS = {"post_pulse_observation_window_us": 90.0, "log_stride": 1000}

FIELD_OBSERVATION_BUCKETS = (
    'first_callback', 'rf_phase_0_near', 'rf_phase_pi_over_2_near', 'rf_phase_pi_near',
    'pulse_start_before', 'pulse_start_after', 'pulse_end_before', 'pulse_end_after',
)


def validate_native_field_observation(spec: dict, *, particle_ids: list[int],
        source_instances: tuple[str, ...], domain_ids: list[str], clock_epoch_id: str,
        flight: dict) -> dict:
    """Validate opt-in bounded query evidence, never alter a flight control.

    Time windows are half-open canonical us. Near-phase targets are labels for
    actual query times, not integrator landing constraints or error tolerances.
    The sole eligible batch contains the first frozen original source ID.
    """
    required = {'schema_version','role','source_instance_id','domain_id','clock_epoch_id',
                'eligible_batch_anchor_particle_id','deadline_us','max_rows','rows_per_bucket','max_output_bytes','buckets'}
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError('native field observation fields differ')
    if (type(spec['schema_version']) is not int or spec['schema_version'] != 1
            or spec['role'] != 'single_reflection_applied_field_observation'
            or spec['source_instance_id'] not in source_instances or spec['domain_id'] not in domain_ids
            or spec['clock_epoch_id'] != clock_epoch_id):
        raise ValueError('native field observation source/domain/clock/version differs')
    if (not particle_ids or any(type(pid) is not int or pid < 1 for pid in particle_ids)
            or len(set(particle_ids)) != len(particle_ids)
            or type(spec['eligible_batch_anchor_particle_id']) is not int
            or spec['eligible_batch_anchor_particle_id'] != particle_ids[0]):
        raise ValueError('native field observation anchor must be the first frozen cohort ID')
    for key, value in (('max_rows',16),('rows_per_bucket',2),('max_output_bytes',1048576)):
        if type(spec[key]) is not int or spec[key] != value:
            raise ValueError('native field observation requires 16 rows / 2 per bucket / 1MiB cap')
    finite = lambda value: type(value) in (int,float) and math.isfinite(value)
    if not finite(spec['deadline_us']):
        raise ValueError('native field observation deadline must be finite')
    buckets = spec['buckets']
    if (not isinstance(buckets,list) or len(buckets) != 8 or any(not isinstance(row,dict) for row in buckets)
            or [row.get('bucket_id') for row in buckets] != list(FIELD_OBSERVATION_BUCKETS)):
        raise ValueError('native field observation requires its eight ordered buckets')
    for row in buckets:
        if (set(row) != {'bucket_id','time_min_us','time_max_us','target_time_us','target_rf_phase_rad'}
                or any(not finite(row[key]) for key in ('time_min_us','time_max_us','target_time_us'))
                or not row['time_min_us'] < row['time_max_us'] <= spec['deadline_us']
                or not row['time_min_us'] <= row['target_time_us'] <= row['time_max_us']
                or (row['target_rf_phase_rad'] is not None and not finite(row['target_rf_phase_rad']))):
            raise ValueError('native field observation window/target must be finite and bounded')
    for index,target in ((1,0.),(2,math.pi/2),(3,math.pi)):
        if buckets[index]['target_rf_phase_rad'] != target:
            raise ValueError('native field observation near-phase target differs from its named bucket')
    if flight['pulse']['mode'] != 'timed':
        raise ValueError('native field observation requires the actual timed pulse, not a discovery prediction')
    start = flight['pulse']['time_us']
    for index, edge in ((4,start),(6,start+flight['pulse']['width_us'])):
        before,after = buckets[index:index+2]
        if (before['time_max_us'] != edge or after['time_min_us'] != edge
                or before['target_time_us'] != edge or after['target_time_us'] != edge):
            raise ValueError('native field observation pulse windows must straddle the actual half-open edges')
    return json.loads(json.dumps(spec,allow_nan=False))


def _instrument_native_field_observation(program: str, specification: dict, context: dict) -> str:
    """Insert bounded read-only capture around this module's actual Lua arithmetic."""
    def insert(original: str, replacement: str) -> None:
        nonlocal program
        if program.count(original) != 1:
            raise ValueError('native field observation template boundary is not unique')
        program = program.replace(original,replacement,1)

    header = dict(schema_version=1,role='single_reflection_applied_field_observation_header',
                  specification=specification,context=context)
    encoded = json.dumps(header,separators=(',',':'),ensure_ascii=True,allow_nan=False)
    if len(encoded.encode()) > 65536:
        raise ValueError('native field observation header exceeds its bounded metadata budget')
    insert('local single_flight_standalone_dynamic_specs=',
           'local single_flight_field_observer=nil\nlocal single_flight_standalone_dynamic_specs=')
    insert('local function single_flight_apply_standalone_dynamic_field(instance,time)',
           'local function single_flight_apply_standalone_dynamic_field(instance,time,observation)')
    insert('  local ex,ey,ez\n  for index,response in ipairs(spec.rf_differential_pas) do',
           '  local ex,ey,ez\n  if observation then\n'
           '    observation.pa_gu={x,y,z}\n'
           '    observation.carrier_native_path=instance.pa.path\n'
           '    observation.carrier_native_field_gu={instance.pa:field_vc(x,y,z)}\n'
           '  end\n  for index,response in ipairs(spec.rf_differential_pas) do')
    anchor = '  local coefficient=single_flight_rf_drives[index].differential_at(time)/spec.rf_reference_voltage_v\n'
    insert(anchor,anchor+'  if observation then observation.rf_members[index]={coefficient_used=coefficient,native_field_gu={ex,ey,ez},native_path=response.path} end\n')
    anchor = "      'pulse-delta standalone field is undefined for '..spec.role)\n"
    insert(anchor,anchor+'    if observation then observation.pulse_active_used=true; observation.pulse_scale_used=spec.pulse_delta_scale or 1; observation.pulse_native_field_gu={ex,ey,ez}; observation.pulse_native_path=spec.pulse_delta_pa.path; observation.pulse_basis="actual_field_vc_used" end\n')
    observer = r'''
local function single_flight_observation_json(value)
  local kind=type(value)
  if kind=='nil' then return 'null' end
  if kind=='boolean' then return value and 'true' or 'false' end
  if kind=='number' then
    assert(value==value and value~=math.huge and value~=-math.huge,'nonfinite applied-field evidence')
    return string.format('%.17g',value)
  end
  if kind=='string' then
    return '"'..value:gsub('[%z\1-\31\\"]',function(c)
      if c=='"' then return '\\"' end
      if c=='\\' then return '\\\\' end
      return string.format('\\u%04x',c:byte())
    end)..'"'
  end
  assert(kind=='table','unsupported applied-field evidence value')
  local fields={}
  if #value>0 then
    for index,item in ipairs(value) do fields[index]=single_flight_observation_json(item) end
    return '['..table.concat(fields,',')..']'
  end
  local keys={};for key in pairs(value) do keys[#keys+1]=key end;table.sort(keys)
  for _,key in ipairs(keys) do fields[#fields+1]=single_flight_observation_json(key)..':'..single_flight_observation_json(value[key]) end
  return '{'..table.concat(fields,',')..'}'
end
local single_flight_observation_spec=@SPEC@
local single_flight_observation_counts={}
local single_flight_observation_rows=0
local single_flight_observation_callbacks=0
local single_flight_observation_bytes=0
local single_flight_observation_stopped=false
local single_flight_observation_deadline_seen=false
local function single_flight_observation_write(event,encoded)
  local line='TRACE: '..event..' '..encoded
  assert(single_flight_observation_bytes+#line+1<=single_flight_observation_spec.max_output_bytes/2,'applied-field evidence phase byte cap exceeded')
  local stream=single_flight_trace_stream or io.stdout
  local ok,err=stream:write(line,'\n');assert(ok,err or 'applied-field evidence write failed')
  local flushed,reason=stream:flush();assert(flushed,reason or 'applied-field evidence flush failed')
  single_flight_observation_bytes=single_flight_observation_bytes+#line+1
end
single_flight_field_observer={}
function single_flight_field_observer.start_run()
  single_flight_observation_rows=0;single_flight_observation_callbacks=0
  single_flight_observation_bytes=0;single_flight_observation_stopped=false
  single_flight_observation_deadline_seen=false
  for _,bucket in ipairs(single_flight_observation_spec.buckets) do single_flight_observation_counts[bucket.bucket_id]=0 end
  single_flight_observation_write('applied_field_observation_header',@HEADER@)
end
function single_flight_field_observer.begin(instance,time)
  -- Constant checks and scalar window scans precede allocation or extra PA queries.
  if single_flight_observation_stopped or single_flight_observation_rows>=16 then return nil end
  if ion_instance~=@DOMAIN_INDEX@ then return nil end
  if time>=single_flight_observation_spec.deadline_us then single_flight_observation_deadline_seen=true;return nil end
  single_flight_observation_callbacks=single_flight_observation_callbacks+1
  local selected=nil
  for _,bucket in ipairs(single_flight_observation_spec.buckets) do
    if time>=bucket.time_min_us and time<bucket.time_max_us and single_flight_observation_counts[bucket.bucket_id]<2 then selected=bucket;break end
  end
  if not selected then return nil end
  local pid=single_flight_canonical_particle_id()
  assert(@ELIGIBLE_IDS@[pid],'unknown applied-field observation source ID')
  return {schema_version=1,role='single_reflection_applied_field_query',basis='efield_adjust_query_only',
    record_seq=single_flight_observation_rows+1,callback_seq=single_flight_observation_callbacks,
    bucket_id=selected.bucket_id,instrument_time_us=time,solver_elapsed_us=ion_time_of_flight,
    particle_id=pid,ion_number=ion_number,instance_index=ion_instance,domain_id=@DOMAIN_ID@,
    world_frame_id=@FRAME@,world_position_mm={ion_px_mm,ion_py_mm,ion_pz_mm},
    grid_spacing_mm={instance.pa.dx_mm,instance.pa.dy_mm,instance.pa.dz_mm},
    instance_scale=instance.scale,instance_rotation_deg={instance.az,instance.el,instance.rt},
    entry_gradient_gu={ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu},rf_members={},
    actual_rf_phase_rad=single_flight_rf_drives[@PHASE_REFERENCE_INDEX@].phase_at(time),
    rf_phase_basis='unwrapped_kernel_phase_at',
    pulse_active_used=false,pulse_basis='not_applied_not_queried'}
end
function single_flight_field_observer.finish(row,result)
  if not row then return end
  row.region_override={replace_all=result and result.replace_all or false}
  if result then
    row.region_override.dvoltsx_gu=result.dvoltsx_gu
    row.region_override.dvoltsy_gu=result.dvoltsy_gu
    row.region_override.dvoltsz_gu=result.dvoltsz_gu
  end
  row.after_region_gradient_gu={ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu}
  row.final_gradient_gu={ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu}
  single_flight_observation_write('applied_field_observation',single_flight_observation_json(row))
  single_flight_observation_rows=single_flight_observation_rows+1
  single_flight_observation_counts[row.bucket_id]=single_flight_observation_counts[row.bucket_id]+1
  if single_flight_observation_rows>=16 then single_flight_observation_stopped='row_cap' end
end
function single_flight_field_observer.summary()
  local missing={}
  for _,bucket in ipairs(single_flight_observation_spec.buckets) do
    if single_flight_observation_counts[bucket.bucket_id]<2 then missing[#missing+1]=bucket.bucket_id end
  end
  single_flight_observation_write('applied_field_observation_summary',single_flight_observation_json({
    schema_version=1,role='single_reflection_applied_field_observation_summary',rows=single_flight_observation_rows,
    counts=single_flight_observation_counts,coverage_complete=#missing==0,
    stopped_by=single_flight_observation_stopped or 'native_end',deadline_seen=single_flight_observation_deadline_seen}))
end
'''
    # Source IDs are keys, not local ion numbers; no observation selects survivors.
    eligible = '{'+','.join(f'[{pid}]=true' for pid in context['eligible_batch_particle_ids'])+'}'
    observer = (observer.replace('@SPEC@',_lua_value(specification)).replace('@HEADER@',_lua_value(encoded))
        .replace('@DOMAIN_INDEX@',str(context['instance_index'])).replace('@ELIGIBLE_IDS@',eligible)
        .replace('@DOMAIN_ID@',_lua_value(specification['domain_id'])).replace('@FRAME@',_lua_value(context['world_frame_id'])))
    reference = next(index for index,row in enumerate(context['rf_sources'],1)
                     if row['instance_id']==specification['source_instance_id'])
    observer = observer.replace('@PHASE_REFERENCE_INDEX@',str(reference))
    # ``@ELIGIBLE_IDS@[pid]`` needs parentheses around a Lua table constructor.
    observer = observer.replace('assert('+eligible+'[pid]', 'assert(('+eligible+')[pid]')
    insert('local function single_flight_trace_checkpoint',observer+'\nlocal function single_flight_trace_checkpoint')
    anchor = '  single_flight_reported={}\nend\nfunction segment.efield_adjust()'
    insert(anchor,'  single_flight_reported={}\n  single_flight_field_observer.start_run()\nend\nfunction segment.efield_adjust()')
    anchor = '  single_flight_apply_standalone_dynamic_field(instance,time)\n'
    insert(anchor,'  local field_observation=single_flight_field_observer.begin(instance,time)\n'
        '  single_flight_apply_standalone_dynamic_field(instance,time,field_observation)\n'
        '  if field_observation then field_observation.after_dynamic_gradient_gu={ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu} end\n')
    anchor = '  end\nend\nfunction segment.instance_adjust()'
    insert(anchor,'  end\n  single_flight_field_observer.finish(field_observation,result)\nend\nfunction segment.instance_adjust()')
    return program+'\nfunction segment.terminate_run() single_flight_field_observer.summary() end\n'


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
                "pulse_delta_scale",
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
        pulse_scale = row.get("pulse_delta_scale", 1.)
        if (isinstance(pulse_scale, bool) or not isinstance(pulse_scale, (int, float))
                or not math.isfinite(pulse_scale) or (pulse_delta is None and "pulse_delta_scale" in row)):
            raise ValueError("pulse scale requires a finite coefficient and its actual pulse member")
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
                "pulse_delta_scale": float(pulse_scale),
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


def project_program_paths(numerical_program: str, native_path_source: str) -> str:
    """Forward-render only the compiler's declared standalone path lookups.

    The input is a numerical Program emitted by this compiler, never historical
    native text with guessed sections removed. Parent transport source is read
    only through its existing frozen file record when validating a saved Program.
    """
    marker = "local function single_flight_exact_basename(value,label)"
    lookups = ("path", "spec.pulse_delta_pa_path")
    if numerical_program.count(marker) != 1 or "local single_flight_native_run_path=" in numerical_program:
        raise ValueError("numerical Program lacks the unique compiler path boundary")
    for expression in lookups:
        original = "simion.pas:open(" + expression + ")"
        if numerical_program.count(original) != 1:
            raise ValueError("numerical Program standalone path lookup differs")
        numerical_program = numerical_program.replace(original, "simion.pas:open(single_flight_native_run_path(" + expression + "))")
    prelude = "local single_flight_native_run_path=(function()\n" + native_path_source + "\nend)()\n"
    return numerical_program.replace(marker, prelude + marker, 1)


def _standalone_dynamic_field_lua(specs: list[dict[str, Any]], *, native_path_projection: bool = True, native_path_source: str | None = None) -> str:
    """Share exact sidecar validation and RF/pulse field composition glue."""
    if native_path_projection:
        source = native_path_source
        if not isinstance(source, str) or not source.strip():
            raise ValueError("native path projection requires its explicit frozen Lua source")
        return project_program_paths(_standalone_dynamic_field_lua(specs, native_path_projection=False), source)
    # Unit scaling uses the original arithmetic, with no redundant multiply.
    # Both execution and numerical controls are rendered by this same template.
    unit_pulse = all(row.get("pulse_delta_scale", 1.) == 1. for row in specs)
    emitted_specs = [dict(row) for row in specs]
    if unit_pulse:
        for row in emitted_specs:
            row.pop("pulse_delta_scale", None)
    standalone_dynamic_specs_lua = _lua_value(emitted_specs)
    pulse_field = ("    ion_dvoltsx_gu=ion_dvoltsx_gu-ex\n"
                   "    ion_dvoltsy_gu=ion_dvoltsy_gu-ey\n"
                   "    ion_dvoltsz_gu=ion_dvoltsz_gu-ez") if unit_pulse else (
                   "    local coefficient=spec.pulse_delta_scale\n"
                   "    ion_dvoltsx_gu=ion_dvoltsx_gu-coefficient*ex\n"
                   "    ion_dvoltsy_gu=ion_dvoltsy_gu-coefficient*ey\n"
                   "    ion_dvoltsz_gu=ion_dvoltsz_gu-coefficient*ez")
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
{pulse_field}
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


def _native_field_analyzer_config(multipoles: dict[str, dict], design: dict, geometry: dict, oatof: dict, *, model_document=None) -> tuple[dict, dict]:
    """Project the actual four-instance field design without legacy geometry."""
    from msplatform.backends.simion.frontend import (
        frontend_electrode_maps, native_frontend_instances, frontend_accelerator_operating_voltages,
    )

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
    g = geometry["accelerator_projection"]
    multipole_ids, accelerator_ids = frontend_electrode_maps(geometry)
    electrodes = dict(accelerator_ids)
    scientific = plan['schema_version'] == 5
    if model_document is not None:
        expected_on = {int(key):value for key,value in model_document['electrical_projection']['accelerator_on'].items()}
        voltage = {role:expected_on[electrodes[f'accelerator_{role}_id']]
                   for role in ('repeller','grid1','intermediate2','grid2')}
    elif scientific:
        expected_on = frontend_accelerator_operating_voltages(oatof, geometry)
        # These are the existing analyzer renderer's names, not scientific IDs.
        voltage = {role: expected_on[electrodes[f'accelerator_{role}_id']]
                   for role in ('repeller', 'grid1', 'intermediate2', 'grid2')}
    else:
        electrical = resolve_accelerator_electrical_design(oatof, variant_id="three_zone_square", schema_version=1)
        voltage = electrical['operating_voltages_v']
        if electrical["ring_z_mm"] != g["ring_z_mm"]:
            raise ValueError("native full flight physical electrical mapping differs")
        plane_keys = dict(repeller="repeller_front_z_mm",grid1="grid1_z_mm",intermediate2="intermediate2_z_mm",grid2="grid2_z_mm")
        if any(electrical["planes_z_mm"][role] != g[key] for role,key in plane_keys.items()):
            raise ValueError("native frontend planes differ from final provider geometry")
        expected_on = {electrodes[f"accelerator_{role}_id"]: voltage[role]
                       for role in ("repeller", "grid1", "intermediate2", "grid2")}
        expected_on.update(zip(electrodes["accelerator_ring_ids"], voltage["rings"], strict=True))
        expected_on[electrodes["grounded_shield_id"]] = 0.
    states = design["accelerator_voltage_states"]
    if (states.get("pulse_voltage_policy_id") != "all_accelerator_electrodes_zero_before_pulse_v1"
            or {int(k):v for k,v in states["operating_voltages_v"].items()} != expected_on
            or {int(k):v for k,v in states["off_voltages_v"].items()} != {key:0. for key in expected_on}):
        raise ValueError("native full flight voltages differ from provider ON and explicit OFF policy")
    points = design["working_points"]
    if not isinstance(points, list) or [p["kind"] for p in points] != kinds:
        raise ValueError("native design requires its ordered selected-scope working fields")
    carrier = {key: 0. for key in expected_on}
    groups = {}
    if model_document is not None:
        carrier.update({int(key):value for key,value in model_document['electrical_projection']['carrier'].items()})
        groups = {instance:{int(key):value for key,value in values.items()}
                  for instance,values in model_document['electrical_projection']['rf_groups'].items()}
    else:
        for instance_id in upstream_ids:
            voltage_projection = scientific_multipole_voltages if scientific else physical_multipole_voltages
            values, groups[instance_id] = voltage_projection(multipoles[instance_id], multipole_ids[instance_id])
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
    physical, coordinate = oatof['geometry_mm'], oatof['coordinate_convention']
    if model_document is not None:
        marker = geometry['downstream_build_contract']['simion_detector_marker']
        expected = {row['role']:row for row in model_document['downstream_geometry']['frontend_geometry']['downstream_pa_instances']}
    else:
        marker = oatof['simion_detector_marker']
        detector_row = next(row for row in geometry["downstream_pa_instances"] if row["role"] == "detector")
        if "physical_detector" not in detector_row:
            raise ValueError("canonical physical detector body is required")
        if detector_row["physical_detector"] != resolve_physical_geometry(oatof)["simion"]["detector_body"]:
            raise ValueError("physical detector differs from the canonical provider")
        provider = derive_simion_geometry(geometry=physical,coordinate=coordinate,
            build=oatof['simion_geometry_build'],marker=marker,source=oatof['particle_source'],
            physical_detector=detector_row["physical_detector"])
        expected = {row['role']:row for row in provider['simion_instances'] if row['role'] != 'accelerator'}
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
    detector_body = downstream["detector"].get("physical_detector")
    if detector_body is None:
        raise ValueError("canonical physical detector body is required")
    analyzer_geometry["detector_physical_thickness_mm"] = detector_body["height_mm"]
    analyzer_geometry["detector_physical_back_cells"] = downstream["detector"]["physical_back_cells"]
    analyzer_geometry["detector_physical_front_cells"] = downstream["detector"]["physical_front_cells"]
    config = dict(accelerator_topology_id="three_zone_frontend_contract_derived_v1",
        instance_roles=dict(flight_tube=1,reflectron=2,accelerator=3,detector=4),
        instance_filenames=dict(flight_tube="flight_tube_ground.pa0",reflectron="reflectron.pa0",
                                accelerator="accelerator.pa0",detector="detector_ground.pa0"),
        provider_placements=placements,geometry=analyzer_geometry,
        field_modes={key:False for key in ("ideal_accelerator","ideal_accelerator_axial","ideal_drift_axial",
            "ideal_reflectron_stage1","ideal_reflectron_stage1_axial","ideal_reflectron_stage2","ideal_reflectron_stage2_axial")},
        voltages=dict(repeller_v=voltage["repeller"],grid1_v=voltage["grid1"],intermediate2_v=voltage["intermediate2"],
            exit_v=voltage["grid2"],mid_v=(geometry["downstream_build_contract"] if model_document is not None else oatof)["electrodes_V"]["midgrid"],backplate_v=(geometry["downstream_build_contract"] if model_document is not None else oatof)["electrodes_V"]["backplate"]),
        accelerator_ring_count=len(g["ring_z_mm"]),
        electrode_ids=dict(repeller=electrodes["accelerator_repeller_id"],grid1=electrodes["accelerator_grid1_id"],
            intermediate2=electrodes["accelerator_intermediate2_id"],grid2=electrodes["accelerator_grid2_id"],
            rings=electrodes["accelerator_ring_ids"]),
        detector=dict(tstep_enabled=True,capture_arm_distance_mm=marker["capture_arm_distance_mm"],
            capture_depth_mm=marker["capture_depth_mm"],marker_absorber_thickness_mm=marker["absorber_thickness_mm"]),
        diagnostics=dict(_SUCCESSOR_DIAGNOSTICS))
    return frontend, config


def validate_program_trajectory_quality(value: Any) -> int:
    """Validate the documented reserved-variable range, not the separate CLI option."""
    if type(value) is not int or not -500 <= value <= 500:
        raise ValueError("SIMION Program trajectory_quality must be an integer within -500..500")
    return value


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
    validate_program_trajectory_quality(flight["trajectory_quality"])
    if requires_rf:
        value = flight["rf_steps_per_period"]
        if type(value) is not int or value < 1:
            raise ValueError("native flight rf_steps_per_period must be a positive integer")
    return dict(flight)


def _bound_tracking_model(prepared_model, multipoles, oatof, geometry, design, flight):
    """Verify the sole model compiler's complete geometry/mapping/drive snapshot."""
    import hashlib
    from .model import require_prepared_model, model_geometry, compile_prepared_model
    from .frontend import native_frontend_instances
    from .fields import prepare_field_design
    from copy import deepcopy

    document = require_prepared_model(prepared_model)
    compiled = model_geometry(prepared_model)
    expected = compile_prepared_model(compiled, document['components_resolved'],
        drive=document['drive'], physics=document['physics'])
    def semantic_projection(value):
        value = deepcopy(value)
        value.pop('model_identity_sha256')
        # Persisted JSON sorts group object keys; rebuilding may enumerate those
        # groups differently. The explicit scientific/native target rows are
        # compared exactly by identity, not their incidental list order.
        keys = [(row['instance_id'],row['electrode_group_id']) for row in value['native_drive_rows']]
        if len(keys) != len(set(keys)):
            raise ValueError('tracking model duplicate scientific rows are not compiler-bound')
        value['native_drive_rows'] = sorted(value['native_drive_rows'],
            key=lambda row:(row['instance_id'],row['electrode_group_id']))
        return value
    if semantic_projection(expected.document) != semantic_projection(document):
        raise ValueError('tracking model derived drive or mapping is not compiler-bound')
    actual_geometry = model_geometry(prepared_model, downstream_drive=True)
    upstream, tof = native_frontend_instances(geometry['composition_plan'])
    if (geometry != actual_geometry.frontend_geometry or oatof != document['components_resolved'][tof]
            or multipoles != {key:document['components_resolved'][key] for key in upstream}):
        raise ValueError('tracking providers or compiled geometry differ from bound model')
    if dict(flight['pulse']) != document['drive']['pulse']:
        raise ValueError('tracking pulse differs from bound model drive')
    numerics = {row['domain_id']:{'refine_convergence_v':row['refine_convergence_v']} for row in design['domains']}
    expected_design = prepare_field_design(multipoles,oatof,geometry,
        variant_id=geometry['composition_plan']['components'][tof]['variant_id'],
        pulse_voltage_policy_id=document['physics']['pulse_voltage_policy_id'],
        boundary_policy=document['physics']['boundary_policy'], frontend_domains=numerics,
        rf_reference_voltage_v=design.get('rf_reference_voltage_v'), flight=flight,
        electrical_projection=document['electrical_projection'])
    checked = deepcopy(design)
    for domain in checked['domains']:
        digest = domain.pop('gem_sha256', None)
        if digest is not None and (not isinstance(digest, str) or re.fullmatch(r'[a-fA-F0-9]{64}', digest) is None
                or digest.lower() != hashlib.sha256(actual_geometry.frontend_gems[domain['domain_id']].encode('utf-8')).hexdigest()):
            raise ValueError('tracking field GEM differs from bound model')
    # A FieldBundle is persisted JSON: native voltage table integer keys are
    # transported as strings. Compare that exact finite JSON meaning while
    # retaining array order, complete key coverage and every voltage value.
    if json.loads(json.dumps(checked,allow_nan=False)) != json.loads(json.dumps(expected_design,allow_nan=False)):
        raise ValueError('tracking field design differs from bound model drive')
    return document


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
    native_path_projection: bool = True,
    native_path_source: str | None = None,
    field_observation: dict | None = None,
    plane_observations: list[dict] | None = None,
    consumed_plane_events: list[dict] | None = None,
    original_birth_times_us: list[float] | None = None,
    absolute_deadlines_us: list[float] | None = None,
    propagation_stop: dict | None = None,
    prepared_model=None,
) -> str:
    """Assemble native full-flight callbacks from frozen source and field contracts."""
    from msplatform.backends.simion.frontend import frontend_electrode_maps

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
    model_document = (_bound_tracking_model(prepared_model,multipoles_by_instance,oatof,frontend_geometry,native_design,flight)
                      if prepared_model is not None else None)
    frontend, native_analyzer_config = _native_field_analyzer_config(multipoles_by_instance, native_design, frontend_geometry, oatof,
                                                                  model_document=model_document)
    if not birth_times_us or any(isinstance(item, bool) or not isinstance(item, (int, float))
            or not math.isfinite(item) for item in birth_times_us):
        raise ValueError("canonical instrument clock requires finite absolute birth times")
    if any(
            not math.isfinite(birth + flight["maximum_flight_us"]) for birth in birth_times_us):
        raise ValueError("native flight age horizon is non-finite")
    if particle_ids is None:
        particle_ids = list(range(1, len(birth_times_us) + 1))
    validate_native_particle_ids(particle_ids)
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
        if model_document is not None:
            bound = next(row for row in model_document['drive']['groups'][instance].values() if row['kind']=='rf')
            drive = dict(waveform=bound['waveform'],frequency_Hz=bound['frequency_hz'],phase_rad=bound['phase_rad'],
                         rf_amplitude_V_zero_to_peak_per_group=bound['rf_amplitude_v'])
        else:
            drive = multipoles_by_instance[instance]['drive']
        if drive["waveform"] not in {"sine", "cosine"}:
            raise ValueError("single-flight Program RF waveform must be sine or cosine")
        rf_configs.append(dict(waveform=drive["waveform"], frequency_hz=drive["frequency_Hz"],
            phase_rad=drive["phase_rad"], rf_amplitude_v=drive["rf_amplitude_V_zero_to_peak_per_group"],
            rf_scale=1., rf_steps_per_period=rf_steps_per_period))
    observation_context = None
    if field_observation is not None:
        if (set(field_observation) != {'specification','evidence_context'}
                or frontend_geometry['composition_plan']['schema_version'] != 5):
            raise ValueError('native field observation requires plan5 and its explicit evidence context')
        evidence = field_observation['evidence_context']
        spec = validate_native_field_observation(field_observation['specification'],
            particle_ids=evidence['mother_particle_ids'],source_instances=tuple(rf_instances),
            domain_ids=list(frontend_geometry['numerical_domains']),clock_epoch_id=evidence['clock_epoch_id'],flight=flight)
        if (spec['eligible_batch_anchor_particle_id'] not in particle_ids
                or not set(particle_ids) <= set(evidence['mother_particle_ids'])):
            raise ValueError('native field observation belongs only to the unique anchor batch')
        observation_context = dict(evidence,eligible_batch_particle_ids=particle_ids,
            instance_index=3 if spec['domain_id']=='parent' else 5,
            world_frame_id=frontend_geometry['native_frame_id'],
            gradient_unit='V/gu_positive_grad_V',basis_unit='field_vc_native_E_opposite_grad_V',
            query_semantics='efield_adjust_query_only_not_accepted_particle_state',
            phase_row_cap=16,phase_byte_cap=524288,maximum_recorded_phases=2,
            rf_sources=[dict(instance_id=instance,drive=(model_document['drive']['groups'][instance] if model_document is not None else multipoles_by_instance[instance]['drive']),
                electrode_group_native_ids=frontend_geometry['electrode_bindings'][instance]) for instance in rf_instances])
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
        "accelerator_overlays": [
            {"role": str(item["role"]), "instance_index": int(item["instance_index"]), "filename": str(item["filename"])}
            for item in overlay_specs
        ],
    }
    formal_iob_config_lua = _lua_value(formal_iob_config)
    if build_metadata is not None:
        if model_document is not None:
            build_metadata["prepared_model_identity_sha256"] = model_document["model_identity_sha256"]
            build_metadata["drive_authority"] = "compiler_bound_prepared_model"
        build_metadata["instance_roles"] = dict(formal_iob_config["instance_roles"])
        build_metadata["physical_frontend_topology_id"] = native_analyzer_config["accelerator_topology_id"]
        build_metadata["provider_placements"] = analyzer_config["provider_placements"]
        pieces = (scientific_multipole_rod_pieces if frontend_geometry['composition_plan']['schema_version'] == 5
                  else multipole_rod_pieces)
        build_metadata["physical_rod_piece_count"] = sum(len(pieces(provider)) for provider in multipoles_by_instance.values())
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
        if observation_context is not None:
            build_metadata['native_field_observation'] = dict(specification=spec,context=observation_context)
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
    native_overlay_check_lua = ("""      assert(oi.x==overlay.origin_mm.x and oi.y==overlay.origin_mm.y and oi.z==overlay.origin_mm.z and
        oi.az==0 and oi.el==0 and oi.rt==0 and oi.scale==1,'native refinement placement differs')
      for _,axis in ipairs({'x','y','z'}) do
        assert(oi.pa['n'..axis]==overlay.dimensions['n'..axis] and
          oi.pa['d'..axis..'_mm']==overlay.cell_mm_xyz[axis],'native refinement grid differs')
      end
""")
    overlay_specs_lua = _lua_value(overlay_specs)
    standalone_dynamic_field_lua = _standalone_dynamic_field_lua(standalone_dynamic_specs, native_path_projection=native_path_projection, native_path_source=native_path_source)
    active_field_instance_indices_lua = _lua_value(active_field_instance_indices)
    time_origin_table = "{" + ",".join(
        f"[{index}]={_lua_number(value)}"
        for index, value in enumerate(birth_times_us, start=1)
    ) + "}"
    if original_birth_times_us is not None:
        if (len(original_birth_times_us) != len(birth_times_us) or
                any(type(b) not in (int,float) or not math.isfinite(b) or b > start
                    for b,start in zip(original_birth_times_us,birth_times_us,strict=True))):
            raise ValueError("original births must be finite, complete and not after segment arrivals")
    if absolute_deadlines_us is not None:
        if original_birth_times_us is None:
            raise ValueError("absolute deadlines require explicit original birth facts")
        if (len(absolute_deadlines_us) != len(birth_times_us) or
                any(type(end) not in (int,float) or not math.isfinite(end) or end <= start
                    for end,start in zip(absolute_deadlines_us,birth_times_us,strict=True))):
            raise ValueError("absolute deadline must follow each arrival; already-complete particles cannot Fly")
    particle_id_table = "{" + ",".join(
        f"[{index}]={value}" for index, value in enumerate(particle_ids, start=1)
    ) + "}"
    source_velocity_table = _lua_value(initial_velocities_mm_per_us)
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
    if absolute_deadlines_us is not None:
        native_step_limits_lua = native_step_limits_lua.replace(
            _lua_number(flight['maximum_flight_us']) + "-ion_time_of_flight",
            "single_flight_absolute_deadline_us[single_flight_source_row_index()]-single_flight_instrument_time_us()")
        native_age_limit_lua = native_age_limit_lua.replace(
            "ion_time_of_flight>=" + _lua_number(flight['maximum_flight_us']),
            "time>=single_flight_absolute_deadline_us[single_flight_source_row_index()]")
    if original_birth_times_us is not None:
        native_age_limit_lua = native_age_limit_lua.replace(
            "single_flight_canonical_particle_id(),ion_time_of_flight))",
            "single_flight_canonical_particle_id(),time-single_flight_original_birth_us[single_flight_source_row_index()]))")
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
{three_zone_adjustables}adjustable V_mid={_lua_number(analyzer_config['voltages']['mid_v'])}
adjustable V_backplate={_lua_number(analyzer_config['voltages']['backplate_v'])}
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
local single_flight_continuous_rf_next_sample={{}}
{rf_grid_lua}
  local single_flight_overlay_enabled={1 if overlay_specs else 0}
  local single_flight_overlays={overlay_specs_lua}
local single_flight_active_field_instances={active_field_instance_indices_lua}
local single_flight_domain_split_enabled={(0)}
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
local function single_flight_instance_state(instance)
  return {{filename=instance.filename,nx=instance.pa.nx,ny=instance.pa.ny,
    nz=instance.pa.nz,dx_mm=instance.pa.dx_mm,dy_mm=instance.pa.dy_mm,
    dz_mm=instance.pa.dz_mm,scale=instance.scale}}
end
local function single_flight_workbench_state()
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
  single_flight_analyzer.initialize_workbench(
    single_flight_workbench_state())
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
  -- The detector PA contains the physical body at every flight phase.
  -- Observation eligibility is decided by the analyzer, not PA selection.
  local overlay=single_flight_overlay_for_instance(ion_instance)
  if overlay==nil then return end
  local b=overlay.bounds_mm
  local detector=simion.wb.instances[single_flight_detector_instance_index]
  if detector:inside_wc(ion_px_mm,ion_py_mm,ion_pz_mm) or
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
  single_flight_require_analyzer_particle(ion_time_of_flight)
  single_flight_particle_state[ion_number]={{frontend=single_flight_frontend.initialize_particle(ion_pz_mm),
    previous={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}}}
  single_flight_previous[ion_number]={{t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,
    vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}}
  single_flight_reported[ion_number]={{}}
  single_flight_continuous_rf_next_sample[ion_number]=1
  single_flight_write_trace(string.format('TRACE: source_release ion=%d particle_id=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g simion_native_kinetic_energy_eV=%.17g source_instance=%d',ion_number,single_flight_canonical_particle_id(),time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_ke,ion_instance))
{native_observation_initialize_lua}end
function segment.tstep_adjust()
{native_step_limits_lua}{native_observation_step_lua}  local analyzer_dt=nil
  analyzer_dt=single_flight_analyzer.tstep_adjust{{x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
    vx_mm_per_us=ion_vx_mm,vy_mm_per_us=ion_vy_mm,vz_mm_per_us=ion_vz_mm,
    detector_cell_dx_mm=simion.wb.instances[single_flight_detector_instance_index].pa.dx_mm}}
  if analyzer_dt and ion_time_step>analyzer_dt then ion_time_step=analyzer_dt end
  local time=single_flight_instrument_time_us()
{observation_step_lua}  -- A continuous comparator must integrate the same pre-pulse RF waveform on
  -- the same absolute native grid as its handoff producer.  Merely capping the
  -- maximum step permits SIMION's adaptive trajectory step to drift between
  -- RF nodes and changes which ions reach the aperture.  Persist the next
  -- discrete index per ion; derive it from floating point time only once at
  -- release, then advance monotonically at exact landings.
  if #single_flight_rf_drives>0 and
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
  single_flight_require_analyzer_particle(ion_time_of_flight)
  local state=single_flight_require_particle_state()
  local current={{time_us=time,position_z_mm=ion_pz_mm,velocity_z_mm_per_us=ion_vz_mm}}
  single_flight_frontend.observe_step(state.previous,current,state.frontend)
  state.previous=current
  local p=single_flight_previous[ion_number]
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
    if original_birth_times_us is not None:
        declarations = "local single_flight_original_birth_us=" + _lua_value(original_birth_times_us) + "\n"
        if absolute_deadlines_us is not None:
            declarations += "local single_flight_absolute_deadline_us=" + _lua_value(absolute_deadlines_us) + "\n"
        marker = "local single_flight_particle_state={}"
        if program.count(marker) != 1:
            raise ValueError("modern source clock insertion point differs")
        program = program.replace(marker, declarations + marker, 1)
        if build_metadata is not None:
            build_metadata['source_clock'] = dict(original_birth_times_us=list(original_birth_times_us),
                absolute_deadlines_us=list(absolute_deadlines_us) if absolute_deadlines_us is not None else None,
                native_clock='per_row_start_origin_plus_native_elapsed_once')
    if plane_observations is not None:
        program = _instrument_plane_observations(program, plane_observations, frontend_geometry,
                consumed_plane_events=consumed_plane_events, particle_ids=particle_ids, start_times_us=birth_times_us, propagation_stop=propagation_stop)
        if build_metadata is not None:
            build_metadata["plane_observations"] = plane_observations
            build_metadata["consumed_plane_events"] = consumed_plane_events or []
    if propagation_stop is not None:
        if (plane_observations is None or original_birth_times_us is None or absolute_deadlines_us is None
                or consumed_plane_events or original_birth_times_us != birth_times_us):
            raise ValueError("cut stop requires modern birth clock/deadline and declared plane, without consumed restart")
        if build_metadata is not None:
            build_metadata["propagation_stop"] = dict(propagation_stop)
            build_metadata["cut_stop_mechanism"] = dict(schema_version=2,
                wire="HANDOFF_CUT_STOP_V2", endpoint_wire="HANDOFF_ACCEPTED_ENDPOINT_V1",
                observed_callback_boundary="bracket_end", native_termination_boundary="bracket_start",
                qualification="recorded_callback_and_native_boundaries_not_exact_plane_landing")
    if observation_context is not None:
        program = _instrument_native_field_observation(program,spec,observation_context)
    if program.count("simion.workbench_program()") != 1:
        raise ValueError("combined single-flight Program must declare one workbench")
    for callback in _SUCCESSOR_CALLBACKS:
        count = len(re.findall(rf"function\s+segment\.{callback}\s*\(", program))
        if count != 1:
            raise ValueError(f"combined single-flight Program callback {callback} count is {count}")
    return program


def _instrument_plane_observations(program: str, definitions: list[dict], geometry: dict, *,
                                   consumed_plane_events=None, particle_ids=None, start_times_us=None, propagation_stop=None) -> str:
    """Add a versioned passive accepted-step wire; never change native motion.

    Each direction has its own occurrence sequence. Every recorded crossing is
    retained; reaching a declared output cap emits an explicit incomplete fact.
    Legacy TRACE bytes and behavior remain unchanged when this is not requested.
    """
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("plane observations require a nonempty explicit definition list")
    plan = geometry["composition_plan"]
    poses = {row["instance_id"]: RigidTransform.from_contract(row["transform"]) for row in plan["recipe"]["instances"]}
    declarations, ids, planes = [], set(), {}
    for spec in definitions:
        if (not isinstance(spec, dict) or set(spec) != {"schema_version", "observation_id", "source_instance_id", "port_id", "max_records"}
                or type(spec["schema_version"]) is not int or spec["schema_version"] != 1
                or not isinstance(spec["observation_id"], str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", spec["observation_id"])
                or spec["observation_id"] in ids or type(spec["max_records"]) is not int or spec["max_records"] <= 0):
            raise ValueError("plane observation definition/version/identity/cap differs")
        instance = spec["source_instance_id"]
        if instance not in plan["scope"]["instance_ids"] or instance not in poses:
            raise ValueError("plane observation source is outside the selected assembly")
        component = plan["components"][instance]
        port = component["ports"].get(spec["port_id"])
        if not isinstance(port, dict):
            raise ValueError("plane observation requires an actual provider port")
        pose = poses[instance]
        plane = pose.transform_plane(PlaneSurface(component["local_frame_id"], tuple(port["center_mm"]), tuple(port["outward_normal"])))
        if plane.frame_id != geometry["native_frame_id"]:
            raise ValueError("plane observation requires the actual native world frame")
        ids.add(spec["observation_id"])
        planes[spec["observation_id"]] = plane
        declarations.append(dict(observation_id=spec["observation_id"], center=list(plane.center_mm),
                                 normal=list(plane.normal), max_records=spec["max_records"]))
    validate_propagation_stop(propagation_stop, definitions)
    consumed = consumed_plane_events or []
    if not isinstance(consumed, list):
        raise ValueError("consumed plane events must be an explicit list")
    starts = dict(zip(particle_ids or [], start_times_us or [], strict=True))
    seen = set()
    for event in consumed:
        if (set(event) != {"particle_id", "observation_id", "direction", "occurrence", "instrument_time_us", "position_mm"}
                or event["particle_id"] not in starts or event["particle_id"] in seen
                or event["observation_id"] not in planes or event["direction"] not in {"outward", "inward"}
                or type(event["occurrence"]) is not int or event["occurrence"] < 1
                or event["instrument_time_us"] != starts[event["particle_id"]]
                or not isinstance(event["position_mm"], list) or len(event["position_mm"]) != 3
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in event["position_mm"])):
            raise ValueError("consumed plane event does not match the native source/start/observation")
        plane = planes[event["observation_id"]]
        position = event["position_mm"]
        distance = sum((v-c)*n for v,c,n in zip(position,plane.center_mm,plane.normal,strict=True))
        # 48 basic rounding operations conservatively cover both signed-distance
        # evaluations, interpolation fraction/position and this plane residual.
        # Opposite-sign bracketing distances avoid a cancelling denominator.
        # This is a binary64 transport/operation bound, never a physical epsilon.
        u = 2.**-53
        gamma = (48*u)/(1-48*u)
        scale = sum((abs(v)+abs(c))*abs(n) for v,c,n in zip(position,plane.center_mm,plane.normal,strict=True))
        if abs(distance) > gamma*scale:
            raise ValueError("consumed event is not on its declared provider plane within binary64 rounding")
        seen.add(event["particle_id"])
    declaration = "local single_flight_plane_observations=" + _lua_value(declarations) + "\nlocal single_flight_plane_counts={}\nlocal single_flight_plane_totals={}\n"
    declaration += "local single_flight_plane_consumed=" + _lua_value(consumed) + "\nlocal single_flight_plane_pending={}\n"
    declaration += r'''local function single_flight_plane_initialize(native_id,pid,time,x,y,z)
  for _,event in ipairs(single_flight_plane_consumed) do
    if event.particle_id==pid then
      local pos=event.position_mm
      assert(time==event.instrument_time_us and x==pos[1] and y==pos[2] and z==pos[3],
        'restart initial state differs from the consumed plane event')
      local key=event.observation_id..':'..native_id
      single_flight_plane_counts[key..':'..event.direction]=event.occurrence
      single_flight_plane_pending[key]={t=time,x=x,y=y,z=z,direction=event.direction,occurrence=event.occurrence}
    end
  end
end
'''
    marker = "local single_flight_reported={}"
    if program.count(marker) != 1:
        raise ValueError("plane observation declaration insertion point differs")
    program = program.replace(marker, declaration + marker, 1)
    if consumed:
        initialize_marker = "  single_flight_reported[ion_number]={}"
        if program.count(initialize_marker) != 1:
            raise ValueError("consumed plane initialization insertion point differs")
        program = program.replace(initialize_marker, initialize_marker + "\n  single_flight_plane_initialize(ion_number,single_flight_canonical_particle_id(),time,ion_px_mm,ion_py_mm,ion_pz_mm)", 1)

    body = r'''  if p and time>p.t then
    for _,plane in ipairs(single_flight_plane_observations) do
      local c,n=plane.center,plane.normal
      local d0=(p.x-c[1])*n[1]+(p.y-c[2])*n[2]+(p.z-c[3])*n[3]
      local d1=(ion_px_mm-c[1])*n[1]+(ion_py_mm-c[2])*n[2]+(ion_pz_mm-c[3])*n[3]
      local vn=ion_vx_mm*n[1]+ion_vy_mm*n[2]+ion_vz_mm*n[3]
      local direction=nil
      if d0<0 and d1>=0 and vn>0 then direction='outward'
      elseif d0>0 and d1<=0 and vn<0 then direction='inward' end
      local pending_key=plane.observation_id..':'..ion_number
      local pending=single_flight_plane_pending[pending_key]
      if pending then
        assert(p.t==pending.t and p.x==pending.x and p.y==pending.y and p.z==pending.z,
          'first accepted step does not start at the consumed boundary initialization')
        if direction==pending.direction then direction=nil
        elseif direction==nil and ((pending.direction=='outward' and d1<0 and vn<0) or
                                   (pending.direction=='inward' and d1>0 and vn>0)) then
          -- The boundary itself is known, but a first-step turnaround root is
          -- not localized. Preserve its real endpoints, never invent an inward6D state.
          local total=single_flight_plane_totals[plane.observation_id] or 0
          if total<plane.max_records then
            single_flight_plane_totals[plane.observation_id]=total+1
            single_flight_write_trace(string.format('PLANE_BOUNDARY_RETURN_V1: observation_id=%s ion=%d particle_id=%d consumed_direction=%s consumed_occurrence=%d interval_start_us=%.17g interval_end_us=%.17g step_start_x_mm=%.17g step_start_y_mm=%.17g step_start_z_mm=%.17g step_end_x_mm=%.17g step_end_y_mm=%.17g step_end_z_mm=%.17g step_start_vx_mm_per_us=%.17g step_start_vy_mm_per_us=%.17g step_start_vz_mm_per_us=%.17g step_end_vx_mm_per_us=%.17g step_end_vy_mm_per_us=%.17g step_end_vz_mm_per_us=%.17g method=unlocalized_consumed_boundary_return',
              plane.observation_id,ion_number,single_flight_canonical_particle_id(),pending.direction,pending.occurrence,p.t,time,
              p.x,p.y,p.z,ion_px_mm,ion_py_mm,ion_pz_mm,p.vx,p.vy,p.vz,ion_vx_mm,ion_vy_mm,ion_vz_mm))
          elseif total==plane.max_records then
            single_flight_plane_totals[plane.observation_id]=total+1
            single_flight_write_trace('PLANE_OBSERVATION_INCOMPLETE_V1: observation_id='..plane.observation_id..' reason=declared_record_cap')
          end
        end
        single_flight_plane_pending[pending_key]=nil
      end
      if direction then
        local key=plane.observation_id..':'..ion_number..':'..direction
        local occurrence=(single_flight_plane_counts[key] or 0)+1
        single_flight_plane_counts[key]=occurrence
        local total=single_flight_plane_totals[plane.observation_id] or 0
        if total<plane.max_records then
          local f=-d0/(d1-d0)
          single_flight_plane_totals[plane.observation_id]=total+1
          single_flight_write_trace(string.format('PLANE_OBSERVATION_V1: observation_id=%s ion=%d particle_id=%d direction=%s occurrence=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g step_start_instrument_time_us=%.17g step_end_instrument_time_us=%.17g signed_distance_before_mm=%.17g signed_distance_after_mm=%.17g step_start_x_mm=%.17g step_start_y_mm=%.17g step_start_z_mm=%.17g step_end_x_mm=%.17g step_end_y_mm=%.17g step_end_z_mm=%.17g step_start_vx_mm_per_us=%.17g step_start_vy_mm_per_us=%.17g step_start_vz_mm_per_us=%.17g step_end_vx_mm_per_us=%.17g step_end_vy_mm_per_us=%.17g step_end_vz_mm_per_us=%.17g method=accepted_step_linear_interpolation',
            plane.observation_id,ion_number,single_flight_canonical_particle_id(),direction,occurrence,
            p.t+f*(time-p.t),p.x+f*(ion_px_mm-p.x),p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),
            p.vx+f*(ion_vx_mm-p.vx),p.vy+f*(ion_vy_mm-p.vy),p.vz+f*(ion_vz_mm-p.vz),p.t,time,d0,d1,p.x,p.y,p.z,ion_px_mm,ion_py_mm,ion_pz_mm,p.vx,p.vy,p.vz,ion_vx_mm,ion_vy_mm,ion_vz_mm))
        elseif total==plane.max_records then
          single_flight_plane_totals[plane.observation_id]=total+1
          single_flight_write_trace('PLANE_OBSERVATION_INCOMPLETE_V1: observation_id='..plane.observation_id..' reason=declared_record_cap')
        end
      end
    end
  end
'''
    marker = "  local reported=single_flight_reported[ion_number] or {}"
    if program.count(marker) != 1:
        raise ValueError("plane observation callback insertion point differs")
    program = program.replace(marker, body + marker, 1)
    if propagation_stop is not None:
        program = _instrument_cut_stop(program, propagation_stop)
    return program


def validate_propagation_stop(policy, definitions):
    """Validate an optional first-outward segmented-upstream endpoint stop."""
    if policy is None:
        return
    if (not isinstance(policy, dict) or set(policy) != {"schema_version", "scope", "observation_id", "direction", "occurrence"}
            or type(policy["schema_version"]) is not int or policy["schema_version"] != 1
            or policy["scope"] != "segmented_upstream" or policy["direction"] != "outward"
            or type(policy["occurrence"]) is not int or policy["occurrence"] != 1
            or not definitions or sum(row["observation_id"] == policy["observation_id"] for row in definitions) != 1):
        raise ValueError("cut stop requires one declared first-outward segmented-upstream observation")


def _instrument_cut_stop(program, policy):
    """Record the accepted END and genuine native terminate boundary separately.

    SIMION's documented other_actions ion_splat=1 mechanism does not land on
    the plane. Raw bracket/interpolated state and actual endpoint stay distinct.
    Existing physical/analyzer splats take precedence. No native state is moved.
    V2 does not claim terminate reserved variables equal the other_actions END.
    """
    declaration = "local single_flight_cut_policy=" + _lua_value(policy) + "\nlocal single_flight_cut_candidates={}\nlocal single_flight_cut_stopped={}\n"
    marker = "local single_flight_reported={}"
    program = program.replace(marker, declaration + marker, 1)
    marker = "          local f=-d0/(d1-d0)"
    if program.count(marker) != 1:
        raise ValueError("cut stop event insertion point differs")
    program = program.replace(marker, marker + r"""
          if plane.observation_id==single_flight_cut_policy.observation_id and direction=='outward' and occurrence==1 then
            single_flight_cut_candidates[ion_number]={event_time=p.t+f*(time-p.t),endpoint_time=time}
          end""", 1)
    marker = "  if result.splat"
    index = program.find(marker, program.index("function segment.other_actions()"))
    end = program.find("\n", index)
    if index < 0 or end < 0:
        raise ValueError("cut stop native decision insertion point differs")
    program = program[:end] + r"""
  local cut=single_flight_cut_candidates[ion_number]
  single_flight_cut_candidates[ion_number]=nil
  if cut and ion_splat==0 and cut.endpoint_time==time and
      cut.event_time<=single_flight_absolute_deadline_us[single_flight_source_row_index()] then
    single_flight_cut_stopped[ion_number]=cut
    -- Genuine current other_actions state, before requesting the native stop.
    single_flight_write_trace(string.format('HANDOFF_ACCEPTED_ENDPOINT_V1: observation_id=%s ion=%d particle_id=%d direction=outward occurrence=1 event_instrument_time_us=%.17g endpoint_instrument_time_us=%.17g instance=%d x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g method=other_actions_accepted_step_end raw_ion_splat=%d time_step_us=%.17g',
      single_flight_cut_policy.observation_id,ion_number,single_flight_canonical_particle_id(),cut.event_time,time,ion_instance,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_splat,ion_time_step))
    ion_splat=1
    return
  end""" + program[end:]
    marker = "function segment.terminate()\n"
    if program.count(marker) != 1:
        raise ValueError("cut stop terminate insertion point differs")
    program = program.replace(marker, marker + r"""  local cut=single_flight_cut_stopped[ion_number]
  if cut then
    local time=single_flight_instrument_time_us()
    single_flight_write_trace(string.format('TRACE: handoff_terminal_raw ion=%d instance=%d instrument_time_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g',
      ion_number,ion_instance,time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))
    single_flight_write_trace(string.format('HANDOFF_CUT_STOP_V2: observation_id=%s ion=%d particle_id=%d direction=outward occurrence=1 event_instrument_time_us=%.17g endpoint_instrument_time_us=%.17g instance=%d x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g method=accepted_step_dual_boundary_stop',
      single_flight_cut_policy.observation_id,ion_number,single_flight_canonical_particle_id(),cut.event_time,time,ion_instance,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm))
    return
  end
""", 1)
    return program
