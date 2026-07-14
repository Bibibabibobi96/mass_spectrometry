local report_path = assert(os.getenv('OATOF_SIMION_SYNC_REPORT'),
  'OATOF_SIMION_SYNC_REPORT is not set')
local report = assert(io.open(report_path, 'w'))

local function record(fmt, ...)
  local line = string.format(fmt, ...)
  report:write(line, '\n')
  print(line)
end

simion.command('"oatof_ideal_grounded.iob"')
local wb = simion.wb
assert(#wb.instances == 3, 'formal IOB must contain exactly three PA instances')

local expected = {
  {name='reflectron.pa0', x=0, y=0, z=619.83, az=-90, nx=213, ny=356, nz=1, dx=1},
  {name='accelerator.pa0', x=-93.8, y=-45, z=-15, az=0, nx=361, ny=361, nz=141, dx=0.25},
  {name='flight_tube_ground.pa0', x=0, y=0, z=19.83, az=-90, nx=601, ny=355, nz=1, dx=1},
}
for index, target in ipairs(expected) do
  local instance = wb.instances[index]
  assert(instance.filename:match(target.name .. '$'),
    string.format('instance %d file mismatch: %s', index, instance.filename))
  assert(math.abs(instance.x-target.x) < 1e-9 and
         math.abs(instance.y-target.y) < 1e-9 and
         math.abs(instance.z-target.z) < 1e-9 and
         math.abs(instance.az-target.az) < 1e-9,
    string.format('instance %d transform mismatch', index))
  assert(instance.pa.nx==target.nx and instance.pa.ny==target.ny and
         instance.pa.nz==target.nz and math.abs(instance.pa.dx_mm-target.dx)<1e-12,
    string.format('instance %d PA dimensions/grid mismatch', index))
  record('INSTANCE_%d=%s,%.9g,%.9g,%.9g,%.9g', index,
    target.name, instance.x, instance.y, instance.z, instance.az)
  record('INSTANCE_%d_PA=%d,%d,%d,%.9g', index,
    instance.pa.nx, instance.pa.ny, instance.pa.nz, instance.pa.dx_mm)
end

local points = {
  {'src_1p5', -48.8, 0, 1.5},
  {'src_10', -48.8, 0, 10},
  {'src_19', -48.8, 0, 19},
  {'drift_300', 0, 0, 300},
  {'drift_500', 0, 0, 500},
  {'refl_650', 0, 0, 650},
  {'refl_760', 0, 0, 760},
}
for _, point in ipairs(points) do
  local ex, ey, ez = wb:efield(point[2], point[3], point[4])
  record('FIELD_%s_XYZ_MM=%.9g,%.9g,%.9g',
    point[1], point[2], point[3], point[4])
  record('FIELD_%s_E_V_PER_MM=%.15g,%.15g,%.15g',
    point[1], ex or 0, ey or 0, ez or 0)
end

record('STATUS=PASS')
report:close()
