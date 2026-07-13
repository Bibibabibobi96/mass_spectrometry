simion.command('"formal/oatof_ideal_grounded.iob"')
local wb=simion.wb
local a=wb.instances[2]
a.x,a.y,a.z=-62.8,-14,-15
wb:save([[formal/oatof_ideal_grounded.iob]])
print('updated accelerator origin to -62.8,-14,-15 mm')
