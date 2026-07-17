-- Export a common-axis field profile from a grid-phase accelerator candidate.
-- The candidate geometry is shifted inside the PA and the PA instance is moved
-- by the opposite amount, leaving all global mechanical coordinates unchanged.

local iob_path=assert(os.getenv('OATOF_FORMAL_IOB_PATH'))
local pa_path=assert(os.getenv('OATOF_ACCELERATOR_PA_OVERRIDE'))
local output_path=assert(os.getenv('OATOF_SIMION_FIELD_CSV'))
local back_margin=assert(tonumber(os.getenv('OATOF_ACCELERATOR_PA_BACK_MARGIN_MM') or '0'))
local phase=assert(tonumber(os.getenv('OATOF_ACCELERATOR_PA_GRID_PHASE_Z_MM') or '0'))

simion.command('"'..iob_path..'"')
local instance=assert(simion.wb.instances[2], 'accelerator instance is absent')
instance.pa:load(pa_path)
instance:_debug_update_size()
instance.x=-48.8-(instance.pa.nx-1)*instance.pa.dx_mm/2
instance.y=-(instance.pa.ny-1)*instance.pa.dy_mm/2
instance.z=-10-back_margin-phase

local output=assert(io.open(output_path,'w'))
output:write('sample_index,x_mm,y_mm,z_mm,Ez_V_per_m\n')
for index=0,1940 do
  local z=0.2+0.01*index
  local xg,yg,zg=instance:wb_to_pa_coords(-48.8,0,z)
  local _,_,ez=instance.pa:field_vc(xg,yg,zg)
  ez=1000*(ez or 0)/instance.pa.dz_mm
  output:write(string.format('%d,-48.8,0,%.12g,%.15g\n',index+1,z,ez))
end
output:close()
print(string.format('GRID_PHASE_FIELD: pa=%s dimensions=%dx%dx%d cell=(%.12g,%.12g,%.12g) instance_z=%.12g phase=%.12g back_margin=%.12g',
  pa_path,instance.pa.nx,instance.pa.ny,instance.pa.nz,
  instance.pa.dx_mm,instance.pa.dy_mm,instance.pa.dz_mm,
  instance.z,phase,back_margin))
print('GRID_PHASE_FIELD_STATUS=PASS')
