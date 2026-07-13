function paths = oatof_paths()
%OATOF_PATHS Resolve oa-TOF source and artifact paths from this file.
%
% Keep this function free of machine-specific absolute paths.  Entry
% scripts may move with the repository as long as the workspace keeps the
% sibling layout simulation_repo/ and artifacts/.

    componentRoot = fileparts(mfilename('fullpath'));
    repoRoot = componentRoot;
    for level = 1:4
        repoRoot = fileparts(repoRoot);
    end
    workspaceRoot = fileparts(repoRoot);

    paths = struct();
    paths.workspaceRoot = workspaceRoot;
    paths.repoRoot = repoRoot;
    paths.commonDir = fullfile(repoRoot, 'common');
    paths.componentRoot = componentRoot;
    paths.comsolDir = fullfile(componentRoot, 'comsol');
    paths.cadDir = fullfile(componentRoot, 'cad');
    paths.testsDir = fullfile(componentRoot, 'tests');

    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'components', ...
        'mass_analyzers', 'oa_tof', 'dual_stage_ringstack');
    paths.comsolModelRoot = fullfile(paths.artifactRoot, 'models', 'comsol');
    paths.comsolFormalDir = fullfile(paths.comsolModelRoot, 'formal');
    paths.comsolArchiveDir = fullfile(paths.comsolModelRoot, 'archive');
    paths.comsolScratchDir = fullfile(paths.artifactRoot, 'scratch', 'comsol');
    paths.comsolResultsDir = fullfile(paths.artifactRoot, 'results', 'comsol');
    paths.cadFormalDir = fullfile(paths.artifactRoot, 'cad', 'formal');
    paths.cadArchiveDir = fullfile(paths.artifactRoot, 'cad', 'archive');
    paths.cadScratchDir = fullfile(paths.artifactRoot, 'scratch', 'cad');
    paths.simionWorkspaceDir = fullfile(paths.artifactRoot, 'models', ...
        'simion', 'workspace');
    paths.simionScratchDir = fullfile(paths.artifactRoot, 'scratch', 'simion');
end
