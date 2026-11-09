"""Pattern sketch responsiveness, prism correctness, and portable section material."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import unittest
from functools import partial
from unittest.mock import patch
import numpy as np
import cadquery as cq
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMatrix4x4,QVector3D
from rccad import kernel as k,history as h
from rccad.document import Body
from rccad.viewport import CadView
from rccad.sectionmesh import cap_mesh
from rccad.linearpreview import preview


def area(mesh):
    if mesh is None:return 0.
    p=mesh.vertices[mesh.triangles]
    return float(np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1).sum()/2)


class PatternPreviewTests(unittest.TestCase):
    def test_prism_preview_keeps_holes_and_matches_exact_bounds_for_both_directions(self):
        face=cq.Face.makeFromWires(cq.Wire.makeCircle(10,cq.Vector(),cq.Vector(0,0,1)),[cq.Wire.makeCircle(4,cq.Vector(),cq.Vector(0,0,1))])
        for d1,d2,symmetric in ((8,0,False),(-8,0,False),(8,3,False),(-8,0,True)):
            make=partial(k.extrude_face,face,(0,0,1),d1,d2,symmetric)
            mesh=preview(make,.12);exact=k.display_mesh(make())
            np.testing.assert_allclose(mesh.vertices.min(axis=0),exact.vertices.min(axis=0),atol=1e-5)
            np.testing.assert_allclose(mesh.vertices.max(axis=0),exact.vertices.max(axis=0),atol=1e-5)
            # Cap triangles must never span the real circular hole.
            ids=mesh.triangles[:2*len(k.display_mesh(face).triangles)]
            centers=mesh.vertices[ids].mean(axis=1)
            self.assertTrue(np.all(np.linalg.norm(centers[:,:2],axis=1)>3.8))
            with patch.object(k,'display_mesh',side_effect=AssertionError('cached planar profile rebuilt')):
                again=preview(make,.12)
            self.assertEqual(len(mesh.triangles),len(again.triangles))

    def test_distinct_pattern_wires_skip_global_edge_splitting(self):
        wires=[cq.Wire.makeCircle(1,cq.Vector(i%10*5,i//10*5,0),cq.Vector(0,0,1)) for i in range(100)]
        with patch.object(k,'split_edges',side_effect=AssertionError('global General Fuse')):
            faces=k.regions('XY',[e for w in wires for e in w.Edges()],wires)
        self.assertEqual(len(faces),100)
        self.assertAlmostEqual(sum(f.Area() for f in faces),100*np.pi,5)
        a=cq.Wire.makeCircle(3,cq.Vector(),cq.Vector(0,0,1));b=a.translate((3,0,0))
        overlap=k.regions('XY',[*a.Edges(),*b.Edges()],[a,b])
        self.assertEqual(len(overlap),3)

    def test_face_boundaries_split_only_profiles_that_touch_them(self):
        surface=cq.Face.makeFromWires(k.sketch('rectangle','XY',100,100))
        inside=cq.Face.makeFromWires(cq.Wire.makeCircle(1,cq.Vector(20,20,0),cq.Vector(0,0,1)))
        outside=cq.Face.makeFromWires(cq.Wire.makeCircle(1,cq.Vector(120,20,0),cq.Vector(0,0,1)))
        with patch.object(k,'_fromlist',side_effect=AssertionError('unnecessary planar Boolean')):
            self.assertEqual(k.split_by_faces([inside,outside],[surface]),[inside,outside])
        crossing=cq.Face.makeFromWires(cq.Wire.makeCircle(4,cq.Vector(50,20,0),cq.Vector(0,0,1)))
        pieces=k.split_by_faces([inside,crossing],[surface])
        self.assertEqual(len(pieces),3)
        self.assertAlmostEqual(sum(f.Area() for f in pieces),inside.Area()+crossing.Area(),5)


class SketchBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_batches_follow_selection_and_separate_moving_sketch(self):
        v=CadView();self.addCleanup(v.deleteLater);self.addCleanup(v.close);v.resize(900,700)
        bodies=[Body(str(i),k.sketch('circle','XY',2,x=i%10*6,y=i//10*6),kind='sketch').prepared() for i in range(60)]
        v.set_models(bodies)
        self.assertEqual(len(v._sketch_batches),1)
        self.assertTrue(all(not line.visible() for parts in v._parts.values() for line in parts['lines']))
        m=QMatrix4x4();m.translate(1,0,0);v.set_body_matrix(bodies[0].id,m)
        self.assertTrue(all(line.visible() for line in v._parts[bodies[0].id]['lines']))
        batch=v._sketch_batches[0];m.translate(1,0,0);v.set_body_matrix(bodies[0].id,m)
        self.assertIs(batch,v._sketch_batches[0])
        v.clear_body_matrices();self.assertTrue(all(not line.visible() for line in v._parts[bodies[0].id]['lines']))
        v.set_models(bodies,[bodies[-1].id]);self.assertEqual(len(v._sketch_batches),2)
        v.set_models([]);self.assertFalse(v._sketch_batches)


class PortableMaterialTests(unittest.TestCase):
    def test_shell_hole_nested_island_and_transformed_section_area(self):
        shell=k.box(80,60,60).cut(k.box(60,40,48).translate((10,10,6)))
        mesh=k.display_mesh(shell);plane=np.array([0,1,0,-25.])
        self.assertAlmostEqual(area(cap_mesh(mesh,plane)),80*60-60*48,2)
        island=k.box(20,20,20).translate((30,20,20))
        self.assertAlmostEqual(area(cap_mesh(k.display_mesh(cq.Compound.makeCompound([shell,island])),plane)),80*60-60*48+400,2)
        m=np.eye(4);m[:3,3]=[5,10,7]
        self.assertAlmostEqual(area(cap_mesh(mesh,np.array([0,1,0,-35.]),m)),80*60-60*48,2)
        self.assertIsNone(cap_mesh(mesh,[0,1,0,-80]))

    def test_oblique_box_and_open_container_material(self):
        self.assertAlmostEqual(area(cap_mesh(k.display_mesh(k.box(10,10,10)),[1,1,0,-10])),100*np.sqrt(2),2)
        box=k.box(80,60,60).cut(k.box(60,40,60).translate((10,10,8)))
        box=box.fuse(k.box(10,20,40).translate((50,10,8))).clean()
        self.assertAlmostEqual(area(cap_mesh(k.display_mesh(box),[0,1,0,-25])),80*8+20*52+10*40,2)
