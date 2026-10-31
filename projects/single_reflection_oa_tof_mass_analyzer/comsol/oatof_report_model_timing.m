function oatof_report_model_timing(label,nP,native_phase_times,postprocessPhases,t_raw_save,t_save1,t_total_start)
%OATOF_REPORT_MODEL_TIMING Print completed delivery timing without a model API.
arguments
    label {mustBeTextScalar}
    nP (1,1) {mustBeNumeric,mustBeReal,mustBeInteger,mustBePositive}
    native_phase_times {mustBeNumeric,mustBeReal,mustBeFinite,mustBeNonnegative}
    postprocessPhases (1,1) struct
    t_raw_save (1,1) {mustBeNumeric,mustBeReal,mustBeFinite,mustBeNonnegative}
    t_save1 (1,1) {mustBeNumeric,mustBeReal,mustBeFinite,mustBeNonnegative}
    t_total_start (1,1) {mustBeNumeric,mustBeReal}
end
t_extract=postprocessPhases.extraction;
t_replot=postprocessPhases.plot_view;
t_matlabplot=postprocessPhases.matlab_plot;
t_resultplots=postprocessPhases.result_nodes;
nP_plot=postprocessPhases.plot_count;

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
phase_times = [native_phase_times, t_extract, t_replot, t_matlabplot,t_resultplots,t_raw_save,t_save1,t_native];
for pi_ = 1:numel(phase_names)
    fprintf('  %-45s %8.2fs  (%5.1f%%)\n', phase_names{pi_}, phase_times(pi_), 100*phase_times(pi_)/t_total);
end
fprintf('  %-45s %8.2fs\n', 'SUM OF PHASES', sum(phase_times));
fprintf('  %-45s %8.2fs\n', 'TOTAL (t_total_start to here)', t_total);
fprintf('=====================================================\n');
end
