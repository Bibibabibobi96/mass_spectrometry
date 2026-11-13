function result = read_assembly_stationary_solution(model, studyTag, solutionTag, datasetTag)
%READ_ASSEMBLY_STATIONARY_SOLUTION Read a saved stationary solution identity.
% Does not Compute, sample fields, modify or save the model.
arguments
    model
    studyTag (1,:) char
    solutionTag (1,:) char
    datasetTag (1,:) char
end
sol=model.sol(solutionTag);
assert(~sol.isEmpty(),'assembly:SolutionEmpty','Stationary solution is empty');
assert(sol.isAttached() && strcmp(char(sol.study()),studyTag), ...
    'assembly:Study','Solution is not attached to the selected study');
sizes=double(sol.getSize()); sizes=sizes(:)';
assert(numel(sizes)==2 && all(isfinite(sizes)) && all(sizes>0) && ...
    sizes(2)==1 && double(sol.getNU('Sol'))==1, ...
    'assembly:SolutionShape','Expected exactly one nonempty stationary solution');
dataset=model.result.dataset(datasetTag);
assert(strcmp(char(dataset.getType()),'Solution') && ...
    strcmp(char(dataset.getString('solution')),solutionTag), ...
    'assembly:Dataset','Solution dataset is not bound to the selected solution');
result=struct('study_tag',studyTag,'solution_tag',solutionTag,'dataset_tag',datasetTag, ...
    'dataset_solution',char(dataset.getString('solution')),'solution_empty',false, ...
    'solution_dofs',sizes(1),'solution_count',sizes(2),'stored_main_solutions',double(sol.getNU('Sol')));
end
