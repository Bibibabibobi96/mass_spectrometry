-- Compose the selected official HS1 lifecycle with the existing RF Program.
-- The caller supplies only frozen resources and explicit scientific controls.
local M={}
function M.install(hs,gas,binder,config,clock,particle_id,waveforms)
  assert(type(hs)=='table' and type(hs.segment)=='table' and type(hs.reset_run_state)=='function' and type(hs.bound_parameters)=='function','adapted HS1 required')
  assert(type(config)=='table' and type(config.baseline)=='table' and type(config.numerics)=='table','explicit HS1 controls required')
  local b,n=config.baseline,config.numerics
  local local_gas=binder.bind(hs,gas,function() return ion_px_mm,ion_py_mm,ion_pz_mm end,assert(config.query_frame_id))
  local active,done=nil,{}
  local function reset()
    hs.reset_run_state()
    adjustable _gas_mass_amu=b.gas.mass_amu
    adjustable _temperature_k=b.gas.temperature_k
    adjustable _pressure_pa=0
    adjustable _sigma_m2=b.gas.cross_section_m2
    adjustable _mean_free_path_mm=b.gas.mean_free_path_mm
    adjustable _steps_per_MFP=n.hs1_steps_per_mfp
    adjustable _random_seed=n.seed+1
    adjustable _mark_collisions=0
    adjustable _trace_level=0
    local expected={gas_mass_amu=b.gas.mass_amu,temperature_k=b.gas.temperature_k,pressure_pa=0,
      sigma_m2=b.gas.cross_section_m2,mean_free_path_mm=b.gas.mean_free_path_mm,
      steps_per_mfp=n.hs1_steps_per_mfp,random_seed=n.seed+1,mark_collisions=0,trace_level=0}
    local function check()
      local actual=hs.bound_parameters()
      for key,value in pairs(expected) do assert(actual[key]==value,'HS1 bound parameter differs: '..key) end
    end
    check();hs.segment.initialize();check()
  end
  local original_run,original_step,original_actions,original_terminate=segment.initialize_run,segment.tstep_adjust,segment.other_actions,segment.terminate
  local function activate()
    assert(not done[ion_number],'terminated particle cannot reactivate HS1')
    if active==ion_number then return end
    assert(sim_grouped==0,'HS1 requires sequential particle processing')
    assert(not active or done[active],'interleaved particle stream is unsupported')
    reset();seed(n.seed+particle_id()-1);active=ion_number
  end
  function segment.initialize_run()
    original_run();active=nil;done={};sim_grouped=0;sim_rerun_flym=0;reset();seed(n.seed)
  end
  function segment.tstep_adjust()
    activate();hs.segment.tstep_adjust();original_step()
    local time=clock()
    for _,edge in ipairs(config.schedule_edges_us) do
      if edge>time then ion_time_step=waveforms.cap_before_edge(time,ion_time_step,edge) end
    end
  end
  function segment.other_actions()
    activate();hs.segment.other_actions();original_actions()
  end
  function segment.terminate()
    original_terminate();done[ion_number]=true
  end
  return local_gas
end
return M
