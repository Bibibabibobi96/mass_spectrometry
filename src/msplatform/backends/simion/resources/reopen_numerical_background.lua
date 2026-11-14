-- Cold-process checker: read only, no save, field solve or flight.
local native_path=assert(loadfile(assert(arg[8],'native path resource required')))()
local path=native_path(assert(arg[1]))
local n={tonumber(arg[2]),tonumber(arg[3]),tonumber(arg[4])}
local d={tonumber(arg[5]),tonumber(arg[6]),tonumber(arg[7])}
for i=1,3 do assert(n[i] and n[i]>=3 and n[i]==math.floor(n[i]) and d[i] and d[i]>0 and d[i]<math.huge,'invalid grid') end
local pa=assert(simion.pas:open(path),'cannot reopen carrier')
assert(pa.nx==n[1] and pa.ny==n[2] and pa.nz==n[3],'cold dimensions differ')
assert(pa.dx_mm==d[1] and pa.dy_mm==d[2] and pa.dz_mm==d[3],'cold pitch differs')
assert(pa.symmetry=='3dplanar' and pa.potential_type=='electric' and pa.refinable==false,'cold PA type differs')
local count=0
for x,y,z in pa:points() do
  local potential,electrode=pa:point(x,y,z)
  assert(potential==0 and electrode==false,'cold point differs');count=count+1
end
assert(count==n[1]*n[2]*n[3],'cold scan incomplete')
pa:close()
print('NUMERICAL_CARRIER_COLD_REOPEN=PASS POINTS='..count..' REFINE=False FLY=False')
