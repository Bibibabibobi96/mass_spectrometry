function paths = oatof_paths(artifactRoot, projectRoot)
%OATOF_PATHS Resolve oa-TOF source and artifact paths from this file.
%
% Keep this function free of machine-specific absolute paths.  Entry
% scripts may move with the repository as long as the workspace keeps the
% sibling layout simulation_repo/ and artifacts/.

    comsolDir = fileparts(mfilename('fullpath'));
    if nargin<1, artifactRoot=""; end
    if nargin<2 || strlength(string(projectRoot))==0
        projectRoot = string(getenv('OATOF_PROJECT_ROOT'));
    end
    addpath(comsolDir);
    workspace=workspace_paths('single_reflection_oa_tof_mass_analyzer',ArtifactRoot=string(artifactRoot));

    paths = struct();
    paths.workspaceRoot = workspace.workspaceRoot;
    paths.repoRoot = string(getenv('OATOF_REPOSITORY_ROOT'));
    paths.commonComsolDir = comsolDir;
    paths.commonPathsDir = comsolDir;
    paths.commonSolidWorksDir = string(getenv('OATOF_SOLIDWORKS_ROOT'));
    paths.projectRoot = projectRoot;
    paths.comsolDir = comsolDir;
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
