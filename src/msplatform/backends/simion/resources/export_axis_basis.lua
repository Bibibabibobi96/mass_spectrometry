-- Export normalized fast-adjust basis potentials on the reflectron axis.
-- Usage: simion --nogui lua export_axis_basis.lua stem_without_suffix max_electrode output.csv max_x_mm
local stem = assert(arg[1], 'missing PA stem')
local maximum_electrode = assert(tonumber(arg[2]), 'invalid maximum electrode')
local output = assert(arg[3], 'missing output CSV')
local maximum_x_mm = assert(tonumber(arg[4]), 'invalid maximum axial position')
assert(maximum_electrode >= 1 and maximum_electrode == math.floor(maximum_electrode),
  'maximum electrode must be a positive integer')

simion.pas:close()
local arrays = {}
for electrode = 1,maximum_electrode do
  arrays[electrode] = simion.pas:open(stem .. '.pa' .. electrode)
end
local reference = arrays[1]
local last_x = math.min(reference.nx-1, math.floor(maximum_x_mm/reference.dx_mm+1e-9))
local stream = assert(io.open(output, 'w'))
stream:write('x_mm')
for electrode = 1,maximum_electrode do
  stream:write(',basis_' .. electrode .. '_V')
end
stream:write('\n')
for x = 0,last_x do
  stream:write(string.format('%.12g', x*reference.dx_mm))
  for electrode = 1,maximum_electrode do
    stream:write(string.format(',%.12g', arrays[electrode]:potential(x,0,0)))
  end
  stream:write('\n')
end
stream:close()
simion.pas:close()
print(string.format('AXIS_BASIS_EXPORT=PASS rows=%d electrodes=%d output=%s',
  last_x+1, maximum_electrode, output))
