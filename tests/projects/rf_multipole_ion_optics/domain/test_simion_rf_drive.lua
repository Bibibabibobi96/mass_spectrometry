-- Pure-Lua numerical and contract checks for the shared RF drive kernel.
-- Run through SIMION's supported Lua CLI; no workbench, PA, refine, or Fly is used.

local kernel_path = assert(arg[1], 'RF drive kernel path is required')
local kernel = assert(dofile(kernel_path), 'RF drive kernel did not return a module')

local function near(actual, expected, label)
  local tolerance = 1e-11 * math.max(1, math.abs(expected))
  assert(math.abs(actual - expected) <= tolerance,
    label .. ': expected ' .. expected .. ', got ' .. actual)
end

local function captures(drive, time_us)
  local values = {}
  drive.apply_at(time_us, function(electrode_id, voltage)
    values[electrode_id] = voltage
  end)
  return values
end

local function config(waveform, phase_rad, steps)
  return {
    waveform=waveform,
    frequency_hz=1e6,
    phase_rad=phase_rad,
    rf_amplitude_v=100,
    rf_scale=0.5,
    common_mode_scale=2,
    group_dc_v={[1]=3, [2]=-7},
    rf_steps_per_period=steps,
    electrodes={
      {electrode_id=11, electrode_group=1, polarity=1, common_mode_v=10},
      {electrode_id=12, electrode_group=2, polarity=-1, common_mode_v=-5},
    },
  }
end

local cosine = kernel.new(config('cosine', 0, 160))
local cosine_zero = captures(cosine, 0)
near(cosine_zero[11], 73, 'cosine group 1 voltage')
near(cosine_zero[12], -67, 'cosine group 2 voltage')
near(cosine.timestep_cap_us, 0.00625, '160-step timestep cap')

local sine = kernel.new(config('sine', 0, 320))
local sine_zero = captures(sine, 0)
near(sine_zero[11], 23, 'sine group 1 DC/common voltage')
near(sine_zero[12], -17, 'sine group 2 DC/common voltage')
near(sine.timestep_cap_us, 0.003125, '320-step timestep cap')

local sine_phase = kernel.new(config('sine', math.pi / 2, 160))
local sine_phase_zero = captures(sine_phase, 0)
near(sine_phase_zero[11], 73, 'phase-shifted sine group 1 voltage')
near(sine_phase_zero[12], -67, 'phase-shifted sine group 2 voltage')

local cosine_phase = kernel.new(config('cosine', math.pi, 160))
local cosine_phase_zero = captures(cosine_phase, 0)
near(cosine_phase_zero[11], -27, 'phase-shifted cosine group 1 voltage')
near(cosine_phase_zero[12], 33, 'phase-shifted cosine group 2 voltage')

local absolute_time = captures(cosine, 0.75)
local birth_plus_elapsed = captures(cosine, 0.25 + 0.5)
near(absolute_time[11], birth_plus_elapsed[11], 'birth-clock group 1 equivalence')
near(absolute_time[12], birth_plus_elapsed[12], 'birth-clock group 2 equivalence')

local static = {}
cosine.apply_static(function(electrode_id, voltage)
  static[electrode_id] = voltage
end)
near(static[11], 23, 'static group 1 DC/common voltage')
near(static[12], -17, 'static group 2 DC/common voltage')

local differential = {}
cosine.apply_differential_at(0, function(electrode_id, voltage)
  differential[electrode_id] = voltage
end)
near(differential[11], 50, 'differential group 1 voltage')
near(differential[12], -50, 'differential group 2 voltage')

local function rejects(mutator, expected_message)
  local candidate = config('cosine', 0, 160)
  mutator(candidate)
  local ok, message = pcall(kernel.new, candidate)
  assert(not ok, 'invalid RF drive contract was accepted')
  assert(tostring(message):find(expected_message, 1, true),
    'unexpected rejection message: ' .. tostring(message))
end

rejects(function(value) value.waveform = 'triangle' end, 'waveform must be sine or cosine')
rejects(function(value) value.rf_steps_per_period = 0 end, 'positive integer')
rejects(function(value) value.electrodes[1].polarity = -1 end, 'polarity must match')
rejects(function(value) value.electrodes[2].electrode_id = 11 end, 'electrode_id must be unique')
rejects(function(value) value.unofficial = true end, 'unknown field')

local function differential_config(source)
  return {waveform=source.waveform, frequency_hz=source.frequency_hz,
    phase_rad=source.phase_rad, rf_amplitude_v=source.rf_amplitude_v,
    rf_scale=source.rf_scale, rf_steps_per_period=source.rf_steps_per_period}
end

for _, waveform in ipairs({'sine', 'cosine'}) do
  local values = config(waveform, 0.37, 80)
  values.frequency_hz, values.rf_amplitude_v, values.rf_scale = 450000, 137, 0.2
  local complete = kernel.new(values)
  local differential_only = kernel.new_differential(differential_config(values))
  local count = 0
  for key in pairs(differential_only) do
    assert(key=='phase_at' or key=='differential_at' or key=='timestep_cap_us',
      'differential-only drive must not expose electrode/static setters')
    count = count + 1
  end
  assert(count==3)
  assert(differential_only.timestep_cap_us==complete.timestep_cap_us)
  for _, time in ipairs({-2.75,0,0.75,123.125}) do
    assert(differential_only.phase_at(time)==complete.phase_at(time))
    assert(differential_only.differential_at(time)==complete.differential_at(time))
    local phase = time*values.frequency_hz*1e-6*2*math.pi+values.phase_rad
    local wave = waveform=='sine' and math.sin or math.cos
    near(differential_only.phase_at(time), phase, 'differential phase')
    near(differential_only.differential_at(time), values.rf_scale*values.rf_amplitude_v*wave(phase),
      'differential-only independent reference')
  end
end

local first_config = differential_config(config('sine', 0.25, 40))
local first = kernel.new_differential(first_config)
local before = first.differential_at(0.25)
local second_config = differential_config(config('cosine', 0.75, 160))
second_config.frequency_hz, second_config.rf_amplitude_v = 2700000, 17
local second = kernel.new_differential(second_config)
assert(first.timestep_cap_us~=second.timestep_cap_us)
assert(first.phase_at(0.25)~=second.phase_at(0.25))
assert(first.differential_at(0.25)~=second.differential_at(0.25))
second_config.phase_rad, first_config.rf_scale = 2, 99
assert(first.differential_at(0.25)==before, 'each instance freezes its own numeric inputs')

local valid = differential_config(config('cosine', 0, 160))
for _,key in ipairs({'rf_amplitude_v','rf_scale'}) do
  local value = differential_config(config('cosine', 0, 160))
  value[key] = 0
  assert(kernel.new_differential(value).differential_at(0.25)==0,
    'zero amplitude/scale remains a valid explicit RF control')
end
for key in pairs(valid) do
  local value = differential_config(config('cosine', 0, 160))
  value[key] = nil
  assert(not pcall(kernel.new_differential,value),'missing differential field accepted: '..key)
end
for _,key in ipairs({'electrodes','group_dc_v','common_mode_scale','unofficial'}) do
  local value = differential_config(config('cosine', 0, 160))
  value[key] = 0
  assert(not pcall(kernel.new_differential,value),'extra differential field accepted: '..key)
end
for _,case in ipairs({{'waveform','triangle'},{'frequency_hz',0},{'frequency_hz',-1},
  {'rf_amplitude_v',-1},{'rf_scale',-1},{'rf_steps_per_period',0},
  {'rf_steps_per_period',1.5},{'rf_steps_per_period',math.huge}}) do
  local value = differential_config(config('cosine', 0, 160))
  value[case[1]] = case[2]
  assert(not pcall(kernel.new_differential,value),'invalid differential input accepted: '..case[1])
end
for _,key in ipairs({'frequency_hz','phase_rad','rf_amplitude_v','rf_scale','rf_steps_per_period'}) do
  for _,invalid in ipairs({false,'1',math.huge,-math.huge,0/0}) do
    local value = differential_config(config('cosine', 0, 160))
    value[key] = invalid
    assert(not pcall(kernel.new_differential,value),'nonfinite/nonnumeric differential input accepted: '..key)
  end
end
for _,invalid in ipairs({false,'0',math.huge,-math.huge,0/0}) do
  assert(not pcall(first.phase_at,invalid),'invalid phase clock accepted')
  assert(not pcall(first.differential_at,invalid),'invalid differential clock accepted')
end
rejects(function(value) value.rf_steps_per_period = math.huge end, 'positive integer')

print('SIMION_RF_DRIVE_KERNEL_TEST=PASS')
