-- Verify one private full-corridor response bank before immutable publication.
--
-- Usage: SIMION lua verify_native_corridor_response_bank.lua RAW.pa# \
--   NATIVE.pa1 DETACHED.response1.pa ... NATIVE.pa8 DETACHED.response8.pa
--
-- The caller must use a disposable transaction staging directory.  Published
-- cache paths are forbidden by the owning PowerShell runner.

local raw_path = assert(arg[1], 'raw corridor PA# required')
assert(raw_path:match('%.pa#$'), 'raw corridor input must end in .pa#')
assert((#arg - 1) == 16, 'eight native/detached response pairs are required')

local function assert_same_grid(reference, candidate, label)
  assert(candidate.nx == reference.nx and candidate.ny == reference.ny and candidate.nz == reference.nz,
    label .. ' grid dimensions differ')
  assert(candidate.dx_mm == reference.dx_mm and candidate.dy_mm == reference.dy_mm and candidate.dz_mm == reference.dz_mm,
    label .. ' mesh differs')
  assert(candidate.symmetry == reference.symmetry, label .. ' symmetry differs')
end

local function sample_indices(pa)
  return {
    {0, 0, 0},
    {pa.nx - 1, pa.ny - 1, pa.nz - 1},
    {math.floor((pa.nx - 1) / 2), math.floor((pa.ny - 1) / 2), math.floor((pa.nz - 1) / 2)},
  }
end

simion.pas:close()
local raw = assert(simion.pas:open(raw_path), 'cannot open private raw corridor PA')
for response_id = 1, 8 do
  local native_path = assert(arg[2 * response_id], 'native response path missing')
  local detached_path = assert(arg[2 * response_id + 1], 'detached response path missing')
  assert(native_path:match('%.pa' .. response_id .. '$'), 'native response suffix differs')
  assert(detached_path:match('%.pa$') and not detached_path:match('%.pa%d+$'),
    'detached response must use standalone .pa suffix')
  local native = assert(simion.pas:open(native_path), 'cannot open private native response')
  local detached = assert(simion.pas:open(detached_path), 'cannot open detached response')
  assert_same_grid(raw, native, 'native response ' .. response_id)
  assert_same_grid(raw, detached, 'detached response ' .. response_id)
  assert(detached.refinable ~= true, 'detached response remains refinable')
  for _, index in ipairs(sample_indices(raw)) do
    local nv, ne = native:point(index[1], index[2], index[3])
    local dv, de = detached:point(index[1], index[2], index[3])
    assert(nv == dv and ne == de, 'detached response node differs for response ' .. response_id)
  end
  native:close(); detached:close()
end
raw:close()
print('MRTOF_NATIVE_CORRIDOR_RESPONSE_BANK_VERIFY=PASS responses=8 detached_runtime_only=true')
