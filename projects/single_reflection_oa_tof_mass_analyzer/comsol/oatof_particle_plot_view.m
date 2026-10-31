function view=oatof_particle_plot_view(time_s,x_mm,z_mm,maximum_particles)
%OATOF_PARTICLE_PLOT_VIEW Read-only graphic columns of one solved population.
% This view never replaces the original arrays used for events or statistics.
arguments
 time_s (:,1) double
 x_mm double
 z_mm double
 maximum_particles (1,1) double {mustBeInteger,mustBePositive}=50
end
assert(isequal(size(x_mm),size(z_mm))&&ismatrix(x_mm), ...
 'oatof:PlotShape','Plot coordinate arrays must have matching time and particle axes.');
assert(size(x_mm,1)==numel(time_s)&&size(x_mm,2)>0, ...
 'oatof:PlotPopulation','Plot view requires the original nonempty time/population axes.');
assert(all(isfinite(time_s))&&all(diff(time_s)>0), ...
 'oatof:PlotTime','Original plot time samples must be finite and strictly increasing.');
indices=1:min(maximum_particles,size(x_mm,2));
view=struct('time_s',time_s,'particle_indices',indices,'population_size',size(x_mm,2), ...
 'x_mm',x_mm(:,indices),'z_mm',z_mm(:,indices));
end
