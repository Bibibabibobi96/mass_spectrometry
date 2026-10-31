classdef OaTofGuiSaveCompletionTest < matlab.unittest.TestCase
    properties
        modelPath
    end
    methods (TestMethodSetup)
        function prepare(testCase)
            projectRoot=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
            testCase.applyFixture(matlab.unittest.fixtures.WorkingFolderFixture);
            previous=struct('results',getenv('OATOF_RESULTS_DIR'), ...
                'model',getenv('OATOF_SAVE_FIXTURE_MODEL'),'failure',getenv('OATOF_SAVE_FIXTURE_FAIL'));
            testCase.addTeardown(@() restoreSaveEnvironment(previous));
            testCase.addTeardown(@clearSaveFixtures);
            testCase.modelPath=fullfile(pwd,'model.mph');
            setenv('OATOF_RESULTS_DIR',pwd);
            setenv('OATOF_SAVE_FIXTURE_MODEL',testCase.modelPath);
            setenv('OATOF_SAVE_FIXTURE_FAIL','0');
            writeSaveFixture('oatof_build_saved_particle_solution.m',[
                "function [r,m,c,s]=oatof_build_saved_particle_solution(varargin)"
                "arguments (Repeating)"
                "varargin"
                "end"
                "f=getenv('OATOF_SAVE_FIXTURE_MODEL');fid=fopen(f,'w');fprintf(fid,'RAW');fclose(fid);"
                "r=[];m=struct();c=struct('schema_version',1,'role','oatof_saved_particle_solution','saved_model_bytes',3);"
                "oatof_write_saved_particle_context(f,c);"
                "s=struct('paths',struct(),'output_model_path',f,'label','Fixture','modelPath',f,'phase_times',ones(1,7),'t_raw_save',0,'t_total_start',tic());"
                "end"]);
            writeSaveFixture('oatof_postprocess_saved_solution.m',[
                "function [r,p]=oatof_postprocess_saved_solution(varargin)"
                "arguments (Repeating)"
                "varargin"
                "end"
                "r=struct('nP',100);p=struct('extraction',0,'plot_view',0,'matlab_plot',0,'result_nodes',0,'plot_count',50);"
                "end"]);
            writeSaveFixture('oatof_save_run_model.m',[
                "function f=oatof_save_run_model(varargin)"
                "arguments (Repeating)"
                "varargin"
                "end"
                "f=getenv('OATOF_SAVE_FIXTURE_MODEL');c=jsondecode(fileread([f '.postprocess.json']));"
                "assert(strcmp(c.model_save_state,'gui_update_started'),'fixture:BeginMarkerMissing','GUI marker must be persistent before save.');"
                "fid=fopen(f,'w');fprintf(fid,'BAD');fclose(fid);"
                "if strcmp(getenv('OATOF_SAVE_FIXTURE_FAIL'),'1'),error('fixture:GuiSaveFailure','Same-size partial GUI save');end"
                "end"]);
            clearSaveFixtures;
            testCase.assertEqual(which('oatof_build_saved_particle_solution'),fullfile(pwd,'oatof_build_saved_particle_solution.m'));
            testCase.assertEqual(which('oatof_build_model_core'),fullfile(projectRoot,'comsol','oatof_build_model_core.m'));
            testCase.assertEqual(which('oatof_write_saved_particle_context'),fullfile(projectRoot,'comsol','oatof_write_saved_particle_context.m'));
        end
    end
    methods (Test)
        function sameSizeInterruptedGuiSaveRetainsStartedMarker(testCase)
            setenv('OATOF_SAVE_FIXTURE_FAIL','1');
            testCase.verifyError(@() oatof_build_model_core(),'fixture:GuiSaveFailure');
            saved=jsondecode(fileread([testCase.modelPath '.postprocess.json']));
            info=dir(testCase.modelPath);
            testCase.verifyEqual(saved.model_save_state,'gui_update_started');
            testCase.verifyEqual(info.bytes,saved.saved_model_bytes,AbsTol=0);
            testCase.verifyEqual(fileread(testCase.modelPath),'BAD');
        end
        function successfulGuiSavePersistsCompletionAfterWrite(testCase)
            result=oatof_build_model_core();
            saved=jsondecode(fileread([testCase.modelPath '.postprocess.json']));
            testCase.verifyEqual(saved.model_save_state,'gui_update_complete');
            testCase.verifyEqual(result.model_path,testCase.modelPath);
            testCase.verifyEqual(saved.saved_model_bytes,3,AbsTol=0);
        end
    end
end
function writeSaveFixture(name,lines)
fid=fopen(name,'w');cleanup=onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',join(lines,newline));
end
function clearSaveFixtures()
clear oatof_build_saved_particle_solution oatof_postprocess_saved_solution oatof_save_run_model
rehash
end
function restoreSaveEnvironment(previous)
setenv('OATOF_RESULTS_DIR',previous.results);
setenv('OATOF_SAVE_FIXTURE_MODEL',previous.model);
setenv('OATOF_SAVE_FIXTURE_FAIL',previous.failure);
end
