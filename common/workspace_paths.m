function paths = workspace_paths(componentParts)
%WORKSPACE_PATHS Resolve repository and artifact paths without hard-coding a user path.
%
% paths = workspace_paths({'mass_analyzers','oa_tof','dual_stage_ringstack'})

    arguments
        componentParts (1,:) cell = {}
    end

    commonDir = fileparts(mfilename('fullpath'));
    repoRoot = fileparts(commonDir);
    workspaceRoot = fileparts(repoRoot);

    paths = struct();
    paths.workspaceRoot = workspaceRoot;
    paths.repoRoot = repoRoot;
    paths.artifactRoot = fullfile(workspaceRoot, 'artifacts');

    if isempty(componentParts)
        paths.componentArtifactRoot = '';
        return;
    end

    paths.componentArtifactRoot = fullfile( ...
        paths.artifactRoot, 'components', componentParts{:});
end
