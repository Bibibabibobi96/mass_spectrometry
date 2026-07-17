local source=debug.getinfo(1,'S').source
local script_path=source:sub(1,1)=='@' and source:sub(2) or source
local script_dir=script_path:match('^(.*[\\/])') or ''
local artifact_formal=script_dir..[[../../../../../artifacts/projects/oa_tof/models/simion/formal/oatof_524amu/]]
local template = os.getenv('OATOF_FOUR_INSTANCE_TEMPLATE_IOB') or
  script_dir..[[../../../../../artifacts/projects/oa_tof/models/simion/workspace/04_workbench/template_four_instance/mag_halbach_cylinder_2dp.iob]]
local output = os.getenv('OATOF_FORMAL_IOB_OUTPUT') or
  artifact_formal..[[oatof_ideal_grounded.iob]]
local f=os.getenv('OATOF_FORMAL_PA_DIR') or artifact_formal
if not f:match('[\\/]$') then f=f..'/' end
local reflectron_pa=os.getenv('OATOF_REFLECTRON_PA') or f..'reflectron.pa0'
local accelerator_pa=os.getenv('OATOF_ACCELERATOR_PA') or f..'accelerator.pa0'
local flight_tube_pa=os.getenv('OATOF_FLIGHT_TUBE_PA') or f..'flight_tube_ground.pa0'
local detector_pa=os.getenv('OATOF_DETECTOR_PA') or f..'detector_ground.pa0'
local detector_active_plane_z=tonumber(os.getenv('OATOF_DETECTOR_ACTIVE_PLANE_Z') or '0')
local detector_marker_thickness=tonumber(os.getenv('OATOF_DETECTOR_MARKER_THICKNESS') or '0.05')
local detector_marker_back_margin=tonumber(os.getenv('OATOF_DETECTOR_MARKER_BACK_MARGIN_Z') or '0.05')
local reflectron_entgrid_z=tonumber(os.getenv('OATOF_REFLECTRON_ENTGRID_Z') or '600')
local accelerator_repeller_thickness=tonumber(os.getenv('OATOF_ACCELERATOR_REPELLER_THICKNESS') or '1')
local accelerator_rear_gap=tonumber(os.getenv('OATOF_ACCELERATOR_REAR_GAP') or '5')
local accelerator_shield_wall=tonumber(os.getenv('OATOF_ACCELERATOR_SHIELD_WALL') or '4')
local accelerator_translation_z=tonumber(os.getenv('OATOF_ACCELERATOR_TRANSLATION_Z') or '-19.92918680341103')
local shield_near_gap=tonumber(os.getenv('OATOF_SHIELD_NEAR_ENDCAP_GAP') or '20')
local shield_endcap_thickness=tonumber(os.getenv('OATOF_SHIELD_ENDCAP_THICKNESS') or '10')
local shield_near_bore_z=accelerator_translation_z-accelerator_repeller_thickness-accelerator_rear_gap-
  accelerator_shield_wall-shield_near_gap
local shield_near_outer_z=shield_near_bore_z-shield_endcap_thickness
local function read_file(path,label)
  local input=assert(io.open(path,'rb'),'cannot open '..label..': '..path)
  local content=input:read('*a')
  input:close()
  return content
end
local function write_file(path,content,label)
  local output_file=assert(io.open(path,'wb'),'cannot write '..label..': '..path)
  output_file:write(content)
  output_file:close()
end
-- wb:save may create minimal same-basename sidecars. Read the complete Program
-- and GUI release definition before saving, then restore both beside the IOB.
-- The Program segment.load contract makes the Particles-tab T.Qual visible as
-- 8 immediately on every IOB load and reapplies it before every Fly'm.
local program_source=os.getenv('OATOF_FORMAL_PROGRAM_SOURCE') or
  script_dir..[[formal/oatof_ideal_grounded.lua]]
local fly2_source=os.getenv('OATOF_FORMAL_FLY2_SOURCE') or
  script_dir..[[formal/oatof_ideal_grounded.fly2]]
local program_content=read_file(program_source,'formal Program')
local fly2_content=read_file(fly2_source,'GUI particle definition')
assert(program_content:match('adjustable%s+trajectory_quality%s*=%s*8'),
  'formal Program must default trajectory_quality to 8')
assert(program_content:match('function%s+segment%.load%s*%(') and
       program_content:match('sim_trajectory_quality%s*=%s*trajectory_quality'),
  'formal Program must set GUI T.Qual during segment.load')
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
r.x,r.y,r.z=0,0,reflectron_entgrid_z; r.az,r.el,r.rt,r.scale=-90,0,0,1
local accelerator_axis_x,accelerator_axis_y=-48.8,0
local accelerator_half_x=(a.pa.nx-1)*a.pa.dx_mm/2
local accelerator_half_y=(a.pa.ny-1)*a.pa.dy_mm/2
a.x,a.y,a.z=accelerator_axis_x-accelerator_half_x,
  accelerator_axis_y-accelerator_half_y,-accelerator_repeller_thickness-
  accelerator_rear_gap-accelerator_shield_wall+accelerator_translation_z
a.az,a.el,a.rt,a.scale=0,0,0,1
t.x,t.y,t.z=0,0,shield_near_outer_z; t.az,t.el,t.rt,t.scale=-90,0,0,1
local detector_half_x=(d.pa.nx-1)*d.pa.dx_mm/2
local detector_half_y=(d.pa.ny-1)*d.pa.dy_mm/2
d.x,d.y,d.z=-accelerator_axis_x-detector_half_x,
  -accelerator_axis_y-detector_half_y,
  detector_active_plane_z-detector_marker_back_margin-detector_marker_thickness
d.az,d.el,d.rt,d.scale=0,0,0,1
wb:save(output)
local program_output=output:gsub('%.[iI][oO][bB]$','.lua')
local fly2_output=output:gsub('%.[iI][oO][bB]$','.fly2')
assert(fly2_output~=output,'formal IOB output must end in .iob')
write_file(program_output,program_content,'same-basename formal Program')
write_file(fly2_output,fly2_content,'same-basename GUI particle definition')
