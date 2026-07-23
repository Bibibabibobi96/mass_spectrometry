function configure_comsol_stationary_direct_solver(solution)
%CONFIGURE_COMSOL_STATIONARY_DIRECT_SOLVER Use the shared MUMPS stationary solve.

stationary=solution.feature('s1');
childTags=cell(stationary.feature.tags());
assert(any(strcmp(childTags,'fc1')) && any(strcmp(childTags,'dDef')), ...
    'Expected stationary direct-solver features are missing. Found: %s', ...
    strjoin(childTags,','));
stationary.feature('dDef').set('linsolver','mumps');
stationary.feature('fc1').set('linsolver','dDef');
end
