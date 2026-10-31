-- Native SIMION electrode field, with a clean one-instance Workbench seed.
local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])'),
 'invoke the builder using its absolute script path')
local c = assert(loadfile(directory..'frozen_config.lua'))()
local native_path=assert(loadfile(directory..'native_run_path.lua'))()
local wb=simion.wb
wb:load(native_path(c.workbench_seed_path))
assert(#wb.instances==1,'one integration volume required')
wb.instances[1].pa:load(native_path(c.native_field.directory..'/processor.pa0'))
wb.instances[1]:_debug_update_size()
local origin=c.native_projection.origin_mm
local transform=c.coordinate_transform
local rotation={{1,0,0},{0,1,0},{0,0,1}}
local translation={0,0,0}
local az,el,rt=0,0,0
if transform then
 rotation=transform.rotation;translation=transform.translation_mm
 local expected={{0,0,-1},{1,0,0},{0,-1,0}}
 for row=1,3 do for col=1,3 do
  assert(rotation[row][col]==expected[row][col],'unsupported project rotation for certified SIMION pose')
 end end
 -- Official SIMION order is rt then el then az: Rx(-90) followed by Rz(90).
 az,el,rt=0,90,-90
end
local position={}
for row=1,3 do
 position[row]=translation[row]
 for col=1,3 do position[row]=position[row]+rotation[row][col]*origin[col] end
end
local instance=wb.instances[1]
instance.ox,instance.oy,instance.oz=0,0,0
instance.az,instance.el,instance.rt,instance.scale=az,el,rt,1
instance.x,instance.y,instance.z=position[1],position[2],position[3]
local function assert_near(a,b,label)
 assert(math.abs(a-b)<=1e-10,label..' differs from frozen rigid transform')
end
-- Query actual vendor transforms, rather than trusting Euler-angle assignments.
for column=1,3 do
 local basis={0,0,0};basis[column]=1
 local x,y,z=instance:pa_to_wb_orient(unpack(basis))
 local actual={x,y,z}
 for row=1,3 do assert_near(actual[row],rotation[row][column],'PA basis') end
 print(string.format('ION_PROCESSOR_POSE_BASIS %d %.15g %.15g %.15g',column,x,y,z))
end
local x,y,z=instance:pa_to_wb_coords(0,0,0)
assert_near(x,position[1],'PA origin X');assert_near(y,position[2],'PA origin Y');assert_near(z,position[3],'PA origin Z')
print(string.format('ION_PROCESSOR_POSE_ORIGIN %.15g %.15g %.15g',x,y,z))
-- Coordinates take PA grid units, unlike the orientation API's free vectors.
local grid=c.native_projection.grid_mm
assert(type(grid)=='number' and grid>0,'native PA grid spacing required for pose unit check')
for column=1,3 do
 local basis={0,0,0};basis[column]=1
 local a,b,d=instance:pa_to_wb_coords(unpack(basis))
 local actual={a,b,d}
 for row=1,3 do assert_near(actual[row],position[row]+grid*rotation[row][column],'PA grid unit') end
 print(string.format('ION_PROCESSOR_POSE_GRID_MM %d %.15g %.15g %.15g',column,a,b,d))
end
-- No voltage adjustment or PA save: GUI owns an independent local family copy.
wb:load_particles(directory..'processor.fly2')
wb:save(directory..'processor.iob')
print('ION_PROCESSOR_WORKBENCH=PASS field=native_laplace adjustable_electrodes=15')
