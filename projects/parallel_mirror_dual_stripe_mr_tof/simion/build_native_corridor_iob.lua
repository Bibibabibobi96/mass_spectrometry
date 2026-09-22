-- Build the sole native full-flight-corridor Workbench.
--
-- Usage (after --):
--   4_instance_seed GLOBAL_PA0 CORRIDOR_PA0 ACCELERATOR_PA DETECTOR_PA
--   OUTPUT_IOB PROGRAM FLY2 OPERATING_POINT VOLTAGE_MAP PRIORITY_CONTRACT
--   (X Y Z)*4
--
-- Validate the complete local ID 1..8 voltage table here.  The flight applies
-- it once in memory; IOB geometry/priority checks need no Fast Adjust.

local offset = (arg[1] == '--') and 1 or 0
local function input(index, label)
  local value = assert(arg[index + offset], label .. ' required')
  return value
end
local seed = input(1, 'four-instance seed')
local paths = { input(2, 'global PA'), input(3, 'corridor family PA0'),
  input(4, 'accelerator PA'), input(5, 'detector PA') }
local output, program, fly2 = input(6, 'output IOB'), input(7, 'program'), input(8, 'Fly2')
local operating_path, voltage_map_path, priority_path = input(9, 'operating point'), input(10, 'voltage map'), input(11, 'priority contract')
assert(seed:match('4_instance_seed%.iob$'), 'four-instance seed is required')
assert(paths[2]:match('%.pa0$'), 'corridor must be a native .pa0 family controller')
assert(output:match('%.iob$') and program:match('%.lua$') and fly2:match('%.fly2$'), 'invalid output companion suffix')
local origins = {}
for index = 1, 4 do
  origins[index] = {}
  for axis = 1, 3 do
    origins[index][axis] = assert(tonumber(input(11 + (index - 1) * 3 + axis,
      string.format('instance %d origin axis %d', index, axis))), 'origin must be numeric')
  end
end
local priority = assert(dofile(priority_path), 'priority contract is invalid')
assert(priority.role == 'mrtof_native_corridor_iob_priority_contract' and type(priority.instances) == 'table' and #priority.instances == 4,
  'native corridor priority contract is incomplete')
local expected_roles = {'global_fallback', 'native_corridor', 'accelerator', 'detector'}
local role_instances = {}
for index, role in ipairs(expected_roles) do
  local item = priority.instances[index]
  assert(item.role == role and item.priority_number == index,
    string.format('priority contract instance %d must be %s with priority %d', index, role, index))
  assert(role_instances[role] == nil, 'duplicate native corridor instance role: ' .. role)
  role_instances[role] = index
end
local groups = assert(priority.corridor_voltage_groups,
  'native corridor priority contract has no voltage groups')
assert(type(groups) == 'table' and #groups == 8,
  'native corridor priority contract requires exactly eight voltage groups')
for local_id, physical_ids in ipairs(groups) do
  assert(type(physical_ids) == 'table' and #physical_ids > 0,
    'native corridor voltage group is empty for local ID ' .. local_id)
  for _, physical_id in ipairs(physical_ids) do
    assert(type(physical_id) == 'number' and physical_id == math.floor(physical_id)
        and physical_id >= 1,
      'native corridor voltage group contains an invalid physical electrode ID')
  end
end
local operating = assert(loadfile(operating_path), 'operating point sidecar missing')()
local voltage_map = assert(loadfile(voltage_map_path), 'voltage map sidecar missing')()
local voltages = voltage_map(operating.mirror_voltages_v, operating.stripe_biases_v,
  operating.prism_voltages_v, operating.accelerator_voltages_v,
  operating.accelerator_ring_voltages_v, operating.nonaccelerator_scale)
local corridor_values = {}
for local_id, physical_ids in ipairs(groups) do
  local value = voltages.analyser[physical_ids[1]]
  assert(value ~= nil, 'missing physical voltage for corridor local ID ' .. local_id)
  for _, physical_id in ipairs(physical_ids) do
    assert(voltages.analyser[physical_id] == value, 'physical voltage group is not equal for local ID ' .. local_id)
  end
  corridor_values[local_id] = value
end
local function assert_complete_local_voltage_table(values)
  local count = 0
  for key, value in pairs(values) do
    assert(type(key) == 'number' and key == math.floor(key) and key >= 1 and key <= 8,
      'corridor Fast Adjust voltage table contains an unknown local electrode ID: ' .. tostring(key))
    assert(type(value) == 'number' and value == value and math.abs(value) < math.huge,
      'corridor Fast Adjust voltage is not finite for local ID ' .. key)
    count = count + 1
  end
  assert(count == 8, 'corridor Fast Adjust requires exactly local electrode IDs 1..8')
  for local_id = 1, 8 do
    assert(values[local_id] ~= nil,
      'corridor Fast Adjust voltage is missing for local ID ' .. local_id)
  end
  return values
end
assert_complete_local_voltage_table(corridor_values)
local wb = assert(simion.wb, 'SIMION Workbench API unavailable')
assert(wb.load and wb.save and wb.find_at, 'SIMION Workbench load/save/find_at API unavailable')
wb:load(seed)
assert(wb.filename and #wb.instances == 4, 'native corridor IOB must contain exactly four instances')
-- SIMION 2020 exposes the GUI priority primarily through the persisted PAs
-- ordering; it does not expose a documented instance.priority setter.  Probe
-- candidate fields when present, but never treat our contract table as proof.
local priority_field = nil
for _, name in ipairs({'priority', 'priority_number', 'priority_index', 'order'}) do
  local ok, value = pcall(function() return wb.instances[1][name] end)
  if ok and value ~= nil then priority_field = name; break end
end
for index, path in ipairs(paths) do
  local instance = wb.instances[index]
  assert(priority.instances[index].priority_number == index, 'Workbench priority mapping differs from contract')
  instance.pa:load(path)
  assert(instance._debug_update_size, 'SIMION instance-size refresh unavailable')
  instance:_debug_update_size()
  instance.x, instance.y, instance.z = origins[index][1], origins[index][2], origins[index][3]
  instance.az, instance.el, instance.rt, instance.scale = 0, 0, 0, 1
end
-- Saving a Workbench also attempts to save dirty PAs.  Persist its geometry
-- before Fast Adjust so the guarded private controller is never written.
wb:save(output)
-- Reopen the saved IOB and check the explicit role-to-priority binding again.
wb:load(output)
assert(#wb.instances == 4, 'saved native corridor IOB changed instance count')
-- The saved IOB contains geometry, not an adjusted field.  Its flight program
-- applies the complete validated voltage table on the first Fast Adjust call.
for index, item in ipairs(priority.instances) do
  assert(item.priority_number == index, 'saved IOB priority contract mismatch')
  if priority_field then
    local actual = wb.instances[index][priority_field]
    assert(tonumber(actual) == index,
      string.format('SIMION priority field %s mismatch at instance %d: %s',
        priority_field, index, tostring(actual)))
  end
end
local function bounds(instance)
  local pa = assert(instance.pa, 'instance PA is missing')
  return instance.x, instance.y, instance.z,
    instance.x + (pa.nx - 1) * pa.dx_mm * instance.scale,
    instance.y + (pa.ny - 1) * pa.dy_mm * instance.scale,
    instance.z + (pa.nz - 1) * pa.dz_mm * instance.scale
end
local function overlap_probe(label, expected, left_index, right_index)
  local ax0, ay0, az0, ax1, ay1, az1 = bounds(wb.instances[left_index])
  local bx0, by0, bz0, bx1, by1, bz1 = bounds(wb.instances[right_index])
  local x0, y0, z0 = math.max(ax0, bx0), math.max(ay0, by0), math.max(az0, bz0)
  local x1, y1, z1 = math.min(ax1, bx1), math.min(ay1, by1), math.min(az1, bz1)
  assert(x1 > x0 and y1 > y0 and z1 > z0,
    string.format('priority probe has no geometric overlap: %s', label))
  local x, y, z = (x0+x1)/2, (y0+y1)/2, (z0+z1)/2
  local electrode, instance = wb:find_at(x, y, z)
  assert(instance == expected,
    string.format('priority probe %s selected instance=%s expected=%d electrode=%s at %.9g,%.9g,%.9g',
      label, tostring(instance), expected, tostring(electrode), x, y, z))
  print(string.format('MRTOF_NATIVE_CORRIDOR_PRIORITY_PROBE=%s expected=%d actual=%s electrode=%s',
    label, expected, tostring(instance), tostring(electrode)))
end
overlap_probe('global_intersection_corridor', role_instances.native_corridor,
  role_instances.global_fallback, role_instances.native_corridor)
overlap_probe('corridor_intersection_accelerator', role_instances.accelerator,
  role_instances.native_corridor, role_instances.accelerator)
overlap_probe('corridor_intersection_detector', role_instances.detector,
  role_instances.native_corridor, role_instances.detector)
print('MRTOF_NATIVE_CORRIDOR_PRIORITY_API=' .. (priority_field or 'unavailable_documented_setter'))
local function copy(source, target)
  if source == target then return end
  local i = assert(io.open(source, 'rb')); local payload = i:read('*a'); i:close()
  local o = assert(io.open(target, 'wb')); o:write(payload); o:close()
end
copy(program, output:gsub('%.iob$', '.lua'))
copy(fly2, output:gsub('%.iob$', '.fly2'))
copy(priority_path, output:gsub('%.iob$', '.priority.lua'))
copy(operating_path, output:gsub('%.iob$', '.operating_point.lua'))
copy(voltage_map_path, output:gsub('%.iob$', '.voltage_map.lua'))
copy(program:gsub('%.lua$', '.mirror_cycle_counter.lua'),
  output:gsub('%.iob$', '.mirror_cycle_counter.lua'))
print('MRTOF_NATIVE_CORRIDOR_IOB_BUILD=PASS instances=4 corridor_voltage_table_ids=1..8 fast_adjust=flight pa_save=false refine=false priority=probe_verified')
