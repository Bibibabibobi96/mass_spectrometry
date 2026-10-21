classdef OaTofSolverPolicyTest < matlab.unittest.TestCase
    properties (TestParameter)
        policyCase = struct( ...
            'generalizedAlpha',struct('ode','implicit','method','genalpha','key','tstepsgenalpha'), ...
            'bdf',struct('ode','implicit','method','bdf','key','tstepsbdf'), ...
            'dormandPrince',struct('ode','explicit','method','genalpha','key','tstepsdopri5'))
        stepMode = {'free','intermediate','strict'}
    end
    methods (TestClassSetup)
        function addProjectPaths(testCase)
            testDir = fileparts(mfilename('fullpath'));
            projectRoot = fileparts(fileparts(testDir));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(testDir,'test_support')));
        end
    end
    methods (Test)
        function writesAndVerifiesOnlyActiveProperty(testCase,policyCase,stepMode)
            solver = FakeOaTofTimeSolver(policyCase.ode,policyCase.method);
            before = solver.values;
            runtime = struct('solver_steps',stepMode,'times_to_store','tlist');
            actual = oatof_cpt_solver_policy(solver,runtime,'apply');
            expected = before;
            expected.(policyCase.key) = stepMode;
            expected.tout = 'tlist';
            testCase.verifyEqual(solver.values,expected);
            testCase.verifyEqual(solver.writes,[string(policyCase.key);"tout"]);
            testCase.verifyEqual(actual.step_property,policyCase.key);
            verified = oatof_cpt_solver_policy(solver,runtime,'verify');
            testCase.verifyEqual(verified,actual);
            testCase.verifyEqual(numel(solver.writes),2);
        end
        function verifyRejectsInactiveBdfFalsePositive(testCase)
            solver = FakeOaTofTimeSolver('implicit','genalpha');
            solver.values.tstepsbdf = 'free';
            solver.values.tout = 'tlist';
            runtime = struct('solver_steps','free','times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'verify'), ...
                'oatof:SolverPolicyReadback');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsUnsupportedAlgorithmBeforeWriting(testCase)
            solver = FakeOaTofTimeSolver('implicit','init');
            runtime = struct('solver_steps','free','times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:UnsupportedTimeSolver');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsUnsupportedExplicitMethodBeforeWriting(testCase)
            solver = FakeOaTofTimeSolver('explicit','genalpha');
            solver.values.timemethodexp = 'verlet';
            runtime = struct('solver_steps','free','times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:UnsupportedTimeSolver');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsMissingPolicyBeforeWriting(testCase)
            solver = FakeOaTofTimeSolver('implicit','genalpha');
            runtime = struct('times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:SolverPolicy');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsManualWithoutTimeStepContract(testCase)
            solver = FakeOaTofTimeSolver('implicit','genalpha');
            runtime = struct('solver_steps','manual','times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:SolverPolicy');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsUnknownOdeSolverBeforeWriting(testCase)
            solver = FakeOaTofTimeSolver('unknown','genalpha');
            runtime = struct('solver_steps','free','times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:UnsupportedTimeSolver');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsUnsupportedRungeKuttaBeforeWriting(testCase)
            solver = FakeOaTofTimeSolver('explicit','genalpha');
            solver.values.rkmethod = 'unknown';
            runtime = struct('solver_steps','free','times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:UnsupportedTimeSolver');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsInvalidStorageBeforeWriting(testCase)
            solver = FakeOaTofTimeSolver('implicit','genalpha');
            runtime = struct('solver_steps','free','times_to_store','unknown');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:SolverPolicy');
            testCase.verifyEmpty(solver.writes);
        end
        function rejectsASetterThatDidNotChangeNativeValue(testCase)
            solver = FakeOaTofTimeSolver('implicit','genalpha');
            solver.ignoreWrites = true;
            runtime = struct('solver_steps','free','times_to_store','tlist');
            testCase.verifyError(@() oatof_cpt_solver_policy(solver,runtime,'apply'), ...
                'oatof:SolverPolicyReadback');
            testCase.verifyEqual(solver.values.tstepsgenalpha,'strict');
        end
    end
end
