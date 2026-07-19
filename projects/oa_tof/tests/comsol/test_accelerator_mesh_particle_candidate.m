% Test an in-memory fixed-particle candidate with a selected accelerator mesh.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('OATOF_COMSOL_OUTPUT_CSV');
hmaxText = getenv('OATOF_ACCELERATOR_HMAX_MM');
particleIdsText = getenv('OATOF_PARTICLE_IDS');
sourceModelPath = getenv('OATOF_SOURCE_MODEL_PATH');
ionTablePath = getenv('OATOF_ION_TABLE');
fineStepText = getenv('OATOF_FINE_TSTEP_NS');
driftStepText = getenv('OATOF_DRIFT_TSTEP_NS');
reuseExistingField = strcmp(getenv('OATOF_REUSE_EXISTING_FIELD'), '1');
useParticleStopTime = strcmp(getenv('OATOF_USE_PARTICLE_STOP_TIME'), '1');
useSegmentedOutput = strcmp(getenv('OATOF_SEGMENTED_OUTPUT'), '1');
clearParticleSolutionData = strcmp( ...
    getenv('OATOF_CLEAR_PARTICLE_SOLUTION_DATA'), '1');
applyParticleProperties = ~strcmp( ...
    getenv('OATOF_APPLY_PARTICLE_PROPERTIES'), '0');
assert(~isempty(outputCsv), 'OATOF_COMSOL_OUTPUT_CSV is not set.');
if isempty(hmaxText), hmaxText = '0.5'; end
hmaxMm = str2double(hmaxText);
assert(isfinite(hmaxMm) && hmaxMm > 0, 'Invalid accelerator hmax.');
if isempty(fineStepText)
    fineStepNs = NaN;
else
    fineStepNs = str2double(fineStepText);
    assert(isfinite(fineStepNs) && fineStepNs > 0, ...
        'OATOF_FINE_TSTEP_NS must be a positive number.');
end
if isempty(driftStepText)
    driftStepNs = 50;
else
    driftStepNs = str2double(driftStepText);
    assert(isfinite(driftStepNs) && driftStepNs > 0, ...
        'OATOF_DRIFT_TSTEP_NS must be a positive number.');
end

testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
addpath(fullfile(projectDir, 'comsol'));
paths = oatof_paths();
import com.comsol.model.util.*
if isempty(sourceModelPath)
    modelPath = fullfile(paths.comsolFormalDir, ...
        'oa_tof__model.mph');
else
    modelPath = sourceModelPath;
end
if isempty(ionTablePath)
    ionTable = fullfile(paths.simionFormalDir, ...
        'oatof_comsol_524amu_gaussian_N100.ion');
else
    ionTable = ionTablePath;
end
assert(isfile(ionTable), 'Fixed SIMION particle table not found: %s', ionTable);
ion = readmatrix(ionTable, 'FileType', 'text', 'Delimiter', ',');
if isempty(particleIdsText)
    particleIds = (1:size(ion,1)).';
else
    particleIds = str2double(split(string(particleIdsText), ','));
    assert(all(isfinite(particleIds) & particleIds == floor(particleIds)), ...
        'OATOF_PARTICLE_IDS must contain comma-separated integers.');
    assert(all(particleIds >= 1 & particleIds <= size(ion,1)), ...
        'OATOF_PARTICLE_IDS contains an out-of-range ID.');
    assert(numel(unique(particleIds)) == numel(particleIds), ...
        'OATOF_PARTICLE_IDS contains duplicates.');
end
selectedIon = ion(particleIds, :);
massValues = unique(selectedIon(:,2));
chargeValues = unique(selectedIon(:,3));
assert(numel(massValues) == 1 && isfinite(massValues(1)) && massValues(1) > 0, ...
    'Selected fixed-particle table must contain one positive ion mass.');
assert(numel(chargeValues) == 1 && isfinite(chargeValues(1)) && ...
    chargeValues(1) == floor(chargeValues(1)) && chargeValues(1) ~= 0, ...
    'Selected fixed-particle table must contain one nonzero integer charge state.');
massAmu = massValues(1);
chargeState = chargeValues(1);
outputDir = fileparts(outputCsv);
if ~isfolder(outputDir), mkdir(outputDir); end
[~, outputStem] = fileparts(outputCsv);
releasePath = fullfile(outputDir, sprintf( ...
    '%s_fixedN%d_selected_release_from_data_file.txt', ...
    outputStem, numel(particleIds)));

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\nION_TABLE=%s\nOUTPUT_CSV=%s\n', ...
    modelPath, ionTable, outputCsv);
fprintf(fid, 'ACCELERATOR_HMAX_MM=%.12g\n', hmaxMm);
fprintf(fid, 'PARTICLE_IDS=%s\n', join(string(particleIds), ','));
fprintf(fid, 'MASS_AMU=%.12g\nCHARGE_STATE=%d\n', massAmu, chargeState);
fprintf(fid, 'REUSE_EXISTING_FIELD=%d\n', reuseExistingField);
fprintf(fid, 'USE_PARTICLE_STOP_TIME=%d\n', useParticleStopTime);
fprintf(fid, 'USE_SEGMENTED_OUTPUT=%d\n', useSegmentedOutput);
fprintf(fid, 'CLEAR_PARTICLE_SOLUTION_DATA=%d\n', clearParticleSolutionData);
fprintf(fid, 'APPLY_PARTICLE_PROPERTIES=%d\n', applyParticleProperties);
fprintf(fid, 'REQUESTED_DRIFT_TSTEP_NS=%.12g\n', driftStepNs);
if isfinite(fineStepNs)
    fprintf(fid, 'REQUESTED_FINE_TSTEP_NS=%.12g\n', fineStepNs);
else
    fprintf(fid, 'REQUESTED_FINE_TSTEP_NS=UNCHANGED\n');
end

try
    model = mphopen(modelPath);
    mesh = model.component('comp1').mesh('mesh1');
    if reuseExistingField
        tagsAfter = string(cell(mesh.feature.tags()));
        fprintf(fid, 'MESH_FEATURES_REUSED=%s\n', join(tagsAfter, ','));
    else
        tag = 'szaccelconv';
        sizeFeature = mesh.feature().create(tag, 'Size');
        sizeFeature.label('DIAGNOSTIC accelerator-domain particle candidate');
        sizeFeature.selection().geom('geom1', 3);
        sizeFeature.selection().named('selbracket');
        sizeFeature.set('custom', 'on');
        sizeFeature.set('hmaxactive', true);
        sizeFeature.set('hmax', sprintf('%.12g[mm]', hmaxMm));
        tagsBefore = string(cell(mesh.feature.tags()));
        ftetIndex = find(tagsBefore == "ftet1", 1);
        assert(~isempty(ftetIndex), 'Formal mesh does not contain ftet1.');
        mesh.feature.move(tag, ftetIndex-1);
        tagsAfter = string(cell(mesh.feature.tags()));
        assert(find(tagsAfter == tag, 1) < find(tagsAfter == "ftet1", 1), ...
            'Diagnostic Size is not before ftet1.');
        fprintf(fid, 'MESH_FEATURES=%s\n', join(tagsAfter, ','));
    end

    % Both controls below are persisted GUI settings: Study > Time
    % Dependent > Output times, and Solver > Time-Dependent Solver >
    % Times to store / Steps taken by solver. No hidden solver option is
    % used by this diagnostic.
    timeStudy = model.study('std2').feature('time1');
    oldTlist = char(timeStudy.getString('tlist'));
    if useSegmentedOutput
        assert(isfinite(fineStepNs), ...
            'Segmented output requires OATOF_FINE_TSTEP_NS.');
        assert(chargeState == 1, ...
            'Segmented-output formulas currently support singly charged ions only.');
        configure_oatof_segmented_output( ...
            model, massAmu, fineStepNs, driftStepNs);
    elseif isfinite(fineStepNs)
        oldFineToken = regexp(oldTlist, ...
            'range\(0,([^,]+),2e-6\)', 'tokens', 'once');
        assert(~isempty(oldFineToken), ...
            'Could not identify the fine step in GUI Output times.');
        newFineStep = sprintf('%.12g', fineStepNs*1e-9);
        newTlist = strrep(oldTlist, oldFineToken{1}, newFineStep);
        assert(~strcmp(newTlist, oldTlist), ...
            'Requested fine step did not change GUI Output times.');
        timeStudy.set('tlist', newTlist);
    end
    solverTime = model.sol('sol2').feature('t1');
    solverTime.set('tstepsbdf', 'free');
    solverTime.set('tout', 'tlist');
    cpt = model.component('comp1').physics('cpt');
    cpt.prop('StoreExtra').set('StoreExtra', false);
    cpt.prop('StoreParticleStatusData').set( ...
        'StoreParticleStatusData', useParticleStopTime);
    fprintf(fid, 'GUI_STUDY_OUTPUT_TIMES_BEFORE=%s\n', oldTlist);
    fprintf(fid, 'GUI_STUDY_OUTPUT_TIMES_AFTER=%s\n', ...
        char(timeStudy.getString('tlist')));
    fprintf(fid, 'GUI_SOLVER_STEPS_TAKEN=%s\n', ...
        char(solverTime.getString('tstepsbdf')));
    fprintf(fid, 'GUI_SOLVER_TIMES_TO_STORE=%s\n', ...
        char(solverTime.getString('tout')));
    fprintf(fid, 'GUI_CPT_STORE_EXTRA_WALL_TIMES=%d\n', ...
        cpt.prop('StoreExtra').getBoolean('StoreExtra'));
    fprintf(fid, 'GUI_CPT_STORE_PARTICLE_STATUS=%d\n', ...
        cpt.prop('StoreParticleStatusData').getBoolean( ...
        'StoreParticleStatusData'));
    if useSegmentedOutput
        eventNames = {'t_accel_exit_ref','t_refl_entry_ref', ...
            't_refl_exit_ref','t_detector_ref','cpt_t_accel_end', ...
            'cpt_t_refl_start','cpt_t_refl_end', ...
            'cpt_t_detector_start','cpt_t_detector_end','cpt_t_end'};
        for eventIndex = 1:numel(eventNames)
            fprintf(fid, 'GUI_%s_US=%.12g\n', upper(eventNames{eventIndex}), ...
                mphevaluate(model, eventNames{eventIndex}, 'us'));
        end
    end

    massKg = massAmu*1.66053906660e-27;
    energyEv = selectedIon(:,9);
    azimuth = deg2rad(selectedIon(:,7));
    elevation = deg2rad(selectedIon(:,8));
    speed = sqrt(2*energyEv*1.602176e-19/massKg);
    velocity = [speed.*cos(elevation).*cos(azimuth), ...
        speed.*cos(elevation).*sin(azimuth), speed.*sin(elevation)];
    writematrix([selectedIon(:,4:6), velocity], releasePath, 'Delimiter', 'tab');
    rel1 = model.component('comp1').physics('cpt').feature('rel1');
    rel1.label(sprintf('DIAGNOSTIC fixed particle subset (N=%d)', numel(particleIds)));
    rel1.set('Filename', releasePath);
    rel1.importData();
    if applyParticleProperties
        particleProperties = model.component('comp1').physics('cpt').feature('pp1');
        particleProperties.label(sprintf( ...
            'Particle properties: %.12g amu, charge %+d', massAmu, chargeState));
        particleProperties.set('mp', sprintf('%.15g[kg]', massKg));
        particleProperties.set('Z', sprintf('%d', chargeState));
    end
    fprintf(fid, 'RELEASE_FILE=%s\n', releasePath);

    meshStart = tic;
    if reuseExistingField
        meshSeconds = 0;
    else
        mesh.run;
        meshSeconds = toc(meshStart);
    end
    meshInfo = mphmeshstats(model, 'mesh1');
    esStart = tic;
    if reuseExistingField
        esSeconds = 0;
    else
        model.study('std1').run;
        esSeconds = toc(esStart);
    end
    % The historical 524 Da path let Study Compute replace the old particle
    % solution.  Keep explicit clearing as an opt-in diagnostic because
    % COMSOL 6.4 build 293 has crashed while reinitializing the cleared
    % solution mesh.
    if clearParticleSolutionData
        model.sol('sol2').clearSolutionData();
    end
    fprintf(fid, 'PARTICLE_SOLUTION_DATA_CLEARED=%d\n', ...
        clearParticleSolutionData);
    particleStart = tic;
    fprintf(fid, 'STUDY_STARTED=1\n');
    model.study('std2').run;
    particleSeconds = toc(particleStart);
    fprintf(fid, 'STUDY_COMPLETED=1\n');
    solutionInfo = mphsolinfo(model, 'soltag', 'sol2', 'NU', 'on');
    fprintf(fid, 'SOLUTION_SIZES=%s\n', mat2str(solutionInfo.sizes));

    p0 = mphparticle(model, 'dataset', 'pdset1', 't', 0);
    fprintf(fid, 'INITIAL_RELEASE_READ=PASS\n');
    releasedPositionMm = squeeze(p0.p);
    releasedVelocityMS = squeeze(p0.v);
    expectedPositionMm = selectedIon(:,4:6);
    expectedSpeedMS = sqrt(2*selectedIon(:,9)*1.602176e-19/massKg);
    positionErrorMm = max(abs(releasedPositionMm(:)-expectedPositionMm(:)));
    speedErrorMS = max(abs(sqrt(sum(releasedVelocityMS.^2,2))-expectedSpeedMS));

    detectorZ = mphevaluate(model, 'detector_z', 'mm');
    if useSegmentedOutput
        expectedTof = mphevaluate(model, 't_detector_ref', 's');
    else
        expectedTof = 31.4478763926e-6*sqrt(massAmu/100);
    end
    arrivalHalfWindow = 200e-9;
    if useParticleStopTime
        % Store particle status data is a GUI checkbox on the CPT physics
        % interface. cpt.st is the solver-computed wall stop time, so no
        % hidden time correction or trajectory-grid inference is needed.
        pdStop = mphparticle(model, 'dataset', 'pdset1', ...
            'expr', {'cpt.st','qx','qy','qz'}, ...
            't', expectedTof+arrivalHalfWindow, 'dataonly', 'on');
        detectorTimes = squeeze(pdStop.d1);
        detectorX = squeeze(pdStop.d2);
        detectorY = squeeze(pdStop.d3);
        detectorFinalZ = squeeze(pdStop.d4);
        detectorTimes = detectorTimes(:);
        detectorX = detectorX(:);
        detectorY = detectorY(:);
        detectorFinalZ = detectorFinalZ(:);
        assert(numel(detectorTimes) == numel(particleIds), ...
            'Stored stop-time particle count does not match the subset.');
        assert(all(abs(detectorFinalZ-detectorZ) < 2), ...
            'Stored stop-time particles are not frozen at the detector.');
    else
        evalTimes = expectedTof + (-arrivalHalfWindow:0.2e-9:arrivalHalfWindow);
        pd = mphparticle(model, 'dataset', 'pdset1', ...
            'expr', {'qx','qy','qz'}, 't', evalTimes, 'dataonly', 'on');
        t = pd.t(:);
        x = orient_time_by_particle(squeeze(pd.d1), numel(t));
        y = orient_time_by_particle(squeeze(pd.d2), numel(t));
        z = orient_time_by_particle(squeeze(pd.d3), numel(t));
        assert(size(z,2) == numel(particleIds), ...
            'Solved particle count does not match the selected fixed subset.');
        detectorTimes = nan(size(z,2), 1);
        detectorX = nan(size(z,2), 1);
        detectorY = nan(size(z,2), 1);
        for particle = 1:size(z,2)
            crossingIndex = find(z(:,particle) < detectorZ+0.5, 1, 'first');
            if isempty(crossingIndex), continue; end
            [detectorTimes(particle), detectorX(particle), detectorY(particle)] = ...
                interpolate_crossing(t, x(:,particle), y(:,particle), ...
                z(:,particle), crossingIndex, detectorZ);
        end
    end
    assert(all(isfinite(detectorTimes)), 'Expected all fixed particles to hit.');
    result = table(particleIds, detectorTimes*1e6, detectorX, detectorY, ...
        true(numel(detectorTimes),1), selectedIon(:,4), selectedIon(:,5), ...
        selectedIon(:,6), selectedIon(:,9), ...
        'VariableNames', {'Ion','TofUs','XMm','YMm','Hit', ...
        'X0Mm','Y0Mm','Z0Mm','EnergyEv'});
    writetable(result, outputCsv);

    fprintf(fid, 'MESH_ELEMENTS=%d\nMESH_SECONDS=%.6f\n', ...
        meshInfo.numelem(2), meshSeconds);
    fprintf(fid, 'ELECTROSTATICS_SECONDS=%.6f\nPARTICLE_SECONDS=%.6f\n', ...
        esSeconds, particleSeconds);
    fprintf(fid, 'MAX_T0_RELEASE_POSITION_ERROR_MM=%.12g\n', positionErrorMm);
    fprintf(fid, 'MAX_T0_RELEASE_SPEED_ERROR_M_PER_S=%.12g\n', speedErrorMS);
    fprintf(fid, 'DETECTED=%d/%d\nMEAN_TOF_US=%.12g\n', ...
        sum(isfinite(detectorTimes)), numel(detectorTimes), mean(detectorTimes)*1e6);
    fprintf(fid, 'STATUS=PASS\n');
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function values = orient_time_by_particle(values, timeCount)
if size(values, 1) == timeCount, return; end
if size(values, 2) == timeCount, values = values.'; return; end
error('Unexpected particle array shape %dx%d for %d times.', ...
    size(values,1), size(values,2), timeCount);
end

function [crossingTime, crossingX, crossingY] = ...
    interpolate_crossing(t, x, y, z, index, target)
if index > 1 && all(isfinite([x(index-1:index); y(index-1:index); ...
        z(index-1:index)]), 'all') && z(index) ~= z(index-1)
    fraction = (target-z(index-1))/(z(index)-z(index-1));
    crossingTime = t(index-1) + fraction*(t(index)-t(index-1));
    crossingX = x(index-1) + fraction*(x(index)-x(index-1));
    crossingY = y(index-1) + fraction*(y(index)-y(index-1));
else
    crossingTime = t(index);
    crossingX = x(index);
    crossingY = y(index);
end
end
