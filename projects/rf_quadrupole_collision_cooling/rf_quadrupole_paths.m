function paths = rf_quadrupole_paths()
%RF_QUADRUPOLE_PATHS Resolve RF-quadrupole project source and artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(componentRoot));
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.projectRoot = componentRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'projects', ...
        'rf_quadrupole_collision_cooling');
    paths.modelsRoot = fullfile(paths.artifactRoot, 'models');
    paths.resultsRoot = fullfile(paths.artifactRoot, 'results');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.comsolFormalDir = fullfile(paths.modelsRoot, 'comsol', 'formal');
    paths.comsolCandidateDir = fullfile(paths.modelsRoot, 'comsol', 'candidates');
    paths.simionFormalDir = fullfile(paths.modelsRoot, 'simion', 'formal');
    paths.simionCandidateDir = fullfile(paths.modelsRoot, 'simion', 'candidates');
    paths.comsolResultsDir = fullfile(paths.resultsRoot, 'comsol');
    paths.simionResultsDir = fullfile(paths.resultsRoot, 'simion');
    paths.crossSolverResultsDir = fullfile(paths.resultsRoot, 'cross_solver');
    paths.scratchDir = paths.scratchRoot;
end
