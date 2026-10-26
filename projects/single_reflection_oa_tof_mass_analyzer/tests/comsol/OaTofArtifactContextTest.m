classdef OaTofArtifactContextTest < matlab.unittest.TestCase
    properties
        activeProject
        folder
    end
    methods (TestMethodSetup)
        function prepare(testCase)
            clear oatof_paths workspace_paths run_oatof_model oatof_build_model_core
            testCase.activeProject=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(testCase.activeProject));
            fixture=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.folder=fixture.Folder;
        end
    end
    methods (Test)
        function ordinaryDefaultPathsAreUnchanged(testCase)
            paths=oatof_paths();
            repo=fileparts(fileparts(testCase.activeProject));
            expected=fullfile(fileparts(repo),'artifacts','projects','single_reflection_oa_tof_mass_analyzer');
            testCase.verifyEqual(paths.artifactRoot,expected);
            testCase.verifyEqual(paths.projectRoot,testCase.activeProject);
            testCase.verifyEqual(paths.runsRoot,fullfile(expected,'runs'));
            testCase.verifyEqual(paths.comsolFormalDir,fullfile(expected,'formal','comsol'));
        end
        function frozenSourceUsesExplicitArtifactRoot(testCase)
            [project,artifact,~]=testCase.snapshot();
            paths=oatof_paths(artifact);
            expected=char(fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer'));
            testCase.verifyEqual(paths.projectRoot,project);
            testCase.verifyEqual(paths.artifactRoot,expected);
            testCase.verifyEqual(paths.runsRoot,fullfile(expected,'runs'));
            testCase.verifyEqual(paths.commonComsolDir,fullfile(testCase.folder,'source_snapshot','common','comsol'));
        end
        function namedEntryAcceptsManagedScratchBeforeNativeBoundary(testCase)
            [~,artifact,contract]=testCase.snapshot();
            output=fullfile(artifact,'projects','single_reflection_oa_tof_mass_analyzer','scratch','probe','model.mph');
            testCase.verifyError(@() run_oatof_model(ArtifactRoot=artifact,ContractPath=contract, ...
                OutputModelPath=output,AcceleratorGeometry=struct('invalid',1)), ...
                'oatof:AcceleratorProjection');
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
        function relativeArtifactRootIsRejected(testCase)
            testCase.verifyError(@() oatof_paths('relative/artifacts'),'workspace:ArtifactRoot');
        end
    end
    methods (Access=private)
        function [project,artifact,contract]=snapshot(testCase)
            clear oatof_paths workspace_paths run_oatof_model oatof_build_model_core
            repo=fileparts(fileparts(testCase.activeProject));
            snapshotRoot=fullfile(testCase.folder,'source_snapshot');
            project=fullfile(snapshotRoot,'projects','single_reflection_oa_tof_mass_analyzer');
            mkdir(fullfile(project,'comsol'));
            mkdir(fullfile(snapshotRoot,'common','paths'));
            mkdir(fullfile(snapshotRoot,'common','comsol'));
            copyfile(fullfile(repo,'common','paths','workspace_paths.m'),fullfile(snapshotRoot,'common','paths'));
            copyfile(fullfile(testCase.activeProject,'oatof_paths.m'),project);
            copyfile(fullfile(testCase.activeProject,'load_oatof_contract.m'),project);
            copyfile(fullfile(testCase.activeProject,'comsol','run_oatof_model.m'),fullfile(project,'comsol'));
            copyfile(fullfile(testCase.activeProject,'comsol','oatof_build_model_core.m'),fullfile(project,'comsol'));
            contract=string(fullfile(testCase.folder,'resolved.json'));
            copyfile(fullfile(testCase.activeProject,'config','resolved_geometry.json'),contract);
            artifact=string(fullfile(testCase.folder,'artifacts'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(project));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(project,'comsol')));
        end
    end
end
