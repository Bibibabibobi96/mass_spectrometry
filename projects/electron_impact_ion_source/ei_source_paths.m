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
    paths.modelsRoot = fullfile(paths.artifactRoot, 'models');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.resultsRoot = fullfile(paths.artifactRoot, 'results');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.comsolFormalDir = fullfile(paths.modelsRoot, 'comsol', 'formal');
    paths.comsolCandidateDir = fullfile(paths.modelsRoot, 'comsol', 'candidates');
    paths.comsolResultsDir = fullfile(paths.resultsRoot, 'comsol');
    paths.comsolScratchDir = fullfile(paths.scratchRoot, 'comsol');
    paths.modelsDir = paths.comsolScratchDir; % Legacy collision-script alias.
    paths.resultsDir = paths.comsolResultsDir;
end
