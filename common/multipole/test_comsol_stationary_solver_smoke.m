% Verify the governed COMSOL stationary CG-AMG configuration on a tiny model.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL stationary-solver smoke report path is missing.');
progressPath = [reportPath '.progress.log'];
addpath(fullfile(fileparts(mfilename('fullpath'))));

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the stationary-solver smoke report.');
cleanup = onCleanup(@() fclose(fid));

try
    import com.comsol.model.*
    import com.comsol.model.util.*
    tag = 'MULTIPOLE_STATIONARY_SOLVER_SMOKE';
    if any(strcmp(cell(ModelUtil.tags()), tag)), ModelUtil.remove(tag); end
    model = ModelUtil.create(tag);
    component = model.component.create('comp1', true);
    geometry = component.geom.create('geom1', 2);
    geometry.lengthUnit('mm');
    geometry.feature.create('sq1', 'Square');
    geometry.feature('sq1').set('size', '1');
    geometry.run;

    electrostatics = component.physics.create('es', 'Electrostatics', 'geom1');
    electrostatics.selection.all;
    shapeProperty = electrostatics.prop('ShapeProperty');
    shapeProperty.set('order_electricpotential', 2);
    potential = electrostatics.feature.create('pot1', 'ElectricPotential', 1);
    potential.selection.set(1);
    potential.set('V0', '1[V]');
    ground = electrostatics.feature.create('gnd1', 'Ground', 1);
    ground.selection.set(4);

    material = component.material.create('mat1', 'Common');
    material.selection.all;
    material.propertyGroup('def').set('relpermittivity', '1');
    material.propertyGroup('def').set('electricconductivity', '0[S/m]');

    mesh = component.mesh.create('mesh1');
    mesh.autoMeshSize(1);
    mesh.run;
    study = model.study.create('std1');
    study.create('stat', 'Stationary');
    solution = model.sol.create('sol1');
    solution.study('std1');
    solution.createAutoSequence('std1');
    actual = configure_comsol_stationary_solver(solution, 'cg_amg', ...
        struct('relative_tolerance', 0.001, 'maximum_iterations', 500, ...
        'error_check_mode', 'on'));
    solution.attach('std1');

    ModelUtil.showProgress(progressPath);
    progressCleanup = onCleanup(@() ModelUtil.showProgress(false));
    solution.runAll;
    clear progressCleanup
    progressText = fileread(progressPath);
    assert(~isempty(regexp(progressText, '\<LinIt\>', 'once')) && ...
        ~isempty(regexp(progressText, '\<LinRes\>', 'once')), ...
        'COMSOL progress log omits LinIt/LinRes headers.');
    assert(str2double(char( ...
        shapeProperty.getString('order_electricpotential'))) == 2, ...
        'COMSOL did not retain quadratic electric-potential elements.');

    fprintf(fid, 'TASK=MULTIPOLE_STATIONARY_SOLVER_SMOKE\n');
    fprintf(fid, 'STATIONARY_LINEAR_SOLVER_BACKEND=%s\n', upper(actual.backend));
    fprintf(fid, 'STATIONARY_CONTROL=%s\n', upper(actual.control));
    fprintf(fid, 'STATIONARY_RELATIVE_TOLERANCE=%.17g\n', actual.relative_tolerance);
    fprintf(fid, 'STATIONARY_FULLY_COUPLED_LINEAR_SOLVER=%s\n', ...
        upper(actual.fully_coupled_linsolver));
    fprintf(fid, 'STATIONARY_MAX_LINEAR_ITERATIONS=%d\n', ...
        actual.maximum_linear_iterations);
    fprintf(fid, 'STATIONARY_LINEAR_ERROR_CHECK=%s\n', ...
        upper(actual.linear_error_check));
    fprintf(fid, 'STATIONARY_CONVERGENCE_LOG=%s\n', upper(actual.convergence_log));
    fprintf(fid, 'ELECTRIC_POTENTIAL_ELEMENT_ORDER=QUADRATIC\n');
    fprintf(fid, 'PROGRESS_HAS_LINIT_LINRES=1\n');
    fprintf(fid, 'STATUS=PASS\n');
    ModelUtil.remove(tag);
catch ME
    fprintf(fid, 'ERROR_ID=%s\n', ME.identifier);
    fprintf(fid, 'ERROR_MESSAGE=%s\n', regexprep(ME.message, '[\r\n]+', ' '));
    fprintf(fid, 'STATUS=FAIL\n');
    rethrow(ME);
end
