-- Build one native Fast Adjust family (PA# plus PA0 through PA9).
-- These are native solution arrays required by SIMION's pa:fast_adjust, not
-- detached standalone response PAs.
local gem, output = assert(arg[1], 'GEM required'), assert(arg[2], 'PA# required')
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
family:refine{solutions={1,2,3,4,5,6,7,8,9}}
family:close()
for solution=0,9 do
  assert(io.open(output:gsub('%.pa#$', '.pa'..solution), 'rb'), 'solution array was not created: '..solution)
end
print('ACCELERATOR_COMPONENT_FOCUS_PA=PASS family=pa_hash_plus_pa0_through_pa9 detached_response_bank=false')
