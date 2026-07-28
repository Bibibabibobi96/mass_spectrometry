local report_path = assert(arg[1], 'report path is required')
local iob_path = assert(arg[2], 'IOB path is required')
local resolved_path = assert(arg[3], 'resolved Lua contract is required')
local allow_legacy_order = arg[4]=='allow_legacy_order'
local contract = assert(dofile(resolved_path), 'resolved contract did not return a table')
local report = assert(io.open(report_path, 'w'))

local function record(fmt, ...)
  local line = string.format(fmt, ...)
  report:write(line, '\n')
  print(line)
end

simion.command('"' .. iob_path .. '"')
local wb = simion.wb
assert(#wb.instances == 4, 'formal IOB must contain exactly four PA instances')
local expected = contract.derived.simion_instances
local role_index = {}
for index, target in ipairs(expected) do
  local role=target.role
  if not role and allow_legacy_order then
    if target.name:match('flight_tube') then role='flight_tube_shield'
    elseif target.name:match('reflectron') then role='reflectron'
    elseif target.name:match('accelerator') then role='accelerator'
    elseif target.name:match('detector') then role='detector' end
  end
  assert(role, 'SIMION instance role is missing for '..tostring(target.name))
  if not allow_legacy_order then
    assert(target.workbench_index==index and target.priority_number==index,
      string.format('contract slot/priority mismatch for %s: slot=%s priority=%s index=%d',
        role,tostring(target.workbench_index),tostring(target.priority_number),index))
  end
  assert(not role_index[role], 'duplicate SIMION instance role: '..role)
  role_index[role]=index
  local instance = wb.instances[index]
  assert(instance.filename:match(target.name .. '$'),
    string.format('instance %d file mismatch: %s', index, instance.filename))
  assert(math.abs(instance.x-target.x_mm) < 1e-9 and
         math.abs(instance.y-target.y_mm) < 1e-9 and
         math.abs(instance.z-target.z_mm) < 1e-9 and
         math.abs(instance.az-target.az_deg) < 1e-9,
    string.format('instance %d transform mismatch: actual=(%.12g,%.12g,%.12g,%.12g) expected=(%.12g,%.12g,%.12g,%.12g)',
      index,instance.x,instance.y,instance.z,instance.az,
      target.x_mm,target.y_mm,target.z_mm,target.az_deg))
  assert(instance.pa.nx==target.nx and instance.pa.ny==target.ny and
         instance.pa.nz==target.nz and math.abs(instance.pa.dx_mm-target.cell_mm)<1e-12,
    string.format('instance %d PA dimensions/grid mismatch: actual=%dx%dx%d@%.12g expected=%dx%dx%d@%.12g',
      index,instance.pa.nx,instance.pa.ny,instance.pa.nz,instance.pa.dx_mm,
      target.nx,target.ny,target.nz,target.cell_mm))
  record('INSTANCE_%d=%s,%.9g,%.9g,%.9g,%.9g', index,
    target.name, instance.x, instance.y, instance.z, instance.az)
  record('INSTANCE_%d_PA=%d,%d,%d,%.9g', index,
    instance.pa.nx, instance.pa.ny, instance.pa.nz, instance.pa.dx_mm)
end

if not allow_legacy_order then
  assert(role_index.flight_tube_shield==1 and role_index.reflectron==2 and
         role_index.accelerator==3 and role_index.detector==4,
    'unsafe SIMION priority order; expected shield < reflectron < accelerator < detector')
end
local p=contract.derived.field_sample_points_mm
local points = {
  {'src_center', role_index.accelerator, p.source_center[1],p.source_center[2],p.source_center[3]},
  {'accel_mid', role_index.accelerator, p.accelerator_mid[1],p.accelerator_mid[2],p.accelerator_mid[3]},
  {'accel_exit', role_index.accelerator, p.accelerator_exit[1],p.accelerator_exit[2],p.accelerator_exit[3]},
  {'drift_mid', role_index.flight_tube_shield, p.drift_mid[1],p.drift_mid[2],p.drift_mid[3]},
  {'refl_stage1', role_index.reflectron, p.reflectron_stage1[1],p.reflectron_stage1[2],p.reflectron_stage1[3]},
  {'refl_stage2', role_index.reflectron, p.reflectron_stage2[1],p.reflectron_stage2[2],p.reflectron_stage2[3]},
}
for _, point in ipairs(points) do
  -- wb:efield selects the static highest-priority PA at this point.  It does
  -- not invoke segment.instance_adjust and therefore audits the IOB overlap
  -- relation independently of trajectory Program logic.
  local instance=wb.instances[point[2]]
  local xg,yg,zg=instance:wb_to_pa_coords(point[3],point[4],point[5])
  local ex,ey,ez=instance.pa:field_vc(xg,yg,zg)
  ex=ex/(instance.pa.dx_mm*instance.scale)
  ey=ey/(instance.pa.dy_mm*instance.scale)
  ez=ez/(instance.pa.dz_mm*instance.scale)
  record('FIELD_%s_XYZ_MM=%.9g,%.9g,%.9g',
    point[1], point[3], point[4], point[5])
  record('FIELD_%s_PA_LOCAL_E_V_PER_MM=%.15g,%.15g,%.15g',
    point[1], ex or 0, ey or 0, ez or 0)
  local wx,wy,wz=wb:efield(point[3],point[4],point[5])
  local on_electrode,active_electric=wb:find_at(point[3],point[4],point[5])
  record('FIELD_%s_WB_STATIC_E_V_PER_MM=%.15g,%.15g,%.15g',
    point[1], wx or 0, wy or 0, wz or 0)
  record('FIELD_%s_WB_STATIC_ACTIVE_INSTANCE=%s ELECTRODE=%s',
    point[1], tostring(active_electric), tostring(on_electrode))
  local local_norm=math.sqrt((ex or 0)^2+(ey or 0)^2+(ez or 0)^2)
  local wb_norm=math.sqrt((wx or 0)^2+(wy or 0)^2+(wz or 0)^2)
  local scale=math.max(1,local_norm,wb_norm)
  if not allow_legacy_order then
    assert(math.abs(local_norm-wb_norm)<=1e-8*scale,
      string.format('static priority mismatch at %s: expected role instance=%d local_norm=%.15g wb_norm=%.15g',
        point[1],point[2],local_norm,wb_norm))
  end
end

-- Probe the middle of the persisted detector electrode, not a Lua virtual
-- plane.  The IOB itself must select detector instance 4 over shield 1.
local detector_x=contract.coordinate_convention.detector_x
local detector_z=contract.simion_detector_marker.active_plane_z_mm-
  contract.simion_detector_marker.absorber_thickness_mm/2
local detector_electrode,detector_instance=wb:find_at(detector_x,0,detector_z)
record('DETECTOR_STATIC_PROBE_XYZ_MM=%.15g,0,%.15g',detector_x,detector_z)
record('DETECTOR_STATIC_ACTIVE_INSTANCE=%s ELECTRODE=%s',
  tostring(detector_instance),tostring(detector_electrode))
if not allow_legacy_order then
  assert(detector_electrode and detector_instance==role_index.detector,
    string.format('static detector priority mismatch: expected instance=%d actual=%s electrode=%s',
      role_index.detector,tostring(detector_instance),tostring(detector_electrode)))
end

record('STATUS=PASS')
report:close()
