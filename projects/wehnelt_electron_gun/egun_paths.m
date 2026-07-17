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
    paths.modelsRoot = fullfile(paths.artifactRoot, 'models');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.resultsRoot = fullfile(paths.artifactRoot, 'results');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.modelFormalDir = fullfile(paths.artifactRoot, 'models', 'comsol', 'formal');
    paths.modelWorkspaceDir = fullfile(paths.artifactRoot, 'models', 'comsol', 'workspace');
    paths.modelArchiveDir = fullfile(paths.artifactRoot, 'models', 'comsol', 'archive');
    paths.resultsDir = fullfile(paths.resultsRoot, 'comsol');
    paths.resultsFormalDir = fullfile(paths.resultsDir, 'formal');
    paths.resultsWorkspaceDir = fullfile(paths.resultsDir, 'workspace');
    paths.resultsArchiveDir = fullfile(paths.resultsDir, 'archive');
    paths.scratchDir = fullfile(paths.scratchRoot, 'comsol');
end
