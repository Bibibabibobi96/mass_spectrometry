function paths = ei_source_paths()
%EI_SOURCE_PATHS Resolve electron-impact ion-source artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(componentRoot));
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.componentRoot = componentRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'projects', ...
        'electron_impact_ion_source');
    paths.modelsDir = fullfile(paths.artifactRoot, 'scratch', 'comsol');
    paths.resultsDir = fullfile(paths.artifactRoot, 'results', 'comsol');
end
