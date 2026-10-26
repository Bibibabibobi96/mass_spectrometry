classdef OaTofCadExportTest < matlab.unittest.TestCase
    %OATOFCADEXPORTTEST Tests the non-destructive oa-TOF CAD export contract.

    methods (TestClassSetup)
        function addCommonFolderToPath(testCase)
            testsFolder = fileparts(fileparts(mfilename('fullpath')));
            componentRoot = fileparts(testsFolder);
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(componentRoot));
            paths = oatof_paths();
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(paths.cadDir));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(paths.commonSolidWorksDir));
        end
    end

    methods (Test, TestTags = {'Unit'})
        function testManifestContainsOnlyPhysicalFeatures(testCase)
            tags = testCase.physicalFeatures(5,10,5);
            manifest = oatof_cad_export_manifest(flipud(tags));
            % Frozen Formal baseline: 5 OA, 10 stage-1 and 5 stage-2 rings.
            testCase.verifyEqual(manifest.FeatureTag,tags);
            testCase.verifyEqual(height(manifest),25);
            testCase.verifyTrue(any(manifest.FeatureTag == "flighttubewall"));
            testCase.verifyTrue(any(manifest.FeatureTag == "backplate"));
            testCase.verifyFalse(any(contains(manifest.FeatureTag, "vac")));
            testCase.verifyFalse(any(contains(manifest.FeatureTag, "grid")));
        end
        function testActualTwentyRingAcceleratorIsComplete(testCase)
            tags = testCase.physicalFeatures(20,10,5);
            helpers = ["accelring_20O"; "accelring_20H"; "ring1_10O"; ...
                "ring2_5H"; "grid1"; "intermediate2"; "grid2"; "vac"];
            manifest = oatof_cad_export_manifest([flipud(tags);helpers]);
            testCase.verifyEqual(manifest.FeatureTag,tags);
            testCase.verifyEqual(nnz(manifest.Component=="accelerator_ring"),20);
            testCase.verifyEqual(height(manifest),40);
        end
        function testMissingRingFamilyIsRejected(testCase)
            tags = testCase.physicalFeatures(20,10,5);
            tags(startsWith(tags,"accelring_")) = [];
            testCase.verifyError(@() oatof_cad_export_manifest(tags), ...
                'oatofCadExport:MissingRings');
        end
        function testMissingRingIndexIsRejected(testCase)
            tags = testCase.physicalFeatures(20,10,5);
            for missing = ["accelring_11","ring1_4","ring2_2"]
                testCase.verifyError(@() oatof_cad_export_manifest(tags(tags~=missing)), ...
                    'oatofCadExport:RingNumbering');
            end
        end
        function testConflictingRingIndicesAreRejected(testCase)
            tags = testCase.physicalFeatures(20,10,5);
            for invalid = ["accelring_1","accelring_01","ring1_0","ring2_02"]
                testCase.verifyError(@() oatof_cad_export_manifest([tags;invalid]), ...
                    'oatofCadExport:RingNumbering');
            end
        end
        function testMissingFixedPhysicalFeatureIsRejected(testCase)
            tags = testCase.physicalFeatures(20,10,5);
            testCase.verifyError(@() oatof_cad_export_manifest(tags(tags~="detector")), ...
                'oatofCadExport:MissingPhysicalFeature');
        end
        function testExplicitArtifactRootRejectsFormalStepBeforeNativeOpen(testCase)
            [modelPath,artifactRoot,formalCad]=testCase.artifactContext();
            testCase.verifyError(@() export_oatof_cad_step(modelPath,formalCad, ...
                ArtifactRoot=artifactRoot),'oatofPromotion:MissingTransaction');
        end
        function testExplicitArtifactRootRejectsFormalAssemblyBeforeNativeOpen(testCase)
            [modelPath,artifactRoot,formalCad]=testCase.artifactContext();
            testCase.verifyError(@() ms_export_oatof_to_solidworks(modelPath,formalCad,false, ...
                ArtifactRoot=artifactRoot),'oatofPromotion:MissingTransaction');
        end
    end

    methods (Test, TestTags = {'Integration', 'COMSOL'})
        function testExportsFinalModelToTemporaryStep(testCase)
            paths = oatof_paths();
            modelPath = fullfile(paths.comsolFormalDir, ...
                "single_reflection_oa_tof_mass_analyzer__model.mph");
            outputDir = string(tempname);
            mkdir(outputDir);
            testCase.addTeardown(@() rmdir(outputDir, 's'));

            testCase.assertTrue(isfile(modelPath));
            result = export_oatof_cad_step(modelPath, outputDir);

            testCase.verifyTrue(isfile(result.stepPath));
            testCase.verifyTrue(isfile(result.manifestPath));
            testCase.verifyGreaterThan(dir(result.stepPath).bytes, 0);
            testCase.verifyEqual(result.format, 'STEP AP203');
            testCase.verifyEqual(result.unit, 'mm');
        end
    end

    methods (Test, TestTags = {'Integration', 'SolidWorks'})
        function testImportsPartsAndCreatesAssembly(testCase)
            paths = oatof_paths();
            modelPath = fullfile(paths.comsolFormalDir, ...
                "single_reflection_oa_tof_mass_analyzer__model.mph");
            outputDir = string(tempname);
            mkdir(outputDir);
            testCase.addTeardown(@() rmdir(outputDir, 's'));

            testCase.assertTrue(isfile(modelPath));
            exportResult = export_oatof_cad_step(modelPath, outputDir);
            partIndex = find(any(abs(exportResult.partTranslationsMm) > 0, 2), 1, 'first');
            testCase.assertNotEmpty(partIndex, ...
                'The placement test requires a part with a nonzero COMSOL center.');
            partStepPaths = string(exportResult.partStepPaths(partIndex));
            [~, partBases, ~] = fileparts(partStepPaths);
            partPaths = fullfile(outputDir, "parts", partBases + ".sldprt");
            assemblyPath = fullfile(outputDir, "oaTOF_test.sldasm");
            solidWorksResult = import_step_to_solidworks( ...
                partStepPaths, partPaths, false, assemblyPath, ...
                exportResult.partTranslationsMm(partIndex, :));

            testCase.verifyEqual(solidWorksResult.partCount, numel(partPaths));
            testCase.verifyTrue(all(isfile(partPaths)));
            testCase.verifyTrue(isfile(assemblyPath));
            testCase.verifyGreaterThan(dir(assemblyPath).bytes, 0);
            testCase.verifyEqual(solidWorksResult.assembly.componentCount, numel(partPaths));
            testCase.verifyEqual([solidWorksResult.parts.loadErrors], zeros(1, numel(partPaths)));
            testCase.verifyEqual([solidWorksResult.parts.saveErrors], zeros(1, numel(partPaths)));
            actualAssemblyWorldCentersMm = ...
                solidWorksResult.assembly.componentWorldCentersM * 1000;
            testCase.verifyEqual(actualAssemblyWorldCentersMm, ...
                exportResult.partTranslationsMm(partIndex, :), 'AbsTol', 1e-6);
        end
    end
    methods (Access=private)
        function tags=physicalFeatures(~,acceleratorCount,stage1Count,stage2Count)
            tags=["repeller";"accelshield";"accelring_"+string((1:acceleratorCount)'); ...
                "flighttubewall";"ring1_"+string((1:stage1Count)'); ...
                "ring2_"+string((1:stage2Count)');"backplate";"detector"];
        end
        function [modelPath,artifactRoot,formalCad]=artifactContext(testCase)
            fixture=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            artifactRoot=string(fullfile(fixture.Folder,'artifacts'));
            formalCad=string(fullfile(artifactRoot,'projects','single_reflection_oa_tof_mass_analyzer','formal','cad'));
            modelPath=string(fullfile(fixture.Folder,'unopened.mph'));
            fid=fopen(modelPath,'w');
            cleanup=onCleanup(@() fclose(fid));
            fprintf(fid,'Not a native model: protection must reject before opening.');
            clear cleanup
            previous=getenv('OATOF_PROMOTION_TRANSACTION');
            testCase.addTeardown(@() setenv('OATOF_PROMOTION_TRANSACTION',previous));
            setenv('OATOF_PROMOTION_TRANSACTION','');
        end
    end
end
