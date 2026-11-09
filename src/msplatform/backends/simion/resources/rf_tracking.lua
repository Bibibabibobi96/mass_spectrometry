-- SIMION2020 official workbench callbacks and reserved variables.
-- The sole installed model_drive/rf_drive consumer supplies all electrode formulas.
local function single_flight_write_trace(text) print(text);io.stdout:flush() end
local single_flight_reported={}
local rf_previous,rf_births,rf_deadline_stopped={},{},{}
local function rf_emit(event,reason,t,x,y,z,vx,vy,vz)
  single_flight_write_trace(string.format('RF_NATIVE_STATE_V1: {"event":%q,"reason":%q,"particle_id":%.0f,"ion":%d,"instrument_time_us":%.17g,"x_mm":%.17g,"y_mm":%.17g,"z_mm":%.17g,"vx_mm_per_us":%.17g,"vy_mm_per_us":%.17g,"vz_mm_per_us":%.17g,"mass_amu":%.17g,"charge_state":%.17g,"instance":%d}',
    event,reason,single_flight_canonical_particle_id(),ion_number,t,x,y,z,vx,vy,vz,ion_mass,ion_charge,ion_instance))
end
local function rf_emit_current(event,reason)
  rf_emit(event,reason,single_flight_instrument_time_us(),ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm)
end
function segment.initialize_run()
  rf_previous,rf_births,rf_deadline_stopped={},{},{}
  sim_trajectory_quality=rf_trajectory_quality
  if rf_grouped~=nil then sim_grouped=rf_grouped end
  sim_repulsion='none'
  sim_relativity=0
  -- Official SIMION8.2 callback coverage includes instance0 outside PAs.
  -- This defines no external field, force, or extension of the workbench.
  sim_segment_global=1
  single_flight_write_trace(string.format('RF_DYNAMICS_V1: {"grouped":%d,"repulsion":%q,"relativity":%d,"segment_global":%d}',sim_grouped,sim_repulsion,sim_relativity,sim_segment_global))
end
function segment.initialize()
  single_flight_restore_source_velocity(rf_initial_velocities)
  local time=single_flight_instrument_time_us()
  assert(time==single_flight_time_origin_us[single_flight_source_row_index()],'RF actual start clock differs')
  rf_emit_current('source_release','none')
  rf_births[ion_number]=true
  single_flight_reported[ion_number]={}
  rf_previous[ion_number]={t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}
end
function segment.fast_adjust()
  local domain=rf_instance_domains[ion_instance]
  if not domain then return end
  local time=single_flight_instrument_time_us()
  for _,row in ipairs(rf_consumer.evaluate_at(time)) do
    for _,target in ipairs(row.native_targets) do
      if target.domain==domain then adj_elect[target.electrode_id]=row.voltage_v end
    end
  end
end
function segment.tstep_adjust()
  local time=single_flight_instrument_time_us()
  ion_time_step=math.min(ion_time_step,rf_step_cap_us)
  local deadline=single_flight_absolute_deadline_us[single_flight_source_row_index()]
  if deadline>time then ion_time_step=math.min(ion_time_step,deadline-time) end
end
function segment.other_actions()
  local time=single_flight_instrument_time_us()
  local p=rf_previous[ion_number]
  assert(rf_births[ion_number],'RF native step precedes actual initialize')
  local reported=single_flight_reported[ion_number] or {}
  if p and time>p.t then
    for _,requested in ipairs(rf_observation_times) do
      if p.t<requested and time>=requested and not reported[requested] then
        local f=(requested-p.t)/(time-p.t)
        rf_emit('shared','accepted_step_linear_interpolation',requested,
          p.x+f*(ion_px_mm-p.x),p.y+f*(ion_py_mm-p.y),p.z+f*(ion_pz_mm-p.z),
          p.vx+f*(ion_vx_mm-p.vx),p.vy+f*(ion_vy_mm-p.vy),p.vz+f*(ion_vz_mm-p.vz))
        reported[requested]=true
      end
    end
  end
  local result={splat=false}
  if result.splat then ion_splat=1 end
  if time>=single_flight_absolute_deadline_us[single_flight_source_row_index()] and ion_splat==0 then
    rf_emit_current('deadline_endpoint','absolute_deadline')
    rf_deadline_stopped[ion_number]=true;ion_splat=1
  end
  rf_previous[ion_number]={t=time,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}
end
function segment.terminate()
  rf_emit_current('terminal',rf_deadline_stopped[ion_number] and 'deadline' or 'unknown')
end
