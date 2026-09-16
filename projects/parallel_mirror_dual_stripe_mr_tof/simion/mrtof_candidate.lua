-- Full MR-TOF Candidate workbench program.  Candidate/prototype only.
simion.workbench_program()
-- Required by SIMION 2020's documented 8.2 instance_adjust overlap path.
simion.early_access(8.2)
-- Native SIMION 2020 regression: retain terminal callbacks outside every PA.
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local operating_point_path = assert(program_path:gsub('%.lua$', '.operating_point.lua'))
local operating_point = assert(loadfile(operating_point_path), 'missing run-local operating-point sidecar: '..operating_point_path)()
local local_refinement_path = program_path:gsub('%.lua$', '.local_refinement.lua')
local local_refinement_loader = loadfile(local_refinement_path)
local local_refinement = local_refinement_loader and local_refinement_loader() or {enabled=false}
assert(type(local_refinement) == 'table' and type(local_refinement.enabled) == 'boolean',
  'local-refinement sidecar must return a table with a boolean enabled field')
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
local patch_interface_planes
if local_refinement.enabled then
  patch_interface_planes = operating_point.patch_interface_planes_project
    or local_refinement.patch_interface_planes_project
  assert(type(patch_interface_planes) == 'table',
    'local refinement has no contract-derived local-PA interface planes')
end
local phase_origin_mirror_side = assert(operating_point.phase_origin_mirror_side,
  'operating point has no phase-origin mirror side')
local return_mirror_side = assert(operating_point.return_mirror_side,
  'operating point has no return mirror side')
assert(phase_origin_mirror_side == 1 and return_mirror_side == -1,
  'manufactured path must run from the positive to the opposite negative mirror turn')
assert(operating_point.detector_normal_project == '+z', 'detector must face project +z')
local target_drift_period_ratio = assert(operating_point.target_drift_period_ratio,
  'operating point has no target drift-period ratio')
local target_half_oscillation_count = assert(operating_point.target_half_oscillation_count,
  'operating point has no target half-oscillation count')
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
assert(target_drift_period_ratio > 0
    and target_half_oscillation_count == 2 * target_drift_period_ratio
    and target_half_oscillation_count == math.floor(target_half_oscillation_count),
  'target drift ratio must resolve to a positive integral half-cycle count')
assert(target_half_oscillation_count % 2 == 1,
  'opposite-turn return requires a half-integer target drift ratio')
-- The detector faces +z.  The valid return therefore first encounters its +z
-- face while remaining at z>0 and travelling toward -z.
local detector_z = detector_box[6]
local detector_surface_tolerance_mm = math.max(1e-9,
  1e-9*math.max(math.abs(detector_box[1]),math.abs(detector_box[2]),
    math.abs(detector_box[3]),math.abs(detector_box[4]),
    math.abs(detector_box[5]),math.abs(detector_box[6])))

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
local accelerator_field_gate_requested = operating_point.runtime_accelerator_field_gate_enable
assert(accelerator_field_gate_requested == nil
  or type(accelerator_field_gate_requested) == 'boolean',
  'runtime_accelerator_field_gate_enable must be boolean when present')
local accelerator_pulse_mode = operating_point.accelerator_pulse_mode or 'static'
assert(accelerator_pulse_mode == 'static'
    or accelerator_pulse_mode == 'initial_exit_triggered_single_center'
    or accelerator_pulse_mode == 'fixed_global_time',
  'accelerator_pulse_mode must be static, initial_exit_triggered_single_center, or fixed_global_time')
assert(accelerator_pulse_mode == 'static' or accelerator_field_gate_requested == true,
  'accelerator pulsing requires the standalone accelerator field gate')
local accelerator_pulse_off_time_us = operating_point.accelerator_pulse_off_time_us
if accelerator_pulse_mode == 'fixed_global_time' then
  assert(type(accelerator_pulse_off_time_us) == 'number'
      and accelerator_pulse_off_time_us == accelerator_pulse_off_time_us
      and accelerator_pulse_off_time_us > 0
      and math.abs(accelerator_pulse_off_time_us) < math.huge,
    'fixed_global_time requires a positive finite accelerator_pulse_off_time_us')
else
  assert(accelerator_pulse_off_time_us == nil,
    'accelerator_pulse_off_time_us is only valid for fixed_global_time')
end
assert(operating_point.prism_switch == nil,
  'active MR-TOF Candidate forbids all P1/P2 voltage switching')
if local_refinement.enabled then
  assert(not runtime_fast_adjust_requested,
    'local replacement PAs presently require saved static working points; full analyser Fast Adjust is unsupported')
  assert(type(local_refinement.instances) == 'table' and #local_refinement.instances == 5,
    'local refinement requires five ordered replacement instances')
  assert(local_refinement.global_analyzer_instance == 1
      and local_refinement.accelerator_instance == 7
      and local_refinement.detector_instance == 8,
    'local-refinement instance roles must be global=1, accelerator=7, detector=8')
end
-- The standalone accelerator is instance 2 in the reviewed three-component
-- workbench and instance 7 when the five local analyser replacements are
-- present.  Initial-exit gating is valid in either explicit topology.
-- Ordinary reviewed flights consume a manifest-bound standalone operating PA.
-- Finite-3-D downstream Jacobian trials bind the same standalone analyser
-- representation and apply their run-local Stripe/P1/P2 coordinates in memory.
adjustable runtime_fast_adjust_enable = runtime_fast_adjust_requested and 1 or 0
local full_path_timeout_us = assert(operating_point.full_path_timeout_us, 'operating point has no full-path timeout')
assert(full_path_timeout_us > 0, 'full-path timeout must be positive')
local p2_low_field_reference = operating_point.p2_low_field_reference
if p2_low_field_reference ~= nil then
  assert(type(p2_low_field_reference) == 'table'
      and type(p2_low_field_reference.z_mm) == 'number'
      and p2_low_field_reference.z_mm == p2_low_field_reference.z_mm
      and math.abs(p2_low_field_reference.z_mm) < math.huge,
    'P2 low-field reference requires one finite project-z plane')
  for _,key in ipairs({'x_min_mm','x_max_mm','y_min_mm','y_max_mm'}) do
    local value = p2_low_field_reference[key]
    assert(type(value) == 'number' and value == value and math.abs(value) < math.huge,
      'P2 low-field reference requires finite '..key)
  end
  assert(p2_low_field_reference.x_min_mm < p2_low_field_reference.x_max_mm
      and p2_low_field_reference.y_min_mm < p2_low_field_reference.y_max_mm,
    'P2 low-field reference aperture bounds must be ordered')
end

-- `other_actions` is called for every integration segment.  Keep the prior
-- state in scalar arrays rather than allocating a five-field table per step:
-- the latter turns a long, otherwise identical trajectory into hundreds of
-- thousands of Lua allocations and GC cycles.
local previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
local turns, slow_turns, crossings, y0_crossings, p1_crossings, detected, splat_codes, splat_event_emitted = {}, {}, {}, {}, {}, {}, {}, {}
local cycle_counters, target_k_emitted = {}, {}
local prism_stage = {}
local return_sequence_error = {}
local patch_interface_crossings = {}
local selected_instances = {}
local accelerator_pulse_complete = {}
local accelerator_safe_exit_observed = {}
local p2_low_field_reference_emitted = {}

local function local_instance_definition(instance_number)
  if not local_refinement.enabled then return nil end
  for _,definition in ipairs(local_refinement.instances) do
    if definition.instance == instance_number then return definition end
  end
  return nil
end

function segment.instance_adjust()
  if not local_refinement.enabled then return end
  local definition = local_instance_definition(ion_instance)
  if definition == nil then return end
  local lower_ok = definition.z_min_mm == nil or ion_pz_mm >= definition.z_min_mm
  local upper_ok = definition.z_max_mm == nil or ion_pz_mm < definition.z_max_mm
  if not (lower_ok and upper_ok) then
    -- Official SIMION overlap semantics: zero suppresses only the currently
    -- selected higher-priority instance, then selection resumes below it.
    ion_instance = 0
  end
end

local function sample_coordinate(sample, axis)
  if axis == 'x' then return sample.x_mm end
  if axis == 'y' then return sample.y_mm end
  if axis == 'z' then return sample.z_mm end
  error('invalid patch-interface axis: '..tostring(axis))
end

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
        local n = event.is_pre_origin_turn and 0 or event.half_cycles
        print(string.format('MRTOF_EVENT turn ion=%d n=%d t_us=%.12g z_mm=%.12g',
          ion_number, n, event.t_us, event.z_mm))
        print(string.format('MRTOF_EVENT fast_turn ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, n, event.t_us, event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
        if event.is_pre_origin_turn then
          print(string.format('MRTOF_EVENT pre_origin_positive_mirror_turn ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
            ion_number, event.t_us, event.x_mm, event.y_mm, event.z_mm,
            event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
        end
      elseif event.stage == 'after_main_drift' then
        if prism_stage[ion_number] == 'awaiting_return_positive_mirror'
          and event.side == 1 then
          -- P1 belongs to the injection branch.  On the non-retracing static
          -- return branch, the positive-mirror turn sends the ion directly
          -- toward the detector at z>0 with v_z<0; requiring a second P1 pass
          -- would put the detector behind its reviewed physical plane.
          prism_stage[ion_number] = 'awaiting_static_detector'
          print(string.format('MRTOF_EVENT return_positive_mirror_turn ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, event.t_us,
          event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
        else
          return_sequence_error[ion_number] = 'unexpected_post_return_mirror_turn'
        end
      end
    elseif event.kind == 'nonmirror_reversal' then
      if not accelerator_safe_exit_observed[ion_number] then
        -- A finite source angle can give an ion a small initial +z velocity.
        -- The accelerator then drives that component through zero while
        -- forming the designed -z beam.  This is launch formation, not an
        -- analyser reflection; the mirror-only reversal invariant begins at
        -- the first safe accelerator exit.
        print(string.format('MRTOF_EVENT accelerator_launch_vz_zero ion=%d direction_before=%d direction_after=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, event.direction_before, event.direction_after,
          event.t_us, event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      else
        return_sequence_error[ion_number] = 'nonmirror_vz_reversal'
        print(string.format('MRTOF_EVENT nonmirror_reversal ion=%d direction_before=%d direction_after=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, event.direction_before, event.direction_after,
          event.t_us, event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      end
    elseif event.kind == 'drift_phase_origin' then
      print(string.format('MRTOF_EVENT drift_phase_origin ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.t_us, event.x_mm, event.y_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
    elseif event.kind == 'drift_phase_candidate' then
      print(string.format('MRTOF_EVENT drift_phase_candidate ion=%d k=%.12g half_cycles=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.period_ratio, event.half_cycles,
        event.t_us, event.x_mm, event.y_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      if event.half_cycles == target_half_oscillation_count then
        print(string.format('MRTOF_EVENT target_k_phase_sample ion=%d k=%.12g half_cycles=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, event.period_ratio, event.half_cycles, event.t_us, event.x_mm, event.y_mm, event.z_mm,
          event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      end
    elseif event.kind == 'drift_phase_return' then
      print(string.format('MRTOF_EVENT drift_phase_return ion=%d k=%.12g half_cycles=%d slow_coordinate_residual_mm=%.12g t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.period_ratio, event.half_cycles, event.slow_coordinate_residual_mm,
        event.t_us, event.x_mm, event.y_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
      if event.half_cycles == target_half_oscillation_count and not target_k_emitted[ion_number] then
        target_k_emitted[ion_number] = true
        print(string.format('MRTOF_EVENT target_k ion=%d k=%.12g half_cycles=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
          ion_number, event.period_ratio, event.half_cycles,
          event.t_us, event.x_mm, event.y_mm, event.z_mm))
        if prism_stage[ion_number] == 'p2_complete' then
          prism_stage[ion_number] = 'awaiting_return_p2_entry'
        else
          return_sequence_error[ion_number] = 'target_phase_return_before_completed_injection'
        end
      end
    elseif event.kind == 'slow_coordinate' then
      y0_crossings[ion_number] = (y0_crossings[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT slow_coordinate_y0 ion=%d n=%d direction_y=%d t_us=%.12g x_mm=%.12g y_mm=0 z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, y0_crossings[ion_number], event.direction,
        event.t_us, event.x_mm, event.z_mm,
        event.vx_mm_us, event.vy_mm_us, event.vz_mm_us))
    elseif event.kind == 'drift_coordinate_return' then
      print(string.format('MRTOF_EVENT drift_coordinate_return ion=%d k_before=%.12g fractional_k=%.12g t_us=%.12g x_mm=%.12g y_mm=0 z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, event.k_before, event.fractional_k, event.t_us, event.x_mm, event.z_mm,
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
  return_sequence_error = {}
  patch_interface_crossings = {}
  selected_instances = {}
  accelerator_pulse_complete = {}
  accelerator_safe_exit_observed = {}
  if local_refinement.enabled then
    assert(#patch_interface_planes > 0, 'at least one local-PA interface plane is required')
    for _,plane in ipairs(patch_interface_planes) do
      assert(type(plane.name) == 'string' and type(plane.region) == 'string'
        and type(plane.face) == 'string', 'patch-interface identity is incomplete')
      assert((plane.axis == 'x' or plane.axis == 'y' or plane.axis == 'z')
        and type(plane.coordinate_mm) == 'number', 'patch-interface coordinate is invalid')
      assert((plane.u_axis == 'x' or plane.u_axis == 'y' or plane.u_axis == 'z')
        and (plane.v_axis == 'x' or plane.v_axis == 'y' or plane.v_axis == 'z')
        and plane.u_axis ~= plane.axis and plane.v_axis ~= plane.axis
        and plane.u_axis ~= plane.v_axis, 'patch-interface in-plane axes are invalid')
      assert(plane.u_min_mm < plane.u_max_mm and plane.v_min_mm < plane.v_max_mm,
        'patch-interface in-plane bounds are invalid')
    end
    assert(simion.wb and #simion.wb.instances == 8,
      'local-refinement flight requires eight contiguous instances')
    local expected = {
      {'mrtof_analyzer%.pa0$', 'iob_input_analyzer%.pa$'},
      {'local_negative_mirror%.pa0$', 'iob_input_local_1%.pa$'},
      {'local_negative_bridge%.pa0$', 'iob_input_local_2%.pa$'},
      {'local_central%.pa0$', 'iob_input_local_3%.pa$'},
      {'local_positive_bridge%.pa0$', 'iob_input_local_4%.pa$'},
      {'local_positive_mirror%.pa0$', 'iob_input_local_5%.pa$'},
      {'mrtof_accelerator%.pa0$', 'iob_input_accelerator%.pa$'},
      {'mrtof_detector%.pa#$', 'iob_input_detector%.pa$'}
    }
    for index,patterns in ipairs(expected) do
      local filename=simion.wb.instances[index].filename
      assert(filename:match(patterns[1]) or filename:match(patterns[2]),
        string.format('local-refinement instance %d has the wrong PA role', index))
    end
    print('MRTOF_CANDIDATE: status=prototype geometry=three_component_3d local_replacement=enabled')
  else
    assert(simion.wb and #simion.wb.instances == 3,
      'MR-TOF Candidate flight requires analyser, accelerator, and detector instances')
    assert(simion.wb.instances[1].filename:match('mrtof_analyzer%.pa0$')
      or simion.wb.instances[1].filename:match('iob_input_analyzer%.pa$'), 'instance 1 must be analyser PA')
    assert(simion.wb.instances[2].filename:match('mrtof_accelerator%.pa0$')
      or simion.wb.instances[2].filename:match('iob_input_accelerator%.pa$'), 'instance 2 must be accelerator PA')
    assert(simion.wb.instances[3].filename:match('mrtof_detector%.pa#$')
      or simion.wb.instances[3].filename:match('iob_input_detector%.pa$'), 'instance 3 must be detector PA')
    print('MRTOF_CANDIDATE: status=prototype geometry=three_component_3d')
  end
end

function segment.fast_adjust()
  if runtime_fast_adjust_enable == 0 then return end
  local analyser=simion.wb.instances[1].pa
  local values=voltage_map(mirror_voltages,{V_stripe_1,V_stripe_2},{V_prism_1,V_prism_2},
    {V_repeller,V_grid1,V_grid2},accelerator_ring_voltages,V_nonaccelerator_scale)
  if runtime_fast_adjust_enable ~= 0 then analyser:fast_adjust(values.analyser) end
end

function segment.efield_adjust()
  if not accelerator_field_gate_requested then return end
  local accelerator_instance = local_refinement.enabled and 7 or 2
  if ion_instance ~= accelerator_instance then return end
  local field_active = true
  if accelerator_pulse_mode == 'initial_exit_triggered_single_center' then
    field_active = not accelerator_pulse_complete[ion_number]
  elseif accelerator_pulse_mode == 'fixed_global_time' then
    field_active = (tonumber(ion_time_of_flight) or 0) < accelerator_pulse_off_time_us
  end
  if not field_active then
    -- The instance remains present as the exact electrode/collision geometry;
    -- only its solved operating field is suppressed after the pulse boundary.
    ion_dvoltsx_gu, ion_dvoltsy_gu, ion_dvoltsz_gu = 0, 0, 0
  end
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
  if accelerator_pulse_mode == 'fixed_global_time'
      and ion_time_of_flight < accelerator_pulse_off_time_us then
    local remaining_us = accelerator_pulse_off_time_us - ion_time_of_flight
    if remaining_us > 0 then ion_time_step = math.min(ion_time_step, remaining_us) end
  end
end

function segment.initialize()
  -- Retain the release state so a first-step plane crossing is not omitted.
  if previous_z[ion_number] == nil then
    previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
    previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight
    cycle_counters[ion_number] = mirror_cycle_counter.new(
      mirror_regions, phase_origin_mirror_side, return_mirror_side,
      target_half_oscillation_count)
    prism_stage[ion_number] = 'awaiting_p1_exit'
    emit_cycle_events(cycle_counters[ion_number]:sample(cycle_sample(
      ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight)))
  end
end

function segment.other_actions()
  if accelerator_pulse_mode == 'fixed_global_time'
      and not accelerator_pulse_complete[ion_number]
      and ion_time_of_flight >= accelerator_pulse_off_time_us then
    accelerator_pulse_complete[ion_number] = true
    print(string.format('MRTOF_EVENT accelerator_global_pulse_applied ion=%d t_us=%.12g scheduled_t_us=%.12g instance=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g trigger=fixed_global_time',
      ion_number, ion_time_of_flight, accelerator_pulse_off_time_us, ion_instance,
      ion_px_mm, ion_py_mm, ion_pz_mm))
  end
  local accelerator_instance = local_refinement.enabled
    and local_refinement.accelerator_instance or 2
  local maximum_instance = local_refinement.enabled and 8 or 3
  assert(ion_instance >= 0 and ion_instance <= maximum_instance,
    'SIMION selected an undeclared workbench instance')
  if selected_instances[ion_number] ~= ion_instance then
      if not accelerator_safe_exit_observed[ion_number]
          and selected_instances[ion_number] == accelerator_instance
          and ion_instance ~= accelerator_instance then
        accelerator_safe_exit_observed[ion_number] = true
        print(string.format('MRTOF_EVENT accelerator_safe_exit ion=%d t_us=%.12g from_instance=%d to_instance=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, ion_time_of_flight, selected_instances[ion_number], ion_instance,
          ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm))
      end
      if accelerator_safe_exit_observed[ion_number]
          and selected_instances[ion_number] ~= accelerator_instance
          and ion_instance == accelerator_instance then
        return_sequence_error[ion_number] = 'accelerator_reentry_after_safe_exit'
        print(string.format('MRTOF_EVENT accelerator_reentry ion=%d t_us=%.12g instance=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, ion_time_of_flight, ion_instance, ion_px_mm, ion_py_mm, ion_pz_mm,
          ion_vx_mm, ion_vy_mm, ion_vz_mm))
      end
      if accelerator_pulse_mode == 'initial_exit_triggered_single_center'
          and not accelerator_pulse_complete[ion_number]
          and selected_instances[ion_number] == accelerator_instance
          and ion_instance ~= accelerator_instance then
        accelerator_pulse_complete[ion_number] = true
        print(string.format('MRTOF_EVENT accelerator_pulse_off ion=%d t_us=%.12g from_instance=%d to_instance=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g',
          ion_number, ion_time_of_flight, selected_instances[ion_number], ion_instance,
          ion_px_mm, ion_py_mm, ion_pz_mm))
      end
      print(string.format('MRTOF_EVENT instance_transition ion=%d t_us=%.12g instance=%d x_mm=%.12g y_mm=%.12g z_mm=%.12g',
        ion_number, ion_time_of_flight, ion_instance, ion_px_mm, ion_py_mm, ion_pz_mm))
      selected_instances[ion_number] = ion_instance
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
  -- SIMION exposes ion_splat while stepping, but not in terminate.  Cache it
  -- now, but defer the generic collision receipt until after detector-contact
  -- classification so one physical detector hit cannot emit two splat events.
  if ion_splat ~= 0 then
    splat_codes[ion_number] = ion_splat
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
    if local_refinement.enabled then
      for _,plane in ipairs(patch_interface_planes) do
        local before_coordinate = sample_coordinate(before, plane.axis)
        local after_coordinate = sample_coordinate(after, plane.axis)
        local delta = after_coordinate-before_coordinate
        local crosses = (before_coordinate < plane.coordinate_mm
            and after_coordinate >= plane.coordinate_mm)
          or (before_coordinate > plane.coordinate_mm
            and after_coordinate <= plane.coordinate_mm)
        if crosses and delta ~= 0 then
          local crossing = interpolated_sample(before, after,
            (plane.coordinate_mm-before_coordinate)/delta)
          local u = sample_coordinate(crossing, plane.u_axis)
          local v = sample_coordinate(crossing, plane.v_axis)
          if u >= plane.u_min_mm and u <= plane.u_max_mm
            and v >= plane.v_min_mm and v <= plane.v_max_mm then
            local key = tostring(ion_number)..':'..plane.name
            patch_interface_crossings[key] = (patch_interface_crossings[key] or 0)+1
            print(string.format('MRTOF_EVENT patch_interface ion=%d name=%s region=%s face=%s n=%d direction=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
              ion_number, plane.name, plane.region, plane.face,
              patch_interface_crossings[key], delta > 0 and 1 or -1,
              crossing.t_us, crossing.x_mm, crossing.y_mm, crossing.z_mm,
              crossing.vx_mm_us, crossing.vy_mm_us, crossing.vz_mm_us))
          end
        end
      end
    end
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
    if p2_low_field_reference ~= nil
        and not p2_low_field_reference_emitted[ion_number]
        and prism_stage[ion_number] == 'p2_complete'
        and dz > 0
        and pz < p2_low_field_reference.z_mm
        and ion_pz_mm >= p2_low_field_reference.z_mm then
      local reference = interpolated_sample(before, after,
        (p2_low_field_reference.z_mm-pz)/dz)
      if reference.x_mm >= p2_low_field_reference.x_min_mm
          and reference.x_mm <= p2_low_field_reference.x_max_mm
          and reference.y_mm >= p2_low_field_reference.y_min_mm
          and reference.y_mm <= p2_low_field_reference.y_max_mm
          and reference.vy_mm_us > 0
          and reference.vz_mm_us > 0 then
        p2_low_field_reference_emitted[ion_number] = true
        print(string.format('MRTOF_EVENT p2_low_field_reference ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, reference.t_us, reference.x_mm, reference.y_mm,
          reference.z_mm, reference.vx_mm_us, reference.vy_mm_us,
          reference.vz_mm_us))
      end
    end
    if dz > 0 and prism_stage[ion_number] == 'awaiting_return_p2_entry'
      and pz < prism_regions.p2.z_min_mm and ion_pz_mm >= prism_regions.p2.z_min_mm then
      local entry = interpolated_sample(before, after,
        (prism_regions.p2.z_min_mm-pz)/dz)
      if inside_region(entry, prism_regions.p2) then
        prism_stage[ion_number] = 'inside_return_p2'
        print(string.format('MRTOF_EVENT return_p2_entry ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, entry.t_us, entry.x_mm, entry.y_mm, entry.z_mm,
          entry.vx_mm_us, entry.vy_mm_us, entry.vz_mm_us))
      end
    end
    if dz > 0 and prism_stage[ion_number] == 'inside_return_p2'
      and pz < prism_regions.p2.z_max_mm and ion_pz_mm >= prism_regions.p2.z_max_mm then
      local exit = interpolated_sample(before, after,
        (prism_regions.p2.z_max_mm-pz)/dz)
      if inside_region(exit, prism_regions.p2) then
        prism_stage[ion_number] = 'awaiting_return_positive_mirror'
        print(string.format('MRTOF_EVENT return_p2_pass ion=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, exit.t_us, exit.x_mm, exit.y_mm, exit.z_mm,
          exit.vx_mm_us, exit.vy_mm_us, exit.vz_mm_us))
      end
    end
    state = emit_cycle_events(counter:sample(cycle_sample(
      ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight)))
    if (not state.sequence_valid or return_sequence_error[ion_number] ~= nil)
      and ion_splat == 0 then
      local rejection_reason = return_sequence_error[ion_number]
        or state.sequence_error or 'trajectory_sequence_invalid'
      splat_codes[ion_number] = 4
      splat_event_emitted[ion_number] = true
      -- ion_splat is SIMION's only programmatic stop mechanism.  Code 4 is a
      -- project topology rejection, not contact with an electrode.
      print(string.format('MRTOF_EVENT splat ion=%d code=4 termination_kind=programmatic_topology_rejection physical_collision=0 reason=%s t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
        ion_number, rejection_reason,
        ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
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
    local detector_contact_direction = 0
    if ion_splat ~= 0 and ion_vz_mm < 0
      and math.abs(ion_pz_mm-detector_box[6]) <= detector_surface_tolerance_mm then
      detector_contact_direction = -1
    elseif ion_splat ~= 0 and ion_vz_mm > 0
      and math.abs(ion_pz_mm-detector_box[3]) <= detector_surface_tolerance_mm then
      detector_contact_direction = 1
    end
    local detector_contact = detector_contact_direction ~= 0
      and ion_px_mm >= detector_box[1]-detector_surface_tolerance_mm
      and ion_px_mm <= detector_box[4]+detector_surface_tolerance_mm
      and ion_py_mm >= detector_box[2]-detector_surface_tolerance_mm
      and ion_py_mm <= detector_box[5]+detector_surface_tolerance_mm
    local detector_plane_crossing = (dz < 0 and pz > detector_z and ion_pz_mm <= detector_z)
      or (dz > 0 and pz < detector_z and ion_pz_mm >= detector_z)
    if detector_plane_crossing or detector_contact then
      local fraction = detector_contact and 1 or (detector_z - pz) / dz
      if fraction >= 0 and fraction <= 1 then
        local x = px + fraction * (ion_px_mm - px)
        local y = py + fraction * (ion_py_mm - py)
        local vx = pvx + fraction * (ion_vx_mm - pvx)
        local vy = pvy + fraction * (ion_vy_mm - pvy)
        local vz = pvz + fraction * (ion_vz_mm - pvz)
        local detector_direction = detector_contact and detector_contact_direction or (dz < 0 and -1 or 1)
        local detector_plane_z = detector_contact and ion_pz_mm or detector_z
        print(string.format('MRTOF_EVENT detector_plane ion=%d direction_z=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, detector_direction, pt + fraction * (ion_time_of_flight - pt), x, y,
          detector_plane_z, vx, vy, vz))
        if detector_direction == -1
          and prism_stage[ion_number] == 'awaiting_static_detector'
          and not detected[ion_number]
          and x >= detector_box[1] and x <= detector_box[4]
          and y >= detector_box[2] and y <= detector_box[5] then
          detected[ion_number] = true
          prism_stage[ion_number] = 'static_detector_complete'
          print(string.format('MRTOF_EVENT detector ion=%d direction_z=-1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
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
  if ion_splat ~= 0 and not splat_event_emitted[ion_number] then
    splat_event_emitted[ion_number] = true
    print(string.format('MRTOF_EVENT splat ion=%d code=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
      ion_number, splat_codes[ion_number] or ion_splat, ion_time_of_flight,
      ion_px_mm, ion_py_mm, ion_pz_mm,
      turns[ion_number] or 0, crossings[ion_number] or 0))
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
