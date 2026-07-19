function paths = egun_paths()
%EGUN_PATHS Resolve Wehnelt electron-gun source and artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(componentRoot));
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.projectRoot = componentRoot;
    paths.componentRoot = componentRoot;
    paths.repoRoot = repoRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'projects', ...
        'wehnelt_electron_gun');
    paths.formalRoot = fullfile(paths.artifactRoot, 'formal');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.archiveRoot = fullfile(paths.artifactRoot, 'archive');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.runId = getenv('WEHNELT_RUN_ID');
    assert(~isempty(paths.runId), 'WEHNELT_RUN_ID is required for a traceable run.');
    paths.runDir = fullfile(paths.runsRoot, paths.runId);
    paths.modelWorkspaceDir = fullfile(paths.runDir, 'comsol');
    paths.resultsDir = fullfile(paths.runDir, 'results');
end
