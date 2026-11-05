-- Legacy source/frozen-tree adapter; sole body is the installed backend resource.
local source=assert(debug.getinfo(1,'S').source,'resource adapter source missing')
assert(source:sub(1,1)=='@','resource adapter requires a file source')
local directory=assert(source:sub(2):gsub('\\','/'):match('^(.*)/[^/]+$'),'resource directory missing')
return assert(loadfile(directory..'/../../src/msplatform/backends/simion/resources/single_flight_pulse_hook.lua'))()
