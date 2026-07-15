function paths = workspace_paths(projectName)
%WORKSPACE_PATHS Resolve repository and artifact paths without hard-coding a user path.
%
% paths = workspace_paths('oa_tof')

    arguments
        projectName (1,1) string = ""
    end

    pathsDir = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(pathsDir));
    workspaceRoot = fileparts(repoRoot);

    paths = struct();
    paths.workspaceRoot = workspaceRoot;
    paths.repoRoot = repoRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts');

    if strlength(projectName) == 0
        paths.projectArtifactRoot = '';
        paths.componentArtifactRoot = ''; % Backward-compatible field name.
        return;
    end

    paths.projectArtifactRoot = fullfile(paths.artifactRoot, 'projects', projectName);
    paths.componentArtifactRoot = paths.projectArtifactRoot;
end
