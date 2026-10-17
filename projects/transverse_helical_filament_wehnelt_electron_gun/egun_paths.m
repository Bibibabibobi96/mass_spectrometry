function paths = egun_paths()
%EGUN_PATHS Resolve Wehnelt electron-gun source and artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(componentRoot));
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.projectRoot = componentRoot;
    configuredArtifactRoot = getenv('WEHNELT_ARTIFACT_ROOT');
    if isempty(configuredArtifactRoot)
        paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'projects', ...
            'transverse_helical_filament_wehnelt_electron_gun');
    else
        paths.artifactRoot = configuredArtifactRoot;
    end
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.runId = getenv('WEHNELT_RUN_ID');
    assert(~isempty(paths.runId), 'WEHNELT_RUN_ID is required for a traceable run.');
    paths.runDir = fullfile(paths.runsRoot, paths.runId);
    paths.modelWorkspaceDir = fullfile(paths.runDir, 'comsol');
    paths.resultsDir = fullfile(paths.runDir, 'results');
end
