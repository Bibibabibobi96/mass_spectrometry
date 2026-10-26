classdef OaTofPairedAcceleratorPulseTest < matlab.unittest.TestCase
    % Pure input rejection at the real backend before any vendor model load.
    properties
        root
        plan
        source
    end
    methods (TestMethodSetup)
        function prepare(testCase)
            project=fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(project,'comsol')));
            fixture=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            testCase.root=fixture.Folder;
            testCase.source=array2table([17,100,1,-14,0,-18,3000,-45,90,5; ...
                3,100,1,-13,1,-19,-2000,81,-93,3], ...
                'VariableNames',{'particle_id','mass_amu','charge_state','x_mm','y_mm','z_mm', ...
                'vx_m_per_s','vy_m_per_s','vz_m_per_s','kinetic_energy_eV'});
            sourcePath=fullfile(testCase.root,'source.csv'); writetable(testCase.source,sourcePath);
            binding=struct('accelerator_repeller_id',11,'grounded_shield_id',12, ...
                'accelerator_grid1_id',13,'accelerator_intermediate2_id',14, ...
                'accelerator_grid2_id',15,'accelerator_ring_ids',16:35);
            voltages=cell2struct(num2cell(zeros(1,25)),arrayfun(@(id) sprintf('x%d',id),11:35,'UniformOutput',false),2);
            static=struct('schema_version',2,'role','oatof_paired_accelerator_static_field_plan', ...
                'accelerator_variant','three_zone_square','oatof_instance_id','oa', ...
                'composition_plan',struct('scope',struct('instance_ids',{{'oa'}})), ...
                'numerical_domain',struct('boundary_policy','native_zero_neumann','comsol_outer_boundary','zero_charge'), ...
                'native_geometry_compilation',struct('electrode_bindings',struct('oa',binding)), ...
                'static_on_electrode_voltages_v',voltages);
            staticPath=fullfile(testCase.root,'static.json'); testCase.writeJson(staticPath,static);
            record=@(path) struct('path',path,'bytes',0,'sha256',repmat('0',1,64));
            testCase.plan=struct('schema_version',1,'role','paired_accelerator_pulse_plan', ...
                'static_plan',record(staticPath),'model',record(fullfile(testCase.root,'never_load.mph')), ...
                'source_csv',record(sourcePath),'particle_count',2,'mass_amu',100,'mass_kg',1e-25, ...
                'charge_state',1,'source_time_us',50,'pulse',struct('on_us',50,'off_us',57), ...
                'observation_times_us',[50,57,58],'off_electrode_voltages_v',voltages, ...
                'numerics',struct('maximum_step_us',0.001,'relative_tolerance',1e-6,'absolute_tolerance',1e-8));
        end
    end
    methods (Test)
        function rejectsMissingPulseEdge(testCase)
            testCase.plan.observation_times_us=[50,56,58];
            testCase.rejects('oatof:PairedPulseTimes');
        end
        function rejectsClockReset(testCase)
            testCase.plan.observation_times_us=[0,50,57,58];
            testCase.rejects('oatof:PairedPulseTimes');
        end
        function rejectsReversedPulse(testCase)
            testCase.plan.pulse.off_us=49;
            testCase.rejects('oatof:PairedPulseTimes');
        end
        function rejectsNoObservationAfterOff(testCase)
            testCase.plan.observation_times_us=[50,51,57];
            testCase.rejects('oatof:PairedPulseTimes');
        end
        function rejectsNullStepInsteadOfSilentlyOmittingIt(testCase)
            testCase.plan.numerics.maximum_step_us=[];
            testCase.rejects('oatof:PairedPulseNumerics');
        end
        function rejectsNonpositiveSolverTolerance(testCase)
            testCase.plan.numerics.relative_tolerance=0;
            testCase.rejects('oatof:PairedPulseNumerics');
        end
        function rejectsUnsupportedCharge(testCase)
            testCase.plan.charge_state=2;
            testCase.rejects('oatof:PairedPulseSpecies');
        end
        function rejectsNonzeroOffWithoutInventingAnotherField(testCase)
            testCase.plan.off_electrode_voltages_v.x13=1;
            testCase.rejects('oatof:PairedPulseOff');
        end
        function rejectsMissingRealElectrode(testCase)
            testCase.plan.off_electrode_voltages_v=rmfield(testCase.plan.off_electrode_voltages_v,'x35');
            testCase.rejects('oatof:PairedPulseOff');
        end
        function rejectsMissingOriginalParticle(testCase)
            writetable(testCase.source(1,:),testCase.plan.source_csv.path);
            testCase.rejects('oatof:CartesianCount');
        end
        function rejectsDuplicateOriginalId(testCase)
            testCase.source.particle_id(:)=17;
            writetable(testCase.source,testCase.plan.source_csv.path);
            testCase.rejects('oatof:CartesianIdentity');
        end
        function rejectsChangedSpecies(testCase)
            testCase.source.mass_amu(2)=101;
            writetable(testCase.source,testCase.plan.source_csv.path);
            testCase.rejects('oatof:CartesianSpecies');
        end
    end
    methods (Access=private)
        function rejects(testCase,identifier)
            path=fullfile(testCase.root,'plan.json'); testCase.writeJson(path,testCase.plan);
            output=fullfile(testCase.root,'not_created');
            testCase.verifyError(@() run_paired_accelerator_pulse(path,output),identifier);
            testCase.verifyFalse(isfolder(output));
        end
        function writeJson(~,path,value)
            fid=fopen(path,'w'); cleanup=onCleanup(@() fclose(fid)); %#ok<NASGU>
            fprintf(fid,'%s\n',jsonencode(value));
        end
    end
end
