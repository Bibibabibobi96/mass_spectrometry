function result = solve_assembly_stationary(projectionPath, requestPath, baselinePath, sourcePath, outputPath, rawOutputPath, computeReportPath, operation)
%SOLVE_ASSEMBLY_STATIONARY Compute one workpoint or cold-read it without sampling.
arguments
    projectionPath (1,:) char
    requestPath (1,:) char
    baselinePath (1,:) char
    sourcePath (1,:) char
    outputPath (1,:) char
    rawOutputPath (1,:) char
    computeReportPath (1,:) char
    operation (1,:) char {mustBeMember(operation,{'compute','reopen','recover'})}
end
import com.comsol.model.util.*
projection=jsondecode(fileread(projectionPath));request=jsondecode(fileread(requestPath));
baseline=jsondecode(fileread(baselinePath));
if strcmp(operation,'compute')
    assert(~isfile(outputPath) && ~isfile(rawOutputPath),'assembly:Output','Refusing to overwrite solved model');
    model=mphload(sourcePath,'AssemblyStationarySolution');
else
    model=mphload(outputPath,'AssemblyStationarySolution');
end
cleanupModel=onCleanup(@() ModelUtil.remove('AssemblyStationarySolution'));
comp=model.component('comp1'); groups=projection.electrode_groups;
if isstruct(groups),groups=num2cell(groups);end
rows=request.group_voltages;if isstruct(rows),rows=num2cell(rows);end
keys=cell(1,numel(groups));faces=cell(1,numel(groups));values=zeros(1,numel(groups));
assert(numel(rows)==numel(groups),'assembly:Groups','Group count differs');
for k=1:numel(groups)
    group=groups{k};row=rows{k};
    keys{k}=[char(group.instance_id) '/' char(group.electrode_group_id)];
    assert(strcmp(keys{k},[char(row.instance_id) '/' char(row.electrode_group_id)]), ...
        'assembly:Groups','Group order differs from frozen request');
    values(k)=double(row.voltage_v);
    faces{k}=double(comp.selection(sprintf('assembly_group_%03d',k)).entities());
end
selected=struct('group_keys',{keys},'group_faces',{faces}, ...
    'vacuum_domains',double(comp.selection('assembly_reference_vacuum').entities()), ...
    'outer_faces',double(comp.selection('assembly_outer_boundary').entities()));
baseKeys=cellstr(string(baseline.group_keys));
assert(isequal(keys(:),baseKeys(:)),'assembly:Groups','Source geometry group keys differ');
for k=1:numel(keys)
    if iscell(baseline.group_faces)
        old=baseline.group_faces{k};
    elseif numel(keys)==1
        old=baseline.group_faces;
    else
        old=baseline.group_faces(k,:);
    end
    actual=sort(double(faces{k}(:)));expected=sort(double(old(:)));
    assert(isequal(actual,expected),'assembly:Groups','Source geometry group faces differ');
end
assert(isequal(sort(selected.vacuum_domains(:)),sort(double(baseline.vacuum_domains(:)))) && ...
    isequal(sort(selected.outer_faces(:)),sort(double(baseline.outer_faces(:)))), ...
    'assembly:Selections','Source geometry vacuum or outer selection differs');
verify_assembly_electrostatic_bindings(model,selected,request,keys,values);
if strcmp(operation,'compute')
    assert(isempty(model.sol.tags),'assembly:Unsolved','Source contains a solution');
    assert(strcmp(char(model.study('std1').feature('stat').getType()),'Stationary'), ...
        'assembly:Study','Explicit stationary study required');
    model.study('std1').run;
    % Preserve the actual computed model before any dataset or readback getter.
    mphsave(model,rawOutputPath,'copy','on');
    tags=cellstr(string(cell(model.study('std1').getSolverSequences('SolverSequence'))));
    assert(numel(tags)==1,'assembly:Solver','Expected exactly one study solver sequence');
    solutionTag=char(tags{1});datasetTag='assembly_field_solution';
    datasetTags=cellstr(string(cell(model.result.dataset.tags)));
    assert(~any(strcmp(datasetTags,datasetTag)),'assembly:Dataset','Dataset tag already exists');
    dataset=model.result.dataset.create(datasetTag,'Solution');dataset.set('solution',solutionTag);
elseif strcmp(operation,'recover')
    tags=cellstr(string(cell(model.study('std1').getSolverSequences('SolverSequence'))));
    assert(numel(tags)==1,'assembly:Solver','Expected exactly one study solver sequence');
    solutionTag=char(tags{1});datasetTag='assembly_field_solution';
else
    computed=jsondecode(fileread(computeReportPath));
    solutionTag=char(computed.solution.solution_tag);datasetTag=char(computed.solution.dataset_tag);
end
solution=read_assembly_stationary_solution(model,'std1',solutionTag,datasetTag);
info=mphsolinfo(model,'soltag',solutionTag,'NU','on');
assert(strcmpi(char(info.soltype),'Stationary') && strcmp(char(info.study),'std1'), ...
    'assembly:Study','Actual solution is not the selected stationary study');
solution.solver_type=char(info.soltype);
solution.solver_sequence_type=char(model.sol(solutionTag).getSequenceType());
solution.solver_features=cellstr(string(cell(model.sol(solutionTag).feature.tags)));
solution.comsol_version=char(ModelUtil.getComsolVersion());
solution.solver_policy='comsol_stationary_default';
if strcmp(operation,'compute')
    mphsave(model,outputPath);
end
result=struct('operation',operation,'scope','single_stationary_workpoint', ...
    'model_path',outputPath,'solution',solution,'group_keys',{keys}, ...
    'group_faces',{faces},'vacuum_domains',selected.vacuum_domains, ...
    'outer_faces',selected.outer_faces,'compute_calls',double(strcmp(operation,'compute')));
end
