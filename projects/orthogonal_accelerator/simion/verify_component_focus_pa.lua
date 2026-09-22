-- Verify the exact native Fast Adjust controller family before publication.
local controller = assert(arg[1], 'PA# required')
assert(controller:match('%.pa#$'), 'PA# path required')
local family = assert(simion.pas:open(controller))
local electrodes = family.electrode_numbers
assert(type(electrodes) == 'table' and #electrodes == 9,
  'expected exactly nine adjustable electrodes')
for solution = 0, 9 do
  local path = controller:gsub('%.pa#$', '.pa' .. solution)
  local handle = assert(io.open(path, 'rb'), 'solution array is missing: ' .. solution)
  handle:close()
end
family:close()
print('ACCELERATOR_COMPONENT_FOCUS_PA_VERIFY=PASS family=pa_hash_plus_pa0_through_pa9 electrodes=9')
