local source=assert(arg[1], 'GEM input required')
local output=assert(arg[2], 'PA# output required')
_G.var={mmgu=2}
simion.command(string.format('gem2pa %q %q',source,output))
_G.var=nil
local pa=assert(simion.pas:open(output))
local counts={}
for z=0,pa.nz-1 do for y=0,pa.ny-1 do for x=0,pa.nx-1 do
  local potential,electrode=pa:point(x,y,z)
  if electrode then counts[potential]=(counts[potential] or 0)+1 end
end end end
for id=16,20 do print(string.format('PRISM_PROBE id=%d count=%d',id,counts[id] or 0)) end
pa:close()
