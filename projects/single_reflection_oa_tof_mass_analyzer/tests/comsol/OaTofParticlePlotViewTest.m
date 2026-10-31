classdef OaTofParticlePlotViewTest < matlab.unittest.TestCase
 methods (TestClassSetup)
  function addProjectPath(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
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
end
