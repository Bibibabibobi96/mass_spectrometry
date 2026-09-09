-- Compare two solved PA fields at caller-supplied project-coordinate samples.
-- The optional z reflection lets one symmetric positive-z PA represent the
-- corresponding negative-z device.  Geometry, sample ownership, voltage
-- grouping, and acceptance criteria remain the caller's responsibility.
--
-- Usage:
-- simion --nogui lua compare_pa_fields_at_samples.lua
--   PA_A ORIGIN_A_X,Y,Z PA_B ORIGIN_B_X,Y,Z
--   B_TRANSFORM(identity|reflect_z) INPUT_CSV OUTPUT_CSV

local pa_a_path=assert(arg[1], 'PA A required')
local origin_a_text=assert(arg[2], 'PA A project origin required')
local pa_b_path=assert(arg[3], 'PA B required')
local origin_b_text=assert(arg[4], 'PA B project origin required')
local transform_b=arg[5] or 'identity'
local input_path=assert(arg[6], 'sample CSV required')
local output_path=assert(arg[7], 'output CSV required')
assert(transform_b=='identity' or transform_b=='reflect_z',
  'B transform must be identity or reflect_z')

local function triple(text,label)
  local values={}
  for value in text:gmatch('[^,]+') do
    values[#values+1]=assert(tonumber(value),label..' contains a non-number')
  end
  assert(#values==3,label..' must contain three values')
  return values
end

local function split_csv(line)
  local fields={}
  for value in (line..','):gmatch('(.-),') do fields[#fields+1]=value end
  return fields
end

local origin_a=triple(origin_a_text,'PA A origin')
local origin_b=triple(origin_b_text,'PA B origin')
local pa_a=assert(simion.pas:open(pa_a_path),'cannot open PA A')
local pa_b=assert(simion.pas:open(pa_b_path),'cannot open PA B')
assert(pa_a.dx_mm>0 and pa_a.dy_mm>0 and pa_a.dz_mm>0,'PA A scale must be positive')
assert(pa_b.dx_mm>0 and pa_b.dy_mm>0 and pa_b.dz_mm>0,'PA B scale must be positive')

local function sample(pa,origin,project,reflect_z)
  local mapped={project[1],project[2],reflect_z and -project[3] or project[3]}
  local coordinates={
    (mapped[1]-origin[1])/pa.dx_mm,
    (mapped[2]-origin[2])/pa.dy_mm,
    (mapped[3]-origin[3])/pa.dz_mm,
  }
  assert(pa:inside_vc(coordinates[1],coordinates[2],coordinates[3]),
    'sample lies outside PA')
  local potential=pa:potential_vc(coordinates[1],coordinates[2],coordinates[3])
  local ex,ey,ez=pa:field_vc(coordinates[1],coordinates[2],coordinates[3])
  local field={
    (ex or 0)/pa.dx_mm,
    (ey or 0)/pa.dy_mm,
    (ez or 0)/pa.dz_mm,
  }
  if reflect_z then field[3]=-field[3] end
  return potential,field
end

local input=assert(io.open(input_path,'r'))
local header=assert(input:read('*l'),'sample CSV is empty')
assert(header=='name,x_mm,y_mm,z_mm','sample CSV header differs')
local output=assert(io.open(output_path,'w'))
output:write('name,x_mm,y_mm,z_mm,potential_a_V,potential_b_V,delta_potential_V,',
  'ex_a_V_per_mm,ey_a_V_per_mm,ez_a_V_per_mm,',
  'ex_b_V_per_mm,ey_b_V_per_mm,ez_b_V_per_mm,',
  'delta_ex_V_per_mm,delta_ey_V_per_mm,delta_ez_V_per_mm\n')
local count=0
for line in input:lines() do
  if line~='' then
    local fields=split_csv(line)
    assert(#fields==4,'sample CSV row must contain four fields')
    local project={
      assert(tonumber(fields[2]),'sample x must be numeric'),
      assert(tonumber(fields[3]),'sample y must be numeric'),
      assert(tonumber(fields[4]),'sample z must be numeric'),
    }
    local potential_a,field_a=sample(pa_a,origin_a,project,false)
    local potential_b,field_b=sample(pa_b,origin_b,project,transform_b=='reflect_z')
    output:write(string.format(
      '%s,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g\n',
      fields[1],project[1],project[2],project[3],potential_a,potential_b,
      potential_a-potential_b,field_a[1],field_a[2],field_a[3],
      field_b[1],field_b[2],field_b[3],field_a[1]-field_b[1],
      field_a[2]-field_b[2],field_a[3]-field_b[3]))
    count=count+1
  end
end
input:close();output:close();pa_a:close();pa_b:close()
assert(count>0,'sample CSV contains no samples')
print(string.format('PA_FIELD_SAMPLE_COMPARISON=PASS samples=%d transform_b=%s output=%s',
  count,transform_b,output_path))
