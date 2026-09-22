-- Build one read-only accelerator component IOB from the repository one-instance seed.
local o=(arg[1]=='--') and 1 or 0
local function a(i,label)local v=assert(arg[i+o],label);return v end
local seed,pa,output,program,fly=a(1,'seed required'),a(2,'pa0 required'),a(3,'output required'),a(4,'program required'),a(5,'fly2 required')
local origin_x=assert(tonumber(a(6,'origin x required')),'origin x must be numeric')
local origin_y=assert(tonumber(a(7,'origin y required')),'origin y must be numeric')
local origin_z=assert(tonumber(a(8,'origin z required')),'origin z must be numeric')
assert(seed:match('1_instance_seed%.iob$'),'one-instance seed required')
assert(pa:match('%.pa0$'),'published native controller required')
assert(output:match('%.iob$') and program:match('%.lua$') and fly:match('%.fly2$'),'invalid IOB companion suffix')
local wb=assert(simion.wb);wb:load(seed);assert(#wb.instances==1,'seed must contain one instance')
wb.instances[1].pa:load(pa); assert(wb.instances[1]._debug_update_size);wb.instances[1]:_debug_update_size()
wb.instances[1].x,wb.instances[1].y,wb.instances[1].z=origin_x,origin_y,origin_z;wb.instances[1].az,wb.instances[1].el,wb.instances[1].rt,wb.instances[1].scale=0,0,0,1
wb:save(output)
local function cp(s,t)local i=assert(io.open(s,'rb'));local d=i:read('*a');i:close();local w=assert(io.open(t,'wb'));w:write(d);w:close()end
cp(program,output:gsub('%.iob$','.lua'));cp(fly,output:gsub('%.iob$','.fly2'));cp(program:gsub('%.lua$','.operating_point.lua'),output:gsub('%.iob$','.operating_point.lua'));cp(program:gsub('%.lua$','.source_states.lua'),output:gsub('%.iob$','.source_states.lua'))
print('ACCELERATOR_COMPONENT_FOCUS_IOB=PASS instances=1 pa_mode=published_read_only_runtime_fast_adjust')
