classdef commonArtifactPathsTest < matlab.unittest.TestCase
    % Test real path functions in an isolated, automatically removed workspace.
    properties
        Workspace
        ProjectRoot
    end

    properties (TestParameter)
        lifecycle = {'runs', 'scratch'}
        invalidRelative = {'formal/review', 'runs', 'runs/id/nested'}
        publishedStatus = {'success', 'failed', 'interrupted', 'superseded'}
    end

    methods (TestMethodSetup)
        function isolatedWorkspace(testCase)
            temporary = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.Workspace = char(java.io.File(temporary.Folder).getCanonicalPath());
            source = fileparts(fileparts(mfilename('fullpath')));
            isolatedPaths = fullfile(testCase.Workspace, 'repo', 'common', 'paths');
            mkdir(isolatedPaths);
            copyfile(fullfile(source, 'common_artifact_paths.m'), isolatedPaths);
            copyfile(fullfile(source, 'workspace_paths.m'), isolatedPaths);
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(isolatedPaths));
            testCase.ProjectRoot = fullfile(testCase.Workspace, 'artifacts', 'projects', 'example');
            mkdir(testCase.ProjectRoot);
        end
    end

    methods (Test)
        function createsOnlyRunLocalOutputs(testCase, lifecycle)
            context = fullfile(testCase.ProjectRoot, lifecycle, 'example');
            mkdir(context);
            result = common_artifact_paths(context);
            testCase.verifyEqual(result.artifactRoot, context);
            testCase.verifyEqual(result.modelsDir, fullfile(context, 'comsol'));
            testCase.verifyEqual(result.resultsDir, fullfile(context, 'results'));
            testCase.verifyTrue(isfolder(result.modelsDir));
            testCase.verifyTrue(isfolder(result.resultsDir));
        end

        function rejectsMissingContextWithoutCreatingIt(testCase)
            context = fullfile(testCase.ProjectRoot, 'runs', 'missing');
            testCase.verifyError(@() common_artifact_paths(context), 'common_artifact_paths:InvalidContext');
            testCase.verifyFalse(isfolder(context));
        end

        function rejectsInvalidLayout(testCase, invalidRelative)
            context = fullfile(testCase.ProjectRoot, invalidRelative);
            mkdir(context);
            testCase.verifyError(@() common_artifact_paths(context), 'common_artifact_paths:InvalidContext');
            testCase.verifyFalse(isfolder(fullfile(context, 'comsol')));
        end

        function rejectsOutsideArtifacts(testCase)
            testCase.verifyError(@() common_artifact_paths(testCase.Workspace), ...
                'common_artifact_paths:InvalidContext');
        end

        function acceptsCheckpoint(testCase)
            context = fullfile(testCase.ProjectRoot, 'runs', 'checkpoint');
            mkdir(context);
            testCase.writeManifest(context, 'checkpoint');
            result = common_artifact_paths(context);
            testCase.verifyEqual(result.artifactRoot, context);
        end

        function rejectsPublishedContext(testCase, publishedStatus)
            context = fullfile(testCase.ProjectRoot, 'runs', 'published');
            mkdir(context);
            testCase.writeManifest(context, publishedStatus);
            testCase.verifyError(@() common_artifact_paths(context), 'common_artifact_paths:PublishedContext');
            testCase.verifyFalse(isfolder(fullfile(context, 'comsol')));
        end
    end

    methods (Access = private)
        function writeManifest(~, context, status)
            file = fopen(fullfile(context, 'run_manifest.json'), 'w');
            closeFile = onCleanup(@() fclose(file)); %#ok<NASGU>
            fprintf(file, '%s', jsonencode(struct('status', status)));
        end
    end
end
