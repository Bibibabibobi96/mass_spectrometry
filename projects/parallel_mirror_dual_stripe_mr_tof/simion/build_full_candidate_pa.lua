-- Build and inspect the monolithic MR-TOF Candidate PA with SIMION 2020.
-- Usage: simion.exe --nogui lua build_full_candidate_pa.lua INPUT.gem OUTPUT.pa#
--        [mm_per_gu_x=4] [mm_per_gu_y=0.4] [mm_per_gu_z=4] [initialize_only=1]
--        [basis_start=0] [basis_end=0] [allow_quantized_ideal_grid=0]
local source = assert(arg[1], 'usage: INPUT.gem OUTPUT.pa# [xy] [z] [initialize_only]')
local output = assert(arg[2], 'output PA# is required')
local mmgu_x = tonumber(arg[3] or '4')
local mmgu_y = tonumber(arg[4] or '0.4')
local mmgu_z = tonumber(arg[5] or '4')
local initialize_only = tonumber(arg[6] or '1')
local basis_start = tonumber(arg[7] or '0')
local basis_end = tonumber(arg[8] or '0')
local allow_quantized_ideal_grid = tonumber(arg[9] or '0')
assert(source:match('%.gem$'), 'input must be a GEM file')
assert(output:match('%.pa#$'), 'output must end in .pa#')
assert(mmgu_x > 0 and mmgu_y > 0 and mmgu_z > 0, 'mesh spacings must be positive')
assert(basis_start >= 0 and basis_end >= basis_start and basis_end <= 30,
  'basis batch must be either 0,0 or a stable-electrode range within 1..30')
local exact_grid_alignment = math.abs(33.6/mmgu_y-math.floor(33.6/mmgu_y+0.5)) < 1e-9
  and math.abs(500/mmgu_y-math.floor(500/mmgu_y+0.5)) < 1e-9
assert(exact_grid_alignment or allow_quantized_ideal_grid == 1,
  'ideal grids require node alignment unless this is an explicitly quantized geometry-review PA')
if not exact_grid_alignment then
  print(string.format('BUILD: geometry_review_only=quantized_ideal_grids mmgu_y=%.12g', mmgu_y))
end
local staged = output:gsub('%.pa#$', '.source.gem')
local fin = assert(io.open(source, 'rb'))
local text = fin:read('*a')
fin:close()
assert(text:find('; mirror_design_status=theory_l0_validated', 1, true)
  or text:find('; mirror_design_status=analytic_l0_l1_candidate__3d_unvalidated__pa_build_allowed', 1, true),
  'refusing PA build: mirror geometry/voltages have not qualified a controlled prototype build')
local fout = assert(io.open(staged, 'wb'))
fout:write(text)
fout:close()
_G.var = {mmgu_x=mmgu_x, mmgu_y=mmgu_y, mmgu_z=mmgu_z}
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
          rows[potential][y] = true
        end
      end
    end
  end
end
local physical_ids = {}
for id = 1, 20 do table.insert(physical_ids, id) end
for _, id in ipairs({22, 23, 24, 26, 27, 28, 29, 30}) do table.insert(physical_ids, id) end
for _, id in ipairs(physical_ids) do
  print(string.format('BUILD: raw_electrode_points id=%d count=%d', id, counts[id] or 0))
end
for _, id in ipairs(physical_ids) do
  assert(counts[id] and counts[id] > 0, 'electrode '..id..' has no raw PA points')
end
for _, id in ipairs({23, 24}) do
  local n, row = 0, nil
  for z in pairs(rows[id] or {}) do n=n+1; row=z end
  assert(n == 1, 'ideal grid '..id..' occupies '..n..' raw rows')
  print(string.format('BUILD: native_ideal_grid electrode=%d raw_y_row=%d raw_points=%d', id, row, counts[id]))
end
print(string.format('BUILD: dimensions=%dx%dx%d mm_per_gu=(%.12g,%.12g,%.12g)',
  pa.nx, pa.ny, pa.nz, mmgu_x, mmgu_y, mmgu_z))
pa:close()
if initialize_only ~= 0 then
  -- Do not invoke bare refine{} here: it attempts every one of the 25
  -- solution arrays at once, which obscures failures and is not an initial
  -- PA0 proof.  SIMION's documented solutions={0} route creates exactly the
  -- grounded/geometry PA0 needed to validate the first IOB instance.  The
  -- independently logged basis-array batch is a later gate.
  local initialized = assert(simion.pas:open(output))
  -- Use SIMION 2020's documented default convergence.  The repository
  -- contract deliberately forbids an active convergence override: it is a
  -- solver-owned numerical setting, not a candidate-model parameter.
  initialized:refine{solutions={0}}
  initialized:close()
  local pa0 = output:gsub('%.pa#$', '.pa0')
  local check = assert(io.open(pa0, 'rb'), 'PA0 was not created by solutions={0}')
  check:close()
  print('BUILD: initialized_pa0=PASS')
end
if basis_end > 0 then
  for solution = basis_start, basis_end do
    local basis = assert(simion.pas:open(output))
    basis:refine{solutions={solution}}
    basis:close()
    local path = output:gsub('%.pa#$', '.pa'..solution)
    local check = assert(io.open(path, 'rb'), 'basis array was not created: '..path)
    check:close()
    print(string.format('BUILD: initialized_basis_array=%d PASS', solution))
  end
end
print('BUILD: PASS')
