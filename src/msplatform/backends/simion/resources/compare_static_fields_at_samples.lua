-- Long-term verification consumer of the actual flight scalar-field adapter.
-- Compile the request with static_field_binding.py's existing CLI, then:
-- simion --nogui lua compare_static_fields_at_samples.lua REQUEST.lua
-- Outputs the common/simion/field_comparison.py protocol; delta = A - B.
-- No trajectory, PA writes, independent interpolator, or accuracy qualification.
local request=assert(loadfile(assert(arg[1],'sampling request required')))()
assert(request.schema_version==1 and type(request.samples)=='table' and #request.samples>0,
  'invalid scalar sampling request')
local adapter=assert(loadfile(assert(request.adapter,'scalar adapter required')))()
local a,b=adapter(assert(request.a),'raw_sample'),adapter(assert(request.b),'raw_sample')
local output=assert(io.open(assert(request.output_csv),'w'))
output:write('name,x_mm,y_mm,z_mm,potential_a_V,potential_b_V,delta_potential_V,',
  'ex_a_V_per_mm,ey_a_V_per_mm,ez_a_V_per_mm,',
  'ex_b_V_per_mm,ey_b_V_per_mm,ez_b_V_per_mm,',
  'delta_ex_V_per_mm,delta_ey_V_per_mm,delta_ez_V_per_mm\n')
for _,sample in ipairs(request.samples) do
  local xyz=sample.position_mm
  assert(type(sample.name)=='string' and sample.name~='' and not sample.name:find('[,"\r\n]')
    and type(xyz)=='table' and #xyz==3,'invalid sampling row')
  for _,value in ipairs(xyz) do
    assert(type(value)=='number' and value==value and math.abs(value)<math.huge,'nonfinite coordinate')
  end
  local va,ax,ay,az=a(unpack(xyz))
  local vb,bx,by,bz=b(unpack(xyz))
  local values={xyz[1],xyz[2],xyz[3],va,vb,va-vb,ax,ay,az,bx,by,bz,ax-bx,ay-by,az-bz}
  assert(#values==15,'field query returned missing values')
  for index,value in ipairs(values) do
    assert(type(value)=='number' and value==value and math.abs(value)<math.huge,'nonfinite sampled field')
    values[index]=string.format('%.17g',value)
  end
  output:write(sample.name,',',table.concat(values,','),'\n')
end
output:close()
print('STATIC_FIELD_SAMPLE_COMPARISON=PASS samples='..#request.samples..' output='..request.output_csv)
