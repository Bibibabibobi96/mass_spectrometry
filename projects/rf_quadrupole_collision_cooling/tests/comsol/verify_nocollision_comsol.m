reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
paths = rf_quadrupole_paths();
contract = load_rf_quadrupole_contract();
interface = jsondecode(fileread(fullfile(projectRoot,'config','interface_contract.json')));
g = contract.geometry_mm;
modelPath = getenv('RFQUAD_COMSOL_MODEL_PATH');
assert(~isempty(modelPath) && isfile(modelPath), ...
    'RFQUAD_COMSOL_MODEL_PATH must name an existing candidate MPH.');
expectedParticles = str2double(getenv('RFQUAD_EXPECTED_PARTICLES'));
expectedHits = str2double(getenv('RFQUAD_EXPECTED_HITS'));
expectedRfPeakV = str2double(getenv('RFQUAD_EXPECTED_RF_PEAK_V'));
expectedFrequencyHz = str2double(getenv('RFQUAD_EXPECTED_FREQUENCY_HZ'));
assert(all(isfinite([expectedParticles,expectedHits,expectedRfPeakV,expectedFrequencyHz])), ...
    'Expected GUI verification values are missing.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

import com.comsol.model.util.*
fprintf(fid, 'MATLAB_VERSION=%s\n', version);
fprintf(fid, 'COMSOL_VERSION=%s\n', char(ModelUtil.getComsolVersion));
fprintf(fid, 'MODEL=%s\n', modelPath);
model = mphload(modelPath, 'RFQuadTransportGuiVerify');
writeGuiSolverDiagnostic(fid, model, 'after_mphload');

assert(abs(model.param.evaluate('r0')*1e3 - g.inscribed_radius_r0) < 1e-9, ...
    'Persisted r0 is not the SIMION reference value.');
assert(abs(model.param.evaluate('r_rod')*1e3 - g.rod_radius) < 1e-9, ...
    'Persisted rod radius is not the SIMION reference value.');
assert(abs(model.param.evaluate('L_rod')*1e3 - g.rod_length) < 1e-9, ...
    'Persisted rod length is not the SIMION reference value.');
assert(abs(model.param.evaluate('V_rf') - expectedRfPeakV) < 1e-8, ...
    'Persisted RF amplitude moved from the transport contract.');
assert(abs(model.param.evaluate('f_rf') - expectedFrequencyHz) < 1e-6, ...
    'Persisted RF frequency moved from the transport contract.');
assert(abs(model.param.evaluate('z_rod_exit')*1e3 - interface.planes.rod_exit.z_mm) < 1e-9, ...
    'Persisted rod-exit plane moved from the interface contract.');
assert(abs(model.param.evaluate('z_handoff')*1e3 - interface.planes.handoff.z_mm) < 1e-9, ...
    'Persisted handoff plane moved from the interface contract.');
assert(abs(model.param.evaluate('z_acceptance')*1e3 - interface.planes.acceptance_detector.z_mm) < 1e-9, ...
    'Persisted acceptance plane moved from the interface contract.');

cpt = model.component('comp1').physics('cpt');
featureTags = cell(cpt.feature.tags());
releaseTags = featureTags(startsWith(featureTags, 'rel'));
assert(numel(releaseTags) == expectedParticles, 'GUI-visible release-node count differs from the run config.');
assert(~any(contains(lower(string(featureTags)), 'coll')), ...
    'A collision feature is present in the no-collision candidate.');
assert(any(strcmp(featureTags, 'ef1')), 'GUI-visible RF Electric Force is absent.');
assert(numel(model.component('comp1').selection('sel_vac').entities()) > 0, ...
    'Persisted vacuum selection is empty.');
exportTags = cell(model.result.export.tags());
assert(any(strcmp(exportTags, 'exp_phase_raw')), ...
    'GUI-visible raw particle phase-space export is absent.');

initialSolutions = joinJavaStrings(model.sol.tags);
assert(model.sol('sol1').isAttached(), 'sol1 is not attached to std1.');
assert(model.sol('sol2').isAttached(), 'sol2 is not attached to std2.');
hasStaticSolution=any(strcmp(cell(model.sol.tags()),'sol_static'));
if hasStaticSolution
    assert(model.sol('sol_static').isAttached(), 'sol_static is not attached to std_static.');
end
fprintf(fid, 'SOLUTION_TAGS_INITIAL=%s\n', initialSolutions);

writeGuiSolverDiagnostic(fid, model, 'before_std1');
tStatic = tic;
model.study('std1').run;
fprintf(fid, 'STD1_GUI_COMPUTE_SECONDS=%.6f\n', toc(tStatic));
writeGuiSolverDiagnostic(fid, model, 'after_std1');
if hasStaticSolution
    tStaticEndplate=tic;
    model.study('std_static').run;
    fprintf(fid, 'STD_STATIC_GUI_COMPUTE_SECONDS=%.6f\n', toc(tStaticEndplate));
end
afterStatic = joinJavaStrings(model.sol.tags);
assert(strcmp(afterStatic, initialSolutions), ...
    'std1 GUI Compute generated an unexpected solver sequence.');

writeGuiSolverDiagnostic(fid, model, 'before_std2');
tParticle = tic;
model.study('std2').run;
fprintf(fid, 'STD2_GUI_COMPUTE_SECONDS=%.6f\n', toc(tParticle));
afterParticle = joinJavaStrings(model.sol.tags);
assert(strcmp(afterParticle, initialSolutions), ...
    'std2 GUI Compute generated an unexpected solver sequence.');

pd = mphparticle(model, 'dataset', 'pdset1');
x = squeeze(pd.p(:,:,1));
y = squeeze(pd.p(:,:,2));
z = squeeze(pd.p(:,:,3));
radial = sqrt(x.^2 + y.^2);
assert(size(z,2) == expectedParticles, 'GUI Compute did not preserve the configured particle source.');
detectorZ = interface.planes.acceptance_detector.z_mm;
detectorRadius = g.enclosure.detector_radius_mm;
hits = false(1, size(z,2));
arrival = nan(1, size(z,2));
for particle = 1:size(z,2)
    sample = find(z(:,particle) >= detectorZ-1e-6, 1, 'first');
    if ~isempty(sample) && radial(sample,particle) <= detectorRadius
        hits(particle) = true;
        arrival(particle) = pd.t(sample)*1e6;
    end
end
fprintf(fid, 'PARTICLES=%d\n', size(z,2));
fprintf(fid, 'HITS=%d\n', sum(hits));
fprintf(fid, 'TRANSMISSION=%.12g\n', mean(hits));
fprintf(fid, 'MEAN_DETECTOR_TIME_US=%.12g\n', mean(arrival,'omitnan'));
fprintf(fid, 'Q_MATHIEU=%.12g\n', mphglobal(model,'q_mathieu','dataset','dset1'));
assert(sum(hits) == expectedHits, 'GUI Compute hit count moved from the saved candidate result.');

fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('RFQuadTransportGuiVerify');

function text = joinJavaStrings(values)
items = cell(1, length(values));
for idx = 1:length(values)
    items{idx} = char(values(idx));
end
text = strjoin(items, ',');
end

function writeGuiSolverDiagnostic(fid, model, stage)
try
    try
        document = collectGuiSolverDiagnostic(model, stage);
    catch diagnosticError
        document = struct( ...
            'schema_version', 1, ...
            'role', 'rf_quadrupole_gui_solver_diagnostic', ...
            'stage', stage, ...
            'collector_status', 'error', ...
            'collector_error_identifier', char(diagnosticError.identifier), ...
            'collector_error_message', char(diagnosticError.message));
    end
    try
        encoded = jsonencode(document);
    catch encodingError
        fallback = struct( ...
            'schema_version', 1, ...
            'role', 'rf_quadrupole_gui_solver_diagnostic', ...
            'stage', stage, ...
            'collector_status', 'encoding_error', ...
            'collector_error_identifier', char(encodingError.identifier), ...
            'collector_error_message', char(encodingError.message));
        encoded = jsonencode(fallback);
    end
    fprintf(fid, 'GUI_SOLVER_DIAGNOSTIC_JSON=%s\n', encoded);
catch
    % Diagnostics are observational and must never replace the primary GUI error.
end
end

function document = collectGuiSolverDiagnostic(model, stage)
document = struct( ...
    'schema_version', 1, ...
    'role', 'rf_quadrupole_gui_solver_diagnostic', ...
    'stage', stage, ...
    'collector_status', 'ok');
document.study_tags = safeDiagnosticGetter(@() diagnosticTags(model.study.tags()));
document.solver_sequence_tags = safeDiagnosticGetter(@() diagnosticTags(model.sol.tags()));
document.studies = struct( ...
    'std1', diagnosticStudy(model, 'std1'), ...
    'std2', diagnosticStudy(model, 'std2'));
document.solvers = struct( ...
    'sol1', diagnosticSolver(model, 'sol1'), ...
    'sol2', diagnosticSolver(model, 'sol2'));
document.sol2_v1 = struct( ...
    'exists', safeDiagnosticGetter( ...
        @() hasDiagnosticTag(model.sol('sol2').feature.tags(), 'v1')), ...
    'notsolmethod', safeDiagnosticGetter( ...
        @() char(model.sol('sol2').feature('v1').getString('notsolmethod'))), ...
    'notsol', safeDiagnosticGetter( ...
        @() char(model.sol('sol2').feature('v1').getString('notsol'))));
document.sol2_v1.dependency_solver_tag = document.sol2_v1.notsol;
end

function state = diagnosticStudy(model, tag)
state = struct( ...
    'exists', safeDiagnosticGetter(@() hasDiagnosticTag(model.study.tags(), tag)), ...
    'step_tags', safeDiagnosticGetter( ...
        @() diagnosticTags(model.study(tag).feature.tags())));
end

function state = diagnosticSolver(model, tag)
state = struct( ...
    'exists', safeDiagnosticGetter(@() hasDiagnosticTag(model.sol.tags(), tag)), ...
    'feature_tags', safeDiagnosticGetter( ...
        @() diagnosticTags(model.sol(tag).feature.tags())), ...
    'is_attached', safeDiagnosticGetter(@() logical(model.sol(tag).isAttached())), ...
    'is_initialized', safeDiagnosticGetter( ...
        @() logical(model.sol(tag).isInitialized())), ...
    'is_empty', safeDiagnosticGetter(@() logical(model.sol(tag).isEmpty())));
end

function result = safeDiagnosticGetter(getter)
try
    result = struct( ...
        'status', 'ok', ...
        'value', [], ...
        'error_identifier', '', ...
        'error_message', '');
    result.value = getter();
catch getterError
    result = struct( ...
        'status', 'error', ...
        'value', [], ...
        'error_identifier', char(getterError.identifier), ...
        'error_message', char(getterError.message));
end
end

function present = hasDiagnosticTag(values, expected)
present = any(strcmp(diagnosticTags(values), expected));
end

function items = diagnosticTags(values)
items = cell(1, length(values));
for idx = 1:length(values)
    items{idx} = char(values(idx));
end
end
