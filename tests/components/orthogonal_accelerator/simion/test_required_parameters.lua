-- Solver-free regression. Run with Lua 5.1+ and the provider source directory.
-- No SIMION process, PA construction, file output, or solver is started.
local directory = assert(arg[1], 'accelerator SIMION source directory is required')
local builder = assert(loadfile(directory .. '/build_two_zone_pa.lua'))
local function reject(arguments, expected)
  arg = arguments
  local ok, message = pcall(builder)
  assert(not ok, 'invalid builder input unexpectedly succeeded')
  assert(tostring(message):find(expected, 1, true), tostring(message))
end
reject({}, 'all 26 accelerator builder arguments are required')
reject({'source.gem','out.pa#'}, 'all 26 accelerator builder arguments are required')
local complete = {'C:/source.gem','C:/out.pa#',1,1,5,5,5,5,4,0,3.5,0,0,0,3,16,5,1,1,1,2240,1760,0,0,0,0}
local names = {'mmgu_xy','mmgu_z','bore_half','ring_width','insulation_gap',
  'rear_gap','shield_wall','vacuum_margin','max_gib','back_domain_margin',
  'front_domain_margin','grid_phase_z','stage1_length','stage2_length',
  'ring_count','repeller_thickness','ring_thickness','front_vacuum_margin',
  'repeller_voltage','grid1_voltage','interface_port_enable',
  'interface_port_width_y','interface_port_height_z','interface_port_center_z'}
for index = 3,26 do
  local values = {}
  for key,value in ipairs(complete) do values[key] = value end
  values[index] = 'not-a-number'
  reject(values, names[index-2] .. ' is required')
end
-- Missing GEM inputs fail before the preprocessor reaches any geometry API.
local file = assert(io.open(directory .. '/two_zone_accelerator.gem','rb'))
local text = file:read('*a'); file:close()
assert(not text:find(' or ',1,true), 'GEM must not supply implicit parameter defaults')
assert(text:find("assert(_G.var",1,true), 'GEM requires the resolved builder parameter table')
print('ACCELERATOR_REQUIRED_PARAMETERS=PASS cases=26')
