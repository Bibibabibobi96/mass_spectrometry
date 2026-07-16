-- Inspect an already built candidate IOB without triggering interactive PA
-- generation/refinement.  The caller must provide both paths explicitly.
local report_path = assert(os.getenv('RFQUAD_SIMION_REFERENCE_REPORT'),
  'RFQUAD_SIMION_REFERENCE_REPORT is not set')
local iob_path = assert(os.getenv('RFQUAD_SIMION_REFERENCE_IOB'),
  'RFQUAD_SIMION_REFERENCE_IOB is not set')

simion.command('"' .. iob_path .. '"')
local report = assert(io.open(report_path, 'w'))
local function record(fmt, ...)
  local line = string.format(fmt, ...)
  report:write(line, '\n')
  print(line)
end

record('IOB=%s', iob_path)
record('INSTANCE_COUNT=%d', #simion.wb.instances)
assert(#simion.wb.instances == 1, 'monolithic candidate must contain one PA instance')
for index = 1, #simion.wb.instances do
  local instance = simion.wb.instances[index]
  local pa = instance.pa
  record('INSTANCE_%d_FILE=%s', index, instance.filename)
  record('INSTANCE_%d_TRANSFORM=%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g',
    index, instance.x, instance.y, instance.z,
    instance.az, instance.el, instance.rt, instance.scale)
  record('INSTANCE_%d_PA=%d,%d,%d,%.15g,%.15g,%.15g',
    index, pa.nx, pa.ny, pa.nz, pa.dx_mm, pa.dy_mm, pa.dz_mm)
  local xx,xy,xz = instance:pa_to_wb_orient(1,0,0)
  local yx,yy,yz = instance:pa_to_wb_orient(0,1,0)
  local zx,zy,zz = instance:pa_to_wb_orient(0,0,1)
  record('INSTANCE_%d_PA_X_IN_WB=%.15g,%.15g,%.15g', index, xx,xy,xz)
  record('INSTANCE_%d_PA_Y_IN_WB=%.15g,%.15g,%.15g', index, yx,yy,yz)
  record('INSTANCE_%d_PA_Z_IN_WB=%.15g,%.15g,%.15g', index, zx,zy,zz)
  assert(pa.nx == 39 and pa.ny == 39 and pa.nz == 477,
    'candidate PA dimensions moved from the built-in reference')
  assert(math.abs(pa.dx_mm - 0.2) < 1e-12 and
         math.abs(pa.dy_mm - 0.2) < 1e-12 and
         math.abs(pa.dz_mm - 0.2) < 1e-12,
    'candidate PA cell size moved from 0.2 mm')
end
record('STATUS=PASS')
report:close()
