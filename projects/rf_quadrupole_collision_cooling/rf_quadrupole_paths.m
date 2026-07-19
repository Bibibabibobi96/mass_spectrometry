function paths = rf_quadrupole_paths()
%RF_QUADRUPOLE_PATHS Resolve RF-quadrupole project source and artifact paths.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(componentRoot));
    workspaceRoot = fileparts(repoRoot);
    paths = struct();
    paths.projectRoot = componentRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'projects', ...
        'rf_quadrupole_collision_cooling');
    paths.formalRoot = fullfile(paths.artifactRoot, 'formal');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.archiveRoot = fullfile(paths.artifactRoot, 'archive');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.comsolFormalDir = fullfile(paths.formalRoot, 'comsol');
    paths.simionFormalDir = fullfile(paths.formalRoot, 'simion');
end
