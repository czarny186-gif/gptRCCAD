import math
from pathlib import Path
import tempfile
import unittest
import unittest.mock
from rccad import kernel as k
from dataclasses import replace as rep
from rccad.document import Body, Document


class KernelTests(unittest.TestCase):
    def test_box_volume(self):
        self.assertAlmostEqual(k.box(10,20,30).Volume(),6000)

    def test_revolve_profile_volume_axis_and_errors(self):
        import cadquery as cq
        face=cq.Face.makeFromWires(k.sketch('rectangle','XY',10,20,10,10))     # x 5..15, y 0..20
        full=k.revolve_face(face,(0,0,0),(0,1,0),360);self.assertAlmostEqual(full.Volume(),math.pi*(15**2-5**2)*20,2)
        half=k.revolve_face(face,(0,0,0),(0,1,0),180);self.assertAlmostEqual(half.Volume(),full.Volume()/2,2)
        horizontal=k.revolve_face(cq.Face.makeFromWires(k.sketch('rectangle','XY',20,10,10,10)),(0,0,0),(1,0,0),360);self.assertAlmostEqual(horizontal.Volume(),math.pi*(15**2-5**2)*20,2)
        with self.assertRaises(k.CadError):k.revolve_face(face,(10,0,0),(0,1,0),360)       # oś przecina profil
        with self.assertRaises(k.CadError):k.revolve_face(face,(0,0,0),(0,0,1),360)        # oś prostopadła do profilu
        for angle in (0,400,float('nan')):
            with self.subTest(angle=angle),self.assertRaises(k.CadError):k.revolve_face(face,(0,0,0),(0,1,0),angle)

    def test_shell_closed_open_outward_and_errors(self):
        b=k.box(20,20,20)
        closed=k.shell_solid(b,[],2,True);self.assertAlmostEqual(closed.Volume(),8000-16**3,1)
        top=[f for f in b.Faces() if abs(f.Center().z-20)<1e-6][0]
        opened=k.shell_solid(b,[top],2,True);self.assertAlmostEqual(opened.Volume(),8000-16*16*18,1)
        out=k.shell_solid(b,[top],2,False);self.assertGreater(out.Volume(),8000-16*16*18)
        for bad in (0,-1,float('nan')):
            with self.subTest(t=bad),self.assertRaises(k.CadError):k.shell_solid(b,[top],bad,True)
        with self.assertRaises(k.CadError):k.shell_solid(b,[top],15,True)

    def test_cut_that_splits_solid_gives_separate_bodies_and_union_merges(self):
        from rccad import history as hist
        base=Body('Belka',k.box(30,10,10),'solid').prepared()
        tool=k.transform(k.box(6,30,30),(12,-10,-10))
        out=hist.combine([base],[tool],'cut');solids=[b for b in out if b.kind=='solid']
        self.assertEqual(len(solids),2);self.assertEqual(solids[0].id,base.id);self.assertNotEqual(solids[1].id,base.id)
        self.assertAlmostEqual(sum(b.shape.Volume() for b in solids),30*10*10-6*10*10,2)
        self.assertEqual([b.id for b in hist.combine([base],[tool],'cut')],[b.id for b in out])      # powtarzalne identyfikatory (historia)
        joined=hist.run_bool(list(out),dict(op='union',base=solids[0].id,tools=[solids[1].id],keep=False))
        self.assertEqual(len([b for b in joined if b.kind=='solid']),1)

    def test_sweep_and_loft_volumes_and_errors(self):
        import cadquery as cq
        face=cq.Face.makeFromWires(k.sketch('circle','XY',10))
        line=lambda a,b:cq.Edge.makeLine(cq.Vector(*a),cq.Vector(*b))
        pipe=k.sweep_face(face,cq.Wire.assembleEdges([line((0,0,0),(0,0,30))]));self.assertAlmostEqual(pipe.Volume(),math.pi*25*30,1)
        bent=k.sweep_face(face,cq.Wire.assembleEdges([line((0,0,0),(0,0,20)),line((0,0,20),(20,0,20))]));self.assertGreater(bent.Volume(),math.pi*25*35)
        with self.assertRaises(k.CadError):k.path_wire(cq.Compound.makeCompound([]))
        bottom=k.sketch('rectangle','XY',10,10,0,0);top=k.sketch('rectangle',k.Frame((0,0,20),(1,0,0),(0,0,1)),6,6,0,0)
        for ruled in (True,False):
            self.assertAlmostEqual(k.loft_wires([bottom,top],None,ruled).Volume(),20/3*(100+36+60),1)
        self.assertAlmostEqual(k.loft_wires([bottom],(0,0,15)).Volume(),100*15/3,1)
        with self.assertRaises(k.CadError):k.loft_wires([bottom])

    def test_planar_faces_of_loft_and_sweep_are_recognised(self):
        import cadquery as cq
        bottom=k.sketch('rectangle','XY',10,10,0,0);top=k.sketch('rectangle',k.Frame((0,0,20),(1,0,0),(0,0,1)),6,6,0,0)
        loft=k.loft_wires([bottom,top])
        self.assertTrue(all(k.is_planar_face(f) for f in loft.Faces()))
        for f in loft.Faces():       # każda płaska ściana (także boczna, zapisana jako B-spline) daje się wskazać do szkicu i wyciągania
            c=f.Center();face,_=k.face_at(loft,f.normalAt().toTuple(),c.toTuple());self.assertAlmostEqual(face.Area(),f.Area(),3)
        pipe=k.sweep_face(cq.Face.makeFromWires(k.sketch('rectangle','XY',10,6,0,0)),cq.Wire.assembleEdges([cq.Edge.makeLine(cq.Vector(0,0,0),cq.Vector(0,0,30))]))
        for f in pipe.Faces():
            c=f.Center();k.face_at(pipe,f.normalAt().toTuple(),c.toTuple())
        round_loft=k.loft_wires([k.sketch('circle','XY',10,0,0,0),k.sketch('circle',k.Frame((0,0,20),(1,0,0),(0,0,1)),10,0,0)])
        self.assertEqual(sum(1 for f in round_loft.Faces() if k.is_planar_face(f)),2)      # tylko dwie podstawy, bok jest zakrzywiony

    def test_extrude_face_of_swept_ring_top(self):
        import cadquery as cq
        path=cq.Wire.makeEllipse(30,10,cq.Vector(0,0,0),cq.Vector(0,0,1),cq.Vector(1,0,0))
        profile=cq.Face.makeFromWires(k.sketch('rectangle',k.Frame((30,0,0),(1,0,0),(0,1,0)),4,6,0,0))
        ring=k.sweep_face(profile,path);self.assertGreater(ring.Volume(),0)
        top=max(ring.Faces(),key=lambda f:f.Center().z);self.assertTrue(k.is_planar_face(top))
        face,normal=k.face_at(ring,(0,0,1),top.Vertices()[0].toTuple())      # punkt na ścianie (środek pierścienia leży w otworze)
        area=face.Area();near=lambda got,want:self.assertAlmostEqual(got,want,delta=0.05*want)      # pole B-sklejanej ściany liczone jest przybliżenie
        up=k.extrude_face(face,normal,5);near(up.Volume(),area*5)
        down=k.extrude_face(face,normal,-2);near(down.Volume(),area*2)
        both=k.extrude_face(face,normal,3,2);near(both.Volume(),area*5)
        sym=k.extrude_face(face,normal,4,0,True);near(sym.Volume(),area*4)
        joined=k.boolean('union',ring,[up]);near(joined.Volume(),ring.Volume()+up.Volume())

    def test_invalid_dimensions(self):
        for x in (0,-1,float('nan'),float('inf')):
            with self.subTest(x=x),self.assertRaises(k.CadError):k.box(x,20,30)

    def test_quick_blend_preview_lies_on_the_exact_surface(self):
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
        from OCP.gp import gp_Pnt
        outer = k.box(20, 10, 8)
        notch = k.boolean('subtract', k.box(20, 20, 10), [k.box(10, 10, 10).translate((10, 10, 0))])
        inner = [i for i, e in enumerate(notch.Edges()) if e.geomType() == 'LINE' and abs(e.tangentAt(0).z) > .99
                 and abs(e.Center().x - 10) < 1e-6 and abs(e.Center().y - 10) < 1e-6]
        for shape, ids in ((outer, [0]), (notch, inner)):          # krawędź wypukła i wklęsła
            for kind in ('fillet', 'chamfer'):
                quick = k.quick_blend_mesh(shape, ids, 2, kind)
                made = k.compound(k.new_faces(shape, k.blend(shape, set(ids), 2, kind))).wrapped
                worst = max(BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex(), made).Value()
                            for p in quick.vertices)
                self.assertLess(worst, 1e-4, (kind, ids))
        round_edge = k.blend(outer, {0}, 2, 'fillet')
        curved = [i for i, e in enumerate(round_edge.Edges()) if e.geomType() != 'LINE']
        self.assertIsNone(k.quick_blend_mesh(round_edge, curved[:1], 1, 'fillet'))   # nieobsługiwana -> czeka na dokładny


    def test_trimmed_shapes_forming_one_outline_become_one_sketch(self):
        from rccad import history as h
        r = Body('Prostokąt', k.sketch('rectangle', 'XY', 20, 20), 'sketch', 'XY').prepared()
        c = Body('Okrąg', k.sketch('circle', 'XY', 8, 8).translate((10, 10, 0)), 'sketch', 'XY').prepared()
        b = h.run_trim([r, c], dict(type='trim', id=c.id, mid=(10 - 4 * .7071, 10 - 4 * .7071, 0), out=[]))
        b = h.run_trim(b, dict(type='trim', id=r.id, mid=(8, 10, 0), out=[]))
        self.assertEqual(len(b), 2)                                   # jeszcze otwarte: dwa szkice
        rid = next(x.id for x in b if x.name == 'Prostokąt')
        b = h.run_trim(b, dict(type='trim', id=rid, mid=(10, 8, 0), out=[]))
        self.assertEqual([x.name for x in b], ['Prostokąt'])          # zamknięty obrys: jeden szkic
        self.assertTrue(b[0].shape.IsClosed())
        import cadquery as cq
        self.assertAlmostEqual(cq.Face.makeFromWires(b[0].shape).Area(), 400 + 3 / 4 * math.pi * 16, 2)   # suma obu kształtów (okrąg o promieniu 4)

    def test_sketch_overhanging_a_face_splits_into_regions(self):
        from rccad import history as h
        box = Body('Kostka', k.box(20, 20, 10)).prepared()
        plane = k.Frame.from_dict(dict(origin=(10, 10, 10), normal=(0, 0, 1), xdir=(1, 0, 0)))
        circle = Body('Okrąg', k.sketch('circle', plane, 8, 8).translate((10, 0, 0)), 'sketch', plane).prepared()
        pl, members = list(h.sketch_groups([box, circle]).values())[0]
        self.assertEqual(len(h._group_regions(pl, members)), 1)                     # stare kroki: bez podziału
        parts = h._group_regions(pl, members, [box, circle])
        self.assertEqual(sorted(round(f.Area(), 2) for f in parts), [25.13, 25.13])  # na ścianie i poza nią
        outside = h.resolve_profile([box, circle], dict(k='region', plane=h.plane_to_json(pl), center=[22, 10, 10], split=1))
        self.assertAlmostEqual(outside['face'].Area(), 8 * math.pi, 2)
        self.assertLess(outside['face'].Center().x, 25)
        self.assertGreater(outside['face'].Center().x, 20)

    def test_each_text_and_each_pattern_is_its_own_group(self):
        # każdy osobno dodany napis i każdy nowy szyk to osobna grupa na liście obiektów - także przy tej samej treści
        from rccad import history as h
        plane = dict(origin=[0, 0, 0], xdir=[1, 0, 0], normal=[0, 0, 1])
        text = lambda out: dict(type='text', name='Tekst', plane=plane, out=out,
                                params=dict(text='Ab', anchor=[0, 0], size=5, font='Arial', bold=False, italic=False, angle=0))
        first = h.run_text([], text([]))
        both = h.run_text(first, text([]))
        folders = [b.folder for b in both]
        self.assertEqual(len(set(folders)), 2)
        self.assertEqual(set(folders), {'Tekst „Ab”', 'Tekst „Ab” (2)'})
        # zajęta jest też nazwa, po której zostały tylko wyciągnięte bryły („— bryły”)
        solids_left = [Body('W', k.box(1, 1, 1), folder='Tekst „Ab” — bryły')]
        self.assertEqual({b.folder for b in h.run_text(solids_left, text([])) if b.kind == 'sketch'}, {'Tekst „Ab” (2)'})
        s = Body('Szkic', k.sketch('rectangle', 'XY', 5, 5), 'sketch', 'XY').prepared()
        pat = lambda bodies, src: h.run_pattern(bodies, dict(type='pattern', id=src.id, kind='rect',
                                                             params=dict(counts=[3, 1, 1], spacing=[0, 10, 0]), join=False, out=[]))
        one = pat([s], s)
        copy = next(b for b in one if b.id != s.id)
        two = pat(one, copy)                                  # szyk z kopii poprzedniego szyku - nowa grupa
        self.assertEqual(sorted({b.folder for b in two}), ['Szkic — szyk', 'Szkic — szyk (2)'])
        self.assertEqual(next(b for b in two if b.id == copy.id).folder, 'Szkic — szyk')   # źródło zostaje w swojej grupie
        self.assertEqual(sum(b.folder == 'Szkic — szyk (2)' for b in two), 2)
        other = Body('Szkic', k.sketch('circle', 'XY', 3), 'sketch', 'XY').prepared()
        three = pat([*one, other], other)                     # inny obiekt o tej samej nazwie - też osobna grupa
        self.assertEqual(sum(b.folder == 'Szkic — szyk (2)' for b in three), 3)

    def test_pattern_separate_goes_to_folder_and_folder_step(self):
        from rccad import history as h
        s = Body('Szkic', k.sketch('rectangle', 'XY', 5, 5), 'sketch', 'XY').prepared()
        sep = h.run_pattern([s], dict(type='pattern', id=s.id, kind='rect', params=dict(counts=[3, 1, 1], spacing=[10, 0, 0]), join=False, out=[]))
        self.assertEqual({b.folder for b in sep}, {'Szkic — szyk'})
        one = h.run_pattern([s], dict(type='pattern', id=s.id, kind='rect', params=dict(counts=[3, 1, 1], spacing=[10, 0, 0]), join=False, out=[], group='ab12'))
        self.assertEqual({(b.folder, b.group) for b in one}, {('', 'ab12')})
        moved = h.run_folder(sep, dict(type='folder', ids=[sep[0].id], folder='Moje'))
        self.assertEqual([b.folder for b in moved], ['Moje', 'Szkic — szyk', 'Szkic — szyk'])
        doc = Document()
        doc.commit(moved)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'f.rccad'
            doc.save(path)
            again = Document.load(path) if hasattr(Document, 'load') else None
        if again is not None:
            self.assertEqual(sorted(b.folder for b in again.bodies), sorted(b.folder for b in moved))

    def test_all_edges_fillet_true_spherical_corners(self):
        s=k.box(30,30,30);r=k.blend(s,range(12),3)
        exact=24**3+6*24**2*3+3*math.pi*24*9+4*math.pi*27/3
        self.assertAlmostEqual(r.Volume(),exact,places=5)
        self.assertTrue(r.isValid())
        self.assertEqual(len(k.display_mesh(r).edges),0)
        self.assertAlmostEqual(s.Volume(),27000)  # Input is never changed.

    def test_chamfer(self):
        s=k.box(30,30,30);r=k.blend(s,[0],2,'chamfer')
        self.assertTrue(r.isValid());self.assertLess(r.Volume(),s.Volume())

    def test_bad_fillet_does_not_change_shape(self):
        s=k.box(10,10,10)
        with self.assertRaises(k.CadError):k.blend(s,[0],1000)
        self.assertAlmostEqual(s.Volume(),1000)

    def test_empty_and_invalid_edge_selection(self):
        for indices in ([],[-1],[999]):
            with self.subTest(indices=indices),self.assertRaises(k.CadError):k.blend(k.box(10,10,10),indices,1)

    def test_through_hole(self):
        self.assertAlmostEqual(k.hole(k.box(30,30,30),4,15,15).Volume(),27000-math.pi*16*30,places=5)

    def test_blind_hole(self):
        self.assertAlmostEqual(k.hole(k.box(30,30,30),4,15,15,10).Volume(),27000-math.pi*16*10,places=5)

    def test_hole_outside_rejected(self):
        with self.assertRaises(k.CadError):k.hole(k.box(30,30,30),4,200,200)

    def test_hole_then_all_roundings(self):
        s=k.hole(k.box(40,40,30),6,20,20)
        r=k.blend(s,range(len(s.Edges())),2)
        self.assertTrue(r.isValid());self.assertLess(r.Volume(),s.Volume())
        self.assertEqual(len(k.display_mesh(r).edges),0)

    def test_boolean_operations(self):
        a=k.box(10,10,10);b=k.box(10,10,10).translate((5,0,0))
        for op,volume in [('union',1500),('subtract',500),('intersect',500)]:
            with self.subTest(op=op):self.assertAlmostEqual(k.boolean(op,a,[b]).Volume(),volume,places=5)

    def test_non_intersecting_intersection_rejected(self):
        with self.assertRaises(k.CadError):k.boolean('intersect',k.box(10,10,10),[k.box(10,10,10).translate((100,0,0))])

    def test_sketch_and_extrude_all_planes(self):
        for plane in ('XY','XZ','YZ'):
            with self.subTest(plane=plane):
                wire=k.sketch('rectangle',plane,20,10)
                self.assertAlmostEqual(k.extrude(wire,plane,5).Volume(),1000,places=5)

    def test_circle_polygon_and_symmetric_extrusion(self):
        wire=k.sketch('circle','XY',10)
        s=k.extrude(wire,'XY',10,True)
        self.assertAlmostEqual(s.Volume(),math.pi*25*10,places=5)
        self.assertAlmostEqual(s.BoundingBox().zmin,-5)
        self.assertGreater(k.extrude(k.sketch('polygon','XY',10,sides=6),'XY',10).Volume(),0)

    def test_sketch_from_drag_uses_workplane_axes(self):
        for plane in ('XY','XZ','YZ'):
            with self.subTest(plane=plane):
                args=k.sketch_from_drag('rectangle',plane,10,20,40,50)
                box=k.bounds(k.sketch(**args))
                c0,c1=k.to_world(plane,10,20),k.to_world(plane,40,50)
                for got,want in zip((box.xmin,box.ymin,box.zmin),map(min,zip(c0,c1))):self.assertAlmostEqual(got,want,places=5)
                for got,want in zip((box.xmax,box.ymax,box.zmax),map(max,zip(c0,c1))):self.assertAlmostEqual(got,want,places=5)
        circle=k.sketch_from_drag('circle','XY',5,5,8,9)
        self.assertAlmostEqual(circle['width'],10)
        with self.assertRaises(k.CadError):k.sketch_from_drag('rectangle','XY',0,0,0,5)

    def test_edge_chain_follows_tangent_outline(self):
        plain=k.box(40,30,20)
        self.assertEqual(k.edge_chain(plain,0),{0})
        vertical=[i for i,e in enumerate(plain.Edges()) if abs(e.startPoint().z-e.endPoint().z)>10]
        rounded=k.blend(plain,vertical,5)
        top=[i for i,e in enumerate(rounded.Edges()) if abs(e.startPoint().z-20)<1e-6 and abs(e.endPoint().z-20)<1e-6]
        self.assertEqual(len(top),8)
        self.assertEqual(k.edge_chain(rounded,top[0]),set(top))

    def test_transform_and_mirror(self):
        a=k.box(10,20,30);b=k.transform(a,(2,3,4),(20,30,40));c=k.mirror(a,'YZ')
        self.assertAlmostEqual(a.Volume(),b.Volume(),places=5)
        self.assertAlmostEqual(a.Volume(),c.Volume(),places=5)
        self.assertLessEqual(c.BoundingBox().xmax,1e-6)

    def test_step_and_brep_roundtrip(self):
        a=k.blend(k.box(30,30,30),range(12),3)
        with tempfile.TemporaryDirectory() as directory:
            for ext in ('step','brep'):
                with self.subTest(ext=ext):
                    path=Path(directory)/('model.'+ext);k.export_shapes([a],path)
                    imported=k.import_shapes(path)
                    self.assertEqual(len(imported),1)
                    self.assertAlmostEqual(imported[0][0].Volume(),a.Volume(),places=4)

    def test_stl_export_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.stl';k.export_shapes([k.box(10,10,10)],path)
            imported=k.import_shapes(path)
            self.assertEqual(imported[0][1],'mesh')
            self.assertGreater(len(k.display_mesh(imported[0][0]).triangles),0)

    def test_exact_measurements_and_blind_hole_after_tessellation(self):
        shape=k.box(30,30,30);k.display_mesh(shape)
        bounds=k.bounds(shape)
        self.assertAlmostEqual(bounds.xlen,30,places=6)
        self.assertAlmostEqual(bounds.zmax,30,places=6)
        self.assertAlmostEqual(k.hole(shape,4,15,15,10).Volume(),27000-math.pi*16*10,places=5)

    def test_svg_import_removes_duplicate_outlines_keeping_shape(self):
        import tempfile, os
        from rccad import import2d
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
               '<path d="M10 10 L50 10 L50 50 L10 50 Z"/><path d="M10 10 L50 10 L50 50 L10 50 Z"/>'
               '<path d="M50 50 L10 50 L10 10 L50 10.01 L50 50"/><circle cx="70" cy="70" r="10"/><circle cx="70" cy="70" r="10"/></svg>')
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'a.svg')
            open(path, 'w').write(svg)
            wires = import2d.sketch_wires(path)
        self.assertEqual(len(wires), 2)                       # kwadrat (z kopiami) i koło (z kopią)
        self.assertEqual(sorted(round(w.Length(), 2) for w in wires), [62.83, 160.0])
        self.assertTrue(all(w.IsClosed() for w in wires))

    def test_dxf_sketch_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.dxf'
            k.export_shapes([k.sketch('rectangle','XY',20,10)],path)
            imported=k.import_shapes(path)
            self.assertEqual(len(imported),1)
            self.assertEqual(imported[0][1],'sketch')
            self.assertAlmostEqual(k.extrude(imported[0][0],'XY',5).Volume(),1000,places=4)

    def test_wire_display_has_edges(self):
        mesh=k.display_mesh(k.sketch('rectangle','XY',20,10))
        self.assertEqual(len(mesh.edges),4)


class DocumentTests(unittest.TestCase):
    def test_history_and_saved_revision(self):
        d=Document();a=Body('A',k.box(10,10,10)).prepared();d.commit([a])
        self.assertTrue(d.dirty);d.undo();self.assertFalse(d.bodies);self.assertFalse(d.dirty)
        d.redo();self.assertEqual(d.bodies[0].id,a.id)
        with tempfile.TemporaryDirectory() as directory:
            d.save(Path(directory)/'a.rccadx');self.assertFalse(d.dirty)
            d.commit([]);self.assertTrue(d.dirty);d.undo();self.assertFalse(d.dirty)

    def test_project_roundtrip_solid_and_sketch(self):
        d=Document();d.commit([Body('Bryła ą',k.box(10,10,10)).prepared(),Body('Szkic',k.sketch('circle','XY',10),'sketch').prepared()])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'a.rccadx';d.save(path);other=Document.load(path)
            self.assertEqual(other.bodies[0].name,'Bryła ą')
            self.assertEqual(other.bodies[0].id,d.bodies[0].id)
            self.assertEqual(other.bodies[1].kind,'sketch')
            self.assertFalse(other.dirty)
            self.assertAlmostEqual(other.bodies[0].shape.Volume(),1000)

    def test_project_saves_whole_history_and_reopens_at_current_step(self):
        d=Document();a=Body('A',k.box(10,10,10)).prepared();d.commit([a],'Pierwszy');b=Body('B',k.box(5,5,5)).prepared();d.commit([a,b],'Drugi')
        d.commit([a],'Trzeci');d.undo()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'h.rccadx';d.save(path);o=Document.load(path)
            self.assertEqual(o.timeline(),(['Początek','Pierwszy','Drugi','Trzeci'],2));self.assertEqual([x.name for x in o.bodies],['A','B'])
            self.assertAlmostEqual(o.bodies[1].shape.Volume(),125);o.redo();self.assertEqual(len(o.bodies),1);o.goto(0);self.assertFalse(o.bodies)
            o.goto(1);self.assertEqual(o.bodies[0].id,a.id);self.assertFalse(o.dirty and False)

    def test_history_recompute_through_pattern_chamfer_transform_mirror_bool(self):
        from dataclasses import replace as rep
        from rccad import history as h
        a=Body('A',k.box(10,10,10)).prepared();xmin=k.bounds(a.shape).xmin
        idx=[i for i,e in enumerate(a.shape.Edges()) if abs(e.positionAt(.5).toTuple()[0]-xmin)<1e-6][0]
        info=lambda r,i:{'label':i,'icon':i,'op':r}
        r_pat=dict(type='pattern',id=a.id,kind='rect',params=dict(counts=[2,1,1],spacing=[30,0,0]),join=False,out=['b'*32])
        r_mod=dict(type='mod',id=a.id,kind='chamfer',size=1,verts=[],edges=h.edge_refs(a.shape,[idx]))
        r_tr=dict(type='transform',id=a.id,mode='move',v=[0,0,5])
        r_mir=dict(type='mirror',id='b'*32,normal=[0,1,0],origin=[0,-5,0],keep=True,join=False,out='c'*32)
        r_bool=dict(type='bool',op='union',base=a.id,tools=['c'*32],keep=False)
        states=[((),{'label':'Początek','icon':'start'}),((a,),{'label':'A','icon':'file'})]
        for r in (r_pat,r_mod,r_tr,r_mir,r_bool):
            states.append((h.run_recipe(states[-1][0],r),info(r,r['type'])))
        wide=rep(a,shape=k.box(20,10,10),mesh=None).prepared()
        out,failed=h.recompute(states,1,(wide,));self.assertEqual(failed,0)
        final={b.id:b for b in out[-1][0]};self.assertNotIn('c'*32,final)          # narzędzie połączone i usunięte
        self.assertGreater(final[a.id].shape.Volume(),2000);self.assertAlmostEqual(final['b'*32].shape.Volume(),2000,2)
        base,_=h.toggle_step(states,3);vol=lambda st,i:{b.id:b for b in st[i][0]}[a.id].shape.Volume()
        self.assertTrue(base[3][1]['off']);self.assertAlmostEqual(vol(base,3),1000,2);self.assertAlmostEqual(vol(base,5),1000,2)     # bez fazy bryła ma pełną objętość
        gone,f2=h.delete_step(states,2);self.assertEqual((len(gone),f2),(len(states)-1,2))      # bez szyku odbicie i boolean nie mają obiektu: zostają oznaczone
        self.assertTrue(gone[-1][1].get('stale'))
        swapped,f3=h.move_step(states,3);self.assertEqual([i['icon'] for _,i in swapped[3:5]],['transform','mod'])
        mid=out[3][0];self.assertLess({b.id:b for b in mid}[a.id].shape.Volume(),2000)     # krok fazowania przeliczony na szerszej bryle

    def test_history_references_survive_resizing_of_the_base_body(self):
        import numpy as np
        from dataclasses import replace as rep
        from rccad import history as h
        a=Body('A',k.box(10,10,10)).prepared();xmin,ymin=k.bounds(a.shape).xmin,k.bounds(a.shape).ymin
        face,n=k.face_at(a.shape,(0,0,1),(5,5,10))
        src=dict(kind='face',id=a.id,face=face,normal=tuple(n),center=face.Center().toTuple(),hit=(5,5,10))
        r_ext=dict(type='extrude',mode='join',dir='one',d1=5,d2=0,profiles=h.describe_profiles([src],[a]),spent=[],out=[])
        idx=[i for i,e in enumerate(a.shape.Edges()) if abs(e.positionAt(.5).toTuple()[0]-xmin)<1e-6 and abs(e.positionAt(.5).toTuple()[1]-ymin)<1e-6][0]
        r_mod=dict(type='mod',id=a.id,kind='chamfer',size=1,verts=[],edges=h.edge_refs(a.shape,[idx]))
        corner=np.array([k.bounds(a.shape).xmax,k.bounds(a.shape).ymax,k.bounds(a.shape).zmax])
        r_vtx=dict(type='mod',id=a.id,kind='chamfer',size=2,verts=[corner.tolist()],vrefs=h.vertex_refs(a.shape,[corner]),edges=[])
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'file'})]
        for r in (r_ext,r_mod,r_vtx):states.append((h.run_recipe(states[-1][0],r),{'label':r['type'],'icon':r['type'],'op':r}))
        tall=rep(a,shape=k.box(10,10,20),mesh=None).prepared()
        out,failed=h.recompute(states,1,(tall,));self.assertEqual(failed,0)
        vol=out[2][0][0].shape.Volume();self.assertAlmostEqual(vol,2500,1)         # wyciągnięcie wskazało górną ścianę wyższej bryły
        self.assertLess(out[3][0][0].shape.Volume(),vol)                          # faza na właściwej krawędzi pionowej
        self.assertLess(out[4][0][0].shape.Volume(),out[3][0][0].shape.Volume())  # faza narożnika znalazła narożnik górnej ściany

    def test_dimension_constraints_follow_and_project_keeps_notes_groups_constraints(self):
        from dataclasses import replace as rep
        from rccad import history as h
        mk=lambda name,tool,pts:Body(name,k.sketch_shape(tool,'XY',pts,5),'sketch','XY',meta=dict(tool=tool,points=[list(p) for p in pts],sides=5)).prepared()
        a=mk('Prostokąt A','rect',[(0,0),(20,10)]);b=mk('Prostokąt B','rect',[(40,0),(50,5)])
        cons=[dict(a=a.id,ai=0,b=b.id,bi=0,k=1.0)]
        wide=mk('Prostokąt A','rect',[(0,0),(30,10)]);wide=rep(wide,id=a.id)
        out=h.apply_constraints((wide,b),cons);self.assertAlmostEqual(k.bounds(out[1].shape).xlen,30,3);self.assertAlmostEqual(k.bounds(out[1].shape).ylen,5,3)
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'sketch'}),((a,b),{'label':'B','icon':'sketch'})]
        new,failed=h.recompute(states,1,(wide,),cons);self.assertEqual(failed,0)
        self.assertAlmostEqual(k.bounds({x.id:x for x in new[2][0]}[b.id].shape).xlen,30,3)         # szkic B dogonił nowy wymiar A
        d=Document();d.commit([a],'A');d.commit([a,b],'B');d.constraints=cons;d.set_info(1,note='Pierwszy',group='Szkice')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'c.rccadx';d.save(path);o=Document.load(path)
            self.assertEqual(o.constraints,cons);infos=o.infos()[0];self.assertEqual((infos[1]['note'],infos[1]['group']),('Pierwszy','Szkice'))

    def test_trim_delete_sketchmeta_placement_and_fast_paths(self):
        from dataclasses import replace as rep
        from rccad import history as h
        mk=lambda name,tool,pts:Body(name,k.sketch_shape(tool,'XY',pts,5),'sketch','XY',meta=dict(tool=tool,points=[list(p) for p in pts],sides=5)).prepared()
        a=mk('A','rect',[(0,0),(20,10)]);c=mk('C','circle',[(0,0),(3,0)]);c=rep(c,id='d'*32)
        r_meta=dict(type='sketchmeta',id=a.id,meta=dict(tool='rect',points=[[0,0],[40,10]],sides=5))
        out=h.run_recipe((a,),r_meta);self.assertAlmostEqual(k.bounds(out[0].shape).xlen,40,3)
        gone=h.run_recipe((a,c),dict(type='delete',ids=[c.id]));self.assertEqual([b.id for b in gone],[a.id])
        placed=h.place_bodies((a,c),[c.id],(5,0,0),(0,0,0));self.assertAlmostEqual(k.bounds(placed[1].shape).xmin,2,3)
        self.assertAlmostEqual(k.bounds(placed[0].shape).xmin,0,3)                    # nietknięty obiekt zostaje
        steps0=[((),(a,)),((a,),(a,c)),((a,c),(a,c))]
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'sketch'}),((a,c),{'label':'C','icon':'sketch'}),(gone,{'label':'Del','icon':'trash','op':dict(type='delete',ids=[c.id])})]
        job={'cancel':False,'i':0,'n':0}
        out,failed=h.recompute(states,1,(a,),(),job);self.assertEqual(failed,0);self.assertEqual(job['n'],2)
        self.assertIs(out[1][0][0],a)                                        # nic się nie zmieniło: wynik z cache (te same obiekty)
        job={'cancel':True};
        with self.assertRaises(k.CadError):h.recompute(states,1,(a,),(),job)
        wide=rep(a,shape=k.box(5,5,5))
        out,failed=h.recompute(states,1,(wide,),());self.assertEqual(failed,0);self.assertEqual([b.id for b in out[-1][0]],[a.id])     # usunięcie przeniesione bez przeliczania
        d=Document();d.commit([a,c],'AC');d.commit([a],'Del')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'lazy.rccadx';d.save(path);d.undo();o=Document.load(path)
            self.assertTrue(all(b.mesh is not None for b in o.bodies));o.undo();self.assertTrue(all(b.mesh is not None for b in o.bodies))    # siatki liczone leniwie przy przeskoku

    def test_expressions_and_old_projects_with_variables_load_as_numbers(self):
        from rccad import history as h
        import json, zipfile
        self.assertAlmostEqual(h.evaluate('sqrt(w*w) / 2 + 1,5', {'w': 10}), 6.5)
        self.assertAlmostEqual(h.evaluate('cos(60)'), .5)
        for bad in ('__import__("os")', 'w.real', 'x + 1', '1/0', '[1]'):
            with self.assertRaises(k.CadError):h.evaluate(bad, {'w': 1})
        a=Body('A',k.box(10,10,10)).prepared()
        face,n=k.face_at(a.shape,(0,0,1),(5,5,10))
        src=dict(kind='face',id=a.id,face=face,normal=tuple(n),center=face.Center().toTuple(),hit=(5,5,10))
        r=dict(type='extrude',mode='join',dir='one',d1=20.0,d2=0,profiles=h.describe_profiles([src],[a]),spent=[],out=[])
        d=Document();d.commit([a],'A');d.commit(list(h.run_recipe(d.bodies,r)),'E',op=r)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'vars.rccadx';d.save(path)
            with zipfile.ZipFile(path) as z:items={i.filename:z.read(i.filename) for i in z.infolist()}
            m=json.loads(items['manifest.json']);self.assertNotIn('variables',m);self.assertNotIn('snapshots',m)
            m['variables']={'h':'20'};m['states'][-1]['op']['d1']={'expr':'h'}      # projekt ze starszej wersji (zmienne projektu)
            items['manifest.json']=json.dumps(m).encode()
            with zipfile.ZipFile(path,'w') as z:
                for name,data in items.items():z.writestr(name,data)
            o=Document.load(path)
        self.assertEqual(o.states()[-1][1]['op']['d1'],20.0)
        self.assertFalse(hasattr(o,'variables') or hasattr(o,'snapshots') or hasattr(o,'backup'))

    def test_sketch_on_face_follows_the_face_when_an_earlier_step_changes(self):
        from rccad import history as h
        a=Body('A',k.box(10,10,10)).prepared()
        frame=k.Frame((5.0,5.0,10.0),(1.0,0.0,0.0),(0.0,0.0,1.0))
        meta=dict(tool='circle',points=[[0,0],[2,0]],surface=dict(target=a.id,normal=[0,0,1]))
        sk=Body('S',h.meta_shape(frame,meta),'sketch',frame,meta=meta).prepared()
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'file'}),((a,sk),{'label':'S','icon':'sketch'})]
        taller=rep(a,shape=k.box(10,10,15))
        out,failed=h.recompute(states,1,(taller,),());self.assertEqual(failed,0)
        moved=next(b for b in out[-1][0] if b.id==sk.id)
        self.assertAlmostEqual(moved.plane.origin[2],15,6);self.assertAlmostEqual(k.bounds(moved.shape).zmax,15,6)
        self.assertEqual(moved.meta,sk.meta)
        self.assertEqual(h.reads(dict(type='extrude',profiles=[{'k':'surfacetext','group':'abc'}]),out[-1][0]),set())     # napis na powierzchni: bez błędu
        plain=dict(tool='circle',points=[[0,0],[2,0]])         # starszy projekt: szkic na płaskiej ścianie bez zapisanej ściany
        sk2=Body('S2',h.meta_shape(frame,plain),'sketch',frame,meta=plain).prepared()
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'file'}),((a,sk2),{'label':'S','icon':'sketch'})]
        out,failed=h.recompute(states,1,(taller,),());self.assertEqual(failed,0)
        self.assertAlmostEqual(next(b for b in out[-1][0] if b.id==sk2.id).plane.origin[2],15,6)
        frame_in=k.Frame((5.0,5.0,10.0),(1.0,0.0,0.0),(0.0,0.0,-1.0))                      # normalna w głąb bryły
        sk3=Body('S3',h.meta_shape(frame_in,plain),'sketch',frame_in,meta=plain).prepared()
        states=[((),{'label':'P','icon':'start'}),((a,),{'label':'A','icon':'file'}),((a,sk3),{'label':'S','icon':'sketch'})]
        out,failed=h.recompute(states,1,(taller,),())
        self.assertAlmostEqual(next(b for b in out[-1][0] if b.id==sk3.id).plane.origin[2],15,6)

    def test_hidden_surface_sketch_is_projected_only_when_shown(self):
        a=Body('A',k.box(10,10,10)).prepared()
        frame=k.Frame((5.0,5.0,10.0),(1.0,0.0,0.0),(0.0,0.0,1.0))
        from rccad import history as h
        meta=dict(tool='circle',points=[[0,0],[2,0]],surface=dict(target=a.id,normal=[0,0,1]))
        sk=Body('S',h.meta_shape(frame,meta),'sketch',frame,meta=meta,visible=False).prepared()
        d=Document();d.commit([a,sk])
        d.commit([rep(a,shape=k.box(10,10,10).translate((0,0,0))),sk])
        self.assertIn(sk.id,d.reproject)
        self.assertTrue(d.reprojected({sk.id}));self.assertNotIn(sk.id,d.reproject)

    def test_autosave_does_not_mark_saved(self):
        a=Body('A',k.box(10,10,10)).prepared();b=Body('B',k.box(5,5,5)).prepared()
        d=Document();d.commit([a],'A');d.commit([a,b],'B')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'v.rccadx';d.save(path);self.assertFalse(d.dirty)
            d.commit([a],'C');auto=Path(directory)/'v.autosave.rccadx';d.save(auto,mark=False)
            self.assertTrue(d.dirty);self.assertEqual(d.path,path)
            self.assertEqual(len(Document.load(auto).states()),4)

    def test_face_reference_prefers_extreme_face_after_resizing(self):
        from rccad import history as h
        import cadquery as cq
        def build(ha,hb):
            return cq.Workplane('XY').box(10,10,ha,centered=False).union(cq.Workplane('XY').box(10,10,hb,centered=False).translate((10,0,0))).val()
        old=Body('L',build(20,8)).prepared()
        face,n=k.face_at(old.shape,(0,0,1),(5,5,20))
        src=dict(kind='face',id=old.id,face=face,normal=tuple(n),center=face.Center().toTuple(),hit=(5,5,20))
        ref=h.describe_profiles([src],[old])[0]
        self.assertEqual(ref.get('extreme'),'max')
        new=build(30,22)       # plan: wieża A (x<10) jest teraz wyższa, a niższa wieża B ma wierzch bliżej starej wysokości
        matched,_=h.match_face(new,ref)
        self.assertLess(matched.Center().toTuple()[0],10);self.assertAlmostEqual(matched.Center().toTuple()[2],30,3)

    def test_constraints_inside_one_sketch_chains_and_cycles(self):
        from dataclasses import replace as rep
        from rccad import history as h
        mk=lambda name,tool,pts:Body(name,k.sketch_shape(tool,'XY',pts,5),'sketch','XY',meta=dict(tool=tool,points=[list(p) for p in pts],sides=5)).prepared()
        r=mk('R','rect',[(0,0),(30,10)]);b=mk('B','rect',[(40,0),(50,5)])
        cons=[dict(a=r.id,ai=1,b=b.id,bi=0,k=1.0),dict(a=r.id,ai=0,b=r.id,bi=1,k=.5)]      # kolejność „od końca”: łańcuch musi się ustalić
        out={x.id:x for x in h.apply_constraints((r,b),cons)}
        self.assertAlmostEqual(k.bounds(out[r.id].shape).ylen,15,3);self.assertAlmostEqual(k.bounds(out[b.id].shape).xlen,15,3)
        self.assertFalse(h.constraint_cycle(cons))
        self.assertTrue(h.constraint_cycle(cons+[dict(a=b.id,ai=0,b=r.id,bi=0,k=1.0)]))
        self.assertTrue(h.constraint_cycle([dict(a=r.id,ai=0,b=r.id,bi=1,k=1.0),dict(a=r.id,ai=1,b=r.id,bi=0,k=1.0)]))

    def test_text_extrusion_covers_whole_text_after_edit(self):
        from rccad import history as h
        try:k.text_shape('XY','AB',0,0,10)
        except Exception:self.skipTest('brak czcionki w środowisku')
        group=h.new_text_group();self.assertEqual(h.text_group_of(group+'00000000'),group)
        self.assertIsNone(h.text_group_of(__import__('uuid').uuid4().hex))
        def text(content,out):
            return dict(type='text',plane=h.plane_to_json('XY'),name='Tekst',out=out,params=dict(text=content,anchor=[0,0],size=10.0,font='Arial',bold=False,italic=False,angle=0.0))
        r1=text('AB',h.text_ids(group,2));bodies=h.run_recipe((),r1)
        self.assertTrue(all(h.text_group_of(b.id)==group for b in bodies))
        self.assertEqual([b.id for b in h.run_recipe((),dict(r1,params=dict(r1['params'],text='ABC')))][:2],[b.id for b in bodies][:2])      # stałe identyfikatory po zmianie treści
        members=[b for b in bodies];faces=h.material_regions('XY',members);self.assertTrue(faces);self.assertLessEqual(len(faces),len(h._group_regions('XY',members)))
        srcs=[dict(kind='region',id=None,face=f,wire=f.outerWire(),plane='XY',normal=(0,0,1),center=f.Center().toTuple()) for f in faces]
        specs=h.describe_profiles(srcs,bodies);self.assertEqual([x['k'] for x in specs],['textgroup'])
        ext=dict(type='extrude',mode='new',dir='one',d1=3.0,d2=0,profiles=specs,spent=[b.id for b in bodies],out=[])
        before=h.run_recipe(bodies,ext);vol=lambda bs:sum(b.shape.Volume() for b in bs if b.kind=='solid')
        longer=h.run_recipe((),dict(r1,params=dict(r1['params'],text='ABCD')))
        after=h.run_recipe(longer,ext)
        self.assertGreater(vol(after),vol(before));self.assertFalse(any(b.kind=='sketch' and b.visible for b in after))      # wszystkie litery (także nowe) wyciągnięte i wygaszone

    def test_corrupted_project(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.rccadx';path.write_bytes(b'not a zip')
            with self.assertRaises(k.CadError):Document.load(path)

    def test_failed_save_preserves_previous_file(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'a.rccadx';d=Document();d.save(path);before=path.read_bytes()
            d.commit([Body('A',k.box(10,10,10)).prepared()])
            with patch('rccad.document.cq.exporters.export',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):d.save(path)
            self.assertEqual(path.read_bytes(),before)
            self.assertTrue(d.dirty)


    def test_loft_side_faces_are_found(self):
        """Ściany boczne brył z wyciągnięcia złożonego (płaskie, ale zapisane jako B-sklejane) da się wskazać do szkicu i wyciągania."""
        import cadquery as cq
        def rect(w, h, z):
            return cq.Wire.makePolygon([cq.Vector(-w / 2, -h / 2, z), cq.Vector(w / 2, -h / 2, z), cq.Vector(w / 2, h / 2, z), cq.Vector(-w / 2, h / 2, z)], close=True)
        report = []
        for name, wires, ruled in (('2 profile', [rect(20, 20, 0), rect(10, 10, 20)], False), ('2 profile ruled', [rect(20, 20, 0), rect(10, 10, 20)], True),
                                   ('przesunięty', [rect(20, 20, 0), rect(14, 8, 25)], False), ('3 profile ruled', [rect(20, 20, 0), rect(12, 12, 10), rect(6, 6, 25)], True)):
            solid = k.loft_wires(wires, None, ruled)
            for face in solid.Faces():
                c = face.Center()
                planar = k.is_planar_face(face)
                found = None
                if planar:
                    n = face.normalAt().toTuple()
                    try:
                        found = k.face_at(solid, n, c.toTuple())[0].isSame(face)
                    except k.CadError:
                        found = False
                report.append((name, face.geomType(), planar, found))
        bad = [r for r in report if r[2] is False and r[0] != '3 profile ruled' or r[3] is False]
        self.assertFalse(bad, str(report))

    def test_twisted_loft_side_faces_use_tangent_plane(self):
        """Wyciągnięcie złożone przez różne czworokąty daje skręcone ściany boczne: da się je wskazać (płaszczyzna styczna w punkcie)."""
        import cadquery as cq
        import numpy as np
        quad = lambda pts, z: cq.Wire.makePolygon([cq.Vector(x, y, z) for x, y in pts], close=True)
        solid = k.loft_wires([quad([(0, 0), (60, 0), (62, 40), (-5, 35)], 0), quad([(10, 10), (50, 25), (40, 45), (0, 30)], 30)], None, False)
        report = []
        for face in solid.Faces():
            on = face.Center() if face.geomType() == 'PLANE' else face.positionAt(0.5, 0.5)
            pv = cq.Vector(on.x, on.y, on.z)
            n = face.normalAt(pv).toTuple()
            try:
                got, normal = k.face_at(solid, n, on.toTuple(), curved=True)
                report.append((face.geomType(), k.is_planar_face(face), bool(got.isSame(face)), round(float(face.distance(cq.Vertex.makeVertex(on.x, on.y, on.z))), 5)))
            except k.CadError as exc:
                report.append((face.geomType(), k.is_planar_face(face), 'ERR', str(exc), [round(f.distance(cq.Vertex.makeVertex(on.x, on.y, on.z)), 4) for f in solid.Faces()]))
        self.assertTrue(all(r[2] is True for r in report), str(report))

    def test_twisted_face_supporting_plane_cuts_whole_wall(self):
        """Płaszczyzna szkicu na skręconej ścianie przylega do niej od zewnątrz, więc wycięcie w głąb przechodzi przez całą ścianę."""
        import cadquery as cq
        import numpy as np
        quad = lambda pts, z: cq.Wire.makePolygon([cq.Vector(x, y, z) for x, y in pts], close=True)
        solid = k.loft_wires([quad([(0, 0), (60, 0), (62, 40), (-5, 35)], 0), quad([(10, 10), (50, 25), (40, 45), (0, 30)], 30)], None, False)
        for face in solid.Faces():
            if k.is_planar_face(face):
                continue
            on = face.positionAt(0.5, 0.5)
            normal = face.normalAt(cq.Vector(on.x, on.y, on.z)).toTuple()
            origin, n = k.supporting_plane(face, on.toTuple(), normal)
            V = np.asarray(k.display_mesh(face).vertices, float)
            self.assertLessEqual(float(((V - np.array(origin)) @ np.array(n)).max()), 1e-6)       # cała ściana po wewnętrznej stronie płaszczyzny
            self.assertGreater(float(np.array(n) @ np.array(normal)), 0.5)


if __name__=='__main__':unittest.main()


class SheetJoinTests(unittest.TestCase):
    def test_join_and_extension_is_stable(self):
        from rccad import sheetmetal as shm
        self.assertEqual([shm._nice_ceil(v) for v in (3, 10, 10.5, 21, 49, 51)], [5, 10, 20, 50, 50, 100])
        t = 1.0
        base = dict(o=[0, 0, 0], x=[1, 0, 0], y=[0, 1, 0], z=[0, 0, 1], lx=60, ly=40, lz=t)
        rules = dict(gap=.1, relief='none', relief_size=3, joint='sheet', miter=True, auto_corners=True, kfactor=.44)
        edges = [([60, 0, t], [60, 40, t], [1, 0, 0]), ([60, 40, t], [0, 40, t], [0, 1, 0])]
        flanges = [dict(kind='base', p0=a, p1=b, n=[0, 0, 1], m=m, r=1, angle=90, length=10) for a, b, m in edges]
        captured = []
        original = shm._join_sheet
        with unittest.mock.patch.object(shm, '_join_sheet', side_effect=lambda s, p: captured.append((s, list(p))) or original(s, p)):
            shm._BUILD_CACHE.clear(); shm._PARTS_CACHE.clear(); shm._OPS_CACHE.clear()
            shm.build_sheet(dict(base=base, t=t, flanges=flanges, rules=rules))
        shape, parts = max(captured, key=lambda c: len(c[1]))
        glued = shm._join_sheet(shape, parts)
        plain = k.boolean('union', shape, parts)
        self.assertLess(glued.cut(plain).Volume() + plain.cut(glued).Volume(), 1e-6)
        self.assertEqual(len(glued.Solids()), 1)
