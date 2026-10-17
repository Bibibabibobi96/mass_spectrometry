-- Project-imposed analytical potentials, NOT an electrode/Laplace field solution.
-- Coordinates: x guide -> HP -> LP, y extraction, z other transverse axis [mm].
-- Time is instrument time [us]; injected rf_voltage_v is the instantaneous
-- single-polarity rod voltage from common/multipole/simion_rf_drive.lua [V].
-- This pure module owns no waveform, SIMION callback, particle, or file I/O.
local model = {}

local function finite(value, name)
  assert(type(value) == 'number' and value == value and math.abs(value) < math.huge,
    name .. ' must be finite')
  return value
end

-- Cubic smoothstep with its exact x derivative. Interface mixing deliberately
-- imposes fringe fields: its Laplacian generally is nonzero, even though each
-- isolated multipole and pre-extraction DC quadrupole is harmonic.
local function blend(x, center, halfwidth)
  local u = (x - center + halfwidth) / (2 * halfwidth)
  if u <= 0 then return 0, 0 end
  if u >= 1 then return 1, 0 end
  return u * u * (3 - 2 * u), 3 * u * (1 - u) / halfwidth
end

local function trap(x, y, z, center, curvature, offset, rf, r0, extraction, gradient)
  local dx = x - center
  local p = 0.5 * curvature * dx * dx - 0.25 * curvature * z * z + offset
  local gx, gy, gz = curvature * dx, 0, -0.5 * curvature * z
  if extraction then
    -- Retain axial localization, remove y DC deconfinement, and impose the
    -- push-pull extraction field. This switched idealization is non-Laplacian.
    p, gy = p - gradient * y, -gradient
  else
    local rf_scale = rf / (r0 * r0)
    p = p - 0.25 * curvature * y * y + rf_scale * (y * y - z * z)
    gy = -0.5 * curvature * y + 2 * rf_scale * y
    gz = gz - 2 * rf_scale * z
  end
  return p, gx, gy, gz
end

function model.new(baseline)
  assert(type(baseline) == 'table' and baseline.schema_version == 1,
    'field model requires baseline schema_version 1')
  local geometry, electric, schedule, gas = {}, {}, {}, {}
  for name, target in pairs({geometry=geometry, electric=electric, schedule=schedule, gas=gas}) do
    assert(type(baseline[name]) == 'table', 'missing baseline.' .. name)
    for key, value in pairs(baseline[name]) do
      if name=='electric' and key=='rf_quench_alignment' then
        assert(value=='requested_time' or value=='next_cosine_zero',
          'unsupported electric.rf_quench_alignment')
        -- This analytic reference retains its own historical pulse formula;
        -- the native waveform consumes separately compiled native_timing.
        target[key]=value
      else target[key] = finite(value, name .. '.' .. key) end
    end
  end
  local g, e, s = geometry, electric, schedule
  for _, key in ipairs({'guide_length_mm', 'hp_length_mm', 'lp_length_mm', 'r0_mm',
    'guide_r0_mm', 'interface_halfwidth_mm', 'guide_blend_halfwidth_mm'}) do
    assert(g[key] and g[key] > 0, 'geometry.' .. key .. ' must be positive')
  end
  assert(g.guide_order == 4, 'field model requires octupole guide_order 4')
  for _, key in ipairs({'hp_center_mm', 'lp_center_mm', 'extraction_end_y_mm'}) do
    finite(g[key], 'geometry.' .. key)
  end
  for _, key in ipairs({'rf_peak_to_peak_v', 'guide_rf_peak_to_peak_v',
    'hp_axial_curvature_v_per_mm2', 'lp_axial_curvature_v_per_mm2',
    'lp_capture_offset_v', 'hp_transfer_offset_v', 'hp_transfer_gradient_v_per_mm',
    'lp_transfer_axial_curvature_v_per_mm2', 'lift_v',
    'extraction_gradient_v_per_mm'}) do
    finite(e[key], 'electric.' .. key)
  end
  assert(e.rf_peak_to_peak_v > 0, 'RF peak-to-peak voltage must be positive')
  assert(s.capture_end_us >= 0 and s.transfer_end_us > s.capture_end_us and
    s.lift_end_us > s.transfer_end_us and s.extraction_start_us == s.lift_end_us and
    s.terminal_us > s.extraction_start_us, 'invalid pulse schedule')
  assert(gas.hp_pressure_pa >= 0 and gas.lp_pressure_pa >= 0,
    'gas pressures must be non-negative')
  g.guide_end_mm = g.guide_length_mm
  g.hp_end_mm = g.guide_end_mm + g.hp_length_mm
  g.lp_end_mm = g.hp_end_mm + g.lp_length_mm
  local guide_ratio = e.guide_rf_peak_to_peak_v / e.rf_peak_to_peak_v
  local guide_r04 = g.guide_r0_mm ^ 4

  local function stage(t_us)
    if t_us < s.capture_end_us then return 'capture' end
    if t_us < s.transfer_end_us then return 'transfer' end
    if t_us < s.extraction_start_us then return 'lift' end
    if t_us < s.terminal_us then return 'extraction' end
    return 'terminal'
  end

  local function offsets(t_us)
    if t_us < s.capture_end_us then return 0, e.lp_capture_offset_v end
    if t_us < s.transfer_end_us then return e.hp_transfer_offset_v, 0 end
    if t_us >= s.lift_end_us then return e.hp_transfer_offset_v, e.lift_v end
    local u = (t_us - s.transfer_end_us) / (s.lift_end_us - s.transfer_end_us)
    return e.hp_transfer_offset_v, e.lift_v * u * u * (3 - 2 * u)
  end

  local function lp_curvature(t_us)
    if t_us < s.transfer_end_us then return e.lp_transfer_axial_curvature_v_per_mm2 end
    if t_us >= s.lift_end_us then return e.lp_axial_curvature_v_per_mm2 end
    local u = (t_us - s.transfer_end_us) / (s.lift_end_us - s.transfer_end_us)
    return e.lp_transfer_axial_curvature_v_per_mm2 + u * u * (3 - 2 * u) *
      (e.lp_axial_curvature_v_per_mm2 - e.lp_transfer_axial_curvature_v_per_mm2)
  end

  local function evaluate(x, y, z, t_us, rf_voltage_v)
    local a, da = blend(x, g.guide_end_mm, g.guide_blend_halfwidth_mm)
    local b, db = blend(x, g.hp_end_mm, g.interface_halfwidth_mm)
    local hp_offset, lp_offset = offsets(t_us)
    local rf = rf_voltage_v
    local guide_scale = rf * guide_ratio / guide_r04
    -- Re[(y + iz)^4] and its analytical derivatives.
    local pg = guide_scale * (y ^ 4 - 6 * y * y * z * z + z ^ 4)
    local gyg = guide_scale * (4 * y ^ 3 - 12 * y * z * z)
    local gzg = guide_scale * (4 * z ^ 3 - 12 * y * y * z)
    local ph, gxh, gyh, gzh = trap(x, y, z, g.hp_center_mm,
      e.hp_axial_curvature_v_per_mm2, hp_offset, rf, g.r0_mm, false, 0)
    -- The HP cell is biased so its axial potential equals zero at the guide
    -- interface during capture. A switched auxiliary wedge removes the HP
    -- minimum during transfer; its slope and offset are explicit baseline inputs.
    ph = ph - 0.5 * e.hp_axial_curvature_v_per_mm2 *
      (g.guide_end_mm - g.hp_center_mm) ^ 2
    if t_us >= s.capture_end_us then
      ph = ph - e.hp_transfer_gradient_v_per_mm * (x - g.hp_center_mm)
      gxh = gxh - e.hp_transfer_gradient_v_per_mm
    end
    local pl, gxl, gyl, gzl = trap(x, y, z, g.lp_center_mm,
      lp_curvature(t_us), lp_offset, rf, g.r0_mm,
      t_us >= s.extraction_start_us, e.extraction_gradient_v_per_mm)
    local trap_p = (1 - b) * ph + b * pl
    local p = (1 - a) * pg + a * trap_p
    local gx = da * (trap_p - pg) + a * ((1 - b) * gxh + b * gxl + db * (pl - ph))
    local gy = (1 - a) * gyg + a * ((1 - b) * gyh + b * gyl)
    local gz = (1 - a) * gzg + a * ((1 - b) * gzh + b * gzl)
    return p, gx, gy, gz
  end

  local function potential(x_mm, y_mm, z_mm, t_us, rf_voltage_v)
    local p = evaluate(x_mm, y_mm, z_mm, t_us, rf_voltage_v)
    return p
  end

  local function gradient(x_mm, y_mm, z_mm, t_us, rf_voltage_v)
    local _, gx, gy, gz = evaluate(x_mm, y_mm, z_mm, t_us, rf_voltage_v)
    return gx, gy, gz
  end

  local function pressure(x_mm, y_mm, z_mm, _t_us)
    -- Gas is an imposed piecewise constant bath inside the rectangular trap.
    -- The guide and external extraction channel are vacuum in this abstraction.
    if math.abs(y_mm) >= g.r0_mm or math.abs(z_mm) >= g.r0_mm then return 0 end
    if x_mm >= g.guide_end_mm and x_mm < g.hp_end_mm then return gas.hp_pressure_pa end
    if x_mm >= g.hp_end_mm and x_mm <= g.lp_end_mm then return gas.lp_pressure_pa end
    return 0
  end

  return {potential=potential, gradient=gradient, stage=stage, pressure=pressure,
    geometry=geometry, field_kind='imposed_analytical_non_laplace_interfaces'}
end

return model
