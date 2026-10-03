-- Verify the reusable coarse 10000 V physical-electrode donor bank.
local raw=assert(simion.pas:open(assert(arg[1], 'raw PA required')))
local basis_voltage=10000
local numerical_tolerance=2e-6*basis_voltage
for index=2,#arg do
  local path=assert(arg[index])
  local pa=assert(simion.pas:open(path), 'donor PA missing: '..path)
  assert(pa.nx==raw.nx and pa.ny==raw.ny and pa.nz==raw.nz, 'donor grid differs')
  assert(pa.dx_mm==raw.dx_mm and pa.dy_mm==raw.dy_mm and pa.dz_mm==raw.dz_mm, 'donor scale differs')
  local minimum,maximum=pa:potentials_minmax()
  print(string.format('COARSE_BASIS_RANGE member=%s min=%.17g max=%.17g',path,minimum,maximum))
  assert(minimum>=-numerical_tolerance,
    string.format('donor has an invalid negative basis minimum: %.17g',minimum))
  assert(math.abs(maximum-basis_voltage)<=numerical_tolerance,
    string.format('donor basis voltage differs from 10000 V: %.17g',maximum))
  pa:close()
end
raw:close()
print('MRTOF_COARSE_BASIS_BANK_VERIFY=PASS donors='..(#arg-1))
