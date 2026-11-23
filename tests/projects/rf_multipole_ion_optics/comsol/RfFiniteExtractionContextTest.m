classdef RfFiniteExtractionContextTest < matlab.unittest.TestCase
 properties (TestParameter)
  portKind=struct('finite','circle','open','open_rod_envelope');
  badPort=struct('unknown','unknown','nullRadius','empty','nonfinite','infinite','negative','negative');
  invalid=struct('missingContext','missing','duplicateOrder','duplicate','reorderedIds','ids', ...
   'changedBirth','birth','changedSpecies','species','missingClock','clock','wrongSolution','solution');
 end
 methods (TestClassSetup)
  function helperPath(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(root,'comsol')));
  end
 end
 methods (Test)
  function acceptsExplicitNonidentityMappingWithoutResampling(testCase)
   [source,metadata,context]=fixture();
   validate_finite_extraction_context(source,metadata,context);
   testCase.verifyEqual(source.particle_id,[41;7;93]);
   testCase.verifyEqual(context.native_order,[1;3;2]);
  end
  function incompleteOrConflictingEvidenceRejected(testCase,invalid)
   [source,metadata,context,identifier]=invalidFixture(invalid);
   testCase.verifyError(@()validate_finite_extraction_context(source,metadata,context),identifier);
  end
  function portJsonRoundtripPreservesPhysicalMeaning(testCase,portKind)
   [source,metadata,context]=fixture();
   [context,expected]=portFixture(context,portKind);
   decoded=jsondecode(jsonencode(context));
   acceptance=validate_finite_extraction_context(source,metadata,decoded);
   testCase.verifyEqual(acceptance.entrance_interface.aperture_radius_mm,expected,'AbsTol',0);
   testCase.verifyEqual(decoded.acceptance.entrance_interface.cross_section.shape,portKind);
  end
  function invalidPortCannotBecomePhysicalAperture(testCase,badPort)
   [source,metadata,context]=fixture();
   context=invalidPortFixture(context,badPort);
   testCase.verifyError(@()validate_finite_extraction_context(source,metadata,context),'rf:ExtractionPort');
  end
  function missingDependencyRejectedBeforeCommercialAccess(testCase)
   request=struct('model_path','never-existing-rf-parent.mph','source_path','absent.csv', ...
    'source_metadata_path','absent.json','mapping_path','absent-map.json','context',struct());
   testCase.verifyError(@()reextract_finite_3d_transport(request,1),'rf:ExtractionDependency');
  end
 end
end
function [source,metadata,context]=fixture()
source=table([41;7;93],[0;1;0],zeros(3,1),zeros(3,1),zeros(3,1), ...
 ones(3,1),ones(3,1),ones(3,1),100*ones(3,1),ones(3,1), ...
 'VariableNames',{'particle_id','birth_time_s','x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s','mass_amu','charge_state'});
metadata=struct('role','multipole_canonical_particle_source_metadata','mass_amu',100,'charge_state',1,'parent_resolved_design_sha256','fixture');
context=struct('solution_on','sol_on','solution_zero','sol_zero','dataset_on','pd_on_temp', ...
 'dataset_zero','pd_zero_temp','native_order',[1;3;2],'source_ids',source.particle_id, ...
 'source_birth_s',source.birth_time_s,'geometry',struct('census_plane_z',7,'rod_z_min',0, ...
 'rod_z_max',5,'handoff_plane_z',6,'entrance_port_plane_z',0,'exit_port_plane_z',6), ...
 'acceptance',struct('working_region_radius',1,'entrance_interface',struct('cross_section',struct('shape','circle','radius_mm',1)), ...
 'exit_interface',struct('cross_section',struct('shape','circle','radius_mm',1))),'census_radius_mm',1, ...
 'drive',struct('frequency_Hz',1,'phase_rad',0),'primary_case_id','finite_3d_rf_on', ...
 'control_case_id','zero_rf_control','resolved_design_sha256','fixture','outputs',struct('events','events.csv','trajectories','trace.csv', ...
 'canonical','','primary_canonical','','control_canonical','','primary_trajectories','','control_trajectories',''));
end
function [source,metadata,context,identifier]=invalidFixture(kind)
[source,metadata,context]=fixture();identifier='rf:ExtractionMapping';
switch kind
 case 'missing',context=rmfield(context,'geometry');identifier='rf:ExtractionContext';
 case 'duplicate',context.native_order=[1;1;2];
 case 'ids',context.source_ids=[7;41;93];
 case 'birth',context.source_birth_s(2)=2;
 case 'species',source.mass_amu(2)=200;identifier='rf:ExtractionSource';
 case 'clock',context.drive=rmfield(context.drive,'phase_rad');identifier='rf:ExtractionContext';
 case 'solution',context.solution_on='sol_current';identifier='rf:ExtractionContext';
end
end

function [context,expected]=portFixture(context,kind)
if strcmp(kind,'circle')
 section=struct('shape','circle','radius_mm',2);expected=2;
else
 section=struct('shape','open_rod_envelope','inscribed_radius_mm',4);expected=Inf;
end
context.acceptance.entrance_interface.cross_section=section;
context.acceptance.exit_interface.cross_section=section;
end
function context=invalidPortFixture(context,kind)
section=struct('shape','circle','radius_mm',1);
switch kind
 case 'unknown',section.shape='unknown';
 case 'empty',section.radius_mm=[];
 case 'infinite',section.radius_mm=Inf;
 case 'negative',section.radius_mm=-1;
end
context.acceptance.entrance_interface.cross_section=section;
end
