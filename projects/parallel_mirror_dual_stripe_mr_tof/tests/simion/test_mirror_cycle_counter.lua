-- Pure-Lua event-logic regression: synthetic samples are NOT flight evidence.
local counter = assert(loadfile('projects/parallel_mirror_dual_stripe_mr_tof/simion/mirror_cycle_counter.lua'))()
local regions = {negative={z_min_mm=-20,z_max_mm=-10}, positive={z_min_mm=10,z_max_mm=20}}
local passed = 0
local function test(name, check) check(); passed = passed + 1; print('PASS '..name) end
local function count(events, kind)
  local n = 0
  for _, event in ipairs(events) do if event.kind == kind then n = n + 1 end end
  return n
end
local function driver(target_half_cycles)
  local c, t, all = counter.new(regions, 1, -1, target_half_cycles or 3), 0, {}
  local function step(z, vz, method, y, vy, x)
    t = t + 1
    local sample = {x_mm=x or 0,y_mm=y or 0,z_mm=z,vx_mm_us=0,
      vy_mm_us=vy or -1,vz_mm_us=vz,t_us=t}
    local events = c[method or 'sample'](c, sample)
    for _, event in ipairs(events) do all[#all + 1] = event end
    return events
  end
  return c, step, all
end
local function mirror(step, side, vy, y)
  step(11*side, side, nil, y, vy)
  step(12*side, 0, nil, y, vy)
  return step(12*side, -side, nil, y, vy)
end
local function arm_and_origin(step, y)
  step(1, 1, 'arm_main_drift', -5, 1)
  return mirror(step, 1, 1, y or 0)
end

test('positive mirror turn is phase origin', function()
  local c, step = driver()
  local origin = arm_and_origin(step, 0)
  assert(count(origin, 'drift_phase_origin') == 1)
  assert(c:state().stage == 'main_drift' and c:state().half_cycles == 0)
end)

test('half-integer target returns at opposite mirror turn', function()
  local c, step, events = driver(3)
  arm_and_origin(step, 0)
  mirror(step, -1, 1, 10)
  mirror(step, 1, -1, 5)
  local returned = mirror(step, -1, -1, 0)
  assert(count(returned, 'drift_phase_return') == 1)
  local found
  for _, event in ipairs(events) do if event.kind == 'drift_phase_return' then found = event end end
  assert(found.period_ratio == 1.5 and found.half_cycles == 3 and found.side == -1)
  assert(c:state().stage == 'after_main_drift')
end)

test('target is constructor data rather than a hidden K limit', function()
  local c, step, events = driver(63)
  arm_and_origin(step)
  for half = 1, 63 do mirror(step, half % 2 == 1 and -1 or 1, half < 63 and 1 or -1, half) end
  local found
  for _, event in ipairs(events) do if event.kind == 'drift_phase_return' then found = event end end
  assert(found.period_ratio == 31.5 and c:state().half_cycles == 63)
end)

test('slow y zero is diagnostic and does not terminate phase counting', function()
  local c, step, events = driver(3)
  arm_and_origin(step); mirror(step, -1, 1, 1)
  step(-5, 1, nil, 0.25, -1); step(-4, 1, nil, -0.25, -1)
  assert(count(events, 'drift_coordinate_return') == 1)
  assert(c:state().stage == 'main_drift' and c:state().half_cycles == 1)
end)

test('central crossings are diagnostics only', function()
  local c, step, events = driver(3)
  arm_and_origin(step); step(0, -1, nil, 5, 1)
  assert(count(events, 'central_plane') >= 1 and c:state().half_cycles == 0)
end)

test('same-side repeated reflection fails closed', function()
  local c, step = driver()
  arm_and_origin(step); mirror(step, -1, 1); mirror(step, -1, 1)
  assert(not c:state().sequence_valid)
end)

test('zero velocity without reversal is not a turn', function()
  local c, step = driver()
  step(1, 1, 'arm_main_drift', 5, 1); step(11, 1); step(12, 0); step(13, 1)
  assert(c:state().pre_origin_turns == 0 and c:state().stage == 'armed_main_drift')
end)

test('invalid phase contracts fail closed', function()
  assert(not pcall(counter.new, nil, 1, -1, 51))
  assert(not pcall(counter.new, regions, 1, 1, 51))
  assert(not pcall(counter.new, regions, 1, -1, 50))
  assert(not pcall(counter.new, regions, 1, -1, 0))
end)

print(string.format('PASS mirror_cycle_counter: %d synthetic turn-phase tests; no solver flight', passed))
