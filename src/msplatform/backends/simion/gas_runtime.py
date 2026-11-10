"""Compile explicit static gas to Lua 5.1; explicitly materialize when requested.

Grid fields retain the existing dual-cone .9g values/.17g geometry and 8192
child-prototype chunks. Canonical domains use their explicit endpoint ownership;
the old uniform-control 1e-6 mm envelope is not a new default. This compiler has
the existing Program joint input. Pure compilation performs no I/O; the explicit
materializer writes caller-owned paths/metadata. Vendor callbacks, RNG, stepping
and execution ownership do not live here.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from msplatform.contracts.gas import BoxDomain, CylindricalDomain, GasState, UnboundedDomain
from msplatform.contracts.particle_physics import BOLTZMANN_CONSTANT_J_K
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.gas.field import GasField
from msplatform.io.file_identity import file_sha256
from .source import lua_value


def _text(value: str) -> str:
    """Use Lua 5.1 long strings for exact UTF-8 frame/region/source identifiers."""
    separator = ""
    while "]" + separator + "]" in value:
        separator += "="
    return "[" + separator + "[" + value + "]" + separator + "]"


def _domain(domain) -> str:
    if isinstance(domain, UnboundedDomain):
        return "{kind='unbounded'}"
    if isinstance(domain, CylindricalDomain):
        return lua_value(dict(kind="cylinder", lo=domain.minimum_z_mm,
                              hi=domain.maximum_z_mm, radius=domain.maximum_radius_mm,
                              inner_radius=domain.minimum_radius_mm))
    if not isinstance(domain, BoxDomain):
        raise ValueError("unsupported gas domain")
    return lua_value(dict(kind="box", lo=list(domain.minimum_mm), hi=list(domain.maximum_mm),
                          lower=list(domain.lower_closed), upper=list(domain.upper_closed)))


def _state(state: GasState) -> str:
    return lua_value(dict(status=state.status, pressure_pa=state.pressure_pa,
        temperature_k=state.temperature_k,
        bulk_velocity_m_s=None if state.bulk_velocity_m_s is None else list(state.bulk_velocity_m_s)))


def _chunks(values) -> str:
    # Preserve the recorded 8192-entry constant-table and z-major/r-minor layout.
    chunks = []
    for start in range(0, len(values), 8192):
        body = ",".join("false" if value is None else format(value, ".9g")
                        for value in values[start:start+8192])
        chunks.append("(function() return {" + body + "} end)()")
    return "{" + ",\n".join(chunks) + "}"


def compile_gas_runtime(field: GasField, *, placement: RigidTransform | None = None) -> str:
    """Return UTF-8 Lua source: sample(x_mm,y_mm,z_mm,frame_id) -> joint state.

    A placement maps the field frame to the query frame, using canonical inverse
    Rr+t and Rv once. Static queries have no time/particle key. The returned module
    also exposes an internal numeric SDS projection of the same validated query.
    Both paths retain every per-query finite/EOS check and do not cache samples.
    The module carries source semantics and the legacy-grid geometry-support limitation;
    it does not verify an external published source or mutate/write any file.
    """
    if not isinstance(field, GasField):
        raise ValueError("an explicitly prepared GasField is required")
    spec = field.spec
    if placement is None:
        placement = RigidTransform.identity(spec.frame_id)
    if not isinstance(placement, RigidTransform) or placement.from_frame_id != spec.frame_id:
        raise ValueError("placement must start in the gas field frame")
    inverse = placement.inverse()
    source = spec.source
    parts = ["-- Generated static gas lookup; do not edit. Lua 5.1.\nlocal field={}",
        "local domain=" + _domain(spec.domain),
        "local inverse=" + lua_value(dict(rotation=[list(row) for row in inverse.rotation],
                                           translation=list(inverse.translation_mm))),
        "local rotation=" + lua_value([list(row) for row in placement.rotation]),
        "local frame=" + _text(placement.to_frame_id),
        "field.field_id=" + _text(spec.field_id),
        "field.composition_id=" + _text(spec.composition_id),
        "field.sampling_profile=" + _text(spec.sampling_profile),
        "field.source={kind=" + _text(source.kind) + ",source_id=" + _text(source.source_id)
        + ",assumptions={" + ",".join(_text(value) for value in source.assumptions) + "}}",
        "field.source.reference=" + ("nil" if source.reference is None else
            "{path=" + _text(source.reference["path"]) + ",exists=true,bytes="
            + lua_value(source.reference["bytes"]) + ",sha256=" + _text(source.reference["sha256"]) + "}"),
        "local kb=" + format(BOLTZMANN_CONSTANT_J_K, ".17g")]
    if spec.representation == "axisymmetric_rz_grid":
        data = field.data
        parts.extend(["field.interpolation_policy=" + _text(spec.interpolation_policy),
            "field.axis_projection_policy=" + _text(data.axis_projection_policy),
            "field.applicability='geometry_support_not_separately_proved'",
            f"local nr,nz={len(data.r_values_mm)},{len(data.z_values_mm)}",
            "local r0,z0,dr,dz=" + ",".join(format(v, ".17g") for v in
                (data.r_values_mm[0], data.z_values_mm[0], data.r_values_mm[1]-data.r_values_mm[0],
                 data.z_values_mm[1]-data.z_values_mm[0])),
            "local p=" + _chunks(data.pressure_pa), "local t=" + _chunks(data.temperature_k),
            "local ur=" + _chunks(data.radial_velocity_m_s), "local uz=" + _chunks(data.axial_velocity_m_s),
            _GRID])
        lookup = "status,pressure,temperature,vx,vy,vz=grid(x,y,z)"
    elif spec.representation == "uniform":
        parts.append("local uniform=" + _state(spec.uniform_state))
        lookup = "state=uniform"
    elif spec.representation == "piecewise_uniform":
        parts.append("local background=" + _state(spec.background_state))
        parts.append("local regions={" + ",".join("{id=" + _text(region.region_id)
            + ",domain=" + _domain(region.domain) + ",state=" + _state(region.state) + "}"
            for region in spec.regions) + "}")
        lookup = "state=background; for _,region in ipairs(regions) do if inside(region.domain,x,y,z) then state=region.state; region_id=region.id; break end end"
    else:
        parts.append("local background=" + lua_value(dict(
            status=spec.axisymmetric_background.status,
            pressure_pa=spec.axisymmetric_background.pressure_pa,
            temperature_k=spec.axisymmetric_background.temperature_k,
            ur=spec.axisymmetric_background.radial_velocity_m_s,
            uz=spec.axisymmetric_background.axial_velocity_m_s)))
        parts.append("local axial_regions=" + lua_value([dict(
            id=region.region_id, lo=region.minimum_z_mm, hi=region.maximum_z_mm,
            lower=region.lower_closed, upper=region.upper_closed,
            values=dict(status=region.values.status, pressure_pa=region.values.pressure_pa,
                temperature_k=region.values.temperature_k, ur=region.values.radial_velocity_m_s,
                uz=region.values.axial_velocity_m_s)) for region in spec.axisymmetric_regions]))
        lookup = ("local values=background; for _,region in ipairs(axial_regions) do "
                  "if (z>region.lo or (region.lower and z==region.lo)) and "
                  "(z<region.hi or (region.upper and z==region.hi)) then values=region.values; "
                  "region_id=region.id; break end end; local r=math.sqrt(x*x+y*y); "
                  "vx,vy,vz=0,0,values.uz; if r~=0 then "
                  "vx,vy=values.ur*x/r,values.ur*y/r end; "
                  "status,pressure,temperature=values.status,values.pressure_pa,values.temperature_k")
    parts.extend([_COMMON, "local function query(x,y,z,query_frame)\n"
        "  assert(query_frame==frame,'gas query frame differs')\n"
        "  assert(finite(x) and finite(y) and finite(z),'gas position must be finite')\n"
        "  x,y,z=transform(inverse.rotation,x,y,z,inverse.translation)\n"
        "  assert(finite(x) and finite(y) and finite(z),'transformed gas position must be finite')\n"
        "  local state,status,pressure,temperature,vx,vy,vz,region_id\n"
        "  if not inside(domain,x,y,z) then status='outside_domain' else " + lookup + " end\n"
        "  if state then status,pressure,temperature=state.status,state.pressure_pa,state.temperature_k; "
        "if state.bulk_velocity_m_s then vx,vy,vz=unpack(state.bulk_velocity_m_s) end end\n"
        "  if vx then vx,vy,vz=transform(rotation,vx,vy,vz); "
        "assert(finite(vx) and finite(vy) and finite(vz),'transformed gas velocity must be finite') end\n"
        "  local density\n  if status=='gas' then density=pressure/(kb*temperature) elseif status=='vacuum' then density=0 end\n"
        "  if density then assert(density==density and density<math.huge,'ideal-gas density is not finite') end\n"
        "  if status=='gas' then assert(density>0,'gas number density must be positive') end\n"
        "  return status,pressure,temperature,vx,vy,vz,density,region_id\nend\n"
        "function field.sample(x,y,z,query_frame)\n"
        "  local status,pressure,temperature,vx,vy,vz,density,region_id=query(x,y,z,query_frame)\n"
        "  local velocity; if vx then velocity={vx,vy,vz} end\n"
        "  return {status=status,pressure_pa=pressure,temperature_k=temperature,bulk_velocity_m_s=velocity,"
        "number_density_m3=density,frame_id=frame,region_id=region_id,composition_id=field.composition_id}\nend\n"
        "-- Internal numeric projection for the actual SDS binding, not a legacy scalar API.\n"
        "function field._sample_sds(channel,x,y,z,query_frame)\n"
        "  assert(channel=='pressure' or channel=='temperature' or channel=='velocity','unsupported SDS gas channel')\n"
        "  local status,pressure,temperature,vx,vy,vz=query(x,y,z,query_frame)\n"
        "  if channel=='pressure' then return status,pressure elseif channel=='temperature' then return status,temperature end\n"
        "  return status,vx,vy,vz\nend\nreturn field\n"])
    return "\n".join(parts)


def materialize_gas_runtime(
    field: GasField,
    output_lua: Path,
    output_manifest: Path,
    *,
    manifest_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Write the same joint compiler output with explicit caller-owned metadata.

    Scientific source acceptance and declaration/protection of run outputs stay
    with their existing component and execution owners. No project dispatch or
    default scientific input is supplied here.
    """
    metadata = copy.deepcopy(dict(manifest_metadata))
    if "runtime_lua" in metadata:
        raise ValueError("runtime output identity is derived by materialization")
    output_lua, output_manifest = Path(output_lua).resolve(), Path(output_manifest).resolve()
    output_lua.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_lua.write_text(compile_gas_runtime(field), encoding="utf-8", newline="\n")
    metadata["runtime_lua"] = {"path": str(output_lua), "sha256": file_sha256(output_lua).lower()}
    output_manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return metadata


_COMMON = """
local function inside(d,x,y,z)
  if d.kind=='unbounded' then return true end
  if d.kind=='cylinder' then local r=math.sqrt(x*x+y*y); return z>=d.lo and z<=d.hi and r>=d.inner_radius and r<=d.radius end
  local values={x,y,z}
  for i,v in ipairs(values) do
    if not ((v>d.lo[i] or (d.lower[i] and v==d.lo[i])) and
            (v<d.hi[i] or (d.upper[i] and v==d.hi[i]))) then return false end
  end
  return true
end
local function finite(v)
  return type(v)=='number' and v==v and math.abs(v)<math.huge
end
local function transform(rotation,x,y,z,translation)
  local a,b,c=rotation[1],rotation[2],rotation[3]
  return a[1]*x+a[2]*y+a[3]*z+(translation and translation[1] or 0),
         b[1]*x+b[2]*y+b[3]*z+(translation and translation[2] or 0),
         c[1]*x+c[2]*y+c[3]*z+(translation and translation[3] or 0)
end
"""

_GRID = """
local function value(a,i)
  local chunk=math.floor((i-1)/8192)+1
  return a[chunk][i-(chunk-1)*8192]
end
local function grid(x,y,z)
  local r=math.sqrt(x*x+y*y)
  local xr,xz=(r-r0)/dr,(z-z0)/dz
  local ir,iz=math.floor(xr),math.floor(xz)
  if ir>=nr-1 then ir=nr-2; xr=nr-1 end
  if iz>=nz-1 then iz=nz-2; xz=nz-1 end
  local fr,fz=xr-ir,xz-iz
  local first=iz*nr+ir+1
  local indices={first,first+1,first+nr,first+nr+1}
  local weights={(1-fr)*(1-fz),fr*(1-fz),(1-fr)*fz,fr*fz}
  local total=0
  for k,i in ipairs(indices) do if weights[k]>0 and value(p,i)~=false then total=total+weights[k] end end
  if total<=0 then return 'no_data' end
  local pressure,temperature,radial,axial=0,0,0,0
  for k,i in ipairs(indices) do
    if weights[k]>0 and value(p,i)~=false then
      pressure=pressure+weights[k]*value(p,i)
      temperature=temperature+weights[k]*value(t,i)
      radial=radial+weights[k]*value(ur,i)
      axial=axial+weights[k]*value(uz,i)
    end
  end
  local vr,vz=radial/total,axial/total
  local vx,vy=0,0
  if r~=0 then vx,vy=vr*x/r,vr*y/r end
  return 'gas',pressure/total,temperature/total,vx,vy,vz
end
"""
