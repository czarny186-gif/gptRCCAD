"""Four-edge hems on either skin, joint rules and reversible sheet editing."""
import copy
from pathlib import Path
import tempfile
import unittest
import cadquery as cq
import ezdxf
from rccad import sheetmetal as s,sheetedit as e,kernel as k
from rccad.document import Body,Document


def hem_recipe(joint='parallel',down=False,tip=False):
    z=0 if down else 1;n=[0,0,-1 if down else 1]
    edges=[([100,0,z],[100,50,z],[1,0,0]),([100,50,z],[0,50,z],[0,1,0]),
           ([0,50,z],[0,0,z],[-1,0,0]),([0,0,z],[100,0,z],[0,-1,0])]
    specs=[dict(kind='base',p0=a,p1=b,n=n,m=m,r=1,angle=90,length=10) for a,b,m in edges]
    if tip:
        specs += [dict(kind='tip',parent=i,side='out',r=1,angle=90,length=3,hem=dict(gap=.2,ret=3)) for i in range(4)]
    else:
        for f in specs:f['hem']=dict(gap=.2,ret=5)
    return dict(base=dict(o=[0,0,0],x=[1,0,0],y=[0,1,0],z=[0,0,1],lx=100,ly=50,lz=1),t=1,flanges=specs,rules=dict(joint=joint,gap=.2))


class HemSheetTests(unittest.TestCase):
    def same(self,a,b):
        self.assertLess(a.cut(b).Volume(1e-9)+b.cut(a).Volume(1e-9),1e-4)

    def test_four_top_and_bottom_hems_build_one_edge_at_a_time_in_both_modes(self):
        for joint in ('parallel','sheet'):
            for down in (False,True):
                r=hem_recipe(joint,down)
                for count in range(1,5):
                    with self.subTest(joint=joint,down=down,count=count):
                        shape=s.build_sheet(dict(r,flanges=r['flanges'][:count]))
                        self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
                flat,st=e.switch(shape,e.state(r),True)
                self.assertTrue(flat.isValid());self.assertEqual(len(flat.Solids()),1)
                restored,_=e.switch(flat,st,False);self.same(shape,restored)
                bb=k.bounds(shape)
                self.assertAlmostEqual(bb.zmin if down else bb.zmax,-1.2 if down else 2.2,delta=1e-5)

    def test_zero_joint_gap_on_two_mm_sheet_has_no_development_overlap(self):
        for joint in ('parallel','sheet'):
            r=hem_recipe(joint);r['base']['lz']=r['t']=2;r['rules']['gap']=0
            for f in r['flanges']:
                f['p0'][2]=f['p1'][2]=2
            self.assertEqual(len(e.layout(r).flat.Solids()),1)

    def test_hem_frames_use_actual_radius_and_split_exact_bend_and_return(self):
        r=hem_recipe();r['flanges']=r['flanges'][:1]
        frames,_=s._effective(r['flanges'],1,True);f=frames[0]
        self.assertAlmostEqual(f['r'],.1);self.assertEqual(f['angle'],180)
        pieces=s._flange_parts(f,1);self.assertEqual(len(pieces),2)
        exact=s.hem_solid(f['p0'],f['p1'],1,f['n'],f['m'],1,5,.2)
        self.same(pieces[0].fuse(pieces[1]),exact)
        import math
        flat_bend=e.layout(r).flat_bends[0]
        self.assertAlmostEqual(flat_bend.Volume(1e-9),50*math.pi*(.1+s.K_DEFAULT),delta=1e-5)

    def test_hem_return_seams_follow_the_selected_joint_style(self):
        for joint in ('parallel','sheet'):
            r=hem_recipe(joint);frames,corners=s._effective(r['flanges'],1,True)
            parts=s._corner_parts(r,frames,corners)
            diagonal=any(abs(face.normalAt().x)>1e-5 and abs(face.normalAt().y)>1e-5
                         for pieces in parts.values() for piece in pieces for face in piece.Faces()
                         if face.geomType()=='PLANE')
            self.assertEqual(diagonal,joint=='sheet')

    def test_four_flange_tip_hems_unfold_for_both_faces_and_joint_modes(self):
        for joint in ('parallel','sheet'):
            for down in (False,True):
                with self.subTest(joint=joint,down=down):
                    r=hem_recipe(joint,down,True);shape=s.build_sheet(r)
                    flat,st=e.switch(shape,e.state(r),True)
                    self.assertTrue(flat.isValid());self.assertEqual(len(flat.Solids()),1)
                    folded,_=e.switch(flat,st,False);self.same(shape,folded)

    def test_flat_return_and_bend_holes_survive_repeated_refolding(self):
        for joint in ('parallel','sheet'):
            with self.subTest(joint=joint):
                r=hem_recipe(joint);model=e.layout(r);flat=model.flat
                points=[model.panels[1].flat.Center(),model.flat_bends[0].Center()]
                for p in points:flat=flat.cut(cq.Solid.makeCylinder(.15,3,cq.Vector(p.x,p.y,-1)))
                st=e.state(r,True)
                for cycle in range(2):
                    folded,fs=e.switch(flat,st,False)
                    restored,st=e.switch(folded,fs,True)
                    self.same(flat,restored);flat=restored

    def test_folded_return_edit_native_save_and_dxf_keep_the_hem(self):
        r=hem_recipe();model=e.layout(r);p=model.panels[1].folded.Center()
        tool=cq.Solid.makeCylinder(.3,1.1,cq.Vector(p.x,p.y,p.z-.55))
        edited=model.folded.cut(tool);flat,st=e.switch(edited,e.state(r),True)
        body=Body('Zawinięta blacha',flat,meta={'sheet':st}).prepared();doc=Document();doc.commit([body])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'hem.rccadx';doc.save(path);loaded=Document.load(path).bodies[0]
            folded,fs=e.switch(loaded.shape,loaded.meta['sheet'],False);self.same(folded,edited)
            dxf=Path(tmp)/'hem.dxf';e.export_dxf(folded,fs,dxf);data=ezdxf.readfile(dxf)
            self.assertFalse(data.audit().has_errors)
            self.assertEqual(len(data.modelspace().query('LINE[layer=="BEND_UP"]'))+len(data.modelspace().query('LINE[layer=="BEND_DOWN"]')),4)

    def test_bottom_normals_do_not_flip_when_hems_move_the_centroid(self):
        r=hem_recipe(down=True)
        for f in r['flanges']:f['hem']['ret']=30
        r['flanges']=r['flanges'][:3];shape=s.build_sheet(r)
        self.assertLess(shape.Center().z,0)
        edge=next(edge for edge in shape.Edges() if edge.geomType()=='LINE' and abs(edge.Center().y)<1e-6 and abs(edge.Center().z)<1e-6 and edge.Length()>20)
        n,m=s.edge_side(shape,edge,1)
        self.assertLess(n[2],-.99)
        picked=s.spec_for_edge(r['base'],1,r['flanges'],r['rules'],[50,0,0],.01)
        self.assertLess(picked['n'][2],-.99)

    def test_a_hem_can_share_a_corner_with_an_ordinary_flange_and_have_a_child(self):
        for joint in ('parallel','sheet'):
            r=hem_recipe(joint)
            for f in r['flanges'][1:]:f.pop('hem')
            r['flanges'].append(dict(kind='tip',parent=0,side='out',r=.5,angle=45,length=3))
            shape=s.build_sheet(r);self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
            self.assertTrue(e.layout(r).flat.isValid())
