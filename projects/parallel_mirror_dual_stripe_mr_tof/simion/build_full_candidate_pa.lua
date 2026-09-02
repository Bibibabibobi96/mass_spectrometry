-- Build and inspect the monolithic MR-TOF Candidate PA with SIMION 2020.
-- Usage: simion.exe --nogui lua build_full_candidate_pa.lua INPUT.gem OUTPUT.pa#
--        [mm_per_gu_xy=4] [mm_per_gu_z=0.4] [initialize_only=1]
local source = assert(arg[1], 'usage: INPUT.gem OUTPUT.pa# [xy] [z] [initialize_only]')
local output = assert(arg[2], 'output PA# is required')
local mmgu_xy = tonumber(arg[3] or '4')
local mmgu_z = tonumber(arg[4] or '0.4')
local initialize_only = tonumber(arg[5] or '1')
assert(source:match('%.gem$'), 'input must be a GEM file')
assert(output:match('%.pa#$'), 'output must end in .pa#')
assert(mmgu_xy > 0 and mmgu_z > 0, 'mesh spacings must be positive')
assert(math.abs(6/mmgu_z-math.floor(6/mmgu_z+0.5)) < 1e-9,
  'grid-1 position must be aligned to a raw z row')
assert(math.abs(39.6/mmgu_z-math.floor(39.6/mmgu_z+0.5)) < 1e-9,
  'grid-2 position must be aligned to a raw z row')
local staged = output:gsub('%.pa#$', '.source.gem')
local fin = assert(io.open(source, 'rb'))
local text = fin:read('*a')
fin:close()
local fout = assert(io.open(staged, 'wb'))
fout:write(text)
fout:close()
_G.var = {mmgu_xy=mmgu_xy, mmgu_z=mmgu_z}
simion.command(string.format('gem2pa %q %q', staged, output))
_G.var = nil
os.remove(staged)
os.remove(staged:gsub('%.gem$', '.processed.gem'))
local pa = assert(simion.pas:open(output))
local rows, counts = {}, {}
for z = 0, pa.nz - 1 do
  for y = 0, pa.ny - 1 do
    for x = 0, pa.nx - 1 do
      local potential, electrode = pa:point(x, y, z)
      if electrode then
        counts[potential] = (counts[potential] or 0) + 1
        if potential == 23 or potential == 24 then
          rows[potential] = rows[potential] or {}
          rows[potential][z] = true
        end
      end
    end
  end
end
for id = 1, 25 do
  assert(counts[id] and counts[id] > 0, 'electrode '..id..' has no raw PA points')
end
for _, id in ipairs({23, 24}) do
  local n, row = 0, nil
  for z in pairs(rows[id] or {}) do n=n+1; row=z end
  assert(n == 1, 'ideal grid '..id..' occupies '..n..' raw rows')
  print(string.format('BUILD: native_ideal_grid electrode=%d raw_z_row=%d raw_points=%d', id, row, counts[id]))
end
print(string.format('BUILD: dimensions=%dx%dx%d mm_per_gu=(%.12g,%.12g,%.12g)',
  pa.nx, pa.ny, pa.nz, mmgu_xy, mmgu_xy, mmgu_z))
pa:close()
if initialize_only ~= 0 then
  local initialized = assert(simion.pas:open(output))
  initialized:refine{}
  initialized:close()
  print('BUILD: initialized_basis_arrays=PASS')
end
print('BUILD: PASS')
