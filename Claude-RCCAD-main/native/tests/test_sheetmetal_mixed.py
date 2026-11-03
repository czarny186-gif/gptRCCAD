"""Diverging returns must not inherit an imaginary shared 45-degree corner."""
import unittest
import numpy as np
from rccad import kernel as k, sheetmetal as s


def mixed_recipe(joint='diagonal'):
    plate = k.box(38,78,1)
    face = next(f for f in plate.Faces() if abs(f.Center().z-1)<1e-6)
    base = s.sheet_of_face(plate,face)['base']
    edges = [([0,0,1],[38,0,1],[0,-1,0]),([0,78,1],[0,0,1],[-1,0,0]),
             ([38,78,1],[38,0,1],[1,0,0]),([0,78,1],[38,78,1],[0,1,0])]
    specs = [dict(kind='base',p0=a,p1=b,n=[0,0,1],m=m,r=1,angle=90,length=5) for a,b,m in edges]
    for parent,side in ((1,'in'),(0,'out'),(2,'in'),(3,'in'),(7,'out'),(8,'out'),
                        (4,'out'),(10,'out'),(6,'out'),(12,'in')):
        specs.append(dict(kind='tip',parent=parent,side=side,r=1,angle=90,length=5))
    return dict(base=base,t=1,flanges=specs,rules=dict(joint=joint,gap=.5,relief='square',relief_size=1))


class MixedReturnsTests(unittest.TestCase):
    def assertStraightEnd(self,eff,parts,corners,index,root,neighbor,t):
        P = next(P for P,a,b,_ in corners if {a,b} == {root,neighbor})
        axis = s._unit(eff[root]['p1']-eff[root]['p0'])
        outward = axis if np.linalg.norm(P-eff[root]['p1'])<np.linalg.norm(P-eff[root]['p0']) else -axis
        point,_,normal,direction = s._tip_geom(eff[index],'out',t)
        vertices = [np.array(v.toTuple()) for v in parts[index][-1].Vertices()]
        endpoints = []
        for distance in (0,eff[index]['length']):
            plane = point-distance*direction
            candidates = [v for v in vertices if abs(float((v-plane)@normal))<1e-5
                          and abs(float((v-plane)@direction))<1e-5]
            self.assertTrue(candidates,'The requested straight leg must retain its full length.')
            endpoints.append(max(float((v-P)@outward) for v in candidates))
        # A forced miter changes this coordinate by the leg length (5 mm).
        self.assertAlmostEqual(endpoints[0],endpoints[1],delta=1e-5)

    def test_three_inward_one_outward_with_later_reversals(self):
        for joint in ('parallel','diagonal'):
            with self.subTest(joint=joint):
                recipe = mixed_recipe(joint)
                shape = s.build_sheet(recipe)
                self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
                eff,corners = s._effective(recipe['flanges'],1,True)
                parts = s._corner_parts(recipe,eff,corners)
                for index,root,neighbor in ((4,1,0),(5,0,1),(6,2,0),(10,1,0),
                                            (11,1,0),(12,2,0),(13,2,0)):
                    self.assertStraightEnd(eff,parts,corners,index,root,neighbor,1)

    def test_any_of_four_sides_can_diverge_without_cutting_straight_returns(self):
        for divergent in range(4):
            with self.subTest(side=divergent):
                recipe = mixed_recipe()
                specs = recipe['flanges'][:4]
                specs += [dict(kind='tip',parent=i,side='out' if i==divergent else 'in',r=1,angle=90,length=5) for i in range(4)]
                recipe['flanges']=specs
                shape = s.build_sheet(recipe)
                self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
                eff,corners = s._effective(specs,1,True)
                parts = s._corner_parts(recipe,eff,corners)
                for _,a,b,_ in corners:
                    if divergent in (a,b):
                        self.assertStraightEnd(eff,parts,corners,4+a,a,b,1)
                        self.assertStraightEnd(eff,parts,corners,4+b,b,a,1)

    def test_individual_steps_remain_connected_for_mixed_chain(self):
        recipe = mixed_recipe()
        for count in range(1,len(recipe['flanges'])+1):
            with self.subTest(step=count):
                shape = s.build_sheet(dict(recipe,flanges=recipe['flanges'][:count]))
                self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)


if __name__ == '__main__':
    unittest.main()
