"""Synthetic streaming checks of the production invalid-node classifier."""
import copy
import math
import unittest
from msplatform.backends.comsol.assembly_scalar_fill import InvalidNodeClassifier


def fixture():
    pose={'schema_version':1,'role':'rigid_transform','from_frame_id':'local','to_frame_id':'world','rotation':[[1,0,0],[0,1,0],[0,0,1]],'translation_mm':[0,0,0]}
    body={'kind':'difference','base':{'kind':'box','center_mm':[0,0,0],'size_mm':[2.5,2.5,2.5]},'tools':[{'kind':'cylinder','center_mm':[0,0,0],'radius_mm':0.25,'height_mm':3}]}
    sheet={'kind':'box','center_mm':[2,0,0],'size_mm':[0,2,2]}
    members=[{'instance_id':'oa','member_id':'body','electrode_group_id':'metal','representation_role':'physical_solid','shape':body,'transform':pose},
             {'instance_id':'oa','member_id':'grid','electrode_group_id':'sheet','representation_role':'ideal_surface','shape':sheet,'transform':pose}]
    projection={'assembly_frame_id':'world','members':members,'electrode_groups':[{'instance_id':'oa','electrode_group_id':'metal','member_ids':['body']},{'instance_id':'oa','electrode_group_id':'sheet','member_ids':['grid']}]}
    request={'group_voltages':[{'instance_id':'oa','electrode_group_id':'sheet','voltage_v':0},{'instance_id':'oa','electrode_group_id':'metal','voltage_v':-100}]}
    grid={'frame_id':'world','origin_mm':[-2,-1,-1],'pitch_mm':[1,1,1],'dimensions':[5,3,3],'point_count':45}
    return projection,request,grid


class ScalarInteriorTests(unittest.TestCase):
    def test_streamed_hole_metal_sheet_and_vacuum(self):
        projection,request,grid=fixture();before=copy.deepcopy((projection,request,grid));node=( {'index':21+i,'world_mm':[-2+i,0,0]} for i in range(5))
        classifier=InvalidNodeClassifier(projection,request,grid);result=list(classifier.classify(node))
        self.assertEqual([row['classification'] for row in result],['outside','interior','outside','interior','boundary'])
        self.assertEqual([row['voltage_v'] for row in result if 'voltage_v' in row],[-100.,-100.])
        self.assertEqual(dict(classifier.counts),{'outside':2,'interior':2,'boundary':1})
        self.assertEqual((projection,request,grid),before)
    def test_group_native_ids_are_irrelevant_and_snapshot_isolated(self):
        projection,request,grid=fixture();projection['native_ids']={'metal':1,'sheet':2}
        a=InvalidNodeClassifier(projection,request,grid);projection['native_ids']={'metal':999,'sheet':3};b=InvalidNodeClassifier(projection,request,grid)
        request['group_voltages'][1]['voltage_v']=999
        rows=[{'index':22,'world_mm':[-1,0,0]}]
        self.assertEqual(list(a.classify(rows)),list(b.classify(rows)))
        self.assertEqual(list(a.classify(rows))[0]['voltage_v'],-100.)
    def test_missing_voltage_groups_indices_and_coordinates_refuse(self):
        projection,request,grid=fixture()
        with self.assertRaisesRegex(ValueError,'coverage'):InvalidNodeClassifier(projection,{'group_voltages':request['group_voltages'][:1]},grid)
        broken=copy.deepcopy(projection);broken['electrode_groups'][0]['member_ids'].append('missing')
        with self.assertRaisesRegex(ValueError,'member coverage'):InvalidNodeClassifier(broken,request,grid)
        classifier=InvalidNodeClassifier(projection,request,grid)
        for nodes in ([{'index':22,'world_mm':[0,0,0]}],[{'index':46,'world_mm':[0,0,0]}],[{'index':22,'world_mm':[-1,0,0]},{'index':22,'world_mm':[-1,0,0]}]):
            with self.subTest(nodes=nodes),self.assertRaises(ValueError):list(classifier.classify(nodes))
    def test_overlap_refuses_and_unsupported_never_fills(self):
        projection,request,grid=fixture();other=copy.deepcopy(projection['members'][0]);other.update(member_id='other',electrode_group_id='other')
        projection['members'].append(other);projection['electrode_groups'].append({'instance_id':'oa','electrode_group_id':'other','member_ids':['other']});request['group_voltages'].append({'instance_id':'oa','electrode_group_id':'other','voltage_v':1})
        with self.assertRaisesRegex(ValueError,'different electrode groups'):list(InvalidNodeClassifier(projection,request,grid).classify([{'index':22,'world_mm':[-1,0,0]}]))
        other['shape']={'kind':'unknown'}
        row=list(InvalidNodeClassifier(projection,request,grid).classify([{'index':22,'world_mm':[-1,0,0]}]))[0]
        self.assertEqual(row,{'index':22,'classification':'unsupported'})
    def test_near_boundary_never_fills(self):
        projection,request,grid=fixture();grid.update(origin_mm=[1.25,0,0],pitch_mm=[1,1,1],dimensions=[2,2,2],point_count=8)
        for x in (math.nextafter(1.25,-math.inf),1.25,math.nextafter(1.25,math.inf)):
            grid['origin_mm']=[x,0,0]
            row=list(InvalidNodeClassifier(projection,request,grid).classify([{'index':1,'world_mm':[x,0,0]}]))[0]
            with self.subTest(x=x): self.assertEqual(row,{'index':1,'classification':'boundary'})

if __name__=='__main__': unittest.main()
