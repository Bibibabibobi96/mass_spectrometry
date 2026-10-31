classdef OaTofParticlePlotViewTest < matlab.unittest.TestCase
 properties (TestParameter)
  population=struct('n100',100,'n1000',1000,'n5000',5000);
  invalidInventory=struct('allEqual',[0;0],'decreasing',[0;1;0],'nonfinite',[0;NaN;1]);
  sharedInventory=struct('allEqual',[0;0],'decreasing',[0;1;0], ...
   'nonfinite',[0;NaN;1],'complex',[0;1i;1],'matrix',[0 1;2 3]);
  boundaryRow=struct('lastFresh',256,'nextFresh',257);
  detectorEvent=struct('freeze','frozen_on_detector','crossing','crossing');
 end
 methods (TestClassSetup)
  function addProjectPath(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(root));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(root,'comsol')));
  end
 end
 methods (Test)
  function largePopulationRemainsTheSameSolvedPopulation(testCase)
   t=[0;1e-6;2e-6];x=reshape(1:7503,3,2501);z=-x;
   originalX=x;originalZ=z;z(2,7)=NaN;originalZ(2,7)=NaN;
   view=oatof_particle_plot_view(t,x,z,50);
   testCase.verifyEqual(view.population_size,2501);
   testCase.verifyEqual(view.particle_indices,1:50);
   testCase.verifyEqual(view.time_s,t);
   testCase.verifyEqual(view.x_mm,x(:,1:50));testCase.verifyEqual(view.z_mm,z(:,1:50));
   testCase.verifyEqual(x,originalX);testCase.verifyEqual(z,originalZ);
  end
  function smallPopulationAndSingleParticleKeepTheirAxes(testCase)
   t=[0;1];x=[4;5];z=[7;8];view=oatof_particle_plot_view(t,x,z,50);
   testCase.verifyEqual(view.particle_indices,1);testCase.verifyEqual(size(view.x_mm),[2 1]);
   testCase.verifyEqual(view.z_mm,z);
  end
  function invalidAxesAndTimesFailBeforePlotting(testCase)
   testCase.verifyError(@()oatof_particle_plot_view([0;1],zeros(3,2),zeros(3,2)), 'oatof:PlotPopulation');
   testCase.verifyError(@()oatof_particle_plot_view([0;1],zeros(2,2),zeros(2,3)), 'oatof:PlotShape');
   testCase.verifyError(@()oatof_particle_plot_view([1;0],zeros(2,2),zeros(2,2)), 'oatof:PlotTime');
  end
 end

 methods (Test)
  function sharedPostprocessUsesBoundedWindowsForWholeCohort(testCase,population)
   [context,folder,mockFolder]=postprocessFixture(testCase);
   configureLargePopulation(mockFolder,population);context.particle_count=population;
   [result,phases]=oatof_postprocess_saved_solution(struct('param',[]),context,folder);
   testCase.verifyEqual(result.nP,population);testCase.verifyEqual(result.nDet,population);
   testCase.verifyEqual(phases.plot_count,50);
   testCase.verifyEqual(result.postprocess_extraction.passes,2);
   testCase.verifyLessThanOrEqual(getappdata(0,'oatof_fixture_max_rows'),257);
   testCase.verifyEqual(getappdata(0,'oatof_fixture_calls'),result.postprocess_extraction.api_calls);
   testCase.verifyLessThan(result.postprocess_extraction.maximum_api_payload_bytes, ...
    24*result.postprocess_extraction.original_query_rows*population);
   testCase.verifyLessThan(result.postprocess_extraction.reducer_state_bytes,1024*population+65536);
   events=readtable(result.raw_detector_events_path);
   testCase.verifyEqual(events.Ion,(1:population)');testCase.verifyTrue(all(events.Hit));
  end
  function sharedPostprocessUsesWholePopulationWithoutSolver(testCase)
   [context,folder]=postprocessFixture(testCase);
   [result,~]=oatof_postprocess_saved_solution(struct('param',[]),context,folder);
   testCase.verifyEqual(result.nP,2);
   testCase.verifyEqual(result.nDet,2);
   testCase.verifyEqual(result.native_particle_solve_count,0);
   rows=readtable(result.raw_detector_events_path);
   testCase.verifyEqual(rows.Ion,[1;2]);
   testCase.verifyEqual(rows.X0Mm,[0;0]);
   testCase.verifyEqual(rows.Z0Mm,[0;0]);
  end
  function sharedPostprocessRejectsMissingMotherBeforeExport(testCase)
   [context,folder]=postprocessFixture(testCase);
   context.particle_count=3;
   testCase.verifyError(@()oatof_postprocess_saved_solution(struct('param',[]),context,folder), ...
    'oatof:SavedPopulation');
   testCase.verifyFalse(isfile(fullfile(folder,'comsol_detector_events_Fixture.csv')));
  end
  function scientificWindowFailureKeepsFullRawMotherAndCounts(testCase)
   [context,folder,mockFolder]=postprocessFixture(testCase);
   data=load(fullfile(mockFolder,'read_fixture.mat'));value=data.value;
   value.d3(:,2)=0;save(fullfile(mockFolder,'read_fixture.mat'),'value');
   failure=captureScientificFailure(@()oatof_postprocess_saved_solution(struct('param',[]),context,folder));
   testCase.assertNotEmpty(failure);
   testCase.verifySubstring(failure.message,'Event-window gate could not identify every');
   testCase.verifySubstring(failure.message,'nP=2 nDet=1 complete=1 accel=1 refl_entry=1 refl_exit=1 detector=1');
   rows=readtable(fullfile(folder,'comsol_detector_events_Fixture.csv'));
   testCase.verifyEqual(rows.Ion,[1;2]);
   testCase.verifyEqual(logical(rows.Hit),[true;false]);
   request=jsondecode(fileread(fullfile(folder,'comsol_detector_events_Fixture.analysis_request.json')));
   testCase.verifyEqual(request.raw_events_csv,fullfile(folder,'comsol_detector_events_Fixture.csv'));
  end
  function sharedQueryRetainsEveryStoredAndPreviousTime(testCase)
   [context,folder]=postprocessFixture(testCase);
   context.solution_times_s=sort([context.solution_times_s;1.234567891e-6]);
   original=context.solution_times_s;
   [result,~]=oatof_postprocess_saved_solution(struct('param',[]),context,folder);
   expected=fullFixtureQuery(context);
   queries=getappdata(0,'oatof_fixture_queries');
   [first,second,overlap]=reconstructQueryPasses(queries);
   testCase.verifyEqual(first,expected,'AbsTol',0);
   testCase.verifyEqual(second,expected,'AbsTol',0);
   testCase.verifyTrue(overlap);
   testCase.verifyTrue(all(ismember(original,first)));
   testCase.verifyTrue(all(ismember(oldFixtureQuery(context),first)));
   testCase.verifyEqual(context.solution_times_s,original,'AbsTol',0);
   testCase.verifyEqual(result.postprocess_extraction.stored_inventory_rows,numel(original));
   testCase.verifyEqual(result.nP,2);
  end
  function storedApproachAcrossWindowKeepsOriginalDetectorEvent(testCase,boundaryRow,detectorEvent)
   [context,folder,mockFolder]=postprocessFixture(testCase);
   [context,approachTime]=configureStoredApproach(mockFolder,context,boundaryRow,detectorEvent);
   fullTimes=fullFixtureQuery(context);
   reference=fixtureArrivalReference(mockFolder,context,fullTimes);
   old=fixtureArrivalReference(mockFolder,context,oldFixtureQuery(context));
   [result,~]=oatof_postprocess_saved_solution(struct('param',[]),context,folder);
   testCase.verifyEqual(old.status,repmat(oldDetectorStatus(detectorEvent),2,1));
   testCase.verifyEqual(reference.event,repmat(string(detectorEvent),2,1));
   testCase.verifyEqual(result.detectorStatus,reference.status.');
   testCase.verifyEqual(result.nP,2);testCase.verifyEqual(result.nDet,2);
   rows=readtable(result.raw_detector_events_path);
   testCase.verifyEqual(rows.Ion,[1;2]);testCase.verifyTrue(all(rows.Hit));
   testCase.verifyEqual(string(rows.Event),reference.event);
   testCase.verifyLessThanOrEqual(getappdata(0,'oatof_fixture_max_rows'),257);
   queries=getappdata(0,'oatof_fixture_queries');
   [first,second,overlap]=reconstructQueryPasses(queries);
   testCase.verifyEqual(first,fullTimes,'AbsTol',0);
   testCase.verifyEqual(second,fullTimes,'AbsTol',0);testCase.verifyTrue(overlap);
   testCase.verifyEqual(mod(find(fullTimes==approachTime)-1,256),mod(boundaryRow-1,256));
  end
  function invalidSharedInventoryFailsBeforeAnyParticleRead(testCase,sharedInventory)
   [context,folder]=postprocessFixture(testCase);
   context.solution_times_s=sharedInventory;
   testCase.verifyError(@()oatof_postprocess_saved_solution(struct('param',[]),context,folder), ...
    'oatof:SavedTimes');
   testCase.verifyEmpty(getappdata(0,'oatof_fixture_calls'));
   testCase.verifyFalse(isfile(fullfile(folder,'comsol_detector_events_Fixture.csv')));
  end
  function missingSharedInventoryFailsBeforeAnyParticleRead(testCase)
   [context,folder]=postprocessFixture(testCase);
   context=rmfield(context,'solution_times_s');
   testCase.verifyError(@()oatof_postprocess_saved_solution(struct('param',[]),context,folder), ...
    'oatof:SavedContext');
   testCase.verifyEmpty(getappdata(0,'oatof_fixture_calls'));
  end
  function normalSharedReaderChecksEqualTimeCompleteStatesOnce(testCase)
   request=coldReadFixture(testCase,[0;.5;1;1;2;3;4;5;6]*1e-6,[1 1;NaN NaN;3 3]);
   context=jsondecode(fileread(request.context_path));
   [result,~]=oatof_postprocess_saved_solution(struct('param',[]),context,request.output_dir);
   testCase.verifyEqual(getappdata(0,'oatof_fixture_state_calls'),1);
   testCase.verifyEqual(result.nP,2);testCase.verifyEqual(result.nDet,2);
  end
  function normalSharedReaderRejectsDifferentEqualTimeCompleteStates(testCase)
   request=coldReadFixture(testCase,[0;.5;1;1;2;3;4;5;6]*1e-6,[1 2;NaN NaN;3 3]);
   context=jsondecode(fileread(request.context_path));
   testCase.verifyError(@()oatof_postprocess_saved_solution(struct('param',[]),context,request.output_dir), ...
    'oatof:ColdDuplicateState');
   testCase.verifyEmpty(getappdata(0,'oatof_fixture_calls'));
   testCase.verifyFalse(isfolder(request.output_dir));
  end
  function coldAdapterKeepsExecutionOutputSpellingThroughRealHelper(testCase)
   request=coldReadFixture(testCase,[0;.5;1;2;3;4;5;6]*1e-6,[1 1]);
   result=reextract_oatof_saved_solution(request);
   testCase.verifyEqual(result.raw_detector_events_path, ...
    fullfile(request.output_dir,'comsol_detector_events_Fixture.csv'));
   testCase.verifyEqual(result.native_particle_solve_count,0);
   testCase.verifyFalse(result.parent_model_saved);
   testCase.verifyEqual(fileread(request.model_path),'MPH');
  end
  function exactDuplicateInventoryRetainsAllRowsAndChecksCompleteState(testCase)
   request=coldReadFixture(testCase,[0;.5;1;1;2;3;4;5;6]*1e-6,[1 1;NaN NaN;3 3]);
   original=fileread(request.context_path);
   result=reextract_oatof_saved_solution(request);
   testCase.verifyEqual(getappdata(0,'oatof_fixture_state_calls'),1);
   testCase.verifyEqual(fileread(request.context_path),original);
   testCase.verifyEqual(result.native_particle_solve_count,0);
   testCase.verifyFalse(result.parent_model_saved);
   testCase.verifyTrue(isfile(result.raw_detector_events_path));
  end
  function equalTimeDifferentCompleteStateFailsBeforeExport(testCase)
   request=coldReadFixture(testCase,[0;.5;1;1;2;3;4;5;6]*1e-6,[1 2;NaN NaN;3 3]);
   testCase.verifyError(@()reextract_oatof_saved_solution(request),'oatof:ColdDuplicateState');
   testCase.verifyEmpty(getappdata(0,'oatof_fixture_calls'));
   testCase.verifyFalse(isfolder(request.output_dir));
  end
  function invalidStoredInventoryFailsBeforeNativeOpen(testCase,invalidInventory)
   request=coldReadFixture(testCase,invalidInventory,[1 1]);
   testCase.verifyError(@()reextract_oatof_saved_solution(request),'oatof:ColdTimes');
   testCase.verifyEmpty(getappdata(0,'oatof_fixture_state_calls'));
   testCase.verifyEmpty(getappdata(0,'oatof_fixture_calls'));
  end
  function coldAdapterRejectsUnboundRequestBeforeNativeOpen(testCase)
   testCase.verifyError(@()reextract_oatof_saved_solution(struct()),'oatof:ColdRequest');
  end
 end

end

function failure=captureScientificFailure(action)
failure=[];
try
 action();
catch error
 failure=error;
end
end

function [context,folder,mockFolder]=postprocessFixture(testCase)
folder=tempname;mkdir(folder);
testCase.addTeardown(@()rmdir(folder,'s'));
testCase.addTeardown(@()close('all'));
testCase.addTeardown(@clearBoundedReaderCounters);
mockFolder=fullfile(folder,'native_read_fixture');mkdir(mockFolder);
file=fullfile(mockFolder,'mphparticle.m');
fid=fopen(file,'w');assert(fid>=0);
fprintf(fid,'%s',sprintf([ ...
 'function value=mphparticle(varargin)\n' ...
 'data=load(fullfile(fileparts(mfilename(''fullpath'')),''read_fixture.mat''));base=data.value;\n' ...
 'times=varargin{find(strcmp(varargin,''t''))+1};times=times(:);value=struct(''t'',times);\n' ...
 'queries=getappdata(0,''oatof_fixture_queries'');if isempty(queries),queries={};end;queries{end+1}=times;setappdata(0,''oatof_fixture_queries'',queries);\n' ...
 'calls=getappdata(0,''oatof_fixture_calls'');if isempty(calls),calls=0;end;setappdata(0,''oatof_fixture_calls'',calls+1);\n' ...
 'maximum=getappdata(0,''oatof_fixture_max_rows'');if isempty(maximum),maximum=0;end;setappdata(0,''oatof_fixture_max_rows'',max(maximum,numel(times)));\n' ...
 'for k=1:3,key=sprintf(''d%%d'',k);v=interp1(base.t,base.(key),times,''linear'',NaN);if isfield(data,''population''),v=repmat(v(:,1),1,data.population);end;value.(key)=v;end\nend\n']));fclose(fid);
testCase.applyFixture(matlab.unittest.fixtures.PathFixture(mockFolder));
value=struct('t',[0;.5;1;2;3;4;5;6]*1e-6, ...
 'd1',zeros(8,2),'d2',zeros(8,2),'d3',repmat([0;2;10;14;12;10;0;-2],1,2));
save(fullfile(mockFolder,'read_fixture.mat'),'value');
context=struct('schema_version',1,'role','oatof_saved_particle_solution', ...
 'solution_tag','sol2','dataset_tag','pdset1','particle_count',2, ...
 'label','Fixture','mass_amu',524,'expected_tof',5e-6,'fine_tstep',1e-9, ...
 'Tsim',6e-6,'d1_mm',2,'reflectron_stage2_min_mm',2,'d2_mm',4, ...
 'd2_margin_fraction',.2,'allow_particle_loss',false,'fine_end',8e-6, ...
 'Ez_accel_ideal','0','Ez_drift_ideal','0','Ez_stage1_ideal','0','Ez_stage2_ideal','0', ...
 'field_mode','real','reflectron_backplate_voltage_v',100,'modelPath','unused.mph', ...
 'flight_length_mm',10,'reflectron_length_mm',6,'detector_z_mm',0,'detector_x_mm',0, ...
 'detector_radius_mm',2,'accelerator_exit_mm',1,'field_idealization',struct(), ...
 'native_particle_solve_count',0,'generate_model_plots',false,'solution_times_s',value.t, ...
 'timing',struct('t_accel_end_s',1e-6,'t_refl_start_s',.5e-6, ...
 't_refl_end_s',4.5e-6,'t_detector_start_s',4e-6,'t_detector_end_s',6e-6));
end

function writeFixtureText(path,text)
fid=fopen(path,'w');assert(fid>=0);
cleanup=onCleanup(@()fclose(fid));fprintf(fid,'%s',text);
clear cleanup
end

function configureLargePopulation(folder,population)
data=load(fullfile(folder,'read_fixture.mat'));value=data.value;
for k=1:3,key=sprintf('d%d',k);value.(key)=value.(key)(:,1);end
save(fullfile(folder,'read_fixture.mat'),'value','population');
end
function clearBoundedReaderCounters
for key={'oatof_fixture_calls','oatof_fixture_max_rows','oatof_fixture_state_calls','oatof_fixture_queries'}
 if isappdata(0,key{1}),rmappdata(0,key{1});end
end
end

function request=coldReadFixture(testCase,times,states)
   [context,folder,mockFolder]=postprocessFixture(testCase);
   parent=fullfile(folder,'parent');mkdir(parent);
   child=fullfile(folder,'child');mkdir(child);mkdir(fullfile(child,'nested'));
   request=struct('model_path',fullfile(parent,'model.mph'), ...
    'context_path',fullfile(parent,'model.mph.postprocess.json'), ...
    'parent_run_directory',parent,'child_run_directory',child, ...
    'output_dir',fullfile(child,'nested','..','results'), ...
    'candidate_contract_path',fullfile(fileparts(fileparts(fileparts(mfilename('fullpath')))), ...
        'config','resolved_geometry.json'));
   context.saved_model_bytes=3;
   context.solution_times_s=times;
   writeFixtureText(request.model_path,'MPH');
   writeFixtureText(request.context_path,jsonencode(context));
   writeFixtureText(fullfile(mockFolder,'mphopen.m'),sprintf( ...
    'function model=mphopen(varargin)\nmodel=struct(''param'',[],''result'',struct(''dataset'',@(unused)struct(''getString'',@(key)''sol2'')));\nend\n'));
   writeFixtureText(fullfile(mockFolder,'mphsolinfo.m'),sprintf( ...
    'function info=mphsolinfo(varargin)\ndata=load(fullfile(fileparts(mfilename(''fullpath'')),''inventory.mat''));info=struct(''soltype'',''Time'',''solvals'',data.times);\nend\n'));
   writeFixtureText(fullfile(mockFolder,'oatof_validate_candidate_solution.m'),sprintf( ...
    'function validation=oatof_validate_candidate_solution(varargin)\nvalidation=struct();\nend\n'));
   rehash
   testCase.assertEqual(which('oatof_validate_candidate_solution'), ...
    fullfile(mockFolder,'oatof_validate_candidate_solution.m'));
   testCase.assertEqual(which('mphopen'),fullfile(mockFolder,'mphopen.m'));
   testCase.assertEqual(which('mphsolinfo'),fullfile(mockFolder,'mphsolinfo.m'));
   save(fullfile(mockFolder,'inventory.mat'),'times','states');
   writeFixtureText(fullfile(mockFolder,'mphgetu.m'),sprintf([ ...
    'function value=mphgetu(varargin)\n' ...
    'assert(strcmp(varargin{find(strcmp(varargin,''soltag''))+1},''sol2''));\n' ...
    'data=load(fullfile(fileparts(mfilename(''fullpath'')),''inventory.mat''));\n' ...
    'numbers=varargin{find(strcmp(varargin,''solnum''))+1};assert(isequal(numbers,[3 4]));\n' ...
    'calls=getappdata(0,''oatof_fixture_state_calls'');if isempty(calls),calls=0;end;setappdata(0,''oatof_fixture_state_calls'',calls+1);\n' ...
    'value=data.states;\nend\n']));
   rehash
end

function times=oldFixtureQuery(context)
arrival=(context.expected_tof-200e-9):context.fine_tstep:(context.expected_tof+200e-9);
times=unique([linspace(0,context.Tsim,2001),arrival,context.Tsim]).';
end
function times=fullFixtureQuery(context)
times=unique([oldFixtureQuery(context);context.solution_times_s(:)]);
end
function [first,second,overlap]=reconstructQueryPasses(queries)
assert(mod(numel(queries),2)==0);
count=numel(queries)/2;passes=cell(1,2);overlap=true;
for pass=1:2
 times=[];
 for window=1:count
  block=queries{(pass-1)*count+window};
  if window>1
   overlap=overlap&&block(1)==times(end);
   block=block(2:end);
  end
  times=[times;block]; %#ok<AGROW> Small query vectors, never particle payloads.
 end
 passes{pass}=times;
end
first=passes{1};second=passes{2};
end
function [context,approachTime]=configureStoredApproach(folder,context,boundaryRow,detectorEvent)
data=load(fullfile(folder,'read_fixture.mat'));value=data.value;
value.t=[0;.5;1;2;3;4;4.6461;4.6464;4.6467;6]*1e-6;
final=0;
if strcmp(detectorEvent,'crossing'),final=-.4;end
value.d3=repmat([0;2;10;14;12;10;.8;.4;final;final],1,2);
value.d1=zeros(size(value.d3));value.d2=value.d1;
context.solution_times_s=value.t;
approachTime=value.t(8);
initial=fullFixtureQuery(context);index=find(initial==approachTime);
target=256*ceil(index/256)+(boundaryRow-256);
extra=(1:(target-index))'/(target-index+1)*1e-10;
context.solution_times_s=sort([value.t;extra]);
save(fullfile(folder,'read_fixture.mat'),'value');
end
function result=fixtureArrivalReference(folder,context,times)
data=load(fullfile(folder,'read_fixture.mat'));value=data.value;
x=interp1(value.t,value.d1,times,'linear',NaN);
y=interp1(value.t,value.d2,times,'linear',NaN);
z=interp1(value.t,value.d3,times,'linear',NaN);
result=oatof_extract_detector_arrivals(times,x,y,z,context.detector_z_mm, ...
 1e-3,.5,context.detector_x_mm,0,context.detector_radius_mm);
end

function status=oldDetectorStatus(detectorEvent)
status="detector_hit";
if strcmp(detectorEvent,'frozen_on_detector'),status="freeze_without_approach_segment";end
end
