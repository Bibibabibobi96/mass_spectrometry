-- Legacy loader: the sole implementation is the installed backend resource.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local root=assert(source:match('^(.*)/common/simion/build_dirichlet_patch_operating_pa%.lua$'),'legacy SIMION resource requires its frozen source tree')
return assert(loadfile(root..'/src/msplatform/backends/simion/resources/build_dirichlet_patch_operating_pa.lua'))()
