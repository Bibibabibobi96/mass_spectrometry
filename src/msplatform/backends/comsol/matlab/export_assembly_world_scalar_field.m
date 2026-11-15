function result = export_assembly_world_scalar_field(modelPath, projectionPath, baselinePath, gridPath, headerBytes, outputDirectory)
% Sample an already saved Assembly solution; no Compute, save or particle work.
arguments
    modelPath (1,:) char
    projectionPath (1,:) char
    baselinePath (1,:) char
    gridPath (1,:) char
    headerBytes (1,1) double {mustBeInteger,mustBePositive}
    outputDirectory (1,:) char
end
import com.comsol.model.util.*
projection=jsondecode(fileread(projectionPath));baseline=jsondecode(fileread(baselinePath));grid=jsondecode(fileread(gridPath));
model=mphload(modelPath,'AssemblyWorldScalarExport');cleanupModel=onCleanup(@() ModelUtil.remove('AssemblyWorldScalarExport'));
if isfield(grid,'role') && strcmp(char(grid.role),'assembly_world_scalar_grid_batch')
    entries=grid.entries;
    assert(~isempty(entries),'assembly:GridBatch','Explicit nonempty grids required');
    for i=1:numel(entries)
        entry=entries(i); one=jsondecode(fileread(char(entry.grid_path)));
        value=sample_one(model,projection,baseline,one,modelPath,char(entry.output_directory),headerBytes);
        write_report(char(entry.report_path),value);
    end
    result=struct('status','success','scope','assembly_world_scalar_grid_batch', ...
        'grid_count',numel(entries),'compute_calls',0);
else
    result=sample_one(model,projection,baseline,grid,modelPath,outputDirectory,headerBytes);
end
end

function result=sample_one(model,projection,baseline,grid,modelPath,outputDirectory,headerBytes)
assert(strcmp(char(projection.assembly_frame_id),char(grid.frame_id)),'assembly:Frame','World frame differs');
solution=read_assembly_stationary_solution(model,char(grid.study_tag),char(grid.solution_tag),char(grid.dataset_tag));
vacuum=mphgetselection(model.component('comp1').physics('es').selection);
a=double(vacuum.entities);b=double(baseline.vacuum_domains);
assert(~isempty(a) && isequal(sort(a(:)),sort(b(:))),'assembly:Vacuum','Vacuum selection differs from frozen geometry');
sampler=@(coordinates) mphinterp(model,'V','coord',coordinates,'dataset',char(grid.dataset_tag), ...
    'ext',0,'coorderr','off','selection',vacuum.entities,'recover','off','unit','V');
[potential,valid,finiteFEM,filled,querySeconds]=sample_scalar_grid_blocks(grid,sampler,[]);
assert(filled==0,'assembly:Fill','Assembly export cannot invent conductor values');
geometryLengthUnit=char(model.component('comp1').geom('geom1').lengthUnit());
witness=struct('status','insufficient','index',0,'requested_mm',[],'actual_mm',[], ...
    'geometry_length_unit',geometryLengthUnit);
dimensions=double(grid.dimensions(:).');pitch=double(grid.pitch_mm(:));origin=double(grid.origin_mm(:));
for index=1:numel(valid)
    if ~valid(index),continue,end
    [ix,iy,iz]=ind2sub(dimensions,index);
    requested=origin+pitch.*[ix-1;iy-1;iz-1];
    if ~any(requested~=0),continue,end
    [x,y,z]=mphinterp(model,{'x','y','z'},'coord',requested,'dataset',char(grid.dataset_tag), ...
        'ext',0,'coorderr','off','selection',vacuum.entities,'recover','off','unit',{'mm','mm','mm'});
    actual=double([x;y;z]);
    assert(numel(actual)==3 && all(isfinite(actual)) && ...
        all(abs(actual(:)-requested(:))<=double(grid.coordinate_sanity_mm)), ...
        'assembly:CoordinateUnit','World coordinate witness differs');
    witness=struct('status','verified','index',index,'requested_mm',requested(:).', ...
        'actual_mm',actual(:).','geometry_length_unit',geometryLengthUnit);
    break
end
dimensions=double(grid.dimensions(:).');pitch=double(grid.pitch_mm(:).');
write_raw_payload(fullfile(outputDirectory,'field_v.pa'),potential,headerBytes);
write_raw_payload(fullfile(outputDirectory,'field_valid.pa'),double(valid),headerBytes);
result=struct('status','success','scope','assembly_world_scalar_samples','field_qualification',false, ...
    'model_path',modelPath,'frame_id',grid.frame_id,'origin_mm',grid.origin_mm,'pitch_mm',grid.pitch_mm, ...
    'dimensions',grid.dimensions,'point_count',grid.point_count,'dataset_tag',grid.dataset_tag, ...
    'solution_tag',grid.solution_tag,'study_tag',grid.study_tag,'solution_readback',solution, ...
    'vacuum_domains',vacuum.entities,'fem_valid',finiteFEM,'invalid_count',grid.point_count-nnz(valid), ...
    'filled_conductor_count',filled,'coordinate_mapping','world_identity','compute_calls',0, ...
    'invalid_policy','masked; storage zero is not a valid sample','query_seconds',querySeconds, ...
    'coordinate_witness',witness);
end

function write_report(path,value)
fid=fopen(path,'w','n','UTF-8');
assert(fid>=0,'assembly:Report','Cannot create scalar report');
cleanup=onCleanup(@() fclose(fid));
fprintf(fid,'%s',jsonencode(value));
end

function write_raw_payload(path,values,headerBytes)
% Header bytes are reserved only; Python owns the PA header definition.
assert(~isfile(path),'assembly:OutputExists','Scalar output already exists');
fid=fopen(path,'w','ieee-le');
assert(fid>=0,'assembly:OutputOpen','Cannot create scalar output');
try
    assert(fwrite(fid,zeros(headerBytes,1,'uint8'),'uint8')==headerBytes, ...
        'assembly:OutputWrite','Scalar prefix write failed');
    assert(fwrite(fid,values,'double')==numel(values), ...
        'assembly:OutputWrite','Scalar payload write failed');
    status=fclose(fid);fid=-1;
    assert(status==0,'assembly:OutputClose','Scalar output close failed');
catch errorInfo
    if fid>=0, fclose(fid); end
    rethrow(errorInfo)
end
end
