function paths = common_artifact_paths(runDir, options)
%COMMON_ARTIFACT_PATHS Resolve COMSOL outputs in an existing project context.
% Pass the same runs/<run_id> or scratch/<task_id> directory to dependent
% component-test stages. This helper never chooses or creates a run identity.

    arguments
        runDir {mustBeTextScalar, mustBeNonempty}
        options.ArtifactRoot (1,1) string = ""
    end

    workspace = workspace_paths(ArtifactRoot=options.ArtifactRoot);
    projectsRoot = resolve_path_identity(fullfile(workspace.artifactRoot, 'projects'));
    executionRunDir = char(runDir);
    runDir = resolve_path_identity(runDir);
    prefix = [projectsRoot filesep];
    if ~isfolder(runDir) || ~startsWith(runDir, prefix, 'IgnoreCase', ispc)
        error('common_artifact_paths:InvalidContext', ...
            'Provide an existing artifact project runs/run_id or scratch/task_id directory.');
    end
    parts = split(string(runDir(numel(prefix) + 1:end)), filesep);
    if numel(parts) ~= 3 || ~ismember(parts(2), ["runs", "scratch"])
        error('common_artifact_paths:InvalidContext', ...
            'The output context must be a direct child of project runs or scratch.');
    end
    manifestPath = fullfile(runDir, 'run_manifest.json');
    if isfile(manifestPath)
        manifest = jsondecode(fileread(manifestPath));
        if ~isfield(manifest, 'status') || ~strcmp(manifest.status, 'checkpoint')
            error('common_artifact_paths:PublishedContext', ...
                'A published run cannot be reused as a component-test output context.');
        end
    end
    paths = struct();
    paths.artifactRoot = runDir;
    paths.modelsDir = fullfile(executionRunDir, 'comsol');
    paths.resultsDir = fullfile(executionRunDir, 'results');
    if ~isfolder(paths.modelsDir), mkdir(paths.modelsDir); end
    if ~isfolder(paths.resultsDir), mkdir(paths.resultsDir); end
end
