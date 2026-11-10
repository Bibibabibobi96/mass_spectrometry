"""Compile explicit static gas fields to local Lua 5.1 lookup, without I/O.

Grid fields retain the existing dual-cone .9g values/.17g geometry and 8192
child-prototype chunks. Canonical domains use their explicit endpoint ownership;
the old uniform-control 1e-6 mm envelope is not a new default. This compiler has
software test consumers; existing Program adoption and old-generator retirement
are a subsequent atomic slice. No vendor callbacks, RNG, stepping or cache live here.
"""
from __future__ import annotations

from msplatform.contracts.gas import BoxDomain, CylindricalDomain, GasState, UnboundedDomain
from msplatform.contracts.particle_physics import BOLTZMANN_CONSTANT_J_K
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.gas.field import GasField
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
                              hi=domain.maximum_z_mm, radius=domain.maximum_radius_mm))
    if not isinstance(domain, BoxDomain):
        raise ValueError("unsupported gas domain")
    return lua_value(dict(kind="box", lo=list(domain.minimum_mm), hi=list(domain.maximum_mm),
                          lower=list(domain.lower_closed), upper=list(domain.upper_closed)))


def _state(state: GasState) -> str:
    return lua_value(dict(status=state.status, pressure_pa=state.pressure_pa,
        temperature_k=state.temperature_k,
        bulk_velocity_m_s=None if state.bulk_velocity_m_s is None else list(state.bulk_velocity_m_s)))


def _chunks(values) -> str:
    # Same constant-table boundary and z-major/r-minor layout as export_runtime.
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
    carries source semantics and the legacy-grid geometry-support limitation;
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
        "field.source={kind=" + _text(source.kind) + ",source_id=" + _text(source.source_id)
        + ",assumptions={" + ",".join(_text(value) for value in source.assumptions) + "}}",
        "field.source.reference=" + ("nil" if source.reference is None else
            "{path=" + _text(source.reference["path"]) + ",exists=true,bytes="
            + lua_value(source.reference["bytes"]) + ",sha256=" + _text(source.reference["sha256"]) + "}"),
        "local kb=" + format(BOLTZMANN_CONSTANT_J_K, ".17g")]
    if spec.representation == "axisymmetric_rz_grid":
        data = field.data
        parts.extend(["field.interpolation_policy=" + _text(spec.interpolation_policy),
            "field.applicability='geometry_support_not_separately_proved'",
            f"local nr,nz={len(data.r_values_mm)},{len(data.z_values_mm)}",
            "local r0,z0,dr,dz=" + ",".join(format(v, ".17g") for v in
                (data.r_values_mm[0], data.z_values_mm[0], data.r_values_mm[1]-data.r_values_mm[0],
                 data.z_values_mm[1]-data.z_values_mm[0])),
            "local p=" + _chunks(data.pressure_pa), "local t=" + _chunks(data.temperature_k),
            "local ur=" + _chunks(data.radial_velocity_m_s), "local uz=" + _chunks(data.axial_velocity_m_s),
            _GRID])
        lookup = "state=grid(x,y,z)"
    elif spec.representation == "uniform":
        parts.append("local uniform=" + _state(spec.uniform_state))
        lookup = "state=uniform"
    else:
        parts.append("local background=" + _state(spec.background_state))
        parts.append("local regions={" + ",".join("{id=" + _text(region.region_id)
            + ",domain=" + _domain(region.domain) + ",state=" + _state(region.state) + "}"
            for region in spec.regions) + "}")
        lookup = "state=background; for _,region in ipairs(regions) do if inside(region.domain,x,y,z) then state=region.state; region_id=region.id; break end end"
    parts.extend([_COMMON, "function field.sample(x,y,z,query_frame)\n"
        "  assert(query_frame==frame,'gas query frame differs')\n"
        "  for _,v in ipairs({x,y,z}) do assert(type(v)=='number' and v==v and math.abs(v)<math.huge,'gas position must be finite') end\n"
        "  x,y,z=transform(inverse.rotation,{x,y,z},inverse.translation)\n"
        "  for _,v in ipairs({x,y,z}) do assert(v==v and math.abs(v)<math.huge,'transformed gas position must be finite') end\n"
        "  local state,region_id\n  if not inside(domain,x,y,z) then state={status='outside_domain'} else "
        + lookup + " end\n"
        "  local velocity=state.bulk_velocity_m_s\n"
        "  if velocity then local a,b,c=transform(rotation,velocity); velocity={a,b,c} end\n"
        "  if velocity then for _,v in ipairs(velocity) do assert(v==v and math.abs(v)<math.huge,'transformed gas velocity must be finite') end end\n"
        "  local density\n  if state.status=='gas' then density=state.pressure_pa/(kb*state.temperature_k) elseif state.status=='vacuum' then density=0 end\n"
        "  if density then assert(density==density and density<math.huge,'ideal-gas density is not finite') end\n"
        "  if state.status=='gas' then assert(density>0,'gas number density must be positive') end\n"
        "  return {status=state.status,pressure_pa=state.pressure_pa,temperature_k=state.temperature_k,bulk_velocity_m_s=velocity,number_density_m3=density,frame_id=frame,region_id=region_id,composition_id=field.composition_id}\nend\nreturn field\n"])
    return "\n".join(parts)


_COMMON = """
local function inside(d,x,y,z)
  if d.kind=='unbounded' then return true end
  if d.kind=='cylinder' then return z>=d.lo and z<=d.hi and math.sqrt(x*x+y*y)<=d.radius end
  local values={x,y,z}
  for i,v in ipairs(values) do
    if not ((v>d.lo[i] or (d.lower[i] and v==d.lo[i])) and
            (v<d.hi[i] or (d.upper[i] and v==d.hi[i]))) then return false end
  end
  return true
end
local function transform(rotation,vector,translation)
  local result={}
  for i,row in ipairs(rotation) do
    result[i]=row[1]*vector[1]+row[2]*vector[2]+row[3]*vector[3]+(translation and translation[i] or 0)
  end
  return result[1],result[2],result[3]
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
  if total<=0 then return {status='no_data'} end
  local function sample(a)
    local result=0
    for k,i in ipairs(indices) do if weights[k]>0 and value(p,i)~=false then result=result+weights[k]*value(a,i) end end
    return result/total
  end
  local vr,vz=sample(ur),sample(uz)
  local velocity={0,0,vz}
  if r~=0 then velocity={vr*x/r,vr*y/r,vz} end
  return {status='gas',pressure_pa=sample(p),temperature_k=sample(t),bulk_velocity_m_s=velocity}
end
"""
