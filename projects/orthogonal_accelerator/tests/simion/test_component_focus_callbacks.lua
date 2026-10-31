-- Execute the production callbacks and installed SIMION test_plane library.
-- Inert PA/stream adapters isolate callback behavior; no native Fly is claimed.
local program=assert(arg[1],'production component_focus.lua is required')
local library=assert(arg[2],'installed official testplanelib.lua is required')
local real_loadfile,real_open=loadfile,io.open
local writer_source=program:gsub("[\\/]projects[\\/]orthogonal_accelerator[\\/]simion[\\/]component_focus%.lua$","/common/simion/scientific_event_csv.lua")
assert(writer_source~=program,"production Program must be inside the repository projects root")
local rows
local function setup()
 rows={};segment={};ion_number=1;ion_splat=0;sim_ions_count=2
 local point={particle_count=2,focus_plane_tolerance_mm=0.1,field_mode='native',
  local_exit_z_mm=0,focus_plane_local_z_mm=0,maximum_step_us=0.1,
  voltages={},trajectory_quality=10}
 loadfile=function(path)
  if path==program:gsub('%.lua$','.scientific_event_csv.lua') then return real_loadfile(writer_source) end
  if path==program:gsub('%.lua$','.operating_point.lua') then return function() return point end end
  if path==program:gsub('%.lua$','.source_states.lua') then
   return function() return {{t=0,x=0,y=0,z=32,vx=0,vy=0,vz=0},{t=0,x=0,y=0,z=32,vx=0,vy=0,vz=0}} end
  end
  return real_loadfile(path)
 end
 io.open=function(path,mode)
  assert(path=='component_focus.events.csv' and mode=='w')
  return {write=function(self,text) rows[#rows+1]=text;return self end,flush=function() return true end,close=function() return true end}
 end
 simion={workbench_program=function() end,import=function(name)
  assert(name=='testplanelib.lua');return assert(real_loadfile(library))()
 end,wb={instances={{pa={fast_adjust=function() end}}}}}
 assert(real_loadfile(program))();segment.initialize_run()
 assert(rows[1]=='kind,ion,code,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us\n',"original event header must remain exact")
end
local function state(t,z,vz)
 ion_time_of_flight=t;ion_px_mm=t*2;ion_py_mm=t*3;ion_pz_mm=z
 ion_vx_mm=2;ion_vy_mm=3;ion_vz_mm=vz;ion_time_step=0.01
end
local function events(kind)
 local result={}
 for _,line in ipairs(rows) do if line:sub(1,#kind+1)==kind..',' then
  local fields={};for value in line:gmatch('([^,]*)[,]?') do fields[#fields+1]=value end
  result[#result+1]=fields
 end end
 return result
end
local function near(a,b) assert(math.abs(a-b)<1e-10,tostring(a)..' differs from '..tostring(b)) end

setup();state(1,0.09,-165);segment.other_actions();segment.tstep_adjust()
assert(#events('focus')==0,'approach inside tolerance must not record focus')
state(1.001,-0.075,-165);segment.other_actions()
local focus=events('focus');assert(#focus==1 and #events('exit')==1)
assert(focus[1][4]==string.format('%.12g',1+0.09/165),"event output must retain 12 significant digits")
near(tonumber(focus[1][4]),1+0.09/165);near(tonumber(focus[1][7]),0)
near(tonumber(focus[1][5]),2*(1+0.09/165))
assert(ion_splat==1 and #events('terminal')==1)
segment.terminate();segment.terminate_run();assert(#events('terminal')==1)

setup();state(1,0.2,-2);segment.other_actions()
state(1.1,0,-2);segment.other_actions();assert(#events('focus')==1)
near(tonumber(events('focus')[1][4]),1.1)
ion_splat=0;state(1.2,-0.2,-2);segment.other_actions()
assert(#events('focus')==1 and #events('exit')==1,'shared endpoint must be recorded once')

setup();state(1,-0.1,1);segment.other_actions()
state(1.2,0.1,1);segment.other_actions();assert(#events('focus')==0,'reverse crossing')
state(1.3,-0.1,-1);segment.other_actions();assert(#events('focus')==0,'reversing bracket is not directed')

setup();state(1,0,-1);segment.other_actions()
state(1.1,-0.1,-1);segment.other_actions();assert(#events('focus')==1,'exact initial endpoint')
near(tonumber(events('focus')[1][4]),1)

setup();state(1,0.1,-1);segment.other_actions()
ion_number=2;state(2,0.2,-1);segment.other_actions()
ion_number=1;state(1.2,-0.1,-1);segment.other_actions()
ion_number=2;ion_splat=0;state(2.4,-0.2,-1);segment.other_actions()
assert(#events('focus')==2 and #events('source')==2,'interleaved particle identity')
loadfile=real_loadfile;io.open=real_open
print('ACCELERATOR_COMPONENT_FOCUS_CALLBACKS=PASS cases=6 native_solver=false')
