-- Export the total workbench field along a frozen C3 accelerator axis.
-- This intentionally uses SIMION's documented workbench-level API rather
-- than a single PA's local field, so a five-instance overlay IOB is sampled
-- as the particle engine sees it.  It is an exporter only: no trajectory is
-- launched and no pulse time is selected here.
local output_path=assert(os.getenv('OATOF_TOTAL_AXIS_FIELD_CSV'),
  'OATOF_TOTAL_AXIS_FIELD_CSV is not set')
local iob_path=assert(os.getenv('OATOF_TOTAL_AXIS_FIELD_IOB'),
  'OATOF_TOTAL_AXIS_FIELD_IOB is not set')
local program_path=assert(os.getenv('OATOF_TOTAL_AXIS_FIELD_PROGRAM'),
  'OATOF_TOTAL_AXIS_FIELD_PROGRAM is not set')
local pulse_time=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_PULSE_TIME_US')),
  'OATOF_TOTAL_AXIS_FIELD_PULSE_TIME_US is not set')
local expected_instances=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_EXPECTED_INSTANCES')),
  'OATOF_TOTAL_AXIS_FIELD_EXPECTED_INSTANCES is not set')
local axis_x=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_X_MM')),
  'OATOF_TOTAL_AXIS_FIELD_X_MM is not set')
local axis_y=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_Y_MM')),
  'OATOF_TOTAL_AXIS_FIELD_Y_MM is not set')
local z_start=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_Z_START_MM')),
  'OATOF_TOTAL_AXIS_FIELD_Z_START_MM is not set')
local z_end=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_Z_END_MM')),
  'OATOF_TOTAL_AXIS_FIELD_Z_END_MM is not set')
local z_step=assert(tonumber(os.getenv('OATOF_TOTAL_AXIS_FIELD_Z_STEP_MM')),
  'OATOF_TOTAL_AXIS_FIELD_Z_STEP_MM is not set')
assert(z_step>0 and z_end>=z_start,'axis interval is invalid')

simion.command('"'..iob_path..'"')
assert(#simion.wb.instances==expected_instances,
  'workbench instance count differs from frozen C3 runtime')
-- The IOB contains PA bases, not the C3 candidate's fast-adjusted voltages.
-- Load the exact frozen Program and apply its normal initialize/fast-adjust
-- callbacks at the frozen pulse time before querying the workbench field.
dofile(program_path)
assert(type(segment)=='table' and type(segment.initialize_run)=='function' and
  type(segment.fast_adjust)=='function',
  'frozen single-flight Program lacks required field-initialization callbacks')
segment.initialize_run()
ion_time_of_flight=pulse_time
ion_instance=3
segment.fast_adjust()
ion_instance=5
segment.fast_adjust()
local output=assert(io.open(output_path,'w'))
output:write('sample_index,x_mm,y_mm,z_mm,potential_V,Ex_V_per_mm,Ey_V_per_mm,Ez_V_per_mm\n')
local count=math.floor((z_end-z_start)/z_step+1e-9)+1
for index=1,count do
  local z=z_start+(index-1)*z_step
  local potential=simion.wb:epotential(axis_x,axis_y,z)
  local ex,ey,ez=simion.wb:efield(axis_x,axis_y,z)
  assert(potential and ex and ey and ez,'workbench field is undefined on requested axis')
  output:write(string.format('%d,%.12g,%.12g,%.12g,%.15g,%.15g,%.15g,%.15g\n',
    index,axis_x,axis_y,z,potential,ex,ey,ez))
end
output:close()
print(string.format('TOTAL_AXIS_FIELD=PASS INSTANCES=%d POINTS=%d',#simion.wb.instances,count))
