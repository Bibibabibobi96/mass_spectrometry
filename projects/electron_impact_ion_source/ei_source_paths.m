function paths = ei_source_paths()
%EI_SOURCE_PATHS Resolve electron-impact ion-source artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(componentRoot));
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.projectRoot = componentRoot;
    paths.componentRoot = componentRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'projects', ...
        'electron_impact_ion_source');
    paths.formalRoot = fullfile(paths.artifactRoot, 'formal');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.archiveRoot = fullfile(paths.artifactRoot, 'archive');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.runId = getenv('EI_SOURCE_RUN_ID');
    assert(~isempty(paths.runId), 'EI_SOURCE_RUN_ID is required for a traceable run.');
    paths.runDir = fullfile(paths.runsRoot, paths.runId);
    paths.modelsDir = fullfile(paths.runDir, 'comsol');
    paths.resultsDir = fullfile(paths.runDir, 'results');
end
