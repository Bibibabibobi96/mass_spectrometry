-- Native runtime focus trace for one accelerator PA controller; it never saves PA state.
-- Lifecycle follows projects/rf_multipole_ion_optics/simion/simion_transport.lua: persistent streams,
-- per-ion first-action state, per-ion terminate finalization, run-end backstop.
simion.workbench_program()
local program_path=debug.getinfo(1,'S').source:sub(2)
local CSV=assert(loadfile(program_path:gsub('%.lua$','.scientific_event_csv.lua')))()
local point=assert(loadfile(program_path:gsub('%.lua$','.operating_point.lua')),'operating-point companion required')()
local source_states=assert(loadfile(program_path:gsub('%.lua$','.source_states.lua')),'authoritative source-states companion required')()
-- SIMION 2020 examples/test_plane/testplanelib.lua, frozen by the flight runner.
-- The official library controls landing steps; bounded directed states below
-- own our event identity/6D projection, without a spatial-tolerance early hit.
local TestPlane=simion.import 'testplanelib.lua'
local exit_plane,focus_plane
local previous_state={}
local terminal_written={}
local focus_written={}
local exit_written={}
local event_file=nil
local function state_now()
 return {t=ion_time_of_flight,x=ion_px_mm,y=ion_py_mm,z=ion_pz_mm,vx=ion_vx_mm,vy=ion_vy_mm,vz=ion_vz_mm}
end
local function emit_event(kind,particle,code,state)
 assert(event_file,'component focus event recorder is unavailable')
 event_file:write({kind,string.format('%d',particle),code or '',state.t,state.x,state.y,state.z-point.local_exit_z_mm,state.vx,state.vy,state.vz})
 event_file:flush()
end
local function emit_authoritative_source(particle)
 local source=assert(source_states[particle],'authoritative source state is missing')
 emit_event('source',particle,nil,source)
end
local function ensure_source(particle,current)
 if previous_state[particle] then return previous_state[particle] end
 previous_state[particle]=current
 emit_authoritative_source(particle)
 return current
end
local function finalize_particle(particle,state,code)
 if terminal_written[particle] then return end
 emit_event('terminal',particle,code or 2,state)
 terminal_written[particle]=true
end
local function record_focus(particle,focus)
 if focus_written[particle] then return end
 assert(focus.vz<0,'focus capture must be -z directed')
 emit_event('focus',particle,nil,focus)
 focus_written[particle]=true
end
local function record_exit(particle,state)
 if exit_written[particle] then return end
 assert(state.vz<0,'exit capture must be -z directed')
 emit_event('exit',particle,nil,state)
 exit_written[particle]=true
end
local function capture_focus(particle,focus,current)
 record_focus(particle,focus)
 finalize_particle(particle,current,1)
 ion_splat=1
end
local function directed_crossing(previous,current,z)
 -- Same bounded endpoint semantics as common.analysis.plane_crossings:
 -- positive elapsed time, both velocities forward, no extrapolation.
 if current.t<=previous.t or previous.vz>=0 or current.vz>=0 or
    previous.z<z or current.z>z or current.z>=previous.z then return nil end
 local f=(z-previous.z)/(current.z-previous.z)
 return {t=previous.t+f*(current.t-previous.t),x=previous.x+f*(current.x-previous.x),y=previous.y+f*(current.y-previous.y),z=z,vx=previous.vx+f*(current.vx-previous.vx),vy=previous.vy+f*(current.vy-previous.vy),vz=previous.vz+f*(current.vz-previous.vz)}
end
function segment.initialize_run()
 assert(#simion.wb.instances==1,'one accelerator instance required')
 assert(sim_ions_count==point.particle_count,'component focus particle count differs from frozen source')
 assert(#source_states==point.particle_count,'authoritative source state count differs from frozen source')
 assert(point.focus_plane_tolerance_mm>0,'focus-plane tolerance must be positive')
 assert(point.field_mode=='native' or point.field_mode=='zone1_ideal' or point.field_mode=='zone2_ideal' or point.field_mode=='full_ideal','field mode is invalid')
 previous_state={};terminal_written={};focus_written={};exit_written={}
 exit_plane=TestPlane(0,0,point.local_exit_z_mm,0,0,-1,function() end)
 focus_plane=TestPlane(0,0,point.focus_plane_local_z_mm,0,0,-1,function() end)
 event_file=CSV.open('component_focus.events.csv',{'kind','ion','code','t_us','x_mm','y_mm','z_mm','vx_mm_us','vy_mm_us','vz_mm_us'},12)
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
 if ion_vz_mm>=0 then return end
 if not exit_written[ion_number] then exit_plane.tstep_adjust() end
 if not focus_written[ion_number] then focus_plane.tstep_adjust() end
end
function segment.initialize()
 -- SIMION calls initialize for the Fly'm; record each ion on its first action.
end
function segment.other_actions()
 exit_plane.other_actions();focus_plane.other_actions()
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
 local exit=directed_crossing(previous,current,point.local_exit_z_mm)
 if exit then record_exit(ion_number,exit) end
 local focus=directed_crossing(previous,current,point.focus_plane_local_z_mm)
 if focus then capture_focus(ion_number,focus,current) end
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
