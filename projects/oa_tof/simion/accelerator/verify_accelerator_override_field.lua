-- Load an already fast-adjusted accelerator PA0 into the formal workbench and
-- report the cross-solver field checkpoints without saving or changing the IOB.
-- Run from the formal workbench directory with OATOF_ACCELERATOR_PA_OVERRIDE.

local path=assert(os.getenv('OATOF_ACCELERATOR_PA_OVERRIDE'),
  'OATOF_ACCELERATOR_PA_OVERRIDE is not set')
simion.command('"oatof_ideal_grounded.iob"')
local wb=simion.wb
local a=wb.instances[2]
a.pa:load(path)
a:_debug_update_size()
local axis_x,axis_y,z0=-48.8,0,-15
a.x=axis_x-(a.pa.nx-1)*a.pa.dx_mm*a.scale/2
a.y=axis_y-(a.pa.ny-1)*a.pa.dy_mm*a.scale/2
a.z=z0
print(string.format('PA=%dx%dx%d,%.12g,%.12g,%.12g',
  a.pa.nx,a.pa.ny,a.pa.nz,a.pa.dx_mm,a.pa.dy_mm,a.pa.dz_mm))
print(string.format('ORIGIN=%.12g,%.12g,%.12g',a.x,a.y,a.z))
local points={{'src_1p5',1.5},{'src_10',10},{'src_19',19}}
for _,p in ipairs(points) do
 local ex,ey,ez=wb:efield(axis_x,axis_y,p[2])
 print(string.format('FIELD_%s_E_V_PER_MM=%.15g,%.15g,%.15g',p[1],ex or 0,ey or 0,ez or 0))
end
print('OVERRIDE_FIELD_STATUS=PASS')
