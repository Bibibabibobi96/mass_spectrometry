classdef RfReleaseUpdateScopeTest < matlab.unittest.TestCase
 methods (TestClassSetup)
  function actualProductionScope(testCase)
   project=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   text=fileread(fullfile(project,'comsol','solve_deterministic_rf_quadrupole_particles.m'));
   start=strfind(text,'releaseConstructionTimer=tic;');
   body=strfind(text,'    for i=1:numel(releaseGroups)');
   cleanup=strfind(text,'catch releaseConstructionFailure');
   endMarker='releaseConstructionSeconds=toc(releaseConstructionTimer);';
   finish=strfind(text,endMarker)+numel(endMarker);
   assert(isscalar(start)&&isscalar(body)&&isscalar(cleanup)&&isscalar(finish));
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   % Only the real vendor construction body is replaced by a controlled call;
   % getter/setter/entry guard/try/catch/addCause/final refresh stay production.
   source=[sprintf('function releaseConstructionSeconds=actualReleaseUpdateScope(model,construct)\n') text(start:body-1) ...
    sprintf(' construct();\n') text(cleanup:finish-1) sprintf('\nend\n')];
   path=fullfile(folder.Folder,'actualReleaseUpdateScope.m');
   fid=fopen(path,'w');assert(fid>=0);cleanupFile=onCleanup(@()fclose(fid));fprintf(fid,'%s',source);clear cleanupFile;
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(folder.Folder));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(project,'tests','comsol','test_support')));
   testCase.addTeardown(@clearReleaseUpdateScope);
  end
 end
 methods (Test)
  function successRefreshesBeforeReturning(testCase)
   model=ReleaseUpdateRecorder;
   elapsed=actualReleaseUpdateScope(model,@()model.construct());
   testCase.verifyGreaterThanOrEqual(elapsed,0);
   testCase.verifyTrue(isfinite(elapsed));
   testCase.verifyFalse(model.Disabled);
   testCase.verifyEqual(model.Events,{'get','disable','construct','refresh','get'});
  end
  function constructionFailureRestoresAndPreservesPrimary(testCase)
   model=ReleaseUpdateRecorder;model.FailConstruct=true;
   failure=captureReleaseScopeFailure(model);
   testCase.verifyEqual(failure.identifier,'rf:InjectedConstructionFailure');
   testCase.verifyFalse(model.Disabled);
   testCase.verifyEqual(model.Events,{'get','disable','construct','refresh'});
  end
  function restoreFailureIsCauseOfOriginalConstructionFailure(testCase)
   model=ReleaseUpdateRecorder;model.FailConstruct=true;model.FailRestore=true;
   failure=captureReleaseScopeFailure(model);
   testCase.verifyEqual(failure.identifier,'rf:InjectedConstructionFailure');
   testCase.verifyEqual(failure.cause{1}.identifier,'rf:InjectedRefreshFailure');
   testCase.verifyTrue(model.Disabled);
  end
  function finalRefreshFailureCannotProceedToSaveOrSolve(testCase)
   model=ReleaseUpdateRecorder;model.FailRestore=true;
   failure=captureReleaseScopeFailure(model);
   testCase.verifyEqual(failure.identifier,'rf:InjectedRefreshFailure');
   testCase.verifyTrue(model.Disabled);
  end
  function disabledEntryFailsBeforeConstruction(testCase)
   model=ReleaseUpdateRecorder;model.Disabled=true;
   failure=captureReleaseScopeFailure(model);
   testCase.verifyEqual(failure.identifier,'rf:ReleaseUpdatesState');
   testCase.verifyEqual(model.Events,{'get'});
  end
 end
end
function failure=captureReleaseScopeFailure(model)
try
 actualReleaseUpdateScope(model,@()model.construct());
catch failure
 return
end
error('rf:MissingExpectedScopeFailure','The controlled failure did not propagate.');
end

function clearReleaseUpdateScope
clear actualReleaseUpdateScope
end
