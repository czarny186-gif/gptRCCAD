"""Butt seams continue through intermediate panels and their rounded bends."""
import unittest
from test_sheetmetal_boxes import box_recipe
from rccad import sheetmetal as s


class ParallelCornerTests(unittest.TestCase):
    def test_intermediate_panels_and_bends_have_no_diagonal_seam_faces(self):
        for turn in ('in', 'out'):
            with self.subTest(turn=turn):
                recipe = box_recipe(turn, 'out', 'parallel', gap=.5)
                frames, corners = s._effective(recipe['flanges'], 2, True)
                parts = s._corner_parts(recipe, frames, corners)
                for pieces in parts.values():
                    for piece in pieces:
                        for face in piece.Faces():
                            if face.geomType() == 'PLANE':
                                n = face.normalAt()
                                self.assertFalse(abs(n.x) > 1e-5 and abs(n.y) > 1e-5)
                shape = s.build_sheet(recipe)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids()), 1)

    def test_acute_obtuse_boxes_do_not_grow_corner_wings(self):
        import math
        for angle in (15,30,45,60,120,135,150,165,180):
            with self.subTest(angle=angle):
                recipe=small_box(angle)
                shape=s.build_sheet(recipe);bb=shape.BoundingBox()
                theta=math.radians(angle);outer=1.5
                reach=max(outer*(1 if angle>=90 else math.sin(theta)),outer*math.sin(theta)+5*max(0,math.cos(theta)))
                self.assertAlmostEqual(bb.xmin,-reach,delta=2e-5)
                self.assertAlmostEqual(bb.xmax,100+reach,delta=2e-5)
                self.assertAlmostEqual(bb.ymin,-reach,delta=2e-5)
                self.assertAlmostEqual(bb.ymax,50+reach,delta=2e-5)
                self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids()),1)

    def test_inclined_wall_clearance_is_measured_normal_to_the_skin(self):
        import math
        import numpy as np
        from rccad import kernel as k
        for angle in (45,135):
            with self.subTest(angle=angle):
                recipe=small_box(angle);shape=s.build_sheet(recipe);theta=math.radians(angle)
                radial=.5*math.sin(theta)+2.5*math.cos(theta)
                height=1.5-.5*math.cos(theta)+2.5*math.sin(theta)
                point=np.array([100+radial,50+radial+1/(2*math.sin(theta)),height])
                normal=np.array([-math.sin(theta),0,math.cos(theta)])
                self.assertEqual(k.point_state(shape,point+.1*normal),'out')
                self.assertEqual(k.point_state(shape,point-.01*normal),'in')
                self.assertEqual(k.point_state(shape,point+.21*normal),'in')

    def test_rounded_transitions_have_one_material_interval_across_the_width(self):
        import math
        import numpy as np
        import cadquery as cq
        for turn in ('in','out'):
            recipe=small_box(90,3,turn)
            frames,corners=s._effective(recipe['flanges'],1,True)
            parts=s._corner_parts(recipe,frames,corners)
            for i,frame in enumerate(frames):
                origin,X,Y,Z,span=s._frame(frame['p0'],frame['p1'],1,frame['n'],frame['m'])
                for degrees in (10,30,50,70,85):
                    phi=math.radians(degrees)
                    point=origin+math.sin(phi)*X+(1.5-math.cos(phi))*Y
                    line=cq.Edge.makeLine(cq.Vector(*(point-100*Z)),cq.Vector(*(point+(span+100)*Z)))
                    intervals=[]
                    for edge in line.intersect(parts[i][0]).Edges():
                        a,b=sorted(float((np.array(v.toTuple())-point)@Z) for v in edge.Vertices())
                        if b-a>1e-6:intervals.append((a,b))
                    intervals.sort();merged=[]
                    for a,b in intervals:
                        if merged and a<=merged[-1][1]+1e-5:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
                        else:merged.append((a,b))
                    self.assertEqual(len(merged),1,(turn,i,degrees,merged))

    def test_rotating_the_sheet_does_not_change_butt_seams(self):
        import math
        import copy
        import numpy as np
        recipe=small_box(135);original=s.build_sheet(recipe)
        axis=np.array([1,2,3])/math.sqrt(14);angle=math.radians(37)
        cross=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
        rotation=np.eye(3)*math.cos(angle)+(1-math.cos(angle))*np.outer(axis,axis)+math.sin(angle)*cross
        shift=np.array([17,-8,31]);rotated=copy.deepcopy(recipe)
        rotated['base']['o']=(rotation@np.array(recipe['base']['o'])+shift).tolist()
        for key in ('x','y','z'):rotated['base'][key]=(rotation@np.array(recipe['base'][key])).tolist()
        for spec in rotated['flanges']:
            for key in ('p0','p1'):spec[key]=(rotation@np.array(spec[key])+shift).tolist()
            for key in ('n','m'):spec[key]=(rotation@np.array(spec[key])).tolist()
        actual=s.build_sheet(rotated);expected=original.rotate((0,0,0),tuple(axis),37).translate(tuple(shift))
        self.assertLess(abs(actual.cut(expected).Volume(1e-9))+abs(expected.cut(actual).Volume(1e-9)),1e-4)

    def test_main_bend_cylinders_keep_the_requested_radius_and_thickness(self):
        import numpy as np
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        recipe=small_box(90,3);frames,corners=s._effective(recipe['flanges'],1,True)
        parts=s._corner_parts(recipe,frames,corners)
        for i,frame in enumerate(frames):
            axis=(frame['p1']-frame['p0'])/np.linalg.norm(frame['p1']-frame['p0'])
            radii=[]
            for face in parts[i][0].Faces():
                if face.geomType()!='CYLINDER':continue
                cylinder=BRepAdaptor_Surface(face.wrapped).Cylinder()
                if abs(float(np.array(cylinder.Axis().Direction().Coord())@axis))>1-1e-6:
                    radii.append(round(cylinder.Radius(),6))
            self.assertEqual(sorted(radii),[.5,1.5],i)


def small_box(angle=90,levels=1,turn='in'):
    recipe=box_recipe(turn,'out' if levels>2 else None,'parallel',gap=.2,levels=levels)
    recipe['t']=recipe['base']['lz']=1
    for spec in recipe['flanges']:
        spec['r']=.5;spec['length']=5
        if spec['kind']=='base':
            spec['angle']=angle
            spec['p0'][2]=spec['p1'][2]=1
    return recipe
