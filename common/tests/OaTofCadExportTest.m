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
        function testImportsStepToNativePart(testCase)
            modelPath = "C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\project_oaTOF\MS_oaTOF_TwoStageRingStackReflectron_Final.mph";
            outputDir = string(tempname);
            mkdir(outputDir);
            testCase.addTeardown(@() rmdir(outputDir, 's'));

            testCase.assertTrue(isfile(modelPath));
            exportResult = export_oatof_cad_step(modelPath, outputDir);
            solidWorksResult = import_step_to_solidworks(exportResult.stepPath, ...
                fullfile(outputDir, "oaTOF_test.sldprt"), false);

            testCase.verifyTrue(isfile(solidWorksResult.sldprtPath));
            testCase.verifyGreaterThan(dir(solidWorksResult.sldprtPath).bytes, 0);
            testCase.verifyGreaterThanOrEqual(solidWorksResult.importDiagnosisCode, -1);
        end
    end
end
