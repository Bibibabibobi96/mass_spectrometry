-- Callback-neutral pulse timing hook.  The assembler injects the one canonical
-- instrument clock; this module never reads a SIMION-native time variable.

local pulse = {}

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

function pulse.new(config)
  local has_timing = config.pulse_time_us ~= nil or config.pulse_width_us ~= nil
  exact_keys(config, has_timing and {canonical_clock=true, voltage_waveforms=true, pulse_time_us=true,
    pulse_width_us=true, pulse_mode=true} or {canonical_clock=true, voltage_waveforms=true, pulse_mode=true}, 'pulse config')
  assert(type(config.canonical_clock) == 'function', 'canonical_clock must be a function')
  assert(type(config.voltage_waveforms) == 'table' and
    type(config.voltage_waveforms.cap_before_edge) == 'function' and
    type(config.voltage_waveforms.rectangular_gate) == 'function',
    'voltage_waveforms must provide cap_before_edge and rectangular_gate')
  local cap_before_edge = config.voltage_waveforms.cap_before_edge
  local rectangular_gate = config.voltage_waveforms.rectangular_gate
  local pulse_time_us, pulse_end_us
  if has_timing then
    pulse_time_us = finite(config.pulse_time_us, 'pulse_time_us')
    local width = finite(config.pulse_width_us, 'pulse_width_us')
    assert(width > 0, 'pulse_width_us must be positive')
    pulse_end_us = finite(pulse_time_us + width, 'pulse end')
    assert(pulse_end_us > pulse_time_us, 'pulse end must be later than start')
  end
  local pulse_mode = config.pulse_mode
  assert(type(pulse_mode) == 'function', 'pulse_mode must be a function')

  local function mode()
    local value = pulse_mode()
    assert(value == 0 or value == 1 or value == 2, 'pulse mode must be 0, 1, or 2')
    assert(has_timing or value == 2, 'timing-free pulse must remain held OFF')
    return value
  end

  local function instrument_time_us()
    return finite(config.canonical_clock(), 'canonical instrument_time_us')
  end

  local function state_at(time_us)
    time_us = finite(time_us, 'instrument_time_us')
    local selected_mode = mode()
    if not has_timing then
      return {instrument_time_us=time_us, pulse_mode=selected_mode, active=false}
    end
    local active, next_edge_us = selected_mode == 0, nil
    if selected_mode == 1 then
      active, next_edge_us = rectangular_gate(time_us, pulse_time_us, pulse_end_us)
    end
    return {instrument_time_us=time_us, pulse_effective_time_us=pulse_time_us,
      tof_since_pulse_us=time_us-pulse_time_us, pulse_mode=selected_mode,
      active=active, next_edge_us=next_edge_us}
  end

  local function cap_timestep_at(time_us, current_dt_us)
    current_dt_us = finite(current_dt_us, 'current_dt_us')
    assert(current_dt_us >= 0, 'current_dt_us must be nonnegative')
    local state = state_at(time_us)
    if state.next_edge_us ~= nil then
      return cap_before_edge(state.instrument_time_us, current_dt_us, state.next_edge_us)
    end
    return current_dt_us
  end

  return {
    instrument_time_us=instrument_time_us,
    state_at=state_at,
    is_active_at=function(time_us) return state_at(time_us).active end,
    cap_timestep_at=cap_timestep_at,
    diagnostics_at=state_at,
  }
end

return pulse
