-- Callback-neutral RF/pulse/frontend hook.  OA-TOF electrode IDs remain owned
-- by the injected project electrode plan.

local frontend = {}

local function finite(value, name)
  assert(type(value) == 'number' and value == value and value > -math.huge and value < math.huge,
    name .. ' must be finite')
  return value
end

local function exact_keys(value, expected, name)
  assert(type(value) == 'table', name .. ' must be a table')
  for key, _ in pairs(value) do assert(expected[key], name .. ' has unknown field ' .. tostring(key)) end
  for key, _ in pairs(expected) do assert(value[key] ~= nil, name .. ' is missing field ' .. key) end
end

function frontend.new(config)
  exact_keys(config, {rf_drive=true, pulse_hook=true, electrode_plan=true, planes_z_mm=true},
    'frontend config')
  local rf_drive = config.rf_drive
  local pulse_hook = config.pulse_hook
  local electrode_plan = config.electrode_plan
  assert(type(rf_drive) == 'table' and type(rf_drive.apply_at) == 'function' and
    type(rf_drive.timestep_cap_us) == 'number', 'rf_drive contract is invalid')
  assert(type(pulse_hook) == 'table' and type(pulse_hook.state_at) == 'function' and
    type(pulse_hook.is_active_at) == 'function' and
    type(pulse_hook.cap_timestep_at) == 'function' and
    type(pulse_hook.diagnostics_at) == 'function', 'pulse_hook contract is invalid')
  assert(type(electrode_plan) == 'table' and type(electrode_plan.apply_at) == 'function',
    'electrode_plan contract is invalid')
  local planes = config.planes_z_mm
  assert(type(planes) == 'table' and #planes > 0, 'planes_z_mm must be a non-empty array')
  local compiled_planes = {}
  for index, value in ipairs(planes) do
    compiled_planes[index] = finite(value, 'planes_z_mm[' .. index .. ']')
    if index > 1 then assert(compiled_planes[index] > compiled_planes[index-1],
      'planes_z_mm must be strictly increasing') end
  end
  for key, _ in pairs(planes) do assert(type(key) == 'number' and key >= 1 and
    key <= #planes and key % 1 == 0, 'planes_z_mm must be a contiguous array') end

  local function initialize_particle(position_z_mm)
    position_z_mm = finite(position_z_mm, 'position_z_mm')
    local state = {last_eval_time_us=nil, last_eval_position_z_mm=nil, planes={}}
    for index, plane_z_mm in ipairs(compiled_planes) do
      state.planes[index] = {status=position_z_mm >= plane_z_mm and 'hitted' or 'approaching',
        zero_step_count=0, observed_count=0}
    end
    return state
  end

  local function apply_at(time_us, setter)
    time_us = finite(time_us, 'instrument_time_us')
    assert(type(setter) == 'function', 'electrode setter must be a function')
    local pulse_state = pulse_hook.state_at(time_us)
    rf_drive.apply_at(time_us, setter)
    electrode_plan.apply_at(time_us, pulse_state, setter)
    return pulse_state
  end

  local function plane_cap(time_us, position_z_mm, velocity_z_mm_per_us, current_dt_us, state)
    if not pulse_hook.is_active_at(time_us) or velocity_z_mm_per_us <= 0 then return current_dt_us end
    if state.last_eval_time_us == time_us and state.last_eval_position_z_mm == position_z_mm then
      return current_dt_us
    end
    state.last_eval_time_us, state.last_eval_position_z_mm = time_us, position_z_mm
    for index, plane_z_mm in ipairs(compiled_planes) do
      local plane_state = state.planes[index]
      if position_z_mm < plane_z_mm and plane_state.status ~= 'hitted' then
        local distance = plane_z_mm - position_z_mm
        local tolerance = 32 * 2.2204460492503131e-16 * math.max(1, math.abs(plane_z_mm))
        if plane_state.status == 'willhit' and math.abs(distance) <= tolerance then
          plane_state.status = 'hitting'
          plane_state.zero_step_count = plane_state.zero_step_count + 1
          assert(plane_state.zero_step_count == 1,
            'plane hitting requested more than one zero-step confirmation')
          return 0
        end
        assert(plane_state.status == 'approaching' or plane_state.status == 'willhit',
          'plane landing state is invalid')
        local crossing_time_us = distance / velocity_z_mm_per_us
        assert(crossing_time_us > 0, 'plane crossing made no representable time progress')
        if current_dt_us >= crossing_time_us then
          plane_state.status = 'willhit'
          return crossing_time_us
        end
        return current_dt_us
      end
    end
    return current_dt_us
  end

  local function cap_timestep_at(time_us, position_z_mm, velocity_z_mm_per_us, current_dt_us, state)
    time_us = finite(time_us, 'instrument_time_us')
    position_z_mm = finite(position_z_mm, 'position_z_mm')
    velocity_z_mm_per_us = finite(velocity_z_mm_per_us, 'velocity_z_mm_per_us')
    current_dt_us = finite(current_dt_us, 'current_dt_us')
    assert(current_dt_us >= 0 and type(state) == 'table' and type(state.planes) == 'table',
      'frontend timestep state is invalid')
    local result = pulse_hook.cap_timestep_at(time_us, current_dt_us)
    result = plane_cap(time_us, position_z_mm, velocity_z_mm_per_us, result, state)
    if result > rf_drive.timestep_cap_us then result = rf_drive.timestep_cap_us end
    return result
  end

  local function observe_step(previous, current, state)
    exact_keys(previous, {time_us=true, position_z_mm=true, velocity_z_mm_per_us=true},
      'previous step')
    exact_keys(current, {time_us=true, position_z_mm=true, velocity_z_mm_per_us=true},
      'current step')
    finite(previous.time_us, 'previous.time_us')
    finite(previous.position_z_mm, 'previous.position_z_mm')
    finite(previous.velocity_z_mm_per_us, 'previous.velocity_z_mm_per_us')
    finite(current.time_us, 'current.time_us')
    finite(current.position_z_mm, 'current.position_z_mm')
    finite(current.velocity_z_mm_per_us, 'current.velocity_z_mm_per_us')
    assert(current.time_us >= previous.time_us, 'observed step time must be monotonic')
    assert(type(state) == 'table' and type(state.planes) == 'table',
      'frontend observation state is invalid')
    local events = {}
    for index, plane_z_mm in ipairs(compiled_planes) do
      local plane_state = state.planes[index]
      local crossed = previous.position_z_mm < plane_z_mm and current.position_z_mm >= plane_z_mm and
        current.velocity_z_mm_per_us > 0
      if plane_state.status == 'willhit' and crossed then
        assert(current.time_us > previous.time_us, 'plane crossing made no representable time progress')
        plane_state.status = 'hitting'
        plane_state.observed_count = plane_state.observed_count + 1
        assert(plane_state.observed_count == 1, 'plane crossing was observed more than once')
        events[#events+1] = {plane_index=index, plane_z_mm=plane_z_mm,
          instrument_time_us=current.time_us, event='hitting'}
      elseif plane_state.status == 'hitting' then
        if plane_state.zero_step_count > 0 then
          local tolerance = 32 * 2.2204460492503131e-16 * math.max(1, math.abs(plane_z_mm))
          assert(current.velocity_z_mm_per_us > 0 and
            plane_z_mm-current.position_z_mm <= tolerance,
            'plane zero-step confirmation is outside boundary tolerance')
          plane_state.observed_count = plane_state.observed_count + 1
          assert(plane_state.observed_count == 1,
            'plane zero-step confirmation was observed more than once')
          events[#events+1] = {plane_index=index, plane_z_mm=plane_z_mm,
            instrument_time_us=current.time_us, event='hitting'}
        end
        plane_state.status = 'hitted'
      end
    end
    return events
  end

  return {initialize_particle=initialize_particle, apply_at=apply_at,
    cap_timestep_at=cap_timestep_at, observe_step=observe_step,
    diagnostics_at=function(time_us) return pulse_hook.diagnostics_at(time_us) end}
end

return frontend
