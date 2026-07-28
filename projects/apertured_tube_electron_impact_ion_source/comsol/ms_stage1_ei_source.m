function result = ms_stage1_ei_source(resolvedContractPath, label)
% Mass spectrometer Stage 1: Electron Impact (EI) ionization source.
% All physical and numerical values come from a resolver-validated contract.
% The build_only_smoke mode builds geometry, mesh, physics, studies and
% solver trees, saves an isolated run model, and returns before solving.
%
% Geometry follows the validated long, thin, apertured-electrode topology.
% Earlier short, solid-disk prototypes caused severe CPT memory growth; the
% physical dimensions themselves now live only in the baseline contract.
%
% A cathode accelerates electrons along the tube via the contract-defined
% DC field toward a collector anode. The
% tube is filled with background neutral gas (Nd) and a native CPT
% `Collisions` + `Ionization` Attribute counts ionizing collisions along
% each electron's trajectory (same family as the validated Elastic/
% ResonantChargeExchange attributes; see COMSOL_API.md under wall,
% termination, and collisions).
%
% IMPORTANT SIMPLIFICATION: COMSOL's CPT physics interface only allows
% ONE ParticleProperties feature (pp1) per interface, and Ionization's
% ReleasedIonProperties/ReleasedElectronProperties can only reference
% that same pp1 -- there is no way, within a single cpt interface, to
% have electrons spawn a literal separate heavy tracked ion species. So
% the contract keeps ReleaseIonizedParticle false: the Ionization
% attribute is used purely for its real, Monte-Carlo, validated
% ionizing-COLLISION-COUNTING physics (Nd*sigma*v collision frequency),
% giving a genuine simulated ionization YIELD -- while the heavy ion's
% birth position (used in Stage 2+) is approximated from the geometric
% extent of the electron beam's path through the ionization volume.
%
% Cross section, gas density, voltages, release state, and numerical mode
% are resolved outside MATLAB and are never defaulted in this builder.

componentRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(componentRoot);
paths = ei_source_paths();
if nargin < 1 || isempty(resolvedContractPath)
    error('A resolved EI-source contract path is required; no defaults exist.');
end
contract = load_ei_source_contract(char(resolvedContractPath));
physical = contract.physical;
geometry = physical.geometry_mm;
electrodes = physical.electrodes_V;
gas = physical.gas;
ionization = physical.ionization;
electronSource = physical.electron_source;
numerical = contract.numerical;
executionMode = numerical.execution_mode;
if nargin < 2 || isempty(label)
    label = contract.selected_mode_id;
end
import com.comsol.model.*
import com.comsol.model.util.*
assert(any(strcmp(executionMode, {'full', 'build_only'})), ...
    'executionMode must be full or build_only.');

if any(strcmp(cell(ModelUtil.tags()), 'ModelEISource'))
    ModelUtil.remove('ModelEISource');
end
model = ModelUtil.create('ModelEISource');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('EI ionization source geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('R_tube', with_unit(geometry.tube_bore_radius, 'mm'), ...
    'Ionization tube bore radius');
p.set('L_cell', with_unit(geometry.cathode_anode_path_length, 'mm'), ...
    'Cathode-anode path length');
p.set('t_disk', with_unit(geometry.electrode_disk_thickness, 'mm'), ...
    'Electrode disk thickness');
p.set('r_hole', with_unit(geometry.electrode_aperture_radius, 'mm'), ...
    'Electrode aperture radius');
p.set('hole_margin', ...
    with_unit(geometry.boolean_hole_overshoot_each_side, 'mm'), ...
    'Boolean subtraction overshoot on each disk side');
p.set('release_r', with_unit(geometry.release_volume_radius, 'mm'), ...
    'Release volume radius');
p.set('release_l', with_unit(geometry.release_volume_length, 'mm'), ...
    'Release volume axial length');
p.set('release_z0', with_unit(geometry.release_volume_start_z, 'mm'), ...
    'Release volume start position');
p.set('collector_backoff', ...
    with_unit(geometry.collector_capture_backoff, 'mm'), ...
    'Collector capture threshold backoff');
p.set('V_cathode', with_unit(electrodes.cathode, 'V'), ...
    'Cathode potential');
p.set('V_anode', with_unit(electrodes.anode, 'V'), ...
    'Anode potential');
p.set('epsr_gas', scalar_text(gas.relative_permittivity), ...
    'Ionization-gas relative permittivity');
p.set('Nd', with_unit(gas.neutral_number_density_per_m3, '1/m^3'), ...
    'Neutral number density');
p.set('sigma_ion', with_unit(ionization.cross_section_m2, 'm^2'), ...
    'Electron-impact ionization cross section');
p.set('dE_ion', with_unit(ionization.primary_energy_loss_eV, 'eV'), ...
    'Primary-electron energy loss per ionization');
p.set('v_release_x', with_unit(electronSource.release_velocity_m_per_s(1), ...
    'm/s'), 'Release velocity x component');
p.set('v_release_y', with_unit(electronSource.release_velocity_m_per_s(2), ...
    'm/s'), 'Release velocity y component');
p.set('v_release_z', with_unit(electronSource.release_velocity_m_per_s(3), ...
    'm/s'), 'Release velocity z component');
p.set('Tsim', with_unit(numerical.time_ns.end, 'ns'), ...
    'Particle-tracing end time');
p.set('dtstep', with_unit(numerical.time_ns.step, 'ns'), ...
    'Particle-tracing output step');

geom1.feature.create('cathO', 'Cylinder');
geom1.feature('cathO').label('Cathode outer solid');
geom1.feature('cathO').set('r', 'R_tube');
geom1.feature('cathO').set('h', 't_disk');
geom1.feature('cathO').set('pos', {'0' '0' '-t_disk'});
geom1.feature.create('cathH', 'Cylinder');
geom1.feature('cathH').label('Cathode aperture hole');
geom1.feature('cathH').set('r', 'r_hole');
geom1.feature('cathH').set('h', 't_disk+2*hole_margin');
geom1.feature('cathH').set('pos', {'0' '0' '-t_disk-hole_margin'});
geom1.feature.create('cathode', 'Difference');
geom1.feature('cathode').label('Cathode (electron emitter, V=V_cathode)');
geom1.feature('cathode').selection('input').set({'cathO'});
geom1.feature('cathode').selection('input2').set({'cathH'});

geom1.feature.create('anodO', 'Cylinder');
geom1.feature('anodO').label('Anode outer solid');
geom1.feature('anodO').set('r', 'R_tube');
geom1.feature('anodO').set('h', 't_disk');
geom1.feature('anodO').set('pos', {'0' '0' 'L_cell'});
geom1.feature.create('anodH', 'Cylinder');
geom1.feature('anodH').label('Anode aperture hole');
geom1.feature('anodH').set('r', 'r_hole');
geom1.feature('anodH').set('h', 't_disk+2*hole_margin');
geom1.feature('anodH').set('pos', {'0' '0' 'L_cell-hole_margin'});
geom1.feature.create('anode', 'Difference');
geom1.feature('anode').label('Anode / collector (V=V_anode)');
geom1.feature('anode').selection('input').set({'anodO'});
geom1.feature('anode').selection('input2').set({'anodH'});

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Ionization tube body (background gas)');
geom1.feature('cylv').set('r', 'R_tube');
geom1.feature('cylv').set('h', 'L_cell+2*t_disk');
geom1.feature('cylv').set('pos', {'0' '0' '-t_disk'});

geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (near-cathode emission zone)');
geom1.feature('relvol').set('r', 'release_r');
geom1.feature('relvol').set('h', 'release_l');
geom1.feature('relvol').set('pos', {'0' '0' 'release_z0'});
geom1.feature('relvol').set('selresult', 'on');

for t = {'cathode','anode'}
    geom1.feature(t{1}).set('selresult', 'on');
end
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Ionization tube vacuum/gas (all domains except electrodes)');
comp1.selection('sel_vac').set('input', {'geom1_cathode_dom','geom1_anode_dom'});
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2, error('Expected 2 domains (rest-of-tube + relvol), got %d', vac_n); end

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Ionization gas (contract relative permittivity)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'epsr_gas'});
for t = {'cathode','anode'}
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.label(sprintf('%s material', t{1}));
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'epsr_gas'});
end

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: cathode-anode accelerating field');
es.selection.named('sel_vac');
Vmap = struct('cathode','V_cathode','anode','V_anode');
for t = {'cathode','anode'}
    tagb = sprintf('selb_%s', t{1});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).label(sprintf('%s boundary', t{1}));
    comp1.selection(tagb).set('input', {sprintf('geom1_%s_dom', t{1})});
    potk = es.create(sprintf('pot_%s', t{1}), 'ElectricPotential', 2);
    potk.label(sprintf('%s potential', t{1}));
    potk.selection.named(tagb);
    potk.set('V0', Vmap.(t{1}));
end

mesh1 = comp1.mesh.create('mesh1');
mesh1.label(sprintf('Mesh (hauto=%d)', numerical.mesh.automatic_level));
mesh1.feature('size').set('hauto', numerical.mesh.automatic_level);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
fprintf('mesh: isempty=%d iscomplete=%d\n', mi.isempty, mi.iscomplete);
if mi.isempty || ~mi.iscomplete, error('mesh failed'); end

std1 = model.study.create('std1');
std1.label('Stationary: accelerating field');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: ES');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
if strcmp(executionMode, 'full')
    model.sol('sol1').runAll;
    fprintf('SUCCESS: electrostatics solved.\n');
end

%% CPT: electrons cross the ionization tube, undergo Ionization collisions
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: EI source %s', label));
cpt.selection.named('sel_vac');
% pp1 defaults to electron (mp=me_const, Z=-1) -- exactly what we want here.

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: contract-defined fixed velocity from cathode');
rel1.selection.named('geom1_relvol_dom');
% !!! CRITICAL: do NOT use VelocitySpecification='Maxwellian' here.
% Unlike Inlet's 'Thermal' mode, Release's 'Maxwellian' mode samples the
% Maxwell-Boltzmann speed distribution DETERMINISTICALLY across Nvel=200
% discrete velocity bins PER MESH-BASED RELEASE POINT -- this multiplies
% the tracked particle count by ~200x (confirmed by isolation testing:
% every other candidate cause -- geometry topology, tstepsbdf, the
% ES-solution-reuse trick, electron vs. heavy-ion mass, even
% ReleaseSecondaryElectron -- was ruled out one at a time; only switching
% away from Maxwellian fixed the repeated multi-GB server memory
% blowups/hangs during the CPT time-dependent solve). A fixed distribution
% is an explicit baseline simplification here.
rel1.set('v0', {'v_release_x' 'v_release_y' 'v_release_z'});


ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: accelerating field');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'root.comp1.es.Ex');

coll1 = cpt.create('coll1', 'Collisions', 3);
coll1.label(sprintf('Collisions: background gas Nd=%.2g /m^3', ...
    gas.neutral_number_density_per_m3));
coll1.selection.named('sel_vac');
coll1.set('Nd', 'Nd');
coll1.set('CollisionDetection', ionization.collision_detection);
coll1.set('CountAllCollisions', ionization.count_all_collisions);

ion1 = coll1.create('ion1', 'Ionization');
ion1.label('Electron-impact ionization (constant cross section)');
ion1.set('xsec', 'sigma_ion');
ion1.set('dE', 'dE_ion');
ion1.set('CountCollisions', ionization.count_ionization_collisions);
ion1.set('ReleaseSecondaryElectron', ...
    ionization.release_secondary_electron);
ion1.set('ReleaseIonizedParticle', ionization.release_ionized_particle);
ion1.set('ReleasePrimaryElectron', ionization.release_primary_electron);
% !!! CRITICAL FIX: ReleaseSecondaryElectron defaults to TRUE -- every
% ionizing collision would otherwise spawn a NEW tracked electron (a
% genuine electron-avalanche mechanism, physically appropriate for
% plasma-discharge modeling but NOT wanted here). With CountAllCollisions
% active and a non-negligible ionization probability, this caused
% exponential growth in the number of tracked particles over the
% simulated time, which is what was actually behind the repeated
% "Out of memory xmesh processing" / multi-hour hangs / 10s-of-GB server
% memory blowups seen while debugging this script (NOT the geometry
% topology, NOT tstepsbdf, NOT the ES-solution-reuse trick -- all of
% which were re-tested and ruled out first). ReleaseIonizedParticle stays
% at its default (false) for the separate, structural reason explained in
% the file header (only one ParticleProperties/pp1 per cpt interface).
% The contract keeps ReleasePrimaryElectron true: the original
% electron should keep being tracked (losing dE) after an ionizing event,
% it just shouldn't spawn a NEW one.

std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: EI source %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label(sprintf('Transient solver (0-%g ns)', numerical.time_ns.end));
tstep.set('tlist', 'range(0,dtstep,Tsim)');
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
cpt.feature('pp1').set('StudyStep', 'std2/time1');
rel1.set('StudyStep', 'std2/time1');
coll1.set('StudyStep', 'std2/time1');
ion1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: EI source CPT %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
if numerical.solver.strict_time_steps
    model.sol('sol2').feature('t1').set('tstepsbdf', 'strict');
end
parameterBindingsVerified = verify_parameter_bindings(model, contract);
if strcmp(executionMode, 'build_only')
    modelsDir = paths.modelsDir;
    if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
    modelPath = fullfile(modelsDir, sprintf('MS_Stage1_EISource_%s__build_only.mph', ...
        strrep(label, ' ', '_')));
    model.save(modelPath);
    result = struct('status', 'PASS', 'execution_mode', executionMode, ...
        'model_path', modelPath, 'geometry_built', true, 'mesh_built', true, ...
        'electrostatics_solved', false, 'particle_tracing_solved', false, ...
        'contract_loaded', true, 'contract_path', resolvedContractPath, ...
        'contract_project_id', contract.project_id, ...
        'contract_model_id', contract.model_id, ...
        'selected_mode_id', contract.selected_mode_id, ...
        'parameter_bindings_verified', parameterBindingsVerified, ...
        'candidate_evidence_allowed', ...
        contract.evidence.candidate_evidence_allowed);
    fprintf('[%s] BUILD_ONLY=PASS model=%s\n', label, modelPath);
    return;
end
model.sol('sol2').runAll;
fprintf('[%s] SUCCESS: EI source CPT solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: EI source %s', label));
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'cpt.coll1.ion1.Nc'});
nP = size(pd.p,2);
fprintf('[%s] electrons released: %d\n', label, nP);

x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
r = sqrt(x.^2+y.^2);
Nc_end = pd.d1(end,:);

zEnd = z(end,:);
collectorThresholdMm = geometry.cathode_anode_path_length - ...
    geometry.collector_capture_backoff;
collected = zEnd > collectorThresholdMm;
meanNc = mean(Nc_end);
fracIonizing = mean(Nc_end > 0);
fprintf('[%s] electrons collected at anode: %d / %d (%.1f%%)\n', label, sum(collected), nP, 100*sum(collected)/nP);
fprintf('[%s] mean ionizing collisions per electron: %.5f\n', label, meanNc);
fprintf('[%s] fraction of electrons with >=1 ionizing collision (ion yield per electron): %.5f%%\n', label, 100*fracIonizing);

pathLengthM = geometry.cathode_anode_path_length * 1e-3;
theory_prob = gas.neutral_number_density_per_m3 * ...
    ionization.cross_section_m2 * pathLengthM;
fprintf('[%s] theory (Nd*sigma*L, low-probability approx): %.5f%% -- compare to simulated %.5f%%\n', ...
    label, 100*theory_prob, 100*fracIonizing);

result = struct('label', label, ...
    'Nd', gas.neutral_number_density_per_m3, ...
    'nP', nP, 'mean_ionizing_collisions', meanNc, ...
    'ion_yield_frac', fracIonizing, 'theory_yield_frac', theory_prob, ...
    'R_tube', geometry.tube_bore_radius * 1e-3, ...
    'L_cell', pathLengthM, ...
    'V_accel', electrodes.anode - electrodes.cathode, ...
    'contract_path', resolvedContractPath, ...
    'selected_mode_id', contract.selected_mode_id, ...
    'parameter_bindings_verified', parameterBindingsVerified);

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
subplot(1,2,1);
hold on;
for i = 1:min(numerical.reporting.maximum_trajectory_curves,nP)
    plot(z(:,i), r(:,i), '-'); % z,r already in mm (geom1.lengthUnit('mm'))
end
xlabel('z [mm]'); ylabel('r [mm]'); grid on;
title('electron trajectories through ionization tube');
subplot(1,2,2);
histogram(Nc_end, 'BinMethod','integers');
xlabel('ionizing collisions per electron'); ylabel('count'); grid on;
title(sprintf('ionization event histogram (mean=%.4f)', meanNc));
sgtitle({sprintf('EI Source Stage 1: %s', label), ...
    sprintf('%geV electrons, Nd=%.2g/m^3, ion yield=%.4f%% (theory %.4f%%)', ...
    electrodes.anode-electrodes.cathode, ...
    gas.neutral_number_density_per_m3, 100*fracIonizing, ...
    100*theory_prob)}, 'Interpreter','none');
print(fh, fullfile(resultsDir, sprintf('ms_stage1_ei_%s.png', ...
    strrep(label,' ','_'))), '-dpng', ...
    sprintf('-r%d', numerical.reporting.figure_dpi));
fprintf('[%s] SUCCESS: trajectory/histogram plot saved.\n', label);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('EI source: %s electron trajectories', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('EI Source: %s, ion yield=%.4f%%', label, 100*fracIonizing));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('Electron trajectories');
pg1.run;

modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('MS_Stage1_EISource_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end

function text = with_unit(value, unit)
%WITH_UNIT Convert one validated scalar to an explicit COMSOL expression.
    text = sprintf('%.17g[%s]', value, unit);
end

function text = scalar_text(value)
%SCALAR_TEXT Convert one validated dimensionless scalar to text.
    text = sprintf('%.17g', value);
end

function verified = verify_parameter_bindings(model, contract)
%VERIFY_PARAMETER_BINDINGS Confirm GUI-visible parameters consume the contract.
    geometry = contract.physical.geometry_mm;
    gas = contract.physical.gas;
    ionization = contract.physical.ionization;
    checks = {
        'R_tube', with_unit(geometry.tube_bore_radius, 'mm');
        'L_cell', with_unit(geometry.cathode_anode_path_length, 'mm');
        'r_hole', with_unit(geometry.electrode_aperture_radius, 'mm');
        'Nd', with_unit(gas.neutral_number_density_per_m3, '1/m^3');
        'sigma_ion', with_unit(ionization.cross_section_m2, 'm^2');
        'dE_ion', with_unit(ionization.primary_energy_loss_eV, 'eV')
    };
    for index = 1:size(checks, 1)
        actual = char(model.param.get(checks{index, 1}));
        assert(strcmp(actual, checks{index, 2}), ...
            'COMSOL parameter %s is not bound to the resolved contract.', ...
            checks{index, 1});
    end
    verified = true;
end
