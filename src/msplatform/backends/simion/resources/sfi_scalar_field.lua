-- Callback-neutral world-scalar basis composition; no workbench globals.
local composer = {}

function composer.new(adapter, rf_kernel, pulse, bindings, rf)
  assert(type(adapter) == 'function', 'scalar adapter factory required')
  assert(type(rf_kernel) == 'table' and type(rf_kernel.compile_physical) == 'function', 'RF kernel required')
  assert(type(pulse) == 'table' and type(pulse.is_active_at) == 'function', 'pulse hook required')
  assert(type(bindings) == 'table' and bindings.carrier ~= nil and bindings.rf_reference ~= nil
    and bindings.pulse_delta ~= nil, 'three explicit scalar bindings required')
  assert(type(rf) == 'table' and rf.phase_reference_instrument_time_us == 0,
    'RF phase reference must be instrument time zero')
  -- The RF basis already includes each physical group amplitude and polarity.
  -- A unit amplitude and scale therefore produce a dimensionless waveform.
  local wave = rf_kernel.compile_physical{waveform=rf.waveform, frequency_hz=rf.frequency_hz,
    phase_rad=rf.phase_rad, rf_amplitude_v=1, rf_scale=1}
  local carrier = adapter(bindings.carrier)
  local reference = adapter(bindings.rf_reference)
  local delta = adapter(bindings.pulse_delta)
  assert(type(carrier) == 'function' and type(reference) == 'function' and type(delta) == 'function',
    'scalar adapter must return query functions')
  local function sample(instance, x, y, z, instrument_time_us)
    assert(instance ~= nil, 'selected instance required')
    -- Query all supports even when a subsequent coefficient is zero.
    local cx,cy,cz = carrier(instance,x,y,z)
    local rx,ry,rz = reference(instance,x,y,z)
    local px,py,pz = delta(instance,x,y,z)
    local coefficient = wave.differential_at(instrument_time_us)
    local active = pulse.is_active_at(instrument_time_us) and 1 or 0
    return cx + coefficient*rx + active*px,
      cy + coefficient*ry + active*py, cz + coefficient*rz + active*pz
  end
  return sample
end

return composer
