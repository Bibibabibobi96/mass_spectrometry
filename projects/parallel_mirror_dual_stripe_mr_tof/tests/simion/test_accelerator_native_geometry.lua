-- Read-only SIMION 2020 PA# geometry verification: raw.pa# samples.csv.
-- The frozen test CSV is derived from the same run-local MR contract/resolved
-- geometry as the GEM. Never use a PA0: PA# potentials carry electrode IDs.
-- Official installed support: docs/simion.chm lua_simion.pas.html (pa:point,
-- pa.nx/ny/nz, pa.dx_mm/dy_mm/dz_mm); existing vendor PA.py documents the same
-- read-only node/electrode distinction. No refinement, adjustment or save.
assert(#arg == 2, 'raw.pa# and frozen samples.csv required')
assert(arg[1]:match('%.pa#$'), 'geometry ID verification requires raw PA#')
local input = assert(io.open(arg[2], 'r'))
assert(input:read('*l') == 'kind,label,x,y,z,expected_id', 'invalid sample schema')
local pa = assert(simion.pas:open(arg[1]))
local checked, failures, metadata = 0, 0, {}
for line in input:lines() do
  local kind,label,x,y,z,eid = line:match('^([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+)$')
  assert(kind, 'malformed geometry sample row')
  x,y,z,eid = assert(tonumber(x)),assert(tonumber(y)),assert(tonumber(z)),assert(tonumber(eid))
  if kind == 'dimensions' then
    assert(pa.nx == x and pa.ny == y and pa.nz == z, 'PA dimensions differ from frozen contract')
    metadata[kind] = true
  elseif kind == 'mesh' then
    assert(pa.dx_mm == x and pa.dy_mm == y and pa.dz_mm == z, 'PA mesh differs from frozen contract')
    metadata[kind] = true
  elseif kind == 'origin' or kind == 'identity' then
    assert(not metadata[kind], 'duplicate geometry metadata')
    metadata[kind] = true
    print(string.format('NATIVE_GEOMETRY_%s=%s,%.17g,%.17g,%.17g', kind, label, x,y,z))
  elseif kind == 'sample' then
    assert(metadata.dimensions and metadata.mesh and metadata.origin and metadata.identity,
      'geometry metadata must precede samples')
    assert(x == math.floor(x) and y == math.floor(y) and z == math.floor(z), 'sample must be an exact PA node')
    assert(x >= 0 and x < pa.nx and y >= 0 and y < pa.ny and z >= 0 and z < pa.nz,
      'sample outside PA')
    local potential,electrode = pa:point(x,y,z)
    local actual = electrode and potential or 0
    checked = checked+1
    if electrode ~= (eid ~= 0) or math.abs(actual-eid) > 16*2^-52*100000 then
      failures = failures+1
      print(string.format('NATIVE_GEOMETRY_FAIL label=%s node=%d,%d,%d expected_id=%d actual_id=%.17g',
        label,x,y,z,eid,actual))
    end
  else
    error('unknown sample record kind: '..kind)
  end
end
input:close()
pa:close()
assert(checked > 0, 'empty native geometry sample set')
print(string.format('NATIVE_ACCELERATOR_GEOMETRY samples=%d failures=%d',checked,failures))
assert(failures == 0, 'native accelerator geometry differs from resolved contract')
print('NATIVE_ACCELERATOR_GEOMETRY=PASS')
