-- Read one contract-owned project-coordinate x-z slice from the four
-- standalone mirror B--E response PAs.  The generated Lua spec owns every
-- geometry, range, path, and response-normalization value used here.
--
-- Usage: simion --nogui lua sample_mirror_l1_response_slice.lua SPEC.lua OUTPUT.csv
--
-- This uses the SIMION 2020 read-only PA APIs documented in the installed
-- docs/simion.chm lua_simion.pas reference: pas:open, PA metadata, point,
-- potential_vc, field_vc, and close.  It never saves, adjusts, or refines a PA.

assert(#arg == 2, 'generated Lua spec and output CSV path required')
local spec_path = assert(arg[1], 'generated Lua spec required')
local output_path = assert(arg[2], 'output CSV path required')
local GROUPS = {'B', 'C', 'D', 'E'}
local CSV_HEADER = table.concat({
  'x_mm', 'z_mm', 'is_electrode',
  'mirror_B_potential_v', 'mirror_B_ex_v_per_mm', 'mirror_B_ey_v_per_mm', 'mirror_B_ez_v_per_mm',
  'mirror_C_potential_v', 'mirror_C_ex_v_per_mm', 'mirror_C_ey_v_per_mm', 'mirror_C_ez_v_per_mm',
  'mirror_D_potential_v', 'mirror_D_ex_v_per_mm', 'mirror_D_ey_v_per_mm', 'mirror_D_ez_v_per_mm',
  'mirror_E_potential_v', 'mirror_E_ex_v_per_mm', 'mirror_E_ey_v_per_mm', 'mirror_E_ez_v_per_mm',
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

local function exact_grid_index(project_coordinate, origin, spacing, label)
  local raw = (project_coordinate - origin) / spacing
  local nearest = math.floor(raw + 0.5)
  assert(math.abs(raw - nearest) <= GRID_TOLERANCE * math.max(1, math.abs(raw)),
    label .. ' must lie on a native PA grid node')
  return nearest
end

local function validate_response_specs(spec)
  assert(type(spec.responses) == 'table' and #spec.responses == #GROUPS,
    'spec must contain exactly four B--E responses')
  local responses = {}
  for index, group in ipairs(GROUPS) do
    local response = spec.responses[index]
    assert(type(response) == 'table' and response.group == group,
      'responses must be ordered exactly B,C,D,E')
    assert(type(response.standalone_pa_path) == 'string' and
      response.standalone_pa_path ~= '', group .. ' standalone PA path required')
    responses[index] = {
      group = group,
      path = response.standalone_pa_path,
      normalization_v = finite(response.normalization_v, group .. ' normalization_v'),
    }
    assert(responses[index].normalization_v > 0, group .. ' normalization_v must be positive')
    if index > 1 then
      assert(responses[index].normalization_v == responses[1].normalization_v,
        'B--E responses must share one normalization_v')
    end
  end
  return responses
end

local function assert_matching_grid(reference, candidate, group)
  assert(candidate.nx == reference.nx and candidate.ny == reference.ny and
    candidate.nz == reference.nz, group .. ' response PA dimensions differ')
  assert(candidate.dx_mm == reference.dx_mm and candidate.dy_mm == reference.dy_mm and
    candidate.dz_mm == reference.dz_mm, group .. ' response PA scales differ')
end

local function assert_node_inside(pa, x, y, z, label)
  assert(x >= 0 and x < pa.nx and y >= 0 and y < pa.ny and z >= 0 and z < pa.nz,
    label .. ' lies outside PA grid')
  assert(pa:inside_vc(x, y, z), label .. ' lies outside PA interpolation domain')
end

local function response_node(response, x, y, z)
  local _, electrode = response.pa:point(x, y, z)
  local potential = finite(response.pa:potential_vc(x, y, z),
    response.group .. ' potential')
  local ex, ey, ez = response.pa:field_vc(x, y, z)
  ex = finite(ex, response.group .. ' ex')
  ey = finite(ey, response.group .. ' ey')
  ez = finite(ez, response.group .. ' ez')
  return electrode and true or false,
    potential,
    ex / response.pa.dx_mm,
    ey / response.pa.dy_mm,
    ez / response.pa.dz_mm
end

local function run()
  local spec = assert(loadfile(spec_path), 'cannot load generated Lua spec')()
  assert(type(spec) == 'table', 'generated Lua spec must return a table')
  assert(spec.schema_version == 1, 'unsupported sampler spec schema_version')
  assert(spec.role == 'mrtof_real_3d_mirror_l1_response_slice', 'unexpected sampler spec role')
  assert(type(spec.project_frame) == 'string' and spec.project_frame ~= '',
    'project_frame required')
  assert(type(spec.region_id) == 'string' and spec.region_id ~= '', 'region_id required')
  local origin = coordinate_table(spec.region_origin_project_mm, 'region_origin_project_mm')
  local slice_y = finite(spec.slice_y_mm, 'slice_y_mm')
  local x_min, x_max = range_table(spec.x_range_mm, 'x_range_mm')
  local z_min, z_max = range_table(spec.z_range_mm, 'z_range_mm')
  local responses = validate_response_specs(spec)

  for index, response in ipairs(responses) do
    response.pa = assert(simion.pas:open(response.path),
      'cannot open ' .. response.group .. ' standalone response PA')
    opened_pas[#opened_pas + 1] = response.pa
    assert(response.pa.dx_mm > 0 and response.pa.dy_mm > 0 and response.pa.dz_mm > 0,
      response.group .. ' response PA scales must be positive')
    if index > 1 then assert_matching_grid(responses[1].pa, response.pa, response.group) end
  end

  local reference = responses[1].pa
  local ix_min = exact_grid_index(x_min, origin.x, reference.dx_mm, 'x_range_mm.min_mm')
  local ix_max = exact_grid_index(x_max, origin.x, reference.dx_mm, 'x_range_mm.max_mm')
  local iy = exact_grid_index(slice_y, origin.y, reference.dy_mm, 'slice_y_mm')
  local iz_min = exact_grid_index(z_min, origin.z, reference.dz_mm, 'z_range_mm.min_mm')
  local iz_max = exact_grid_index(z_max, origin.z, reference.dz_mm, 'z_range_mm.max_mm')
  assert(ix_min <= ix_max and iz_min <= iz_max, 'resolved native grid ranges must be ordered')
  assert_node_inside(reference, ix_min, iy, iz_min, 'minimum requested sample')
  assert_node_inside(reference, ix_max, iy, iz_max, 'maximum requested sample')

  output = assert(io.open(output_path, 'w'), 'cannot open output CSV')
  output:write(CSV_HEADER, '\n')
  local samples, vacuum_samples, electrode_samples = 0, 0, 0
  for iz = iz_min, iz_max do
    local project_z = origin.z + iz * reference.dz_mm
    for ix = ix_min, ix_max do
      local project_x = origin.x + ix * reference.dx_mm
      local values = {}
      local common_mask = nil
      for response_index, response in ipairs(responses) do
        assert_node_inside(response.pa, ix, iy, iz,
          response.group .. ' requested sample')
        local electrode, potential, ex, ey, ez = response_node(response, ix, iy, iz)
        if response_index == 1 then
          common_mask = electrode
        else
          assert(electrode == common_mask,
            'B--E response electrode masks differ at requested native grid node')
        end
        values[#values + 1] = potential
        values[#values + 1] = ex
        values[#values + 1] = ey
        values[#values + 1] = ez
      end
      local mask = common_mask and 1 or 0
      output:write(string.format(
        '%.17g,%.17g,%d,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\n',
        project_x, project_z, mask,
        values[1], values[2], values[3], values[4], values[5], values[6],
        values[7], values[8], values[9], values[10], values[11], values[12],
        values[13], values[14], values[15], values[16]))
      samples = samples + 1
      if common_mask then electrode_samples = electrode_samples + 1
      else vacuum_samples = vacuum_samples + 1 end
    end
  end
  assert(samples > 0, 'requested slice contains no samples')
  output:close()
  output = nil
  print(string.format(
    'MRTOF_MIRROR_L1_RESPONSE_SLICE=PASS region=%s samples=%d vacuum=%d electrode=%d output=%s',
    spec.region_id, samples, vacuum_samples, electrode_samples, output_path))
end

local ok, failure = pcall(run)
if output then pcall(function() output:close() end); output = nil end
for index = #opened_pas, 1, -1 do
  pcall(function() opened_pas[index]:close() end)
end
if not ok then error(failure, 0) end
