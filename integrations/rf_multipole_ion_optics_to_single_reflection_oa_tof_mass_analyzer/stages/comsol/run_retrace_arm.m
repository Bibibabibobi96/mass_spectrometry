% Run one validated declarative COMSOL retrace arm.
%
% The PowerShell boundary validates the JSON contract before COMSOL starts.
% This vendor-side boundary repeats the safety-critical identity, velocity,
% change-class, and census checks rather than trusting process environment.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
armPath = getenv('RF_OATOF_COMSOL_RETRACE_ARM');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');
assert(isfile(armPath), 'RF_OATOF_COMSOL_RETRACE_ARM must identify an arm JSON.');
arm = jsondecode(fileread(armPath));
assert(arm.schema_version == 1 && strcmp(arm.role, 'rf_oatof_comsol_retrace_arm'), ...
    'COMSOL retrace arm identity is invalid.');
assert(any(strcmp(arm.change_class, {'source','field_mask','voltage'})), ...
    'Geometry and mesh changes require the governed model builder.');
assert(isfile(arm.source_model) && isfile(arm.cartesian_release) && ...
    isfile(arm.handoff_receipt) && isfile(arm.source_model_metadata) && ...
    isfile(arm.cartesian_release_metadata) && isfolder(arm.output_root), ...
    'COMSOL retrace arm paths are incomplete.');
receipt = jsondecode(fileread(arm.handoff_receipt));
modelMetadata = jsondecode(fileread(arm.source_model_metadata));
releaseMetadata = jsondecode(fileread(arm.cartesian_release_metadata));
assert(strcmp(receipt.role, 'simion_winner_to_comsol_handoff_receipt') && ...
    strcmp(receipt.status, 'frozen'), 'Handoff receipt identity is invalid.');
assert(strcmp(modelMetadata.role, 'rf_oatof_comsol_source_model_identity') && ...
    strcmp(releaseMetadata.role, 'rf_oatof_comsol_cartesian_retrace_release'), ...
    'Frozen source metadata identity is invalid.');
assert(strcmpi(file_sha256(arm.source_model), arm.source_model_sha256) && ...
    strcmpi(file_sha256(arm.source_model), receipt.source_model.mph.sha256) && ...
    strcmpi(file_sha256(arm.source_model_metadata), receipt.source_model.metadata.sha256) && ...
    strcmpi(file_sha256(arm.cartesian_release), releaseMetadata.output.sha256), ...
    'Frozen retrace input SHA-256 changed after preflight.');

repoRoot = getenv('RF_OATOF_COMSOL_RETRACE_REPO_ROOT');
assert(isfolder(repoRoot), 'RF_OATOF_COMSOL_RETRACE_REPO_ROOT is required.');
projectComsol = fullfile(repoRoot, 'projects', ...
    'single_reflection_oa_tof_mass_analyzer', 'comsol');
addpath(projectComsol);

release = readtable(arm.cartesian_release, 'VariableNamingRule', 'preserve');
requiredColumns = {'particle_id','mass_amu','charge_state','x_mm','y_mm','z_mm', ...
    'vx_m_per_s','vy_m_per_s','vz_m_per_s','kinetic_energy_eV'};
assert(isequal(release.Properties.VariableNames, requiredColumns), ...
    'Cartesian release columns or ordering differ from the contract.');
particleIds = release.particle_id;
assert(all(isfinite(particleIds)) && all(particleIds == floor(particleIds)) && ...
    numel(unique(particleIds)) == height(release), ...
    'Cartesian release particle identity is invalid.');
assert(all(abs(release.mass_amu-arm.mass_amu) < 1e-9) && ...
    all(release.charge_state == 1), 'Cartesian release species differs.');
velocity = [release.vx_m_per_s,release.vy_m_per_s,release.vz_m_per_s];
assert(all(isfinite(velocity), 'all'), 'Cartesian release velocity is not finite.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
censusPath = fullfile(arm.output_root, 'particle_census.csv');
particlesPath = fullfile(arm.output_root, 'particles.csv');
try
    model = mphopen(arm.source_model);
    rel = model.component('comp1').physics('cpt').feature('rel1');
    releaseData = [release.x_mm,release.y_mm,release.z_mm,velocity];
    releasePath = fullfile(arm.output_root, 'cartesian_release_from_data_file.txt');
    writematrix(releaseData, releasePath, 'Delimiter', 'tab');
    serialized = readmatrix(releasePath, 'FileType', 'text');
    velocityResidual = serialized(:,4:6)-velocity;
    maximumVelocityResidual = max(abs(velocityResidual), [], 'all');
    assert(maximumVelocityResidual < 1e-6, ...
        'COMSOL release velocity does not preserve global Cartesian components.');
    rel.set('Filename', releasePath);
    rel.set('icolp', '0');
    rel.set('VelocitySpecification', 'SpecifyVelocity');
    rel.set('InitialVelocity', 'FromFile');
    rel.set('icolv', '3');
    rel.importData();

    % Reset every governed parameter to the frozen source-model baseline,
    % then apply only the declared variation for this arm.
    set_parameter_object(model, arm.baseline_field_mask, 'field mask');
    set_parameter_object(model, arm.baseline_voltages_V, 'voltage');
    set_parameter_object(model, arm.field_mask, 'field mask');
    set_parameter_object(model, arm.voltage_overrides_V, 'voltage');
    electrostaticsRerun = strcmp(arm.change_class, 'voltage');
    if electrostaticsRerun
        model.study('std1').run;
    end
    model.study('std2').run;

    try, model.result.dataset.remove('retrace_pdset'); catch, end
    dataset = model.result.dataset.create('retrace_pdset', 'Particle');
    dataset.set('solution', 'sol2');
    data = mphparticle(model, 'dataset', 'retrace_pdset', ...
        'expr', {'qx','qy','qz'}, 'dataonly', 'on');
    t = data.t(:);
    x = orient_time_by_particle(squeeze(data.d1), numel(t));
    y = orient_time_by_particle(squeeze(data.d2), numel(t));
    z = orient_time_by_particle(squeeze(data.d3), numel(t));
    assert(size(z,2) == height(release), ...
        'Solved particle count differs from Cartesian release.');
    detectorZ = mphevaluate(model, 'detector_z', 'mm');
    detectorX = mphevaluate(model, 'detector_x', 'mm');
    detectorRadius = mphevaluate(model, 'detector_radius', 'mm');
    arrivals = oatof_extract_detector_arrivals( ...
        t,x,y,z,detectorZ,1e-3,0.5,detectorX,0,detectorRadius);
    [status,rawStatus] = classify_terminal_status(t,x,y,z,arrivals);
    tofUs = arrivals.time_s(:)*1e6;
    radiusMm = arrivals.radius_mm(:);
    census = table(particleIds,tofUs,status,rawStatus,radiusMm, ...
        release.x_mm,release.y_mm,release.z_mm,release.vx_m_per_s, ...
        release.vy_m_per_s,release.vz_m_per_s,release.kinetic_energy_eV, ...
        'VariableNames', {'particle_id','tof_us','status','solver_raw_status', ...
        'detector_radius_mm','initial_x_mm','initial_y_mm','initial_z_mm', ...
        'initial_vx_m_per_s','initial_vy_m_per_s','initial_vz_m_per_s', ...
        'initial_energy_eV'});
    assert(height(census) == height(release) && ...
        isequal(census.particle_id,particleIds), ...
        'Census does not preserve every released particle in order.');
    writetable(census, censusPath);
    writetable(census(status == "hit",:), particlesPath);
    if ~isempty(arm.output_model)
        mphsave(model, arm.output_model);
    end
    fprintf(fid, ['STATUS=PASS\nARM=%s\nCHANGE_CLASS=%s\nPARTICLES=%d\n' ...
        'DETECTED=%d/%d\nMAX_RELEASE_VELOCITY_RESIDUAL_M_PER_S=%.12g\n' ...
        'MESH_REBUILT=0\nELECTROSTATICS_RERUN=%d\nPARTICLE_SOLVE=1\n'], ...
        arm.arm_id,arm.change_class,height(release),sum(status == "hit"), ...
        height(release),maximumVelocityResidual,electrostaticsRerun);
catch exception
    if ~exist('particleIds', 'var'), particleIds = zeros(0,1); end
    failureCount = numel(particleIds);
    failureStatus = repmat("solver_failure", failureCount, 1);
    failureRawStatus = repmat(string(exception.identifier), failureCount, 1);
    failureTof = nan(failureCount,1);
    failureRadius = nan(failureCount,1);
    if exist('release', 'var') && height(release) == failureCount
        failureCensus = table(particleIds,failureTof,failureStatus,failureRawStatus, ...
            failureRadius,release.x_mm,release.y_mm,release.z_mm,release.vx_m_per_s, ...
            release.vy_m_per_s,release.vz_m_per_s,release.kinetic_energy_eV, ...
            'VariableNames',{'particle_id','tof_us','status','solver_raw_status', ...
            'detector_radius_mm','initial_x_mm','initial_y_mm','initial_z_mm', ...
            'initial_vx_m_per_s','initial_vy_m_per_s','initial_vz_m_per_s', ...
            'initial_energy_eV'});
    else
        failureCensus = table(particleIds,failureTof,failureStatus,failureRawStatus, ...
            failureRadius,'VariableNames',{'particle_id','tof_us','status', ...
            'solver_raw_status','detector_radius_mm'});
    end
    writetable(failureCensus, censusPath);
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function set_parameter_object(model,object,role)
names = fieldnames(object);
for index = 1:numel(names)
    name = names{index}; value = object.(name);
    assert(isnumeric(value) && isscalar(value) && isfinite(value), ...
        '%s parameter %s must be finite scalar.', role, name);
    if strcmp(role, 'field mask')
        assert(~isempty(regexp(name, ...
            '^ideal_(accel|drift|stage1|stage2)_(ex|ey|ez)$', 'once')) && ...
            any(value == [0 1]), 'Invalid field-mask parameter: %s', name);
        model.param.set(name, sprintf('%d', value));
    else
        assert(~isempty(regexp(name, '^V_[A-Za-z][A-Za-z0-9_]*$', 'once')), ...
            'Invalid voltage parameter: %s', name);
        model.param.set(name, sprintf('%.17g[V]', value));
    end
end
end

function values = orient_time_by_particle(values,timeCount)
if size(values,1) == timeCount, return; end
if size(values,2) == timeCount, values = values.'; return; end
error('Unexpected particle array shape.');
end

function [status,rawStatus] = classify_terminal_status(t,x,y,z,arrivals)
count = size(z,2);
status = repmat("solver_failure",count,1);
rawStatus = arrivals.status(:);
for particle = 1:count
    if arrivals.hit(particle)
        status(particle) = "hit";
        continue
    end
    raw = rawStatus(particle);
    if raw == "outside_active_radius" || startsWith(raw,"freeze") || ...
            raw == "frozen_on_detector"
        status(particle) = "wall";
        continue
    end
    % Without a persisted COMSOL terminal-event identity, trajectory shape
    % alone cannot distinguish wall, escape, timeout, and solver failure.
    % Fail closed instead of publishing an inferred physical loss cause.
    status(particle) = "solver_failure";
end

function digest = file_sha256(path)
stream = java.io.FileInputStream(java.io.File(path));
cleanup = onCleanup(@() stream.close());
hash = java.security.MessageDigest.getInstance('SHA-256');
buffer = zeros(1,1048576,'int8');
while true
    count = stream.read(buffer,0,numel(buffer));
    if count < 0, break; end
    hash.update(buffer(1:count));
end
bytes = typecast(hash.digest(),'uint8');
digest = upper(reshape(dec2hex(bytes,2).',1,[]));
clear cleanup
end
assert(all(ismember(status, ...
    ["hit","wall","escape","timeout","solver_failure"])), ...
    'Unknown census status was produced.');
end
