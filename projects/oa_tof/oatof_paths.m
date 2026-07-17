function paths = oatof_paths()
%OATOF_PATHS Resolve oa-TOF source and artifact paths from this file.
%
% Keep this function free of machine-specific absolute paths.  Entry
% scripts may move with the repository as long as the workspace keeps the
% sibling layout simulation_repo/ and artifacts/.

    projectRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(projectRoot));
    workspaceRoot = fileparts(repoRoot);

    paths = struct();
    paths.workspaceRoot = workspaceRoot;
    paths.repoRoot = repoRoot;
    paths.commonComsolDir = fullfile(repoRoot, 'common', 'comsol');
    paths.commonPathsDir = fullfile(repoRoot, 'common', 'paths');
    paths.commonSolidWorksDir = fullfile(repoRoot, 'common', 'solidworks');
    paths.commonDir = paths.commonSolidWorksDir; % Backward-compatible CAD helper path.
    paths.projectRoot = projectRoot;
    paths.componentRoot = projectRoot; % Backward-compatible field name.
    paths.comsolDir = fullfile(projectRoot, 'comsol');
    paths.cadDir = fullfile(projectRoot, 'cad');
    paths.testsDir = fullfile(projectRoot, 'tests');

    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts', 'projects', 'oa_tof');
    paths.modelsRoot = fullfile(paths.artifactRoot, 'models');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.resultsRoot = fullfile(paths.artifactRoot, 'results');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.comsolModelRoot = fullfile(paths.artifactRoot, 'models', 'comsol');
    paths.comsolFormalDir = fullfile(paths.comsolModelRoot, 'formal');
    paths.comsolCandidateDir = fullfile(paths.comsolModelRoot, 'candidates');
    paths.comsolArchiveDir = fullfile(paths.comsolModelRoot, 'archive');
    paths.comsolScratchDir = fullfile(paths.scratchRoot, 'comsol');
    paths.comsolResultsDir = fullfile(paths.resultsRoot, 'comsol');
    paths.cadFormalDir = fullfile(paths.artifactRoot, 'cad', 'formal');
    paths.cadArchiveDir = fullfile(paths.artifactRoot, 'cad', 'archive');
    paths.cadScratchDir = fullfile(paths.artifactRoot, 'scratch', 'cad');
    paths.simionModelRoot = fullfile(paths.artifactRoot, 'models', 'simion');
    paths.simionFormalDir = fullfile(paths.simionModelRoot, 'formal', 'oatof_524amu');
    % Retained only as the source/archive tree for older diagnostics and the
    % convergence reference.  Formal runtime assets no longer depend on it.
    paths.simionWorkspaceDir = fullfile(paths.artifactRoot, 'models', ...
        'simion', 'workspace');
    paths.simionCandidateDir = fullfile(paths.simionWorkspaceDir, ...
        'diagnostics', 'accelerator_compact_scan', 'workbenches');
    paths.simionScratchDir = fullfile(paths.scratchRoot, 'simion');
end
