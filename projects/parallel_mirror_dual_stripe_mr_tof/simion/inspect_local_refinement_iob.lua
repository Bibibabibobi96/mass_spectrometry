-- Reload and inspect the eight-instance local-replacement Workbench.
-- Usage: ... IOB REPORT (X Y Z DX DY DZ)*8
local offset=(arg[1]=='--') and 1 or 0
local function input(index,label)
  local value=assert(arg[index+offset],label..' required')
  return value
end
local iob=input(1,'IOB')
local report_path=input(2,'report')
local expected={}
for index=1,8 do
  expected[index]={}
  for field=1,6 do
    expected[index][field]=assert(tonumber(input(2+(index-1)*6+field,
      string.format('instance %d expected field %d',index,field))),'expected value must be numeric')
  end
end
local wb=assert(simion.wb,'SIMION Workbench API unavailable')
wb:load(iob)
assert(#wb.instances==8,'local-refinement IOB must contain exactly eight instances')
local patterns={
  'mrtof_analyzer%.pa0$', 'local_negative_mirror%.pa0$', 'local_negative_bridge%.pa0$',
  'local_central%.pa0$', 'local_positive_bridge%.pa0$', 'local_positive_mirror%.pa0$',
  'mrtof_accelerator%.pa0$', 'mrtof_detector%.pa#$'
}
local lines={}
for index=1,#wb.instances do
  local instance=wb.instances[index]
  assert(instance.filename:match(patterns[index]),string.format('instance %d role mismatch',index))
  local values={instance.x,instance.y,instance.z,instance.pa.dx_mm,instance.pa.dy_mm,instance.pa.dz_mm}
  for field,value in ipairs(values) do
    assert(math.abs(value-expected[index][field])<1e-9,
      string.format('instance %d field %d mismatch: %.12g versus %.12g',index,field,value,expected[index][field]))
  end
  assert(instance.az==0 and instance.el==0 and instance.rt==0 and instance.scale==1,
    string.format('instance %d must use identity orientation and unit scale',index))
  lines[#lines+1]=string.format('INSTANCE=%d PA=%s ORIGIN_MM=%.12g,%.12g,%.12g MESH_MM=%.12g,%.12g,%.12g',
    index,instance.filename,values[1],values[2],values[3],values[4],values[5],values[6])
end
lines[#lines+1]='STATUS=PASS'
local report=assert(io.open(report_path,'wb')); report:write(table.concat(lines,'\n'),'\n'); report:close()
print('MRTOF_LOCAL_REFINEMENT_IOB_INSPECTION=PASS instances=8')
