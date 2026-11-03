"""Sheet-metal corner construction: square walls, mitred flanges and curved reliefs."""
import copy
import math
import unittest
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from rccad import kernel as k, sheetmetal as s


def folded_fixture(reference=True):
    # Physical tangent segments measured from a reference part, not a new
    # interpretation of user-entered panel lengths.
    width,depth,radius = (96,46,1) if reference else (100,50,.5)
    x,y = (-48,2) if reference else (-50,0)
    plate = cq.Solid.makeBox(width,depth,1,cq.Vector(x,y,0))
    top = next(f for f in plate.Faces() if abs(f.Center().z-1)<1e-6)
    base = s.sheet_of_face(plate,top)['base']
    edges = [([x,y,1],[x+width,y,1],[0,-1,0]),([x,y+depth,1],[x,y,1],[-1,0,0]),
             ([x+width,y,1],[x+width,y+depth,1],[1,0,0]),([x+width,y+depth,1],[x,y+depth,1],[0,1,0])]
    specs = [dict(kind='base',p0=a,p1=b,n=[0,0,1],m=m,r=radius,angle=90,length=6 if reference else 10) for a,b,m in edges]
    for parent,side,length in [(0,'in',6),(1,'in',6),(2,'in',6),(3,'out',6),
                               (4,'out',6),(5,'out',8),(6,'out',8),(7,'in',8),(8,'out',8)]:
        specs.append(dict(kind='tip',parent=parent,side=side,r=radius,angle=90,length=length if reference else 10))
    return dict(base=base,t=1,flanges=specs,rules=dict(joint='sheet',gap=1 if reference else .5))


class SheetJointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipe = folded_fixture()
        cls.shape = s.build_sheet(cls.recipe)
        cls.frames,cls.corners = s._effective(cls.recipe['flanges'],1,True)
        cls.parts = s._corner_parts(cls.recipe,cls.frames,cls.corners)

    def test_upright_panels_have_square_ends_even_at_different_heights(self):
        first = self.parts[0][1]
        caps = [f for f in first.Faces() if abs(f.normalAt().x)>.99999]
        self.assertEqual(len(caps),2)
        self.assertAlmostEqual(max(f.Center().x for f in caps),48.292893218813,delta=1e-5)
        self.assertAlmostEqual(min(f.Center().x for f in caps),-48.292893218813,delta=1e-5)
        taller = self.parts[9][1]
        caps = [f for f in taller.Faces() if abs(f.normalAt().y)>.99999]
        self.assertEqual(len(caps),2)
        self.assertAlmostEqual(min(f.Center().y for f in caps),10.707106781187,delta=1e-5)
        self.assertAlmostEqual(max(f.Center().y for f in caps),48.292893218813,delta=1e-5)

    def test_horizontal_neighboring_flanges_keep_diagonal_joint(self):
        normals = [f.normalAt() for f in self.parts[4][1].Faces() if f.geomType()=='PLANE']
        self.assertTrue(any(abs(abs(n.x)-math.sqrt(.5))<1e-5 and abs(abs(n.y)-math.sqrt(.5))<1e-5 for n in normals))

    def test_relief_follows_the_arc_between_panel_ends(self):
        q = math.sqrt(.5)
        for index,x,y,z in [(4,-48,2-1.5*q,8+1.5*q),
                            (8,-41.292893218813+2*q,8+1.5*q,11-1.5*q)]:
            with self.subTest(bend=index):
                self.assertEqual(k.point_state(self.parts[index][0],(x+.02,y,z)),'in')
                self.assertEqual(k.point_state(self.parts[index][0],(x-.02,y,z)),'out')

    def test_round_bend_surfaces_and_thickness_are_preserved(self):
        radii = [BRepAdaptor_Surface(f.wrapped).Cylinder().Radius() for f in self.shape.Faces() if f.geomType()=='CYLINDER']
        self.assertEqual(len(radii),26)
        self.assertEqual({round(r,6) for r in radii},{1,2})
        self.assertEqual(sum(f.geomType()=='BSPLINE' for f in self.shape.Faces()),8)
        self.assertTrue(self.shape.isValid());self.assertEqual(len(self.shape.Solids()),1)
        self.assertAlmostEqual(self.shape.Volume(1e-9),12352.593,delta=.1)

    def test_first_bend_does_not_grow_artificial_corner_bulges(self):
        bb = self.parts[0][0].BoundingBox()
        self.assertAlmostEqual(bb.xmin,-48,delta=1e-5)
        self.assertAlmostEqual(bb.xmax,48,delta=1e-5)

    def test_existing_length_and_base_dimension_policy_is_unchanged(self):
        recipe = folded_fixture(False);original = copy.deepcopy(recipe)
        shape = s.build_sheet(recipe);bb = shape.BoundingBox()
        self.assertEqual(recipe,original)
        self.assertAlmostEqual(bb.xlen,103,delta=1e-5)
        self.assertAlmostEqual(bb.ylen,65,delta=1e-5)
        self.assertAlmostEqual(bb.zlen,25,delta=1e-5)
        eff,_ = s._effective(recipe['flanges'],1,True)
        self.assertTrue(all(f['length']==10 for f in eff))

    def test_middle_bending_profiles_are_unchanged_by_corner_style(self):
        recipe = folded_fixture(False)
        new = s.build_sheet(recipe)
        recipe['rules']['joint']='diagonal'
        old = s.build_sheet(recipe)
        def edges(shape,plane,origin):
            section=cq.Workplane(plane,origin=origin).add(shape).section(0).val()
            return sorted((e.geomType(),round(e.Length(),5),
                           tuple(round(v,5) for v in e.Center().toTuple())) for e in section.Edges())
        self.assertEqual(edges(old,'XZ',(0,25,0)),edges(new,'XZ',(0,25,0)))
        self.assertEqual(edges(old,'YZ',(0,0,0)),edges(new,'YZ',(0,0,0)))

    def test_short_box_three_levels_accepts_all_turn_directions(self):
        from test_sheetmetal_boxes import box_recipe
        for first in ('in','out'):
            for last in ('in','out'):
                with self.subTest(first=first,last=last):
                    recipe = box_recipe(first,last);recipe['rules']['joint']='sheet'
                    shape = s.build_sheet(recipe)
                    self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)

    def test_diverging_returns_still_keep_straight_ends(self):
        from test_sheetmetal_mixed import mixed_recipe, MixedReturnsTests
        recipe = mixed_recipe();recipe['rules']['joint']='sheet'
        shape = s.build_sheet(recipe)
        self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
        eff,corners = s._effective(recipe['flanges'],1,True)
        parts = s._corner_parts(recipe,eff,corners)
        check = MixedReturnsTests()
        for index,root,neighbor in ((4,1,0),(5,0,1),(6,2,0),(10,1,0),(11,1,0),(12,2,0),(13,2,0)):
            check.assertStraightEnd(eff,parts,corners,index,root,neighbor,1)


if __name__ == '__main__':
    unittest.main()
