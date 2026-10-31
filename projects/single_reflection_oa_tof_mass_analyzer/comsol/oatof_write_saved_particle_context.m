function oatof_write_saved_particle_context(modelPath,context,saveState)
arguments
    modelPath
    context (1,1) struct
    saveState {mustBeTextScalar,mustBeMember(saveState,["raw_complete","gui_update_started","gui_update_complete"])}="raw_complete"
end
% The only two-argument producer call is the original completed raw-save boundary.
context.model_save_state=char(saveState);
contextPath=[char(modelPath) '.postprocess.json'];
contextTemp=[contextPath '.tmp'];
fid=fopen(contextTemp,'w');
assert(fid>=0,'oatof:SavedContextWrite','Cannot persist saved solution context.');
cleanup=onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',jsonencode(context));
clear cleanup
movefile(contextTemp,contextPath,'f');
end
