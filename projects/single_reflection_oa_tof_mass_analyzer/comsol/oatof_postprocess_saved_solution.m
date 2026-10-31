function [result,phases]=oatof_postprocess_saved_solution(model,context,resultsDir)
% One post-solve scientific/export/GUI implementation for normal and cold paths.
arguments
    model
    context (1,1) struct
    resultsDir {mustBeTextScalar}
end
required={'schema_version','role','solution_tag','dataset_tag','particle_count','label','mass_amu','expected_tof','fine_tstep','Tsim','d1_mm','reflectron_stage2_min_mm','d2_mm','d2_margin_fraction','allow_particle_loss','timing','fine_end','Ez_accel_ideal','Ez_drift_ideal','Ez_stage1_ideal','Ez_stage2_ideal','field_mode','reflectron_backplate_voltage_v','modelPath','flight_length_mm','reflectron_length_mm','detector_z_mm','detector_x_mm','detector_radius_mm','accelerator_exit_mm','field_idealization','native_particle_solve_count','generate_model_plots'};
assert(all(isfield(context,required)),'oatof:SavedContext','Saved context lacks a required frozen value.');
assert(context.schema_version==1 && strcmp(context.role,'oatof_saved_particle_solution'), ...
    'oatof:SavedContext','Saved particle context identity differs.');
assert(strcmp(context.solution_tag,'sol2') && strcmp(context.dataset_tag,'pdset1'), ...
    'oatof:SavedContext','Saved particle solution binding differs.');
label=context.label;
mass_amu=context.mass_amu;
expected_tof=context.expected_tof;
fine_tstep=context.fine_tstep;
Tsim=context.Tsim;
d1_mm=context.d1_mm;
reflectron_stage2_min_mm=context.reflectron_stage2_min_mm;
d2_mm=context.d2_mm;
d2_margin_fraction=context.d2_margin_fraction;
allow_particle_loss=context.allow_particle_loss;
timing=context.timing;
fine_end=context.fine_end;
Ez_accel_ideal=context.Ez_accel_ideal;
Ez_drift_ideal=context.Ez_drift_ideal;
Ez_stage1_ideal=context.Ez_stage1_ideal;
Ez_stage2_ideal=context.Ez_stage2_ideal;
field_mode=context.field_mode;
reflectron_backplate_voltage_v=context.reflectron_backplate_voltage_v;
modelPath=context.modelPath;
p=model.param;
t_extract_start=tic;

% COMSOL 6.4 documents that dataonly='on' suppresses the default p/v
% trajectory payload and that the `t` property limits evaluation to an
% explicit time vector.  Both are required here: requesting every stored
% time at sub-nanosecond spacing can exhaust the client JVM even for N=100.
% Keep a sparse whole-flight trace for penetration/plot diagnostics and the
% exact fine output spacing in a generous window around the expected return.
% The latter preserves detector-crossing interpolation while omitting
% output points irrelevant to detector arrival.
arrival_half_window = 200e-9;
arrival_times = (expected_tof-arrival_half_window):fine_tstep: ...
    (expected_tof+arrival_half_window);
trajectory_times = linspace(0, Tsim, 2001);
extract_times = unique([trajectory_times, arrival_times, Tsim]);
% Fixed bounded I/O policy: at N5000 a 257-row XYZ payload is 30.84 MB.
% This is not a solver timestep or an automatic process-RAM budget.
window_samples=256;t=extract_times(:);nP=context.particle_count;
plot_count=min(nP,50);plot_x=nan(numel(t),plot_count);plot_z=plot_x;
settings=struct('detector_z',context.detector_z_mm,'freeze_tolerance_mm',1e-3, ...
 'approach_window_mm',0.5,'detector_x',context.detector_x_mm,'detector_y',0,'active_radius_mm',context.detector_radius_mm);
state=oatof_detector_arrival_reducer('init',[],settings,nP);
t_accel_gate=nan(1,nP);t_refl_entry_gate=nan(1,nP);t_refl_exit_gate=nan(1,nP);
api_calls=0;maximum_api_payload_bytes=0;api_seconds=0;requested_rows=0;
for pass=1:2
 if pass==2,state=oatof_detector_arrival_reducer('begin_observation',state);end
 for first=1:window_samples:numel(t)
  last=min(first+window_samples-1,numel(t));selected=max(1,first-1):last;
  api_timer=tic;
  data=mphparticle(model,'dataset','pdset1','expr',{'qx','qy','qz'}, ...
   't',extract_times(selected),'dataonly','on');
  api_seconds=api_seconds+toc(api_timer);api_calls=api_calls+1;requested_rows=requested_rows+numel(selected);
  assert(isstruct(data)&&all(isfield(data,{'t','d1','d2','d3'})), ...
   'oatof:SavedPopulation','Native coordinate fields are incomplete.');
  assert(isequal(data.t(:),t(selected)),'oatof:SavedTimes','Native query clock differs from the exact frozen vector.');
  assert(isequal(size(data.d1),[numel(selected) nP])&& ...
   isequal(size(data.d2),size(data.d1),size(data.d3)), ...
   'oatof:SavedPopulation','Stored solution population/shape differs from the frozen request.');
  allocation=whos('data');maximum_api_payload_bytes=max(maximum_api_payload_bytes,allocation.bytes);
  x=data.d1;y=data.d2;z=data.d3;fresh=(1+double(first>1)):numel(selected);
  if pass==1
   state=oatof_detector_arrival_reducer('survey',state,t(selected),x,y,z,selected(1));
   plot_x(selected(fresh),:)=x(fresh,1:plot_count);plot_z(selected(fresh),:)=z(fresh,1:plot_count);
   t_accel_gate=firstPredicateTimes(t_accel_gate,z(fresh,:)>=context.accelerator_exit_mm,t(selected(fresh)));
   t_refl_entry_gate=firstPredicateTimes(t_refl_entry_gate,z(fresh,:)>=context.flight_length_mm,t(selected(fresh)));
  else
   state=oatof_detector_arrival_reducer('observe',state,t(selected),x,y,z,selected(1));
   after_turn=selected(fresh)' >= state.turn_index';
   t_refl_exit_gate=firstPredicateTimes(t_refl_exit_gate, ...
    after_turn&z(fresh,:)<=context.flight_length_mm,t(selected(fresh)));
  end
  clear data x y z
 end
end
[state,arrivals]=oatof_detector_arrival_reducer('finish',state);
state_size=whos('state');
extraction_observation=struct('passes',2,'logical_window_samples',window_samples, ...
 'api_calls',api_calls,'api_requested_rows',requested_rows,'original_query_rows',numel(t), ...
 'maximum_api_payload_bytes',maximum_api_payload_bytes,'reducer_state_bytes',state_size.bytes, ...
 'retained_plot_particles',plot_count,'api_seconds',api_seconds);
zEnd=state.last_raw_xyz(:,3)';zmax=state.raw_maximum_z';initial_xyz=state.initial_xyz;
fprintf('[%s] ions released: %d\n', label, nP);

fprintf('[%s] z_max reached: %.2fmm (entrance grid at %gmm, backplate at %gmm)\n', label, max(zmax), context.flight_length_mm, context.flight_length_mm+context.reflectron_length_mm);
fprintf('[%s] final z extracted for raw trajectory evidence.\n', label);

% --- Verify the deepest ACTUAL penetration INTO STAGE 2 ONLY (over all
% nP simulated ions) matches the corrected THEORETICAL d2_min=(U0-U1)/E2
% (doc §7.51 -- the depth at which the ion's remaining axial KE after
% stage1, q(U0-U1), reaches exactly zero under field E2). Stage2 begins
% at the mid-grid, z=L_flight+d1_mm (NOT at the entrance grid), so the
% comparison must subtract d1_mm from the total penetration depth first.
L_flight_mm_pen = context.flight_length_mm;
penetration_total_mm = zmax - L_flight_mm_pen; % per-ion depth past the entrance grid (stage1+stage2)
penetration_stage2_mm = penetration_total_mm - d1_mm; % per-ion depth past the MID grid (stage2 only)
penetration_max_mm = max(penetration_total_mm);
penetration_stage2_max_mm = max(penetration_stage2_mm);
fprintf('[%s] reflectron penetration: total max=%.3fmm, stage2-only max=%.3fmm, over %d ions (theory d2_min=(U0-U1)/E2=%.3fmm, adaptive d2=%.3fmm [+%.0f%% margin])\n', ...
    label, penetration_max_mm, penetration_stage2_max_mm, nP, reflectron_stage2_min_mm, d2_mm, d2_margin_fraction*100);
fprintf('[%s] stage2 penetration_max vs d2_min: diff=%.3fmm (%.2f%% of d2_min)\n', ...
    label, penetration_stage2_max_mm-reflectron_stage2_min_mm, ...
    100*(penetration_stage2_max_mm-reflectron_stage2_min_mm)/reflectron_stage2_min_mm);

% One extractor owns return-leg selection, crossing interpolation,
% Wall/Freeze handling and active-radius acceptance for every COMSOL path.
% Both normal/cold streaming and the array adapter use the unique reducer.
detTimes = arrivals.time_s.';
detTimes(~arrivals.hit.') = NaN;
nDet = sum(arrivals.hit);
fprintf('[%s] detected on detector plate: %d/%d. Arrival-time metrics are delegated to Python.\n', label, nDet, nP);
% Parameter-link gate: actual events must remain safely inside the predicted
% fine windows. This catches future mass/voltage/length/source changes that
% invalidate the one-dimensional reference formulas instead of silently
% degrading resolution in a coarse output segment.
completeEvent = isfinite(t_accel_gate) & isfinite(t_refl_entry_gate) & ...
    isfinite(t_refl_exit_gate) & arrivals.hit.';
if allow_particle_loss
    assert(nDet >= 2 && sum(completeEvent) == nDet, ...
        ['Every detector hit must have accelerator and reflectron events; ' ...
         'at least two detector hits are required.']);
else
    assert(all(completeEvent) && nDet == nP, ...
        'Event-window gate could not identify every accelerator/reflectron/detector event.');
end
t_accel_complete = t_accel_gate(completeEvent);
t_refl_entry_complete = t_refl_entry_gate(completeEvent);
t_refl_exit_complete = t_refl_exit_gate(completeEvent);
det_complete = detTimes(completeEvent);
assert(max(t_accel_complete) < timing.t_accel_end_s-0.1e-6, ...
    'Accelerator exit is too close to/outside the fine-window end.');
assert(min(t_refl_entry_complete) > timing.t_refl_start_s+0.25e-6, ...
    'Reflectron entry is too close to/outside the fine-window start.');
assert(max(t_refl_exit_complete) < timing.t_refl_end_s-0.25e-6, ...
    'Reflectron return exit is too close to/outside the fine-window end.');
assert(min(det_complete) > timing.t_detector_start_s+0.1e-6 && ...
    max(det_complete) < timing.t_detector_end_s-0.1e-6, ...
    'Detector arrivals are too close to/outside the fine detector window.');
fprintf(['[%s] event-window gate PASS: accel exit <=%.4fus; reflectron ' ...
    'entry %.4f-%.4fus, exit %.4f-%.4fus; detector %.4f-%.4fus; complete=%d/%d.\n'], ...
    label, max(t_accel_complete)*1e6, min(t_refl_entry_complete)*1e6, ...
    max(t_refl_entry_complete)*1e6, min(t_refl_exit_complete)*1e6, ...
    max(t_refl_exit_complete)*1e6, min(det_complete)*1e6, max(det_complete)*1e6, ...
    sum(completeEvent), nP);
% !!! Safety check for the "fix B" adaptive fine_end window (per explicit
% speed-optimization request): if any detected ion's arrival landed close
% to fine_end, its recorded timestamp may have snapped to the COARSE
% (500ns) post-window grid instead of the fine 1ns grid, silently adding
% quantization noise to that ion's timing precision. Warn loudly rather
% than let a future scan (different d1/mass/margin) silently lose
% precision on its slowest ions.
if nDet > 0
    latest_det = max(detTimes, [], 'omitnan');
    margin_to_fine_end = fine_end - latest_det;
    if margin_to_fine_end < 2e-6
        fprintf('[%s] !!! WARNING: latest detection (%.3fus) is within %.3fus of fine_end (%.3fus) -- the adaptive tlist fine window may be too tight for this parameter combination, some ions'' timing precision may be degraded. Consider raising the 2.5x margin factor on fine_end.\n', ...
            label, latest_det*1e6, margin_to_fine_end*1e6, fine_end*1e6);
    end
end

t_extract = toc(t_extract_start);
fprintf('[TIMING] full-population extraction plus solver-native detector-event classification: %.2fs\n', t_extract);

if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
handoff = oatof_export_detector_events(resultsDir,label,mass_amu,arrivals, ...
    initial_xyz(:,1),initial_xyz(:,2),initial_xyz(:,3));
result = struct('label', label, 'mass_amu', mass_amu, 'nP', nP, 'zEnd', zEnd, ...
    'nDet', nDet, 'detectorStatus', arrivals.status.', ...
    'detectorRadiusMm', arrivals.radius_mm.', ...
    'raw_detector_events_path', handoff.events_path, ...
    'analysis_request_path', handoff.request_path, ...
    'analysis_output_dir', handoff.analysis_output_dir, ...
    'penetration_max_mm', penetration_max_mm, ...
    'd2min_mm', reflectron_stage2_min_mm, 'd2_mm', d2_mm, ...
    'field_idealization', context.field_idealization, ...
    'model_path',modelPath,'raw_solution_persisted',true, ...
    'native_particle_solve_count',context.native_particle_solve_count,'automatic_time_extension_performed',false, ...
    'observation_end_time_s',Tsim, ...
    'unresolved_detector_event_count',sum(~arrivals.plane_event), ...
    'outside_active_detector_count',sum(arrivals.plane_event&~arrivals.hit), ...
    'postprocess_extraction',extraction_observation);

% Graphics are a read-only projection of the original scientific population.
t_replot_start=tic;
plotView=oatof_particle_plot_view(t(:),plot_x,plot_z,50);
nP_plot=numel(plotView.particle_indices);t_plot=plotView.time_s;
x_plot=plotView.x_mm;z_plot=plotView.z_mm;plot_dataset_tag='pdset1';
t_replot=toc(t_replot_start);
fprintf('[%s] trajectory plot uses original solution columns 1:%d of N=%d; no additional CPT solve.\n',label,nP_plot,nP);
fprintf('[TIMING] original-solution trajectory view: %.2fs\n',t_replot);

t_matlabplot_start = tic;
fh = figure('Visible','off');
subplot(1,2,1);
hold on;
for i = 1:nP_plot
    plot(x_plot(:,i), z_plot(:,i), '-');
end
xlabel('x [mm]'); ylabel('z [mm]'); grid on;
title(sprintf('ion trajectory (N=%d subset): x vs z', nP_plot));
subplot(1,2,2);
hold on;
for i = 1:nP_plot
    plot(t_plot*1e6, z_plot(:,i), '-');
end
xlabel('t [\mus]'); ylabel('z [mm]'); grid on;
title('z position vs time');

% !!! Title now includes N (statistical sample size, nP -- NOT the N_plot=50
% trajectory-rendering subset) and field_mode, per doc convention (always
% show sample size so a reader can't mistake an N=100 result for N=1000,
% see the statistical-sample-size warning in COMSOL_调试方法论.md. Also dropped the hardcoded
% "V_mirror=4551.15V" that was stale (V_mirror is now computed dynamically
% per d1_mm/d2_margin_frac and no longer a fixed literal) in favor of the
% actual computed value.
sgtitle({sprintf('oa-TOF two-stage ring-stack reflectron: %s (N=%d, field_mode=%s)', label, nP, field_mode), ...
    sprintf('%gamu +1 ion, baseline source when selected, d1=%gmm, V_mirror=%.2fV; peak metrics exported to Python', ...
    mass_amu, d1_mm, reflectron_backplate_voltage_v)}, 'Interpreter','none');
print(fh, fullfile(resultsDir, sprintf('ms_oaTOF_ringstack_reflectron_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory plot saved; peak visualization is generated by Python analysis.\n', label);
t_matlabplot = toc(t_matlabplot_start);
fprintf('[TIMING] MATLAB trajectory figure (PNG): %.2fs\n', t_matlabplot);

% !!! Native in-model field diagnostics are deliberately limited to FIVE
% plots: (1) signed-log full-domain Ez, (2) signed-log full-domain
% real-ideal Ez, (3) log residual |E| in the nominally field-free drift,
% (4) real-ideal Ez versus z at five radii, and (5) real-ideal Ez versus
% radius at five ion-accessible z positions inside the reflectron. The
% apparent-mass spectrum remains a separate result plot. All are wrapped
% in try/catch because visualization is not required for the core solve.
% !!! CutPlane dataset API validated empirically against a live COMSOL
% session before use here (a throwaway test model, not guessed from
% memory): 'quickplane'/'quicky' are the correct property names for a
% CutPlane DATASET -- 'quickynumber' (used by the Slice PLOT FEATURE
% inside a 3D scene, which is a different thing) errors with "Unknown
% property" on a CutPlane dataset. One shared y=0 CutPlane dataset feeds
% all three heatmaps below (same physical cross-section, equivalent to an r-z
% profile for this axisymmetric-like ring-stack since x=r for x>0 and the
% mirror x<0 side reflects the same profile) -- only the Surface plot's
% expr differs between the two.
t_resultplots=0;
if context.generate_model_plots
t_resultplots = oatof_create_result_nodes(model,p,label,Ez_accel_ideal,Ez_drift_ideal, ...
    Ez_stage1_ideal,Ez_stage2_ideal);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('oa-TOF (ring-stack): %s trajectory', label));
pg1.set('data', plot_dataset_tag);
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Orthogonal accelerator + ring-stack reflectron: %gamu +1 ion', mass_amu));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('oa-TOF ion trajectory (ring-stack reflectron)');
col_time = trj1.create('col_time', 'Color');
col_time.set('expr', 't');
col_time.set('descr', 'Time');
col_time.set('unit', 's');
col_time.set('colortable', 'Thermal');
col_time.set('colorlegend', 'on');

end
phases=struct('extraction',t_extract,'plot_view',t_replot, ...
    'matlab_plot',t_matlabplot,'result_nodes',t_resultplots,'plot_count',nP_plot);
end

function times=firstPredicateTimes(times,predicate,queryTimes)
[found,index]=max(predicate,[],1);fresh=isnan(times)&found;
times(fresh)=queryTimes(index(fresh));
end
