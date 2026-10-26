classdef OaTofCartesianReleaseTest < matlab.unittest.TestCase
    properties
        path
        release
    end
    methods (TestMethodSetup)
        function prepareRelease(testCase)
            projectRoot=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(projectRoot));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
            fixture=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.path=fullfile(fixture.Folder,'cartesian.csv');
            testCase.release=array2table([17,100,1,-14,0,-18,3000,-45,90,5; ...
                3,100,1,-13,1,-19,-2000,81,-93,3], ...
                'VariableNames',{'particle_id','mass_amu','charge_state','x_mm','y_mm','z_mm', ...
                'vx_m_per_s','vy_m_per_s','vz_m_per_s','kinetic_energy_eV'});
        end
    end
    methods (Test)
        function preservesIdsOrderAndDirectCartesianVelocity(testCase)
            writetable(testCase.release,testCase.path);
            [actual,data]=oatof_read_cartesian_release(testCase.path,100,2);
            testCase.verifyEqual(actual,testCase.release);
            testCase.verifyEqual(data,testCase.release{:,4:9});
            [withoutCount,~]=oatof_read_cartesian_release(testCase.path,100);
            testCase.verifyEqual(withoutCount.particle_id,[17;3]);
        end
        function rejectsAngularTable(testCase)
            writematrix(ones(2,9),testCase.path);
            testCase.verifyError(@() oatof_read_cartesian_release(testCase.path,100,2),'oatof:CartesianColumns');
        end
        function rejectsDuplicateId(testCase)
            value=testCase.release; value.particle_id(:)=17; writetable(value,testCase.path);
            testCase.verifyError(@() oatof_read_cartesian_release(testCase.path,100,2),'oatof:CartesianIdentity');
        end
        function rejectsSpeciesMismatch(testCase)
            value=testCase.release; value.charge_state(2)=2; writetable(value,testCase.path);
            testCase.verifyError(@() oatof_read_cartesian_release(testCase.path,100,2),'oatof:CartesianSpecies');
        end
        function rejectsNonfiniteState(testCase)
            value=testCase.release; value.vz_m_per_s(2)=NaN; writetable(value,testCase.path);
            testCase.verifyError(@() oatof_read_cartesian_release(testCase.path,100,2),'oatof:CartesianValues');
        end
        function rejectsMissingParticle(testCase)
            writetable(testCase.release(1,:),testCase.path);
            testCase.verifyError(@() oatof_read_cartesian_release(testCase.path,100,2),'oatof:CartesianCount');
        end
        function rejectsTwoSourceFormatsBeforeNativeModelCreation(testCase)
            testCase.verifyError(@() run_oatof_model(FixedParticleTable="a.ion", ...
                CartesianRelease="a.csv",FieldDesignOnly=true),'oatof:ParticleSource');
        end
        function rejectsCartesianFullBuildWithoutOriginalIdCensus(testCase)
            testCase.verifyError(@() run_oatof_model(CartesianRelease="a.csv"),'oatof:CartesianBuildScope');
        end
    end
end
