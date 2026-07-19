classdef OaTofFieldIdealizationTest < matlab.unittest.TestCase
    methods (TestClassSetup)
        function addProjectPath(testCase)
            projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot, 'comsol')));
        end
    end

    methods (Test)
        function realFieldHasEmptyMask(testCase)
            actual = oatof_parse_field_idealization("real");
            testCase.verifyFalse(any(actual.mask, 'all'));
            testCase.verifyEqual(actual.canonical, "real");
        end

        function legacyRegionRemainsCompatible(testCase)
            actual = oatof_parse_field_idealization("ideal_reflectron");
            expected = false(4, 3);
            expected(3:4, :) = true;
            testCase.verifyEqual(actual.mask, expected);
        end

        function arbitraryCombinationIsComposable(testCase)
            actual = oatof_parse_field_idealization( ...
                "ideal:accelerator.ez+stage2.ex+stage2.ey");
            expected = false(4, 3);
            expected(1, 3) = true;
            expected(4, 1:2) = true;
            testCase.verifyEqual(actual.mask, expected);
            testCase.verifyEqual(actual.canonical, ...
                "ideal:accel.ez+stage2.ex+stage2.ey");
        end

        function wildcardsExpand(testCase)
            actual = oatof_parse_field_idealization("ideal:all.ez+stage1.all");
            expected = false(4, 3);
            expected(:, 3) = true;
            expected(3, :) = true;
            testCase.verifyEqual(actual.mask, expected);
        end

        function invalidAtomIsRejected(testCase)
            testCase.verifyError(@() oatof_parse_field_idealization("ideal:stage2"), ...
                'oaTOF:InvalidFieldIdealization');
        end
    end
end
