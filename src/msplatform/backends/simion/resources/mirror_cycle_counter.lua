-- Project-frame, per-particle main-drift event counter; no SIMION dependency.
-- The drift phase begins at the contract-selected positive mirror turn after
-- P1/P2.  Every subsequent physical mirror turn advances the phase by T0/2.
-- The baseline supplies the desired half-cycle count, so K may be changed to
-- any supported half-integer without editing this event machine.
-- Caller must resolve trajectory sampling near roots: linear interpolation is
-- event localization between supplied samples, not an integrator/convergence test.
local M = {}
local Counter = {}
Counter.__index = Counter
local fields = {'x_mm', 'y_mm', 'z_mm', 'vx_mm_us', 'vy_mm_us', 'vz_mm_us', 't_us'}

local function finite(value)
  return type(value) == 'number' and value == value and math.abs(value) < math.huge
end

local function sample_copy(sample)
  assert(type(sample) == 'table', 'sample must be a project-frame table')
  local copy = {}
  for _, key in ipairs(fields) do
    assert(finite(sample[key]), 'missing or nonfinite sample '..key)
    copy[key] = sample[key]
  end
  return copy
end

local function sign(value)
  if value > 0 then return 1 elseif value < 0 then return -1 else return 0 end
end

local function root_sample(a, b, key)
  local fraction = -a[key] / (b[key] - a[key])
  assert(fraction >= 0 and fraction <= 1, 'root is not bracketed')
  local root = {}
  for _, field in ipairs(fields) do root[field] = a[field] + fraction * (b[field] - a[field]) end
  root[key] = 0
  root.bracket_start_us, root.bracket_end_us = a.t_us, b.t_us
  root.localization = 'linear_bracket'
  return root
end

local function zero_sample(sample, confirmed_at)
  local root = sample_copy(sample)
  root.bracket_start_us, root.bracket_end_us = sample.t_us, confirmed_at.t_us
  root.localization = 'sampled_zero'
  return root
end

local function emit(self, events, kind, root)
  local event = sample_copy(root)
  event.kind, event.stage = kind, self.stage
  event.bracket_start_us, event.bracket_end_us = root.bracket_start_us, root.bracket_end_us
  event.localization = root.localization
  event.confirmed_t_us = self.last.t_us
  event.k, event.half_cycles = self.cycles, self.half_cycles
  events[#events + 1] = event
  return event
end

local function invalidate(self, event, reason)
  self.sequence_valid = false
  self.sequence_error = self.sequence_error or reason
  event.accepted, event.reason = false, reason
end

local function central_event(self, events, root, direction)
  self.central_crossings = self.central_crossings + 1
  self.last_central_t = root.t_us
  local event = emit(self, events, 'central_plane', root)
  event.direction = direction
  event.accepted = self.stage == 'main_drift'
  event.reason = event.accepted and 'diagnostic_inside_main_drift' or 'outside_main_drift'
end

local function slow_coordinate_event(self, events, root, direction)
  local event = emit(self, events, 'slow_coordinate', root)
  event.direction = direction
  event.accepted = self.stage == 'main_drift'
  event.reason = event.accepted and 'diagnostic_inside_main_drift' or 'outside_main_drift'
  if not event.accepted or direction >= 0 or self.coordinate_return_observed then return end
  self.coordinate_return_observed = true
  self.coordinate_returns = self.coordinate_returns + 1
  local observed = emit(self, events, 'drift_coordinate_return', root)
  observed.direction = direction
  local phase_turn = self.last_phase_turn
  observed.k_before = phase_turn and phase_turn.k or self.half_cycles / 2
  observed.fractional_k = observed.k_before
  if phase_turn and finite(phase_turn.period_us) and phase_turn.period_us > 0 then
    local elapsed = root.t_us - phase_turn.t_us
    if elapsed >= 0 then
      observed.phase_crossing_t_us = phase_turn.t_us
      observed.phase_crossing_y_mm = phase_turn.y_mm
      observed.phase_time_residual_us = elapsed
      observed.phase_period_us = phase_turn.period_us
      observed.fractional_k = phase_turn.k + elapsed / phase_turn.period_us
    end
  end
  observed.accepted = false
  observed.reason = 'coordinate_return_is_diagnostic_until_target_turn_phase'
end

local function mirror_event(self, events, root, before, after)
  local side = sign(root.z_mm)
  local region = side == 1 and self.positive or self.negative
  if side == 0 or root.z_mm < region.z_min_mm or root.z_mm > region.z_max_mm
    or before ~= side or after ~= -side then
    self.nonmirror_reversals = self.nonmirror_reversals + 1
    local event = emit(self, events, 'nonmirror_reversal', root)
    event.direction_before, event.direction_after = before, after
    event.accepted, event.reason = false, 'outside_mirror_or_not_outward_to_inward'
    if self.stage == 'armed_main_drift' or self.stage == 'main_drift' then
      invalidate(self, event, 'nonmirror_reversal_in_main_drift')
    end
    return
  end
  local count_key = (self.stage == 'before_main_drift' or self.stage == 'armed_main_drift') and 'pre_main_turns'
    or self.stage == 'after_main_drift' and 'post_main_turns' or 'observed_main_turns'
  self[count_key] = self[count_key] + 1
  local event = emit(self, events, 'mirror_turn', root)
  event.side, event.accepted = side, false
  if self.stage == 'armed_main_drift' then
    if self.phase ~= 'awaiting_phase_origin_turn' or side ~= self.origin_mirror_side
        or root.vy_mm_us <= 0 then
      invalidate(self, event, 'phase_origin_must_be_the_declared_outbound_mirror_turn')
      return
    end
    self.stage, self.phase = 'main_drift', 'awaiting_target_turn'
    self.pre_origin_turns = 1
    self.expected_turn_side = -self.origin_mirror_side
    self.phase_origin_turn = sample_copy(root)
    self.latest_turn_by_side[side] = {
      t_us=root.t_us, y_mm=root.y_mm, k=0, side=side
    }
    self.last_phase_turn = self.latest_turn_by_side[side]
    event.accepted, event.is_phase_origin_turn, event.is_pre_origin_turn = true, true, true
    local origin = emit(self, events, 'drift_phase_origin', root)
    origin.side, origin.period_ratio = side, 0
    return
  end
  if self.stage ~= 'main_drift' then return end
  if not self.sequence_valid then event.reason = 'invalid_sequence'; return end
  if side ~= self.expected_turn_side then
    invalidate(self, event, 'unexpected_mirror_turn')
    return
  end
  self.half_cycles = self.half_cycles + 1
  self.cycles = self.half_cycles / 2
  event.half_cycles, event.k = self.half_cycles, self.cycles
  local previous_same_side = self.latest_turn_by_side[side]
  local phase_turn = {
    t_us=root.t_us, y_mm=root.y_mm, k=self.cycles, side=side
  }
  if previous_same_side then
    phase_turn.period_us = root.t_us - previous_same_side.t_us
  end
  self.latest_turn_by_side[side] = phase_turn
  self.last_phase_turn = phase_turn
  self.expected_turn_side = -self.expected_turn_side
  emit(self, events, 'completed_half_oscillation', root).side = side
  self.accepted_main_turns, event.accepted = self.accepted_main_turns + 1, true
  local candidate = emit(self, events, 'drift_phase_candidate', root)
  candidate.side, candidate.period_ratio = side, self.half_cycles / 2
  if self.half_cycles == self.target_half_oscillation_count then
    if side ~= self.return_mirror_side then
      invalidate(self, candidate, 'target_half_cycle_reached_on_wrong_mirror_side')
      return
    end
    local returned = emit(self, events, 'drift_phase_return', root)
    returned.side, returned.period_ratio = side, self.half_cycles / 2
    returned.target_half_oscillation_count = self.target_half_oscillation_count
    returned.slow_coordinate_residual_mm = root.y_mm
    self.stage, self.phase = 'after_main_drift', 'target_opposite_mirror_turn_reached'
  elseif self.half_cycles > self.target_half_oscillation_count then
    invalidate(self, candidate, 'target_half_cycle_count_was_skipped')
  end
end

-- Preserve the last nonzero sign across zero nodes/plateaus. A zero-velocity
-- contact without a sign change is not a turn. A z=0 arrival with nonzero vz
-- owns the crossing immediately; its departure cannot count it again.
local function find_roots(self, sample)
  local roots = {}
  local v = self.v_before
  if sample.vz_mm_us == 0 then
    self.v_zero = self.v_zero or sample
  else
    if v and sign(v.vz_mm_us) ~= sign(sample.vz_mm_us) then
      local root = self.v_zero and zero_sample(self.v_zero, sample) or root_sample(v, sample, 'vz_mm_us')
      roots[#roots + 1] = {kind='turn', root=root, before=sign(v.vz_mm_us), after=sign(sample.vz_mm_us)}
    end
    self.v_before, self.v_zero = sample, nil
  end
  local z = self.z_before
  if sample.z_mm == 0 then
    self.z_zero = self.z_zero or sample
    local direction = sign(sample.vz_mm_us)
    if not self.z_zero_emitted and direction ~= 0 and
      ((z and direction == -sign(z.z_mm)) or
       (not z and self.stage == 'armed_main_drift')) then
      roots[#roots + 1] = {kind='central', root=zero_sample(self.z_zero, sample), direction=direction}
      self.z_zero_emitted = true
    end
  else
    if self.z_zero then
      if not self.z_zero_emitted and ((z and sign(z.z_mm) ~= sign(sample.z_mm)) or
        (not z and self.stage == 'armed_main_drift')) then
        roots[#roots + 1] = {kind='central', root=zero_sample(self.z_zero, sample), direction=sign(sample.z_mm)}
      end
    elseif z and sign(z.z_mm) ~= sign(sample.z_mm) then
      roots[#roots + 1] = {kind='central', root=root_sample(z, sample, 'z_mm'), direction=sign(sample.z_mm)}
    end
    self.z_before, self.z_zero, self.z_zero_emitted = sample, nil, false
  end
  local y = self.y_before
  if sample.y_mm == 0 then
    -- Keep the last node of a sampled y=0 plateau.  A turn can only be
    -- confirmed on departure, so retaining the first node would create an
    -- event timestamp earlier than a simultaneously confirmed mirror turn.
    self.y_zero = sample
  else
    if self.y_zero then
      if not self.y_zero_emitted and y and sign(y.y_mm) ~= sign(sample.y_mm) then
        local root = zero_sample(self.y_zero, sample)
        local direction = sign(root.vy_mm_us)
        if direction == 0 then direction = sign(sample.y_mm) end
        roots[#roots + 1] = {
          kind='slow_coordinate', root=root, direction=direction
        }
      end
    elseif y and sign(y.y_mm) ~= sign(sample.y_mm) then
      local root = root_sample(y, sample, 'y_mm')
      local direction = sign(root.vy_mm_us)
      if direction == 0 then direction = sign(sample.y_mm) end
      roots[#roots + 1] = {
        kind='slow_coordinate', root=root, direction=direction
      }
    end
    self.y_before, self.y_zero, self.y_zero_emitted = sample, nil, false
  end
  local root_priority = {turn=1, central=2, slow_coordinate=3}
  table.sort(roots, function(a, b)
    if a.root.t_us == b.root.t_us then return root_priority[a.kind] < root_priority[b.kind] end
    return a.root.t_us < b.root.t_us
  end)
  return roots
end

function M.new(regions, origin_mirror_side, return_mirror_side, target_half_oscillation_count)
  assert(type(regions) == 'table', 'explicit resolved mirror regions are required')
  local copy = {}
  for _, side in ipairs({'negative', 'positive'}) do
    local region = regions[side]
    assert(type(region) == 'table' and finite(region.z_min_mm) and finite(region.z_max_mm)
      and region.z_min_mm < region.z_max_mm, 'invalid '..side..' mirror z region')
    copy[side] = {z_min_mm=region.z_min_mm, z_max_mm=region.z_max_mm}
  end
  assert(copy.negative.z_max_mm < 0 and copy.positive.z_min_mm > 0,
    'mirror regions must be on opposite sides of central z=0')
  assert(origin_mirror_side == -1 or origin_mirror_side == 1,
    'phase-origin mirror side must be -1 or +1')
  assert(return_mirror_side == -origin_mirror_side,
    'return mirror side must oppose the phase-origin mirror side')
  assert(type(target_half_oscillation_count) == 'number'
      and target_half_oscillation_count > 0
      and target_half_oscillation_count == math.floor(target_half_oscillation_count),
    'target half-oscillation count must be a positive integer')
  assert(target_half_oscillation_count % 2 == 1,
    'opposite-turn return requires an odd half-oscillation count')
  copy.origin_mirror_side = origin_mirror_side
  copy.return_mirror_side = return_mirror_side
  copy.target_half_oscillation_count = target_half_oscillation_count
  copy.stage, copy.phase = 'before_main_drift', 'awaiting_arm'
  copy.cycles, copy.half_cycles, copy.accepted_main_turns = 0, 0, 0
  copy.pre_origin_turns, copy.origin_crossings = 0, 0
  copy.pre_main_turns, copy.observed_main_turns, copy.post_main_turns = 0, 0, 0
  copy.nonmirror_reversals, copy.central_crossings, copy.sequence_valid = 0, 0, true
  copy.coordinate_returns, copy.coordinate_return_observed = 0, false
  copy.latest_turn_by_side, copy.last_phase_turn = {}, nil
  return setmetatable(copy, Counter)
end

function Counter:sample(input)
  local sample = sample_copy(input)
  if self.last and sample.t_us == self.last.t_us then
    for _, key in ipairs(fields) do assert(sample[key] == self.last[key], 'conflicting simultaneous samples') end
    return {} -- Multiple callbacks may expose the exact same state.
  end
  assert(not self.last or sample.t_us > self.last.t_us, 'sample time must increase')
  self.last = sample
  local events = {}
  for _, found in ipairs(find_roots(self, sample)) do
    if found.kind == 'turn' then mirror_event(self, events, found.root, found.before, found.after)
    elseif found.kind == 'central' then central_event(self, events, found.root, found.direction)
    else slow_coordinate_event(self, events, found.root, found.direction) end
  end
  return events
end

function Counter:arm_main_drift(input)
  assert(self.stage == 'before_main_drift', 'main drift must be armed exactly once')
  local events = self:sample(input)
  self.stage, self.phase = 'armed_main_drift', 'awaiting_phase_origin_turn'
  -- Do not carry a pre-P1 bracket into the P1/P2/reference-to-turn interval.
  self.v_before, self.v_zero = nil, nil
  self.z_before, self.z_zero, self.z_zero_emitted = nil, nil, false
  self.y_before, self.y_zero, self.y_zero_emitted = self.last, nil, false
  emit(self, events, 'main_drift_armed', zero_sample(self.last, self.last))
  return events
end

function Counter:state()
  return {
    stage=self.stage, phase=self.phase, sequence_valid=self.sequence_valid,
    sequence_error=self.sequence_error,
    cycles=self.cycles, half_cycles=self.half_cycles, accepted_main_turns=self.accepted_main_turns,
    pre_origin_turns=self.pre_origin_turns, origin_crossings=self.origin_crossings,
    pre_main_turns=self.pre_main_turns, observed_main_turns=self.observed_main_turns,
    post_main_turns=self.post_main_turns, nonmirror_reversals=self.nonmirror_reversals,
    central_crossings=self.central_crossings,
    coordinate_returns=self.coordinate_returns,
    coordinate_return_observed=self.coordinate_return_observed,
    pending_zero_velocity=self.v_zero ~= nil,
    pending_central_crossing=self.z_zero ~= nil and not self.z_zero_emitted,
  }
end

return M
