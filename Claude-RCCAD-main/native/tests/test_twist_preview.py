"""TWIST – podgląd na kopii siatki wyświetlania (rccad/twist_preview.py)."""
import math
import time
import unittest

import cadquery as cq
import numpy as np

from rccad import kernel as k
from rccad import twist_math as tm
from rccad import twist_preview as tp


def area(V, T):
    return float(np.linalg.norm(np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]]), axis=1).sum() / 2)


def volume(V, T):
    return float(np.einsum('ij,ij->i', V[T[:, 0]], np.cross(V[T[:, 1]], V[T[:, 2]])).sum() / 6)


def open_edges(V, T, digits=7):
    """Krawędzie należące do jednego trójkąta (szczeliny) - punkty porównywane po zaokrągleniu."""
    key = {}
    ids = np.unique(np.round(V, digits), axis=0, return_inverse=True)[1].reshape(-1)
    count = {}
    for a, b, c in ids[T]:
        for e in ((a, b), (b, c), (c, a)):
            if e[0] == e[1]:
                continue
            s = tuple(sorted(e))
            count[s] = count.get(s, 0) + 1
    return sum(1 for v in count.values() if v == 1)


class TwistPreviewTests(unittest.TestCase):
    def setUp(self):
        shape = cq.Workplane().box(20, 30, 80).faces('>Z').workplane().hole(8).val().translate(cq.Vector(0, 0, 40))
        self.mesh = k.display_mesh(shape)
        self.V = np.asarray(self.mesh.vertices, float)
        self.T = np.asarray(self.mesh.triangles, np.int64)

    def sliced(self, layers=32):
        return tp.SlicedMesh(self.mesh.vertices, self.mesh.triangles, self.mesh.edges, (0, 0, 0), (0, 0, 1), tp.cut_planes(0, 80, layers))

    def test_slicing_keeps_surface_orientation_and_is_watertight(self):
        s = self.sliced()
        self.assertGreater(len(s.triangles), len(self.T) * 5)
        self.assertAlmostEqual(area(s.vertices, s.triangles), area(self.V, self.T), 6)
        self.assertAlmostEqual(volume(s.vertices, s.triangles), volume(self.V, self.T), 6)    # ta sama orientacja trójkątów
        self.assertEqual(open_edges(*s.twisted(tm.make_field((0, 0, 0), (0, 0, 1), 0.0, 0, 80))[:1], s.triangles), 0)
        self.assertEqual(open_edges(self.V, self.T), 0)
        for layers in (8, 64):
            for angle in (90.0, -270.0, 720.0):
                v, _ = self.sliced(layers).twisted(tm.make_field((0, 0, 0), (0, 0, 1), angle, 0, 80))
                self.assertEqual(open_edges(v, self.sliced(layers).triangles), 0, (layers, angle))   # bez szczelin po skręceniu

    def test_slices_follow_planes_and_triangle_count_is_linear(self):
        planes = tp.cut_planes(0, 80, 16)
        s = self.sliced(16)
        t = s.vertices[:, 2]
        tt = t[s.triangles]
        for c in planes:                                                          # żaden trójkąt nie przecina płaszczyzny
            self.assertFalse(((tt.min(axis=1) < c - 1e-9) & (tt.max(axis=1) > c + 1e-9)).any())
        n16, n64 = len(self.sliced(16).triangles), len(self.sliced(64).triangles)
        self.assertLess(n64, n16 * 4.5)                                          # liniowo, nie kwadratowo
        box = k.display_mesh(k.box(10, 10, 10))
        big = tp.SlicedMesh(box.vertices, box.triangles, box.edges, (0, 0, 0), (0, 0, 1), tp.cut_planes(0, 10, 256))
        self.assertLess(len(big.triangles), 12 * (2 * 256 + 1))

    def test_twisted_copy_matches_engine_and_original_is_untouched(self):
        before_v, before_t = self.mesh.vertices.copy(), self.mesh.triangles.copy()
        before_e = {key: p.copy() for key, p in self.mesh.edges.items()}
        f = tm.make_field((0, 0, 0), (0, 0, 1), 90.0, 0, 80, 'smoothstep')
        s = self.sliced()
        v, edges = s.twisted(f)
        np.testing.assert_allclose(v, f.apply(s.vertices))
        corner = np.argmin(np.linalg.norm(s.vertices - (10, 15, 80), axis=1))
        np.testing.assert_allclose(v[corner], (-15, 10, 80), atol=1e-9)           # górny róg obrócony o 90°
        np.testing.assert_array_equal(self.mesh.vertices, before_v)
        np.testing.assert_array_equal(self.mesh.triangles, before_t)
        for key, p in before_e.items():
            np.testing.assert_array_equal(self.mesh.edges[key], p)
        self.assertEqual(set(edges), set(self.mesh.edges))
        vertical = next(key for key, p in self.mesh.edges.items() if len(p) == 2 and abs(p[1][2] - p[0][2]) > 70)
        self.assertGreater(len(edges[vertical]), 20)                              # pionowa krawędź gęsto podzielona
        np.testing.assert_allclose(np.linalg.norm(edges[vertical][:, :2], axis=1), np.linalg.norm(self.mesh.edges[vertical][0][:2]), atol=1e-9)

    def test_densify_polyline(self):
        p = tp.densify_polyline([(1, 0, 0), (1, 0, 10)], (0, 0, 0), (0, 0, 1), [2.5, 5, 7.5])
        np.testing.assert_allclose(p[:, 2], [0, 2.5, 5, 7.5, 10])
        p = tp.densify_polyline([(1, 0, 10), (1, 0, 0)], (0, 0, 0), (0, 0, 1), [5])
        np.testing.assert_allclose(p[:, 2], [10, 5, 0])
        flat = tp.densify_polyline([(0, 0, 3), (5, 0, 3)], (0, 0, 0), (0, 0, 1), [3])
        self.assertEqual(len(flat), 2)

    def test_layer_count(self):
        self.assertEqual(tp.layer_count(0), tp.MIN_LAYERS)
        self.assertGreaterEqual(tp.layer_count(90) * tp.STEP_DEG, 90)
        self.assertEqual(tp.layer_count(100), tp.layer_count(120))                  # potęga dwójki: przeciąganie rzadko tnie od nowa
        self.assertEqual(tp.layer_count(1e5), tp.MAX_LAYERS)
        self.assertLess(tp.layer_count(3600, triangles=200_000), tp.MAX_LAYERS)    # budżet trójkątów
        self.assertGreater(tp.layer_count(90, 'smoothstep'), tp.layer_count(60))

    def test_large_mesh_is_fast(self):
        shape = cq.Workplane().cylinder(100, 20).faces('>Z').workplane().hole(10).val()
        mesh = k.display_mesh(shape)
        f = tm.make_field((0, 0, 0), (0, 0, 1), 360.0, -50, 50)
        start = time.perf_counter()
        s = tp.SlicedMesh(mesh.vertices, mesh.triangles, mesh.edges, f.origin, f.direction, tp.cut_planes(-50, 50, tp.layer_count(360, triangles=len(mesh.triangles))))
        for _ in range(10):
            s.twisted(f)
        self.assertLess(time.perf_counter() - start, 2.0)

    def test_preview_module_has_no_cad_or_ui_imports(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(tp))
        names = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {(n.module or '').split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(names & {'OCP', 'cadquery', 'PySide6'}, names)


if __name__ == '__main__':
    unittest.main()
