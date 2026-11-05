"""Reference-style square roots and constant planes on inward parallel chains."""
import copy
import math
import unittest
import numpy as np
import cadquery as cq
from rccad import sheetmetal as s,sheetedit as e,kernel as k
from test_sheetmetal_parallel import small_box


def reference_box():
    r=small_box(90,3)
    for f in r['flanges'][8:]:f['side']='in'
    return r


class ReferenceParallelTests(unittest.TestCase):
    def same(self,left,right):
        self.assertLess(left.cut(right).Volume(1e-9)+right.cut(left).Volume(1e-9),1e-4)

    def test_both_first_walls_have_square_near_skin_ends(self):
        r=reference_box();frames,corners=s._effective(r['flanges'],1,True);parts=s._corner_parts(r,frames,corners)
        right=k.bounds(parts[0][1]);back=k.bounds(parts[1][1])
        self.assertAlmostEqual(right.ymin,-.3,delta=1e-6)
        self.assertAlmostEqual(right.ymax,50.3,delta=1e-6)
        self.assertAlmostEqual(back.xmin,-.3,delta=1e-6)
        self.assertAlmostEqual(back.xmax,100.3,delta=1e-6)
        for i in (4,8):
            bounds=k.bounds(parts[i][1])
            self.assertAlmostEqual(bounds.ymin,-.3,delta=1e-6)
            self.assertAlmostEqual(bounds.ymax,50.3,delta=1e-6)
        for i in (5,9):
            self.assertAlmostEqual(k.bounds(parts[i][1]).xmax,93.3,delta=1e-6)
        shape=s.build_sheet(r)
        self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
        material=s.base_solid(r['base']).Volume(1e-9)+sum(piece.Volume(1e-9) for pieces in parts.values() for piece in pieces)
        self.assertAlmostEqual(material,shape.Volume(1e-9),delta=1e-4)

    def test_straight_return_wall_has_the_requested_butt_clearance(self):
        shape=s.build_sheet(reference_box());point=np.array([93.5,44,4]);normal=np.array([-1,0,0])
        for offset,expected in ((-.01,'in'),(.1,'out'),(.21,'in')):
            self.assertEqual(k.point_state(shape,point+offset*normal),expected)

    def test_developed_root_patches_have_one_owner_and_refold_exactly(self):
        r=reference_box();layout=e.layout(r)
        self.assertTrue(layout.flat.isValid());self.assertEqual(len(layout.flat.Solids()),1)
        for i,left in enumerate(layout.flat_bends[:4]):
            for right in layout.flat_bends[:i]:
                self.assertLess(abs(left.intersect(right).Volume(1e-9)),1e-7)
        folded,st=e.switch(layout.flat,e.state(r,True),False)
        self.same(folded,s.build_sheet(r));self.assertEqual(st['bend_engine'],4)

    def test_engine_three_migration_retains_holes_and_updates_rules(self):
        r=reference_box();tool=cq.Solid.makeCylinder(.5,4,cq.Vector(25,25,-1))
        actual=s.build_sheet(r,parallel_version=3).cut(tool)
        source=e.state(r);source.update(bend_engine=3,dirty=True)
        flat,st=e.switch(actual,source,True);folded,st=e.switch(flat,st,False)
        self.same(folded,s.build_sheet(r).cut(tool))
        updated=copy.deepcopy(r);updated['rules']['gap']=.3
        rebuilt,st=e.rebuild(actual,source,updated)
        self.same(rebuilt,s.build_sheet(updated).cut(tool));self.assertEqual(st['bend_engine'],4)

    def test_rotated_reference_corner_has_the_same_geometry(self):
        r=reference_box();original=s.build_sheet(r);rotated=copy.deepcopy(r)
        axis=np.array([1,2,3])/math.sqrt(14);theta=math.radians(37)
        cross=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
        rotation=np.eye(3)*math.cos(theta)+(1-math.cos(theta))*np.outer(axis,axis)+math.sin(theta)*cross
        shift=np.array([17,-8,31]);rotated['base']['o']=(rotation@np.array(r['base']['o'])+shift).tolist()
        for key in ('x','y','z'):rotated['base'][key]=(rotation@np.array(r['base'][key])).tolist()
        for f in rotated['flanges']:
            if f['kind']!='base':continue
            for key in ('p0','p1'):f[key]=(rotation@np.array(f[key])+shift).tolist()
            for key in ('n','m'):f[key]=(rotation@np.array(f[key])).tolist()
        self.same(s.build_sheet(rotated),original.rotate((0,0,0),tuple(axis),37).translate(tuple(shift)))
