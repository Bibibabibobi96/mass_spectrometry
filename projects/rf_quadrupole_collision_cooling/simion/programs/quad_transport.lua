-- RF-only transport profile for the SIMION built-in quadrupole geometry.
-- Geometry axis is PA z and workbench x; workbench y/z are transverse.

simion.workbench_program()

local run_config_path = assert(os.getenv('RFQUAD_RUN_CONFIG_LUA'),
  'RFQUAD_RUN_CONFIG_LUA is not set')
local run_config = assert(dofile(run_config_path), 'run config did not return a table')
local source_states = assert(run_config.source_states, 'run config source_states is missing')

-- Safe placeholders only.  The required run_config below is the authority;
-- nonzero physics defaults here would mask a broken configuration load.
adjustable transport_rf_peak_v = 0
adjustable transport_dc_amplitude_v = 0
adjustable transport_frequency_hz = 0
adjustable transport_phase_deg = 0.0
adjustable transport_axis_voltage_v = 0.0
adjustable transport_entrance_voltage_v = 0.0
adjustable transport_exit_voltage_v = 0.0
adjustable transport_detector_voltage_v = 0.0
adjustable transport_rf_steps_per_period = 0
adjustable transport_max_elapsed_us = 0

local birth_time = {}
local max_rod_radius = {}
local max_radius = {}
local hits = 0
local crossings = 0
local trajectory_file
local particle_state_file
local previous_state = {}
local next_axial_plane = {}
local crossed_rod_exit = {}
local crossed_handoff = {}
local timed_out = {}
local trajectory_plane_step_mm
local rod_z_min_mm
local rod_z_max_mm
local rod_exit_plane_mm
local handoff_plane_mm
local detector_crossing_threshold_mm
local detector_radius_mm
local radial_escape_radius_mm

-- Apply the explicit run configuration while the Program is loaded.  SIMION
-- has no segment.load lifecycle callback; relying on one would leave the GUI
-- adjustable defaults active and silently ignore parameterized runs.
transport_rf_peak_v = assert(run_config.rf_peak_v)
transport_dc_amplitude_v = assert(run_config.dc_amplitude_v)
transport_frequency_hz = assert(run_config.frequency_hz)
transport_phase_deg = assert(run_config.phase_deg)
transport_axis_voltage_v = assert(run_config.axis_voltage_v)
transport_entrance_voltage_v = assert(run_config.entrance_voltage_v)
transport_exit_voltage_v = assert(run_config.exit_voltage_v)
transport_detector_voltage_v = assert(run_config.detector_voltage_v)
transport_rf_steps_per_period = assert(run_config.rf_steps_per_period)
transport_max_elapsed_us = assert(run_config.maximum_time_us)
assert(transport_rf_peak_v > 0, 'run config rf_peak_v must be positive')
assert(transport_dc_amplitude_v >= 0, 'run config dc_amplitude_v must be non-negative')
assert(transport_frequency_hz > 0, 'run config frequency_hz must be positive')
assert(transport_rf_steps_per_period > 0, 'run config rf_steps_per_period must be positive')
assert(transport_max_elapsed_us > 0, 'run config maximum_time_us must be positive')
trajectory_plane_step_mm = assert(run_config.trajectory_plane_step_mm)
rod_z_min_mm = assert(run_config.rod_z_min_mm)
rod_z_max_mm = assert(run_config.rod_z_max_mm)
rod_exit_plane_mm = assert(run_config.rod_exit_plane_mm)
handoff_plane_mm = assert(run_config.handoff_plane_mm)
detector_crossing_threshold_mm = assert(run_config.detector_crossing_threshold_mm)
detector_radius_mm = assert(run_config.detector_radius_mm)
radial_escape_radius_mm = assert(run_config.radial_escape_radius_mm)
local omega = transport_frequency_hz * 1E-6 * 2 * math.pi
local phase = transport_phase_deg * math.pi / 180

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

local function divergence_deg(v_axial, v_x, v_y)
  local radial = math.sqrt(v_x^2 + v_y^2)
  if v_axial > 0 then return math.atan(radial / v_axial) * 180 / math.pi end
  if v_axial < 0 then return (math.pi - math.atan(radial / -v_axial)) * 180 / math.pi end
  return 90
end

local function write_particle_state(particle, event, status, terminal_reason, state)
  if not particle_state_file then return end
  -- SIMION velocity components are mm/us; 1 mm/us = 1000 m/s.
  -- IOB basis: component z=wb x, component x=wb z, component y=-wb y.
  local v_axial = state.vx * 1000
  local v_x = state.vz * 1000
  local v_y = -state.vy * 1000
  local radial = math.sqrt(state.y^2 + state.z^2)
  local rf_phase = (state.t * omega + phase) % (2 * math.pi)
  particle_state_file:write(string.format(
    '%d,%s,%s,%s,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g\n',
    particle, event, status, terminal_reason, state.t,
    state.t - (birth_time[particle] or state.t), rf_phase,
    state.x, state.z, -state.y, v_axial, v_x, v_y, state.ke,
    radial, divergence_deg(v_axial, v_x, v_y), max_rod_radius[particle] or radial))
end

local function interpolate_state(previous, current, plane)
  local fraction = (plane - previous.x) / (current.x - previous.x)
  local function lerp(a, b) return a + fraction * (b - a) end
  return {t=lerp(previous.t,current.t), x=plane,
    y=lerp(previous.y,current.y), z=lerp(previous.z,current.z),
    vx=lerp(previous.vx,current.vx), vy=lerp(previous.vy,current.vy),
    vz=lerp(previous.vz,current.vz), ke=lerp(previous.ke,current.ke)}
end

function segment.initialize_run()
  birth_time = {}
  max_rod_radius = {}
  max_radius = {}
  hits = 0
  crossings = 0
  previous_state = {}
  next_axial_plane = {}
  crossed_rod_exit = {}
  crossed_handoff = {}
  timed_out = {}
  local trajectory_path = run_config.trajectory_csv
  if trajectory_path and trajectory_path ~= '' then
    trajectory_file = assert(io.open(trajectory_path, 'w'))
    trajectory_file:write('particle_id,time_us,axial_z_mm,transverse_x_mm,transverse_y_mm,r_mm\n')
  else
    trajectory_file = nil
  end
  local particle_state_path = run_config.particle_state_csv
  if particle_state_path and particle_state_path ~= '' then
    particle_state_file = assert(io.open(particle_state_path, 'w'))
    particle_state_file:write('particle_id,event,status,terminal_reason,time_us,elapsed_time_us,rf_phase_rad,axial_z_mm,transverse_x_mm,transverse_y_mm,velocity_axial_m_s,velocity_x_m_s,velocity_y_m_s,kinetic_energy_eV,radial_position_mm,divergence_angle_deg,max_rod_radius_mm\n')
  else
    particle_state_file = nil
  end
end

function segment.init_p_values()
  adj_elect03 = transport_entrance_voltage_v
  adj_elect04 = transport_exit_voltage_v
  adj_elect05 = transport_detector_voltage_v
end

function segment.fast_adjust()
  local rf = transport_rf_peak_v * math.sin(ion_time_of_flight * omega + phase)
  local differential = transport_dc_amplitude_v + rf
  adj_elect01 = transport_axis_voltage_v + differential
  adj_elect02 = transport_axis_voltage_v - differential
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
  local current = {t=current_t, x=current_x, y=current_y, z=current_z,
    vx=ion_vx_mm, vy=ion_vy_mm, vz=ion_vz_mm, ke=ion_ke}
  if not previous then
    local source = assert(source_states[ion_number], 'authoritative source state is missing')
    local radius = math.sqrt(source.y^2 + source.z^2)
    birth_time[ion_number] = source.t
    max_rod_radius[ion_number] = radius
    max_radius[ion_number] = radius
    write_trajectory(ion_number, current_t, current_x, current_y, current_z)
    previous_state[ion_number] = current
    next_axial_plane[ion_number] = math.floor(current_x / trajectory_plane_step_mm + 1) * trajectory_plane_step_mm
    write_particle_state(ion_number, 'source', 'alive', 'none', source)
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
  local radius = radial_mm()
  max_radius[ion_number] = math.max(max_radius[ion_number] or radius, radius)
  if ion_px_mm >= rod_z_min_mm and ion_px_mm <= rod_z_max_mm then
    max_rod_radius[ion_number] = math.max(max_rod_radius[ion_number] or radius, radius)
  end
  if current_x > previous.x then
    if not crossed_rod_exit[ion_number] and previous.x < rod_exit_plane_mm and current_x >= rod_exit_plane_mm then
      write_particle_state(ion_number, 'rod_exit', 'alive', 'none',
        interpolate_state(previous, current, rod_exit_plane_mm))
      crossed_rod_exit[ion_number] = true
    end
    if not crossed_handoff[ion_number] and previous.x < handoff_plane_mm and current_x >= handoff_plane_mm then
      write_particle_state(ion_number, 'handoff', 'transmitted', 'none',
        interpolate_state(previous, current, handoff_plane_mm))
      crossed_handoff[ion_number] = true
    end
  end
  previous_state[ion_number] = current
  if ion_time_of_flight - (birth_time[ion_number] or 0) >= transport_max_elapsed_us then
    timed_out[ion_number] = true
    ion_splat = -4
  end
end

function segment.terminate()
  local radius = radial_mm()
  -- The run config derives a safe terminal threshold from the detector plane
  -- and PA cell size so SIMION's fractional-surface back-off is not mistaken
  -- for an upstream loss.
  local crossed = ion_px_mm >= detector_crossing_threshold_mm
  local hit = crossed and radius <= detector_radius_mm
  if crossed then crossings = crossings + 1 end
  if hit then hits = hits + 1 end
  local status, reason = 'lost', 'electrode'
  if timed_out[ion_number] then status, reason = 'timeout', 'timeout'
  elseif hit then status, reason = 'transmitted', 'acceptance_detector'
  elseif ion_px_mm < 0 then reason = 'backward_escape'
  elseif radius > radial_escape_radius_mm then reason = 'radial_escape'
  end
  write_particle_state(ion_number, 'terminal', status, reason,
    {t=ion_time_of_flight, x=ion_px_mm, y=ion_py_mm, z=ion_pz_mm,
     vx=ion_vx_mm, vy=ion_vy_mm, vz=ion_vz_mm, ke=ion_ke})
  write_trajectory(ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm)
end

function segment.terminate_run()
  if trajectory_file then trajectory_file:close() end
  if particle_state_file then particle_state_file:close() end
  local summary_path = assert(run_config.summary_json, 'run config summary_json is missing')
  local summary = assert(io.open(summary_path, 'w'))
  summary:write(string.format(
    '{\n  "solver": "SIMION",\n  "mode": "%s",\n  "operating_point": "%s",\n  "collision_model": "none",\n  "particles": %d,\n  "detector_plane_crossings": %d,\n  "hits": %d,\n  "transmission": %.12g,\n  "rf_peak_V": %.12g,\n  "dc_amplitude_V_per_group": %.12g,\n  "frequency_Hz": %.12g,\n  "rf_steps_per_period": %.12g\n}\n',
    run_config.mode, run_config.operating_point, sim_ions_count, crossings, hits, hits/sim_ions_count,
    transport_rf_peak_v, transport_dc_amplitude_v, transport_frequency_hz, transport_rf_steps_per_period))
  summary:close()
  print(string.format('RFQUAD_STATUS particles=%d crossings=%d hits=%d transmission=%.12g',
    sim_ions_count, crossings, hits, hits/sim_ions_count))
end
