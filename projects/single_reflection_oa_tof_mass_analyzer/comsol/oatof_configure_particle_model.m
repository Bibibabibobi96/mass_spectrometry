function state = oatof_configure_particle_model(model,comp1,p,paths,contract,mass_amu,label,use_fixed_particle_table,fixed_particle_table,n_particles,field_mode,fine_tstep_ns,drift_tstep_ns,solver_mode)
t_cptsetup_start = tic;
%% CPT
m_kg = mass_amu*1.66054e-27;
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: oa-TOF ring-stack %s', label));
cpt.selection.named('sel_vac');
cpt.feature('pp1').label(sprintf('Particle properties: %gamu +1 ion', mass_amu));
cpt.feature('pp1').set('mp', sprintf('%.6e[kg]', m_kg));
cpt.feature('pp1').set('Z', '1');

% !!! Explicit Wall/Freeze condition on the detector's own boundary, per
% explicit request: previously the ion stopped at the detector only
% because it physically left 'sel_vac' (the CPT domain) upon reaching
% the detector's solid material -- an IMPLICIT side-effect of the
% domain selection, not a deliberately configured particle-wall
% interaction. Making it explicit (a real Wall feature with Freeze)
% is the correct, robust way to model "detector absorbs the ion on
% impact" rather than relying on the CPT solver's default behavior when
% a trajectory exits the tracked domain.
wall_det = cpt.create('wall_det', 'Wall', 2);
wall_det.label('Detector wall (freeze on impact)');
wall_det.selection.named('selb_detector');
wall_det.set('WallCondition', 'Freeze');

% !!! No dedicated wall_backplate CPT feature: backplate is a real solid
% again (per explicit request, see the geometry comment above), so it's
% excluded from sel_vac (the CPT domain) just like repeller/detector/the
% rings -- an off-nominal ion that ever reached it would get the same
% implicit domain-boundary stop those electrodes already rely on, no
% explicit Wall/Freeze needed (that was only added while backplate was an
% idealized zero-thickness boundary an ion could otherwise pass through).

v_in = sqrt(2*5*1.602176e-19/m_kg);
fprintf('\n5eV entrance speed (x-direction): %.4e m/s\n', v_in);
if use_fixed_particle_table
    assert(isfile(fixed_particle_table), 'Fixed particle table not found: %s', fixed_particle_table);
    fixed_particles = readmatrix(fixed_particle_table, 'FileType', 'text', 'Delimiter', ',');
    assert(size(fixed_particles,2) >= 9 && size(fixed_particles,1) == n_particles, ...
        'Fixed particle table must have N=%d rows and at least 9 columns.', n_particles);
    assert(all(abs(fixed_particles(:,2) - mass_amu) < 1e-6) && all(fixed_particles(:,3) == 1), ...
        'Fixed particle table mass or charge does not match %g amu, +1.', mass_amu);
    energy_eV = fixed_particles(:,9);
    assert(all(isfinite(energy_eV) & energy_eV > 0), 'Fixed particle table contains invalid energies.');
    azimuth = deg2rad(fixed_particles(:,7)); elevation = deg2rad(fixed_particles(:,8));
    speed = sqrt(2*energy_eV*1.602176e-19/m_kg);
    local_velocity = [speed.*cos(elevation).*cos(azimuth), ...
        speed.*cos(elevation).*sin(azimuth), speed.*sin(elevation)];
    % The ION azimuth/elevation columns use the SIMION accelerator-local
    % frame.  This COMSOL model uses the shared global frame, whose axes
    % are related by (vx,vy,vz)_global=(vx,vz,-vy)_local.  Rotate once at
    % the solver-input boundary; positions are already global coordinates.
    velocity = [local_velocity(:,1), local_velocity(:,3), -local_velocity(:,2)];
    % Release-from-file coordinates are interpreted in the component
    % geometry length unit. geom1 uses mm, matching SIMION .ion columns
    % 4:6, so do not convert positions to SI metres. Velocity remains SI
    % m/s, as required by the particle interface.
    fixed_release_data = [fixed_particles(:,4:6), velocity];
    fixed_release_dir = getenv('OATOF_RUNTIME_DIR');
    assert(~isempty(fixed_release_dir), ...
        'OATOF_RUNTIME_DIR is required for fixed-particle run evidence.');
    if ~exist(fixed_release_dir, 'dir'), mkdir(fixed_release_dir); end
    fixed_release_path = fullfile(fixed_release_dir, sprintf('%s_release_from_data_file.txt', strrep(label,' ','_')));
    writematrix(fixed_release_data, fixed_release_path, 'Delimiter', 'tab');
    rel1 = cpt.create('rel1', 'ReleaseFromDataFile', -1);
    rel1.label(sprintf('Release from fixed SIMION particle table (N=%d)', n_particles));
    rel1.set('Filename', fixed_release_path);
    rel1.set('icolp', '0');
    rel1.set('VelocitySpecification', 'SpecifyVelocity');
    rel1.set('InitialVelocity', 'FromFile');
    rel1.set('icolv', '3');
    rel1.importData();
    fprintf('[%s] fixed particle table imported: %s (N=%d)\n', label, fixed_particle_table, n_particles);
else
    rel1 = cpt.create('rel1', 'Release', 3);
    rel1.label('Release: Gaussian energy (5eV mean, 0.4eV sigma) along x');
    rel1.selection.named('geom1_relvol_dom');
% !!! Gaussian (Normal) energy spread around the 5eV mean, per explicit
% request, to test dispersion with a large particle count. COMSOL's
% InitialKineticEnergy property turned out to be a MODE-SELECTOR enum
% ("Expression"/"ConstantSpeedSpherical"/etc.), NOT a free expression
% field -- attempting a Gaussian formula there errors with "Invalid
% parameter value". The v0 (velocity) property, by contrast, IS a free
% expression field (already proven with plain numeric values throughout
% this project) -- so the Gaussian is embedded directly there instead,
% converting a Normal-distributed energy (mean 5eV, stdev 0.4eV) to speed
% via KE=0.5*m*v^2. randnormal(seed) is COMSOL's built-in standard-normal
% (mean 0, stdev 1) sampler; SamplingFromDistribution='Random' makes each
% released particle draw an independent sample (not the same value
% repeated for all).
rel1.set('SamplingFromDistribution', 'Random');
p.set('E_mean_eV', sprintf('%.12g[V]', contract.validation_target.initial_energy_mean_ev), ...
    'Mean ion kinetic energy from baseline.json');
p.set('E_std_eV', sprintf('%.12g[V]', contract.validation_target.initial_energy_sigma_ev), ...
    'Ion kinetic-energy standard deviation from baseline.json');
% !!! randnormal() is NOT a recognized COMSOL function (confirmed via
% solve-time error "Unknown function or operator: randnormal") -- built a
% standard-normal sample manually via the Box-Muller transform using
% COMSOL's random() (uniform [0,1]) instead, which IS a known, documented
% CPT expression function for exactly this per-particle-randomization
% purpose.
rel1.set('v0', {sprintf('sqrt(2*abs(E_mean_eV+E_std_eV*sqrt(-2*log(random(1)))*cos(2*pi*random(2)))*1.602176e-19[C]/%.6e[kg])', m_kg) '0' '0'});
% !!! Default InitialPosition='MeshBased' with N=1 released particles
% from mesh vertices/elements directly (giving exactly 6, tied to
% relvol's own mesh density, not a deliberately chosen count).
% InitialPosition='Density' with N=<count> gives an explicit, requested
% total particle count instead, sampled within the release domain.
% Raised to 500 to test dispersion statistics with a large ensemble.
rel1.set('InitialPosition', 'Density');
rel1.set('N', num2str(n_particles));
end

% !!! Simplified per explicit request: no pulsing needed anymore -- ALL
% electrodes (reflectron rings/grids AND the accelerator's repeller/
% accelmid/gridA/gridB) are now combined into the SINGLE static 'es'
% solve, each at its own real, always-on voltage. The CPT force is just
% a direct reference to this one field, no unit-field scaling or sigmoid
% time-gating required.
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: combined static field (reflectron + accelerator, all electrodes always on)');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'userdef');
% field_mode is a composable idealization mask. The canonical syntax is
% ideal:<region>.<component>[+...], for example
% ideal:accel.ez+stage2.ex+stage2.ey. Regions and components may use
% 'all'; legacy ideal/ideal_accel/... names remain compatible. The 12
% GUI-visible flags below are the persisted model truth, so a saved MPH
% exposes every active replacement instead of hiding it in MATLAB state.
% !!! SIGN: the accelerator region has V DECREASING with z (repeller
% high -> grid2 low), so Ez=-dV/dz is POSITIVE there (pushing the
% positive ion forward, +z) -- confirmed against the real solved
% field's own measured sign (z=0.2mm: Ez=+159532 V/m). The reflectron
% region has V INCREASING with z (entgrid 0 -> backplate high) as the
% ion decelerates, so Ez=-dV/dz is NEGATIVE there.
Ez_accel_ideal = 'if(z<z_accel_grid1,(V_repeller-V_grid1)/accel_stage1_length,V_grid1/accel_stage2_length)';
Ez_drift_ideal = '0';
Ez_stage1_ideal = '-V_mid/L_stage1';
Ez_stage2_ideal = '-(V_mirror-V_mid)/(L_refl-L_stage1)';
idealization = oatof_parse_field_idealization(field_mode);
region_names = {'accel', 'drift', 'stage1', 'stage2'};
component_names = {'ex', 'ey', 'ez'};
for region_index = 1:4
    for component_index = 1:3
        flag_name = sprintf('ideal_%s_%s', region_names{region_index}, component_names{component_index});
        model.param.set(flag_name, sprintf('%d', idealization.mask(region_index, component_index)), ...
            sprintf('Field diagnostic mask: idealize %s %s', region_names{region_index}, upper(component_names{component_index})));
    end
end
accel_cond = '(z<z_accel_grid2)';
drift_cond = '(z>=z_accel_grid2&&z<L_flight)';
stage1_cond = '(z>=L_flight&&z<L_flight+L_stage1)';
stage2_cond = '(z>=L_flight+L_stage1&&z<L_flight+L_refl)';
Ex_ideal = sprintf(['if(ideal_accel_ex&&%s,0,if(ideal_drift_ex&&%s,0,' ...
    'if(ideal_stage1_ex&&%s,0,if(ideal_stage2_ex&&%s,0,es.Ex))))'], ...
    accel_cond, drift_cond, stage1_cond, stage2_cond);
Ey_ideal = sprintf(['if(ideal_accel_ey&&%s,0,if(ideal_drift_ey&&%s,0,' ...
    'if(ideal_stage1_ey&&%s,0,if(ideal_stage2_ey&&%s,0,es.Ey))))'], ...
    accel_cond, drift_cond, stage1_cond, stage2_cond);
Ez_ideal = sprintf(['if(ideal_accel_ez&&%s,%s,if(ideal_drift_ez&&%s,%s,' ...
    'if(ideal_stage1_ez&&%s,%s,if(ideal_stage2_ez&&%s,%s,es.Ez))))'], ...
    accel_cond, Ez_accel_ideal, drift_cond, Ez_drift_ideal, ...
    stage1_cond, Ez_stage1_ideal, stage2_cond, Ez_stage2_ideal);
ef1.set('E', {Ex_ideal, Ey_ideal, Ez_ideal});

% !!! Distance estimate updated to match the extended L_flight=3000mm
% (was hardcoded 0.36m = 0.3+0.03 margin for the old 300mm flight tube;
% now 3.0+0.03=3.03m, same ~9% margin factor as before).
% !!! Distance estimate updated for the new, much shorter L_flight=320mm
% (was 3.30m for the old 3000mm design; new: L_flight+L_refl/2+margin
% =320+45=365mm, *1.09 margin factor=~0.40m).
% !!! Distance estimate updated for L_flight extended to 600mm (doc
% §7.49, was 500mm): +100mm added to the previous 1.1m estimate.

% !!! Widened margin further (4.0->8.0): with the idealized-grid rebuild
% (zero field leakage, full ideal field strength), the ion's z_max
% stopped exactly at 300.00mm (the reflectron entrance) -- it hadn't even
% penetrated the reflectron yet when Tsim ran out, let alone completed a
% round trip. The much cleaner/stronger field changes the flight-time
% profile enough that the old margin (already generous for the leaky
% design) is no longer sufficient.
% !!! Two-phase adaptive Tsim (doc §6.14): a live in-solver StopCondition
% ("stop once all particles have reached the detector") was investigated
% extensively and found to be architecturally blocked -- every
% particle-aggregation mechanism in COMSOL's Particle Tracing Module
% (ParticleCounter.Nsel, BoundaryAccumulator's built-in globals, and the
% module's own built-in cpt.max/min/sum(...) per-particle couplings) only
% evaluates post-hoc via mphparticle, never live inside StopCondition's
% own expression evaluator ("Unknown function or operator"/"Undefined
% variable" every time, confirmed on this exact production model, not a
% naming issue). The working alternative: solve first with a SHORT,
% physics-based margin (1.5x estimated round-trip time, not the blanket
% 8x), then
% check completeness post-hoc with plain mphparticle; only fall back to
% the full 8x margin (re-solving from scratch) in the rare case the short
% one wasn't enough. Verified: R and detection times come out
% bit-identical whether the short margin succeeds directly or falls back
% to the full margin (deterministic particle release seed), so this has
% zero accuracy impact -- it only ever removes wasted tail computation
% for parameter combinations where the short margin already suffices.
std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: oa-TOF ring-stack %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver');
% Output windows follow the resolved numerical contract. They control stored
% data; the active algorithm's free/strict policy is configured below.
% Earlier BDF-only comments did not describe the saved GA/Strict solver.
% Controlled evidence and historical window changes are in project history.
timing = configure_oatof_segmented_output( ...
    model, mass_amu, fine_tstep_ns, drift_tstep_ns, contract);
expected_tof = timing.expected_tof_s;
runtime = contract.comsol_runtime;
Tsim_full = expected_tof*runtime.fallback_time_factor + ...
    runtime.fallback_end_padding_us*1e-6;
fine_start = timing.t_refl_start_s;
fine_end = timing.t_detector_end_s;
Tsim = timing.t_end_s;
fprintf(['[%s] parameter-linked output windows: fine %.3gns, drift %.3gns; ' ...
    'reflectron %.4f-%.4fus; detector fine end %.4fus; predicted TOF %.4fus.\n'], ...
    label, fine_tstep_ns, drift_tstep_ns, fine_start*1e6, ...
    timing.t_refl_end_s*1e6, fine_end*1e6, expected_tof*1e6);
fine_tstep = fine_tstep_ns*1e-9;
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
cpt.feature('pp1').set('StudyStep', 'std2/time1');
rel1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: oa-TOF CPT ring-stack %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
% Attach the configured solver so the Study's GUI Compute reuses sol2
% instead of creating a default zero-field CPT solver.
model.sol('sol2').attach('std2');
% Strict requires internal steps to include requested output times, while
% Free permits adaptive intermediate steps. Select the ACTIVE algorithm key,
% consume the author policy, and verify the native readback before Compute.
oatof_cpt_solver_policy(model.sol('sol2').feature('t1'),runtime,'apply');
% !!! FIX for the N>=20 crash ("NaN or Inf found when solving linear
% system using GMRES", t=6.38us, deterministic regardless of N):
% inspection showed the Time-Dependent solver's FullyCoupled nonlinear
% solver (fc1) uses the Iterative linear solver (i1, GMRES-based) by
% default. Switching to the Direct solver (dDef, e.g. MUMPS/PARDISO)
% should be far more numerically robust against whatever ill-conditioned
% situation a specific particle's trajectory triggers (GMRES can fail to
% converge on a hard step; a direct solve doesn't have that failure
% mode).
model.sol('sol2').feature('t1').feature('fc1').set('linsolver', 'dDef');
% !!! Configure the ACTUAL underlying direct-solver engine used by
% 'dDef' (mumps/pardiso on CPU, or cudss on GPU) per solver_mode --
% distinct from the 'linsolver'='dDef' setting above, which just tells
% fc1 to use the dDef FEATURE (as opposed to the iterative i1 feature
% that caused the N>=20 crash).
if strcmpi(solver_mode, 'gpu')
    model.sol('sol2').feature('t1').feature('dDef').set('linsolver', 'cudss');
else
    model.sol('sol2').feature('t1').feature('dDef').set('linsolver', 'pardiso');
end
t_cptsetup = toc(t_cptsetup_start);
fprintf('[TIMING] CPT setup (physics/release/study/solver config, before solve): %.2fs\n', t_cptsetup);
state = struct();
state.cpt = cpt; state.rel1 = rel1; state.tstep = tstep;
state.Ez_accel_ideal = Ez_accel_ideal; state.Ez_drift_ideal = Ez_drift_ideal;
state.Ez_stage1_ideal = Ez_stage1_ideal; state.Ez_stage2_ideal = Ez_stage2_ideal;
state.field_idealization = idealization;
state.Tsim = Tsim; state.Tsim_full = Tsim_full; state.timing = timing;
state.expected_tof = expected_tof; state.fine_tstep = fine_tstep;
state.fine_end = fine_end; state.t_cptsetup = t_cptsetup;
end
