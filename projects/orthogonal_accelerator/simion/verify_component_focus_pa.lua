-- Verify the exact native Fast Adjust controller family before publication.
local controller = assert(arg[1], 'PA# required')
local expected = assert(tonumber(arg[2]), 'electrode count required')
local expected_nx = assert(tonumber(arg[3]), 'expected nx required')
local expected_ny = assert(tonumber(arg[4]), 'expected ny required')
local expected_nz = assert(tonumber(arg[5]), 'expected nz required')
assert(controller:match('%.pa#$'), 'PA# path required')
local family = assert(simion.pas:open(controller:gsub('%.pa#$', '.pa0')))
local electrodes = family.electrode_numbers
assert(family.symmetry == '3dplanar[x]', 'controller must use x mirror symmetry')
assert(family.nx == expected_nx and family.ny == expected_ny and family.nz == expected_nz,
  'controller grid dimensions differ from the stored half-domain plan')
assert(type(electrodes) == 'table' and #electrodes == expected,
  'adjustable electrode count differs from the profile: actual='..tostring(type(electrodes)=='table' and #electrodes or 'invalid')..', expected='..tostring(expected))
for solution = 0, expected do
  local path = controller:gsub('%.pa#$', '.pa' .. solution)
  local handle = assert(io.open(path, 'rb'), 'solution array is missing: ' .. solution)
  handle:close()
end
print(string.format('ACCELERATOR_COMPONENT_FOCUS_PA_VERIFY=PASS electrodes=%d dimensions=%dx%dx%d symmetry=%s',
  expected, family.nx, family.ny, family.nz, family.symmetry))
family:close()
