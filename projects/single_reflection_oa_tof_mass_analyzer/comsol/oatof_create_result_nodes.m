function t_resultplots = oatof_create_result_nodes(model,p,label,Ez_accel_ideal,Ez_drift_ideal,Ez_stage1_ideal,Ez_stage2_ideal,R_resolution,nDet,mass_bandwidth,mass_grid,mass_intensity)
t_resultplots_start = tic;
try
    cpl_y0 = model.result.dataset.create('cpl_y0', 'CutPlane');
    cpl_y0.label('y=0 cross-section (r-z profile)');
    cpl_y0.set('quickplane', 'zx');
    cpl_y0.set('quicky', '0');
    fprintf('[%s] SUCCESS: shared y=0 CutPlane dataset (cpl_y0) created.\n', label);
catch ME
    fprintf('[%s] WARNING: CutPlane dataset creation failed (%s) -- field heatmaps below will be skipped.\n', label, ME.message);
end

% Full-device theoretical target, independent of field_mode. This fixes
% the old diagnostic's blind spot at z<L_flight: both accelerator stages
% and the zero-field drift are now included with the two reflectron stages.
Ez_ideal_full_expr = sprintf(['if(z<0||z>L_flight+L_refl,NaN,' ...
    'if(z<z_accel_grid2,%s,if(z<L_flight,%s,' ...
    'if(z<L_flight+L_stage1,%s,%s))))'], ...
    Ez_accel_ideal, Ez_drift_ideal, Ez_stage1_ideal, Ez_stage2_ideal);
Ez_diff_full_expr = sprintf('es.Ez-(%s)', Ez_ideal_full_expr);
Ez_signedlog_expr = 'sign(es.Ez)*log10(1+abs(es.Ez)/(1[V/m]))';
Ez_diff_signedlog_expr = sprintf('sign(%s)*log10(1+abs(%s)/(1[V/m]))', ...
    Ez_diff_full_expr, Ez_diff_full_expr);
Eres_drift_log_expr = ['if(z<z_accel_grid2||z>L_flight,NaN,' ...
    'log10(1+sqrt(es.Ex^2+es.Ey^2+es.Ez^2)/(1[V/m])))'];
try
    % (1) Full-domain real-ideal difference. Signed-log compression keeps
    % weak leakage visible beside strong edge fields and retains its sign.
    pg_field_diff = model.result.create('pg_field_diff', 'PlotGroup2D');
    pg_field_diff.label(sprintf('1 Field error, full domain, signed log: %s', label));
    pg_field_diff.set('data', 'cpl_y0');
    pg_field_diff.set('titletype', 'manual');
    pg_field_diff.set('title', 'signed log10(1+|Ez(real)-Ez(ideal)|/1V/m), full device; sign retained');
    sf_diff = pg_field_diff.create('sf_diff', 'Surface');
    sf_diff.label('signed-log full-domain Ez error');
    sf_diff.set('expr', Ez_diff_signedlog_expr);
    pg_field_diff.run;
    fprintf('[%s] SUCCESS: full-domain signed-log field-error heatmap created.\n', label);
catch ME
    fprintf('[%s] WARNING: field leakage diagnostic heatmap failed (%s).\n', label, ME.message);
end
try
    % (2) Full-domain actual Ez with the same signed-log convention.
    pg_field_full = model.result.create('pg_field_full', 'PlotGroup2D');
    pg_field_full.label(sprintf('2 Actual Ez, full domain, signed log: %s', label));
    pg_field_full.set('data', 'cpl_y0');
    pg_field_full.set('titletype', 'manual');
    pg_field_full.set('title', 'signed log10(1+|Ez|/1V/m), full device; sign retained');
    sf_full = pg_field_full.create('sf_full', 'Surface');
    sf_full.label('signed-log actual Ez');
    sf_full.set('expr', Ez_signedlog_expr);
    pg_field_full.run;
    fprintf('[%s] SUCCESS: full-domain signed-log actual-field heatmap created.\n', label);
catch ME
    fprintf('[%s] WARNING: full-domain field heatmap failed (%s).\n', label, ME.message);
end
try
    % (3) Total residual magnitude in the nominally field-free drift. This
    % catches transverse shield/end leakage that an Ez-only plot misses.
    pg_field_drift = model.result.create('pg_field_drift', 'PlotGroup2D');
    pg_field_drift.label(sprintf('3 Drift residual field magnitude, log: %s', label));
    pg_field_drift.set('data', 'cpl_y0');
    pg_field_drift.set('titletype', 'manual');
    pg_field_drift.set('title', 'log10(1+|E|/1V/m), nominally field-free drift only');
    sf_drift = pg_field_drift.create('sf_drift', 'Surface');
    sf_drift.label('log residual total field in drift');
    sf_drift.set('expr', Eres_drift_log_expr);
    pg_field_drift.run;
    fprintf('[%s] SUCCESS: drift residual-field heatmap created.\n', label);
catch ME
    fprintf('[%s] WARNING: drift residual-field heatmap failed (%s).\n', label, ME.message);
end
try
    % (4) Quantitative axial profiles at five radii. They deliberately
    % cover only the reflectron: the off-axis accelerator has a different
    % physical axis, so a single fixed-x full-device line is misleading.
    % Stay 0.1 mm off the grids/plate to avoid material-boundary samples.
    Lf_mm_plot = p.evaluate('L_flight', 'mm');
    Lr_mm_plot = p.evaluate('L_refl', 'mm');
    bore_mm_plot = p.evaluate('bore_r', 'mm');
    xr_mm_plot = p.evaluate('x_refl_center', 'mm');
    zprof_mm = linspace(Lf_mm_plot+0.1, Lf_mm_plot+Lr_mm_plot-0.1, 801);
    rfrac = [0, 0.2, 0.4, 0.6, 0.8];
    dEz_prof = NaN(numel(zprof_mm), numel(rfrac));
    for ir = 1:numel(rfrac)
        coord_prof = [repmat(xr_mm_plot+rfrac(ir)*bore_mm_plot, 1, numel(zprof_mm)); ...
                      zeros(1, numel(zprof_mm)); zprof_mm];
        dEz_prof(:,ir) = mphinterp(model, Ez_diff_full_expr, 'coord', coord_prof, ...
            'dataset', 'dset1', 'matherr', 'off').';
    end
    % es.Ez is the derivative of the finite-element potential and is not
    % continuous across first-order tetrahedron faces. Dense line samples
    % therefore expose element-scale sawteeth even though V is continuous.
    % A 9-point Savitzky-Golay window spans only ~2.1 mm here, far below
    % the shortest ring pitch (~14.5 mm): it removes mesh-face jitter but
    % retains the physically meaningful ring-stack ripple. Preserve the
    % unfiltered samples in a separate native table for audit/convergence.
    dEz_prof_raw = dEz_prof;
    dEz_prof = smoothdata(dEz_prof, 1, 'sgolay', 9);
    tbl_fieldprof_raw = model.result.table.create('tbl_fieldprof_raw', 'Table');
    tbl_fieldprof_raw.label(sprintf('RAW reflectron axial Ez-error profiles: %s', label));
    tbl_fieldprof_raw.comments('Unsmoothed FEM-gradient samples for mesh-convergence audit [V/m]');
    tbl_fieldprof_raw.setTableData([zprof_mm(:), dEz_prof_raw]);
    tbl_fieldprof_raw.setColumnHeaders({'z [mm]', 'r/bore=0', 'r/bore=0.2', ...
        'r/bore=0.4', 'r/bore=0.6', 'r/bore=0.8'});
    tbl_fieldprof = model.result.table.create('tbl_fieldprof', 'Table');
    tbl_fieldprof.label(sprintf('Reflectron axial Ez-error profiles: %s', label));
    tbl_fieldprof.comments('SG-smoothed (~2.1mm window) dEz at r/bore = 0, 0.2, 0.4, 0.6, 0.8 [V/m]; raw samples in tbl_fieldprof_raw');
    tbl_fieldprof.setTableData([zprof_mm(:), dEz_prof]);
    tbl_fieldprof.setColumnHeaders({'z [mm]', 'r/bore=0', 'r/bore=0.2', 'r/bore=0.4', ...
        'r/bore=0.6', 'r/bore=0.8'});
    pg_fieldprof = model.result.create('pg_fieldprof', 'PlotGroup1D');
    pg_fieldprof.label(sprintf('4 Reflectron axial Ez error at five radii: %s', label));
    pg_fieldprof.set('titletype', 'manual');
    pg_fieldprof.set('title', 'Ez(real)-Ez(ideal) versus z at five radii (SG display smoothing; raw table retained)');
    pg_fieldprof.set('xlabel', 'z [mm]');
    pg_fieldprof.set('ylabel', 'Ez(real)-Ez(ideal) [V/m]');
    tg_fieldprof = pg_fieldprof.create('tg_fieldprof', 'Table');
    tg_fieldprof.label('Five axial Ez-error profiles');
    tg_fieldprof.set('table', 'tbl_fieldprof');
    tg_fieldprof.set('plotcolumninput', 'manual');
    tg_fieldprof.set('xaxisdata', '1');
    tg_fieldprof.set('plotcolumns', '2,3,4,5,6');
    % Multi-curve plots must carry an explicit, physically meaningful
    % legend (COMSOL defaults this Table Graph to legend=off and generic
    % generic column labels, which violates the project plotting rules).
    tg_fieldprof.set('legend', 'on');
    tg_fieldprof.set('legendmethod', 'manual');
    tg_fieldprof.set('legends', {'r/bore=0', 'r/bore=0.2', 'r/bore=0.4', ...
        'r/bore=0.6', 'r/bore=0.8'});
    tg_fieldprof.set('showwidth', 'on');
    tg_fieldprof.set('linewidth', '2');
    pg_fieldprof.run;
    fprintf('[%s] SUCCESS: five-radius axial Ez-error profile plot created.\n', label);
catch ME
    fprintf('[%s] WARNING: five-radius axial field-error profile failed (%s).\n', label, ME.message);
end
try
    % (5) Complementary radial profiles at three depths in each stage.
    % This makes the z-dependence explicit without mixing z and r on one
    % horizontal axis. Normalize r by bore_r so future bore scans remain
    % directly comparable; stop at 0.8*bore_r per the selected useful
    % aperture and to avoid edge singularities.
    L1_mm_plot = p.evaluate('L_stage1', 'mm');
    L2_mm_plot = Lr_mm_plot-L1_mm_plot;
    stage1frac = [0.25, 0.50, 0.75];
    % Formal maximum stage-2 penetration is 51.07mm = 58.8% of L2, so
    % stage2 75% is never sampled by an ion and is intentionally omitted.
    stage2frac = [0.25, 0.50];
    zslice_mm = [Lf_mm_plot+stage1frac*L1_mm_plot, ...
        Lf_mm_plot+L1_mm_plot+stage2frac*L2_mm_plot];
    rn_prof = linspace(0, 0.8, 301);
    dEz_radial = NaN(numel(rn_prof), numel(zslice_mm));
    for iz = 1:numel(zslice_mm)
        coord_radial = [xr_mm_plot+rn_prof*bore_mm_plot; ...
                        zeros(1, numel(rn_prof)); ...
                        repmat(zslice_mm(iz), 1, numel(rn_prof))];
        dEz_radial(:,iz) = mphinterp(model, Ez_diff_full_expr, 'coord', coord_radial, ...
            'dataset', 'dset1', 'matherr', 'off').';
    end
    dEz_radial_raw = dEz_radial;
    % Seven radial samples span ~4.0mm, still far below ring pitch and
    % small compared with bore_r; preserve raw values in a separate table.
    dEz_radial = smoothdata(dEz_radial, 1, 'sgolay', 7);
    radial_legends = {'stage1 z/L1=0.25', 'stage1 z/L1=0.50', 'stage1 z/L1=0.75', ...
        'stage2 z/L2=0.25', 'stage2 z/L2=0.50'};
    tbl_fieldradial_raw = model.result.table.create('tbl_fieldradial_raw', 'Table');
    tbl_fieldradial_raw.label(sprintf('RAW reflectron radial Ez-error profiles: %s', label));
    tbl_fieldradial_raw.comments('Unsmoothed FEM-gradient samples for mesh-convergence audit [V/m]');
    tbl_fieldradial_raw.setTableData([rn_prof(:), dEz_radial_raw]);
    tbl_fieldradial_raw.setColumnHeaders([{'r/bore'}, radial_legends]);
    tbl_fieldradial = model.result.table.create('tbl_fieldradial', 'Table');
    tbl_fieldradial.label(sprintf('Reflectron radial Ez-error profiles at five z positions: %s', label));
    tbl_fieldradial.comments('SG-smoothed (~4.0mm radial window) dEz at ion-accessible stage depths [V/m]; raw samples in tbl_fieldradial_raw');
    tbl_fieldradial.setTableData([rn_prof(:), dEz_radial]);
    tbl_fieldradial.setColumnHeaders([{'r/bore'}, radial_legends]);
    pg_fieldradial = model.result.create('pg_fieldradial', 'PlotGroup1D');
    pg_fieldradial.label(sprintf('5 Reflectron radial Ez error at five z positions: %s', label));
    pg_fieldradial.set('titletype', 'manual');
    pg_fieldradial.set('title', 'Ez(real)-Ez(ideal) versus r/bore at five ion-accessible depths (SG display smoothing)');
    pg_fieldradial.set('xlabel', 'r/bore');
    pg_fieldradial.set('ylabel', 'Ez(real)-Ez(ideal) [V/m]');
    tg_fieldradial = pg_fieldradial.create('tg_fieldradial', 'Table');
    tg_fieldradial.label('Five z-position radial Ez-error profiles');
    tg_fieldradial.set('table', 'tbl_fieldradial');
    tg_fieldradial.set('plotcolumninput', 'manual');
    tg_fieldradial.set('xaxisdata', '1');
    tg_fieldradial.set('plotcolumns', '2,3,4,5,6');
    tg_fieldradial.set('legend', 'on');
    tg_fieldradial.set('legendmethod', 'manual');
    tg_fieldradial.set('legends', radial_legends);
    tg_fieldradial.set('showwidth', 'on');
    tg_fieldradial.set('linewidth', '2');
    pg_fieldradial.run;
    fprintf('[%s] SUCCESS: five-z-position radial Ez-error profile plot created.\n', label);
catch ME
    fprintf('[%s] WARNING: five-z-position radial field-error profile failed (%s).\n', label, ME.message);
end
try
    tbl_ms = model.result.table.create('tbl_massspec', 'Table');
    tbl_ms.label(sprintf('Mass spectrum data: %s', label));
    tbl_ms.comments(sprintf('%s: Gaussian-KDE apparent-mass intensity, R_FWHM=%.1f, N=%d, bandwidth=%.6gDa', label, R_resolution, nDet, mass_bandwidth));
    tbl_ms.setTableData([mass_grid(:), mass_intensity(:)]);
    pg_ms = model.result.create('pg_massspec', 'PlotGroup1D');
    pg_ms.label(sprintf('Mass spectrum: %s', label));
    pg_ms.set('titletype', 'manual');
    pg_ms.set('title', sprintf('Mass spectrum (apparent mass, R_FWHM=%.1f, N=%d)', R_resolution, nDet));
    pg_ms.set('xlabel', 'apparent mass [Da]');
    pg_ms.set('ylabel', 'intensity [counts]');
    tg_ms = pg_ms.create('tg_ms', 'Table');
    tg_ms.label('Mass spectrum (Table Graph)');
    tg_ms.set('table', 'tbl_massspec');
    tg_ms.set('plotcolumninput', 'manual');
    tg_ms.set('xaxisdata', '1');
    tg_ms.set('plotcolumns', '2');
    pg_ms.run;
    fprintf('[%s] SUCCESS: mass spectrum table plot (pg_massspec) created.\n', label);
catch ME
    fprintf('[%s] WARNING: mass spectrum table plot failed (%s).\n', label, ME.message);
end
t_resultplots = toc(t_resultplots_start);
fprintf('[TIMING] native Result plots (5 field diagnostics + mass spectrum table): %.2fs\n', t_resultplots);
end
