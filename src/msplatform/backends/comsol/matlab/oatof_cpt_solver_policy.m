function snapshot = oatof_cpt_solver_policy(solverTime,runtime,action)
%OATOF_CPT_SOLVER_POLICY Apply or verify the active CPT time-step policy.
% The resolved numerical contract owns the requested policy. COMSOL 6.4
% Time API, table 6-74, selects the property by active ODE/integrator type:
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html
% This boundary preserves the algorithm, tolerances and all inactive keys.
arguments
    solverTime
    runtime (1,1) struct
    action (1,1) string {mustBeMember(action,["apply","verify"])}
end
assert(all(isfield(runtime,{'solver_steps','times_to_store'})), ...
    'oatof:SolverPolicy','Resolved COMSOL runtime lacks its time-step policy.');
steps = string(runtime.solver_steps);
storage = string(runtime.times_to_store);
assert(isscalar(steps) && any(steps == ["free","intermediate","strict"]), ...
    'oatof:SolverPolicy', ...
    'solver_steps must be free, intermediate or strict; manual needs an explicit step contract.');
assert(isscalar(storage) && storage == "tlist", ...
    'oatof:SolverPolicy','OA-TOF detector sampling requires times_to_store=tlist.');

odeType = string(solverTime.getString('odesolvertype'));
method = ""; explicitMethod = ""; rkMethod = "";
if odeType == "implicit"
    method = string(solverTime.getString('timemethod'));
    switch method
        case "genalpha"
            stepProperty = 'tstepsgenalpha';
        case "bdf"
            stepProperty = 'tstepsbdf';
        otherwise
            error('oatof:UnsupportedTimeSolver','Unsupported implicit CPT method: %s.',method);
    end
elseif odeType == "explicit"
    explicitMethod = string(solverTime.getString('timemethodexp'));
    assert(explicitMethod == "rk",'oatof:UnsupportedTimeSolver', ...
        'Only adaptive Runge-Kutta is supported by the CPT time-step policy.');
    rkMethod = string(solverTime.getString('rkmethod'));
    assert(rkMethod == "dopri5",'oatof:UnsupportedTimeSolver', ...
        'Unsupported explicit CPT Runge-Kutta method: %s.',rkMethod);
    stepProperty = 'tstepsdopri5';
else
    error('oatof:UnsupportedTimeSolver','Unsupported CPT ODE solver type: %s.',odeType);
end
if action == "apply"
    solverTime.set(stepProperty,char(steps));
    solverTime.set('tout',char(storage));
end
actualSteps = string(solverTime.getString(stepProperty));
actualStorage = string(solverTime.getString('tout'));
assert(actualSteps == steps && actualStorage == storage, ...
    'oatof:SolverPolicyReadback', ...
    'Active %s/tout differ from the resolved policy: %s/%s, expected %s/%s.', ...
    stepProperty,actualSteps,actualStorage,steps,storage);
snapshot = struct('ode_solver_type',char(odeType),'time_method',char(method), ...
    'explicit_method',char(explicitMethod),'runge_kutta_method',char(rkMethod), ...
    'step_property',stepProperty,'solver_steps',char(actualSteps), ...
    'times_to_store',char(actualStorage));
end
