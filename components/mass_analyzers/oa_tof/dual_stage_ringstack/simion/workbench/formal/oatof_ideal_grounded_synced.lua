-- HISTORICAL ONLY: legacy three-PA/virtual-detector validation script.
-- Do not use as the formal GUI model. Use oatof_ideal_grounded.iob and its
-- same-name oatof_ideal_grounded.lua, which contain the physical detector PA.
simion.workbench_program()
adjustable V_repeller=2240
adjustable V_grid1=1760
adjustable V_mid=1600
adjustable V_backplate=2400
adjustable ideal_grid_epsilon_mm=0.005
adjustable detector_x_mm=48.8
adjustable detector_y_mm=0
adjustable detector_z_mm=19.83
adjustable detector_radius_mm=25
adjustable diagnostic_return_plane_z_mm=20.5
adjustable diagnostic_max_tof_us=35
adjustable trajectory_log_enable=1
adjustable trajectory_log_stride=1000
adjustable accelerator_instance_x_mm=-93.8
adjustable accelerator_instance_y_mm=-45
adjustable accelerator_instance_z_mm=-15
function segment.initialize_run()
 local r,a,t=simion.wb.instances[1].pa,simion.wb.instances[2].pa,simion.wb.instances[3].pa
 local ai=simion.wb.instances[2]
 ai.x,ai.y,ai.z=accelerator_instance_x_mm,accelerator_instance_y_mm,accelerator_instance_z_mm
 a:fast_adjust{[1]=V_repeller,[2]=V_grid1,[3]=V_grid1*5/6,[4]=V_grid1*4/6,[5]=V_grid1/2,[6]=V_grid1*2/6,[7]=V_grid1/6,[8]=0,[9]=0}
 r:fast_adjust{[1]=0,[2]=V_mid/11,[3]=2*V_mid/11,[4]=3*V_mid/11,[5]=4*V_mid/11,[6]=5*V_mid/11,[7]=6*V_mid/11,[8]=7*V_mid/11,[9]=8*V_mid/11,[10]=9*V_mid/11,[11]=10*V_mid/11,[12]=V_mid,[13]=V_mid+(V_backplate-V_mid)/6,[14]=V_mid+2*(V_backplate-V_mid)/6,[15]=V_mid+3*(V_backplate-V_mid)/6,[16]=V_mid+4*(V_backplate-V_mid)/6,[17]=V_mid+5*(V_backplate-V_mid)/6,[18]=V_backplate,[19]=0}
 t:fast_adjust{[1]=0}
end
local grids={{name='grid1',z=3},{name='grid2',z=19.83},{name='entgrid',z=619.83},{name='midgrid',z=739.83}}
local last_z,jumped={},{}
local diagnostic_plane_hit={}
local detector_crossed={}
local grid_jump_count={}
local TP=simion.import 'testplanelib.lua'
local detector_plane=TP(detector_x_mm,detector_y_mm,detector_z_mm,0,0,1,function()
 if ion_vz_mm<0 then
  local dx,dy=ion_px_mm-detector_x_mm,ion_py_mm-detector_y_mm
  print(string.format('TRACE: detector_plane t=%.12g x=%.12g y=%.12g r=%.12g',ion_time_of_flight,ion_px_mm,ion_py_mm,math.sqrt(dx*dx+dy*dy)))
  if dx*dx+dy*dy<=detector_radius_mm*detector_radius_mm then ion_splat=1; print('TRACE: detector_hit') end
 end
end)
detector_plane.draw(1)
local step_count={}
function segment.initialize()
 last_z[ion_number]=ion_pz_mm; step_count[ion_number]=0; diagnostic_plane_hit[ion_number]=false; detector_crossed[ion_number]=false; grid_jump_count[ion_number]={}
 if trajectory_log_enable~=0 then print('TRACE: ion,t_us,x_mm,y_mm,z_mm,vx_mm_us,vy_mm_us,vz_mm_us,instance,event') end
end
function segment.other_actions()
 local n,z,vz=ion_number,ion_pz_mm,ion_vz_mm
 local zp,eps=last_z[n] or z,ideal_grid_epsilon_mm
 step_count[n]=(step_count[n] or 0)+1
 if trajectory_log_enable~=0 and step_count[n]%math.max(1,trajectory_log_stride)==0 then
  print(string.format('TRACE: %d,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%.12g,%d,step',n,ion_time_of_flight,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,ion_vy_mm,ion_vz_mm,ion_instance))
 end
 if not diagnostic_plane_hit[n] and zp>diagnostic_return_plane_z_mm and z<=diagnostic_return_plane_z_mm and vz<0 then
  diagnostic_plane_hit[n]=true
  print(string.format('TRACE: diagnostic_return_plane t=%.12g x=%.12g y=%.12g z=%.12g vz=%.12g',ion_time_of_flight,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vz_mm))
 end
 if not detector_crossed[n] and zp>detector_z_mm and z<=detector_z_mm and vz<0 then
  detector_crossed[n]=true
  local dt=(detector_z_mm-z)/vz
  local xc=ion_px_mm+ion_vx_mm*dt
  local yc=ion_py_mm+ion_vy_mm*dt
  local dx,dy=xc-detector_x_mm,yc-detector_y_mm
  print(string.format('TRACE: detector_crossing t=%.12g x=%.12g y=%.12g z=%.12g r=%.12g',ion_time_of_flight+dt,xc,yc,detector_z_mm,math.sqrt(dx*dx+dy*dy)))
  if dx*dx+dy*dy<=detector_radius_mm*detector_radius_mm then ion_splat=1; print('TRACE: detector_hit_interpolated') end
 end
 for _,g in ipairs(grids) do
  local k=tostring(n)..':'..g.name; local d=vz>=0 and 1 or -1
  local pre,post=g.z-d*eps,g.z+d*eps
  if jumped[k] and math.abs(z-g.z)>4*eps then jumped[k]=nil end
  if not jumped[k] and ((d>0 and zp<pre and z>=pre) or (d<0 and zp>pre and z<=pre)) then
   if math.abs(vz)<1e-12 then error('grid jump with zero axial velocity') end
   ion_time_of_flight=ion_time_of_flight+math.abs(post-z)/math.abs(vz)
   if g.name=='grid2' and d<0 and not detector_crossed[n] and post<detector_z_mm and detector_z_mm<=pre then
    detector_crossed[n]=true
    local dt_to_post=(post-detector_z_mm)/vz
    local xc=ion_px_mm-ion_vx_mm*dt_to_post
    local yc=ion_py_mm-ion_vy_mm*dt_to_post
    local dx,dy=xc-detector_x_mm,yc-detector_y_mm
    print(string.format('TRACE: detector_crossing t=%.12g x=%.12g y=%.12g z=%.12g r=%.12g',ion_time_of_flight-dt_to_post,xc,yc,detector_z_mm,math.sqrt(dx*dx+dy*dy)))
    if dx*dx+dy*dy<=detector_radius_mm*detector_radius_mm then
     ion_splat=1
     local gc=grid_jump_count[n] or {}
     print(string.format('TRACE: detector_hit_interpolated jumps grid1=%d grid2=%d entgrid=%d midgrid=%d',gc.grid1 or 0,gc.grid2 or 0,gc.entgrid or 0,gc.midgrid or 0))
    end
   end
   grid_jump_count[n]=grid_jump_count[n] or {}
   grid_jump_count[n][g.name]=(grid_jump_count[n][g.name] or 0)+1
   ion_pz_mm=post; jumped[k]=true; break
  end
 end
 last_z[n]=ion_pz_mm
 detector_plane.other_actions()
 if ion_time_of_flight>=diagnostic_max_tof_us then ion_splat=1; print('TRACE: timeout') end
end
function segment.tstep_adjust() detector_plane.tstep_adjust() end
