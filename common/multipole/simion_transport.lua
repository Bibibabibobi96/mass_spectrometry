-- Shared collision-free SIMION transport program for circular-rod multipoles.
-- The frozen project adapter supplies voltages, coordinates and interface planes.

simion.workbench_program()

local run_config_path = assert(os.getenv('MULTIPOLE_SIMION_RUN_CONFIG_LUA'),
  'MULTIPOLE_SIMION_RUN_CONFIG_LUA is not set')
local run_config = assert(dofile(run_config_path), 'run config did not return a table')
local source_states = assert(run_config.source_states, 'run config source_states is missing')
if run_config.instance_scale then
  assert(simion.wb and #simion.wb.instances == 1,
    'instance_scale requires one loaded PA instance')
  simion.wb.instances[1].scale = run_config.instance_scale
  if simion.wb.instances[1]._debug_update_size then
    simion.wb.instances[1]:_debug_update_size()
  end
end

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
local detector_counted = {}
local detector_hit = {}
local trajectory_plane_step_mm
local rod_z_min_mm
local rod_z_max_mm
local rod_exit_plane_mm
local handoff_plane_mm
local detector_crossing_threshold_mm
local detector_radius_mm
local radial_escape_radius_mm
local axial_axis
local origin_x_mm
local origin_y_mm
local origin_z_mm
local backward_escape_plane_mm
local rf_scale

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
axial_axis = run_config.axial_axis or 'x'
assert(axial_axis == 'x' or axial_axis == 'z', 'axial_axis must be x or z')
origin_x_mm = run_config.origin_x_mm or 0
origin_y_mm = run_config.origin_y_mm or 0
origin_z_mm = run_config.origin_z_mm or 0
backward_escape_plane_mm = run_config.backward_escape_plane_mm or 0
rf_scale = run_config.rf_scale or 1
assert(rf_scale == 0 or rf_scale == 1, 'rf_scale must be zero or one')
local omega = transport_frequency_hz * 1E-6 * 2 * math.pi
local phase = transport_phase_deg * math.pi / 180

local function canonical_state(t, x, y, z, vx, vy, vz, ke)
  if axial_axis == 'x' then
    return {t=t, x=x-origin_x_mm, y=z-origin_z_mm, z=-(y-origin_y_mm),
      vx=vx, vy=vz, vz=-vy, ke=ke}
  end
  return {t=t, x=z-origin_z_mm, y=x-origin_x_mm, z=y-origin_y_mm,
    vx=vz, vy=vx, vz=vy, ke=ke}
end

local function radial_mm(state)
  return math.sqrt(state.y^2 + state.z^2)
end

local function write_trajectory(particle, state)
  if not trajectory_file then return end
  trajectory_file:write(string.format('%d,%.12g,%.12g,%.12g,%.12g,%.12g\n',
    particle, state.t, state.x, state.y, state.z, radial_mm(state)))
end

local function divergence_deg(v_axial, v_x, v_y)
  local radial = math.sqrt(v_x^2 + v_y^2)
  if v_axial > 0 then return math.atan(radial / v_axial) * 180 / math.pi end
  if v_axial < 0 then return (math.pi - math.atan(radial / -v_axial)) * 180 / math.pi end
  return 90
end

local function write_particle_state(particle, event, status, terminal_reason, state)
  if not particle_state_file then return end
  -- Canonical velocity components remain in mm/us here; 1 mm/us = 1000 m/s.
  local v_axial = state.vx * 1000
  local v_x = state.vy * 1000
  local v_y = state.vz * 1000
  local radial = math.sqrt(state.y^2 + state.z^2)
  local rf_phase = (state.t * omega + phase) % (2 * math.pi)
  particle_state_file:write(string.format(
    '%d,%s,%s,%s,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g\n',
    particle, event, status, terminal_reason, state.t,
    state.t - (birth_time[particle] or state.t), rf_phase,
    state.x, state.y, state.z, v_axial, v_x, v_y, state.ke,
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
  detector_counted = {}
  detector_hit = {}
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
  if run_config.has_electrode_4 ~= false then adj_elect04 = transport_exit_voltage_v end
  if run_config.has_electrode_5 ~= false then adj_elect05 = transport_detector_voltage_v end
end

function segment.fast_adjust()
  local rf = rf_scale * transport_rf_peak_v * math.sin(ion_time_of_flight * omega + phase)
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
  local current = canonical_state(ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_ke)
  local current_t, current_x = current.t, current.x
  if not previous then
    local raw_source = assert(source_states[ion_number], 'authoritative source state is missing')
    local source = canonical_state(raw_source.t, raw_source.x, raw_source.y, raw_source.z,
      raw_source.vx, raw_source.vy, raw_source.vz, raw_source.ke)
    local radius = math.sqrt(source.y^2 + source.z^2)
    birth_time[ion_number] = source.t
    max_rod_radius[ion_number] = radius
    max_radius[ion_number] = radius
    write_trajectory(ion_number, current)
    previous_state[ion_number] = current
    next_axial_plane[ion_number] = math.floor(current_x / trajectory_plane_step_mm + 1) * trajectory_plane_step_mm
    write_particle_state(ion_number, 'source', 'alive', 'none', source)
    return
  end
  local plane = next_axial_plane[ion_number]
  if previous and current_x > previous.x and plane then
    while plane <= current_x do
      local fraction = (plane - previous.x) / (current_x - previous.x)
      write_trajectory(ion_number, {t=previous.t + fraction * (current_t - previous.t), x=plane,
        y=previous.y + fraction * (current.y - previous.y),
        z=previous.z + fraction * (current.z - previous.z)})
      plane = plane + trajectory_plane_step_mm
    end
    next_axial_plane[ion_number] = plane
  end
  local radius = radial_mm(current)
  max_radius[ion_number] = math.max(max_radius[ion_number] or radius, radius)
  if current.x >= rod_z_min_mm and current.x <= rod_z_max_mm then
    max_rod_radius[ion_number] = math.max(max_rod_radius[ion_number] or radius, radius)
  end
  if current_x > previous.x then
    if not crossed_rod_exit[ion_number] and previous.x < rod_exit_plane_mm and current_x >= rod_exit_plane_mm then
      write_particle_state(ion_number, 'rod_exit', 'alive', 'none',
        interpolate_state(previous, current, rod_exit_plane_mm))
      crossed_rod_exit[ion_number] = true
    end
    if not crossed_handoff[ion_number] and previous.x < handoff_plane_mm and current_x >= handoff_plane_mm then
      local handoff = interpolate_state(previous, current, handoff_plane_mm)
      local accepted = radial_mm(handoff) <= detector_radius_mm
      write_particle_state(ion_number, 'handoff', accepted and 'transmitted' or 'lost',
        accepted and 'none' or 'acceptance_radius', handoff)
      crossed_handoff[ion_number] = true
      if run_config.detector_is_handoff then
        detector_counted[ion_number] = true
        detector_hit[ion_number] = accepted
        crossings = crossings + 1
        if accepted then hits = hits + 1 end
        ion_splat = -5
      end
    end
  end
  previous_state[ion_number] = current
  if ion_time_of_flight - (birth_time[ion_number] or 0) >= transport_max_elapsed_us then
    timed_out[ion_number] = true
    ion_splat = -4
  end
end

function segment.terminate()
  local current = canonical_state(ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_ke)
  local radius = radial_mm(current)
  -- The run config derives a safe terminal threshold from the detector plane
  -- and PA cell size so SIMION's fractional-surface back-off is not mistaken
  -- for an upstream loss.
  local crossed = detector_counted[ion_number] or current.x >= detector_crossing_threshold_mm
  local hit = detector_counted[ion_number] and detector_hit[ion_number] or
    (crossed and radius <= detector_radius_mm)
  if not detector_counted[ion_number] then
    if crossed then crossings = crossings + 1 end
    if hit then hits = hits + 1 end
  end
  local status, reason = 'lost', 'electrode'
  if timed_out[ion_number] then status, reason = 'timeout', 'timeout'
  elseif hit then status, reason = 'transmitted', 'acceptance_detector'
  elseif current.x < backward_escape_plane_mm then reason = 'backward_escape'
  elseif radius > radial_escape_radius_mm then reason = 'radial_escape'
  end
  write_particle_state(ion_number, 'terminal', status, reason, current)
  write_trajectory(ion_number, current)
end

function segment.terminate_run()
  if trajectory_file then trajectory_file:close() end
  if particle_state_file then particle_state_file:close() end
  local summary_path = assert(run_config.summary_json, 'run config summary_json is missing')
  local summary = assert(io.open(summary_path, 'w'))
  summary:write(string.format(
    '{\n  "solver": "SIMION",\n  "mode": "%s",\n  "operating_point": "%s",\n  "collision_model": "none",\n  "particles": %d,\n  "detector_plane_crossings": %d,\n  "hits": %d,\n  "transmission": %.12g,\n  "rf_scale": %.12g,\n  "rf_peak_V": %.12g,\n  "dc_amplitude_V_per_group": %.12g,\n  "frequency_Hz": %.12g,\n  "rf_steps_per_period": %.12g\n}\n',
    run_config.mode, run_config.operating_point, sim_ions_count, crossings, hits, hits/sim_ions_count,
    rf_scale, transport_rf_peak_v, transport_dc_amplitude_v, transport_frequency_hz, transport_rf_steps_per_period))
  summary:close()
  print(string.format('MULTIPOLE_STATUS particles=%d crossings=%d hits=%d transmission=%.12g',
    sim_ions_count, crossings, hits, hits/sim_ions_count))
end
