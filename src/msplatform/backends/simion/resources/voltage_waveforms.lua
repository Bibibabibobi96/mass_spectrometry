-- Pure voltage timing mathematics; callers supply their validated clock and edges.
local waveforms = {}

function waveforms.cap_before_edge(time_us, current_dt_us, edge_us)
  local remaining_us = edge_us - time_us
  if remaining_us > 0 then return math.min(current_dt_us, remaining_us) end
  return current_dt_us
end

-- Half-open ideal pulse; the caller owns the clock and validated edges.
function waveforms.rectangular_gate(time_us, on_us, off_us)
  if time_us < on_us then return false, on_us end
  if time_us < off_us then return true, off_us end
  return false, nil
end

-- Caller supplies the normalized fraction and owns its timing/clamping policy.
function waveforms.cubic_transition(start_value, end_value, u)
  return start_value + (end_value - start_value) * u * u * (3 - 2 * u)
end

return waveforms
