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
    paths.comsolModelRoot = fullfile(paths.artifactRoot, 'models', 'comsol');
    paths.comsolFormalDir = fullfile(paths.comsolModelRoot, 'formal');
    paths.comsolCandidateDir = fullfile(paths.comsolModelRoot, 'candidates');
    paths.comsolArchiveDir = fullfile(paths.comsolModelRoot, 'archive');
    paths.comsolScratchDir = fullfile(paths.artifactRoot, 'scratch', 'comsol');
    paths.comsolResultsDir = fullfile(paths.artifactRoot, 'results', 'comsol');
    paths.cadFormalDir = fullfile(paths.artifactRoot, 'cad', 'formal');
    paths.cadArchiveDir = fullfile(paths.artifactRoot, 'cad', 'archive');
    paths.cadScratchDir = fullfile(paths.artifactRoot, 'scratch', 'cad');
    % SIMION keeps the legacy workspace layer until its relative PA links are
    % rebuilt and validated.  Do not flatten this path with a file-only move.
    paths.simionWorkspaceDir = fullfile(paths.artifactRoot, 'models', ...
        'simion', 'workspace');
    paths.simionFormalDir = fullfile(paths.simionWorkspaceDir, ...
        '04_workbench', 'formal');
    paths.simionCandidateDir = fullfile(paths.simionWorkspaceDir, ...
        'diagnostics', 'accelerator_compact_scan', 'workbenches');
    paths.simionScratchDir = fullfile(paths.artifactRoot, 'scratch', 'simion');
end
