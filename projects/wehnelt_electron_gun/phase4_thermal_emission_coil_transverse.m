function result = phase4_thermal_emission_coil_transverse(resolvedContractPath)
% Thermal CPT emission for the transverse-coil electron gun
% (helix axis perpendicular to the beam axis), directly comparable to
% the historical axial/coaxial coil under the same resolved baseline,
% to assess whether
% electron utilization (collection efficiency) actually improves.
% The selected resolved mode determines whether particle tracing is executed.

componentRoot = fileparts(mfilename('fullpath'));
addpath(componentRoot);
paths = egun_paths();
if nargin < 1 || isempty(resolvedContractPath)
    error('A resolved Wehnelt contract path is required; no defaults exist.');
end
contract = load_wehnelt_contract(char(resolvedContractPath));
executionMode = contract.numerical.execution_mode;
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = fullfile(paths.modelWorkspaceDir, 'ElectronGun_CoilT_ES.mph');
savePath  = fullfile(paths.modelWorkspaceDir, 'wehnelt_electron_gun__model.mph');
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
parameterBindingsVerified = apply_wehnelt_contract_parameters(model, contract);
comp1 = model.component('comp1');

sel_vac  = 'sel_vac';

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named(sel_vac);

inl1 = cpt.create('inl1', 'Inlet', 2);
inl1.label('Cathode Coil Emission (Thermal, transverse)');
inl1.selection.named('selb_cath');
inl1.set('N', contract.evidence.requested_particle_count);
inl1.set('VelocitySpecification', 'Thermal');
inl1.set('T_src', 'userdef');
inl1.set('T', 'filament_T');

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.selection.named(sel_vac);
ef1.set('E_src', 'root.comp1.es.Ex');

std2 = model.study.create('std2');
tstep = std2.create('time1', 'Transient');
tstep.set('tlist', ...
    'range(particle_t_start,particle_t_step,particle_t_end)');
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
model.sol.create('sol2');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', 'sol1');
if strcmp(executionMode, 'build_only')
    if ~exist(paths.modelWorkspaceDir, 'dir'), mkdir(paths.modelWorkspaceDir); end
    model.save(savePath);
    result = struct('status', 'PASS', 'execution_mode', executionMode, ...
        'model_path', savePath, 'cpt_tree_built', true, ...
        'electrostatics_solved', false, 'particle_tracing_solved', false, ...
        'contract_loaded', true, ...
        'contract_project_id', contract.project_id, ...
        'selected_mode_id', contract.selected_mode_id, ...
        'parameter_bindings_verified', parameterBindingsVerified, ...
        'candidate_evidence_allowed', ...
        contract.evidence.candidate_evidence_allowed);
    fprintf('BUILD_ONLY=PASS model=%s\n', savePath);
    return;
end
model.sol('sol2').runAll;
fprintf('SUCCESS: Particle tracing (thermal, transverse coil) solved.\n');

resultsDir = paths.resultsDir;
if ~exist(resultsDir, 'dir'), mkdir(resultsDir); end
pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.set('solution', 'sol2');
try
    pg3 = model.result.create('pg_traj', 'PlotGroup3D');
    pg3.set('data', 'pdset1');
    tr1 = pg3.create('traj1', 'ParticleTrajectories');
    tr1.set('data', 'pdset1');
    imgT = model.result.export.create('imgT', 'Image');
    imgT.set('plotgroup', 'pg_traj');
    imgT.set('pngfilename', fullfile(resultsDir, 'electron_trajectories_transverse.png'));
    imgT.set('width', contract.numerical.reporting.trajectory_image_width_px);
    imgT.set('height', contract.numerical.reporting.trajectory_image_height_px);
    imgT.run;
    fprintf('SUCCESS: Trajectory image exported.\n');
catch ME
    fprintf('WARNING: Trajectory plot/export failed: %s\n', ME.message);
end

pd = mphparticle(model, 'dataset', 'pdset1');
me_ = 9.10938e-31; qe = 1.602176e-19;
n_released = size(pd.p, 2);
qx_end = pd.p(end,:,1); qy_end = pd.p(end,:,2); qz_end = pd.p(end,:,3);
vx = pd.v(end,:,1); vy = pd.v(end,:,2); vz = pd.v(end,:,3);
validPosition = isfinite(qx_end) & isfinite(qy_end) & isfinite(qz_end);
finiteVelocity = isfinite(vx) & isfinite(vy) & isfinite(vz);
speed = sqrt(vx.^2+vy.^2+vz.^2);
KE_eV = 0.5*me_*speed.^2/qe;
validEnergy = validPosition & finiteVelocity & isfinite(KE_eV);
energyMin = contract.physical.collection_metric.usable_energy_min_eV;
energyMax = contract.physical.collection_metric.usable_energy_max_eV;
n_arrived = sum(validEnergy & KE_eV > energyMin & KE_eV < energyMax);
n_selfabs = sum(~validPosition);

fprintf('\n=== Transverse-coil thermal emission results ===\n');
fprintf('Particles released: %d\n', n_released);
fprintf('Lost (NaN, self-absorbed on coil/Wehnelt before reaching a valid state): %d (%.2f%%)\n', ...
    n_selfabs, 100*n_selfabs/n_released);
fprintf(['Reached contract usable-energy band %.6g-%.6g eV ' ...
    '(passed anode): %d / %d (%.2f%%)\n'], ...
    energyMin, energyMax, n_arrived, n_released, ...
    100*n_arrived/n_released);
KEv = KE_eV(validEnergy);
if isempty(KEv)
    error(['Particle tracing produced no finite kinetic-energy samples at ' ...
        'finite final particle positions.']);
end
fprintf('KE[eV] among valid: min=%.4f max=%.4f mean=%.4f median=%.4f\n', ...
    min(KEv), max(KEv), mean(KEv), median(KEv));

if ~exist(paths.modelWorkspaceDir, 'dir'), mkdir(paths.modelWorkspaceDir); end
model.save(savePath);
fprintf('\nSUCCESS: model saved to %s\n', savePath);
result = struct('status', 'PASS', 'execution_mode', executionMode, ...
    'model_path', savePath, 'cpt_tree_built', true, ...
    'electrostatics_solved', true, 'particle_tracing_solved', true, ...
    'contract_loaded', true, ...
    'contract_project_id', contract.project_id, ...
    'selected_mode_id', contract.selected_mode_id, ...
    'parameter_bindings_verified', parameterBindingsVerified, ...
    'candidate_evidence_allowed', ...
    contract.evidence.candidate_evidence_allowed);
end
