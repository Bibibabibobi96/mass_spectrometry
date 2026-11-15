-- Raw geometry occupancy -> non-refinable collision-only ordinary PA.
-- One admitted owner invokes build then verify in separate native processes.
-- No fields, Refine, Fast Adjust or particle flight are performed here.
-- Usage: MODE SOURCE.pa# NEW.pa NATIVE_PATH_RESOURCE
local mode=assert(arg[1],'mode required')
assert(mode=='build' or mode=='verify','collision mode must be build or verify')
local native_path=assert(loadfile(assert(arg[4],'native path resource required')))()
local source=native_path(assert(arg[2],'raw PA# required'))
local output=native_path(assert(arg[3],'new collision PA required'))
local source_base=assert(source:match('^(.*)%.[pP][aA]#$'),'raw .pa# source required')
local output_base=assert(output:match('^(.*)%.[pP][aA]$'),'ordinary .pa output required')
assert(source_base:lower()~=output_base:lower(),'source and output stems must differ')
local function exists(path)
 local f=io.open(path,'rb');if f then f:close();return true end;return false
end
local function nonempty(path)
 local f=assert(io.open(path,'rb'),'required input missing: '..path);local first=f:read(1);f:close();assert(first~=nil,'required input empty: '..path)
end
nonempty(source)
local empty=false
local state_path=arg[5]
local state_grid=nil
if state_path then
 local state=assert(io.open(native_path(state_path),'rb'),'surface state missing');local text=state:read('*a');state:close()
 local surface_mode,nx,ny,nz,dx,dy,dz,scanned,offsets=text:match('^%s*{%s*"schema_version":1,"mode":"(%a+)","grid":%[(%d+),(%d+),(%d+)%],"pitch":%[([^,]+),([^,]+),([^%]]+)%],"scanned_nodes":([^,]+),"offset_nodes":([^}]+)}%s*$')
 assert(surface_mode=='present' or surface_mode=='empty','invalid surface state')
 state_grid={tonumber(nx),tonumber(ny),tonumber(nz),tonumber(dx),tonumber(dy),tonumber(dz)}
 empty=surface_mode=='empty'
 if empty then assert(tonumber(scanned)==state_grid[1]*state_grid[2]*state_grid[3] and tonumber(offsets)==0,'invalid empty surface proof')
 else assert(scanned=='null' and offsets=='null','present state overclaims scan') end
end
if empty then assert(not exists(source_base..'.pa-surf'),'empty source has unexpected companion') else nonempty(source_base..'.pa-surf') end
for _,suffix in ipairs({'.wgem','.lua','.fly2','.ion','.con','.rec','.pa0'}) do
 assert(not exists(source_base..suffix),'raw geometry companion forbidden: '..suffix)
end
for i=1,1000 do
 assert(not exists(source_base..'.pa'..i),'raw geometry response family forbidden')
 assert(not exists(output_base..'.pa'..i),'collision output response family forbidden')
end
for _,suffix in ipairs({'.wgem','.lua','.fly2','.ion','.con','.rec','.pa0','.pa#'}) do
 assert(not exists(output_base..suffix),'collision output companion forbidden: '..suffix)
end
if mode=='build' then
 assert(not exists(output) and not exists(output_base..'.pa-surf'),'collision destination already exists')
else
 nonempty(output);if empty then assert(not exists(output_base..'.pa-surf'),'empty output has unexpected companion') else nonempty(output_base..'.pa-surf') end
end
simion.pas:close()
local src=assert(simion.pas:open(source),'cannot open raw geometry PA')
assert(src.symmetry=='3dplanar' and src.potential_type=='electric','raw geometry must be 3D planar electric')
local dimensions={src.nx,src.ny,src.nz};local pitch={src.dx_mm,src.dy_mm,src.dz_mm}
if state_grid then for i=1,3 do assert(dimensions[i]==state_grid[i] and pitch[i]==state_grid[i+3],'surface state/grid differs') end end
for i=1,3 do assert(type(dimensions[i])=='number' and dimensions[i]>=3 and dimensions[i]==math.floor(dimensions[i]),'invalid dimensions');assert(type(pitch[i])=='number' and pitch[i]>0 and pitch[i]<math.huge,'invalid pitch') end
local count,metal_count,surface_count=0,0,0
local function finite(x)return type(x)=='number' and x==x and math.abs(x)<math.huge end
local out
if mode=='verify' then out=assert(simion.pas:open(output),'cannot open collision output PA')
else out=assert(simion.pas:open(),'cannot create collision output PA') end
if mode=='build' then
 out:size(unpack(dimensions));out.symmetry=src.symmetry;out.potential_type=src.potential_type
 out.dx_mm,out.dy_mm,out.dz_mm=unpack(pitch);out.refinable=false
else
 assert(out.nx==dimensions[1] and out.ny==dimensions[2] and out.nz==dimensions[3],'collision dimensions differ')
 assert(out.dx_mm==pitch[1] and out.dy_mm==pitch[2] and out.dz_mm==pitch[3],'collision pitch differs')
 assert(out.symmetry==src.symmetry and out.potential_type==src.potential_type and out.refinable==false,'collision type or refinable status differs')
end
for x,y,z in src:points() do
 local value,metal=src:point(x,y,z)
 assert(finite(value) and type(metal)=='boolean','invalid raw node')
 assert(metal or value==0,'raw vacuum must be zero; collision output does not create a field')
 local sx,sy,sz=src:surface_info(x,y,z)
 if sx~=nil or sy~=nil or sz~=nil then surface_count=surface_count+1 end
 if mode=='build' then
  out:point(x,y,z,value,metal)
  if sx~=nil or sy~=nil or sz~=nil then out:surface_info(x,y,z,sx,sy,sz) end
 else
  local actual,actual_metal=out:point(x,y,z)
  assert(actual==value and actual_metal==metal,'collision node value or electrode flag differs')
  local ax,ay,az=out:surface_info(x,y,z)
  assert(ax==sx and ay==sy and az==sz,'collision fractional surface offset differs')
 end
 count=count+1;if metal then metal_count=metal_count+1 end
end
assert(count==dimensions[1]*dimensions[2]*dimensions[3],'collision node traversal count differs')
assert(metal_count>0 and (empty and surface_count==0 or not empty and surface_count>0),'physical metal and fractional surface evidence required')
if mode=='build' then out:save(output) end
out:close();src:close()
nonempty(output);if empty then assert(not exists(output_base..'.pa-surf'),'empty output has unexpected companion') else nonempty(output_base..'.pa-surf') end
print(string.format('RAW_COLLISION_%s=PASS nodes=%d metal_nodes=%d surface_nodes=%d FIELD_STATUS=not_solved REFINE=False FLY=False',mode:upper(),count,metal_count,surface_count))
io.stdout:flush()
