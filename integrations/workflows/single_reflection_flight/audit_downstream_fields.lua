-- Legacy loader: the sole implementation is the installed backend resource.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local root=assert(source:match('^(.*)/integrations/workflows/single_reflection_flight/audit_downstream_fields%.lua$'),'legacy SIMION resource requires its frozen source tree')
return assert(loadfile(root..'/src/msplatform/backends/simion/resources/audit_downstream_fields.lua'))()
