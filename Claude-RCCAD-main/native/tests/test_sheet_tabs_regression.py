"""Sheet/tab-wall regressions: edits, bend order, manufacturable corners and DXF."""
import copy
from dataclasses import replace
import tempfile
from pathlib import Path
import unittest
import numpy as np
import cadquery as cq
from rccad import history as h,kernel as k,sheetmetal as s,sheetedit as e
from rccad.document import Body,Document


class Assembly:
    def __init__(self,joint='parallel',t=2):
        self.t=t;self.rules=dict(joint=joint,gap=.2,relief='none',miter=True,auto_corners=True)
        b=Body('Blacha',k.box(100,60,t));self.id=b.id
        face=max(b.shape.Faces(),key=lambda f:f.Center().z)
        self.bodies=h.run_sheet([b],dict(id=b.id,face=h.face_ref(face,(0,0,1),face.Center().toTuple(),b.shape),rules=self.rules))

    def body(self,bid=None):return next(b for b in self.bodies if b.id==(bid or self.id))

    def edge(self,bid,side=None,parent=None,tip='out'):
        r=s.normalize(self.body(bid).meta['sheet']['recipe']);base=r['base'];t=r['t']
        if parent is None:
            O=np.array(base['o'])+t*np.array(base['z']);X=np.array(base['x'])*base['lx'];Y=np.array(base['y'])*base['ly']
            a,b=dict(F=(O,O+X),R=(O+X,O+X+Y),B=(O+X+Y,O+Y),L=(O+Y,O))[side]
        else:
            frames,_=s._effective(r['flanges'],t,True)
            a,b=(s._hem_end_geom(frames[parent],tip,t) if frames[parent].get('hem') else s._tip_geom(frames[parent],tip,t))[:2]
        idx=h._edge_on_segment(self.body(bid).shape,np.array(a),np.array(b))
        if idx is None:raise AssertionError('Missing attachment edge')
        return idx

    def bend(self,side=None,bid=None,parent=None,tip='out',angle=90,length=30,hem=False,reverse=False):
        b=self.body(bid);r=b.meta['sheet']['recipe'];idx=self.edge(b.id,side,parent,tip)
        spec=s.spec_for_edge(r['base'],r['t'],r['flanges'],self.rules,b.shape.Edges()[idx].positionAt(.5).toTuple(),.1)
        spec.update(r=.5,angle=angle,length=length)
        if hem:spec['hem']=dict(gap=.2,ret=length)
        else:spec.update(measure='outer',outside=False)
        if reverse:
            n=np.array(spec['n']);spec.update(p0=(np.array(spec['p0'])-r['t']*n).tolist(),p1=(np.array(spec['p1'])-r['t']*n).tolist(),n=(-n).tolist())
        self.bodies=h.run_sheetbuild(self.bodies,dict(type='sheetbuild',id=b.id,base=r['base'],t=r['t'],rules=self.rules,flanges=[*r['flanges'],spec]))

    def wall(self,side,bid=None,length=30):
        b=self.body(bid);idx=self.edge(b.id,side);before={b.id for b in self.bodies}
        self.bodies=h.run_sheet_tabwall(self.bodies,dict(id=b.id,edges=h.edge_refs(b.shape,[idx]),t=self.t,length=length,measure='outer',width=5,fit=.1,corner=self.rules['joint']))
        return next(b.id for b in self.bodies if b.id not in before)

    def hole(self,bid=None):
        b=self.body(bid);base=b.meta['sheet']['recipe']['base']
        Z=np.array(base['z']);C=np.array(base['o'])+base['lx']/2*np.array(base['x'])+base['ly']/2*np.array(base['y'])-2*Z
        tool=Body('Otwór',cq.Solid.makeCylinder(2,self.t+4,cq.Vector(*C),cq.Vector(*Z)))
        assert b.shape.intersect(tool.shape).Volume()>1
        self.bodies=h.run_bool([*self.bodies,tool],dict(base=b.id,tools=[tool.id],op='subtract'))
        return tool.shape

    def check(self,test):
        for i,b in enumerate(self.bodies):
            test.assertTrue(b.shape.isValid());test.assertEqual(len(b.shape.Solids()),1)
            for c in self.bodies[i+1:]:test.assertLess(b.shape.intersect(c.shape).Volume(1e-9),1e-4)

    def cycle(self,test,repeats=1):
        old={b.id:b.shape for b in self.bodies}
        for _ in range(repeats):
            self.bodies=h.run_sheetmode(self.bodies,dict(id=self.id,flat=True));self.check(test)
            for b in self.bodies:test.assertAlmostEqual(b.shape.BoundingBox().zlen,self.t,delta=1e-5)
            self.bodies=h.run_sheetmode(self.bodies,dict(id=self.id,flat=False));self.check(test)
            for b in self.bodies:test.assertLess(old[b.id].cut(b.shape).Volume(1e-9)+b.shape.cut(old[b.id]).Volume(1e-9),1e-4)


class SheetTabRegressionTests(unittest.TestCase):
    def setUp(self):
        self.defer=k.deferred_mesh();self.defer.__enter__()
    def tearDown(self):self.defer.__exit__(None,None,None)

    def test_wall_hole_survives_regeneration_and_project_reload(self):
        for joint in ('sheet',):
            with self.subTest(joint=joint):
                a=Assembly(joint);wid=a.wall('R');tool=a.hole(wid);a.wall('L')
                doc=Document();doc.commit(a.bodies)
                with tempfile.TemporaryDirectory() as d:
                    path=Path(d)/'sheet.rccadx';doc.save(path);a.bodies=list(Document.load(path).bodies)
                a.bend('F');a.bend('B')
                self.assertLess(a.body(wid).shape.intersect(tool).Volume(),1e-6);a.cycle(self)

    def test_base_hole_and_wall_bend_allow_later_base_bends(self):
        a=Assembly();tool=a.hole();wid=a.wall('R');a.wall('L')
        a.bend('B',bid=wid,length=12);a.bend('F');a.bend('B')
        self.assertLess(a.body().shape.intersect(tool).Volume(),1e-6);a.cycle(self)

    def test_wall_hems_allow_later_base_bends(self):
        a=Assembly('sheet');wid=a.wall('R');a.wall('L')
        a.bend('B',bid=wid,length=10,hem=True);a.bend('F');a.bend('B');a.cycle(self)

    def test_obtuse_wall_flange_can_develop_and_refold(self):
        for joint in ('parallel',):
            with self.subTest(joint=joint):
                a=Assembly(joint);a.bend('F');a.bend('B');left=a.wall('L');right=a.wall('R')
                a.bend('B',bid=left,angle=135,length=12);a.bend('B',bid=right,angle=135,length=12);a.cycle(self,repeats=2)

    def test_mixed_corner_returns_and_wall_lips_stay_disjoint(self):
        a=Assembly('sheet',1);a.bend('F');a.bend('B');left=a.wall('L');right=a.wall('R')
        a.bend(parent=0,tip='in',length=12);a.bend(parent=1,tip='in',length=12)
        for wid in (left,right):
            b=a.body(wid);v=np.array([50.,30.,0.])-np.array(b.shape.Center().toTuple());v[2]=0
            reverse=float(v@np.array(b.meta['sheet']['recipe']['base']['z']))<0
            a.bend('B',bid=wid,length=12,reverse=reverse)
        a.cycle(self)

    def test_thin_returns_clear_the_ends_of_sixty_degree_wall_bends(self):
        a=Assembly('parallel',.8);a.bend('F');a.bend('B');left=a.wall('L');right=a.wall('R')
        a.bend(parent=0,tip='in',length=12);a.bend(parent=1,tip='out',length=12)
        a.bend('B',bid=left,angle=60,length=8);a.bend('B',bid=right,angle=60,length=8)
        a.cycle(self)

    def test_a_wall_through_the_middle_of_a_bend_is_still_rejected(self):
        from rccad.sheetassembly import _clear_bend_ends
        base=dict(o=[0,0,0],x=[1,0,0],y=[0,1,0],z=[0,0,1],lx=20,ly=10,lz=1)
        recipe=dict(base=base,t=1,flanges=[dict(kind='base',p0=[0,0,1],p1=[20,0,1],n=[0,0,1],m=[0,-1,0],r=.5,angle=90,length=5)],rules={})
        model=e.layout(recipe)
        obstacle=dict(o=[9.5,-3,0],x=[0,1,0],y=[0,0,1],z=[1,0,0],lx=4,ly=3,lz=1)
        other=e.layout(dict(base=obstacle,t=1,flanges=[],rules={}))
        with self.assertRaisesRegex(k.CadError,'środek gięcia'):_clear_bend_ends(model.folded,model,other.folded,.1,other)

    def test_flat_wall_cut_survives_folding_and_another_base_bend(self):
        from rccad import plywood as pw
        a=Assembly();wid=a.wall('R');a.bend('F')
        a.bodies=h.run_sheetmode(a.bodies,dict(id=a.id,flat=True))
        wall=a.body(wid);C=np.array(wall.shape.Center().toTuple())+np.array([3.,3.,-3.])
        tool=Body('Otwór na płasko',cq.Solid.makeCylinder(1,a.t+6,cq.Vector(*C),cq.Vector(0,0,1)))
        self.assertAlmostEqual(wall.shape.intersect(tool.shape).Volume(),np.pi*a.t,delta=1e-5)
        expected=pw.apply_matrix(tool.shape,pw._mat(wall.meta['ply']['tab']['unfold']['M']))
        a.bodies=h.run_bool([*a.bodies,tool],dict(base=wid,tools=[tool.id],op='subtract'))
        a.bodies=h.run_sheetmode(a.bodies,dict(id=a.id,flat=False))
        self.assertLess(a.body(wid).shape.intersect(expected).Volume(),1e-6)
        a.bend('B');self.assertLess(a.body(wid).shape.intersect(expected).Volume(),1e-6);a.cycle(self)

    def test_legacy_wall_hole_is_not_absorbed_into_automatic_joints(self):
        a=Assembly();wid=a.wall('R');a.wall('L');tool=a.hole(wid)
        a.bodies=[replace(b,meta=dict(b.meta,sheet={key:value for key,value in b.meta['sheet'].items() if key!='joints'})) for b in a.bodies]
        a.bend('F');self.assertLess(a.body(wid).shape.intersect(tool).Volume(),1e-6);a.cycle(self)


class SheetTabDxfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        from rccad.studio import StudioWindow
        self.w=StudioWindow();self.w.show();self.app.processEvents()
        self.dialogs=[patch.object(QMessageBox,'warning'),patch.object(QMessageBox,'information')]
        for value in self.dialogs:value.start()
        self.folder=tempfile.TemporaryDirectory()

    def wait(self):
        import time
        until=time.monotonic()+120
        while self.w.busy and time.monotonic()<until:self.app.processEvents();time.sleep(.005)
        self.app.processEvents();self.assertFalse(self.w.busy)

    def tearDown(self):
        from PySide6.QtCore import QEvent
        self.wait();self.w.document._saved_revision=self.w.document._revision
        self.w.close();self.w.deleteLater();self.app.sendPostedEvents(None,QEvent.DeferredDelete);self.app.processEvents()
        for value in self.dialogs:value.stop()
        self.folder.cleanup()

    def export(self,a,path):
        from unittest.mock import patch
        self.w.document=Document();self.w.document.commit(a.bodies);self.w.refresh()
        with patch('rccad.studio.QFileDialog.getSaveFileName',return_value=(str(path),'')):
            self.w.export_flat_pattern(self.w.document.get(a.id));self.wait()

    def test_all_wall_bend_lines_match_before_and_after_unfolding(self):
        import ezdxf
        with k.deferred_mesh():
            a=Assembly();a.bend('F');a.bend('B');left=a.wall('L');right=a.wall('R')
            a.bend('B',bid=left,length=12);a.bend('B',bid=right,length=12)
        paths=[Path(self.folder.name)/f'{i}.dxf' for i in range(2)];values=[]
        for index,path in enumerate(paths):
            if index:
                with k.deferred_mesh():a.bodies=h.run_sheetmode(a.bodies,dict(id=a.id,flat=True))
            self.export(a,path);doc=ezdxf.readfile(path);self.assertFalse(doc.audit().errors)
            lines=[x for x in doc.modelspace() if x.dxf.layer.startswith('BEND_')]
            self.assertEqual(len(lines),4)
            values.append(sorted((x.dxf.layer,tuple(round(v,5) for v in (x.dxf.start.x,x.dxf.start.y)),tuple(round(v,5) for v in (x.dxf.end.x,x.dxf.end.y))) for x in lines))
            for line in lines:self.assertTrue(line.has_xdata('RCCAD'))
        self.assertEqual(values[0],values[1])

    def test_failed_wall_development_never_overwrites_dxf(self):
        from unittest.mock import patch
        with k.deferred_mesh():a=Assembly();a.wall('R')
        path=Path(self.folder.name)/'existing.dxf';path.write_bytes(b'previous complete file')
        with patch.object(self.w,'_flat_tab_walls',side_effect=k.CadError('Wall cannot unfold')):
            self.export(a,path)
        self.assertEqual(path.read_bytes(),b'previous complete file')

    def test_legacy_history_without_sheet_metadata_can_export(self):
        import ezdxf
        from unittest.mock import patch
        from test_sheetmetal_parallel import small_box
        r=small_box(90,3);body=Body('Starsza blacha',s.base_solid(r['base'])).prepared()
        face=next(f for f in body.shape.Faces() if f.geomType()=='PLANE' and f.normalAt().z>.99)
        w=self.w;w.document.commit([body])
        conv=dict(type='sheet',id=body.id,base=r['base'],t=1,rules=r['rules'],face=h.face_ref(face,[0,0,1],face.Center().toTuple(),body.shape))
        w.document.commit([body],op=conv)
        legacy=body.changed(s.build_sheet(r,parallel_version=1));w.document.commit([legacy],op=dict(r,type='sheetbuild',id=body.id));w.refresh()
        path=Path(self.folder.name)/'legacy.dxf'
        with patch('rccad.studio.QFileDialog.getSaveFileName',return_value=(str(path),'')):
            w.export_flat_pattern(legacy);self.wait()
        doc=ezdxf.readfile(path);self.assertFalse(doc.audit().errors)
        self.assertTrue(any(x.dxf.layer.startswith('BEND_') for x in doc.modelspace()))
