-- Populate the public four/five-slot container from an explicit runtime build spec.
-- This is preparation only: no Refine, Fast Adjust, or particle flight.
-- Every build provisions private neutral bootstrap PAs before replacing slots.
-- Slot order is flight tube, reflectron, coupled frontend, detector. Provider
-- placements are already resolved in oatof_global; no placement is inferred.
return function(spec,mode,native_path)
assert(mode=='build' or mode=='verify' or mode=='build_geometry' or mode=='verify_geometry'
  or mode=='build_model' or mode=='verify_model' or mode=='build_fields' or mode=='verify_fields','unsupported workbench operation')
local fields_only=mode=='build_fields' or mode=='verify_fields'
local model_only=mode=='build_model' or mode=='verify_model'
local geometry_only=mode=='build_geometry' or mode=='verify_geometry' or model_only
local source_free=geometry_only or fields_only
local dual_cone=spec.role=='dual_cone_tracking_iob' or spec.role=='dual_cone_geometry_iob'
local joint_ip_tracking=spec.role=='rf_ip_tracking_iob'
local component_tracking=joint_ip_tracking or spec.role=='independent_rf_tracking_iob' or spec.role=='independent_oa_tracking_iob' or spec.role=='dual_cone_tracking_iob'
local tracking_role=component_tracking
local independent_oa=spec.role=='independent_oa_geometry_iob_build'
local joint_rf_ip=spec.role=='rf_ip_geometry_iob_build'
local joint_rf_oa=spec.role=='rf_oa_geometry_iob_build'
local joint_oa_mr=spec.role=='oa_mr_geometry_iob_build'
local independent_component=spec.role=='independent_rf_geometry_iob_build' or independent_oa or tracking_role or dual_cone or joint_rf_ip or joint_oa_mr or joint_rf_oa
assert(not joint_rf_oa or mode=='build_geometry' or mode=='verify_geometry','RF-OA geometry only; model and fields unsupported')
assert(not joint_oa_mr or mode=='build_geometry' or mode=='verify_geometry' or model_only,'OA–MR fields and tracking workbench unsupported')
assert(not joint_rf_ip or mode=='build_geometry' or mode=='verify_geometry' or mode=='build_model' or mode=='verify_model','RF–IP tracking and fields workbench unsupported')
local independent_marker=joint_rf_oa and 'RF_OA_GEOMETRY_IOB' or joint_rf_ip and 'RF_IP_GEOMETRY_IOB' or joint_oa_mr and 'OA_MR_GEOMETRY_IOB' or dual_cone and 'DUAL_CONE_GEOMETRY_IOB' or independent_oa and 'INDEPENDENT_OA_GEOMETRY_IOB' or 'INDEPENDENT_RF_GEOMETRY_IOB'
assert(not independent_component or mode=='build_geometry' or mode=='verify_geometry'
  or model_only or (tracking_role and (mode=='build' or mode=='verify')),'independent geometry/model mode is unsupported')
assert(spec.schema_version==1 and (spec.role=='single_reflection_iob_build' or independent_component),
  'unsupported single-reflection IOB build specification')
local count=#spec.instances
assert(not joint_rf_ip or count==1,'RF–IP geometry requires one actual PA instance')
assert(not joint_rf_oa or count==1,'RF-OA geometry requires one actual PA instance')
assert(not joint_oa_mr or count==3,'OA–MR geometry requires three actual PA instances')
assert(not dual_cone or
  (spec.role=='dual_cone_tracking_iob' and (mode=='build' or mode=='verify')) or
  (spec.role=='dual_cone_geometry_iob' and geometry_only),
  'dual-cone role differs from its actual source-free/tracking operation')
assert(not dual_cone or count==1,'dual-cone monolithic geometry requires exactly one PA instance')
assert(not joint_ip_tracking or count==1,'RF-IP tracking requires one parent PA instance')
assert((independent_component and count>=1 and count<=10) or (not independent_component and (count==4 or count==5)), 'unsupported physical PA instance count')
local roles={'flight_tube','reflectron','accelerator','detector','entrance_refinement'}
if independent_component then
 roles={}
 local unique={}
 for index,row in ipairs(spec.instances) do
  assert(type(row.role)=='string' and not unique[row.role],'RF instance identities must be unique')
  unique[row.role]=true;roles[index]=row.role
 end
end
local role_list=table.concat(roles,',',1,count)
local companions={}
local stem=assert(spec.output_iob):gsub('%.iob$','')
assert(stem~=spec.output_iob, 'output must have .iob extension')
local function require_zero_particle_control(path)
  local file=assert(io.open(path,'rb'),'explicit zero-particle native format control missing: '..path)
  -- This bounded grammar accepts only the canonical empty FLY2 table and the
  -- actual SIMION2020 save spelling; no Lua code/beam definitions are executed.
  local text=file:read(4097) or '';file:close()
  assert(#text<=4096,'zero-particle format control exceeds the bounded profile')
  local compact=text:gsub('%s','')
  assert(compact=='particles{coordinates=0,}' or compact=='particles{coordinates=0}',
    'zero-particle native format control contains a particle or unsupported code')
  return text
end
if source_free then
  require_zero_particle_control(native_path(assert(spec.empty_particle_control,
    'explicit zero-particle native format control required')))
  local file=io.open(stem..'.fly2','rb')
  if mode=='verify_geometry' or mode=='verify_model' or mode=='verify_fields' then
    assert(file,'saved zero-particle native format control missing');file:close()
    companions[stem..'.fly2']=require_zero_particle_control(stem..'.fly2')
  elseif file then file:close();error('unsolved build refuses an existing FLY2 companion') end
end

-- An unsolved model must fail before loading a workbench if SIMION could
-- reconstruct/refine a missing PA from wgem, or execute an ambient hook.
if fields_only then
  for _,base in ipairs({stem,assert(spec.seed_iob):gsub('%.iob$','')}) do
    for _,extension in ipairs({'.wgem','.lua','.ion','.con','.rec'}) do
      local file=io.open(base..extension,'rb')
      if file then file:close();error('field-only workbench forbids automatic-build/source/Program companion: '..base..extension) end
    end
  end
end
if model_only then
  assert(type(spec.model)=='table','explicit model consumer specification required')
  local function reject_companions(base,allow_zero_control)
    for _,extension in ipairs({'.wgem','.lua','.fly2','.ion','.con','.rec'}) do
      local file=io.open(base..extension,'rb')
      if file then
        file:close()
        if extension=='.fly2' and allow_zero_control then require_zero_particle_control(base..extension)
        else error('unsolved model forbids automatic-build/source/Program companion: '..base..extension) end
      end
    end
  end
  reject_companions(stem,mode=='verify_model')
  reject_companions(assert(spec.seed_iob):gsub('%.iob$',''))
  for _,row in ipairs(spec.instances) do
    assert(row.path:match('%.pa#$'),'unsolved model requires the actual raw PA representation')
    reject_companions(row.path:gsub('%.pa#$',''))
    local file=assert(io.open(row.path,'rb'),'model geometry PA is missing before workbench load: '..row.path)
    assert(file:seek('end')>0,'model geometry PA is empty');file:close()
  end
  for _,key in ipairs({'configuration','consumer','rf_drive','pulse_hook','waveforms'}) do
    local file=assert(io.open(assert(spec.model[key]),'rb'),'model consumer resource missing: '..key)
    file:close()
  end
end

for _,extension in ipairs(source_free and {'.lua','.ion','.con','.rec'} or {'.lua','.fly2'}) do
  local path=stem..extension
  local input=io.open(path,'rb')
  if source_free then
    if input then input:close();error('geometry-only IOB must not attach a source/Program companion: '..path) end
  else
    assert(input,'prepared companion is missing: '..path)
    companions[path]=input:read('*a');input:close()
  end
end
if independent_component and not tracking_role then
  for _,base in ipairs({stem,assert(spec.seed_iob):gsub('%.iob$','')}) do
    for _,extension in ipairs({'.wgem','.lua','.ion','.con','.rec'}) do
      local file=io.open(base..extension,'rb')
      if file then file:close();error('RF raw geometry forbids automatic-build/source/Program companion') end
    end
  end
  for _,row in ipairs(spec.instances) do
    assert(row.path:match('%.pa#$'),'RF geometry requires the actual raw PA representation')
    for _,key in ipairs({'path','fractional_surface','surface_witnesses'}) do
      local file=assert(io.open(assert(row[key]),'rb'),'RF geometry input missing before IOB load: '..key)
      assert(file:seek('end')>0,'RF geometry input empty: '..key);file:close()
    end
  end
end

for index,row in ipairs(spec.instances) do
  if dual_cone then
    assert(row.role=='dual_cone','dual-cone native slot identity differs')
    local ids={1,2,3,11,12,21,22}
    assert(type(row.response_ids)=='table' and #row.response_ids==#ids,'dual-cone requires all seven native electrodes')
    for i,eid in ipairs(ids) do assert(row.response_ids[i]==eid,'dual-cone native electrode mapping differs') end
    assert(row.placement.scale==1,'dual-cone instance scaling is not implemented')
  end
  assert(row.role==roles[index] and row.instance_index==index and row.priority_number==index,
    'IOB role/order differs at slot '..index)
  assert(type(row.path)=='string' and row.path~='', 'runtime PA path is missing')
  for _,key in ipairs({'x_mm','y_mm','z_mm','az_deg','el_deg','rt_deg','scale'}) do
    local value=row.placement[key]
    assert(type(value)=='number' and value==value and math.abs(value)<math.huge,
      'invalid provider placement '..row.role..'.'..key)
  end
end


local function verify_fractional_component(item,row)
  if not independent_component then return end
  assert(item.ox==0 and item.oy==0 and item.oz==0,'RF PA working origin must remain zero')
  local function near(a,b) return math.abs(a-b)<=64*2.220446049250313e-16*math.max(1,math.abs(a),math.abs(b)) end
  for axis=1,3 do
    local v={0,0,0};v[axis]=1
    local x,y,z=item:pa_to_wb_orient(unpack(v))
    for k,value in ipairs({x,y,z}) do assert(near(value,row.rotation[k][axis]),'RF basis differs from original matrix') end
  end
  for _,q in ipairs({{0,0,0},{1,1,1},{item.pa.nx-1,item.pa.ny-1,item.pa.nz-1}}) do
    local x,y,z=item:pa_to_wb_coords(unpack(q))
    local pitch={item.pa.dx_mm,item.pa.dy_mm,item.pa.dz_mm}
    for k,value in ipairs({x,y,z}) do
      local expected=row.placement[({'x_mm','y_mm','z_mm'})[k]]
      for j=1,3 do expected=expected+row.rotation[k][j]*pitch[j]*q[j] end
      assert(near(value,expected),'RF point differs from original rigid transform')
    end
  end
  if component_tracking then
    assert(row.path:match('%.pa0$'),'RF tracking requires the original solved carrier')
    local actual={}
    for _,eid in ipairs(item.pa.electrode_numbers) do actual[eid]=true end
    for _,eid in ipairs(row.response_ids) do assert(actual[eid],'RF solved carrier mapping differs');actual[eid]=nil end
    assert(next(actual)==nil,'RF carrier contains an undeclared electrode')
  end
  local surface=assert(io.open(row.fractional_surface,'rb'),'fractional companion missing before IOB load')
  assert(surface:seek('end')>0);surface:close()
  local witnesses=assert(io.open(row.surface_witnesses,'rb'))
  local checked=0
  for line in witnesses:lines() do
    local x,y,z,sx,sy,sz=line:match('^(%d+),(%d+),(%d+),([^,]+),([^,]+),([^,]+)$')
    assert(x,'invalid surface witness')
    local ax,ay,az=item.pa:surface_info(tonumber(x),tonumber(y),tonumber(z))
    for k,actual in ipairs({{ax},{ay},{az}}) do
      local wanted=({sx,sy,sz})[k]
      assert((wanted=='nil' and actual[1]==nil) or (wanted~='nil' and actual[1]==tonumber(wanted)), 'cold fractional surface readback differs')
    end
    checked=checked+1
  end
  witnesses:close();assert(checked>0,'fractional surface witnesses empty')
  for _,sample in ipairs(row.physical_samples) do
    local potential,metal=item.pa:point(unpack(sample.gu))
    assert(metal==(sample.metal~=false) and (component_tracking or sample.metal==false or potential==sample.electrode_id),'cold RF physical node differs')
  end
end

if mode=='verify' or mode=='verify_geometry' or mode=='verify_model' or mode=='verify_fields' then
  local interfaces
  if not geometry_only and not tracking_role then
  assert(type(spec.response_fields)=='table','prepared response field paths are required')
  interfaces=assert(spec.interface_field_probes,'resolved interface field probes are required')
  assert(#interfaces==2,'OA exit and reflectron entry interface probes are required')
  end
  local function finite(value)
    return type(value)=='number' and value==value and math.abs(value)<math.huge
  end
  local endpoint_reports={}
  local function endpoint_gu(pa,to_gu,x,y,z)
    local values={to_gu(x,y,z)}
    local extent=math.max(1,pa.nx-1,pa.ny-1,pa.nz-1,
      math.abs(values[1]),math.abs(values[2]),math.abs(values[3]))
    local _,exponent=math.frexp(extent)
    -- The shared binary64_serialization_close contract uses 32 ULP. Here
    -- the scale includes all transformed coordinates/array extents because
    -- rotation and origin subtraction can cancel onto a zero endpoint.
    -- This normalizes a representational endpoint only, never an interior
    -- sample or a physical plane; substantive domain errors remain outside.
    local tolerance=32*2^(exponent-53)
    for axis,maximum in ipairs({pa.nx-1,pa.ny-1,pa.nz-1}) do
      local original=values[axis]
      local boundary=original<0 and 0 or original>maximum and maximum or nil
      if boundary and math.abs(original-boundary)<=tolerance then
        values[axis]=boundary
        local key=tostring(pa)..':'..axis..':'..string.format('%.17g',original)
        if not endpoint_reports[key] then
          endpoint_reports[key]=true
          print(string.format('SINGLE_REFLECTION_INTERFACE_ENDPOINT axis=%d original_gu=%.17g query_gu=%.17g allowance_gu=%.17g basis=binary64_32_ulp_coordinate_projection_only',
            axis,original,boundary,tolerance))
        end
      end
    end
    return unpack(values)
  end
  local function check_zero_sheet(pa,probe,to_gu,member)
    local tolerance=probe.voltage_tolerance_v
    assert(finite(tolerance) and tolerance>0 and probe.expected_potential_v==0,
      'interface requires a bounded imposed-zero potential audit')
    for index,point in ipairs(probe.points_mm) do
      local gx,gy,gz=endpoint_gu(pa,to_gu,point[1],point[2],point[3])
      local nx,ny,nz=math.floor(gx+.5),math.floor(gy+.5),math.floor(gz+.5)
      if pa.symmetry=='2dcylindrical' then
        ny=math.floor(math.sqrt(gy*gy+gz*gz)+.5);nz=0
      end
      local voltage,metal=pa:point(nx,ny,nz)
      assert(metal==true and finite(voltage) and math.abs(voltage)<=tolerance,
        'interface physical grounded grid node differs: '..probe.label..' '..member)
      local value=pa:potential_vc(gx,gy,gz)
      assert(finite(value) and math.abs(value)<=tolerance,
        'interface plane potential differs: '..probe.label..' '..member)
      local tangent={}
      for axis=1,2 do
        local minus,plus={unpack(point)},{unpack(point)}
        minus[axis]=minus[axis]-probe.tangent_step_mm
        plus[axis]=plus[axis]+probe.tangent_step_mm
        local a,b,c=endpoint_gu(pa,to_gu,unpack(minus));local low=pa:potential_vc(a,b,c)
        a,b,c=endpoint_gu(pa,to_gu,unpack(plus));local high=pa:potential_vc(a,b,c)
        assert(finite(low) and finite(high) and math.abs(low)<=tolerance and math.abs(high)<=tolerance,
          'interface tangential equipotential differs: '..probe.label..' '..member)
        tangent[axis]=-(high-low)/(2*probe.tangent_step_mm)
      end
      print(string.format('SINGLE_REFLECTION_INTERFACE_PLANE label=%s member=%s sample=%d x_mm=%.17g y_mm=%.17g z_mm=%.17g potential_v=%.17g tangent_ex_v_per_mm=%.17g tangent_ey_v_per_mm=%.17g physical_node_electrode=%s',
        probe.label,member,index,point[1],point[2],point[3],value,tangent[1],tangent[2],tostring(metal)))
    end
  end
  -- Check the actual canonical sidecar paths independently, before loading
  -- the carrier slots. Only one response PA is resident at a time.
  if not geometry_only and not component_tracking then
  for _,row in ipairs(spec.response_fields) do
    local response=assert(simion.pas:open(row.path),'response path did not load: '..row.path)
    local okay,message=pcall(function()
      for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
        assert(response[key]==row.grid[key],'response grid differs: '..row.domain..'.'..row.kind..'.'..key)
      end
      if row.domain=='parent' then
        local p=spec.instances[3].placement
        assert(p.az_deg==0 and p.el_deg==0 and p.rt_deg==0 and p.scale==1,
          'frontend interface response requires the resolved Cartesian placement')
        check_zero_sheet(response,interfaces[1],function(x,y,z)
          return (x-p.x_mm)/response.dx_mm,(y-p.y_mm)/response.dy_mm,(z-p.z_mm)/response.dz_mm
        end,row.kind)
        for index,point in ipairs(interfaces[1].points_mm) do
          local x=(point[1]-p.x_mm)/response.dx_mm
          local y=(point[2]-p.y_mm)/response.dy_mm
          local z=(point[3]-interfaces[1].axial_step_mm-p.z_mm)/response.dz_mm
          assert(response:inside_vc(x,y,z),'interface response side is outside its PA')
          local voltage=response:potential_vc(x,y,z)
          local ex,ey,ez=response:field_vc(x,y,z)
          assert(finite(voltage) and finite(ex) and finite(ey) and finite(ez),'nonfinite interface response field')
          print(string.format('SINGLE_REFLECTION_INTERFACE_RESPONSE_SIDE label=%s member=%s sample=%d side=minus z_mm=%.17g potential_v=%.17g ex_v_per_mm=%.17g ey_v_per_mm=%.17g ez_v_per_mm=%.17g basis=unscaled_frozen_working_member',
            interfaces[1].label,row.kind,index,point[3]-interfaces[1].axial_step_mm,voltage,
            ex/response.dx_mm,ey/response.dy_mm,ez/response.dz_mm))
        end
      end
    end)
    response:close()
    assert(okay,message)
    print('SINGLE_REFLECTION_RESPONSE_PATH_GRID=PASS DOMAIN='..row.domain..' KIND='..row.kind..' PATH='..row.path..' FLY=False')
  end
  end -- solved response-field checks are not geometry checks
  -- A separate process opens the saved workbench; never replace its PA paths,
  -- placements or particle controls while checking the persisted assembly.
  simion.command('"'..spec.output_iob..'"')
  assert(#simion.wb.instances==count,'saved workbench must contain the declared slots')
  -- Keep the official setter, but loaded IOBs may retain absolute ../
  -- spellings in its getter. Compare full absolute lexical identities only;
  -- do not change a slot or introduce another PA transport mechanism.
  local path_reference=simion.pas:open()
  local function path_key(path)
    local projected=native_path(path)
    local input=assert(projected):gsub('\\','/')
    assert(not input:match('^%a:[^/]') and not input:match('^//[?.]/'),
      'unsupported absolute PA path')
    path_reference.path=projected
    local value=assert(path_reference.path):gsub('\\','/'):lower()
    assert(not value:find('[%z\1-\31]'),'unsupported absolute PA path')
    local root,tail=value:match('^(%a:/)(.*)$')
    if not root then
      local server,share,remainder=value:match('^//([^/]+)/([^/]+)/*(.*)$')
      assert(server and server~='?' and server~='.' and server~='..'
        and share~='.' and share~='..','unsupported absolute PA path')
      root,tail='//'..server..'/'..share..'/',remainder
    end
    local parts={}
    for part in tail:gmatch('[^/]+') do
      if part=='..' then
        assert(#parts>0,'PA path escapes absolute root')
        parts[#parts]=nil
      elseif part~='.' then
        assert(not part:find(':',1,true),'unsupported absolute PA path')
        parts[#parts+1]=part
      end
    end
    return root..table.concat(parts,'/')
  end
  for index,row in ipairs(spec.instances) do
    local item=simion.wb.instances[index]
    -- Retain every directory and the drive/UNC root; pa.filename alone
    -- deliberately returns only the basename and is not an identity check.
    assert(path_key(item.pa.path)==path_key(row.path),'saved PA path differs at slot '..index)
    for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
      assert(item.pa[key]==row.grid[key],'saved PA grid differs: '..row.role..'.'..key)
    end
    for property,key in pairs({x='x_mm',y='y_mm',z='z_mm',az='az_deg',el='el_deg',rt='rt_deg',scale='scale'}) do
      assert(item[property]==row.placement[key],'saved provider placement differs: '..row.role..'.'..key)
    end
    verify_fractional_component(item,row)
  end
  path_reference:close()
  for path,data in pairs(companions) do
    local input=assert(io.open(path,'rb'),'saved companion is missing: '..path)
    local actual=input:read('*a');input:close()
    assert(actual==data,'workbench reopening changed a prepared companion: '..path)
  end
  if geometry_only then
    print((independent_component and independent_marker..'_REOPEN=PASS INSTANCES=' or 'SINGLE_REFLECTION_GEOMETRY_IOB_REOPEN=PASS INSTANCES=')..count..' FLY=False SOURCE=False REFINE=False')
    return
  end
  if component_tracking then
    -- The complete RF slot path/grid/pose, electrode map, metal/vacuum and
    -- fractional witnesses were checked above. TOF interface/priority probe
    -- definitions do not describe an independent RF instrument.
    print((joint_ip_tracking and 'RF_IP_TRACKING_COLD=PASS INSTANCES=' or dual_cone and 'DUAL_CONE_TRACKING_COLD=PASS INSTANCES=' or spec.role=='independent_oa_tracking_iob' and 'INDEPENDENT_OA_TRACKING_COLD=PASS INSTANCES=' or 'INDEPENDENT_RF_TRACKING_COLD=PASS INSTANCES=')..count..' FLY=False REFINE=False')
    return
  end
  -- SIMION 2020 official lua_simion.wb.html#simion.wb..find_at:
  -- status is an electrode Boolean; nele/nmag are highest-priority instances.
  -- This checks only frozen points, never RF/pulse fields or their continuity.
  local probes=spec.native_priority_occupancy_probes
  assert(type(probes)=='table' and #probes>0,'frozen native priority/occupancy points are required')
  local checked,observed,mismatches=0,0,{}
  for _,probe in ipairs(probes) do
    assert(type(probe.label)=='string' and type(probe.point_mm)=='table'
      and #probe.point_mm==3,'invalid frozen priority/occupancy point')
    local point=probe.point_mm
    for _,value in ipairs(point) do
      assert(type(value)=='number' and value==value and math.abs(value)<math.huge,
        'nonfinite priority/occupancy point')
    end
    local electrode,electric,magnetic=simion.wb:find_at(point[1],point[2],point[3])
    local source_index,source,gu,potential,node_electrode
    if probe.expected_node_electrode~=nil then
      assert(type(probe.expected_node_electrode)=='boolean' and probe.basis
        and probe.basis.kind=='resolved_physical_sample','source node expectation requires a physical sample')
      source_index=assert(({parent=3,entrance_refinement=5})[probe.basis.domain_id],
        'unknown physical-sample source domain')
      source=assert(simion.wb.instances[source_index],'physical-sample source instance is missing')
      gu=assert(probe.basis.gu,'physical-sample source node is missing')
      potential,node_electrode=source.pa:point(gu[1],gu[2],gu[3])
    end
    -- Official SIMION2020 FAQ: metal occupies the interior between electrode
    -- vertices. An integer electrode vertex need not be inside that volume.
    -- This frozen topology expectation is limited to surface=none arrays.
    local adjacent_metal_cells
    if probe.expected_adjacent_metal_cell~=nil then
      assert(probe.expected_adjacent_metal_cell==true and source
        and probe.expected_node_electrode==true,'metal cell check requires a physical source node')
      adjacent_metal_cells=0
      for dx=-1,0 do for dy=-1,0 do for dz=-1,0 do
        local x,y,z=gu[1]+dx,gu[2]+dy,gu[3]+dz
        if x>=0 and y>=0 and z>=0 and x+1<source.pa.nx
          and y+1<source.pa.ny and z+1<source.pa.nz then
          local full=true
          for ax=0,1 do for ay=0,1 do for az=0,1 do
            local _,metal=source.pa:point(x+ax,y+ay,z+az)
            if metal~=true then full=false end
          end end end
          if full then adjacent_metal_cells=adjacent_metal_cells+1 end
        end
      end end end
    end
    local has_expectation=probe.expected_instance~=nil or probe.expected_electrode~=nil
      or probe.expected_node_electrode~=nil
    local okay=true
    if probe.expected_instance~=nil then okay=electric==probe.expected_instance end
    if probe.expected_electrode~=nil then
      assert(type(probe.expected_electrode)=='boolean','electrode expectation must be Boolean')
      okay=okay and electrode==probe.expected_electrode
    end
    if probe.expected_node_electrode~=nil then
      okay=okay and node_electrode==probe.expected_node_electrode
    end
    if adjacent_metal_cells~=nil then okay=okay and adjacent_metal_cells>0 end
    if has_expectation then checked=checked+1 else observed=observed+1 end
    if not okay then mismatches[#mismatches+1]=probe.label end
    print(string.format('SINGLE_REFLECTION_NATIVE_POINT label=%q x_mm=%.17g y_mm=%.17g z_mm=%.17g electrode=%s electric_instance=%s magnetic_instance=%s expected_electrode=%s expected_instance=%s source_node_electrode=%s expected_node_electrode=%s adjacent_metal_cells=%s check=%s',
      probe.label,point[1],point[2],point[3],tostring(electrode),tostring(electric),tostring(magnetic),
      tostring(probe.expected_electrode),tostring(probe.expected_instance),tostring(node_electrode),tostring(probe.expected_node_electrode),tostring(adjacent_metal_cells),
      has_expectation and (okay and 'pass' or 'failed') or 'observation_only'))
    if not okay and source then
      -- Integer PA electrode nodes and workbench collision occupancy are
      -- different facts, especially for ideal zero-thickness grids. Record
      -- the official native transforms without moving the point or changing
      -- the failed expectation (SIMION2020 lua_simion.wb.html instance APIs).
      local gx,gy,gz=source:wb_to_pa_coords(point[1],point[2],point[3])
      local wx,wy,wz=source:pa_to_wb_coords(gu[1],gu[2],gu[3])
      local inside=source:inside_wc(point[1],point[2],point[3])
      print(string.format('SINGLE_REFLECTION_NATIVE_SOURCE_NODE label=%q source_instance=%d gu_x=%.17g gu_y=%.17g gu_z=%.17g node_voltage_v=%.17g node_electrode=%s world_to_pa_x_gu=%.17g world_to_pa_y_gu=%.17g world_to_pa_z_gu=%.17g node_world_x_mm=%.17g node_world_y_mm=%.17g node_world_z_mm=%.17g inside_source=%s selected_instance=%s',
        probe.label,source_index,gu[1],gu[2],gu[3],potential,tostring(node_electrode),
        gx,gy,gz,wx,wy,wz,tostring(inside),tostring(electric)))
    end
  end
  assert(#mismatches==0,'native priority/occupancy point mismatch: '..table.concat(mismatches,','))
  print('SINGLE_REFLECTION_NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED='..checked..' OBSERVED='..observed..' SCOPE=declared_points_only')
  -- Official SIMION2020 examples/dielectric/resistive_2dp.lua uses the
  -- instance transforms and PA *_vc APIs for read-only world-coordinate
  -- fields. examples/electrostatic_induction/inductionlib.lua documents each
  -- anisotropic V/gu -> V/mm divisor. Do not use instance:field here: it can
  -- execute the Program callbacks instead of inspecting the frozen PA.
  local function sample_field(item,point)
    local x,y,z=endpoint_gu(item.pa,function(a,b,c) return item:wb_to_pa_coords(a,b,c) end,unpack(point))
    assert(item.pa:inside_vc(x,y,z),'interface side sample is outside its declared PA')
    local voltage=item.pa:potential_vc(x,y,z)
    local ex,ey,ez=item.pa:field_vc(x,y,z)
    assert(finite(voltage) and finite(ex) and finite(ey) and finite(ez),'nonfinite interface field')
    ex,ey,ez=item:pa_to_wb_orient(ex/(item.pa.dx_mm*item.scale),
      ey/(item.pa.dy_mm*item.scale),ez/(item.pa.dz_mm*item.scale))
    return voltage,ex,ey,ez
  end
  for _,probe in ipairs(interfaces) do
    local item=assert(simion.wb.instances[probe.instance_index])
    local ground=assert(simion.wb.instances[probe.grounded_instance_index])
    check_zero_sheet(item.pa,probe,function(x,y,z) return item:wb_to_pa_coords(x,y,z) end,'carrier')
    for index,point in ipairs(probe.points_mm) do
      local phi=sample_field(ground,point)
      assert(math.abs(phi)<=probe.voltage_tolerance_v,'interface grounded-domain potential differs')
      for _,side in ipairs({'minus','plus'}) do
        local position={unpack(point)}
        position[3]=position[3]+(side=='minus' and -1 or 1)*probe.axial_step_mm
        local source=((probe.instance_index==3 and side=='minus') or
                      (probe.instance_index==2 and side=='plus')) and item or ground
        local v,ex,ey,ez=sample_field(source,position)
        print(string.format('SINGLE_REFLECTION_INTERFACE_SIDE label=%s sample=%d side=%s instance=%d z_mm=%.17g potential_v=%.17g ex_v_per_mm=%.17g ey_v_per_mm=%.17g ez_v_per_mm=%.17g normal_jump=allowed_ideal_electrode',
          probe.label,index,side,source==item and probe.instance_index or probe.grounded_instance_index,
          position[3],v,ex,ey,ez))
      end
    end
  end
  print('SINGLE_REFLECTION_INTERFACE_FIELDS=PASS SCOPE=sampled_grounded_ideal_grid_split_domains FINITE_GRID_EDGE_COUPLING=unqualified NORMAL_FIELD_CONTINUITY=not_required')
  if fields_only then print('SINGLE_REFLECTION_FIELD_IOB_REOPEN=PASS SOURCE=False FLY=False REFINE=False') end
  print('SINGLE_REFLECTION_IOB_REOPEN=PASS INSTANCES='..count..' PRIORITY_ORDER='..role_list..' FLY=False')
  return
end
local bootstrap={}
do
  assert(type(spec.bootstrap_paths)=='table' and #spec.bootstrap_paths==count,'explicit private bootstrap PA paths required')
  local parent=assert(spec.seed_iob):gsub('\\','/'):match('^(.*)/')
  for _,extension in ipairs({'.lua','.fly2','.ion','.con','.rec','.wgem'}) do
    local path=spec.seed_iob:gsub('%.iob$',extension)
    local handle=io.open(path,'rb')
    if handle then handle:close();error('seed has an unexpected source/Program companion: '..path) end
  end
  for index,path in ipairs(spec.bootstrap_paths) do
    assert(path:gsub('\\','/')==parent..string.format('/iob_seed_placeholder_%02d.pa0',index),
      'bootstrap must use distinct seed-local placeholder names')
    local handle=io.open(path,'rb')
    if handle then handle:close();error('bootstrap placeholder already exists') end
  end
  for _,path in ipairs(spec.bootstrap_paths) do
    local pa=assert(simion.pas:open())
    -- SIMION 2020 pa:size rejects nx<3 (native geometry readback, 2026-11-04).
    -- These are private container inputs, never solved fields or particle sources.
    pa:size(3,3,3);pa.symmetry='3dplanar';pa.potential_type='electric'
    pa.dx_mm,pa.dy_mm,pa.dz_mm=1,1,1
    pa:save(path);pa:close();bootstrap[#bootstrap+1]=path
  end
end
simion.command('"'..assert(spec.seed_iob)..'"')
assert(#simion.wb.instances==count, 'public container must contain the declared slots')
do
  -- Inspect all loaded paths before changing any slot: no author PA may be
  -- silently read and then replaced to conceal a failed relative seed.
  local reference=assert(simion.pas:open())
  -- SIMION 2020 instances is indexed userdata, not a Lua table for ipairs.
  for index=1,#simion.wb.instances do
    local item=simion.wb.instances[index]
    reference.path=native_path(spec.bootstrap_paths[index])
    assert(item.pa.path:lower()==reference.path:lower(),'seed loaded a PA outside this private bootstrap')
    assert(item.pa.nx==3 and item.pa.ny==3 and item.pa.nz==3,'seed did not load the minimal neutral bootstrap')
  end
  reference:close()
end

for index,row in ipairs(spec.instances) do
  local item=simion.wb.instances[index]
  item.pa.filename=row.path
  item.pa:load()
  item:_debug_update_size()
  for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
    assert(item.pa[key]==row.grid[key],
      'runtime PA grid differs from provider '..row.role..'.'..key)
  end
  local p=row.placement
  item.x,item.y,item.z=p.x_mm,p.y_mm,p.z_mm
  item.az,item.el,item.rt,item.scale=p.az_deg,p.el_deg,p.rt_deg,p.scale
  if independent_component then item.ox,item.oy,item.oz=0,0,0;verify_fractional_component(item,row) end
  -- The provider's two-dimensional domains are cylindrical. nz_use belongs
  -- only to planar-2D extrusion (SIMION lua_simion.wb instance.nz_use).
end
-- Saving a seed-derived workbench can replace its Program/FLY2 companions.
-- Preserve the prepared bytes, as in the established local frontend builder.
if source_free then
  -- Replace the seed's embedded factory beam definitions with the verified
  -- zero-beam format control. No source is sampled and no Fly is performed.
  simion.wb:load_particles(native_path(spec.empty_particle_control))
else simion.wb:load_particles(stem..'.fly2') end
local okay,message=pcall(function() simion.wb:save(spec.output_iob) end)
for path,data in pairs(companions) do
  local output=assert(io.open(path,'wb'));output:write(data);output:close()
end
assert(okay,message)
do
  -- The independently reopened output is the final path/pose proof; this
  -- process must still verify all real slots before dropping intermediates.
  local reference=assert(simion.pas:open())
  for index,row in ipairs(spec.instances) do
    local item=simion.wb.instances[index]
    reference.path=native_path(row.path)
    assert(item.pa.path:lower()==reference.path:lower(),'geometry slot path differs before publication')
    for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
      assert(item.pa[key]==row.grid[key],'geometry slot grid differs before publication')
    end
    for property,key in pairs({x='x_mm',y='y_mm',z='z_mm',az='az_deg',el='el_deg',rt='rt_deg',scale='scale'}) do
      assert(item[property]==row.placement[key],'geometry slot pose differs before publication')
    end
  end
  reference:close();simion.pas:close()
  for _,path in ipairs(bootstrap) do assert(os.remove(path),'cannot remove owned neutral bootstrap') end
end
if source_free then
  require_zero_particle_control(stem..'.fly2')
  for _,extension in ipairs({'.lua','.ion','.con','.rec','.wgem'}) do
    local handle=io.open(stem..extension,'rb')
    if handle then handle:close();error('geometry save unexpectedly materialized a source/Program companion') end
  end
  if fields_only then print('SINGLE_REFLECTION_FIELD_IOB=PASS SOURCE=False FLY=False REFINE=False')
  else print((independent_component and independent_marker..'=PASS INSTANCES=' or 'SINGLE_REFLECTION_GEOMETRY_IOB=PASS INSTANCES=')..count..' FLY=False SOURCE=False REFINE=False') end
else
  print('SINGLE_REFLECTION_IOB=PASS INSTANCES='..count..' ROLES='..role_list)
end
end
