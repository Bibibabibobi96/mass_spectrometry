-- Inspect one raw PA grid point while diagnosing a Candidate trajectory.
-- Usage: simion.exe --nogui lua inspect_pa_electrode.lua PA# X Y Z [ELECTRODE_ID]
local path = assert(arg[1], 'PA# required')
local x, y, z = tonumber((assert(arg[2], 'x required'))), tonumber((assert(arg[3], 'y required'))), tonumber((assert(arg[4], 'z required')))
local pa = assert(simion.pas:open(path))
for dz = -2, 2 do
  for dy = -1, 1 do
    for dx = -1, 1 do
      local potential, electrode = pa:point(x + dx, y + dy, z + dz)
      if electrode then
        print(string.format('PA_POINT: x=%d y=%d z=%d potential=%s electrode=%s', x + dx, y + dy, z + dz, tostring(potential), tostring(electrode)))
      end
    end
  end
end
local id = tonumber(arg[5])
if id then
  local xmin, ymin, zmin, xmax, ymax, zmax
  for zz = 0, pa.nz - 1 do
    for yy = 0, pa.ny - 1 do
      for xx = 0, pa.nx - 1 do
        local potential, electrode = pa:point(xx, yy, zz)
        if electrode and potential == id then
          xmin, ymin, zmin = xmin and math.min(xmin, xx) or xx, ymin and math.min(ymin, yy) or yy, zmin and math.min(zmin, zz) or zz
          xmax, ymax, zmax = xmax and math.max(xmax, xx) or xx, ymax and math.max(ymax, yy) or yy, zmax and math.max(zmax, zz) or zz
        end
      end
    end
  end
  print(string.format('PA_ELECTRODE_BOUNDS: id=%d grid=[%d,%d,%d]..[%d,%d,%d]', id, xmin, ymin, zmin, xmax, ymax, zmax))
end
pa:close()
