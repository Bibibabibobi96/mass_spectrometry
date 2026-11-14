-- Explicit numerical background: output path, nx ny nz, dx dy dz, native path resource.
-- Destination must be fresh and private; owner performs path and lifecycle guards.
local native_path=assert(loadfile(assert(arg[8],'native path resource required')))()
local path=native_path(assert(arg[1]))
assert(not io.open(path,'rb'),'carrier output already exists')
local n={tonumber(arg[2]),tonumber(arg[3]),tonumber(arg[4])}
local d={tonumber(arg[5]),tonumber(arg[6]),tonumber(arg[7])}
for i=1,3 do
  assert(n[i] and n[i]>=3 and n[i]==math.floor(n[i]),'invalid grid count')
  assert(d[i] and d[i]>0 and d[i]<math.huge,'invalid pitch')
end
local pa=assert(simion.pas:open()); pa:size(n[1],n[2],n[3])
pa.symmetry='3dplanar'; pa.potential_type='electric'; pa.refinable=false
pa.dx_mm,pa.dy_mm,pa.dz_mm=d[1],d[2],d[3]
for x,y,z in pa:points() do pa:point(x,y,z,0,false) end
pa:save(path); pa:close()
local check=assert(simion.pas:open(path))
assert(check.nx==n[1] and check.ny==n[2] and check.nz==n[3],'reopened dimensions differ')
assert(check.dx_mm==d[1] and check.dy_mm==d[2] and check.dz_mm==d[3],'reopened pitch differs')
assert(check.symmetry=='3dplanar' and check.potential_type=='electric' and check.refinable==false,'reopened PA type differs')
local count=0
for x,y,z in check:points() do
  local value,metal=check:point(x,y,z)
  assert(value==0 and metal==false,'carrier point differs'); count=count+1
end
assert(count==n[1]*n[2]*n[3],'incomplete point scan')
check:close(); print('NUMERICAL_CARRIER_REOPEN=PASS POINTS='..count..' REFINE=False FLY=False')
