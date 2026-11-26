function result = solve_assembly_pulse_basis(projectionPath, offRequestPath, onRequestPath, sourcePath, outputPath, operation, maximumMeshElements, meshFactsPath)
%SOLVE_ASSEMBLY_PULSE_BASIS COMSOL 6.4 two stationary sequences in one model.
% The owning managed stage must verify inputs/claims and independently reopen.
% withsol requires solutions of the same model, COMSOL 6.4 Reference Manual
% comsol_ref_definitions.21.039 (consulted 2026-11-27). Not natively validated.
assert(any(strcmp(operation,{'compute','reopen'})));
import com.comsol.model.util.*
projection=jsondecode(fileread(projectionPath));
off=jsondecode(fileread(offRequestPath)); on=jsondecode(fileread(onRequestPath));
if strcmp(operation,'compute')
    assert(~isfile(outputPath)); model=mphload(sourcePath,'AssemblyPulseBasis');
else
    model=mphload(outputPath,'AssemblyPulseBasis');
end
cleanup=onCleanup(@() ModelUtil.remove('AssemblyPulseBasis')); %#ok<NASGU>
comp=model.component('comp1'); groups=projection.electrode_groups;
if isstruct(groups),groups=num2cell(groups);end
rowsOff=off.group_voltages;rowsOn=on.group_voltages;
if isstruct(rowsOff),rowsOff=num2cell(rowsOff);end
if isstruct(rowsOn),rowsOn=num2cell(rowsOn);end
assert(numel(groups)==numel(rowsOff) && numel(groups)==numel(rowsOn));
keys=cell(1,numel(groups));faces=cell(1,numel(groups)); voff=zeros(1,numel(groups));von=voff;
for k=1:numel(groups)
    keys{k}=[char(groups{k}.instance_id) '/' char(groups{k}.electrode_group_id)];
    assert(strcmp(keys{k},[char(rowsOff{k}.instance_id) '/' char(rowsOff{k}.electrode_group_id)]) && ...
           strcmp(keys{k},[char(rowsOn{k}.instance_id) '/' char(rowsOn{k}.electrode_group_id)]));
    voff(k)=double(rowsOff{k}.voltage_v);von(k)=double(rowsOn{k}.voltage_v);
    faces{k}=double(comp.selection(sprintf('assembly_group_%03d',k)).entities());
end
selected=struct('group_keys',{keys},'group_faces',{faces}, ...
    'vacuum_domains',double(comp.selection('assembly_reference_vacuum').entities()), ...
    'outer_faces',double(comp.selection('assembly_outer_boundary').entities()));
assert(~isempty(selected.vacuum_domains) && ~isempty(selected.outer_faces));
if strcmp(operation,'compute')
    assert(isempty(model.sol.tags));
    verify_assembly_electrostatic_bindings(model,selected,off,keys,voff);
    assert(isscalar(maximumMeshElements) && isfinite(maximumMeshElements) && ...
        maximumMeshElements > 0 && maximumMeshElements == fix(maximumMeshElements));
    comp.mesh('mesh1').run;
    meshElementCount=double(comp.mesh('mesh1').getNumElem());
    try
        electricPotentialOrder=double(comp.physics('es').prop('ShapeProperty').getInt('order_electricpotential'));
        orderStatus='native_readback';
    catch
        electricPotentialOrder=[];orderStatus='unavailable';
    end
    meshFacts=struct('schema_version',1,'role','native_mesh_facts', ...
        'mesh_element_count',meshElementCount,'maximum_mesh_elements',maximumMeshElements, ...
        'electric_potential_order',electricPotentialOrder,'order_status',orderStatus, ...
        'solver_selection','not_generated_before_study_run','solution_dofs','unavailable_before_solve');
    fid=fopen(meshFactsPath,'w','n','UTF-8');assert(fid>=0);
    fprintf(fid,'%s',jsonencode(meshFacts));fclose(fid);
    fprintf(1,'ASSEMBLY_MESH_ELEMENT_COUNT=%.0f MAXIMUM=%.0f\n',meshElementCount,maximumMeshElements);
    drawnow; java.lang.System.out.flush();
    assert(meshElementCount > 0 && meshElementCount <= maximumMeshElements, ...
        'assembly:MeshBudget','Mesh element count %.0f violates explicit range 1..%.0f', ...
        meshElementCount, maximumMeshElements);
    model.study('std1').run;
    tags=cellstr(string(cell(model.study('std1').getSolverSequences('SolverSequence'))));
    assert(numel(tags)==1);offTag=char(tags{1});
    meshBefore=assembly_mesh_identity(model);
    offDataset=model.result.dataset.create('assembly_basis_off','Solution');offDataset.set('solution',offTag);
    for k=1:numel(keys)
        comp.physics('es').feature(sprintf('assembly_potential_%03d',k)).set('V0',sprintf('%.17g[V]',von(k)));
    end
    verify_assembly_electrostatic_bindings(model,selected,on,keys,von);
    study=model.study.create('std_assembly_on');study.create('stat','Stationary');
    model.study('std_assembly_on').run;
    tagsOn=cellstr(string(cell(model.study('std_assembly_on').getSolverSequences('SolverSequence'))));
    assert(numel(tagsOn)==1 && ~strcmp(offTag,tagsOn{1}));onTag=char(tagsOn{1});
    assert(isequal(meshBefore,assembly_mesh_identity(model)),'assembly:MeshIdentity','Basis mesh changed');
    onDataset=model.result.dataset.create('assembly_basis_on','Solution');onDataset.set('solution',onTag);
    infoOff=read_assembly_stationary_solution(model,'std1',offTag,'assembly_basis_off');
    infoOn=read_assembly_stationary_solution(model,'std_assembly_on',onTag,'assembly_basis_on');
    mphsave(model,outputPath,'copy','on','excludedata','off');
else
    offTag=char(model.result.dataset('assembly_basis_off').getString('solution'));
    onTag=char(model.result.dataset('assembly_basis_on').getString('solution'));
    assert(~strcmp(offTag,onTag));
    verify_assembly_electrostatic_bindings(model,selected,on,keys,von,'co_resident');
    infoOff=read_assembly_stationary_solution(model,'std1',offTag,'assembly_basis_off');
    infoOn=read_assembly_stationary_solution(model,'std_assembly_on',onTag,'assembly_basis_on');
    meshBefore=assembly_mesh_identity(model);
    meshElementCount=double(comp.mesh('mesh1').getNumElem());
end
solverTree=struct('status','unavailable','features',{{}});
try
    sequence=model.sol(offTag);tags=cellstr(string(cell(sequence.feature.tags)));
    descriptions=cell(1,numel(tags));
    for j=1:numel(tags)
        feature=sequence.feature(tags{j});children=cellstr(string(cell(feature.feature.tags)));
        childTypes=cell(1,numel(children));
        for q=1:numel(children)
            childTypes{q}=struct('tag',children{q},'type',char(feature.feature(children{q}).getType()));
        end
        descriptions{j}=struct('tag',tags{j},'type',char(feature.getType()),'children',{childTypes});
    end
    solverTree=struct('status','native_readback','features',{descriptions});
catch
end
result=struct('operation',operation,'model_path',outputPath,'off_solution',infoOff, ...
    'on_solution',infoOn,'group_keys',{keys},'off_voltages_v',voff,'on_voltages_v',von, ...
    'mesh_identity',meshBefore,'mesh_element_count',meshElementCount, ...
    'maximum_mesh_elements',maximumMeshElements,'solver_tree',solverTree,'vacuum_domains',selected.vacuum_domains,'compute_calls',2*strcmp(operation,'compute'));
end
