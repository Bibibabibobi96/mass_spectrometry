-- Project-built swept straight-segment / closed finite-cylinder contact kernel.
-- This is geometry, not SIMION's voxel collision rule or a curved-trajectory
-- proof. Positions/radii are in the same physical units (normally mm).
-- No radius expansion, mesh padding, vendor API, state mutation or I/O.
local M={}
local abs,sqrt,max,min=math.abs,math.sqrt,math.max,math.min
local EPS=2^-52 -- IEEE-754 binary64 machine epsilon; roundoff only.
local rank={cap_start=1,cap_end=2,side=3,initial_inside=4}

local function finite(value)
 return type(value)=='number' and value==value and abs(value)<math.huge
end

local function vector(value)
 assert(type(value)=='table' and #value==3,'finite xyz vector required')
 for k=1,3 do assert(finite(value[k]),'finite xyz vector required') end
end

local function dot(a,b)
 return a[1]*b[1]+a[2]*b[2]+a[3]*b[3]
end

local function cylinder_contact(shape,start,finish)
 assert(shape.shape=='cylinder3d','finite cylinder3d required')
 local a,b=shape.endpoints_mm[1],shape.endpoints_mm[2]
 vector(a);vector(b)
 local radius=shape.radius_mm
 assert(finite(radius) and radius>0,'positive finite cylinder radius required')
 local axis,d,m={},{},{}
 local scale=radius
 for k=1,3 do
  axis[k]=b[k]-a[k];d[k]=finish[k]-start[k];m[k]=start[k]-a[k]
  scale=max(scale,abs(a[k]),abs(b[k]),abs(start[k]),abs(finish[k]))
 end
 local length=sqrt(dot(axis,axis))
 assert(finite(length) and length>0,'distinct finite cylinder endpoints required')
 local u={axis[1]/length,axis[2]/length,axis[3]/length}
 local z,dz=dot(m,u),dot(d,u)
 local w,v={},{}
 for k=1,3 do w[k]=m[k]-z*u[k];v[k]=d[k]-dz*u[k] end
 local radial2,radius2=dot(w,w),radius*radius
 -- Bounds reflect subtraction/projection and scalar arithmetic at this scale.
 -- They are not an authored clearance and never alter the physical radius.
 local position_error=32*EPS*scale
 local z_error=position_error+32*EPS*max(length,abs(z),abs(dz))
 local radial_error=position_error*(2*sqrt(radial2)+position_error)
                    +32*EPS*(radial2+radius2)
 if radial2-radius2<=radial_error and z>=-z_error and z<=length+z_error then
  if abs(z)<=z_error then return 0,'cap_start' end
  if abs(z-length)<=z_error then return 0,'cap_end' end
  if abs(radial2-radius2)<=radial_error then return 0,'side' end
  return 0,'initial_inside'
 end
 if dot(d,d)==0 then return nil end
 local best,face
 local function accept(t,kind)
  if not finite(t) then return end
  local error=64*EPS*max(1,abs(t))
  if t < -error or t > 1+error then return end
  t=max(0,min(1,t))
  if not best or t<best-error or (abs(t-best)<=error and rank[kind]<rank[face]) then
   best,face=t,kind
  end
 end
 -- Side: |w+t*v|^2=radius^2. The q-form avoids cancellation between roots.
 local aa,bb,cc=dot(v,v),2*dot(w,v),radial2-radius2
 if aa>0 then
  local fourac=4*aa*cc
  local discriminant=bb*bb-fourac
  local disc_error=64*EPS*(bb*bb+abs(fourac))
  if discriminant>=-disc_error then
   discriminant=max(0,discriminant)
   local roots
   if discriminant==0 then roots={-bb/(2*aa)} else
    local q=-.5*(bb+(bb>=0 and 1 or -1)*sqrt(discriminant))
    roots={q/aa,cc/q}
   end
   for _,t in ipairs(roots) do
    local along=z+t*dz
    if along>=-z_error and along<=length+z_error then accept(t,'side') end
   end
  end
 end
 -- Caps are disks, not infinite planes. Parallel segments have no cap roots.
 if dz~=0 then
  for index,cap in ipairs({0,length}) do
   local t=(cap-z)/dz
   local radial={w[1]+t*v[1],w[2]+t*v[2],w[3]+t*v[3]}
   local r2=dot(radial,radial)
   local error=position_error*(2*sqrt(r2)+position_error)+32*EPS*(r2+radius2)
   if r2-radius2<=error then accept(t,index==1 and 'cap_start' or 'cap_end') end
  end
 end
 return best,face
end

-- Return earliest fraction, canonical numeric electrode_id, face; or nil.
-- Boundary contact (including tangency) is included. A strict initial interior
-- returns fraction=0/initial_inside; a boundary start names its cap or side.
-- Roundoff-coincident contacts choose lower ID, then cap_start/cap_end/side.
-- Full canonical rods include negative-x rods: no abs(x) or PA folding here.
function M.first_contact(rods,start,finish)
 assert(type(rods)=='table','canonical rod list required')
 vector(start);vector(finish)
 local best,id,face
 for _,rod in ipairs(rods) do
  assert(rod.namespace=='quadrupole_lens' and finite(rod.electrode_id),
         'canonical quadrupole rod and numeric electrode_id required')
  for _,shape in ipairs(rod.solids) do
   local t,kind=cylinder_contact(shape,start,finish)
   if t then
    local error=64*EPS*max(1,abs(t),abs(best or t))
    if not best or t<best-error or
       (abs(t-best)<=error and (rod.electrode_id<id or
        (rod.electrode_id==id and rank[kind]<rank[face]))) then
     best,id,face=t,rod.electrode_id,kind
    end
   end
  end
 end
 return best,id,face
end

return M
