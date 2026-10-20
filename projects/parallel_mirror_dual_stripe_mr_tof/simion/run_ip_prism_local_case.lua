-- Native GEM/ordinary PA/Workbench/Fly; all scientific controls are frozen.
local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])'))
local c=assert(loadfile(directory..'case_config.lua'))()
-- The frozen dispatch wrapper passes an execution stage, never a physics override.
local stage=(...) or 'combined'
assert(stage=='combined' or stage=='build' or stage=='fly' or stage=='assemble','unknown local execution stage')
local field_path=c.field_path or (directory..'field.pa')
local function read(path)
 local handle=assert(io.open(path,'rb'));local bytes=handle:read('*a');handle:close();return bytes
end
local function write(path,bytes)
 local handle=assert(io.open(path,'wb'));handle:write(bytes);handle:close()
end
-- Official wb:save also saves associated files. Preserve complete companions
-- as in common/multipole/build_simion_runtime_iob.lua; never keep GUI stubs.
local program_path,particles_path=directory..'local.lua',directory..'local.fly2'
local program_bytes,particles_bytes=read(program_path),read(particles_path)
-- The official command interface and pa:refine are supported in installed 8.2.
-- Official Remove All PAs also releases workbench references. Closing each PA
-- individually fails when the previous case's saved IOB still references it.
-- Installed 8.2 example: examples/molecular_beam/aa_deflector_build.lua.
simion.pas:close()
if stage=='combined' or stage=='build' then
 assert(field_path:gsub('\\','/'):lower()==(directory..'field.pa'):gsub('\\','/'):lower(),
  'only the declared field owner may build a shared local field')
 simion.command(string.format('gem2pa %q %q',directory..'field.gem',field_path))
 local pa=assert(simion.pas:open(field_path))
 pa:refine{convergence=c.convergence_v}
 pa:save(field_path)
 pa:close()
end
local wb=simion.wb
wb:load(c.workbench_seed_path)
assert(#wb.instances==1,'one local field instance required')
local instance=wb.instances[1]
instance.pa:load(field_path)
instance:_debug_update_size()
instance.ox,instance.oy,instance.oz=0,0,0
instance.az,instance.el,instance.rt,instance.scale=0,0,0,1
instance.x,instance.y,instance.z=c.box_mm[1],c.box_mm[2],c.box_mm[3]
for axis=1,3 do
 local q={0,0,0};q[axis]=1
 local actual={instance:pa_to_wb_coords(unpack(q))}
 for k=1,3 do assert(math.abs(actual[k]-c.box_mm[k]-(axis==k and c.pitch_mm[k] or 0))<1e-9,'PA grid pose differs') end
end
-- Confirm every source is vacuum using the actual vendor collision array.
local probe=assert(io.open(directory..'source_occupancy.csv','w'))
probe:write('particle_id,electrode\n')
for _,s in ipairs(c.source) do
 local gx,gy,gz=math.abs(s.x_mm)/c.pitch_mm[1],(s.y_mm-c.box_mm[2])/c.pitch_mm[2],(s.z_mm-c.box_mm[3])/c.pitch_mm[3]
 local metal=instance.pa:electrode(math.floor(gx+0.5),math.floor(gy+0.5),math.floor(gz+0.5))
 probe:write(s.particle_id..','..(metal and '1' or '0')..'\n')
 assert(not metal,'measured source starts in electrode')
end
probe:close()
-- On-axis profile gives the actual finite-field extent, not a sharp entry.
probe=assert(io.open(directory..'axis_field.csv','w'))
probe:write('z_mm,potential_v,ex_v_per_mm,ey_v_per_mm,ez_v_per_mm,electrode\n')
for index=0,math.floor((c.exit_z_mm-c.observation_planes[#c.observation_planes].z_mm)/c.probe_step_mm) do
 local z=c.exit_z_mm-index*c.probe_step_mm
 local gx,gy,gz=0,(c.nominal_y_mm-c.box_mm[2])/c.pitch_mm[2],(z-c.box_mm[3])/c.pitch_mm[3]
 local v=instance.pa:potential_vc(gx,gy,gz)
 local ex,ey,ez=instance.pa:field_vc(gx,gy,gz)
 local metal=instance.pa:electrode(math.floor(gx+0.5),math.floor(gy+0.5),math.floor(gz+0.5))
 probe:write(string.format('%.17g,%.17g,%.17g,%.17g,%.17g,%d\n',z,v,ex/c.pitch_mm[1],ey/c.pitch_mm[2],ez/c.pitch_mm[3],metal and 1 or 0))
end
probe:close()
wb:load_particles(directory..'local.fly2')
local function save_reload()
 wb:save(directory..'local.iob')
 write(program_path,program_bytes);write(particles_path,particles_bytes)
 wb:load(directory..'local.iob')
 assert(#wb.instances==1 and wb.instances[1].pa.path:gsub('\\','/'):lower()==field_path:gsub('\\','/'):lower(),'saved field binding differs')
 assert(read(program_path)==program_bytes and read(particles_path)==particles_bytes,'saved Program/FLY2 identity differs')
end
save_reload()
if stage=='combined' or stage=='fly' then
 simion.command(string.format('fly --trajectory-quality=%d --programs=1 --retain-trajectories=0 --particles=%q %q',c.trajectory_quality,directory..'local.fly2',directory..'local.iob'))
end
-- The headless command-interface Fly clears this Workbench on return in the
-- installed 8.2.0.11 (native lifecycle probe, 2026-10-20). Saving it now writes
-- an empty, invalid-size IOB. Keep the validated pre-Fly IOB and companions;
-- default GUI flags require an independent fresh-process replay, not this save.
print('IP_PRISM_CASE=PASS '..c.case_id..' stage='..stage)
