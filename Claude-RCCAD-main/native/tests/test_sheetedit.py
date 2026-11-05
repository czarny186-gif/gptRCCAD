"""Edits survive unfold/refold, native history and project persistence."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
import cadquery as cq
import ezdxf
from rccad import kernel as k, sheetmetal as s, sheetedit as e, history as h
from rccad.document import Body, Document


def recipe(angle=90):
    return dict(base=dict(o=[0,0,0],x=[1,0,0],y=[0,1,0],z=[0,0,1],lx=100,ly=50,lz=2),t=2,
                flanges=[dict(kind='base',p0=[100,0,2],p1=[100,50,2],n=[0,0,1],m=[1,0,0],r=2,angle=angle,length=20)],
                rules=dict(joint='sheet',gap=.2,kfactor=.44))


def cylinder(x,y,r=1):
    return cq.Solid.makeCylinder(r,6,cq.Vector(x,y,-2))


class SheetEditTests(unittest.TestCase):
    def assertSame(self,left,right,tol=2e-5):
        self.assertTrue(left.isValid());self.assertTrue(right.isValid())
        self.assertLess(abs(left.cut(right).Volume(1e-9))+abs(right.cut(left).Volume(1e-9)),tol)

    def test_development_thickness_allowance_and_no_edit_roundtrip(self):
        for angle in (45,90,135):
            with self.subTest(angle=angle):
                r=recipe(angle);l=e.layout(r)
                allowance=math.radians(angle)*2.88
                self.assertAlmostEqual(l.flat.Volume(1e-9),10000+50*2*(20+allowance),delta=1e-4)
                self.assertAlmostEqual(l.flat.BoundingBox().zlen,2,delta=1e-5)
                folded,_=e.switch(l.flat,e.state(r,True),False)
                self.assertSame(folded,l.folded)

    def test_native_sketch_extrusion_preserves_sheet_identity(self):
        r=recipe();l=e.layout(r)
        body=Body('Blacha',l.flat,meta={'sheet':e.state(r,True)}).prepared()
        sketch=Body('Otwór',cq.Workplane('XY').center(25,25).circle(1).val(),'sketch','XY').prepared()
        op=dict(type='extrude',mode='cut',dir='one',d1=6,d2=0,
                profiles=[dict(k='sketch',id=sketch.id)],spent=[sketch.id],out=[])
        cut=h.run_recipe([body,sketch],op)
        edited=next(b for b in cut if b.id==body.id)
        self.assertTrue(edited.meta['sheet']['dirty'])
        folded=h.run_recipe(cut,dict(type='sheetmode',id=body.id,state=e.state(r),flat=False))
        self.assertEqual(k.point_state(next(b for b in folded if b.id==body.id).shape,(25,25,1)),'out')

    def test_downward_bend_maps_flange_hole_to_the_correct_side(self):
        r=recipe();r['flanges'][0].update(p0=[100,0,0],p1=[100,50,0],n=[0,0,-1])
        l=e.layout(r);x=100+math.pi/2*2.88+10
        modified=l.flat.cut(cylinder(x,25))
        folded,st=e.switch(modified,e.state(r,True),False)
        self.assertEqual(k.point_state(folded,(103,25,-12)),'out')
        restored,_=e.switch(folded,st,True)
        self.assertSame(modified,restored)

    def test_rotated_translated_sheet_keeps_development_and_hole_geometry(self):
        import numpy as np
        r=recipe(135);original=e.layout(r)
        axis=np.array([1,2,3])/math.sqrt(14);angle=math.radians(37)
        cross=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
        rotation=np.eye(3)*math.cos(angle)+(1-math.cos(angle))*np.outer(axis,axis)+math.sin(angle)*cross
        move=np.array([10000,-20000,30000])
        transformed=copy.deepcopy(r)
        transformed['base']['o']=(rotation@np.array(r['base']['o'])+move).tolist()
        for key in ('x','y','z'):transformed['base'][key]=(rotation@np.array(r['base'][key])).tolist()
        for spec in transformed['flanges']:
            for key in ('p0','p1'):spec[key]=(rotation@np.array(spec[key])+move).tolist()
            for key in ('n','m'):spec[key]=(rotation@np.array(spec[key])).tolist()
        rotated=e.layout(transformed)
        self.assertSame(rotated.flat,original.flat,tol=1e-4)
        modified=rotated.flat.cut(cylinder(25,25))
        folded,st=e.switch(modified,e.state(transformed,True),False)
        self.assertEqual(k.point_state(folded,rotation@np.array([25,25,1])+move),'out')
        restored,_=e.switch(folded,st,True)
        self.assertSame(modified,restored,tol=1e-4)

    def test_multilevel_boxes_preserve_base_edits(self):
        from test_sheetmetal_boxes import box_recipe
        for joint,turn in [('sheet','in'),('sheet','out'),('diagonal','in'),('diagonal','out')]:
            with self.subTest(joint=joint,turn=turn):
                r=box_recipe(turn,'out',joint);l=e.layout(r)
                modified=l.flat.cut(cylinder(25,25))
                folded,st=e.switch(modified,e.state(r,True),False)
                self.assertTrue(folded.isValid());self.assertEqual(len(folded.Solids()),1)
                restored,_=e.switch(folded,st,True)
                self.assertSame(modified,restored,tol=5e-5)

    def test_parallel_multilevel_box_develops_without_detached_material(self):
        from test_sheetmetal_boxes import box_recipe
        r=box_recipe('in','out','parallel');flat=e.layout(r).flat
        self.assertEqual(len(flat.Solids()),1)
        self.assertEqual(sum(len(face.innerWires()) for face in flat.Faces() if face.normalAt().z>.99),0)

    def test_legacy_parallel_project_migrates_without_losing_holes(self):
        from test_sheetmetal_boxes import box_recipe
        r=box_recipe('in','out','parallel')
        legacy=s.build_sheet(r,parallel_version=1);tool=cylinder(25,25)
        edited=legacy.cut(tool);source=e.state(r);source.pop('bend_engine');source['dirty']=True
        blank,st=e.switch(edited,source,True)
        self.assertEqual(st['bend_engine'],4);self.assertEqual(len(blank.Solids()),1)
        folded,st=e.switch(blank,st,False)
        self.assertSame(folded,s.build_sheet(r).cut(tool),tol=1e-4)
        updated=copy.deepcopy(r);updated['rules']['gap']=.3
        rebuilt,st=e.rebuild(edited,source,updated)
        self.assertEqual(st['bend_engine'],4)
        self.assertSame(rebuilt,s.build_sheet(updated).cut(tool),tol=1e-4)

    def test_holes_on_flat_base_and_flange_retain_positions_over_repeated_cycles(self):
        r=recipe();l=e.layout(r);allowance=math.pi/2*2.88
        modified=l.flat.cut(cylinder(25,25)).cut(cylinder(100+allowance+10,25))
        source=e.state(r,True)
        for _ in range(3):
            folded,source=e.switch(modified,source,False)
            self.assertEqual(k.point_state(folded,(25,25,1)),'out')
            self.assertEqual(k.point_state(folded,(103,25,14)),'out')
            self.assertEqual(k.point_state(folded,(103,30,14)),'in')
            flat,source=e.switch(folded,source,True)
            self.assertSame(flat,modified)

    def test_folded_wall_edits_and_added_material_are_preserved(self):
        r=recipe();l=e.layout(r)
        bore=cq.Solid.makeCylinder(1,8,cq.Vector(99,25,14),cq.Vector(1,0,0))
        pad=cq.Solid.makeBox(3,4,4,cq.Vector(104,10,10))
        modified=l.folded.cut(bore).fuse(pad).clean()
        flat,st=e.switch(modified,e.state(r),True)
        self.assertLess(flat.BoundingBox().zmin,-2.99)
        restored,st=e.switch(flat,st,False)
        self.assertSame(modified,restored)
        synced,_=e.switch(restored,st,False,sync=True)
        self.assertSame(synced,modified)

    def test_rounded_free_corner_survives_bending(self):
        r=recipe();l=e.layout(r);tip=100+math.pi/2*2.88+20
        index=next(i for i,edge in enumerate(l.flat.Edges()) if abs(edge.Center().x-tip)<1e-5 and
                   abs(edge.Center().y)<1e-5 and abs(edge.Length()-2)<1e-5)
        modified=k.blend(l.flat,[index],1)
        folded,st=e.switch(modified,e.state(r,True),False)
        restored,_=e.switch(folded,st,True)
        self.assertSame(modified,restored)
        self.assertLess(folded.Volume(),l.folded.Volume())

    def test_through_hole_in_bend_survives_cylindrical_mapping(self):
        r=recipe();l=e.layout(r);x=100+math.pi/4*2.88
        modified=l.flat.cut(cylinder(x,25,.5))
        folded,st=e.switch(modified,e.state(r,True),False)
        self.assertEqual(k.point_state(folded,(100+3/math.sqrt(2),25,4-3/math.sqrt(2))),'out')
        restored,st=e.switch(folded,st,True)
        self.assertSame(modified,restored)

    def test_slot_crossing_base_bend_and_leg_is_not_split_or_lost(self):
        r=recipe();l=e.layout(r);allowance=math.pi/2*2.88
        tool=cq.Solid.makeBox(allowance+2,4,6,cq.Vector(99,23,-2))
        modified=l.flat.cut(tool)
        folded,st=e.switch(modified,e.state(r,True),False)
        self.assertEqual(k.point_state(folded,(99.5,25,1)),'out')
        self.assertEqual(k.point_state(folded,(100+3/math.sqrt(2),25,4-3/math.sqrt(2))),'out')
        self.assertEqual(k.point_state(folded,(103,25,4.5)),'out')
        restored,_=e.switch(folded,st,True)
        self.assertSame(modified,restored)

    def test_partial_thickness_bend_pocket_is_rejected_without_mutation(self):
        r=recipe();l=e.layout(r);x=100+math.pi/4*2.88
        modified=l.flat.cut(cq.Solid.makeCylinder(.5,1,cq.Vector(x,25,1)))
        original_volume=modified.Volume()
        with self.assertRaisesRegex(k.CadError,'gruboś'):
            e.switch(modified,e.state(r,True),False)
        self.assertAlmostEqual(modified.Volume(),original_volume,delta=1e-8)
        self.assertTrue(modified.isValid())

    def test_new_flange_and_rules_do_not_erase_existing_holes(self):
        r=recipe();base=copy.deepcopy(r);base['flanges']=[]
        plain=s.build_sheet(base);modified=plain.cut(cylinder(25,25))
        source=e.state(base);source['dirty']=True
        folded,source=e.rebuild(modified,source,r)
        self.assertEqual(k.point_state(folded,(25,25,1)),'out')
        updated=copy.deepcopy(r);updated['rules']['kfactor']=.35
        changed,source=e.rebuild(folded,source,updated)
        self.assertEqual(k.point_state(changed,(25,25,1)),'out')
        self.assertTrue(source['edited'])

    def test_solid_edit_metadata_history_undo_and_save_load(self):
        r=recipe();body=Body('Blacha',s.build_sheet(r),meta={'sheet':e.state(r)}).prepared()
        doc=Document();doc.commit([body])
        op=dict(type='sheetmode',id=body.id,state=e.state(r),flat=True)
        flat=h.run_recipe(doc.bodies,op)[0];doc.commit([flat],op=op)
        edited=flat.changed(flat.shape.cut(cylinder(25,25)))
        self.assertTrue(edited.meta['sheet']['dirty']);self.assertFalse(flat.meta['sheet']['dirty'])
        doc.commit([edited],label='Otwór')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sheet.rccadx';doc.save(path);loaded=Document.load(path)
            self.assertTrue(loaded.bodies[0].meta['sheet']['flat'])
            folded=h.run_recipe(loaded.bodies,dict(type='sheetmode',id=body.id,state=e.state(r),flat=False))[0]
            self.assertEqual(k.point_state(folded.shape,(25,25,1)),'out')
            loaded.undo();loaded.undo();self.assertFalse(loaded.bodies[0].meta['sheet']['flat'])
            loaded.redo();self.assertTrue(loaded.bodies[0].meta['sheet']['flat'])

    def test_edited_dxf_preserves_circle_and_mm_units(self):
        r=recipe();l=e.layout(r);modified=l.flat.cut(cylinder(25,25,2))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'laser.dxf';e.export_dxf(modified,e.state(r,True),path)
            dxf=ezdxf.readfile(path)
            self.assertEqual(dxf.units,4);self.assertFalse(dxf.audit().has_errors)
            circles=list(dxf.modelspace().query('CIRCLE[layer=="CUT"]'))
            self.assertEqual(len(circles),1);self.assertAlmostEqual(circles[0].dxf.radius,2,delta=1e-7)
            self.assertAlmostEqual(circles[0].dxf.center.x,25,delta=1e-7)
            self.assertEqual(len(dxf.modelspace().query('LINE[layer=="BEND_UP"]')),1)
            from test_sheetmetal_boxes import box_recipe
            box=box_recipe('in','out','sheet');blank=e.layout(box).flat
            e.export_dxf(blank,e.state(box,True),path)
            complex_dxf=ezdxf.readfile(path)
            self.assertFalse(complex_dxf.audit().has_errors)
            self.assertGreater(len(complex_dxf.modelspace().query('SPLINE[layer=="CUT"]')),0)

    def test_dxf_bend_lines_stay_inside_cut_outline(self):
        from test_sheetmetal_boxes import box_recipe
        box=box_recipe('in','out','sheet');blank=e.layout(box).flat
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'box.dxf';e.export_dxf(blank,e.state(box,True),path)
            msp=ezdxf.readfile(path).modelspace()
            outline=cq.importers.importDXF(str(path),include=['CUT']).faces().vals();self.assertTrue(outline)
            bends=list(msp.query('LINE[layer=="BEND_UP"]'))+list(msp.query('LINE[layer=="BEND_DOWN"]'));self.assertEqual(len(bends),12)
            shorter=0
            for line in bends:
                a,b=line.dxf.start,line.dxf.end
                for t in (0,.25,.5,.75,1):
                    q=cq.Vertex.makeVertex(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t,0)
                    self.assertLess(min(f.distance(q) for f in outline),1e-4)
                shorter+=math.hypot(b.x-a.x,b.y-a.y)<50-1e-3
            self.assertGreater(shorter,0)      # ukosy w narożnikach skracają skrajne linie gięcia
        line=s.clip_line_to_faces((-10,5,0),(30,5,0),[cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(0,0,0),cq.Vector(20,0,0),cq.Vector(20,10,0),cq.Vector(0,10,0)],close=True))])
        self.assertEqual(len(line),1);self.assertAlmostEqual(line[0][0][0],0,6);self.assertAlmostEqual(line[0][1][0],20,6)

    def test_nonuniform_dxf_is_rejected_atomically(self):
        r=recipe();l=e.layout(r);modified=l.flat.cut(cq.Solid.makeCylinder(2,1,cq.Vector(25,25,1)))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'laser.dxf';path.write_text('previous')
            with self.assertRaisesRegex(k.CadError,'gruboś'):e.export_dxf(modified,e.state(r,True),path)
            self.assertEqual(path.read_text(),'previous')


class ParallelReliefMigrationTests(unittest.TestCase):
    def test_four_level_blank_and_old_engine_edits_survive_refolding(self):
        from test_sheetmetal_parallel import four_level_box
        r=four_level_box();original=s.build_sheet(r)
        model=e.layout(r)
        self.assertTrue(model.flat.isValid());self.assertEqual(len(model.flat.Solids()),1)
        tool=cylinder(25,25);legacy=s.build_sheet(r,parallel_version=2).cut(tool)
        source=e.state(r);source.update(bend_engine=2,dirty=True)
        flat,st=e.switch(legacy,source,True)
        self.assertEqual(st['bend_engine'],4)
        folded,st=e.switch(flat,st,False)
        self.assertLess(folded.cut(original.cut(tool)).Volume(1e-9)+original.cut(tool).cut(folded).Volume(1e-9),1e-4)


class BendDirectionFromPickedFaceTests(unittest.TestCase):
    """Wybrana przy konwersji ściana jest górą blachy: ścianki w górę nad nią to gięcia UP (na rysunku linia ciągła)
    - niezależnie od proporcji płyty i kolejności jej wierzchołków."""

    def test_walls_up_are_bend_up_for_any_plate_proportions(self):
        for size in ((100,50,2),(50,100,2),(40,40,2)):
            plate=k.box(*size)
            top=next(f for f in plate.Faces() if abs(f.Center().z-size[2])<1e-6)
            base=s.sheet_of_face(plate,top)['base']
            self.assertGreater(base['z'][2],.99,size)
            lx,ly=size[0],size[1]
            r=dict(base=base,t=2,rules={},flanges=[dict(kind='base',p0=[lx,0,2],p1=[lx,ly,2],n=[0,0,1],m=[1,0,0],r=2,angle=90,length=15)])
            folded=s.build_sheet(r);self.assertGreater(folded.BoundingBox().zmax,10,size)      # ścianka w górę
            flat,fs=e.switch(folded,e.state(r,False),True)
            self.assertEqual([l['direction'] for l in e.flat_bend_lines(flat,fs)],['UP'],size)
