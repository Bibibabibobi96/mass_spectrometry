-- RF-only transport profile for the SIMION built-in quadrupole geometry.
-- Geometry axis is PA z and workbench x; workbench y/z are transverse.

simion.workbench_program()

local run_config_path = assert(os.getenv('RFQUAD_RUN_CONFIG_LUA'),
  'RFQUAD_RUN_CONFIG_LUA is not set')
local run_config = assert(dofile(run_config_path), 'run config did not return a table')

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
local trajectory_file
local previous_state = {}
local next_axial_plane = {}
local trajectory_plane_step_mm = 0.2

function segment.load()
  transport_rf_peak_v = assert(run_config.rf_peak_v)
  transport_frequency_hz = assert(run_config.frequency_hz)
  transport_phase_deg = assert(run_config.phase_deg)
  transport_axis_voltage_v = assert(run_config.axis_voltage_v)
  transport_entrance_voltage_v = assert(run_config.entrance_voltage_v)
  transport_exit_voltage_v = assert(run_config.exit_voltage_v)
  transport_detector_voltage_v = assert(run_config.detector_voltage_v)
  transport_rf_steps_per_period = assert(run_config.rf_steps_per_period)
  transport_max_elapsed_us = assert(run_config.maximum_time_us)
end

local function radial_mm()
  return math.sqrt(ion_py_mm^2 + ion_pz_mm^2)
end

local function write_trajectory(particle, time_us, wb_x, wb_y, wb_z)
  if not trajectory_file then return end
  -- IOB basis: PA x -> wb z, PA y -> -wb y, PA z -> wb x.
  local pa_x, pa_y, pa_z = wb_z, -wb_y, wb_x
  trajectory_file:write(string.format('%d,%.12g,%.12g,%.12g,%.12g,%.12g\n',
    particle, time_us, pa_z, pa_x, pa_y, math.sqrt(pa_x^2 + pa_y^2)))
end

function segment.initialize_run()
  birth_time = {}
  max_rod_radius = {}
  max_radius = {}
  hits = 0
  crossings = 0
  previous_state = {}
  next_axial_plane = {}
  local path = assert(run_config.particle_csv, 'run config particle_csv is missing')
  particle_file = assert(io.open(path, 'w'))
  particle_file:write('particle_id,crossed_detector_plane,hit,arrival_time_us,detector_plane_radius_mm,max_rod_radius_mm,max_radius_mm,terminate_x_mm,terminate_y_mm,terminate_z_mm\n')
  local trajectory_path = run_config.trajectory_csv
  if trajectory_path and trajectory_path ~= '' then
    trajectory_file = assert(io.open(trajectory_path, 'w'))
    trajectory_file:write('particle_id,time_us,axial_z_mm,transverse_x_mm,transverse_y_mm,r_mm\n')
  else
    trajectory_file = nil
  end
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
  -- SIMION calls this once for a Fly'm, not once per ion.  Per-ion state
  -- is therefore initialized on that ion's first other_actions callback.
end

function segment.other_actions()
  local previous = previous_state[ion_number]
  local current_t, current_x, current_y, current_z = ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm
  if not previous then
    local radius = radial_mm()
    birth_time[ion_number] = current_t
    max_rod_radius[ion_number] = radius
    max_radius[ion_number] = radius
    write_trajectory(ion_number, current_t, current_x, current_y, current_z)
    previous_state[ion_number] = {t=current_t, x=current_x, y=current_y, z=current_z}
    next_axial_plane[ion_number] = math.floor(current_x / trajectory_plane_step_mm + 1) * trajectory_plane_step_mm
    return
  end
  local plane = next_axial_plane[ion_number]
  if previous and current_x > previous.x and plane then
    while plane <= current_x do
      local fraction = (plane - previous.x) / (current_x - previous.x)
      write_trajectory(ion_number,
        previous.t + fraction * (current_t - previous.t),
        plane,
        previous.y + fraction * (current_y - previous.y),
        previous.z + fraction * (current_z - previous.z))
      plane = plane + trajectory_plane_step_mm
    end
    next_axial_plane[ion_number] = plane
  end
  previous_state[ion_number] = {t=current_t, x=current_x, y=current_y, z=current_z}
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
  write_trajectory(ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm)
end

function segment.terminate_run()
  if particle_file then particle_file:close() end
  if trajectory_file then trajectory_file:close() end
  local summary_path = assert(run_config.summary_json, 'run config summary_json is missing')
  local summary = assert(io.open(summary_path, 'w'))
  summary:write(string.format(
    '{\n  "solver": "SIMION",\n  "mode": "transport_no_collision",\n  "collision_model": "none",\n  "particles": %d,\n  "detector_plane_crossings": %d,\n  "hits": %d,\n  "transmission": %.12g,\n  "rf_peak_V": %.12g,\n  "frequency_Hz": %.12g,\n  "rf_steps_per_period": %.12g\n}\n',
    sim_ions_count, crossings, hits, hits/sim_ions_count,
    transport_rf_peak_v, transport_frequency_hz, transport_rf_steps_per_period))
  summary:close()
  print(string.format('RFQUAD_STATUS particles=%d crossings=%d hits=%d transmission=%.12g',
    sim_ions_count, crossings, hits, hits/sim_ions_count))
end
