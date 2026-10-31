-- Full MR-TOF Candidate workbench program.  Candidate/prototype only.
simion.workbench_program()
-- Native SIMION 2020 regression: retain terminal callbacks outside every PA.
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local waveforms = assert(loadfile(program_path:gsub('%.lua$', '.voltage_waveforms.lua')))()
local operating_point_path = assert(program_path:gsub('%.lua$', '.operating_point.lua'))
local operating_point = assert(loadfile(operating_point_path), 'missing run-local operating-point sidecar: '..operating_point_path)()
local accelerator_provider = operating_point.accelerator_provider or 'orthogonal_accelerator'
assert(accelerator_provider == 'orthogonal_accelerator'
    or accelerator_provider == 'dual_pressure_rectilinear_ion_processor', 'unknown accelerator provider')
local measured_mode = accelerator_provider == 'dual_pressure_rectilinear_ion_processor'
local static_field = operating_point.static_field
local measured_source
if measured_mode then
  assert(operating_point.field_assembly_verified == true
      and operating_point.measured_source_matches_workpoint == true,
    'IP flight requires verified replacement fields and measured source matching')
  assert(static_field and static_field.accelerator_provider == accelerator_provider
      and static_field.assembly_scope == 'full_c0_ion_processor_replacement',
    'measured IP source requires its full C0 replacement static field')
  assert(operating_point.runtime_fast_adjust_enable == false,
    'measured IP source forbids runtime Fast Adjust')
  assert(type(operating_point.measured_source_directory) == 'string'
      and #operating_point.measured_source_directory > 0, 'measured source directory required')
  measured_source = assert(loadfile(program_path:gsub('%.lua$', '.source_runtime.lua')))().load(
    operating_point.measured_source_directory)
end
-- Official SIMION initialize/time globals; source projection owns the single
-- epoch mapping (https://simion.com/info/time.html, reviewed 2026-10-16).
local function instrument_time_us()
  if measured_source then return measured_source.instrument_time_us(ion_time_of_flight) end
  return ion_time_of_flight
end
local function event_id()
  if measured_source then return measured_source.source_id(ion_number) end
  return ion_number
end
-- The frozen sidecar explicitly declares per-batch persistent science files.
local scientific_output=assert(operating_point.scientific_event_output,'frozen scientific event output required')
local scientific_events,scientific_trajectory
local scientific_csv=assert(loadfile(assert(scientific_output.csv_writer_path,'frozen CSV writer path required')))()
local scientific_columns={'kind','ion','accelerator','accelerator_fast_adjust','after_t_us','after_vy_mm_us','after_vz_mm_us','after_z_mm','before_t_us','before_vy_mm_us','before_vz_mm_us','before_z_mm','central_crossings','code','corridor','corridor_fast_adjust','direction_after','direction_before','direction_ok','direction_y','direction_z','fast_adjust','field','fraction','fractional_k','from_instance','geometry','gui_field_queries_equivalent','half_cycles','inside_aperture','instance','k','k_before','localization','n','native_splat','phase','phase_crossing_t_us','phase_crossing_y_mm','phase_period_us','phase_time_residual_us','physical_collision','projection_dt_us','raw_t_us','raw_x_mm','raw_y_mm','raw_z_mm','reason','scheduled_t_us','slow_coordinate_residual_mm','splat','status','step_span_us','t_us','termination_kind','to_instance','trigger','turns','volts','vx_mm_us','vy_mm_us','vz_mm_us','x_mm','y_mm','z_mm'}
local trajectory_columns={'ion','phase','t_us','x_mm','y_mm','z_mm','vx_mm_us','vy_mm_us','vz_mm_us'}
local function initialize_scientific_output()
  local events_path,trajectory_path
  if scientific_output.environment_required then
    events_path=os.getenv(scientific_output.events_environment_variable)
    trajectory_path=os.getenv(scientific_output.trajectory_environment_variable)
    assert(events_path and #events_path>0,'batch scientific event locator is required')
    if operating_point.trajectory_recording_enabled then assert(trajectory_path and #trajectory_path>0,'batch scientific trajectory locator is required') end
  else
    events_path=scientific_output.events_path
    trajectory_path=scientific_output.trajectory_path
  end
  assert(events_path and #events_path>0,'declared event output missing')
  scientific_events=scientific_csv.open(events_path,scientific_columns,12)
  if operating_point.trajectory_recording_enabled then
    assert(trajectory_path and #trajectory_path>0,'declared trajectory output missing')
    scientific_trajectory=scientific_csv.open(trajectory_path,trajectory_columns,17)
  end
end
local function scientific_particle_id(value)
  assert(type(value)=='number' and value>=1 and value<=9007199254740991 and value%1==0,
    'scientific particle ID must be a positive safe integer')
  return string.format('%.0f',value)
end
local function record_scientific(kind, row, extra)
  assert(type(row)=='table','scientific event fields required')
  if extra then
    for key,value in pairs(extra) do
      assert(row[key]==nil,'duplicate project scientific event field')
      row[key]=value
    end
  end
  local trajectory=kind==nil
  if not trajectory then row.kind=kind end
  local columns=trajectory and trajectory_columns or scientific_columns
  local writer=assert(trajectory and scientific_trajectory or scientific_events,'scientific output is not initialized')
  local values={}
  for i,key in ipairs(columns) do values[i]=row[key] or '' end
  writer:write(values)
  if kind=='terminal' then writer:flush();if scientific_trajectory then scientific_trajectory:flush() end end
end

-- Official SIMION initialize/other_actions/terminate callbacks expose actual
-- solver states. Observation only: no time-step or particle-state assignment.
-- https://simion.com/info/trajectory_programming.html (SIMION 8.1+, 2026-10-16).
local trajectory_sample_buckets = {}
local function record_trajectory_sample(phase, explicit_time_us)
  if operating_point.trajectory_recording_enabled ~= true then return end
  local sample_time_us = explicit_time_us or instrument_time_us()
  local mode = operating_point.trajectory_recording_mode or 'every_step'
  assert(mode == 'every_step' or mode == 'fixed_interval', 'unknown trajectory recording mode')
  if mode == 'fixed_interval' then
    local interval = operating_point.trajectory_recording_interval_us
    assert(type(interval) == 'number' and interval > 0 and interval < math.huge,
      'fixed_interval trajectory recording requires a positive finite interval')
    -- Select actual callbacks after absolute-clock bucket crossings. Never
    -- interpolate a state, force an integration step, or suppress MR events.
    local bucket = math.floor(sample_time_us / interval)
    if phase == 'step' and trajectory_sample_buckets[ion_number] ~= nil
        and bucket <= trajectory_sample_buckets[ion_number] then return end
    trajectory_sample_buckets[ion_number] = bucket
  end
  record_scientific(nil, {ion=scientific_particle_id(event_id()), phase=phase, t_us=string.format('%.17g',sample_time_us), x_mm=string.format('%.17g',ion_px_mm), y_mm=string.format('%.17g',ion_py_mm), z_mm=string.format('%.17g',ion_pz_mm), vx_mm_us=string.format('%.17g',ion_vx_mm), vy_mm_us=string.format('%.17g',ion_vy_mm), vz_mm_us=string.format('%.17g',ion_vz_mm)})
end
local static_field_adjust
if static_field then
  static_field_adjust = assert(loadfile(program_path:gsub('%.lua$', '.scalar_field_adapter.lua')))()(static_field)
end
local priority_path = program_path:gsub('%.lua$', '.priority.lua')
local native_corridor_roles = assert(loadfile(priority_path), 'missing native-corridor priority sidecar: '..priority_path)()
assert(type(native_corridor_roles) == 'table'
    and native_corridor_roles.role == 'mrtof_native_corridor_iob_priority_contract'
    and native_corridor_roles.schema_version == 1,
  'native-corridor priority sidecar has the wrong role or schema')
local collision_overlay = static_field and static_field.collision_overlay
local role_count = collision_overlay and 5 or 4
if collision_overlay then
  assert(measured_mode and collision_overlay.schema_version == 1
      and collision_overlay.role == 'mrtof_analyzer_collision_overlay'
      and native_corridor_roles.collision_overlay
      and native_corridor_roles.collision_overlay.patch_plan_path == collision_overlay.patch_plan_path
      and native_corridor_roles.collision_overlay.pa_path == collision_overlay.pa_path,
    'fifth collision instance requires matching verified overlay projections')
else
  assert(native_corridor_roles.collision_overlay == nil, 'undeclared collision overlay in priority contract')
end
assert(type(native_corridor_roles.instances) == 'table'
    and #native_corridor_roles.instances == role_count,
  'native-corridor priority sidecar has wrong instance count')
if measured_mode then
  assert(native_corridor_roles.accelerator_provider == accelerator_provider,
    'priority sidecar must identify the IP replacement assembly')
end
local native_corridor_instances = {}
local expected_roles = measured_mode and {'global_fallback', 'native_corridor', 'ion_processor_collision', 'detector'}
  or {'global_fallback', 'native_corridor', 'accelerator', 'detector'}
if collision_overlay then expected_roles[5] = 'analyzer_collision_patch' end
for index, expected_role in ipairs(expected_roles) do
  local definition = native_corridor_roles.instances[index]
  assert(type(definition) == 'table'
      and definition.role == expected_role
      and definition.priority_number == index,
    string.format('native-corridor priority instance %d must be role %s', index, expected_role))
  native_corridor_instances[expected_role] = index
end
local native_corridor_voltage_groups = native_corridor_roles.corridor_voltage_groups
local applied_native_corridor_values, applied_accelerator_values
local voltage_map_path = program_path:gsub('%.lua$', '.voltage_map.lua')
local voltage_map
if not measured_mode then
  voltage_map = assert(loadfile(voltage_map_path), 'missing run-local voltage mapper: '..voltage_map_path)()
end
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
local accelerator_voltages = operating_point.accelerator_voltages_v
local accelerator_ring_voltages = operating_point.accelerator_ring_voltages_v
assert(#detector_box == 6 and detector_box[1] < detector_box[4]
  and detector_box[2] < detector_box[5] and detector_box[3] < detector_box[6],
  'numerical detector box must be positive')
assert(type(first_prism_l0.target_plane_z_mm) == 'number', 'P1 interface needs a z plane')
assert(#stripe_biases == 2 and #prism_voltages == 2, 'two Stripe and prism voltages required')
if not measured_mode then
  assert(type(accelerator_voltages) == 'table' and #accelerator_voltages == 3
      and type(accelerator_ring_voltages) == 'table' and #accelerator_ring_voltages > 0,
    'OA requires three endpoint and nonempty stage-2 ring voltages')
end
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

adjustable V_stripe_1 = stripe_biases[1]
adjustable V_stripe_2 = stripe_biases[2]
adjustable V_prism_1 = prism_voltages[1]
adjustable V_prism_2 = prism_voltages[2]
adjustable V_mirror_B = mirror_voltages[2]
adjustable V_mirror_C = mirror_voltages[3]
adjustable V_mirror_D = mirror_voltages[4]
adjustable V_mirror_E = mirror_voltages[5]
adjustable V_repeller = accelerator_voltages and accelerator_voltages[1] or 0
adjustable V_grid1 = accelerator_voltages and accelerator_voltages[2] or 0
adjustable V_grid2 = accelerator_voltages and accelerator_voltages[3] or 0
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
local accelerator_safe_exit_only = operating_point.accelerator_safe_exit_only or false
local accelerator_exit_plane_z = operating_point.accelerator_exit_plane_project_z_mm
if measured_mode then
  assert(accelerator_pulse_mode == 'static' and not accelerator_safe_exit_only
      and not accelerator_field_gate_requested and accelerator_exit_plane_z == nil,
    'measured IP handoff forbids OA launch and safe-exit controls')
end
assert(type(accelerator_safe_exit_only) == 'boolean',
  'accelerator_safe_exit_only must be boolean')
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
-- Legacy verification workbenches retain their existing fixed layouts.  The
-- preferred native-corridor workbench resolves every instance from the copied
-- priority sidecar, including the standalone accelerator and detector.
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
local selected_instances = {}
local accelerator_pulse_complete = {}
local accelerator_safe_exit_observed = {}
local accelerator_geometric_exit_observed = {}
local p2_low_field_reference_emitted = {}
local detector_native_contacts = {}
local solver_birth_times = {}

local function role_instance(role)
  return assert(native_corridor_instances[role],
    'native-corridor priority sidecar has no role '..tostring(role))
end

local function accelerator_instance_number()
  if measured_mode then return nil end
  return role_instance('accelerator')
end

local function detector_instance_number()
  return role_instance('detector')
end

local function detector_contact_sample(before, after, native_splat, instance, stage)
  if native_splat ~= -1 or instance ~= detector_instance_number()
    or stage ~= 'awaiting_static_detector' or before.z_mm <= detector_z
    or after.z_mm < detector_z or before.vz_mm_us >= 0 or after.vz_mm_us >= 0 then
    return nil
  end
  -- SIMION may end an electrode collision just outside the surface. Use the
  -- installed test_plane time_to_plane formula, not a fixed distance tolerance.
  -- This bounded contact projection is NOT a measured crossing bracket.
  -- https://simion.com/info/trajectory_programming.html (electrode-hit recording)
  -- https://simion.com/info/test_plane.html; SIMION-2020/examples/test_plane
  local dt = (detector_z-after.z_mm)/after.vz_mm_us
  local span = after.t_us-before.t_us
  if not (dt >= 0 and dt <= span and span > 0) then return nil end
  if not (after.x_mm > detector_box[1] and after.x_mm < detector_box[4]
    and after.y_mm > detector_box[2] and after.y_mm < detector_box[5]) then return nil end
  local x, y = after.x_mm+dt*after.vx_mm_us, after.y_mm+dt*after.vy_mm_us
  -- Both samples remain outside the front; the segment to this strict interior
  -- face point cannot first intersect a side/back face of the detector solid.
  if not (x > detector_box[1] and x < detector_box[4]
    and y > detector_box[2] and y < detector_box[5]) then return nil end
  return {t_us=after.t_us+dt, x_mm=x, y_mm=y, z_mm=detector_z,
    vx_mm_us=after.vx_mm_us, vy_mm_us=after.vy_mm_us, vz_mm_us=after.vz_mm_us}
end

local function maximum_instance_number()
  return #native_corridor_roles.instances
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
  local has_mirror_turn = false
  for _,event in ipairs(events) do
    if event.kind == 'mirror_turn' then
      has_mirror_turn = true
      -- The manufactured injection path contains one real negative-mirror
      -- pre-reflection between P1 and P2.  A prism refracts the ray; it must
      -- never be identified from a v_z sign reversal.
      if event.stage == 'before_main_drift' and event.side == -1
        and prism_stage[ion_number] == 'p1_complete' then
        prism_stage[ion_number] = 'awaiting_p2_entry'
        record_scientific('pre_injection_mirror_turn', {ion=scientific_particle_id(event_id()), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
      end
      if event.accepted then
        local n = event.is_pre_origin_turn and 0 or event.half_cycles
        record_scientific('turn', {ion=scientific_particle_id(event_id()), n=string.format('%d',n), t_us=event.t_us, z_mm=event.z_mm})
        record_scientific('fast_turn', {ion=scientific_particle_id(event_id()), n=string.format('%d',n), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
        if event.is_pre_origin_turn then
          record_scientific('pre_origin_positive_mirror_turn', {ion=scientific_particle_id(event_id()), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
        end
      elseif event.stage == 'after_main_drift' then
        if prism_stage[ion_number] == 'awaiting_return_positive_mirror'
          and event.side == 1 then
          -- P1 belongs to the injection branch.  On the non-retracing static
          -- return branch, the positive-mirror turn sends the ion directly
          -- toward the detector at z>0 with v_z<0; requiring a second P1 pass
          -- would put the detector behind its reviewed physical plane.
          prism_stage[ion_number] = 'awaiting_static_detector'
          record_scientific('return_positive_mirror_turn', {ion=scientific_particle_id(event_id()), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
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
        record_scientific('accelerator_launch_vz_zero', {ion=scientific_particle_id(event_id()), direction_before=string.format('%d',event.direction_before), direction_after=string.format('%d',event.direction_after), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
      else
        return_sequence_error[ion_number] = 'nonmirror_vz_reversal'
        record_scientific('nonmirror_reversal', {ion=scientific_particle_id(event_id()), direction_before=string.format('%d',event.direction_before), direction_after=string.format('%d',event.direction_after), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
      end
    elseif event.kind == 'drift_phase_origin' then
      record_scientific('drift_phase_origin', {ion=scientific_particle_id(event_id()), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
    elseif event.kind == 'drift_phase_candidate' then
      record_scientific('drift_phase_candidate', {ion=scientific_particle_id(event_id()), k=event.period_ratio, half_cycles=string.format('%d',event.half_cycles), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
      if event.half_cycles == target_half_oscillation_count then
        record_scientific('target_k_phase_sample', {ion=scientific_particle_id(event_id()), k=event.period_ratio, half_cycles=string.format('%d',event.half_cycles), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
      end
    elseif event.kind == 'drift_phase_return' then
      record_scientific('drift_phase_return', {ion=scientific_particle_id(event_id()), k=event.period_ratio, half_cycles=string.format('%d',event.half_cycles), slow_coordinate_residual_mm=event.slow_coordinate_residual_mm, t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
      if event.half_cycles == target_half_oscillation_count and not target_k_emitted[ion_number] then
        target_k_emitted[ion_number] = true
        record_scientific('target_k', {ion=scientific_particle_id(event_id()), k=event.period_ratio, half_cycles=string.format('%d',event.half_cycles), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm})
        if prism_stage[ion_number] == 'p2_complete' then
          prism_stage[ion_number] = 'awaiting_return_p2_entry'
        else
          return_sequence_error[ion_number] = 'target_phase_return_before_completed_injection'
        end
      end
    elseif event.kind == 'slow_coordinate' then
      y0_crossings[ion_number] = (y0_crossings[ion_number] or 0) + 1
      record_scientific('slow_coordinate_y0', {ion=scientific_particle_id(event_id()), n=string.format('%d',y0_crossings[ion_number]), direction_y=string.format('%d',event.direction), t_us=event.t_us, x_mm=event.x_mm, y_mm=0, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
    elseif event.kind == 'drift_coordinate_return' then
      local phase_fields = {}
      if event.phase_crossing_t_us then
        phase_fields = {phase_crossing_t_us=event.phase_crossing_t_us, phase_crossing_y_mm=event.phase_crossing_y_mm,
          phase_time_residual_us=event.phase_time_residual_us, phase_period_us=event.phase_period_us}
      end
      record_scientific('drift_coordinate_return', {ion=scientific_particle_id(event_id()), k_before=event.k_before, fractional_k=event.fractional_k, t_us=event.t_us, x_mm=event.x_mm, y_mm=0, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us}, phase_fields)
    elseif event.kind == 'central_plane' and event.stage == 'main_drift' then
      crossings[ion_number] = (crossings[ion_number] or 0) + 1
      local n = crossings[ion_number]
      record_scientific('central_plane', {ion=scientific_particle_id(event_id()), n=string.format('%d',n), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm})
      record_scientific('central_plane_directional', {ion=scientific_particle_id(event_id()), n=string.format('%d',n), direction_z=string.format('%d',event.direction), t_us=event.t_us, x_mm=event.x_mm, y_mm=event.y_mm, z_mm=event.z_mm, vx_mm_us=event.vx_mm_us, vy_mm_us=event.vy_mm_us, vz_mm_us=event.vz_mm_us})
    end
  end
  -- Flush the complete turn event group, never every integration step.
  if has_mirror_turn then io.flush() end
  local state = cycle_counters[ion_number]:state()
  turns[ion_number] = state.accepted_main_turns
  return state
end

function segment.initialize_run()
  initialize_scientific_output()
  trajectory_sample_buckets = {}
  solver_birth_times = {}
  detector_native_contacts = {}
  applied_native_corridor_values, applied_accelerator_values = nil, nil
  sim_trajectory_quality = trajectory_quality
  previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
  turns, slow_turns, crossings, y0_crossings, p1_crossings, detected, splat_codes, splat_event_emitted = {}, {}, {}, {}, {}, {}, {}, {}
  cycle_counters, target_k_emitted = {}, {}
  prism_stage = {}
  return_sequence_error = {}
  selected_instances = {}
  accelerator_pulse_complete = {}
  accelerator_safe_exit_observed = {}
  accelerator_geometric_exit_observed = {}
  assert(simion.wb and #simion.wb.instances == maximum_instance_number(),
    'native-corridor flight has wrong role-bound instance count')
  -- Roles are the explicit priority-contract slots verified when the IOB is
  -- built.  Published PA basenames are provenance details, not role identity;
  -- direct read-only reuse must not require old per-trial projection names.
  for index,role in ipairs(expected_roles) do
    local instance = role_instance(role)
    assert(instance == index,
      string.format('native-corridor role %s resolved to wrong instance %d', role, instance))
    local filename = assert(simion.wb.instances[instance].filename,
      'native-corridor role '..role..' has no PA filename')
    assert(type(filename) == 'string' and #filename > 0,
      'native-corridor role '..role..' has an empty PA filename')
    if role == 'analyzer_collision_patch' then
      local function normalized(path) return path:gsub('\\','/'):lower() end
      local pa_path = assert(simion.wb.instances[instance].pa.path, 'collision patch PA path is unavailable')
      assert(normalized(pa_path) == normalized(collision_overlay.pa_path),
        'flight collision patch PA differs from its verified projection')
    end
  end
  -- SIMION does not invoke fast_adjust automatically when a PA0 controller is
  -- loaded without adj_elect globals.  Apply both consumed voltage tables once
  -- here, immediately before the run, without saving either PA.
  segment.fast_adjust()
  if static_field then
    print('MRTOF_CANDIDATE: status=prototype geometry='..tostring(role_count)..'_collision_instances field='..(static_field.mode or 'comsol_static_scalar_v')..' fast_adjust=false gui_field_queries_equivalent=false')
  else
    print('MRTOF_CANDIDATE: status=prototype geometry=native_corridor_4_instance corridor_fast_adjust=8_channel accelerator_fast_adjust=profile_sized')
  end
end

function segment.fast_adjust()
  if measured_mode then
    assert(runtime_fast_adjust_enable == 0, 'measured IP field cannot be Fast Adjusted')
    local frozen = assert(static_field.analyzer_voltages_v)
    assert(#frozen == 20, 'IP replacement needs twenty analyzer voltage slots')
    local function same(index, value)
      assert(type(frozen[index]) == 'number' and math.abs(frozen[index]-value) <= 1e-9,
        'static IP field does not match analyzer voltage '..index)
    end
    local mirrors = {0,V_mirror_B,V_mirror_C,V_mirror_D,V_mirror_E}
    for i=1,5 do same(i,mirrors[i]*V_nonaccelerator_scale); same(i+5,mirrors[i]*V_nonaccelerator_scale) end
    same(11,V_stripe_1*V_nonaccelerator_scale); same(12,V_stripe_1*V_nonaccelerator_scale)
    same(13,V_stripe_2*V_nonaccelerator_scale); same(14,V_stripe_2*V_nonaccelerator_scale)
    same(16,V_prism_1); same(17,V_prism_2)
    for _,i in ipairs({15,18,19,20}) do same(i,0) end
    return
  end
  local current_mirror_voltages = {0,V_mirror_B,V_mirror_C,V_mirror_D,V_mirror_E}
  local values=voltage_map.physical_voltages(current_mirror_voltages,{V_stripe_1,V_stripe_2},{V_prism_1,V_prism_2},
    {V_repeller,V_grid1,V_grid2},accelerator_ring_voltages,V_nonaccelerator_scale)
  if static_field then
    assert(accelerator_pulse_mode == 'static', 'static field forbids OA pulse')
    for i=1,20 do
      assert(math.abs((values.analyser[i] or 0)-static_field.analyzer_voltages_v[i]) <= 1e-9,
        'static field does not match analyzer voltage '..i)
    end
    for i=1,#values.accelerator do
      assert(math.abs(values.accelerator[i]-static_field.accelerator_voltages_v[i]) <= 1e-9,
        'static field does not match OA voltage '..i)
    end
    return -- Collision arrays are never Fast Adjusted or written.
  end
  local requested = voltage_map.corridor_voltages(values.analyser,native_corridor_voltage_groups)
  local corridor_changed = applied_native_corridor_values == nil
  for local_id = 1,8 do
    if corridor_changed or requested[local_id] ~= applied_native_corridor_values[local_id] then corridor_changed = true; break end
  end
  local accelerator_changed = applied_accelerator_values == nil
  for local_id = 1,#values.accelerator do
    if accelerator_changed or values.accelerator[local_id] ~= applied_accelerator_values[local_id] then accelerator_changed = true; break end
  end
  if not corridor_changed and not accelerator_changed then return end
  print(string.format('MRTOF_NATIVE_FAST_ADJUST begin corridor=%s accelerator=%s',
    tostring(corridor_changed), tostring(accelerator_changed)))
  io.flush()
  if corridor_changed then
    simion.wb.instances[role_instance('native_corridor')].pa:fast_adjust(requested)
    applied_native_corridor_values = requested
  end
  if accelerator_changed then
    simion.wb.instances[accelerator_instance_number()].pa:fast_adjust(values.accelerator)
    applied_accelerator_values = values.accelerator
  end
  print(string.format('MRTOF_NATIVE_FAST_ADJUST complete corridor=%s accelerator=%s',
    tostring(corridor_changed), tostring(accelerator_changed)))
  io.flush()
end

function segment.efield_adjust()
  if static_field_adjust then
    if ion_instance >= 1 and ion_instance <= maximum_instance_number() then static_field_adjust() end
    return
  end
  if not accelerator_field_gate_requested then return end
  local accelerator_instance = accelerator_instance_number()
  if ion_instance ~= accelerator_instance then return end
  local field_active = true
  if accelerator_pulse_mode == 'initial_exit_triggered_single_center' then
    field_active = not accelerator_pulse_complete[ion_number]
  elseif accelerator_pulse_mode == 'fixed_global_time' then
    field_active = (tonumber(instrument_time_us()) or 0) < accelerator_pulse_off_time_us
  end
  if not field_active then
    -- The instance remains present as the exact electrode/collision geometry;
    -- only its solved operating field is suppressed after the pulse boundary.
    ion_dvoltsx_gu, ion_dvoltsy_gu, ion_dvoltsz_gu = 0, 0, 0
  end
end

function segment.instance_adjust()
  if not measured_mode and static_field and ion_instance == accelerator_instance_number()
      and ion_pz_mm < static_field.accelerator_front_z_mm then
    ion_instance = 0 -- Leave only the frozen OA numerical front padding.
  end
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
  if accelerator_pulse_mode == 'fixed_global_time'
      and instrument_time_us() < accelerator_pulse_off_time_us then
    ion_time_step = waveforms.cap_before_edge(instrument_time_us(), ion_time_step,
      accelerator_pulse_off_time_us)
  end
end

function segment.initialize()
  local birth_time_us = instrument_time_us()
  if measured_source then
    -- Reserved variables belong to this workbench environment, not the pure
    -- loadfile module: https://simion.com/info/lua_scope.html (2026-10-16).
    local source_state = measured_source.initialize(ion_number)
    ion_mass, ion_charge = source_state.mass, source_state.charge
    ion_time_of_birth = source_state.t
    ion_px_mm, ion_py_mm, ion_pz_mm = source_state.x, source_state.y, source_state.z
    ion_vx_mm, ion_vy_mm, ion_vz_mm = source_state.vx, source_state.vy, source_state.vz
    -- SIMION 2020 can expose TOF=0 in initialize before applying FLY2 TOB.
    -- The frozen source owns this observation epoch; never assign engine TOF.
    solver_birth_times[ion_number] = source_state.t
    birth_time_us = measured_source.instrument_time_us(source_state.t)
  end
  -- Retain the release state so a first-step plane crossing is not omitted.
  if previous_z[ion_number] == nil then
    record_trajectory_sample('birth', birth_time_us)
    previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
    previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, birth_time_us
    cycle_counters[ion_number] = mirror_cycle_counter.new(
      mirror_regions, phase_origin_mirror_side, return_mirror_side,
      target_half_oscillation_count)
    prism_stage[ion_number] = 'awaiting_p1_exit'
    if measured_mode then accelerator_safe_exit_observed[ion_number] = true end
    emit_cycle_events(cycle_counters[ion_number]:sample(cycle_sample(
      ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm, birth_time_us)))
  end
end

function segment.other_actions()
  record_trajectory_sample('step')
  if accelerator_pulse_mode == 'fixed_global_time'
      and not accelerator_pulse_complete[ion_number]
      and instrument_time_us() >= accelerator_pulse_off_time_us then
    accelerator_pulse_complete[ion_number] = true
    record_scientific('accelerator_global_pulse_applied', {ion=scientific_particle_id(event_id()), t_us=instrument_time_us(), scheduled_t_us=accelerator_pulse_off_time_us, instance=string.format('%d',ion_instance), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, trigger='fixed_global_time'})
  end
  local accelerator_instance = accelerator_instance_number()
  local maximum_instance = maximum_instance_number()
  assert(ion_instance >= 0 and ion_instance <= maximum_instance,
    'SIMION selected an undeclared workbench instance')
  if selected_instances[ion_number] ~= ion_instance then
      if not accelerator_safe_exit_observed[ion_number]
          and selected_instances[ion_number] == accelerator_instance
          and ion_instance ~= accelerator_instance then
        accelerator_safe_exit_observed[ion_number] = true
        record_scientific('accelerator_safe_exit', {ion=scientific_particle_id(event_id()), t_us=instrument_time_us(), from_instance=string.format('%d',selected_instances[ion_number]), to_instance=string.format('%d',ion_instance), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, vx_mm_us=ion_vx_mm, vy_mm_us=ion_vy_mm, vz_mm_us=ion_vz_mm})
        if accelerator_safe_exit_only then
          splat_codes[ion_number] = 1
          splat_event_emitted[ion_number] = true
          record_scientific('splat', {ion=scientific_particle_id(event_id()), code=1, t_us=instrument_time_us(), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, turns=0, central_crossings=0})
          selected_instances[ion_number] = ion_instance
          ion_splat = 1
          return
        end
      end
      if accelerator_safe_exit_observed[ion_number]
          and selected_instances[ion_number] ~= accelerator_instance
          and ion_instance == accelerator_instance then
        return_sequence_error[ion_number] = 'accelerator_reentry_after_safe_exit'
        record_scientific('accelerator_reentry', {ion=scientific_particle_id(event_id()), t_us=instrument_time_us(), instance=string.format('%d',ion_instance), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, vx_mm_us=ion_vx_mm, vy_mm_us=ion_vy_mm, vz_mm_us=ion_vz_mm})
      end
      if accelerator_pulse_mode == 'initial_exit_triggered_single_center'
          and not accelerator_pulse_complete[ion_number]
          and selected_instances[ion_number] == accelerator_instance
          and ion_instance ~= accelerator_instance then
        accelerator_pulse_complete[ion_number] = true
        record_scientific('accelerator_pulse_off', {ion=scientific_particle_id(event_id()), t_us=instrument_time_us(), from_instance=string.format('%d',selected_instances[ion_number]), to_instance=string.format('%d',ion_instance), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm})
      end
      record_scientific('instance_transition', {ion=scientific_particle_id(event_id()), t_us=instrument_time_us(), instance=string.format('%d',ion_instance), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm})
      selected_instances[ion_number] = ion_instance
  end
  -- Timeout is elapsed downstream flight, independent of instrument epoch
  -- and differing measured handoff times within the packet.
  local elapsed_us = ion_time_of_flight - (solver_birth_times[ion_number] or 0)
  if elapsed_us >= full_path_timeout_us and ion_splat == 0 then
    splat_codes[ion_number] = 2
    record_scientific('splat', {ion=scientific_particle_id(event_id()), code=2, t_us=instrument_time_us(), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, turns=string.format('%d',turns[ion_number] or 0), central_crossings=string.format('%d',crossings[ion_number] or 0)})
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
    if accelerator_exit_plane_z ~= nil
        and not accelerator_geometric_exit_observed[ion_number]
        and state.stage == 'before_main_drift'
        and prism_stage[ion_number] == 'awaiting_p1_exit'
        and pz > accelerator_exit_plane_z and ion_pz_mm <= accelerator_exit_plane_z then
      local exit = interpolated_sample(
        cycle_sample(px, py, pz, pvx, pvy, pvz, pt),
        cycle_sample(ion_px_mm, ion_py_mm, ion_pz_mm,
          ion_vx_mm, ion_vy_mm, ion_vz_mm, instrument_time_us()),
        (accelerator_exit_plane_z-pz)/dz)
      if exit.vz_mm_us < 0 then
        accelerator_geometric_exit_observed[ion_number] = true
        record_scientific('accelerator_geometric_exit', {ion=scientific_particle_id(event_id()), localization='linear_bracket', t_us=exit.t_us, x_mm=exit.x_mm, y_mm=exit.y_mm, z_mm=accelerator_exit_plane_z, vx_mm_us=exit.vx_mm_us, vy_mm_us=exit.vy_mm_us, vz_mm_us=exit.vz_mm_us})
      end
    end
    if pz > first_prism_l0.target_plane_z_mm and ion_pz_mm <= first_prism_l0.target_plane_z_mm then
      local fraction = (first_prism_l0.target_plane_z_mm-pz) / dz
      local vz = pvz + fraction*(ion_vz_mm-pvz)
      if vz < 0 then
        p1_crossings[ion_number] = (p1_crossings[ion_number] or 0) + 1
        local p1_crossing = cycle_sample(
          px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py), first_prism_l0.target_plane_z_mm,
          pvx + fraction*(ion_vx_mm-pvx), pvy + fraction*(ion_vy_mm-pvy), vz,
          pt + fraction*(instrument_time_us()-pt))
        record_scientific('p1_plane', {ion=scientific_particle_id(event_id()), n=string.format('%d',p1_crossings[ion_number]), t_us=p1_crossing.t_us, x_mm=p1_crossing.x_mm, y_mm=p1_crossing.y_mm, z_mm=p1_crossing.z_mm, vx_mm_us=p1_crossing.vx_mm_us, vy_mm_us=p1_crossing.vy_mm_us, vz_mm_us=p1_crossing.vz_mm_us})
        if state.stage == 'before_main_drift' and prism_stage[ion_number] == 'awaiting_p1_exit' then
          prism_stage[ion_number] = 'p1_complete'
          record_scientific('prism_pass', {ion=scientific_particle_id(event_id()), n=1, t_us=p1_crossing.t_us, x_mm=p1_crossing.x_mm, y_mm=p1_crossing.y_mm, z_mm=p1_crossing.z_mm, vx_mm_us=p1_crossing.vx_mm_us, vy_mm_us=p1_crossing.vy_mm_us, vz_mm_us=p1_crossing.vz_mm_us})
        end
      end
    end

    -- P2 is traversed after the physical negative-mirror pre-reflection.
    -- Its grounded shield is open along z, so collision-free entry/exit of
    -- that finite CAD envelope provides a solver-observable passage event.
    local before = cycle_sample(px, py, pz, pvx, pvy, pvz, pt)
    local after = cycle_sample(ion_px_mm, ion_py_mm, ion_pz_mm,
      ion_vx_mm, ion_vy_mm, ion_vz_mm, instrument_time_us())
    if dz > 0 and prism_stage[ion_number] == 'awaiting_p2_entry'
      and pz < prism_regions.p2.z_min_mm and ion_pz_mm >= prism_regions.p2.z_min_mm then
      local entry = interpolated_sample(before, after,
        (prism_regions.p2.z_min_mm-pz)/dz)
      if inside_region(entry, prism_regions.p2) then
        prism_stage[ion_number] = 'inside_p2_station'
        record_scientific('prism_entry', {ion=scientific_particle_id(event_id()), n=2, t_us=entry.t_us, x_mm=entry.x_mm, y_mm=entry.y_mm, z_mm=entry.z_mm, vx_mm_us=entry.vx_mm_us, vy_mm_us=entry.vy_mm_us, vz_mm_us=entry.vz_mm_us})
      end
    end
    if dz > 0 and prism_stage[ion_number] == 'inside_p2_station'
      and pz < prism_regions.p2.z_max_mm and ion_pz_mm >= prism_regions.p2.z_max_mm then
      local exit = interpolated_sample(before, after,
        (prism_regions.p2.z_max_mm-pz)/dz)
      if inside_region(exit, prism_regions.p2) then
        prism_stage[ion_number] = 'p2_complete'
        record_scientific('prism_pass', {ion=scientific_particle_id(event_id()), n=2, t_us=exit.t_us, x_mm=exit.x_mm, y_mm=exit.y_mm, z_mm=exit.z_mm, vx_mm_us=exit.vx_mm_us, vy_mm_us=exit.vy_mm_us, vz_mm_us=exit.vz_mm_us})
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
      local inside_aperture = reference.x_mm >= p2_low_field_reference.x_min_mm
          and reference.x_mm <= p2_low_field_reference.x_max_mm
          and reference.y_mm >= p2_low_field_reference.y_min_mm
          and reference.y_mm <= p2_low_field_reference.y_max_mm
      local direction_ok = reference.vy_mm_us > 0 and reference.vz_mm_us > 0
      p2_low_field_reference_emitted[ion_number] = true
      record_scientific('p2_low_field_crossing', {ion=scientific_particle_id(event_id()), t_us=reference.t_us, x_mm=reference.x_mm, y_mm=reference.y_mm, z_mm=reference.z_mm, vx_mm_us=reference.vx_mm_us, vy_mm_us=reference.vy_mm_us, vz_mm_us=reference.vz_mm_us, inside_aperture=string.format('%d',inside_aperture and 1 or 0), direction_ok=string.format('%d',direction_ok and 1 or 0), fraction=string.format('%.17g',(p2_low_field_reference.z_mm-pz)/dz), before_t_us=string.format('%.17g',before.t_us), before_z_mm=string.format('%.17g',before.z_mm), before_vy_mm_us=string.format('%.17g',before.vy_mm_us), before_vz_mm_us=string.format('%.17g',before.vz_mm_us), after_t_us=string.format('%.17g',after.t_us), after_z_mm=string.format('%.17g',after.z_mm), after_vy_mm_us=string.format('%.17g',after.vy_mm_us), after_vz_mm_us=string.format('%.17g',after.vz_mm_us)})
      if inside_aperture and direction_ok then
        record_scientific('p2_low_field_reference', {ion=scientific_particle_id(event_id()), t_us=reference.t_us, x_mm=reference.x_mm, y_mm=reference.y_mm, z_mm=reference.z_mm, vx_mm_us=reference.vx_mm_us, vy_mm_us=reference.vy_mm_us, vz_mm_us=reference.vz_mm_us})
      end
    end
    if dz > 0 and prism_stage[ion_number] == 'awaiting_return_p2_entry'
      and pz < prism_regions.p2.z_min_mm and ion_pz_mm >= prism_regions.p2.z_min_mm then
      local entry = interpolated_sample(before, after,
        (prism_regions.p2.z_min_mm-pz)/dz)
      if inside_region(entry, prism_regions.p2) then
        prism_stage[ion_number] = 'inside_return_p2'
        record_scientific('return_p2_entry', {ion=scientific_particle_id(event_id()), t_us=entry.t_us, x_mm=entry.x_mm, y_mm=entry.y_mm, z_mm=entry.z_mm, vx_mm_us=entry.vx_mm_us, vy_mm_us=entry.vy_mm_us, vz_mm_us=entry.vz_mm_us})
      end
    end
    if dz > 0 and prism_stage[ion_number] == 'inside_return_p2'
      and pz < prism_regions.p2.z_max_mm and ion_pz_mm >= prism_regions.p2.z_max_mm then
      local exit = interpolated_sample(before, after,
        (prism_regions.p2.z_max_mm-pz)/dz)
      if inside_region(exit, prism_regions.p2) then
        prism_stage[ion_number] = 'awaiting_return_positive_mirror'
        record_scientific('return_p2_pass', {ion=scientific_particle_id(event_id()), t_us=exit.t_us, x_mm=exit.x_mm, y_mm=exit.y_mm, z_mm=exit.z_mm, vx_mm_us=exit.vx_mm_us, vy_mm_us=exit.vy_mm_us, vz_mm_us=exit.vz_mm_us})
      end
    end
    state = emit_cycle_events(counter:sample(cycle_sample(
      ion_px_mm, ion_py_mm, ion_pz_mm, ion_vx_mm, ion_vy_mm, ion_vz_mm, instrument_time_us())))
    if (not state.sequence_valid or return_sequence_error[ion_number] ~= nil)
      and ion_splat == 0 then
      local rejection_reason = return_sequence_error[ion_number]
        or state.sequence_error or 'trajectory_sequence_invalid'
      splat_codes[ion_number] = 4
      splat_event_emitted[ion_number] = true
      -- ion_splat is SIMION's only programmatic stop mechanism.  Code 4 is a
      -- project topology rejection, not contact with an electrode.
      record_scientific('splat', {ion=scientific_particle_id(event_id()), code=4, termination_kind='programmatic_topology_rejection', physical_collision=0, reason=rejection_reason, t_us=instrument_time_us(), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, turns=string.format('%d',turns[ion_number] or 0), central_crossings=string.format('%d',crossings[ion_number] or 0)})
      ion_splat = 4
      return
    end
    if pvy * ion_vy_mm < 0 then
      local fraction = -pvy / (ion_vy_mm - pvy)
      slow_turns[ion_number] = (slow_turns[ion_number] or 0) + 1
      record_scientific('slow_turn', {ion=scientific_particle_id(event_id()), n=string.format('%d',slow_turns[ion_number]), t_us=pt + fraction*(instrument_time_us()-pt), x_mm=px + fraction*(ion_px_mm-px), y_mm=py + fraction*(ion_py_mm-py), z_mm=pz + fraction*(ion_pz_mm-pz)})
    end
    local detector_contact = detector_contact_sample(before, after, ion_splat,
      ion_instance, prism_stage[ion_number])
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
        local detector_direction = detector_contact and -1 or (dz < 0 and -1 or 1)
        local detector_time = pt + fraction * (instrument_time_us() - pt)
        local localization = 'linear_bracket'
        local contact_evidence = {}
        if detector_contact then
          x,y,vx,vy,vz = detector_contact.x_mm,detector_contact.y_mm,
            detector_contact.vx_mm_us,detector_contact.vy_mm_us,detector_contact.vz_mm_us
          detector_time = detector_contact.t_us
          localization = 'detector_contact_projection'
          detector_native_contacts[ion_number] = true
          contact_evidence = {native_splat=-1, raw_t_us=string.format('%.17g',instrument_time_us()),
            raw_x_mm=string.format('%.17g',ion_px_mm), raw_y_mm=string.format('%.17g',ion_py_mm), raw_z_mm=string.format('%.17g',ion_pz_mm),
            projection_dt_us=string.format('%.17g',detector_time-instrument_time_us()), step_span_us=string.format('%.17g',instrument_time_us()-pt)}
        end
        record_scientific('detector_plane', {ion=scientific_particle_id(event_id()), direction_z=string.format('%d',detector_direction), t_us=detector_time, x_mm=x, y_mm=y, z_mm=detector_z, vx_mm_us=vx, vy_mm_us=vy, vz_mm_us=vz, localization=localization}, contact_evidence)
        if detector_direction == -1
          and prism_stage[ion_number] == 'awaiting_static_detector'
          and not detected[ion_number]
          and x >= detector_box[1] and x <= detector_box[4]
          and y >= detector_box[2] and y <= detector_box[5] then
          detected[ion_number] = true
          prism_stage[ion_number] = 'static_detector_complete'
          record_scientific('detector', {ion=scientific_particle_id(event_id()), direction_z=-1, t_us=detector_time, x_mm=x, y_mm=y, z_mm=detector_z, localization=localization}, contact_evidence)
          splat_codes[ion_number] = 1
          splat_event_emitted[ion_number] = true
          record_scientific('splat', {ion=scientific_particle_id(event_id()), code=1, t_us=detector_time, x_mm=x, y_mm=y, z_mm=detector_z, turns=string.format('%d',turns[ion_number] or 0), central_crossings=string.format('%d',crossings[ion_number] or 0), localization=localization}, contact_evidence)
          ion_splat = 1
        end
      end
    end
  end
  if ion_splat ~= 0 and not splat_event_emitted[ion_number] then
    splat_event_emitted[ion_number] = true
    record_scientific('splat', {ion=scientific_particle_id(event_id()), code=string.format('%d',splat_codes[ion_number] or ion_splat), t_us=instrument_time_us(), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, turns=string.format('%d',turns[ion_number] or 0), central_crossings=string.format('%d',crossings[ion_number] or 0)})
  end
  previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
  previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, instrument_time_us()
end

function segment.terminate()
  record_trajectory_sample('terminal')
  local contact_evidence = detector_native_contacts[ion_number]
    and {native_splat=-1,localization='detector_contact_projection'} or {}
  record_scientific('terminal', {ion=scientific_particle_id(event_id()), splat=string.format('%d',splat_codes[ion_number] or 0), instance=string.format('%d',ion_instance), volts=ion_volts, t_us=instrument_time_us(), x_mm=ion_px_mm, y_mm=ion_py_mm, z_mm=ion_pz_mm, vx_mm_us=ion_vx_mm, vy_mm_us=ion_vy_mm, vz_mm_us=ion_vz_mm, turns=string.format('%d',turns[ion_number] or 0), central_crossings=string.format('%d',crossings[ion_number] or 0)}, contact_evidence)
end

function segment.terminate_run()
  if scientific_events then scientific_events:close();scientific_events=nil end
  if scientific_trajectory then scientific_trajectory:close();scientific_trajectory=nil end
end
