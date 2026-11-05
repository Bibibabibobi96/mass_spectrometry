-- Legacy source/frozen-tree adapter; implementation is the canonical resource.
local source=assert(debug.getinfo(1,'S').source,'native path adapter source missing')
assert(source:sub(1,1)=='@','native path adapter requires a file source')
local directory=assert(source:sub(2):gsub('\\','/'):match('^(.*)/[^/]+$'),
  'native path adapter directory missing')
return assert(loadfile(directory..'/../../src/msplatform/execution/resources/native_run_path.lua'))()
