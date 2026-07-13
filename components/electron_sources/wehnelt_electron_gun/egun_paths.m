function paths = egun_paths()
%EGUN_PATHS Resolve Wehnelt electron-gun source and artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = componentRoot;
    for level = 1:3
        repoRoot = fileparts(repoRoot);
    end
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.componentRoot = componentRoot;
    paths.repoRoot = repoRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'components', ...
        'electron_sources', 'wehnelt_electron_gun');
    paths.modelWorkspaceDir = fullfile(paths.artifactRoot, 'models', 'comsol', 'workspace');
    paths.modelArchiveDir = fullfile(paths.artifactRoot, 'models', 'comsol', 'archive');
    paths.resultsDir = fullfile(paths.artifactRoot, 'results', 'comsol');
    paths.scratchDir = fullfile(paths.artifactRoot, 'scratch', 'comsol');
end
