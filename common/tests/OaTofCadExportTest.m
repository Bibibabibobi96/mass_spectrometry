classdef OaTofCadExportTest < matlab.unittest.TestCase
    %OATOFCADEXPORTTEST Tests the non-destructive oa-TOF CAD export contract.

    methods (TestClassSetup)
        function addCommonFolderToPath(testCase)
            commonFolder = fileparts(fileparts(mfilename('fullpath')));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(commonFolder));
        end
    end

    methods (Test, TestTags = {'Unit'})
        function testManifestContainsOnlyPhysicalFeatures(testCase)
            manifest = oatof_cad_export_manifest();
            expectedCount = 20;

            testCase.verifyEqual(height(manifest), expectedCount);
            testCase.verifyTrue(any(manifest.FeatureTag == "flighttubewall"));
            testCase.verifyTrue(any(manifest.FeatureTag == "backplate"));
            testCase.verifyFalse(any(contains(manifest.FeatureTag, "vac")));
            testCase.verifyFalse(any(contains(manifest.FeatureTag, "grid")));
        end
    end

    methods (Test, TestTags = {'Integration', 'COMSOL'})
        function testExportsFinalModelToTemporaryStep(testCase)
            modelPath = "C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\project_oaTOF\MS_oaTOF_TwoStageRingStackReflectron_Final.mph";
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
            modelPath = "C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\project_oaTOF\MS_oaTOF_TwoStageRingStackReflectron_Final.mph";
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
            actualTranslationsMm = reshape([solidWorksResult.parts.translationMm], 3, []).';
            testCase.verifyEqual(actualTranslationsMm, ...
                exportResult.partTranslationsMm(partIndex, :), 'AbsTol', 1e-9);
            actualAssemblyTranslationsMm = ...
                solidWorksResult.assembly.componentTranslationsM * 1000;
            testCase.verifyEqual(actualAssemblyTranslationsMm, ...
                exportResult.partTranslationsMm(partIndex, :), 'AbsTol', 1e-6);
        end
    end
end
