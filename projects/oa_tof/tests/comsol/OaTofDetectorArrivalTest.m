classdef OaTofDetectorArrivalTest < matlab.unittest.TestCase
    methods (TestClassSetup)
        function addProjectPath(testCase)
            projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
        end
    end

    methods (Test)
        function interpolatesDownwardCrossingAfterTurn(testCase)
            t = (0:4).';
            z = [0;2;1;0.5;-0.5];
            result = oatof_extract_detector_arrivals(t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.time_s,3.5,'AbsTol',1e-12);
            testCase.verifyEqual(result.event,"crossing");
        end

        function rejectsOutboundCrossingBeforeTurn(testCase)
            t = (0:4).';
            z = [-0.5;0.5;2;1;0.5];
            result = oatof_extract_detector_arrivals(t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyFalse(result.hit);
            testCase.verifyEqual(result.event,"no_detector_event");
        end

        function acceptsTightFrozenDetectorPlateau(testCase)
            t = (0:5).';
            z = [0;2;1;0.2;0.0005;0.0005];
            result = oatof_extract_detector_arrivals(t,zeros(6,1),zeros(6,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.time_s,3.25,'AbsTol',1e-12);
            testCase.verifyEqual(result.event,"frozen_on_detector");
        end

        function rejectsNearDetectorWithoutFreeze(testCase)
            t = (0:5).';
            z = [0;2;1;0.0005;0.02;0.03];
            result = oatof_extract_detector_arrivals(t,zeros(6,1),zeros(6,1),z,0,1e-3);
            testCase.verifyFalse(result.hit);
            testCase.verifyEqual(result.event,"near_detector_without_freeze");
        end

        function rejectsPlaneCrossingOutsideActiveRadius(testCase)
            t = (0:4).';
            z = [0;2;1;0.5;-0.5];
            x = [0;0;0;2;2];
            result = oatof_extract_detector_arrivals( ...
                t,x,zeros(5,1),z,0,1e-3,0.5,0,0,1);
            testCase.verifyFalse(result.hit);
            testCase.verifyEqual(result.event,"crossing");
            testCase.verifyEqual(result.status,"outside_active_radius");
            testCase.verifyEqual(result.radius_mm,2,'AbsTol',1e-12);
        end

        function reportsDetectorHitStatusAndRadius(testCase)
            t = (0:4).';
            z = [0;2;1;0.5;-0.5];
            x = [0;0;0;0.3;0.5];
            y = [0;0;0;0.4;0.4];
            result = oatof_extract_detector_arrivals( ...
                t,x,y,z,0,1e-3,0.5,0,0,1);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.status,"detector_hit");
            testCase.verifyEqual(result.radius_mm,hypot(0.4,0.4),'AbsTol',1e-12);
        end
    end
end
