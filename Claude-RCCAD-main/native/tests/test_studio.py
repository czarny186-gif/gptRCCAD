"""Okno Studio: układ jak w HTML oraz przepływ szkic → wyciągnięcie → Boolean / zaokrąglenie / lustro."""
import os, faulthandler
faulthandler.dump_traceback_later(600, exit=True, file=open(os.environ.get("DIAG_FILE","diag_hang.txt"),"w"))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import time, math
import tempfile
from pathlib import Path
import numpy as np
import unittest
from unittest.mock import patch
from PySide6.QtCore import QEvent,Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from rccad import kernel as k
from rccad import history as hist
from rccad.document import Body
from rccad.studio import StudioWindow


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.w=StudioWindow();self.w.resize(1400,850);self.w.show();self.app.processEvents()
        self.patches=[patch.object(QMessageBox,'warning',return_value=QMessageBox.Ok),patch.object(QMessageBox,'information',return_value=QMessageBox.Ok)]
        for p in self.patches:p.start()

    def tearDown(self):
        self.wait();self.w.document._saved_revision=self.w.document._revision;self.w.close();self.app.processEvents()
        for p in self.patches:p.stop()

    def wait(self):
        end=time.monotonic()+20
        while self.w.busy and time.monotonic()<end:
            self.app.processEvents();time.sleep(.005)
        self.app.processEvents()
        self.assertFalse(self.w.busy)

    def preview(self):
        end=time.monotonic()+20
        while time.monotonic()<end and any(st['running'] or st['pending'] for st in self.w._pv.values()):
            self.app.processEvents();time.sleep(.005)
        self.app.processEvents()

    def sketch(self,tool,*points,plane='XY'):
        if self.w.mode!='sketch':self.w.set_mode('plane');self.w.plane_picked(plane)
        self.w.choose_tool(tool)
        for p in points:self.w.sketch_clicked(plane,*p)
        self.wait()

    def test_objects_panel_lists_selects_hides_deletes(self):
        w=self.w
        a=Body('Szkic XY',k.sketch('rectangle','XY',10,10),'sketch','XY').prepared()
        b=Body('Tekst XY',k.sketch('rectangle','XY',10,10,20,0),'sketch','XY').prepared()
        c=Body('Bryła',k.box(10,10,10),'solid').prepared()
        w.document.commit((a,b,c));w.refresh();self.app.processEvents()
        self.assertEqual(len(w.objects.rows),3)
        self.assertEqual([w._obj_no[i.id] for i in (a,b,c)],[1,1,1])
        w.objects_select(a.id,Qt.NoModifier);w.objects_select(c.id,Qt.ShiftModifier)
        self.assertEqual(set(w.selected),{a.id,c.id})
        w.objects_select(c.id,Qt.ShiftModifier);self.assertEqual(w.selected,[a.id])
        w.objects_select(a.id,Qt.NoModifier);self.assertEqual(w.selected,[])      # ponowny klik odznacza
        w.objects_hover(c.id);self.assertEqual(w._obj_hover,c.id);self.assertIn(c.id,w.view.selected_bodies);w.objects_hover('');self.assertNotIn(c.id,w.view.selected_bodies)
        w.objects_hide(a.id);self.assertEqual(w.selected,[]);self.assertIn(a.id,w.hidden_ids)
        w.objects_select(a.id,Qt.NoModifier);self.assertEqual(w.selected,[a.id]);self.assertIn(a.id,w.view.selected_bodies);w.objects_select(a.id,Qt.NoModifier)
        w.objects_lock(b.id);self.assertIn(b.id,w.view.locked);w.objects_select(b.id,Qt.NoModifier);self.assertEqual(w.selected,[b.id]);w.objects_select(b.id,Qt.NoModifier)
        w.objects_delete(c.id);self.wait()
        self.assertEqual({x.id for x in w.document.bodies},{a.id,b.id})
        self.assertEqual(len(w.objects.rows),2)
        w.undo();self.wait();self.assertEqual(len(w.objects.rows),3)
        self.assertEqual(w._obj_no[c.id],1)
        w.redo();self.wait();self.assertEqual(len(w.objects.rows),2)

    def test_click_on_letter_selects_whole_text_shift_removes_one(self):
        from rccad import history as hist
        w=self.w;shapes=k.text_shape('XY','Abc',0,0,10)
        ids=hist.text_ids(hist.new_text_group(),len(shapes))
        w.document.commit(tuple(Body('Tekst XY',sh,'sketch','XY',id=i).prepared() for sh,i in zip(shapes,ids)));w.refresh()
        key,(plane,bodies)=next(iter(w._drawn_sketches().items()))
        letters=[f for f in w._regions_for(key,plane,bodies)];self.assertGreaterEqual(len(letters),3)
        face=letters[0];pt=hist._inner_point(face)
        src=dict(kind='region',id=None,face=face,wire=face.outerWire(),plane=plane,normal=tuple(k.frame_of(plane).normal),center=face.Center().toTuple())
        with patch.object(w.view,'_plane_hit',return_value=(1.0,pt)):out=w._with_letters(src,5,5)
        self.assertTrue(out.get('letters'));n=len(out['siblings'])+1;self.assertEqual(n,3)   # A, b, c (wnętrza liter nie są materiałem)
        w.set_mode('extrude')
        with patch.object(w,'_profile_at',return_value=out):w.pick_profile(5,5,False)
        self.assertEqual(len(w.ex_profiles),n)
        with patch.object(w,'_profile_at',return_value=out):w.pick_profile(5,5,True)
        self.assertEqual(len(w.ex_profiles),n-1)
        with patch.object(w,'_profile_at',return_value=out):w.pick_profile(5,5,True)
        self.assertEqual(len(w.ex_profiles),n)

    def test_revolve_tool_history_undo_and_panel(self):
        import math
        from rccad import history as hist
        w=self.w;sk=Body('Szkic XY',k.sketch('rectangle','XY',10,20,10,10),'sketch','XY').prepared();w.document.commit([sk]);w.refresh()
        self.assertIn('revolve',w.tools);w.toggle_mode('revolve');self.assertEqual(w.mode,'revolve');self.assertTrue(w.rev_panel.isVisible())
        src=dict(kind='sketch',id=sk.id,face=None,wire=sk.shape,plane='XY',normal=(0,0,1),center=sk.shape.Center().toTuple())
        with patch.object(w,'_profile_at',return_value=src):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.rev_profiles),1);self.assertEqual(w.rev_axis.currentData(),'v')      # profil leży po jednej stronie osi pionowej
        w.apply_revolve();self.wait()
        solids=[b for b in w.document.bodies if b.kind=='solid'];self.assertEqual(len(solids),1)
        self.assertAlmostEqual(solids[0].shape.Volume(),math.pi*(15**2-5**2)*20,1);self.assertEqual(solids[0].name,'Obrót')
        infos,cur=w.document.infos();self.assertEqual((infos[-1]['icon'],infos[-1]['op']['type']),('revolve','revolve'))
        self.assertIsNone(w.mode)
        base=w.document.states()[cur-1][0];again=hist.run_recipe(base,infos[-1]['op'])
        self.assertAlmostEqual([b for b in again if b.kind=='solid'][0].shape.Volume(),solids[0].shape.Volume(),2)
        w.undo();self.wait();self.assertFalse([b for b in w.document.bodies if b.kind=='solid'])
        w.redo();self.wait();self.assertEqual(len([b for b in w.document.bodies if b.kind=='solid']),1)
        w.toggle_mode('revolve');self.assertEqual(w.rev_step2.value.text(),'Najpierw wybierz profil')

    def test_sheet_rules_panel_holds_gap_and_relief(self):
        w=self.w
        self.assertIn('rules',w.tools)
        w.toggle_mode('rules');self.assertEqual(w.mode,'rules');self.assertTrue(w.rules_panel.isVisible())
        w.fl_gap.setValue(1.5);w.fl_relief.setCurrentIndex(w.fl_relief.count()-1)
        self.assertEqual(w.fl_gap.value(),1.5)
        self.assertIn(w.fl_relief.currentData(),('none','square','round'))
        self.assertFalse(w.flange_panel.isVisible())
        w.toggle_mode('rules');self.assertIsNone(w.mode)

    def converted_sheet(self):
        from rccad import sheetmetal as shm
        w = self.w
        body = Body('Test blachy', k.box(100, 50, 2), 'solid').prepared()
        w.document.commit([body])
        face = next(f for f in body.shape.Faces() if abs(f.Center().z-2) < 1e-6)
        info = shm.sheet_of_face(body.shape, face)
        w.sheet_pick = dict(id=body.id, face=face, normal=(0,0,1), point=face.Center().toTuple(), info=info)
        w.apply_sheet();self.wait()
        w.toggle_mode('flange')
        w.fl_pick = dict(id=body.id, spec=dict(kind='base', p0=[100,0,2], p1=[100,50,2], n=[0,0,1], m=[1,0,0]))
        return body

    def test_flange_mode_highlights_only_edges_and_restores_object_selection(self):
        body = self.converted_sheet(); w = self.w
        self.assertEqual(w.selected, [body.id])
        self.assertNotIn(body.id, w.view.selected_bodies)
        w.apply_flange(); self.wait()
        self.assertEqual(w.selected, [body.id])
        self.assertNotIn(body.id, w.view.selected_bodies)
        w.set_mode(None)
        self.assertIn(body.id, w.view.selected_bodies)

    def test_corner_choices_hide_diagonal_and_restore_legacy_as_sheet(self):
        body = self.converted_sheet(); w = self.w
        self.assertEqual(w.fl_joint.findData('diagonal'), -1)
        state = w._sheet_state(body.id)
        op = dict(type='sheetbuild', id=body.id, base=state['base'], t=state['t'],
                  flanges=[], rules=dict(joint='diagonal'))
        w.document.commit([body], label='Stare narożniki', op=op)  # old project without sheet metadata
        w.set_mode('rules')
        self.assertEqual(w.fl_joint.currentData(), 'sheet')
        self.assertEqual(w._sheet_state(body.id)['rules']['joint'], 'diagonal')

    def test_unfold_edit_sync_fold_buttons_preserve_holes_and_history(self):
        import cadquery as cq
        w=self.w;body=self.converted_sheet()
        w.apply_flange();self.wait()
        original=w.document.get(body.id).shape.Volume()
        w.tools['unfold_sheet'].click();self.wait()
        self.assertTrue(w._sheet_state(body.id)['flat'])
        sheet=w.document.get(body.id)
        sketch=Body('Otwór',cq.Workplane('XY').center(20,20).circle(1).val(),'sketch','XY').prepared()
        op=dict(type='extrude',mode='cut',dir='one',d1=6,d2=0,
                profiles=[dict(k='sketch',id=sketch.id)],spent=[sketch.id],out=[])
        w.document.commit(hist.run_recipe([sheet,sketch],op),label='Wycięcie',op=op)
        w.selected=[body.id];w.refresh()
        w.tools['sheet_sync'].click();self.wait()
        self.assertTrue(w._sheet_state(body.id)['flat'])
        w.tools['fold_sheet'].click();self.wait()
        self.assertFalse(w._sheet_state(body.id)['flat'])
        self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),original-2*math.pi,delta=1e-4)
        w.undo();self.wait();self.assertTrue(w._sheet_state(body.id)['flat'])
        w.redo();self.wait();self.assertFalse(w._sheet_state(body.id)['flat'])

    def test_failed_refold_keeps_flat_edits_and_does_not_add_history(self):
        import cadquery as cq
        from rccad import sheetedit
        w=self.w;body=self.converted_sheet();w.apply_flange();self.wait()
        w.tools['unfold_sheet'].click();self.wait()
        current=w.document.get(body.id);metadata=current.meta['sheet']
        layout=sheetedit.layout(metadata['recipe']);point=layout.flat_bends[0].Center();t=metadata['recipe']['t']
        shape=current.shape.cut(cq.Solid.makeCylinder(.3,t/2,cq.Vector(point.x,point.y,t/2)))
        changed=current.changed(shape);w.document.commit([changed],label='Kieszeń na łuku');w.refresh()
        revision=w.document._revision;volume=shape.Volume()
        w.tools['fold_sheet'].click();self.wait()
        self.assertEqual(w.document._revision,revision)
        self.assertTrue(w._sheet_state(body.id)['flat'])
        self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),volume,delta=1e-8)

    def test_old_parallel_project_without_engine_marker_upgrades_in_the_ui(self):
        from test_sheetmetal_parallel import small_box
        from rccad import sheetmetal
        w=self.w;r=small_box(90,3)
        body=Body('Starsza blacha',sheetmetal.base_solid(r['base'])).prepared()
        face=next(f for f in body.shape.Faces() if f.geomType()=='PLANE' and f.normalAt().z>.99)
        w.document.commit([body])
        conv=dict(type='sheet',id=body.id,base=r['base'],t=1,rules=r['rules'],
                  face=hist.face_ref(face,[0,0,1],face.Center().toTuple(),body.shape))
        w.document.commit([body],op=conv)
        legacy=body.changed(sheetmetal.build_sheet(r,parallel_version=1))
        w.document.commit([legacy],op=dict(r,type='sheetbuild',id=body.id))
        w.selected=[body.id];w.refresh()
        self.assertEqual(w._editable_sheet_state(body.id)['bend_engine'],1)
        w.tools['unfold_sheet'].click();self.wait()
        current=w.document.get(body.id)
        self.assertTrue(current.meta['sheet']['flat'])
        self.assertEqual(current.meta['sheet']['bend_engine'],3)
        self.assertEqual(len(current.shape.Solids()),1)

    def test_sheet_reverse_creates_downward_bend_and_undo_redo(self):
        body = self.converted_sheet();w = self.w
        w.fl_reverse.setChecked(True)
        w.apply_flange();self.wait()
        folded = w.document.get(body.id).shape
        self.assertLess(folded.BoundingBox().zmin, -20)
        self.assertAlmostEqual(max(v.Z for v in folded.Vertices()), 2, delta=1e-6)
        w.undo();self.wait();self.assertAlmostEqual(w.document.get(body.id).shape.Volume(), 10000)
        w.redo();self.wait();self.assertAlmostEqual(w.document.get(body.id).shape.Volume(), folded.Volume())

    def test_sheet_outside_tip_pick_survives_new_dimension_setting(self):
        from rccad import sheetmetal as shm
        body = self.converted_sheet();w = self.w
        w.fl_outside.setChecked(True)
        w.apply_flange();self.wait()
        state = w._sheet_state(body.id)
        eff, _ = shm._effective(state['specs'], state['t'], True, True)
        a,b,_,_ = shm._tip_geom(eff[0], 'out', state['t'])
        midpoint = (a+b)/2
        folded = w.document.get(body.id)
        index = next(i for i,e in enumerate(folded.shape.Edges()) if np.linalg.norm(np.array(e.positionAt(.5).toTuple())-midpoint) < 1e-4)
        w.fl_outside.setChecked(False)
        w.fl_armed = False
        with patch.object(w.view, 'nearest_edge', return_value=(body.id,index,None)):
            w.pick_flange(5,5)
        self.assertEqual(w.fl_pick['spec'], dict(kind='tip',parent=0,side='out'))
        w.apply_flange();self.wait()
        state = w._sheet_state(body.id)
        self.assertEqual([s['outside'] for s in state['specs']], [True, False])
        eff, _ = shm._effective(state['specs'], state['t'], True, False)
        self.assertAlmostEqual(eff[0]['length'], 16)
        self.assertAlmostEqual(eff[1]['length'], 20)

    def test_sheet_flat_button_exports_without_changing_history(self):
        body = self.converted_sheet();w = self.w
        w.fl_miter.setChecked(False);w.apply_flange();self.wait()
        count = len(w.document.infos()[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'blank'
            with patch('rccad.studio.QFileDialog.getSaveFileName', return_value=(str(path), 'DXF (*.dxf)')):
                w.tools['flat'].click();self.wait()
            self.assertTrue(path.with_suffix('.dxf').is_file())
        self.assertEqual(len(w.document.infos()[0]), count)
        self.assertEqual(w.selected, [body.id])

    def test_sheet_box_five_mm_walls_then_returns_and_reverse_bends(self):
        body = self.converted_sheet();w = self.w
        w.fl_length.setValue(5);w.fl_gap.setValue(.2)
        edges = [([100,0,2],[100,50,2],[1,0,0]),([100,50,2],[0,50,2],[0,1,0]),
                 ([0,50,2],[0,0,2],[-1,0,0]),([0,0,2],[100,0,2],[0,-1,0])]
        picks = [dict(kind='base',p0=a,p1=b,n=[0,0,1],m=m) for a,b,m in edges]
        picks += [dict(kind='tip',parent=i,side='in') for i in range(4)]
        picks += [dict(kind='tip',parent=i+4,side='in') for i in range(4)]
        for index,pick in enumerate(picks):
            with self.subTest(step=index+1):
                w.fl_pick = dict(id=body.id,spec=pick)
                w.fl_reverse.setChecked(index >= 8)
                w.apply_flange();self.wait()
                state = w._sheet_state(body.id)
                self.assertEqual(len(state['specs']),index+1)
                self.assertTrue(w.document.get(body.id).shape.isValid())
        self.assertTrue(all(spec['side']=='out' for spec in state['specs'][8:]))
        volume = w.document.get(body.id).shape.Volume()
        w.undo();self.wait();self.assertEqual(len(w._sheet_state(body.id)['specs']),11)
        w.redo();self.wait();self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),volume,delta=.001)

    def test_sheet_rules_rebuild_existing_bends_without_adding_one(self):
        body = self.converted_sheet();w = self.w
        w.fl_outside.setChecked(True);w.apply_flange();self.wait()
        original = w.document.get(body.id).shape.Volume()
        w.toggle_mode('rules');w.fl_outside.setChecked(False);w.fl_gap.setValue(.5)
        w.fl_apply_rules.click();self.wait()
        state = w._sheet_state(body.id)
        self.assertEqual(len(state['specs']),1)
        self.assertTrue(state['specs'][0]['outside'])
        self.assertEqual(state['rules']['gap'],.5)
        self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),original,delta=.001)
        w.undo();self.wait();self.assertEqual(w._sheet_state(body.id)['rules']['gap'],0)

    def test_sheet_joint_default_and_saved_rules_are_preserved(self):
        body = self.converted_sheet();w = self.w
        self.assertEqual(w._sheet_state(body.id)['rules']['joint'],'sheet')
        w.fl_joint.setCurrentIndex(w.fl_joint.findData('parallel'))
        w.fl_gap.setValue(.7)
        w.fl_relief.setCurrentIndex(w.fl_relief.findData('round'))
        w.fl_relief_size.setValue(2)
        w.apply_flange();self.wait()
        original = w.document.get(body.id).shape.Volume()
        w.fl_joint.setCurrentIndex(w.fl_joint.findData('sheet'));w.fl_gap.setValue(0)
        w.toggle_mode('rules')
        self.assertEqual(w.fl_joint.currentData(),'parallel')
        self.assertAlmostEqual(w.fl_gap.value(),.7)
        self.assertEqual(w.fl_relief.currentData(),'round')
        self.assertAlmostEqual(w.fl_relief_size.value(),2)
        self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),original,delta=.001)
        w.fl_joint.setCurrentIndex(w.fl_joint.findData('sheet'));w.fl_apply_rules.click();self.wait()
        self.assertEqual(w._sheet_state(body.id)['rules']['joint'],'sheet')
        self.assertAlmostEqual(w.fl_gap.value(),.7)

    def _four_bottom_hems_and_refold(self,joint):
        w=self.w;body=self.converted_sheet()
        w.fl_joint.setCurrentIndex(w.fl_joint.findData(joint));w.apply_sheet_rules();self.wait()
        w.toggle_mode('hem');w.hm_radius.setValue(1);w.hm_gap.setValue(.2);w.hm_length.setValue(5)
        for count,point in enumerate(((100,25,0),(50,50,0),(0,25,0),(50,0,0)),1):
            current=w.document.get(body.id)
            index=next(i for i,edge in enumerate(current.shape.Edges()) if edge.geomType()=='LINE' and
                       np.linalg.norm(np.array(edge.positionAt(.5).toTuple())-point)<1e-5)
            with patch.object(w.view,'nearest_edge',return_value=(body.id,index,None)):
                w.view_clicked(5,5,False,False)
            if count==1:w.apply_hem()
            self.wait()
            state=w._sheet_state(body.id)
            self.assertEqual(len(state['specs']),count)
            self.assertLess(state['specs'][-1]['n'][2],-.99)
            self.assertEqual(state['rules']['joint'],joint)
        original=w.document.get(body.id).shape
        w.tools['unfold_sheet'].click();self.wait()
        self.assertTrue(w._sheet_state(body.id)['flat'],w.notice.text())
        self.assertEqual(len(w.document.get(body.id).shape.Solids()),1)
        w.tools['fold_sheet'].click();self.wait()
        self.assertFalse(w._sheet_state(body.id)['flat'])
        folded=w.document.get(body.id).shape
        self.assertLess(folded.cut(original).Volume(1e-9)+original.cut(folded).Volume(1e-9),1e-4)

    def test_four_bottom_parallel_hems_can_be_picked_unfolded_and_refolded(self):
        self._four_bottom_hems_and_refold('parallel')

    def test_four_bottom_sheet_hems_can_be_picked_unfolded_and_refolded(self):
        self._four_bottom_hems_and_refold('sheet')

    def test_hem_tool_is_separate_and_adds_hem(self):
        w=self.w;plate=Body('Blacha',k.box(100,50,2),'solid').prepared();w.document.commit([plate]);w.refresh()
        self.assertIn('hem',w.tools)
        w.toggle_mode('sheet')
        top=[f for f in plate.shape.Faces() if abs(f.Center().z-2)<1e-6 and f.geomType()=='PLANE'][0]
        c=top.Center();hit=(plate.id,(0,0,1),(c.x,c.y,c.z))
        with patch.object(w.view,'pick_face',return_value=hit):
            w.view_clicked(5,5,False,False)
        w.apply_sheet();self.wait()
        w.toggle_mode('hem');self.assertTrue(w.hem_panel.isVisible());self.assertFalse(w.flange_panel.isVisible())
        edge=[(i,e) for i,e in enumerate(plate.shape.Edges()) if abs(e.positionAt(0).x-100)<1e-6 and abs(e.positionAt(1).x-100)<1e-6 and abs(e.positionAt(0).z-2)<1e-6 and abs(e.positionAt(1).z-2)<1e-6][0]
        with patch.object(w.view,'nearest_edge',return_value=(plate.id,edge[0],None)):
            w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.fl_pick)
        w.hm_gap.setValue(0.5);w.apply_hem();self.wait()
        infos,_=w.document.infos();op=infos[-1]['op']
        self.assertEqual(op['type'],'sheetbuild');self.assertIn('hem',op['flanges'][-1])
        solid=[b for b in w.document.bodies if b.kind=='solid'][0]
        self.assertGreater(solid.shape.Volume(),10000+100)

    def test_sheet_tab_convert_then_flange(self):
        from rccad import history as hist
        w=self.w;plate=Body('Blacha',k.box(100,50,2),'solid').prepared();w.document.commit([plate]);w.refresh()
        self.assertIn('sheet',w.tools);self.assertIn('flange',w.tools)
        w.toggle_mode('sheet');self.assertEqual(w.mode,'sheet');self.assertTrue(w.sheet_panel.isVisible())
        top=[f for f in plate.shape.Faces() if abs(f.Center().z-2)<1e-6 and f.geomType()=='PLANE'][0]
        c=top.Center();hit=(plate.id,(0,0,1),(c.x,c.y,c.z))
        with patch.object(w.view,'pick_face',return_value=hit):
            w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.sheet_pick);self.assertIn('Blacha 2.00 mm',w.sheet_status.text())
        w.apply_sheet();self.wait()
        self.assertAlmostEqual(w._sheet_state(plate.id)['t'],2,6)
        infos,_=w.document.infos();self.assertEqual((infos[-1]['icon'],infos[-1]['op']['type']),('sheet','sheet'))
        w.toggle_mode('flange');self.assertTrue(w.flange_panel.isVisible())
        edge=[(i,e) for i,e in enumerate(plate.shape.Edges()) if abs(e.positionAt(0).x-100)<1e-6 and abs(e.positionAt(1).x-100)<1e-6 and abs(e.positionAt(0).z-2)<1e-6 and abs(e.positionAt(1).z-2)<1e-6][0]
        with patch.object(w.view,'nearest_edge',return_value=(plate.id,edge[0],None)):
            w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.fl_pick);self.assertIn('w górę',w.fl_status.text())
        w.fl_length.setValue(20);w.apply_flange();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0]
        self.assertGreater(solid.shape.Volume(),10000+100)
        infos,cur=w.document.infos();self.assertEqual((infos[-1]['icon'],infos[-1]['op']['type']),('flange','sheetbuild'))
        base=w.document.states()[cur-1][0];again=hist.run_recipe(base,infos[-1]['op'])
        self.assertAlmostEqual([b for b in again if b.kind=='solid'][0].shape.Volume(),solid.shape.Volume(),1)
        w.undo();self.wait();self.assertAlmostEqual([b for b in w.document.bodies if b.kind=='solid'][0].shape.Volume(),10000,1)

    def test_shell_tool_history_undo_and_panel(self):
        from rccad import history as hist
        w=self.w;box=Body('Pudełko',k.box(20,20,20),'solid').prepared();w.document.commit([box]);w.refresh()
        self.assertIn('shell',w.tools);w.toggle_mode('shell');self.assertEqual(w.mode,'shell');self.assertTrue(w.shell_panel.isVisible())
        top=[f for f in box.shape.Faces() if abs(f.normalAt().toTuple()[2]-1)<1e-6 and abs(f.Center().z-20)<1e-6][0]
        c=top.Center();hit=(box.id,(0,0,1),(c.x,c.y,c.z))
        with patch.object(w.view,'pick_face',return_value=hit):
            w._hover_shell_solid(5,5);self.assertTrue(w.view.preview_items)      # bryła podświetla się jeszcze przed wyborem
            w.view_clicked(5,5,False,False);self.assertEqual(w.sh_id,box.id);self.assertEqual(w.sh_faces,[])
            self.assertEqual(w.selected,[box.id]);self.assertTrue(w.view.xray)       # wybrana bryła świeci się, a podgląd widać przez przezroczystość
            w.view_clicked(5,5,False,False);self.assertEqual(len(w.sh_faces),1)
            w.view_clicked(5,5,False,False);self.assertEqual(len(w.sh_faces),0)       # ponowne kliknięcie cofa otwarcie
            w.view_clicked(5,5,False,False);self.assertEqual(len(w.sh_faces),1)
        w.sh_thick.setValue(2);w.apply_shell();self.wait();self.assertFalse(w.view.xray)
        solid=[b for b in w.document.bodies if b.kind=='solid'][0];self.assertAlmostEqual(solid.shape.Volume(),8000-16*16*18,1)
        infos,cur=w.document.infos();self.assertEqual((infos[-1]['icon'],infos[-1]['op']['type']),('shell','shell'));self.assertIsNone(w.mode)
        base=w.document.states()[cur-1][0];again=hist.run_recipe(base,infos[-1]['op'])
        self.assertAlmostEqual([b for b in again if b.kind=='solid'][0].shape.Volume(),solid.shape.Volume(),2)
        w.undo();self.wait();self.assertAlmostEqual([b for b in w.document.bodies if b.kind=='solid'][0].shape.Volume(),8000,1)
        w.redo();self.wait();self.assertAlmostEqual([b for b in w.document.bodies if b.kind=='solid'][0].shape.Volume(),solid.shape.Volume(),1)

    def test_about_dialog_has_name_version_date_and_author(self):
        from rccad.about import AboutDialog
        from rccad import FULL_VERSION
        d=AboutDialog(self.w);v={key:label.text() for key,label in d.values.items()}
        self.assertEqual(v['Nazwa'],'RCCAD Desktop');self.assertEqual(v['Wersja'],FULL_VERSION);self.assertEqual(v['Twórca'],'Radosław Czarnota');self.assertTrue(v['Data utworzenia']);d.close()
        self.assertTrue(hasattr(self.w,'show_about'))

    def _solids(self):
        return [b for b in self.w.document.bodies if b.kind=='solid']

    def test_sweep_tool_history_undo(self):
        from rccad import history as hist
        w=self.w;prof=Body('Szkic XY',k.sketch('rectangle','XY',10,10,0,0),'sketch','XY').prepared()
        path=Body('Ścieżka',k.polyline('XZ',[(0,0),(0,30)]),'sketch','XZ').prepared();w.document.commit([prof,path]);w.refresh()
        w.toggle_mode('sweep');self.assertEqual(w.mode,'sweep');self.assertTrue(w.sweep_panel.isVisible())
        src=dict(kind='sketch',id=prof.id,face=None,wire=prof.shape,plane='XY',normal=(0,0,1),center=prof.shape.Center().toTuple())
        with patch.object(w,'_profile_at',return_value=src):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.sw_profiles),1);self.assertIsNone(w.sw_path)
        with patch.object(w.view,'nearest_edge',return_value=(path.id,0)):w.view_clicked(6,6,False,False)
        self.assertEqual(w.sw_path['k'],'sketch');w.apply_sweep();self.wait()
        solids=self._solids();self.assertEqual(len(solids),1);self.assertAlmostEqual(solids[0].shape.Volume(),3000,1)
        infos,cur=w.document.infos();self.assertEqual((infos[-1]['icon'],infos[-1]['op']['type']),('sweep','sweep'))
        again=hist.run_recipe(w.document.states()[cur-1][0],infos[-1]['op']);self.assertAlmostEqual([b for b in again if b.kind=='solid'][0].shape.Volume(),3000,1)
        w.undo();self.wait();self.assertFalse(self._solids());w.redo();self.wait();self.assertEqual(len(self._solids()),1)

    def test_loft_tool_profiles_point_history_undo(self):
        from rccad import history as hist
        w=self.w;fr=k.Frame((0,0,20),(1,0,0),(0,0,1))
        a=Body('Dół',k.sketch('rectangle','XY',10,10,0,0),'sketch','XY').prepared();b=Body('Góra',k.sketch('rectangle',fr,6,6,0,0),'sketch',fr).prepared()
        w.document.commit([a,b]);w.refresh();w.toggle_mode('loft');self.assertEqual(w.mode,'loft');self.assertTrue(w.loft_panel.isVisible())
        mk=lambda body,plane,n:dict(kind='sketch',id=body.id,face=None,wire=body.shape,plane=plane,normal=n,center=body.shape.Center().toTuple())
        sa,sb=mk(a,'XY',(0,0,1)),mk(b,fr,(0,0,1))
        with patch.object(w,'_profile_at',return_value=sa):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.lf_profiles),1);self.assertFalse(w._lf_ready())
        w.lf_kind.setCurrentIndex(1)
        with patch.object(w.view,'nearest_vertex',return_value=(a.id,(0,0,15))):w.view_clicked(5,5,False,False)
        self.assertEqual(w.lf_point,(0.0,0.0,15.0));self.assertTrue(w._lf_ready());self.assertAlmostEqual(w._lf_tool()().Volume(),500,1)
        w.lf_kind.setCurrentIndex(0);self.assertIsNone(w.lf_point)
        with patch.object(w,'_profile_at',return_value=sb):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.lf_profiles),2);w.apply_loft();self.wait()
        solids=self._solids();self.assertEqual(len(solids),1);self.assertAlmostEqual(solids[0].shape.Volume(),20/3*(100+36+60),1)
        infos,cur=w.document.infos();self.assertEqual((infos[-1]['icon'],infos[-1]['op']['type']),('loft','loft'))
        again=hist.run_recipe(w.document.states()[cur-1][0],infos[-1]['op']);self.assertAlmostEqual([x for x in again if x.kind=='solid'][0].shape.Volume(),solids[0].shape.Volume(),1)
        w.undo();self.wait();self.assertFalse(self._solids());w.redo();self.wait();self.assertEqual(len(self._solids()),1)

    def test_tabs_switch_with_tools_and_measurements(self):
        w=self.w;self.assertEqual(w._tab,'Szkic')
        w.toggle_mode('extrude');self.assertEqual(w._tab,'Bryła');self.assertTrue(w.tab_buttons['Bryła'].isChecked());w.set_mode(None)
        w.toggle_mode('shell');self.assertEqual(w._tab,'Edycja');w.set_mode(None)
        box=Body('Pudło',k.box(10,20,30),'solid').prepared();sk=Body('Szkic',k.sketch('circle','XY',10,0,50,0),'sketch','XY').prepared()
        w.document.commit([box,sk]);w.refresh()
        w.toggle_mode('mdist');self.assertEqual(w._tab,'Pomiary');self.assertTrue(w.ms_panels['mdist'].isVisible())
        with patch.object(w.view,'nearest_vertex',side_effect=[(box.id,(0,0,0)),(box.id,(3,4,12))]):
            w.view_clicked(5,5,False,False);w.view_clicked(6,6,False,False)
        self.assertIn('13.000',w.ms_status['mdist'].text());self.assertIn('ΔZ 12.000',w.ms_status['mdist'].text())
        w.toggle_mode('mdist');w.toggle_mode('mangle')
        with patch.object(w.view,'nearest_vertex',side_effect=[(box.id,(1,0,0)),(box.id,(0,0,0)),(box.id,(0,1,0))]):
            for _ in range(3):w.view_clicked(5,5,False,False)
        self.assertIn('90.00',w.ms_status['mangle'].text())
        w.toggle_mode('mangle');w.toggle_mode('mrad')
        with patch.object(w.view,'nearest_edge',return_value=(sk.id,0)):w.view_clicked(5,5,False,False)
        self.assertIn('Promień: 5.000',w.ms_status['mrad'].text());self.assertIn('Średnica: 10.000',w.ms_status['mrad'].text())
        w.toggle_mode('mrad');w.toggle_mode('mprops')
        with patch.object(w.view,'pick_face',return_value=(box.id,(0,0,1),(5,10,30))):w.view_clicked(5,5,False,False)
        self.assertIn('6,000.00 mm³',w.ms_status['mprops'].text());self.assertIn('10.000 × 20.000 × 30.000',w.ms_status['mprops'].text())
        w.set_mode(None)

    def test_drawing_tab_opens_window_and_auto_saves(self):
        w=self.w;box=Body('Pudło',k.box(10,20,30),'solid').prepared();w.document.commit([box]);w.refresh()
        w.toggle_mode('drawing');self.assertEqual(w._tab,'Rysunek');self.assertTrue(w.dr_panels['drawing'].isVisible())
        with patch.object(w.view,'pick_face',return_value=(box.id,(0,0,1),(5,10,30))):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w._drawing_windows),1);self.assertTrue(w._drawing_windows[0].isVisible());w._drawing_windows[0].close()
        import tempfile,os
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'auto.pdf')
            w.toggle_mode('autodrawing')
            with patch.object(w.view,'pick_face',return_value=(box.id,(0,0,1),(5,10,30))),patch('rccad.studio.QFileDialog.getSaveFileName',return_value=(path,'PDF')):
                w.view_clicked(5,5,False,False);self.wait()
            self.assertTrue(os.path.getsize(path)>500)

    def test_objects_list_rename_and_group_delete_are_in_history(self):
        w=self.w;from rccad import history as hist
        a=Body('Pudło A',k.box(10,10,10),'solid').prepared();b=Body('Pudło B',k.box(5,5,5),'solid').prepared();sk=Body('Szkic',k.sketch('circle','XY',10,0,50,0),'sketch','XY').prepared()
        w.document.commit([a,b,sk]);w.refresh()
        w.objects_rename(a.id,'Korpus');self.assertEqual(w.document.get(a.id).name,'Korpus')
        infos,cur=w.document.infos();self.assertEqual(infos[-1]['op']['type'],'rename');self.assertIn('Korpus',infos[-1]['label'])
        again=hist.run_recipe(w.document.states()[cur-1][0],infos[-1]['op']);self.assertEqual([x.name for x in again if x.id==a.id],['Korpus'])
        w.undo();self.assertEqual(w.document.get(a.id).name,'Pudło A');w.redo();self.assertEqual(w.document.get(a.id).name,'Korpus')
        w.objects_group_delete('solid');self.assertEqual([x.kind for x in w.document.bodies],['sketch'])
        infos,_=w.document.infos();self.assertEqual(infos[-1]['op']['type'],'delete');self.assertEqual(len(infos[-1]['op']['ids']),2)
        w.undo();self.assertEqual(len([x for x in w.document.bodies if x.kind=='solid']),2)
        row=w.objects.rows[a.id];row.start_edit();row.edit.setText('Nowa');row.edit.returnPressed.emit();self.wait()
        self.app.processEvents();self.assertEqual(w.document.get(a.id).name,'Nowa')

    def test_change_sketch_surface_without_leaving_and_loft_preview_survives_hover(self):
        w=self.w;box=Body('Pudło',k.box(10,20,30),'solid').prepared();w.document.commit([box]);w.refresh()
        w.toggle_mode('sketch');w.enter_sketch('XY');self.assertEqual(w.mode,'sketch')
        self.app.processEvents();self.assertTrue(w.tools['surface'].isVisibleTo(w.view));self.assertFalse(w.sk_bar.isVisible())
        w.pick_other_surface();self.assertEqual(w.mode,'plane')
        with patch.object(w.view,'pick_face',return_value=(box.id,(0,0,1),(5,10,30))):w.view_clicked(5,5,False,False)
        self.assertEqual(w.mode,'sketch');self.assertFalse(isinstance(w.sketch_plane,str))
        w.pick_other_surface();self.assertEqual(w.mode,'plane');w.set_mode(None)
        w.set_mode('loft');w._result_preview=True
        with patch.object(w,'_hover_extrude') as hover:
            w.view_hover(5,5);hover.assert_not_called()
            w._result_preview=False;w.view_hover(5,5);hover.assert_called()
        w.set_mode(None)

    def test_layout_matches_html_measurements(self):
        w=self.w;W=w.view.width()
        from rccad.studio import TABS
        b=w.tools['file'];self.assertEqual((b.x(),b.y(),b.width(),b.height()),(18,50,52,52))
        for tab,keys in TABS.items():
            w.set_tab(tab);self.app.processEvents()
            for i,key in enumerate(keys):
                b=w.tools[key];self.assertEqual(b.isVisibleTo(w.view),key!='surface',key);self.assertEqual((b.x(),b.y(),b.width(),b.height()),(78+60*i,50,52,52),key)
            for other,okeys in TABS.items():
                if other!=tab:
                    for key in okeys:self.assertFalse(w.tools[key].isVisibleTo(w.view),key)
        w.set_tab('Szkic')
        self.assertEqual(w.cube.width(),138);self.assertEqual(w.cube.x(),W-160)
        self.assertEqual(w.undo_button.x(),W-398);self.assertEqual(w.redo_button.x(),W-350);self.assertEqual(w.layers.x(),W-302);self.assertEqual(w.xray.x(),W-254)
        self.assertFalse(w.shape_bar.isVisible())

    def test_rectangle_is_live_on_any_plane(self):
        w=self.w
        for plane in ('XY','XZ','YZ'):
            w.set_mode(None);w.set_mode('plane');w.plane_picked(plane);w.choose_tool('rect')
            w.sketch_clicked(plane,0,0);w.sketch_moved(plane,20,10);self.assertTrue(w.view.preview_items,plane)
            self.assertIn('20,000',w.dim.text())
            w.sketch_clicked(plane,20,10);self.wait()
        self.assertEqual([b.plane for b in w.document.bodies],['XY','XZ','YZ'])

    def test_sketch_on_solid_face_and_live_preview(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('plane')
        with patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],[10,10,20])):
            w.view_hover(5,5);w.view_clicked(5,5,False,False)
        self.assertEqual(w.mode,'sketch');self.assertNotIsInstance(w.sketch_plane,str)
        w.choose_tool('circle');w.sketch_clicked(w.sketch_plane,10,10);w.sketch_moved(w.sketch_plane,14,10)
        self.preview();self.assertTrue(w.view.preview_items);w.sketch_clicked(w.sketch_plane,14,10);self.wait()
        sk=w.document.bodies[-1];self.assertEqual(sk.kind,'sketch');self.assertAlmostEqual(k.bounds(sk.shape).zmin,20,3)

    def test_all_supported_shapes_create_sketches(self):
        cases=[('centerRect',[(0,0),(10,5)]),('circle',[(0,0),(8,0)]),('circle2',[(0,0),(10,0)]),('circle3',[(10,0),(0,10),(-10,0)]),
               ('ellipse',[(0,0),(12,6)]),('slot',[(0,0),(20,0),(0,4)]),('polygon',[(0,0),(10,0)])]
        for tool,points in cases:
            before=len(self.w.document.bodies);self.sketch(tool,*points)
            self.assertEqual(len(self.w.document.bodies),before+1,tool)

    def pick_sketch_profile(self,sk):
        with patch.object(self.w.view,'pick_profile',return_value=sk.id):self.w.view_clicked(5,5,False,False)

    def test_rotated_sketch_extrudes_along_its_tilt(self):
        from dataclasses import replace as rep
        w=self.w;self.sketch('rect',(0,0),(20,10));b=w.document.bodies[0]
        tilted=k.transform(b.shape,(0,0,0),(10,0,0));w.document.commit([rep(b,shape=tilted,mesh=k.display_mesh(tilted))])
        centre=np.array(tilted.Center().toTuple())
        for patches in (dict(),dict(_region_at=None)):
            with patch.object(w.view,'_plane_hit',lambda pl,x,y:(1.0,centre)),patch.object(w.view,'pick_face',return_value=None),patch.object(w.view,'pick_profile',return_value=b.id):
                if patches:
                    with patch.object(w,'_region_at',return_value=None):src=w._profile_at(5,5)
                else:src=w._profile_at(5,5)
            self.assertAlmostEqual(abs(src['normal'][2]),math.cos(math.radians(10)),4);self.assertGreater(abs(src['normal'][1]),.1)
            w.ex_profiles=[src];w.ex_value.setValue(10)
            solid=w._make_tools()[0]();self.assertAlmostEqual(solid.Volume(),2000,1)
            self.assertAlmostEqual(solid.BoundingBox().ylen,10*math.cos(math.radians(10))+10*math.sin(math.radians(10)),2)

    def test_smallest_coplanar_region_wins_over_old_profile(self):
        w=self.w;self.sketch('rect',(0,0),(20,20))
        fr=k.Frame((0.0,0.0,0.0),(1.0,0.0,0.0),(0.0,0.0,-1.0))
        c=Body('Szkic ściana',k.sketch_shape('circle',fr,[(10,-10),(13,-10)]),'sketch',fr).prepared();w.document.commit([*w.document.bodies,c]);w.refresh()
        with patch.object(w.view,'_plane_hit',lambda pl,x,y:(5.0,np.array([10.0,10.0,0.0]))):
            region=w._region_at(5,5)
        self.assertIsNotNone(region);self.assertLess(region[2].Area(),100)

    def test_extrude_by_clicking_profile_with_preview(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));w.set_mode('extrude')
        self.pick_sketch_profile(w.document.bodies[0]);w.ex_value.setValue(15)
        self.assertTrue(w.ex_bar.isVisible());self.preview();self.assertTrue(w.view.preview_items);self.assertTrue(w.view.handles)
        w.apply_extrude();self.wait()
        solids=[b for b in w.document.bodies if b.kind=='solid'];self.assertEqual(len(solids),1)
        self.assertAlmostEqual(solids[0].shape.Volume(),20*10*15,2);self.assertIsNone(w.mode)

    def test_extrude_arrow_drag_changes_distance_live(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_value.setValue(10);w.handle_dragged('ex',5.04);self.assertAlmostEqual(w.ex_value.value(),15.0,1)
        w.handle_dragged('ex',-2.0);self.assertAlmostEqual(w.ex_value.value(),8.0,1);w.handle_released('ex');self.assertIsNone(w._hv)

    def test_two_sided_extrude(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_dir.setCurrentIndex(2);w.ex_value.setValue(10);w.ex_second.setValue(5);w.apply_extrude();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0];self.assertAlmostEqual(solid.shape.Volume(),1500,2)

    def test_sketch_on_inclined_loft_face_extrudes_flush(self):
        """Szkic na pochylonej ścianie bryły z wyciągnięcia złożonego: wyciągnięcie musi przylegać do ściany (bez przerwy) i dodawać objętość."""
        import cadquery as cq
        rect=lambda a,b,z,cx=0,cy=0:cq.Wire.makePolygon([cq.Vector(cx-a/2,cy-b/2,z),cq.Vector(cx+a/2,cy-b/2,z),cq.Vector(cx+a/2,cy+b/2,z),cq.Vector(cx-a/2,cy+b/2,z)],close=True)
        problems=[]
        for name,wires in (('mały nad dużym',[rect(60,40,0),rect(20,12,40,5,3)]),('daleko',[rect(80,50,0),rect(10,6,90,-8,4)])):
            solid=k.loft_wires(wires)
            for fi in range(6):
                w=self.w;w.set_mode(None);self.wait()
                try:
                    a=Body('L',solid,'solid').prepared();w.document.commit([a]);w.refresh()
                    face=solid.Faces()[fi]
                    if abs(face.normalAt().z)>.999:continue
                    mesh=k.display_mesh(face);tri=np.asarray(mesh.vertices,float)[np.asarray(mesh.triangles)][0]
                    nrm=np.cross(tri[1]-tri[0],tri[2]-tri[0]);nrm/=np.linalg.norm(nrm);pt=tri.mean(axis=0)
                    w.set_mode('plane')
                    with patch.object(w.view,'pick_face',return_value=(a.id,tuple(nrm),tuple(pt))):
                        w.view_clicked(5,5,False,False)
                    plane=w.sketch_plane
                    f=k.frame_of(plane);dist=abs(float((np.array(face.Center().toTuple())-np.array(f.origin))@np.array(f.normal)))
                    if dist>1e-3:problems.append(f'{name}/{fi}: płaszczyzna szkicu {dist:.3f} od ściany')
                    c=np.array(face.Center().toTuple());u,v=k.uv_of(plane,c)
                    self.wait();toasts=[];w.toast=lambda m,*a,**kw:toasts.append(m)
                    mode0=w.mode;boxes=[]
                    QMessageBox.warning=staticmethod(lambda *a,**kw:boxes.append(a[1:]) or QMessageBox.Ok)
                    w.choose_tool('circle');w.sketch_clicked(plane,u,v);w.sketch_clicked(plane,u+3,v);self.wait()
                    try:dbg=repr(w._wire([(u,v),(u+3,v)]))
                    except Exception as exc:dbg=f'wire: {type(exc).__name__} {exc}'
                    sk=[b for b in w.document.bodies if b.kind=='sketch']
                    if not sk:problems.append(f'{name}/{fi}: brak szkicu tryb={mode0}/{w.mode} narzędzie={w.tool} punkty={w.points} komunikaty={toasts} okna={boxes} wire={dbg} busy={w.busy} ciała={[(b.kind,b.name) for b in w.document.bodies]} uv={(u,v)}');continue
                    w.set_mode('extrude')
                    ray=(c+nrm*100,-nrm)
                    with patch.object(w.view,'pick_face',return_value=(a.id,tuple(nrm),tuple(c))),patch.object(w.view,'_ray',return_value=ray),patch.object(w.view,'pick_profile',return_value=sk[-1].id):
                        w.view_clicked(5,5,False,False)
                    if not w.ex_profiles:problems.append(f'{name}/{fi}: kliknięcie nie wybrało profilu');continue
                    pr=w.ex_profiles[0];fc=pr.get('face')
                    if fc is not None:
                        off=abs(float((np.array(fc.Center().toTuple())-c)@nrm))
                        if off>1e-3:problems.append(f'{name}/{fi}: profil {pr["kind"]} leży {off:.3f} od ściany')
                    w.ex_value.setValue(5)
                    w.apply_extrude();self.wait()
                    solids=[b for b in w.document.bodies if b.kind=='solid']
                    total=sum(b.shape.Volume() for b in solids)
                    gap=len(solids)>1 and len(solids[0].shape.Solids())+len(solids[1].shape.Solids())>1
                    if abs(total-(solid.Volume()+math.pi*9*5))>2 or len(solids)!=1 or len(solids[0].shape.Solids())!=1:
                        problems.append(f'{name}/{fi}: bryły={len(solids)} części={[len(b.shape.Solids()) for b in solids]} objętość {total:.1f} zamiast {solid.Volume()+math.pi*45:.1f}')
                except Exception as exc:
                    problems.append(f'{name}/{fi}: {type(exc).__name__} {exc}')
        self.assertFalse(problems,'\n'.join(problems))

    def test_sketch_on_twisted_loft_face_joins_without_gap(self):
        """Skręcona ściana (górny profil obrócony): szkic leży na płaszczyźnie przylegającej, a dodane wyciągnięcie ma się z bryłą zrastać bez przerwy."""
        import cadquery as cq
        bottom=cq.Wire.makePolygon([cq.Vector(x,y,0) for x,y in ((-30,-20),(30,-20),(30,20),(-30,20))],close=True)
        a_=math.radians(25);top=cq.Wire.makePolygon([cq.Vector(x*math.cos(a_)-y*math.sin(a_),x*math.sin(a_)+y*math.cos(a_),50) for x,y in ((-10,-6),(10,-6),(10,6),(-10,6))],close=True)
        solid=k.loft_wires([bottom,top],None,False)
        problems=[]
        for fi,face in enumerate(solid.Faces()):
            if k.is_planar_face(face) or abs(face.normalAt().z)>.99:continue
            w=self.w;w.set_mode(None);self.wait()
            a=Body('L',solid,'solid').prepared();w.document.commit([a]);w.refresh();self.wait()
            mesh=k.display_mesh(face);tri=np.asarray(mesh.vertices,float)[np.asarray(mesh.triangles)][len(mesh.triangles)//2]
            nrm=np.cross(tri[1]-tri[0],tri[2]-tri[0]);nrm/=np.linalg.norm(nrm);pt=tri.mean(axis=0)
            w.set_mode('plane')
            with patch.object(w.view,'pick_face',return_value=(a.id,tuple(nrm),tuple(pt))):w.view_clicked(5,5,False,False)
            plane=w.sketch_plane;u,v=k.uv_of(plane,pt)
            w.choose_tool('circle');w.sketch_clicked(plane,u,v);w.sketch_clicked(plane,u+2,v);self.wait()
            sk=[b for b in w.document.bodies if b.kind=='sketch']
            if not sk:problems.append(f'{fi}: brak szkicu');continue
            w.set_mode('extrude')
            with patch.object(w.view,'pick_face',return_value=None),patch.object(w.view,'pick_profile',return_value=sk[-1].id):w.view_clicked(5,5,False,False)
            pr=w.ex_profiles[0];fr=k.frame_of(plane);o_=np.array(fr.origin);n_=np.array(fr.normal)
            dbg=f"kind={pr['kind']} planeN·nrm={float(n_@nrm):.3f} dist_o_face={float(face.distance(cq.Vertex.makeVertex(*o_))):.3f} in+={solid.isInside(cq.Vector(*(o_+n_*.01)))} in-={solid.isInside(cq.Vector(*(o_-n_*.01)))} pad={hist.gap_pad(w.document.bodies,pr):.3f}"
            w.ex_value.setValue(5);w.apply_extrude();self.wait()
            solids=[b for b in w.document.bodies if b.kind=='solid']
            parts=sum(len(b.shape.Solids()) for b in solids);gain=sum(b.shape.Volume() for b in solids)-solid.Volume()
            if parts!=1 or gain<math.pi*4*5*.99:problems.append(f'{fi}: części={parts} przyrost {gain:.1f} (oczekiwano co najmniej {math.pi*20:.1f}) {dbg}')
        self.assertFalse(problems,'\n'.join(problems))

    def test_extrude_face_of_solid_joins_and_cuts(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('extrude')
        with patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],[10,10,20])):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_profiles[0]['kind'],'face')
        w.ex_op.setCurrentIndex(1);w.ex_value.setValue(5);w.apply_extrude();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),20*20*25,1)

    def make_solids(self):
        w=self.w
        a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.box(10,10,40)).prepared()
        w.document.commit([a,b]);w.refresh()
        return a,b

    def test_boolean_base_and_tool_selection_with_live_result(self):
        w=self.w;a,b=self.make_solids();w.set_mode('bool')
        for body in (a,b):
            with patch.object(w.view,'pick_body',return_value=body.id):w.view_clicked(5,5,False,False)
        self.assertEqual(w.bool_ids,[a.id,b.id]);self.assertIn(a.id,w.view.tints)
        w.update_bool_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.bool_op.setCurrentIndex(0);w.apply_bool();self.wait()
        self.assertEqual(len([x for x in w.document.bodies if x.kind=='solid']),1)
        self.assertGreater(w.document.bodies[0].shape.Volume(),8000)

    def test_fillet_arrow_and_live_preview(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        with patch.object(w.view,'nearest_edge',return_value=(a.id,0)):w.view_clicked(5,5,False,False)
        self.assertEqual(w.edges,{a.id:{0}});self.assertTrue(w.view.handles)
        w.handle_dragged('mod',2.0);self.assertGreater(w.mod_size.value(),3.0);w.handle_released('mod')
        w.mod_size.setValue(2);w.update_mod_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.apply_mod();self.wait();self.assertLess(w.document.bodies[0].shape.Volume(),8000)

    def test_corner_vertex_is_blended_alone_and_face_double_click_selects_edges(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        pt=np.array(a.mesh.edges[0][0],float)
        cham=k.blend_vertices(a.shape,[pt],3,'chamfer');rnd=k.blend_vertices(a.shape,[pt],3,'fillet')
        self.assertAlmostEqual(8000-cham.Volume(),27/6,3);self.assertTrue(0<8000-rnd.Volume()<27/6)
        self.assertEqual(len(cham.Edges()),len(a.shape.Edges())+3)
        with patch.object(w.view,'nearest_vertex',return_value=(a.id,pt)):w.view_clicked(5,5,False,False)
        self.assertEqual((len(w.mod_vertices[a.id]),w.edges),(1,{}));self.assertTrue(w.view.handles);self.assertEqual(len(w.view.sel_vertices),1)
        w.mod_size.setValue(3);w.update_mod_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.apply_mod();self.wait();self.assertLess(w.document.bodies[0].shape.Volume(),8000);self.assertGreater(w.document.bodies[0].shape.Volume(),7990)
        a=w.document.bodies[0];w.set_mode('mod');far=max((np.array(e[0],float) for e in a.mesh.edges.values()),key=lambda q:float(np.linalg.norm(q-pt)))
        with patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],far.tolist())):w.view_double_clicked(5,5)
        self.assertEqual(w.mod_vertices,{});self.assertGreaterEqual(len(w.edges[a.id]),4);self.assertTrue(w.view.selection_items)

    def test_local_piece_preview_matches_edge_and_pattern_candidate_prefers_sketch(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared()
        piece=k.local_piece(a.shape,{0},None,5.0);self.assertIsNotNone(piece);m=k.map_edges(a.shape,piece,[0]);self.assertIsNotNone(m)
        self.assertLess(k.blend(piece,set(m),2,'chamfer').Volume(),piece.Volume())
        w.document.commit([a]);w.refresh();w.set_mode('pattern')
        with patch.object(w.view,'nearest_edge',return_value=None),patch.object(w.view,'pick_body',return_value=a.id):
            self.assertEqual(w._pattern_candidate(5,5),a.id)
        w.pat_filter.setCurrentIndex(2)
        with patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'nearest_edge',return_value=None),patch.object(w.view,'pick_body',return_value=a.id):
            self.assertIsNone(w._pattern_candidate(5,5))
        w.pat_filter.setCurrentIndex(0);w.pat_id=a.id
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'pick_face',return_value=None),patch.object(w.view,'plane_at',return_value=None),patch.object(w.view,'_ray',return_value=(np.array([0,0,10.]),np.array([0,0,-1.]))):
            self.assertTrue(np.allclose(w._pattern_target(5,5),[0,0,0]))

    def test_history_timeline_fades_used_sketch_and_jumps_between_steps(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));sk=w.document.bodies[0];w.set_mode('extrude');self.pick_sketch_profile(sk)
        w.ex_value.setValue(5);w.apply_extrude();self.wait()
        self.assertFalse(w.document.get(sk.id).visible)               # wykorzystany szkic wygasa
        labels,cur=w.document.timeline();self.assertEqual(cur,len(labels)-1);self.assertEqual(labels[-1],'Wyciągnięcie');self.assertGreaterEqual(len(labels),3)
        w.hist_button.setChecked(True);self.app.processEvents();self.assertTrue(w.hist_bar.isVisible());self.assertGreaterEqual(w.hist_row.count(),len(labels))
        w.hist_ghost.setChecked(True);self.assertTrue(w.view._cache[sk.id][1])
        w.history_goto(cur-1);self.assertTrue(w.document.get(sk.id).visible);self.assertEqual(len([b for b in w.document.bodies if b.kind=='solid']),0)
        w.history_goto(cur);self.assertEqual(len([b for b in w.document.bodies if b.kind=='solid']),1)
        n=len(w._hist_widgets)
        w.undo();self.assertEqual(len(w._hist_widgets),n-1)                      # „Cofnij” usuwa krok także z paska historii
        w.redo();self.assertEqual(len(w._hist_widgets),n)                       # „Ponów” przywraca go
        w.undo();w.undo();self.assertEqual(len(w._hist_widgets),n-2);w.redo();self.assertEqual(len(w._hist_widgets),n-1)
        w.redo();self.assertEqual(len(w._hist_widgets),n)
        chips=list(w._hist_widgets.values());w.history_goto(cur-1);self.assertEqual(list(w._hist_widgets.values()),chips)      # skok w historii nie tworzy widżetów od nowa
        w.history_goto(cur);self.assertEqual(len(w._hist_widgets),len(labels));self.assertTrue(w._hist_widgets[cur][-1].isChecked())
        self.sketch('rect',(40,0),(50,10));self.assertEqual(len(w._hist_widgets),len(labels)+1);self.assertEqual(list(w._hist_widgets.values())[:len(chips)],chips)    # nowy krok dodaje jeden symbol

    def test_history_edit_recomputes_following_steps_and_can_be_reverted(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));sk=w.document.bodies[0];w.set_mode('extrude');self.pick_sketch_profile(sk)
        w.ex_value.setValue(5);w.apply_extrude();self.wait()
        infos,cur=w.document.infos();last=len(infos)-1
        self.assertEqual((infos[last]['icon'],infos[last]['op']['type']),('extrude','extrude'));self.assertEqual(infos[1]['icon'],'sketch')
        vol=lambda:[b for b in w.document.bodies if b.kind=='solid'][0].shape.Volume()
        self.assertAlmostEqual(vol(),1000,2)
        w.history_edit(last);w._hist_fields_extrude['d1'].setValue(8);w._history_edit_apply(last,w._hist_fields);self.wait();self.assertAlmostEqual(vol(),1600,2)
        w.history_edit(1);w._hist_fields['edits'][0].setText('30');w._history_edit_apply(1,w._hist_fields);self.wait()
        self.assertAlmostEqual(vol(),2400,2);self.assertEqual(w.document.timeline()[1],last)       # krok sketch zmieniony, wyciągnięcie przeliczone
        w.history_revert();self.assertAlmostEqual(vol(),1600,2)
        w.hist_button.setChecked(True);self.app.processEvents();self.assertGreaterEqual(w.hist_row.count(),last+1)

    def test_operation_after_history_jump_is_inserted_and_later_steps_recomputed(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));sk=w.document.bodies[0];w.set_mode('extrude');self.pick_sketch_profile(sk)
        w.ex_value.setValue(5);w.apply_extrude();self.wait();before=len(w.document.infos()[0])
        w.history_goto(1);self.assertTrue(w.document.keep_future)
        self.sketch('circle',(40,0),(45,0));self.wait()
        infos,cur=w.document.infos();self.assertEqual((len(infos),cur),(before+1,len(infos)-1))
        kinds=[b.kind for b in w.document.bodies];self.assertEqual(kinds.count('solid'),1);self.assertGreaterEqual(kinds.count('sketch'),2)
        self.assertEqual(infos[-1]['icon'],'extrude');self.assertFalse(w.document.keep_future)

    def test_chamfer(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod');w.mod_kind.setCurrentIndex(1)
        w.edges={a.id:{0}};w.mod_size.setValue(2);w.apply_mod();self.wait();self.assertLess(w.document.bodies[0].shape.Volume(),8000)

    def test_mirror_object_then_face(self):
        w=self.w;a=Body('A',k.hole(k.box(20,20,20),3,5,5)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mirror')
        with patch.object(w.view,'pick_body',return_value=a.id):w.view_clicked(5,5,False,False)
        with patch.object(w.view,'pick_face',return_value=(a.id,[1,0,0],[20,10,10])):w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.mirror_frame);w.update_mirror_preview();self.preview();self.assertTrue(w.view.preview_items)
        w.apply_mirror();self.wait();self.assertEqual(len(w.document.bodies),2)

    def test_move_and_rotate_selected_solid_live(self):
        w=self.w;a,b=self.make_solids();w.selected=[a.id];w.set_mode('move');self.assertIs(w.t_target.id,a.id)
        w.t_spins[0].setValue(7);self.assertIn(a.id,w.view._body_m)
        w.handle_dragged('x',3.0);w.handle_released('x');w.apply_transform();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Center().x,10+10,2)
        w.selected=[a.id];w.set_mode('rotate');w.t_spins[2].setValue(90);self.assertIn(a.id,w.view._body_m)
        w.apply_transform();self.wait()

    def test_move_selected_sketch(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));sk=w.document.bodies[0];w.set_mode(None);w.selected=[sk.id];w.set_mode('move')
        w.t_spins[1].setValue(5);w.apply_transform();self.wait()
        self.assertAlmostEqual(k.bounds(w.document.get(sk.id).shape).ymin,5,3)

    def test_undo_redo_and_escape(self):
        w=self.w;self.sketch('circle',(0,0),(5,0));self.assertTrue(w.undo_button.isEnabled())
        w.undo();self.assertEqual(len(w.document.bodies),0);w.redo();self.assertEqual(len(w.document.bodies),1)
        w.points=[(0,0)];w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));self.assertEqual(w.points,[])

    def test_line_chain_closes_into_extrudable_profile(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        for p in ((0,0),(20,0),(20,10),(0,0)):w.sketch_clicked('XY',*p)
        self.wait();self.assertEqual(len(w.document.bodies),1);self.assertTrue(w.document.bodies[0].shape.IsClosed())

    def test_open_line_finishes_on_double_point(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        for p in ((0,0),(10,0),(10,10),(10,10)):w.sketch_clicked('XY',*p)
        self.wait();self.assertEqual(len(w.document.bodies),1);self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_arc_point_construction_rect3(self):
        self.sketch('arc',(10,0),(0,10),(-10,0));self.sketch('point',(3,3));self.sketch('construction',(0,0),(30,0))
        self.sketch('rect3',(0,0),(10,0),(5,4));self.assertEqual(len(self.w.document.bodies),4)

    def test_measure_does_not_create_geometry(self):
        self.sketch('measure',(0,0),(3,4));self.assertEqual(len(self.w.document.bodies),0);self.assertIn('5,000',self.w.notice.text())

    def test_trim_removes_clicked_segment(self):
        self.sketch('rect',(0,0),(10,10));w=self.w;w.choose_tool('trim');body=w.document.bodies[0]
        pieces=k.trim_pieces([body.shape.Edges()],0)
        with patch.object(w,'_trim_target',return_value=(body,pieces,0)):w.sketch_clicked('XY',0,0)
        self.wait();self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_tangent_circle_between_two_lines(self):
        w=self.w;self.sketch('line',(0,0),(30,0),(30,0));self.sketch('line',(0,0),(0,30),(0,30))
        a,b=w.document.bodies;w.choose_tool('circleTangent2')
        for body in (a,b):
            with patch.object(w,'_cursor_edge',return_value=(body.id,0)):w.sketch_clicked('XY',1,1)
        self.assertEqual(len(w.tangent_lines),2);w.sketch_clicked('XY',10,10);self.wait()
        self.assertEqual(len(w.document.bodies),3)

    def test_text_wizard_surface_area_handles_and_enter(self):
        try:k.text_shape('XY','AB',0,0,10)
        except Exception:self.skipTest('brak czcionki w środowisku')
        self.assertGreaterEqual(len(k.text_shape('XY','O',0,0,10)),2)
        a=k.text_shape('XY','Ab',0,0,10)[0].Center().toTuple();b=k.text_shape('XY','Ab',30,5,10)[0].Center().toTuple()
        self.assertAlmostEqual(b[0]-a[0],30,3);self.assertAlmostEqual(b[1]-a[1],5,3)
        s20=k.text_shape('XY','Ab',0,0,20)[0].Center().toTuple();self.assertAlmostEqual(s20[0],a[0]*2,3)
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('text')
        self.assertEqual(w.txt['stage'],'surface');self.assertTrue(w.view.plane_pick)
        with patch.object(w,'pick_surface',return_value=('XZ',None)):w.view_clicked(5,5,False,False)
        self.assertEqual((w.txt['stage'],w.sketch_plane),('area',"XZ"))
        with patch.object(w.view,'plane_point',side_effect=lambda pl,x,y:(x/10,y/10)),patch.object(w.view,'project_one',side_effect=lambda p:(p[0]*10,p[2]*10) if True else None):
            self.assertTrue(w._sketch_hook('press',0,0));w._sketch_hook('move',300,100);w._sketch_hook('release',300,100)
            self.assertEqual(w.txt['stage'],'edit');self.assertIsNotNone(w.view.sketch_box);size0=w.txt['size'];self.assertGreater(size0,0)
            g=w._text_geometry();bx=w._text_box_world()
            sx,sy=bx['scale'][0]*10,bx['scale'][2]*10
            self.assertTrue(w._sketch_hook('press',sx,sy));w._sketch_hook('move',sx*1.5,sy*1.5);w._sketch_hook('release',sx*1.5,sy*1.5)
            self.assertGreater(w.txt['size'],size0)
            rx,ry=w._text_box_world()['rotate'][0]*10,w._text_box_world()['rotate'][2]*10
            self.assertTrue(w._sketch_hook('press',rx,ry));w._sketch_hook('move',rx-80,ry+80);w._sketch_hook('release',rx-80,ry+80)
            self.assertNotEqual(w.txt['angle'],0.0)
        before=len(w.document.bodies);ev=QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier);w.keyPressEvent(ev);self.wait()
        self.assertGreater(len(w.document.bodies),before);self.assertEqual(w.txt['stage'],'area')
        infos,cur=w.document.infos();self.assertEqual((infos[-1]['icon'],infos[-1]['op']['type']),('text','text'))
        w.history_edit(cur);w._hist_text['text'].setText('Xy');w._hist_text['size'].setValue(7);w._history_edit_apply(cur,w._hist_fields);self.wait()
        self.assertEqual(w.document.infos()[0][-1]['op']['params']['text'],'Xy');self.assertEqual(w.document.infos()[0][-1]['op']['params']['size'],7)

    def test_typed_dimensions_are_live(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect');w.sketch_clicked('XY',0,0)
        self.assertTrue(w.open_dim_input('3'));w.dim_edits[0].setText('30');w.dim_edits[1].setText('10')
        w.update_dim_preview();self.preview();self.assertTrue(w.view.preview_items);w.apply_typed();self.wait()
        b=k.bounds(w.document.bodies[0].shape);self.assertAlmostEqual(b.xlen,30,3);self.assertAlmostEqual(b.ylen,10,3)

    def test_handles_are_drawn_on_top_overlay_and_draggable(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        self.assertTrue(w.view.handles);geo=w.view.handle_geometry(w.view.handles[0]);self.assertIsNotNone(geo)
        grabbed=w.view._grab_handle(*geo['end']);self.assertIsNotNone(grabbed);self.assertEqual(grabbed['id'],'ex')
        w.view.overlay.repaint();self.app.processEvents()

    def test_snap_to_existing_sketch_corner(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.choose_tool('line')
        x,y=w.view.project_one(k.to_world('XY',10,10))
        u,v,label=w._snapper(x+3,y+2,(10.4,10.3));self.assertEqual(label,'Punkt styku');self.assertAlmostEqual(u,10,3);self.assertAlmostEqual(v,10,3)
        u,v,label=w._snapper(x+60,y+60,(14.3,3.9));self.assertEqual(label,None if label is None else 'Siatka')
        w.view.set_marker(k.to_world('XY',10,10),label='Punkt styku');self.assertIsNotNone(w.view.snap_marker)

    def test_overlapping_shapes_make_regions_and_extrude_overlap(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));self.sketch('rect',(5,0),(15,10))
        plane,bodies=w._drawn_sketches()['XY'];faces=w._regions_for('XY',plane,bodies)
        self.assertEqual(len(faces),3);areas=sorted(round(f.Area()) for f in faces);self.assertEqual(areas,[50,50,50])
        self.assertTrue(any(k.face_contains(f,k.to_world('XY',7.5,5)) for f in faces))
        mid=[f for f in faces if k.face_contains(f,k.to_world('XY',7.5,5))][0]
        w.set_mode('extrude');src=dict(kind='region',id=None,face=mid,wire=mid.outerWire(),plane='XY',normal=(0,0,1),center=mid.Center().toTuple())
        with patch.object(w,'_profile_at',return_value=src):w.view_clicked(5,5,False,False)
        w.ex_value.setValue(4);w.apply_extrude();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0];self.assertAlmostEqual(solid.shape.Volume(),50*4,2)

    def test_trim_splits_at_intersection(self):
        w=self.w;self.sketch('line',(0,0),(20,0),(20,0));self.sketch('line',(10,-5),(10,5),(10,5))
        a,b=w.document.bodies;pieces=k.trim_pieces([a.shape.Edges(),b.shape.Edges()],0);self.assertEqual(len(pieces),2)
        w.choose_tool('trim')
        with patch.object(w,'_trim_target',return_value=(a,pieces,0)):w.sketch_clicked('XY',0,0)
        self.wait();self.assertEqual(len(w.document.bodies),2)
        self.assertAlmostEqual(k.bounds(w.document.bodies[0].shape).xlen,10,3)

    def test_help_dialog_selection_glow_and_mirror_steps(self):
        from rccad.help import HelpDialog,TOPICS
        d=HelpDialog(self.w);self.assertEqual(d.list.count(),len(TOPICS));d.list.setCurrentRow(2);self.assertTrue(d.body.text());d.close()
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        self.assertTrue(w.view.selection_items)
        w.set_mode('mirror');self.assertEqual(w.mir_step1.value.text(),'Kliknij bryłę lub szkic')
        w.view.stretch_preview((0,0,0),(0,0,1),1.5)


    def test_cube_arrows_auto_cut_xray_pick_and_splash(self):
        w=self.w;w.view.setCameraPosition(azimuth=-90,elevation=0);w._cube_rotate(90,0);self.assertAlmostEqual(w.view.opts['azimuth'],0,3)
        w._cube_rotate(0,90);self.assertAlmostEqual(w.view.opts['elevation'],90,3)
        hit=w.cube._hit(w.cube._arrow_center('left'));self.assertEqual(hit,('arrow','left'))
        self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_value.setValue(10);w.apply_extrude();self.wait()
        solid=[b for b in w.document.bodies if b.kind=='solid'][0]
        self.assertEqual(k.point_state(solid.shape,(5,5,5)),'in')
        from rccad.splash import Splash
        sp=Splash('');sp.show();sp.repaint();sp.close()

    def test_idle_planes_axes_close_prompt_and_reverse_arrow(self):
        w=self.w;w.set_mode(None);w.view.set_view('iso');self.app.processEvents()
        xy=w.view.project_one((.5,.5,0));name=w.view.plane_at(*xy);self.assertIn(name,('XY','XZ','YZ'))
        w.view_clicked(xy[0],xy[1],False,False);self.assertEqual((w.mode,w.sketch_plane),('sketch',name))
        w.set_mode(None);w.view.set_view('Z');w.view.update();self.assertFalse(w.view.axis_lines[2][0].visible())
        w.view.set_view('iso');w.view.update();self.assertTrue(w.view.axis_lines[2][0].visible())
        self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        w.ex_value.setValue(-5);w._place_extrude_handle();h=w.view.handles[0];self.assertAlmostEqual(float(np.dot(h['dir'],h['tip']-h['start'])),-5,3)
        self.assertTrue(w.document.dirty)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Cancel):
            from PySide6.QtGui import QCloseEvent
            ev=QCloseEvent();w.closeEvent(ev);self.assertFalse(ev.isAccepted())

    def test_defaults_and_auto_new_body(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');self.pick_sketch_profile(w.document.bodies[0])
        self.assertEqual(w.ex_value.value(),10);self.assertEqual(w.ex_op.currentData(),'new')
        w.set_mode('mod');self.assertEqual(w.mod_size.value(),2)

    def test_tab_numeric_edit_polygon_sides_and_clear_all(self):
        w=self.w
        self.sketch('rect',(0,0),(20,10))
        sk=w.document.bodies[-1];self.assertEqual(sk.meta['tool'],'rect')
        w.set_mode(None);w.selected=[sk.id];self.assertTrue(w.open_dim_edit())
        self.assertEqual([e.text() for e in w.dim_edits if e.isVisible()],['20.0','10.0'])
        w.dim_edits[0].setText('30');w.dim_edits[1].setText('5');w.apply_dim_edit();self.wait()
        b=k.bounds(w.document.bodies[-1].shape);self.assertAlmostEqual(b.xlen,30,3);self.assertAlmostEqual(b.ylen,5,3)
        w.set_mode('plane');w.plane_picked('XY');w.choose_tool('polygon');w.sketch_clicked('XY',0,0)
        self.assertTrue(w.open_dim_input());self.assertEqual(len([e for e in w.dim_edits if e.isVisible()]),2)
        w.dim_edits[0].setText('10');w.dim_edits[1].setText('6');w.apply_typed();self.wait()
        self.assertEqual(w.document.bodies[-1].meta['sides'],6);self.assertEqual(len(w.document.bodies[-1].shape.Edges()),6)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):w.clear_all()
        self.assertEqual(len(w.document.bodies),0)
        labels,cur=w.document.timeline();self.assertEqual((len(labels),cur),(1,0))       # czyszczenie usuwa też historię
        self.assertFalse(w.document.can_undo or w.document.can_redo or w.document.constraints or w.document.snapshots)
        w.undo();w.redo();self.assertEqual(len(w.document.bodies),0)
        self.sketch('rect',(0,0),(5,5));self.assertEqual(len(w.document.timeline()[0]),2)       # po wyczyszczeniu historia zaczyna się od nowa

    def test_shape_icons_and_menu_card(self):
        from rccad import shell_ui as ui
        for item in ui.load_shapes():
            if not item['variant']:self.assertFalse(ui.style_icon('s_'+item['shape'],28).isNull(),item['shape'])
        m=ui.RichMenu(self.w,[(ui.icons.pixmap('f_new',34),'A','b',lambda:None)],'T',300);self.assertEqual(m.card.objectName(),'rich');m.close()

    def test_tool_toggle_select_and_drag_resize(self):
        w=self.w;self.sketch('rect',(0,0),(20,10))
        w._tool_clicked('rect');self.assertIsNone(w.tool);self.assertFalse(any(b.isChecked() for b in w.shape_buttons.values()))
        w.view.update();a=w.view.project_one((20,5,0));self.assertTrue(w.view.drag_hook('press',*a))
        self.assertEqual(w.selected,[w.document.bodies[-1].id]);self.assertEqual(len(w.view.sketch_grips),8)
        w.view.drag_hook('move',*w.view.project_one((30,5,0)));w.view.drag_hook('release',*w.view.project_one((30,5,0)));self.wait()
        b=k.bounds(w.document.bodies[-1].shape);self.assertAlmostEqual(b.xlen,30,1);self.assertAlmostEqual(b.ylen,10,1)
        w._tool_clicked('circle');self.assertEqual(w.tool,'circle');self.assertEqual(w.selected,[])
        w._tool_clicked('circle');self.assertIsNone(w.tool)

    def test_arc_is_editable_after_drawing(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY')
        w.choose_tool('arc');w.sketch_clicked('XY',0,20);w.sketch_clicked('XY',5,23);w.sketch_clicked('XY',10,20);self.wait()
        arc=w.document.bodies[-1];self.assertEqual(arc.meta['tool'],'arc');w.choose_tool(None);w.selected=[arc.id];self.assertTrue(w.open_dim_edit())
        self.assertEqual([e.text() for e in w.dim_edits if e.isVisible()],['10.0','3.0']);w.dim_panel.hide()

    def test_cube_face_preselects_sketch_plane_and_grid_button(self):
        w=self.w;w.set_mode(None);w._cube_clicked('X');self.assertIsNone(w.mode)
        w.toggle_mode('sketch');self.assertEqual((w.mode,w.sketch_plane),('sketch','YZ'))
        w.set_mode(None);w.view.set_view('iso');w.toggle_mode('sketch');self.assertEqual(w.mode,'plane')
        w.set_mode(None);self.assertTrue(w.grid_button.isChecked())
        w.grid_button.setChecked(False);self.assertFalse(any(g.visible() for g in w.view.grid_items))
        w.grid_button.setChecked(True);self.assertTrue(all(g.visible() for g in w.view.grid_items))

    def test_cube_button_picks_sketch_plane_and_grid_adapts(self):
        w=self.w;w.set_mode('plane');w._cube_clicked('X');self.assertEqual((w.mode,w.sketch_plane),('sketch','YZ'))
        w.view.opts['distance']=400;w.view.update();far=w.view._grid_key[0]
        w.view.opts['distance']=15;w.view.update();near=w.view._grid_key[0];self.assertLess(near,far)

    def test_transform_preview_is_instant_matrix(self):
        w=self.w;a,b=self.make_solids();w.selected=[a.id];w.set_mode('rotate');w.t_spins[0].setValue(30)
        self.assertIsNotNone(w.view._body_m.get(a.id));w.set_mode(None);self.assertNotIn(a.id,w.view._body_m)

    def test_trimmed_union_outline_is_one_extrudable_region(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));self.sketch('rect',(5,0),(15,10));w.choose_tool('trim')
        for which,(x,y) in ((0,(10,5)),(-1,(5,5))):
            n=len(w.document.bodies);bi=which if which>=0 else n-1;body=w.document.bodies[bi]
            pieces=k.trim_pieces([b.shape.Edges() for b in w.document.bodies],bi)
            idx=min(range(len(pieces)),key=lambda i:(pieces[i].Center().x-x)**2+(pieces[i].Center().y-y)**2)
            with patch.object(w,'_trim_target',return_value=(body,pieces,idx)):w.sketch_clicked('XY',0,0)
            self.wait()
        plane,bodies=w._drawn_sketches()['XY'];faces=w._regions_for('XY',plane,bodies)
        self.assertTrue(any(abs(f.Area()-150)<1e-3 for f in faces),[round(f.Area(),2) for f in faces])
        big=[f for f in faces if abs(f.Area()-150)<1e-3][0]
        w.set_mode('extrude');src=dict(kind='region',id=None,face=big,wire=big.outerWire(),plane='XY',normal=(0,0,1),center=big.Center().toTuple())
        with patch.object(w,'_profile_at',return_value=src):w.view_clicked(5,5,False,False)
        w.ex_value.setValue(3);w.apply_extrude();self.wait()
        self.assertAlmostEqual([b for b in w.document.bodies if b.kind=='solid'][0].shape.Volume(),450,2)

    def test_escape_and_right_click_keep_line_and_leave_drawing(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('line')
        for p in ((0,0),(10,0),(10,10)):w.sketch_clicked('XY',*p)
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));self.wait()
        self.assertEqual(len(w.document.bodies),1);self.assertEqual(w.points,[]);self.assertEqual(w.mode,'sketch')
        for p in ((20,0),(30,0)):w.sketch_clicked('XY',*p)
        w.context_menu(5,5);self.wait();self.assertEqual(len(w.document.bodies),2)
        w.sketch_clicked('XY',40,0);w.context_menu(5,5);self.assertEqual(len(w.document.bodies),2)

    def test_hover_cursor_only_after_first_click(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect');self.assertFalse(w.sketch_hover_wanted())
        w.sketch_clicked('XY',0,0);self.assertTrue(w.sketch_hover_wanted())

    def test_svg_import(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'a.svg');open(f,'w').write('<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="20" height="10"/><circle cx="5" cy="5" r="2"/><path d="M0 0 L10 0 L10 10 Z"/></svg>')
            self.assertEqual(len(k.svg_profiles(f)),3)

    def test_file_menu_and_context_menu_open(self):
        from rccad import shell_ui as ui
        seen=[]
        with patch.object(ui.PopupMenu,'popup_at',lambda menu,pos:seen.append(('ctx',len(menu.actions)))),\
             patch.object(ui.RichMenu,'popup_at',lambda menu,pos:seen.append(('rich',len(menu.actions)))):
            self.w.file_menu()
            a,b=self.make_solids()
            with patch.object(self.w.view,'pick_body',return_value=a.id):self.w.context_menu(5,5)
            self.w.tools['sketch'].click();self.w.plane_picked('XY')
            for b in self.w.shape_bar.findChildren(__import__('PySide6.QtWidgets',fromlist=['QToolButton']).QToolButton):
                if b.objectName()=='shapeExpand':b.click()
        self.assertEqual(seen[:2],[('rich',8),('ctx',4)]);self.assertEqual([n for kind,n in seen[2:]],[3,4])

    def test_every_button_click_raises_no_exception(self):
        import sys
        from PySide6.QtWidgets import QToolButton
        from rccad import shell_ui as ui
        errors=[];old=sys.excepthook;sys.excepthook=lambda *a:errors.append(a[1])
        try:
            with patch.object(ui.PopupMenu,'popup_at',lambda *a:None),patch.object(ui.RichMenu,'popup_at',lambda *a:None):
                for key in ('file','sketch','extrude','bool','mod','mirror','mod','bool'):self.w.tools[key].click();self.app.processEvents()
                self.w.tools['sketch'].click();self.w.plane_picked('XY')
                for b in list(self.w.shape_buttons.values()):b.click();self.app.processEvents()
                for b in self.w.shape_bar.findChildren(QToolButton):
                    if b.objectName()=='shapeExpand':b.click();self.app.processEvents()
                self.w.set_mode(None)
                for b in self.w.cube.findChildren(QToolButton):b.click()
                for b in (*self.w.pad_buttons.values(),self.w.layers,self.w.xray,self.w.home,self.w.undo_button,self.w.redo_button):b.click();self.app.processEvents()
        finally:sys.excepthook=old
        self.assertEqual(errors,[])


if __name__=='__main__':
    unittest.main()
