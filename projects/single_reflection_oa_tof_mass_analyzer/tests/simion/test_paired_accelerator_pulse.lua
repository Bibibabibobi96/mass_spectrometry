-- Callback fixture only. Synthetic PA vectors are not a field or native-Fly result.
local module=dofile(assert(arg[1]));local math_module=dofile(assert(arg[2]))
local pulse_module=dofile(assert(arg[3]))
local t,rows,queries=9.5,{},0
local pa={path='baseline.pa',potential_type='electric',nx=10,ny=11,nz=12,dx_mm=.5,dy_mm=1,dz_mm=.05}
function pa:inside_vc() return true end
function pa:field_vc() queries=queries+1;return 2,-3,4 end
local instance={pa=pa,x=-1,y=-5,z=-2,az=0,el=0,rt=0,scale=1}
function instance:wb_to_pa_coords(x,y,z) return (x-self.x)/pa.dx_mm,(y-self.y)/pa.dy_mm,(z-self.z)/pa.dz_mm end
simion={wb={instances={instance}}}
ion_number=1;ion_instance=1;ion_time_of_flight=0;ion_splat=0
ion_px_mm,ion_py_mm,ion_pz_mm=0,0,0
ion_vx_mm,ion_vy_mm,ion_vz_mm=0,0,0
local cfg={field_pa='baseline.pa',grid={nx=10,ny=11,nz=12,dx_mm=.5,dy_mm=1,dz_mm=.05},
 origin={x=-1,y=-5,z=-2},source_time_us=9.5,trajectory_quality=19,maximum_step_us=.25,
 particle_count=2,birth_times_us={.041,.007},velocities_mm_per_us={{1.25,-.5,2},{2,3,4}},
 observation_times_us={9.5,10,11,12,13}}
local shared_pulse=pulse_module.new{canonical_clock=function() return t end,voltage_waveforms=math_module,
 pulse_time_us=10,pulse_width_us=2,pulse_mode=function() return 1 end}
local restore_calls=0
local callbacks=module.new(cfg,{clock=function() return t end,row_index=function() return ion_number end,
 particle_id=function() return ({41,7})[ion_number] end,pulse=shared_pulse,waveforms=math_module,
 restore_velocity=function(vectors) restore_calls=restore_calls+1;ion_vx_mm,ion_vy_mm,ion_vz_mm=unpack(vectors[ion_number]) end,
 emit=function(row) rows[#rows+1]=row end})
callbacks.load();assert(sim_trajectory_quality==19)
callbacks.initialize_run();callbacks.initialize()
assert(restore_calls==1 and ion_vx_mm==1.25 and ion_vy_mm==-.5 and ion_vz_mm==2)
assert(rows[1].particle_id==41 and rows[1].instrument_time_us==9.5 and rows[1].original_birth_time_us==.041)
assert(rows[1].solver_raw_status==0 and rows[2].solver_raw_status==0)
callbacks.efield_adjust();assert(queries==0 and ion_dvoltsx_gu==0 and ion_dvoltsy_gu==0 and ion_dvoltsz_gu==0)
t=9.875;ion_time_step=1;callbacks.tstep_adjust();assert(ion_time_step==.125)
t=10;callbacks.efield_adjust();assert(queries==1 and ion_dvoltsx_gu==-2 and ion_dvoltsy_gu==3 and ion_dvoltsz_gu==-4)
callbacks.other_actions();t=11;callbacks.other_actions()
t=12;callbacks.efield_adjust();assert(queries==1 and ion_dvoltsx_gu==0 and ion_dvoltsy_gu==0 and ion_dvoltsz_gu==0)
callbacks.other_actions();ion_time_step=1;callbacks.tstep_adjust();assert(ion_time_step>0)
local function terminate_without_splat_access()
  local previous=ion_splat
  rawset(_G,'ion_splat',nil)
  local old_meta=getmetatable(_G)
  setmetatable(_G,{__index=function(_,key)
    if key=='ion_splat' then error('Read access denied to ion_splat in terminate') end
  end})
  assert(not pcall(function() return ion_splat end),'fixture must deny this reserved variable')
  callbacks.terminate()
  setmetatable(_G,old_meta);rawset(_G,'ion_splat',previous)
end
t=13;callbacks.other_actions();assert(ion_splat==1);terminate_without_splat_access()
assert(rows[#rows].terminal_reason=='observation_window_complete' and rows[#rows].solver_raw_status==nil)
ion_number=2;ion_splat=0;t=9.5;callbacks.initialize()
t=9.75;ion_splat=8;ion_px_mm=0/0;terminate_without_splat_access()
assert(rows[#rows].particle_id==7 and rows[#rows].terminal_reason=='unknown' and rows[#rows].solver_raw_status==nil and rows[#rows].state_present==0)
callbacks.terminate_run()
-- A second Fly resets only run bookkeeping and restores the same source vectors.
callbacks.initialize_run();ion_number=1;t=9.5;ion_splat=0;ion_px_mm=0;callbacks.initialize()
assert(restore_calls==3 and rows[#rows].particle_id==41)
print('PAIRED_ACCELERATOR_PULSE_CALLBACK_FIXTURE=PASS')
