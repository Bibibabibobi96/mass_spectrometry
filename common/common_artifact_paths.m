function paths = common_artifact_paths()
%COMMON_ARTIFACT_PATHS Resolve shared COMSOL baseline artifact paths.

    workspace = workspace_paths();
    paths = struct();
    paths.artifactRoot = fullfile(workspace.artifactRoot, 'common');
    paths.modelsDir = fullfile(paths.artifactRoot, 'models', 'comsol');
    paths.resultsDir = fullfile(paths.artifactRoot, 'results', 'comsol');
    paths.scratchDir = fullfile(paths.artifactRoot, 'scratch', 'comsol');
end
