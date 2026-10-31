-- Populate the public four/five-slot container from an explicit runtime build spec.
-- This is preparation only: no Refine, Fast Adjust, particle flight, or PA save.
-- Slot order is flight tube, reflectron, coupled frontend, detector. Provider
-- placements are already resolved in oatof_global; no placement is inferred.
return function(spec,mode,native_path)
assert(mode=='build' or mode=='verify','unsupported workbench operation')
assert(spec.schema_version==1 and spec.role=='single_reflection_iob_build',
  'unsupported single-reflection IOB build specification')
local count=#spec.instances
assert(count==4 or count==5, 'four physical PA instances and optional entrance refinement are required')
local roles={'flight_tube','reflectron','accelerator','detector','entrance_refinement'}
local role_list=table.concat(roles,',',1,count)
local companions={}
local stem=assert(spec.output_iob):gsub('%.iob$','')
assert(stem~=spec.output_iob, 'output must have .iob extension')
for _,extension in ipairs({'.lua','.fly2'}) do
  local path=stem..extension
  local input=assert(io.open(path,'rb'), 'prepared companion is missing: '..path)
  companions[path]=input:read('*a');input:close()
end
for index,row in ipairs(spec.instances) do
  assert(row.role==roles[index] and row.instance_index==index and row.priority_number==index,
    'IOB role/order differs at slot '..index)
  assert(type(row.path)=='string' and row.path~='', 'runtime PA path is missing')
  for _,key in ipairs({'x_mm','y_mm','z_mm','az_deg','el_deg','rt_deg','scale'}) do
    local value=row.placement[key]
    assert(type(value)=='number' and value==value and math.abs(value)<math.huge,
      'invalid provider placement '..row.role..'.'..key)
  end
end
if mode=='verify' then
  assert(type(spec.response_fields)=='table','prepared response field paths are required')
  local interfaces=assert(spec.interface_field_probes,'resolved interface field probes are required')
  assert(#interfaces==2,'OA exit and reflectron entry interface probes are required')
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
  -- A separate process opens the saved workbench; never replace its PA paths,
  -- placements or particle controls while checking the persisted assembly.
  simion.command('"'..spec.output_iob..'"')
  assert(#simion.wb.instances==count,'saved workbench must contain the declared slots')
  -- SIMION2020 pa.path setter normalizes absolute/relative path components
  -- (official lua_simion.pas.html#pa.path). Use an unloaded temporary PA so
  -- saved ../ spellings are resolved without changing or reloading a slot.
  local path_reference=simion.pas:open()
  local function path_key(path)
    path_reference.path=native_path(path)
    return assert(path_reference.path):lower()
  end
  for index,row in ipairs(spec.instances) do
    local item=simion.wb.instances[index]
    -- SIMION2020 lua_simion.pas.html#pa.path is the normalized absolute path;
    -- pa.filename deliberately returns only the basename.
    assert(path_key(item.pa.path)==path_key(row.path),'saved PA path differs at slot '..index)
    for _,key in ipairs({'nx','ny','nz','dx_mm','dy_mm','dz_mm'}) do
      assert(item.pa[key]==row.grid[key],'saved PA grid differs: '..row.role..'.'..key)
    end
    for property,key in pairs({x='x_mm',y='y_mm',z='z_mm',az='az_deg',el='el_deg',rt='rt_deg',scale='scale'}) do
      assert(item[property]==row.placement[key],'saved provider placement differs: '..row.role..'.'..key)
    end
  end
  path_reference:close()
  for path,data in pairs(companions) do
    local input=assert(io.open(path,'rb'),'saved companion is missing: '..path)
    local actual=input:read('*a');input:close()
    assert(actual==data,'workbench reopening changed a prepared companion: '..path)
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
  print('SINGLE_REFLECTION_IOB_REOPEN=PASS INSTANCES='..count..' PRIORITY_ORDER='..role_list..' FLY=False')
  return
end
simion.command('"'..assert(spec.seed_iob)..'"')
assert(#simion.wb.instances==count, 'public container must contain the declared slots')
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
  -- The provider's two-dimensional domains are cylindrical. nz_use belongs
  -- only to planar-2D extrusion (SIMION lua_simion.wb instance.nz_use).
end
-- Saving a seed-derived workbench can replace its Program/FLY2 companions.
-- Preserve the prepared bytes, as in the established local frontend builder.
simion.wb:load_particles(stem..'.fly2')
local okay,message=pcall(function() simion.wb:save(spec.output_iob) end)
for path,data in pairs(companions) do
  local output=assert(io.open(path,'wb'));output:write(data);output:close()
end
assert(okay,message)
print('SINGLE_REFLECTION_IOB=PASS INSTANCES='..count..' ROLES='..role_list)
end
