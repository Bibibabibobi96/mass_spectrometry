function paths = oatof_paths(artifactRoot)
%OATOF_PATHS Resolve oa-TOF source and artifact paths from this file.
%
% Keep this function free of machine-specific absolute paths.  Entry
% scripts may move with the repository as long as the workspace keeps the
% sibling layout simulation_repo/ and artifacts/.

    projectRoot = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(projectRoot));
    if nargin<1, artifactRoot=""; end
    addpath(fullfile(repoRoot,'common','paths'));
    workspace=workspace_paths('single_reflection_oa_tof_mass_analyzer',ArtifactRoot=string(artifactRoot));

    paths = struct();
    paths.workspaceRoot = workspace.workspaceRoot;
    paths.repoRoot = repoRoot;
    paths.commonComsolDir = fullfile(repoRoot, 'common', 'comsol');
    paths.commonPathsDir = fullfile(repoRoot, 'common', 'paths');
    paths.commonSolidWorksDir = fullfile(repoRoot, 'common', 'solidworks');
    paths.projectRoot = projectRoot;
    paths.comsolDir = fullfile(projectRoot, 'comsol');
    paths.cadDir = fullfile(projectRoot, 'cad');
    paths.testsDir = fullfile(projectRoot, 'tests');

    paths.artifactRoot = char(workspace.projectArtifactRoot);
    paths.formalRoot = fullfile(paths.artifactRoot, 'formal');
    paths.runsRoot = fullfile(paths.artifactRoot, 'runs');
    paths.archiveRoot = fullfile(paths.artifactRoot, 'archive');
    paths.scratchRoot = fullfile(paths.artifactRoot, 'scratch');
    paths.comsolFormalDir = fullfile(paths.formalRoot, 'comsol');
    paths.cadFormalDir = fullfile(paths.formalRoot, 'cad');
    paths.simionFormalDir = fullfile(paths.formalRoot, 'simion');
end
