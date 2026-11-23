-- Solver-free regression for build_component_focus_iob.lua argument parsing.
-- It mocks the Workbench and streams; no PA/cache file is opened or written.
local directory=assert(arg[1],'accelerator SIMION source directory is required')
local builder=assert(loadfile(directory..'/build_component_focus_iob.lua'))
local opened={}
local original_open=io.open
io.open=function(path,mode)
 local stream={}
 if mode=='rb' then function stream:read(_) return 'fixture' end
 else function stream:write(_) end end
 function stream:close() end
 opened[#opened+1]={path=path,mode=mode}
 return stream
end
local instance={pa={load=function(_,path) assert(path=='controller.pa0') end},_debug_update_size=function(_) end}
simion={wb={instances={instance},load=function(_,path) assert(path=='1_instance_seed.iob') end,save=function(_,path) assert(path=='output.iob') end}}
arg={'--','1_instance_seed.iob','controller.pa0','output.iob','component_focus.lua','component_focus_input.fly2','-32','-32','0'}
local ok,message=pcall(builder)
io.open=original_open
assert(ok,tostring(message))
assert(instance.x==-32 and instance.y==-32 and instance.z==0,'numeric IOB origin parsing failed')
assert(#opened==8,'expected every required GUI companion stream operation')
local saw_source_states=false
for _,entry in ipairs(opened) do
 if entry.path=='output.source_states.lua' then saw_source_states=true end
end
assert(saw_source_states,'IOB package must include the renamed source-states companion')
print('ACCELERATOR_COMPONENT_FOCUS_IOB_ARGUMENTS=PASS')
