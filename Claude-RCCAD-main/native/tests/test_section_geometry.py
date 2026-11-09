"""Section picking follows the same half-space as the displayed surfaces."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import numpy as np
import cadquery as cq
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QVector3D,QMatrix4x4
from rccad import kernel as k,measurement
from rccad.sectionview import clip_segments
from rccad.viewport import CadView
from rccad.document import Body


class SectionGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.view=CadView();self.view.resize(1000,800)
        shape=k.boolean('subtract',k.box(80,60,60),[k.box(60,40,48).translate(cq.Vector(10,10,6))])
        self.body=Body('Komora',shape).prepared();self.view.set_models([self.body])
        self.view.opts['center']=QVector3D(40,30,30);self.view.setCameraPosition(distance=180,elevation=0,azimuth=-90)

    def tearDown(self):self.view.close();self.view.deleteLater();self.app.processEvents()

    def test_cut_opens_closed_chamber_and_picks_original_inside_face(self):
        xy=self.view.project_one((40,50,30))
        self.assertAlmostEqual(self.view.pick_face(*xy)[2][1],0,4)
        self.view.set_section_plane([0,1,0,-25])
        hit=self.view.pick_face(*xy)
        self.assertAlmostEqual(hit[2][1],50,4)
        face,n=k.face_at(self.body.shape,hit[1],hit[2]);self.assertAlmostEqual(n[1],-1,5)
        self.view.set_section_plane(None)
        self.assertAlmostEqual(self.view.pick_face(*xy)[2][1],0,4)

    def test_all_removed_means_no_body_face_or_vertex_even_in_xray(self):
        self.view.set_section_plane([0,1,0,-100]);self.view.xray=True
        xy=self.view.project_one((40,50,30))
        self.assertIsNone(self.view.pick_face(*xy));self.assertIsNone(self.view.pick_body(*xy))
        for q in self.body.shape.Vertices():
            xy=self.view.project_one(q.toTuple())
            self.assertIsNone(self.view.nearest_vertex(*xy));self.assertIsNone(self.view.nearest_edge(*xy))

    def test_clipping_follows_preview_transform_and_rejects_front_body(self):
        foreground=Body('Przed',k.box(80,10,60).translate(cq.Vector(0,-20,0))).prepared()
        self.view.set_models([foreground,self.body]);xy=self.view.project_one((40,50,30))
        self.assertEqual(self.view.pick_body(*xy),foreground.id)
        self.view.set_section_plane([0,1,0,-25]);self.assertEqual(self.view.pick_body(*xy),self.body.id)
        m=QMatrix4x4();m.translate(0,10,0);self.view._body_m={self.body.id:m}
        xy=self.view.project_one((40,60,30));self.assertAlmostEqual(self.view.pick_face(*xy)[2][1],60,4)

    def test_hidden_sketch_cannot_be_selected_through_its_removed_fill(self):
        sk=Body('Szkic',k.sketch('rectangle','XY',20,20),'sketch','XY').prepared()
        self.view.set_models([sk]);c=sk.shape.Center()
        self.view.opts['center']=QVector3D(c.x,c.y,0);self.view.setCameraPosition(distance=100,elevation=90,azimuth=-90)
        xy=self.view.project_one(c.toTuple());self.assertEqual(self.view.pick_profile(*xy),sk.id)
        self.view.set_section_plane([0,0,1,-5])
        self.assertIsNone(self.view.pick_profile(*xy));self.assertIsNone(self.view.pick_face(*xy))

    def test_clipped_line_pairs_preserve_endpoints_and_crossing_directions(self):
        pairs=np.array([[[-2,0,0],[2,0,0]],[[2,1,0],[-2,1,0]],[[-3,2,0],[-1,2,0]],[[1,3,0],[3,3,0]]])
        out=clip_segments(pairs,[1,0,0,0]).reshape(-1,2,3)
        np.testing.assert_allclose(out,[[[0,0,0],[2,0,0]],[[2,1,0],[0,1,0]],[[1,3,0],[3,3,0]]])
        self.assertEqual(clip_segments([], [1,0,0,0]).shape,(0,3))

    def test_perspective_point_and_clipped_edge_stick_to_cursor(self):
        from rccad.studio import StudioWindow
        self.view.setCameraPosition(distance=180,elevation=20,azimuth=-55)
        points=np.array([[10,0,0],[70,60,60]],float)
        expected=points[0]+.7*(points[1]-points[0]);xy=self.view.project_one(expected)
        actual=StudioWindow._edge_point_near(self.view,points,*xy)
        np.testing.assert_allclose(actual,expected,atol=1e-4)
        self.view.set_section_plane([0,1,0,-25])
        actual=StudioWindow._edge_point_near(self.view,points,*self.view.project_one(points[0]))
        self.assertGreaterEqual(actual[1],25-1e-6)


class ExactMeasurementTests(unittest.TestCase):
    def test_edge_projection_is_on_actual_arc_and_faces(self):
        edge=cq.Edge.makeCircle(10)
        q=measurement.on_edge(edge,[7,7,.01]);self.assertAlmostEqual(np.linalg.norm(q[:2]),10,8);self.assertAlmostEqual(q[2],0,8)
        face=max(k.box(10,10,10).Faces(),key=lambda f:f.Center().z)
        q=measurement.on_shape(face,[2,3,9.999]);np.testing.assert_allclose(q,[2,3,10],atol=1e-8)

    def test_angle_distinguishes_oriented_points_from_unoriented_edges(self):
        a=[1,0,0];b=[-1,1,0]
        self.assertAlmostEqual(measurement.angle_between(a,b),135)
        self.assertAlmostEqual(measurement.angle_between(a,b,True),45)
        self.assertAlmostEqual(measurement.angle_between(a,[-1,-1,0],True),45)
        self.assertAlmostEqual(measurement.angle_between(a,[-1,0,0],True),0)
        with self.assertRaises(k.CadError):measurement.angle_between([0,0,0],a)
        arc=measurement.angle_arc([1,2,3],a,[0,1,0],5)
        np.testing.assert_allclose(arc[0],[6,2,3]);np.testing.assert_allclose(arc[-1],[1,7,3],atol=1e-8)
