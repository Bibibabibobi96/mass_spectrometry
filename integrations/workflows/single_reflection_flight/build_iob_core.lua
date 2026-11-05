-- Legacy bridge to the one geometry/field workbench implementation.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local root=assert(source:match('^(.*)/integrations/workflows/single_reflection_flight/build_iob_core%.lua$'))
return assert(loadfile(root..'/src/msplatform/backends/simion/resources/iob_core.lua'))()
