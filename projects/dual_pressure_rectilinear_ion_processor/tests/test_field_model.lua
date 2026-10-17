-- Solver-independent field regression; invoked by test_field_model.py.
local module = dofile(assert(arg[1]))
local baseline = dofile(assert(arg[2]))
local rf_kernel = dofile(assert(arg[3]))
local m = module.new(baseline)
local g, e, s = baseline.geometry, baseline.electric, baseline.schedule
local comparisons = 0

local function near(actual, expected, tolerance, label)
  assert(math.abs(actual - expected) <= tolerance,
    label .. ': expected ' .. tostring(expected) .. ', got ' .. tostring(actual))
  comparisons = comparisons + 1
end

local drive = rf_kernel.new({
  waveform='cosine', frequency_hz=e.rf_frequency_hz,
  phase_rad=baseline.clock.rf_phase_rad, rf_amplitude_v=e.rf_peak_to_peak_v / 2,
  rf_scale=1, common_mode_scale=1, group_dc_v={0, 0}, rf_steps_per_period=100,
  electrodes={{electrode_id=1, electrode_group=1, polarity=1, common_mode_v=0},
    {electrode_id=2, electrode_group=2, polarity=-1, common_mode_v=0}},
})

local period_us = 1e6 / e.rf_frequency_hz
local function potential(x, y, z, t)
  return m.potential(x, y, z, t, drive.differential_at(t))
end

-- Central differences independently differentiate the scalar potential; the
-- 1e-4 mm increment balances O(h^2) truncation with cancellation at ~4000 V.
-- Absolute 2e-5 V/mm + relative 2e-7 covers that numerical differentiation error.
for _, t in ipairs({0.013, s.capture_end_us, s.transfer_end_us,
  (s.transfer_end_us + s.lift_end_us) / 2, s.extraction_start_us, s.terminal_us}) do
  for _, x in ipairs({10, g.guide_length_mm - 1.2, g.guide_length_mm,
    g.guide_length_mm + 1.2, g.hp_center_mm,
    g.guide_length_mm + g.hp_length_mm - 3,
    g.guide_length_mm + g.hp_length_mm,
    g.guide_length_mm + g.hp_length_mm + 3, g.lp_center_mm}) do
    local xyz, h = {x, 0.43, -0.29}, 1e-4
    local gradient = {m.gradient(xyz[1], xyz[2], xyz[3], t, drive.differential_at(t))}
    for axis = 1, 3 do
      local saved = xyz[axis]
      xyz[axis] = saved + h
      local plus = potential(xyz[1], xyz[2], xyz[3], t)
      xyz[axis] = saved - h
      local minus = potential(xyz[1], xyz[2], xyz[3], t)
      xyz[axis] = saved
      near(gradient[axis], (plus - minus) / (2 * h),
        2e-5 + 2e-7 * math.abs(gradient[axis]), 'potential gradient axis ' .. axis)
    end
  end
end

assert(m.stage(0) == 'capture')
assert(m.stage(s.capture_end_us) == 'transfer')
assert(m.stage(s.transfer_end_us) == 'lift')
assert(m.stage(s.extraction_start_us) == 'extraction')
assert(m.stage(s.terminal_us) == 'terminal')

-- DC cancels between the two RF phases: these are independent analytical
-- reference values for octupole and quadrupole amplitude/normalization.
local rf_difference = drive.differential_at(0) - drive.differential_at(period_us / 2)
near(potential(10, 1, 0, 0) - potential(10, 1, 0, period_us / 2),
  rf_difference * e.guide_rf_peak_to_peak_v / e.rf_peak_to_peak_v / g.guide_r0_mm ^ 4,
  1e-10, 'octupole RF amplitude')
near(potential(g.hp_center_mm, 1, 0, 0) -
  potential(g.hp_center_mm, 1, 0, period_us / 2),
  rf_difference / g.r0_mm ^ 2, 1e-10, 'quadrupole RF amplitude')

-- A spatially uniform lift adds energy reference without exerting center force;
-- away from center the explicitly scheduled LP compression also changes force.
for _, t in ipairs({s.transfer_end_us, (s.transfer_end_us + s.lift_end_us) / 2,
  s.lift_end_us - 1e-3}) do
  local gx, gy, gz = m.gradient(g.lp_center_mm, 0, 0, t, 0)
  near(gx, 0, 1e-12, 'lift center gx')
  near(gy, 0, 1e-12, 'lift center gy')
  near(gz, 0, 1e-12, 'lift center gz')
end
near(m.potential(g.lp_center_mm, 0, 0, (s.transfer_end_us + s.lift_end_us) / 2, 0),
  e.lift_v / 2, 1e-10, 'midpoint common-mode lift')

local t = s.extraction_start_us
local _, gy = m.gradient(g.lp_center_mm, 0, 0, t, 0)
near(gy, -e.extraction_gradient_v_per_mm, 1e-12, 'positive-ion extraction force sign')
near(m.potential(g.lp_center_mm, 0, 0, t, 0) -
  m.potential(g.lp_center_mm, g.extraction_end_y_mm, 0, t, 0),
  4900, 1e-10, 'analytical reference work to 9.8 mm [eV]; not native energy')
near(m.potential(g.lp_center_mm, 0.7, 0.2, t, 500),
  m.potential(g.lp_center_mm, 0.7, 0.2, t, -500), 1e-12, 'LP RF shutoff')
assert(math.abs(m.potential(g.hp_center_mm, 0.7, 0.2, t, 500) -
  m.potential(g.hp_center_mm, 0.7, 0.2, t, -500)) > 1)
near(m.potential(g.guide_length_mm, 0, 0, 0, 0), 0, 1e-12,
  'HP entrance referenced to guide DC')
local capture_gx = m.gradient(g.hp_center_mm, 0, 0, 0, 0)
local transfer_gx = m.gradient(g.hp_center_mm, 0, 0, s.capture_end_us, 0)
near(capture_gx, 0, 1e-12, 'capture HP minimum')
near(transfer_gx, -e.hp_transfer_gradient_v_per_mm, 1e-12, 'transfer wedge')

near(m.pressure(10, 0, 0, 0), 0, 0, 'guide vacuum')
near(m.pressure(g.hp_center_mm, 0, 0, 0), baseline.gas.hp_pressure_pa, 0, 'HP gas')
near(m.pressure(g.lp_center_mm, 0, 0, 0), baseline.gas.lp_pressure_pa, 0, 'LP gas')
near(m.pressure(g.lp_center_mm, g.r0_mm, 0, 0), 0, 0, 'extraction channel vacuum')
near(m.pressure(g.lp_center_mm, 0, -g.r0_mm, 0), 0, 0, 'transverse boundary vacuum')
near(m.pressure(m.geometry.lp_end_mm + 1, 0, 0, 0), 0, 0, 'downstream vacuum')

local bad = {schema_version=99}
assert(not pcall(module.new, bad), 'unknown schema must fail')
local original_alignment=e.rf_quench_alignment
for _,alignment in ipairs({'requested_time','next_cosine_zero'}) do
 e.rf_quench_alignment=alignment
 assert(pcall(module.new,baseline),'known author enum must be accepted without changing reference equations')
end
e.rf_quench_alignment='unsupported'
assert(not pcall(module.new,baseline),'unknown alignment must fail separately from numeric checks')
e.rf_quench_alignment=original_alignment
local frequency=e.rf_frequency_hz;e.rf_frequency_hz='3700000'
assert(not pcall(module.new,baseline),'numeric scientific fields must not accept strings')
e.rf_frequency_hz=frequency
print('FIELD_MODEL_TEST_PASS comparisons=' .. comparisons)
