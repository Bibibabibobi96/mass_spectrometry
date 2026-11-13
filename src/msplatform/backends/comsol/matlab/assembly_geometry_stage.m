function result = assembly_geometry_stage(projectionPath, modelPath, descriptorPath, validationPath, operation)
% Geometry only: no mesh, physics, studies, solutions, or particle operations.
arguments
    projectionPath (1,:) char
    modelPath (1,:) char
    descriptorPath (1,:) char
    validationPath (1,:) char
    operation (1,:) char {mustBeMember(operation,{'build','reopen'})}
end
import com.comsol.model.util.*
projection=jsondecode(fileread(projectionPath));
assert(~isempty(projection.members) && ~isempty(projection.electrode_groups), ...
    'assembly:Scene','Expected nonempty selected complete scene');
validation=jsondecode(fileread(validationPath));
tag='AssemblyGeometryOnlyDiagnostic';
if strcmp(operation,'build')
    model=ModelUtil.create(tag);
    cleanupModel=onCleanup(@() ModelUtil.remove(tag));
    comp=model.component.create('comp1',true);
    geom=comp.geom.create('geom1',3);
    built=build_assembly_reference_geometry(geom,projection);
    geom.run;
    selected=validate_assembly_reference_selections(comp,'geom1',built, ...
        validation);
    assert(numel(selected.group_keys)==numel(projection.electrode_groups),'assembly:Groups','Incomplete scientific groups');
    assert(~isfile(descriptorPath),'assembly:Write','Descriptor already exists');
    fid=fopen(descriptorPath,'w','n','UTF-8');
    assert(fid>=0,'assembly:Write','Cannot create build descriptor');
    fileCleanup=onCleanup(@() fclose(fid));
    fprintf(fid,'%s',jsonencode(built));
    mphsave(model,modelPath);
else
    model=mphload(modelPath,tag);
    cleanupModel=onCleanup(@() ModelUtil.remove(tag));
    comp=model.component('comp1'); geom=comp.geom('geom1');
    built=jsondecode(fileread(descriptorPath));
    comp.selection.remove('assembly_reference_vacuum_faces');
    comp.selection.remove('assembly_reference_vacuum');
    members=built.members;
    if isstruct(members), members=num2cell(members); end
    for k=1:numel(members)
        if ~strcmp(members{k}.representation_role,'ideal_surface')
            comp.selection.remove(sprintf('assembly_member_adj_%04d',k));
        end
    end
    selected=validate_assembly_reference_selections(comp,'geom1',built, ...
        validation);
    assert(numel(selected.group_keys)==numel(projection.electrode_groups),'assembly:Groups','Cold group selection incomplete');
end
assert(isempty(comp.physics.tags) && isempty(comp.mesh.tags) && ...
    isempty(model.study.tags) && isempty(model.sol.tags),'assembly:NoPhysics', ...
    'Geometry-only model contains an unexpected mesh, physics, study or solution');
result=struct('operation',operation,'member_count',numel(projection.members), ...
    'group_count',numel(projection.electrode_groups),'model_path',modelPath, ...
    'geometry_domains',geom.getNDomains(),'physics_count',0,'mesh_count',0, ...
    'study_count',0,'solver_count',0,'scope','geometry_only', ...
    'group_keys',{selected.group_keys},'group_faces',{selected.group_faces}, ...
    'vacuum_domains',selected.vacuum_domains,'outer_faces',selected.outer_faces);
end
