-- Shared collision-free SIMION transport program for circular-rod multipoles.
-- The frozen project adapter supplies voltages, coordinates and interface planes.

simion.workbench_program()

local run_config_path = assert(os.getenv('MULTIPOLE_SIMION_RUN_CONFIG_LUA'),
  'MULTIPOLE_SIMION_RUN_CONFIG_LUA is not set')
local run_config = assert(dofile(run_config_path), 'run config did not return a table')
local rf_drive_kernel_path = assert(os.getenv('MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA'),
  'MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA is not set')
local rf_drive_kernel = assert(dofile(rf_drive_kernel_path),
  'RF drive kernel did not return a table')
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
adjustable transport_phase_rad = 0.0
adjustable transport_axis_voltage_v = 0.0
adjustable transport_entrance_voltage_v = 0.0
adjustable transport_exit_voltage_v = 0.0
adjustable transport_physical_detector_voltage_v = 0.0
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
local handoff_state = {}
local timed_out = {}
local census_counted = {}
local census_hit = {}
local terminal_written = {}
local trajectory_plane_step_mm
local rod_z_min_mm
local rod_z_max_mm
local rod_exit_plane_mm
local handoff_plane_mm
local census_plane_mm
local numerical_census_marker_threshold_mm
local census_radius_mm
local handoff_aperture
local radial_escape_radius_mm
local axial_axis
local origin_x_mm
local origin_y_mm
local origin_z_mm
local backward_escape_plane_mm
local rf_scale
local axial_scale
local segmented_rod_electrodes
local rf_drive

local function set_electrode_voltage(electrode_id, voltage)
  assert(type(electrode_id) == 'number' and electrode_id == math.floor(electrode_id)
    and electrode_id >= 1 and electrode_id <= 1000,
    'SIMION electrode id must be an integer from 1 through 1000')
  adj_elect[electrode_id] = voltage
end

-- Apply the explicit run configuration while the Program is loaded.  SIMION
-- has no segment.load lifecycle callback; relying on one would leave the GUI
-- adjustable defaults active and silently ignore parameterized runs.
transport_rf_peak_v = assert(run_config.rf_peak_v)
transport_dc_amplitude_v = assert(run_config.dc_amplitude_v)
transport_frequency_hz = assert(run_config.frequency_hz)
transport_phase_rad = assert(run_config.phase_rad)
transport_waveform = assert(run_config.waveform)
transport_axis_voltage_v = assert(run_config.axis_voltage_v)
transport_entrance_voltage_v = assert(run_config.entrance_voltage_v)
transport_exit_voltage_v = assert(run_config.exit_voltage_v)
transport_physical_detector_voltage_v = assert(run_config.physical_detector_voltage_v)
transport_rf_steps_per_period = assert(run_config.rf_steps_per_period)
transport_max_elapsed_us = assert(run_config.maximum_time_us)
assert(transport_rf_peak_v > 0, 'run config rf_peak_v must be positive')
assert(transport_dc_amplitude_v >= 0, 'run config dc_amplitude_v must be non-negative')
assert(transport_frequency_hz > 0, 'run config frequency_hz must be positive')
assert(transport_rf_steps_per_period > 0, 'run config rf_steps_per_period must be positive')
assert(transport_max_elapsed_us > 0, 'run config maximum_time_us must be positive')
assert(transport_waveform == 'sine' or transport_waveform == 'cosine',
  'run config waveform must be sine or cosine')
trajectory_plane_step_mm = assert(run_config.trajectory_plane_step_mm)
rod_z_min_mm = assert(run_config.rod_z_min_mm)
rod_z_max_mm = assert(run_config.rod_z_max_mm)
rod_exit_plane_mm = assert(run_config.rod_exit_plane_mm)
handoff_plane_mm = assert(run_config.handoff_plane_mm)
census_plane_mm = assert(run_config.census_plane_mm)
numerical_census_marker_threshold_mm = assert(run_config.numerical_census_marker_threshold_mm)
census_radius_mm = assert(run_config.census_radius_mm)
handoff_aperture = run_config.handoff_aperture
if handoff_aperture then
  assert(handoff_aperture.shape == 'rectangular' or handoff_aperture.shape == 'circular',
    'handoff aperture shape must be rectangular or circular')
  assert(handoff_aperture.width_mm and handoff_aperture.width_mm > 0,
    'handoff aperture width must be positive')
  assert(handoff_aperture.height_mm and handoff_aperture.height_mm > 0,
    'handoff aperture height must be positive')
end
radial_escape_radius_mm = assert(run_config.radial_escape_radius_mm)
axial_axis = run_config.axial_axis or 'x'
assert(axial_axis == 'x' or axial_axis == 'z', 'axial_axis must be x or z')
origin_x_mm = run_config.origin_x_mm or 0
origin_y_mm = run_config.origin_y_mm or 0
origin_z_mm = run_config.origin_z_mm or 0
backward_escape_plane_mm = run_config.backward_escape_plane_mm or 0
rf_scale = run_config.rf_scale or 1
assert(rf_scale == 0 or rf_scale == 1, 'rf_scale must be zero or one')
axial_scale = run_config.axial_scale or 0
assert(axial_scale == 0 or axial_scale == 1, 'axial_scale must be zero or one')
segmented_rod_electrodes = run_config.segmented_rod_electrodes
if segmented_rod_electrodes then
  assert(#segmented_rod_electrodes >= 2, 'rod electrode table is incomplete')
  assert(run_config.ground_electrode_id, 'ground electrode id is missing')
  assert(run_config.output_electrode_id, 'output electrode id is missing')
  assert(run_config.ground_reference_v, 'ground reference voltage is missing')
  assert(run_config.output_reference_v, 'output reference voltage is missing')
end

local function compile_rf_drive()
  local electrodes = {}
  if segmented_rod_electrodes then
    for index, electrode in ipairs(segmented_rod_electrodes) do
      local group = electrode.electrode_group
      electrodes[index] = {
        electrode_id=electrode.electrode_id,
        electrode_group=group,
        polarity=group == 1 and 1 or -1,
        common_mode_v=electrode.common_mode_v,
      }
    end
  else
    electrodes = {
      {electrode_id=1, electrode_group=1, polarity=1,
        common_mode_v=transport_axis_voltage_v},
      {electrode_id=2, electrode_group=2, polarity=-1,
        common_mode_v=transport_axis_voltage_v},
    }
  end
  return rf_drive_kernel.new {
    waveform=transport_waveform,
    frequency_hz=transport_frequency_hz,
    phase_rad=transport_phase_rad,
    rf_amplitude_v=transport_rf_peak_v,
    rf_scale=rf_scale,
    common_mode_scale=segmented_rod_electrodes and axial_scale or 1,
    group_dc_v={[1]=transport_dc_amplitude_v, [2]=-transport_dc_amplitude_v},
    rf_steps_per_period=transport_rf_steps_per_period,
    electrodes=electrodes,
  }
end

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

local function inside_handoff_aperture(state)
  if not handoff_aperture then
    return radial_mm(state) <= census_radius_mm
  end
  if handoff_aperture.shape == 'rectangular' then
    return math.abs(state.y) <= handoff_aperture.width_mm / 2 and
      math.abs(state.z) <= handoff_aperture.height_mm / 2
  end
  return radial_mm(state) <= handoff_aperture.width_mm / 2
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
  local rf_phase = rf_drive.phase_at(state.t) % (2 * math.pi)
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

local function project_state_to_plane(state, plane)
  assert(state.vx > 0, 'census projection requires positive axial velocity')
  local dt = (plane - state.x) / state.vx
  return {t=state.t + dt, x=plane, y=state.y + dt * state.vy,
    z=state.z + dt * state.vz, vx=state.vx, vy=state.vy,
    vz=state.vz, ke=state.ke}
end

function segment.initialize_run()
  rf_drive = compile_rf_drive()
  birth_time = {}
  max_rod_radius = {}
  max_radius = {}
  hits = 0
  crossings = 0
  previous_state = {}
  next_axial_plane = {}
  crossed_rod_exit = {}
  crossed_handoff = {}
  handoff_state = {}
  timed_out = {}
  census_counted = {}
  census_hit = {}
  terminal_written = {}
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
  if segmented_rod_electrodes then
    set_electrode_voltage(run_config.ground_electrode_id,
      axial_scale * run_config.ground_reference_v)
    set_electrode_voltage(run_config.output_electrode_id,
      axial_scale * run_config.output_reference_v)
    if run_config.physical_detector_electrode_id and run_config.physical_detector_electrode_id > 0 then
      set_electrode_voltage(run_config.physical_detector_electrode_id,
        axial_scale * transport_physical_detector_voltage_v)
    end
    if run_config.entrance_reference_electrode_id and run_config.entrance_reference_electrode_id > 0 then
      set_electrode_voltage(run_config.entrance_reference_electrode_id,
        axial_scale * run_config.entrance_reference_v)
    end
    if run_config.entrance_plate_electrode_id and run_config.entrance_plate_electrode_id > 0 then
      set_electrode_voltage(run_config.entrance_plate_electrode_id,
        axial_scale * run_config.entrance_plate_v)
    end
    return
  end
  local static_scale = run_config.scale_static_boundaries and axial_scale or 1
  adj_elect03 = static_scale * transport_entrance_voltage_v
  if run_config.has_electrode_4 ~= false then
    adj_elect04 = static_scale * transport_exit_voltage_v
  end
  if run_config.has_electrode_5 ~= false then
    adj_elect05 = static_scale * transport_physical_detector_voltage_v
  end
end

function segment.fast_adjust()
  rf_drive.apply_at(ion_time_of_flight, set_electrode_voltage)
  if segmented_rod_electrodes then
    set_electrode_voltage(run_config.ground_electrode_id,
      axial_scale * run_config.ground_reference_v)
    set_electrode_voltage(run_config.output_electrode_id,
      axial_scale * run_config.output_reference_v)
    if run_config.physical_detector_electrode_id and run_config.physical_detector_electrode_id > 0 then
      set_electrode_voltage(run_config.physical_detector_electrode_id,
        axial_scale * transport_physical_detector_voltage_v)
    end
    if run_config.entrance_reference_electrode_id and run_config.entrance_reference_electrode_id > 0 then
      set_electrode_voltage(run_config.entrance_reference_electrode_id,
        axial_scale * run_config.entrance_reference_v)
    end
    if run_config.entrance_plate_electrode_id and run_config.entrance_plate_electrode_id > 0 then
      set_electrode_voltage(run_config.entrance_plate_electrode_id,
        axial_scale * run_config.entrance_plate_v)
    end
    return
  end
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, rf_drive.timestep_cap_us)
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
      local accepted = inside_handoff_aperture(handoff)
      write_particle_state(ion_number, 'handoff', accepted and 'transmitted' or 'lost',
        accepted and 'none' or 'acceptance_aperture', handoff)
      crossed_handoff[ion_number] = true
      handoff_state[ion_number] = handoff
      if not accepted then
        write_particle_state(ion_number, 'terminal', 'lost', 'acceptance_aperture', handoff)
        write_trajectory(ion_number, handoff)
        terminal_written[ion_number] = true
        ion_splat = -6
      end
      if run_config.numerical_census_marker_is_handoff then
        census_counted[ion_number] = true
        census_hit[ion_number] = accepted
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

local function finalize_particle(particle, current)
  if terminal_written[particle] then return end
  -- The run config derives a safe terminal threshold from the census plane
  -- and PA cell size so SIMION's fractional-surface back-off is not mistaken
  -- for an upstream loss.
  local crossed = census_counted[particle] or current.x >= numerical_census_marker_threshold_mm
  local terminal_state = current
  if crossed and handoff_state[particle] and handoff_state[particle].vx > 0 then
    terminal_state = project_state_to_plane(handoff_state[particle], census_plane_mm)
  end
  local radius = radial_mm(terminal_state)
  local hit = census_counted[particle] and census_hit[particle] or
    (crossed and inside_handoff_aperture(terminal_state))
  if not census_counted[particle] then
    if crossed then crossings = crossings + 1 end
    if hit then hits = hits + 1 end
  end
  local status, reason = 'lost', 'electrode'
  if timed_out[particle] then status, reason = 'timeout', 'timeout'
  elseif hit then status, reason = 'transmitted', 'acceptance_surface'
  elseif terminal_state.x < backward_escape_plane_mm then reason = 'backward_escape'
  elseif radius > radial_escape_radius_mm then reason = 'radial_escape'
  end
  write_particle_state(particle, 'terminal', status, reason, terminal_state)
  write_trajectory(particle, terminal_state)
  terminal_written[particle] = true
end

function segment.terminate()
  local current = canonical_state(ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_ke)
  finalize_particle(ion_number, current)
end

function segment.terminate_run()
  -- SIMION does not call segment.terminate for every electrode splat. Close
  -- those paths deterministically from the last state seen by other_actions.
  for particle = 1, sim_ions_count do
    if previous_state[particle] then finalize_particle(particle, previous_state[particle]) end
  end
  if trajectory_file then trajectory_file:close() end
  if particle_state_file then particle_state_file:close() end
  local summary_path = assert(run_config.summary_json, 'run config summary_json is missing')
  local summary = assert(io.open(summary_path, 'w'))
  summary:write(string.format(
    '{\n  "solver": "SIMION",\n  "mode": "%s",\n  "operating_point": "%s",\n  "parent_resolved_design_sha256": "%s",\n  "collision_model": "none",\n  "particles": %d,\n  "census_plane_crossings": %d,\n  "hits": %d,\n  "transmission": %.12g,\n  "rf_scale": %.12g,\n  "rf_peak_V": %.12g,\n  "dc_amplitude_V_per_group": %.12g,\n  "frequency_Hz": %.12g,\n  "rf_steps_per_period": %.12g\n}\n',
    run_config.mode, run_config.operating_point,
    assert(run_config.parent_resolved_design_sha256, 'parent resolved-design hash is missing'),
    sim_ions_count, crossings, hits, hits/sim_ions_count,
    rf_scale, transport_rf_peak_v, transport_dc_amplitude_v, transport_frequency_hz, transport_rf_steps_per_period))
  summary:close()
  print(string.format('MULTIPOLE_STATUS particles=%d crossings=%d hits=%d transmission=%.12g',
    sim_ions_count, crossings, hits, hits/sim_ions_count))
end
