-- SIMION owns trajectory advancement.  This adapter composes the shared RF
-- kernel with SIMION's official collision_sds module and a frozen gas field.
simion.workbench_program()

local config_path = assert(os.getenv('DUAL_CONE_SIMION_RUN_CONFIG_LUA'),
  'DUAL_CONE_SIMION_RUN_CONFIG_LUA is not set')
local config = assert(loadfile(config_path))()
local rf = assert(loadfile(assert(config.rf_drive_kernel)))()

-- Official instance transforms own the inverse/forward orientation. A PA grid
-- already embeds the device offset; pitch converts point GU to local mm only.
local function pose_instance()
  assert(#simion.wb.instances==1,'dual-cone pose requires its one bound PA instance')
  return assert(simion.wb.instances[config.native_instance_index])
end
local function device_position(x,y,z)
  if config.device_placement then
    local gx,gy,gz=pose_instance():wb_to_pa_coords(x,y,z)
    return gx*config.pa_dx_mm-config.device_x_offset_mm,
           gy*config.pa_dy_mm-config.device_y_offset_mm,
           gz*config.pa_dz_mm-config.device_z_offset_mm
  end
  -- Explicit translation-only reader for the original configuration shape.
  return x-config.device_x_offset_mm,y-config.device_y_offset_mm,z-config.device_z_offset_mm
end

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

local selected_model
if config.model_configuration then
  selected_model=assert(loadfile(assert(config.model_consumer)))().new(
    assert(loadfile(config.model_configuration))(),rf,
    assert(loadfile(assert(config.pulse_hook)))(),assert(loadfile(assert(config.waveforms)))())
end
local stage_1 = drive(config.stage_1)
local stage_2 = drive(config.stage_2)
local trajectory_stream
local final_stream
local next_sample_us = {}
local terminal_code = {}
local gas_support_lost = {}
local final_recorded = {}

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
  if selected_model then
    for _,row in ipairs(selected_model.evaluate_at(ion_time_of_flight)) do
      for _,target in ipairs(row.native_targets) do
        assert(target.domain=='dual_cone','saved drive target domain differs')
        set_electrode_voltage(target.electrode_id,row.voltage_v)
      end
    end
    return
  end
  adj_elect[1] = config.first_cone_v
  adj_elect[2] = config.second_cone_v
  adj_elect[3] = config.downstream_aperture_plate_v
  stage_1.apply_at(ion_time_of_flight, set_electrode_voltage)
  stage_2.apply_at(ion_time_of_flight, set_electrode_voltage)
end

function segment.tstep_adjust()
  ion_time_step = math.min(ion_time_step, stage_1.timestep_cap_us, stage_2.timestep_cap_us,
    config.maximum_step_us)
end

function segment.initialize_run()
  next_sample_us = {}
  terminal_code = {}
  gas_support_lost = {}
  final_recorded = {}
  -- Official SIMION callback coverage includes particles outside PA volumes.
  -- No efield_adjust/mfield_adjust is supplied: this defines no external field.
  sim_segment_global = 1
  print('DUAL_CONE_CALLBACK_COVERAGE=GLOBAL ENABLED=' .. tostring(sim_segment_global))
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
  if gas_support_lost[ion_number] then
    terminal_code[ion_number] = 3
    ion_splat = 1
  end
  if ion_time_of_flight >= (next_sample_us[ion_number] or 0) then
    emit_sample()
    next_sample_us[ion_number] = ion_time_of_flight + config.trajectory_sample_interval_us
  end
  local axial,terminal=ion_pz_mm,config.downstream_workbench_z_mm
  if config.device_placement then
    local _,_,local_z=device_position(ion_px_mm,ion_py_mm,ion_pz_mm)
    axial,terminal=local_z,config.downstream_device_z_mm
  end
  if ion_time_of_flight >= config.maximum_time_us or axial >= terminal then
    terminal_code[ion_number] = axial >= terminal and 1 or 2
    ion_splat = 1
  end
end

local function emit_final(code)
  if final_recorded[ion_number] then return end
  terminal_code[ion_number] = code or terminal_code[ion_number] or 0
  emit_sample()
  final_stream:write(string.format('%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d\n',
    ion_number, ion_time_of_flight, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm, terminal_code[ion_number]))
  trajectory_stream:flush()
  final_stream:flush()
  final_recorded[ion_number] = true
end

function segment.terminate()
  emit_final()
end

function segment.terminate_run()
  if trajectory_stream then trajectory_stream:close() end
  if final_stream then final_stream:close() end
end

if config.mode == 'gas_assisted_transport' then
  local field = assert(loadfile(assert(config.gas_field_lua)))()
  assert(type(field.sample)=='function','gas field omits joint sample')
  local function positive_parameter(value, name)
    assert(type(value) == 'number' and value == value and value > 0 and value < math.huge,
      name .. ' must be a positive finite number')
  end
  positive_parameter(config.collision_gas_mass_amu, 'collision_gas_mass_amu')
  positive_parameter(config.collision_gas_diameter_nm, 'collision_gas_diameter_nm')
  assert(config.diffusion_enabled == 0 or config.diffusion_enabled == 1,
    'diffusion_enabled must be 0 or 1')
  local SDS = simion.import(assert(config.collision_sds_lua), 'noinstall')
  -- Official collision_sds 8.1.2.7 init runs before mass-data completion.
  function SDS.init()
    adjustable SDS_collision_gas_mass_amu = config.collision_gas_mass_amu
    adjustable SDS_collision_gas_diameter_nm = config.collision_gas_diameter_nm
    adjustable SDS_diffusion = config.diffusion_enabled
  end
  local binding=assert(loadfile(assert(config.collision_sds_binding_lua)))()
  binding.install(SDS,field,{
    frame_id=assert(config.gas_field_frame_id),
    outside_domain_policy=assert(config.gas_outside_domain_policy),
    position=device_position,
    velocity=function(vx,vy,vz)
      -- SDS receives m/s in workbench orientation, never PA-pitch scaling.
      if config.device_placement then return pose_instance():pa_to_wb_orient(vx,vy,vz) end
      return vx,vy,vz
    end,
    is_support_lost=function()return gas_support_lost[ion_number] end,
    on_coverage_lost=function()
      gas_support_lost[ion_number]=true
      terminal_code[ion_number]=3
      -- Preserve final-record publication before any safe supplier fallback.
      emit_final(3)
    end,
  })
elseif config.mode ~= 'c0_gem_smoke' then
  error('unsupported SIMION mode: ' .. tostring(config.mode))
end
