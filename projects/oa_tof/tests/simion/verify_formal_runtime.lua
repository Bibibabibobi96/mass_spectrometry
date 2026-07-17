local report_path = assert(arg[1], 'report path is required')
local iob_path = assert(arg[2], 'IOB path is required')
local resolved_path = assert(arg[3], 'resolved Lua contract is required')
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
for index, target in ipairs(expected) do
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

local p=contract.derived.field_sample_points_mm
local points = {
  {'src_center', 2, p.source_center[1],p.source_center[2],p.source_center[3]},
  {'accel_mid', 2, p.accelerator_mid[1],p.accelerator_mid[2],p.accelerator_mid[3]},
  {'accel_exit', 2, p.accelerator_exit[1],p.accelerator_exit[2],p.accelerator_exit[3]},
  {'drift_mid', 3, p.drift_mid[1],p.drift_mid[2],p.drift_mid[3]},
  {'refl_stage1', 1, p.reflectron_stage1[1],p.reflectron_stage1[2],p.reflectron_stage1[3]},
  {'refl_stage2', 1, p.reflectron_stage2[1],p.reflectron_stage2[2],p.reflectron_stage2[3]},
}
for _, point in ipairs(points) do
  -- Query the PA directly.  Static workbench field APIs invoke instance
  -- routing without an active ion and therefore cannot represent the
  -- particle-only segment.instance_adjust partition used during Fly'm.
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
end

record('STATUS=PASS')
report:close()
