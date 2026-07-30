function actual = configure_comsol_stationary_solver(solution, requestedBackend, iterativeSettings)
%CONFIGURE_COMSOL_STATIONARY_SOLVER Configure one governed stationary backend.

requestedBackend = lower(char(requestedBackend));
assert(any(strcmp(requestedBackend, {'mumps', 'pardiso', 'cg_amg'})), ...
    'Unsupported stationary linear-solver backend: %s', requestedBackend);
assert(isstruct(iterativeSettings), ...
    'Stationary iterative-solver settings must be a structure.');

stationary = solution.feature('s1');
childTags = cell(stationary.feature.tags());
assert(any(strcmp(childTags, 'dDef')), ...
    'Expected stationary solver features are missing. Found: %s', ...
    strjoin(childTags, ','));
hasFullyCoupled = any(strcmp(childTags, 'fc1'));
hasSegregated = any(strcmp(childTags, 'se1'));
assert(xor(hasFullyCoupled, hasSegregated), ...
    'Stationary solver must have exactly one coupling strategy. Found: %s', ...
    strjoin(childTags, ','));
if hasSegregated
    stationary.feature.create('fc1', 'FullyCoupled');
    stationary.feature.remove('se1');
    childTags = cell(stationary.feature.tags());
end
assert(any(strcmp(childTags, 'fc1')) && ...
    ~any(strcmp(childTags, 'se1')), ...
    'Stationary solver was not normalized to the canonical fully coupled tree.');

if strcmp(requestedBackend, 'cg_amg')
    assert(isequal(sort(fieldnames(iterativeSettings)), ...
        sort({'relative_tolerance';'maximum_iterations';'error_check_mode'})), ...
        'CG-AMG iterative-solver setting fields differ.');
    relativeTolerance = double(iterativeSettings.relative_tolerance);
    maximumIterations = double(iterativeSettings.maximum_iterations);
    errorCheckMode = lower(char(iterativeSettings.error_check_mode));
    assert(isfinite(relativeTolerance) && relativeTolerance > 0 && ...
        relativeTolerance < 1, ...
        'CG-AMG relative tolerance must be finite and between zero and one.');
    assert(isfinite(maximumIterations) && maximumIterations >= 1 && ...
        maximumIterations == fix(maximumIterations), ...
        'CG-AMG maximum iterations must be a positive integer.');
    assert(strcmp(errorCheckMode, 'on'), ...
        'CG-AMG error-check mode must be on.');
    stationary.set('control', 'user');
    stationary.set('stol', relativeTolerance);
    if any(strcmp(childTags, 'aDef'))
        advanced = stationary.feature('aDef');
    else
        stationary.feature.create('a1', 'Advanced');
        advanced = stationary.feature('a1');
    end
    advanced.set('convinfo', 'detailed');
    if ~any(strcmp(childTags, 'i1'))
        stationary.feature.create('i1', 'Iterative');
    end
    iterative = stationary.feature('i1');
    iterative.set('linsolver', 'cg');
    iterative.set('maxlinit', maximumIterations);
    iterative.set('errorchk', errorCheckMode);
    iterativeTags = cell(iterative.feature.tags());
    if ~any(strcmp(iterativeTags, 'mg1'))
        iterative.feature.create('mg1', 'Multigrid');
    end
    iterative.feature('mg1').set('prefun', 'amg');
    stationary.feature('fc1').set('linsolver', 'i1');

    actualLinearSolver = lower(char(iterative.getString('linsolver')));
    actualPreconditioner = lower(char(iterative.feature('mg1').getString('prefun')));
    actualFullyCoupledSolver = char(stationary.feature('fc1').getString('linsolver'));
    actualMaximumIterations = double(iterative.getInt('maxlinit'));
    actualErrorCheck = lower(char(iterative.getString('errorchk')));
    assert(strcmp(actualFullyCoupledSolver, 'i1') && ...
        strcmp(actualLinearSolver, 'cg') && strcmp(actualPreconditioner, 'amg') && ...
        actualMaximumIterations == maximumIterations && ...
        strcmp(actualErrorCheck, errorCheckMode), ...
        'CG-AMG stationary solver configuration was not retained.');
    actualBackend = 'cg_amg';
    actualControl = lower(char(stationary.getString('control')));
    actualRelativeTolerance = double(stationary.getDouble('stol'));
    actualConvergenceLog = lower(char(advanced.getString('convinfo')));
    assert(strcmp(actualControl, 'user') && ...
        actualRelativeTolerance == relativeTolerance && ...
        strcmp(actualConvergenceLog, 'detailed'), ...
        'Stationary solver convergence control was not retained.');
else
    assert(isempty(fieldnames(iterativeSettings)), ...
        'Direct stationary solvers forbid iterative-solver settings.');
    stationary.feature('dDef').set('linsolver', requestedBackend);
    stationary.feature('fc1').set('linsolver', 'dDef');
    actualBackend = lower(char(stationary.feature('dDef').getString('linsolver')));
    actualFullyCoupledSolver = char(stationary.feature('fc1').getString('linsolver'));
    actualMaximumIterations = NaN;
    actualErrorCheck = 'not_applicable';
    actualControl = 'not_applicable';
    actualRelativeTolerance = NaN;
    actualConvergenceLog = 'not_applicable';
    assert(strcmp(actualFullyCoupledSolver, 'dDef') && ...
        strcmp(actualBackend, requestedBackend), ...
        'Stationary direct-solver backend differs from the requested backend.');
end

actual = struct('backend',actualBackend, ...
    'fully_coupled_linsolver',actualFullyCoupledSolver, ...
    'control',actualControl, ...
    'relative_tolerance',actualRelativeTolerance, ...
    'maximum_linear_iterations',actualMaximumIterations, ...
    'linear_error_check',actualErrorCheck, ...
    'convergence_log',actualConvergenceLog);
end
