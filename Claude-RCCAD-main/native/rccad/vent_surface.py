"""Wentylacja - odwzorowanie wzoru 2D na powierzchnie brył (SurfaceMapper) i zarządzanie obszarami (RegionManager).

Odwzorowanie: dziedzina 2D (mm) ↔ punkty ściany. Tryby:
  plane     - ściana płaska: układ ściany (dokładnie)
  unwrap    - rozwinięcie powierzchni rozwijalnej: walec (x = R·θ, y wzdłuż osi), stożek (rozwinięcie wycinka);
              szew okresowy - kąt liczony względem środka zakresu ściany (wzór nie rozcina się na szwie)
  uv        - współrzędne UV powierzchni przeskalowane metryką w środku ściany (BRepAdaptor_Surface)
  geodesic  - rzeczywiste odległości na powierzchni: mapa wykładnicza od środka obszaru (kroki po powierzchni
              z rzutowaniem GeomAPI_ProjectPointOnSurf) - kierunek i odległość po powierzchni zachowane
  tangent   - jak geodesic, ale profile otworów płaskie w płaszczyznach stycznych (zachowanie kształtu)
  linear    - rzutowanie liniowe wzdłuż kierunku (przecięcie promienia ze ścianą)
  normal    - rzutowanie prostopadłe (najbliższy punkt powierzchni) z płaszczyzny odniesienia
  curve     - wzdłuż krzywej: x - długość łuku krzywej, y - odsunięcie po powierzchni prostopadle do krzywej
Wszystkie zwracają punkt, normalną (na zewnątrz bryły) i kierunki styczne zgodne z osiami dziedziny."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

MAPPINGS = ('auto', 'plane', 'unwrap', 'uv', 'geodesic', 'tangent', 'linear', 'normal', 'curve')
MAPPING_LABELS = {'auto': 'Automatycznie (według rodzaju powierzchni)', 'plane': 'Płaszczyzna ściany', 'unwrap': 'Rozwinięcie powierzchni (walec, stożek)',
                  'uv': 'Współrzędne UV powierzchni', 'geodesic': 'Rzeczywiste odległości na powierzchni', 'tangent': 'Lokalne płaszczyzny styczne',
                  'linear': 'Rzutowanie liniowe', 'normal': 'Rzutowanie prostopadłe', 'curve': 'Wzdłuż wskazanej krzywej'}
PRIORITIES = ('size', 'shape', 'spacing', 'proportion')
PRIORITY_LABELS = {'size': 'Zachowanie wielkości otworów', 'shape': 'Zachowanie kształtu otworów', 'spacing': 'Zachowanie odstępów',
                   'proportion': 'Zachowanie proporcji całego wzoru'}


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def surface_kind(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_BSplineSurface, GeomAbs_BezierSurface, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
    t = BRepAdaptor_Surface(face).GetType()
    return {GeomAbs_Plane: 'plane', GeomAbs_Cylinder: 'cylinder', GeomAbs_Cone: 'cone', GeomAbs_Sphere: 'sphere', GeomAbs_Torus: 'torus',
            GeomAbs_BSplineSurface: 'bspline', GeomAbs_BezierSurface: 'bspline'}.get(t, 'other')


class Mapper:
    """Odwzorowanie dziedzina ↔ ściana. face - TopoDS_Face (z bryły; orientacja uwzględniana dla normalnej)."""

    def __init__(self, face, mode='auto', centre=None, direction=None, curve=None, up=(0, 0, 1.0), rotate=0.0):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepTools import BRepTools
        from OCP.TopAbs import TopAbs_REVERSED
        self.face = face
        self.ad = BRepAdaptor_Surface(face)
        self.kind = surface_kind(face)
        self.rev = face.Orientation() == TopAbs_REVERSED
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        self.ub = (u0, u1, v0, v1)
        if mode == 'auto':
            mode = 'plane' if self.kind == 'plane' else ('unwrap' if self.kind in ('cylinder', 'cone') else 'geodesic')
        if mode == 'unwrap' and self.kind not in ('cylinder', 'cone', 'plane'):
            raise kernel.CadError('Rozwinięcie jest możliwe tylko dla powierzchni rozwijalnych (walec, stożek) - wybierz inny sposób odwzorowania.')
        if mode == 'unwrap' and self.kind == 'plane':
            mode = 'plane'
        self.mode = mode
        self.rot = math.radians(float(rotate))
        uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
        if centre is not None:                                             # środek odwzorowania w punkcie (np. kliknięcie)
            uc, vc = self.project_uv(centre)
        self.uc, self.vc = uc, vc
        P, N, Du, Dv = self.eval_uv(uc, vc)
        self.o, self.n = P, N
        up = np.asarray(up, float)
        if self.kind == 'plane' or mode in ('plane', 'linear', 'normal', 'geodesic', 'tangent'):
            ref = up - N * float(up @ N)
            if np.linalg.norm(ref) < 1e-6:
                ref = Du - N * float(Du @ N)
            yv = _unit(ref)
            xv = _unit(np.cross(yv, N))
        else:
            xv, yv = _unit(Du), _unit(np.cross(N, _unit(Du)))
        c, s = math.cos(self.rot), math.sin(self.rot)
        self.x, self.y = c * xv + s * yv, -s * xv + c * yv
        self.dir = _unit(direction) if direction is not None else N
        if mode in ('linear',) and direction is not None:
            d = self.dir
            ref = up - d * float(up @ d)
            if np.linalg.norm(ref) < 1e-6:
                ref = np.array([1.0, 0, 0]) - d * d[0]
            self.y = _unit(ref)
            self.x = _unit(np.cross(self.y, d))
        if mode == 'uv':
            self.su = float(np.linalg.norm(Du))
            self.sv = float(np.linalg.norm(Dv))
        if mode == 'unwrap':
            self._unwrap_setup()
        if mode in ('geodesic', 'tangent'):
            self._G = None
        if mode == 'curve':
            if curve is None or len(curve) < 2:
                raise kernel.CadError('Odwzorowanie wzdłuż krzywej: wskaż krzywą.')
            self.curve = np.asarray(curve, float)
            seg = np.linalg.norm(np.diff(self.curve, axis=0), axis=1)
            self.cum = np.r_[0, np.cumsum(seg)]

    # ------------------------------------------------------------------ powierzchnia
    def eval_uv(self, u, v):
        from OCP.gp import gp_Pnt, gp_Vec
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        self.ad.D1(float(u), float(v), p, du, dv)
        Du, Dv = np.array(du.Coord()), np.array(dv.Coord())
        n = np.cross(Du, Dv)
        if np.linalg.norm(n) < 1e-12:                                     # biegun - normalna z sąsiedztwa
            e = 1e-4 * max(self.ub[1] - self.ub[0], 1e-6)
            p2, du2, dv2 = gp_Pnt(), gp_Vec(), gp_Vec()
            self.ad.D1(float(u + e), float(v), p2, du2, dv2)
            n = np.cross(np.array(du2.Coord()), np.array(dv2.Coord()))
        n = _unit(n)
        if self.rev:
            n = -n
        return np.array(p.Coord()), n, Du, Dv

    def project_uv(self, P):
        from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
        from OCP.BRep import BRep_Tool
        from OCP.gp import gp_Pnt
        if not hasattr(self, '_surf'):
            self._surf = BRep_Tool.Surface_s(self.face)
        pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, P)), self._surf)
        if pr.NbPoints() == 0:
            raise kernel.CadError('Punkt nie rzutuje się na powierzchnię.')
        u, v = pr.LowerDistanceParameters()
        return float(u), float(v)

    # ------------------------------------------------------------------ rozwinięcie
    def _unwrap_setup(self):
        if self.kind == 'cylinder':
            cyl = self.ad.Cylinder()
            self.R = cyl.Radius()
            self.ax_o = np.array(cyl.Location().Coord())
            self.ax_d = np.array(cyl.Axis().Direction().Coord())
        elif self.kind == 'cone':
            cone = self.ad.Cone()
            self.ax_o = np.array(cone.Apex().Coord())
            self.ax_d = np.array(cone.Axis().Direction().Coord())
            self.half = cone.SemiAngle()
            self.R0 = cone.RefRadius()
            self.loc = np.array(cone.Location().Coord())

    def _uv_to_dom(self, u, v):
        """UV → dziedzina (rozwinięcie: kąt względem środka zakresu - szew okresowy nie przecina wzoru)."""
        if self.mode == 'uv':
            return np.array([(u - self.uc) * self.su, (v - self.vc) * self.sv]) @ np.array([[math.cos(self.rot), math.sin(self.rot)], [-math.sin(self.rot), math.cos(self.rot)]])
        if self.kind == 'cylinder':
            x, y = self.R * (u - self.uc), (v - self.vc)
        else:
            # stożek: v - odległość wzdłuż tworzącej od okręgu odniesienia; rozwinięcie we współrzędnych biegunowych
            sa = math.sin(self.half)
            sg = 1.0 if (self.vc + self.R0 / sa) >= 0 else -1.0                # odległość od wierzchołka wzdłuż tworzącej
            s_ = sg * (v + self.R0 / sa)
            s0 = sg * (self.vc + self.R0 / sa)
            phi = (u - self.uc) * abs(sa)
            x, y = s_ * math.sin(phi), s_ * math.cos(phi) - s0
        c, s = math.cos(self.rot), math.sin(self.rot)
        return np.array([c * x + s * y, -s * x + c * y])

    def _dom_to_uv(self, xy):
        c, s = math.cos(self.rot), math.sin(self.rot)
        x0, y0 = float(xy[0]), float(xy[1])
        x, y = c * x0 - s * y0, s * x0 + c * y0
        if self.mode == 'uv':
            return self.uc + x / self.su, self.vc + y / self.sv
        if self.kind == 'cylinder':
            return self.uc + x / self.R, self.vc + y
        sa = math.sin(self.half)
        sg = 1.0 if (self.vc + self.R0 / sa) >= 0 else -1.0
        s0 = sg * (self.vc + self.R0 / sa)
        yy = y + s0
        s_ = math.hypot(x, yy)
        phi = math.atan2(x, yy)
        return self.uc + phi / abs(sa), sg * s_ - self.R0 / sa

    # ------------------------------------------------------------------ mapa wykładnicza (rzeczywiste odległości)
    def _geo_grid(self, rmax):
        """Siatka biegunowa mapy wykładniczej: promienie (72 kierunki) krokami 0,5 mm po powierzchni z transportem
        kierunku i rzutem na powierzchnię; punkty 3D zapamiętane do interpolacji."""
        nphi = 48
        h = max(.5, rmax / 100)
        n = max(2, int(rmax / h) + 2)
        G = np.zeros((nphi, n, 3))
        for i in range(nphi):
            a = 2 * math.pi * i / nphi
            T = _unit(self.x * math.cos(a) + self.y * math.sin(a))
            P = self.o.copy()
            G[i, 0] = P
            for k in range(1, n):
                Q = P + T * h
                try:
                    u, v = self.project_uv(Q)
                except kernel.CadError:
                    G[i, k:] = P
                    break
                P2, N2, _du, _dv = self.eval_uv(u, v)
                d = P2 - P
                T2 = d - N2 * float(d @ N2)
                T = _unit(T2) if np.linalg.norm(T2) > 1e-9 else T
                P = P2
                G[i, k] = P
        self._G, self._Gh, self._Gr = G, h, (n - 1) * h

    def _extent(self):
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        if not hasattr(self, '_ext'):
            b = Bnd_Box()
            BRepBndLib.Add_s(self.face, b)
            x0, y0, z0, x1, y1, z1 = b.Get()
            self._ext = float(np.linalg.norm([x1 - x0, y1 - y0, z1 - z0]))
        return self._ext

    def _geo_point(self, xy):
        r = float(np.linalg.norm(xy))
        if r < 1e-9:
            return self.uc, self.vc
        if getattr(self, '_G', None) is None or r > self._Gr:
            self._geo_grid(max(r * 1.5, self._extent()))
        a = math.atan2(xy[1], xy[0]) % (2 * math.pi)
        nphi = self._G.shape[0]
        fi = a / (2 * math.pi) * nphi
        i0 = int(fi) % nphi
        i1 = (i0 + 1) % nphi
        ti = fi - int(fi)
        fk = r / self._Gh
        k0 = min(int(fk), self._G.shape[1] - 2)
        tk = fk - k0
        P = ((1 - ti) * ((1 - tk) * self._G[i0, k0] + tk * self._G[i0, k0 + 1]) + ti * ((1 - tk) * self._G[i1, k0] + tk * self._G[i1, k0 + 1]))
        return self.project_uv(P)

    # ------------------------------------------------------------------ API
    def to3d(self, xy):
        """Punkt dziedziny → (punkt, normalna na zewnątrz, kierunek x, kierunek y) na ścianie."""
        xy = np.asarray(xy, float)
        m = self.mode
        if m == 'plane':
            P = self.o + self.x * xy[0] + self.y * xy[1]
            return P, self.n, self.x, self.y
        if m in ('unwrap', 'uv'):
            u, v = self._dom_to_uv(xy)
            P, N, Du, Dv = self.eval_uv(u, v)
            e = 1e-3
            Px, _N, _a, _b = self.eval_uv(*self._dom_to_uv(xy + [e, 0]))
            Py, _N, _a, _b = self.eval_uv(*self._dom_to_uv(xy + [0, e]))
            return P, N, _unit(Px - P), _unit(Py - P)
        if m in ('geodesic', 'tangent'):
            u, v = self._geo_point(xy)
            P, N, Du, Dv = self.eval_uv(u, v)
            xd = self.x - N * float(self.x @ N)
            xd = _unit(xd) if np.linalg.norm(xd) > 1e-6 else _unit(Du)
            return P, N, xd, _unit(np.cross(N, xd))
        if m == 'linear':
            Q = self.o + self.x * xy[0] + self.y * xy[1]
            P = self._ray(Q, self.dir)
            u, v = self.project_uv(P)
            _P, N, Du, _Dv = self.eval_uv(u, v)
            xd = _unit(self.x - N * float(self.x @ N))
            return P, N, xd, _unit(np.cross(N, xd))
        if m == 'normal':
            Q = self.o + self.x * xy[0] + self.y * xy[1]
            u, v = self.project_uv(Q)
            P, N, Du, _Dv = self.eval_uv(u, v)
            xd = _unit(self.x - N * float(self.x @ N))
            return P, N, xd, _unit(np.cross(N, xd))
        if m == 'curve':
            s = float(xy[0])
            k = min(max(int(np.searchsorted(self.cum, s, 'right') - 1), 0), len(self.cum) - 2)
            seg = self.cum[k + 1] - self.cum[k]
            t = (s - self.cum[k]) / max(seg, 1e-12)
            C = self.curve[k] + (self.curve[k + 1] - self.curve[k]) * t
            T = _unit(self.curve[k + 1] - self.curve[k])
            u, v = self.project_uv(C)
            P, N, Du, _Dv = self.eval_uv(u, v)
            side = _unit(np.cross(N, T))
            if abs(float(xy[1])) > 1e-9:                                    # odsunięcie po powierzchni (kroki z rzutem)
                n_steps = max(1, int(abs(xy[1]) / 1.0))
                h = float(xy[1]) / n_steps
                for _ in range(n_steps):
                    u, v = self.project_uv(P + side * h)
                    P, N, Du, _Dv = self.eval_uv(u, v)
                    side = _unit(side - N * float(side @ N))
            return P, N, _unit(T - N * float(T @ N)), side
        raise kernel.CadError('Nieznany sposób odwzorowania.')

    def to2d(self, P):
        """Punkt 3D (na ścianie albo blisko) → dziedzina."""
        P = np.asarray(P, float)
        m = self.mode
        if m in ('plane', 'linear', 'normal'):
            d = P - self.o
            if m == 'linear':
                d = d - self.dir * float(d @ self.dir)
            return np.array([float(d @ self.x), float(d @ self.y)])
        if m in ('unwrap', 'uv'):
            u, v = self.project_uv(P)
            if self.ad.IsUPeriodic():
                per = self.ad.UPeriod()
                u = self.uc + ((u - self.uc + per / 2) % per) - per / 2
            return self._uv_to_dom(u, v)
        if m in ('geodesic', 'tangent'):                                   # odwrotność mapy: Newton na przybliżeniu stycznym
            d = P - self.o
            xy = np.array([float(d @ self.x), float(d @ self.y)])
            for _ in range(6):
                Q, N, _x, _y = self.to3d(xy)
                e = P - Q
                step = np.array([float(e @ _x), float(e @ _y)])
                xy = xy + step
                if np.linalg.norm(step) < 1e-5:
                    break
            return xy
        if m == 'curve':
            D = np.linalg.norm(self.curve - P, axis=1)
            k = int(min(D.argmin(), len(self.curve) - 2))
            a, b = self.curve[k], self.curve[k + 1]
            t = float(np.clip((P - a) @ (b - a) / max((b - a) @ (b - a), 1e-18), 0, 1))
            C = a + (b - a) * t
            side = _unit(np.cross(self.n, _unit(b - a)))
            return np.array([self.cum[k] + t * np.linalg.norm(b - a), float((P - C) @ side)])
        raise kernel.CadError('Nieznany sposób odwzorowania.')

    def _ray(self, Q, d):
        from OCP.IntCurvesFace import IntCurvesFace_Intersector
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        if not hasattr(self, '_ix'):
            self._ix = IntCurvesFace_Intersector(self.face, 1e-6)
        ln = gp_Lin(gp_Pnt(*map(float, Q - d * 1e4)), gp_Dir(*map(float, d)))
        self._ix.Perform(ln, -1e9, 1e9)
        if not self._ix.IsDone() or self._ix.NbPnt() == 0:
            return Q
        best = min(range(1, self._ix.NbPnt() + 1), key=lambda i: abs(self._ix.WParameter(i) - 1e4))
        return np.array(self._ix.Pnt(best).Coord())

    def jacobian(self, xy, e=.5):
        """Pole elementu powierzchni na jednostkę pola dziedziny (rzeczywiste pole otworów i obszaru)."""
        P, _N, _x, _y = self.to3d(xy)
        Px, *_ = self.to3d(np.asarray(xy, float) + [e, 0])
        Py, *_ = self.to3d(np.asarray(xy, float) + [0, e])
        return float(np.linalg.norm(np.cross(Px - P, Py - P))) / (e * e)

    def boundary(self, samples=24):
        """Kontury ściany w dziedzinie: (zewnętrzny, [otwory]) - z krzywych na powierzchni (pcurve) dla UV / rozwinięcia,
        z punktów 3D dla pozostałych odwzorowań."""
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
        from OCP.TopAbs import TopAbs_WIRE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        outer_w = BRepTools.OuterWire_s(self.face)
        loops_out, loops_in = [], []
        ex = TopExp_Explorer(self.face, TopAbs_WIRE)
        while ex.More():
            w = TopoDS.Wire_s(ex.Current())
            pts = []
            we = BRepTools_WireExplorer(w, self.face)
            while we.More():
                e = we.Current()
                rev = we.Orientation() == 1
                if self.mode in ('unwrap', 'uv'):
                    from OCP.BRepAdaptor import BRepAdaptor_Curve2d
                    c2 = BRepAdaptor_Curve2d(e, self.face)
                    ts = np.linspace(c2.FirstParameter(), c2.LastParameter(), samples)
                    if rev:
                        ts = ts[::-1]
                    for t in ts[:-1]:
                        q = c2.Value(float(t))
                        pts.append(self._uv_to_dom(q.X(), q.Y()))
                else:
                    c = BRepAdaptor_Curve(e)
                    ts = np.linspace(c.FirstParameter(), c.LastParameter(), samples)
                    if rev:
                        ts = ts[::-1]
                    for t in ts[:-1]:
                        pts.append(self.to2d(np.array(c.Value(float(t)).Coord())))
                we.Next()
            arr = np.array(pts, float)
            if len(arr) >= 3:
                (loops_out if w.IsSame(outer_w) else loops_in).append(arr)
            ex.Next()
        if self.mode not in ('unwrap', 'uv', 'plane') and self._closed():
            # ściana zamknięta (pełny walec, kula, torus): poza UV kontur nie jest prostym wielokątem - obszar to część
            # powierzchni zwrócona w stronę normalnej środka (otoczka punktów siatki UV), bez szwu i biegunów
            from .vent_geom2d import area as _ar
            u0, u1, v0, v1 = self.ub
            pts = []
            for u in np.linspace(u0, u1, 25):
                for v in np.linspace(v0, v1, 25):
                    P, N, _a, _b = self.eval_uv(u, v)
                    if float(N @ self.n) > .35:
                        try:
                            pts.append(self.to2d(P))
                        except kernel.CadError:
                            pass
            if len(pts) >= 3:
                from .vent_shapes import _hull
                hull = np.array(_hull(np.array(pts)))
                c = hull.mean(0)
                hull = c + (hull - c) * .97
                if abs(_ar(hull)) > 1e-6:
                    return [hull], []
        return loops_out, loops_in

    def _closed(self):
        u0, u1, v0, v1 = self.ub
        cu = self.ad.IsUPeriodic() and (u1 - u0) > self.ad.UPeriod() * .99
        cv = self.ad.IsVPeriodic() and (v1 - v0) > self.ad.VPeriod() * .99
        return bool(cu or cv or self.kind == 'sphere')


# ---------------------------------------------------------------------------------------------- obszary
REGIONS = ('face', 'rect', 'square', 'circle', 'ellipse', 'polygon', 'ring', 'sector', 'sketch', 'edges', 'contours', 'between', 'lasso')
REGION_LABELS = {'face': 'Cała zaznaczona powierzchnia', 'rect': 'Prostokąt', 'square': 'Kwadrat', 'circle': 'Okrąg', 'ellipse': 'Elipsa',
                 'polygon': 'Wielokąt foremny', 'ring': 'Pierścień', 'sector': 'Sektor kołowy', 'sketch': 'Obszar ze szkicu',
                 'edges': 'Obszar ograniczony krawędziami', 'contours': 'Kilka zamkniętych konturów (szkic)', 'between': 'Między dwoma konturami',
                 'lasso': 'Dowolny fragment (punkty)'}


def region_polys(r, face_outer, face_holes):
    """Wielokąty obszaru w dziedzinie: (zewnętrzne, otwory). r - dict(type, cx, cy, w, h, d, d2, sides, a0, a1, angle, scale,
    loops / points). Obszar jest zawsze przycinany do ściany (otwory ściany pozostają otworami obszaru)."""
    t = r.get('type', 'face')
    cx, cy = float(r.get('cx', 0.0)), float(r.get('cy', 0.0))
    ang = math.radians(float(r.get('angle', 0.0)))
    sc = float(r.get('scale', 1.0) or 1.0)
    c, s = math.cos(ang), math.sin(ang)
    T = lambda P: np.array([cx, cy]) + (np.asarray(P, float) * sc) @ np.array([[c, s], [-s, c]])
    circle = lambda R_, n=96, a0=0.0, a1=2 * math.pi: np.array([[R_ * math.cos(t_), R_ * math.sin(t_)] for t_ in np.linspace(a0, a1, n, endpoint=a1 - a0 < 2 * math.pi - 1e-9)])
    outers, holes = [], []
    w, h = float(r.get('w', 40.0)), float(r.get('h', 30.0))
    if t == 'face':
        return [np.asarray(o, float) for o in face_outer], [np.asarray(q, float) for q in face_holes]
    if t in ('rect', 'square'):
        hh = w if t == 'square' else h
        outers.append(T([(-w / 2, -hh / 2), (w / 2, -hh / 2), (w / 2, hh / 2), (-w / 2, hh / 2)]))
    elif t == 'circle':
        outers.append(T(circle(float(r.get('d', w)) / 2)))
    elif t == 'ellipse':
        outers.append(T(circle(1.0) * [w / 2, h / 2]))
    elif t == 'polygon':
        n = max(3, int(r.get('sides', 6)))
        outers.append(T(circle(float(r.get('d', w)) / 2, n)))
    elif t == 'ring':
        outers.append(T(circle(float(r.get('d', w)) / 2)))
        holes.append(T(circle(float(r.get('d2', w / 2)) / 2)))
    elif t == 'sector':
        a0, a1 = math.radians(float(r.get('a0', 0.0))), math.radians(float(r.get('a1', 90.0)))
        arc = circle(float(r.get('d', w)) / 2, 64, a0, a1)
        inner = float(r.get('d2', 0.0)) / 2
        pts = list(arc) + (list(circle(inner, 32, a1, a0)) if inner > 0 else [(0.0, 0.0)])
        outers.append(T(pts))
    elif t in ('sketch', 'edges', 'contours', 'lasso', 'between'):
        loops = [np.asarray(q, float) for q in (r.get('loops') or [])]
        if t == 'lasso':
            loops = [np.asarray(r.get('points') or [], float)]
        if not loops or any(len(q) < 3 for q in loops):
            raise kernel.CadError('Obszar: wskaż zamknięte kontury (szkic, krawędzie albo punkty).')
        if t == 'between':
            if len(loops) < 2:
                raise kernel.CadError('Obszar między konturami: potrzebne dwa zamknięte kontury.')
            loops = sorted(loops, key=lambda q: -abs(_area(q)))
            outers.append(loops[0])
            holes += loops[1:]
        else:                                                               # kontury zagnieżdżone - parzystość (kontur w konturze = otwór)
            for i, q in enumerate(loops):
                depth = sum(1 for j, o in enumerate(loops) if j != i and _inside(q.mean(0), o))
                (holes if depth % 2 else outers).append(q)
    else:
        raise kernel.CadError(f'Nieznany obszar: {t}.')
    return outers, holes


def _area(P):
    x, y = P[:, 0], P[:, 1]
    return .5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _inside(q, poly):
    from .vent_geom2d import pip
    return bool(pip(np.asarray(q, float)[None], poly)[0])


# ---------------------------------------------------------------------------------------------- wiele ścian
def unfold_chain(faces, seed=0, samples=12):
    """Kontynuacja wzoru przez krawędzie: sąsiednie ściany (płaskie i rozwijalne - także zaokrąglenia) rozkładane do
    wspólnej dziedziny przez dopasowanie wspólnej krawędzi (sztywne przekształcenie 2D, ściana po drugiej stronie
    krawędzi). Zwraca listę (mapper, macierz 3×3 dziedzina ściany → wspólna) w kolejności BFS."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    maps = [Mapper(f, 'unwrap' if surface_kind(f) in ('cylinder', 'cone') else ('plane' if surface_kind(f) == 'plane' else 'uv')) for f in faces]
    for m in maps:
        if m.mode not in ('plane', 'unwrap'):
            m.approx = True
    edges = []
    for f in faces:
        lst = []
        ex = TopExp_Explorer(f, TopAbs_EDGE)
        while ex.More():
            lst.append(ex.Current())
            ex.Next()
        edges.append(lst)
    placed = {seed: np.eye(3)}
    order = [seed]
    queue = [seed]
    while queue:
        a = queue.pop(0)
        for b in range(len(faces)):
            if b in placed:
                continue
            shared = [e for e in edges[a] if any(e.IsSame(e2) for e2 in edges[b])]
            if not shared:
                continue
            from OCP.TopoDS import TopoDS
            c = BRepAdaptor_Curve(TopoDS.Edge_s(shared[0]))
            P3 = [np.array(c.Value(float(t)).Coord()) for t in np.linspace(c.FirstParameter(), c.LastParameter(), samples)]
            A2 = np.array([(placed[a] @ np.r_[maps[a].to2d(q), 1])[:2] for q in P3])
            B2 = np.array([maps[b].to2d(q) for q in P3])
            ca, cb = A2.mean(0), B2.mean(0)
            interior_a = (placed[a] @ np.r_[maps[a].to2d(np.asarray(maps[a].o)), 1])[:2]
            best = None
            for refl in (1, -1):
                Bm = (B2 - cb) * [1, refl]
                H = Bm.T @ (A2 - ca)
                U, _S, Vt = np.linalg.svd(H)
                R = (U @ Vt).T
                if np.linalg.det(R) < 0:
                    Vt[-1] *= -1
                    R = (U @ Vt).T
                M = np.eye(3)
                M[:2, :2] = R @ np.diag([1, refl])
                M[:2, 2] = ca - R @ (cb * [1, refl])
                err = float(np.abs((np.c_[B2, np.ones(len(B2))] @ M.T)[:, :2] - A2).max())
                ib = (M @ np.r_[maps[b].to2d(np.asarray(maps[b].o)), 1])[:2]
                d = A2[-1] - A2[0]
                nrm = np.array([-d[1], d[0]])
                opposite = float((ib - ca) @ nrm) * float((interior_a - ca) @ nrm) < 0
                score = err + (0 if opposite else 1e3)
                if best is None or score < best[0]:
                    best = (score, M)
            placed[b] = best[1]
            order.append(b)
            queue.append(b)
    return [(maps[i], placed[i]) for i in order if i in placed], [i for i in range(len(faces)) if i not in placed]
