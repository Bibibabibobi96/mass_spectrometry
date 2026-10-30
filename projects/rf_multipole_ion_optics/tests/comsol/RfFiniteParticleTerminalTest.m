classdef RfFiniteParticleTerminalTest < matlab.unittest.TestCase
 properties (TestParameter)
  ending=struct('finalFinite',true,'endedBeforeFinal',false);
  rejection=struct('none','','rod','usable_radius_exceeded','port','exit_port_envelope_loss');
  exportCase=struct('windowEnd','windowEnd','rejectedWindowEnd','rejected','endedUnknown','ended','accepted','accepted');
 end
 methods (TestClassSetup)
  function projectHelper(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(root,'comsol')));
  end
  function actualPureExportFunctions(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   materializeActualExportFunctions(fullfile(root,'comsol','solve_finite_3d_transport.m'),folder.Folder);
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(folder.Folder));
   testCase.addTeardown(@clearExportFunctions);
  end
 end
 methods (Test)
  function unknownCauseNeverBecomesElectrodeLoss(testCase,ending)
   record=recordFixture(ending);
   result=classify_finite_particle_terminal(record,false);
   expected=reasonFixture(ending);
   testCase.verifyEqual(result.status,'unknown');
   testCase.verifyEqual(result.reason,expected);
   testCase.verifyEqual(result.acceptance_status,'unresolved');
  end
  function acceptanceRejectionAndLifecycleRemainIndependent(testCase,ending,rejection)
   result=classify_finite_particle_terminal(recordFixture(ending),false,rejection);
   [expectedStatus,expectedReason]=acceptanceFixture(rejection);
   testCase.verifyEqual(result.status,'unknown');
   testCase.verifyEqual(result.reason,reasonFixture(ending));
   testCase.verifyEqual(result.acceptance_status,expectedStatus);
   testCase.verifyEqual(result.acceptance_reason,expectedReason);
  end
  function acceptedCensusPreservesTransmittedResult(testCase,ending)
   result=classify_finite_particle_terminal(recordFixture(ending),true);
   testCase.verifyEqual(result.status,'transmitted');
   testCase.verifyEqual(result.reason,'acceptance_surface');
   testCase.verifyEqual(result.acceptance_status,'accepted');
  end
  function syntheticRecordsCrossActualEventAndCanonicalCsvExports(testCase,exportCase)
   [record,source,expected]=exportFixture(exportCase);
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   path=fullfile(folder.Folder,'state.csv');
   [events,~]=analyze_particle_case({record},source,'fixture',7,1,1,0,5,0,6,1,1,1);
   write_canonical_particle_state({record},source,path,5,6,7,1,1,1,1,0);
   state=readtable(path,'TextType','string');terminal=state(state.event=="terminal",:);
   testCase.verifyEqual(string(events.status),string(expected.status));
   testCase.verifyEqual(string(events.terminal_reason),string(expected.eventReason));
   testCase.verifyEqual(terminal.status,string(expected.status));
   testCase.verifyEqual(terminal.terminal_reason,string(expected.canonicalReason));
   testCase.verifyEqual(terminal.acceptance_status,string(expected.acceptance));
   testCase.verifyEqual(string(events.acceptance_status),string(expected.acceptance));
  end
  function contradictoryAcceptedRejectionFails(testCase)
   testCase.verifyError(@()classify_finite_particle_terminal(recordFixture(true),true,'usable_radius_exceeded'), ...
    'rf:TerminalAcceptance');
  end
  function legacyMissingObservationCannotInventCause(testCase)
   testCase.verifyError(@()classify_finite_particle_terminal(struct(),false),'rf:TerminalObservation');
  end
 end
end
function record=recordFixture(finalFinite)
lastIndex=4;lastTime=4;
if finalFinite,lastIndex=6;lastTime=6;end
record=struct('terminal_observation',struct('solution_end_index',6,'solution_end_time_s',6, ...
 'last_finite_solution_index',lastIndex,'last_finite_time_s',lastTime, ...
 'finite_at_solution_end',logical(finalFinite),'finite_track_ended',logical(~finalFinite), ...
 'native_termination_cause','not_observed'));
end
function reason=reasonFixture(finalFinite)
reason='ended_without_loss_evidence';
if finalFinite,reason='time_window_end';end
end
function [status,reason]=acceptanceFixture(rejection)
status='unresolved';reason='none';
if ~isempty(rejection),status='rejected';reason=rejection;end
end

function materializeActualExportFunctions(sourcePath,folder)
% A thin ABI fixture: copy exact pure production exporter bodies, not their logic.
text=fileread(sourcePath);starts=regexp(text,'(?m)^function[^\r\n]*','start');
names={'analyze_particle_case','write_canonical_particle_state','canonical_state_row','interpolate_particle_plane'};
for index=1:numel(names)
 matched=false;
 for section=1:numel(starts)
  finish=numel(text);if section<numel(starts),finish=starts(section+1)-1;end
  body=text(starts(section):finish);firstLine=strtok(body,newline);
  if ~isempty(regexp(firstLine,['\<' names{index} '\s*\('],'once'))
   fid=fopen(fullfile(folder,[names{index} '.m']),'w');assert(fid>=0);
   cleanup=onCleanup(@()fclose(fid));fprintf(fid,'%s',body);clear cleanup
   matched=true;break
  end
 end
 assert(matched,'Actual production exporter is missing: %s',names{index});
end
clearExportFunctions;
end
function clearExportFunctions
clear analyze_particle_case write_canonical_particle_state canonical_state_row interpolate_particle_plane
end
function [record,source,expected]=exportFixture(kind)
record=recordFixture(true);record.time_s=[0;1;2];record.solution_index=[1;2;3];
record.trajectory_solution_index=[1;2;3];record.position_mm=[0 0 0;0 0 1;0 0 2];
record.velocity_m_s=repmat([0 0 1],3,1);
record.terminal_observation.solution_end_index=3;record.terminal_observation.solution_end_time_s=2;
record.terminal_observation.last_finite_solution_index=3;record.terminal_observation.last_finite_time_s=2;
source=table(17,0,0,0,0,0,0,1,'VariableNames', ...
 {'particle_id','birth_time_s','x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s'});
expected=struct('status','unknown','eventReason','time_window_end', ...
 'canonicalReason','time_window_end','acceptance','unresolved');
if strcmp(kind,'rejected')
 record.position_mm(:,1)=[0;2;2];expected.acceptance='rejected';
elseif strcmp(kind,'ended')
 record.terminal_observation.solution_end_index=5;record.terminal_observation.solution_end_time_s=4;
 record.terminal_observation.finite_at_solution_end=false;record.terminal_observation.finite_track_ended=true;
 expected.eventReason='ended_without_loss_evidence';expected.canonicalReason='ended_without_loss_evidence';
elseif strcmp(kind,'accepted')
 record.position_mm(:,3)=[0;5;8];expected.status='transmitted';
 expected.eventReason='near_interface_census_plane';expected.canonicalReason='acceptance_surface';
 expected.acceptance='accepted';
end
end
