-- Pure-Lua event-logic regression: synthetic samples are NOT flight evidence.
-- Run from repository root with a stock Lua interpreter, without SIMION.
local counter = assert(loadfile('projects/parallel_mirror_dual_stripe_mr_tof/simion/mirror_cycle_counter.lua'))()
local regions = {negative={z_min_mm=-20,z_max_mm=-10}, positive={z_min_mm=10,z_max_mm=20}}
local passed = 0
local function test(name, check)
  check()
  passed = passed + 1
  print('PASS '..name)
end
local function count(events, kind)
  local n = 0
  for _, event in ipairs(events) do if event.kind == kind then n = n + 1 end end
  return n
end
local function driver()
  local c, t, all = counter.new(regions), 0, {}
  local function step(z, vz, method)
    t = t + 1
    local events = c[method or 'sample'](c, {x_mm=t/10,y_mm=t/5,z_mm=z,vz_mm_us=vz,t_us=t})
    for _, event in ipairs(events) do all[#all + 1] = event end
    return events
  end
  return c, step, all
end
local function mirror(step, side)
  step(11*side, side)
  step(12*side, 0)
  return step(12*side, -side)
end

test('50th turn is not cycle 25; following same-direction crossing is', function()
  local c, step, events = driver()
  step(0, 1, 'enter_main_drift')
  for cycle = 1, 25 do
    mirror(step, 1)
    step(0, -1)
    mirror(step, -1)
    assert(c:state().cycles == cycle-1)
    assert(c:state().phase == 'awaiting_second_return')
    assert(c:state().half_cycles == 2*cycle-1)
    assert(c:state().accepted_main_turns == 2*cycle)
    assert(count(step(0, 1), 'completed_oscillation') == 1)
    assert(c:state().cycles == cycle)
  end
  assert(count(events, 'completed_oscillation') == 25)
  assert(c:state().stage == 'main_drift' and c:state().sequence_valid)
end)

test('negative-direction anchor works and entry is explicit for noncentral source', function()
  local c, step = driver()
  step(5, 1)
  mirror(step, 1)
  step(0, -1)
  assert(c:state().cycles == 0 and c:state().pre_main_turns == 1)
  step(-5, -1, 'enter_main_drift')
  mirror(step, -1)
  assert(c:state().accepted_main_turns == 0 and c:state().anchor_direction == nil)
  step(0, 1)
  mirror(step, 1); step(0, -1)
  mirror(step, -1); step(0, 1)
  assert(c:state().cycles == 1 and c:state().pre_main_turns == 1)
  local n, advance = driver()
  advance(0, -1, 'enter_main_drift')
  mirror(advance, -1); advance(0, 1)
  mirror(advance, 1); advance(0, -1)
  assert(n:state().cycles == 1 and n:state().anchor_direction == -1)
end)

test('zero nodes and repeated zero samples do not lose or double-count events', function()
  local c, step, events = driver()
  step(0, 0, 'enter_main_drift'); step(0, 0); step(1, 1)
  step(11, 1); step(12, 0); step(12, 0); step(12, -1)
  step(0, -1); step(0, -1); step(-1, -1)
  step(-11, -1); step(-12, 0); step(-12, 0); step(-12, 1)
  step(0, 1); step(0, 1); step(1, 1)
  assert(c:state().sequence_valid and c:state().cycles == 1)
  assert(count(events, 'mirror_turn') == 2 and count(events, 'poincare_anchor') == 1)
  assert(count(events, 'central_plane') == 3)
end)

test('zero velocity without reversal is not a mirror turn', function()
  local c, step = driver()
  step(0, 1, 'enter_main_drift'); step(11, 1); step(12, 0); step(13, 1)
  assert(c:state().observed_main_turns == 0 and c:state().sequence_valid)
end)

test('touching z=0 then returning to same side is not a crossing', function()
  local c, step, events = driver()
  step(-1, 1); step(0, 0); step(0, 0); step(-1, -1)
  assert(count(events, 'central_plane') == 0 and c:state().cycles == 0)
end)

test('same-side repeated reflection fails closed instead of pairing turns', function()
  local c, step = driver()
  step(0, 1, 'enter_main_drift'); mirror(step, 1)
  step(11, 1); mirror(step, 1)
  step(0, -1); mirror(step, -1); step(0, 1)
  assert(not c:state().sequence_valid and c:state().cycles == 0)
  assert(c:state().accepted_main_turns == 1 and c:state().observed_main_turns == 3)
end)

test('central crossing without both mirrors is invalid', function()
  local c, step = driver()
  step(0, 1, 'enter_main_drift'); step(1, 1); step(-1, -1)
  assert(not c:state().sequence_valid and c:state().cycles == 0)
end)

test('outside-mirror reversal is diagnostic, not a mirror turn', function()
  local c, step, events = driver()
  step(0, 1, 'enter_main_drift'); step(3, 1); step(4, -1)
  assert(count(events, 'mirror_turn') == 0 and count(events, 'nonmirror_reversal') == 1)
  assert(c:state().accepted_main_turns == 0 and c:state().cycles == 0)
end)

test('all resolved mirror depth is valid, not only the outer E electrode', function()
  local c, step = driver()
  step(0, 1, 'enter_main_drift')
  -- Inner-region turns are deliberately far from outer boundary at |z|=20.
  step(10, 1); step(10, -1); step(0, -1)
  step(-10, -1); step(-10, 1); step(0, 1)
  assert(c:state().sequence_valid and c:state().cycles == 1)
end)

test('linear brackets report interpolated coordinates and time', function()
  local c = counter.new(regions)
  c:enter_main_drift({x_mm=0,y_mm=0,z_mm=0,vz_mm_us=2,t_us=0})
  c:sample({x_mm=1,y_mm=2,z_mm=11,vz_mm_us=2,t_us=1})
  local events = c:sample({x_mm=3,y_mm=6,z_mm=13,vz_mm_us=-2,t_us=3})
  assert(#events == 1 and events[1].kind == 'mirror_turn')
  assert(events[1].t_us == 2 and events[1].x_mm == 2 and events[1].y_mm == 4)
  assert(events[1].z_mm == 12 and events[1].vz_mm_us == 0)
  assert(events[1].bracket_start_us == 1 and events[1].bracket_end_us == 3)
  c:sample({x_mm=5,y_mm=10,z_mm=1,vz_mm_us=-2,t_us=4})
  events = c:sample({x_mm=7,y_mm=14,z_mm=-1,vz_mm_us=-2,t_us=6})
  assert(events[1].kind == 'central_plane' and events[1].t_us == 5)
  assert(events[1].z_mm == 0 and events[1].x_mm == 6 and events[1].y_mm == 12)
end)

test('explicit main-drift exit freezes K but preserves partial segment and extra reflections', function()
  local c, step, events = driver()
  step(0, 1, 'enter_main_drift')
  mirror(step, 1); step(0, -1)
  step(-1, -1, 'end_main_drift')
  mirror(step, -1); step(0, 1)
  assert(c:state().stage == 'after_main_drift' and c:state().cycles == 0)
  assert(c:state().half_cycles == 1 and c:state().phase == 'awaiting_second_turn')
  assert(c:state().post_main_turns == 1 and c:state().accepted_main_turns == 1)
  assert(count(events, 'completed_oscillation') == 0)
end)

test('no target-K limit is hidden in the counter', function()
  local c, step = driver()
  step(0, 1, 'enter_main_drift')
  for _ = 1, 26 do
    mirror(step, 1); step(0, -1); mirror(step, -1); step(0, 1)
  end
  assert(c:state().cycles == 26 and c:state().stage == 'main_drift')
end)

test('exit after second turn does not complete the unfinished cycle later', function()
  local c, step = driver()
  step(0, 1, 'enter_main_drift')
  mirror(step, 1); step(0, -1); mirror(step, -1)
  step(-1, 1, 'end_main_drift'); step(0, 1)
  assert(c:state().cycles == 0 and c:state().half_cycles == 1)
  assert(c:state().accepted_main_turns == 2 and c:state().phase == 'awaiting_second_return')
end)

test('entry on an already sampled crossing owns one physical crossing only', function()
  local c = counter.new(regions)
  c:sample({x_mm=0,y_mm=0,z_mm=-1,vz_mm_us=1,t_us=0})
  local sample = {x_mm=0,y_mm=0,z_mm=0,vz_mm_us=1,t_us=1}
  local crossing = c:sample(sample)
  assert(count(crossing, 'central_plane') == 1)
  local entry = c:enter_main_drift(sample)
  assert(count(entry, 'poincare_anchor') == 1 and count(entry, 'central_plane') == 0)
  assert(c:state().central_crossings == 1 and c:state().anchor_direction == 1)
  assert(#c:sample(sample) == 0)
  assert(c:state().central_crossings == 1)
end)

test('per-particle counters and returned state do not share mutable counts', function()
  local c, step = driver()
  local other, other_step = driver()
  step(0, 1, 'enter_main_drift')
  other_step(0, -1, 'enter_main_drift')
  mirror(step, 1); step(0, -1); mirror(step, -1); step(0, 1)
  local snapshot = c:state()
  snapshot.cycles = 100
  assert(c:state().cycles == 1 and other:state().cycles == 0)
  assert(other:state().anchor_direction == -1)
end)

test('missing regions, sample fields, backward time, and implicit re-entry fail closed', function()
  assert(not pcall(counter.new, nil))
  assert(not pcall(counter.new, {positive={z_min_mm=-1,z_max_mm=1},negative=regions.negative}))
  local c, step = driver()
  assert(not pcall(c.sample, c, {z_mm=0,vz_mm_us=1,t_us=0}))
  step(0, 1, 'enter_main_drift')
  assert(not pcall(c.sample, c, {x_mm=0,y_mm=0,z_mm=0,vz_mm_us=1,t_us=0}))
  assert(not pcall(c.enter_main_drift, c, {x_mm=0,y_mm=0,z_mm=0,vz_mm_us=1,t_us=2}))
  assert(not pcall(c.sample, c, {x_mm=0,y_mm=0,z_mm=0,vz_mm_us=1,t_us=1}))
  step(1, 1, 'end_main_drift')
  assert(not pcall(c.enter_main_drift, c, {x_mm=0,y_mm=0,z_mm=0,vz_mm_us=1,t_us=3}))
end)

print(string.format('PASS mirror_cycle_counter: %d synthetic event-logic tests; no solver flight', passed))
