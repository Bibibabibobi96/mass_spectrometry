simion.command('"oatof_ideal_grounded.iob"')
local wb=simion.wb
local a=wb.instances[2]
a.pa.filename='accelerator.pa0'
a.az,a.el,a.rt,a.scale=0,0,0,1
local accelerator_axis_x_mm=-48.8
local accelerator_axis_y_mm=0
local accelerator_instance_z_mm=-15
local half_x=(a.pa.nx-1)*a.pa.dx_mm*a.scale/2
local half_y=(a.pa.ny-1)*a.pa.dy_mm*a.scale/2
a.x=accelerator_axis_x_mm-half_x
a.y=accelerator_axis_y_mm-half_y
a.z=accelerator_instance_z_mm
wb:save('oatof_ideal_grounded.iob')
print(string.format('saved synchronized formal IOB: cell=(%.12g,%.12g,%.12g) origin=(%.12g,%.12g,%.12g)',a.pa.dx_mm,a.pa.dy_mm,a.pa.dz_mm,a.x,a.y,a.z))
