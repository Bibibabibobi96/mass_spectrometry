function oatof_write_saved_particle_context(modelPath,context)
arguments
    modelPath
    context
end
contextPath=[char(modelPath) '.postprocess.json'];
contextTemp=[contextPath '.tmp'];
fid=fopen(contextTemp,'w');
assert(fid>=0,'oatof:SavedContextWrite','Cannot persist saved solution context.');
cleanup=onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',jsonencode(context));
clear cleanup
movefile(contextTemp,contextPath,'f');
end
