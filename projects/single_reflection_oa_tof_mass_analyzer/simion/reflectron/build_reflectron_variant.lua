-- Explicit legacy command adapter to the single installed native implementation.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local root=assert(source:match('^(.*)/projects/single_reflection_oa_tof_mass_analyzer/simion/[^/]+/[^/]+%.lua$'))
return assert(loadfile(root..'/src/msplatform/backends/simion/resources/build_reflectron_variant.lua'))()
