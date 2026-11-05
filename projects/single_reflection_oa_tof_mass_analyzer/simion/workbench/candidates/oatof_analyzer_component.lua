-- P3 compatibility loader; remove with remaining project-path consumers by P4.
local path=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local relative='projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/oatof_analyzer_component.lua'
local root=assert((path==relative and '.') or path:match('^(.*)/projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/[^/]+$'), 'frozen repository root unavailable')
return assert(loadfile(root..'/src/msplatform/backends/simion/resources/oatof_analyzer_component.lua'))()
