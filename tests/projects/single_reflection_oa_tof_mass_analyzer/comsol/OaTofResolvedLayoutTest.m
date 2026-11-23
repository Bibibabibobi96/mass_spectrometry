classdef OaTofResolvedLayoutTest < matlab.unittest.TestCase
    properties
        contract
        folder
    end
    methods (TestMethodSetup)
        function prepareContract(testCase)
            projectRoot=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(projectRoot));
            fixture=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.folder=fixture.Folder;
            testCase.contract=jsondecode(fileread(fullfile(projectRoot,'config','resolved_geometry.json')));
        end
    end
    methods (Test)
        function baselineIsUnchanged(testCase)
            actual=testCase.load(testCase.contract);
            testCase.verifyEqual(actual,testCase.contract);
            testCase.verifyEqual(actual.geometry_mm.detector_z,0);
            testCase.verifyEqual(actual.coordinate_convention.detector_x,48.8);
        end
        function explicitDetectorIsIndependentOfTheoreticalFocus(testCase)
            value=testCase.contract;
            value.geometry_mm.detector_z=12.5;
            value.coordinate_convention.detector_x=69.01362184380704;
            actual=testCase.load(value);
            testCase.verifyEqual(actual.geometry_mm.detector_z,12.5);
            testCase.verifyEqual(actual.coordinate_convention.detector_x,69.01362184380704);
            testCase.verifyEqual(actual.geometry_mm.accelerator_focus_z,value.geometry_mm.accelerator_focus_z);
        end
        function invalidDetectorZIsRejected(testCase)
            value=testCase.contract; value.geometry_mm.detector_z=NaN;
            testCase.verifyError(@() testCase.load(value),'oatof:DetectorPosition');
        end
        function invalidDetectorXIsRejected(testCase)
            value=testCase.contract; value.coordinate_convention.detector_x=Inf;
            testCase.verifyError(@() testCase.load(value),'oatof:DetectorPosition');
        end
        function inconsistentFocusStillFails(testCase)
            value=testCase.contract; value.geometry_mm.accelerator_focus_z=1;
            testCase.verifyError(@() testCase.load(value),'oatof:ResolvedDerivation');
        end
    end
    methods (Access=private)
        function actual=load(testCase,value)
            path=fullfile(testCase.folder,'resolved.json');
            fid=fopen(path,'w');
            cleanup=onCleanup(@() fclose(fid));
            fprintf(fid,'%s',jsonencode(value));
            clear cleanup
            actual=load_oatof_contract(path);
        end
    end
end
