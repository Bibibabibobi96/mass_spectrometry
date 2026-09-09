-- Compare one solved local PA response with its coarse parent response on all
-- six patch faces.  This is device-neutral: the caller owns geometry, voltage
-- grouping, origins, mesh choice, sampling stride, and acceptance criteria.
--
-- Usage:
-- simion --nogui lua compare_dirichlet_patch_interface.lua
--   LOCAL_SOLVED_PA LOCAL_RAW_PA SOURCE_PA_PATHS_PIPE_SEPARATED
--   SOURCE_PROJECT_ORIGIN_X,Y,Z PATCH_PROJECT_ORIGIN_X,Y,Z OUTPUT_CSV
--   STRIDE SAMPLING_MODE(native_all_nodes|matched_lattice)

local local_path=assert(arg[1], 'solved local PA required')
local raw_path=assert(arg[2], 'raw local PA required')
local source_text=assert(arg[3], 'coarse response PA path list required')
local source_origin_text=assert(arg[4], 'coarse project origin required')
local patch_origin_text=assert(arg[5], 'patch project origin required')
local output_path=assert(arg[6], 'output CSV required')
local stride=arg[7] and assert(tonumber(arg[7]), 'stride must be numeric') or 1
local sampling_mode=arg[8] or 'matched_lattice'
assert(stride==math.floor(stride) and stride>0, 'stride must be a positive integer')
assert(sampling_mode=='native_all_nodes' or sampling_mode=='matched_lattice',
  'sampling mode must be native_all_nodes or matched_lattice')
assert(sampling_mode~='native_all_nodes' or stride==1,
  'native_all_nodes sampling requires stride 1')

local function split(text, pattern)
  local values={}
  for value in text:gmatch(pattern) do values[#values+1]=value end
  return values
end

local function triple(text, label)
  local values={}
  for value in text:gmatch('[^,]+') do
    values[#values+1]=assert(tonumber(value), label..' contains a non-number')
  end
  assert(#values==3, label..' must contain three values')
  return values
end

local source_paths=split(source_text, '[^|]+')
assert(#source_paths>0, 'at least one coarse response PA is required')
local source_origin=triple(source_origin_text, 'coarse project origin')
local patch_origin=triple(patch_origin_text, 'patch project origin')
local local_pa=assert(simion.pas:open(local_path), 'cannot open solved local PA')
local raw_pa=assert(simion.pas:open(raw_path), 'cannot open raw local PA')
assert(local_pa.nx==raw_pa.nx and local_pa.ny==raw_pa.ny and local_pa.nz==raw_pa.nz,
  'local solved and raw PA shapes differ')
assert(local_pa.dx_mm==raw_pa.dx_mm and local_pa.dy_mm==raw_pa.dy_mm and
  local_pa.dz_mm==raw_pa.dz_mm, 'local solved and raw PA scales differ')
local sources={}
for _,path in ipairs(source_paths) do
  local pa=assert(simion.pas:open(path), 'cannot open coarse response PA: '..path)
  assert(pa.dx_mm>0 and pa.dy_mm>0 and pa.dz_mm>0, 'coarse PA scale must be positive')
  sources[#sources+1]=pa
end

local dimensions={local_pa.nx,local_pa.ny,local_pa.nz}
local spacing={local_pa.dx_mm,local_pa.dy_mm,local_pa.dz_mm}
local faces={
  {name='x_min',axis=1,fixed=0,inward=1,outward=-1,u=2,v=3},
  {name='x_max',axis=1,fixed=local_pa.nx-1,inward=-1,outward=1,u=2,v=3},
  {name='y_min',axis=2,fixed=0,inward=1,outward=-1,u=1,v=3},
  {name='y_max',axis=2,fixed=local_pa.ny-1,inward=-1,outward=1,u=1,v=3},
  {name='z_min',axis=3,fixed=0,inward=1,outward=-1,u=1,v=2},
  {name='z_max',axis=3,fixed=local_pa.nz-1,inward=-1,outward=1,u=1,v=2},
}

local function coarse_potential_and_field(project,axis)
  local potential,field=0,0
  for _,source in ipairs(sources) do
    local coordinates={
      (project[1]-source_origin[1])/source.dx_mm,
      (project[2]-source_origin[2])/source.dy_mm,
      (project[3]-source_origin[3])/source.dz_mm,
    }
    assert(source:inside_vc(coordinates[1],coordinates[2],coordinates[3]),
      'interface sample lies outside a coarse response PA')
    potential=potential+source:potential_vc(coordinates[1],coordinates[2],coordinates[3])
    local ex,ey,ez=source:field_vc(coordinates[1],coordinates[2],coordinates[3])
    local fields={ex or 0,ey or 0,ez or 0}
    local source_spacing={source.dx_mm,source.dy_mm,source.dz_mm}
    field=field+fields[axis]/source_spacing[axis]
  end
  return potential,field
end

local output=assert(io.open(output_path,'w'))
output:write('face,total_nodes,vacuum_potential_samples,field_samples,face_physical_nodes,',
  'near_physical_vacuum_nodes,',
  'max_abs_potential_V,rms_potential_V,',
  'max_abs_normal_field_V_per_mm,rms_normal_field_V_per_mm,',
  'max_abs_reference_potential_V,max_abs_reference_normal_field_V_per_mm\n')
local total_samples=0
for _,face in ipairs(faces) do
  local potential_count,field_count,face_physical_count,near_physical_count=0,0,0,0
  local max_dp,sum_dp2,max_df,sum_df2,max_p,max_f=0,0,0,0,0,0
  local first_start,first_end,second_start,second_end
  if sampling_mode=='native_all_nodes' then
    first_start=0;first_end=dimensions[face.u]-1
    second_start=0;second_end=dimensions[face.v]-1
  else
    -- Keep a one-sample-spacing guard from face edges and align physical
    -- coordinates between a 1-mm patch and a 0.5-mm patch with stride 2.
    first_start=stride;first_end=dimensions[face.u]-1-stride
    second_start=stride;second_end=dimensions[face.v]-1-stride
  end
  for first=first_start,first_end,stride do
    for second=second_start,second_end,stride do
      local node={0,0,0}
      node[face.axis]=face.fixed
      node[face.u]=first
      node[face.v]=second
      local inside_node={node[1],node[2],node[3]}
      inside_node[face.axis]=inside_node[face.axis]+face.inward
      local _,face_physical=raw_pa:point(node[1],node[2],node[3])
      local _,inside_physical=raw_pa:point(
        inside_node[1],inside_node[2],inside_node[3])
      local face_project={
        patch_origin[1]+node[1]*spacing[1],
        patch_origin[2]+node[2]*spacing[2],
        patch_origin[3]+node[3]*spacing[3],
      }
      if face_physical then
        -- A physical boundary node is owned by the electrode voltage, not by
        -- the sampled Dirichlet vacuum boundary.  In a SIMION solution array
        -- its raw point value may also encode a basis/electrode convention,
        -- so comparing it with an interpolated vacuum potential is invalid.
        face_physical_count=face_physical_count+1
      else
        local coarse_face=coarse_potential_and_field(face_project,face.axis)
        -- Read the Dirichlet vacuum node itself.  potential_vc() applies
        -- interpolation semantics at electrode nodes and is intentionally
        -- not used here.
        local local_face=local_pa:point(node[1],node[2],node[3])
        local dp=local_face-coarse_face
        potential_count=potential_count+1
        max_dp=math.max(max_dp,math.abs(dp));sum_dp2=sum_dp2+dp*dp
        max_p=math.max(max_p,math.abs(coarse_face))
      end
      if not face_physical and inside_physical then
        near_physical_count=near_physical_count+1
      elseif not face_physical then
        local inside_half={node[1],node[2],node[3]}
        inside_half[face.axis]=inside_half[face.axis]+0.5*face.inward
        local lx,ly,lz=local_pa:field_vc(inside_half[1],inside_half[2],inside_half[3])
        local local_fields={lx or 0,ly or 0,lz or 0}
        local local_normal=local_fields[face.axis]/spacing[face.axis]
        local outside_project={face_project[1],face_project[2],face_project[3]}
        outside_project[face.axis]=outside_project[face.axis]+
          0.5*face.outward*spacing[face.axis]
        local _,coarse_normal=coarse_potential_and_field(outside_project,face.axis)
        local df=local_normal-coarse_normal
        field_count=field_count+1
        max_df=math.max(max_df,math.abs(df));sum_df2=sum_df2+df*df
        max_f=math.max(max_f,math.abs(coarse_normal))
      end
    end
  end
  assert(potential_count>0 and field_count>0,
    'interface face has no potential or vacuum-field samples: '..face.name)
  local total_count=potential_count+face_physical_count
  assert(field_count+near_physical_count==potential_count,
    'vacuum interface node accounting differs: '..face.name)
  total_samples=total_samples+total_count
  output:write(string.format('%s,%d,%d,%d,%d,%d,%.15g,%.15g,%.15g,%.15g,%.15g,%.15g\n',
    face.name,total_count,potential_count,field_count,face_physical_count,near_physical_count,
    max_dp,math.sqrt(sum_dp2/potential_count),
    max_df,math.sqrt(sum_df2/field_count),max_p,max_f))
end
output:close()
local_pa:close();raw_pa:close()
for _,source in ipairs(sources) do source:close() end
print(string.format('DIRICHLET_PATCH_INTERFACE=PASS samples=%d stride=%d mode=%s output=%s',
  total_samples,stride,sampling_mode,output_path))
