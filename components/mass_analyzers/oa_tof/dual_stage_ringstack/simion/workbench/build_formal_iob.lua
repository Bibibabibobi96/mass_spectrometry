local source=debug.getinfo(1,'S').source
local script_path=source:sub(1,1)=='@' and source:sub(2) or source
local script_dir=script_path:match('^(.*[\\/])') or ''
local template = os.getenv('OATOF_FOUR_INSTANCE_TEMPLATE_IOB') or
  script_dir..[[template_four_instance\mag_halbach_cylinder_2dp.iob]]
local output = os.getenv('OATOF_FORMAL_IOB_OUTPUT') or
  script_dir..[[formal/oatof_ideal_grounded.iob]]
local f=os.getenv('OATOF_FORMAL_PA_DIR') or script_dir..[[formal/]]
if not f:match('[\\/]$') then f=f..'/' end
simion.command('"' .. template .. '"')
local wb=simion.wb
assert(#wb.instances == 4, 'formal template must contain exactly four PA instances')
local r,a,t,d=wb.instances[1],wb.instances[2],wb.instances[3],wb.instances[4]
r.pa:load(f..'reflectron.pa0'); r:_debug_update_size()
a.pa:load(f..'accelerator.pa0'); a:_debug_update_size()
t.pa:load(f..'flight_tube_ground.pa0'); t:_debug_update_size()
d.pa:load(f..'detector_ground.pa0'); d:_debug_update_size()
r.x,r.y,r.z=0,0,619.83; r.az,r.el,r.rt,r.scale=-90,0,0,1
a.x,a.y,a.z=-93.8,-45,-15; a.az,a.el,a.rt,a.scale=0,0,0,1
t.x,t.y,t.z=0,0,19.83; t.az,t.el,t.rt,t.scale=-90,0,0,1
d.x,d.y,d.z=7.8,-41,17.83; d.az,d.el,d.rt,d.scale=0,0,0,1
wb:save(output)
