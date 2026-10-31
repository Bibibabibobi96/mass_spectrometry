function result=reextract_oatof_saved_solution(request)
% Read the admitted saved solution; never solve or save its parent model.
arguments
    request (1,1) struct
end
required={'model_path','context_path','output_dir','parent_run_directory','child_run_directory','candidate_contract_path'};
assert(all(isfield(request,required)), 'oatof:ColdRequest', ...
    'Cold extraction requires explicit model/context/output paths.');
assert(isfile(request.model_path) && isfile(request.context_path) && isfile(request.candidate_contract_path), ...
    'oatof:ColdInput','An admitted saved input is missing.');
contract=load_oatof_contract(request.candidate_contract_path);
context=jsondecode(fileread(request.context_path));
assert(context.schema_version==1 && strcmp(context.role,'oatof_saved_particle_solution'), ...
    'oatof:SavedContext','Saved context identity differs.');
assert(context.particle_count>0 && context.particle_count==floor(context.particle_count) && ...
    strcmp(context.solution_tag,'sol2') && strcmp(context.dataset_tag,'pdset1'), ...
    'oatof:SavedContext','Saved population/solution binding is invalid.');
modelFile=dir(request.model_path);
assert(modelFile.bytes==context.saved_model_bytes, 'oatof:ColdModel', ...
    'Saved model size differs; original writer must establish a complete saved output.');
times=context.solution_times_s(:);
assert(numel(times)>1 && all(isfinite(times)) && all(diff(times)>0), ...
    'oatof:ColdTimes','Saved time inventory is missing or invalid.');
parent=string(java.io.File(request.model_path).getCanonicalPath());
output=string(java.io.File(request.output_dir).getCanonicalPath());
parentRun=string(java.io.File(request.parent_run_directory).getCanonicalPath());
childRun=string(java.io.File(request.child_run_directory).getCanonicalPath());
assert(startsWith(lower(parent),lower(parentRun+filesep)) && ...
    startsWith(lower(output),lower(childRun+filesep)) && ...
    ~startsWith(lower(childRun+filesep),lower(parentRun+filesep)), ...
    'oatof:ColdOutput','Recovery outputs must belong to a separate admitted child run.');
model=mphopen(char(request.model_path),'ModelOATOFPPostprocess','-nostore');
info=mphsolinfo(model,'soltag',context.solution_tag);
assert(strcmp(info.soltype,'Time') && isequal(info.solvals(:),times), ...
    'oatof:ColdTimes','Cold solution time inventory differs.');
assert(strcmp(model.result.dataset(context.dataset_tag).getString('solution'),context.solution_tag), ...
    'oatof:ColdDataset','Cold particle dataset is not bound to the saved solution.');
% The shared extractor verifies the full requested population before any export.
context.modelPath=char(parent);
context.native_particle_solve_count=0;
context.generate_model_plots=false;
[result,~]=oatof_postprocess_saved_solution(model,context,char(request.output_dir));
oatof_validate_candidate_solution(model,result,contract);
result.candidate_model_validation='passed';
result.parent_model_saved=false;
result.native_field_solve_count=0;
result.recovery_scope='saved_solution_postprocessing_only';
end
