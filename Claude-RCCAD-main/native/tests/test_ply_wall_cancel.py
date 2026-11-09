"""Targeted wall cancellation must replay neighbours, without deleting siblings."""
import unittest
from rccad import history as hist, kernel as k
from rccad.document import Body


class WallCancelTests(unittest.TestCase):
    def setUp(self):
        sk=Body('Szkic',k.sketch('rectangle','XY',100,60),'sketch','XY').prepared()
        self.base=hist.run_recipe([sk],dict(type='ply_panel',profiles=[{'k':'sketch','id':sk.id}],d=3,t=3,method='laser',spent=[sk.id],out=['base']))[-1]
        self.edges=[i for i,e in enumerate(self.base.shape.Edges()) if abs(e.Center().z-3)<1e-6]

    def recipe(self,edges,ids,base=None):
        b=base or self.base
        return dict(type='ply_wall',base=b.id,edges=hist.edge_refs(b.shape,edges),t=3,h=20,side='on',flip=False,method='laser',out=ids)

    def test_remove_first_insertion_rebuilds_later_neighbour(self):
        states=[((self.base,),{})]
        for i,e in enumerate(self.edges):
            op=self.recipe([e],[f'w{i}'])
            states.append((tuple(hist.run_recipe(states[-1][0],op)),dict(op=op)))
        result,failed=hist.cancel_ply_wall(states,'w0')
        self.assertEqual(failed,0);self.assertEqual(len(result),4)
        self.assertNotIn('w0',[b.id for b in result[-1][0]])
        fresh=[self.base]
        for _,info in states[2:]:fresh=hist.run_recipe(fresh,info['op'])
        for b in fresh:
            actual=next(x for x in result[-1][0] if x.id==b.id)
            self.assertAlmostEqual(b.shape.Volume(),actual.shape.Volume(),5)
            self.assertTrue(actual.shape.isValid())

    def test_batch_removes_correct_edge_regardless_of_original_order(self):
        op=self.recipe(self.edges,['a','b','c','d'])
        after=tuple(hist.run_recipe([self.base],op));states=[((self.base,),{}),(after,dict(op=op))]
        for name in op['out']:
            with self.subTest(wall=name):
                result,failed=hist.cancel_ply_wall(states,name)
                self.assertEqual(failed,0)
                old={b.id:b for b in after};new={b.id:b for b in result[-1][0]}
                self.assertEqual(set(new),set(old)-{name})
                for key in set(new)-{self.base.id}:
                    self.assertEqual(new[key].meta['ply']['wall']['edge'],old[key].meta['ply']['wall']['edge'])

    def test_dependent_wall_rejects_without_mutating_original_history(self):
        op=self.recipe([self.edges[0]],['a'])
        after=tuple(hist.run_recipe([self.base],op));wall=after[-1]
        child=dict(type='transform',id=wall.id,mode='move',v=[0,0,10])
        end=tuple(hist.run_recipe(after,child))
        states=[((self.base,),{}),(after,dict(op=op)),(end,dict(op=child))]
        with self.assertRaises(k.CadError):hist.cancel_ply_wall(states,'a')
        self.assertEqual([b.id for b in states[-1][0]],['base','a'])
