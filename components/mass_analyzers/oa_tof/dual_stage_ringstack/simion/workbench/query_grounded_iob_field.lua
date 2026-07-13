simion.command('"oatof_grounded_tube.iob"')
local wb=simion.wb
for _,p in ipairs({{0,0,1.5},{0,0,10},{0,0,25}}) do
 local ex,ey,ez=wb:efield(p[1],p[2],p[3])
 print(string.format('xyz=(%g,%g,%g) E=(%.8g,%.8g,%.8g)',p[1],p[2],p[3],ex or 0,ey or 0,ez or 0))
end
