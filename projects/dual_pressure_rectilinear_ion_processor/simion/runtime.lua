-- Actual SIMION integration in native refined electrode fields + official HS1.
simion.workbench_program()
local program_file=debug.getinfo(1,'S').source:sub(2)
local directory=program_file:match('^(.*[/\\])') or './'
local c=assert(loadfile(directory..'frozen_config.lua'))()
local b,n,g=c.baseline,c.numerics,c.baseline.geometry
-- Native PA geometry remains local; SIMION particle coordinates are project XYZ.
-- The common rigid-transform contract is validated before this frozen input exists.
local rotation=c.coordinate_transform and c.coordinate_transform.rotation or {{1,0,0},{0,1,0},{0,0,1}}
local translation=c.coordinate_transform and c.coordinate_transform.translation_mm or {0,0,0}
local function project_vector(x,y,z)
 local v={x,y,z};local result={}
 for i=1,3 do result[i]=0;for j=1,3 do result[i]=result[i]+rotation[i][j]*v[j] end end
 return result[1],result[2],result[3]
end
local function project_position(x,y,z)
 local a,b0,c0=project_vector(x,y,z)
 return a+translation[1],b0+translation[2],c0+translation[3]
end
local function local_vector(x,y,z)
 local v={x,y,z};local result={}
 for i=1,3 do result[i]=0;for j=1,3 do result[i]=result[i]+rotation[j][i]*v[j] end end
 return result[1],result[2],result[3]
end
local function local_position(x,y,z)
 return local_vector(x-translation[1],y-translation[2],z-translation[3])
end
local function world_state(state)
 local x,y,z=project_position(state.x,state.y,state.z)
 local vx,vy,vz=project_vector(state.vx,state.vy,state.vz)
 return {t=state.t,x=x,y=y,z=z,vx=vx,vy=vy,vz=vz}
end
local source=assert(loadfile(directory..'source_states.lua'))()
local drive=assert(loadfile(directory..'native_drive.lua'))()
local rf=assert(loadfile(directory..'simion_rf_drive.lua'))().new{
 waveform='cosine',frequency_hz=b.electric.rf_frequency_hz,
 phase_rad=b.clock.rf_phase_rad,rf_amplitude_v=b.electric.rf_peak_to_peak_v/2,
 rf_scale=1,common_mode_scale=1,group_dc_v={0,0},
 rf_steps_per_period=n.rf_steps_per_period,
 electrodes={{electrode_id=1,electrode_group=1,polarity=1,common_mode_v=0}}
}
local hs=simion.import(directory..'collision_hs1.lua')
-- Official module exposes adjustables in the workbench program environment.
_gas_mass_amu=b.gas.mass_amu
_temperature_k=b.gas.temperature_k
_pressure_pa=0
_sigma_m2=b.gas.cross_section_m2
_mean_free_path_mm=b.gas.mean_free_path_mm
_steps_per_MFP=n.hs1_steps_per_mfp
_random_seed=n.seed+1
_mark_collisions=0
_trace_level=0
local function local_pressure()
 local x,y,z=local_position(ion_px_mm,ion_py_mm,ion_pz_mm)
 if math.abs(y)>=g.r0_mm or math.abs(z)>=g.r0_mm then return 0 end
 if x>=g.guide_length_mm and x<g.guide_length_mm+g.hp_length_mm then return b.gas.hp_pressure_pa end
 if x>=g.guide_length_mm+g.hp_length_mm then return b.gas.lp_pressure_pa end
 return 0
end
hs.pressure=local_pressure
local function reset_collision_module()
 -- SIMION forbids importing a workbench program inside a Fly callback.
 -- The frozen run copy adds only this explicit reset hook; all collision
 -- equations and sampling logic remain byte-identical to the official file.
 assert(hs.reset_run_state,'frozen HS1 reset adapter is required')
 hs.reset_run_state()
 _gas_mass_amu=b.gas.mass_amu;_temperature_k=b.gas.temperature_k
 _pressure_pa=0;_sigma_m2=b.gas.cross_section_m2
 _mean_free_path_mm=b.gas.mean_free_path_mm;_steps_per_MFP=n.hs1_steps_per_mfp
 _random_seed=n.seed+1;_mark_collisions=0;_trace_level=0
 hs.pressure=local_pressure
 hs.segment.initialize()
end
local events,trace
local seen,done,previous,next_sample,extraction_trace={},{},{},{},{}
local checkpoints={{b.schedule.capture_end_us,'capture'},
 {b.schedule.transfer_end_us,'transfer'}, {b.schedule.extraction_start_us,'pre_extraction'}}
local hp_end=g.guide_length_mm+g.hp_length_mm
local lp_end=hp_end+g.lp_length_mm
local function draw_numerical_exit_outline()
 -- Visual guide only: this adds no metal, detector interaction, or field.
 local plot=simion.experimental and simion.experimental.plot_line_segment
 assert(type(plot)=='function',
  'numerical exit outline requires simion.experimental.plot_line_segment')
 local function edge(x0,y0,z0,x1,y1,z1)
  local a,b0,c0=project_position(x0,y0,z0)
  local d,e,f=project_position(x1,y1,z1)
  plot(a,b0,c0,d,e,f,0,0,12,12,false)
 end
 local y=g.extraction_end_y_mm
 local z0,z1=c.native_projection.origin_mm[3],c.native_projection.maximum_mm[3]
 -- Zero volt values only set the drawing height in the potential-energy view.
 -- Color 12 and mark=false distinguish this frame from particle trajectory data.
 edge(hp_end,y,z0,lp_end,y,z0)
 edge(lp_end,y,z0,lp_end,y,z1)
 edge(lp_end,y,z1,hp_end,y,z1)
 edge(hp_end,y,z1,hp_end,y,z0)
end
local function write_state(event,reason,state)
 state=world_state(state)
 events:write(string.format('%s,%d,%s,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g\n',
  event,ion_number,reason or 'none',state.t,state.x,state.y,state.z,state.vx,state.vy,state.vz))
end
local function now()
 local x,y,z=local_position(ion_px_mm,ion_py_mm,ion_pz_mm)
 local vx,vy,vz=local_vector(ion_vx_mm,ion_vy_mm,ion_vz_mm)
 return {t=ion_time_of_flight,x=x,y=y,z=z,vx=vx,vy=vy,vz=vz}
end
local function crossing(a,v,coordinate,plane)
 local fraction=(plane-a[coordinate])/(v[coordinate]-a[coordinate])
 local result={}
 for _,key in ipairs({'t','x','y','z','vx','vy','vz'}) do result[key]=a[key]+fraction*(v[key]-a[key]) end
 result[coordinate]=plane
 return result
end
local function emit(event,state)
 local id=ion_number;seen[id]=seen[id] or {}
 if not seen[id][event] then write_state(event,'none',state);seen[id][event]=true end
end
local function finish(reason,state)
 if done[ion_number] then return end
 write_state('terminal',reason,state);done[ion_number]=true;ion_splat=1
end
function segment.initialize_run()
 if events then events:close() end
 if trace then trace:close() end
 seen,done,previous,next_sample,extraction_trace={},{},{},{},{}
 reset_collision_module()
 seed(n.seed)
 sim_grouped=0
 sim_rerun_flym=0
 sim_trajectory_image_control=0
 draw_numerical_exit_outline()
 assert(#simion.wb.instances==1 and #source==sim_ions_count,'source/volume mismatch')
 events=assert(io.open(directory..'events.csv','w'))
 events:write('event,particle_id,reason,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n')
 trace=assert(io.open(directory..'samples.csv','w'))
 trace:write('particle_id,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n')
 sim_trajectory_quality=n.trajectory_quality
 print('ION_PROCESSOR_BEGIN N='..#source..' field=native_electrodes collision=official_HS1')
end
function segment.initialize()
 hs.segment.initialize()
end
function segment.fast_adjust()
 local voltages=drive.voltages(c,ion_time_of_flight,
  rf.differential_at(b.clock.epoch_us+ion_time_of_flight))
 for id,v in ipairs(voltages) do adj_elect[id]=v end
end
function segment.tstep_adjust()
 hs.segment.tstep_adjust()
 ion_time_step=math.min(ion_time_step,n.dt_us,rf.timestep_cap_us)
 local t=ion_time_of_flight
 for _,point in ipairs(checkpoints) do
  if point[1]>t then ion_time_step=math.min(ion_time_step,point[1]-t) end
 end
 local pulse_start=drive.pulse_start_us(c)
 if pulse_start>t then ion_time_step=math.min(ion_time_step,pulse_start-t) end
 if b.schedule.terminal_us>t then
  ion_time_step=math.min(ion_time_step,b.schedule.terminal_us-t)
 end
end
function segment.other_actions()
 local id=ion_number
 if not seen[id] then
  emit('source',assert(source[id]));previous[id]=now();next_sample[id]=0
 end
 if done[id] then return end
 hs.segment.other_actions()
 local s=now()
 if s.t>=b.schedule.extraction_start_us and not extraction_trace[id] then
  extraction_trace[id]=true
  next_sample[id]=math.min(next_sample[id],b.schedule.extraction_start_us)
 end
 if s.t>=next_sample[id] then
  local output=world_state(s)
  trace:write(string.format('%d,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g\n',id,output.t,output.x,output.y,output.z,output.vx,output.vy,output.vz))
  local interval=extraction_trace[id] and n.extraction_sample_interval_us or n.sample_interval_us
  next_sample[id]=s.t+interval
 end
 if s.x>=g.guide_length_mm and previous[id].x<g.guide_length_mm then
  emit('hp_enter',crossing(previous[id],s,'x',g.guide_length_mm))
 end
 for _,point in ipairs(checkpoints) do
  if s.t>=point[1] then emit(point[2],s) end
 end
 local extraction=s.t>=b.schedule.extraction_start_us and s.x>hp_end
 if extraction and s.y>=g.extraction_end_y_mm and previous[id].y<g.extraction_end_y_mm then
  local exit=crossing(previous[id],s,'y',g.extraction_end_y_mm)
  write_state('extraction_exit','acceptance_surface',exit)
  finish('acceptance_surface',exit)
 elseif not extraction and (math.abs(s.y)>g.boundary_radius_mm or math.abs(s.z)>g.boundary_radius_mm) then
  finish('radial_escape',s)
 end
 if s.x<0 then finish('backward_escape',s) end
 -- The LP end is an open lens aperture, not an absorbing metal plane.
 -- Native PA electrode/domain termination governs downstream losses.
 if s.t>=b.schedule.terminal_us then finish('timeout',s) end
 if ion_splat~=0 and not done[id] then finish('solver_stop',s) end
 previous[id]=s
end
function segment.terminate()
 if not seen[ion_number] then emit('source',assert(source[ion_number])) end
 if not done[ion_number] then finish('solver_stop',now()) end
 if ion_number%10==0 then events:flush();trace:flush();print('ION_PROCESSOR_PROGRESS particle='..ion_number) end
end
function segment.terminate_run()
 if events then events:close();events=nil end
 if trace then trace:close();trace=nil end
 print('ION_PROCESSOR_END')
end
