-- Official scalar-V field_array consumer; collision PAs remain independent.
simion.early_access(8.2)
local function load_native_field(binding, reuse_workbench)
  local pa
  local crop = binding.memory_consumer_crop
  local size = crop and crop.consumer_dimensions or binding.dimensions
  if crop then
    assert(not reuse_workbench and (binding.name=='positive_integer_grid_a'
      or binding.name=='negative_integer_grid_a'), 'memory consumer crop requires a non-WB mirror window')
    local known={source_dimensions=true,consumer_dimensions=true,start_grid=true,width_grid=true}
    local count=0
    for key in pairs(crop) do assert(known[key], 'unknown memory consumer crop field');count=count+1 end
    assert(count==4, 'complete memory consumer crop descriptor required')
    for _,key in ipairs({'source_dimensions','consumer_dimensions','start_grid','width_grid'}) do
      assert(type(crop[key])=='table' and #crop[key]==3, 'memory consumer crop triple required')
    end
    assert(binding.symmetry=='x' and binding.origin_mm[1]==0, 'memory crop requires the unchanged x mirror origin')
    for a=1,3 do
      local full,consumer=crop.source_dimensions[a],size[a]
      assert(type(full)=='number' and full==math.floor(full) and full==binding.dimensions[a],
        'memory crop source dimensions differ from frozen binding')
      assert(type(consumer)=='number' and consumer==math.floor(consumer) and consumer>=5
        and crop.start_grid[a]==0 and crop.width_grid[a]==consumer-1,
        'memory crop requires origin-preserving integer support')
      assert((a==1 and consumer<full) or (a~=1 and consumer==full), 'only mirror x support may be cropped')
      local box=assert(binding.active_box_mm, 'memory crop requires the unchanged active box')[a]
      local lower,upper=(box[1]-binding.origin_mm[a])/binding.pitch_mm[a],
        (box[2]-binding.origin_mm[a])/binding.pitch_mm[a]
      if a==1 then lower=0;upper=math.max(math.abs(box[1]),math.abs(box[2]))/binding.pitch_mm[a] end
      assert((a==1 or math.floor(lower)-1>=0) and math.ceil(upper)+1<consumer,
        'memory crop lacks complete active-box gradient halo')
    end
  end
  local function same_path(path)
    return type(path)=='string' and path:gsub('\\','/'):lower()==binding.scalar_pa:gsub('\\','/'):lower()
  end
  local function matches_shape(candidate, dimensions)
    return candidate and same_path(candidate.path) and candidate.symmetry=='3dplanar[x]'
      and candidate.nx==dimensions[1] and candidate.ny==dimensions[2]
      and candidate.nz==dimensions[3] and candidate.dx_mm==binding.pitch_mm[1]
      and candidate.dy_mm==binding.pitch_mm[2] and candidate.dz_mm==binding.pitch_mm[3]
  end
  local function matches(candidate)
    return matches_shape(candidate,size) or (crop and matches_shape(candidate,crop.source_dimensions))
  end
  if crop and simion.wb and simion.wb.instances then
    for index=1,#simion.wb.instances do
      assert(not same_path(simion.wb.instances[index].pa.path), 'memory crop must not mutate a WB-owned PA')
    end
  end
  if reuse_workbench and simion.wb and simion.wb.instances then
    -- Official existing-object access: https://simion.com/info/lua_simion.pas.html
    -- Native static consumption never modifies this shared collision PA.
    -- Workbench instances are SIMION userdata: use the same length/index API
    -- as build_native_corridor_iob.lua, not table-only ipairs.
    for index=1,#simion.wb.instances do
      local instance=simion.wb.instances[index]
      local candidate=instance.pa
      if matches(candidate) then
        pa=candidate;break
      end
    end
  end
  local reused=pa~=nil
  local existing_reused=false
  if not pa then
    -- Official integer PA-container API, no private cache or PA ownership change:
    -- https://simion.com/info/lua_simion.pas.html
    for index=1,#simion.pas do
      local candidate=simion.pas[index]
      if matches(candidate) then pa=candidate;existing_reused=true;break end
    end
  end
  pa=pa or assert(simion.pas:open(binding.scalar_pa))
  print('MRTOF_NATIVE_PA_LOAD workbench_reused='..tostring(reused)
    ..' existing_pa_reused='..tostring(existing_reused)..' path='..binding.scalar_pa)
  local pitch = binding.pitch_mm
  if crop then
    local cropped=false
    if matches_shape(pa,crop.source_dimensions) then
      assert(pa.crop, 'official PA crop API required')
      -- Official SIMION 8.1.1.22+ preserves fractional surfaces in pa:crop.
      -- Keep origin, pitch, active routing and all retained node values. The
      -- source file and independent WB collision PAs are never saved/modified.
      -- https://simion.com/info/lua_simion.pas.html (reviewed 2026-10-16).
      pa:crop(crop.start_grid[1],crop.start_grid[2],crop.start_grid[3],
        crop.width_grid[1],crop.width_grid[2],crop.width_grid[3],false)
      cropped=true
    end
    assert(matches_shape(pa,size), 'memory consumer crop dimensions/pitch/mirror differ')
    print('MRTOF_NATIVE_PA_MEMORY_CROP name='..binding.name..' performed='..tostring(cropped)
      ..' source_nx='..crop.source_dimensions[1]..' consumer_nx='..size[1]..' save=false refine=false')
  end
  assert(binding.symmetry == 'x' and pa.symmetry == '3dplanar[x]', 'native PA requires actual x mirror')
  assert(pa.nx == size[1] and pa.ny == size[2] and pa.nz == size[3], 'native dimensions differ')
  assert(pa.dx_mm == pitch[1] and pa.dy_mm == pitch[2] and pa.dz_mm == pitch[3], 'native pitch differs')
  local verified_lo,verified_hi
  local function field(x,y,z,sample_potential)
    local q={(x-binding.origin_mm[1])/pitch[1],(y-binding.origin_mm[2])/pitch[2],
      (z-binding.origin_mm[3])/pitch[3]}
    local lo,hi={},{}
    for a=1,3 do
      local u=a==1 and math.abs(q[a]) or q[a]
      lo[a],hi[a]=math.floor(u)-1,math.ceil(u)+1
      assert((a==1 or lo[a]>=0) and hi[a]<size[a], 'NUMERICAL_COVERAGE_FAILURE NATIVE_SUPPORT_OUTSIDE')
    end
    -- Native static PAs are immutable during flight. Cache only the last fully
    -- checked integer support box; every new box must still fail on bad support.
    local verified=verified_lo~=nil
    for a=1,3 do
      if not verified or lo[a]~=verified_lo[a] or hi[a]~=verified_hi[a] then verified=false;break end
    end
    if not verified then
      for k=lo[3],hi[3] do for j=lo[2],hi[2] do for i=lo[1],hi[1] do
        local v=pa:potential(math.abs(i),j,k)
        assert(type(v)=='number' and v==v and math.abs(v)<math.huge,
          'NUMERICAL_COVERAGE_FAILURE NATIVE_SUPPORT_NONFINITE')
      end end end
      verified_lo,verified_hi=lo,hi
    end
    assert(pa:inside_vc(unpack(q)), 'NUMERICAL_COVERAGE_FAILURE NATIVE_DOMAIN_EXIT')
    -- Official field_vc uses grid coordinates and native mirror semantics.
    -- Match the measured native chain: divide each component by its own axis pitch.
    local ex,ey,ez=pa:field_vc(unpack(q))
    for _,v in ipairs({ex,ey,ez}) do
      assert(type(v)=='number' and v==v and math.abs(v)<math.huge,
        'NUMERICAL_COVERAGE_FAILURE NATIVE_FIELD_UNAVAILABLE')
    end
    assert(ex and ey and ez, 'NUMERICAL_COVERAGE_FAILURE NATIVE_FIELD_UNAVAILABLE')
    if sample_potential then
      local v=pa:potential_vc(unpack(q))
      assert(type(v)=='number' and v==v and math.abs(v)<math.huge,
        'NUMERICAL_COVERAGE_FAILURE NATIVE_POTENTIAL_UNAVAILABLE')
      return ex/pitch[1],ey/pitch[2],ez/pitch[3],v
    end
    return ex/pitch[1],ey/pitch[2],ez/pitch[3]
  end
  return field
end

local function load_field(binding, shared_mask, reuse_workbench)
  if binding.mode == 'native_static_pa' then return load_native_field(binding, reuse_workbench) end
  local pitch = binding.pitch_mm
  assert(type(pitch) == 'table' and #pitch == 3, 'pitch_mm must be [dx,dy,dz]')
  for a=1,3 do
    assert(type(pitch[a]) == 'number' and pitch[a] == pitch[a]
      and pitch[a] > 0 and pitch[a] < math.huge, 'invalid scalar axis spacing')
  end
  local pa = assert(simion.pas:open(binding.scalar_pa))
  local mask = shared_mask or assert(simion.pas:open(binding.valid_pa))
  assert(pa.symmetry == '3dplanar' and mask.symmetry == '3dplanar', 'scalar field cannot use PA mirrors')
  assert(pa.nx == mask.nx and pa.ny == mask.ny and pa.nz == mask.nz, 'V/mask dimensions differ')
  assert(pa.dx_mm == pitch[1] and pa.dy_mm == pitch[2] and pa.dz_mm == pitch[3], 'scalar pitch differs')
  assert(mask.dx_mm == pitch[1] and mask.dy_mm == pitch[2] and mask.dz_mm == pitch[3], 'mask pitch differs')
  if binding.active_box_mm then
    local box = binding.active_box_mm
    local size = {pa.nx,pa.ny,pa.nz}
    assert(type(box) == 'table' and #box == 3, 'invalid refinement active_box_mm')
    for a=1,3 do
      assert(type(box[a]) == 'table' and #box[a] == 2, 'invalid refinement axis bounds')
      local lower,upper = box[a][1],box[a][2]
      assert(type(lower) == 'number' and type(upper) == 'number' and lower < upper
        and math.abs(lower) < math.huge and math.abs(upper) < math.huge, 'invalid refinement axis bounds')
      local qlo,qhi = (lower-binding.origin_mm[a])/pitch[a],(upper-binding.origin_mm[a])/pitch[a]
      assert(math.floor(qlo)-1 >= 0 and math.ceil(qhi)+1 < size[a], 'refinement box lacks support halo')
    end
  end
  -- Official electrode() setter changes only the in-memory interpolation marker.
  -- The independent workbench collision PAs are untouched; never save this PA.
  -- Authority: frozen OA ideal_sheet_mm projected by static_field_binding.py.
  local marked, skipped, maximum_roundoff_v = 0, 0, 0
  for _,sheet in ipairs(assert(binding.ideal_sheet_projection, 'missing frozen OA sheet projection')) do
    assert(sheet.k >= 0 and sheet.k < pa.nz and sheet.i_min >= 0 and sheet.i_max < pa.nx
      and sheet.j_min >= 0 and sheet.j_max < pa.ny, 'OA sheet projection outside scalar grid')
    for j=sheet.j_min,sheet.j_max do for i=sheet.i_min,sheet.i_max do
      if mask:potential(i,j,sheet.k) == 1 then
        local v = pa:potential(i,j,sheet.k)
        assert(v == v and math.abs(v) < math.huge, 'NUMERICAL_COVERAGE_FAILURE SHEET_NONFINITE')
        pa:electrode(i,j,sheet.k,true)
        local after = pa:potential(i,j,sheet.k)
        local delta = math.abs(after-v)
        -- Official PA encoding adds/subtracts 2*max_voltage for electrode bits.
        -- Allow only binary64 encoding roundoff, not a physical voltage tolerance.
        -- Installed official examples/pa2text uses debug_max_voltage for this header.
        local roundoff = 8*2^-52*math.max(1,math.abs(2*pa.debug_max_voltage+v))
        assert(delta <= roundoff, 'OA sheet marker changed potential beyond encoding roundoff')
        maximum_roundoff_v = math.max(maximum_roundoff_v,delta)
        marked = marked + 1
      else skipped = skipped + 1 end
    end end
  end
  print('MRTOF_SCALAR_SHEET_MARKERS marked='..marked..' invalid_skipped='..skipped
    ..' maximum_encoding_roundoff_v='..string.format('%.17g',maximum_roundoff_v)..' no_save=true')
  local fa = simion.experimental.field_array{V=pa, type='V', antimirror=''}
  local function field(x, y, z, sample_potential, support)
    local shared = support and support.mask == mask
    local local_mm,lo,hi
    if shared then
      local_mm,lo,hi = support.local_mm,support.lo,support.hi
    else
      local_mm = {x-binding.origin_mm[1], y-binding.origin_mm[2], z-binding.origin_mm[3]}
      lo,hi = {},{}
      local size = {pa.nx,pa.ny,pa.nz}
      for a=1,3 do
        local q = local_mm[a]/pitch[a]
        lo[a], hi[a] = math.floor(q)-1, math.ceil(q)+1
        assert(lo[a] >= 0 and hi[a] < size[a], 'NUMERICAL_COVERAGE_FAILURE V_SUPPORT_BOX_OUTSIDE')
      end
    end
    -- Existing measured support envelope, without extrapolation or fill-zero.
    for k=lo[3],hi[3] do for j=lo[2],hi[2] do for i=lo[1],hi[1] do
      if not shared then
        assert(mask:potential(i,j,k) == 1, 'NUMERICAL_COVERAGE_FAILURE V_SUPPORT_UNKNOWN')
      end
      local v = pa:potential(i,j,k)
      assert(v == v and math.abs(v) < math.huge, 'NUMERICAL_COVERAGE_FAILURE V_SUPPORT_NONFINITE')
    end end end
    if support and not shared then
      support.mask,support.local_mm,support.lo,support.hi = mask,local_mm,lo,hi
    end
    if sample_potential then
      -- Official potential_vc uses grid units; field_array.efield uses mm.
      -- https://simion.com/info/lua_simion.pas.html
      local ex,ey,ez = fa.efield(unpack(local_mm))
      local v = pa:potential_vc(local_mm[1]/pitch[1],local_mm[2]/pitch[2],local_mm[3]/pitch[3])
      return ex,ey,ez,v
    end
    return fa.efield(unpack(local_mm))
  end
  return field,mask
end

local function load_routed_field(binding, shared_masks)
  local masks = shared_masks or {}
  local base,mask = load_field(binding,masks[1],true)
  masks[1] = mask
  local windows = {}
  if binding.refinement_windows ~= nil then
    assert(type(binding.refinement_windows) == 'table', 'refinement_windows must be an ordered list')
    for index,window in ipairs(binding.refinement_windows) do
      assert(type(window.name) == 'string' and window.name ~= '' and window.active_box_mm,
        'refinement window requires name and active_box_mm')
      local shadowed
      if binding.mode=='native_static_pa' and window.mode=='native_static_pa' then
        local box=window.active_box_mm
        assert(type(box)=='table' and #box==3, 'invalid refinement active_box_mm')
        for a=1,3 do
          assert(type(box[a])=='table' and #box[a]==2, 'invalid refinement axis bounds')
          local lower,upper=box[a][1],box[a][2]
          assert(type(lower)=='number' and type(upper)=='number' and lower<upper
            and math.abs(lower)<math.huge and math.abs(upper)<math.huge, 'invalid refinement axis bounds')
          local qlo=(lower-window.origin_mm[a])/window.pitch_mm[a]
          local qhi=(upper-window.origin_mm[a])/window.pitch_mm[a]
          if a==1 then qlo=0;qhi=math.max(math.abs(lower),math.abs(upper))/window.pitch_mm[a] end
          assert((a==1 or math.floor(qlo)-1>=0) and math.ceil(qhi)+1<window.dimensions[a],
            'refinement box lacks support halo')
        end
        -- First-match inclusive routing: one earlier native box must contain
        -- the whole box. Never combine partial boxes or change binding metadata.
        for _,prior in ipairs(windows) do
          if prior.native then
            local contained=true
            for a=1,3 do
              if box[a][1]<prior.box[a][1] or box[a][2]>prior.box[a][2] then contained=false;break end
            end
            if contained then shadowed=prior.name;break end
          end
        end
      end
      if shadowed then
        print('MRTOF_NATIVE_PA_LOAD skip_shadowed=true name='..window.name..' covered_by='..shadowed)
      else
        local window_field,window_mask = load_field(window,masks[index+1])
        masks[index+1] = window_mask
        windows[#windows+1] = {box=window.active_box_mm,field=window_field,name=window.name,
          native=window.mode=='native_static_pa'}
      end
    end
  end
  local function field(x,y,z,sample_potential,support)
    if binding.consumer_view then
      assert(binding.consumer_view=='x_symmetry_plane' and x==0,
        'NUMERICAL_COVERAGE_FAILURE CENTER_VIEW_OFF_PLANE')
    end
    local xyz = {x,y,z}
    for _,window in ipairs(windows) do
      local inside = true
      for a=1,3 do
        if xyz[a] < window.box[a][1] or xyz[a] > window.box[a][2] then inside = false;break end
      end
      -- Inclusive boxes, first match wins. No blending or unknown-to-base fallback.
      if inside then return window.field(x,y,z,sample_potential,support) end
    end
    return base(x,y,z,sample_potential,support)
  end
  return field,masks
end

local function expose(field, mode)
  assert(mode == nil or mode == 'raw_sample', 'unsupported scalar query mode')
  if mode == 'raw_sample' then
    -- Verification only: same E/support/routes, plus interpolated scalar V.
    return function(x,y,z)
      local ex,ey,ez,v = field(x,y,z,true)
      return v,ex,ey,ez
    end
  end
  return simion.experimental.make_efield_adjust(field)
end

return function(binding, mode)
  if binding.response_terms == nil then
    return expose(load_routed_field(binding),mode)
  end
  assert(type(binding.response_terms) == 'table' and #binding.response_terms >= 2
    and #binding.response_terms <= 5, 'PS response combination requires baseline and one to four axes')
  local terms={}
  -- Binding compilation proves identical sealed masks at each ordered level.
  -- Share only these read-only PAs within this combination; V/support stay per term.
  local shared_masks
  for _,term in ipairs(binding.response_terms) do
    assert(type(term.coefficient)=='number' and term.coefficient==term.coefficient
      and math.abs(term.coefficient)<math.huge and term.response_terms==nil, 'invalid response coefficient/nesting')
    if term.coefficient~=0 then
      local field,masks = load_routed_field(term,shared_masks)
      shared_masks = masks
      terms[#terms+1]={coefficient=term.coefficient,field=field}
    end
  end
  return expose(function(x,y,z,sample_potential)
    local ex,ey,ez=0,0,0
    local v=0
    -- Fresh for this query only; differing routed mask levels recheck support.
    local support={}
    for _,term in ipairs(terms) do
      if term.coefficient~=0 then
        local ax,ay,az,av=term.field(x,y,z,sample_potential,support)
        ex,ey,ez=ex+term.coefficient*ax,ey+term.coefficient*ay,ez+term.coefficient*az
        if sample_potential then v=v+term.coefficient*av end
      end
    end
    if sample_potential then return ex,ey,ez,v end
    return ex,ey,ez
  end,mode)
end
