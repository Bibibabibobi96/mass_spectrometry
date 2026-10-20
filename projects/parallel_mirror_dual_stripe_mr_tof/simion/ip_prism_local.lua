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
local events,samples,pa
local previous,done,next_sample,crossed={},{},{},{}
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
 done[ion_number]=true
end
function segment.initialize_run()
 previous,done,next_sample,crossed={},{},{},{}
 sim_grouped=0
 sim_trajectory_image_control=image_control
 sim_trajectory_quality=c.trajectory_quality
 pa=simion.wb.instances[1].pa
 assert(#simion.wb.instances==1 and sim_ions_count==#c.source,'source/PA count mismatch')
 events=assert(io.open(directory..'events.csv','w'))
 samples=assert(io.open(directory..'samples.csv','w'))
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
function segment.other_actions()
 local s=state();local prior=assert(previous[ion_number])
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
 if not done[ion_number] then finish('solver_stop',state()) end
end
function segment.terminate_run()
 for index=1,#c.source do assert(done[index],'missing terminal particle') end
 events:close();samples:close()
 print('IP_PRISM_LOCAL_FLIGHT=PASS case='..c.case_id..' count='..#c.source)
end
