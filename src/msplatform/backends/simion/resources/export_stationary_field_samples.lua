-- Export one stationary field case from an already solved PA without saving it.
-- The finite3D owner supplies frozen common points, origin, grid and voltages.
local controller=assert(arg[1],'PA0 controller required')
local points_path=assert(arg[2],'common points CSV required')
local output_path=assert(arg[3],'output CSV required')
local field_case=assert(arg[4],'field case required')
assert(field_case=='differential' or field_case=='static','unknown stationary field case')
local function triple(text,label)
  local values={}
  for value in tostring(text or ''):gmatch('[^,]+') do
    values[#values+1]=assert(tonumber(value),label..' is nonnumeric')
  end
  assert(#values==3,label..' requires three values')
  for _,value in ipairs(values) do assert(value==value and math.abs(value)<math.huge,label..' is nonfinite') end
  return values
end
local origin=triple(arg[5],'PA origin')
local cell=triple(arg[6],'PA cell')
assert(cell[1]>0 and cell[2]>0 and cell[3]>0,'PA cell must be positive')
local voltages={}
for index=7,#arg do
  local id_text,value_text=arg[index]:match('^(%d+)=(.*)$')
  assert(id_text,'voltage must be ID=V')
  local id=assert(tonumber(id_text),'electrode ID is nonnumeric')
  local value=assert(tonumber(value_text),'electrode voltage is nonnumeric')
  assert(id>0 and id==math.floor(id) and voltages[id]==nil,'electrode ID is invalid or duplicated')
  assert(value==value and math.abs(value)<math.huge,'electrode voltage is nonfinite')
  voltages[id]=value
end
assert(next(voltages)~=nil,'stationary electrode voltages are required')
local input=assert(io.open(points_path,'r'))
assert(input:read('*l')=='sample_id,region,x_mm,y_mm,z_mm','common points header differs')
local output=assert(io.open(output_path,'w'))
output:write('sample_id,region,field_case,x_mm,y_mm,z_mm,potential_V,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n')
simion.pas:close()
local pa=assert(simion.pas:open(controller),'cannot open solved PA family')
pa:fast_adjust(voltages)
local function split(line)
  local fields={}
  for value in (line..','):gmatch('(.-),') do fields[#fields+1]=value end
  return fields
end
local count=0
for line in input:lines() do
  if line:match('%S') then
    local row=split(line)
    assert(#row==5,'common point row width differs')
    local x,y,z=tonumber(row[3]),tonumber(row[4]),tonumber(row[5])
    assert(x and y and z,'common point coordinate is nonnumeric')
    local gx,gy,gz=(x+origin[1])/cell[1],(y+origin[2])/cell[2],(z+origin[3])/cell[3]
    assert(pa:inside_vc(gx,gy,gz),'stationary sample is outside the solved PA: '..row[1])
    local potential=pa:potential_vc(gx,gy,gz)
    local ex,ey,ez=pa:field_vc(gx,gy,gz)
    for _,value in ipairs({potential,ex,ey,ez}) do
      assert(type(value)=='number' and value==value and math.abs(value)<math.huge,
        'stationary sample is not a finite vacuum observation: '..row[1])
    end
    output:write(string.format('%s,%s,%s,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\n',
      row[1],row[2],field_case,x,y,z,potential,1000*ex/cell[1],1000*ey/cell[2],1000*ez/cell[3]))
    count=count+1
  end
end
assert(count>0,'common points are empty')
pa:close()
input:close()
output:close()
print(string.format('MULTIPOLE_STATIONARY_SAMPLE_EXPORT=PASS case=%s points=%d',field_case,count))
