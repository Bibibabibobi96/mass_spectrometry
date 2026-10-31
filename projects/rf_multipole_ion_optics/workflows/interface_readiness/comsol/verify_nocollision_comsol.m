reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(fileparts(testDir)));
addpath(projectRoot);
runConfigPath=getenv('RFQUAD_RUN_CONFIG');
assert(~isempty(runConfigPath)&&isfile(runConfigPath),'rfquad:GuiFrozenInputs', ...
    'RFQUAD_RUN_CONFIG must identify the original frozen GUI task inputs.');
runConfig=jsondecode(fileread(runConfigPath));
assert(strcmp(runConfig.role,'rf_quadrupole_comsol_run_config')&& ...
    strcmp(runConfig.project,'rf_multipole_ion_optics')&& ...
    strcmp(runConfig.workflow_id,'transport_interface_readiness'), ...
    'rfquad:GuiFrozenInputs','GUI task inputs belong to another workflow.');
assert(isfield(runConfig,'inputs')&&isfield(runConfig.inputs,'resolved_design')&& ...
    isfield(runConfig.inputs,'interface_contract')&& ...
    isfile(runConfig.inputs.resolved_design)&&isfile(runConfig.inputs.interface_contract), ...
    'rfquad:GuiFrozenInputs','Frozen GUI design or interface contract is missing.');
contract=load_rf_quadrupole_contract(runConfig.inputs.resolved_design);
interface=jsondecode(fileread(runConfig.inputs.interface_contract));
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
assert(abs(model.param.evaluate('z_acceptance')*1e3 - interface.planes.census.z_mm) < 1e-9, ...
    'Persisted acceptance plane moved from the interface contract.');

cpt = model.component('comp1').physics('cpt');
featureTags = cell(cpt.feature.tags());
releaseTags = featureTags(startsWith(featureTags, 'rel'));
runRoot=getenv('RFQUAD_GUI_RUN_ROOT');assert(~isempty(runRoot)&&isfolder(runRoot),'Explicit persistent GUI run base required.');
metadata=jsondecode(fileread(getenv('RFQUAD_SOLVER_RAW_METADATA_PATH')));
nativeOrder=metadata.native_order(:);assert(isequal(sort(nativeOrder),(1:expectedParticles)'),'GUI source mapping is not a full permutation.');
assert(numel(releaseTags)==metadata.release_group_count,'GUI grouped release count differs from actual source plan.');
% Validate saved cold solution BEFORE rebinding/importing any execution source.
[~,~,sourceTransportTolerance]=readAndValidateGuiSource(model,metadata,nativeOrder,expectedParticles);
fprintf(fid,'SAVED_COLD_SOURCE_INITIALIZATION_VALIDATED=%d TRANSPORT_TOLERANCE_MM_AND_M_S=%.17g\n',expectedParticles,sourceTransportTolerance);
fprintf(fid,'GUI_CANONICAL_RUN_BASE=%s\n',runRoot);
importedCount=0;
for releaseIndex=1:numel(releaseTags)
 release=cpt.feature(releaseTags{releaseIndex});entry=metadata.release_files(releaseIndex);
 relative=strrep(char(entry.relative_path),'\','/');
 assert(~isempty(regexp(relative,'^runtime/particle_[0-9]+[.]txt$','once')),'Frozen release role path is invalid.');
 persistentReleasePath=fullfile(runRoot,relative);data=readmatrix(persistentReleasePath,'FileType','text','Delimiter',char(9));
 assert(size(data,2)==6&&all(isfinite(data),'all'),'GUI release has invalid 6D.');
 rows=nativeOrder(importedCount+(1:size(data,1)));assert(isequal(rows(:),entry.source_rows(:)),'Frozen group source order differs.');expected=[metadata.source_initial_position_mm(rows,:) metadata.source_initial_velocity_m_s(rows,:)];
 assert(isequal(data,expected),'GUI release source 6D differs.');
 expectedBirth=metadata.source_birth_s(rows);assert(entry.birth_s==expectedBirth(1),'Frozen group birth differs.');assert(all(expectedBirth==expectedBirth(1)),'GUI release merged different exact births.');
 assert(strcmp(char(release.getString('rt')),sprintf('%.17g[s]',expectedBirth(1))),'GUI release clock differs.');
 release.set('Filename',persistentReleasePath);release.importData();
 fprintf(fid,'SOURCE_FILE_REBIND=loaded_copy_only RELEASE_TAG=%s CANONICAL_PATH=%s\n',releaseTags{releaseIndex},persistentReleasePath);
 importedCount=importedCount+size(data,1);
end
assert(importedCount==expectedParticles,'GUI imported mother population differs.');
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

[pd,timeVector,sourceTransportTolerance]=readAndValidateGuiSource(model,metadata,nativeOrder,expectedParticles);
fprintf(fid,'GUI_COMPUTED_SOURCE_INITIALIZATION_VALIDATED=%d TRANSPORT_TOLERANCE_MM_AND_M_S=%.17g\n',expectedParticles,sourceTransportTolerance);
x = squeeze(pd.position_mm(:,:,1));
y = squeeze(pd.position_mm(:,:,2));
z = squeeze(pd.position_mm(:,:,3));
radial = sqrt(x.^2 + y.^2);
assert(size(z,2) == expectedParticles, 'GUI Compute did not preserve the configured particle source.');
detectorZ = interface.planes.census.z_mm;
detectorRadius = g.enclosure.physical_detector_radius_mm;
hits = false(1, size(z,2));
arrival = nan(1, size(z,2));
for particle = 1:size(z,2)
    sample = find(z(:,particle) >= detectorZ-1e-6, 1, 'first');
    if ~isempty(sample) && radial(sample,particle) <= detectorRadius
        hits(particle) = true;
        arrival(particle) = timeVector(sample)*1e6;
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

function [pd,timeVector,sourceTransportTolerance]=readAndValidateGuiSource(model,metadata,nativeOrder,expectedParticles)
solutionInfo=mphsolinfo(model,'soltag','sol2');timeVector=union(solutionInfo.solvals(:),metadata.source_birth_s(:));
assert(~isempty(timeVector)&&all(isfinite(timeVector))&&all(diff(timeVector)>0),'GUI solution clock invalid.');
% Same explicit unit expressions as the validated production window reader.
expressions={'cpt.pidx','x/1[mm]','y/1[mm]','z/1[mm]', ...
 'cpt.vx/1[m/s]','cpt.vy/1[m/s]','cpt.vz/1[m/s]'};
data=mphparticle(model,'dataset','pdset1','t',timeVector','expr',expressions,'dataonly','on');
assert(isstruct(data)&&all(isfield(data,{'d1','d2','d3','d4','d5','d6','d7'})),'GUI explicit-unit particle arrays missing.');
assert(size(data.d1,1)==numel(timeVector),'GUI particle time axis differs from explicit query clock.');
for fieldIndex=2:7
 assert(isequal(size(data.(sprintf('d%d',fieldIndex))),size(data.d1)),'GUI explicit-unit 6D/pidx shapes differ.');
end
pd=struct('position_mm',cat(3,data.d2,data.d3,data.d4), ...
 'velocity_m_s',cat(3,data.d5,data.d6,data.d7),'native_pidx',data.d1);
assert(size(pd.position_mm,2)==expectedParticles,'GUI native complete mother count differs.');
assert(isequal(isfinite(pd.position_mm),isfinite(pd.velocity_m_s))&&any(isfinite(pd.velocity_m_s),'all'),'GUI full active 6D required.');
sourceTransportTolerance=1e-12; % Existing six-column source readback budget: mm and m/s, not integration error.
for native=1:expectedParticles
 original=nativeOrder(native);birth=metadata.source_birth_s(original);sourceSample=find(timeVector==birth,1);
 assert(~isempty(sourceSample),'Authoritative exact birth missing from GUI query clock.');
 sourcePosition=reshape(pd.position_mm(sourceSample,native,:),1,3);sourceVelocity=reshape(pd.velocity_m_s(sourceSample,native,:),1,3);
 assert(all(isfinite(sourcePosition))&&all(isfinite(sourceVelocity)),'GUI source initialization cannot be validated: exact-birth active 6D unknown.');
 assert(max(abs(sourcePosition-metadata.source_initial_position_mm(original,:)))<=sourceTransportTolerance,'GUI actual source position differs from frozen transport budget.');
 assert(max(abs(sourceVelocity-metadata.source_initial_velocity_m_s(original,:)))<=sourceTransportTolerance,'GUI actual source velocity differs from frozen transport budget.');
 assert(~any(isfinite(pd.position_mm(1:sourceSample-1,native,:)),'all'),'GUI particle exists before authoritative birth.');
 ids=pd.native_pidx(:,native);ids=ids(isfinite(ids));assert(~isempty(ids)&&all(ids==native),'GUI native pidx differs.');
end
end
