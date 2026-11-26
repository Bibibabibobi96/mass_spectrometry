-- Installed workbench transport; no author-repository path discovery.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local directory=assert(source:match('^(.*)/'))
local native_path=assert(loadfile(assert(arg[3],'public native path resource required')))()
local spec=dofile(native_path(assert(arg[1],'geometry IOB spec required')))
spec.seed_iob=native_path(spec.seed_iob)
if not spec.preserve_canonical_output then spec.output_iob=native_path(spec.output_iob) end
for _,key in ipairs({'bootstrap_paths'}) do for index,path in ipairs(spec[key]) do spec[key][index]=native_path(path) end end
for _,row in ipairs(spec.instances) do
 if not spec.preserve_canonical_instances then row.path=native_path(row.path) end
 for _,key in ipairs({'fractional_surface','surface_witnesses'}) do if row[key] then row[key]=native_path(row[key]) end end
end
return assert(loadfile(directory..'/iob_core.lua'))()(spec,assert(arg[2],'geometry operation required'),native_path)
