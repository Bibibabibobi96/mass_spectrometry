function paths = workspace_paths(projectName,options)
%WORKSPACE_PATHS Resolve repository and artifact paths without hard-coding a user path.
%
% paths = workspace_paths('single_reflection_oa_tof_mass_analyzer')

    arguments
        projectName (1,1) string = ""
        options.ArtifactRoot (1,1) string = ""
    end

    pathsDir = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(fileparts(pathsDir));
    workspaceRoot = fileparts(repoRoot);

    paths = struct();
    paths.workspaceRoot = workspaceRoot;
    paths.repoRoot = repoRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts');
    artifactRoot = options.ArtifactRoot;
    if strlength(artifactRoot)==0
        artifactRoot = string(getenv('MASS_SPECTROMETRY_ARTIFACT_ROOT'));
    end
    if strlength(artifactRoot)>0
        root=java.io.File(char(artifactRoot));
        assert(root.isAbsolute(),'workspace:ArtifactRoot', ...
            'ArtifactRoot must be an explicit absolute artifacts root.');
        paths.artifactRoot=char(root.getCanonicalPath());
    end

    if strlength(projectName) == 0
        paths.projectArtifactRoot = '';
        return;
    end

    paths.projectArtifactRoot = fullfile(paths.artifactRoot, 'projects', projectName);
end
