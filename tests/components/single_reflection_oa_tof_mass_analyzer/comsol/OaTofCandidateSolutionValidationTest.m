classdef OaTofCandidateSolutionValidationTest < matlab.unittest.TestCase
    properties (TestParameter)
        rejection = {'population','detections','classification','rings','dataset', ...
            'missing_cpt_dt_fine','missing_cpt_dt_drift', ...
            'missing_cpt_t_refl_start','missing_cpt_t_refl_end', ...
            'missing_cpt_t_detector_start','missing_cpt_t_detector_end'};
    end
    methods (TestClassSetup)
        function sourcePath(testCase)
            project=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(project,'comsol')));
        end
    end
    methods (Test)
        function completeOriginalCandidateGatesAccept(testCase)
            [model,result,contract]=candidateValidationFixture('valid');
            actual=oatof_validate_candidate_solution(model,result,contract);
            testCase.verifyEqual(actual.stage1_rings,10);
            testCase.verifyEqual(actual.stage2_rings,5);
            testCase.verifyEqual(actual.time_window_token_count,6);
        end
        function originalScientificRejectionsRemain(testCase,rejection)
            [model,result,contract]=candidateValidationFixture(rejection);
            actual=captureValidationFailure(model,result,contract);
            testCase.verifyEqual(actual.identifier,'');
            testCase.verifySubstring(actual.message,expectedValidationMessage(rejection));
        end
    end
end

function [model,result,contract]=candidateValidationFixture(rejection)
result=struct('nP',100,'nDet',100,'detectorStatus',repmat("detector_hit",1,100));
contract=struct('rings',struct('stage1_count',10,'stage2_count',5));
stage1=10;timeList='cpt_dt_fine cpt_dt_drift cpt_t_refl_start cpt_t_refl_end cpt_t_detector_start cpt_t_detector_end';
solution='sol2';
switch rejection
    case 'population'
        result.nP=99;
    case 'detections'
        result.nDet=99;
    case 'classification'
        result.detectorStatus(17)="not_observed";
    case 'rings'
        stage1=11;
    case 'dataset'
        solution='sol1';
end
if startsWith(rejection,'missing_')
    timeList=strjoin(setdiff(strsplit(timeList),{extractAfter(rejection,'missing_')},'stable'),' ');
end
model=struct('param',struct('evaluate',@(name)fixtureRing(name,stage1)), ...
    'study',@(tag)struct('feature',@(feature)struct('getString',@(property)timeList)), ...
    'result',struct('dataset',@(tag)struct('getString',@(property)solution)));
end

function value=fixtureRing(name,stage1)
switch name
    case 'N_rings1'
        value=stage1;
    case 'N_rings2'
        value=5;
    otherwise
        error('oatof:FixtureUnexpectedParameter','Unexpected parameter %s.',name);
end
end

function actual=captureValidationFailure(model,result,contract)
try
    oatof_validate_candidate_solution(model,result,contract);
catch actual
    return
end
error('oatof:FixtureExpectedRejection','The actual Candidate consumer accepted an invalid fixture.');
end

function message=expectedValidationMessage(rejection)
switch rejection
    case {'population','detections'}
        message='Candidate detected only';
    case 'classification'
        message='Detector extraction did not classify each particle exactly once.';
    case 'rings'
        message='Parameterized ring counts differ from the candidate contract.';
    case 'dataset'
        message='Particle dataset is not linked uniquely to sol2.';
    otherwise
        message='Segmented particle time window is incomplete:';
end
end
