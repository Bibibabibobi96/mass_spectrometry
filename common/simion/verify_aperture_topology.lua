-- Repository-wide fail-closed verifier for a rectangular aperture in a compiled PA.
-- The caller supplies physical coordinates; this script checks that at least
-- one integer-node column remains non-electrode through the full flange depth.

local function required_env(name)
  return assert(os.getenv(name), name .. ' is not set')
end

local function required_number(name)
  local raw = required_env(name)
  local value = tonumber(raw)
  return assert(value, name .. ' must be numeric')
end

local pa_path = required_env('SIMION_APERTURE_PA_PATH')
local report_path = required_env('SIMION_APERTURE_REPORT_PATH')
local origin_x = required_number('SIMION_APERTURE_ORIGIN_X_MM')
local origin_y = required_number('SIMION_APERTURE_ORIGIN_Y_MM')
local origin_z = required_number('SIMION_APERTURE_ORIGIN_Z_MM')
local cell_x_mm = required_number('SIMION_APERTURE_CELL_MM_X')
local cell_y_mm = required_number('SIMION_APERTURE_CELL_MM_Y')
local cell_z_mm = required_number('SIMION_APERTURE_CELL_MM_Z')
local flange_x_min = required_number('SIMION_APERTURE_FLANGE_X_MIN_MM')
local flange_x_max = required_number('SIMION_APERTURE_FLANGE_X_MAX_MM')
local center_y = required_number('SIMION_APERTURE_CENTER_Y_MM')
local center_z = required_number('SIMION_APERTURE_CENTER_Z_MM')
local width_mm = required_number('SIMION_APERTURE_WIDTH_MM')
local height_mm = required_number('SIMION_APERTURE_HEIGHT_MM')
local boundary_policy = required_env('SIMION_APERTURE_BOOLEAN_BOUNDARY_POLICY')

assert(cell_x_mm > 0 and cell_y_mm > 0 and cell_z_mm > 0
    and width_mm >= cell_y_mm and height_mm >= cell_z_mm,
  'aperture dimensions must each be at least one positive PA cell')
assert(flange_x_max >= flange_x_min, 'flange x bounds are reversed')
assert(boundary_policy == 'exclude_shape_inside_or_on_v1',
  'unsupported aperture Boolean boundary policy')

local pa = assert(simion.pas:open(pa_path), 'could not open compiled aperture PA')
local epsilon = 1e-9
local function lower_index(value, origin, cell_mm)
  return math.ceil((value - origin) / cell_mm - epsilon)
end
local function upper_index(value, origin, cell_mm)
  return math.floor((value - origin) / cell_mm + epsilon)
end

local ix_min = lower_index(flange_x_min, origin_x, cell_x_mm)
local ix_max = upper_index(flange_x_max, origin_x, cell_x_mm)
local iy_min = lower_index(center_y - width_mm / 2, origin_y, cell_y_mm)
local iy_max = upper_index(center_y + width_mm / 2, origin_y, cell_y_mm)
local iz_min = lower_index(center_z - height_mm / 2, origin_z, cell_z_mm)
local iz_max = upper_index(center_z + height_mm / 2, origin_z, cell_z_mm)

assert(ix_min >= 0 and iy_min >= 0 and iz_min >= 0
    and ix_max < pa.nx and iy_max < pa.ny and iz_max < pa.nz,
  'aperture topology check bounds lie outside the compiled PA')

local open_columns = 0
local candidate_columns = 0
for iy = iy_min, iy_max do
  for iz = iz_min, iz_max do
    candidate_columns = candidate_columns + 1
    local open = true
    for ix = ix_min, ix_max do
      local _, is_electrode = pa:point(ix, iy, iz)
      if is_electrode then
        open = false
        break
      end
    end
    if open then
      open_columns = open_columns + 1
    end
  end
end

local guard_electrode_check_passed = true
local guard_electrode_counts = {}
local guard_columns = {
  {iy_min - 1, math.floor((iz_min + iz_max) / 2)},
  {iy_max + 1, math.floor((iz_min + iz_max) / 2)},
  {math.floor((iy_min + iy_max) / 2), iz_min - 1},
  {math.floor((iy_min + iy_max) / 2), iz_max + 1},
}
for guard_index, guard in ipairs(guard_columns) do
  local electrode_count = 0
  local interior_guard_intact = true
  for ix = ix_min, ix_max do
    local _, is_electrode = pa:point(ix, guard[1], guard[2])
    if is_electrode then electrode_count = electrode_count + 1 end
    -- The two flange endpoints join the adjacent vacuum domains, so they are
    -- not a side-wall test.  Every interior node through the flange thickness
    -- must remain electrode, preventing a slit beside the defined aperture.
    if ix > ix_min and ix < ix_max and not is_electrode then
      interior_guard_intact = false
    end
  end
  guard_electrode_counts[guard_index] = electrode_count
  if not interior_guard_intact then
    guard_electrode_check_passed = false
  end
end

local status = open_columns > 0 and guard_electrode_check_passed and 'PASS' or 'FAIL'
local report = assert(io.open(report_path, 'w'))
report:write(string.format(
  '{\n  "schema_version": 1,\n  "role": "simion_compiled_pa_aperture_topology_check",\n' ..
  '  "status": "%s",\n  "candidate_column_count": %d,\n' ..
  '  "open_column_count": %d,\n  "guard_electrode_check_passed": %s,\n' ..
  '  "boolean_boundary_policy": "%s",\n  "index_bounds": {' ..
  '"x": [%d, %d], "y": [%d, %d], "z": [%d, %d]}\n}\n',
  status, candidate_columns, open_columns,
  tostring(guard_electrode_check_passed), boundary_policy,
  ix_min, ix_max, iy_min, iy_max, iz_min, iz_max))
report:close()
print(string.format('APERTURE_TOPOLOGY=%s OPEN_COLUMNS=%d CANDIDATES=%d',
  status, open_columns, candidate_columns))
print(string.format('APERTURE_GUARD_COVERAGE=%d,%d,%d,%d OF %d',
  guard_electrode_counts[1], guard_electrode_counts[2],
  guard_electrode_counts[3], guard_electrode_counts[4], ix_max - ix_min + 1))
assert(status == 'PASS',
  'compiled PA aperture is closed or its surrounding electrode guard is missing')
