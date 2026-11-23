reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(fileparts(testDir)));
addpath(projectRoot);
addpath(fullfile(projectRoot,'comsol'));
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
observationRoot=getenv('RFQUAD_GUI_OBSERVATION_ROOT');
assert(~isempty(observationRoot)&&isfolder(observationRoot),'rfquad:GuiObservationOutput','Explicit current-owner observation output directory required.');
ownerExecutionRoot=getenv('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY');
ownerPersistentRoot=getenv('MASS_SPECTROMETRY_RUN_DIRECTORY');
assert(~isempty(ownerExecutionRoot)&&~isempty(ownerPersistentRoot)&& ...
 (sameGuiPath(observationRoot,fullfile(ownerExecutionRoot,'results'))|| ...
  sameGuiPath(observationRoot,fullfile(ownerPersistentRoot,'results'))), ...
 'rfquad:GuiObservationOutput','Observation output must be the explicit current public owner result directory.');
metadata=jsondecode(fileread(getenv('RFQUAD_SOLVER_RAW_METADATA_PATH')));
nativeOrder=metadata.native_order(:);assert(isequal(sort(nativeOrder),(1:expectedParticles)'),'GUI source mapping is not a full permutation.');
assert(numel(releaseTags)==metadata.release_group_count,'GUI grouped release count differs from actual source plan.');
% Bind the complete frozen source before changing the loaded model. This is
% configuration/file evidence, separate from availability of a native birth echo.
assert(numel(metadata.source_birth_s)==expectedParticles&& ...
 isequal(size(metadata.source_initial_position_mm),[expectedParticles 3])&& ...
 isequal(size(metadata.source_initial_velocity_m_s),[expectedParticles 3]), ...
 'rfquad:GuiSourceBinding','Frozen source 6D/birth dimensions differ.');
sourceBindings=cell(1,numel(releaseTags));releasePaths=cell(size(sourceBindings));importedCount=0;
for releaseIndex=1:numel(releaseTags)
 release=cpt.feature(releaseTags{releaseIndex});entry=metadata.release_files(releaseIndex);
 assert(strcmp(char(release.getType()),'ReleaseFromDataFile'),'rfquad:GuiSourceBinding','GUI release feature type differs.');
 relative=strrep(char(entry.relative_path),char(92),'/');
 assert(~isempty(regexp(relative,'^runtime/particle_[0-9]+[.]txt$','once')),'Frozen release role path is invalid.');
 releasePaths{releaseIndex}=fullfile(runRoot,relative);
 data=readmatrix(releasePaths{releaseIndex},'FileType','text','Delimiter',char(9));
 assert(importedCount+size(data,1)<=expectedParticles,'rfquad:GuiSourceBinding','Release files exceed the original mother population.');
 rows=nativeOrder(importedCount+(1:size(data,1)));
 sourceBindings{releaseIndex}=validateGuiReleaseBinding(release,entry,rows,metadata,data,guiAllowedReleaseFilenames(runConfig,runRoot,relative));
 importedCount=importedCount+size(data,1);
end
assert(importedCount==expectedParticles,'rfquad:GuiSourceBinding','GUI imported mother population differs.');
saved=readGuiStoredObservations(model,metadata,nativeOrder,expectedParticles,g);
persistGuiObservation(fullfile(observationRoot,'gui_observations_saved.mat'),saved,metadata,'saved_before_compute');
savedBirth=guiNativeBirthObservation(saved,metadata,nativeOrder);
[savedHits,~,savedOutcomes]=guiCensusAndTerminal(saved,interface,g);
sourceReport=struct('source_binding_verified',true,'release_bindings',{sourceBindings}, ...
 'saved_native_birth_observation',savedBirth);
fprintf(fid,'GUI_SOURCE_BINDING_JSON=%s\n',jsonencode(sourceReport));
writeGuiJson(fullfile(observationRoot,'gui_source_binding.json'),sourceReport);
for releaseIndex=1:numel(releaseTags)
 release=cpt.feature(releaseTags{releaseIndex});
 release.set('Filename',releasePaths{releaseIndex});release.importData();
 fprintf(fid,'SOURCE_FILE_REBIND=loaded_copy_only RELEASE_TAG=%s CANONICAL_PATH=%s\n',releaseTags{releaseIndex},releasePaths{releaseIndex});
end
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

current=readGuiStoredObservations(model,metadata,nativeOrder,expectedParticles,g);
persistGuiObservation(fullfile(observationRoot,'gui_observations_computed.mat'),current,metadata,'computed_after_std1_std2');
currentBirth=guiNativeBirthObservation(current,metadata,nativeOrder);
[hits,arrival,currentOutcomes]=guiCensusAndTerminal(current,interface,g);
parity=compare_rf_gui_observations(saved,current,savedOutcomes,currentOutcomes);
parity.role='rf_interface_gui_parity';parity.source_binding_verified=true;
parity.gui_operation_completed=true;parity.original_acceptance_verified=(sum(hits)==expectedHits);
parity.original_acceptance=struct('particles',numel(current.records),'expected_particles',expectedParticles, ...
 'hits',sum(hits),'expected_hits',expectedHits);
parity.status='FAIL';if parity.original_acceptance_verified,parity.status='PASS';end
parity.snapshot_files={'gui_observations_saved.mat','gui_observations_computed.mat'};
parity.saved_native_birth_observation=savedBirth;parity.computed_native_birth_observation=currentBirth;
parity.native_birth_echo_unavailable_saved_observation=savedBirth.native_birth_echo_unavailable_saved_observation;
parity.per_id_acceptance_difference_count=nnz(savedHits~=hits);
writeGuiJson(fullfile(observationRoot,'gui_verification.json'),parity);
fprintf(fid,'GUI_PARITY_JSON=%s\n',jsonencode(parity));
fprintf(fid, 'PARTICLES=%d\n', numel(current.records));
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

function binding=validateGuiReleaseBinding(release,entry,rows,metadata,data,allowedFilenames)
% Settings/file authority are not an independent native initial-state echo.
binding=struct();
for name={'Filename','icolp','VelocitySpecification','InitialVelocity','icolv','rt'}
 binding.(name{1})=char(release.getString(name{1}));
end
assert(any(cellfun(@(path)sameGuiPath(binding.Filename,path),allowedFilenames)), ...
 'rfquad:GuiSourceBinding','Saved release Filename is not the declared current/persistent/original-owner path.');
assert(strcmp(binding.icolp,'0')&&strcmp(binding.VelocitySpecification,'SpecifyVelocity')&& ...
 strcmp(binding.InitialVelocity,'FromFile')&&strcmp(binding.icolv,'3'), ...
 'rfquad:GuiSourceBinding','Saved position/velocity column binding differs.');
assert(isequal(rows(:),entry.source_rows(:)),'rfquad:GuiSourceBinding','Group source-row order differs.');
birth=metadata.source_birth_s(rows);
assert(all(isfinite(birth))&&all(birth==birth(1))&&entry.birth_s==birth(1)&& ...
 strcmp(binding.rt,sprintf('%.17g[s]',birth(1))), ...
 'rfquad:GuiSourceBinding','Saved exact release time differs from the frozen group.');
expected=[metadata.source_initial_position_mm(rows,:) metadata.source_initial_velocity_m_s(rows,:)];
assert(isequal(size(data),size(expected))&&size(data,2)==6&&all(isfinite(data),'all')&&isequal(data,expected), ...
 'rfquad:GuiSourceBinding','Release file does not preserve the complete frozen six columns.');
binding.source_rows=rows(:)';binding.particle_ids=metadata.source_ids(rows);binding.birth_s=birth(1);
binding.source_binding_verified=true;
end

function paths=guiAllowedReleaseFilenames(runConfig,runRoot,relative)
% The one historical representation is proven by that original owner's actual
% completion. Do not search roots or accept another file by its basename.
persistentRun=fullfile(runConfig.paths.artifact_root,'projects',runConfig.project,'runs',runConfig.run_id);
paths={fullfile(runRoot,relative),fullfile(persistentRun,relative)};
receiptPath=fullfile(persistentRun,'results','execution_completion.json');
if isfile(receiptPath)
 receipt=jsondecode(fileread(receiptPath));
 assert(strcmp(receipt.role,'run_artifact_workflow_completion')&&strcmp(receipt.run_id,runConfig.run_id), ...
  'rfquad:GuiSourceBinding','Original owner completion identity differs.');
 if isfield(receipt,'execution_alias')
  alias=receipt.execution_alias;
  assert(sameGuiPath(alias.target_directory,persistentRun),'rfquad:GuiSourceBinding','Original alias target is not this frozen run.');
  paths{end+1}=fullfile(alias.path,relative);
 end
end
end

function equal=sameGuiPath(a,b)
a=strrep(char(a),char(92),'/');b=strrep(char(b),char(92),'/');
if ispc,equal=strcmpi(a,b);else,equal=strcmp(a,b);end
end

function saved=readGuiStoredObservations(model,metadata,nativeOrder,expectedParticles,g)
info=mphsolinfo(model,'soltag','sol2');times=info.solvals(:);
assert(strcmp(info.soltype,'Time')&&~isempty(times)&&all(isfinite(times))&&all(diff(times)>0), ...
 'rfquad:GuiObservationClock','Stored solution clock is invalid.');
ids=metadata.source_ids(:);
assert(numel(ids)==expectedParticles&&all(isfinite(ids))&&all(ids==fix(ids))&&all(ids>0)&&numel(unique(ids))==expectedParticles, ...
 'rfquad:GuiSourceBinding','Frozen original particle IDs are not complete and unique.');
% Stride1 retains every finite ORIGINAL stored observation, with the shared
% reader's full-ID mapping, inactive-state and lifecycle-gap checks.
[records,receipt]=extract_rf_particle_records(model,'sol2','pdset1','cpt', ...
 ids(nativeOrder)',[],[g.rod_z_min g.rod_z_max],1,256);
assert(numel(records)==expectedParticles,'rfquad:GuiObservationCount','Stored mother population differs.');
saved=struct('time_s',times,'records',{records},'extraction',receipt);
end

function echo=guiNativeBirthObservation(saved,metadata,nativeOrder)
tolerance=1e-12; % Preserve the prior source readback budget, mm and m/s.
verified=[];unavailable=[];
for native=1:numel(nativeOrder)
 row=nativeOrder(native);record=saved.records{native};birth=metadata.source_birth_s(row);
 assert(~any(record.time_s<birth),'rfquad:GuiSourceClock','Finite native state precedes frozen birth.');
 sample=find(record.time_s==birth,1);
 if isempty(sample)
  unavailable(end+1)=record.particle_id; %#ok<AGROW>
 else
  assert(max(abs(record.position_mm(sample,:)-metadata.source_initial_position_mm(row,:)))<=tolerance&& ...
   max(abs(record.velocity_m_s(sample,:)-metadata.source_initial_velocity_m_s(row,:)))<=tolerance, ...
   'rfquad:GuiNativeBirth','Available exact stored birth state differs from source authority.');
  verified(end+1)=record.particle_id; %#ok<AGROW>
 end
end
echo=struct('native_birth_echo_unavailable_saved_observation',~isempty(unavailable), ...
 'unavailable_particle_ids',unavailable,'verified_exact_stored_birth_particle_ids',verified, ...
 'source_transport_tolerance_mm_and_m_s',tolerance);
end

function [hits,arrival,outcomes]=guiCensusAndTerminal(saved,interface,g)
count=numel(saved.records);hits=false(1,count);arrival=nan(1,count);outcomes=cell(1,count);
for index=1:count
 record=saved.records{index};p=record.position_mm;radial=hypot(p(:,1),p(:,2));
 sample=find(p(:,3)>=interface.planes.census.z_mm-1e-6,1,'first');
 if ~isempty(sample)&&radial(sample)<=g.enclosure.physical_detector_radius_mm
  hits(index)=true;arrival(index)=record.time_s(sample)*1e6;
 end
 rejection='';
 if ~hits(index)
  if p(end,3)<0,rejection='backward_escape';
  elseif radial(end)>g.enclosure.outer_half_width_mm,rejection='radial_escape';end
 end
 outcome=classify_finite_particle_terminal(record,hits(index),rejection);
 outcome.particle_id=record.particle_id;outcomes{index}=outcome;
end
end

function result=persistGuiObservation(path,observation,metadata,stage)
% Existing extraction records, with explicit units/original source mapping.
assert(~isfile(path),'rfquad:GuiObservationOutput','Never overwrite a completed observation snapshot.');
units=struct('position','mm','velocity','m/s','time','s','clock','absolute_instrument_time','frame','rf_quadrupole_component');
save(path,'observation','metadata','units','stage','-v7');
result=struct('path',path,'particles',numel(observation.records),'stage',stage);
end

function writeGuiJson(path,value)
fid=fopen(path,'w','n','UTF-8');assert(fid>=0,'rfquad:GuiObservationOutput','Cannot persist GUI diagnostics.');
cleanup=onCleanup(@()fclose(fid));fprintf(fid,'%s',jsonencode(value));
end
