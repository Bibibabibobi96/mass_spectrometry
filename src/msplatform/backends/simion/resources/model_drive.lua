-- Unsolved-model boundary consumer. No SIMION/particle/field API is accessed.
local model = {}

function model.new(config, rf_drive, pulse_hook, voltage_waveforms)
  assert(config.schema_version == 1 and config.role == 'simion_model_drive', 'invalid model drive')
  local modes = {held_on=0, timed=1, held_off=2}
  local mode = config.pulse and assert(modes[config.pulse.mode], 'unsupported model pulse') or nil
  local pulse_config = {voltage_waveforms=voltage_waveforms, pulse_mode=function() return mode end}
  if mode == 1 then
    pulse_config.pulse_time_us, pulse_config.pulse_width_us = config.pulse.time_us, config.pulse.width_us
  elseif mode == 0 then
    -- Held ON has no physical edges. A timed pulse is not fabricated for it.
    -- The consumer below uses the explicit constant mode without a timing hook.
  end
  local pulse = mode and mode ~= 0 and pulse_hook.compile_physical(pulse_config) or nil
  local compiled = {}
  for index, row in ipairs(config.groups) do
    local rf
    if row.kind == 'rf' then
      rf = rf_drive.compile_physical{waveform=row.waveform, frequency_hz=row.frequency_hz,
        phase_rad=row.phase_rad, rf_amplitude_v=row.rf_amplitude_v, rf_scale=1}
    end
    assert(row.kind == 'static' or row.kind == 'rf' or row.kind == 'pulse', 'unsupported group drive')
    assert(row.kind ~= 'pulse' or config.pulse, 'pulse group requires its actual pulse contract')
    compiled[index] = {row=row, rf=rf}
  end
  local function evaluate_at(time_us)
    assert(type(time_us)=='number' and time_us==time_us and math.abs(time_us)<math.huge,
      'model instrument time must be finite')
    local active = mode == 0 or (pulse and pulse.state_at(time_us).active)
    local values = {}
    for index, entry in ipairs(compiled) do
      local row, value = entry.row
      if row.kind == 'static' then value = row.voltage_v
      elseif row.kind == 'rf' then
        value = row.common_mode_v + row.dc_v + row.polarity * entry.rf.differential_at(time_us)
      else value = active and row.on_voltage_v or row.off_voltage_v end
      values[index] = {instance_id=row.instance_id, electrode_group_id=row.electrode_group_id,
        native_targets=row.native_targets, voltage_v=value, voltage_unit='V',
        instrument_time_us=time_us, field_status='not_solved'}
    end
    return values
  end
  return {evaluate_at=evaluate_at, describe=function() return config end}
end

return model
