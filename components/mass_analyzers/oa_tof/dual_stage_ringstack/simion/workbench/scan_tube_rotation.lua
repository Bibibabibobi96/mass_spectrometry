simion.command('"oatof_grounded_tube.iob"')
local t=simion.wb.instances[3]
local angles={{0,0,0},{0,90,0},{0,-90,0},{90,0,0},{-90,0,0},{0,0,90},{0,0,-90},{90,0,90},{-90,0,90}}
local pts={{0,0,1.5},{0,0,100},{0,0,500},{100,0,19.83},{500,0,19.83},{0,100,19.83}}
for _,a in ipairs(angles) do
 t.az,t.el,t.rt=a[1],a[2],a[3]
 local s={}
 for _,p in ipairs(pts) do
  local ok,v=pcall(function() return t:inside_wc(p[1],p[2],p[3]) end)
  table.insert(s,ok and tostring(v) or 'ERR')
 end
 print(string.format('aer=%g,%g,%g inside=%s',a[1],a[2],a[3],table.concat(s,',')))
end
