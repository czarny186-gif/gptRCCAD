"""Correctness guards for accelerated paths; no machine-dependent time limits."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import unittest
from unittest.mock import patch
from dataclasses import replace
import numpy as np
import cadquery as cq
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMatrix4x4,QVector3D
from rccad import kernel as k,history as h,workers
from rccad.document import Body
from rccad.viewport import CadView,_pick_data,_PICK
from rccad.perfcache import LRU
from rccad.spatial import BoundsTree


class CacheAndBoundsTests(unittest.TestCase):
    def test_lru_evicts_only_old_entries_and_accounts_bytes(self):
        c=LRU(64,max_entries=500)
        for i in range(8):c[i]=np.zeros(8,dtype=np.uint8)
        c.get(0);c[8]=np.zeros(8,dtype=np.uint8)
        self.assertIn(0,c);self.assertNotIn(1,c);self.assertEqual(c.bytes,64)
        c[0]=np.zeros(16,dtype=np.uint8);self.assertEqual(c.bytes,64)
        c[99]=np.zeros(128,dtype=np.uint8);self.assertNotIn(99,c);self.assertEqual(c.bytes,64)
        c.clear();self.assertEqual(c.bytes,0)

    def test_more_than_256_active_meshes_stay_cached(self):
        _PICK.clear();meshes=[]
        for i in range(400):
            mesh=k.DisplayMesh(np.array([[i,0,0],[i+1,0,0],[i,1,0.]],dtype=np.float32),np.array([[0,1,2]]),{},(i,0,0),1)
            meshes.append(mesh);_pick_data(mesh)
        first=_pick_data(meshes[0]);last=_pick_data(meshes[-1])
        self.assertIs(first,_pick_data(meshes[0]));self.assertIs(last,_pick_data(meshes[-1]));self.assertGreaterEqual(len(_PICK),400)

    def test_bounds_tree_matches_exhaustive_rays_and_point_queries(self):
        rng=np.random.default_rng(81);lo=rng.uniform(-50,50,(180,3));hi=lo+rng.uniform(.1,12,(180,3));tree=BoundsTree(lo,hi)
        for _ in range(60):
            p=rng.uniform(-60,60,3);d=rng.normal(size=3);d[rng.integers(3)]=0
            expected=[]
            for i,(a,b) in enumerate(zip(lo,hi)):
                near=0.;far=np.inf
                for j in range(3):
                    if abs(d[j])<1e-15:
                        if not a[j]<=p[j]<=b[j]:far=-1
                    else:
                        t=sorted(((a[j]-p[j])/d[j],(b[j]-p[j])/d[j]));near=max(near,t[0]);far=min(far,t[1])
                if far>=near:expected.append(i)
            self.assertEqual(tree.ray(p,d),expected)
            expected=np.flatnonzero(np.all((p>=lo-2)&(p<=hi+2),axis=1)).tolist()
            self.assertEqual(tree.point(p,2),expected)

    def test_triangle_face_ids_and_cached_exact_face_resolution(self):
        shape=k.box(30,20,10).cut(cq.Solid.makeCylinder(3,10,cq.Vector(15,10,0)))
        mesh=k.display_mesh(shape);self.assertEqual(len(mesh.face_ids),len(mesh.triangles))
        faces=shape.Faces()
        for i in np.linspace(0,len(mesh.triangles)-1,20,dtype=int):
            p=mesh.vertices[mesh.triangles[i]].mean(axis=0)
            self.assertLess(faces[int(mesh.face_ids[i])].distance(cq.Vertex.makeVertex(*map(float,p))),.13)
        face,n=k.face_at(shape,(0,-1,0),(5,0,5));self.assertAlmostEqual(n[1],-1)
        with patch.object(k,'bounds',side_effect=AssertionError('repeated face bounds')):
            again,_=k.face_at(shape,(0,-1,0),(6,0,5))
        self.assertEqual(face.hashCode(),again.hashCode())
        # An incorrect triangle hint must fall back to exact geometry.
        again,_=k.face_at(shape,(0,-1,0),(6,0,5),face_hint=next(i for i,f in enumerate(faces) if f.distance(cq.Vertex.makeVertex(6,0,5))>1))
        self.assertEqual(face.hashCode(),again.hashCode())


class IndexedPickingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.v=CadView();self.v.resize(900,650)
        self.bodies=[Body(str(i),k.box(12,10,8).translate((i%4*22,i//4*20,0))).prepared() for i in range(12)]
        wire=Body('Line',cq.Wire.makePolygon([cq.Vector(0,-8,0),cq.Vector(50,-8,0)]),kind='sketch').prepared()
        self.bodies.append(wire)
        self.v.set_models(self.bodies);self.v.opts['center']=QVector3D(40,25,4);self.v.setCameraPosition(distance=180,elevation=35,azimuth=-65)
    def tearDown(self):self.v.close();self.v.deleteLater();self.app.processEvents()

    def same(self,a,b):
        self.assertEqual(a is None,b is None)
        if a is not None:
            self.assertEqual(a[0],b[0])
            for x,y in zip(a[1:],b[1:]):np.testing.assert_allclose(x,y,atol=1e-5)

    def test_indexed_and_exhaustive_picks_match_across_camera_section_and_transform(self):
        m=QMatrix4x4();m.translate(4,-3,5);m.rotate(27,0,0,1);self.v.set_body_matrix(self.bodies[2].id,m)
        for ortho,section in ((True,None),(False,None),(True,np.array([0,1,0,-9.])),(False,np.array([1,1,.3,-30.]))):
            self.v.set_ortho(ortho);self.v.set_roll(19);self.v.set_section_plane(section);self.v.locked={self.bodies[5].id}
            points=[self.v.project_one(p) for p in ((0,0,0),(12,0,8),(22,0,4),(44,0,0),(5,20,8),(66,40,8),(31,14,3),(25,-8,0))]
            for xy in points:
                if xy is None:continue
                fast=(self.v.pick_face(*xy),self.v.nearest_edge(*xy),self.v.nearest_vertex(*xy))
                with patch.object(self.v,'_ray_bodies',side_effect=lambda *_:iter(self.v.bodies)),patch.object(self.v,'_screen_bodies',side_effect=lambda *_:iter(self.v.bodies)):
                    slow=(self.v.pick_face(*xy),self.v.nearest_edge(*xy),self.v.nearest_vertex(*xy))
                for a,b in zip(fast,slow):self.same(a,b)

    def test_projection_cache_reuse_and_invalidation(self):
        b=self.bodies[0];first=self.v._edge_projection(b);self.assertIs(first,self.v._edge_projection(b))
        camera=self.v._camera_data()
        self.v.project_one((2,3,4));self.assertIs(camera,self.v._camera_data())
        self.v.opts['fov']+=5;self.assertIsNot(first,self.v._edge_projection(b));self.assertIsNot(camera,self.v._camera_data())
        first=self.v._edge_projection(b);m=QMatrix4x4();m.translate(1000,0,0);self.v.set_body_matrix(b.id,m)
        moved=self.v._edge_projection(b);self.assertIsNot(first,moved);np.testing.assert_allclose(moved[0],first[0]+[1000,0,0])
        self.v.clear_body_matrices();np.testing.assert_allclose(self.v._edge_projection(b)[0],first[0])
        self.v.set_section_plane([1,0,0,-6]);cut=self.v._edge_projection(b);self.assertTrue(np.all(cut[0][:,0]>=6-1e-5))
        self.v.set_section_plane(None);np.testing.assert_allclose(self.v._edge_projection(b)[0],first[0])

    def test_visibility_and_mesh_replacement_invalidate_scene(self):
        xy=self.v.project_one((5,0,4));self.v.set_models([self.bodies[0]])
        self.assertEqual(self.v.pick_body(*xy),self.bodies[0].id)
        self.v.set_models([replace(self.bodies[0],visible=False)]);self.assertIsNone(self.v.pick_body(*xy))
        moved=self.bodies[0].changed(k.box(12,10,8).translate((1000,0,0)));self.v.set_models([moved]);self.assertIsNone(self.v.pick_body(*xy))
        self.assertNotIn(moved.id,self.v._visible_body_ids())


class CachedOperationTests(unittest.TestCase):
    def setUp(self):h._REMOTE_SHAPES.clear()
    def invoke(self,fn,*args):return fn(*args)

    def test_scoped_booleans_match_local_and_omit_unrelated_shapes(self):
        a=Body('A',k.box(20,20,10)).prepared();far=Body('Far',k.box(10,10,10).translate((200,0,0))).prepared()
        sketch=Body('Sketch',cq.Wire.makePolygon([cq.Vector(200,0,0),cq.Vector(201,0,0)]),kind='sketch').prepared()
        bodies=[a,far,sketch]
        for mode,tool in [('cut',k.box(3,24,12).translate((8,-2,-1))),('join',k.box(5,5,5).translate((18,0,0))),('intersect',k.box(10,10,12)),('new',k.box(4,4,4))]:
            kwargs=dict(spent=[sketch.id],ids=['fixed-result'])
            local=h.combine(bodies,[tool],mode,**kwargs)
            with patch.object(workers,'ready',return_value=True),patch.object(workers,'call_affine',side_effect=lambda key,fn,*args:fn(*args)) as spy:
                remote=h.offloaded(h.combine,bodies,[tool],mode,**kwargs)
            self.assertEqual([b.id for b in remote],[b.id for b in local])
            self.assertEqual([b.visible for b in remote],[b.visible for b in local])
            for x,y in zip(remote,local):
                if x.kind=='solid':self.assertLess(x.shape.cut(y.shape).Volume()+y.shape.cut(x.shape).Volume(),1e-6)
            for call in spy.call_args_list:
                packets=call.args[4];self.assertLessEqual(len(packets),1)
            self.assertIs(next(b for b in remote if b.id==far.id),far)

    def test_worker_cache_hit_eviction_retry_and_changed_geometry(self):
        body=Body('A',k.box(10,10,10)).prepared();tool=k.box(2,2,12).translate((4,4,-1))
        def remote():return h.offloaded(h.combine,[body],[tool],'cut')
        with patch.object(workers,'ready',return_value=True),patch.object(workers,'call_affine',side_effect=lambda key,fn,*args:fn(*args)) as spy:
            first=remote();self.assertEqual(spy.call_count,2)
            spy.reset_mock();again=remote();self.assertEqual(spy.call_count,1)
            self.assertTrue(all(p[2] is None for p in spy.call_args.args[4]))
            h._REMOTE_SHAPES.clear();spy.reset_mock();remote();self.assertEqual(spy.call_count,2)
            body=body.changed(k.box(12,10,10));spy.reset_mock();changed=remote();self.assertEqual(spy.call_count,2)
        self.assertAlmostEqual(first[0].shape.Volume(),again[0].shape.Volume(),6)
        self.assertAlmostEqual(changed[0].shape.Volume()-first[0].shape.Volume(),200,6)
