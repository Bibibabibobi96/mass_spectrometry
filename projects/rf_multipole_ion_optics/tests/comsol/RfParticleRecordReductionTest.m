classdef RfParticleRecordReductionTest < matlab.unittest.TestCase
 properties (TestParameter)
  activeCase=struct('partialPosition','d2','partialVelocity','d5', ...
   'missingNativeId','d1','contradictoryLifecycle','lifecycle');
  gapCase=struct('withinWindow',[0;1;NaN;3;4;5], ...
   'acrossWindows',[0;NaN;NaN;NaN;4;5]);
  readerCase=struct('emptyParticle','empty','unknownShape','shape');
  identityCase=struct('changedOverlap','overlap','duplicateNativeId','duplicate');
 end
 methods (TestClassSetup)
  function projectHelper(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(root,'comsol')));
  end
 end
 methods (TestMethodSetup)
  function isolatedNativeReader(testCase)
   temp=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   writeStub(fullfile(temp.Folder,'mphsolinfo.m'),sprintf([ ...
    'function info=mphsolinfo(varargin)\n' ...
    'data=getappdata(0,''rf_reducer_unit_data'');info=struct(''soltype'',''Time'',''solvals'',data.time);\nend\n']));
   writeStub(fullfile(temp.Folder,'mphparticle.m'),sprintf([ ...
    'function result=mphparticle(~,varargin)\n' ...
    'data=getappdata(0,''rf_reducer_unit_data'');\n' ...
    'calls=getappdata(0,''rf_reducer_unit_calls'');if isempty(calls),calls=0;end;setappdata(0,''rf_reducer_unit_calls'',calls+1);\n' ...
    'expr=varargin{find(strcmp(varargin,''expr''))+1};setappdata(0,''rf_reducer_unit_expr'',expr);\n' ...
    'times=varargin{find(strcmp(varargin,''t''))+1};[found,rows]=ismember(times,data.time);assert(all(found));\n' ...
    'assert(strcmp(varargin{find(strcmp(varargin,''dataonly''))+1},''on''));\n' ...
    'result=struct;for k=1:7,name=sprintf(''d%%d'',k);result.(name)=data.(name)(rows,:);end\n' ...
    'if isfield(data,''bad_overlap'')&&rows(1)>1,result.d2(1,1)=999;end\nend\n']));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(temp.Folder));
   clear mphparticle mphsolinfo
   testCase.addTeardown(@clearReaderFixture);
  end
 end
 methods (Test)
  function timingReceiptCountsActualCallsAndUniqueRows(testCase)
   setData(makeData((1:6)',(0:5)',ones(6,1)));
   [~,receipt]=extract_rf_particle_records([], 'sol','part','cpt',[17 91],2.5,[0 10],100,3);
   testCase.verifyEqual(receipt.mphparticle_calls,2);
   testCase.verifyEqual(getappdata(0,'rf_reducer_unit_calls'),2);
   testCase.verifyEqual(receipt.consumed_time_rows,6);
   testCase.verifyEqual(receipt.original_time_rows,6);
   testCase.verifyGreaterThanOrEqual(receipt.mphparticle_seconds,0);
   testCase.verifyGreaterThanOrEqual(receipt.consume_seconds,0);
   testCase.verifyGreaterThanOrEqual(receipt.extract_seconds, ...
    receipt.mphparticle_seconds+receipt.consume_seconds);
  end
  function n100OriginalInventoryConsumerCostBaseline(testCase)
   % Synthetic workload shape only; never a measured COMSOL API or science case.
   % Small warmup avoids warming with an extra full production-shape traversal.
   setData(makeData((1:6)',(0:5)',ones(6,1)));
   extract_rf_particle_records([], 'sol','part','cpt',[17 91],2.5,[0 10],5,3);
   data=makeN100Inventory;ids=17+3*(0:99);setData(data);
   % Act and Assert: the local harness preserves both measured modes and every check.
   exerciseConsumerModes(testCase,data,ids);
  end
  function preservesEachParticleNarrowerRodRegionMaximum(testCase)
   setData(makeData((1:4)',[1;2;4;8],[9;5;4;1]));
   regions=zeros(2,2,2);regions(:,:,1)=[3 10;0 10];regions(:,:,2)=[3 10;2 10];
   records=extract_rf_particle_records([], 'sol','part','cpt',[17 91],5,regions,100,4);
   p2=records{2};testCase.verifyEqual(p2.particle_id,91);
   testCase.verifyTrue(ismember(2,p2.solution_index));
   canonical=p2.position_mm(:,3)>=2&p2.position_mm(:,3)<=10;
   physical=p2.position_mm(:,3)>=3&p2.position_mm(:,3)<=10;
   testCase.verifyEqual(max(sqrt(sum(p2.position_mm(canonical,1:2).^2,2))),5);
   testCase.verifyEqual(max(sqrt(sum(p2.position_mm(physical,1:2).^2,2))),4);
  end
  function leadingAndTerminalNanPreserveSparseSampleOrdinals(testCase)
   setData(makeData((1:6)',[NaN;0;1;2;3;NaN],[NaN;1;2;4;5;NaN]));
   records=extract_rf_particle_records([], 'sol','part','cpt2',[17 91],1.5,[0 10],2,3);
   record=records{1};testCase.verifyEqual(record.trajectory_solution_index,[2;4;5]);
   testCase.verifyEqual(record.solution_index,unique(record.solution_index));
   testCase.verifyTrue(all(ismember([3;4],record.solution_index)));
   expr=getappdata(0,'rf_reducer_unit_expr');
   testCase.verifyEqual(expr{1},'cpt2.pidx');testCase.verifyEqual(expr{5},'cpt2.vx/1[m/s]');
  end
  function finalInventoryFactsAreRetainedWithoutInventingNativeCause(testCase)
   setData(makeData((1:6)',(0:5)',ones(6,1)));
   [records,receipt]=extract_rf_particle_records([], 'sol','part','cpt',[17 91],2.5,[0 10],100,3);
   observation=records{1}.terminal_observation;
   testCase.verifyTrue(observation.finite_at_solution_end);
   testCase.verifyFalse(observation.finite_track_ended);
   testCase.verifyEqual(observation.solution_end_index,6);
   testCase.verifyEqual(observation.solution_end_time_s,6,'AbsTol',0);
   testCase.verifyEqual(receipt.solution_end_time_s,6,'AbsTol',0);
   testCase.verifyEqual(observation.native_termination_cause,'not_observed');
  end
  function terminalNanRetainsEndedObservationAndFinalClock(testCase)
   setData(makeData((1:6)',[0;1;2;3;NaN;NaN],ones(6,1)));
   records=extract_rf_particle_records([], 'sol','part','cpt',[17 91],2.5,[0 10],100,3);
   observation=records{1}.terminal_observation;
   testCase.verifyFalse(observation.finite_at_solution_end);
   testCase.verifyTrue(observation.finite_track_ended);
   testCase.verifyEqual(observation.last_finite_solution_index,4);
   testCase.verifyEqual(observation.last_finite_time_s,4,'AbsTol',0);
   testCase.verifyEqual(observation.solution_end_time_s,6,'AbsTol',0);
  end
  function unorderedNativeColumnsPreserveSparseSourceIdsAndCrossWindowBracket(testCase)
   data=makeData((1:5)',(0:4)',ones(5,1));
   data=reorderColumns(data,[2 1]);
   data.d2(:,1)=7;data.d2(:,2)=3;setData(data);
   [records,receipt]=extract_rf_particle_records([], 'sol','part','cpt3',[17 91],2.5,[0 10],100,3);
   testCase.verifyEqual([records{1}.particle_id records{2}.particle_id],[17 91]);
   testCase.verifyEqual(records{1}.position_mm(:,1),3*ones(numel(records{1}.time_s),1));
   testCase.verifyEqual(records{2}.position_mm(:,1),7*ones(numel(records{2}.time_s),1));
   testCase.verifyTrue(all(ismember([3;4],records{1}.solution_index)));
   testCase.verifyEqual(receipt.original_time_rows,5);testCase.verifyEqual(receipt.physics_identifier,'cpt3');
   expr=getappdata(0,'rf_reducer_unit_expr');testCase.verifyEqual(expr{7},'cpt3.vz/1[m/s]');
  end
  function birthAfterUnidentifiedFirstWindowIsValid(testCase)
   data=makeData((1:8)',[NaN;NaN;NaN;NaN;0;1;2;NaN],ones(8,1));
   data.d1(1:4,:)=NaN;setData(data);
   records=extract_rf_particle_records([], 'sol','part','cpt',[17 91],1.5,[0 10],2,3);
   testCase.verifyEqual(records{1}.time_s(1),5);testCase.verifyEqual(records{2}.particle_id,91);
  end
  function activePartialStateOrIdAndContradictoryLifecycleFailClosed(testCase,activeCase)
   setData(invalidActiveData(activeCase));
   testCase.verifyError(@()extract_rf_particle_records([], 'sol','part','cpt',[17 91],2,[0 10],2,3),'rf:ParticleActiveState');
  end
  function emptyParticleOrUnknownShapeFailsClosed(testCase,readerCase)
   [data,expectedError]=invalidReaderData(readerCase);setData(data);
   testCase.verifyError(@()extract_rf_particle_records([], 'sol','part','cpt',[17 91],2,[0 10],2,3),expectedError);
  end
  function internalGapCannotReachConsumerInterpolation(testCase,gapCase)
   setData(makeData((1:6)',gapCase,ones(6,1)));
   testCase.verifyError(@()extract_rf_particle_records([], 'sol','part','cpt',[17 91],2.5,[0 10],100,3),'rf:ParticleLifecycleGap');
  end
  function changedOverlapOrDuplicateNativeIdentityFailsClosed(testCase,identityCase)
   [data,expectedError]=invalidIdentityData(identityCase);setData(data);
   testCase.verifyError(@()extract_rf_particle_records([], 'sol','part','cpt',[17 91],2.5,[0 10],100,3),expectedError);
  end
 end
end
function data=makeData(time,z,radius)
count=numel(time);data=struct('time',time,'d1',repmat([1 2],count,1), ...
 'd2',repmat(radius,1,2),'d3',zeros(count,2),'d4',repmat(z,1,2), ...
 'd5',zeros(count,2),'d6',zeros(count,2),'d7',ones(count,2));
inactive=isnan(z);for k=2:7,key=sprintf('d%d',k);data.(key)(inactive,:)=NaN;end
end
function setData(data)
setappdata(0,'rf_reducer_unit_data',data);
end
function writeStub(path,text)
fid=fopen(path,'w');cleanup=onCleanup(@()fclose(fid));fprintf(fid,'%s',text); %#ok<NASGU>
end
function clearReaderFixture
clear mphparticle mphsolinfo
for key={'rf_reducer_unit_data','rf_reducer_unit_expr','rf_reducer_unit_calls'}
 if isappdata(0,key{1}),rmappdata(0,key{1});end
end
end

function data=reorderColumns(data,order)
for k=1:7,key=sprintf('d%d',k);data.(key)=data.(key)(:,order);end
end
function data=invalidActiveData(kind)
data=makeData((1:4)',(0:3)',ones(4,1));
if strcmp(kind,'lifecycle')
 data=makeData((1:4)',[NaN;0;1;2],ones(4,1));data.d5(1,1)=0;
else
 data.(kind)(2,1)=NaN;
end
end
function [data,expectedError]=invalidReaderData(kind)
data=makeData((1:4)',(0:3)',ones(4,1));
if strcmp(kind,'empty')
 for k=2:7,key=sprintf('d%d',k);data.(key)(:,2)=NaN;end
 expectedError='rf:ParticleActiveState';
else
 data.d6=zeros(4,1);expectedError='rf:ParticleShape';
end
end
function [data,expectedError]=invalidIdentityData(kind)
if strcmp(kind,'overlap')
 data=makeData((1:6)',(0:5)',ones(6,1));data.bad_overlap=true;
 expectedError='rf:ParticleOverlap';
else
 data=makeData((1:4)',(0:3)',ones(4,1));data.d1(:,2)=1;
 expectedError='rf:ParticleIndex';
end
end

function data=makeN100Inventory
% Full distinct IDs, late births beyond the first window and observed endings.
count=7119;particles=100;time=linspace(0,80e-6,count)';
data=struct('time',time,'d1',repmat(1:particles,count,1));
for k=2:7,key=sprintf('d%d',k);data.(key)=NaN(count,particles);end
for index=1:particles
 first=1+mod(index*17,600);last=count-mod(index,3)*113;rows=(first:last)';
 data.d2(rows,index)=index/100+sin(rows/1000)/100;
 data.d3(rows,index)=cos(rows/1000)/100;data.d4(rows,index)=80*(rows-first)/(count-first);
 data.d5(rows,index)=1;data.d6(rows,index)=2;data.d7(rows,index)=1000;
 data.d1(1:first-1,index)=NaN;
end
% Native output columns may be unordered; mapping remains the original source IDs.
data=reorderColumns(data,particles:-1:1);
end

function exerciseConsumerModes(testCase,data,ids)
   modes={'native','gui'};
   for modeIndex=1:numel(modes)
    if strcmp(modes{modeIndex},'native'),planes=[20 40 60 60-1e-6];stride=5;
    else,planes=[];stride=1;end
    setappdata(0,'rf_reducer_unit_calls',0);timer=tic;
    [records,receipt]=extract_rf_particle_records([], 'sol','part','cpt',ids,planes,[0 80],stride,256);
    elapsed=toc(timer);
    testCase.verifyEqual(receipt.original_time_rows,7119);
    testCase.verifyEqual(receipt.consumed_time_rows,7119);
    testCase.verifyEqual(receipt.mphparticle_calls,28);
    testCase.verifyEqual(getappdata(0,'rf_reducer_unit_calls'),28);
    testCase.verifyEqual(cellfun(@(r)r.particle_id,records),ids);
    for index=1:100
     record=records{index};active=find(isfinite(data.d2(:,101-index)));
     testCase.verifyEqual(record.solution_index(1),active(1));
     testCase.verifyEqual(record.solution_index(end),active(end));
     testCase.verifyEqual(record.time_s,data.time(record.solution_index));
     testCase.verifyEqual(record.position_mm,[data.d2(record.solution_index,101-index), ...
      data.d3(record.solution_index,101-index),data.d4(record.solution_index,101-index)]);
     testCase.verifyEqual(record.velocity_m_s,[data.d5(record.solution_index,101-index), ...
      data.d6(record.solution_index,101-index),data.d7(record.solution_index,101-index)]);
     testCase.verifyEqual(record.terminal_observation.native_termination_cause,'not_observed');
     if strcmp(modes{modeIndex},'gui'),testCase.verifyEqual(record.solution_index,active);end
    end
    fprintf('RF_CONSUMER_BASELINE_JSON=%s\n',jsonencode(struct('mode',modes{modeIndex}, ...
     'api','deterministic_stub_not_comsol','wall_seconds',elapsed,'receipt',receipt)));
   end
end
