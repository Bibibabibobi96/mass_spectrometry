-- Callback composition only: all electric fields come from the assembled GEM.
local M={}
function M.install(c,callbacks)
  local cap_before_edge=callbacks.voltage_waveforms.cap_before_edge
  local original={}
  for key,value in pairs(segment) do original[key]=value end
  -- Import at Program load; SIMION rejects callback-time workbench imports.
  local hs=simion.import(c.hs1_path)
  for key in pairs(segment) do segment[key]=nil end
  for key,value in pairs(original) do segment[key]=value end
  local fields,active,done={},nil,{}
  local function call(name) if original[name] then original[name]() end end
  local function pressure()
    local p={ion_px_mm-c.pose.translation_mm[1],ion_py_mm-c.pose.translation_mm[2],ion_pz_mm-c.pose.translation_mm[3]}
    local local_p={0,0,0}
    for i=1,3 do for j=1,3 do local_p[i]=local_p[i]+c.pose.rotation[j][i]*p[j] end end
    local d=c.gas.domain_native_mm
    if local_p[1]>=d.x_min and local_p[1]<d.x_max and math.abs(local_p[2])<d.transverse_halfwidth and math.abs(local_p[3])<d.transverse_halfwidth then
      return c.gas.parameters.hp_pressure_pa*c.pressure_scale
    end
    return 0
  end
  local function reset_hs()
    hs.reset_run_state()
    adjustable _gas_mass_amu=c.gas.parameters.mass_amu
    adjustable _temperature_k=c.gas.parameters.temperature_k
    adjustable _pressure_pa=0
    adjustable _sigma_m2=c.gas.parameters.cross_section_m2
    adjustable _mean_free_path_mm=c.gas.parameters.mean_free_path_mm
    adjustable _steps_per_MFP=c.numerics.hs1_steps_per_mfp
    adjustable _random_seed=c.numerics.collision_seed+1
    adjustable _mark_collisions=0
    adjustable _trace_level=0
    hs.pressure=pressure
    local expected={gas_mass_amu=c.gas.parameters.mass_amu,temperature_k=c.gas.parameters.temperature_k,
      pressure_pa=0,sigma_m2=c.gas.parameters.cross_section_m2,mean_free_path_mm=c.gas.parameters.mean_free_path_mm,
      steps_per_mfp=c.numerics.hs1_steps_per_mfp,random_seed=c.numerics.collision_seed+1,mark_collisions=0,trace_level=0}
    local function audit()
      local bound=hs.bound_parameters()
      for k,v in pairs(expected) do assert(bound[k]==v,'HS1 bound parameter differs: '..k) end
    end
    audit();hs.segment.initialize();audit()
  end
  local function close_stopped_stream()
    local state=callbacks.state_for()
    -- SIMION's other_actions sees both native splats and core-requested stops.
    -- Close here as well as terminate: a later particle must not inherit HS1.
    -- Official semantics: https://simion.com/info/trajectory_programming.html
    if (state and state.terminal) or ion_splat~=0 then done[ion_number]=true end
    return done[ion_number]
  end
  local function activate()
    assert(not done[ion_number],'terminated collision stream reactivated')
    if active==ion_number then return end
    assert(sim_grouped==0,'per-original-ID collision streams require sequential flight')
    assert(not active or done[active],'unfinished collision stream interleaved')
    reset_hs()
    local particle_seed=c.numerics.collision_seed+callbacks.particle_id()-1
    seed(particle_seed)
    print(string.format('COOLED_RNG: ion=%d particle_id=%d seed=%d',ion_number,callbacks.particle_id(),particle_seed))
    active=ion_number
  end
  local function coefficients(t)
    local released=t>=c.drive.release_start_us
    return {entry_close_delta=t>=c.drive.entrance_close_us and 1 or 0,
      release_delta=released and 1 or 0,
      inner_auxiliary_unit=released and 0 or c.calibration.inner_correction_v,
      hp_common_unit=released and c.calibration.release_hp_common_correction_v or 0}
  end
  function segment.initialize_run()
    call('initialize_run')
    sim_grouped=0;sim_rerun_flym=0
    active=nil;done={}
    for kind,path in pairs(c.extra_fields) do
      local pa=fields[kind]
      if not pa then pa=assert(simion.pas:open(path));fields[kind]=pa end
      -- Reuse the established standalone-response validator: dimensions,
      -- pitch, symmetry and potential type all belong to the shared core.
      callbacks.validate_response(pa,'cooled '..kind)
    end
  end
  function segment.efield_adjust()
    call('efield_adjust')
    local instance=simion.wb.instances[ion_instance]
    if not instance then return end
    local x,y,z=instance:wb_to_pa_coords(ion_px_mm,ion_py_mm,ion_pz_mm)
    if not instance.pa:inside_vc(x,y,z) then return end
    for kind,k in pairs(coefficients(callbacks.clock())) do
      if k~=0 then
        local ex,ey,ez=fields[kind]:field_vc(x,y,z)
        assert(ex~=nil and ey~=nil and ez~=nil,'cooled response field is undefined for '..kind)
        ion_dvoltsx_gu=ion_dvoltsx_gu-k*ex
        ion_dvoltsy_gu=ion_dvoltsy_gu-k*ey
        ion_dvoltsz_gu=ion_dvoltsz_gu-k*ez
      end
    end
  end
  function segment.tstep_adjust()
    local state=callbacks.state_for()
    if ion_instance==0 or done[ion_number] or (state and state.terminal) then call('tstep_adjust');return end
    activate();hs.segment.tstep_adjust()
    local t=callbacks.clock()
    local state=callbacks.state_for()
    if state and t>=c.drive.release_start_us then state.next_track=math.min(state.next_track,t+c.numerics.extraction_sample_interval_us) end
    call('tstep_adjust')
    for _,boundary in ipairs({c.drive.entrance_close_us,c.drive.release_start_us}) do
      ion_time_step=cap_before_edge(t,ion_time_step,boundary)
    end
  end
  function segment.other_actions()
    if ion_instance==0 or close_stopped_stream() then
      call('other_actions');close_stopped_stream();return
    end
    local state=callbacks.state_for()
    activate()
    local vx,vy,vz=ion_vx_mm,ion_vy_mm,ion_vz_mm
    hs.segment.other_actions()
    if vx~=ion_vx_mm or vy~=ion_vy_mm or vz~=ion_vz_mm then
      print(string.format('COOLED_COLLISION: particle_id=%d instrument_time_us=%.17g pressure_pa=%.17g vx_before=%.17g vy_before=%.17g vz_before=%.17g vx_after=%.17g vy_after=%.17g vz_after=%.17g',
        callbacks.particle_id(),callbacks.clock(),pressure(),vx,vy,vz,ion_vx_mm,ion_vy_mm,ion_vz_mm))
    end
    call('other_actions')
    close_stopped_stream()
    state=callbacks.state_for()
    if state and callbacks.clock()>=c.drive.release_start_us then state.next_track=math.min(state.next_track,callbacks.clock()+c.numerics.extraction_sample_interval_us) end
  end
  function segment.terminate()
    call('terminate');done[ion_number]=true
  end
end
return M
