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
label=state.label;modelPath=state.modelPath;t_total_start=state.t_total_start;
t_raw_save=state.t_raw_save;
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
t_extract=postprocessPhases.extraction;
t_replot=postprocessPhases.plot_view;
t_matlabplot=postprocessPhases.matlab_plot;
t_resultplots=postprocessPhases.result_nodes;
nP_plot=postprocessPhases.plot_count;nP=result.nP;

t_save1_start=tic;
% Update GUI nodes at the same persisted path. The raw full-population solution
% was already saved before extraction and MATLAB rendering began.
modelPath = oatof_save_run_model(model,output_model_path,paths);
result.model_path = modelPath;
modelFile=dir(modelPath);context.saved_model_bytes=modelFile.bytes;
oatof_write_saved_particle_context(modelPath,context);
t_save1 = toc(t_save1_start);
fprintf('[%s] SUCCESS: model saved.\n', label);
fprintf('[TIMING] existing model GUI-node update (.mph write): %.2fs\n',t_save1);
t_native_start = tic;
% pg1.run mutates the stored particle solution to the plot subset in
% batch mode. Keep the N-statistics solution intact; Desktop renders this
% already-configured plot group on demand.
t_native = toc(t_native_start);
fprintf('[%s] native trajectory plot configured for GUI rendering; batch render skipped to preserve N=%d statistics solution.\n', label, nP);

t_total = toc(t_total_start);
fprintf('\n===== [TIMING SUMMARY: %s, N=%d] =====\n', label, nP);
phase_names = {'geometry (params+features+geom1.run)', ...
    'selections+materials+ES physics setup', 'mesh (mesh1.run+mphmeshstats)', ...
    'electrostatics solve (sol1)', 'field diagnostic queries', ...
    'CPT setup (before solve)', sprintf('CPT solve (N=%d, statistics population)', nP), ...
    'full-population extraction+post-processing', sprintf('original-solution plot view (N=%d)',nP_plot), ...
    'MATLAB trajectory figure (PNG)', 'native Result plots (field diagnostics)', ...
    'raw solution persistence','same-path GUI-node update','native 3D plot (not run)'};
phase_times = [state.phase_times, t_extract, t_replot, t_matlabplot,t_resultplots,t_raw_save,t_save1,t_native];
for pi_ = 1:numel(phase_names)
    fprintf('  %-45s %8.2fs  (%5.1f%%)\n', phase_names{pi_}, phase_times(pi_), 100*phase_times(pi_)/t_total);
end
fprintf('  %-45s %8.2fs\n', 'SUM OF PHASES', sum(phase_times));
fprintf('  %-45s %8.2fs\n', 'TOTAL (t_total_start to here)', t_total);
fprintf('=====================================================\n');
end
