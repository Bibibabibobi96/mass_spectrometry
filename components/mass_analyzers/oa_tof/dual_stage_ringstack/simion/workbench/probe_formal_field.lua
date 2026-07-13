simion.command('"formal/oatof_ideal_grounded.iob"')
local a=simion.wb.instances[2].pa
a:fast_adjust{[1]=2240,[2]=1760,[3]=1466.666667,[4]=1173.333333,[5]=880,[6]=586.666667,[7]=293.333333,[8]=0,[9]=0}
for _,p in ipairs({{-48.8,0,1.0},{-48.8,0,1.5},{-48.8,0,2.0},{-48.8,0,3.0},{-48.8,0,10},{0,0,300},{0,0,500},{48.8,0,19.83}}) do
 local ex,ey,ez=simion.wb:efield(p[1],p[2],p[3])
 print(string.format('E at z=%g: %.9g %.9g %.9g',p[3],ex or 0,ey or 0,ez or 0))
end
