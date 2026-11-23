-- Build one profile-sized native Fast Adjust family.
-- These are native solution arrays required by SIMION's pa:fast_adjust, not
-- detached standalone response PAs.
local gem, output = assert(arg[1], 'GEM required'), assert(arg[2], 'PA# required')
local electrode_count = assert(tonumber(arg[3]), 'electrode count required')
assert(electrode_count >= 1 and electrode_count == math.floor(electrode_count),
  'electrode count must be a positive integer')
assert(gem:match('%.gem$') and output:match('%.pa#$'), 'GEM and PA# paths required')
local staged = output:gsub('%.pa#$', '.source.gem')
local source = assert(io.open(gem, 'rb')); local body = source:read('*a'); source:close()
local copy = assert(io.open(staged, 'wb')); copy:write(body); copy:close()
simion.command(string.format('gem2pa %q %q', staged, output))
os.remove(staged); os.remove(staged:gsub('%.gem$', '.processed.gem'))
-- Preserve the GEM electrode flags.  The PA potential setter looks like a
-- zero-voltage initializer but clears those flags in SIMION 2020, leaving
-- Refine with no adjustable potentials.  This follows the installed official
-- ``examples/resistive/lens_pa0_build.lua`` pattern instead.
local family = assert(simion.pas:open(output))
family:refine{solutions={0}}
family:load(output)
local solutions = {}
for solution=1,electrode_count do solutions[#solutions+1] = solution end
family:refine{solutions=solutions}
family:close()
for solution=0,electrode_count do
  assert(io.open(output:gsub('%.pa#$', '.pa'..solution), 'rb'), 'solution array was not created: '..solution)
end
print(string.format('ACCELERATOR_COMPONENT_FOCUS_PA=PASS electrode_count=%d detached_response_bank=false', electrode_count))
