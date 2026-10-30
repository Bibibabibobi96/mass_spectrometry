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
for key={'rf_reducer_unit_data','rf_reducer_unit_expr'}
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
