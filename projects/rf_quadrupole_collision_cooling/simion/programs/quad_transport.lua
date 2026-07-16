-- RF-only transport profile for the SIMION built-in quadrupole geometry.
-- Geometry axis is PA z and workbench x; workbench y/z are transverse.

simion.workbench_program()

adjustable transport_rf_peak_v = 139.81792
adjustable transport_frequency_hz = 1.1E6
adjustable transport_phase_deg = 0.0
adjustable transport_axis_voltage_v = 0.0
adjustable transport_entrance_voltage_v = 0.0
adjustable transport_exit_voltage_v = 0.0
adjustable transport_detector_voltage_v = 0.0
adjustable transport_rf_steps_per_period = 20
adjustable transport_max_elapsed_us = 80.0

local omega = transport_frequency_hz * 1E-6 * 2 * math.pi
local phase = transport_phase_deg * math.pi / 180
local birth_time = {}
local max_rod_radius = {}
local max_radius = {}
local hits = 0
local crossings = 0
local particle_file

local function radial_mm()
  return math.sqrt(ion_py_mm^2 + ion_pz_mm^2)
end

function segment.initialize_run()
  birth_time = {}
  max_rod_radius = {}
  max_radius = {}
  hits = 0
  crossings = 0
  local path = os.getenv('RFQUAD_SIMION_PARTICLE_CSV')
  assert(path and path ~= '', 'RFQUAD_SIMION_PARTICLE_CSV is not set')
  particle_file = assert(io.open(path, 'w'))
  particle_file:write('particle_id,crossed_detector_plane,hit,arrival_time_us,detector_plane_radius_mm,max_rod_radius_mm,max_radius_mm,terminate_x_mm,terminate_y_mm,terminate_z_mm\n')
end

function segment.init_p_values()
  adj_elect03 = transport_entrance_voltage_v
  adj_elect04 = transport_exit_voltage_v
  adj_elect05 = transport_detector_voltage_v
end

function segment.fast_adjust()
  local rf = transport_rf_peak_v * math.sin(ion_time_of_flight * omega + phase)
  adj_elect01 = transport_axis_voltage_v + rf
  adj_elect02 = transport_axis_voltage_v - rf
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step,
    1E6 / transport_frequency_hz / transport_rf_steps_per_period)
end

function segment.initialize()
  birth_time[ion_number] = ion_time_of_flight
  max_rod_radius[ion_number] = radial_mm()
  max_radius[ion_number] = radial_mm()
end

function segment.other_actions()
  local radius = radial_mm()
  max_radius[ion_number] = math.max(max_radius[ion_number] or radius, radius)
  if ion_px_mm >= 5.8 and ion_px_mm <= 85.4 then
    max_rod_radius[ion_number] = math.max(max_rod_radius[ion_number] or radius, radius)
  end
  if ion_time_of_flight - (birth_time[ion_number] or 0) >= transport_max_elapsed_us then
    ion_splat = -4
  end
end

function segment.terminate()
  local radius = radial_mm()
  -- SIMION reports an electrode splat slightly in front of the fractional
  -- surface.  The detector begins at x=95.2 mm and one PA cell is 0.2 mm;
  -- 94.7 mm is safely downstream of the exit-enclosure front wall (90.2 mm)
  -- while allowing the integrator's surface back-off.
  local crossed = ion_px_mm >= 94.7
  local hit = crossed and radius <= 3.6
  if crossed then crossings = crossings + 1 end
  if hit then hits = hits + 1 end
  particle_file:write(string.format('%d,%d,%d,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g\n',
    ion_number, crossed and 1 or 0, hit and 1 or 0,
    hit and ion_time_of_flight or 0/0, crossed and radius or 0/0,
    max_rod_radius[ion_number] or 0/0, max_radius[ion_number] or radius,
    ion_px_mm, ion_py_mm, ion_pz_mm))
end

function segment.terminate_run()
  if particle_file then particle_file:close() end
  local summary_path = os.getenv('RFQUAD_SIMION_SUMMARY_JSON')
  assert(summary_path and summary_path ~= '', 'RFQUAD_SIMION_SUMMARY_JSON is not set')
  local summary = assert(io.open(summary_path, 'w'))
  summary:write(string.format(
    '{\n  "solver": "SIMION",\n  "mode": "transport_no_collision",\n  "collision_model": "none",\n  "particles": %d,\n  "detector_plane_crossings": %d,\n  "hits": %d,\n  "transmission": %.12g,\n  "rf_peak_V": %.12g,\n  "frequency_Hz": %.12g,\n  "rf_steps_per_period": %.12g\n}\n',
    sim_ions_count, crossings, hits, hits/sim_ions_count,
    transport_rf_peak_v, transport_frequency_hz, transport_rf_steps_per_period))
  summary:close()
  print(string.format('RFQUAD_STATUS particles=%d crossings=%d hits=%d transmission=%.12g',
    sim_ions_count, crossings, hits, hits/sim_ions_count))
end
