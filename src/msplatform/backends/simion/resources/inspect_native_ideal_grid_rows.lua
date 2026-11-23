-- Formal-gate support receipt for official SIMION one-row, zero-width ideal grids.
-- Reads raw PA# electrode points through the documented simion.pas PA API.
local accelerator_path=assert(arg[1], 'accelerator PA# is required')
local reflectron_path=assert(arg[2], 'reflectron PA# is required')
local output_path=assert(arg[3], 'receipt path is required')
local accelerator_grid2_id=assert(tonumber(arg[4]), 'accelerator grid2 electrode id is required')
local reflectron_midgrid_id=assert(tonumber(arg[5]), 'reflectron midgrid electrode id is required')
local expected={
  grid1=assert(tonumber(arg[6]), 'grid1 expected row is required'),
  grid2=assert(tonumber(arg[7]), 'grid2 expected row is required'),
  entgrid=assert(tonumber(arg[8]), 'entgrid expected row is required'),
  midgrid=assert(tonumber(arg[9]), 'midgrid expected row is required'),
}

local function axial_rows(path,axis,electrode_id)
  local pa=assert(simion.pas:open(path))
  local rows={}
  local electrode_point_count=0
  for z=0,pa.nz-1 do
    for y=0,pa.ny-1 do
      for x=0,pa.nx-1 do
        local potential,is_electrode=pa:point(x,y,z)
        if is_electrode and math.abs(potential-electrode_id)<1e-9 then
          rows[axis=='x' and x or z]=true
          electrode_point_count=electrode_point_count+1
        end
      end
    end
  end
  local count,actual_row=0,nil
  for row in pairs(rows) do count=count+1; actual_row=row end
  pa:close()
  return {row_count=count,actual_row=actual_row,electrode_point_count=electrode_point_count}
end

local counts={
  grid1=axial_rows(accelerator_path,'z',2),
  grid2=axial_rows(accelerator_path,'z',accelerator_grid2_id),
  entgrid=axial_rows(reflectron_path,'x',1),
  midgrid=axial_rows(reflectron_path,'x',reflectron_midgrid_id),
}
for name,measurement in pairs(counts) do
  assert(measurement.row_count==1,string.format('%s raw PA electrode occupies %d axial rows; expected 1',name,measurement.row_count))
  assert(measurement.electrode_point_count>0,name..' raw PA electrode has no points')
  assert(measurement.actual_row==expected[name],string.format('%s raw PA row is %s; expected %d',name,tostring(measurement.actual_row),expected[name]))
end
local output=assert(io.open(output_path,'w'))
output:write(string.format(
  '{"schema_version":2,"role":"oa_tof_native_ideal_grid_raw_pa_receipt","ideal_grid_model":"simion_one_row_zero_width_native_transmission","grids":{"grid1":{"row_count":%d,"actual_row":%d,"expected_row":%d,"electrode_points":%d},"grid2":{"row_count":%d,"actual_row":%d,"expected_row":%d,"electrode_points":%d},"entgrid":{"row_count":%d,"actual_row":%d,"expected_row":%d,"electrode_points":%d},"midgrid":{"row_count":%d,"actual_row":%d,"expected_row":%d,"electrode_points":%d}}}\n',
  counts.grid1.row_count,counts.grid1.actual_row,expected.grid1,counts.grid1.electrode_point_count,
  counts.grid2.row_count,counts.grid2.actual_row,expected.grid2,counts.grid2.electrode_point_count,
  counts.entgrid.row_count,counts.entgrid.actual_row,expected.entgrid,counts.entgrid.electrode_point_count,
  counts.midgrid.row_count,counts.midgrid.actual_row,expected.midgrid,counts.midgrid.electrode_point_count))
output:close()
print('NATIVE_IDEAL_GRID_RAW_PA_STATUS=PASS')
