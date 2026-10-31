classdef RfInterfaceGuiParityTest < matlab.unittest.TestCase
 properties (TestParameter)
  bindingField=struct('filename','Filename','positionColumn','icolp', ...
   'velocityMode','VelocitySpecification','velocitySource','InitialVelocity','velocityColumn','icolv','releaseClock','rt');
  parityFault=struct('position','position','velocity','velocity','id','id','active','active','terminal','terminal','outcome','outcome');
 end
 methods (TestClassSetup)
  function actualGuiFunctions(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(root,'comsol')));
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   text=fileread(fullfile(root,'workflows','interface_readiness','comsol','verify_nocollision_comsol.m'));
   names={'validateGuiReleaseBinding','guiAllowedReleaseFilenames','guiNativeBirthObservation','guiCensusAndTerminal','compareGuiStoredObservations'};
   for index=1:numel(names)
    name=names{index};first=regexp(text,['(?m)^function[^\n]*=' name '\(']);assert(isscalar(first));
    writeGuiTestFile(fullfile(folder.Folder,[name '.m']),text(first:end));
   end
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(folder.Folder));
   testCase.addTeardown(@clearGuiTestFunctions);
  end
 end
 methods (Test)
  function frozenHeaderSelectsItsOwnExtractionAndClassifier(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   frozenProject=fullfile(folder.Folder,'project');mkdir(fullfile(frozenProject,'comsol'));
   taskDirectory=fullfile(frozenProject,'workflows','interface_readiness','comsol');mkdir(taskDirectory);
   copyfile(fullfile(root,'comsol','extract_rf_particle_records.m'),fullfile(frozenProject,'comsol'));
   copyfile(fullfile(root,'comsol','visit_rf_particle_windows.m'),fullfile(frozenProject,'comsol'));
   copyfile(fullfile(root,'comsol','classify_finite_particle_terminal.m'),fullfile(frozenProject,'comsol'));
   text=fileread(fullfile(root,'workflows','interface_readiness','comsol','verify_nocollision_comsol.m'));
   stop=strfind(text,'runConfigPath=getenv(');testCase.assertEqual(numel(stop),1);
   prefix=fullfile(taskDirectory,'frozen_header.m');writeGuiTestFile(prefix,text(1:stop-1));
   originalPath=path;testCase.addTeardown(@()path(originalPath));
   run(prefix);
   testCase.verifyEqual(which('extract_rf_particle_records'),fullfile(frozenProject,'comsol','extract_rf_particle_records.m'));
   testCase.verifyEqual(which('visit_rf_particle_windows'),fullfile(frozenProject,'comsol','visit_rf_particle_windows.m'));
   testCase.verifyEqual(which('classify_finite_particle_terminal'),fullfile(frozenProject,'comsol','classify_finite_particle_terminal.m'));
  end
  function fullSourceBindingKeepsSparseOriginalIdsAndOrder(testCase)
   [feature,entry,rows,metadata,data,paths]=bindingFixture();
   actual=validateGuiReleaseBinding(feature,entry,rows,metadata,data,paths);
   testCase.verifyTrue(actual.source_binding_verified);
   testCase.verifyEqual(actual.particle_ids,[9;41]);
   testCase.verifyEqual(actual.source_rows,[2 1]);
  end
  function actualGetterMismatchRejects(testCase,bindingField)
   [feature,entry,rows,metadata,data,paths]=bindingFixture(bindingField);
   testCase.verifyError(@()validateGuiReleaseBinding(feature,entry,rows,metadata,data,paths),'rfquad:GuiSourceBinding');
  end
  function changedSixDimensionalSourceRejects(testCase)
   [feature,entry,rows,metadata,data,paths]=bindingFixture();data(1,6)=data(1,6)+1e-8;
   testCase.verifyError(@()validateGuiReleaseBinding(feature,entry,rows,metadata,data,paths),'rfquad:GuiSourceBinding');
  end
  function oldAliasRequiresItsOriginalOwnerCompletion(testCase)
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   [config,runRoot,relative,oldPath]=aliasFixture(folder.Folder,false);
   actual=guiAllowedReleaseFilenames(config,runRoot,relative);
   testCase.verifyTrue(any(strcmp(actual,oldPath)));
  end
  function anotherOwnerAliasIsNotAccepted(testCase)
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   [config,runRoot,relative]=aliasFixture(folder.Folder,true);
   testCase.verifyError(@()guiAllowedReleaseFilenames(config,runRoot,relative),'rfquad:GuiSourceBinding');
  end
  function missingExactBirthIsUnavailableNotFirstFiniteEcho(testCase)
   [saved,metadata,order]=observationFixture();
   actual=guiNativeBirthObservation(saved,metadata,order);
   testCase.verifyTrue(actual.native_birth_echo_unavailable_saved_observation);
   testCase.verifyEqual(actual.unavailable_particle_ids,[9 41]);
   testCase.verifyEmpty(actual.verified_exact_stored_birth_particle_ids);
  end
  function availableExactBirthStillUsesOriginalTransportBudget(testCase)
   [saved,metadata,order]=observationFixture();metadata.source_birth_s(2)=1;
   metadata.source_initial_position_mm(2,:)=saved.records{1}.position_mm(1,:);
   metadata.source_initial_velocity_m_s(2,:)=saved.records{1}.velocity_m_s(1,:)+2e-12;
   testCase.verifyError(@()guiNativeBirthObservation(saved,metadata,order),'rfquad:GuiNativeBirth');
  end
  function commonStoredStatesPreserveUnknownTerminalFacts(testCase)
   [saved,~,~,interface,g]=observationFixture();
   [~,~,outcomes]=guiCensusAndTerminal(saved,interface,g);
   actual=compareGuiStoredObservations(saved,saved,outcomes,outcomes);
   testCase.verifyEqual(actual.status,'PASS');
   testCase.verifyEqual(actual.scientific_result,'NOT_EVALUATED');
   testCase.verifyEqual(actual.particle_ids,[9 41]);
   testCase.verifyEqual(actual.compared_finite_state_count,5);
   testCase.verifyEqual(actual.terminal_outcomes{1}.status,'unknown');
   testCase.verifyEqual(actual.terminal_outcomes{2}.reason,'ended_without_loss_evidence');
  end
  function changedStateIdsMasksOrTerminalFactsReject(testCase,parityFault)
   [saved,~,~,interface,g]=observationFixture();[~,~,outcomes]=guiCensusAndTerminal(saved,interface,g);
   [current,changed,id]=parityMutation(saved,outcomes,parityFault);
   testCase.verifyError(@()compareGuiStoredObservations(saved,current,outcomes,changed),id);
  end
  function unchangedToleranceAcceptsSubBudgetDifference(testCase)
   [saved,~,~,interface,g]=observationFixture();[~,~,outcomes]=guiCensusAndTerminal(saved,interface,g);
   current=saved;current.records{1}.position_mm(1,1)=current.records{1}.position_mm(1,1)+0.5e-12;
   actual=compareGuiStoredObservations(saved,current,outcomes,outcomes);
   testCase.verifyGreaterThan(actual.maximum_position_error_mm,0);
   testCase.verifyEqual(actual.transport_tolerance_mm_and_m_s,1e-12);
  end
  function noSharedFiniteStateForOriginalParticleRejects(testCase)
   [saved,~,~,interface,g]=observationFixture();[~,~,outcomes]=guiCensusAndTerminal(saved,interface,g);
   current=saved;current.time_s=[0;0.5;3];current.records{2}.time_s=0.5;
   current.records{2}.position_mm=current.records{2}.position_mm(1,:);
   current.records{2}.velocity_m_s=current.records{2}.velocity_m_s(1,:);
   testCase.verifyError(@()compareGuiStoredObservations(saved,current,outcomes,outcomes),'rfquad:GuiParityObservation');
  end
 end
end

function [feature,entry,rows,metadata,data,paths]=bindingFixture(fault)
if nargin<1,fault='';end
values=struct('Filename',fullfile(tempdir,'owned_run','runtime','particle_001.txt'), ...
 'icolp','0','VelocitySpecification','SpecifyVelocity','InitialVelocity','FromFile','icolv','3','rt',sprintf('%.17g[s]',0.5));
paths={values.Filename};
if strcmp(fault,'Filename'),values.Filename=fullfile(tempdir,'wrong_run','runtime','particle_001.txt');
elseif ~isempty(fault),values.(fault)='different';end
feature=struct('getString',@(name)values.(name));rows=[2;1];
entry=struct('source_rows',rows,'birth_s',0.5);
metadata=struct('source_ids',[41;9],'source_birth_s',[0.5;0.5], ...
 'source_initial_position_mm',[1 2 3;4 5 6],'source_initial_velocity_m_s',[7 8 9;10 11 12]);
data=[metadata.source_initial_position_mm(rows,:) metadata.source_initial_velocity_m_s(rows,:)];
end

function [config,runRoot,relative,oldPath]=aliasFixture(folder,badTarget)
config=struct('paths',struct('artifact_root',folder),'project','rf_multipole_ion_optics','run_id','fixture');
persistentRun=fullfile(folder,'projects',config.project,'runs',config.run_id);mkdir(fullfile(persistentRun,'results'));
runRoot=persistentRun;relative='runtime/particle_001.txt';alias=fullfile(folder,'execution','owned');oldPath=fullfile(alias,relative);
target=persistentRun;if badTarget,target=fullfile(folder,'another_run');end
receipt=struct('role','run_artifact_workflow_completion','run_id','fixture', ...
 'execution_alias',struct('path',alias,'target_directory',target));
writeGuiTestFile(fullfile(persistentRun,'results','execution_completion.json'),jsonencode(receipt));
end

function [saved,metadata,order,interface,g]=observationFixture()
order=[2;1];metadata=struct('source_ids',[41;9],'source_birth_s',[0.5;0.5], ...
 'source_initial_position_mm',[10 20 30;40 50 60],'source_initial_velocity_m_s',[7 8 9;10 11 12]);
a=struct('particle_id',9,'time_s',[1;2;3],'position_mm',[0 0 0;1 0 1;2 0 2], ...
 'velocity_m_s',ones(3,3),'terminal_observation',terminalObservation(3,true));
b=struct('particle_id',41,'time_s',[1;2],'position_mm',[0 0 0;1 0 1], ...
 'velocity_m_s',ones(2,3),'terminal_observation',terminalObservation(2,false));
saved=struct('time_s',[0;1;2;3],'records',{{a,b}});
interface=struct('planes',struct('census',struct('z_mm',10)));
g=struct('enclosure',struct('physical_detector_radius_mm',10,'outer_half_width_mm',20));
end

function value=terminalObservation(last,atEnd)
value=struct('solution_end_index',4,'solution_end_time_s',3,'last_finite_solution_index',last+1, ...
 'last_finite_time_s',last,'finite_at_solution_end',atEnd,'finite_track_ended',~atEnd,'native_termination_cause','not_observed');
end

function [current,changed,id]=parityMutation(saved,outcomes,kind)
current=saved;changed=outcomes;
switch kind
 case 'position',current.records{1}.position_mm(1,1)=2e-12;id='rfquad:GuiParityState';
 case 'velocity',current.records{1}.velocity_m_s(1,1)=1+2e-12;id='rfquad:GuiParityState';
 case 'id',current.records{1}.particle_id=99;id='rfquad:GuiParityIds';
 case 'active',current.records{1}.time_s(2)=[];id='rfquad:GuiParityActive';
 case 'terminal',current.records{1}.terminal_observation.finite_track_ended=true;id='rfquad:GuiParityTerminal';
 case 'outcome',changed{2}.status='lost';changed{2}.reason='electrode';id='rfquad:GuiParityTerminal';
end
end

function writeGuiTestFile(path,text)
fid=fopen(path,'w','n','UTF-8');assert(fid>=0);cleanup=onCleanup(@()fclose(fid));fprintf(fid,'%s',text);
end
function clearGuiTestFunctions()
clear validateGuiReleaseBinding guiAllowedReleaseFilenames guiNativeBirthObservation guiCensusAndTerminal compareGuiStoredObservations
end
