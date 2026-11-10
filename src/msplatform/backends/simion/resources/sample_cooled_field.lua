-- Sample one solved ordinary PA at explicit MR-coordinate points, without Fly.
-- Usage: simion --nogui lua sample_field.lua PA_PATH ORIGIN_X,Y,Z INPUT_CSV OUTPUT_CSV
local path=assert(arg[1],'solved PA required')
local origin={}
for token in assert(arg[2],'MR origin required'):gmatch('[^,]+') do
  origin[#origin+1]=assert(tonumber(token),'numeric origin required')
end
assert(#origin==3,'three origin components required')
local pa=assert(simion.pas:open(path),'cannot open solved PA')
assert(pa.dx_mm>0 and pa.dy_mm>0 and pa.dz_mm>0,'positive PA pitch required')
local input=assert(io.open(assert(arg[3],'point CSV required'),'r'))
assert(input:read('*l')=='name,x_mm,y_mm,z_mm','point columns differ')
local output=assert(io.open(assert(arg[4],'output CSV required'),'w'))
output:write('name,x_mm,y_mm,z_mm,potential_v,ex_v_per_mm,ey_v_per_mm,ez_v_per_mm\n')
local count=0
for line in input:lines() do
  if line~='' then
    local name,x,y,z=line:match('^([^,]+),([^,]+),([^,]+),([^,]+)$')
    assert(name,'four point fields required')
    x,y,z=assert(tonumber(x)),assert(tonumber(y)),assert(tonumber(z))
    local gx,gy,gz=(x-origin[1])/pa.dx_mm,(y-origin[2])/pa.dy_mm,(z-origin[3])/pa.dz_mm
    assert(pa:inside_vc(gx,gy,gz),'probe lies outside actual PA')
    local potential=pa:potential_vc(gx,gy,gz)
    local ex,ey,ez=pa:field_vc(gx,gy,gz)
    output:write(string.format('%s,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\n',
      name,x,y,z,potential,ex/pa.dx_mm,ey/pa.dy_mm,ez/pa.dz_mm))
    count=count+1
  end
end
input:close();output:close();pa:close()
assert(count>0,'no field samples')
print('COOLED_FIELD_PROBE=PASS samples='..count)
