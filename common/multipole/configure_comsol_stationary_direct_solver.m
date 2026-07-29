function actualBackend = configure_comsol_stationary_direct_solver(solution, requestedBackend)
%CONFIGURE_COMSOL_STATIONARY_DIRECT_SOLVER Configure the governed direct backend.

requestedBackend = lower(char(requestedBackend));
assert(any(strcmp(requestedBackend, {'mumps', 'pardiso'})), ...
    'Unsupported stationary direct-solver backend: %s', requestedBackend);

stationary=solution.feature('s1');
childTags=cell(stationary.feature.tags());
assert(any(strcmp(childTags,'fc1')) && any(strcmp(childTags,'dDef')), ...
    'Expected stationary direct-solver features are missing. Found: %s', ...
    strjoin(childTags,','));
stationary.feature('dDef').set('linsolver',requestedBackend);
stationary.feature('fc1').set('linsolver','dDef');
actualBackend=lower(char(stationary.feature('dDef').getString('linsolver')));
assert(strcmp(actualBackend,requestedBackend), ...
    'Stationary direct-solver backend differs from the requested backend.');
end
