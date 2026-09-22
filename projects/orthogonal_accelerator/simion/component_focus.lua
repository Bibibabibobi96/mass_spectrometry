-- Native runtime focus trace for one accelerator PA controller; it never saves PA state.
-- Lifecycle follows common/multipole/simion_transport.lua: persistent streams,
-- per-ion first-action state, per-ion terminate finalization, run-end backstop.
simion.workbench_program()
local program_path=debug.getinfo(1,'S').source:sub(2)
local point=assert(loadfile(program_path:gsub('%.lua$','.operating_point.lua')),'operating-point companion required')()
local source_states=assert(loadfile(program_path:gsub('%.lua$','.source_states.lua')),'authoritative source-states companion required')()
local previous_state={}
local terminal_written={}
local focus_written={}
local event_file=nil
local function state_now()
 return {t=ion_time_of_flight,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vz=ion_vz_mm}
end
local function emit_event(kind,particle,code,state,vz)
 assert(event_file,'component focus event recorder is unavailable')
 event_file:write(string.format('%s,%d,%s,%.12g,%.12g,%.12g,%.12g,%s\n',kind,particle,code or '',state.t,state.x,state.y,state.z-point.local_exit_z_mm,vz and string.format('%.12g',vz) or ''))
 event_file:flush()
end
local function emit_authoritative_source(particle)
 local source=assert(source_states[particle],'authoritative source state is missing')
 emit_event('source',particle,nil,source,nil)
end
local function ensure_source(particle,current)
 if previous_state[particle] then return previous_state[particle] end
 previous_state[particle]=current
 emit_authoritative_source(particle)
 return current
end
local function finalize_particle(particle,state,code)
 if terminal_written[particle] then return end
 emit_event('terminal',particle,code or 2,state,nil)
 terminal_written[particle]=true
end
local function record_focus(particle,focus)
 if focus_written[particle] then return end
 assert(focus.vz<0,'focus capture must be -z directed')
 emit_event('focus',particle,nil,focus,focus.vz)
 focus_written[particle]=true
end
local function capture_focus(particle,focus,current)
 record_focus(particle,focus)
 finalize_particle(particle,current,1)
 ion_splat=1
end
function segment.initialize_run()
 assert(#simion.wb.instances==1,'one accelerator instance required')
 assert(sim_ions_count==point.particle_count,'component focus particle count differs from frozen source')
 assert(#source_states==point.particle_count,'authoritative source state count differs from frozen source')
 assert(point.focus_plane_tolerance_mm>0,'focus-plane tolerance must be positive')
 assert(point.field_mode=='native' or point.field_mode=='zone1_ideal' or point.field_mode=='zone2_ideal' or point.field_mode=='full_ideal','field mode is invalid')
 event_file=assert(io.open('component_focus.events.csv','w'),'component focus event CSV cannot be opened')
 event_file:write('kind,ion,code,t_us,x_mm,y_mm,z_mm,vz_mm_us\n')
 event_file:flush()
 local pa=simion.wb.instances[1].pa;pa:fast_adjust(point.voltages)
 sim_trajectory_quality=point.trajectory_quality
 print('ACCELERATOR_COMPONENT_FOCUS status=prototype runtime_fast_adjust=true pa_save=false event_csv=component_focus.events.csv')
end
function segment.efield_adjust()
 local z=ion_pz_mm
 local ideal_zone1=(point.field_mode=='zone1_ideal' or point.field_mode=='full_ideal') and z>=point.grid1_local_z_mm and z<=point.repeller_local_z_mm
 local ideal_zone2=(point.field_mode=='zone2_ideal' or point.field_mode=='full_ideal') and z>=point.local_exit_z_mm and z<point.grid1_local_z_mm
 if not ideal_zone1 and not ideal_zone2 then return end
 local start_v,end_v,start_z,end_z
 if ideal_zone1 then
  start_v,end_v,start_z,end_z=point.voltages[2],point.voltages[3],point.repeller_local_z_mm,point.grid1_local_z_mm
 else
  start_v,end_v,start_z,end_z=point.voltages[3],point.voltages[4],point.grid1_local_z_mm,point.local_exit_z_mm
 end
 local derivative=(end_v-start_v)/(end_z-start_z)
 local pa=simion.wb.instances[ion_instance].pa
 ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=0,0,derivative*pa.dz_mm*simion.wb.instances[ion_instance].scale
end
function segment.tstep_adjust()
 ion_time_step=math.min(ion_time_step,point.maximum_step_us)
 local current=state_now()
 if focus_written[ion_number] or current.vz>=-1e-12 then return end
 local dz=current.z-point.focus_plane_local_z_mm
 if dz>0 then
  local dt_to_plane=dz/(-current.vz)
  if dt_to_plane>0 and ion_time_step>dt_to_plane then ion_time_step=dt_to_plane end
 end
 -- The next callback sees the integrator's actual landed state.  Do not
 -- synthesize a free-flight focus event from the velocity estimate above.
 if math.abs(dz)<=point.focus_plane_tolerance_mm then record_focus(ion_number,current) end
end
function segment.initialize()
 -- SIMION calls initialize for the Fly'm; record each ion on its first action.
end
function segment.other_actions()
 local current=state_now()
 local previous=previous_state[ion_number]
 if not previous then
  previous=ensure_source(ion_number,current)
  if ion_splat~=0 then finalize_particle(ion_number,current,ion_splat) end
  return
 end
 if ion_splat~=0 then
  finalize_particle(ion_number,current,ion_splat)
  previous_state[ion_number]=current
  return
 end
 if previous.z>point.focus_plane_local_z_mm and current.z<=point.focus_plane_local_z_mm and current.vz<0 then
  local f=(point.focus_plane_local_z_mm-previous.z)/(current.z-previous.z)
  local focus={t=previous.t+f*(current.t-previous.t),x=previous.x+f*(current.x-previous.x),y=previous.y+f*(current.y-previous.y),z=point.focus_plane_local_z_mm,vz=previous.vz+f*(current.vz-previous.vz)}
  capture_focus(ion_number,focus,current)
 end
 previous_state[ion_number]=current
end
function segment.terminate()
 local current=state_now()
 ensure_source(ion_number,current)
 finalize_particle(ion_number,current,focus_written[ion_number] and 1 or 2)
end
function segment.terminate_run()
 -- SIMION can bypass terminate for an electrode splat; use last observed state.
 for particle=1,sim_ions_count do
  if previous_state[particle] then finalize_particle(particle,previous_state[particle],2) end
 end
 if event_file then event_file:close();event_file=nil end
end
