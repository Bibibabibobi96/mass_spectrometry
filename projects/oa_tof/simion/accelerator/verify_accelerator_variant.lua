-- Verify PA header values without loading a workbench.
-- Usage: simion.exe --nogui lua verify_accelerator_variant.lua pa_file nx ny nz dx dy dz

local path = assert(arg[1], 'missing PA file')
local expected = {
  nx=assert(tonumber(arg[2]), 'missing nx'),
  ny=assert(tonumber(arg[3]), 'missing ny'),
  nz=assert(tonumber(arg[4]), 'missing nz'),
  dx=assert(tonumber(arg[5]), 'missing dx'),
  dy=assert(tonumber(arg[6]), 'missing dy'),
  dz=assert(tonumber(arg[7]), 'missing dz'),
}
local pa = assert(simion.pas:open(path), 'cannot open PA')
assert(pa.nx==expected.nx and pa.ny==expected.ny and pa.nz==expected.nz,
  string.format('dimension mismatch actual=%dx%dx%d expected=%dx%dx%d',
    pa.nx,pa.ny,pa.nz,expected.nx,expected.ny,expected.nz))
local tol=1e-12
assert(math.abs(pa.dx_mm-expected.dx)<tol and
       math.abs(pa.dy_mm-expected.dy)<tol and
       math.abs(pa.dz_mm-expected.dz)<tol,
  string.format('cell mismatch actual=(%.12g,%.12g,%.12g) expected=(%.12g,%.12g,%.12g)',
    pa.dx_mm,pa.dy_mm,pa.dz_mm,expected.dx,expected.dy,expected.dz))
print(string.format('PA_HEADER=%dx%dx%d,%.12g,%.12g,%.12g',
  pa.nx,pa.ny,pa.nz,pa.dx_mm,pa.dy_mm,pa.dz_mm))
print('PA_HEADER_STATUS=PASS')
