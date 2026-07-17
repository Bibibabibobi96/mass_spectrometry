-- Export a common-axis field profile from a grid-phase accelerator candidate.
-- The candidate geometry is shifted inside the PA and the PA instance is moved
-- by the opposite amount, leaving all global mechanical coordinates unchanged.

local iob_path=assert(os.getenv('OATOF_FORMAL_IOB_PATH'))
local pa_path=assert(os.getenv('OATOF_ACCELERATOR_PA_OVERRIDE'))
local output_path=assert(os.getenv('OATOF_SIMION_FIELD_CSV'))
local back_margin=assert(tonumber(os.getenv('OATOF_ACCELERATOR_PA_BACK_MARGIN_MM') or '0'))
local phase=assert(tonumber(os.getenv('OATOF_ACCELERATOR_PA_GRID_PHASE_Z_MM') or '0'))
local accelerator_axis_x=assert(tonumber(os.getenv('OATOF_ACCELERATOR_AXIS_X_MM')))
local accelerator_axis_y=assert(tonumber(os.getenv('OATOF_ACCELERATOR_AXIS_Y_MM')))
local accelerator_instance_z=assert(tonumber(os.getenv('OATOF_ACCELERATOR_INSTANCE_Z_MM')))
local sample_z_start=assert(tonumber(os.getenv('OATOF_ACCELERATOR_SAMPLE_Z_START_MM')))
local sample_z_end=assert(tonumber(os.getenv('OATOF_ACCELERATOR_SAMPLE_Z_END_MM')))
local sample_z_step=0.01
local sample_count=math.floor((sample_z_end-sample_z_start)/sample_z_step+0.5)+1

simion.command('"'..iob_path..'"')
local instance=assert(simion.wb.instances[2], 'accelerator instance is absent')
instance.pa:load(pa_path)
instance:_debug_update_size()
instance.x=accelerator_axis_x-(instance.pa.nx-1)*instance.pa.dx_mm/2
instance.y=accelerator_axis_y-(instance.pa.ny-1)*instance.pa.dy_mm/2
instance.z=accelerator_instance_z-back_margin-phase

local output=assert(io.open(output_path,'w'))
output:write('sample_index,x_mm,y_mm,z_mm,Ez_V_per_m\n')
for index=0,sample_count-1 do
  local z=sample_z_start+sample_z_step*index
  local xg,yg,zg=instance:wb_to_pa_coords(accelerator_axis_x,accelerator_axis_y,z)
  local _,_,ez=instance.pa:field_vc(xg,yg,zg)
  ez=1000*(ez or 0)/instance.pa.dz_mm
  output:write(string.format('%d,%.12g,%.12g,%.12g,%.15g\n',index+1,accelerator_axis_x,accelerator_axis_y,z,ez))
end
output:close()
print(string.format('GRID_PHASE_FIELD: pa=%s dimensions=%dx%dx%d cell=(%.12g,%.12g,%.12g) instance_z=%.12g phase=%.12g back_margin=%.12g',
  pa_path,instance.pa.nx,instance.pa.ny,instance.pa.nz,
  instance.pa.dx_mm,instance.pa.dy_mm,instance.pa.dz_mm,
  instance.z,phase,back_margin))
print('GRID_PHASE_FIELD_STATUS=PASS')
