-- Sample one project-coordinate x-z slice from five fixed operating PAs.
--
-- Usage: simion --nogui lua sample_fixed_operating_field_slice.lua SPEC.lua OUTPUT.csv
--
-- The generated spec owns paths, local origins, PA mesh, responsibility
-- ranges, and the common output grid.  This script only opens PAs and reads
-- point/potential/field values; it never saves, adjusts, or refines them.

assert(#arg == 2, 'generated Lua spec and output CSV path required')
local spec_path = assert(arg[1], 'generated Lua spec required')
local output_path = assert(arg[2], 'output CSV path required')
local REGION_ORDER = {
  'mirror_turn_negative',
  'stripe_mirror_bridge_negative',
  'central_transport',
  'stripe_mirror_bridge_positive',
  'mirror_turn_positive',
}
local CSV_HEADER = table.concat({
  'region_id', 'source_mesh_x_mm', 'source_mesh_y_mm', 'source_mesh_z_mm',
  'x_mm', 'z_mm', 'is_electrode', 'potential_v',
  'ex_v_per_mm', 'ey_v_per_mm', 'ez_v_per_mm',
}, ',')
local GRID_TOLERANCE = 64 * 2^-52

local opened_pas = {}
local output = nil

local function finite(value, label)
  assert(type(value) == 'number' and value == value and math.abs(value) < math.huge,
    label .. ' must be finite')
  return value
end

local function coordinate_table(value, label)
  assert(type(value) == 'table', label .. ' must be a table')
  return {
    x = finite(value.x, label .. '.x'),
    y = finite(value.y, label .. '.y'),
    z = finite(value.z, label .. '.z'),
  }
end

local function range_table(value, label)
  assert(type(value) == 'table', label .. ' must be a table')
  local minimum = finite(value.min_mm, label .. '.min_mm')
  local maximum = finite(value.max_mm, label .. '.max_mm')
  assert(minimum <= maximum, label .. ' must be ordered')
  return minimum, maximum
end

local function exact_count(lower, upper, spacing, label)
  local raw = (upper - lower) / spacing
  local nearest = math.floor(raw + 0.5)
  assert(math.abs(raw - nearest) <= GRID_TOLERANCE * math.max(1, math.abs(raw)),
    label .. ' must align to the common output grid')
  return nearest
end

local function same_number(left, right)
  return math.abs(left - right) <= GRID_TOLERANCE * math.max(1, math.abs(left), math.abs(right))
end

local function assert_inside(pa, x, y, z, label)
  assert(x >= 0 and x <= pa.nx - 1 and y >= 0 and y <= pa.ny - 1 and
    z >= 0 and z <= pa.nz - 1, label .. ' lies outside PA grid')
  assert(pa:inside_vc(x, y, z), label .. ' lies outside PA interpolation domain')
end

-- A fine common grid can land between nodes of a 0.5-mm PA.  Potential and
-- field use SIMION's native interpolation.  The one canonical geometry mask
-- is conservative: a sample is electrode if any corner of its interpolation
-- cell is electrode.  Thus a trajectory can never cross an ambiguous cell.
local function conservative_electrode_mask(pa, x, y, z)
  local axes = {}
  for index, value in ipairs({x, y, z}) do
    local lower = math.floor(value)
    local upper = math.ceil(value)
    axes[index] = lower == upper and {lower} or {lower, upper}
  end
  for _, ix in ipairs(axes[1]) do
    for _, iy in ipairs(axes[2]) do
      for _, iz in ipairs(axes[3]) do
        local _, electrode = pa:point(ix, iy, iz)
        if electrode then return true end
      end
    end
  end
  return false
end

local function run()
  local spec = assert(loadfile(spec_path), 'cannot load generated Lua spec')()
  assert(type(spec) == 'table', 'generated Lua spec must return a table')
  assert(spec.schema_version == 1, 'unsupported sampler spec schema_version')
  assert(spec.role == 'mrtof_fixed_operating_field_slice', 'unexpected sampler spec role')
  assert(type(spec.project_frame) == 'string' and spec.project_frame ~= '',
    'project_frame required')
  local slice_y = finite(spec.slice_y_mm, 'slice_y_mm')
  local sample_step = finite(spec.sample_step_mm, 'sample_step_mm')
  assert(sample_step > 0, 'sample_step_mm must be positive')
  local x_min, x_max = range_table(spec.x_range_mm, 'x_range_mm')
  assert(type(spec.regions) == 'table' and #spec.regions == #REGION_ORDER,
    'spec must contain exactly five operating PA regions')

  local regions = {}
  local previous_max = nil
  for index, expected_id in ipairs(REGION_ORDER) do
    local source = spec.regions[index]
    assert(type(source) == 'table' and source.region_id == expected_id,
      'regions must use canonical five-region order')
    assert(type(source.standalone_pa_path) == 'string' and source.standalone_pa_path ~= '',
      expected_id .. ' standalone PA path required')
    local origin = coordinate_table(source.region_origin_project_mm,
      expected_id .. '.region_origin_project_mm')
    local mesh = coordinate_table(source.mesh_mm_per_gu, expected_id .. '.mesh_mm_per_gu')
    assert(mesh.x > 0 and mesh.y > 0 and mesh.z > 0, expected_id .. ' mesh must be positive')
    local z_min, z_max = range_table(source.z_range_mm, expected_id .. '.z_range_mm')
    if previous_max then
      assert(same_number(z_min, previous_max + sample_step),
        'region responsibilities must be contiguous without overlap')
    end
    exact_count(z_min, z_max, sample_step, expected_id .. ' z_range_mm')
    previous_max = z_max
    local pa = assert(simion.pas:open(source.standalone_pa_path),
      'cannot open ' .. expected_id .. ' standalone operating PA')
    opened_pas[#opened_pas + 1] = pa
    assert(same_number(pa.dx_mm, mesh.x) and same_number(pa.dy_mm, mesh.y) and
      same_number(pa.dz_mm, mesh.z), expected_id .. ' declared mesh differs from PA metadata')
    regions[index] = {
      region_id = expected_id, origin = origin, mesh = mesh,
      z_min = z_min, z_max = z_max, pa = pa,
    }
  end

  local x_count = exact_count(x_min, x_max, sample_step, 'x_range_mm')
  output = assert(io.open(output_path, 'w'), 'cannot open output CSV')
  output:write(CSV_HEADER, '\n')
  local samples, vacuum_samples, electrode_samples = 0, 0, 0
  for _, region in ipairs(regions) do
    local z_count = exact_count(region.z_min, region.z_max, sample_step,
      region.region_id .. ' responsibility')
    for iz = 0, z_count do
      local project_z = region.z_min + iz * sample_step
      for ix = 0, x_count do
        local project_x = x_min + ix * sample_step
        local local_x = (project_x - region.origin.x) / region.mesh.x
        local local_y = (slice_y - region.origin.y) / region.mesh.y
        local local_z = (project_z - region.origin.z) / region.mesh.z
        assert_inside(region.pa, local_x, local_y, local_z,
          region.region_id .. ' requested sample')
        local potential = finite(region.pa:potential_vc(local_x, local_y, local_z),
          region.region_id .. ' potential')
        local ex, ey, ez = region.pa:field_vc(local_x, local_y, local_z)
        ex = finite(ex, region.region_id .. ' ex') / region.mesh.x
        ey = finite(ey, region.region_id .. ' ey') / region.mesh.y
        ez = finite(ez, region.region_id .. ' ez') / region.mesh.z
        local electrode = conservative_electrode_mask(region.pa, local_x, local_y, local_z)
        output:write(string.format(
          '%s,%.17g,%.17g,%.17g,%.17g,%.17g,%d,%.17g,%.17g,%.17g,%.17g\n',
          region.region_id, region.mesh.x, region.mesh.y, region.mesh.z,
          project_x, project_z, electrode and 1 or 0, potential, ex, ey, ez))
        samples = samples + 1
        if electrode then electrode_samples = electrode_samples + 1
        else vacuum_samples = vacuum_samples + 1 end
      end
    end
  end
  assert(samples > 0, 'requested slice contains no samples')
  output:close()
  output = nil
  print(string.format(
    'MRTOF_FIXED_OPERATING_FIELD_SLICE=PASS samples=%d vacuum=%d electrode=%d output=%s',
    samples, vacuum_samples, electrode_samples, output_path))
end

local ok, failure = pcall(run)
if output then pcall(function() output:close() end); output = nil end
for index = #opened_pas, 1, -1 do
  pcall(function() opened_pas[index]:close() end)
end
if not ok then error(failure, 0) end
