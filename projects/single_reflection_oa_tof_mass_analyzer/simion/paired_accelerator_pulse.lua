-- Narrow OA finite-pulse callbacks. One unchanged ON PA owns field and collision geometry.
-- SIMION2020 efield_adjust uses positive potential derivatives in PA grid units;
-- field_vc returns their negatives. No Refine/FastAdjust/PA save or second array.
local adapter = {}

function adapter.new(cfg, deps)
  local states, terminated, carrier = {}, 0, nil
  local function emit(event, requested, raw_status)
    local row=deps.row_index()
    local present=1
    for _,value in ipairs({ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm}) do
      if value~=value or math.abs(value)==math.huge then present=0 end
    end
    deps.emit({particle_id=deps.particle_id(),native_particle_index=ion_number,event=event,
      instrument_time_us=deps.clock(),requested_time_us=requested,
      x_mm=ion_px_mm,y_mm=ion_py_mm,z_mm=ion_pz_mm,
      vx_m_per_s=ion_vx_mm*1000,vy_m_per_s=ion_vy_mm*1000,vz_m_per_s=ion_vz_mm*1000,
      state_present=present,solver_raw_status=raw_status,original_birth_time_us=cfg.birth_times_us[row],
      terminal_reason=event=='terminal' and (states[ion_number].window_complete and 'observation_window_complete' or 'unknown') or ''})
  end
  local function matches_instance()
    assert(#simion.wb.instances==1,'OA pulse requires one actual ON-field instance')
    local item=simion.wb.instances[1]
    local function path_key(path) return path:gsub('\\','/'):lower() end
    assert(path_key(item.pa.path)==path_key(cfg.field_pa),'OA pulse field path differs')
    for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
      assert(item.pa[key]==cfg.grid[key],'OA pulse grid differs: '..key)
    end
    assert(item.x==cfg.origin.x and item.y==cfg.origin.y and item.z==cfg.origin.z and
      item.az==0 and item.el==0 and item.rt==0 and item.scale==1,'OA pulse direct placement differs')
    assert(item.pa.potential_type=='electric','OA pulse requires an electric PA')
    return item
  end
  local callbacks={}
  function callbacks.load() sim_trajectory_quality=cfg.trajectory_quality end
  function callbacks.initialize_run()
    carrier=matches_instance();states={};terminated=0
    sim_trajectory_quality=cfg.trajectory_quality
  end
  function callbacks.initialize()
    assert(ion_instance==1 and ion_time_of_flight==0,'OA pulse source must start in the declared PA at zero elapsed time')
    local gx,gy,gz=carrier:wb_to_pa_coords(ion_px_mm,ion_py_mm,ion_pz_mm)
    assert(carrier.pa:inside_vc(gx,gy,gz),'OA pulse source is outside its numerical domain')
    deps.restore_velocity(cfg.velocities_mm_per_us)
    assert(deps.clock()==cfg.source_time_us,'OA pulse source clock differs')
    states[ion_number]={next_observation=1,terminated=false}
    emit('source_state',cfg.source_time_us,ion_splat)
    if cfg.observation_times_us[1]==deps.clock() then
      emit('observation',cfg.observation_times_us[1],ion_splat);states[ion_number].next_observation=2
    end
  end
  function callbacks.efield_adjust()
    if ion_instance~=1 then return end
    -- Direct assignment: OFF is zero; ON is this one PA, never base+delta-base.
    ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=0,0,0
    if not deps.pulse.is_active_at(deps.clock()) then return end
    local x,y,z=carrier:wb_to_pa_coords(ion_px_mm,ion_py_mm,ion_pz_mm)
    -- Trial queries can leave the PA before the accepted state terminates.
    -- No field extrapolation or collision-entity inference outside the BVP.
    if not carrier.pa:inside_vc(x,y,z) then return end
    local ex,ey,ez=carrier.pa:field_vc(x,y,z)
    ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=-ex,-ey,-ez
  end
  function callbacks.tstep_adjust()
    local state=assert(states[ion_number],'OA pulse particle was not initialized')
    if state.terminated then return end
    local t=deps.clock()
    local dt=math.min(ion_time_step,cfg.maximum_step_us)
    dt=deps.pulse.cap_timestep_at(t,dt)
    local edge=cfg.observation_times_us[state.next_observation]
    if edge then dt=deps.waveforms.cap_before_edge(t,dt,edge) end
    assert(dt>0,'OA pulse requires a positive native timestep')
    ion_time_step=dt
  end
  function callbacks.other_actions()
    local state=assert(states[ion_number],'OA pulse particle was not initialized')
    if state.terminated or ion_splat~=0 then return end
    local t=deps.clock()
    local target=cfg.observation_times_us[state.next_observation]
    while target and t>=target do
      -- Preserve actual accepted time/6D, also recording the requested time.
      -- A missed landing is visible; no interpolation or fabricated state.
      emit('observation',target,ion_splat)
      state.next_observation=state.next_observation+1
      target=cfg.observation_times_us[state.next_observation]
    end
    if not target then state.window_complete=true;ion_splat=1 end -- declared observation-window stop only
  end
  function callbacks.terminate()
    local state=assert(states[ion_number],'OA pulse terminal lacks initialized source')
    assert(not state.terminated,'OA pulse duplicate native terminal')
    -- SIMION 2020 does not expose ion_splat in terminate. Do not carry a
    -- previous callback's status forward as if it were the native terminal.
    emit('terminal',nil,nil);state.terminated=true;terminated=terminated+1
  end
  function callbacks.terminate_run()
    assert(terminated==cfg.particle_count,'OA pulse native terminals do not cover its explicit batch')
    print('PAIRED_ACCELERATOR_PULSE_CALLBACKS_COMPLETE particles='..terminated)
  end
  return callbacks
end
return adapter
