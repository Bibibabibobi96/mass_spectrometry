classdef OaTofDetectorArrivalTest < matlab.unittest.TestCase
    properties (TestParameter)
        plateauOffset = struct('zero',0,'positiveRoundoff',1e-12,'negativeRoundoff',-1e-12, ...
            'positiveToleranceEdge',1e-3,'negativeToleranceEdge',-1e-3);
    end

    methods (TestClassSetup)
        function addProjectPath(testCase)
            projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
        end
    end

    methods (Test)
        function confirmsZeroBeforeFrozenSuffixUsingLaterNegativeSample(testCase)
            t=(0:4)';z=[2;1;0;-1e-12;-1e-12];
            result=verifyBatchAndStream(testCase,t,zeros(5,1),zeros(5,1),z,0);
            testCase.verifyEqual(result.event,"crossing");
            testCase.verifyEqual(result.segment_end_index,3);
            testCase.verifyEqual(result.plateau_start_index,4);
            testCase.verifyEqual(result.time_s,2,'AbsTol',eps(2));
        end
        function wholeTrackCoordinateScaleControlsSuffix(testCase)
            t=(0:6)';z=[0;2;1;.01;0;0;0];x=[0;0;1e8;0;1e-7;2e-7;0];
            result=verifyBatchAndStream(testCase,t,x,zeros(7,1),z,0);
            testCase.verifyEqual(result.event,"frozen_on_detector");
            testCase.verifyEqual(result.plateau_start_index,5);
            testCase.verifyEqual(result.segment_end_index,4);
            testCase.verifyEqual(result.time_s,2+1/.99,'AbsTol',8*eps(4));
        end
        function emptyInventoryHasNoInventedTrajectory(testCase)
            result=verifyBatchAndStream(testCase,zeros(0,1),zeros(0,2),zeros(0,2),zeros(0,2),0);
            testCase.verifyEqual(result.event,["no_trajectory";"no_trajectory"]);
            testCase.verifyFalse(any(result.hit));
        end
        function interpolatesDownwardCrossingAfterTurn(testCase)
            t = (0:4).';
            z = [0;2;1;0.5;-0.5];
            result = verifyBatchAndStream(testCase,t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.time_s,3.5,'AbsTol',1e-12);
            testCase.verifyEqual(result.event,"crossing");
        end

        function rejectsOutboundCrossingBeforeTurn(testCase)
            t = (0:4).';
            z = [-0.5;0.5;2;1;0.5];
            result = verifyBatchAndStream(testCase,t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyFalse(result.hit);
            testCase.verifyEqual(result.event,"no_detector_event");
        end

        function acceptsTightFrozenDetectorPlateau(testCase)
            t = (0:5).';
            z = [0;2;1;0.2;0.0005;0.0005];
            result = verifyBatchAndStream(testCase,t,zeros(6,1),zeros(6,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.time_s,3.25,'AbsTol',1e-12);
            testCase.verifyEqual(result.event,"frozen_on_detector");
        end

        function rejectsNearDetectorWithoutFreeze(testCase)
            t = (0:5).';
            z = [0;2;1;0.0005;0.02;0.03];
            result = verifyBatchAndStream(testCase,t,zeros(6,1),zeros(6,1),z,0,1e-3);
            testCase.verifyFalse(result.hit);
            testCase.verifyEqual(result.event,"near_detector_without_freeze");
        end

        function rejectsPlaneCrossingOutsideActiveRadius(testCase)
            t = (0:4).';
            z = [0;2;1;0.5;-0.5];
            x = [0;0;0;2;2];
            result = verifyBatchAndStream(testCase, ...
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
            result = verifyBatchAndStream(testCase, ...
                t,x,y,z,0,1e-3,0.5,0,0,1);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.status,"detector_hit");
            testCase.verifyEqual(result.radius_mm,hypot(0.4,0.4),'AbsTol',1e-12);
        end

        function recoversAnalyticArrivalFromFrozenPlateau(testCase,plateauOffset)
            % z=max(0.55275-0.0275*t_ns,0): arrival is 20.1 ns,
            % independent of the first saved frozen sample at 20.2 ns.
            t = [0;2;20;20.2;20.4]*1e-9;
            z = [0.55275;0.49775;0.00275;plateauOffset;plateauOffset];
            x = [1;1.002;1.02;1.0201;1.0201];
            result = verifyBatchAndStream(testCase,t,x,zeros(5,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"frozen_on_detector");
            testCase.verifyEqual(result.time_s,20.1e-9,'AbsTol',128*eps(20.1e-9));
            testCase.verifyEqual(result.x_mm,1.0201,'AbsTol',128*eps(1.0201));
            testCase.verifyEqual(result.segment_start_index,1);
            testCase.verifyEqual(result.segment_end_index,2);
            testCase.verifyEqual(result.plateau_start_index,4);
        end

        function rejectsStationaryPlaneWithoutApproach(testCase,plateauOffset)
            t = [0;2;20]*1e-9;
            z = repmat(plateauOffset,3,1);
            result = verifyBatchAndStream(testCase,t,zeros(3,1),zeros(3,1),z,0,1e-3);
            testCase.verifyFalse(result.plane_event);
            testCase.verifyFalse(result.hit);
            testCase.verifyTrue(isnan(result.time_s));
            testCase.verifyEqual(result.event,"freeze_without_approach_segment");
        end

        function rejectsFreezeWithOnlyOnePrefreezeSample(testCase)
            t = [0;2;3]*1e-9;
            z = [0.01;0;0];
            result = verifyBatchAndStream(testCase,t,zeros(3,1),zeros(3,1),z,0,1e-3);
            testCase.verifyFalse(result.plane_event);
            testCase.verifyEqual(result.event,"freeze_without_approach_segment");
        end

        function acceptsApproachWindowStartingNearDetector(testCase)
            t = [0;1;2;3]*1e-9;
            z = [0.03;0.01;0;0];
            result = verifyBatchAndStream(testCase,t,zeros(4,1),zeros(4,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"frozen_on_detector");
            testCase.verifyEqual(result.time_s,1.5e-9,'AbsTol',128*eps(1.5e-9));
        end

        function acceptsArrivalAtFirstFrozenSampleBoundary(testCase)
            t = [0;2;20;20.1;20.4]*1e-9;
            z = [0.55275;0.49775;0.00275;0;0];
            result = verifyBatchAndStream(testCase,t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"frozen_on_detector");
            testCase.verifyEqual(result.time_s,20.1e-9,'AbsTol',128*eps(20.1e-9));
        end

        function separatesNearPlaneMotionFromTerminalFreeze(testCase)
            t = [0;2;20;20.08;20.2;20.4]*1e-9;
            z = [0.55275;0.49775;0.00275;0.00055;0;0];
            result = verifyBatchAndStream(testCase,t,zeros(6,1),zeros(6,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"frozen_on_detector");
            testCase.verifyEqual(result.time_s,20.1e-9,'AbsTol',128*eps(20.1e-9));
            testCase.verifyEqual(result.plateau_start_index,5);
            testCase.verifyEqual(result.segment_start_index,1);
            testCase.verifyEqual(result.segment_end_index,2);
        end

        function preservesMovingCrossingInsideNearPlaneTolerance(testCase)
            t = [0;1;2;3]*1e-9;
            z = [0.0008;0.0004;-0.0004;-0.0008];
            result = verifyBatchAndStream(testCase,t,zeros(4,1),zeros(4,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"crossing");
            testCase.verifyEqual(result.time_s,1.5e-9,'AbsTol',128*eps(1.5e-9));
            testCase.verifyTrue(isnan(result.plateau_start_index));
        end

        function doesNotTreatTransverseMotionAsFreeze(testCase)
            t = (0:3).';
            z = [1;0.2;0.0005;0.0005];
            x = [0;0;0.1;0.2];
            result = verifyBatchAndStream(testCase,t,x,zeros(4,1),z,0,1e-3);
            testCase.verifyFalse(result.hit);
            testCase.verifyEqual(result.event,"near_detector_without_freeze");
            testCase.verifyTrue(isnan(result.plateau_start_index));
        end

        function preservesCleanCrossingThroughExactPlaneSample(testCase)
            t = (0:3).';
            z = [2;1;0;-1];
            result = verifyBatchAndStream(testCase,t,zeros(4,1),zeros(4,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"crossing");
            testCase.verifyEqual(result.time_s,2,'AbsTol',eps(2));
        end

        function ignoresTouchAndReturnBeforeLaterCrossing(testCase)
            t = (0:4).';
            z = [2;1;0;1;-1];
            result = verifyBatchAndStream(testCase,t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"crossing");
            testCase.verifyEqual(result.time_s,3.5,'AbsTol',eps(3.5));
            testCase.verifyEqual(result.segment_start_index,4);
            testCase.verifyEqual(result.segment_end_index,5);
        end

        function rejectsUnconfirmedSingleZeroEndpoint(testCase)
            t = (0:2).';
            z = [2;1;0];
            result = verifyBatchAndStream(testCase,t,zeros(3,1),zeros(3,1),z,0,1e-3);
            testCase.verifyFalse(result.plane_event);
            testCase.verifyEqual(result.event,"near_detector_without_freeze");
        end

        function acceptsInterpolatedTransitionAfterExtrapolatedArrival(testCase)
            t = (0:4).';
            z = [1;0.2;0.1;0;0];
            result = verifyBatchAndStream(testCase,t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyTrue(result.plane_event);
            testCase.verifyEqual(result.event,"frozen_on_detector");
            testCase.verifyEqual(result.time_s,1.25,'AbsTol',128*eps(1.25));
            testCase.verifyEqual(result.segment_end_index,2);
            testCase.verifyEqual(result.plateau_start_index,4);
        end

        function rejectsExtrapolationBeyondFirstFrozenSample(testCase)
            t = (0:4).';
            z = [0.4;0.3;0.2;0;0];
            result = verifyBatchAndStream(testCase,t,zeros(5,1),zeros(5,1),z,0,1e-3);
            testCase.verifyFalse(result.plane_event);
            testCase.verifyEqual(result.event,"freeze_extrapolation_outside_interval");
            testCase.verifyEqual(result.segment_end_index,2);
            testCase.verifyEqual(result.plateau_start_index,4);
        end

        function rejectsBackwardExtrapolationFromBelowPlane(testCase)
            t = (0:3).';
            z = [-0.0002;-0.0003;-0.0004;-0.0004];
            result = verifyBatchAndStream(testCase,t,zeros(4,1),zeros(4,1),z,0,1e-3);
            testCase.verifyFalse(result.plane_event);
            testCase.verifyEqual(result.event,"freeze_extrapolation_outside_interval");
            testCase.verifyEqual(result.segment_end_index,2);
        end

        function preservesApproachEstimateAcrossNativeInterpolatedFreeze(testCase)
            % Run 20261021_154058__benchmark__comsol__oatof-cpt-fixed-dp5-rtol11-dense-a,
            % Ion 1, original rows 913,914,915,1004,1005,1006,1007.
            % The expected time is the frozen 0.5 mm approach-line estimate,
            % not an independently measured native wall-event time.
            t = [7.133578814126107e-5;7.133598814126107e-5;7.133618814126107e-5; ...
                7.135398814126107e-5;7.135418814126107e-5;7.135438814126107e-5;7.135458814126107e-5];
            x = [46.40552263391943;46.40578970205885;46.40605677019826; ...
                46.42982583460578;46.429905606522375;46.429909636503794;46.429909636503794];
            y = [0.8276753199873369;0.8276764963585795;0.8276776727298221; ...
                0.8277823697704094;0.8277827211466118;0.8277827388977156;0.8277827388977156];
            z = [0.505109715880681;0.4995781335735877;0.49404655126649444; ...
                0.00173572593631381;8.346998622258854e-5;-1.951563910473908e-15;-1.951563910473908e-15];
            result = verifyBatchAndStream(testCase,t,x,y,z,0,1e-3);
            testCase.verifyTrue(result.hit);
            testCase.verifyEqual(result.event,"frozen_on_detector");
            testCase.verifyEqual(result.time_s,7.135405089820257e-5,'AbsTol',128*eps(7.135405089820257e-5));
            testCase.verifyLessThan(result.time_s,t(5));
            testCase.verifyEqual(result.segment_start_index,1);
            testCase.verifyEqual(result.segment_end_index,2);
            testCase.verifyEqual(result.plateau_start_index,6);
        end

        function preservesParticleColumnsAndActiveAreaBoundary(testCase)
            t = (0:3).';
            z = [2,0,2;1,0,1;-1,0,-1;-2,0,-2];
            x = repmat([1,0,1.01],4,1);
            result = verifyBatchAndStream(testCase,t,x,zeros(4,3),z,0,1e-3,0.5,0,0,1);
            testCase.verifySize(result.time_s,[3,1]);
            testCase.verifyEqual(result.plane_event,[true;false;true]);
            testCase.verifyEqual(result.hit,[true;false;false]);
            testCase.verifyEqual(result.status,["detector_hit";"freeze_without_approach_segment";"outside_active_radius"]);
            testCase.verifyEqual(result.time_s([1,3]),[1.5;1.5],'AbsTol',eps(1.5));
            testCase.verifyTrue(isnan(result.time_s(2)));
        end

        function doesNotBridgeMissingTrajectorySamples(testCase)
            t = (0:3).';
            z = [2;NaN;1;-1];
            result = verifyBatchAndStream(testCase,t,zeros(4,1),zeros(4,1),z,0,1e-3);
            testCase.verifyFalse(result.plane_event);
            testCase.verifyEqual(result.event,"invalid_trajectory");
        end

        function rejectsNonIncreasingTimes(testCase)
            t = [0;1;1];
            testCase.verifyError(@() verifyBatchAndStream(testCase, ...
                t,zeros(3,1),zeros(3,1),[1;0;-1],0), 'oatof:InvalidDetectorTimes');
        end

        function rejectsNonfiniteTimes(testCase)
            t = [0;1;NaN];
            testCase.verifyError(@() verifyBatchAndStream(testCase, ...
                t,zeros(3,1),zeros(3,1),[1;0;-1],0), 'oatof:InvalidDetectorTimes');
        end
    end
end

function result=verifyBatchAndStream(testCase,t,x,y,z,detectorZ,varargin)
result=oatof_extract_detector_arrivals(t,x,y,z,detectorZ,varargin{:});
values={1e-3,.5,0,0,Inf};values(1:numel(varargin))=varargin;
settings=struct('detector_z',detectorZ,'freeze_tolerance_mm',values{1}, ...
 'approach_window_mm',values{2},'detector_x',values{3},'detector_y',values{4},'active_radius_mm',values{5});
for width=[1 2 3 7]
 state=oatof_detector_arrival_reducer('init',[],settings,size(z,2));
 for first=1:width:numel(t)
  selected=max(1,first-1):min(first+width-1,numel(t));
  state=oatof_detector_arrival_reducer('survey',state,t(selected),x(selected,:),y(selected,:),z(selected,:),selected(1));
 end
 state=oatof_detector_arrival_reducer('begin_observation',state);
 for first=1:width:numel(t)
  selected=max(1,first-1):min(first+width-1,numel(t));
  state=oatof_detector_arrival_reducer('observe',state,t(selected),x(selected,:),y(selected,:),z(selected,:),selected(1));
 end
 [~,actual]=oatof_detector_arrival_reducer('finish',state);
 testCase.verifyEqual(actual,result);
end
end
