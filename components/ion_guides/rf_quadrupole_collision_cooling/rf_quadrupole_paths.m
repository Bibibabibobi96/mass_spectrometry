function paths = rf_quadrupole_paths()
%RF_QUADRUPOLE_PATHS Resolve RF-quadrupole source and artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = componentRoot;
    for level = 1:3
        repoRoot = fileparts(repoRoot);
    end
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.componentRoot = componentRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'components', ...
        'ion_guides', 'rf_quadrupole_collision_cooling');
    paths.modelsDir = fullfile(paths.artifactRoot, 'scratch', 'comsol');
    paths.resultsDir = fullfile(paths.artifactRoot, 'results', 'comsol');
end
