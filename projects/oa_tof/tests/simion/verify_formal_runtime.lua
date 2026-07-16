local report_path = assert(os.getenv('OATOF_SIMION_SYNC_REPORT'),
  'OATOF_SIMION_SYNC_REPORT is not set')
local report = assert(io.open(report_path, 'w'))

local function record(fmt, ...)
  local line = string.format(fmt, ...)
  report:write(line, '\n')
  print(line)
end

local iob_path = os.getenv('OATOF_FORMAL_IOB_PATH') or
  [[oatof_ideal_grounded.iob]]
simion.command('"' .. iob_path .. '"')
local wb = simion.wb
assert(#wb.instances == 4, 'formal IOB must contain exactly four PA instances')

local expected = {
  {name='reflectron.pa0', x=0, y=0, z=619.83, az=-90, nx=1089, ny=361, nz=1, dx=0.25},
  {name='accelerator.pa0', x=-67.8, y=-19, z=-10, az=0, nx=153, ny=153, nz=601, dx=0.25},
  {name='flight_tube_ground.pa0', x=0, y=0, z=-40, az=-90, nx=661, ny=361, nz=1, dx=1},
  {name='detector_ground.pa0', x=7.8, y=-41, z=19.73, az=0, nx=165, ny=165, nz=31, dx=0.5},
}
for index, target in ipairs(expected) do
  local instance = wb.instances[index]
  assert(instance.filename:match(target.name .. '$'),
    string.format('instance %d file mismatch: %s', index, instance.filename))
  assert(math.abs(instance.x-target.x) < 1e-9 and
         math.abs(instance.y-target.y) < 1e-9 and
         math.abs(instance.z-target.z) < 1e-9 and
         math.abs(instance.az-target.az) < 1e-9,
    string.format('instance %d transform mismatch: actual=(%.12g,%.12g,%.12g,%.12g) expected=(%.12g,%.12g,%.12g,%.12g)',
      index,instance.x,instance.y,instance.z,instance.az,
      target.x,target.y,target.z,target.az))
  assert(instance.pa.nx==target.nx and instance.pa.ny==target.ny and
         instance.pa.nz==target.nz and math.abs(instance.pa.dx_mm-target.dx)<1e-12,
    string.format('instance %d PA dimensions/grid mismatch: actual=%dx%dx%d@%.12g expected=%dx%dx%d@%.12g',
      index,instance.pa.nx,instance.pa.ny,instance.pa.nz,instance.pa.dx_mm,
      target.nx,target.ny,target.nz,target.dx))
  record('INSTANCE_%d=%s,%.9g,%.9g,%.9g,%.9g', index,
    target.name, instance.x, instance.y, instance.z, instance.az)
  record('INSTANCE_%d_PA=%d,%d,%d,%.9g', index,
    instance.pa.nx, instance.pa.ny, instance.pa.nz, instance.pa.dx_mm)
end

local points = {
  {'src_1p5', 2, -48.8, 0, 1.5},
  {'src_10', 2, -48.8, 0, 10},
  {'src_19', 2, -48.8, 0, 19},
  {'drift_300', 3, 0, 0, 300},
  {'drift_500', 3, 0, 0, 500},
  {'refl_650', 1, 0, 0, 650},
  {'refl_760', 1, 0, 0, 760},
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
