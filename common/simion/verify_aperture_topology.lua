-- Repository-wide fail-closed verifier for a rectangular aperture in a compiled PA.
-- The caller supplies physical coordinates; this script checks that at least
-- one integer-node column remains non-electrode through the full flange depth.

local function required_env(name)
  return assert(os.getenv(name), name .. ' is not set')
end

local function required_number(name)
  local raw = required_env(name)
  local value = tonumber(raw)
  assert(value and value == value and math.abs(value) < math.huge,
    name .. ' must be finite and numeric')
  return value
end

local pa_path = required_env('SIMION_APERTURE_PA_PATH')
local report_path = required_env('SIMION_APERTURE_REPORT_PATH')
local origin_x = required_number('SIMION_APERTURE_ORIGIN_X_MM')
local origin_y = required_number('SIMION_APERTURE_ORIGIN_Y_MM')
local origin_z = required_number('SIMION_APERTURE_ORIGIN_Z_MM')
local cell_x_mm = required_number('SIMION_APERTURE_CELL_MM_X')
local cell_y_mm = required_number('SIMION_APERTURE_CELL_MM_Y')
local cell_z_mm = required_number('SIMION_APERTURE_CELL_MM_Z')
local axes = {'x', 'y', 'z'}
local normal_axis = required_env('SIMION_APERTURE_NORMAL_AXIS')
local normal_index
local transverse = {}
for index, axis in ipairs(axes) do
  if axis == normal_axis then normal_index = index
  else transverse[#transverse + 1] = index end
end
assert(normal_index, 'aperture normal axis must be x, y or z')
local origins = {origin_x, origin_y, origin_z}
local cells = {cell_x_mm, cell_y_mm, cell_z_mm}
local flange_min = required_number('SIMION_APERTURE_FLANGE_MIN_MM')
local flange_max = required_number('SIMION_APERTURE_FLANGE_MAX_MM')
local centers = {
  required_number('SIMION_APERTURE_CENTER_X_MM'),
  required_number('SIMION_APERTURE_CENTER_Y_MM'),
  required_number('SIMION_APERTURE_CENTER_Z_MM'),
}
local width_mm = required_number('SIMION_APERTURE_WIDTH_MM')
local height_mm = required_number('SIMION_APERTURE_HEIGHT_MM')
local boundary_policy = required_env('SIMION_APERTURE_BOOLEAN_BOUNDARY_POLICY')

assert(cell_x_mm > 0 and cell_y_mm > 0 and cell_z_mm > 0
    and width_mm >= cells[transverse[1]] and height_mm >= cells[transverse[2]],
  'aperture dimensions must each be at least one positive PA cell')
assert(flange_max >= flange_min, 'flange bounds are reversed')
assert(boundary_policy == 'exclude_shape_inside_or_on_v1'
    or boundary_policy == 'exclude_shape_inside_only_v1',
  'unsupported aperture Boolean boundary policy')

local pa = assert(simion.pas:open(pa_path), 'could not open compiled aperture PA')
local epsilon = 1e-9
local function lower_index(value, origin, cell_mm)
  return math.ceil((value - origin) / cell_mm - epsilon)
end
local function upper_index(value, origin, cell_mm)
  return math.floor((value - origin) / cell_mm + epsilon)
end

-- Traverse logical (normal, width, height) coordinates, then permute the
-- indices into the actual PA axes. No geometry or PA is rotated for this audit.
local n, u, v = normal_index, transverse[1], transverse[2]
local ix_min = lower_index(flange_min, origins[n], cells[n])
local ix_max = upper_index(flange_max, origins[n], cells[n])
local iy_min = lower_index(centers[u] - width_mm / 2, origins[u], cells[u])
local iy_max = upper_index(centers[u] + width_mm / 2, origins[u], cells[u])
local iz_min = lower_index(centers[v] - height_mm / 2, origins[v], cells[v])
local iz_max = upper_index(centers[v] + height_mm / 2, origins[v], cells[v])
local sizes = {pa.nx, pa.ny, pa.nz}
assert(ix_min >= 0 and iy_min >= 0 and iz_min >= 0
    and ix_max < sizes[n] and iy_max < sizes[u] and iz_max < sizes[v],
  'aperture topology check bounds lie outside the compiled PA')
assert(ix_min <= ix_max and iy_min <= iy_max and iz_min <= iz_max,
  'aperture topology check has no integer-node column')
assert(iy_min > 0 and iz_min > 0 and iy_max + 1 < sizes[u] and iz_max + 1 < sizes[v],
  'aperture surrounding guard samples lie outside the compiled PA')
local function point(normal, width, height)
  local indices = {}
  indices[n], indices[u], indices[v] = normal, width, height
  return pa:point(indices[1], indices[2], indices[3])
end

local open_columns = 0
local candidate_columns = 0
for iy = iy_min, iy_max do
  for iz = iz_min, iz_max do
    candidate_columns = candidate_columns + 1
    local open = true
    for ix = ix_min, ix_max do
      local _, is_electrode = point(ix, iy, iz)
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
    local _, is_electrode = point(ix, guard[1], guard[2])
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
local lower, upper = {}, {}
lower[n], lower[u], lower[v] = ix_min, iy_min, iz_min
upper[n], upper[u], upper[v] = ix_max, iy_max, iz_max
local report = assert(io.open(report_path, 'w'))
report:write(string.format(
  '{\n  "schema_version": 2,\n  "role": "simion_compiled_pa_aperture_topology_check",\n' ..
  '  "normal_axis": "%s",\n  "status": "%s",\n  "candidate_column_count": %d,\n' ..
  '  "open_column_count": %d,\n  "guard_electrode_check_passed": %s,\n' ..
  '  "boolean_boundary_policy": "%s",\n  "index_bounds": {' ..
  '"x": [%d, %d], "y": [%d, %d], "z": [%d, %d]}\n}\n',
  normal_axis, status, candidate_columns, open_columns,
  tostring(guard_electrode_check_passed), boundary_policy,
  lower[1], upper[1], lower[2], upper[2], lower[3], upper[3]))
report:close()
print(string.format('APERTURE_TOPOLOGY=%s OPEN_COLUMNS=%d CANDIDATES=%d',
  status, open_columns, candidate_columns))
print(string.format('APERTURE_GUARD_COVERAGE=%d,%d,%d,%d OF %d',
  guard_electrode_counts[1], guard_electrode_counts[2],
  guard_electrode_counts[3], guard_electrode_counts[4], ix_max - ix_min + 1))
assert(status == 'PASS',
  'compiled PA aperture is closed or its surrounding electrode guard is missing')
