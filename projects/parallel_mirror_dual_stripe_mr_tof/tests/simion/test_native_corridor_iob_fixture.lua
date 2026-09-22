-- Tiny inputs and independent reload assertions for the production IOB builder.
local root = assert(arg[1], 'fixture directory required')
local mode = assert(arg[2], 'prepare or inspect required')
local function path(name) return root .. '/' .. name end
local function write(name, text)
  local file = assert(io.open(path(name), 'wb'))
  file:write(text); file:close()
end
if mode == 'prepare' then
  for _, item in ipairs({{'global.pa', 11}, {'accelerator.pa', 3}, {'detector.pa', 3}}) do
    local pa = assert(simion.pas:open())
    pa:size(item[2], 11, 11)
    pa.dx_mm, pa.dy_mm, pa.dz_mm = 1, 1, 1
    pa.potential_type = 'electric'
    pa.refined, pa.refinable = true, false
    pa:save(path(item[1])); pa:close()
  end
  write('program.lua', 'simion.workbench_program()\n')
  write('program.mirror_cycle_counter.lua', 'return {}\n')
  write('source.fly2', 'particles { standard_beam { n = 1, mass = 100, charge = 1, ke = 1, position = vector(5,5,5), direction = vector(1,0,0) } }\n')
  write('operating.lua', 'return {}\n')
  write('voltage_map.lua', [[return function()
    local groups = {{2,7},{3,8},{4,9},{5,10},{11,12},{13,14},{16},{17}}
    local values = {}
    for local_id, ids in ipairs(groups) do
      for _, id in ipairs(ids) do values[id] = 100 * local_id end
    end
    return {analyser=values}
  end
]])
  print('NATIVE_CORRIDOR_IOB_FIXTURE_INPUT=PASS')
elseif mode == 'inspect' then
  local wb = assert(simion.wb)
  wb:load(path('fixture.iob'))
  assert(#wb.instances == 4, 'saved builder output must have four instances')
  local corridor = wb.instances[2].pa
  local mapping = assert(loadfile(path('voltage_map.lua')))()({})
  local priority = assert(loadfile(path('fixture.priority.lua')))()
  local values = {}
  for id, physical_ids in ipairs(priority.corridor_voltage_groups) do
    values[id] = mapping.analyser[physical_ids[1]]
  end
  corridor:fast_adjust(values)
  for id = 1, 8 do
    assert(math.abs(corridor:potential(id - 1, 0, 0) - 100 * id) < 1e-6,
      'saved IOB Fast Adjust voltage differs for local electrode ' .. id)
  end
  for _, item in ipairs({{5,2},{1,3},{9,4}}) do
    local _, instance = wb:find_at(item[1], 5, 5)
    assert(instance == item[2], 'saved IOB priority differs')
  end
  print('NATIVE_CORRIDOR_IOB_FIXTURE_RELOAD=PASS fast_adjust=8 priority=3')
else
  error('unknown fixture mode')
end
