-- Verify the MR-TOF two-instance geometry-review Workbench without flying.
-- Usage: simion.exe --nogui lua inspect_split_candidate_iob.lua IOB REPORT AX AY AZ BX BY BZ
local iob = assert(arg[1], 'IOB required')
local report_path = assert(arg[2], 'report path required')
local expected = {}
for index = 3, 8 do expected[#expected + 1] = assert(tonumber(arg[index]), 'origin value required') end
local report = assert(io.open(report_path, 'wb'))
local function record(text) report:write(text, '\n'); report:flush(); print(text) end
local function close(actual, target) return math.abs(actual - target) <= 1e-9 end

local wb = assert(simion.wb, 'SIMION 2020 did not create an empty Workbench object')
assert(wb.load, 'SIMION 2020 Workbench API lacks the supported IOB load method')
wb:load(iob)
assert(wb.filename, 'IOB did not load a Workbench')
assert(#wb.instances == 2, 'MR-TOF review IOB must have exactly two instances')
local expected_paths = {'mrtof_analyzer.pa0', 'mrtof_accelerator.pa0'}
local expected_mmgu = {{2, 2, 2}, {1, 1, 0.4}}
for index = 1, #wb.instances do
  local instance = wb.instances[index]
  local pa = assert(instance.pa, 'instance '..index..' has no loaded PA')
  assert(instance.filename == expected_paths[index], 'instance '..index..' PA basename mismatch')
  local offset = (index - 1) * 3
  assert(close(instance.x, expected[offset + 1]) and close(instance.y, expected[offset + 2]) and close(instance.z, expected[offset + 3]),
    'instance '..index..' origin mismatch')
  assert(close(pa.dx_mm, expected_mmgu[index][1]) and close(pa.dy_mm, expected_mmgu[index][2]) and close(pa.dz_mm, expected_mmgu[index][3]),
    'instance '..index..' mesh mismatch')
  record(string.format('INSTANCE_%d file=%s origin_mm=%.12g,%.12g,%.12g mesh_mmgu=%.12g,%.12g,%.12g dims=%d,%d,%d',
    index, instance.filename, instance.x, instance.y, instance.z, pa.dx_mm, pa.dy_mm, pa.dz_mm, pa.nx, pa.ny, pa.nz))
end
record('PHYSICAL_MODEL=false')
record('PARTICLE_FLY_EXECUTED=false')
record('STATUS=PASS')
report:close()
