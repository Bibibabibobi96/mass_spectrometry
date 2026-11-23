-- A frozen measured exit cohort in one ordinary static local IP/P1 array.
simion.workbench_program()
local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])'))
local c=assert(loadfile(directory..'case_config.lua'))()
-- Execution-only View/Retain policy. 3 suppresses both for canonical batch
-- evidence; a private GUI replay package explicitly requests 0 (both on).
-- SIMION 2020 examples/child_particles/child80.lua documents these values.
local image_control=3
if c.frontend then
 local f=c.frontend
 assert(f.schema_version==1 and f.role=='ip_prism_local_frontend' and
  (f.trajectory_image_control==0 or f.trajectory_image_control==3),'invalid local frontend')
 for key in pairs(f) do assert(key=='schema_version' or key=='role' or key=='trajectory_image_control','unknown local frontend key') end
 image_control=f.trajectory_image_control
end
-- Apply run controls only in initialize_run. The 2026-10-20 headless
-- wb:load/save_reload path rejected Q writes from load, despite the broader
-- load permissions documented online and in 2020 examples/collision_rs/test.lua.
-- initialize_run is documented at simion.com/info/workbench_program_extensions.html
-- and already ran successfully in this local native workflow. GUI preload
-- defaults remain a separate, unverified IOB-delivery concern.
assert(c.electrode_collision_model=='native_pa' or
 c.electrode_collision_model=='canonical_lens_first_contact','explicit collision model required')
assert(type(c.lens_electrodes)=='table','canonical lens geometry required')
local contact_kernel
if c.electrode_collision_model=='canonical_lens_first_contact' then
 contact_kernel=assert(loadfile(directory..'lens_contact.lua'))()
end
local events,samples,contacts,native_terminals,pa
local previous,done,next_sample,crossed,outcomes,termination_recorded={},{},{},{},{},{}
local function potential(s)
 return pa:potential_vc(math.abs(s[2])/c.pitch_mm[1],(s[3]-c.box_mm[2])/c.pitch_mm[2],(s[4]-c.box_mm[3])/c.pitch_mm[3])
end
local function state()
 return {c.source_epoch_us+ion_time_of_flight,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm}
end
local function record(handle,event,reason,s)
 local id=c.source[ion_number].particle_id
 handle:write(string.format('%s,%d,%s,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\n',
  event,id,reason,s[1],s[2],s[3],s[4],s[5],s[6],s[7],potential(s)))
end
local function finish(reason,s)
 -- Bookkeeping only: terminate cannot write ion_splat. Official SIMION
 -- https://simion.com/info/trajectory_programming.html (time/location stops)
 -- and installed 2020 examples/count_transmission/count.lua separate stop
 -- requests in other_actions from termination recording (checked 2026-10-20).
 if done[ion_number] then return end
 record(events,'terminal',reason,s)
 print(string.format('IP_PRISM_TERMINAL id=%d reason=%s t_us=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g',
  c.source[ion_number].particle_id,reason,s[1],s[2],s[3],s[4]))
 done[ion_number]=true;outcomes[ion_number]=reason
end
function segment.initialize_run()
 previous,done,next_sample,crossed,outcomes,termination_recorded={},{},{},{},{},{}
 sim_grouped=0
 sim_trajectory_image_control=image_control
 sim_trajectory_quality=c.trajectory_quality
 pa=simion.wb.instances[1].pa
 assert(#simion.wb.instances==1 and sim_ions_count==#c.source,'source/PA count mismatch')
 events=assert(io.open(directory..'events.csv','w'))
 samples=assert(io.open(directory..'samples.csv','w'))
 contacts=assert(io.open(directory..'lens_contacts.csv','w'))
 native_terminals=assert(io.open(directory..'native_terminations.csv','w'))
 native_terminals:write('particle_id,native_splat,reason,solver_instrument_time_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n')
 contacts:write('particle_id,electrode_id,component_name,face,fraction,native_splat_before,t0_us,x0_mm,y0_mm,z0_mm,vx0_mm_us,vy0_mm_us,vz0_mm_us,t1_us,x1_mm,y1_mm,z1_mm,vx1_mm_us,vy1_mm_us,vz1_mm_us,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n')
 local header='event,particle_id,reason,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us,potential_v\n'
 events:write(header);samples:write(header)
end
function segment.initialize()
 local src=assert(c.source[ion_number])
 ion_mass,ion_charge=src.mass_amu,src.charge_state
 ion_time_of_birth=src.t_us-c.source_epoch_us
 ion_px_mm,ion_py_mm,ion_pz_mm=src.x_mm,src.y_mm,src.z_mm
 ion_vx_mm,ion_vy_mm,ion_vz_mm=src.vx_mm_us,src.vy_mm_us,src.vz_mm_us
 -- SIMION may expose TOF=0 here before applying FLY2 TOB. Never assign TOF.
 local s={src.t_us,src.x_mm,src.y_mm,src.z_mm,src.vx_mm_us,src.vy_mm_us,src.vz_mm_us}
 previous[ion_number]=s;crossed[ion_number]={}
 next_sample[ion_number]=src.t_us+c.sample_interval_us
 record(events,'birth','measured_exit',s);record(samples,'birth','measured_exit',s)
end
function segment.tstep_adjust()
 ion_time_step=math.min(ion_time_step,c.maximum_step_us)
end
local function interpolate(first,last,fraction)
 local result={}
 for k=1,7 do result[k]=first[k]+fraction*(last[k]-first[k]) end
 return result
end
local function save_contact(prior,raw,s,fraction,id,face,native_splat)
 local name
 for _,rod in ipairs(c.lens_electrodes) do if rod.electrode_id==id then name=rod.name;break end end
 assert(name,'contact does not identify a canonical rod')
 contacts:write(string.format('%d,%d,%s,%s,%.17g,%d',
  c.source[ion_number].particle_id,id,name,face,fraction,native_splat))
 for _,row in ipairs({prior,raw,s}) do
  for k=1,7 do contacts:write(string.format(',%.17g',row[k])) end
 end
 contacts:write('\n')
end
function segment.other_actions()
 local raw=state();local prior=assert(previous[ion_number]);local s=raw
 local fraction,id,face
 local native_splat=ion_splat
 if native_splat~=0 then
  -- A vendor stop has precedence over later program observation/timeout logic.
  -- Do not clear or replace its raw splat value in this callback.
  if not done[ion_number] then
   if raw[1]>=next_sample[ion_number] then record(samples,'step','native_stop',raw) end
   finish('solver_stop',raw)
  end
  previous[ion_number]=raw
  return
 end
 if contact_kernel and native_splat==0 and not done[ion_number] then
  fraction,id,face=contact_kernel.first_contact(c.lens_electrodes,
   {prior[2],prior[3],prior[4]},{raw[2],raw[3],raw[4]})
  if fraction then s=interpolate(prior,raw,fraction) end
 end
 for _,plane in ipairs(c.observation_planes) do
  if not crossed[ion_number][plane.name] and prior[4]>plane.z_mm and s[4]<=plane.z_mm then
   local fraction=(plane.z_mm-prior[4])/(s[4]-prior[4])
   local crossing={}
   for k=1,7 do crossing[k]=prior[k]+fraction*(s[k]-prior[k]) end
   crossing[4]=plane.z_mm
   record(events,'plane',plane.name,crossing)
   crossed[ion_number][plane.name]=true
   if plane.name=='p1_exit' then
    finish('reached_exit',crossing)
    ion_splat=1
    break
   end
  end
 end
 if fraction and not done[ion_number] then
  -- Official location-stop API; the straight-step first-contact kernel is
  -- project-built. Keep native flags untouched and retain both raw bracket
  -- states in lens_contacts.csv. Event time is interpolated, as for p1_exit;
  -- solver TOF is never reassigned. This does not refine the electric field.
  save_contact(prior,raw,s,fraction,id,face,native_splat)
  ion_px_mm,ion_py_mm,ion_pz_mm=s[2],s[3],s[4]
  ion_vx_mm,ion_vy_mm,ion_vz_mm=s[5],s[6],s[7]
  record(samples,'step','lens_contact',s)
  finish('lens_contact',s)
  ion_splat=1
  previous[ion_number]=s
  return
 end
 if s[1]>=next_sample[ion_number] or done[ion_number] then
  record(samples,'step','sample',s);next_sample[ion_number]=s[1]+c.sample_interval_us
 end
 if not done[ion_number] and s[1]-c.source[ion_number].t_us>=c.maximum_flight_us then
  finish('timeout',s)
  ion_splat=1
 end
 previous[ion_number]=s
end
function segment.terminate()
 local s=state()
 if not done[ion_number] then finish('solver_stop',s) end
 if not termination_recorded[ion_number] then
  native_terminals:write(string.format('%d,%d,%s',c.source[ion_number].particle_id,ion_splat,outcomes[ion_number]))
  for k=1,7 do native_terminals:write(string.format(',%.17g',s[k])) end
  native_terminals:write('\n');termination_recorded[ion_number]=true
 end
end
function segment.terminate_run()
 for index=1,#c.source do assert(done[index],'missing terminal particle') end
 events:close();samples:close();contacts:close();native_terminals:close()
 print('IP_PRISM_LOCAL_FLIGHT=PASS case='..c.case_id..' count='..#c.source)
end
