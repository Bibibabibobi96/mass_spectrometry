-- SIMION owns trajectory advancement.  This adapter composes the shared RF
-- kernel with SIMION's official collision_sds module and a frozen gas field.
simion.workbench_program()

local config_path = assert(os.getenv('DUAL_CONE_SIMION_RUN_CONFIG_LUA'),
  'DUAL_CONE_SIMION_RUN_CONFIG_LUA is not set')
local config = assert(loadfile(config_path))()
local rf = assert(loadfile(assert(config.rf_drive_kernel)))()

local function drive(stage)
  return rf.new{
    waveform=stage.waveform,
    frequency_hz=stage.frequency_hz,
    phase_rad=stage.phase_rad,
    rf_amplitude_v=stage.rf_amplitude_v,
    rf_scale=1,
    common_mode_scale=1,
    group_dc_v={[1]=stage.dc_amplitude_v,[2]=-stage.dc_amplitude_v},
    rf_steps_per_period=config.rf_steps_per_period,
    electrodes={
      {electrode_id=stage.electrode_1,electrode_group=1,polarity=1,
       common_mode_v=stage.common_mode_v},
      {electrode_id=stage.electrode_2,electrode_group=2,polarity=-1,
       common_mode_v=stage.common_mode_v},
    },
  }
end

local stage_1 = drive(config.stage_1)
local stage_2 = drive(config.stage_2)
local trajectory_stream
local final_stream
local next_sample_us = {}
local terminal_code = {}

local function set_electrode_voltage(id, voltage)
  assert(id == 1 or id == 2 or id == 3 or id == 11 or id == 12 or id == 21 or id == 22,
    'unsupported electrode id: ' .. tostring(id))
  adj_elect[id] = voltage
end

local function emit_sample()
  trajectory_stream:write(string.format('%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n',
    ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm))
end

function segment.fast_adjust()
  adj_elect[1] = config.first_cone_v
  adj_elect[2] = config.second_cone_v
  adj_elect[3] = config.downstream_aperture_plate_v
  stage_1.apply_at(ion_time_of_flight, set_electrode_voltage)
  stage_2.apply_at(ion_time_of_flight, set_electrode_voltage)
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, stage_1.timestep_cap_us, stage_2.timestep_cap_us)
end

function segment.initialize_run()
  seed(config.random_seed)
  trajectory_stream = assert(io.open(config.trajectory_csv, 'w'))
  final_stream = assert(io.open(config.final_state_csv, 'w'))
  trajectory_stream:write('ion_number,time_us,x_mm,y_mm,z_mm,vx_mm_per_us,vy_mm_per_us,vz_mm_per_us\n')
  final_stream:write('ion_number,time_us,x_mm,y_mm,z_mm,vx_mm_per_us,vy_mm_per_us,vz_mm_per_us,splat\n')
end

function segment.initialize()
  next_sample_us[ion_number] = 0
  emit_sample()
end

function segment.other_actions()
  if ion_time_of_flight >= (next_sample_us[ion_number] or 0) then
    emit_sample()
    next_sample_us[ion_number] = ion_time_of_flight + config.trajectory_sample_interval_us
  end
  if ion_time_of_flight >= config.maximum_time_us or
     ion_pz_mm >= config.downstream_workbench_z_mm then
    terminal_code[ion_number] = ion_pz_mm >= config.downstream_workbench_z_mm and 1 or 2
    ion_splat = 1
  end
end

function segment.terminate()
  emit_sample()
  final_stream:write(string.format('%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d\n',
    ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm, terminal_code[ion_number] or 0))
  trajectory_stream:flush()
  final_stream:flush()
end

function segment.terminate_run()
  if trajectory_stream then trajectory_stream:close() end
  if final_stream then final_stream:close() end
end

if config.mode == 'gas_assisted_transport' then
  local field = assert(loadfile(assert(config.gas_field_lua)))()
  for _,name in ipairs{'pressure_pa','temperature_k','velocity_m_s'} do
    assert(type(field[name]) == 'function', 'gas field omits ' .. name)
  end
  local SDS = simion.import(assert(config.collision_sds_lua), 'noinstall')
  SDS.pressure = function(x,y,z)
    return field.pressure_pa(x-config.device_x_offset_mm,
      y-config.device_y_offset_mm,z-config.device_z_offset_mm) * (760/101325)
  end
  SDS.temperature = function(x,y,z)
    return field.temperature_k(x-config.device_x_offset_mm,
      y-config.device_y_offset_mm,z-config.device_z_offset_mm)
  end
  SDS.velocity = function(x,y,z)
    return field.velocity_m_s(x-config.device_x_offset_mm,
      y-config.device_y_offset_mm,z-config.device_z_offset_mm)
  end
  SDS.install()
elseif config.mode ~= 'c0_gem_smoke' then
  error('unsupported SIMION mode: ' .. tostring(config.mode))
end
