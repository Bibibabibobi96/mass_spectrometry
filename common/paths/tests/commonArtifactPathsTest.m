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
            clear workspace_paths common_artifact_paths resolve_path_identity
            testCase.applyFixture(matlab.unittest.fixtures.EnvironmentVariableFixture( ...
                'MASS_SPECTROMETRY_ARTIFACT_ROOT', ''));
            temporary = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.Workspace = char(java.io.File(temporary.Folder).getCanonicalPath());
            source = fileparts(fileparts(mfilename('fullpath')));
            isolatedPaths = fullfile(testCase.Workspace, 'repo', 'common', 'paths');
            mkdir(isolatedPaths);
            copyfile(fullfile(source, 'common_artifact_paths.m'), isolatedPaths);
            copyfile(fullfile(source, 'workspace_paths.m'), isolatedPaths);
            copyfile(fullfile(source, 'resolve_path_identity.m'), isolatedPaths);
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(isolatedPaths));
            testCase.ProjectRoot = fullfile(testCase.Workspace, 'artifacts', 'projects', 'example');
            mkdir(testCase.ProjectRoot);
        end
    end

    methods (Test)
        function futureFileThroughJunctionUsesExistingAncestorIdentity(testCase)
            testCase.assumeTrue(ispc);
            [context,alias]=testCase.contextAlias();
            future=fullfile(alias,'comsol','nested','model.mph');
            actual=resolve_path_identity(future);
            testCase.verifyEqual(actual,fullfile(context,'comsol','nested','model.mph'));
            testCase.verifyFalse(isfolder(fullfile(context,'comsol')));
        end

        function futureIdentityIsStableAfterFileCreation(testCase)
            testCase.assumeTrue(ispc);
            [context,alias]=testCase.contextAlias();
            future=fullfile(alias,'model.mph');
            before=resolve_path_identity(future);
            writeFixtureFile(fullfile(context,'model.mph'),'inert path identity fixture');
            testCase.verifyEqual(resolve_path_identity(future),before);
        end

        function aliasedContextPreservesNativeOutputSpelling(testCase)
            testCase.assumeTrue(ispc);
            [context,alias]=testCase.contextAlias();
            result=common_artifact_paths(alias);
            testCase.verifyEqual(result.artifactRoot,context);
            testCase.verifyEqual(result.modelsDir,fullfile(alias,'comsol'));
            testCase.verifyEqual(result.resultsDir,fullfile(alias,'results'));
            testCase.verifyTrue(isfolder(fullfile(context,'comsol')));
        end

        function externalJunctionContextIsRejected(testCase)
            testCase.assumeTrue(ispc);
            outside=fullfile(testCase.Workspace,'outside');
            mkdir(outside);
            link=fullfile(testCase.ProjectRoot,'runs','escape');
            mkdir(fileparts(link));
            makeFixtureJunction(link,outside);
            testCase.addTeardown(@() removeFixtureJunction(link));
            testCase.verifyError(@() common_artifact_paths(link),'common_artifact_paths:InvalidContext');
            testCase.verifyFalse(isfolder(fullfile(outside,'comsol')));
        end

        function artifactRootAliasResolvesSameIdentity(testCase)
            testCase.assumeTrue(ispc);
            actualRoot=fullfile(testCase.Workspace,'artifacts');
            link=fullfile(testCase.Workspace,'root_alias');
            makeFixtureJunction(link,actualRoot);
            testCase.addTeardown(@() removeFixtureJunction(link));
            result=workspace_paths(ArtifactRoot=string(link));
            testCase.verifyEqual(result.artifactRoot,actualRoot);
        end

        function explicitRootOverridesDeploymentEnvironment(testCase)
            root = fullfile(testCase.Workspace, 'short-payload');
            context = fullfile(root, 'projects', 'example', 'runs', 'explicit');
            mkdir(context);
            setenv('MASS_SPECTROMETRY_ARTIFACT_ROOT', fullfile(testCase.Workspace, 'other'));
            result = common_artifact_paths(context, ArtifactRoot=root);
            testCase.verifyEqual(result.artifactRoot, context);
            testCase.verifyTrue(isfolder(result.modelsDir));
            testCase.verifyFalse(isfolder(fullfile(testCase.Workspace, 'other')));
        end

        function deploymentRootReachesExistingConsumers(testCase)
            root = fullfile(testCase.Workspace, 'payload');
            context = fullfile(root, 'projects', 'example', 'scratch', 'configured');
            mkdir(context);
            setenv('MASS_SPECTROMETRY_ARTIFACT_ROOT', root);
            result = common_artifact_paths(context);
            testCase.verifyEqual(result.artifactRoot, context);
            testCase.verifyTrue(isfolder(result.resultsDir));
            testCase.verifyFalse(isfolder(fullfile(testCase.ProjectRoot, 'scratch')));
        end

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
        function [context,alias]=contextAlias(testCase)
            context=fullfile(testCase.ProjectRoot,'runs','junction');
            mkdir(context);
            alias=fullfile(testCase.Workspace,'execution_alias');
            makeFixtureJunction(alias,context);
            testCase.addTeardown(@() removeFixtureJunction(alias));
        end

        function writeManifest(~, context, status)
            file = fopen(fullfile(context, 'run_manifest.json'), 'w');
            closeFile = onCleanup(@() fclose(file)); %#ok<NASGU>
            fprintf(file, '%s', jsonencode(struct('status', status)));
        end
    end
end

function makeFixtureJunction(link,target)
script=sprintf('$ErrorActionPreference=''Stop'';New-Item -ItemType Junction -Path ''%s'' -Target ''%s'' | Out-Null', ...
    strrep(link,char(39),[char(39) char(39)]),strrep(target,char(39),[char(39) char(39)]));
[status,output]=system(sprintf('pwsh -NoProfile -Command "%s"',script));
assert(status==0,'fixture:Junction','Could not create fixture junction: %s',output);
end

function removeFixtureJunction(link)
java.nio.file.Files.deleteIfExists(java.io.File(link).toPath());
end

function writeFixtureFile(path,text)
fid=fopen(path,'w');assert(fid>=0);
cleanup=onCleanup(@()fclose(fid)); %#ok<NASGU>
fprintf(fid,'%s',text);
end
