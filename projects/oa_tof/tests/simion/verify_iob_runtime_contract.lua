local report_path=assert(os.getenv('OATOF_SIMION_IOB_REPORT'),
  'OATOF_SIMION_IOB_REPORT is not set')
local iob_path=assert(os.getenv('OATOF_SIMION_IOB_PATH'),
  'OATOF_SIMION_IOB_PATH is not set')
local expected_quality=tonumber(os.getenv('OATOF_SIMION_EXPECTED_QUALITY') or '8')
local expected_instances=tonumber(os.getenv('OATOF_SIMION_EXPECTED_INSTANCES') or '4')
local program_report_path=assert(os.getenv('OATOF_SIMION_PROGRAM_LOAD_REPORT'),
  'OATOF_SIMION_PROGRAM_LOAD_REPORT is not set')

local report=assert(io.open(report_path,'w'))
local function record(fmt,...)
  local line=string.format(fmt,...)
  report:write(line,'\n')
end

simion.command('"'..iob_path..'"')
assert(#simion.wb.instances==expected_instances,
  string.format('IOB instance count mismatch: actual=%d expected=%d',
    #simion.wb.instances,expected_instances))
local expected_order={
  'flight_tube_ground%.pa0$',
  'reflectron%.pa0$',
  'accelerator%.pa0$',
  'detector_ground%.pa0$',
}
for index,pattern in ipairs(expected_order) do
  local filename=simion.wb.instances[index].filename
  assert(filename:match(pattern),
    string.format('unsafe PA priority at instance %d: %s',index,filename))
  record('INSTANCE_%d=%s',index,filename)
end
local program_report_file=assert(io.open(program_report_path,'r'),
  'Program segment.load report was not created; Program may be disabled')
local program_report=program_report_file:read('*a')
program_report_file:close()
local actual_quality=tonumber(program_report:match('TRAJECTORY_QUALITY=([-+0-9.eE]+)'))
assert(program_report:match('STATUS=PASS') and actual_quality==expected_quality,
  string.format('trajectory quality mismatch after IOB load: actual=%s expected=%s',
    tostring(actual_quality),tostring(expected_quality)))

record('IOB_PATH=%s',iob_path)
record('INSTANCE_COUNT=%d',#simion.wb.instances)
record('TRAJECTORY_QUALITY=%g',actual_quality)
record('STATUS=PASS')
report:close()
