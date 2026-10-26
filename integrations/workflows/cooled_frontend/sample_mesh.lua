-- One-PA static probe: field plus nearest and interpolation-corner flags.
-- Same argument order and MR/vector units as sample_field.lua; never Fly.
local path=assert(arg[1],'PA required')
local origin={}
for token in assert(arg[2],'MR origin required'):gmatch('[^,]+') do
  origin[#origin+1]=assert(tonumber(token),'numeric origin required')
end
assert(#origin==3,'three origin components required')
simion.pas:close()
local pa=assert(simion.pas:open(path),'cannot open actual PA')
local input=assert(io.open(assert(arg[3],'point CSV required'),'r'))
assert(input:read('*l')=='name,x_mm,y_mm,z_mm','point columns differ')
local output=assert(io.open(assert(arg[4],'output CSV required'),'w'))
output:write('name,x_mm,y_mm,z_mm,potential_v,ex_v_per_mm,ey_v_per_mm,ez_v_per_mm,nearest_electrode_flag,bracket_electrode_count,nearest_grid_x,nearest_grid_y,nearest_grid_z,on_grid_boundary\n')
local count=0
for line in input:lines() do
  if line~='' then
    local name,x,y,z=line:match('^([^,]+),([^,]+),([^,]+),([^,]+)$')
    assert(name,'four point fields required')
    x,y,z=assert(tonumber(x)),assert(tonumber(y)),assert(tonumber(z))
    local gx,gy,gz=(x-origin[1])/pa.dx_mm,(y-origin[2])/pa.dy_mm,(z-origin[3])/pa.dz_mm
    assert(pa:inside_vc(gx,gy,gz),'probe outside actual PA')
    local ix,iy,iz=math.floor(gx+.5),math.floor(gy+.5),math.floor(gz+.5)
    local _,electrode=pa:point(ix,iy,iz)
    local corners=0
    for dx=0,1 do for dy=0,1 do for dz=0,1 do
      local cx,cy,cz=math.floor(gx)+dx,math.floor(gy)+dy,math.floor(gz)+dz
      assert(cx>=0 and cx<pa.nx and cy>=0 and cy<pa.ny and cz>=0 and cz<pa.nz,'probe bracket outside PA')
      local _,flag=pa:point(cx,cy,cz)
      if flag then corners=corners+1 end
    end end end
    local boundary=ix==0 or iy==0 or iz==0 or ix==pa.nx-1 or iy==pa.ny-1 or iz==pa.nz-1
    local ex,ey,ez=pa:field_vc(gx,gy,gz)
    output:write(string.format('%s,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%d,%d,%d,%d,%d,%d\n',
      name,x,y,z,pa:potential_vc(gx,gy,gz),ex/pa.dx_mm,ey/pa.dy_mm,ez/pa.dz_mm,
      electrode and 1 or 0,corners,ix,iy,iz,boundary and 1 or 0))
    count=count+1
  end
end
input:close();output:close();pa:close()
assert(count>0,'no mesh probe samples')
print('COOLED_MESH_PROBE=PASS samples='..count)
