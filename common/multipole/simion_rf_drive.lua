-- Pure RF/DC rod-drive kernel shared by SIMION multipole Programs.
-- This module owns no SIMION callback, workbench, clock, or adjustable state.

local kernel = {}

local function finite_number(value, label)
  assert(type(value) == 'number' and value == value and math.abs(value) < math.huge,
    label .. ' must be one finite number')
  return value
end

local function exact_keys(value, expected, label)
  assert(type(value) == 'table', label .. ' must be one table')
  for key, _ in pairs(value) do
    assert(expected[key], label .. ' contains unknown field: ' .. tostring(key))
  end
  for key, _ in pairs(expected) do
    assert(value[key] ~= nil, label .. ' is missing field: ' .. key)
  end
end

function kernel.new(config)
  exact_keys(config, {
    waveform=true, frequency_hz=true, phase_rad=true, rf_amplitude_v=true,
    rf_scale=true, common_mode_scale=true, group_dc_v=true,
    rf_steps_per_period=true, electrodes=true,
  }, 'RF drive config')
  assert(config.waveform == 'sine' or config.waveform == 'cosine',
    'RF drive waveform must be sine or cosine')
  local frequency_hz = finite_number(config.frequency_hz, 'RF drive frequency_hz')
  local phase_rad = finite_number(config.phase_rad, 'RF drive phase_rad')
  local rf_amplitude_v = finite_number(config.rf_amplitude_v, 'RF drive rf_amplitude_v')
  local rf_scale = finite_number(config.rf_scale, 'RF drive rf_scale')
  local common_mode_scale = finite_number(
    config.common_mode_scale, 'RF drive common_mode_scale')
  assert(frequency_hz > 0, 'RF drive frequency_hz must be positive')
  assert(rf_amplitude_v >= 0, 'RF drive rf_amplitude_v must be non-negative')
  assert(rf_scale >= 0, 'RF drive rf_scale must be non-negative')
  assert(common_mode_scale >= 0, 'RF drive common_mode_scale must be non-negative')
  assert(type(config.rf_steps_per_period) == 'number' and
    config.rf_steps_per_period == math.floor(config.rf_steps_per_period) and
    config.rf_steps_per_period > 0,
    'RF drive rf_steps_per_period must be one positive integer')
  exact_keys(config.group_dc_v, {[1]=true, [2]=true}, 'RF drive group_dc_v')
  local group_dc_1 = finite_number(config.group_dc_v[1], 'RF drive group 1 DC')
  local group_dc_2 = finite_number(config.group_dc_v[2], 'RF drive group 2 DC')
  assert(type(config.electrodes) == 'table' and #config.electrodes > 0,
    'RF drive electrodes must be one non-empty array')

  local ids, polarities, common_modes, group_dc = {}, {}, {}, {}
  local seen = {}
  for index, electrode in ipairs(config.electrodes) do
    exact_keys(electrode, {
      electrode_id=true, electrode_group=true, polarity=true, common_mode_v=true,
    }, 'RF drive electrode')
    local electrode_id = electrode.electrode_id
    local group = electrode.electrode_group
    local polarity = electrode.polarity
    assert(type(electrode_id) == 'number' and electrode_id == math.floor(electrode_id)
      and electrode_id >= 1 and electrode_id <= 1000,
      'RF drive electrode_id must be an integer from 1 through 1000')
    assert(not seen[electrode_id], 'RF drive electrode_id must be unique')
    assert(group == 1 or group == 2, 'RF drive electrode_group must be 1 or 2')
    assert(polarity == (group == 1 and 1 or -1),
      'RF drive polarity must match electrode_group')
    seen[electrode_id] = true
    ids[index] = electrode_id
    polarities[index] = polarity
    common_modes[index] = finite_number(
      electrode.common_mode_v, 'RF drive electrode common_mode_v')
    group_dc[index] = group == 1 and group_dc_1 or group_dc_2
  end
  local array_count = 0
  for key, _ in pairs(config.electrodes) do
    assert(type(key) == 'number' and key == math.floor(key) and
      key >= 1 and key <= #config.electrodes,
      'RF drive electrodes must be one contiguous array')
    array_count = array_count + 1
  end
  assert(array_count == #config.electrodes,
    'RF drive electrodes must be one contiguous array')

  local omega_per_us = frequency_hz * 1e-6 * 2 * math.pi
  local timestep_cap_us = 1e6 / frequency_hz / config.rf_steps_per_period
  local wave = config.waveform == 'sine' and math.sin or math.cos

  local function phase_at(instrument_time_us)
    return finite_number(instrument_time_us, 'RF drive instrument_time_us') *
      omega_per_us + phase_rad
  end

  local function differential_at(instrument_time_us)
    return rf_scale * rf_amplitude_v * wave(phase_at(instrument_time_us))
  end

  local function apply_static(setter)
    assert(type(setter) == 'function', 'RF drive setter must be one function')
    for index = 1, #ids do
      setter(ids[index], common_mode_scale * common_modes[index] + group_dc[index])
    end
  end

  local function apply_at(instrument_time_us, setter)
    assert(type(setter) == 'function', 'RF drive setter must be one function')
    local differential = differential_at(instrument_time_us)
    for index = 1, #ids do
      setter(ids[index], common_mode_scale * common_modes[index] +
        group_dc[index] + polarities[index] * differential)
    end
  end

  -- Apply only the alternating component.  This is for a PA whose static
  -- common-mode and DC contribution was materialized natively before Fly'm;
  -- callers must not combine it with an absolute-voltage update.
  local function apply_differential_at(instrument_time_us, setter)
    assert(type(setter) == 'function', 'RF drive setter must be one function')
    local differential = differential_at(instrument_time_us)
    for index = 1, #ids do
      setter(ids[index], polarities[index] * differential)
    end
  end

  return {
    phase_at=phase_at,
    differential_at=differential_at,
    apply_static=apply_static,
    apply_at=apply_at,
    apply_differential_at=apply_differential_at,
    timestep_cap_us=timestep_cap_us,
  }
end

return kernel
