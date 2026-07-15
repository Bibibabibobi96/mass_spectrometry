function test_magnetic_coil()
% Reference/validation script: solves the magnetic field of a real 3D
% current-carrying coil (our validated Helix primitive) using COMSOL's
% Magnetic Fields interface (internal tag 'InductionCurrents') + a
% 'Numeric' Coil domain feature, and checks the result against a rough
% infinite-solenoid Biot-Savart estimate (mu0*N*I/L). See
% COMSOL_API.md §8 for the full narrative of what took several
% iterations to figure out (correct physics tag, coil terminal boundary,
% required material conductivity, and the CoilCurrentCalculation study
% step that must precede the Stationary step).

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelMF'))
    ModelUtil.remove('ModelMF');
end
model = ModelUtil.create('ModelMF');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.lengthUnit('mm');

% Coil conductor (5 turns, matches the filament coil used elsewhere)
geom1.feature.create('hel1', 'Helix');
geom1.feature('hel1').set('rmaj', '0.3[mm]');
geom1.feature('hel1').set('rmin', '0.05[mm]');
geom1.feature('hel1').set('axialpitch', '0.2[mm]');
geom1.feature('hel1').set('turns', '5');
geom1.feature('hel1').set('pos', {'0' '0' '0'});

% Surrounding "air" domain
geom1.feature.create('cyl1', 'Cylinder');
geom1.feature('cyl1').set('r', '2[mm]');
geom1.feature('cyl1').set('h', '3[mm]');
geom1.feature('cyl1').set('pos', {'0' '0' '-1[mm]'});

geom1.feature('hel1').set('selresult', 'on');
geom1.run;

% cyl1 spatially contains hel1 -> its own selresult would resolve to ALL
% domains (same trap as the electron-gun vacuum-domain case, §7.2) --
% use Complement instead.
comp1.selection.create('sel_air', 'Complement');
comp1.selection('sel_air').set('input', {'geom1_hel1_dom'});

% Materials: Coil domain needs an electrical conductivity (sigma) --
% without it, the solve fails with "Undefined material property 'sigma'
% required by Domain Coil 1."
mat_w = model.material.create('mat_w', 'Common');
mat_w.label('Tungsten (coil)');
mat_w.selection.named('geom1_hel1_dom');
mat_w.propertyGroup('def').set('electricconductivity', {'1.8e7[S/m]'});
mat_w.propertyGroup('def').set('relpermeability', {'1'});
mat_air = model.material.create('mat_air', 'Common');
mat_air.label('Air');
mat_air.selection.named('sel_air');
mat_air.propertyGroup('def').set('relpermeability', {'1'});
mat_air.propertyGroup('def').set('electricconductivity', {'0'});

% Magnetic Fields physics -- NOTE: the internal tag is 'InductionCurrents',
% NOT 'MagneticFields' (discovered via trial: 'MagneticFields' throws
% "Unknown physics interface"; found the real tag by probing candidates).
mf = comp1.physics.create('mf', 'InductionCurrents', 'geom1');

% Domain Coil feature directly on the real 3D helix domain.
coil1 = mf.create('coil1', 'Coil', 3);
coil1.selection.named('geom1_hel1_dom');
% CoilType stays default 'Numeric' (valid values: "Numeric"/"Circular"/
% "Linear"/"UserDefined" -- Numeric is correct for an arbitrary real 3D
% conductor shape like ours, not an idealized circular/linear coil).
coil1.set('CoilExcitation', 'Current');   % valid: Voltage/Current/CircuitVoltage/CircuitCurrent
coil1.set('ICoil', '1[A]');
coil1.set('N', '1');   % =1 because the real winding count is already
                       % modeled explicitly in the geometry (5 turns),
                       % not a multiplier on top of it (default N=10 is
                       % wrong for a geometrically-explicit coil).

% The 'Numeric' Coil feature auto-creates subfeatures cg1
% (UserDefinedCoilGeometry, unused here), ccc1 (CoilCurrentCalculation,
% labeled "Geometry Analysis 1") containing ct1 (CoilTerminal, "Input
% 1"), and cre1 (CoilReferenceEdge). ct1 needs an explicit boundary
% selection -- one of the coil's two flat end-cap faces (found by
% listing hel1's adjacent boundaries via an Adjacent selection, then
% trying candidates; boundary index is NOT stable across geometry
% variants, always re-derive per model).
hel1_bnds = comp1.selection.create('selb_hel1_probe', 'Adjacent');
hel1_bnds.set('input', {'geom1_hel1_dom'});
ents = hel1_bnds.entities();
coil1.feature('ccc1').feature('ct1').selection.set(ents(1));  % first adjacent boundary worked in testing

mesh1 = comp1.mesh.create('mesh1');
mesh1.feature('size').set('hauto', 4);
mesh1.feature.create('ftet1', 'FreeTet');   % see §7.6: never rely on implicit domain-fill
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
if mi.isempty || mi.hasproblems || ~mi.iscomplete
    error('Mesh build failed.');
end

% !!! KEY FINDING: a plain 'Stationary' study step alone fails with
% "Numeric coil Domain Coil 1 (coil1) not solved for. Solve it in a Coil
% Geometry Analysis step." -- you MUST add a 'CoilCurrentCalculation'
% study step (matches the coil subfeature's own type name) BEFORE the
% 'Stationary' step, in the SAME study. (Tried and ruled out:
% 'CoilGeometryAnalysis' as a study-step type -> "Operation cannot be
% created in this context"; 'StationarySourceSweep' -> solves but is for
% MULTI-coil mutual-inductance sweeps, fails with "No sources found" on
% a single coil.)
std1 = model.study.create('std1');
std1.create('ccc_step1', 'CoilCurrentCalculation');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: coil magnetic field solved.\n');

Bz = mphinterp(model, 'mf.Bz', 'coord', [0;0;0.5], 'dataset', 'dset1', 'matherr', 'off');
mu0 = 4*pi*1e-7;
B_est = mu0*5*1/1e-3;  % infinite-solenoid mu0*N*I/L, order-of-magnitude check
fprintf('Bz at coil center = %.4e T  (infinite-solenoid estimate = %.4e T, ratio = %.2f)\n', ...
    Bz, B_est, Bz/B_est);
end
