function modelPath=oatof_save_run_model(model,output_model_path,paths)
arguments
    model
    output_model_path
    paths
end
assert(~isempty(output_model_path),'OutputModelPath is required for every ordinary model build.');
modelPath=char(output_model_path);
formalRoot=string(java.io.File(paths.comsolFormalDir).getCanonicalPath());
resolvedModelPath=string(java.io.File(modelPath).getCanonicalPath());
assert(~startsWith(lower(resolvedModelPath),lower(formalRoot+filesep)), ...
    'Ordinary COMSOL builds cannot write Formal; use the promotion transaction.');
modelsDir=fileparts(modelPath);
if ~exist(modelsDir,'dir'), mkdir(modelsDir); end
model.save(modelPath);
end
