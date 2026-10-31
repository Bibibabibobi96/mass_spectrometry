classdef OaTofModelTimingReportTest < matlab.unittest.TestCase
    properties (TestParameter)
        population=struct('normal',100,'large',5000)
    end
    methods (TestClassSetup)
        function productionPath(testCase)
            projectRoot=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
        end
    end
    methods (Test)
        function reportsPopulationWithoutChangingInputs(testCase,population)
            phases=struct('extraction',1,'plot_view',2,'matlab_plot',3, ...
                'result_nodes',4,'plot_count',50);
            before=phases;
            start=tic;
            output=evalc('oatof_report_model_timing("Fixture",population,ones(1,7),phases,1,1,start);');
            testCase.verifyTrue(contains(output,sprintf('Fixture, N=%d',population)));
            testCase.verifyTrue(contains(output,'same-path GUI-node update'));
            testCase.verifyTrue(contains(output,'SUM OF PHASES'));
            testCase.verifyEqual(phases,before);
        end
    end
end
