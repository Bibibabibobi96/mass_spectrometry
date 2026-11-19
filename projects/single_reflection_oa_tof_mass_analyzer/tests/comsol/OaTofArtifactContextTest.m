classdef OaTofArtifactContextTest < matlab.unittest.TestCase
    properties
        activeProject
        folder
    end
    methods (TestMethodSetup)
        function prepare(testCase)
            clear oatof_paths workspace_paths resolve_path_identity run_oatof_model oatof_build_model_core oatof_build_saved_particle_solution
            testCase.activeProject=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(testCase.activeProject));
            testCase.applyFixture(matlab.unittest.fixtures.EnvironmentVariableFixture('OATOF_PROJECT_ROOT',testCase.activeProject));
            testCase.applyFixture(matlab.unittest.fixtures.EnvironmentVariableFixture('OATOF_REPOSITORY_ROOT',fileparts(fileparts(testCase.activeProject))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(testCase.activeProject,'comsol')));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(fileparts(fileparts(testCase.activeProject)),'src','msplatform','backends','comsol','matlab')));
            fixture=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.folder=fixture.Folder;
        end
    end
    methods (Test)
        function namedEntryAuthorizesFutureAliasButPreservesNativeSpelling(testCase)
            testCase.assumeTrue(ispc);
            [project,artifact,contract]=testCase.snapshot();
            context=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','runs','alias_case');
            mkdir(context);
            alias=fullfile(testCase.folder,'execution_alias');
            makeFixtureJunction(alias,context);
            testCase.addTeardown(@() removeFixtureJunction(alias));
            writeCoreTransportFixture(fullfile(project,'comsol','oatof_build_model_core.m'));
            clear oatof_build_model_core
            rehash
            output=fullfile(alias,'comsol','future','model.mph');
            result=run_oatof_model(ArtifactRoot=artifact,ContractPath=contract,OutputModelPath=output);
            testCase.verifyEqual(string(result.execution_output),string(output));
            testCase.verifyEqual(string(resolve_path_identity(output)),string(fullfile(context,'comsol','future','model.mph')));
            testCase.verifyFalse(isfile(fullfile(context,'comsol','future','model.mph')));
        end
        function namedEntryRejectsExternalJunction(testCase)
            testCase.assumeTrue(ispc);
            [~,artifact,contract]=testCase.snapshot();
            outside=fullfile(testCase.folder,'outside');
            mkdir(outside);
            alias=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','runs','escape');
            mkdir(fileparts(alias));
            makeFixtureJunction(alias,outside);
            testCase.addTeardown(@() removeFixtureJunction(alias));
            testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact,ContractPath=contract, ...
                OutputModelPath=fullfile(alias,'future.mph')),'oatof:OutputModelPath');
        end
        function namedEntryRejectsFormalJunction(testCase)
            testCase.assumeTrue(ispc);
            [~,artifact,contract]=testCase.snapshot();
            formal=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','formal','comsol');
            mkdir(formal);
            alias=fullfile(testCase.folder,'formal_alias');
            makeFixtureJunction(alias,formal);
            testCase.addTeardown(@() removeFixtureJunction(alias));
            testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact,ContractPath=contract, ...
                OutputModelPath=fullfile(alias,'future.mph')),'oatof:OutputModelPath');
        end
        function ordinaryDefaultPathsAreUnchanged(testCase)
            paths=oatof_paths();
            repo=fileparts(fileparts(testCase.activeProject));
            expected=fullfile(fileparts(repo),'artifacts','projects','single_reflection_oa_tof_mass_analyzer');
            testCase.verifyEqual(paths.artifactRoot,expected);
            testCase.verifyEqual(paths.projectRoot,string(testCase.activeProject));
            testCase.verifyEqual(paths.runsRoot,fullfile(expected,'runs'));
            testCase.verifyEqual(paths.comsolFormalDir,fullfile(expected,'formal','comsol'));
        end
        function frozenSourceUsesExplicitArtifactRoot(testCase)
            [project,artifact,~]=testCase.snapshot();
            paths=oatof_paths(artifact);
            expected=char(fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer'));
            testCase.verifyEqual(paths.projectRoot,string(project));
            testCase.verifyEqual(paths.artifactRoot,expected);
            testCase.verifyEqual(paths.runsRoot,fullfile(expected,'runs'));
            testCase.verifyEqual(string(paths.commonComsolDir), ...
                string(fullfile(fileparts(fileparts(project)),'src','msplatform','backends','comsol','matlab')));
        end
        function namedEntryAcceptsManagedScratchBeforeNativeBoundary(testCase)
            [~,artifact,contract]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','scratch','probe','model.mph');
            testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact,ContractPath=contract, ...
                OutputModelPath=output,AcceleratorGeometry=struct('invalid',1)), ...
                'oatof:AcceleratorProjection');
        end
        function namedEntryPreservesExecutionOutputSpelling(testCase)
            [project,artifact,contract]=testCase.snapshot();
            scratch=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','scratch','probe');
            mkdir(fullfile(scratch,'nested'));
            output=fullfile(scratch,'nested','..','model.mph');
            writeCoreTransportFixture(fullfile(project,'comsol','oatof_build_model_core.m'));
            clear oatof_build_model_core
            rehash
            testCase.assertEqual(which('oatof_build_model_core'), ...
                fullfile(project,'comsol','oatof_build_model_core.m'));
            result=run_oatof_model(ArtifactRoot=artifact,ContractPath=contract,OutputModelPath=output);
            testCase.verifyEqual(result.execution_output,string(output));
            testCase.verifyNotEqual(result.execution_output, ...
                string(java.io.File(char(output)).getCanonicalPath()));
        end
        function namedEntryRejectsFormalFromFrozenSource(testCase)
            [~,artifact,contract]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','formal','comsol','model.mph');
            for geometryOnly=[false,true]
                testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact,ContractPath=contract, ...
                    OutputModelPath=output,GeometryOnly=geometryOnly),'oatof:OutputModelPath');
            end
        end
        function namedEntryRejectsOutsideLifecycleRoot(testCase)
            [~,artifact,contract]=testCase.snapshot();
            output=fullfile(testCase.folder,'outside','model.mph');
            for geometryOnly=[false,true]
                testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact,ContractPath=contract, ...
                    OutputModelPath=output,GeometryOnly=geometryOnly),'oatof:OutputModelPath');
            end
        end
        function geometryOnlyRequiresExplicitContract(testCase)
            [~,artifact,~]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','runs','geometry','model.mph');
            testCase.verifyError(@() run_oatof_model(GeometryOnly=true,ArtifactRoot=artifact, ...
                OutputModelPath=output),'oatof:GeometryOnlyPaths');
        end
        function geometryOnlyRequiresExplicitOutput(testCase)
            [~,artifact,contract]=testCase.snapshot();
            testCase.verifyError(@() run_oatof_model(GeometryOnly=true,ArtifactRoot=artifact, ...
                ContractPath=contract),'oatof:GeometryOnlyPaths');
        end
        function geometryOnlyRejectsFieldAndSourceConfiguration(testCase)
            [~,artifact,contract]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','runs','geometry','model.mph');
            for extra={{'FieldDesignOnly',true},{'FixedParticleTable',"unused.ion"}, ...
                    {'CartesianRelease',"unused.csv"}}
                args=[{'GeometryOnly',true,'ArtifactRoot',artifact, ...
                    'ContractPath',contract,'OutputModelPath',output},extra{1}];
                testCase.verifyError(@() run_oatof_model(args{:}), ...
                    'oatof:GeometryOnlyScope');
            end
        end
        function geometryOnlyAcceptsManagedOutputBeforeNativeBoundary(testCase)
            [~,artifact,contract]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','runs','geometry','model.mph');
            testCase.verifyError(@() run_oatof_model(GeometryOnly=true,ArtifactRoot=artifact, ...
                ContractPath=contract,OutputModelPath=output,AcceleratorGeometry=struct('invalid',1)), ...
                'oatof:AcceleratorProjection');
        end
        function frozenExplicitContractUsesCanonicalResourcesAndRestoresContext(testCase)
            [project,artifact,contract]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','scratch','default','model.mph');
            writeCoreTransportFixture(fullfile(project,'comsol','oatof_build_model_core.m'));
            clear run_oatof_model oatof_build_model_core load_oatof_contract
            originalPath=path;originalFolder=pwd;
            restore=onCleanup(@() path(originalPath));
            folderRestore=onCleanup(@() cd(originalFolder));
            backend=fullfile(fileparts(fileparts(project)),'src','msplatform','backends','comsol','matlab');
            addpath(backend);
            result=run_oatof_model(ArtifactRoot=artifact,ContractPath=contract,OutputModelPath=output);
            testCase.verifyEqual(result.execution_output,string(output));
            testCase.verifyEqual(which('run_oatof_model'),fullfile(backend,'run_oatof_model.m'));
            testCase.verifyEqual(which('load_oatof_contract'),fullfile(backend,'load_oatof_contract.m'));
            testCase.verifyEqual(path,originalPath);
            testCase.verifyEqual(pwd,originalFolder);
        end
        function omittedOrMissingContractIsRejectedBeforeNativeWithContextRestored(testCase)
            [~,artifact,~]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','scratch','missing','model.mph');
            originalPath=path;originalFolder=pwd;
            for fieldDesignOnly=[false,true]
                testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact, ...
                    OutputModelPath=output,FieldDesignOnly=fieldDesignOnly), ...
                    'oatof:MissingResolvedContract');
                testCase.verifyEqual(path,originalPath);
                testCase.verifyEqual(pwd,originalFolder);
            end
            testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact, ...
                ContractPath=fullfile(testCase.folder,'absent.json'),OutputModelPath=output), ...
                'oatof:MissingResolvedContract');
            testCase.verifyEqual(path,originalPath);
            testCase.verifyEqual(pwd,originalFolder);
        end
        function relativeArtifactRootIsRejected(testCase)
            testCase.verifyError(@() oatof_paths('relative/artifacts'),'workspace:ArtifactRoot');
        end
    end
    methods (Access=private)
        function [project,artifact,contract]=snapshot(testCase)
            clear oatof_paths workspace_paths resolve_path_identity run_oatof_model oatof_build_model_core oatof_build_saved_particle_solution
            snapshotRoot=fullfile(testCase.folder,'source_snapshot');
            artifact=string(fullfile(testCase.folder,'artifacts'));
            command=sprintf(['python -c "from pathlib import Path; ' ...
                'from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import freeze_candidate_source_closure; ' ...
                'freeze_candidate_source_closure(Path(r''%s''),Path(r''%s''))"'],snapshotRoot,artifact);
            [status,output]=system(command);
            assert(status==0,'fixture:SourceClosure','Could not create frozen source layout: %s',output);
            project=fullfile(snapshotRoot,'projects','single_reflection_oa_tof_mass_analyzer');
            mkdir(fullfile(project,'comsol'));
            copyfile(fullfile(testCase.activeProject,'comsol','oatof_build_model_core.m'),fullfile(project,'comsol'));
            copyfile(fullfile(testCase.activeProject,'comsol','oatof_build_saved_particle_solution.m'),fullfile(project,'comsol'));
            copyfile(fullfile(testCase.activeProject,'comsol','oatof_save_run_model.m'),fullfile(project,'comsol'));
            copyfile(fullfile(testCase.activeProject,'comsol','oatof_write_saved_particle_context.m'),fullfile(project,'comsol'));
            contract=string(fullfile(testCase.folder,'resolved.json'));
            copyfile(fullfile(testCase.activeProject,'config','resolved_geometry.json'),contract);
            mkdir(fullfile(project,'config'));
            copyfile(contract,fullfile(project,'config','resolved_geometry.json'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(project));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(project,'comsol')));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(snapshotRoot,'src','msplatform','backends','comsol','matlab')));
            testCase.applyFixture(matlab.unittest.fixtures.EnvironmentVariableFixture('OATOF_PROJECT_ROOT',project));
        end
    end
end

function writeCoreTransportFixture(path)
fid=fopen(path,'w');assert(fid>=0);
cleanup=onCleanup(@()fclose(fid));
fprintf(fid,'function result=oatof_build_model_core(varargin)\nresult=struct(''execution_output'',string(varargin{17}));\nend\n');
clear cleanup
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
