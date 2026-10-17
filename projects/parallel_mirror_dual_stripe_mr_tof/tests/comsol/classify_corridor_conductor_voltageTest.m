classdef classify_corridor_conductor_voltageTest < matlab.unittest.TestCase
    % Pure resolved-CSG tests; no COMSOL, artifacts, grids or field solve.
    methods (TestClassSetup)
        function add_source(testCase)
            project = fileparts(fileparts(fileparts(mfilename('fullpath'))));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(project,'comsol')));
        end
    end
    methods (Test)
        function tilted_polygons_not_aabb_and_rotated_holes(testCase)
            [g,v,a,c] = fixture();
            g.mirror_convergence_transform = struct('solid_representation','extruded_yz_polygon');
            g.mirror_electrodes = struct('id',1,'x',[0,2], ...
                'box',[0,20,0,2,24,2], ...
                'polygon_yz_mm',[20,0;22,0;24,2;22,2], ...
                'holes',struct('x',[0,.2],'polygon_yz_mm',[20.5,.5;21.5,.5;22.5,1.5;21.5,1.5]));
            g.mirror_ground_shields = struct('role','inner_stripe_facing_4mm_slot', ...
                'x',[0,2],'box',[0,30,0,2,34,2], ...
                'polygon_yz_mm',[30,0;32,0;34,2;32,2], ...
                'holes',struct('x',[0,.2],'polygon_yz_mm',[30.5,.5;31.5,.5;32.5,1.5;31.5,1.5]));
            g.mirror_e_closures = struct('id',5,'x',[0,2], ...
                'box',[0,40,0,2,44,2],'polygon_yz_mm',[40,0;42,0;44,2;42,2],'holes',[]);
            v(1)=11;v(5)=55;
            [V,id] = classify_corridor_conductor_voltage( ...
                [1,22,1;.1,22,1;1,20.1,1.9;1,32,1;.1,32,1;1,30.1,1.9;1,42,1;1,40.1,1.9],g,v,a,c);
            testCase.verifyEqual(V([1,4,7]),[11;-10;55],'AbsTol',1e-12);
            testCase.verifyTrue(all(isnan(V([2,3,5,6,8]))));
            testCase.verifyEqual(id,[1;0;0;15;0;0;5;0]);
        end
        function missing_tilt_polygon_fails_without_box_fallback(testCase)
            [g,v,a,c] = fixture();
            g.mirror_convergence_transform = struct('solid_representation','extruded_yz_polygon');
            testCase.verifyError(@() classify_corridor_conductor_voltage([1,21,1],g,v,a,c), ...
                'MRTOF:MissingMirrorPolygon');
        end
        function enclosure_and_holes(testCase)
            [g,v,a,c] = fixture();
            [V,id,ns] = classify_corridor_conductor_voltage( ...
                [2.5,0,4;0,0,4;0,0,.5;3,0,4],g,v,a,c);
            testCase.verifyEqual(V(1),0,'AbsTol',1e-12);
            testCase.verifyTrue(all(isnan(V(2:4))));
            testCase.verifyEqual(id,[15;0;0;0]);
            testCase.verifyEqual(ns,["accelerator";"";"";""]);
        end
        function ring_and_support_apertures(testCase)
            [g,v,a,c] = fixture();
            [V,id] = classify_corridor_conductor_voltage( ...
                [1.5,0,2.1;0,0,2.1;1.5,0,5.1;0,0,5.1],g,v,a,c);
            testCase.verifyEqual(V([1,3]),[100;50],'AbsTol',1e-12);
            testCase.verifyTrue(all(isnan(V([2,4]))));
            testCase.verifyEqual(id,[23;0;26;0]);
        end
        function zero_thickness_sheet(testCase)
            [g,v,a,c] = fixture();
            [V,id] = classify_corridor_conductor_voltage( ...
                [0,0,2;.5,.5,2;0,0,2+eps(2);1,0,2],g,v,a,c);
            testCase.verifyEqual(V(1:2),[100;100],'AbsTol',1e-12);
            testCase.verifyTrue(all(isnan(V(3:4))));
            testCase.verifyEqual(id,[23;23;0;0]);
        end
        function repeller_and_detector_mirror(testCase)
            [g,v,a,c] = fixture();
            [V,id,ns] = classify_corridor_conductor_voltage( ...
                [0,0,8.6;.5,-4.5,2.5;-.5,-4.5,2.5],g,v,a,c);
            testCase.verifyEqual(V,[200;0;0],'AbsTol',1e-12);
            testCase.verifyEqual(id,[22;25;25]);
            testCase.verifyEqual(ns,["accelerator";"detector";"detector"]);
        end
        function same_numeric_id_different_namespace(testCase)
            [g,v,a,c] = fixture();
            [V,id,ns] = classify_corridor_conductor_voltage([1,21,1;2.5,0,4],g,v,a,c);
            testCase.verifyEqual(V,[-10;0],'AbsTol',1e-12);
            testCase.verifyEqual(id,[15;15]);
            testCase.verifyEqual(ns,["analyzer";"accelerator"]);
        end
        function cross_component_overlap_is_unknown(testCase)
            [g,v,a,c] = fixture();
            a.detector.box=[-1,-1,8.55,1,1,8.65];
            [V,id,ns] = classify_corridor_conductor_voltage([0,0,8.6],g,v,a,c);
            testCase.verifyTrue(isnan(V));
            testCase.verifyEqual(id,0);
            testCase.verifyEqual(ns,"");
        end
        function unknown_and_exposed_detector_surface(testCase)
            [g,v,a,c] = fixture();
            [V,id,ns] = classify_corridor_conductor_voltage([0,100,100;0,-4.5,3],g,v,a,c);
            testCase.verifyTrue(all(isnan(V)));
            testCase.verifyEqual(id,[0;0]);
            testCase.verifyEqual(ns,["";""]);
        end
        function missing_namespaced_voltage_fails(testCase)
            [g,v,a,c] = fixture();
            c(3)=[];
            testCase.verifyError(@() classify_corridor_conductor_voltage([0,0,2],g,v,a,c), ...
                'MRTOF:ComponentVoltage');
        end
        function translated_resolved_projection(testCase)
            [g,v,a,c] = fixture();
            a.accelerator_resolved_electrodes.local_to_pa_translation_mm=[0,7,0];
            a.accelerator_iob_origin_mm=[0,-12,-3];
            [V,id,ns] = classify_corridor_conductor_voltage([0,-5,-1],g,v,a,c);
            testCase.verifyEqual(V,100,'AbsTol',1e-12);
            testCase.verifyEqual(id,23);
            testCase.verifyEqual(ns,"accelerator");
        end
    end
end

function [g,v,a,c] = fixture()
% Small explicit resolved projection, deliberately unlike an MR workpoint.
g=struct('mirror_electrodes',struct('id',15,'box',[0,20,0,2,22,2], ...
    'beam_slot',[0,20,.5,.2,22,1.5]),'mirror_ground_shields',[], ...
    'mirror_e_closures',[],'stripe_electrodes',[],'central_ground_electrodes',[], ...
    'prism_electrodes',[],'prism_ground_shields',[]);
v=zeros(20,1);v(15)=-10;
oa=struct('schema_version',1,'coordinate_frame','accelerator_centered_transverse_local_z_mm', ...
    'acceleration_direction','-z','local_to_pa_translation_mm',[0,0,0], ...
    'grounded_enclosure',struct('component_electrode_id',15, ...
        'outer_box_mm',box([-3,-3,0,3,3,10]), ...
        'cavity_box_mm',box([-2,-2,0,2,2,9]), ...
        'exit_opening_box_mm',box([-1,-1,0,1,1,1])), ...
    'repeller',struct('component_electrode_id',22,'solid_box_mm',box([-2,-2,8.5,2,2,8.7])), ...
    'grid_supports',struct('component_electrode_id',23,'transmission','ideal_transparent', ...
        'frame_outer_box_mm',box([-2,-2,2,2,2,2.2]), ...
        'aperture_box_mm',box([-1,-1,2,1,1,2.2]), ...
        'ideal_sheet_mm',struct('x_min_mm',-1,'x_max_mm',1,'y_min_mm',-1,'y_max_mm',1,'z_mm',2)), ...
    'rings',struct('component_electrode_id',26, ...
        'outer_box_mm',box([-2,-2,5,2,2,5.2]),'aperture_box_mm',box([-1,-1,5,1,1,5.2])));
a=struct('accelerator_resolved_electrodes',oa,'accelerator_iob_origin_mm',[0,0,0], ...
    'detector',struct('id',25,'separate_pa',true,'box',[-2,-5,2,2,-4,3]));
c=struct('component_namespace',{'accelerator','accelerator','accelerator','accelerator','detector'}, ...
    'component_electrode_id',{15,22,23,26,25},'voltage_v',{0,200,100,50,0});
end

function b=box(v)
b=struct('x_min_mm',v(1),'y_min_mm',v(2),'z_min_mm',v(3), ...
    'x_max_mm',v(4),'y_max_mm',v(5),'z_max_mm',v(6));
end
