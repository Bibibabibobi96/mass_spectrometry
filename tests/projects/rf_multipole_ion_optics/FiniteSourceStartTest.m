classdef FiniteSourceStartTest < matlab.unittest.TestCase
    methods (TestMethodSetup)
        function addConsumerPath(testCase)
            projectRoot=fileparts(fileparts(mfilename('fullpath')));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
        end
    end
    methods (Test)
        function acceptsAuthorizedVolume(testCase)
            [source,metadata]=sourceFixture(true);
            testCase.verifyWarningFree(@()validate_finite_source_start(source,metadata,0));
        end
        function acceptsOriginalPlane(testCase)
            [source,metadata]=sourceFixture(false);
            source.z_mm(:)=0;
            testCase.verifyWarningFree(@()validate_finite_source_start(source,metadata,0));
        end
        function rejectsOffPlaneWithoutVolume(testCase)
            [source,metadata]=sourceFixture(false);
            testCase.verifyError(@()validate_finite_source_start(source,metadata,0),'multipole:sourceStart:plane');
        end
        function rejectsUnprovenVolume(testCase)
            [source,metadata]=sourceFixture(true);
            metadata.energy_model_authority='resolved_design_or_operating_point';
            testCase.verifyError(@()validate_finite_source_start(source,metadata,0),'multipole:sourceStart:volumeAuthority');
        end
        function rejectsWrongSpecies(testCase)
            [source,metadata]=sourceFixture(true);
            source.charge_state(:)=-1;
            testCase.verifyError(@()validate_finite_source_start(source,metadata,0),'multipole:sourceStart:species');
        end
        function rejectsNegativeClock(testCase)
            [source,metadata]=sourceFixture(true);
            source.birth_time_s(:)=-1;
            testCase.verifyError(@()validate_finite_source_start(source,metadata,0),'multipole:sourceStart:state');
        end
    end
end
function [source,metadata]=sourceFixture(volume)
source=table([1;2],[0;0],[0;0],[-2;-1],[0;0],[0;0],[2000;2000],[0;0],[100;100],[1;1], ...
    'VariableNames',{'particle_id','x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s','birth_time_s','mass_amu','charge_state'});
metadata=struct('role','multipole_canonical_particle_source_metadata','particle_count',2, ...
    'mass_amu',100,'charge_state',1,'source_volume_snapshot',volume, ...
    'source_plane_z_mm',[],'operating_point_binding',[], ...
    'energy_model_authority','continuous_axial_volume_source_receipt');
end
