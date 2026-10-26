-- Pure arithmetic contract; no workbench, fields, or particle trajectories.
local waveforms = assert(loadfile(assert(arg[1], 'waveform module required')))()
local cap = waveforms.cap_before_edge
assert(cap(10, 3, 12) == 2)
assert(cap(10, 1, 12) == 1)
assert(cap(12, 3, 12) == 3)
assert(cap(13, 3, 12) == 3)
assert(cap(-3, 5, -1) == 2)
assert(cap(-3, 5, 0) == 3)
assert(cap(1010, 3, 1012) == cap(10, 3, 12))
assert(cap(10, 0, 12) == 0)
assert(cap(10, 3, 10) > 0, 'an exact landing must not create a zero-step loop')
print('VOLTAGE_WAVEFORMS_EDGE_CAP=PASS')

local gate = waveforms.rectangular_gate
for _, row in ipairs({{-3,false,-1},{-1,true,1},{0,true,1},{1,false},{2,false}}) do
  local active, edge = gate(row[1], -1, 1)
  assert(active == row[2] and edge == row[3])
end
local cubic = waveforms.cubic_transition
for _, u in ipairs({0, .125, 1/3, .371983, .5, .875, 1}) do
  assert(cubic(17, 4000, u) == 17 + (4000 - 17) * u * u * (3 - 2 * u))
end
assert(cubic(0, 4000, .5) == 2000)
print('VOLTAGE_WAVEFORMS_RECTANGULAR_CUBIC=PASS')
