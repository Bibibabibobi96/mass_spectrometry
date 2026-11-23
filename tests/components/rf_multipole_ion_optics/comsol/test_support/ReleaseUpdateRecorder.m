classdef ReleaseUpdateRecorder < handle
 properties
  Disabled=false
  FailConstruct=false
  FailRestore=false
  Events={}
 end
 methods
  function previous=disableUpdates(model,varargin)
   previous=model.Disabled;
   if isempty(varargin)
    model.Events{end+1}='get';return
   end
   state=varargin{1};
   if state
    model.Events{end+1}='disable';model.Disabled=true;
   else
    model.Events{end+1}='refresh';
    if model.FailRestore,error('rf:InjectedRefreshFailure','Controlled refresh failed.');end
    model.Disabled=false;
   end
  end
  function construct(model)
   model.Events{end+1}='construct';
   assert(model.Disabled,'rf:UpdatesWereNotDeferred','Construction did not run in its update scope.');
   if model.FailConstruct,error('rf:InjectedConstructionFailure','Controlled construction failed.');end
  end
 end
end
