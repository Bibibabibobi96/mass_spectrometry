-- Full MR-TOF Candidate workbench program.  Candidate/prototype only.
simion.workbench_program()
-- Native SIMION 2020 regression: retain terminal callbacks outside every PA.
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local operating_point_path = assert(program_path:gsub('%.lua$', '.operating_point.lua'))
local operating_point = assert(loadfile(operating_point_path), 'missing run-local operating-point sidecar: '..operating_point_path)()
local voltage_map_path = program_path:gsub('%.lua$', '.voltage_map.lua')
local voltage_map = assert(loadfile(voltage_map_path), 'missing run-local voltage mapper: '..voltage_map_path)()
local cycle_counter_path = program_path:gsub('%.lua$', '.mirror_cycle_counter.lua')
local mirror_cycle_counter = assert(loadfile(cycle_counter_path), 'missing run-local mirror-cycle counter: '..cycle_counter_path)()
local mirror_voltages = assert(operating_point.mirror_voltages_v, 'operating point has no mirror-voltage table')
assert(#mirror_voltages == 5 and mirror_voltages[1] == 0,
  'operating point must contain five mirror voltages with grounded A')
local detector_box = assert(operating_point.detector_box_mm, 'operating point has no numerical detector box')
local first_prism_l0 = assert(operating_point.first_prism_l0, 'operating point has no frozen P1 interface')
local mirror_regions = assert(operating_point.mirror_regions_project, 'operating point has no resolved mirror regions')
local prism_regions = assert(operating_point.prism_regions_project, 'operating point has no resolved prism regions')
local phase_origin_mirror_side = assert(operating_point.phase_origin_mirror_side,
  'operating point has no path-derived phase-origin mirror side')
assert(phase_origin_mirror_side == -1 or phase_origin_mirror_side == 1,
  'phase-origin mirror side must be -1 or +1')
assert(operating_point.detector_normal_project == '+z', 'detector must face project +z')
local target_oscillation_count = assert(operating_point.target_oscillation_count, 'operating point has no target oscillation count')
local stripe_biases = assert(operating_point.stripe_biases_v, 'operating point has no Stripe-bias table')
local prism_voltages = assert(operating_point.prism_voltages_v, 'operating point has no prism-voltage table')
local accelerator_voltages = assert(operating_point.accelerator_voltages_v, 'operating point has no accelerator-voltage table')
local accelerator_ring_voltages = assert(operating_point.accelerator_ring_voltages_v, 'operating point has no accelerator-ring voltage table')
assert(#detector_box == 6 and detector_box[1] < detector_box[4]
  and detector_box[2] < detector_box[5] and detector_box[3] < detector_box[6],
  'numerical detector box must be positive')
assert(type(first_prism_l0.target_plane_z_mm) == 'number', 'P1 interface needs a z plane')
assert(#stripe_biases == 2 and #prism_voltages == 2 and #accelerator_voltages == 3 and #accelerator_ring_voltages == 5,
  'operating point requires two Stripe, two prism, three endpoint, and five stage-2 ring voltages')
for index,value in ipairs(prism_voltages) do
  assert(type(value)=='number' and value==value and math.abs(value)<math.huge,
    'prism voltage '..index..' must be finite')
end
assert(target_oscillation_count > 0 and target_oscillation_count == math.floor(target_oscillation_count),
  'target oscillation count must be a positive integer')
-- The contract declares a +z-facing active surface, not the slab midplane.
-- Only incidence from its +z side is a detector hit; the back remains material.
local detector_z = detector_box[6]

adjustable V_stripe_1 = stripe_biases[1]
adjustable V_stripe_2 = stripe_biases[2]
adjustable V_prism_1 = prism_voltages[1]
adjustable V_prism_2 = prism_voltages[2]
adjustable V_repeller = accelerator_voltages[1]
adjustable V_grid1 = accelerator_voltages[2]
adjustable V_grid2 = accelerator_voltages[3]
adjustable V_nonaccelerator_scale = operating_point.nonaccelerator_scale
adjustable trajectory_quality = operating_point.trajectory_quality
adjustable maximum_step_us = operating_point.maximum_step_us
local runtime_fast_adjust_requested = operating_point.runtime_fast_adjust_enable
assert(runtime_fast_adjust_requested == nil or type(runtime_fast_adjust_requested) == 'boolean',
  'runtime_fast_adjust_enable must be boolean when present')
local runtime_fast_adjust_accelerator_requested = operating_point.runtime_fast_adjust_accelerator_enable
assert(runtime_fast_adjust_accelerator_requested == nil
  or type(runtime_fast_adjust_accelerator_requested) == 'boolean',
  'runtime_fast_adjust_accelerator_enable must be boolean when present')
-- Ordinary reviewed flights consume an already voltageized PA0.  Finite-3-D
-- downstream Jacobian trials instead bind the immutable PA family read-only
-- and apply their run-local Stripe/P1/P2 coordinates in memory.
adjustable runtime_fast_adjust_enable = runtime_fast_adjust_requested and 1 or 0
local full_path_timeout_us = assert(operating_point.full_path_timeout_us, 'operating point has no full-path timeout')
assert(full_path_timeout_us > 0, 'full-path timeout must be positive')
local stop_at_drift_phase_origin = operating_point.stop_at_drift_phase_origin == true
local constrain_x_symmetry_plane = operating_point.constrain_x_symmetry_plane == true

-- `other_actions` is called for every integration segment.  Keep the prior
-- state in scalar arrays rather than allocating a five-field table per step:
-- the latter turns a long, otherwise identical trajectory into hundreds of
-- thousands of Lua allocations and GC cycles.
local previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
local turns, slow_turns, crossings, y0_crossings, p1_crossings, detected, splat_codes, splat_event_emitted = {}, {}, {}, {}, {}, {}, {}, {}
local cycle_counters, target_k_emitted = {}, {}
local prism_stage = {}

local function inside_region(event, region)
  return event.y_mm >= region.y_min_mm and event.y_mm <= region.y_max_mm
    and event.z_mm >= region.z_min_mm and event.z_mm <= region.z_max_mm
end

local function cycle_sample(x, y, z, vx, vy, vz, t)
  return {x_mm=x, y_mm=y, z_mm=z, vx_mm_us=vx, vy_mm_us=vy, vz_mm_us=vz, t_us=t}
end

local function interpolated_sample(a, b, fraction)
  return cycle_sample(
    a.x_mm + fraction*(b.x_mm-a.x_mm),
    a.y_mm + fraction*(b.y_mm-a.y_mm),
    a.z_mm + fraction*(b.z_mm-a.z_mm),
    a.vx_mm_us + fraction*(b.vx_mm_us-a.vx_mm_us),
    a.vy_mm_us + fraction*(b.vy_mm_us-a.vy_mm_us),
    a.vz_mm_us + fraction*(b.vz_mm_us-a.vz_mm_us),
    a.t_us + fraction*(b.t_us-a.t_us))
end

local function emit_cycle_events(events)
  for _,event in ipairs(events) do
    if event.kind == 'mirror_turn' then
      -- The manufactured injection path contains one real negative-mirror
      -- pre-reflection between P1 and P2.  A prism refracts the ray; it must
      -- never be identified from a v_z sign reversal.
      if event.stage == 'before_main_drift' and event.side == -1
        and prism_stage[ion_number] == 'p1_complete' then
        prism_stage[ion_number] = 'awaiting_p2_entry'
        print(string.format('MRTOF_EVENT pre_injection_mirror_turn ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, event.t_us, event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      end
      if event.accepted then
        local n = event.is_phase_origin and 0 or event.half_cycles + 1
        print(string.format('MRTOF_EVENT turn ion=%d n=%d t_us=%.12g z_mm=%.12g',
          ion_number, n, event.t_us, event.z_mm))
        print(string.format('MRTOF_EVENT fast_turn ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, n, event.t_us, event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      end
    elseif event.kind == 'drift_phase_origin' then
      print(string.format('MRTOF_EVENT drift_phase_origin ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.t_us, event.x_mm, event.y_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      if stop_at_drift_phase_origin and ion_splat == 0 then
        splat_codes[ion_number] = 5
        splat_event_emitted[ion_number] = true
        print(string.format('MRTOF_EVENT splat ion=%d code=5 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
          ion_number, event.t_us, event.x_mm, event.y_mm, event.z_mm,
          turns[ion_number] or 0, crossings[ion_number] or 0))
        ion_splat = 5
      end
    elseif event.kind == 'drift_phase_candidate' then
      print(string.format('MRTOF_EVENT drift_phase_candidate ion=%d k=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.k, event.t_us, event.x_mm, event.y_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      if event.k == target_oscillation_count then
        print(string.format('MRTOF_EVENT target_k_phase_sample ion=%d k=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, event.k, event.t_us, event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      end
    elseif event.kind == 'drift_phase_return' then
      print(string.format('MRTOF_EVENT drift_phase_return ion=%d k=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.k, event.t_us, event.x_mm, event.y_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      if event.k == target_oscillation_count and not target_k_emitted[ion_number] then
        target_k_emitted[ion_number] = true
        print(string.format('MRTOF_EVENT target_k ion=%d k=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
          ion_number, event.k, event.t_us, event.x_mm, event.y_mm, event.z_mm))
      end
    elseif event.kind == 'slow_coordinate' then
      y0_crossings[ion_number] = (y0_crossings[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT slow_coordinate_y0 ion=%d n=%d direction_y=%d t_us=%.12g x_mm=%.12g y_mm=0 z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, y0_crossings[ion_number], event.direction,
        event.t_us, event.x_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
    elseif event.kind == 'drift_coordinate_return' then
      print(string.format('MRTOF_EVENT drift_coordinate_return ion=%d k_before=%d fractional_k=%.12g phase_turn_t_us=%.12g phase_turn_y_mm=%.12g phase_time_residual_us=%.12g phase_period_us=%.12g t_us=%.12g x_mm=%.12g y_mm=0 z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.k_before, event.fractional_k, event.phase_turn_t_us, event.phase_turn_y_mm,
        event.phase_time_residual_us, event.phase_period_us, event.t_us, event.x_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
    elseif event.kind == 'central_plane' and event.stage == 'main_drift' then
      crossings[ion_number] = (crossings[ion_number] or 0) + 1
      local n = crossings[ion_number]
      print(string.format('MRTOF_EVENT central_plane ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g',
        ion_number, n, event.t_us, event.x_mm, event.y_mm))
      print(string.format('MRTOF_EVENT central_plane_directional ion=%d n=%d direction_z=%d t_us=%.12g x_mm=%.12g y_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, n, event.direction, event.t_us, event.x_mm, event.y_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
    end
  end
  local state = cycle_counters[ion_number]:state()
  turns[ion_number] = state.accepted_main_turns
  return state
end

function segment.initialize_run()
  sim_trajectory_quality = trajectory_quality
  previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
  turns, slow_turns, crossings, y0_crossings, p1_crossings, detected, splat_codes, splat_event_emitted = {}, {}, {}, {}, {}, {}, {}, {}
  cycle_counters, target_k_emitted = {}, {}
  prism_stage = {}
  assert(simion.wb and #simion.wb.instances == 3,
    'MR-TOF Candidate flight requires analyser, accelerator, and detector instances')
  assert(simion.wb.instances[1].filename:match('mrtof_analyzer%.pa0$'), 'instance 1 must be analyser PA0')
  assert(simion.wb.instances[2].filename:match('mrtof_accelerator%.pa0$'), 'instance 2 must be accelerator PA0')
  assert(simion.wb.instances[3].filename:match('mrtof_detector%.pa#$'), 'instance 3 must be raw zero-voltage detector PA#')
  print('MRTOF_CANDIDATE: status=prototype geometry=three_component_3d')
end

function segment.fast_adjust()
  if runtime_fast_adjust_enable == 0 then return end
  local analyser=simion.wb.instances[1].pa
  local accelerator=simion.wb.instances[2].pa
  local values=voltage_map(mirror_voltages,{V_stripe_1,V_stripe_2},{V_prism_1,V_prism_2},
    {V_repeller,V_grid1,V_grid2},accelerator_ring_voltages,V_nonaccelerator_scale)
  analyser:fast_adjust(values.analyser)
  if runtime_fast_adjust_accelerator_requested then accelerator:fast_adjust(values.accelerator) end
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.accel_adjust()
  if constrain_x_symmetry_plane then ion_ax_mm = 0 end
end

function segment.initialize()
  -- Retain the release state so a first-step plane crossing is not omitted.
  if previous_z[ion_number] == nil then
    previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
    previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight
    cycle_counters[ion_number] = mirror_cycle_counter.new(mirror_regions, phase_origin_mirror_side)
    prism_stage[ion_number] = 'awaiting_p1_exit'
    emit_cycle_events(cycle_counters[ion_number]:sample(cycle_sample(
      ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight)))
  end
end

function segment.other_actions()
  if constrain_x_symmetry_plane then
    ion_px_mm, ion_vx_mm = 0, 0
  end
  if ion_time_of_flight >= full_path_timeout_us and ion_splat == 0 then
    splat_codes[ion_number] = 2
    print(string.format('MRTOF_EVENT splat ion=%d code=2 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
      ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
      turns[ion_number] or 0, crossings[ion_number] or 0))
    splat_event_emitted[ion_number] = true
    ion_splat = 2
    return
  end
  -- SIMION exposes ion_splat while stepping, but not in terminate.  Cache the
  -- nonzero termination reason here so every loss remains explicit.
  if ion_splat ~= 0 then
    splat_codes[ion_number] = ion_splat
    if not splat_event_emitted[ion_number] then
      splat_event_emitted[ion_number] = true
      print(string.format('MRTOF_EVENT splat ion=%d code=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
        ion_number, ion_splat, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
        turns[ion_number] or 0, crossings[ion_number] or 0))
    end
  end
  local px, py, pz = previous_x[ion_number], previous_y[ion_number], previous_z[ion_number]
  local pvx, pvy, pvz, pt = previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number]
  if pz ~= nil then
    local counter = cycle_counters[ion_number]
    local state = counter:state()
    local dz = ion_pz_mm - pz
    if pz > first_prism_l0.target_plane_z_mm and ion_pz_mm <= first_prism_l0.target_plane_z_mm then
      local fraction = (first_prism_l0.target_plane_z_mm-pz) / dz
      local vz = pvz + fraction*(ion_vz_mm-pvz)
      if vz < 0 then
        p1_crossings[ion_number] = (p1_crossings[ion_number] or 0) + 1
        local p1_crossing = cycle_sample(
          px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py), first_prism_l0.target_plane_z_mm,
          pvx + fraction*(ion_vx_mm-pvx), pvy + fraction*(ion_vy_mm-pvy), vz,
          pt + fraction*(ion_time_of_flight-pt))
        print(string.format('MRTOF_EVENT p1_plane ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, p1_crossings[ion_number], p1_crossing.t_us,
          p1_crossing.x_mm, p1_crossing.y_mm, p1_crossing.z_mm,
          p1_crossing.vx_mm_us, p1_crossing.vy_mm_us, p1_crossing.vz_mm_us))
        if state.stage == 'before_main_drift' and prism_stage[ion_number] == 'awaiting_p1_exit' then
          prism_stage[ion_number] = 'p1_complete'
          print(string.format('MRTOF_EVENT prism_pass ion=%d n=1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
            ion_number, p1_crossing.t_us, p1_crossing.x_mm, p1_crossing.y_mm, p1_crossing.z_mm,
            p1_crossing.vx_mm_us, p1_crossing.vy_mm_us, p1_crossing.vz_mm_us))
        end
      end
    end

    -- P2 is traversed after the physical negative-mirror pre-reflection.
    -- Its grounded shield is open along z, so collision-free entry/exit of
    -- that finite CAD envelope provides a solver-observable passage event.
    local before = cycle_sample(px, py, pz, pvx, pvy, pvz, pt)
    local after = cycle_sample(ion_px_mm, ion_py_mm, ion_pz_mm,
      ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight)
    if dz > 0 and prism_stage[ion_number] == 'awaiting_p2_entry'
      and pz < prism_regions.p2.z_min_mm and ion_pz_mm >= prism_regions.p2.z_min_mm then
      local entry = interpolated_sample(before, after,
        (prism_regions.p2.z_min_mm-pz)/dz)
      if inside_region(entry, prism_regions.p2) then
        prism_stage[ion_number] = 'inside_p2_station'
        print(string.format('MRTOF_EVENT prism_entry ion=%d n=2 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, entry.t_us, entry.x_mm, entry.y_mm, entry.z_mm,
          entry.vx_mm_us, entry.vy_mm_us, entry.vz_mm_us))
      end
    end
    if dz > 0 and prism_stage[ion_number] == 'inside_p2_station'
      and pz < prism_regions.p2.z_max_mm and ion_pz_mm >= prism_regions.p2.z_max_mm then
      local exit = interpolated_sample(before, after,
        (prism_regions.p2.z_max_mm-pz)/dz)
      if inside_region(exit, prism_regions.p2) then
        prism_stage[ion_number] = 'p2_complete'
        print(string.format('MRTOF_EVENT prism_pass ion=%d n=2 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, exit.t_us, exit.x_mm, exit.y_mm, exit.z_mm,
          exit.vx_mm_us, exit.vy_mm_us, exit.vz_mm_us))
        state = emit_cycle_events(counter:arm_main_drift(exit))
      end
    end
    state = emit_cycle_events(counter:sample(cycle_sample(
      ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight)))
    if not state.sequence_valid and ion_splat == 0 then
      splat_codes[ion_number] = 4
      splat_event_emitted[ion_number] = true
      print(string.format('MRTOF_EVENT splat ion=%d code=4 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
        ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
        turns[ion_number] or 0, crossings[ion_number] or 0))
      ion_splat = 4
      return
    end
    if pvy * ion_vy_mm < 0 then
      local fraction = -pvy / (ion_vy_mm - pvy)
      slow_turns[ion_number] = (slow_turns[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT slow_turn ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
        ion_number, slow_turns[ion_number], pt + fraction*(ion_time_of_flight-pt),
        px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py), pz + fraction*(ion_pz_mm-pz)))
    end
    if not detected[ion_number] and dz < 0 and pz > detector_z and ion_pz_mm <= detector_z then
      local fraction = (detector_z - pz) / dz
      if fraction >= 0 and fraction <= 1 then
        local x = px + fraction * (ion_px_mm - px)
        local y = py + fraction * (ion_py_mm - py)
        if x >= detector_box[1] and x <= detector_box[4]
          and y >= detector_box[2] and y <= detector_box[5] then
          detected[ion_number] = true
          print(string.format('MRTOF_EVENT detector ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
            ion_number, pt + fraction * (ion_time_of_flight - pt), x, y, detector_z))
          splat_codes[ion_number] = 1
          splat_event_emitted[ion_number] = true
          print(string.format('MRTOF_EVENT splat ion=%d code=1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
            ion_number, pt + fraction * (ion_time_of_flight - pt), x, y, detector_z,
            turns[ion_number] or 0, crossings[ion_number] or 0))
          ion_splat = 1
        end
      end
    end
  end
  previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
  previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight
end

function segment.terminate()
  print(string.format('MRTOF_EVENT terminal ion=%d splat=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g turns=%d central_crossings=%d',
    ion_number, splat_codes[ion_number] or 0,
    ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm,
    turns[ion_number] or 0, crossings[ion_number] or 0))
end
