simion.command('"oatof_ideal_grounded.iob"')
local wb=simion.wb
local a=wb.instances[2]
a.pa.filename='accelerator.pa0'
a.x,a.y,a.z=-68.8,-20,-15
a.az,a.el,a.rt,a.scale=0,0,0,1
wb:save('oatof_ideal_grounded_synced.iob')
print('saved synchronized IOB')
