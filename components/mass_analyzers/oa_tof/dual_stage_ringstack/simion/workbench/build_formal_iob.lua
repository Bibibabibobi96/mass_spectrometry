simion.command('"template_bender\\bend.iob"')
local wb=simion.wb
local f=[[formal/]]
local r,a,t=wb.instances[1],wb.instances[2],wb.instances[3]
r.pa:fast_adjust{[1]=0,[2]=145.454545,[3]=290.909091,[4]=436.363636,[5]=581.818182,[6]=727.272727,[7]=872.727273,[8]=1018.181818,[9]=1163.636364,[10]=1309.090909,[11]=1454.545455,[12]=1600,[13]=1733.333333,[14]=1866.666667,[15]=2000,[16]=2133.333333,[17]=2266.666667,[18]=2400,[19]=0}
a.pa:fast_adjust{[1]=2240,[2]=1760,[3]=1466.666667,[4]=1173.333333,[5]=880,[6]=586.666667,[7]=293.333333,[8]=0,[9]=0}
t.pa:fast_adjust{[1]=0}
r.pa.filename=f..'reflectron.pa0'
a.pa.filename=f..'accelerator.pa0'
t.pa.filename=f..'flight_tube_ground.pa0'
r.x,r.y,r.z=0,0,619.83; r.az,r.el,r.rt,r.scale=-90,0,0,1
a.x,a.y,a.z=-93.8,-45,-15; a.az,a.el,a.rt,a.scale=0,0,0,1
t.x,t.y,t.z=0,0,19.83; t.az,t.el,t.rt,t.scale=-90,0,0,1
wb:save(f..'oatof_ideal_grounded.iob')
