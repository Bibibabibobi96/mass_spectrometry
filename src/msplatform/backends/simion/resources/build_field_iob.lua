-- Source-free solved workbench transport; no tracking Program or particle source.
local source=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local directory=assert(source:match('^(.*)/'))
local native_path=assert(loadfile(assert(arg[3],'native path resource required')))()
local spec=dofile(native_path(assert(arg[1],'field IOB specification required')))
local mode=assert(arg[2],'field operation required')
assert(mode=='build_fields' or mode=='verify_fields','unsupported field operation')
for _,key in ipairs({'seed_iob','output_iob','empty_particle_control'}) do spec[key]=native_path(spec[key]) end
for index,path in ipairs(spec.bootstrap_paths) do spec.bootstrap_paths[index]=native_path(path) end
for _,row in ipairs(spec.instances) do row.path=native_path(row.path) end
for _,row in ipairs(spec.response_fields) do row.path=native_path(row.path) end
return assert(loadfile(directory..'/iob_core.lua'))()(spec,mode,native_path)
