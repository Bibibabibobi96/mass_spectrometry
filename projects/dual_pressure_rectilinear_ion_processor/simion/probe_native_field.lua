-- Read-only native potential audit; coordinates and voltages share Fly inputs.
local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])'))
local c=assert(loadfile(directory..'frozen_config.lua'))()
local waveforms=assert(loadfile(directory..'voltage_waveforms.lua'))()
local drive=assert(loadfile(directory..'native_drive.lua'))(waveforms)
local kernel=assert(loadfile(directory..'simion_rf_drive.lua'))()
local b=c.baseline
local timing=assert(c.native_timing,'frozen native timing required')
local d=assert(c.field_diagnostics,'frozen field diagnostics config required')
local rf=kernel.new{waveform='cosine',frequency_hz=b.electric.rf_frequency_hz,
 phase_rad=b.clock.rf_phase_rad,rf_amplitude_v=b.electric.rf_peak_to_peak_v/2,
 rf_scale=1,common_mode_scale=1,group_dc_v={0,0},rf_steps_per_period=c.numerics.rf_steps_per_period,
 electrodes={{electrode_id=1,electrode_group=1,polarity=1,common_mode_v=0}}}
local pa=simion.pas:open(c.native_field.directory..'/processor.pa0')
local origin,grid=c.native_projection.origin_mm,c.native_projection.grid_mm
local maximum=c.native_projection.maximum_mm
local radius=d.section_radius_scale*b.geometry.r0_mm
assert(-radius>=origin[2] and radius<=maximum[2] and -radius>=origin[3] and radius<=maximum[3],
 'native field cross-section extent exceeds frozen PA domain')
local transverse_count=math.floor(2*radius/(grid*d.section_grid_multiple)+1e-9)+1
local expected_samples=#d.stages*(
 math.floor((maximum[1]-origin[1])/(grid*d.axial_grid_multiple)+1e-9)+1+
 math.floor((maximum[2]-origin[2])/(grid*d.orthogonal_grid_multiple)+1e-9)+1+
 #d.sections*transverse_count*transverse_count)
assert(expected_samples<=d.maximum_samples,'native field diagnostic sample budget exceeded before queries')
local out=assert(io.open(directory..'native_potential_audit.csv','w'))
out:write('t_us,x_mm,y_mm,z_mm,potential_v\n')
for _,t in ipairs({timing.primary_quench_us-d.epsilon_us,timing.primary_quench_us,
 drive.pulse_start_us(c)+d.epsilon_us}) do
 local voltages=drive.voltages(c,t,rf.differential_at(b.clock.epoch_us+t))
 for _,y in ipairs({0,2,3.6,6,8,b.geometry.extraction_end_y_mm,c.native_projection.maximum_mm[2]}) do
  local x,z=b.geometry.lp_center_mm,0
  local v=pa:potential_vc((x-origin[1])/grid,(y-origin[2])/grid,(z-origin[3])/grid,voltages)
  out:write(string.format('%.15g,%.15g,%.15g,%.15g,%.15g\n',t,x,y,z,v))
 end
end
out:close()
print('NATIVE_POTENTIAL_AUDIT=COMPLETE')
-- Read only the solved basis with explicit stage-specific electrode voltages.
local times={capture_mid=b.schedule.capture_end_us/2,
 transfer_mid=(b.schedule.capture_end_us+b.schedule.transfer_end_us)/2,
 pre_extraction=timing.primary_quench_us-d.epsilon_us,
 quench_mid=(timing.primary_quench_us+drive.pulse_start_us(c))/2,
 pulse_after=drive.pulse_start_us(c)+d.epsilon_us}
local function voltages_for(stage,t)
 if stage.component=='total' then return drive.voltages(c,t,rf.differential_at(b.clock.epoch_us+t)) end
 local dc=drive.voltages(c,t,0)
 if stage.component=='dc' then return dc end
 assert(stage.component=='rf_only_peak','unsupported field component')
 local peak=drive.voltages(c,t,b.electric.rf_peak_to_peak_v/2)
 for id=1,#peak do peak[id]=peak[id]-dc[id] end
 return peak
end
local function axis_values(a,bound,step)
 local values={}
 local count=math.floor((bound-a)/step+1e-9)
 for index=0,count do values[#values+1]=a+index*step end
 return values
end
local samples=0
out=assert(io.open(directory..'native_field_samples.csv','w'))
out:write('stage_id,section_id,sample_kind,t_us,x_mm,y_mm,z_mm,potential_v,ex_v_per_mm,ey_v_per_mm,ez_v_per_mm,electrode\n')
local function sample(stage,section,kind,t,x,y,z,voltages)
 samples=samples+1
 assert(samples<=d.maximum_samples,'native field diagnostic sample budget exceeded')
 local gx,gy,gz=(x-origin[1])/grid,(y-origin[2])/grid,(z-origin[3])/grid
 local v=pa:potential_vc(gx,gy,gz,voltages)
 -- field_vc is negative gradient [V/GU]; convert electric field to V/mm.
 local ex,ey,ez=pa:field_vc(gx,gy,gz,voltages)
 local electrode=pa:electrode(math.floor(gx+0.5),math.floor(gy+0.5),math.floor(gz+0.5)) and 1 or 0
 out:write(string.format('%s,%s,%s,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g,%d\n',
  stage.stage_id,section,kind,t,x,y,z,v,ex/grid,ey/grid,ez/grid,electrode))
end
local transverse=axis_values(-radius,radius,grid*d.section_grid_multiple)
for _,stage in ipairs(d.stages) do
 local t=assert(times[stage.time_ref],'unsupported diagnostic time reference')
 local voltages=voltages_for(stage,t)
 for _,x in ipairs(axis_values(origin[1],maximum[1],grid*d.axial_grid_multiple)) do
  sample(stage,'axis','axial',t,x,0,0,voltages)
 end
 for _,y in ipairs(axis_values(origin[2],maximum[2],grid*d.orthogonal_grid_multiple)) do
  sample(stage,'lp_exit','orthogonal',t,b.geometry.lp_center_mm,y,0,voltages)
 end
 for _,section in ipairs(d.sections) do
  local x
  if section.position_ref=='hp_fraction' then x=b.geometry.guide_length_mm+section.fraction*b.geometry.hp_length_mm
  else assert(section.position_ref=='lp_center');x=b.geometry.lp_center_mm end
  for _,y in ipairs(transverse) do for _,z in ipairs(transverse) do
   sample(stage,section.section_id,'cross_section',t,x,y,z,voltages)
  end end
 end
end
out:close()
print('NATIVE_FIELD_DIAGNOSTICS=COMPLETE samples='..samples)
