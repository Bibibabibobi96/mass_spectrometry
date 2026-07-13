simion.command('"oatof_ideal_grounded.iob"')
for i=1,#simion.wb.instances do
 local p=simion.wb.instances[i]
 print(string.format('%d %s xyz=(%g,%g,%g) aer=(%g,%g,%g)',i,p.filename,p.x,p.y,p.z,p.az,p.el,p.rt))
end
