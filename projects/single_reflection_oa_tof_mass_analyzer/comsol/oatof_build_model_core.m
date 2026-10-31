function result = oatof_build_model_core(varargin)
%OATOF_BUILD_MODEL_CORE Complete model delivery from the native saved solution.
% Positional arguments are forwarded unchanged to the original native builder.
arguments (Repeating)
    varargin
end
[result,model,context,state]=oatof_build_saved_particle_solution(varargin{:});
if ~isempty(result)
    return
end
paths=state.paths;output_model_path=state.output_model_path;
label=state.label;modelPath=state.modelPath;
resultsDir = getenv('OATOF_RESULTS_DIR');
if isempty(resultsDir)
    if strcmpi(strtrim(label), 'Final')
        resultsDir = fullfile(paths.formalRoot, 'results');
    elseif ~isempty(output_model_path)
        modelDir = fileparts(char(output_model_path));
        resultsDir = fullfile(fileparts(modelDir), 'results');
    else
        error('OATOF_RESULTS_DIR or OutputModelPath is required for non-formal runs.');
    end
end
[result,postprocessPhases]=oatof_postprocess_saved_solution(model,context,resultsDir);
result.saved_solution_context_path=[char(modelPath) '.postprocess.json'];

t_save1_start=tic;
% Update GUI nodes at the same persisted path. The raw full-population solution
% was already saved before extraction and MATLAB rendering began.
modelPath = oatof_save_run_model(model,output_model_path,paths);
result.model_path = modelPath;
modelFile=dir(modelPath);context.saved_model_bytes=modelFile.bytes;
oatof_write_saved_particle_context(modelPath,context);
t_save1 = toc(t_save1_start);
oatof_report_model_timing(state.label,result.nP,state.phase_times,postprocessPhases, ...
    state.t_raw_save,t_save1,state.t_total_start);
end
