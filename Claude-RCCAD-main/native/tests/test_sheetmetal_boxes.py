"""Short box walls and successive returns: corner material, clearance and edge picking."""
import math
import unittest
import numpy as np
from rccad import kernel as k, sheetmetal as s


def box_recipe(first='in', second=None, joint='parallel', gap=.2, levels=2):
    plate = k.box(100, 50, 2)
    top = next(f for f in plate.Faces() if abs(f.Center().z-2) < 1e-6)
    sheet = s.sheet_of_face(plate, top)
    edges = [([100,0,2],[100,50,2],[1,0,0]), ([100,50,2],[0,50,2],[0,1,0]),
             ([0,50,2],[0,0,2],[-1,0,0]), ([0,0,2],[100,0,2],[0,-1,0])]
    specs = [dict(kind='base',p0=a,p1=b,n=[0,0,1],m=m,r=2,angle=90,length=5) for a,b,m in edges]
    if levels >= 2:
        specs += [dict(kind='tip',parent=i,side=first,r=2,angle=90,length=5) for i in range(4)]
    if second is not None:
        specs += [dict(kind='tip',parent=i+4,side=second,r=2,angle=90,length=5) for i in range(4)]
    return dict(type='sheetbuild', base=sheet['base'],t=2,flanges=specs,rules=dict(joint=joint,gap=gap))


class BoxCornerTests(unittest.TestCase):
    def assertSolid(self, shape):
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids()), 1)

    def test_three_levels_all_directions_and_both_joints(self):
        for joint in ('parallel','diagonal'):
            for first in ('in','out'):
                for second in ('in','out'):
                    with self.subTest(joint=joint, first=first, second=second):
                        shape = s.build_sheet(box_recipe(first, second, joint))
                        self.assertSolid(shape)
                        # Both turn directions retain a complete third leg.
                        x,y = (92.7,41.3) if first == 'in' else (114.7,63.3)
                        z = 17 if second == 'out' else 6
                        self.assertEqual(k.point_state(shape,(x,y,z)), 'in')

    def test_each_click_can_build_four_sides_then_reverse_third_bends(self):
        for joint in ('parallel','diagonal'):
            recipe = box_recipe('in','out',joint)
            specs = recipe['flanges']
            for count in range(1,13):
                with self.subTest(joint=joint, count=count):
                    self.assertSolid(s.build_sheet(dict(recipe,flanges=specs[:count])))

    def test_inward_corner_has_material_in_both_rounded_transitions(self):
        for joint in ('parallel','diagonal'):
            shape = s.build_sheet(box_recipe('in',joint=joint))
            # Sample inside the bend, away from the new straight relief face.
            for point in ((101.5,50.5,11.5), (100.5,51.4,11.5)):
                with self.subTest(joint=joint,point=point):
                    self.assertEqual(k.point_state(shape,point),'in')

    def test_outward_returns_extend_to_close_all_four_corners(self):
        for joint in ('parallel','diagonal'):
            shape = s.build_sheet(box_recipe('out',joint=joint))
            for x,y in ((109,57),(107,59),(-9,57),(-7,59),(109,-7),(107,-9),(-9,-7),(-7,-9)):
                with self.subTest(joint=joint,point=(x,y)):
                    self.assertEqual(k.point_state(shape,(x,y,12)), 'in')

    def test_diagonal_clearance_is_requested_gap_not_radius_plus_gap(self):
        normal = np.array([1,-1,0])/math.sqrt(2)
        for gap in (.1,.5,1.):
            shape = s.build_sheet(box_recipe('out',joint='diagonal',gap=gap))
            center = np.array([108.5,58.5,12])
            self.assertEqual(k.point_state(shape,center), 'out')
            for sign in (-1,1):
                point = center + sign*(gap/2+.02)*normal
                self.assertEqual(k.point_state(shape,point), 'in')

    def test_butt_clearance_is_requested_gap_at_current_leg(self):
        # Measure along the real skin normal, including a circular bend.
        # Translation along X alone would under-measure the clearance here.
        for first,point,normal in [('in',np.array([95,47,12]),np.array([-1,0,0])),
                                   ('out',np.array([106-math.sqrt(7),58,12]),np.array([-math.sqrt(7)/4,0,.75]))]:
            for gap in (.1,.5,1.):
                with self.subTest(first=first,gap=gap):
                    shape=s.build_sheet(box_recipe(first,gap=gap))
                    self.assertEqual(k.point_state(shape,point+gap/2*normal),'out')
                    self.assertEqual(k.point_state(shape,point-.02*normal),'in')
                    self.assertEqual(k.point_state(shape,point+(gap+.02)*normal),'in')

    def test_rotation_and_translation_do_not_change_corner_solution(self):
        recipe = box_recipe('in','out','diagonal')
        original = s.build_sheet(recipe)
        axis = np.array([1,2,3])/math.sqrt(14);angle = math.radians(37)
        cross = np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
        rotation = np.eye(3)*math.cos(angle)+(1-math.cos(angle))*np.outer(axis,axis)+math.sin(angle)*cross
        translation = np.array([17,-8,31])
        base = dict(recipe['base'])
        base['o'] = (rotation@np.array(base['o'])+translation).tolist()
        for key in ('x','y','z'):base[key]=(rotation@np.array(base[key])).tolist()
        specs = []
        for spec in recipe['flanges']:
            spec = dict(spec)
            if spec['kind'] == 'base':
                for key in ('p0','p1'):spec[key]=(rotation@np.array(spec[key])+translation).tolist()
                for key in ('n','m'):spec[key]=(rotation@np.array(spec[key])).tolist()
            specs.append(spec)
        actual = s.build_sheet(dict(recipe,base=base,flanges=specs))
        expected = original.rotate((0,0,0),tuple(axis),37).translate(tuple(translation))
        self.assertSolid(actual)
        self.assertAlmostEqual(actual.Volume(),expected.Volume(),delta=.001)
        self.assertLess(actual.cut(expected).Volume()+expected.cut(actual).Volume(), .001)

    def test_different_return_angles_do_not_require_equal_legs(self):
        recipe = box_recipe('out',joint='diagonal')
        for spec,angle in zip(recipe['flanges'][4:],(30,60,90,120)):spec['angle']=angle
        self.assertSolid(s.build_sheet(recipe))

    def test_inclined_matching_returns_use_neighbor_surface_for_parallel_joint(self):
        for angle in (30,60,120):
            with self.subTest(angle=angle):
                recipe = box_recipe('out')
                for spec in recipe['flanges'][4:]:spec['angle']=angle
                parallel = s.build_sheet(recipe)
                recipe['rules']['joint']='diagonal'
                diagonal = s.build_sheet(recipe)
                self.assertSolid(parallel)
                self.assertSolid(diagonal)
                recipe['rules']['joint']='parallel'
                frames,corners=s._effective(recipe['flanges'],2,True)
                parts=s._corner_parts(recipe,frames,corners)
                peer_normal=s._tip_geom(frames[5],'out',2)[2]
                self.assertTrue(any(face.geomType()=='PLANE' and
                                    abs(float(np.array(face.normalAt().toTuple())@peer_normal))>1-1e-6
                                    for face in parts[4][1].Faces()))

    def test_adding_another_level_does_not_change_existing_attachment_frames(self):
        recipe = box_recipe('out','in')
        short,_ = s._effective(recipe['flanges'][:8],2,True)
        long,_ = s._effective(recipe['flanges'],2,True)
        for a,b in zip(short,long):
            for key in ('p0','p1','n','m'):np.testing.assert_allclose(a[key],b[key],atol=1e-9)

    def test_extended_free_edge_can_be_selected_beyond_original_base_width(self):
        plate = k.box(10,8,1)
        top = next(f for f in plate.Faces() if abs(f.Center().z-1)<1e-6)
        sheet = s.sheet_of_face(plate,top)
        specs = [dict(kind='base',p0=[10,0,1],p1=[10,8,1],n=[0,0,1],m=[1,0,0],r=1,angle=90,length=5),
                 dict(kind='base',p0=[10,8,1],p1=[0,8,1],n=[0,0,1],m=[0,1,0],r=1,angle=90,length=5),
                 dict(kind='tip',parent=0,side='out',r=1,angle=90,length=20),
                 dict(kind='tip',parent=1,side='out',r=1,angle=90,length=20)]
        recipe = dict(base=sheet['base'],t=1,flanges=specs,rules=dict(gap=.2))
        shape = s.build_sheet(recipe)
        self.assertSolid(shape)
        frames,_ = s._effective(specs,1,True)
        point,_,normal,direction = s._tip_geom(frames[2],'out',1)
        candidates = []
        for edge in shape.Edges():
            a,b = np.array(edge.startPoint().toTuple()),np.array(edge.endPoint().toTuple())
            if (abs(float((a-point)@normal))<1e-5 and abs(float((b-point)@normal))<1e-5
                    and abs(float((a-point)@direction))<1e-5 and abs(float((b-point)@direction))<1e-5):
                candidates.append(edge)
        edge = max(candidates,key=lambda e:e.Length())
        midpoint = edge.positionAt(.5).toTuple()
        self.assertGreater(midpoint[1],8)
        found = s.spec_for_edge(recipe['base'],1,specs,recipe['rules'],midpoint,.01)
        self.assertEqual(found,dict(kind='tip',parent=2,side='out'))
        self.assertAlmostEqual(shape.BoundingBox().xmin,0,delta=1e-4)
        self.assertAlmostEqual(shape.BoundingBox().ymin,0,delta=1e-4)

    def test_real_collisions_and_consumed_free_ends_are_still_rejected(self):
        recipe = box_recipe('in','in')
        for spec in recipe['flanges'][8:]:spec['length']=20
        with self.assertRaises(k.CadError):s.build_sheet(recipe)
        recipe = box_recipe('in')
        for spec in recipe['flanges'][4:]:spec['length']=150
        with self.assertRaises(k.CadError):s.build_sheet(recipe)


if __name__ == '__main__':
    unittest.main()
