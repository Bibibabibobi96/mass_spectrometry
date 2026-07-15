local source=debug.getinfo(1,'S').source
local script_path=source:sub(1,1)=='@' and source:sub(2) or source
local script_dir=script_path:match('^(.*[\\/])') or ''
local template = os.getenv('OATOF_FOUR_INSTANCE_TEMPLATE_IOB') or
  script_dir..[[template_four_instance\mag_halbach_cylinder_2dp.iob]]
local output = os.getenv('OATOF_FORMAL_IOB_OUTPUT') or
  script_dir..[[formal/oatof_ideal_grounded.iob]]
local f=os.getenv('OATOF_FORMAL_PA_DIR') or script_dir..[[formal/]]
if not f:match('[\\/]$') then f=f..'/' end
local reflectron_pa=os.getenv('OATOF_REFLECTRON_PA') or f..'reflectron.pa0'
local accelerator_pa=os.getenv('OATOF_ACCELERATOR_PA') or f..'accelerator.pa0'
local flight_tube_pa=os.getenv('OATOF_FLIGHT_TUBE_PA') or f..'flight_tube_ground.pa0'
local detector_pa=os.getenv('OATOF_DETECTOR_PA') or f..'detector_ground.pa0'
local detector_active_plane_z=tonumber(os.getenv('OATOF_DETECTOR_ACTIVE_PLANE_Z') or '19.83')
local detector_marker_thickness=tonumber(os.getenv('OATOF_DETECTOR_MARKER_THICKNESS') or '0.05')
local detector_marker_back_margin=tonumber(os.getenv('OATOF_DETECTOR_MARKER_BACK_MARGIN_Z') or '0.05')
-- wb:save creates a minimal same-basename Fly2.  Read the complete GUI release
-- definition before saving (the default source may share the output basename),
-- then restore it beside the generated IOB so Define Particles never sees an
-- empty particles table.
local fly2_source=os.getenv('OATOF_FORMAL_FLY2_SOURCE') or
  script_dir..[[formal/oatof_ideal_grounded.fly2]]
local fly2_input=assert(io.open(fly2_source,'rb'),
  'cannot open GUI particle definition: '..fly2_source)
local fly2_content=fly2_input:read('*a')
fly2_input:close()
assert(fly2_content:match('standard_beam%s*{'),
  'GUI particle definition must contain standard_beam')
simion.command('"' .. template .. '"')
local wb=simion.wb
assert(#wb.instances == 4, 'formal template must contain exactly four PA instances')
local r,a,t,d=wb.instances[1],wb.instances[2],wb.instances[3],wb.instances[4]
r.pa:load(reflectron_pa); r:_debug_update_size()
a.pa:load(accelerator_pa); a:_debug_update_size()
t.pa:load(flight_tube_pa); t:_debug_update_size()
d.pa:load(detector_pa); d:_debug_update_size()
r.x,r.y,r.z=0,0,619.83; r.az,r.el,r.rt,r.scale=-90,0,0,1
local accelerator_axis_x,accelerator_axis_y=-48.8,0
local accelerator_half_x=(a.pa.nx-1)*a.pa.dx_mm/2
local accelerator_half_y=(a.pa.ny-1)*a.pa.dy_mm/2
local accelerator_rear_gap,accelerator_shield_wall=5,4
a.x,a.y,a.z=accelerator_axis_x-accelerator_half_x,
  accelerator_axis_y-accelerator_half_y,-1-accelerator_rear_gap-accelerator_shield_wall
a.az,a.el,a.rt,a.scale=0,0,0,1
t.x,t.y,t.z=0,0,19.83; t.az,t.el,t.rt,t.scale=-90,0,0,1
local detector_half_x=(d.pa.nx-1)*d.pa.dx_mm/2
local detector_half_y=(d.pa.ny-1)*d.pa.dy_mm/2
d.x,d.y,d.z=-accelerator_axis_x-detector_half_x,
  -accelerator_axis_y-detector_half_y,
  detector_active_plane_z-detector_marker_back_margin-detector_marker_thickness
d.az,d.el,d.rt,d.scale=0,0,0,1
wb:save(output)
local fly2_output=output:gsub('%.[iI][oO][bB]$','.fly2')
assert(fly2_output~=output,'formal IOB output must end in .iob')
local fly2_file=assert(io.open(fly2_output,'wb'),
  'cannot write GUI particle definition: '..fly2_output)
fly2_file:write(fly2_content)
fly2_file:close()
