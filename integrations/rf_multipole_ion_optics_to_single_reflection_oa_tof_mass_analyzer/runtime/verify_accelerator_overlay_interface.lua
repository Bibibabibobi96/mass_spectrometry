-- Verify a boundary-coupled accelerator PA family against its coarse source.
-- Potential continuity is exact by construction; normal-field jump is reported
-- at paired points just outside/inside each of the six overlay faces.
-- Usage:
--   simion.exe --nogui --noprompt lua verify_accelerator_overlay_interface.lua
--     coarse.pa0 fine.pa0 coarse_ox coarse_oy coarse_oz
--     fine_ox fine_oy fine_oz maximum_electrode report.json

local coarse_pa0=assert(arg[1], 'coarse PA0 is required')
local fine_pa0=assert(arg[2], 'fine PA0 is required')
local coarse_origin={assert(tonumber(arg[3])),assert(tonumber(arg[4])),assert(tonumber(arg[5]))}
local fine_origin={assert(tonumber(arg[6])),assert(tonumber(arg[7])),assert(tonumber(arg[8]))}
local maximum_electrode=assert(tonumber(arg[9]), 'maximum electrode is invalid')
local report_path=assert(arg[10], 'report path is required')

local function indexed(path,index)
  return path:gsub('0$',tostring(index))
end

local function world_to_vc(origin,pa,world)
  return (world[1]-origin[1])/pa.dx_mm,
         (world[2]-origin[2])/pa.dy_mm,
         (world[3]-origin[3])/pa.dz_mm
end

local function physical_field(pa,x,y,z)
  local ex,ey,ez=pa:field_vc(x,y,z)
  return ex/pa.dx_mm,ey/pa.dy_mm,ez/pa.dz_mm
end

local faces={
  {name='x_min',axis=1,index=function(pa) return 0 end,inside=1},
  {name='x_max',axis=1,index=function(pa) return pa.nx-1 end,inside=-1},
  {name='y_min',axis=2,index=function(pa) return 0 end,inside=1},
  {name='y_max',axis=2,index=function(pa) return pa.ny-1 end,inside=-1},
  {name='z_min',axis=3,index=function(pa) return 0 end,inside=1},
  {name='z_max',axis=3,index=function(pa) return pa.nz-1 end,inside=-1},
}

local records={}
local global_potential_residual=0
local global_normal_jump=0
local global_samples=0
for basis=0,maximum_electrode do
  simion.pas:close()
  local coarse=simion.pas:open(indexed(coarse_pa0,basis))
  local fine=simion.pas:open(indexed(fine_pa0,basis))
  local basis_potential_residual=0
  local basis_normal_jump=0
  local basis_samples=0
  local dimensions={fine.nx,fine.ny,fine.nz}
  local cells={fine.dx_mm,fine.dy_mm,fine.dz_mm}
  local coarse_cells={coarse.dx_mm,coarse.dy_mm,coarse.dz_mm}
  for _,face in ipairs(faces) do
    local tangents={}
    for axis=1,3 do if axis~=face.axis then tangents[#tangents+1]=axis end end
    local step1=math.max(1,math.floor((dimensions[tangents[1]]-2)/20))
    local step2=math.max(1,math.floor((dimensions[tangents[2]]-2)/20))
    for a=1,dimensions[tangents[1]]-2,step1 do
    for b=1,dimensions[tangents[2]]-2,step2 do
      local index={0,0,0}
      index[face.axis]=face.index(fine)
      index[tangents[1]]=a
      index[tangents[2]]=b
      local world={
        fine_origin[1]+index[1]*fine.dx_mm,
        fine_origin[2]+index[2]*fine.dy_mm,
        fine_origin[3]+index[3]*fine.dz_mm,
      }
      local cx,cy,cz=world_to_vc(coarse_origin,coarse,world)
      assert(coarse:inside_vc(cx,cy,cz),'overlay boundary escapes coarse PA')
      local residual=math.abs(fine:potential(index[1],index[2],index[3])-coarse:potential_vc(cx,cy,cz))
      if residual>basis_potential_residual then basis_potential_residual=residual end

      local epsilon=math.min(cells[face.axis],coarse_cells[face.axis])/4
      local inside={world[1],world[2],world[3]}
      local outside={world[1],world[2],world[3]}
      inside[face.axis]=inside[face.axis]+face.inside*epsilon
      outside[face.axis]=outside[face.axis]-face.inside*epsilon
      local fix,fiy,fiz=world_to_vc(fine_origin,fine,inside)
      local cox,coy,coz=world_to_vc(coarse_origin,coarse,outside)
      if fine:inside_vc(fix,fiy,fiz) and coarse:inside_vc(cox,coy,coz) then
        local fex,fey,fez=physical_field(fine,fix,fiy,fiz)
        local cex,cey,cez=physical_field(coarse,cox,coy,coz)
        local fine_field={fex,fey,fez}
        local coarse_field={cex,cey,cez}
        local jump=math.abs(fine_field[face.axis]-coarse_field[face.axis])
        -- A standalone SIMION fast-adjust paN stores the response to the
        -- conventional 10000 V basis.  Report per applied volt.
        if basis>0 then jump=jump/10000 end
        if jump>basis_normal_jump then basis_normal_jump=jump end
        basis_samples=basis_samples+1
      end
    end end
  end
  if basis_potential_residual>global_potential_residual then global_potential_residual=basis_potential_residual end
  if basis_normal_jump>global_normal_jump then global_normal_jump=basis_normal_jump end
  global_samples=global_samples+basis_samples
  records[#records+1]=string.format(
    '    {"electrode_id": %d, "sample_count": %d, "maximum_boundary_potential_residual_V": %.17g, "maximum_paired_normal_field_jump_V_per_mm_per_V": %.17g}',
    basis,basis_samples,basis_potential_residual,basis_normal_jump)
end
simion.pas:close()

assert(global_samples>0,'overlay interface verification produced no field samples')
assert(global_potential_residual<=1e-8,'overlay boundary potential continuity failed')
local report=assert(io.open(report_path,'w'))
report:write(string.format(
  '{\n  "schema_version": 1,\n  "role": "simion_accelerator_overlay_interface_verification",\n  "status": "pass",\n  "basis_array_count": %d,\n  "field_sample_count": %d,\n  "maximum_boundary_potential_residual_V": %.17g,\n  "maximum_paired_normal_field_jump_V_per_mm_per_V": %.17g,\n  "basis_records": [\n%s\n  ]\n}\n',
  maximum_electrode+1,global_samples,global_potential_residual,
  global_normal_jump,table.concat(records,',\n')))
report:close()
print(string.format(
  'ACCELERATOR_OVERLAY_INTERFACE=PASS BASIS_COUNT=%d SAMPLES=%d POTENTIAL_RESIDUAL=%.12g MAX_NORMAL_JUMP=%.12g',
  maximum_electrode+1,global_samples,global_potential_residual,global_normal_jump))
