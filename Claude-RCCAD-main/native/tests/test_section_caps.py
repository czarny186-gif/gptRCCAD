"""Material-aware section depth and actual stencil images (when OpenGL is available)."""
import os,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import numpy as np
import cadquery as cq
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QVector3D,QMatrix4x4,QImage
from rccad import kernel as k
from rccad.document import Body
from rccad.sectioncaps import section_quad,section_frame
from rccad.viewport import CadView,camera_for_normal


class SectionMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.view=CadView();self.view.resize(1000,800)
        self.view.opts['center']=QVector3D(40,30,30);self.view.setCameraPosition(distance=200,elevation=0,azimuth=-90)
    def tearDown(self):self.view.close();self.view.deleteLater();self.app.processEvents()
    def body(self,shape):
        b=Body('Model',shape).prepared();self.view.set_models([b]);return b

    def test_full_cut_is_an_occluder_not_an_editable_back_face(self):
        b=self.body(k.box(80,60,60));v=self.view;v.set_section_plane([0,1,0,-25])
        xy=v.project_one((40,25,30));ray=v._ray(*xy)
        self.assertIsNotNone(v._section_cap_hit(b,*ray));self.assertEqual(v.pick_body(*xy),b.id)
        self.assertIsNone(v.pick_face(*xy));self.assertFalse(v._visible_point(np.array([40,60,30.])))
        v.set_section_plane(None);self.assertIsNotNone(v.pick_face(*xy))

    def test_a_chamber_remains_open_but_its_wall_blocks_hidden_geometry(self):
        b=self.body(k.boolean('subtract',k.box(80,60,60),[k.box(60,40,48).translate(cq.Vector(10,10,6))]))
        v=self.view;v.set_section_plane([0,1,0,-25])
        hole=v.project_one((40,25,30));wall=v.project_one((5,25,30))
        self.assertIsNone(v._section_cap_hit(b,*v._ray(*hole)))
        self.assertAlmostEqual(v.pick_face(*hole)[2][1],50,4)
        self.assertIsNotNone(v._section_cap_hit(b,*v._ray(*wall)));self.assertIsNone(v.pick_face(*wall))

    def test_thin_material_blocks_points_even_with_normal_edge_tolerance(self):
        self.body(k.box(80,.1,60));v=self.view
        v.opts['center']=QVector3D(40,.05,30);v.set_section_plane([0,1,0,-.05])
        self.assertFalse(v._visible_point(np.array([40,.1,30])))
        self.assertTrue(v._visible_point(np.array([40,.05,30])))

    def test_preview_transform_and_open_surface_do_not_create_false_material(self):
        b=self.body(k.box(80,60,60));v=self.view;m=QMatrix4x4();m.translate(0,10,0);v.set_body_matrix(b.id,m)
        v.set_section_plane([0,1,0,-25]);xy=v.project_one((40,25,30))
        self.assertIsNotNone(v._section_cap_hit(b,*v._ray(*xy)))
        face=k.box(80,60,60).Faces()[0];b=self.body(face)
        self.assertFalse(v._parts[b.id]['cap_solid']);self.assertIsNone(v._section_cap_hit(b,*v._ray(*xy)))

    def test_nested_material_island_is_pickable_as_a_body_while_void_stays_open(self):
        shell=k.boolean('subtract',k.box(80,60,60),[k.box(60,40,48).translate(cq.Vector(10,10,6))])
        island=k.box(20,20,20).translate(cq.Vector(30,20,20))
        b=self.body(cq.Compound.makeCompound([shell,island]));v=self.view;v.set_section_plane([0,1,0,-25])
        for point,solid in [((40,25,30),True),((20,25,30),False),((5,25,30),True)]:
            xy=v.project_one(point);hit=v._section_cap_hit(b,*v._ray(*xy))
            self.assertEqual(hit is not None,solid)
        xy=v.project_one((40,25,30));self.assertEqual(v.pick_body(*xy),b.id);self.assertIsNone(v.pick_face(*xy))

    def test_quad_handles_oblique_plane_and_outside_extents(self):
        plane=np.array([1.,2.,3.,-60.]);o,u,w=section_frame(plane)
        self.assertAlmostEqual(float(o@plane[:3]+plane[3]),0,8)
        self.assertAlmostEqual(float(u@w),0,8);self.assertAlmostEqual(np.linalg.norm(u),1,8)
        quad,*_=section_quad([0,0,0],[40,40,40],plane)
        np.testing.assert_allclose(quad@plane[:3]+plane[3],0,atol=2e-5)
        self.assertIsNone(section_quad([0,0,0],[40,40,40],np.array([0.,1.,0.,-50.])))
        self.assertIsNone(section_quad([0,0,0],[40,40,40],np.array([0.,1.,0.,10.])))


class StencilSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.v=CadView();self.addCleanup(self.v.deleteLater);self.addCleanup(self.v.close)
        self.v.resize(900,700);self.v.show();self.app.processEvents()
        if not self.v.isValid():self.skipTest('An actual OpenGL context is required for framebuffer assertions')
        self.v.opts['center']=QVector3D(40,30,30);self.v.setCameraPosition(distance=200,elevation=0,azimuth=-90)
    def body(self,shape):
        b=Body('Model',shape).prepared();self.v.set_models([b]);return b
    def shot(self,caps=True):
        self.v.section_caps.setVisible(caps)
        for _ in range(3):self.app.processEvents()
        img=self.v.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
        return np.frombuffer(img.constBits(),np.uint8).reshape(img.height(),img.width(),4).copy()
    def patch(self,img,point,r=8):
        xy=self.v.project_one(point);scale=img.shape[1]/self.v.width();x,y=np.rint(np.array(xy)*scale).astype(int)
        r=max(2,round(r*scale))
        return img[y-r:y+r,x-r:x+r,:3].astype(float)
    def contrast(self,a,b,point,r=8):return np.mean(np.abs(self.patch(a,point,r)-self.patch(b,point,r)))

    def test_full_material_is_hatched_at_multiple_depths_and_disable_restores_model(self):
        b=self.body(k.box(80,60,60));before=self.shot()
        for depth in (5,25,55):
            self.v.set_section_plane([0,1,0,-depth]);cap=self.shot();open_view=self.shot(False)
            self.assertGreater(self.contrast(cap,open_view,(40,depth,30)),15)
            self.assertGreater(self.patch(cap,(40,depth,30)).std(),15)
            self.assertIs(self.v.bodies[0].shape,b.shape)
        self.v.set_section_plane(None);after=self.shot()
        np.testing.assert_allclose(after,before,atol=2)

    def test_holes_and_separate_material_islands_are_not_painted_over(self):
        shell=k.boolean('subtract',k.box(80,60,60),[k.box(60,40,48).translate(cq.Vector(10,10,6))])
        self.body(shell);self.v.set_section_plane([0,1,0,-25]);cap=self.shot();open_view=self.shot(False)
        self.assertLess(self.contrast(cap,open_view,(40,25,30)),2)
        self.assertGreater(self.contrast(cap,open_view,(5,25,30),r=4),10)
        island=k.box(20,20,20).translate(cq.Vector(30,20,20))
        self.body(cq.Compound.makeCompound([shell,island]));cap=self.shot();open_view=self.shot(False)
        self.assertGreater(self.contrast(cap,open_view,(40,25,30)),15)
        self.assertLess(self.contrast(cap,open_view,(20,25,30),r=4),2)

    def test_tube_and_oblique_plane_keep_empty_space_and_hatch_actual_material(self):
        self.body(cq.Workplane('XY').circle(30).circle(20).extrude(60).val())
        self.v.opts['center']=QVector3D(0,0,30);self.v.setCameraPosition(distance=200,elevation=90,azimuth=-90)
        self.v.set_section_plane([0,0,-1,30]);cap=self.shot();open_view=self.shot(False)
        self.assertLess(self.contrast(cap,open_view,(0,0,30)),2)
        self.assertGreater(self.contrast(cap,open_view,(25,0,30),r=4),10)
        self.body(k.box(60,60,60));n=np.array([1.,2.,1.]);n/=np.linalg.norm(n);p=np.array([30.,30.,30.])
        self.v.opts['center']=QVector3D(*p);self.v.setCameraPosition(distance=200,**camera_for_normal(-n))
        self.v.set_section_plane(np.r_[n,-n@p]);cap=self.shot();open_view=self.shot(False)
        self.assertGreater(self.contrast(cap,open_view,p),15)

    def test_live_transform_multiple_bodies_and_gl_state_are_stable(self):
        from OpenGL import GL
        b=self.body(k.box(30,60,60));other=Body('Drugi',k.box(30,60,60).translate(cq.Vector(50,0,0))).prepared()
        self.v.set_models([b,other]);self.v.set_section_plane([0,1,0,-25])
        cap=self.shot();open_view=self.shot(False)
        self.assertGreater(self.contrast(cap,open_view,(15,25,30)),15)
        self.assertGreater(self.contrast(cap,open_view,(65,25,30)),15)
        m=QMatrix4x4();m.translate(0,10,0);self.v.set_body_matrix(b.id,m)
        cap=self.shot();open_view=self.shot(False)
        self.assertGreater(self.contrast(cap,open_view,(15,25,30)),15)
        self.v.makeCurrent();self.assertEqual(GL.glGetError(),GL.GL_NO_ERROR);self.v.doneCurrent()
        self.v.set_section_plane(None);self.v.set_models([])
        self.assertFalse(self.v.section_caps._bounds)

    def test_line_clipping_preserves_buffers_and_restores_both_sides(self):
        from rccad.viewport import SectionLine
        from OpenGL import GL
        self.v.set_models([]);self.v.opts['center']=QVector3D(0,0,0)
        self.v.setCameraPosition(distance=100,elevation=0,azimuth=-90)
        line=SectionLine(pos=np.array([[-20,0,0],[20,0,0]],np.float32),color=(1,0,0,1),width=5,antialias=False,mode='lines')
        self.v.addItem(line);before=self.shot();original=line.pos;buffer_id=line.m_vbo_position.bufferId()
        self.v.set_section_plane([1,0,0,0]);cut=self.shot()
        self.assertIs(line.pos,original);self.assertEqual(buffer_id,line.m_vbo_position.bufferId())
        self.assertGreater(np.abs(self.patch(before,(-10,0,0),4)-self.patch(cut,(-10,0,0),4)).max(),20)
        self.assertLess(self.contrast(before,cut,(10,0,0),r=4),2)
        self.v.set_section_plane([-1,0,0,0]);reverse=self.shot()
        self.assertGreater(np.abs(self.patch(before,(10,0,0),4)-self.patch(reverse,(10,0,0),4)).max(),20)
        self.assertLess(self.contrast(before,reverse,(-10,0,0),r=4),2)
        self.v.set_section_plane(None);restored=self.shot();np.testing.assert_allclose(before,restored,atol=2)
        self.v.makeCurrent();self.assertEqual(GL.glGetError(),GL.GL_NO_ERROR);self.v.doneCurrent()

    def test_portable_material_without_stencil_matches_reference_open_box(self):
        import time
        self.v.section_caps.force_portable=True
        shape=k.box(80,60,60).cut(k.box(60,40,60).translate((10,10,8))).fuse(k.box(10,20,40).translate((50,10,8))).clean()
        b=self.body(shape);self.v.set_section_plane([0,1,0,-25])
        end=time.monotonic()+8
        while time.monotonic()<end:
            cap=self.shot()
            if b.id in self.v.section_caps._solid_patches:break
            time.sleep(.005)
        self.assertIn(b.id,self.v.section_caps._solid_patches)
        open_view=self.shot(False)
        self.assertGreater(self.contrast(cap,open_view,(5,25,30),r=4),10)
        self.assertGreater(self.contrast(cap,open_view,(55,25,30),r=4),10)
        self.assertLess(self.contrast(cap,open_view,(30,25,30),r=4),2)
        self.v.setCameraPosition(distance=200,elevation=25,azimuth=-65)
        hit=self.v.pick_face(*self.v.project_one((20,32,8)))
        self.assertIsNotNone(hit);self.assertAlmostEqual(hit[2][2],8,4)
        frame,normal=self.v.face_at(b,hit)
        self.assertAlmostEqual(normal[2],1,5)

    def test_batched_sketches_keep_original_overlay_appearance_on_solid(self):
        solid=self.body(k.box(80,60,60))
        sketches=[Body(str(i),k.sketch('circle','XZ',3,x=7+i%10*6,y=8+i//10*8),kind='sketch',plane='XZ').prepared() for i in range(60)]
        self.v.set_models([solid,*sketches]);batched=self.shot()
        for item in self.v._sketch_batches:item.setVisible(False)
        for body in sketches:
            for item in self.v._parts[body.id]['lines']:item.setVisible(True)
        self.v.update();separate=self.shot()
        self.assertLess(float(np.abs(batched.astype(float)-separate.astype(float)).mean()),.2)
