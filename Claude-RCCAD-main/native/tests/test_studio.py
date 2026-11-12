"""Okno Studio: układ jak w HTML oraz przepływ szkic → wyciągnięcie → Boolean / zaokrąglenie / lustro."""
import os, faulthandler
DIAG=open(os.environ.get("DIAG_FILE","diag_hang.txt"),"w")
# strażnik zawieszenia: włączany w setUp każdego testu okna i wyłączany w tearDown (nie liczy czasu innych modułów)
os.environ.setdefault('QT_QPA_PLATFORM','offscreen' if not os.environ.get('DISPLAY') and os.name!='nt' else '')
import time, math
import tempfile
os.environ['RCCAD_CONFIG_DIR']=tempfile.mkdtemp(prefix='rccad-cfg-')
os.environ.setdefault('RCCAD_WORKERS','0')        # testy okna liczą w jednym procesie (procesy liczące mają własne testy: test_workers)     # zapamiętane ustawienia (Kołnierz → Zatwierdź) nie trafiają do prawdziwego profilu
from pathlib import Path
import numpy as np
import cadquery as cq
from rccad import sketchmeta as sm
import unittest
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtCore import QEvent,Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication,QMessageBox,QCheckBox,QLabel,QToolButton,QSpinBox
from rccad import kernel as k
from rccad import history as hist
from rccad import sheetmetal as shm
from rccad.document import Body, Document
from rccad.studio import TABS
from rccad.studio import StudioWindow


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        faulthandler.dump_traceback_later(600, exit=True, file=DIAG)      # 10 minut na jeden test, nie na cały zestaw
        self.w=StudioWindow();self.w.resize(1400,850);self.w.show();self.app.processEvents()
        self.patches=[patch.object(QMessageBox,'warning',return_value=QMessageBox.Ok),patch.object(QMessageBox,'information',return_value=QMessageBox.Ok)]
        for p in self.patches:p.start()

    def tearDown(self):
        self.wait();self.w.document._saved_revision=self.w.document._revision;self.w.close();self.w.deleteLater();self.app.sendPostedEvents(None,QEvent.DeferredDelete);self.app.processEvents();self.w=None   # okno zwalniane od razu (inaczej pamięć rośnie z każdym testem)
        for p in self.patches:p.stop()
        faulthandler.cancel_dump_traceback_later()

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

    def test_surface_sketch_toolbar_create_and_join(self):
        w = self.w
        solid = Body('Walec', cq.Workplane().cylinder(20, 10).val(), 'solid').prepared()
        w.document.commit([solid])
        w.refresh()
        w.begin_surface_sketch(corner=True)
        self.assertTrue(w.wrap_corner)
        w.begin_surface_sketch()
        self.assertTrue(w.wrap_sketch)
        self.assertFalse(w.wrap_corner)
        normal = (1, 0, 0)
        origin = (10, 0, 0)
        w.surface_target = {'target': solid.id, 'normal': list(normal)}
        plane = k.face_frame(origin, normal)
        w.enter_sketch(plane)
        wire = cq.Workplane(cq.Plane(origin=origin, normal=normal)).circle(3).val()
        w.create_sketch([wire])
        self.wait()
        sketch = next(b for b in w.document.bodies if b.kind == 'sketch')
        self.assertEqual(sketch.meta['surface']['target'], solid.id)
        w.set_mode('extrude')
        w._accept_profile(w._sketch_profile(sketch))
        w.ex_value.setValue(.5)
        self.preview()
        w.apply_extrude()
        self.wait()
        self.assertGreater(next(b.shape for b in w.document.bodies if b.kind == 'solid').Volume(), solid.shape.Volume())

    def test_projected_surface_sketch_is_picked_on_visible_outline(self):
        w = self.w
        solid = Body('Cylinder', cq.Workplane().cylinder(20, 10).val(), 'solid').prepared()
        origin, normal = (10, 0, 0), (1, 0, 0)
        frame = k.face_frame(origin, normal)
        wire = cq.Workplane(cq.Plane(origin=origin, normal=normal)).circle(4).val()
        sketch = Body('Surface sketch', wire, 'sketch', frame,
                      meta={'surface': {'target': solid.id, 'normal': list(normal)}}).prepared()
        sketch = replace(sketch, mesh=k.project_surface_mesh(sketch.mesh, solid.shape, normal))
        w.document.commit([solid, sketch]);w.refresh()
        w.view.look_along(frame);self.app.processEvents()
        xy = w.view.project_one(sketch.mesh.center)
        self.assertIsNotNone(xy)
        self.assertEqual(w.view.pick_profile(*xy[:2]), sketch.id)
        w.set_mode('extrude')
        self.assertEqual(w._profile_at(*xy[:2])['kind'], 'surface')

    def test_corner_sketch_hover_highlight_and_exact_extrude(self):
        w = self.w
        box = Body('Box', k.box(30, 30, 20), 'solid').prepared()
        w.document.commit([box]); w.refresh()
        w.begin_surface_sketch(corner=True)
        edge = min((i for i, e in enumerate(box.shape.Edges()) if abs(e.tangentAt(.5).z) > .99),
                   key=lambda i: np.linalg.norm(np.array(box.shape.Edges()[i].positionAt(.5).toTuple()) - (30, 30, 10)))
        with patch.object(w.view, 'nearest_edge', return_value=(box.id, edge)), patch.object(w.view, 'pick_face', return_value=None):
            frame, _ = w.pick_surface(100, 100, True)
        self.assertIsNotNone(frame)
        w.enter_sketch(frame)
        f = k.frame_of(frame)
        plane = cq.Plane(origin=f.origin, xDir=f.xdir, normal=f.normal)
        w.create_sketch([cq.Workplane(plane).rect(8, 5).val(), cq.Workplane(plane).center(0, 7).circle(1.5).val()])
        self.wait()
        sketches = [b for b in w.document.bodies if b.kind == 'sketch']
        self.assertEqual(len(sketches), 2)
        # szkic leży na bryle (tuż nad nią), a nie na płaszczyźnie stycznej
        points = np.concatenate(list(sketches[0].mesh.edges.values()))
        self.assertLess(max(box.shape.distance(cq.Vertex.makeVertex(*map(float, p))) for p in points[::7]), .05)
        w.set_mode('extrude')
        first = w._sketch_profile(sketches[0])
        with patch.object(w, '_profile_at', return_value=first):
            w.view_hover(100, 100)
        self.assertTrue(w.view.preview_items)                     # podświetlenie przed kliknięciem (wypełnione)
        w._accept_profile(first)
        self.assertEqual(len(w.ex_profiles), 1)
        with patch.object(w, '_profile_at', return_value=w._sketch_profile(sketches[1])):
            w.view_hover(100, 100)
        self.assertTrue(w.view.hover_items)                       # także po wybraniu pierwszego profilu
        with patch.object(w, '_profile_at', return_value=None):
            w.view_hover(100, 100)
        self.assertFalse(w.view.hover_items)
        w.ex_value.setValue(.8)
        self.preview()
        w.apply_extrude()
        self.wait()
        solid = next(b for b in w.document.bodies if b.kind == 'solid')
        self.assertTrue(solid.shape.isValid())
        self.assertAlmostEqual(solid.shape.Volume() - box.shape.Volume(), 8 * 5 * .8 + .8 * .8 * 5, 2)

    def test_surface_tool_buttons_are_distinct_and_next_to_new_sketch(self):
        w=self.w;w.set_tab('Szkic');w._layout_overlays()
        keys=('sketch','wrapsketch','wrapcorner','matchsize','surface')
        self.assertEqual([b for b in keys],[b for b in w._tab_tools('Szkic')])
        self.assertEqual(len({w.tools[key].icon().cacheKey() for key in keys}),5)
        self.assertEqual([w.tools[key].x() for key in keys],sorted(w.tools[key].x() for key in keys))

    def test_surface_hover_shows_point_and_corner_hover_shows_edge(self):
        w=self.w
        cylinder=Body('Cylinder',cq.Workplane().cylinder(20,10).val(),'solid').prepared()
        w.document.commit([cylinder]);w.refresh();w.begin_surface_sketch()
        face=next(f for f in cylinder.shape.Faces() if f.geomType()=='CYLINDER')
        point=np.array([10.,0.,0.])
        with patch.object(w.view,'pick_face',return_value=(cylinder.id,np.array([1.,0.,0.]),point)), \
             patch.object(w.view,'face_at',return_value=(face,(1.,0.,0.))):
            w.view_hover(100,100)
        self.assertTrue(np.allclose(w.view.hover_vertex,point))
        box=Body('Box',k.box(20,20,20),'solid').prepared()
        w.document.commit([box]);w.refresh();w.begin_surface_sketch(corner=True)
        with patch.object(w.view,'nearest_edge',return_value=(box.id,0)), \
             patch.object(w.view,'pick_face',return_value=None):
            w.view_hover(100,100)
            frame,_=w.pick_surface(100,100,True)
        self.assertIsNotNone(frame)
        self.assertTrue(np.allclose(w.view.hover_vertex,k.edge_handle(box.shape,0)[0]))

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

    # 0.4.62: oko, kłódka, kosz i grupy na zaznaczonej pozycji działają na wszystkie zaznaczone
    def test_objects_row_actions_apply_to_all_selected(self):
        w=self.w
        bodies=[Body(f'B{i}',k.box(5,5,5),'solid').prepared() for i in range(4)]
        w.document.commit(bodies);w.refresh();self.app.processEvents()
        a,b,c,d=[x.id for x in bodies]
        w.objects_select(a,Qt.NoModifier);w.objects_select(b,Qt.ShiftModifier);w.objects_select(c,Qt.ShiftModifier)
        w.objects_hide(b);self.assertTrue({a,b,c}<=w.hidden_ids);self.assertNotIn(d,w.hidden_ids)      # jedno kliknięcie - wszystkie zaznaczone
        w.objects_hide(a);self.assertNotIn(a,w.hidden_ids);self.assertIn(b,w.hidden_ids)               # niezaznaczona pozycja - tylko ona
        w.objects_hide(b);w.objects_hide(c)
        w.objects_select(a,Qt.NoModifier);w.objects_select(d,Qt.ShiftModifier)
        w.objects_lock(d);self.assertTrue({a,d}<=w.locked_ids);self.assertNotIn(b,w.locked_ids)
        w.objects_select(a,Qt.NoModifier);w.objects_select(d,Qt.ShiftModifier)
        w.objects_lock(d);self.assertFalse({a,d}&w.locked_ids)
        w.objects_select(a,Qt.NoModifier);w.objects_select(d,Qt.ShiftModifier)
        w.objects_folder_new([a]);self.assertEqual(w.document.get(a).folder,w.document.get(d).folder);self.assertTrue(w.document.get(a).folder)
        w.objects_select(a,Qt.NoModifier);w.objects_select(d,Qt.ShiftModifier)
        w.objects_folder_move([d],'');self.assertEqual((w.document.get(a).folder,w.document.get(d).folder),('',''))   # wyjęcie z grupy - obie
        w.objects_select(b,Qt.NoModifier);w.objects_select(c,Qt.ShiftModifier)
        w.objects_delete(c);self.wait();self.assertEqual({x.id for x in w.document.bodies},{a,d})
        w.objects_delete(a);self.wait();self.assertEqual({x.id for x in w.document.bodies},{d})       # niezaznaczona - tylko ona

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
        with patch.object(w,'_profile_at',return_value=out):w.pick_profile(5,5,True)          # Shift odznacza literę
        self.assertEqual(len(w.ex_profiles),n-1)
        with patch.object(w,'_profile_at',return_value=out):w.pick_profile(5,5,False)         # kliknięcie dodaje z powrotem
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

    def test_flange_panel_icons_defaults_save_bend_toggle_and_reset(self):
        import json
        w=self.w;w.toggle_mode('flange');self.assertTrue(w.flange_panel.isVisible())
        texts=[l.text() for l in w.flange_panel.findChildren(QLabel)]
        self.assertFalse(any(t.startswith('Krawędź górnej ściany wychodzi') or t.startswith('Zewnętrzna: długość') for t in texts))
        self.assertFalse(hasattr(w,'fl_step1'))
        self.assertEqual((w.fl_radius.value(),w.fl_angle.value(),w.fl_length.value(),w.fl_datum.currentData()),(.5,90,5,'outer'))
        for pic in (w.fl_radius_pic,w.fl_angle_pic,w.fl_length_pic):self.assertFalse(pic.pixmap().isNull())
        self.assertEqual([b.text() for b in (w.fl_save,w.fl_bend,w.fl_reset)],['Zatwierdź','Zaginaj','Reset'])
        self.assertFalse(w.fl_armed);self.assertIn('#2fa56d',w.fl_bend.styleSheet())           # zielony: wyginanie wyłączone
        body=self.converted_sheet();w.set_mode('flange');self.assertFalse(w.fl_armed)
        edge=next(i for i,e in enumerate(w.document.get(body.id).shape.Edges()) if abs(e.positionAt(.5).x-100)<1e-6 and abs(e.positionAt(.5).z-2)<1e-6)
        with patch.object(w.view,'nearest_edge',return_value=(body.id,edge,None)):w.view_clicked(5,5,False,False)
        self.wait();self.assertEqual(len(w._sheet_state(body.id)['specs']),0);self.assertIn('Zaginaj',w.fl_status.text())
        w.fl_bend.click();self.assertTrue(w.fl_armed);self.assertIn('#e5484d',w.fl_bend.styleSheet())   # czerwony: kliknięcie krawędzi wygina
        with patch.object(w.view,'nearest_edge',return_value=(body.id,edge,None)):w.view_clicked(5,5,False,False)
        self.wait();self.assertEqual(len(w._sheet_state(body.id)['specs']),1,w.fl_status.text());self.assertEqual(w._sheet_state(body.id)['specs'][0]['length'],20)
        w.fl_bend.click();self.assertFalse(w.fl_armed);self.assertIn('#2fa56d',w.fl_bend.styleSheet())
        w.fl_radius.setValue(1.5);w.fl_angle.setValue(60);w.fl_length.setValue(12);w.fl_datum.setCurrentIndex(1);w.fl_save.click()
        saved=json.loads(w._settings_file().read_text(encoding='utf-8'))
        self.assertEqual(saved,dict(radius=1.5,angle=60.0,length=12.0,measure='inner'));self.assertIn('Zapamiętano',w.fl_status.text())
        w.fl_reset.click();self.assertEqual((w.fl_radius.value(),w.fl_angle.value(),w.fl_length.value(),w.fl_datum.currentData()),(.5,90,5,'outer'))
        w._load_flange_settings();self.assertEqual((w.fl_radius.value(),w.fl_angle.value(),w.fl_length.value(),w.fl_datum.currentData()),(1.5,60,12,'inner'))
        w.fl_reset.click();w.fl_save.click()
        w.toggle_mode('rules');w.rl_ok.click();self.assertEqual(w.mode,'flange');self.assertTrue(w.fl_armed)    # Reguły → Zastosuj włącza wyginanie

    def test_moved_and_rotated_sheet_still_unfolds_folds_and_takes_flanges(self):
        w=self.w;body=self.converted_sheet();w.apply_flange();self.wait()
        volume=w.document.get(body.id).shape.Volume()
        for mode,vals in (('move',(10,5,0)),('rotate',(0,0,30)),('move',(-3,0,7))):
            w.selected=[body.id];w.set_mode(mode);w.select_transform_target(w.document.get(body.id))
            for spin,v in zip(w.t_spins,vals):spin.setValue(v)
            w.apply_transform();self.wait()
            self.assertFalse(w.document.get(body.id).meta['sheet']['dirty'])      # ruch to nie edycja blachy
        moved=w.document.get(body.id).shape;box=moved.BoundingBox()
        state=w._sheet_state(body.id);self.assertAlmostEqual(state['base']['o'][2],7,6)    # przepis przeniesiony razem z bryłą
        again=hist.run_transform([replace(w.document.states()[-2][0][0])],dict(id=body.id,mode='move',v=[-3,0,7]))[0]
        self.assertEqual(again.meta['sheet']['recipe'],w.document.get(body.id).meta['sheet']['recipe'])   # odtworzenie z historii daje to samo
        toasts=[]
        with patch.object(w,'toast',side_effect=lambda m,*a:toasts.append(m)):
            w.set_mode(None);w.selected=[body.id];w.tools['unfold_sheet'].click();self.wait()
            self.assertTrue(w._sheet_state(body.id)['flat'])
            w.selected=[body.id];w.tools['fold_sheet'].click();self.wait()
        self.assertEqual(toasts,[]);self.assertFalse(w._sheet_state(body.id)['flat'])
        folded=w.document.get(body.id).shape;fb=folded.BoundingBox()
        self.assertAlmostEqual(folded.Volume(),volume,4)
        for a,b in ((box.xmin,fb.xmin),(box.ymin,fb.ymin),(box.zmin,fb.zmin),(box.xmax,fb.xmax),(box.ymax,fb.ymax),(box.zmax,fb.zmax)):self.assertAlmostEqual(a,b,4)
        # kolejny kołnierz na przesuniętej i obróconej blasze
        st=w._sheet_state(body.id);base=st['base'];o=np.array(base['o']);x=np.array(base['x']);y=np.array(base['y']);z=np.array(base['z'])
        far=o+x*base['lx']/2+z*base['lz']           # środek górnej krawędzi płyty po stronie o
        edge=min(range(len(folded.Edges())),key=lambda i:np.linalg.norm(np.array(folded.Edges()[i].positionAt(.5).toTuple())-far))
        w.set_mode('flange');w.fl_bend.click()
        with patch.object(w.view,'nearest_edge',return_value=(body.id,edge,None)):w.view_clicked(5,5,False,False)
        self.wait();self.assertEqual(len(w._sheet_state(body.id)['specs']),2,w.fl_status.text())
        self.assertGreater(w.document.get(body.id).shape.Volume(),volume)

    def test_mated_sheet_still_unfolds(self):
        w=self.w;body=self.converted_sheet();w.apply_flange();self.wait()
        block=Body('Kostka',k.box(10,10,10).translate((0,0,-40)),'solid').prepared();w.document.commit([*w.document.bodies,block]);w.refresh()
        sheet=w.document.get(body.id)
        face=next(f for f in sheet.shape.Faces() if f.geomType()=='PLANE' and abs(f.Center().z)<1e-6)
        tface=next(f for f in block.shape.Faces() if abs(f.Center().z+30)<1e-6)
        recipe=dict(type='mate',mode='align',id=body.id,target=block.id,face=hist.face_ref(face,(0,0,-1),face.Center().toTuple(),sheet.shape),
                    tface=hist.face_ref(tface,(0,0,1),tface.Center().toTuple(),block.shape),spin=0.0)
        w.document.commit(hist.run_recipe(w.document.bodies,recipe),label='Wyrównanie',op=recipe)
        self.assertFalse(w.document.get(body.id).meta['sheet']['dirty'])
        w.set_mode(None);w.selected=[body.id];w.tools['unfold_sheet'].click();self.wait()
        self.assertTrue(w._sheet_state(body.id)['flat'])

    def test_unfold_and_fold_without_selection_ask_to_pick_sheet(self):
        w=self.w;body=self.converted_sheet();w.apply_flange();self.wait()
        other=Body('Kostka',k.box(5,5,5)).prepared();w.document.commit([*w.document.bodies,other]);w.refresh()
        w.set_mode(None);w.selected=[];w.tools['unfold_sheet'].click()
        self.assertEqual((w.mode,w._sheet_cmd),('sheetpick','unfold_sheet'));self.assertTrue(w.tools['unfold_sheet'].isChecked())
        with patch.object(w.view,'pick_body',return_value=other.id):w.view_clicked(5,5,False,False)
        self.assertEqual(w.mode,'sheetpick')                       # zwykła bryła: dalej czeka na blachę
        with patch.object(w.view,'pick_body',return_value=body.id):w.view_clicked(5,5,False,False)
        self.wait();self.assertTrue(w._sheet_state(body.id)['flat']);self.assertFalse(w.tools['unfold_sheet'].isChecked())
        w.selected=[];w.tools['fold_sheet'].click();self.assertEqual(w.mode,'sheetpick')
        w.tools['fold_sheet'].click();self.assertIsNone(w.mode)   # ponowne kliknięcie anuluje
        w.selected=[body.id];w.tools['fold_sheet'].click();self.wait()   # zaznaczona blacha: od razu
        self.assertFalse(w._sheet_state(body.id)['flat'])

    def test_hem_and_sheet_panels_icons_buttons_and_settings(self):
        import json
        w=self.w;w.toggle_mode('hem')
        texts=[l.text() for l in w.hem_panel.findChildren(QLabel)]
        self.assertFalse(any(t.startswith('Krawędź zawija się od razu') for t in texts))
        for pic in (w.hm_radius_pic,w.hm_length_pic,w.hm_gap_pic):self.assertFalse(pic.pixmap().isNull())
        self.assertEqual([b.text() for b in (w.hm_save,w.hm_bend,w.hm_reset,w.hm_close)],['Zatwierdź','Zaginaj','Reset','Zamknij'])
        self.assertIn('#2fa56d',w.hm_bend.styleSheet());w.hm_bend.click();self.assertTrue(w.fl_armed);self.assertIn('#e5484d',w.hm_bend.styleSheet())
        w.hm_radius.setValue(1);w.hm_length.setValue(7);w.hm_gap.setValue(.3);w.hm_save.click()
        self.assertEqual(json.loads(w._settings_file('hem').read_text(encoding='utf-8')),dict(radius=1.0,length=7.0,gap=.3))
        w.hm_reset.click();self.assertEqual((w.hm_radius.value(),w.hm_length.value(),w.hm_gap.value()),(2,10,.1))
        w._load_hem_settings();self.assertEqual(w.hm_length.value(),7);w.hm_reset.click();w.hm_save.click()
        w.hm_close.click();self.assertIsNone(w.mode)
        w.toggle_mode('flange');self.assertEqual(w.fl_close.text(),'Zamknij');w.fl_close.click();self.assertIsNone(w.mode)
        w.toggle_mode('sheet');texts=[l.text() for l in w.sheet_panel.findChildren(QLabel)]
        self.assertFalse(any(t.startswith('Zamienia prostopadłościan') for t in texts));self.assertFalse(hasattr(w,'sheet_step1'))
        body=Body('Płyta',k.box(100,50,2),'solid').prepared();w.document.commit([body]);w.refresh()
        with patch.object(w.view,'pick_face',return_value=(body.id,(0,0,1),(50,25,2))):w.view_clicked(5,5,False,False)
        self.assertEqual((w.sheet_t.text(),w.sheet_dims.text()),('2 mm','100 × 50 mm'))

    def test_flange_click_shows_instant_preview_then_exact_result(self):
        w=self.w;body=self.converted_sheet();w.set_mode('flange')
        w.fl_pick=dict(id=body.id,spec=dict(kind='base',p0=[100,0,2],p1=[100,50,2],n=[0,0,1],m=[1,0,0]))
        w.apply_flange()
        self.assertTrue(w.busy);self.assertTrue(w.view.preview_items)                 # podgląd od razu, wynik jeszcze się liczy
        self.wait();self.assertFalse(w.view.preview_items);self.assertEqual(len(w._sheet_state(body.id)['specs']),1)

    def test_sheet_layout_is_prepared_in_background(self):
        from rccad import sheetedit as she
        w=self.w;body=self.converted_sheet();w.apply_flange();self.wait()
        recipe=w.document.get(body.id).meta['sheet']['recipe']
        she._WARM.discard(she._layout_key(recipe));she._cached_layout.cache_clear()
        w._warm_sheets();t0=time.time()
        while not she.is_warm(recipe) and time.time()-t0<30:
            QApplication.processEvents();time.sleep(.01)
        self.assertTrue(she.is_warm(recipe))
        w.warm_pool.waitForDone(30000)

    def test_favorites_tab_toolbox_choose_order_and_keep_tab(self):
        import json
        w=self.w;self.assertEqual(list(w.tab_buttons)[0],'Ulubione')
        w.set_tab('Ulubione');w._layout_overlays()
        self.assertTrue(w.tools['toolbox'].isVisible());self.assertFalse(w.tools['extrude'].isVisible())
        self.assertEqual(w.tools['toolbox'].x(),78)                       # zaraz po dyskietce
        d=w.open_toolbox();self.assertTrue(d.isVisible())
        self.assertNotIn('toolbox',d.rows);self.assertNotIn('file',d.rows);self.assertIn('flange',d.rows);self.assertIn('drawing',d.rows)
        for key in ('extrude','flange','mod'):d.rows[key].check.click();QApplication.processEvents()
        self.assertEqual(d.chosen,['extrude','flange','mod'])
        d.rows['mod'].up.click();QApplication.processEvents();self.assertEqual(d.chosen,['extrude','mod','flange'])
        d.rows['extrude'].down.click();QApplication.processEvents();self.assertEqual(d.chosen,['mod','extrude','flange'])
        self.assertFalse(d.rows['mod'].up.isEnabled());self.assertFalse(d.rows['flange'].down.isEnabled())
        d.close_button.click();self.assertEqual(w.favorites,[])          # Zamknij nie zapisuje
        d=w.open_toolbox()
        for key in ('flange','extrude'):d.rows[key].check.click();QApplication.processEvents()
        d.apply_button.click();self.assertFalse(d.isVisible())
        self.assertEqual(w.favorites,['flange','extrude'])
        self.assertEqual(json.loads(w._settings_file('favorites').read_text(encoding='utf-8')),{'tools':['flange','extrude']})
        w._layout_overlays()
        self.assertEqual([w.tools[k].x() for k in ('toolbox','flange','extrude')],[78,138,198])
        self.assertTrue(w.tools['flange'].isVisible());self.assertFalse(w.tools['revolve'].isVisible())
        w.tools['extrude'].click();self.assertEqual((w.mode,w._tab),('extrude','Ulubione'))   # narzędzie z Ulubionych nie przełącza zakładki
        w.set_mode(None);w.tools['flange'].click();self.assertEqual(w._tab,'Ulubione')
        w.set_mode(None);w.set_tab('Bryła');w._layout_overlays();self.assertTrue(w.tools['extrude'].isVisible());self.assertEqual(w.tools['extrude'].x(),78)
        self.assertFalse(w.tools['toolbox'].isVisible())
        self.assertEqual(w._load_favorites(),['flange','extrude'])
        d=w.open_toolbox();d.reset_button.click();QApplication.processEvents();self.assertEqual(d.chosen,[]);d.apply_button.click()
        self.assertEqual(w.favorites,[]);w.set_tab('Ulubione');w._layout_overlays();self.assertFalse(w.tools['flange'].isVisible())

    def test_tool_panels_have_close_no_cancel_no_small_print(self):
        from PySide6.QtWidgets import QPushButton
        w=self.w
        panels=[w.rev_panel,w.sweep_panel,w.loft_panel,w.shell_panel,w.bool_panel,w.mod_panel,w.mir_panel,w.pat_panel,w.off_panel,w.t_editor,
                *w.mt_panels.values(),*w.dr_panels.values()]
        for panel in panels:
            texts=[b.text() for b in panel.findChildren(QPushButton)]
            self.assertIn('Zamknij',texts);self.assertNotIn('Anuluj',texts)
            self.assertEqual([l for l in panel.findChildren(QLabel) if l.objectName()=='small'],[])
        self.assertNotIn('Anuluj',[b.text() for b in w.ex_bar.findChildren(QPushButton)])
        for pic in (w.rev_angle_pic,w.sh_thick_pic,w.mod_size_pic,w.off_value_pic):self.assertFalse(pic.pixmap().isNull())
        w.set_mode('mod');w.mod_kind.setCurrentIndex(w.mod_kind.findData('chamfer'));self.assertEqual(w.mod_label.text(),'Odległość fazy (mm)')
        self.assertEqual(w.pat_axis._data,['Z','X','Y'])
        for mode,unit in (('move','mm'),('rotate','°')):
            w.set_mode(mode);self.assertEqual(w.t_editor.objectName(),'panel');self.assertTrue(w.t_editor.isVisible())
            self.assertTrue(w.t_heads[mode].isVisible());self.assertFalse(w.t_heads['rotate' if mode=='move' else 'move'].isVisible())
            self.assertEqual([l.text() for l in w.t_axis_labels],[f'{a} ({unit})' for a in 'XYZ'])
            self.assertTrue(all(not p.pixmap().isNull() for p in w.t_axis_pics))
            close=next(b for b in w.t_editor.findChildren(QPushButton) if b.text()=='Zamknij');close.click();self.assertIsNone(w.mode)

    def test_sheet_rules_panel_layout_reset_confirm_and_pick(self):
        w=self.w;w.toggle_mode('rules')
        texts=[l.text() for l in w.rules_panel.findChildren(QLabel)]
        self.assertFalse(any(t.startswith('Reguły narożników przeliczają') or t.startswith('Narożniki są dopasowywane') for t in texts))
        self.assertAlmostEqual(w.fl_gap.value(),.1);self.assertFalse(w.fl_gap_pic.pixmap().isNull())
        self.assertEqual([b.text() for b in (w.rl_ok,w.rl_close,w.rl_reset)],['Zastosuj','Zamknij','Reset'])
        self.assertEqual(w.fl_relief._data,['none','square','round'])
        w.fl_gap.setValue(2);w.fl_relief.setCurrentIndex(2);w.fl_relief_size.setValue(7);w.fl_kfactor.setValue(.3);w.fl_joint.setCurrentIndex(0)
        w.rl_reset.click()
        self.assertEqual((w.fl_gap.value(),w.fl_relief.currentData(),w.fl_relief_size.value(),w.fl_joint.currentData()),(.1,'none',3.0,'sheet'))
        self.assertAlmostEqual(w.fl_kfactor.value(),shm.K_DEFAULT);self.assertEqual(w.mode,'rules')
        body=self.converted_sheet();w.selected=[];w.toggle_mode('rules');self.assertEqual(w.mode,'rules')
        w.fl_gap.setValue(.4);w.fl_apply_rules.click()          # nic nie zaznaczono: trzeba wskazać blachę
        self.assertTrue(w.rl_pick);self.assertIn('Kliknij blachę',w.rl_status.text())
        with patch.object(w.view,'pick_body',return_value=None):w.view_clicked(5,5,False,False)
        self.assertTrue(w.rl_pick);self.assertIn('nie jest blacha',w.rl_status.text())
        with patch.object(w.view,'pick_body',return_value=body.id):w.view_clicked(5,5,False,False)
        self.wait();self.assertFalse(w.rl_pick);self.assertEqual(w.selected,[body.id])
        self.assertAlmostEqual(w._sheet_state(body.id)['rules']['gap'],.4)
        w.fl_gap.setValue(.6);w.rl_ok.click()                    # Zastosuj: ustawienia zostają, włącza się gięcie
        self.assertEqual(w.mode,'flange');self.assertTrue(w.flange_panel.isVisible());self.assertAlmostEqual(w._flange_rules()['gap'],.6)
        w.toggle_mode('rules');w.rl_close.click();self.assertIsNone(w.mode)

    def converted_sheet(self):
        from rccad import sheetmetal as shm
        w = self.w
        w.fl_radius.setValue(2);w.fl_length.setValue(20)      # geometria testów blachy: R2, kołnierz 20 mm (domyślne w programie: R0,5 i 5 mm)
        body = Body('Test blachy', k.box(100, 50, 2), 'solid').prepared()
        w.document.commit([body])
        face = next(f for f in body.shape.Faces() if abs(f.Center().z-2) < 1e-6)
        info = shm.sheet_of_face(body.shape, face)
        w.sheet_pick = dict(id=body.id, face=face, normal=(0,0,1), point=face.Center().toTuple(), info=info)
        w.apply_sheet();self.wait()
        w.toggle_mode('flange')
        w.fl_pick = dict(id=body.id, spec=dict(kind='base', p0=[100,0,2], p1=[100,50,2], n=[0,0,1], m=[1,0,0]))
        return body

    def test_flange_mode_highlights_only_edges_and_never_selects_by_itself(self):
        body = self.converted_sheet(); w = self.w
        self.assertEqual(w.selected, [])                     # konwersja nie zaznacza bryły sama
        self.assertNotIn(body.id, w.view.selected_bodies)
        w.apply_flange(); self.wait()
        self.assertEqual(w.selected, [body.id])              # blacha, na której pracuje narzędzie
        self.assertNotIn(body.id, w.view.selected_bodies)
        w.set_mode(None)                                     # po zamknięciu narzędzia nic nie zostaje zaznaczone
        self.assertEqual(w.selected, [])
        self.assertNotIn(body.id, w.view.selected_bodies)
        w.selected = [body.id]; w.refresh()                  # zaznaczenie kliknięciem zostaje
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
        self.assertNotIn('sheet_sync',w.tools)
        self.assertTrue(w._sheet_state(body.id)['flat'])
        w.tools['fold_sheet'].click();self.wait()
        self.assertFalse(w._sheet_state(body.id)['flat'])
        self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),original-2*math.pi,delta=1e-4)
        w.undo();self.wait();self.assertTrue(w._sheet_state(body.id)['flat'])
        w.redo();self.wait();self.assertFalse(w._sheet_state(body.id)['flat'])

    def test_flat_sheet_drawing_and_dxf_reload_show_bend_lines(self):
        import tempfile,os,ezdxf
        from rccad import drawing as D
        w=self.w;body=self.converted_sheet()
        w.apply_flange();self.wait()
        w.tools['unfold_sheet'].click();self.wait();self.assertTrue(w._sheet_state(body.id)['flat'])
        # rysunek rozłożonej blachy: linie gięcia w rzucie z góry, przycięte do obrysu
        w.open_drawing(w.document.get(body.id));self.wait()
        win=w._drawing_windows[-1];self.assertTrue(win.source.bends)
        win.view_boxes['top'].setChecked(True)
        d=D.build_drawing(win.source,('top',),'A4',True,'eu',None,True,True,True,False)
        styles={p.style for p in d.prims if isinstance(p,D.Poly)};self.assertTrue(styles & {'bend_up','bend_down'})
        flat=w.document.get(body.id).shape;bb=flat.BoundingBox()
        for a,b,_ in win.source.bends:
            for q in (a,b):
                self.assertTrue(bb.xmin-1e-6<=q[0]<=bb.xmax+1e-6 and bb.ymin-1e-6<=q[1]<=bb.ymax+1e-6)
        win.close()
        # eksport DXF i ponowne wczytanie w zakładce Rysunek: linie gięcia wracają jako linie gięcia, nie kontur
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'blacha.dxf')
            with patch('rccad.studio.QFileDialog.getSaveFileName',return_value=(path,'DXF')):
                w.selected=[body.id];w.tools['flat'].click()          # DXF: zawsze najpierw wskazanie blachy
                self.assertEqual(w.mode,'sheetpick');self.assertFalse(os.path.exists(path))
                with patch.object(w.view,'pick_body',return_value=body.id):w.view_clicked(5,5,False,False)
                self.wait();self.assertIsNone(w.mode)
            doc=ezdxf.readfile(path)
            self.assertIn('GIECIE_DOL',doc.linetypes)
            for line in doc.modelspace().query('LINE[layer=="BEND_UP"]'):self.assertEqual(line.dxf.linetype,'CONTINUOUS')
            for line in doc.modelspace().query('LINE[layer=="BEND_DOWN"]'):self.assertEqual(line.dxf.linetype,'GIECIE_DOL')
            w.import_drawing_file(path);self.wait()
            win=w._drawing_windows[-1];self.assertEqual(len(win.source.bends),len(doc.modelspace().query('LINE[layer!="CUT"]')))
            win.close()

    def test_flat_sheet_drawing_iso_view_shows_folded_sheet(self):
        from rccad import drawing as D
        w=self.w;body=self.converted_sheet()
        w.apply_flange();self.wait();folded_box=w.document.get(body.id).shape.BoundingBox()
        w.tools['unfold_sheet'].click();self.wait()
        flat=w.document.get(body.id)
        w.open_drawing(flat);self.wait();win=w._drawing_windows[-1]
        self.assertIsNotNone(win.source.iso_shape)
        iso=win.source.iso_shape.BoundingBox();self.assertAlmostEqual(iso.zmax-iso.zmin,folded_box.zmax-folded_box.zmin,delta=.01)     # zgięta: ścianka w górę
        top=win.source.view('top');self.assertAlmostEqual(top.bbox[3]-top.bbox[1]+top.bbox[2]-top.bbox[0],
                                                          flat.shape.BoundingBox().xlen+flat.shape.BoundingBox().ylen,3)  # rzut z góry: nadal rozwinięcie
        win.close()
        w.selected=[body.id];w.set_mode(None);w.toggle_mode('sheetdrawing')
        with patch.object(w.view,'pick_face',return_value=(body.id,(0,0,1),(50,25,2))):w.view_clicked(5,5,False,False)
        self.wait();win=w._drawing_windows[-1]
        self.assertTrue(win.view_boxes['iso'].isEnabled());self.assertFalse(win.view_boxes['iso'].isChecked())
        win.view_boxes['iso'].setChecked(True);d=D.build_drawing(win.source,**win.settings());self.assertIn('iso',d.views)
        win.close()

    def test_every_bend_line_is_dimensioned_from_outer_edges_in_any_flat_drawing(self):
        from rccad import drawing as D, sheetedit as she, sheetmetal as shm
        from rccad.drawing_window import DrawingWindow
        from test_sheetmetal_boxes import box_recipe
        r=box_recipe('out',None,'sheet',.2,2);folded=shm.build_sheet(r);flat,fs=she.switch(folded,she.state(r,False),True)
        bends=[(l['a'],l['b'],l['direction'],dict(angle=l['angle'],r=l['r'])) for l in she.flat_bend_lines(flat,fs)]
        win=DrawingWindow(flat,'Pudełko',None,bends=bends)          # zwykły „Utwórz rysunek” rozłożonej blachy
        self.assertIn('bends',win.opt);self.assertTrue(win.opt['bends'].isChecked())
        st=dict(win.settings(),views=('top',));d=D.build_drawing(win.source,**st)
        texts=[p.text for p in d.prims if isinstance(p,D.Label)]
        g=win.source.view('top')
        for horizontal,lo,hi in ((True,g.bbox[1],g.bbox[3]),(False,g.bbox[0],g.bbox[2])):
            at=sorted({round(float(pts[0][1] if horizontal else pts[0][0]),4) for pts,_,_ in g.bends
                       if abs((pts[0][1]-pts[1][1]) if horizontal else (pts[0][0]-pts[1][0]))<1e-6})
            chain=[lo,*at,hi]
            self.assertEqual(len(at),4)                            # dwie linie gięcia z każdej strony
            for p,q in zip(chain,chain[1:]):self.assertIn(D.fmt(q-p),texts)     # krawędź-gięcie, gięcie-gięcie, ..., gięcie-krawędź
        d2=D.build_drawing(win.source,**dict(st,bends=False))
        self.assertLess(len([p for p in d2.prims if isinstance(p,D.Label)]),len(texts))
        win.close()

    def test_sheet_bending_drawing_has_bend_chain_dims_labels_and_notes(self):
        from rccad import drawing as D
        w=self.w;body=self.converted_sheet()
        w.apply_flange();self.wait()                       # zgięta blacha z jednym kołnierzem
        self.assertIn('sheetdrawing',w.tools);w.set_mode(None);w.toggle_mode('sheetdrawing');self.assertEqual(w._tab,'Rysunek')
        with patch.object(w.view,'pick_face',return_value=(body.id,(0,0,1),(50,25,2))):w.view_clicked(5,5,False,False)
        self.wait();win=w._drawing_windows[-1]
        self.assertIn('rozwinięcie',win.windowTitle());self.assertEqual(win.settings()['views'],('top',))
        self.assertEqual(len(win.source.bends),1);self.assertEqual(win.source.sheet['t'],2.0)
        self.assertEqual(win.source.bend_info[0]['angle'],90.0)
        d=D.build_drawing(win.source,**win.settings())
        texts=[p.text for p in d.prims if isinstance(p,D.Label)]
        self.assertTrue(any(t.startswith('GÓRA 90° R2') for t in texts),texts)          # ścianka w górę: opis i linia ciągła
        self.assertTrue(any('Grubość blachy t = 2 mm' in t for t in texts))
        self.assertTrue(any('Promień gięcia' in t and 'R = 2 mm' in t for t in texts))
        g=win.source.view('top');(pts,direction,_)=g.bends[0];self.assertEqual(direction,'up')
        # łańcuch: krawędź - linia gięcia - krawędź (suma = wymiar całości w kierunku prostopadłym do linii)
        horizontal=abs(pts[0][1]-pts[1][1])<1e-6
        lo,hi=(g.bbox[1],g.bbox[3]) if horizontal else (g.bbox[0],g.bbox[2]);at=pts[0][1] if horizontal else pts[0][0]
        for value in (at-lo,hi-at):self.assertIn(D.fmt(value),texts)
        # linia gięcia jest elementem do wymiarowania i mierzenia
        bend=[f for f in d.features if f.get('bend')];self.assertEqual(len(bend),1);self.assertEqual(bend[0]['name'],'linia gięcia')
        win.canvas.drawing=d;mid=((bend[0]['a'][0]+bend[0]['b'][0])/2+.3,(bend[0]['a'][1]+bend[0]['b'][1])/2+.3)
        self.assertIs(win.canvas.feature_at(mid),bend[0])
        win.close()
        w.set_mode(None);w.toggle_mode('sheetdrawing')        # zwykła bryła nie jest blachą
        box=Body('Kostka',k.box(5,5,5).translate(cq.Vector(200,0,0))).prepared();w.document.commit([*w.document.bodies,box]);w.refresh()
        n=len(w._drawing_windows)
        with patch.object(w.view,'pick_face',return_value=(box.id,(0,0,1),(202,2,5))):w.view_clicked(5,5,False,False)
        self.wait();self.assertEqual(len(w._drawing_windows),n);self.assertEqual(w.mode,'sheetdrawing')

    def test_loaded_dxf_bend_lines_are_clipped_to_outline_and_holes(self):
        import tempfile,os,ezdxf
        from rccad import import2d
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'stary.dxf');doc=ezdxf.new('R2010');doc.units=ezdxf.units.MM;m=doc.modelspace()
            for n in ('CUT','BEND_UP','BEND_DOWN'):doc.layers.new(n)
            m.add_lwpolyline([(0,0),(100,0),(100,50),(0,50)],close=True,dxfattribs={'layer':'CUT'});m.add_circle((50,25),5,dxfattribs={'layer':'CUT'})
            m.add_line((-10,10),(110,10),dxfattribs={'layer':'BEND_UP'});m.add_line((-10,40),(110,40),dxfattribs={'layer':'BEND_DOWN'})
            m.add_line((-10,25),(110,25),dxfattribs={'layer':'BEND_UP'});doc.saveas(path)
            shape,bends=import2d.load_flat_parts(path)
        self.assertEqual(len(shape.Edges()),5)        # linie gięcia nie są częścią konturu
        got=sorted((round(a[0],3),round(a[1],3),round(b[0],3),round(b[1],3),d) for a,b,d in bends)
        self.assertEqual(got,[(0,10,100,10,'up'),(0,25,45,25,'up'),(0,40,100,40,'down'),(55,25,100,25,'up')])

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
        self.assertEqual(current.meta['sheet']['bend_engine'],shm.ENGINE)
        self.assertEqual(len(current.shape.Solids()),1)

    def test_sheet_reverse_creates_downward_bend_and_undo_redo(self):
        body = self.converted_sheet();w = self.w
        w.fl_reverse.setChecked(True)
        w.apply_flange();self.wait()
        folded = w.document.get(body.id).shape
        self.assertAlmostEqual(min(v.Z for v in folded.Vertices()), 2-20, delta=1e-6)    # gięcie w dół: 20 mm od zewnętrznej (górnej) strony
        self.assertAlmostEqual(max(v.Z for v in folded.Vertices()), 2, delta=1e-6)
        w.undo();self.wait();self.assertAlmostEqual(w.document.get(body.id).shape.Volume(), 10000)
        w.redo();self.wait();self.assertAlmostEqual(w.document.get(body.id).shape.Volume(), folded.Volume())

    def test_sheet_outside_tip_pick_survives_new_dimension_setting(self):
        from rccad import sheetmetal as shm
        body = self.converted_sheet();w = self.w
        w.fl_datum.setCurrentIndex(w.fl_datum.findData('outer'))
        w.apply_flange();self.wait()
        state = w._sheet_state(body.id)
        normal = shm.normalize(dict(base=state['base'],t=state['t'],flanges=state['specs'],rules=state['rules']))
        eff, _ = shm._effective(normal['flanges'], state['t'], True)
        a,b,_,_ = shm._tip_geom(eff[0], 'out', state['t'])
        midpoint = (a+b)/2
        folded = w.document.get(body.id)
        index = next(i for i,e in enumerate(folded.shape.Edges()) if np.linalg.norm(np.array(e.positionAt(.5).toTuple())-midpoint) < 1e-4)
        w.fl_datum.setCurrentIndex(w.fl_datum.findData('inner'))
        w.fl_armed = False
        with patch.object(w.view, 'nearest_edge', return_value=(body.id,index,None)):
            w.pick_flange(5,5)
        self.assertEqual(w.fl_pick['spec'], dict(kind='tip',parent=0,side='out'))
        w.apply_flange();self.wait()
        state = w._sheet_state(body.id)
        self.assertEqual([s['measure'] for s in state['specs']], ['outer', 'inner'])
        normal = shm.normalize(dict(base=state['base'],t=state['t'],flanges=state['specs'],rules=state['rules']))
        self.assertAlmostEqual(normal['flanges'][0]['length'], 20-4-4)       # zewn.: odniesienia obu gięć (R + t) na końcach
        volume = w.document.get(body.id).shape.Volume()
        w.undo();self.wait();self.assertEqual(len(w._sheet_state(body.id)['specs']),1)
        w.redo();self.wait();self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),volume,delta=.001)

    def test_sheet_box_five_mm_walls_then_returns_and_reverse_bends(self):
        body = self.converted_sheet();w = self.w
        w.fl_length.setValue(13);w.fl_gap.setValue(.2)      # wymiar zewnętrzny 13 mm = 5 mm prostej części + 2 x (R + t)
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

    def test_flange_length_measured_outside_or_inside_like_user_examples(self):
        """Blacha 1 mm, wymiar 5 mm, gięcia 90°: zewn. jedno gięcie 5 / w środku 4, dwa gięcia 5 / 3; wewn. 5 / 6 i 5 / 7."""
        from rccad import sheetmetal as shm
        w=self.w;self.assertEqual(w.fl_datum.currentData(),'outer');self.assertEqual(w.fl_datum._data,['outer','inner'])
        plate=k.box(100,50,1);top=next(f for f in plate.Faces() if abs(f.Center().z-1)<1e-6);base=shm.sheet_of_face(plate,top)['base']
        wall=lambda mode:dict(kind='base',p0=[100,0,1],p1=[100,50,1],n=[0,0,1],m=[1,0,0],r=1,angle=90,length=5,measure=mode)
        lip=lambda mode:dict(kind='tip',parent=0,side='in',r=1,angle=90,length=5,measure=mode)
        def levels(fl):
            sh=shm.build_sheet(dict(base=base,t=1,flanges=fl,rules={}))
            return sh,sorted({round(f.Center().z,6) for f in sh.Faces() if f.geomType()=='PLANE' and abs(f.normalAt().z)>.99 and f.Center().x>90})
        sh,_=levels([wall('outer')]);bb=sh.BoundingBox()
        self.assertAlmostEqual(bb.zmax,5,6);self.assertAlmostEqual(bb.zmax-1,4,6);self.assertAlmostEqual(bb.xmax,100,6)   # płyta = wymiar zewnętrzny
        _,z=levels([wall('outer'),lip('outer')]);self.assertAlmostEqual(z[-1]-0,5,6);self.assertAlmostEqual(z[-2]-1,3,6)
        sh,_=levels([wall('inner')]);bb=sh.BoundingBox()
        self.assertAlmostEqual(bb.zmax-1,5,6);self.assertAlmostEqual(bb.zmax,6,6);self.assertAlmostEqual(bb.xmax,101,6)  # płyta = wymiar wewnętrzny
        _,z=levels([wall('inner'),lip('inner')]);self.assertAlmostEqual(z[-2]-1,5,6);self.assertAlmostEqual(z[-1]-0,7,6)
        # kąty: prosty i ostry - przecięcie powierzchni (tg), rozwarty - środek łuku (sin), zawinięcie - szczyt łuku
        self.assertAlmostEqual(shm.measure_setback('outer',2,2,90),4,9)
        self.assertAlmostEqual(shm.measure_setback('inner',2,2,135),2*math.tan(math.radians(67.5)),9)
        self.assertAlmostEqual(shm.measure_setback('outer',2,2,45),4*math.sin(math.radians(22.5)),9)
        self.assertAlmostEqual(shm.measure_setback('inner',2,2,180),2,9)
        with self.assertRaises(k.CadError):
            shm.build_sheet(dict(base=base,t=1,flanges=[dict(wall('outer'),length=1.5)],rules={}))      # mniej niż R + t
        # pudełko mierzone z zewnątrz ma wymiary płyty
        body=self.converted_sheet()
        w.fl_length.setValue(10);w.fl_radius.setValue(2);w.fl_datum.setCurrentIndex(w.fl_datum.findData('outer'))
        edges=[([100,0,2],[100,50,2],[1,0,0]),([100,50,2],[0,50,2],[0,1,0]),([0,50,2],[0,0,2],[-1,0,0]),([0,0,2],[100,0,2],[0,-1,0])]
        for a,b,m in edges:
            w.fl_pick=dict(id=body.id,spec=dict(kind='base',p0=a,p1=b,n=[0,0,1],m=m));w.apply_flange();self.wait()
        bb=k.bounds(w.document.get(body.id).shape)      # dokładne wymiary (zwykły BoundingBox obejmuje punkty kontrolne skośnych cięć narożników)
        self.assertAlmostEqual(bb.xlen,100,4);self.assertAlmostEqual(bb.ylen,50,4);self.assertAlmostEqual(bb.zlen,10,4)
        self.assertEqual([s['measure'] for s in w._sheet_state(body.id)['specs']],['outer']*4)
        # starsze projekty (bez pola measure) zachowują dawne wymiary
        legacy=dict(kind='base',p0=[100,0,1],p1=[100,50,1],n=[0,0,1],m=[1,0,0],r=1,angle=90,length=5)
        self.assertAlmostEqual(shm.build_sheet(dict(base=base,t=1,flanges=[legacy],rules={})).BoundingBox().zmax,1+1+5,6)

    def test_sheet_rules_rebuild_existing_bends_without_adding_one(self):
        body = self.converted_sheet();w = self.w
        w.fl_datum.setCurrentIndex(w.fl_datum.findData('inner'));w.apply_flange();self.wait()
        original = w.document.get(body.id).shape.Volume()
        w.toggle_mode('rules');w.fl_outside.setChecked(False);w.fl_gap.setValue(.5)
        w.fl_apply_rules.click();self.wait()
        state = w._sheet_state(body.id)
        self.assertEqual(len(state['specs']),1)
        self.assertEqual(state['specs'][0]['measure'],'inner')      # reguły nie zmieniają sposobu mierzenia kołnierza
        self.assertEqual(state['rules']['gap'],.5)
        self.assertAlmostEqual(w.document.get(body.id).shape.Volume(),original,delta=.001)
        w.undo();self.wait();self.assertAlmostEqual(w._sheet_state(body.id)['rules']['gap'],.1)      # domyślna szczelina 0,1 mm

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
        w=self.w;body=self.converted_sheet();w.selected=[body.id]          # blacha zaznaczona kliknięciem
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
        w.tools['fold_sheet'].click();self.app.processEvents()
        if w.mode=='sheetpick':                      # wynik operacji nie jest zaznaczony sam - blachę wskazuje się kliknięciem
            with patch.object(w.view,'pick_body',return_value=body.id):w.view_clicked(5,5,False,False)
        self.wait()
        self.assertFalse(w._sheet_state(body.id)['flat'])
        folded=w.document.get(body.id).shape
        self.assertLess(folded.cut(original).Volume(1e-9)+original.cut(folded).Volume(1e-9),1e-4)

    def test_four_bottom_parallel_hems_can_be_picked_unfolded_and_refolded(self):
        self._four_bottom_hems_and_refold('parallel')

    def test_four_bottom_sheet_hems_can_be_picked_unfolded_and_refolded(self):
        self._four_bottom_hems_and_refold('sheet')

    def test_corner_fitting_is_automatic_and_the_old_toggle_is_absent(self):
        from dataclasses import replace
        from rccad import sheetedit
        body=self.converted_sheet();w=self.w;current=w.document.get(body.id)
        source=w._editable_sheet_state(body.id)
        source['recipe']['rules'].update(miter=False,auto_corners=False)
        source['bend_engine']=4
        w.document.commit([replace(current,meta={'sheet':source})])
        w.set_mode(None);w.selected=[body.id];w.toggle_mode('rules')
        self.assertFalse(hasattr(w,'fl_miter'))
        self.assertNotIn('Docinaj i przedłużaj narożniki',[box.text() for box in w.rules_panel.findChildren(QCheckBox)])
        w.apply_sheet_rules();self.wait()
        state=w._editable_sheet_state(body.id)
        self.assertTrue(state['recipe']['rules']['auto_corners'])
        self.assertTrue(state['recipe']['rules']['miter'])
        self.assertEqual(state['bend_engine'],shm.ENGINE)

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
        self.assertIsNotNone(w.sheet_pick);self.assertEqual((w.sheet_t.text(),w.sheet_dims.text()),('2 mm','100 × 50 mm'))
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

    def test_measure_right_click_undoes_one_point_and_keeps_the_tool(self):
        w=self.w;b=Body('Bryła',k.box(20,20,20)).prepared();w.document.commit([b]);w.refresh()
        revision=w.document._revision
        for mode,points in [('mdist',[(0,0,0),(10,0,0)]),('mangle',[(10,0,0),(0,0,0),(0,10,0)])]:
            w.set_mode(mode)
            for point in points:
                with patch.object(w.view,'nearest_vertex',return_value=(b.id,np.array(point,float))):w.view_clicked(5,5,False,False)
            w.context_menu(5,5)
            self.assertEqual(w.mode,mode);self.assertEqual(len(w.ms_points),len(points)-1)
            np.testing.assert_allclose(w.ms_points[0],points[0])
            self.assertEqual(len(w.view.measure_labels),len(points)-1)
            with patch.object(w.view,'nearest_vertex',return_value=(b.id,np.array((0,0,10),float))):w.view_clicked(5,5,False,False)
            self.assertEqual(len(w.ms_points),len(points))
            while w.ms_points:w.context_menu(5,5)
            self.assertFalse(w.ms_refs);self.assertFalse(w.view.measure_labels)
        self.assertEqual(w.document._revision,revision)

    def test_measure_panels_wrap_long_results_above_fixed_footer(self):
        w=self.w;w.resize(1366,768);self.app.processEvents()
        text='<b>Wynik pomiaru</b><br>'+('<br>'.join('Długa nazwa elementu: '+('przykładowa powierzchnia ' * 8) for _ in range(7)))
        for mode in ('mdist','mangle','mrad','mprops'):
            w.set_mode(mode);w.hist_bar.show();w._layout_overlays()
            w._measure_show(text);self.app.processEvents();w._layout_overlays()
            panel=w.ms_panels[mode];area,body=panel.scroll;label=w.ms_status[mode]
            self.assertGreaterEqual(panel.width(),380)
            self.assertGreaterEqual(label.height(),label.heightForWidth(panel.width()-52))
            self.assertGreater(area.verticalScrollBar().maximum(),0)
            footer=panel.footer.itemAt(0).layout().itemAt(0).widget()
            self.assertTrue(footer.isVisible());self.assertGreater(footer.mapTo(panel,footer.rect().topLeft()).y(),area.geometry().bottom())
            self.assertLessEqual(panel.geometry().bottom(),w.hist_bar.y())
            w.context_menu(5,5) # also clears the single-reference tools

    def test_measure_result_height_does_not_grow_with_hover_and_can_shrink(self):
        w=self.w;w.set_mode('mdist')
        w._measure_show('<br>'.join('Wynik pomiaru: 123.456 mm' for _ in range(8)))
        label=w.ms_status['mdist'];height=label.minimumHeight();panel_height=w.ms_panels['mdist'].height()
        for _ in range(30):w._measure_panel_fit()
        self.assertEqual(label.minimumHeight(),height)
        w._measure_show('Wskaż drugi punkt.')
        self.assertLess(label.minimumHeight(),height)
        self.assertLess(w.ms_panels['mdist'].height(),panel_height)

    def test_section_work_hides_only_section_arrow_and_off_forgets_everything(self):
        w=self.w;b=Body('Bryła',k.box(20,20,20)).prepared();w.document.commit([b]);w.refresh()
        w.toggle_section(True)
        with patch.object(w.view,'pick_face',return_value=(b.id,[0,-1,0],[10,0,10])):w.section_pick(5,5)
        w.section_offset.setValue(7);plane=w.view.section_plane.copy();revision=w.document._revision
        w.section_work_button.click()
        self.assertTrue(w.section_working);self.assertEqual(w.section_work_button.text(),'PRZERWIJ')
        self.assertFalse(w.view.section_handles);self.assertFalse(w.section_offset.isEnabled())
        w.set_mode('extrude');np.testing.assert_allclose(w.view.section_plane,plane)
        self.assertFalse(w.view.section_handles)
        w.handle_dragged('section',12);self.assertEqual(w.section_offset.value(),7)
        w.section_work_button.click()
        self.assertFalse(w.section_working);self.assertTrue(w.view.section_handles)
        self.assertEqual(w.section_work_button.text(),'PRACUJ');self.assertTrue(w.section_offset.isEnabled())
        self.assertTrue(w.section_edit_buttons[0].isEnabled())
        w.toggle_section(False)
        self.assertIsNone(w.mode);self.assertIsNone(w.section_origin);self.assertIsNone(w.section_normal)
        self.assertIsNone(w.view.section_plane);self.assertEqual(w.section_offset.value(),0)
        self.assertFalse(w.section_working);self.assertEqual(w.document._revision,revision)
        w.toggle_section(True)
        self.assertTrue(w.section_picking);self.assertIsNone(w.view.section_plane)
        self.assertFalse(w.section_work_button.isEnabled())

    def test_section_off_cancels_pending_tool_without_applying_late_result(self):
        import threading
        w=self.w;gate=threading.Event();applied=[]
        b=Body('Bryła',k.box(20,20,20)).prepared();w.document.commit([b]);w.refresh()
        w.toggle_section(True)
        with patch.object(w.view,'pick_face',return_value=(b.id,[0,-1,0],[10,0,10])):w.section_pick(5,5)
        w.section_work(True);w.set_mode('extrude')
        w.run_operation('Test',lambda:gate.wait(5),lambda value:applied.append(value))
        try:
            w.toggle_section(False)
            self.assertFalse(w.busy);self.assertIsNone(w.mode);self.assertIsNone(w.view.section_plane)
        finally:gate.set()
        w.pool.waitForDone(5000);self.app.processEvents()
        self.assertFalse(applied);self.assertIs(w.document.get(b.id).shape,b.shape)

    def test_measure_angle_edge_right_click_retains_first_reference(self):
        w=self.w;b=Body('Bryła',k.box(20,20,20)).prepared();w.document.commit([b]);w.refresh();w.set_mode('mangle')
        w.ms_angle_kind.setCurrentIndex(1)
        edges=[0,next(i for i,e in enumerate(b.shape.Edges()) if abs(np.dot(np.asarray(e.tangentAt().toTuple()),np.asarray(b.shape.Edges()[0].tangentAt().toTuple())))<.1)]
        for i in edges:
            with patch.object(w.view,'nearest_edge',return_value=(b.id,i)):w.view_clicked(5,5,False,False)
        w.context_menu(5,5)
        self.assertEqual(len(w.ms_angle_refs),1);self.assertEqual(w.ms_angle_refs[0]['edge'],edges[0])
        self.assertIn('Wskaż drugi element',w.ms_status['mangle'].text())
        with patch.object(w.view,'nearest_edge',return_value=(b.id,edges[1])):w.view_clicked(5,5,False,False)
        self.assertIn('90.00',w.ms_status['mangle'].text())

    def test_section_material_can_select_body_properties_without_selecting_hidden_face(self):
        from PySide6.QtGui import QVector3D
        w=self.w;b=Body('Pełny blok',k.box(80,60,60)).prepared();w.document.commit([b]);w.refresh()
        w.view.opts['center']=QVector3D(40,30,30);w.view.setCameraPosition(distance=200,elevation=0,azimuth=-90)
        w.toggle_section(True);xy=w.view.project_one((40,0,30));w.section_pick(*xy)
        w.section_offset.setValue(25);w.section_work(True);w.set_mode('mprops')
        xy=w.view.project_one((40,25,30));self.assertIsNone(w.view.pick_face(*xy))
        self.assertEqual(w._measure_candidate(*xy)['id'],b.id)
        w.view_clicked(*xy,False,False)
        self.assertIn('Pełny blok',w.ms_status['mprops'].text());self.assertIn('288,000.00',w.ms_status['mprops'].text())

    def test_section_persists_across_tools_and_extrudes_actual_inside_wall(self):
        from PySide6.QtGui import QVector3D
        w=self.w
        shape=k.boolean('subtract',k.box(80,60,60),[k.box(60,40,48).translate(cq.Vector(10,10,6))])
        b=Body('Komora',shape).prepared();w.document.commit([b]);w.refresh()
        w.view.opts['center']=QVector3D(40,30,30);w.view.setCameraPosition(distance=180,elevation=0,azimuth=-90)
        xy=w.view.project_one((40,50,30));revision=w.document._revision
        w.toggle_section(True);w.view_clicked(*xy,False,False)
        self.assertFalse(w.section_picking);self.assertEqual(w.selected,[])
        for offset in (5,10,15,25):w.section_offset.setValue(offset)
        self.assertIs(w.document.get(b.id).shape,shape);self.assertEqual(w.document._revision,revision)
        self.assertEqual([h['id'] for h in w.view.all_handles()],['section'])
        plane=w.view.section_plane.copy();w.set_mode('extrude')
        np.testing.assert_allclose(w.view.section_plane,plane)
        w.view_clicked(*xy,False,False)
        self.assertEqual(len(w.ex_profiles),1)
        self.assertAlmostEqual(w.ex_profiles[0]['center'][1],50,4)
        w.ex_op.setCurrentIndex(w.ex_op.findData('join'));w.ex_value.setValue(5)
        w.apply_extrude();self.wait()
        self.assertGreater(w.document.get(b.id).shape.Volume(),shape.Volume())
        np.testing.assert_allclose(w.view.section_plane,plane)
        w.toggle_section(False);self.assertIsNone(w.view.section_plane)
        self.assertFalse(w.view.section_handles);self.assertFalse(w.section_panel.isVisible())

    def test_section_mouse_choice_hover_flip_and_cancel(self):
        from PySide6.QtGui import QVector3D
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint
        w=self.w;b=Body('Bryła',k.box(40,40,40)).prepared()
        w.document.commit([b]);w.refresh();w.view.opts['center']=QVector3D(20,20,20)
        w.view.setCameraPosition(distance=150,elevation=0,azimuth=-90)
        xy=w.view.project_one((20,0,20));w.toggle_section(True);w.view_hover(*xy)
        self.assertTrue(w.view.section_hover_items);self.assertEqual(w.selected,[])
        QTest.mouseClick(w.view,Qt.LeftButton,pos=QPoint(round(xy[0]),round(xy[1])))
        self.assertFalse(w.section_picking);self.assertFalse(w.view.section_hover_items)
        w.section_offset.setValue(10);p=w.view.section_plane.copy();w.section_flip()
        np.testing.assert_allclose(w.view.section_plane,-p)
        w.section_repick();self.assertIsNone(w.view.section_plane)
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier))
        self.assertFalse(w.section_picking);np.testing.assert_allclose(w.view.section_plane,-p)
        w.handle_dragged('section',7);w.handle_released('section')
        self.assertAlmostEqual(w.section_offset.value(),17)
        w.toggle_section(False);w.toggle_section(True)
        self.assertEqual(w.section_offset.value(),0)
        self.assertTrue(w.section_picking);self.assertIsNone(w.section_origin)

    def test_angle_two_edges_and_faces_has_exact_references_and_supplement(self):
        w=self.w
        a=Body('Linia A',cq.Wire.assembleEdges([cq.Edge.makeLine((0,0,0),(20,0,0))]),'sketch','XY').prepared()
        b=Body('Linia B',cq.Wire.assembleEdges([cq.Edge.makeLine((40,0,0),(30,10,0))]),'sketch','XY').prepared()
        box=Body('Kostka',k.box(20,20,20)).prepared()
        w.document.commit([a,b,box]);w.refresh();w.set_mode('mangle');w.ms_angle_kind.setCurrentIndex(1)
        for body in (a,b):
            with patch.object(w.view,'nearest_edge',return_value=(body.id,0)):
                w.view_hover(5,5);self.assertIn(body.name,w.ms_hover_label['mangle'].text())
                w.view_clicked(5,5,False,False)
        self.assertIn('45.00°',w.ms_status['mangle'].text());self.assertIn('135.00°',w.ms_status['mangle'].text())
        self.assertEqual([r['id'] for r in w.ms_angle_refs],[a.id,b.id]);self.assertEqual(len(w.view.measure_labels),2)
        w.ms_angle_kind.setCurrentIndex(2);self.assertFalse(w.ms_angle_refs)
        for n,p in [((0,0,1),(10,10,20)),((1,0,0),(20,10,10))]:
            with patch.object(w.view,'pick_face',return_value=(box.id,n,p)):
                w.view_clicked(5,5,False,False)
        self.assertIn('90.00°',w.ms_status['mangle'].text())
        self.assertEqual(len(w.ms_angle_refs),2)
        w.set_mode('extrude');self.assertFalse(w.view.measure_labels)

    def test_measure_snaps_to_sketch_edge_and_rejects_empty_space(self):
        w=self.w
        b=Body('Linia',cq.Wire.assembleEdges([cq.Edge.makeLine((0,0,0),(20,0,0))]),'sketch','XY').prepared()
        w.document.commit([b]);w.refresh();w.set_mode('mdist')
        xy=w.view.project_one((10,0,0))
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=(b.id,0)),patch.object(w.view,'_visible_point',return_value=True):
            w.view_hover(*xy);w.view_clicked(*xy,False,False)
        np.testing.assert_allclose(w.ms_points[0],[10,0,0],atol=1e-5)
        self.assertIn('Środek krawędzi',w.ms_refs[0]['label'])
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=None),patch.object(w.view,'pick_face',return_value=None):
            w.view_clicked(0,0,False,False)
        self.assertEqual(len(w.ms_points),1)
        w._measure_reset();self.assertFalse(w.view.measure_labels);self.assertIsNone(w.view.snap_marker)

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

    def test_drawing_tab_loads_svg_and_dxf_files(self):
        import tempfile,os,ezdxf
        w=self.w;self.assertIn('importdrawing',w.tools);self.assertFalse(w.tools['importdrawing'].isCheckable())
        with tempfile.TemporaryDirectory() as tmp:
            svg=os.path.join(tmp,'plyta.svg')
            Path(svg).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="40mm" viewBox="0 0 80 40"><rect x="0" y="0" width="80" height="40"/>'
                                 '<circle cx="20" cy="20" r="6"/><path d="M50 10 A 10 10 0 0 1 70 10 Q 75 30 50 30 Z"/></svg>',encoding='utf-8')
            dxf=os.path.join(tmp,'detal.dxf');doc=ezdxf.new('R2010');doc.units=ezdxf.units.CM;m=doc.modelspace()
            m.add_lwpolyline([(0,0,0),(5,0,0.4142),(6,1,0),(6,3),(0,3)],format='xyb',close=True);m.add_circle((2,1.5),.5);doc.saveas(dxf)
            with patch('rccad.studio.QFileDialog.getOpenFileName',return_value=(svg,'SVG')):
                w.tools['importdrawing'].click();self.wait()
            win=w._drawing_windows[-1];self.assertIn('plyta',win.windowTitle())
            self.assertEqual(win.settings()['views'],('top',));self.assertFalse(win.view_boxes['front'].isEnabled())
            bb=win.source.shape.BoundingBox();self.assertAlmostEqual(bb.xlen,80,3);self.assertAlmostEqual(bb.ylen,40,3)
            g=win.source.view('top');self.assertTrue(any(c['full'] and abs(c['r']-6)<1e-6 for c in g.circles))
            win.close()
            w.import_drawing_file(dxf);self.wait()
            win=w._drawing_windows[-1];bb=win.source.shape.BoundingBox()
            self.assertAlmostEqual(bb.xlen,60,3);self.assertAlmostEqual(bb.ylen,30,3)       # centymetry przeliczone na mm
            self.assertTrue(any(c['full'] and abs(c['r']-5)<1e-6 for c in win.source.view('top').circles));win.close()
            bad=os.path.join(tmp,'pusty.svg');Path(bad).write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>',encoding='utf-8')
            n=len(w._drawing_windows);w.import_drawing_file(bad);self.wait();self.assertEqual(len([x for x in w._drawing_windows if x.isVisible()]),0)

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
        controls=[w.clear_button,w.undo_button,w.redo_button,w.section_button,w.scale_button,w.layers,w.xray,w.home]
        for left,right in zip(controls,controls[1:]):self.assertLess(left.geometry().right(),right.x())
        self.assertTrue(w.section_button.isVisible());self.assertLess(w.home.geometry().right(),w.cube.x())
        last=max(b.geometry().right() for b in w.tab_buttons.values())
        self.assertTrue(w.clear_button.x()>last or w.clear_button.y()>=60)
        self.assertFalse(w.shape_bar.isVisible())

    def test_top_controls_fit_narrow_and_wide_windows(self):
        w=self.w
        for width in (1200,1366,1400,1920):
            w.resize(width,850);self.app.processEvents();w._layout_overlays()
            controls=[w.clear_button,w.undo_button,w.redo_button,w.section_button,w.scale_button,w.layers,w.xray,w.home]
            for left,right in zip(controls,controls[1:]):self.assertLess(left.geometry().right(),right.x())
            end=max(b.geometry().right() for b in w.tab_buttons.values())
            self.assertTrue(w.clear_button.x()>end or w.clear_button.y()>=60,width)
            self.assertLess(w.home.geometry().right(),w.cube.x())
            self.assertGreaterEqual(w.section_button.width(),32)
        # Pixel positions depend on Windows DPI/font metrics; retain adjacency
        # and fall back below the tabs when their captions need more space.
        first=next(iter(w.tab_buttons.values()))
        first.setText('Szeroka zakładka ' * 12);w._layout_overlays()
        self.assertGreaterEqual(w.clear_button.y(),60)
        self.assertLess(w.section_button.geometry().right(),w.scale_button.x())

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

    # 0.4.66: zaznaczone szkice (np. grupa importu) - Wyciągnij od razu bierze wszystkie, Shift + klik odznacza
    def test_extrude_takes_selected_sketches_and_shift_deselects(self):
        w=self.w
        a=Body('A',k.sketch('rectangle','XY',10,10),'sketch','XY',folder='plik').prepared()
        b=Body('B',k.transform(k.sketch('rectangle','XY',10,10),(30,0,0)),'sketch','XY',folder='plik').prepared()
        c=Body('C',k.transform(k.sketch('rectangle','XY',10,10),(60,0,0)),'sketch','XY').prepared()
        w.document.commit([a,b,c]);w.refresh()
        w.objects_folder_select([a.id,b.id])
        w.set_mode('extrude')
        self.assertEqual(len(w.ex_profiles),2);self.assertTrue(w.ex_bar.isVisible())
        # Shift + klik na profilu B: odznaczony
        prof=next(p for p in w.ex_profiles if p['center'][0]>20)
        with patch.object(w,'_profile_at',return_value=dict(prof)):w.view_clicked(5,5,True,False)
        self.assertEqual(len(w.ex_profiles),1);self.assertLess(w.ex_profiles[0]['center'][0],20)
        w.ex_value.setValue(5);w.apply_extrude();self.wait()
        self.assertEqual(len([x for x in w.document.bodies if x.kind=='solid']),1)

    # 0.4.66: cała grupa zaznaczona na liście Obiekty - przesuwanie i obracanie wszystkich
    def test_move_whole_selected_group(self):
        w=self.w
        a=Body('A',k.box(5,5,5),folder='G').prepared();b=Body('B',k.transform(k.box(5,5,5),(20,0,0)),folder='G').prepared();c=Body('C',k.transform(k.box(5,5,5),(40,0,0))).prepared()
        w.document.commit([a,b,c]);w.refresh()
        w.objects_folder_select([a.id,b.id]);w.set_mode('move')
        self.assertEqual(sorted(w.t_group),sorted([a.id,b.id]))
        w.t_spins[1].setValue(7);w.apply_transform();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Center().y,9.5,6);self.assertAlmostEqual(w.document.get(b.id).shape.Center().y,9.5,6)
        self.assertAlmostEqual(w.document.get(c.id).shape.Center().y,2.5,6)

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

    def test_extrude_up_to_vertex_edge_face_and_plane(self):
        w=self.w;a=Body('A',k.box(20,20,30)).prepared();w.document.commit([a]);w.refresh()
        self.sketch('rect',(40,0),(50,10));w.set_mode('extrude')
        sk=next(b for b in w.document.bodies if b.kind=='sketch')
        w.ex_extent.setCurrentIndex(w.ex_extent.findData('upto'))
        self.assertFalse(w.ex_dir.isVisible());self.assertEqual(w.ex_dir.currentData(),'one')
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_face',return_value=None),patch.object(w.view,'pick_profile',return_value=sk.id):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_profiles[0]['kind'],'sketch');self.assertIsNone(w.ex_target)
        # punkt (wierzchołek bryły na wysokości 30)
        with patch.object(w.view,'nearest_vertex',return_value=(a.id,np.array([20.0,20.0,30.0]))):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_target['kind'],'vertex');self.assertAlmostEqual(abs(w.ex_value.value()),30.0,3);self.assertTrue(w.ex_target_label.isVisible())
        # ściana równoległa (górna ściana bryły z=30) - liczy się środek ściany
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,np.array([0,0,1.0]),np.array([5.0,5.0,30.0]))):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_target['kind'],'face');self.assertAlmostEqual(abs(w.ex_value.value()),30.0,3)
        # krawędź pozioma na wysokości 30
        body=next(b for b in w.view.bodies if b.id==a.id)
        idx=next(i for i,pts in body.mesh.edges.items() if np.ptp(np.asarray(pts)[:,2])<1e-6 and abs(np.asarray(pts)[0,2]-30)<1e-6)
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=(a.id,idx)):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_target['kind'],'edge');self.assertAlmostEqual(abs(w.ex_value.value()),30.0,3)
        # płaszczyzna na wysokości profilu odrzucona, wartość zostaje
        w._planes_visible=True
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=None),patch.object(w.view,'pick_face',return_value=None),patch.object(w.view,'plane_at',return_value='XY'):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_target['kind'],'edge');self.assertAlmostEqual(abs(w.ex_value.value()),30.0,3)
        w.ex_op.setCurrentIndex(0);w.apply_extrude();self.wait()
        new=[b for b in w.document.bodies if b.kind=='solid' and b.id!=a.id];self.assertEqual(len(new),1)
        self.assertAlmostEqual(new[0].shape.Volume(),10*10*30,2)
        self.assertEqual(w.document.info['op']['upto']['kind'],'edge')

    def _upto_between_boxes(self,op,middle=False):
        """Bryła A (0..20) i bryła B (x 40..60); ściana A x=20 wyciągana do ściany B x=40 (B tylko wyznacza odległość)."""
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.transform(k.box(20,20,20),(40,0,0),(0,0,0))).prepared()
        bodies=[a,b]
        if middle:
            c=Body('C',k.box(4,20,10).translate(cq.Vector(28,10,5))).prepared();bodies.append(c)      # połowa w drodze narzędzia (y 10..30)
        w.document.commit(bodies);w.refresh();w.set_mode('extrude');w.ex_extent.setCurrentIndex(w.ex_extent.findData('upto'))
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.0,0,0]),np.array([20.0,10.0,10.0]))):
            w.view_clicked(5,5,False,False)
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=None),patch.object(w.view,'pick_face',return_value=(b.id,np.array([-1.0,0,0]),np.array([40.0,10.0,10.0]))):
            w.view_clicked(5,5,False,False)
        self.assertAlmostEqual(w.ex_value.value(),20.0,3);self.assertEqual(w._extent_skip(),[b.id])
        w.ex_op.setCurrentIndex(w.ex_op.findData(op));w.apply_extrude();self.wait()
        return a,b

    def test_extrude_up_to_point_inside_other_solid_cuts_into_it(self):
        """Narzędzie wchodzi w drugą bryłę do wskazanego punktu (jej dalszego narożnika): Wytnij wycina z niej tę część."""
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.box(20,20,20).translate(cq.Vector(40,0,0))).prepared()
        w.document.commit([a,b]);w.refresh();w.set_mode('extrude');w.ex_extent.setCurrentIndex(w.ex_extent.findData('upto'))
        sk=Body('Okno',cq.Workplane('XY').rect(10,10).val().translate(cq.Vector(20,10,10)).rotate(cq.Vector(20,10,10),cq.Vector(20,11,10),90),'sketch',
                k.face_frame((20,10,10),(1,0,0))).prepared()
        w.document.commit([a,b,sk]);w.refresh()
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_face',return_value=None),patch.object(w.view,'pick_profile',return_value=sk.id):
            w.view_clicked(5,5,False,False)
        with patch.object(w.view,'nearest_vertex',return_value=(b.id,np.array([50.0,0.0,0.0]))):
            w.view_clicked(5,5,False,False)
        self.assertAlmostEqual(abs(w.ex_value.value()),30.0,3)
        w.ex_op.setCurrentIndex(w.ex_op.findData('cut'));w.apply_extrude();self.wait()
        self.assertAlmostEqual(w.document.get(b.id).shape.Volume(),8000-10*10*10,1)      # w B wycięte 10 mm głębokości
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),8000,1)

    def test_extrude_up_to_other_solid_joins_only_own_solid(self):
        w=self.w;a,b=self._upto_between_boxes('join')
        solids=[x for x in w.document.bodies if x.kind=='solid'];self.assertEqual(len(solids),2)
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),40*20*20,1)        # A dochodzi do B
        self.assertAlmostEqual(w.document.get(b.id).shape.Volume(),20*20*20,1)        # B bez zmian
        self.assertEqual(w.document.info['op']['skip'],[b.id])
        again=hist.run_extrude([a,b],w.document.info['op'])
        self.assertAlmostEqual(next(x for x in again if x.id==b.id).shape.Volume(),8000,1)

    def test_extrude_up_to_other_solid_cuts_only_solids_on_the_way(self):
        w=self.w;a,b=self._upto_between_boxes('cut',middle=True)
        c=next(x for x in w.document.bodies if x.name=='C')
        self.assertAlmostEqual(w.document.get(b.id).shape.Volume(),8000,1)            # narzędzie tylko dotyka B - nic z niej nie ubywa
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),8000,1)
        self.assertAlmostEqual(c.shape.Volume(),4*10*10,1)                               # bryła po drodze wycięta do połowy

    def test_cut_removes_solid_lying_wholly_inside_and_cuts_the_rest(self):
        a=Body('A',k.box(20,20,20)).prepared();c=Body('C',k.box(4,4,4).translate(cq.Vector(30,5,5))).prepared()
        out=hist.combine([a,c],[k.box(30,20,20).translate(cq.Vector(15,0,0))],'cut')
        self.assertEqual([b.name for b in out],['A']);self.assertAlmostEqual(out[0].shape.Volume(),6000,1)
        with self.assertRaises(k.CadError):       # nic do wycięcia - jak dotychczas komunikat zamiast cichej zmiany
            hist.combine([a],[k.box(5,5,5).translate(cq.Vector(50,50,50))],'cut')

    def test_extrude_up_to_same_solid_step_still_joins(self):
        w=self.w
        step=Body('S',k.boolean('union',k.box(20,20,10),[k.transform(k.box(10,20,10),(0,0,10),(0,0,0))])).prepared()
        w.document.commit([step]);w.refresh();w.set_mode('extrude');w.ex_extent.setCurrentIndex(1)
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(step.id,np.array([0,0,1.0]),np.array([15.0,10.0,10.0]))):
            w.view_clicked(5,5,False,False)
        with patch.object(w.view,'nearest_vertex',return_value=(step.id,np.array([0.0,0.0,20.0]))):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w._extent_skip(),[]);w.ex_op.setCurrentIndex(w.ex_op.findData('join'));w.apply_extrude();self.wait()
        self.assertAlmostEqual(w.document.get(step.id).shape.Volume(),20*20*20,1)

    def test_extrude_distance_field_is_focused_and_selected(self):
        w=self.w;w.activateWindow();self.sketch('rect',(0,0),(10,10));w.set_mode('extrude')
        self.pick_sketch_profile(w.document.bodies[0]);self.app.processEvents()
        self.assertTrue(w.ex_value.hasFocus())
        edit=w.ex_value.lineEdit();self.assertEqual(edit.selectedText(),edit.text())

    def test_extrude_up_to_target_unlinks_on_manual_value(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');w.ex_extent.setCurrentIndex(1)
        self.pick_sketch_profile(w.document.bodies[0])
        with patch.object(w.view,'nearest_vertex',return_value=('x',np.array([0.0,0.0,-12.0]))):
            w.view_clicked(5,5,False,False)
        self.assertAlmostEqual(abs(w.ex_value.value()),12.0,3);self.assertIsNotNone(w.ex_target)
        w.ex_value.setValue(7);self.assertIsNone(w.ex_target);self.assertFalse(w.ex_target_label.isVisible())
        w.ex_extent.setCurrentIndex(0);self.assertTrue(w.ex_dir.isVisible())

    def test_extrude_both_ends_of_cube_join_cut_and_replay(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('extrude')
        w.ex_dir.setCurrentIndex(w.ex_dir.findData('ends'))
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,np.array([0,0,1.0]),np.array([10.0,10.0,20.0]))):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.ex_profiles[0]['kind'],'face')
        w.ex_op.setCurrentIndex(w.ex_op.findData('join'));w.ex_value.setValue(5);self.preview()
        self.assertTrue(w.view.preview_items)
        w.apply_extrude();self.wait()
        solid=w.document.get(a.id);self.assertAlmostEqual(solid.shape.Volume(),20*20*30,1)
        bb=solid.shape.BoundingBox();self.assertAlmostEqual(bb.zmin,-5,3);self.assertAlmostEqual(bb.zmax,25,3)
        recipe=w.document.info['op'];self.assertEqual(recipe['dir'],'ends')
        again=hist.run_extrude([a],recipe);self.assertAlmostEqual(next(b for b in again if b.kind=='solid').shape.Volume(),20*20*30,1)
        # wycięcie do środka z obu stron
        w.set_mode('extrude');w.ex_dir.setCurrentIndex(w.ex_dir.findData('ends'))
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_profile',return_value=None),patch.object(w.view,'pick_face',return_value=(a.id,np.array([0,0,1.0]),np.array([10.0,10.0,25.0]))):
            w.view_clicked(5,5,False,False)
        w.ex_op.setCurrentIndex(w.ex_op.findData('cut'));w.ex_value.setValue(-10);w.apply_extrude();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),20*20*10,1)

    def test_extrude_both_ends_needs_opposite_face(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.set_mode('extrude');w.ex_dir.setCurrentIndex(3)
        self.pick_sketch_profile(w.document.bodies[0]);w.ex_value.setValue(5);w.apply_extrude();self.wait()
        self.assertFalse([b for b in w.document.bodies if b.kind=='solid'])

    def _mate_pick(self,body,normal,point):
        with patch.object(self.w.view,'pick_face',return_value=(body.id,np.array(normal,float),np.array(point,float))):
            self.w.view_clicked(5,5,False,False)

    def test_mate_puts_face_against_face_with_centres_together(self):
        w=self.w
        a=Body('A',k.box(10,20,30)).prepared();b=Body('B',k.box(40,40,10).translate(cq.Vector(100,50,0))).prepared()
        w.document.commit([a,b]);w.refresh()
        w.toggle_mode('mate');self.assertEqual(w._tab,'Edycja');self.assertTrue(w.mt_panels['mate'].isVisible())
        self._mate_pick(a,(-1,0,0),(0,10,15))            # lewa ściana A
        self.assertEqual(w.mt_pick['moving']['id'],a.id);self.assertNotIn('target',w.mt_pick)
        self._mate_pick(b,(0,0,1),(120,70,10))           # góra B
        self.preview();self.assertTrue(w.view.preview_items)
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier));self.wait()
        moved=w.document.get(a.id).shape
        self.assertAlmostEqual(moved.Volume(),6000,3);self.assertAlmostEqual(moved.BoundingBox().zmin,10,4)
        self.assertLess(moved.intersect(w.document.get(b.id).shape).Volume(),1e-6)
        touching=[f for f in moved.Faces() if np.allclose(f.Center().toTuple(),(120,70,10),atol=1e-5)]
        self.assertEqual(len(touching),1);self.assertAlmostEqual(touching[0].Area(),20*30,4)       # ściana A leży na środku góry B
        self.assertEqual(w.document.info['op']['type'],'mate');self.assertAlmostEqual(w.document.get(b.id).shape.Volume(),16000,6)      # bryła docelowa bez zmian
        w.undo();self.wait();self.assertAlmostEqual(w.document.get(a.id).shape.BoundingBox().zmin,0,6)

    def test_mate_spin_arrows_turn_moving_body_in_45_degree_steps(self):
        w=self.w
        a=Body('A',k.box(10,20,30)).prepared();b=Body('B',k.box(40,40,10).translate(cq.Vector(100,50,0))).prepared()
        w.document.commit([a,b]);w.refresh();w.toggle_mode('mate')
        self.assertTrue(w.mt_left.isVisible());self.assertEqual(w.mt_angle.text(),'0°')
        self._mate_pick(a,(-1,0,0),(0,10,15));self._mate_pick(b,(0,0,1),(120,70,10))
        w.mt_left.click();self.assertEqual(w.mt_angle.text(),'+45°');self.assertEqual(w._mt_recipe()['spin'],45.0)
        w.mt_left.click();w.mt_right.click();w.mt_left.click()          # +45 +45 -45 +45 = 90
        self.assertEqual(w.mt_angle.text(),'+90°')
        w.apply_mate();self.wait();bb=w.document.get(a.id).shape.BoundingBox()
        self.assertAlmostEqual(bb.xlen,20,4);self.assertAlmostEqual(bb.ylen,30,4)        # bez obrotu 30 x 20
        self.assertAlmostEqual(bb.zmin,10,4)
        self.assertTrue(any(np.allclose(f.Center().toTuple(),(120,70,10),atol=1e-5) for f in w.document.get(a.id).shape.Faces()))
        self.assertEqual(w.document.info['op']['spin'],90.0)
        w.toggle_mode('mate');self.assertEqual(w.mt_angle.text(),'0°')                 # nowe dopasowanie zaczyna od zera
        for _ in range(5):w.spin_mate(-45)
        self.assertEqual(w.mt_angle.text(),'+135°')                                    # -225° = +135°

    def test_align_moves_body_along_reference_normal_only_and_replays(self):
        w=self.w
        a=Body('Niski',k.box(10,10,30)).prepared();c=Body('Wysoki',k.box(10,10,50).translate(cq.Vector(30,0,0))).prepared()
        w.document.commit([a,c]);w.refresh();w.toggle_mode('align')
        self._mate_pick(a,(0,0,1),(5,5,30));self._mate_pick(c,(0,0,1),(35,5,50))
        w.apply_mate();self.wait()
        bb=w.document.get(a.id).shape.BoundingBox()
        self.assertAlmostEqual(bb.zmax,50,4);self.assertAlmostEqual(bb.zmin,20,4);self.assertAlmostEqual(bb.xmin,0,4);self.assertAlmostEqual(bb.ymin,0,4)
        recipe=w.document.info['op'];self.assertEqual(recipe['mode'],'align')
        taller=Body('Wysoki',k.box(10,10,70).translate(cq.Vector(30,0,0)),id=c.id).prepared()   # zmieniona bryła wzorcowa
        again=hist.run_recipe((a,taller),recipe);self.assertAlmostEqual(next(x for x in again if x.id==a.id).shape.BoundingBox().zmax,70,4)
        # w innej płaszczyźnie: ściany boczne (x) - bryła przesuwa się tylko w x
        w.toggle_mode('align');side=w.document.get(a.id)
        self._mate_pick(side,(1,0,0),(10,5,35));self._mate_pick(c,(1,0,0),(40,5,25))
        w.apply_mate();self.wait();bb=w.document.get(a.id).shape.BoundingBox()
        self.assertAlmostEqual(bb.xmax,40,4);self.assertAlmostEqual(bb.zmax,50,4)
        # ta sama bryła dwa razy: druga ściana zmienia tylko ścianę przesuwanej bryły
        w.toggle_mode('mate');self._mate_pick(c,(0,0,1),(35,5,50));self._mate_pick(c,(1,0,0),(40,5,25))
        self.assertNotIn('target',w.mt_pick);self.assertEqual(w.mt_pick['moving']['normal'],(1.0,0.0,0.0))

    def _pick_cyl(self,body,point,hole=False):
        w=self.w
        n=np.array([point[0],point[1],0.0]);n/=np.linalg.norm(n)
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_profile',return_value=None),\
             patch.object(w.view,'pick_face',return_value=(body.id,-n if hole else n,np.array(point,float))):
            w.view_clicked(5,5,False,False)

    def _cyl_radii(self,shape):
        return sorted(round(k.cylinder_info(f,shape)['radius'],4) for f in shape.Faces() if f.geomType()=='CYLINDER')

    def test_extrude_hole_wall_cuts_bigger_or_adds_smaller(self):
        w=self.w
        plate=Body('Płyta',cq.Workplane('XY').box(60,60,10,centered=(True,True,False)).faces('>Z').workplane().hole(20).val()).prepared()
        w.document.commit([plate]);w.refresh();w.set_mode('extrude')
        self._pick_cyl(plate,(10,0,5),True)                                   # ścianka otworu ⌀20
        src=w.ex_profiles[0];self.assertEqual(src['kind'],'cyl');self.assertEqual(src['cyl']['outward'],-1)
        np.testing.assert_allclose(src['normal'],(-1,0,0),atol=1e-9)     # normalna od materiału - do środka otworu
        w.ex_value.setValue(-3);self.assertEqual(w.ex_op.currentData(),'cut')     # do materiału: wycięcie, otwór większy
        self.preview();self.assertTrue(w.view.preview_items)
        w.apply_extrude();self.wait()
        self.assertEqual(self._cyl_radii(w.document.get(plate.id).shape),[13.0])
        recipe=w.document.info['op'];self.assertEqual(recipe['profiles'][0]['k'],'cyl')
        again=hist.run_extrude([plate],recipe);self.assertEqual(self._cyl_radii(next(b for b in again if b.id==plate.id).shape),[13.0])
        w.undo();self.wait()
        w.set_mode('extrude');self._pick_cyl(plate,(0,10,5),True)
        w.ex_value.setValue(4);self.assertEqual(w.ex_op.currentData(),'join')      # od materiału: dodanie, otwór mniejszy
        w.apply_extrude();self.wait()
        self.assertEqual(self._cyl_radii(w.document.get(plate.id).shape),[6.0])
        self.assertEqual(len([b for b in w.document.bodies if b.kind=='solid']),1)

    def _pick_face_at(self,body,face):
        w=self.w;p=face.positionAt(.5,.5);n=np.array(face.normalAt(p).toTuple())
        with patch.object(w,'_region_at',return_value=None),patch.object(w.view,'pick_profile',return_value=None),\
             patch.object(w.view,'pick_face',return_value=(body.id,n,np.array(p.toTuple()))):
            w.view_clicked(5,5,False,False)

    def test_extrude_fillet_face_changes_radius_and_stays_one_body(self):
        w=self.w
        for shape,r,add_r,cut_r in ((cq.Workplane('XY').box(40,40,20,centered=(True,True,False)).edges('|Z').fillet(6).val(),6,3.5858,8.4142),
                                    (cq.Workplane('XY').polyline([(0,0),(40,0),(40,10),(10,10),(10,40),(0,40)]).close().extrude(20)
                                     .edges('|Z').edges(cq.selectors.NearestToPointSelector((10,10,10))).fillet(5).val(),5,7.4142,2.5858),
                                    (cq.Workplane('XY').box(30,30,30).edges('>Z and |X').fillet(4).val(),4,1.5858,6.4142)):
            w.set_mode(None);w.document.commit([]);w.refresh()
            body=Body('Z',shape).prepared();w.document.commit([body]);w.refresh()
            for d,op,want in ((1,'join',add_r),(-1,'cut',cut_r)):
                w.set_mode('extrude');cur=w.document.get(body.id)
                face=min((f for f in cur.shape.Faces() if f.geomType()=='CYLINDER'),key=lambda f:abs(k.cylinder_info(f,cur.shape)['radius']-r))
                self._pick_face_at(cur,face);self.assertTrue(w.ex_profiles[0]['cyl']['fillet'])
                w.ex_value.setValue(d);self.assertEqual(w.ex_op.currentData(),op)
                before=cur.shape.Volume();w.apply_extrude();self.wait()
                solids=[b for b in w.document.bodies if b.kind=='solid'];self.assertEqual(len(solids),1);self.assertEqual(len(solids[0].shape.Solids()),1)
                self.assertIn(round(want,3),[round(x,3) for x in self._cyl_radii(solids[0].shape)])
                self.assertEqual(solids[0].shape.Volume()>before,d>0)
                w.undo();self.wait()
        w.set_mode('extrude');cur=w.document.get(body.id)
        self._pick_face_at(cur,next(f for f in cur.shape.Faces() if f.geomType()=='CYLINDER'))
        w.ex_value.setValue(5);w.apply_extrude();self.wait()          # ponad ostry narożnik: komunikat, bez zmian
        self.assertEqual(len(w.document.bodies),1);self.assertAlmostEqual(w.document.bodies[0].shape.Volume(),cur.shape.Volume(),6)

    def test_extrude_outer_cylinder_grows_or_shrinks(self):
        w=self.w
        rod=Body('Wałek',cq.Workplane('XY').circle(10).extrude(30).val()).prepared()
        w.document.commit([rod]);w.refresh();w.set_mode('extrude')
        self._pick_cyl(rod,(10,0,15))
        self.assertEqual(w.ex_profiles[0]['cyl']['outward'],1)
        w.ex_value.setValue(2.5);self.assertEqual(w.ex_op.currentData(),'join')
        w.apply_extrude();self.wait()
        shape=w.document.get(rod.id).shape;self.assertEqual(self._cyl_radii(shape),[12.5]);self.assertAlmostEqual(shape.BoundingBox().zlen,30,delta=.05)
        w.set_mode('extrude');self._pick_cyl(w.document.get(rod.id),(0,12.5,15))
        w.ex_value.setValue(-6.5);self.assertEqual(w.ex_op.currentData(),'cut')
        w.apply_extrude();self.wait();self.assertEqual(self._cyl_radii(w.document.get(rod.id).shape),[6.0])
        w.set_mode('extrude');self._pick_cyl(w.document.get(rod.id),(6,0,15))
        w.ex_value.setValue(-7);w.apply_extrude();self.wait()                # więcej niż promień: komunikat, model bez zmian
        self.assertEqual(self._cyl_radii(w.document.get(rod.id).shape),[6.0])

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

    def test_boolean_apply_stays_open_for_next_operation(self):
        w=self.w;a,b=self.make_solids()
        c=Body('C',k.box(10,10,10).translate(cq.Vector(15,0,0))).prepared()
        w.document.commit([a,b,c]);w.refresh();w.set_mode('bool')
        w.bool_ids=[a.id,b.id];w.apply_bool();self.wait()
        self.assertEqual(w.mode,'bool');self.assertEqual(w.bool_ids,[a.id])
        w.bool_ids.append(c.id);w.apply_bool();self.wait()
        self.assertEqual(w.mode,'bool');self.assertEqual(w.bool_ids,[a.id])
        self.assertEqual(len(w.document.bodies),1)
        self.assertTrue(w.document.bodies[0].shape.isValid())
        w.set_mode('extrude');self.assertEqual(w.mode,'extrude')

    def test_boolean_whole_group_from_objects_list_becomes_one_solid(self):
        w=self.w
        parts=[Body(f'L{i}',k.box(10,10,10).translate(cq.Vector(8*i,0,0)),folder='Napis').prepared() for i in range(3)]
        other=Body('Inna',k.box(5,5,5).translate(cq.Vector(0,40,0))).prepared()
        w.document.commit([*parts,other]);w.refresh();w.set_mode('bool')
        w.objects_folder_select([p.id for p in parts])
        self.assertEqual(w.mode,'bool')
        self.assertEqual(w.bool_ids,[p.id for p in parts])
        self.assertTrue(all(p.id in w.view.tints for p in parts))
        w.bool_op.setCurrentIndex(0);w.apply_bool();self.wait()
        solids=[b for b in w.document.bodies if b.kind=='solid']
        self.assertEqual(len(solids),2)
        merged=w.document.get(parts[0].id)
        self.assertEqual(merged.folder,'')                       # na liście Obiekty jedna bryła, bez folderu
        self.assertAlmostEqual(merged.shape.Volume(),10*10*26,3)
        w.objects_select(other.id,Qt.NoModifier)                 # klik w pojedynczy obiekt też go dokłada
        self.assertEqual(w.bool_ids,[parts[0].id,other.id])
        w.objects_select(other.id,Qt.NoModifier)
        self.assertEqual(w.bool_ids,[parts[0].id])

    def test_extrude_up_to_target_has_one_recipient_and_replays(self):
        w=self.w
        # Select the destination option immediately before applying the existing two-box fixture.
        apply=w.apply_extrude
        def target_apply():
            self.assertTrue(w.ex_join_scope._buttons[1].isEnabled())
            w.ex_join_scope.setCurrentIndex(1);apply()
        with patch.object(w,'apply_extrude',side_effect=target_apply):
            a,b=self._upto_between_boxes('join')
        self.assertEqual(w.document.info['op']['join_to'],[b.id])
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),8000,3)
        self.assertAlmostEqual(w.document.get(b.id).shape.Volume(),16000,3)
        # A later history insertion must not turn a third body into a recipient.
        c=Body('C',k.box(10,10,10).translate(cq.Vector(25,0,0))).prepared()
        result=hist.run_extrude([a,b,c],w.document.info['op'])
        self.assertEqual(len(result),3)
        self.assertAlmostEqual(next(x for x in result if x.id==c.id).shape.Volume(),1000,3)
        self.assertAlmostEqual(sum(x.shape.Volume() for x in result),25000,3)

    def test_plywood_right_click_cancels_specific_wall_and_reselects_face(self):
        w=self.w
        sk=Body('Szkic',k.sketch('rectangle','XY',100,60),'sketch','XY').prepared()
        base=hist.run_recipe([sk],dict(type='ply_panel',profiles=[{'k':'sketch','id':sk.id}],d=3,t=3,method='laser',spent=[sk.id],out=['base']))[-1]
        w.document.commit([base]);w.refresh();w.set_mode('ply_wall')
        edges=[i for i,e in enumerate(base.shape.Edges()) if abs(e.Center().z-3)<1e-6]
        recipe=dict(type='ply_wall',base=base.id,edges=hist.edge_refs(base.shape,edges),t=3,h=20,side='on',flip=False,method='laser',out=['w1','w2','w3','w4'])
        w.document.commit(hist.run_recipe([base],recipe),op=recipe)
        w.refresh()
        with patch.object(w.view,'pick_body',return_value='w2'):w.context_menu(5,5)
        self.wait();self.assertEqual(w.mode,'ply_wall');self.assertIsNone(w.document.get('w2'))
        self.assertTrue(all(w.document.get(i) is not None for i in ('w1','w3','w4')))
        remaining=w.document.info['op'];self.assertEqual(len(remaining['edges']),3)
        # Two faces of the same body: right-click removes the exact selected face only.
        w.set_mode('ply_between');body=w.document.get(base.id)
        faces=[f for f in body.shape.Faces() if abs(f.normalAt().z)>.99]
        w.pb_faces=[dict(id=body.id,face=f,normal=np.array(f.normalAt().toTuple()),point=np.array(f.Center().toTuple()),name=body.name) for f in faces]
        hit=(body.id,np.array(faces[0].normalAt().toTuple()),np.array(faces[0].Center().toTuple()))
        with patch.object(w.view,'pick_face',return_value=hit):w.context_menu(5,5)
        self.assertEqual(w.mode,'ply_between');self.assertEqual(len(w.pb_faces),1)
        self.assertTrue(w.pb_faces[0]['face'].isSame(faces[1]))
        self.assertFalse(w.view.preview_items)

    def test_fillet_arrow_and_live_preview(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        with patch.object(w.view,'nearest_edge',return_value=(a.id,0)):w.view_clicked(5,5,False,False)
        self.assertEqual(w.edges,{a.id:{0}});self.assertTrue(w.view.handles)
        w.handle_dragged('mod',2.0);self.assertGreater(w.mod_size.value(),3.0);w.handle_released('mod')
        w.mod_size.setValue(2);w.update_mod_preview();self.preview();self.assertTrue(w.view.preview_items,w.mod_status.text())
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
        self.assertEqual(w.mod_vertices,{});self.assertGreaterEqual(len(w.edges[a.id]),4);self.assertFalse(w.view.selection_items)     # ściana się nie podświetla

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
        labels,cur=w.document.timeline();self.assertEqual(cur,len(labels)-1);self.assertTrue(labels[-1].startswith('Wyciągnięcie'));self.assertGreaterEqual(len(labels),3)
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

    def test_history_edit_reopens_the_tool_and_replaces_the_step(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));sk=w.document.bodies[0];w.set_mode('extrude');self.pick_sketch_profile(sk)
        w.ex_value.setValue(5);w.apply_extrude();self.wait()
        self.sketch('rect',(30,0),(40,10));w.set_mode(None)           # krok niezależny od wyciągnięcia
        infos,cur=w.document.infos();ext=2
        self.assertEqual(infos[ext]['op']['type'],'extrude')
        vol=lambda:sum(b.shape.Volume() for b in w.document.bodies if b.kind=='solid')
        self.assertAlmostEqual(vol(),1000,2)
        # dwuklik w krok: model wraca przed krok, otwiera się Wyciągnięcie z wartościami kroku
        w.history_edit(ext)
        self.assertEqual(w.mode,'extrude');self.assertEqual(w.document.infos()[1],ext-1)
        self.assertAlmostEqual(w.ex_value.value(),5);self.assertEqual(w.ex_op.currentData(),'new')
        w.ex_value.setValue(8);w.apply_extrude();self.wait();self.wait()
        infos,cur=w.document.infos()
        self.assertEqual((len(infos),cur),(4,3))                        # ta sama liczba kroków, krok zastąpiony
        self.assertAlmostEqual(vol(),1600,2);self.assertEqual(infos[ext]['op']['d1'],8.0)
        self.assertEqual(len([b for b in w.document.bodies if b.kind=='sketch' and b.visible]),1)    # późniejszy szkic przeniesiony
        self.assertIsNone(w.mode)
        # Zamknij bez Zastosuj: nic się nie zmienia, model wraca na koniec historii
        w.history_edit(ext);w.ex_value.setValue(30);w.set_mode(None);self.app.processEvents();self.wait()
        self.assertEqual(w.document.infos()[1],3);self.assertAlmostEqual(vol(),1600,2);self.assertFalse(w.document.replace_next)
        # krok szkicu: szkic otwiera się z zaznaczonym kształtem, zmiana wymiarów wchodzi do tego kroku
        w.history_edit(1)
        self.assertEqual(w.mode,'sketch');self.assertEqual(w.selected,[sk.id]);self.assertTrue(w.document.merging)
        body=w.document.get(sk.id);meta=sm.apply_values(body.meta,[30,10])
        w._commit_sketch_edit(body,w._meta_shape(body.plane,meta),meta);self.wait()
        self.assertEqual(len(w.document.infos()[0]),4)                  # bez nowego kroku
        w.set_mode(None);self.wait();self.wait()
        infos,cur=w.document.infos();self.assertEqual((len(infos),cur),(4,3))
        self.assertAlmostEqual(vol(),2400,2)                           # wyciągnięcie poszło za nowym rozmiarem szkicu
        self.assertNotIn('op',infos[1])
        self.assertFalse(hasattr(w,'hist_compare') or hasattr(w,'hist_revert') or hasattr(w,'hist_vars') or hasattr(w,'hist_menu_button'))

    def test_undo_redo_revert_history_edits(self):
        w=self.w;self.sketch('rect',(0,0),(20,10));sk=w.document.bodies[0];w.set_mode('extrude');self.pick_sketch_profile(sk)
        w.ex_value.setValue(5);w.apply_extrude();self.wait()
        self.sketch('rect',(30,0),(40,10));w.set_mode(None)
        vol=lambda:sum(b.shape.Volume() for b in w.document.bodies if b.kind=='solid')
        n=len(w.document.infos()[0])
        w.history_edit(2);w.ex_value.setValue(8);w.apply_extrude();self.wait();self.wait()
        self.assertAlmostEqual(vol(),1600,2);self.assertTrue(w.undo_button.isEnabled())
        w.undo();self.wait()                                           # Cofnij: cała historia sprzed edycji kroku
        self.assertAlmostEqual(vol(),1000,2);self.assertEqual(w.document.infos()[0][2]['op']['d1'],5.0);self.assertEqual(len(w.document.infos()[0]),n)
        self.assertEqual(w.document.infos()[1],n-1)
        w.redo();self.wait()                                           # Ponów: wraca wynik edycji
        self.assertAlmostEqual(vol(),1600,2);self.assertEqual(w.document.infos()[0][2]['op']['d1'],8.0)
        w.undo();w.undo();self.wait()                                   # druga strzałka: zwykłe cofnięcie kroku
        self.assertAlmostEqual(vol(),1000,2);self.assertEqual(w.document.infos()[1],n-2)
        w.redo();self.wait()
        # usunięcie kroku też da się cofnąć
        w.history_restructure(lambda st,c,job:hist.delete_step(st,2,c,job));self.wait();self.wait()
        self.assertAlmostEqual(vol(),0,2);self.assertEqual(len(w.document.infos()[0]),n-1)
        w.undo();self.wait();self.assertAlmostEqual(vol(),1000,2);self.assertEqual(len(w.document.infos()[0]),n)
        # zwykły nowy krok po edycji: Cofnij najpierw cofa ten krok, potem edycję
        w.history_edit(2);w.ex_value.setValue(8);w.apply_extrude();self.wait();self.wait()
        self.sketch('rect',(60,0),(70,10));w.set_mode(None)
        w.undo();self.wait();self.assertEqual(len(w.document.infos()[0]),n+1);self.assertAlmostEqual(vol(),1600,2)
        w.undo();self.wait();self.assertAlmostEqual(vol(),1000,2);self.assertEqual(len(w.document.infos()[0]),n)

    def _text_cut_project(self,mode='cut',text='AB'):
        from rccad import history as hist
        w=self.w;self.sketch('rect',(-5,-5),(45,20));sk=w.document.bodies[0];w.set_mode('extrude');self.pick_sketch_profile(sk)
        w.ex_value.setValue(10);w.apply_extrude();self.wait()
        w.set_mode('plane');w.plane_picked('XY');w.choose_tool('text');w.text_edit.setText(text);w.text_size.setValue(10)
        w.txt.update(anchor=(0.0,0.0),size=10.0,angle=0.0);w._text_set_stage('edit');w.apply_text();self.wait();w.set_mode(None);self.wait()
        letters=[b for b in w.document.bodies if hist.text_group_of(b.id)];self.assertTrue(letters)
        key,(plane,bodies)=next((kk,v) for kk,v in w._drawn_sketches().items() if any(hist.text_group_of(b.id) for b in v[1]))
        face=w._regions_for(key,plane,bodies)[0];pt=hist._inner_point(face)
        src=dict(kind='region',id=None,face=face,wire=face.outerWire(),plane=plane,normal=tuple(k.frame_of(plane).normal),center=face.Center().toTuple())
        with patch.object(w.view,'_plane_hit',return_value=(1.0,pt)):out=w._with_letters(src,5,5)
        w.set_mode('extrude')
        with patch.object(w,'_profile_at',return_value=out):w.pick_profile(5,5,False)
        w.ex_op.setCurrentIndex(['new','join','cut','intersect'].index(mode));w.ex_value.setValue(4 if mode=='cut' else -4)
        w.apply_extrude();self.wait();w.set_mode(None)
        self.sketch('rect',(60,0),(70,10));w.set_mode(None)          # dalszy, niezależny krok
        infos=w.document.infos()[0];ti=next(i for i,f in enumerate(infos) if (f.get('op') or {}).get('type')=='text')
        return ti

    def test_history_edit_text_keeps_later_cut_and_join(self):
        for mode in ('cut','join'):
            self.w.document.clear_all();self.w.refresh()
            w=self.w;ti=self._text_cut_project(mode)
            vol=lambda:sum(b.shape.Volume() for b in w.document.bodies if b.kind=='solid')
            v0=vol();self.assertNotAlmostEqual(v0,50*25*10,0)
            w.history_edit(ti);self.assertEqual(w.tool,'text')
            w.text_edit.setText('ABCD');w.apply_text();self.wait();w.set_mode(None);self.wait();self.wait()
            infos,cur=w.document.infos()
            self.assertFalse([f for f in infos if f.get('stale')],mode)
            self.assertEqual(infos[ti]['op']['params']['text'],'ABCD')
            self.assertEqual(cur,len(infos)-1)
            v1=vol();self.assertNotAlmostEqual(v1,v0,0)                      # więcej liter - inna objętość
            self.assertGreater(abs(v1-50*25*10),abs(v0-50*25*10),mode)       # nowy napis nadal wycięty / dodany

    def test_history_edit_fillet_and_boolean_prefill_the_tool(self):
        w=self.w
        a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.box(10,10,40)).prepared()
        w.document.commit([a,b]);w.refresh()
        edge=next(i for i,e in enumerate(a.shape.Edges()) if abs(e.Center().z-20)<1e-6)
        w.set_mode('mod');w.edges={a.id:{edge}};w.mod_size.setValue(2);w.apply_mod();self.wait()
        w.set_mode('bool');w.bool_ids=[a.id,b.id];w.bool_op.setCurrentIndex(1);w.apply_bool();self.wait();w.set_mode(None);self.wait()
        infos,cur=w.document.infos();self.assertEqual([i['op']['type'] for i in infos[2:]],['mod','bool'])
        w.history_edit(2)
        self.assertEqual(w.mode,'mod');self.assertEqual(w.edges,{a.id:{edge}});self.assertAlmostEqual(w.mod_size.value(),2)
        w.mod_size.setValue(4);w.apply_mod();self.wait();self.wait()
        self.assertEqual(w.document.infos()[0][2]['op']['size'],4.0);self.assertEqual(len(w.document.infos()[0]),4)
        self.assertEqual(len([x for x in w.document.bodies if x.kind=='solid']),1)        # Boolean przeliczony na nowym zaokrągleniu
        w.history_edit(3)
        self.assertEqual(w.mode,'bool');self.assertEqual(w.bool_ids,[a.id,b.id]);self.assertEqual(w.bool_op.currentData(),'subtract')
        w.set_mode(None);self.app.processEvents();self.wait()
        self.assertEqual(w.document.infos()[1],3)

    def test_history_edit_opens_for_every_kind_of_step_and_close_changes_nothing(self):
        w=self.w;self.sketch('rect',(0,0),(20,20));sk=w.document.bodies[0];w.set_mode('extrude');self.pick_sketch_profile(sk)
        w.ex_value.setValue(10);w.apply_extrude();self.wait();w.set_mode(None)
        a=next(b for b in w.document.bodies if b.kind=='solid')
        b=Body('B',k.box(5,5,30).translate(cq.Vector(5,5,-5))).prepared();w.document.commit([*w.document.bodies,b]);w.refresh()
        doc=w.document
        def step(op,label):
            doc.commit(list(hist.run_recipe(doc.bodies,op)),label,op=op)
        edge=next(i for i,e in enumerate(a.shape.Edges()) if abs(e.Center().z-10)<1e-6)
        step(dict(type='mod',id=a.id,kind='chamfer',size=1.0,verts=[],vrefs=[],edges=hist.edge_refs(a.shape,{edge})),'Faza')
        step(dict(type='shell',id=a.id,faces=[],thickness=1.0,inward=True),'Skorupa')
        step(dict(type='color',colors={a.id:[1.0,0.0,0.0]}),'Kolor')
        step(dict(type='transform',id=b.id,mode='move',v=(1.0,0.0,0.0)),'Przesunięcie')
        step(dict(type='bool',op='subtract',base=a.id,tools=[b.id]),'Boolean')
        step(dict(type='rename',id=a.id,name='Korpus'),'Nazwa')
        w.refresh()
        infos,last=doc.infos();final=[(x.id,x.shape) for x in doc.bodies]
        for i in range(1,len(infos)):
            kind=(infos[i].get('op') or {}).get('type')
            w.history_edit(i);self.app.processEvents()
            opened=w.mode is not None
            self.assertEqual(opened,kind!='rename',f'krok {i} ({kind}) - okno narzędzia')
            self.assertFalse(hasattr(w,'hist_edit'))                                    # bez zastępczych okien edycji
            w.set_mode(None);self.app.processEvents();self.wait()
            if w.document.infos()[1]!=last:w.history_goto(last);self.wait()
            self.assertEqual(w.document.infos()[1],last,f'krok {i} ({kind})')
            self.assertEqual([(x.id,x.shape) for x in w.document.bodies],final,f'krok {i} ({kind}) zmienił model')
            self.assertFalse(w.document.replace_next or w.document.merging)

    def test_pattern_mirror_split_move_steps_reopen_their_own_tools_prefilled(self):
        w=self.w
        a=Body('A',k.box(10,10,10)).prepared();c=Body('C',k.box(4,4,4).translate(cq.Vector(30,0,0))).prepared()
        w.document.commit([a,c]);w.refresh();doc=w.document
        def step(op,label):
            doc.commit(list(hist.run_recipe(doc.bodies,op)),label,op=op)
        step(dict(type='pattern',id=c.id,kind='rect',params=dict(counts=[3,1,1],spacing=[8.0,10.0,10.0],axes=[[1,0,0],[0,1,0],[0,0,1]]),join=False,out=['p1','p2']),'Szyk')
        step(dict(type='mirror',id=a.id,normal=[1.0,0,0],origin=[-10.0,0,0],keep=True,join=False,out='m1',same_id=True),'Lustro')
        step(dict(type='split',id=a.id,method='plane',plane='XY',normal=[0,0,1.0],origin=[0,0,0],offset=2.0,keep='both',out='s1'),'Przecięcie')
        step(dict(type='transform',id=c.id,mode='move',v=[0.0,5.0,0.0]),'Przesunięcie')
        w.refresh();count=len(doc.infos()[0])
        def edit(i,mode):
            w.history_edit(i);self.app.processEvents()
            self.assertEqual(w.mode,mode,f'krok {i}');self.assertEqual(doc.infos()[1],i-1)
        edit(2,'pattern')
        self.assertEqual(w.pat_id,c.id);self.assertEqual(int(w.pat_counts[0].value()),3);self.assertAlmostEqual(w.pat_gaps[0].value(),8)
        w.pat_counts[0].setValue(4);w.apply_pattern();self.wait();self.wait()
        self.assertEqual(len(doc.infos()[0]),count);self.assertEqual(doc.infos()[0][2]['op']['params']['counts'][0],4)
        edit(3,'mirror')
        self.assertEqual(w.mirror_id,a.id);self.assertTrue(w.mir_keep.isChecked())
        w.mir_keep.setChecked(False);w.apply_mirror();self.wait();self.wait()
        self.assertEqual(len(doc.infos()[0]),count);self.assertFalse(doc.infos()[0][3]['op']['keep'])
        edit(4,'split')
        self.assertEqual(w.sp_id,a.id);self.assertAlmostEqual(w.sp_offset.value(),2.0)
        w.sp_offset.setValue(-1.0);w.apply_split();self.wait();self.wait()
        self.assertEqual(len(doc.infos()[0]),count);self.assertAlmostEqual(doc.infos()[0][4]['op']['offset'],-1.0)
        edit(5,'move')
        self.assertEqual(w.t_target.id,c.id);self.assertAlmostEqual(w.t_spins[1].value(),5.0)
        w.t_spins[1].setValue(9.0);w.apply_transform();self.wait();self.wait()
        infos=doc.infos()[0];self.assertEqual(len(infos),count);self.assertEqual(infos[5]['op']['v'],[0.0,9.0,0.0])
        self.assertFalse(any(i.get('stale') for i in infos))

    def test_taller_extrusion_keeps_hole_from_sketch_on_its_top_face(self):
        w=self.w
        self.sketch('rect',(0,0),(40,20));rect=w.document.bodies[-1];w.set_mode('extrude');self.pick_sketch_profile(rect)
        w.ex_value.setValue(10);w.apply_extrude();self.wait();w.set_mode(None)
        a=next(b for b in w.document.bodies if b.kind=='solid')
        w.set_mode('plane')
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array((0,0,1.0)),np.array((20,10,10.0)))):
            w.view_clicked(5,5,False,False)                                           # szkic na górnej ścianie
        uv=lambda x,y:k.uv_of(w.sketch_plane,(x,y,10))
        w.choose_tool('circle');w.sketch_clicked(w.sketch_plane,*uv(10,10));w.sketch_clicked(w.sketch_plane,*uv(13,10));self.wait()
        circ=w.document.bodies[-1];self.assertEqual(circ.meta['support']['target'],a.id);w.set_mode(None)
        w.set_mode('extrude');self.pick_sketch_profile(circ);w.ex_value.setValue(-5);w.ex_op.setCurrentIndex(2);w.apply_extrude();self.wait();w.set_mode(None)
        E=w.document.get(a.id).shape.Edges();ids={i for i,e in enumerate(E) if abs(e.tangentAt(.5).y)>.9 and e.Center().z>9.9 and abs(e.Center().x-40)<1e-6}
        w.set_mode('mod');w.edges={a.id:ids};w.mod_size.setValue(2);w.apply_mod();self.wait();w.set_mode(None)
        count=len(w.document.infos()[0])
        w.history_edit(2);self.assertEqual(w.mode,'extrude');self.assertAlmostEqual(w.ex_value.value(),10)
        w.ex_value.setValue(20);w.apply_extrude();self.wait();self.wait()
        infos=w.document.infos()[0];self.assertEqual(len(infos),count);self.assertFalse(any(i.get('stale') for i in infos))
        shape=w.document.get(a.id).shape
        self.assertAlmostEqual(k.bounds(shape).zmax,20,4)
        self.assertEqual(k.point_state(shape,(10,10,18)),'out');self.assertEqual(k.point_state(shape,(10,10,8)),'in')    # otwór na nowej górze

    def test_extruding_top_face_early_in_history_keeps_later_work_on_that_face(self):
        """Sześcian, na górnej ścianie: otwór, napis wycięty, zaokrąglone krawędzie. Potem powrót do kroku po wyciągnięciu
        i wyciągnięcie górnej ściany o 5 mm: dalsze kroki idą za nową górą (bez czerwonych kroków)."""
        from rccad import history as hist
        w=self.w
        self.sketch('rect',(0,0),(40,30));rect=w.document.bodies[-1];w.set_mode('extrude');self.pick_sketch_profile(rect)
        w.ex_value.setValue(10);w.apply_extrude();self.wait();w.set_mode(None)
        a=next(b for b in w.document.bodies if b.kind=='solid')
        def top_sketch():
            w.set_mode('plane')
            with patch.object(w.view,'pick_face',return_value=(a.id,np.array((0,0,1.0)),np.array((20,15,10.0)))):
                w.view_clicked(5,5,False,False)
        top_sketch();uv=lambda x,y:k.uv_of(w.sketch_plane,(x,y,10))
        w.choose_tool('circle');w.sketch_clicked(w.sketch_plane,*uv(8,8));w.sketch_clicked(w.sketch_plane,*uv(11,8));self.wait()
        circ=w.document.bodies[-1];w.set_mode(None)
        w.set_mode('extrude');self.pick_sketch_profile(circ);w.ex_value.setValue(-4);w.ex_op.setCurrentIndex(2);w.apply_extrude();self.wait();w.set_mode(None)
        top_sketch();w.choose_tool('text');w.text_edit.setText('AB');w.text_size.setValue(8)
        w.txt.update(anchor=tuple(k.uv_of(w.sketch_plane,(18,12,10))),size=8.0,angle=0.0);w._text_set_stage('edit');w.apply_text();self.wait();w.set_mode(None);self.wait()
        key,(plane,bodies)=next((kk,v) for kk,v in w._drawn_sketches().items() if any(hist.text_group_of(b.id) for b in v[1]))
        face=w._regions_for(key,plane,bodies)[0];pt=hist._inner_point(face)
        src=dict(kind='region',id=None,face=face,wire=face.outerWire(),plane=plane,normal=tuple(k.frame_of(plane).normal),center=face.Center().toTuple())
        with patch.object(w.view,'_plane_hit',return_value=(1.0,pt)):out=w._with_letters(src,5,5)
        w.set_mode('extrude')
        with patch.object(w,'_profile_at',return_value=out):w.pick_profile(5,5,False)
        w.ex_op.setCurrentIndex(2);w.ex_value.setValue(-2);w.apply_extrude();self.wait();w.set_mode(None)
        E=w.document.get(a.id).shape.Edges();ids={i for i,e in enumerate(E) if e.geomType()=='LINE' and e.Center().z>9.9 and (abs(e.Center().x)<1e-6 or abs(e.Center().x-40)<1e-6)}
        self.assertEqual(len(ids),2)
        w.set_mode('mod');w.edges={a.id:ids};w.mod_size.setValue(2);w.apply_mod();self.wait();w.set_mode(None)
        before=w.document.get(a.id).shape.Volume();count=len(w.document.infos()[0])
        self.assertFalse(any(i.get('stale') for i in w.document.infos()[0]))
        # powrót za wyciągnięcie i wyciągnięcie górnej ściany o 5 mm
        w.history_goto(2);self.wait()
        body=w.document.get(a.id);top=next(f for f in body.shape.Faces() if f.normalAt().z>.99)
        sub,others,hole_ids=w._face_with_holes(top,(0,0,1.0),(20,15,10.0))
        src=dict(kind='face',id=a.id,face=sub,whole=top,holes=True,hole_ids=hole_ids,wire=sub.outerWire(),plane=None,normal=(0,0,1.0),
                 center=sub.Center().toTuple(),hit=(20,15,10.0),cluster=(a.id,'top'),sibling=False,siblings=[])
        w.set_mode('extrude')
        with patch.object(w,'_profile_at',return_value=src):w.pick_profile(5,5,False)
        w.ex_op.setCurrentIndex(1);w.ex_value.setValue(5);w.apply_extrude();self.wait();self.wait();self.wait()
        infos=w.document.infos()[0]
        self.assertEqual(len(infos),count+1)
        self.assertFalse([(i['label'],i.get('why')) for i in infos if i.get('stale')])
        shape=w.document.get(a.id).shape
        self.assertAlmostEqual(k.bounds(shape).zmax,15,4)
        self.assertAlmostEqual(shape.Volume(),before+40*30*5,0)                  # otwór, napis i zaokrąglenia przeszły na nową górę
        self.assertEqual(k.point_state(shape,(8,8,13)),'out');self.assertEqual(k.point_state(shape,(8,8,9)),'in')

    def test_project_file_given_at_start_opens(self):
        import tempfile
        w=self.w;a=Body('A',k.box(5,5,5)).prepared();d=Document();d.commit([a])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'Dwuklik.rccadx';d.save(path)
            w.open_path(path);self.wait()
            self.assertEqual(w.document.path,path);self.assertEqual([b.id for b in w.document.bodies],[a.id])
        import main
        self.assertTrue(callable(main.main))

    def test_scale_mate_and_thread_steps_reopen_prefilled(self):
        w=self.w
        a=Body('A',cq.Workplane().box(20,20,10).faces('>Z').workplane().hole(8.5).val()).prepared()
        b=Body('B',k.box(5,5,5).translate(cq.Vector(40,0,0))).prepared()
        w.document.commit([a,b]);w.refresh();doc=w.document
        def step(op,label):
            doc.commit(list(hist.run_recipe(doc.bodies,op)),label,op=op)
        step(dict(type='scale',ids=[b.id],f=[2.0,2.0,2.0],center=[42.5,2.5,2.5]),'Skala')
        bb=doc.get(b.id)
        fa=next(f for f in bb.shape.Faces() if f.normalAt().x<-.9);fb=next(f for f in doc.get(a.id).shape.Faces() if f.normalAt().x>.9)
        step(dict(type='mate',mode='mate',id=b.id,target=a.id,face=hist.face_ref(fa,(-1,0,0),fa.Center().toTuple(),bb.shape),
                  tface=hist.face_ref(fb,(1,0,0),fb.Center().toTuple(),doc.get(a.id).shape)),'Dopasowanie')
        from rccad import threads as th
        info=next(i for i in th.cylinders(doc.get(a.id).shape) if i['internal'])
        std=next(iter(th.STANDARDS));name=th.fit(std,2*info['radius'],True)[0];spec=th.make_thread(info,std,name,'right',info['t0'],info['t1'])
        step(dict(type='thread',items=[dict(id=a.id,cylinder=dict(origin=info['origin'],axis=info['axis'],radius=info['radius'],internal=True),
                  spec=dict(standard=spec['standard'],size=spec['size'],hand='right',start=spec['start'],end=spec['end']),adjust=False)]),'Gwint')
        w.refresh();count=len(doc.infos()[0])
        w.history_edit(2);self.assertEqual(w.mode,'scale');self.assertEqual(w.sc_ids,[b.id]);self.assertAlmostEqual(w.sc_value.value(),200)
        w.sc_value.setValue(150);w.apply_scale();self.wait();self.wait()
        self.assertEqual(len(doc.infos()[0]),count);self.assertEqual(doc.infos()[0][2]['op']['f'],[1.5,1.5,1.5])
        w.history_edit(3);self.assertEqual(w.mode,'mate');self.assertEqual(set(w.mt_pick),{'moving','target'})
        self.assertEqual(w.mt_pick['moving']['id'],b.id);w.set_mode(None);self.app.processEvents();self.wait()
        self.assertEqual(doc.infos()[1],count-1)
        w.history_edit(4);self.assertEqual(w.mode,'thread');self.assertEqual(w.th_pick['id'],a.id);self.assertEqual(w.th_size.currentData(),name)
        w.set_mode(None);self.app.processEvents();self.wait()
        self.assertFalse(any(i.get('stale') for i in doc.infos()[0]))

    def test_delete_and_rename_steps_are_edited_in_place(self):
        w=self.w
        a=Body('A',k.box(5,5,5)).prepared();b=Body('B',k.box(5,5,5).translate(cq.Vector(10,0,0))).prepared();c=Body('C',k.box(5,5,5).translate(cq.Vector(20,0,0))).prepared()
        w.document.commit([a,b,c]);w.refresh();doc=w.document
        w.selected=[b.id];w.delete_selected()
        w.objects_rename(a.id,'Pierwsza');self.wait()
        count=len(doc.infos()[0])
        w.history_edit(2)                                                   # usunięcie: zaznaczone usunięte obiekty, Delete zastępuje krok
        self.assertEqual(doc.infos()[1],1);self.assertEqual(w.selected,[b.id])
        w.selected=[c.id];w.delete_selected();self.wait();self.wait()
        self.assertEqual(len(doc.infos()[0]),count);self.assertEqual(doc.infos()[0][2]['op']['ids'],[c.id])
        self.assertIsNotNone(doc.get(b.id));self.assertIsNone(doc.get(c.id));self.assertEqual(doc.get(a.id).name,'Pierwsza')
        w.history_edit(3)                                                   # zmiana nazwy: pole nazwy na liście Obiekty
        row=w.objects.rows[a.id];self.assertIsNotNone(row.edit)
        row.edit.setText('Druga');row._commit();self.app.processEvents();self.wait();self.wait()
        self.assertEqual(len(doc.infos()[0]),count);self.assertEqual(doc.get(a.id).name,'Druga');self.assertEqual(doc.infos()[0][3]['op']['name'],'Druga')
        w.history_edit(2);ev=QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier);w.keyPressEvent(ev);self.app.processEvents();self.wait()
        self.assertEqual(doc.infos()[1],count-1);self.assertFalse(doc.replace_next)    # Esc: bez zmian

    def test_fillet_meeting_earlier_fillets_is_computed_together_and_chamfer_still_works(self):
        w=self.w
        w.document=Document.load(Path(__file__).parent/'data'/'zaokraglenie.rccadx');w.refresh()      # projekt użytkownika: 3 kroki zaokrągleń r 2
        a=next(b for b in w.document.bodies if b.kind=='solid')
        def blend(at,size,kind):
            body=w.document.get(a.id);E=body.shape.Edges()
            ids={i for i,e in enumerate(E) if e.geomType()=='LINE' and np.allclose(e.Center().toTuple(),at,atol=1e-3)}
            self.assertTrue(ids)
            w.set_mode('mod');w.mod_kind.setCurrentIndex(['fillet','chamfer'].index(kind));w.edges={a.id:ids};w.mod_size.setValue(size)
            w.apply_mod();self.wait();self.wait();w.set_mode(None)
        steps=len(w.document.infos()[0])
        blend((36,-3,0),2.0,'fillet')               # krawędź między zaokrągleniami o tym samym promieniu: osobno się nie da
        infos,cur=w.document.infos()
        self.assertEqual(len(infos),steps-2,[i['label'] for i in infos])         # trzy zaokrąglenia + nowe -> jeden połączony krok na końcu
        self.assertIn('połączone',infos[-1]['label']);self.assertTrue(infos[-1]['op']['groups'])
        body=w.document.get(a.id);self.assertTrue(body.shape.isValid())
        again=hist.run_recipe(w.document.states()[-2][0],infos[-1]['op'])        # krok odtwarza się z przepisu
        self.assertAlmostEqual(next(b for b in again if b.id==a.id).shape.Volume(),body.shape.Volume(),3)
        before=body.shape.Volume()
        blend((-24,-3,28.1),1.0,'chamfer')          # faza krawędzi kończącej się na zaokrągleniach
        self.assertLess(w.document.get(a.id).shape.Volume(),before-1)
        self.assertEqual(w.document.infos()[0][-1]['op']['kind'],'chamfer')

    def test_move_and_rotate_a_whole_square_pocket_by_clicking_one_wall(self):
        w=self.w
        shape=cq.Workplane().box(40,30,10).faces('>Z').workplane().rect(8,6).cutBlind(-4).val()
        a=Body('P',shape).prepared();w.document.commit([a]);w.refresh()
        volume=shape.Volume()
        def click(point,normal):
            with patch.object(w,'pick_object',return_value=a.id),patch.object(w.view,'pick_face',return_value=(a.id,np.array(normal),np.array(point))):
                w.view_clicked(5,5,False,False)
        w.set_mode('move')
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array((0,1,0)),np.array((4,0,3)))):
            w.view_hover(5,5)                                                          # przed kliknięciem otwór się podświetla
        self.assertTrue(w.view.preview_items)
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array((0,0,1)),np.array((15,10,5)))):
            w.view_hover(6,6)
        self.assertFalse(w.view.preview_items)                                         # ściana zewnętrzna - bez podświetlenia
        click((0,-3,3),(0,1,0))                                                        # jedna ściana kieszeni
        self.assertIsNotNone(w.t_feature);self.assertIn('ściany: 5',w.t_status.text())
        w.t_spins[0].setValue(8);w.update_transform_preview();self.assertTrue(w.view.preview_items)
        w.apply_transform();self.wait()
        body=w.document.get(a.id)
        self.assertAlmostEqual(body.shape.Volume(),volume,3)
        self.assertEqual(k.point_state(body.shape,(8,0,3)),'out');self.assertEqual(k.point_state(body.shape,(0,0,3)),'in')   # cała kieszeń przesunięta
        self.assertEqual(w.document.info['op']['type'],'featmove')
        w.set_mode('rotate');click((8,-3,3),(0,1,0))
        w.t_spins[2].setValue(90);w.apply_transform();self.wait()
        body=w.document.get(a.id)
        self.assertAlmostEqual(body.shape.Volume(),volume,3)
        self.assertEqual(k.point_state(body.shape,(8,3.5,3)),'out');self.assertEqual(k.point_state(body.shape,(11.5,0,3)),'in')   # 8 x 6 obrócone o 90°
        w.set_mode('move');click((20,0,0),(1,0,0))                                      # ściana zewnętrzna: cała bryła jak dotąd
        self.assertIsNone(w.t_feature);self.assertEqual(w.t_target.id,a.id)

    def test_changing_existing_things_updates_their_steps_instead_of_adding_duplicates(self):
        """Prostokąt -> wyciągnięcie -> zaokrąglenie krótkich krawędzi -> okrąg -> wycięcie; potem zmiana rozmiaru prostokąta,
        przesunięcie okręgu i mniejsze zaokrąglenie: historia ma dalej te same kroki (bez duplikatów), model jest przeliczony."""
        w=self.w
        self.sketch('rect',(0,0),(40,20));rect=w.document.bodies[-1];w.set_mode('extrude');self.pick_sketch_profile(rect)
        w.ex_value.setValue(10);w.apply_extrude();self.wait();w.set_mode(None)
        a=next(b for b in w.document.bodies if b.kind=='solid')
        E=a.shape.Edges();ids={i for i,e in enumerate(E) if abs(e.tangentAt(.5).y)>.9 and e.Center().z>9.9}
        w.set_mode('mod');w.edges={a.id:ids};w.mod_size.setValue(3);w.apply_mod();self.wait();w.set_mode(None)
        self.sketch('circle',(20,10),(24,10));circ=w.document.bodies[-1];w.set_mode(None)
        w.set_mode('extrude');self.pick_sketch_profile(circ);w.ex_value.setValue(30);w.ex_op.setCurrentIndex(2);w.apply_extrude();self.wait();w.set_mode(None)
        labels=[i['label'] for i in w.document.infos()[0]]
        self.assertEqual(len(labels),6);self.assertEqual(k.point_state(w.document.get(a.id).shape,(20,10,5)),'out')
        solid=lambda:w.document.get(a.id).shape
        # 1. rozmiar prostokąta (uchwyty / Tab): bryła rośnie, kroków tyle samo
        body=w.document.get(rect.id);meta=sm.apply_values(body.meta,[50,20])
        w._commit_sketch_edit(body,w._meta_shape(body.plane,meta),meta);self.wait();self.wait()
        self.assertEqual([i['label'] for i in w.document.infos()[0]],labels)
        self.assertAlmostEqual(k.bounds(solid()).xlen,50,4)
        self.assertFalse(any(i.get('stale') for i in w.document.infos()[0]))
        # 2. przesunięcie okręgu: otwór idzie za nim, kroków tyle samo
        w.set_mode('move');w.select_transform_target(w.document.get(circ.id));w.t_spins[0].setValue(10);w.apply_transform();self.wait();self.wait()
        self.assertEqual([i['label'] for i in w.document.infos()[0]],labels)
        self.assertEqual(k.point_state(solid(),(30,10,5)),'out');self.assertEqual(k.point_state(solid(),(20,10,5)),'in')
        # 3. mniejsze zaokrąglenie: kliknięcie w zaokrąglenie otwiera jego krok, Zastosuj go poprawia
        face=next(f for f in solid().Faces() if f.geomType()=='CYLINDER' and f.Center().z>5 and (f.Center().x<5 or f.Center().x>45))
        w.set_mode('mod')
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=None),\
             patch.object(w.view,'pick_face',return_value=(a.id,None,k._face_point(face))):
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.document.infos()[1],2);self.assertAlmostEqual(w.mod_size.value(),3)
        w.mod_size.setValue(1.5);w.apply_mod();self.wait();self.wait()
        infos=w.document.infos()[0]
        self.assertEqual([i['label'] for i in infos],labels);self.assertEqual(infos[3]['op']['size'],1.5)
        self.assertEqual(k.point_state(solid(),(30,10,5)),'out')                       # przesunięty otwór został
        # 4. dwa przesunięcia bryły po kolei = jeden krok
        for dz in (5,7):
            w.set_mode('move');w.select_transform_target(w.document.get(a.id));w.t_spins[2].setValue(dz);w.apply_transform();self.wait()
        infos=w.document.infos()[0]
        self.assertEqual(len(infos),7);self.assertEqual(infos[-1]['op']['v'],[0.0,0.0,12.0])

    def _holes_with_fillet(self):
        w=self.w
        self.sketch('rect',(0,0),(60,40));base=w.document.bodies[-1];w.set_mode('extrude');self.pick_sketch_profile(base)
        w.ex_value.setValue(10);w.apply_extrude();self.wait();w.set_mode(None)
        a=next(b for b in w.document.bodies if b.kind=='solid')
        self.sketch('rect',(5,15),(21,25));r=w.document.bodies[-1];w.set_mode(None)
        w.set_mode('extrude');self.pick_sketch_profile(r);w.ex_op.setCurrentIndex(2);w.ex_value.setValue(30);w.apply_extrude();self.wait();w.set_mode(None)
        self.sketch('circle',(40,20),(45,20));c=w.document.bodies[-1];w.set_mode(None)
        w.set_mode('extrude');self.pick_sketch_profile(c);w.ex_op.setCurrentIndex(2);w.ex_value.setValue(30);w.apply_extrude();self.wait();w.set_mode(None)
        sh=w.document.get(a.id).shape
        ids={i for i,e in enumerate(sh.Edges()) if e.geomType()=='CIRCLE' and e.Center().z>9.9}
        w.set_mode('mod');w.edges={a.id:ids};w.mod_size.setValue(2);w.apply_mod();self.wait();w.set_mode(None)
        self.assertEqual(w.document.info['op']['type'],'mod')
        return a,c

    def test_moving_filleted_hole_onto_another_drops_the_fillet(self):
        w=self.w;a,c=self._holes_with_fillet()
        n=len(w.document.infos()[0]);filleted=w.document.get(a.id).shape.Volume()
        w.set_mode('move')
        with patch.object(w,'pick_object',return_value=a.id),patch.object(w.view,'pick_face',return_value=(a.id,np.array((-1.0,0,0)),np.array((45.0,20,5)))):
            w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.t_feature)
        w.t_spins[0].setValue(-20);w.apply_transform();self.wait();self.wait()
        infos=w.document.infos()[0]
        self.assertEqual(len(infos),n);self.assertNotIn('mod',[(i.get('op') or {}).get('type') for i in infos])   # krok zaokrąglenia usunięty, doszło przesunięcie
        self.assertEqual(infos[-1]['op']['type'],'featmove');self.assertFalse([i for i in infos if i.get('stale')])
        sh=w.document.get(a.id).shape;self.assertTrue(sh.isValid())
        self.assertEqual(k.point_state(sh,(20,20,5)),'out');self.assertEqual(k.point_state(sh,(40,20,5)),'in')
        w.undo();self.wait()                                                            # jedno Cofnij: zaokrąglenie i otwór wracają
        self.assertEqual(len(w.document.infos()[0]),n);self.assertEqual(w.document.info['op']['type'],'mod')
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),filleted,3)
        # przesunięcie bez kolizji: otwór jedzie razem z zaokrągleniem
        w.set_mode('move')
        with patch.object(w,'pick_object',return_value=a.id),patch.object(w.view,'pick_face',return_value=(a.id,np.array((-1.0,0,0)),np.array((45.0,20,5)))):
            w.view_clicked(5,5,False,False)
        w.t_spins[0].setValue(10);w.apply_transform();self.wait()
        self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),filleted,2)
        self.assertEqual(w.document.info['op']['type'],'featmove')

    def test_moving_hole_sketch_onto_another_drops_unfit_fillet_from_history(self):
        w=self.w;a,c=self._holes_with_fillet()
        n=len(w.document.infos()[0])
        w.set_mode('move');w.select_transform_target(w.document.get(c.id));w.t_spins[0].setValue(-20);w.apply_transform();self.wait();self.wait()
        infos=w.document.infos()[0]
        self.assertFalse([i for i in infos if i.get('stale')],[i.get('why') for i in infos])
        self.assertLessEqual(len(infos),n)
        sh=w.document.get(a.id).shape;self.assertTrue(sh.isValid());self.assertEqual(k.point_state(sh,(20,20,5)),'out')

    def test_repeated_changes_of_one_object_fold_into_its_earlier_step(self):
        w=self.w
        a=Body('A',k.box(10,10,10)).prepared();b=Body('B',k.transform(k.box(10,10,10),(30,0,0))).prepared()
        w.document.commit([a,b]);w.refresh()
        def move(body,dx):
            w.set_mode('move');w.select_transform_target(w.document.get(body.id));w.t_spins[0].setValue(dx);w.apply_transform();self.wait();self.wait()
        move(a,10);move(b,5);move(a,4)                                     # A, B, A: drugi ruch A poprawia pierwszy
        ops=[(i.get('op') or {}) for i in w.document.infos()[0]]
        moves=[o for o in ops if o.get('type')=='transform']
        self.assertEqual(len(moves),2);self.assertEqual(moves[0]['v'],[14.0,0.0,0.0]);self.assertEqual(moves[0]['id'],a.id)
        self.assertAlmostEqual(k.bounds(w.document.get(a.id).shape).xmin,14,5);self.assertAlmostEqual(k.bounds(w.document.get(b.id).shape).xmin,35,5)
        w.undo();self.wait()                                                # Cofnij: A wraca na 10, krok B zostaje
        self.assertAlmostEqual(k.bounds(w.document.get(a.id).shape).xmin,10,5);self.assertAlmostEqual(k.bounds(w.document.get(b.id).shape).xmin,35,5)
        w.redo();self.wait();self.assertAlmostEqual(k.bounds(w.document.get(a.id).shape).xmin,14,5)
        n=len(w.document.infos()[0])
        # nazwa
        self.assertIsNone(w.mode)
        w.objects_rename(a.id,'Pierwsza');self.wait();w.objects_rename(b.id,'Druga');self.wait();w.objects_rename(a.id,'Nowa');self.wait()
        infos=w.document.infos()[0];ren=[i for i in infos if (i.get('op') or {}).get('type')=='rename']
        self.assertEqual(len(ren),2);self.assertEqual(ren[0]['op']['name'],'Nowa');self.assertEqual(w.document.get(a.id).name,'Nowa')
        self.assertIn('Nowa',ren[0]['label'])
        # skala
        w.selected=[];w.toggle_scale(True)
        with patch.object(w,'pick_object',return_value=a.id):w.view_clicked(5,5,False,False)
        w.sc_value.setValue(200);w.apply_scale();self.wait();self.wait()
        w.selected=[];w.toggle_scale(True)
        with patch.object(w,'pick_object',return_value=b.id):w.view_clicked(5,5,False,False)
        w.sc_value.setValue(50);w.apply_scale();self.wait();self.wait()
        w.selected=[];w.toggle_scale(True)
        with patch.object(w,'pick_object',return_value=a.id):w.view_clicked(5,5,False,False)
        w.sc_value.setValue(150);w.apply_scale();self.wait();self.wait()
        sc=[i['op'] for i in w.document.infos()[0] if (i.get('op') or {}).get('type')=='scale']
        self.assertEqual(len(sc),2);self.assertTrue(np.allclose(sc[0]['f'],[3,3,3]))
        self.assertAlmostEqual(k.bounds(w.document.get(a.id).shape).xlen,30,4)
        self.assertFalse([i for i in w.document.infos()[0] if i.get('stale')])

    def test_tilt_face_with_arrows_stretches_the_body_and_close_cancels(self):
        w=self.w
        a=Body('A',k.box(20,10,10)).prepared();w.document.commit([a]);w.refresh()
        self.assertIn('tilt',TABS['Edycja']);w.tools['tilt'].click();self.assertEqual(w.mode,'tilt');self.assertTrue(w.tilt_panel.isVisible())
        top=(10.0,5.0,10.0)
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array((0,0,1.0)),np.array(top))):
            w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.tl_face);self.assertEqual(len([h for h in w.view.handles if h['id'].startswith('tl')]),4)
        w.handle_dragged('tl1',5.0);w.handle_released('tl1')                            # prawy bok w górę o 5 mm
        self.assertAlmostEqual(w.tl_spins[1].value(),5.0);self.assertIn('+14.0°',w.tl_angles.text())
        w._tl_timer.stop();w._tl_preview();self.preview();self.assertTrue(w.view.preview_items)
        steps=w.document.history_length
        w.set_mode(None)                                                                # Zamknij: bez zmian
        self.assertEqual(w.document.history_length,steps);self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),2000,3)
        w.set_mode('tilt')
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array((0,0,1.0)),np.array(top))):
            w.view_clicked(5,5,False,False)
        w.tl_spins[1].setValue(5);w.apply_tilt();self.wait()
        body=w.document.get(a.id)
        self.assertAlmostEqual(body.shape.Volume(),2500,3);self.assertAlmostEqual(k.bounds(body.shape).zmax,15,4)
        self.assertEqual(w.document.info['op']['type'],'tilt');self.assertEqual(w.document.history_length,steps+1)
        w.history_edit(len(w.document.infos()[0])-1)                                    # dwuklik w krok: narzędzie z wartościami
        self.assertEqual(w.mode,'tilt');self.assertAlmostEqual(w.tl_spins[1].value(),5.0)
        w.set_mode(None);self.app.processEvents();self.wait()

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

    # 0.4.63: kilka zaznaczonych - lustro, przecięcie, skorupa i szyk na wszystkich naraz (jeden krok historii)
    def test_operations_apply_to_all_selected(self):
        import cadquery as cq
        from rccad import history as hist
        w=self.w
        a=Body('A',cq.Solid.makeBox(10,10,10)).prepared();b=Body('B',cq.Solid.makeBox(10,10,10,pnt=cq.Vector(20,0,0))).prepared()
        c=Body('C',cq.Solid.makeBox(10,10,10,pnt=cq.Vector(40,0,0))).prepared()
        w.document.commit([a,b,c]);w.refresh()
        w.objects_select(a.id,Qt.NoModifier);w.objects_select(b.id,Qt.ShiftModifier)
        # lustro: zaznaczone przed narzędziem - od razu płaszczyzna; odbija obie
        w.set_mode('mirror');self.assertEqual(w.mirror_id,a.id);self.assertEqual(set(w.view.tints),{a.id,b.id})
        w.mir_keep.setChecked(True)
        with patch.object(w.view,'pick_face',return_value=(c.id,[0,-1,0],[45,0,5])):w.view_clicked(5,5,False,False)
        w.apply_mirror();self.wait()
        self.assertEqual(len(w.document.bodies),5);self.assertEqual(w.document.info['op']['type'],'multi')
        self.assertIn('×2',hist.step_label(w.document.info))
        mirrored=[x for x in w.document.bodies if x.name.endswith('odbicie')]
        self.assertEqual(sorted(round(x.shape.Center().y) for x in mirrored),[-5,-5])
        w.undo();self.wait();self.assertEqual(len(w.document.bodies),3)
        # przecięcie płaszczyzną: każda przez swój środek
        w.objects_select(a.id,Qt.NoModifier);w.objects_select(c.id,Qt.ShiftModifier)
        w.set_mode('split');self.assertEqual(w.sp_id,a.id);self.assertEqual(set(w.view.tints),{a.id,c.id})
        w.apply_split();self.wait()
        self.assertEqual(len(w.document.bodies),5)
        self.assertEqual(sorted(round(x.shape.Volume()) for x in w.document.bodies),[500,500,500,500,1000])
        w.undo();self.wait()
        # skorupa: ta sama grubość, otwarta górna ściana na każdej
        w.objects_select(b.id,Qt.NoModifier);w.objects_select(c.id,Qt.ShiftModifier)
        w.set_mode('shell');self.assertEqual(w.sh_id,b.id);self.assertEqual(set(w.selected),{b.id,c.id})
        with patch.object(w.view,'pick_face',return_value=(b.id,np.array([0,0,1.]),np.array([25,5,10.]))):w.view_clicked(5,5,False,False)
        self.assertIn('+ 1 zaznaczone',w.sh_step1.value.text())
        w.sh_thick.setValue(1);w.apply_shell();self.wait()
        nb,nc=w.document.get(b.id),w.document.get(c.id)
        self.assertAlmostEqual(nb.shape.Volume(),nc.shape.Volume(),3);self.assertLess(nc.shape.Volume(),600)
        self.assertEqual(len(nc.shape.Faces()),len(nb.shape.Faces()))          # obie otwarte od góry
        self.assertEqual(hist.reads(w.document.info['op'],[a,b,c]),{b.id,c.id})
        w.undo();self.wait()
        # szyk: każda zaznaczona dostaje swoje kopie
        w.objects_select(a.id,Qt.NoModifier);w.objects_select(c.id,Qt.ShiftModifier)
        w.set_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=a.id),patch.object(w.view,'nearest_edge',return_value=None):w.view_clicked(5,5,False,False)
        self.assertEqual(set(w.view.tints),{a.id,c.id})
        w.pat_counts[0].setValue(3);w.pat_gaps[0].setValue(0);w.pat_counts[1].setValue(1)
        w.apply_pattern();self.wait()
        self.assertEqual(len(w.document.bodies),7)

    # 0.4.68: Skalowanie - przycisk obok płaszczyzn, cała grupa, różna skala w osiach, szkic z płaszczyzną
    def test_scale_objects_and_sketch(self):
        w=self.w
        a=Body('A',k.box(10,10,10),folder='G').prepared();b=Body('B',k.transform(k.box(10,10,10),(20,0,0)),folder='G').prepared()
        s=Body('S',k.sketch('rectangle','XY',20,10),'sketch','XY').prepared()
        w.document.commit([a,b,s]);w.refresh()
        w.objects_folder_select([a.id,b.id]);w.scale_button.click()
        self.assertEqual(w.mode,'scale');self.assertEqual(sorted(w.sc_ids),sorted([a.id,b.id]))
        w.sc_value.setValue(50);w.sc_anchor.setCurrentIndex(w.sc_anchor.findData('bottom'))
        self.assertIn('30 × 10 × 10 mm  →  15 × 5 × 5 mm',w.sc_size.text())
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier));self.wait()
        bb=k.compound([w.document.get(a.id).shape,w.document.get(b.id).shape]).BoundingBox()
        self.assertAlmostEqual(bb.xlen,15,6);self.assertAlmostEqual(bb.zmin,0,6);self.assertAlmostEqual(bb.zmax,5,6)
        self.assertEqual(w.document.info['op']['type'],'scale');self.assertIsNone(w.mode);self.assertFalse(w.scale_button.isChecked())
        w.selected=[];w.toggle_scale(True)
        with patch.object(w,'pick_object',return_value=s.id):w.view_clicked(5,5,False,False)
        w.sc_axes.setChecked(True);w.sc_xyz[0].setValue(50);w.sc_xyz[1].setValue(300);w.apply_scale();self.wait()
        bb=w.document.get(s.id).shape.BoundingBox();self.assertAlmostEqual(bb.xlen,10,5);self.assertAlmostEqual(bb.ylen,30,5)
        self.assertEqual(w.document.get(s.id).plane,'XY')
        w.undo();self.wait();self.assertAlmostEqual(w.document.get(s.id).shape.BoundingBox().xlen,20,5)

    # 0.4.69: Skalowanie - strzałka do przeciągania (jedna albo trzy - osie), pola osi mieszczą się w panelu
    def test_scale_handles_drag(self):
        w=self.w;a=Body('A',k.box(10,10,10)).prepared();w.document.commit([a]);w.refresh()
        w.selected=[a.id];w.toggle_scale(True)
        self.assertEqual([h['id'] for h in w.view.handles],['scA'])
        w.handle_dragged('scA',float(np.linalg.norm([5,5,5])));w.handle_released('scA')     # róg o połowę przekątnej dalej
        self.assertAlmostEqual(w.sc_value.value(),200,1)
        w.sc_axes.setChecked(True);self.app.processEvents()
        self.assertEqual(sorted(h['id'] for h in w.view.handles),['scX','scY','scZ'])
        w.handle_dragged('scX',-2.5);w.handle_released('scX')                               # połowa wymiaru od środka: 5 mm
        self.assertAlmostEqual(w.sc_xyz[0].value(),150,1)
        spin=w.sc_xyz[2];self.assertLessEqual(spin.mapTo(w.scale_panel,spin.rect().topRight()).x(),w.scale_panel.width())   # nie ucięte z prawej
        w.apply_scale();self.wait()
        bb=w.document.get(a.id).shape.BoundingBox();self.assertAlmostEqual(bb.xlen,15,4);self.assertAlmostEqual(bb.ylen,20,4)

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

    def test_extrude_arrow_follows_last_clicked_profile_including_group_and_deselect(self):
        w=self.w
        bodies=[Body(str(i),k.sketch('circle','XY',6,x=i*30),kind='sketch').prepared() for i in range(3)]
        w.document.commit(bodies);w.selected=[];w.refresh();w.set_mode('extrude')
        a,b,c=[w._sketch_profile(body) for body in bodies]
        b=dict(b,cluster=('group','B'),siblings=[dict(c,cluster=('group','B'))])
        with patch.object(w,'update_extrude_preview',side_effect=w._place_extrude_handle):
            for src in (a,b):
                with patch.object(w,'_profile_at',return_value=src):w.pick_profile(5,5)
                np.testing.assert_allclose(w.view.handles[0]['start'],src['center'])
            self.assertEqual(len(w.ex_profiles),3)
            with patch.object(w,'_profile_at',return_value=b):w.pick_profile(5,5,True)
            np.testing.assert_allclose(w.view.handles[0]['start'],a['center'])
        w._timers['extrude'].stop()

    def test_fillet_chamfer_arrow_tracks_click_order_across_edges_bodies_and_vertices(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.box(20,20,20).translate((60,0,0))).prepared()
        w.document.commit([a,b]);w.selected=[];w.refresh();w.set_mode('mod')
        for body,index in ((a,10),(b,4),(a,0)):
            w._mod_select(body.id,{index},False,False,mark=index);w._timers['mod'].stop()
            np.testing.assert_allclose(w.view.handles[0]['start'],k.edge_handle(body.shape,index)[0])
        point=np.array([60.,0.,0.]);w._mod_vertex_select(b.id,point,False,False);w._timers['mod'].stop()
        np.testing.assert_allclose(w.view.handles[0]['start'],k.vertex_handle(b.shape,point)[0])
        w._mod_vertex_select(b.id,point,True,False);w._timers['mod'].stop()
        np.testing.assert_allclose(w.view.handles[0]['start'],k.edge_handle(a.shape,0)[0])
        w._mod_select(a.id,{0},True,False);w._timers['mod'].stop()
        np.testing.assert_allclose(w.view.handles[0]['start'],k.edge_handle(b.shape,4)[0])
        w.mod_kind.setCurrentIndex(1);w._place_mod_handle();w._timers['mod'].stop()
        np.testing.assert_allclose(w.view.handles[0]['start'],k.edge_handle(b.shape,4)[0])

    def test_late_profile_highlight_cannot_restore_removed_or_replaced_selection(self):
        w=self.w;w.selected=[];w.set_mode('extrude')
        profiles=[w._sketch_profile(Body(str(i),k.sketch('circle','XY',2,x=i*4),kind='sketch').prepared()) for i in range(12)]
        w.ex_profiles=profiles;callbacks=[]
        with patch.object(w,'run_preview',side_effect=lambda key,compute,show:callbacks.append(show)):
            w._mark_profiles()
        mesh=k.display_mesh(profiles[0]['wire'])
        w.ex_profiles=[];w.view.set_selection_meshes(None);callbacks[0](mesh,None)
        self.assertFalse(w.view.selection_items)
        w.ex_profiles=[profiles[-1]];w._mark_profiles();current=list(w.view.selection_items)
        callbacks[0](mesh,None)
        self.assertEqual(current,w.view.selection_items)

    def test_move_and_scale_arrows_start_at_last_selected_object(self):
        w=self.w;a=Body('A',k.box(10,10,10)).prepared();b=Body('B',k.box(10,10,10).translate((40,0,0))).prepared()
        w.document.commit([a,b]);w.refresh();w.selected=[b.id,a.id];w.set_mode('move')
        self.assertEqual(w.t_target.id,a.id)
        np.testing.assert_allclose(w.view.handles[0]['start'],a.mesh.center)
        with patch.object(w,'pick_object',return_value=b.id):w.pick_transform_target(5,5)
        np.testing.assert_allclose(w.view.handles[0]['start'],b.mesh.center)
        w.set_mode(None);w.selected=[b.id,a.id];w.toggle_scale(True)
        handle=next(h for h in w.view.handles if h['id']=='scA')
        np.testing.assert_allclose(handle['start'],[10,10,10])
        w._sc_set([a.id,b.id]);handle=next(h for h in w.view.handles if h['id']=='scA')
        np.testing.assert_allclose(handle['start'],[50,10,10])

    def test_section_material_can_define_an_internal_sketch_plane_without_fake_cad_faces(self):
        from PySide6.QtGui import QVector3D
        w=self.w;body=Body('Solid',k.box(80,60,40)).prepared();w.document.commit([body]);w.selected=[];w.refresh()
        w.view.opts['center']=QVector3D(40,30,20);w.view.setCameraPosition(distance=200,elevation=0,azimuth=-90)
        w.view.set_section_plane([0,1,0,-25]);xy=w.view.project_one((40,25,20))
        self.assertIsNone(w.view.pick_face(*xy))
        plane,face=w.pick_surface(*xy);self.assertIsNone(face);self.assertIsNotNone(plane)
        self.assertAlmostEqual(plane.origin[1],25,4)
        w.enter_sketch(plane);w.choose_tool('rect');w.sketch_clicked(plane,-2,-2);w.sketch_clicked(plane,2,2);self.wait()
        sketch=next(b for b in w.document.bodies if b.kind=='sketch')
        cutter=k.extrude_dir(sketch.shape,k.frame_of(plane).normal,4)
        self.assertAlmostEqual(body.shape.Volume()-k.boolean('subtract',body.shape,[cutter]).Volume(),64,4)

    def test_first_pattern_click_waits_without_blocking_and_keeps_world_selection(self):
        from PySide6.QtGui import QVector3D
        from threading import Event
        import cadquery as cq
        w=self.w;plane=k.Frame((0,0,10),(1,0,0),(0,0,1));base=Body('P',k.box(100,100,10)).prepared()
        sketches=[Body(str(i),cq.Wire.makeCircle(1,cq.Vector(5+i%10*7,5+i//10*7,10),cq.Vector(0,0,1)),kind='sketch',plane=plane,group='p').prepared() for i in range(30)]
        w.document.commit([base,*sketches]);w.selected=[];w.refresh();w.set_mode('extrude')
        w.view.opts['center']=QVector3D(50,50,5);w.view.setCameraPosition(distance=200,elevation=90,azimuth=-90)
        data=hist.prepare_sketch_regions(hist.light(w.document.bodies));gate=Event()
        from rccad import workers
        def call(function,*args):
            if function is hist.prepare_sketch_regions:gate.wait(5);return data
            return function(*args)
        with patch.object(workers,'ready',return_value=True),patch.object(workers,'call_any',side_effect=call),patch.object(w,'update_extrude_preview',side_effect=w._place_extrude_handle):
            w._prefetch_sketch_regions();xy=w.view.project_one((5,5,10));w.pick_profile(*xy)
            self.assertFalse(w.ex_profiles);self.assertEqual(len(w._pending_profile_picks),1)
            w.view.orbit(25,10);gate.set();end=time.monotonic()+10
            while w._sketch_regions_running and time.monotonic()<end:self.app.processEvents();time.sleep(.005)
            self.assertFalse(w._sketch_regions_running);self.assertEqual(len(w.ex_profiles),30)
            np.testing.assert_allclose(w.view.handles[0]['start'],[5,5,10],atol=1e-5)
            self.preview()
        w._timers['extrude'].stop()

    def test_pattern_region_selection_skips_support_face_boolean_and_reuses_group(self):
        from PySide6.QtGui import QVector3D
        import cadquery as cq
        w=self.w;plane=k.Frame((0,0,10),(1,0,0),(0,0,1));base=Body('Plate',k.box(100,100,10)).prepared()
        sketches=[Body(str(i),cq.Wire.makeCircle(1,cq.Vector(5+i%10*7,5+i//10*7,10),cq.Vector(0,0,1)),kind='sketch',plane=plane,group='pattern').prepared() for i in range(100)]
        w.document.commit([base,*sketches]);w.refresh();w.view.opts['center']=QVector3D(50,50,5);w.view.setCameraPosition(distance=200,elevation=90,azimuth=-90)
        xy=w.view.project_one((5,5,10))
        with patch.object(w,'_face_with_holes',side_effect=AssertionError('support face Boolean during profile selection')):
            first=w._profile_at(*xy);again=w._profile_at(*xy)
        self.assertIs(first,again);profiles=[first,*first['siblings']];self.assertEqual(len(profiles),100)
        with patch.object(k,'bounds',side_effect=AssertionError('quadratic sketch bounds scan')):
            self.assertEqual(w._consumed_sketches(profiles),{b.id for b in sketches})
        specs=hist.describe_profiles(profiles,[base,*sketches])
        self.assertEqual({spec['anchor']['id'] for spec in specs},{b.id for b in sketches})

    def test_section_inside_floor_accepts_sketch_and_cut_after_opening_material(self):
        from PySide6.QtGui import QVector3D
        w=self.w;shape=k.box(80,60,60).cut(k.box(60,40,60).translate((10,10,8))).fuse(k.box(10,20,40).translate((50,10,8))).clean()
        body=Body('Open box',shape).prepared();w.document.commit([body]);w.selected=[];w.refresh()
        w.view.opts['center']=QVector3D(40,30,30);w.view.setCameraPosition(distance=200,elevation=25,azimuth=-65)
        w.view.set_section_plane([0,1,0,-25]);xy=w.view.project_one((20,32,8))
        plane,face=w.pick_surface(*xy);self.assertIsNotNone(face)
        self.assertAlmostEqual(face.Center().z,8,5)
        w.enter_sketch(plane);w.choose_tool('rect');u,v=k.uv_of(plane,[20,32,8])
        w.sketch_clicked(plane,u-2,v-2);w.sketch_clicked(plane,u+2,v+2);self.wait()
        sketch=next(b for b in w.document.bodies if b.kind=='sketch')
        cutter=k.extrude_dir(sketch.shape,k.frame_of(plane).normal,-4)
        result=k.boolean('subtract',body.shape,[cutter])
        self.assertAlmostEqual(body.shape.Volume()-result.Volume(),64,4)
        self.assertIsNotNone(w.view.section_plane)

    def test_measure_does_not_create_geometry(self):
        self.sketch('measure',(0,0),(3,4));self.assertEqual(len(self.w.document.bodies),0);self.assertIn('5,000',self.w.notice.text())

    def test_trim_removes_clicked_segment(self):
        self.sketch('rect',(0,0),(10,10));w=self.w;w.choose_tool('trim');body=w.document.bodies[0]
        pieces=k.trim_pieces([body.shape.Edges()],0)
        with patch.object(w,'_trim_target',return_value=(body,pieces,0)):w.sketch_clicked('XY',0,0)
        self.wait();self.assertFalse(w.document.bodies[0].shape.IsClosed())

    def test_sketch_offset_panel_side_value_and_arrow(self):
        self.sketch('rect',(0,0),(20,10));w=self.w;src=w.document.bodies[0]
        w.choose_tool('offset');self.assertTrue(w.off_panel.isVisible())
        with patch.object(w,'_off_body_at_cursor',return_value=(src,(20.0,5.0,0.0))):w.sketch_clicked('XY',20,5)
        self.assertIsNotNone(w.off);np.testing.assert_allclose(w.off['dir'],(1,0,0),atol=1e-9)
        w.off_value.setValue(3)
        h=w.view.handles[0];self.assertEqual(h['id'],'off');np.testing.assert_allclose(h['tip'],(23,5,0),atol=1e-9)
        self.assertTrue(w.view.preview_items)
        w.handle_dragged('off',-5);w.handle_released('off')      # przez kształt do środka: 3 - 5 = -2
        self.assertEqual(w.off_side.currentData(),'in');self.assertAlmostEqual(w.off_value.value(),2)
        np.testing.assert_allclose(w.view.handles[0]['tip'],(18,5,0),atol=1e-9)
        w.apply_offset();self.wait()
        self.assertEqual(len(w.document.bodies),2);new=w.document.bodies[1]
        bb=new.shape.BoundingBox();self.assertAlmostEqual(bb.xlen,16,6);self.assertAlmostEqual(bb.ylen,6,6);self.assertTrue(new.shape.IsClosed())
        self.assertIsNone(w.off);self.assertEqual(w.view.handles,[])
        w.choose_tool('offset')
        with patch.object(w,'_off_body_at_cursor',return_value=(src,(0.0,5.0,0.0))):w.sketch_clicked('XY',0,5)
        w.off_side.setCurrentIndex(w.off_side._data.index('out'));w.off_value.setValue(1.5)
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier));self.wait()
        bb=w.document.bodies[2].shape.BoundingBox();self.assertAlmostEqual(bb.xlen,23,6);self.assertAlmostEqual(bb.ylen,13,6)
        with patch.object(w,'_off_body_at_cursor',return_value=(src,(0.0,5.0,0.0))):w.sketch_clicked('XY',0,5)
        w.off_side.setCurrentIndex(w.off_side._data.index('in'));w.off_value.setValue(6)
        self.assertIn('większy',w.off_status.text());w.apply_offset();self.wait();self.assertEqual(len(w.document.bodies),3)
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));self.assertIsNone(w.off);self.assertEqual(w.mode,'sketch')

    # 0.4.65: szkic dokładnie po obrysie ściany bryły - ofset wybiera linię szkicu, nie krawędź bryły
    def test_sketch_offset_on_face_outline(self):
        from PySide6.QtCore import QPoint
        w=self.w;box=Body('B',k.box(40,30,10)).prepared();fr=k.face_frame((20,15,10),(0,0,1))
        sk=Body('Szkic',k.sketch('rectangle',fr,40,30),'sketch',fr).prepared()
        w.document.commit([box,sk]);w.refresh();w.set_mode('sketch');w.sketch_plane=k.face_frame((5,5,10),(0,0,1));w.choose_tool('offset')
        for _ in range(5):self.app.processEvents()
        xy=w.view.project_one((20,0,10))
        self.assertEqual(w.view.nearest_edge(*xy)[0],box.id)                      # krawędź bryły leży w tym samym miejscu
        with patch('rccad.studio.QCursor.pos',return_value=w.view.mapToGlobal(QPoint(int(xy[0]),int(xy[1])))):
            w.sketch_clicked(fr,0,-15)
        self.assertIsNotNone(w.off);self.assertEqual(w.off['id'],sk.id)
        w.off_side.setCurrentIndex(w.off_side._data.index('in'));w.off_value.setValue(3);w.apply_offset();self.wait()
        bb=w.document.bodies[-1].shape.BoundingBox();self.assertAlmostEqual(bb.xlen,34,6);self.assertAlmostEqual(bb.ylen,24,6);self.assertAlmostEqual(bb.zmin,10,6)

    # 0.4.65: nowa grupa na liście Obiekty pojawia się zwinięta
    def test_new_object_group_starts_collapsed(self):
        w=self.w;a=Body('A',k.box(5,5,5)).prepared();b=Body('B',k.box(5,5,5)).prepared();c=Body('C',k.box(5,5,5)).prepared()
        w.document.commit([a,b,c]);w.refresh();self.app.processEvents()
        w.objects_select(a.id,Qt.NoModifier);w.objects_select(b.id,Qt.ShiftModifier)
        w.objects_folder_new([a.id,b.id]);self.wait();self.app.processEvents()
        self.assertNotIn(a.id,w.objects.rows);self.assertIn(c.id,w.objects.rows)            # zwinięta: wiersze w środku ukryte
        key=next(k2 for k2 in w.objects._folded if k2.endswith(':Grupa 1'))
        w.objects._fold(key);self.app.processEvents()
        self.assertIn(a.id,w.objects.rows)                                                   # strzałka rozwija

    def test_sketch_offset_circle_on_xz(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XZ');w.choose_tool('circle');w.sketch_clicked('XZ',10,6);w.sketch_clicked('XZ',15,6);self.wait()
        src=w.document.bodies[0];w.choose_tool('offset')
        with patch.object(w,'_off_body_at_cursor',return_value=(src,k.to_world('XZ',13,10))):w.sketch_clicked('XZ',13,10)
        np.testing.assert_allclose(w.off['base'],k.to_world('XZ',13,10),atol=1e-6)
        np.testing.assert_allclose(w.off['dir'],(np.array(k.to_world('XZ',13,10))-k.to_world('XZ',10,6))/5,atol=1e-6)
        for value,side,size in ((2,'out',14),(1.5,'in',7)):        # okrąg poza środkiem układu: ofset współśrodkowy (był przesunięty o drugie tyle)
            w.choose_tool('offset')
            with patch.object(w,'_off_body_at_cursor',return_value=(src,k.to_world('XZ',13,10))):w.sketch_clicked('XZ',13,10)
            w.off_side.setCurrentIndex(w.off_side._data.index(side));w.off_value.setValue(value);w.apply_offset();self.wait()
            bb=w.document.bodies[-1].shape.BoundingBox();c=bb.center.toTuple()
            self.assertAlmostEqual(bb.xlen,size,5);self.assertAlmostEqual(bb.zlen,size,5);self.assertAlmostEqual(bb.ylen,0,6)
            np.testing.assert_allclose(c,k.to_world('XZ',10,6),atol=1e-6)

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
        letters=[b for b in w.document.bodies if b.name.startswith('Tekst')]
        self.assertTrue(letters);self.assertEqual({b.folder for b in letters},{'Tekst „Tekst”'})   # napis od razu jako grupa
        count=len(infos)
        w.set_mode(None);w.history_edit(cur)                                             # dwuklik w krok: narzędzie Tekst z treścią kroku
        self.assertEqual((w.mode,w.tool),('sketch','text'));self.assertEqual(w.text_edit.text(),'Tekst');self.assertEqual(w.txt['stage'],'edit')
        w.text_edit.setText('Xy');w.txt['size']=7.0;w.apply_text();self.wait();self.wait()
        infos=w.document.infos()[0];self.assertEqual(len(infos),count)                   # krok zastąpiony, nie dodany
        self.assertEqual(infos[-1]['op']['params']['text'],'Xy');self.assertEqual(infos[-1]['op']['params']['size'],7)

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

    def _dwell_clock(self):
        from rccad import snap as snapping
        now=[100.0];self.w._dwell=snapping.Dwell(clock=lambda:now[0])
        self.w._dwell_timer=__import__('PySide6.QtCore',fromlist=['QTimer']).QTimer(self.w);self.w._dwell_timer.setSingleShot(True)
        return now

    def test_snap_to_existing_sketch_corner(self):
        w=self.w;self.sketch('rect',(0,0),(10,10));w.choose_tool('line');now=self._dwell_clock()
        x,y=w.view.project_one(k.to_world('XY',10,10))
        u,v,label=w._snapper(x+3,y+2,(10.4,10.3));self.assertIsNone(label);self.assertAlmostEqual(u,10.4,6)      # w ruchu: bez przyklejania
        self.assertTrue(w._dwell_timer.isActive())                                                                  # odczeka i sprawdzi ponownie
        now[0]+=.3
        u,v,label=w._snapper(x+3,y+2,(10.4,10.3));self.assertEqual(label,'Punkt styku');self.assertAlmostEqual(u,10,3);self.assertAlmostEqual(v,10,3)
        u,v,label=w._snapper(x+5,y+1,(10.6,10.1));self.assertEqual(label,'Punkt styku')                           # drżenie ręki nie gubi punktu
        u,v,label=w._snapper(x+60,y+60,(14.3,3.9));self.assertIsNone(label);self.assertAlmostEqual(u,14.3,6)      # z dala: kursor wolny
        w.view.set_marker(k.to_world('XY',10,10),label='Punkt styku');self.assertIsNotNone(w.view.snap_marker)

    def test_sketch_on_face_shows_axes_cross_and_arrows_pan_view(self):
        w=self.w;box=Body('Kostka',k.box(30,20,10)).prepared();w.document.commit([box]);w.refresh()
        top=next(f for f in box.shape.Faces() if f.normalAt().z>.99)
        w.enter_sketch(k.face_frame(top.Center().toTuple(),(0,0,1)))
        self.assertEqual(len(w.view.sketch_axis_items),2)
        for item in w.view.sketch_axis_items:      # krzyż przechodzi przez środek ścianki
            a,b=item.pos[0],item.pos[1];mid=(a+b)/2
            self.assertAlmostEqual(float(mid[0]),15,3);self.assertAlmostEqual(float(mid[1]),10,3)
        before=w.view.opts['center'];before=(before.x(),before.y(),before.z())
        w.view.setFocus();ev=QKeyEvent(QEvent.KeyPress,Qt.Key_Right,Qt.NoModifier);QApplication.sendEvent(w.view,ev)
        after=w.view.opts['center'];self.assertNotEqual(before,(after.x(),after.y(),after.z()))
        c1=w.view.opts['center'];c1=(c1.x(),c1.y(),c1.z())
        ev=QKeyEvent(QEvent.KeyPress,Qt.Key_Up,Qt.KeypadModifier);w.keyPressEvent(ev)       # blok numeryczny, okno główne
        c2=w.view.opts['center'];self.assertNotEqual(c1,(c2.x(),c2.y(),c2.z()))
        self.assertTrue(all(not item.visible() for item,_ in w.view.axis_lines))      # główny krzyż w tle ukryty
        w.view.update();self.assertTrue(all(not item.visible() for item,_ in w.view.axis_lines))
        w.set_mode(None);self.assertEqual(w.view.sketch_axis_items,[])        # po wyjściu ze szkicu krzyż znika
        w.view.setCameraPosition(elevation=25,azimuth=-55);w.view.update()
        self.assertTrue(all(item.visible() for item,_ in w.view.axis_lines))          # a główny wraca
        w.enter_sketch('XY');self.assertEqual(w.view.sketch_axis_items,[])   # płaszczyzna główna ma własne osie
        self.assertTrue(any(item.visible() for item,_ in w.view.axis_lines))

    def test_snap_to_grid_corner_and_face_corner_after_dwell(self):
        from rccad import snap as snapping
        w=self.w;box=Body('Kostka',k.box(20,20,20)).prepared();w.document.commit([box]);w.refresh()
        top=next(f for f in box.shape.Faces() if f.normalAt().z>.99)
        w.enter_sketch(k.face_frame(top.Center().toTuple(),(0,0,1)));w.choose_tool('line');now=self._dwell_clock()
        geo=snapping.SketchGeometry(w.document.bodies,w.sketch_plane)
        self.assertIn('Narożnik',geo.pt_label);self.assertIn('Krawędź ściany',geo.seg_label)
        x,y=w.view.project_one((20.0,20.0,20.0));raw=k.uv_of(w.sketch_plane,(19.7,19.8,20.0))
        w._snapper(x+2,y+1,raw);now[0]+=.3
        u,v,label=w._snapper(x+2,y+1,raw);self.assertEqual(label,'Narożnik')
        self.assertAlmostEqual(k.to_world(w.sketch_plane,u,v)[0],20,3);self.assertAlmostEqual(k.to_world(w.sketch_plane,u,v)[1],20,3)
        step=snapping.grid_step(w.view,geo);gx,gy=w.view.project_one(k.to_world(w.sketch_plane,-3*step,-2*step))
        c=snapping.candidate(w.view,geo,gx+1,gy+1,(-3*step+.01*step,-2*step+.01*step))
        self.assertEqual(c[2],'Siatka');self.assertAlmostEqual(c[0],-3*step,6);self.assertAlmostEqual(c[1],-2*step,6)

    def test_grid_snap_uses_visible_grid_corners_and_centers_at_5mm(self):
        from rccad import snap as snapping
        w=self.w;w.enter_sketch('XY');w.choose_tool('line')
        for distance in (40,120,400):                     # różne powiększenia, w tym kratka 5 x 5 mm
            w.view.setCameraPosition(distance=distance);w.view.update();self.app.processEvents()
            geo=snapping.SketchGeometry(w.document.bodies,w.sketch_plane)
            step=snapping.grid_step(w.view,geo);self.assertEqual(step,w.view.grid_spacing)      # dokładnie kratka z widoku
            for target,label in (((3*step,2*step),'Siatka'),((3.5*step,2.5*step),'Środek kratki')):
                gx,gy=w.view.project_one(k.to_world('XY',*target))
                c=snapping.candidate(w.view,geo,gx+1,gy+1,(target[0]+.03*step,target[1]+.03*step))
                self.assertIsNotNone(c,(distance,step,label));self.assertEqual(c[2],label)
                self.assertAlmostEqual(c[0],target[0],6);self.assertAlmostEqual(c[1],target[1],6)
        w.view.setCameraPosition(distance=250);w.view.update();self.app.processEvents()
        self.assertEqual(w.view.grid_spacing,5)

    def test_line_straightens_to_horizontal_vertical_and_45_and_turns_red(self):
        w=self.w;w.enter_sketch('XY');w.choose_tool('line')
        w.sketch_clicked('XY',0.0,0.0)
        far=lambda raw:w._snapper(-500,-500,raw)                       # kursor daleko od siatki i punktów
        u,v,label=far((20.0,0.9));self.assertEqual((round(u,6),round(v,6),label),(20.0,0.0,'Poziomo'))
        u,v,label=far((-0.8,15.0));self.assertEqual((round(u,6),round(v,6),label),(0.0,15.0,'Pionowo'))
        u,v,label=far((10.5,10.0));self.assertEqual(label,'45°');self.assertAlmostEqual(u,v,6)
        self.assertEqual(w._line_aligned,'45°')                           # podgląd linii czerwony
        with patch.object(w.view,'set_preview_mesh') as shown:
            w.sketch_moved('XY',u,v);self.assertEqual(shown.call_args.kwargs['line_color'][:3],(.92,.12,.12))
        u,v,label=far((20.0,5.0));self.assertIsNone(label);self.assertEqual((u,v),(20.0,5.0))        # dalej od kąta: swobodnie
        self.assertIsNone(w._line_aligned)
        end=far((20.0,0.7))[:2];w.sketch_clicked('XY',*end);w.sketch_clicked('XY',*end);self.wait()
        line=w.document.bodies[-1];bb=k.bounds(line.shape);self.assertAlmostEqual(bb.ylen,0,6);self.assertAlmostEqual(bb.xlen,20,6)

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
        w.set_mode('plane');w.plane_picked('XY');w.choose_tool('polygon');w.sides=6;w.sketch_clicked('XY',0,0)   # liczba kątów z paska kształtów
        self.assertTrue(w.open_dim_input());self.assertEqual([w.dim_labels[i].text() for i in range(2)],['Promień (mm)','Obrót (°)'])
        w.dim_edits[0].setText('10');w.dim_edits[1].setText('0');w.apply_typed();self.wait()
        self.assertEqual(w.document.bodies[-1].meta['sides'],6);self.assertEqual(len(w.document.bodies[-1].shape.Edges()),6)
        self.assertAlmostEqual(k.bounds(w.document.bodies[-1].shape).ymax,10,4)          # obrót 0°: wierzchołek u góry
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):w.clear_all()
        self.assertEqual(len(w.document.bodies),0)
        labels,cur=w.document.timeline();self.assertEqual((len(labels),cur),(1,0))       # czyszczenie usuwa też historię
        self.assertFalse(w.document.can_undo or w.document.can_redo or w.document.constraints)
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

    def test_hover_cursor_snaps_before_first_click(self):
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect');self.assertTrue(w.sketch_hover_wanted())    # od razu, przed pierwszym kliknięciem
        w.sketch_clicked('XY',0,0);self.assertTrue(w.sketch_hover_wanted())
        w.choose_tool(None);self.assertFalse(w.sketch_hover_wanted())
        w.choose_tool('circleTangent2');self.assertFalse(w.sketch_hover_wanted())      # najpierw wskazuje się linie
        # przed pierwszym kliknięciem: postój przy narożniku istniejącego szkicu pokazuje znacznik i ustawia punkt startu
        self.sketch('rect',(0,0),(10,10));w.choose_tool('line');now=self._dwell_clock()
        x,y=w.view.project_one(k.to_world('XY',10,10));self.assertEqual(w.points,[])
        from PySide6.QtCore import QPointF
        w.view._hover_time=0;w.view._hover(QPointF(x+3,y+2));self.assertIsNone(w.view.snap_label)
        now[0]+=.3;w.view._hover_time=0;w.view._hover(QPointF(x+3,y+2))
        self.assertEqual(w.view.snap_label,'Punkt styku');self.assertIsNotNone(w.view.snap_marker)
        self.assertAlmostEqual(w.last_uv[0],10,3);self.assertAlmostEqual(w.last_uv[1],10,3)

    def test_svg_import(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'a.svg');open(f,'w').write('<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="20" height="10"/><circle cx="5" cy="5" r="2"/><path d="M0 0 L10 0 L10 10 Z"/></svg>')
            self.assertEqual(len(k.svg_profiles(f)),3)

    # 0.4.61: SVG / DXF jako szkic - krzywe, transformacje, jednostki (bez jednostki = piksele), obwody, grupa
    def test_svg_import_units_curves_transforms_and_group(self):
        import tempfile,ezdxf,time as _t
        import cadquery as cq
        w=self.w
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'logo.svg')
            Path(f).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
                               '<g transform="translate(10,10) scale(2)"><path d="M0 0 C 10 -10 20 10 30 0 L 30 20 Q 15 30 0 20 Z"/></g>'
                               '<circle cx="80" cy="80" r="8"/></svg>',encoding='utf-8')
            wires=k.svg_profiles(f)
            self.assertEqual(len(wires),2);self.assertTrue(all(x.IsClosed() for x in wires))
            kinds={e.geomType() for x in wires for e in x.Edges()};self.assertIn('BEZIER',kinds);self.assertIn('CIRCLE',kinds)
            circle=next(x for x in wires if any(e.geomType()=='CIRCLE' for e in x.Edges()))
            self.assertAlmostEqual(circle.Edges()[0].radius(),8*25.4/96,4)          # 96 px = 1 cal = 25,4 mm
            path=next(x for x in wires if x is not circle);bb=path.BoundingBox()
            self.assertAlmostEqual(bb.xlen,60*25.4/96,3)                               # scale(2) z transform
            mm=os.path.join(d,'mm.svg');Path(mm).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="20mm" viewBox="0 0 100 40"><rect width="100" height="40"/></svg>',encoding='utf-8')
            bb=cq.Compound.makeCompound(k.svg_profiles(mm)).BoundingBox();self.assertAlmostEqual(bb.xlen,50,4);self.assertAlmostEqual(bb.ylen,20,4)
            # duży plik: setki konturów z krzywymi - szybko i jako grupa na liście obiektów
            many=os.path.join(d,'duzo.svg')
            Path(many).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="300mm" viewBox="0 0 300 300">'+''.join(
                f'<path d="M{x} {y} C {x+3} {y-2} {x+6} {y+2} {x+8} {y} L {x+8} {y+8} L {x} {y+8} Z"/>' for x in range(0,300,15) for y in range(0,300,15))+'</svg>',encoding='utf-8')
            start=_t.monotonic()
            with patch('rccad.studio.QFileDialog.getOpenFileName',return_value=(many,'')):w.import_model()
            self.wait();self.assertLess(_t.monotonic()-start,30)
            sk=[b for b in w.document.bodies if b.kind=='sketch'];self.assertEqual(len(sk),400)
            self.assertEqual({b.folder for b in sk},{'duzo'})
            edges=[e for b in sk for e in b.shape.Edges()]
            start=_t.monotonic();reg=k.regions('XY',edges);self.assertLess(_t.monotonic()-start,15);self.assertEqual(len(reg),400)
            dxf=os.path.join(d,'cm.dxf');doc=ezdxf.new('R2010');doc.units=ezdxf.units.CM;doc.modelspace().add_lwpolyline([(0,0),(6,0),(6,3),(0,3)],close=True);doc.saveas(dxf)
            shapes=k.import_shapes(dxf);self.assertEqual(len(shapes),1)
            bb=shapes[0][0].BoundingBox();self.assertAlmostEqual(bb.xlen,60,4)                 # centymetry -> mm

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
        self.assertEqual(seen[:2],[('rich',9),('ctx',4)]);self.assertEqual([n for kind,n in seen[2:]],[3,4])

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

    def test_autosave_runs_with_tool_open_and_history_limit_warns(self):
        w=self.w;d=w.document
        with tempfile.TemporaryDirectory() as directory:
            d.path=Path(directory)/'proj.rccadx'
            d.commit([Body('A',k.box(5,5,5)).prepared()],'Kostka')
            w.set_mode('extrude');self.app.processEvents()
            w._autosave();end=time.monotonic()+20
            while getattr(w,'_autosaved',None)!=(id(d),d._revision) and time.monotonic()<end:
                self.app.processEvents();time.sleep(.01)
            self.assertTrue((Path(directory)/'proj.autosave.rccadx').exists())
            w.set_mode(None);d.path=None
        toasts=[]
        with patch.object(w,'toast',side_effect=lambda text,*a,**kw:toasts.append(text)):
            body=d.bodies[0]
            for i in range(d.WARN_UNDO):d.commit([body],str(i))
            w.refresh();w.refresh()
            self.assertEqual(sum('najstarsze kroki będą usuwane' in t for t in toasts),1)
            for i in range(d.MAX_UNDO):d.commit([body],str(i))
            w.refresh()
            self.assertTrue(any('osiągnęła limit' in t for t in toasts))

    def test_split_tool_plane_face_sketch_and_body(self):
        import cadquery as cq
        w=self.w;a=Body('Kostka',k.box(40,20,10)).prepared();w.document.commit([a]);w.refresh()
        self.assertIn('split',__import__('rccad.studio',fromlist=['TABS']).TABS['Edycja'])
        w.selected=[a.id];w.toggle_mode('split');self.assertEqual((w.mode,w.sp_id),('split',a.id))
        w.sp_plane.setCurrentIndex(2);w.sp_offset.setValue(10);self.assertTrue(w.view.handles)          # YZ przez środek, +10 mm
        w.update_split_preview();self.preview();self.assertTrue(w.view.preview_items);self.assertIn('2',w.sp_status.text())
        w.apply_split();self.wait()
        vols=sorted(round(b.shape.Volume()) for b in w.document.bodies);self.assertEqual(vols,[2000,6000])
        self.assertIsNone(w.mode);self.assertEqual(w.selected,[a.id])                                  # zaznaczona kliknięciem zostaje, nowa część nie zaznacza się sama
        self.assertTrue(w.document.timeline()[0][-1].startswith('Przecięcie płaszczyzną YZ'))
        # zostaje tylko jedna strona: ściana bryły jako płaszczyzna, odsunięta w głąb
        w.undo();w.set_mode('split');w.sp_id=a.id;w.sp_method.setCurrentIndex(1)
        face=next(f for f in a.shape.Faces() if abs(f.Center().z-10)<1e-6)
        with patch.object(w.view,'pick_face',return_value=(a.id,[0,0,1],face.Center().toTuple())):w.view_clicked(5,5,False,False)
        self.assertIsNotNone(w.sp_ref);w.sp_offset.setValue(-4);w.sp_keep.setCurrentIndex(2)       # strona 2: pod płaszczyzną
        w.apply_split();self.wait();self.assertEqual(len(w.document.bodies),1);self.assertAlmostEqual(w.document.bodies[0].shape.Volume(),40*20*6,3)
        # szkic: zamknięty okrąg wycina walec (wewnątrz = strona 2), szkic wygasa
        w.undo();circle=Body('Okrąg',cq.Face.makeFromWires(cq.Wire.assembleEdges([cq.Edge.makeCircle(4,cq.Vector(20,10,10))])),'sketch').prepared()
        w.document.commit([*w.document.bodies,circle]);w.set_mode('split');w.sp_id=a.id;w.sp_method.setCurrentIndex(2);w.sp_keep.setCurrentIndex(0)
        with patch.object(w.view,'pick_body',return_value=circle.id):w.view_clicked(5,5,False,False)
        self.assertEqual(w.sp_ref['tool'],circle.id);w.apply_split();self.wait()
        solids=[b for b in w.document.bodies if b.kind=='solid'];self.assertEqual(len(solids),2)
        self.assertAlmostEqual(min(b.shape.Volume() for b in solids),math.pi*16*10,1);self.assertFalse(w.document.get(circle.id).visible)
        # inna bryła: walec dzieli kostkę, narzędzie zostaje
        w.undo();w.undo();cyl=Body('Walec',cq.Solid.makeCylinder(5,30,cq.Vector(0,0,-10))).prepared()
        w.document.commit([*w.document.bodies,cyl]);w.set_mode('split');w.sp_id=a.id;w.sp_method.setCurrentIndex(3)
        with patch.object(w.view,'pick_body',return_value=cyl.id):w.view_clicked(5,5,False,False)
        w.apply_split();self.wait();self.assertEqual(len(w.document.bodies),3);self.assertIsNotNone(w.document.get(cyl.id))
        # krok przelicza się z przepisu
        info=w.document.states()[-1][1];self.assertEqual(info['op']['type'],'split')
        again=hist.run_recipe(w.document.states()[-2][0],info['op']);self.assertEqual(len(again),3)

    # 0.4.58: szkic pod kursorem podświetlony, cięcie jedną linią (także kończącą się na bryle)
    def test_split_sketch_hover_and_single_line(self):
        w=self.w;a=Body('Kostka',k.box(40,20,10)).prepared()
        top=k.Frame((0,0,10),(1,0,0),(0,0,1))
        line=Body('Linia',k.polyline(top,[(10,-3),(10,25)]),'sketch',top).prepared()     # zaczyna się w środku bryły
        w.document.commit([a,line]);w.refresh()
        w.selected=[a.id];w.toggle_mode('split');w.sp_method.setCurrentIndex(2)
        with patch.object(w.view,'nearest_edge',return_value=(line.id,0)):w.view_hover(5,5)
        self.assertEqual(w.view._hover_key,('body',line.id))                  # szkic pod kursorem świeci
        with patch.object(w.view,'nearest_edge',return_value=None),patch.object(w.view,'pick_body',return_value=None):w.view_hover(6,6)
        self.assertIsNone(w.view._hover_key)
        with patch.object(w.view,'nearest_edge',return_value=(line.id,0)):w.view_clicked(5,5,False,False)
        self.assertEqual(w.sp_ref['tool'],line.id)
        w.apply_split();self.wait()
        vols=sorted(round(b.shape.Volume()) for b in w.document.bodies if b.kind=='solid');self.assertEqual(vols,[2000,6000])
        w.set_mode('split');self.assertIsNone(w.view._hover_key)

    def test_shell_thickness_arrow_follows_last_selected_face_and_panel_fits(self):
        w=self.w;a=Body('Kostka',k.box(30,30,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('shell')
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([0,0,1.]),np.array([15,15,20.]))):
            w.view_clicked(5,5,False,False);w.view_clicked(5,5,False,False)        # bryła, potem otwarta górna ściana
        h=[x for x in w.view.handles if x['id']=='shell'];self.assertEqual(len(h),1)
        self.assertAlmostEqual(abs(float(h[0]['dir'][2])),1,6)                   # uchwyt przy ostatniej wskazanej ścianie
        np.testing.assert_allclose(h[0]['start'],[15,15,18])
        w.handle_dragged('shell',1.5);self.assertAlmostEqual(w.sh_thick.value(),3.5)
        w.handle_dragged('shell',-5);self.assertAlmostEqual(w.sh_thick.value(),.1);w.handle_released('shell')
        self.assertTrue(w._timers['shell'].isActive())
        w.sh_dir.setCurrentIndex(1);h2=w.view.handles[0]
        self.assertTrue(np.allclose(np.array(h2['dir']),-np.array(h[0]['dir'])))   # na zewnątrz: strzałka odwrócona
        w.shell_panel.show();self.app.processEvents()
        seg=w.sh_dir
        self.assertLessEqual(seg.geometry().bottom(),w.sh_status.geometry().top())   # opis pod przyciskami, nie na nich

    # 0.4.61: Shift - kilka krawędzi i narożników, także na różnych bryłach, w jednym kroku
    def test_fillet_click_adds_shift_removes_edges_corners_and_bodies(self):
        import cadquery as cq
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();b=Body('B',cq.Solid.makeBox(10,10,10,pnt=cq.Vector(40,0,0))).prepared()
        w.document.commit([a,b]);w.refresh();w.set_mode('mod')
        top=next(i for i,e in enumerate(a.shape.Edges()) if e.Center().z>19.9)
        corner=np.array(next(v.toTuple() for v in a.shape.Vertices() if v.Z<1e-6))
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=(a.id,top)):w.view_clicked(5,5,False,False)
        with patch.object(w.view,'nearest_vertex',return_value=(a.id,corner)):w.view_clicked(5,5,False,False)        # kliknięcie: narożnik dochodzi do krawędzi
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=(b.id,0)):w.view_clicked(5,5,False,False)   # druga bryła
        self.assertEqual(len(w._mod_items()),2);self.assertIn('krawędzie: 2',w.mod_status.text());self.assertIn('narożniki: 1',w.mod_status.text())
        self.assertEqual(len(w.view.sel_vertices),1)
        w.mod_size.setValue(1.5);w.update_mod_preview();self.preview();self.assertTrue(w.view.preview_items)
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=(b.id,0)):w.view_clicked(5,5,True,False)   # Shift: odznacza
        self.assertEqual(len(w._mod_items()),1)
        with patch.object(w.view,'nearest_vertex',return_value=(a.id,corner)):w.view_clicked(5,5,True,False)         # Shift: odznacza narożnik
        self.assertEqual(len(w.view.sel_vertices),0)
        with patch.object(w.view,'nearest_vertex',return_value=(a.id,corner)):w.view_clicked(5,5,False,False)
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=(b.id,0)):w.view_clicked(5,5,False,False)
        with patch.object(w.view,'nearest_vertex',return_value=None),patch.object(w.view,'nearest_edge',return_value=(b.id,0)):w.view_clicked(5,5,False,False)   # drugi raz bez Shift - zostaje
        self.assertEqual(len(w._mod_items()),2)
        va,vb=a.shape.Volume(),b.shape.Volume()
        w.apply_mod();self.wait()
        na,nb=w.document.get(a.id),w.document.get(b.id)
        self.assertLess(na.shape.Volume(),va-1);self.assertLess(nb.shape.Volume(),vb-.1)
        self.assertGreater(len(na.shape.Faces()),7)                                  # krawędź + narożnik
        op=w.document.info['op'];self.assertEqual(len(op['items']),2)
        from rccad import history as hist
        again=hist.run_recipe([a,b],op);self.assertAlmostEqual(again[0].shape.Volume(),na.shape.Volume(),3)
        self.assertEqual(hist.reads(op,[a,b]),{a.id,b.id})
        w.undo();self.wait();self.assertAlmostEqual(w.document.get(a.id).shape.Volume(),va,3)

    # 0.4.71: Wyciągnij - kliknięcie dodaje profil, Shift + klik odznacza
    def test_extrude_click_adds_shift_removes(self):
        w=self.w
        a=Body('A',k.sketch('rectangle','XY',10,10),'sketch','XY').prepared();b=Body('B',k.transform(k.sketch('rectangle','XY',10,10),(30,0,0)),'sketch','XY').prepared()
        w.document.commit([a,b]);w.refresh();w.selected=[];w.set_mode('extrude')
        pa,pb=w._sketch_profile(a),w._sketch_profile(b)
        with patch.object(w,'_profile_at',return_value=pa):w.view_clicked(5,5,False,False)
        w.ex_value.setValue(7)
        with patch.object(w,'_profile_at',return_value=pb):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.ex_profiles),2);self.assertEqual(w.ex_value.value(),7)          # drugi profil nie kasuje ustawień
        with patch.object(w,'_profile_at',return_value=pa):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.ex_profiles),2)                                                  # już wybrany - zostaje
        with patch.object(w,'_profile_at',return_value=pa):w.view_clicked(5,5,True,False)
        self.assertEqual(len(w.ex_profiles),1);self.assertEqual(w.ex_profiles[0]['id'],b.id)
        w.apply_extrude();self.wait();self.assertEqual(len([x for x in w.document.bodies if x.kind=='solid']),1)

    def test_fillet_preview_shows_only_created_surface(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        with patch.object(w.view,'nearest_edge',return_value=(a.id,0)):w.view_clicked(5,5,False,False)
        w.mod_size.setValue(2);w.update_mod_preview();self.preview()
        pts=np.concatenate([i.opts['meshdata'].vertexes() for i in w.view.preview_items if i.__class__.__name__=='OverMesh'])
        self.assertTrue(len(pts));span=pts.max(axis=0)-pts.min(axis=0)
        self.assertEqual(sorted(round(float(x)) for x in span),[2,2,20])        # sam pas zaokrąglenia R2 wzdłuż krawędzi 20 mm

    def test_heavy_body_shows_coarse_mesh_then_refines_in_background(self):
        import cadquery as cq
        from rccad import workers
        make=lambda:cq.Workplane().box(60,60,5).faces('>Z').workplane().rarray(8,8,6,6).hole(3).edges('|Z').fillet(.4).val()
        self.assertTrue(Body('Płyta',make()).prepared().mesh.fine)            # bez procesów liczących: od razu dokładna siatka
        w=self.w;big=make()
        with patch.object(workers,'ready',return_value=True):body=Body('Płyta',big).prepared()
        self.assertFalse(body.mesh.fine)                                        # z procesami: najpierw zgrubna
        w.document.commit([body]);w.refresh()
        end=time.monotonic()+30
        while not w.document.bodies[0].mesh.fine and time.monotonic()<end:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(w.document.bodies[0].mesh.fine);self.assertFalse(w.document.dirty and w.document.can_redo)
        self.assertEqual(len(w.document.states()),2)                               # bez nowego kroku historii
        w.undo();w.redo();self.app.processEvents()
        end=time.monotonic()+5
        while not w.document.bodies[0].mesh.fine and time.monotonic()<end:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(w.document.bodies[0].mesh.fine)                           # po cofnięciu i ponowieniu - z pamięci

    def test_view_keeps_fill_on_selection_and_fast_picking_matches_brute_force(self):
        from rccad import viewport as vp
        w=self.w;a=Body('A',k.blend(k.hole(k.box(40,40,30),6,20,20),range(12),3)).prepared();w.document.commit([a]);w.refresh(True)
        fill=w.view._parts[a.id]['fill']
        w.selected=[a.id];w.refresh();self.assertIs(w.view._parts[a.id]['fill'],fill)           # zaznaczenie zmienia tylko kolor
        self.assertEqual(w.view._parts[a.id]['color'][:3],vp.PICKED_FILL[:3])
        w.selected=[];w.refresh();self.assertIs(w.view._parts[a.id]['fill'],fill)
        md=vp._meshdata(a.mesh);ref=__import__('pyqtgraph.opengl',fromlist=['MeshData']).MeshData(vertexes=a.mesh.vertices,faces=a.mesh.triangles).vertexNormals()
        self.assertLess(float(np.abs(md.vertexNormals()-ref).max()),1e-5)                        # cieniowanie jak w pyqtgraph
        tri=a.mesh.vertices.astype(float)[a.mesh.triangles]
        def brute(origin,direction):
            e1,e2=tri[:,1]-tri[:,0],tri[:,2]-tri[:,0];h=np.cross(np.broadcast_to(direction,e2.shape),e2);aa=np.einsum('ij,ij->i',e1,h)
            f=np.divide(1.,aa,out=np.zeros_like(aa),where=np.abs(aa)>1e-9);sv=origin-tri[:,0];u=f*np.einsum('ij,ij->i',sv,h);q=np.cross(sv,e1)
            v=f*np.einsum('j,ij->i',direction,q);t=f*np.einsum('ij,ij->i',e2,q);ok=(np.abs(aa)>1e-9)&(u>=-1e-6)&(v>=-1e-6)&(u+v<=1+1e-6)&(t>1e-6)
            return float(t[ok].min()) if ok.any() else None
        W,H=w.view.width(),w.view.height();hits=0
        for x in np.linspace(W*.2,W*.8,9):
            for y in np.linspace(H*.2,H*.8,7):
                origin,direction=w.view._ray(x,y);fast=w.view._hit(origin,direction);slow=brute(origin,direction)
                self.assertEqual(fast is None,slow is None)
                if fast is not None:
                    hits+=1;self.assertAlmostEqual(fast[0],slow,6)
        self.assertGreater(hits,5)
        for index,points in list(a.mesh.edges.items())[:12]:
            xy,_,_=w.view.project_points(points[len(points)//2:len(points)//2+1])
            hit=w.view.nearest_edge(*xy[0])
            if hit is not None:
                self.assertEqual(hit[0],a.id)

    def test_pattern_directions_and_group_acts_as_one_element(self):
        w=self.w;self.sketch('rect',(0,0),(5,5));src=w.document.bodies[0];w.choose_tool(None);w.set_mode(None)
        w.toggle_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=src.id),patch.object(w.view,'nearest_edge',return_value=None):w.view_clicked(5,5,False,False)
        self.assertEqual(w.pat_id,src.id)
        w.pat_counts[0].setValue(3);w.pat_gaps[0].setValue(10);w.pat_counts[1].setValue(2);w.pat_gaps[1].setValue(8)
        w.pat_dirs[0][0].click();w.pat_dirs[1][0].click()                   # X w lewo, Y w dół
        self.assertEqual(w._pattern_spacing()[:2],[-10.0,-8.0])
        w.pat_result.setCurrentIndex(1);self.assertFalse(w.pat_join.isChecked())
        w.apply_pattern();self.wait()
        sketches=[b for b in w.document.bodies if b.kind=='sketch'];self.assertEqual(len(sketches),6)
        self.assertTrue(sketches[0].group and all(b.group==sketches[0].group for b in sketches))
        xs=sorted(round(b.shape.Center().x) for b in sketches);self.assertEqual(xs[0],-18);self.assertEqual(xs[-1],2)
        self.assertEqual(min(round(b.shape.Center().y) for b in sketches),-6)
        # kliknięcie jednej kopii zaznacza całą grupę
        copy=sketches[-1]
        with patch.object(w.view,'nearest_edge',return_value=(copy.id,0)):w.view_clicked(5,5,False,False)
        self.assertEqual(sorted(w.selected),sorted(b.id for b in sketches))
        # wyciągnięcie: jeden profil z grupy wybiera wszystkie
        w.set_mode('extrude');centre=np.array(copy.shape.Center().toTuple())
        with patch.object(w.view,'_plane_hit',lambda pl,x,y:(1.0,centre)),patch.object(w.view,'pick_face',return_value=None):
            w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.ex_profiles),6)
        w.apply_extrude();self.wait()
        self.assertEqual(len([b for b in w.document.bodies if b.kind=='solid']),6)
        # przesunięcie przenosi całą grupę; zapis i odczyt zachowuje grupę
        w.set_mode('move');w.select_transform_target(w.document.get(copy.id));self.assertEqual(len(w.t_group),6)
        w.t_spins[2].setValue(7);w.apply_transform();self.wait()
        self.assertTrue(all(abs(b.shape.Center().z-7)<1e-6 for b in w.document.bodies if b.kind=='sketch'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'g.rccadx';w.document.save(path)
            from rccad.document import Document
            loaded=Document.load(path);self.assertEqual({b.group for b in loaded.bodies if b.kind=='sketch'},{sketches[0].group})

    def test_sketch_on_solid_face_is_picked_before_the_solid(self):
        import cadquery as cq
        w=self.w;box=Body('Kostka',k.box(20,20,10)).prepared()
        line=Body('Linia',cq.Edge.makeLine(cq.Vector(-5,10,10),cq.Vector(25,10,10)),'sketch',k.face_frame((10,10,10),(0,0,1))).prepared()
        w.document.commit([box,line]);w.refresh(True)
        x,y=w.view.project_one((10.0,10.0,10.0))
        self.assertEqual(w.pick_object(x+2,y+1),line.id)                   # linia szkicu na ścianie wygrywa z bryłą
        far=w.view.project_one((3.0,3.0,10.0));self.assertEqual(w.pick_object(*far),box.id)

    def test_many_holes_are_cut_in_one_operation(self):
        import cadquery as cq
        from rccad import history as H
        plate=Body('Płyta',k.box(100,100,5)).prepared()
        tools=[cq.Solid.makeCylinder(1.5,20,cq.Vector(8+10*i,8+10*j,-5)) for i in range(9) for j in range(9)]
        with patch.object(H,'_boolean_changed',wraps=H._boolean_changed) as spy:
            out=H.combine([plate],tools,'cut')
        self.assertEqual(spy.call_count,1)                                         # jedna operacja na wszystkie otwory
        self.assertAlmostEqual(out[0].shape.Volume(),100*100*5-81*np.pi*1.5**2*5,3)
        seq=plate.shape
        for t in tools[:5]:seq=k.boolean('subtract',seq,[t])
        five=H.combine([plate],tools[:5],'cut')[0].shape
        self.assertLess(five.cut(seq).Volume()+seq.cut(five).Volume(),1e-6)     # wynik jak po kolei

    def test_sketch_pattern_on_tilted_face_stays_on_that_face(self):
        import cadquery as cq
        w=self.w;n=np.array([0.0,-np.sin(np.radians(30)),np.cos(np.radians(30))])
        frame=k.face_frame((0.0,0.0,0.0),tuple(n))
        u,v=np.array(frame.xdir,float),np.array(frame.ydir,float)
        centre=cq.Vector(*(3*u+3*v))
        circle=Body('Okrąg',cq.Face.makeFromWires(cq.Wire.assembleEdges([cq.Edge.makeCircle(1,centre,cq.Vector(*n))])),'sketch',frame).prepared()
        w.document.commit([circle]);w.refresh();w.set_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=circle.id),patch.object(w.view,'nearest_edge',return_value=None):w.view_clicked(5,5,False,False)
        w.pat_counts[0].setValue(3);w.pat_gaps[0].setValue(10);w.pat_counts[1].setValue(2);w.pat_gaps[1].setValue(6)
        w.apply_pattern();self.wait()
        copies=[b for b in w.document.bodies if b.kind=='sketch'];self.assertEqual(len(copies),6)
        for b in copies:
            c=np.array(b.shape.Center().toTuple())
            self.assertAlmostEqual(float(c@n),0.0,6)                               # każda kopia leży w płaszczyźnie szkicu
        spread=sorted(round(float(np.array(b.shape.Center().toTuple())@u)) for b in copies)
        self.assertEqual(spread,[3,3,13,13,23,23])

    # 0.4.48: podgląd zaokrąglenia od razu, pasek pracy w tle, Esc przerywa, kółko + lewy przesuwa także w górę i w dół
    def test_fillet_preview_appears_before_background_result(self):
        w=self.w;a=Body('A',k.box(20,20,20)).prepared();w.document.commit([a]);w.refresh();w.set_mode('mod')
        w.edges={a.id:{0,1}};w.mod_size.setValue(2)
        with patch.object(w,'run_preview') as later:
            w.update_mod_preview()
        later.assert_called_once()                          # dokładny podgląd idzie w tło
        self.assertTrue(w.view.preview_items)               # a analityczny jest już widoczny

    def test_busy_bar_under_cube_follows_background_work(self):
        w=self.w;bar=w.busy_bar
        self.assertGreater(bar.y(),w.cube.y()+w.cube.height()-1)
        self.assertFalse(w.working())
        w._refining.add(1)
        self.assertTrue(w.working())
        for _ in range(3):bar._tick()
        self.assertTrue(bar.isVisible())
        w._refining.clear()
        for _ in range(8):bar._tick()
        self.assertFalse(bar.isVisible())

    def test_escape_abandons_running_operation(self):
        import threading
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        w=self.w;gate=threading.Event();applied=[]
        w.run_operation('Test',lambda:(gate.wait(10),1)[1],lambda v:applied.append(v))
        self.assertTrue(w.busy)
        w.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier))
        self.assertFalse(w.busy)
        gate.set();w.pool.waitForDone(5000)
        for _ in range(20):self.app.processEvents();time.sleep(.005)
        self.assertEqual(applied,[])

    def test_middle_and_left_drag_pans_vertically_on_plane_view(self):
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent,QPointF
        v=self.w.view;v.setCameraPosition(azimuth=-90,elevation=0)        # prosto na płaszczyznę XZ
        start=v.opts['center'];start=np.array([start.x(),start.y(),start.z()])
        both=Qt.MiddleButton|Qt.LeftButton
        def ev(kind,x,y,button,buttons):
            return QMouseEvent(kind,QPointF(x,y),QPointF(x,y),button,buttons,Qt.NoModifier)
        v.mousePressEvent(ev(QEvent.MouseButtonPress,300,300,Qt.MiddleButton,Qt.MiddleButton))
        v.mousePressEvent(ev(QEvent.MouseButtonPress,300,300,Qt.LeftButton,both))
        v.mouseMoveEvent(ev(QEvent.MouseMove,300,360,Qt.NoButton,both))
        c=v.opts['center'];moved=np.array([c.x(),c.y(),c.z()])-start
        self.assertGreater(abs(moved[2]),1e-3)                 # w górę / w dół
        self.assertLess(abs(moved[1]),1e-6)                    # nie w głąb ekranu
    def test_moved_body_is_picked_where_it_is_shown_and_keeps_values(self):
        w=self.w;a=Body('A',k.box(40,40,40)).prepared();w.document.commit([a]);w.refresh(True);self.app.processEvents()
        w.set_mode('move');w.select_transform_target(a)
        w.t_spins[0].setValue(80);self.app.processEvents()
        p=w.view.project_one((100,20,40))
        self.assertEqual(w.view.pick_body(*p),a.id)                       # bryłę chwyta się tam, gdzie ją widać
        self.assertIsNone(w.view.pick_body(*w.view.project_one((20,20,40))))  # a nie w pustym, starym miejscu
        self.assertIsNotNone(w.view.nearest_edge(*w.view.project_one((120,0,40))))
        w.view_clicked(*p,False,False)
        self.assertEqual([s.value() for s in w.t_spins],[80.0,0.0,0.0])   # ponowne kliknięcie nie kasuje ustawienia
        self.assertTrue(np.allclose(w.view.free_drag[1],w.t_center+[80,0,0]))
        self.assertEqual(len(w.document.bodies),1);self.assertAlmostEqual(w.document.bodies[0].shape.BoundingBox().xmin,0,4)  # nic nie liczy się przed Zastosuj
        w.apply_transform();self.wait()
        self.assertAlmostEqual(w.document.bodies[0].shape.BoundingBox().xmin,80,3)

    # 0.4.50: kostka (obrót w płaszczyźnie, góra do góry), grupy na liście, szyk jako jedna pozycja, pogrubiony tekst
    def test_cube_roll_and_upright_plane_view(self):
        w=self.w;v=w.view
        v.look_along('XY');r,u,b=v.screen_axes()
        self.assertTrue(np.allclose(u,[0,1,0],atol=1e-6))                  # GÓRA na kostce stoi prosto
        n=np.array([.02,.01,1]);n/=np.linalg.norm(n);x=np.cross([0,1,0],n);x/=np.linalg.norm(x)
        frame=k.Frame.from_dict(dict(origin=(0,0,5),normal=tuple(n),xdir=tuple(x)))
        v.look_along(frame);r,u,b=v.screen_axes()
        self.assertGreater(u[1],.99)                                        # prawie pozioma ściana też „Y do góry”
        v.look_along(k.Frame.from_dict(dict(origin=(0,0,0),normal=(.7071067811865476,.7071067811865476,0),xdir=(0,0,1))));r,u,b=v.screen_axes()
        self.assertGreater(u[2],.99)                                        # pionowa ściana: Z do góry
        v.look_along('XY');w._cube_roll(90);r,u,b=v.screen_axes()
        self.assertTrue(np.allclose(u,[1,0,0],atol=1e-6));self.assertAlmostEqual(v.roll(),90)
        p0=np.array(v.project_one((0,0,0)));v.pan(20,0,0,relative='view');p1=np.array(v.project_one((0,0,0)))
        self.assertTrue(np.allclose(p1-p0,[20,0],atol=.5))                 # przesuwanie dalej idzie za myszą
        w._cube_rotate(0,90);r,u,b=v.screen_axes()
        self.assertAlmostEqual(abs(float(np.dot(b,[0,0,1]))),0,6)            # strzałka w górę przerzuca z widoku z góry na bok
        v.set_view('-Y');w._cube_rotate(-90,0)
        self.assertTrue(np.allclose(v.screen_axes()[2],[-1,0,0],atol=1e-6))  # strzałka w lewo: widok z lewej
        from PySide6.QtCore import QPointF
        hits={w.cube._hit(w.cube._roll_center(s)) for s in (1,-1)}
        self.assertEqual(hits,{('roll',1),('roll',-1)})

    def test_objects_list_pattern_unit_and_folders(self):
        w=self.w
        s1=Body('Szkic 1',k.sketch('rectangle','XY',10,10),'sketch','XY').prepared()
        s2=Body('Szkic 2',k.sketch('circle','XY',4,4).translate((40,0,0)),'sketch','XY').prepared()
        w.document.commit([s1,s2])
        a=hist.run_pattern(list(w.document.bodies),dict(type='pattern',id=s1.id,kind='rect',params=dict(counts=[4,1,1],spacing=[15,0,0]),group='abc1',join=False,out=[]))
        b=hist.run_pattern(a,dict(type='pattern',id=s2.id,kind='rect',params=dict(counts=[1,3,1],spacing=[0,15,0]),join=False,out=[]))
        w.document.commit(b);w.refresh();self.app.processEvents()
        rows=w.objects.rows
        self.assertIn(s1.id,rows);self.assertEqual(sum(1 for i in rows if w.document.get(i).group=='abc1'),1)  # szyk jako jeden szkic
        self.assertEqual(w.objects.folders(),['Szkic 2 — szyk'])
        w.objects_hide(s1.id);self.assertTrue(all(x.id in w.hidden_ids for x in w.document.bodies if x.group=='abc1'))
        w.objects_hide(s1.id)
        w.selected=[s2.id];w.objects_folder_new(None)
        self.assertEqual(w.document.get(s2.id).folder,'Grupa 1')
        infos,cur=w.document.infos();self.assertEqual(infos[-1]['op']['type'],'folder')
        w.objects_folder_move([s1.id],'Grupa 1')
        self.assertEqual({x.folder for x in w.document.bodies if x.group=='abc1'},{'Grupa 1'})   # cały szyk razem
        w.objects_folder_rename('Grupa 1','Mocowania')
        self.assertEqual({x.folder for x in w.document.bodies if x.folder},{'Mocowania','Szkic 2 — szyk'})
        w.undo();self.wait();self.assertIn('Grupa 1',{x.folder for x in w.document.bodies})
        w.redo();self.wait()
        w.objects_folder_move([s2.id],'');self.assertEqual(w.document.get(s2.id).folder,'')


    # 0.4.51: ukryte bryły nietykalne, grupy dla wielu nowych brył, eksport widocznych / zaznaczonych, lista zwijana do paska
    def test_hidden_body_is_not_cut_and_new_bodies_get_folder(self):
        w=self.w
        a=Body('A',k.box(20,20,20)).prepared();b=Body('B',k.box(20,20,20).translate((30,0,0))).prepared()
        sk=Body('Szkic',k.sketch('rectangle','XY',60,8).translate((25,10,20)),'sketch','XY').prepared()
        w.document.commit([a,b,sk]);w.refresh()
        w.hidden_ids.add(b.id)
        w.set_mode('extrude')
        with patch.object(w.view,'pick_profile',return_value=sk.id):w.view_clicked(5,5,False,False)
        w.ex_op.setCurrentIndex(w.ex_op.findData('cut'));w.ex_value.setValue(-5);w.apply_extrude();self.wait()
        self.assertLess(w.document.get(a.id).shape.Volume(),8000-1)
        self.assertAlmostEqual(w.document.get(b.id).shape.Volume(),8000,3)         # ukryta bryła bez zmian
        infos,cur=w.document.infos();self.assertIn(b.id,infos[-1]['op'].get('skip',[]))
        again=hist.run_recipe(w.document.states()[cur-1][0],infos[-1]['op'])
        self.assertAlmostEqual(next(x for x in again if x.id==b.id).shape.Volume(),8000,3)   # także przy przeliczaniu historii
        s1=Body('Okrąg',k.sketch('circle','XY',4,4).translate((0,-30,0)),'sketch','XY').prepared()
        w.document.commit([*w.document.bodies,s1]);w.refresh()
        pat=hist.run_pattern(list(w.document.bodies),dict(type='pattern',id=s1.id,kind='rect',params=dict(counts=[3,1,1],spacing=[10,0,0]),join=False,out=[],group='9f'))
        w.document.commit(pat);w.refresh()
        w.set_mode('extrude')
        with patch.object(w.view,'pick_profile',return_value=s1.id):w.view_clicked(5,5,False,False)
        self.assertEqual(len(w.ex_profiles),3)
        w.ex_op.setCurrentIndex(w.ex_op.findData('new'));w.ex_value.setValue(5);w.apply_extrude();self.wait()
        made=[x for x in w.document.bodies if x.kind=='solid' and x.folder]
        self.assertEqual(len(made),3);self.assertEqual({x.folder for x in made},{'Okrąg — bryły'})  # wyciągnięty szyk od razu w grupie

    def test_export_takes_visible_or_selected_only(self):
        w=self.w
        a=Body('A',k.box(5,5,5)).prepared();b=Body('B',k.box(5,5,5).translate((10,0,0))).prepared();c=Body('C',k.box(5,5,5).translate((20,0,0))).prepared()
        w.document.commit([a,b,c]);w.hidden_ids={c.id}
        self.assertEqual([x.id for x in w.export_bodies()],[a.id,b.id])
        w.selected=[b.id,c.id];self.assertEqual([x.id for x in w.export_bodies()],[b.id])
        with patch('rccad.studio.QFileDialog.getSaveFileName',return_value=('',None)) as dlg:w.export_model()
        dlg.assert_called_once()

    def test_objects_panel_collapses_to_strip(self):
        w=self.w;o=w.objects;W=w.view.width() if w.objects.parentWidget() is w.view else o.parentWidget().width()
        o._toggle_collapse();self.app.processEvents()
        self.assertFalse(o.open);self.assertEqual(o.width(),o.STRIP);self.assertTrue(o.strip.isVisible())
        self.assertEqual(o.x()+o.width(),o.parentWidget().width())                  # pasek przy samej prawej krawędzi
        o.strip.click();self.app.processEvents()
        self.assertTrue(o.open);self.assertGreater(o.width(),200);self.assertFalse(o.strip.isVisible())

    def test_pattern_arrows_set_spacing_in_three_directions(self):
        w=self.w;a=Body('A',k.box(10,10,10)).prepared();w.document.commit([a]);w.refresh()
        w.toggle_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=a.id),patch.object(w.view,'nearest_edge',return_value=None):w.view_clicked(5,5,False,False)
        self.assertEqual(w.pat_id,a.id);w.update_pattern_preview()
        self.assertEqual(sorted(h['id'] for h in w.view.handles),['patX','patY','patZ'])
        hx=next(h for h in w.view.handles if h['id']=='patX')
        self.assertTrue(np.allclose(hx['tip'],np.array(hx['start'])+[w.pat_gaps[0].value(),0,0]),(hx,w.pat_gaps[0].value(),w.pat_counts[0].value()))     # koniec strzałki X na pierwszej kopii
        g=[x.value() for x in w.pat_gaps]
        w.handle_dragged('patX',5);self.assertAlmostEqual(w.pat_gaps[0].value(),g[0]+5)
        w.handle_dragged('patX',8.12);self.assertAlmostEqual(w.pat_gaps[0].value(),g[0]+8.12,places=2)
        hx=next(h for h in w.view.handles if h['id']=='patX')
        self.assertAlmostEqual(hx['tip'][0]-hx['start'][0],g[0]+8.12,places=2)
        w.handle_released('patX')
        w.handle_dragged('patY',15);w.handle_released('patY')
        self.assertEqual((w.pat_counts[1].value(),w.pat_gaps[1].value()),(2,g[1]+15))   # jedna kopia w Y -> przeciągnięcie dodaje kopię
        w.handle_dragged('patZ',-(g[2]+30));w.handle_released('patZ')
        self.assertAlmostEqual(w.pat_gaps[2].value(),30);self.assertEqual(next(b.sign for b in w.pat_dirs[2] if b.isChecked()),-1)   # przez zero: w dół
        w.update_pattern_preview()
        hz=next(h for h in w.view.handles if h['id']=='patZ');self.assertLess(hz['dir'][2],0)
        ops,_=w._pattern_ops(a);self.assertEqual(len(ops),3*2*2-1)
        w.pat_kind.setCurrentIndex(1);w.update_pattern_preview();self.assertFalse([h for h in w.view.handles if h['id'].startswith('pat')])

    def test_three_point_rectangular_range_keeps_last_copy_at_clicked_centers(self):
        w=self.w
        plane=k.face_frame((5,5,2),(0,0,1))
        wire=cq.Workplane(cq.Plane(origin=(5,5,2),normal=(0,0,1))).rect(10,10).val()
        body=Body('Plate sketch',wire,'sketch',plane).prepared();w.document.commit([body]);w.refresh();w.set_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=body.id),patch.object(w.view,'nearest_edge',return_value=None):
            w.pick_pattern(10,10)
        w.view.set_grid_visible(False)
        w.pat_range_button.setChecked(True)
        self.assertIsNotNone(w._pat_range_frame)
        self.assertIs(w.view._grid_plane,w._pat_range_frame)
        self.assertTrue(w.view._grid_on)
        origin=w._pat_range_points[0].copy();self.assertTrue(np.allclose(origin,[5,5,2]))
        endpoints=[origin+40*w._pat_range_axes[0],origin-30*w._pat_range_axes[1]]
        w.pat_counts[0].setValue(5)
        with patch.object(w.view,'pick_face',side_effect=AssertionError('nie pytaj ponownie o powierzchnię')), \
             patch.object(w.view,'_plane_hit',side_effect=[(1,endpoints[0]),(1,endpoints[1])]), \
             patch.object(w.view.grid_items[0],'spacing',return_value=(1,1,None)):
            w.pick_pattern(10,10);w.pick_pattern(20,20)
        w.pat_counts[1].setValue(4)
        ops,_=w._pattern_ops(body)
        self.assertEqual(len(ops),19)
        self.assertAlmostEqual(w._pattern_spacing()[0],10)
        self.assertAlmostEqual(w._pattern_spacing()[1],-10)
        self.assertTrue(any(np.allclose(np.asarray(op[1]),endpoints[0]-origin) for op in ops))
        self.assertTrue(any(np.allclose(np.asarray(op[1]),endpoints[1]-origin) for op in ops))
        w.update_pattern_preview();items=tuple(w.view.preview_items);w.update_pattern_preview()
        self.assertEqual(items,tuple(w.view.preview_items))
        w.handle_dragged('patX',5.25);w.handle_released('patX')
        self.assertAlmostEqual(w._pattern_spacing()[0],45.25/4)
        self.assertAlmostEqual(w.pat_gaps[0].value(),11.31)
        w.pat_range_button.setChecked(False)
        self.assertFalse(w.view._grid_on)

    def test_three_point_range_is_unavailable_for_solids(self):
        w=self.w;body=Body('Block',k.box(10,10,2)).prepared();w.document.commit([body]);w.refresh();w.set_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=body.id),patch.object(w.view,'nearest_edge',return_value=None):
            w.pick_pattern(10,10)
        self.assertFalse(w.pat_range_button.isEnabled())
        w.pat_range_button.setChecked(True)
        self.assertFalse(w.pat_range_button.isChecked())

    def test_three_point_range_snaps_to_vertices_edges_and_circle_centers(self):
        w=self.w
        plane=k.face_frame((0,0,0),(0,0,1))
        sketch=Body('Source',cq.Workplane('XY').rect(2,2).val(),'sketch',plane).prepared()
        circle=Body('Circle',cq.Workplane('XY').center(23.4,0).circle(3).val(),'sketch',plane).prepared()
        solid=Body('Block',k.box(30,10,4)).prepared()
        w.document.commit([sketch,circle,solid]);w.refresh();w.set_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=sketch.id),patch.object(w.view,'nearest_edge',return_value=None):
            w.pick_pattern(10,10)
        w.pat_range_button.setChecked(True)
        with patch.object(w.view,'_plane_hit',return_value=(1,np.array([23.1,0,0]))), \
             patch.object(w.view,'nearest_vertex',return_value=(circle.id,np.array([23.4,0,0]))), \
             patch.object(w.view,'nearest_edge',return_value=None), \
             patch.object(w.view,'_screen_bodies',return_value=[]):
            point,label=w._pattern_range_point(10,10)
        self.assertAlmostEqual(point[0],23.4);self.assertIn('punkt',label)
        with patch.object(w.view,'_plane_hit',return_value=(1,np.array([23.1,0,0]))), \
             patch.object(w.view,'nearest_vertex',return_value=None), \
             patch.object(w.view,'nearest_edge',return_value=None), \
             patch.object(w.view,'_screen_bodies',return_value=[circle]), \
             patch.object(w.view,'project_one',return_value=(10,10)):
            point,label=w._pattern_range_point(10,10)
        self.assertAlmostEqual(point[0],23.4);self.assertEqual(label,'Środek okręgu')
        with patch.object(w.view,'_plane_hit',return_value=(1,np.array([23.1,0,0]))), \
             patch.object(w.view,'nearest_vertex',return_value=None), \
             patch.object(w.view,'nearest_edge',return_value=(solid.id,0)), \
             patch.object(w,'_edge_point_near',return_value=np.array([23.6,0,0])), \
             patch.object(w.view,'_screen_bodies',return_value=[]):
            point,label=w._pattern_range_point(10,10)
        self.assertAlmostEqual(point[0],23.6);self.assertEqual(label,'Krawędź')

    def test_path_handles_move_both_endpoints_and_actual_pattern(self):
        w=self.w;body=Body('Block',k.box(5,5,5)).prepared();w.document.commit([body]);w.refresh();w.set_mode('pattern')
        with patch.object(w.view,'pick_body',return_value=body.id),patch.object(w.view,'nearest_edge',return_value=None):
            w.pick_pattern(10,10)
        w.pat_kind.setCurrentIndex(2)
        w.pat_path=np.array([[0.,0.,0.],[100.,0.,0.]])
        w._pat_path_limits=(0.,100.);w.pat_lcount.setValue(5);w.update_pattern_preview()
        self.assertEqual({h['id'] for h in w.view.handles},{'patS','patE'})
        w.handle_dragged('patS',10);w.handle_released('patS')
        w.handle_dragged('patE',20);w.handle_released('patE')
        self.assertTrue(np.allclose(w._pat_path_limits,(10,80)))
        ops,moved=w._pattern_ops(body)
        self.assertTrue(np.allclose(moved[1],[10,0,0]))
        self.assertEqual([round(op[1][0],2) for op in ops],[27.5,45,62.5,80])
        recipe=dict(type='pattern',id=body.id,kind='path',params=dict(points=w.pat_path.tolist(),count=5,fit=True,
                     spacing=20,start=10,end=80),join=False,out=[])
        actual=hist.run_pattern([body],recipe)
        self.assertEqual(len(actual),5)
        self.assertAlmostEqual(actual[0].shape.BoundingBox().xmin,10,places=6)
        self.assertAlmostEqual(actual[-1].shape.BoundingBox().xmin,80,places=6)

    # 0.4.54: gwint
    def test_thread_tool_live_preview_arrows_and_apply(self):
        import cadquery as cq
        w=self.w
        plate=cq.Workplane().box(40,40,10).faces('>Z').workplane().hole(8).val()
        a=Body('Płyta',plate).prepared();w.document.commit([a]);w.refresh()
        from rccad.studio import TABS;self.assertIn('thread',TABS['Edycja'])
        w.toggle_mode('thread');self.assertTrue(w.thread_panel.isVisible())
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([4.0,0,0]))):
            w.view_hover(5,5);self.assertTrue(w.view.preview_items)          # podświetlona ściana otworu
            w.view_clicked(5,5,False,False)
        self.assertEqual(w.th_side.currentData(),'in')
        self.assertEqual(w.th_size.currentData(),'M10')                       # dopasowanie do otworu Ø8 -> M10 (wiertło 8.5)
        self.assertIn('Ø8.50',w.th_status.text())
        self.assertIsNotNone(w.view._thread_preview)                          # podgląd od razu, bez geometrii
        self.assertEqual(w.document.bodies[0].shape.Volume(),plate.Volume())  # nic nie policzone przed Zastosuj
        self.assertEqual(sorted(h['id'] for h in w.view.handles),['thD','thE','thS'])
        w.handle_dragged('thS',-3);w.handle_released('thS')
        self.assertEqual(w.th_extent.currentData(),'len');self.assertAlmostEqual(w.th_offset.value(),3);self.assertAlmostEqual(w.th_length.value(),7)
        w.handle_dragged('thD',1);w.handle_released('thD')
        self.assertEqual(w.th_size.currentData(),'M12');self.assertFalse(w.th_auto.isChecked())
        w.th_hand.setCurrentIndex(1)
        w.apply_thread();self.wait()
        b=w.document.bodies[0]
        self.assertEqual((b.threads[0]['size'],b.threads[0]['hand']),('M12','left'))
        self.assertAlmostEqual(b.threads[0]['end']-b.threads[0]['start'],7,6)
        self.assertAlmostEqual(th_cyl_radius(b.shape),(12-1.75)/2,4)          # otwór dopasowany do M12
        self.assertIn(a.id,w.view._thread_items)
        infos,cur=w.document.infos();self.assertEqual(infos[-1]['op']['type'],'thread')
        w.undo();self.wait();self.assertFalse(w.document.bodies[0].threads);self.assertNotIn(a.id,w.view._thread_items)

    # 0.4.57: linie gwintu nie zostają po usunięciu walca / wyczyszczeniu pola; krawędzie śrubowe bez cięciw
    def test_thread_lines_vanish_with_body_and_clear(self):
        import cadquery as cq
        w=self.w
        rod=cq.Workplane().circle(5).extrude(30).val()
        a=Body('Wałek',rod).prepared();w.document.commit([a]);w.refresh()
        w.toggle_mode('thread')
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([5.0,0,10]))):
            w.view_clicked(5,5,False,False)
        w.apply_thread();self.wait()
        self.assertIn(a.id,w.view._thread_items)
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([5.0,0,10]))):
            w.view_clicked(5,5,False,False)                                   # znowu wskazany: podgląd na walcu
        self.assertIsNotNone(w.view._thread_preview)
        w.set_mode(None);self.assertIsNone(w.view._thread_preview)            # Esc / wyjście z narzędzia gasi podgląd
        w.objects_delete(a.id);self.wait()
        self.assertEqual(w.view._thread_items,{});self.assertIsNone(w.view._thread_preview)
        w.undo();self.wait();self.assertIn(a.id,w.view._thread_items)
        w.toggle_mode('thread')
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([5.0,0,10]))):
            w.view_clicked(5,5,False,False)
        w._set_hidden([a.id],True);w.refresh();self.assertIsNone(w.view._thread_preview)   # ukryty walec: bez podglądu
        w._set_hidden([a.id],False);w.refresh()
        w.toggle_mode('thread')
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([5.0,0,10]))):
            w.view_clicked(5,5,False,False)
        with patch('rccad.studio.QMessageBox.question',return_value=QMessageBox.Yes):
            w.clear_all()
        self.wait();self.assertEqual(w.view._thread_items,{});self.assertIsNone(w.view._thread_preview)
        from rccad import kernel as k
        helix=cq.Wire.makeHelix(1.0,40,5).Edges()[0]                          # długa linia śrubowa: punkty wzdłuż krzywej, nie cięciwy
        pts=k.edge_points(helix)
        self.assertTrue(np.allclose(np.hypot(pts[:,0],pts[:,1]),5,atol=.05))
        mids=(pts[:-1]+pts[1:])/2;self.assertTrue(np.all(np.hypot(mids[:,0],mids[:,1])>4.95))

    # 0.4.55: okno wymiarów pod Tab, wielokąt, ukrywanie szkicu po wyciągnięciu, prawdziwy gwint przy eksporcie
    def test_tab_dimension_window_prefilled_live_and_enter(self):
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('rect')
        w.sketch_clicked('XY',0,0);w.sketch_moved('XY',20,10)
        tab=QKeyEvent(QEvent.KeyPress,Qt.Key_Tab,Qt.NoModifier)
        active=patch.object(type(w),'isActiveWindow',return_value=True);active.start();self.addCleanup(active.stop)   # okno testowe bez fokusu systemu
        self.assertTrue(w.eventFilter(w.view,tab))
        e=w.dim_edits
        self.assertTrue(w.dim_panel.isVisible());self.assertEqual((e[0].text(),e[1].text()),('20,000','10,000'))   # bieżące wymiary
        self.assertEqual(e[0].selectedText(),'20,000')                                                    # zaznaczone - od razu wpisywanie
        w.eventFilter(w.view,tab);self.assertEqual(e[1].selectedText(),'10,000')                           # Tab - kolejne pole
        e[1].setText('35');w.update_dim_preview();self.assertTrue(w.view.preview_items)                   # podgląd na żywo
        w.dim_ok.click();self.wait()
        bb=w.document.bodies[-1].shape.BoundingBox()
        self.assertAlmostEqual(bb.xlen,20,4);self.assertAlmostEqual(bb.ylen,35,4)
        w.choose_tool('circle');w.sketch_clicked('XY',50,0);w.sketch_moved('XY',58,0)
        w.eventFilter(w.view,tab);self.assertEqual([x.isVisible() for x in e],[True,False,False])         # okrąg: jeden wymiar
        self.assertEqual(e[0].text(),'8,000')

    def test_polygon_vertex_follows_cursor_and_snap_point(self):
        import math
        w=self.w;w.set_mode('plane');w.plane_picked('XY');w.choose_tool('polygon')
        w.sides=5
        w.sketch_clicked('XY',0,0)
        w.sketch_moved('XY',0,20)
        self.assertEqual(w._poly_end,(0.0,20.0));self.assertEqual(w._poly_angle,0)   # wierzchołek u góry, w kursorze
        w.view.snap_label='Siatka';w.sketch_moved('XY',10,0);w.view.snap_label=None
        self.assertEqual(w._poly_end,(10.0,0.0))                             # przyciągnięty punkt = wierzchołek
        w.sketch_moved('XY',10.4,0.3)
        self.assertAlmostEqual(math.hypot(*w._poly_end),math.hypot(10.4,.3),6)   # bez przeskoku wielkości po zejściu z punktu
        w.sketch_moved('XY',-10,10*math.sqrt(3))
        self.assertAlmostEqual(w._poly_angle,30,6)                           # kierunek kursora = obrót
        self.assertIn('30°',w.dim.text());self.assertIn('5 kątów',w.dim.text())
        w.sketch_clicked('XY',-10,10*math.sqrt(3))
        self.wait()
        sk=w.document.bodies[-1];self.assertEqual(len(sk.shape.Edges()),5)
        v=[p.toTuple() for p in sk.shape.Vertices()]
        self.assertTrue(any(abs(math.degrees(math.atan2(y,x))-120)<1e-3 for x,y,_ in v))   # 90° + 30°
        w.sketch_clicked('XY',50,0)
        w.view.snap_label='Siatka'                                           # kursor przyciągnięty do kratki / punktu
        w.sketch_moved('XY',60,0);self.assertEqual(w._poly_end,(60.0,0.0))   # wierzchołek przyklejony do punktu
        w.sketch_clicked('XY',60,0);self.wait();w.view.snap_label=None
        vs=[p.toTuple() for p in w.document.bodies[-1].shape.Vertices()]
        self.assertTrue(any(abs(x-60)<1e-6 and abs(y)<1e-6 for x,y,_ in vs))
        self._check_sides_popup_and_toggle()

    def _check_sides_popup_and_toggle(self):
        from PySide6.QtTest import QTest
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, QPointF
        from rccad import shell_ui
        w=self.w
        arrow=w.shape_buttons['polygon'].parent().findChildren(QToolButton)[-1]
        w._sides_menu(arrow);pop=w._popup
        self.assertIsInstance(pop,shell_ui.SidesPopup);self.assertTrue(pop.isVisible())
        self.assertIsNone(pop.findChild(QSpinBox))                            # tylko grafika i pole
        pop.edit.selectAll();QTest.keyClicks(pop.edit,'8')
        self.assertEqual(w.sides,8);self.assertEqual(pop.glyph.sides,8)
        QTest.keyClicks(pop.edit,'0');self.assertEqual(w.sides,8)             # 80 poza zakresem - bez zmiany
        pop.edit.setText('');QTest.keyClicks(pop.edit,'12');self.assertEqual(w.sides,12)
        w._sides_menu(arrow);self.assertFalse(pop.isVisible())                # strzałka przy otwartym okienku: chowa
        w._sides_menu(arrow);pop=w._popup;self.assertTrue(pop.isVisible())    # i znowu otwiera
        g=arrow.mapToGlobal(arrow.rect().center());local=pop.mapFromGlobal(g)
        pop.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress,QPointF(local),QPointF(g),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier))
        self.assertFalse(pop.isVisible())                                     # kliknięcie strzałki zamyka okienko...
        w._sides_menu(arrow);self.assertFalse(w._popup is not None and w._popup.isVisible())   # ...i to samo kliknięcie nie otwiera go od nowa
        QTest.keyClick(w,Qt.Key_Escape)
        rect=w.shape_buttons['rect'].parent().findChildren(QToolButton)[-1]
        rect.click();menu=w._popup;self.assertIsInstance(menu,shell_ui.RichMenu);self.assertTrue(menu.isVisible())
        rect.click();self.assertFalse(menu.isVisible())                       # warianty prostokąta / koła: to samo
        rect.click();self.assertTrue(w._popup.isVisible());w._popup.close()

    def test_extruded_sketch_is_hidden_with_crossed_eye_and_can_be_shown(self):
        w=self.w;sk=Body('Szkic',k.sketch('rectangle','XY',10,10),'sketch','XY').prepared();w.document.commit([sk]);w.refresh()
        w.set_mode('extrude')
        with patch.object(w.view,'pick_profile',return_value=sk.id):w.view_clicked(5,5,False,False)
        w.ex_value.setValue(5);w.apply_extrude();self.wait();w.set_mode(None)
        self.assertIn(sk.id,w.shown_hidden())                                        # oko przekreślone
        self.assertTrue(w.objects.rows[sk.id].property('off'))
        w.objects_hide(sk.id)
        self.assertNotIn(sk.id,w.shown_hidden())
        self.assertTrue(next(b for b in w.view.bodies if b.id==sk.id).visible)      # znów widoczny
        w.objects_hide(sk.id);self.assertIn(sk.id,w.shown_hidden())
        self.assertFalse(next(b for b in w.view.bodies if b.id==sk.id).visible)

    def test_export_builds_real_threads_in_background(self):
        import cadquery as cq,tempfile
        from pathlib import Path
        from rccad import threads
        w=self.w
        shaft=cq.Workplane().cylinder(20,5).val()
        info=threads.cylinder_info(shaft,[i for i,f in enumerate(shaft.Faces()) if f.geomType()=='CYLINDER'][0])
        t=threads.make_thread(info,'M','M10','right',info['t0'],info['t1'])
        w.document.commit([Body('Śruba',shaft,threads=(t,)).prepared()]);w.refresh()
        self.assertEqual(w.view.THREAD_COLOR[:3],(.16,.45,.86))                   # gwint niebieski
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'sruba.step')
            w.export_in_background(list(w.document.bodies),path)
            self.assertFalse(w.busy)                                               # można dalej pracować
            self.assertTrue(w.working())                                           # pasek pracy w tle
            end=time.monotonic()+60
            while w._exports and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
            back=k.import_shapes(Path(path))[0][0]
            self.assertGreater(len(back.Faces()),len(shaft.Faces())+4)            # prawdziwe zwoje w pliku
            self.assertTrue(back.isValid())

    # 0.4.56: biblioteka zachowuje gwinty i blachę
    def test_library_keeps_threads_and_bent_sheet(self):
        import tempfile,cadquery as cq
        from pathlib import Path
        from rccad import library,threads
        w=self.w;body=self.converted_sheet();w.apply_flange();self.wait()
        plate=cq.Workplane().box(30,30,8).translate((0,0,-60)).faces('>Z').workplane().hole(8.5).val()
        info=threads.cylinder_info(plate,[i for i,f in enumerate(plate.Faces()) if f.geomType()=='CYLINDER'][0])
        nut=Body('Nakrętka',plate,threads=(threads.make_thread(info,'M','M10','right',info['t0'],info['t1']),)).prepared()
        w.document.commit([*w.document.bodies,nut]);w.refresh()
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'RCCAD_CONFIG_DIR':d}):
            dialog=w.open_library('object')
            for src,target in ((w.document.get(body.id),(200.0,0.0,0.0)),(nut,(0.0,200.0,0.0))):
                dialog.take_from_workspace()
                with patch.object(w,'pick_object',return_value=src.id):w.view_clicked(5,5,False,False)
                path=max((p for p in library.entries('object',dialog.folder) if p.is_file()),key=lambda p:p.stat().st_mtime_ns)
                for i in range(dialog.view.count()):
                    it=dialog.view.item(i);it.setSelected(Path(it.data(Qt.UserRole))==path)
                dialog.place_selected();self.wait()
                with patch.object(w,'_library_target',return_value=(np.array(target),np.array([0.0,0,1]),'Siatka')):w.view_clicked(5,5,False,False)
                self.wait()
            dialog.close()
        sheet2,nut2=w.document.bodies[-2],w.document.bodies[-1]
        self.assertTrue(sheet2.meta and sheet2.meta.get('sheet'))                      # dalej blacha
        self.assertEqual(nut2.threads[0]['size'],'M10')                                # gwint zachowany
        bb=nut2.shape.BoundingBox();self.assertAlmostEqual(nut2.threads[0]['origin'][1],(bb.ymin+bb.ymax)/2,4)   # i przeniesiony z bryłą
        w.set_mode(None);w.selected=[sheet2.id];w.tools['unfold_sheet'].click();self.wait()
        self.assertTrue(w._sheet_state(sheet2.id)['flat'])                            # da się rozłożyć

    def test_thread_shift_multi_real_option_and_convert(self):
        import cadquery as cq
        w=self.w
        plate=cq.Workplane().box(80,30,10).faces('>Z').workplane().pushPoints([(-15,0),(15,0),(30,0)]).hole(8.5).val()
        a=Body('Płyta',plate).prepared();w.document.commit([a]);w.refresh()
        w.toggle_mode('thread');self.assertFalse(w.th_real.isChecked())          # prawdziwy gwint domyślnie wyłączony
        for x,shift in ((-15+4.25,False),(15+4.25,True)):
            with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([x,0,0]))):
                w.view_clicked(5,5,shift,False)
        self.assertEqual(len(w.th_extra),1)
        self.assertIn('2 otworach',w.th_status.text())
        np.testing.assert_allclose(next(h for h in w.view.handles if h['id']=='thD')['start'][:2],[15,0],atol=1e-5)
        w.apply_thread();self.wait()
        b=w.document.bodies[0];self.assertEqual(len(b.threads),2)                # dwa gwinty jednym krokiem
        self.assertEqual({t['size'] for t in b.threads},{'M10'})
        faces=len(b.shape.Faces())
        # wskazanie otworu z gwintem wirtualnym: przycisk zamiany na prawdziwy
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([-15+4.25,0,0]))):
            w.view_clicked(5,5,False,False)
        self.assertTrue(w.th_convert.isVisibleTo(w.thread_panel))
        w.convert_thread();self.wait()
        b=w.document.bodies[0];self.assertEqual(len(b.threads),1)                # jeden został wirtualny
        self.assertGreater(len(b.shape.Faces()),faces)                            # drugi to prawdziwe zwoje
        self.assertEqual(w.document.infos()[0][-1]['op']['type'],'thread_real')
        # opcja „od razu prawdziwy” (trzeci, jeszcze pusty otwór)
        with patch.object(w.view,'pick_face',return_value=(a.id,np.array([1.,0,0]),np.array([30+4.25,0,0]))):
            w.view_clicked(5,5,False,False)
        w.th_real.setChecked(True);before=len(w.document.bodies[0].threads);faces=len(w.document.bodies[0].shape.Faces())
        w.apply_thread();self.wait()
        self.assertEqual(len(w.document.bodies[0].threads),before);self.assertGreater(len(w.document.bodies[0].shape.Faces()),faces)

    def test_cutting_with_threaded_bolt_leaves_internal_thread(self):
        import cadquery as cq
        from rccad import threads
        shaft=cq.Workplane().cylinder(40,5).val()
        info=threads.cylinder_info(shaft,[i for i,f in enumerate(shaft.Faces()) if f.geomType()=='CYLINDER'][0])
        bolt=Body('Śruba',shaft,threads=(threads.make_thread(info,'M','M10','right',info['t0'],info['t1']),)).prepared()
        plate=Body('Płyta',cq.Workplane().box(30,30,8).val()).prepared()
        out=hist.run_bool([plate,bolt],dict(type='bool',op='subtract',base=plate.id,tools=[bolt.id],keep=True))
        t=out[0].threads[0]
        self.assertTrue(t['internal']);self.assertEqual(t['size'],'M10');self.assertAlmostEqual(t['end']-t['start'],8,6)
        real=threads.real_shape(out[0].shape,[t]);self.assertTrue(real.isValid());self.assertGreater(real.Volume(),out[0].shape.Volume())



def th_cyl_radius(shape):
    from rccad import threads
    return threads.cylinders(shape)[0]['radius']


if __name__=='__main__':
    unittest.main()
