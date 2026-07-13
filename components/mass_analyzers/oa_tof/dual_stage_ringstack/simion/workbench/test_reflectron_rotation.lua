simion.command('"oatof_grounded_tube.iob"')
local r = simion.wb.instances[1]
local angles = {
 {0,0,0},{0,90,0},{90,0,0},{-90,0,0},{0,-90,0},{90,90,0},
 {0,0,90},{0,0,-90},{90,0,90},{-90,0,90},{0,90,90},{0,-90,90}
}
for _,a in ipairs(angles) do
  r.az,r.el,r.rt=a[1],a[2],a[3]
  local ex,ey,ez=simion.wb:efield(0,0,630)
  print(string.format('az=%g el=%g rt=%g -> Ex=%.6g Ey=%.6g Ez=%.6g',a[1],a[2],a[3],ex or 0,ey or 0,ez or 0))
end
