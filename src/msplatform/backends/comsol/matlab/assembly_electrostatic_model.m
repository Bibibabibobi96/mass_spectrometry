function result = assembly_electrostatic_model(projectionPath, descriptorPath, validationPath, sourcePath, requestPath, outputPath, operation)
% Explicit unsolved Assembly model with physics, mesh and stationary study nodes.
% No mesh run, Compute, particles or GUI; saves the configured MPH for cold reopen.
arguments
    projectionPath (1,:) char
    descriptorPath (1,:) char
    validationPath (1,:) char
    sourcePath (1,:) char
    requestPath (1,:) char
    outputPath (1,:) char
    operation (1,:) char {mustBeMember(operation,{'build','reopen'})}
end
import com.comsol.model.util.*
projection=jsondecode(fileread(projectionPath)); descriptor=jsondecode(fileread(descriptorPath));
validation=jsondecode(fileread(validationPath)); request=jsondecode(fileread(requestPath));
rows=request.group_voltages; if isstruct(rows),rows=num2cell(rows);end
if strcmp(operation,'build')
    assert(~isfile(outputPath),'assembly:Output','Refusing to overwrite model');
    model=mphload(sourcePath,'AssemblyElectrostaticUnsolved');
else
    model=mphload(outputPath,'AssemblyElectrostaticUnsolved');
end
cleanupModel=onCleanup(@() ModelUtil.remove('AssemblyElectrostaticUnsolved'));
comp=model.component('comp1');geom=comp.geom('geom1');
if strcmp(operation,'build')
% Recreate geometry selections before the new physics refers to them.
comp.selection.remove('assembly_reference_vacuum_faces');comp.selection.remove('assembly_reference_vacuum');
members=descriptor.members;if isstruct(members),members=num2cell(members);end
for k=1:numel(members)
    if ~strcmp(members{k}.representation_role,'ideal_surface')
        comp.selection.remove(sprintf('assembly_member_adj_%04d',k));
    end
end
selected=validate_assembly_reference_selections(comp,'geom1',descriptor,validation);
else
    groups=projection.electrode_groups;if isstruct(groups),groups=num2cell(groups);end
    keys=cell(1,numel(groups));faces=cell(1,numel(groups));
    for k=1:numel(groups)
        keys{k}=[char(groups{k}.instance_id) '/' char(groups{k}.electrode_group_id)];
        faces{k}=double(comp.selection(sprintf('assembly_group_%03d',k)).entities());
    end
    selected=struct('group_keys',{keys},'group_faces',{faces}, ...
        'vacuum_domains',double(comp.selection('assembly_reference_vacuum').entities()), ...
        'outer_faces',double(comp.selection('assembly_outer_boundary').entities()));
end
keys=cellfun(@char,selected.group_keys,'UniformOutput',false);
assert(numel(keys)==numel(projection.electrode_groups) && numel(rows)==numel(keys),'assembly:Groups','Group coverage differs');
values=zeros(1,numel(keys));used=false(1,numel(keys));
for k=1:numel(rows)
    row=rows{k}; key=[char(row.instance_id) '/' char(row.electrode_group_id)];idx=find(strcmp(keys,key));
    assert(numel(idx)==1 && ~used(idx) && isfinite(row.voltage_v),'assembly:Voltage','Group voltage differs');
    values(idx)=row.voltage_v;used(idx)=true;
end
assert(all(used),'assembly:Voltage','Missing group voltage');
if strcmp(operation,'build')
    assert(isempty(comp.physics.tags) && isempty(comp.mesh.tags) && isempty(model.study.tags) && isempty(model.sol.tags),'assembly:Input','Geometry must be unsolved');
    es=comp.physics.create('es','Electrostatics','geom1');es.selection.named('assembly_reference_vacuum');
    material=comp.material.create('vacuum','Common');material.selection.named('assembly_reference_vacuum');
    material.propertyGroup('def').set('relpermittivity',sprintf('%.17g',request.relative_permittivity));
    allFaces=[];
    for k=1:numel(keys)
        faces=selected.group_faces{k};assert(~isempty(faces) && isempty(intersect(faces,allFaces)),'assembly:Groups','Shared electrode face');
        name=sprintf('assembly_group_%03d',k);sel=comp.selection.create(name,'Explicit');sel.geom('geom1',2);sel.set(faces);
        feature=es.create(sprintf('assembly_potential_%03d',k),'ElectricPotential',2);feature.selection.named(name);feature.set('V0',sprintf('%.17g[V]',values(k)));allFaces=union(allFaces,faces);
    end
    assert(isempty(intersect(allFaces,selected.outer_faces)),'assembly:Exterior','Exterior overlaps electrode');
    outer=comp.selection.create('assembly_outer_boundary','Explicit');outer.geom('geom1',2);outer.set(selected.outer_faces);
    feature=es.create('assembly_outer_potential','ElectricPotential',2);feature.selection.named('assembly_outer_boundary');feature.set('V0',sprintf('%.17g[V]',request.exterior.voltage_v));
    allsel=comp.selection.create('assembly_electrode_faces','Explicit');allsel.geom('geom1',2);allsel.set(allFaces);
    mesh=comp.mesh.create('mesh1');mesh.feature('size').set('hauto',request.mesh.global_automatic_level);
    add_comsol_size_feature(mesh,'assembly_electrode_size','Assembly electrode boundary size','geom1',2,'assembly_electrode_faces',request.mesh.electrode_hmax_mm);
    tet=mesh.feature.create('ftet1','FreeTet');tet.selection.named('assembly_reference_vacuum');
    study=model.study.create('std1');stat=study.create('stat','Stationary');
    assert(stat.setSolveFor('/physics/es',true),'assembly:Study','Electrostatics is not selectable for study');
    mphsave(model,outputPath);
else
    es=comp.physics('es');mesh=comp.mesh('mesh1');
end
assert(isempty(model.sol.tags),'assembly:Compute','Unexpected solution object');
verify_assembly_electrostatic_bindings(model,selected,request,keys,values);
result=struct('operation',operation,'scope','assembly_electrostatic_unsolved','model_path',outputPath, ...
    'group_keys',{keys},'group_faces',{selected.group_faces},'group_voltages_v',values, ...
    'vacuum_domains',selected.vacuum_domains,'outer_faces',selected.outer_faces, ...
    'relative_permittivity',request.relative_permittivity,'exterior_voltage_v',request.exterior.voltage_v, ...
    'mesh',request.mesh,'compute_calls',0,'solution_count',0,'model_rewritten',strcmp(operation,'build'));
end
