-- Pure-Lua event-logic regression: synthetic samples are NOT flight evidence.
local counter = assert(loadfile('projects/parallel_mirror_dual_stripe_mr_tof/simion/mirror_cycle_counter.lua'))()
local regions = {negative={z_min_mm=-20,z_max_mm=-10}, positive={z_min_mm=10,z_max_mm=20}}
local passed = 0
local function test(name, check)
  check(); passed = passed + 1; print('PASS '..name)
end
local function count(events, kind)
  local n = 0
  for _, event in ipairs(events) do if event.kind == kind then n = n + 1 end end
  return n
end
local function driver()
  local c, t, all = counter.new(regions, 1), 0, {}
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

test('positive turn is phase origin and same-side turn completes a cycle', function()
  local c, step, events = driver()
  local origin = arm_and_origin(step)
  assert(count(origin, 'drift_phase_origin') == 1)
  assert(c:state().stage == 'main_drift' and c:state().cycles == 0)
  mirror(step, -1, 1, 10)
  local returned = mirror(step, 1, 1, 20)
  assert(count(returned, 'completed_oscillation') == 1)
  assert(c:state().cycles == 1 and c:state().half_cycles == 2)
  assert(count(events, 'drift_phase_origin') == 1)
end)

test('negative slow velocity alone cannot claim a phase return', function()
  local c, step, events = driver()
  arm_and_origin(step, 0)
  mirror(step, -1, 1, 100)
  local returned = mirror(step, 1, -1, 0.25)
  assert(count(returned, 'drift_phase_candidate') == 1)
  assert(count(returned, 'drift_phase_return') == 0)
  assert(c:state().stage == 'main_drift' and c:state().cycles == 1)
  local coordinate = step(5, -1, nil, -0.25, -1)
  assert(count(coordinate, 'drift_coordinate_return') == 1)
  local found
  for _, event in ipairs(events) do if event.kind == 'drift_coordinate_return' then found = event end end
  assert(found.k_before == 1 and found.phase_turn_y_mm == 0.25)
  assert(found.phase_period_us > 0 and found.fractional_k > 1)
  assert(found.y_mm == 0 and found.vy_mm_us == -1)
  assert(c:state().stage == 'after_main_drift'
    and c:state().phase == 'coordinate_return_without_phase_closure')
end)

test('only exact y zero at the same-side turn closes phase', function()
  local c, step = driver()
  arm_and_origin(step, 0)
  mirror(step, -1, 1, 100)
  local returned = mirror(step, 1, -1, 0)
  assert(count(returned, 'drift_phase_candidate') == 1)
  assert(count(returned, 'drift_phase_return') == 1)
  assert(c:state().stage == 'after_main_drift' and c:state().cycles == 1)
end)

test('twenty-six origin-side returns have no hidden K limit', function()
  local c, step = driver()
  arm_and_origin(step)
  for cycle = 1, 26 do
    mirror(step, -1, 1); mirror(step, 1, 1)
    assert(c:state().cycles == cycle)
  end
  assert(c:state().cycles == 26 and c:state().stage == 'main_drift')
end)

test('central crossings are diagnostics and never define phase', function()
  local c, step, events = driver()
  arm_and_origin(step)
  step(0, -1, nil, -1, 1); step(-1, -1, nil, -2, 1)
  assert(count(events, 'central_plane') == 1)
  assert(c:state().cycles == 0 and c:state().phase == 'awaiting_opposite_turn')
end)

test('armed origin must be the declared outbound mirror turn', function()
  local c, step = driver()
  step(-1, -1, 'arm_main_drift', 5, 1); mirror(step, -1, 1)
  assert(not c:state().sequence_valid)
  local n, advance = driver()
  advance(1, 1, 'arm_main_drift', 5, 1); mirror(advance, 1, -1)
  assert(not n:state().sequence_valid)
end)

test('zero velocity without reversal is not a turn', function()
  local c, step = driver()
  step(1, 1, 'arm_main_drift', 5, 1)
  step(11, 1); step(12, 0); step(13, 1)
  assert(c:state().origin_turns == 0 and c:state().stage == 'armed_main_drift')
end)

test('same-side repeated reflection fails closed', function()
  local c, step = driver()
  arm_and_origin(step); step(11, 1); mirror(step, 1, 1)
  assert(not c:state().sequence_valid and c:state().cycles == 0)
end)

test('outside-mirror reversal fails an armed path', function()
  local c, step, events = driver()
  step(1, 1, 'arm_main_drift', 5, 1); step(3, 1); step(4, -1)
  assert(count(events, 'nonmirror_reversal') == 1)
  assert(not c:state().sequence_valid and c:state().origin_turns == 0)
end)

test('linear turn brackets interpolate coordinates and time', function()
  local c = counter.new(regions, 1)
  c:arm_main_drift({x_mm=0,y_mm=2,z_mm=1,vx_mm_us=0,vy_mm_us=1,vz_mm_us=2,t_us=0})
  c:sample({x_mm=1,y_mm=1,z_mm=11,vx_mm_us=0,vy_mm_us=1,vz_mm_us=2,t_us=1})
  local events = c:sample({x_mm=3,y_mm=-1,z_mm=13,vx_mm_us=0,vy_mm_us=1,vz_mm_us=-2,t_us=3})
  assert(events[1].kind == 'mirror_turn' and events[1].t_us == 2)
  assert(events[1].x_mm == 2 and events[1].y_mm == 0 and events[1].z_mm == 12)
  assert(events[1].vz_mm_us == 0)
end)

test('post-return reflections remain diagnostics and do not change K', function()
  local c, step = driver()
  arm_and_origin(step); mirror(step, -1, 1); mirror(step, 1, -1)
  local cycles = c:state().cycles
  mirror(step, -1, -1)
  assert(c:state().cycles == cycles and c:state().post_main_turns == 1)
end)

test('per-particle counters do not share state', function()
  local c, step = driver(); local other, advance = driver()
  arm_and_origin(step); mirror(step, -1, 1); mirror(step, 1, 1)
  advance(1, 1, 'arm_main_drift', 5, 1)
  assert(c:state().cycles == 1 and other:state().cycles == 0)
end)

test('invalid contracts times and rearm fail closed', function()
  assert(not pcall(counter.new, nil, 1))
  assert(not pcall(counter.new, {positive={z_min_mm=-1,z_max_mm=1},negative=regions.negative}, 1))
  assert(not pcall(counter.new, regions, 0))
  local c, step = driver()
  assert(not pcall(c.sample, c, {z_mm=0,vz_mm_us=1,t_us=0}))
  step(1, 1, 'arm_main_drift', 5, 1)
  assert(not pcall(c.arm_main_drift, c, {x_mm=0,y_mm=4,z_mm=-2,vx_mm_us=0,vy_mm_us=-1,vz_mm_us=-1,t_us=2}))
  assert(not pcall(c.sample, c, {x_mm=0,y_mm=4,z_mm=-2,vx_mm_us=0,vy_mm_us=-1,vz_mm_us=-1,t_us=0}))
end)

print(string.format('PASS mirror_cycle_counter: %d synthetic turn-phase tests; no solver flight', passed))
