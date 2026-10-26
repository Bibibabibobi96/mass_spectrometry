-- Read-only SIMION 2020 ordinary-PA adapter; called by the managed owner.
-- Official target-version source: docs/simion.chm, lua_simion.pas.html,
-- pa:field_vc: negative potential gradient in V/gu, coordinates in gu.
-- Online abridged reference: https://simion.com/info/lua_simion.pas.html
-- No Refine, Fast Adjust, PA save, workbench, particle, or comparison policy.
local function finite(value)
  return type(value)=='number' and value==value and math.abs(value)<math.huge
end

return function(pa_path, plan, output_csv, facts_path)
  assert(plan.schema_version==1 and plan.role=='oatof_paired_accelerator_static_field_plan', 'paired plan required')
  assert(plan.coordinate_frame=='oatof_global', 'unsupported coordinate frame')
  assert(pa_path:lower():match('%.pa$'), 'ordinary .pa required')
  local grid=plan.native_geometry_compilation.grid
  local pitch,origin=grid.cell_mm_xyz,grid.instance_origin_mm
  local pa=assert(simion.pas:open(pa_path), 'cannot open ordinary PA')
  local ok,result=pcall(function()
    -- pa.refined is inferred on load, not persisted (SIMION 2020 help).
    -- The managed owner binds the successful ordinary-field build receipt.
    assert(pa.potential_type=='electric', 'ordinary electric PA required')
    assert(pa.nx==grid.dimensions.nx and pa.ny==grid.dimensions.ny and pa.nz==grid.dimensions.nz, 'PA dimensions differ')
    assert(pa.dx_mm==pitch.x and pa.dy_mm==pitch.y and pa.dz_mm==pitch.z, 'PA axis pitches differ')
    local points={}
    local input=assert(io.open(plan.sample_points.path,'r'))
    assert(input:read('*l')=='point_id,x_mm,y_mm,z_mm', 'point columns differ')
    local seen={}
    for line in input:lines() do
      local id,x,y,z=line:match('^([^,]+),([^,]+),([^,]+),([^,]+)$')
      id,x,y,z=tonumber(id),tonumber(x),tonumber(y),tonumber(z)
      assert(finite(id) and id>=0 and id==math.floor(id) and not seen[id], 'invalid or duplicate point_id')
      assert(finite(x) and finite(y) and finite(z), 'nonfinite point coordinate')
      seen[id]=true
      local gx,gy,gz=(x-origin.x)/pa.dx_mm,(y-origin.y)/pa.dy_mm,(z-origin.z)/pa.dz_mm
      assert(pa:inside_vc(gx,gy,gz), 'sample outside PA')
      local ex,ey,ez=pa:field_vc(gx,gy,gz)
      assert(finite(ex) and finite(ey) and finite(ez), 'nonfinite native field')
      points[#points+1]={id,x,y,z,ex,ey,ez}
    end
    input:close()
    assert(#points>0 and #points==plan.sample_points.count, 'point coverage differs')
    local output=assert(io.open(output_csv,'w'))
    output:write('point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n')
    for _,p in ipairs(points) do
      -- Each native component is V/its-axis-gu. Preserve the native sign.
      output:write(string.format('%.0f,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\n',
        p[1],p[2],p[3],p[4],1000*p[5]/pa.dx_mm,1000*p[6]/pa.dy_mm,1000*p[7]/pa.dz_mm))
    end
    output:close()
    local facts=assert(io.open(facts_path,'w'))
    facts:write('backend=SIMION\napi=pa:field_vc\nnative_field_unit=V/gu\nexport_field_unit=V/m\n')
    facts:write('field_sign=negative_potential_gradient\nclaim=field_samples_only_no_equivalence_tolerance\n')
    facts:write(string.format('pa=%s\nnx=%d\nny=%d\nnz=%d\ndx_mm=%.17g\ndy_mm=%.17g\ndz_mm=%.17g\n',
      pa_path,pa.nx,pa.ny,pa.nz,pa.dx_mm,pa.dy_mm,pa.dz_mm))
    facts:write(string.format('origin_mm=%.17g,%.17g,%.17g\npoint_count=%d\n',origin.x,origin.y,origin.z,#points))
    facts:write('point_id,x_mm,y_mm,z_mm,Ex_V_per_gu,Ey_V_per_gu,Ez_V_per_gu\n')
    for _,p in ipairs(points) do
      facts:write(string.format('%.0f,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\n',p[1],p[2],p[3],p[4],p[5],p[6],p[7]))
    end
    facts:close()
    return #points
  end)
  pa:close()
  assert(ok,result)
  return result
end
