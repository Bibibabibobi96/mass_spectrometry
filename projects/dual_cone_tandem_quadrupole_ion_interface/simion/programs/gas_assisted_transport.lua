-- SIMION owns trajectory advancement.  This adapter composes the shared RF
-- kernel with SIMION's official collision_sds module and a frozen COMSOL field.
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

function segment.fast_adjust()
  adj_electrode[1] = config.first_cone_v
  adj_electrode[2] = config.second_cone_v
  stage_1.apply_at(ion_time_of_flight)
  stage_2.apply_at(ion_time_of_flight)
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, stage_1.timestep_cap_us(), stage_2.timestep_cap_us())
end

function segment.initialize_run()
  seed(config.random_seed)
end

function segment.other_actions()
  if ion_time_of_flight >= config.maximum_time_us or
     ion_pz_mm >= config.downstream_workbench_z_mm then
    ion_splat = 1
  end
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
  SDS_collision_gas_mass_amu = config.collision_gas_mass_amu
  SDS_collision_gas_diameter_nm = config.collision_gas_diameter_nm
  SDS_diffusion = config.diffusion_enabled
  SDS_min_time_step_usec = 0
  SDS.install()
elseif config.mode ~= 'c0_gem_smoke' then
  error('unsupported SIMION mode: ' .. tostring(config.mode))
end
