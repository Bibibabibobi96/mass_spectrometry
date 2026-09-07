-- Full MR-TOF Candidate workbench program.  Candidate/prototype only.
simion.workbench_program()
-- Native SIMION 2020 regression: retain terminal callbacks outside every PA.
sim_segment_global = 1

local program_path = debug.getinfo(1, 'S').source:sub(2)
local operating_point_path = assert(program_path:gsub('%.lua$', '.operating_point.lua'))
local operating_point = assert(loadfile(operating_point_path), 'missing run-local operating-point sidecar: '..operating_point_path)()
local voltage_map_path = program_path:gsub('%.lua$', '.voltage_map.lua')
local voltage_map = assert(loadfile(voltage_map_path), 'missing run-local voltage mapper: '..voltage_map_path)()
local mirror_voltages = assert(operating_point.mirror_voltages_v, 'operating point has no mirror-voltage table')
assert(#mirror_voltages == 5 and mirror_voltages[1] == 0,
  'operating point must contain five mirror voltages with grounded A')
local detector_box = assert(operating_point.detector_box_mm, 'operating point has no numerical detector box')
local first_prism_l0 = assert(operating_point.first_prism_l0, 'operating point has no frozen P1 interface')
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
local target_turns = 2 * target_oscillation_count

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
-- The IOB builder has already applied and saved this frozen point to PA0.
-- Re-running a 20-array analyzer fast-adjust on every integration segment is
-- prohibitively expensive and changes no static-field value.  Leave this off
-- for ordinary Fly; an interactive voltage edit must rebuild/persist PA0.
adjustable runtime_fast_adjust_enable = 0
local full_path_timeout_us = assert(operating_point.full_path_timeout_us, 'operating point has no full-path timeout')
assert(full_path_timeout_us > 0, 'full-path timeout must be positive')

-- `other_actions` is called for every integration segment.  Keep the prior
-- state in scalar arrays rather than allocating a five-field table per step:
-- the latter turns a long, otherwise identical trajectory into hundreds of
-- thousands of Lua allocations and GC cycles.
local previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
local turns, slow_turns, crossings, stripe_crossings, p1_crossings, detected, splat_codes, splat_event_emitted = {}, {}, {}, {}, {}, {}, {}, {}

function segment.initialize_run()
  sim_trajectory_quality = trajectory_quality
  previous_x, previous_y, previous_z, previous_vx, previous_vy, previous_vz, previous_t = {}, {}, {}, {}, {}, {}, {}
  turns, slow_turns, crossings, stripe_crossings, p1_crossings, detected, splat_codes, splat_event_emitted = {}, {}, {}, {}, {}, {}, {}, {}
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
  accelerator:fast_adjust(values.accelerator)
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, maximum_step_us)
end

function segment.initialize()
  -- Retain the release state so a first-step plane crossing is not omitted.
  if previous_z[ion_number] == nil then
    previous_x[ion_number], previous_y[ion_number], previous_z[ion_number] = ion_px_mm, ion_py_mm, ion_pz_mm
    previous_vx[ion_number], previous_vy[ion_number], previous_vz[ion_number], previous_t[ion_number] = ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_time_of_flight
  end
end

function segment.other_actions()
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
    if pvz * ion_vz_mm < 0 then
      local fraction = -pvz / (ion_vz_mm - pvz)
      local tx = px + fraction * (ion_px_mm - px)
      local ty = py + fraction * (ion_py_mm - py)
      local tz = pz + fraction * (ion_pz_mm - pz)
      local tt = pt + fraction * (ion_time_of_flight - pt)
      turns[ion_number] = (turns[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT turn ion=%d n=%d t_us=%.12g z_mm=%.12g', ion_number, turns[ion_number], ion_time_of_flight, ion_pz_mm))
      print(string.format('MRTOF_EVENT fast_turn ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
        ion_number, turns[ion_number], tt, tx, ty, tz))
      if turns[ion_number] == target_turns then
        splat_codes[ion_number] = 1
        print(string.format('MRTOF_EVENT target_k ion=%d k=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
          ion_number, target_oscillation_count, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm))
        ion_splat = 1
        if not splat_event_emitted[ion_number] then
          splat_event_emitted[ion_number] = true
          print(string.format('MRTOF_EVENT splat ion=%d code=1 t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g turns=%d central_crossings=%d',
            ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
            turns[ion_number], crossings[ion_number] or 0))
        end
      end
    end
    if pvy * ion_vy_mm < 0 then
      local fraction = -pvy / (ion_vy_mm - pvy)
      slow_turns[ion_number] = (slow_turns[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT slow_turn ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g',
        ion_number, slow_turns[ion_number], pt + fraction*(ion_time_of_flight-pt),
        px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py), pz + fraction*(ion_pz_mm-pz)))
    end
    local dy = ion_py_mm - py
    if (py < 0 and ion_py_mm >= 0) or (py > 0 and ion_py_mm <= 0) then
      local fraction = -py / dy
      stripe_crossings[ion_number] = (stripe_crossings[ion_number] or 0) + 1
      local vy = pvy + fraction*(ion_vy_mm-pvy)
      print(string.format('MRTOF_EVENT stripe_plane ion=%d n=%d direction_y=%d t_us=%.12g x_mm=%.12g y_mm=0 z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, stripe_crossings[ion_number], vy < 0 and -1 or 1,
        pt + fraction*(ion_time_of_flight-pt), px + fraction*(ion_px_mm-px), pz + fraction*(ion_pz_mm-pz),
        pvx + fraction*(ion_vx_mm-pvx), vy, pvz + fraction*(ion_vz_mm-pvz)))
      if stripe_crossings[ion_number] == 1 and vy < 0 then
        print(string.format('MRTOF_EVENT p2_to_stripe ion=%d t_us=%.12g x_mm=%.12g y_mm=0 z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, pt + fraction*(ion_time_of_flight-pt), px + fraction*(ion_px_mm-px), pz + fraction*(ion_pz_mm-pz),
          pvx + fraction*(ion_vx_mm-pvx), vy, pvz + fraction*(ion_vz_mm-pvz)))
      end
    end
    local dz = ion_pz_mm - pz
    if pz > first_prism_l0.target_plane_z_mm and ion_pz_mm <= first_prism_l0.target_plane_z_mm then
      local fraction = (first_prism_l0.target_plane_z_mm-pz) / dz
      local vz = pvz + fraction*(ion_vz_mm-pvz)
      if vz < 0 then
        p1_crossings[ion_number] = (p1_crossings[ion_number] or 0) + 1
        print(string.format('MRTOF_EVENT p1_plane ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g z_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
          ion_number, p1_crossings[ion_number], pt + fraction*(ion_time_of_flight-pt),
          px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py), first_prism_l0.target_plane_z_mm,
          pvx + fraction*(ion_vx_mm-pvx), pvy + fraction*(ion_vy_mm-pvy), vz))
      end
    end
    -- Half-open ownership counts arrival at z=0 once, but not departure.
    if (pz < 0 and ion_pz_mm >= 0) or (pz > 0 and ion_pz_mm <= 0) then
      local fraction = -pz / dz
      crossings[ion_number] = (crossings[ion_number] or 0) + 1
      print(string.format('MRTOF_EVENT central_plane ion=%d n=%d t_us=%.12g x_mm=%.12g y_mm=%.12g',
        ion_number, crossings[ion_number], pt + fraction*(ion_time_of_flight-pt),
        px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py)))
      local vz = pvz + fraction*(ion_vz_mm-pvz)
      print(string.format('MRTOF_EVENT central_plane_directional ion=%d n=%d direction_z=%d t_us=%.12g x_mm=%.12g y_mm=%.12g vx_mm_us=%.12g vy_mm_us=%.12g vz_mm_us=%.12g',
        ion_number, crossings[ion_number], vz < 0 and -1 or 1,
        pt + fraction*(ion_time_of_flight-pt), px + fraction*(ion_px_mm-px), py + fraction*(ion_py_mm-py),
        pvx + fraction*(ion_vx_mm-pvx), pvy + fraction*(ion_vy_mm-pvy), vz))
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
