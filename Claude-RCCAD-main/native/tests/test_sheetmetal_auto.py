"""Automatic neighbour fitting, maximum hem returns and mixed corner regressions."""
import copy
import unittest
import cadquery as cq
from rccad import sheetmetal as s,sheetedit as e,kernel as k
from test_sheetmetal_hems import hem_recipe
from test_sheetmetal_parallel import small_box
from test_sheetmetal_boxes import box_recipe


def partial_box():
    edges=[([0,100,1],[0,0,1],[-1,0,0]),([100,0,1],[100,100,1],[1,0,0]),
           ([100,100,1],[0,100,1],[0,1,0]),([0,0,1],[100,0,1],[0,-1,0])]
    flanges=[dict(kind='base',p0=a,p1=b,n=[0,0,1],m=m,r=.6,angle=90,length=5,measure='outer') for a,b,m in edges]
    flanges += [dict(kind='tip',parent=i,side='in',r=.6,angle=90,length=5,measure='outer') for i in range(3)]
    flanges += [dict(kind='tip',parent=i+4,side='out',r=.6,angle=90,length=5,measure='outer') for i in range(2)]
    return dict(base=dict(o=[0,0,0],x=[1,0,0],y=[0,1,0],z=[0,0,1],lx=100,ly=100,lz=1),t=1,flanges=flanges,
                rules=dict(joint='parallel',gap=.2,relief='square',relief_size=1,miter=False,auto_corners=True))


class AutomaticSheetTests(unittest.TestCase):
    def same(self,a,b):
        self.assertLess(a.cut(b).Volume(1e-9)+b.cut(a).Volume(1e-9),1e-4)

    def roundtrip(self,r):
        shape=s.build_sheet(r);self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
        flat,st=e.switch(shape,e.state(r),True)
        self.assertTrue(flat.isValid());self.assertEqual(len(flat.Solids()),1)
        folded,_=e.switch(flat,st,False);self.same(shape,folded)
        return shape

    def test_partial_measured_box_keeps_square_ends_and_builds_every_prefix(self):
        r=partial_box();before=copy.deepcopy(r)
        for count in range(1,len(r['flanges'])+1):
            with self.subTest(count=count):
                shape=s.build_sheet(dict(r,flanges=r['flanges'][:count]));self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)
        normalized=s.normalize(r);self.assertEqual(normalized,s.normalize(normalized));self.assertEqual(r,before)
        self.assertTrue(normalized['rules']['miter']);self.assertFalse(r['rules']['miter'])
        frames,corners=s._effective(normalized['flanges'],1,True)
        for version,first in ((5,(1.2,98.8)),(s.ENGINE,(0,100))):      # 6: pierwsza ściana przechodzi do zewnętrznej powierzchni (zamknięty narożnik)
            parts=s._corner_parts(normalized,frames,corners,parallel_version=version)
            bounds=k.bounds(parts[0][1]);self.assertAlmostEqual(bounds.ymin,first[0],delta=1e-6);self.assertAlmostEqual(bounds.ymax,first[1],delta=1e-6)
            for i in (4,7):
                bounds=k.bounds(parts[i][1]);self.assertAlmostEqual(bounds.ymin,1.2,delta=1e-6);self.assertAlmostEqual(bounds.ymax,98.8,delta=1e-6)
        bounds=k.bounds(self.roundtrip(r));self.assertAlmostEqual(bounds.xlen,100,delta=1e-5);self.assertAlmostEqual(bounds.zmax,9,delta=1e-5)

    def test_hem_returns_fit_the_parent_for_both_sides_and_styles(self):
        for joint in ('parallel','sheet'):
            for side in ('in','out'):
                r=hem_recipe(joint,tip=True);r['rules']['auto_corners']=True
                for f in r['flanges'][:4]:f['length']=5
                for f in r['flanges'][4:]:f['side']=side;f['hem']['ret']=10
                before=copy.deepcopy(r);normalized=s.normalize(r)
                self.assertEqual([f['hem']['ret'] for f in normalized['flanges'][4:]],[5]*4)
                self.roundtrip(r);self.assertEqual(r,before)

    def test_opposing_and_mitered_root_hems_fit_available_space(self):
        for joint in ('parallel','sheet'):
            r=hem_recipe(joint);r['rules']['auto_corners']=True
            for f in r['flanges']:f['hem']['ret']=40
            normalized=s.normalize(r)
            self.assertTrue(all(0<f['hem']['ret']<=40 for f in normalized['flanges']))
            self.assertTrue(any(f['hem']['ret']<40 for f in normalized['flanges']))
            self.roundtrip(r)

    def test_alternating_directions_do_not_poison_other_corners(self):
        for joint in ('parallel','sheet'):
            for first,second in (('in','in'),('in','out'),('out','in')):
                with self.subTest(joint=joint,first=first,second=second):
                    r=box_recipe(first,second,joint);r['rules']['auto_corners']=True
                    r['flanges'][7]['side']='out' if first=='in' else 'in'
                    self.roundtrip(r)

    def test_acute_and_obtuse_return_angles_with_both_joint_styles(self):
        for joint in ('parallel','sheet'):
            for angle,side in ((30,'in'),(60,'out'),(90,'in'),(90,'out'),(120,'in'),(135,'out')):
                with self.subTest(joint=joint,angle=angle,side=side):
                    r=small_box(90,2,side);r['rules'].update(joint=joint,auto_corners=True)
                    for f in r['flanges'][:4]:f['length']=20
                    for f in r['flanges'][4:]:f['angle']=angle
                    self.roundtrip(r)

    def test_old_manual_project_migrates_with_holes(self):
        old=partial_box();old['rules'].update(miter=True,auto_corners=False)
        source=e.state(old);source.update(bend_engine=4,dirty=True)
        tool=cq.Solid.makeCylinder(.5,3,cq.Vector(50,50,-1));actual=s.build_sheet(old,parallel_version=4).cut(tool)
        target=partial_box();updated,st=e.rebuild(actual,source,target)
        self.same(updated,s.build_sheet(target).cut(tool));self.assertEqual(st['bend_engine'],s.ENGINE)
        flat,fs=e.switch(updated,st,True);folded,_=e.switch(flat,fs,False);self.same(folded,updated)

    def test_real_self_collision_remains_an_error(self):
        r=box_recipe('in','in');r['rules']['auto_corners']=True
        for f in r['flanges'][8:]:f['length']=20
        with self.assertRaises(k.CadError):s.build_sheet(r)

    def test_corner_relief_comes_only_from_the_rule(self):
        """Wycięcie w narożniku tylko z Reguł blach: przy „Brak” narożnik jest zamknięty (zostaje szczelina), a kwadrat daje jedno wycięcie."""
        t=1.0
        base=dict(o=[0,0,0],x=[1,0,0],y=[0,1,0],z=[0,0,1],lx=60,ly=40,lz=t)
        def wall(p0,p1,m):return dict(kind='base',p0=p0,p1=p1,n=[0,0,1],m=m,r=.5,angle=90,length=5,measure='outer')
        walls=[wall([60,0,t],[60,40,t],[1,0,0]),wall([60,40,t],[0,40,t],[0,1,0]),wall([0,40,t],[0,0,t],[-1,0,0]),wall([0,0,t],[60,0,t],[0,-1,0])]
        corner=(59.6,39.6,.45)       # punkt w łuku narożnika, poza szczeliną między ścianami
        volumes={}
        for joint in ('parallel','sheet'):
            for relief in ('none','square'):
                r=dict(base=base,t=t,flanges=walls,rules=dict(gap=.1,relief=relief,relief_size=3,joint=joint,miter=True,auto_corners=True,kfactor=.44))
                folded=s.build_sheet(r);old=s.build_sheet(r,parallel_version=5)
                volumes[joint,relief]=folded.Volume()
                if relief=='none':
                    self.assertGreater(folded.Volume(),old.Volume()+1)              # mniej materiału usuniętego niż dawniej (brak samoczynnego wycięcia)
                else:
                    self.assertEqual(k.point_state(folded,corner),'out')         # wycięcie kwadratowe z reguły
                state=e.state(r);self.assertEqual(state['bend_engine'],s.ENGINE)
                flat,flat_state=e.switch(folded,state,True)
                self.assertEqual(len(flat.Solids()),1)
                back,_=e.switch(flat,flat_state,False);self.same(back,folded)
        self.assertAlmostEqual(volumes['parallel','square'],volumes['sheet','square'],3)     # jedno, to samo wycięcie dla obu łączeń
