-- Installed workbench transport; no author-repository path discovery.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local directory=assert(source:match('^(.*)/'))
local native_path=assert(loadfile(assert(arg[3],'public native path resource required')))()
local spec=dofile(native_path(assert(arg[1],'geometry IOB spec required')))
for _,key in ipairs({'seed_iob','output_iob'}) do spec[key]=native_path(spec[key]) end
for _,key in ipairs({'bootstrap_paths'}) do for index,path in ipairs(spec[key]) do spec[key][index]=native_path(path) end end
for _,row in ipairs(spec.instances) do row.path=native_path(row.path) end
return assert(loadfile(directory..'/iob_core.lua'))()(spec,assert(arg[2],'geometry operation required'),native_path)
