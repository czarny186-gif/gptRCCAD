"""Tekstury geometryczne - wspólny silnik: ściany → odwzorowania (wspólne z Wentylacją: rccad.vent_surface) → obszar z marginesami
i strefami → dopasowanie wzoru → elementy 2D (rccad.tex_patterns) → gradienty → bryły narzędzi (rccad.tex_tools) →
operacje logiczne grupowe → kontrola wyniku → statystyki. Krok historii 'tex' (edycja, cofanie, wyłączanie, regeneracja po zmianie
bryły; ściany identyfikowane geometrycznie - punkt, normalna, środek, pole, rodzaj - nie numerem)."""
from __future__ import annotations

import math
import time
import uuid

import numpy as np

from . import kernel
from . import tex_patterns as tp
from . import tex_tools as tt
from . import vent_cut as vc
from . import vent_feature as vf
from . import vent_geom2d as g2
from . import vent_surface as su

LIMIT_EXACT = 6000            # tyle elementów (każdy to kilka ścian B-Rep) liczy się jeszcze w trybie dokładnym
LIMIT_OPT = 10000            # zoptymalizowany B-Rep; powyżej - tryb siatkowy
LIMIT_MESH = 20000
EXACT_PER_S = 900.0           # szacunek wydajności (elementów / s) do przewidywanej złożoności
GRADIENT_PARAMS = ('height', 'depth', 'size', 'spacing', 'density', 'angle', 'wall')
GRADIENT_LABELS = {'height': 'Wysokość', 'depth': 'Głębokość', 'size': 'Wielkość elementów', 'spacing': 'Rozstaw', 'density': 'Gęstość',
                   'angle': 'Kąt obrotu', 'wall': 'Grubość ścianek'}
GRADIENT_TYPES = {'linear': 'Liniowy', 'radial': 'Promieniowy', 'bidirectional': 'Dwukierunkowy', 'curve': 'Wzdłuż krzywej (szkic)',
                  'point': 'Względem odległości od punktu'}
MULTI = ('independent', 'origin', 'continue', 'direction', 'phase')
MULTI_LABELS = {'independent': 'Niezależny wzór dla każdej powierzchni', 'origin': 'Wspólny początek wzoru', 'continue': 'Kontynuacja wzoru przez wspólną krawędź',
                'direction': 'Zachowanie kierunku wzoru', 'phase': 'Automatyczne dopasowanie fazy wzoru'}
REGION_TYPES = ('face', 'rect', 'circle', 'polygon', 'sketch', 'lasso')
REGION_LABELS = {'face': 'Cała zaznaczona powierzchnia', 'rect': 'Prostokąt', 'circle': 'Okrąg', 'polygon': 'Wielokąt foremny', 'sketch': 'Wewnątrz szkicu',
                 'sketch_out': 'Poza szkicem', 'lasso': 'Dowolny wielokąt (punkty)'}


def params(recipe):
    p = dict(tp.DEFAULTS)
    p.update({k: v for k, v in (recipe.get('p') or {}).items() if v is not None or k in ('origin', 'image', 'custom_loops', 'custom_body')})
    return p


def new_recipe(target, refs, **kw):
    r = dict(type='tex', id=uuid.uuid4().hex, target=target, faces=refs, p=dict(tp.DEFAULTS), region={'type': 'face'}, exclusions=[],
             multi='independent', mapping='auto', density=0.0, out_ids=[])
    r.update(kw)
    return r


def _jsonable(d):
    return {k: (float(v) if isinstance(v, (int, float, np.floating)) and not isinstance(v, bool) else v) for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------------------------- obszar dozwolony
def _loops_of(shape):
    """Płaskie ściany XY → lista (zewnętrzny, [otwory])."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        outer_w = BRepTools.OuterWire_s(f)
        outer, holes = None, []
        wx = TopExp_Explorer(f, TopAbs_WIRE)
        while wx.More():
            w = TopoDS.Wire_s(wx.Current())
            pts = []
            we = BRepTools_WireExplorer(w)
            while we.More():
                c = BRepAdaptor_Curve(we.Current())
                ts = np.linspace(c.FirstParameter(), c.LastParameter(), 2 if c.GetType() == 0 else 10)
                if we.Orientation() == 1:
                    ts = ts[::-1]
                pts += [c.Value(float(t)).Coord()[:2] for t in ts[:-1]]
                we.Next()
            arr = np.array(pts, float)
            if len(arr) >= 3:
                if w.IsSame(outer_w):
                    outer = arr
                else:
                    holes.append(arr)
            wx.Next()
        if outer is not None:
            out.append((outer, holes))
        ex.Next()
    return out


def poly_diff(poly, cutters):
    """Wielokąt minus wielokąty (Boolean 2D w OCC): lista (zewnętrzny, [otwory])."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    acc = g2._face_xy([np.asarray(poly, float)])
    for c in cutters:
        acc = BRepAlgoAPI_Cut(acc, g2._face_xy([np.asarray(c, float)])).Shape()
    return [(o, h) for o, h in _loops_of(acc) if abs(tt.ccw(o)) > 1e-4]


def _offset(poly, d):
    """Wielokąt przesunięty o d na zewnątrz (d < 0 - do wewnątrz): lista wielokątów (może zniknąć albo się rozpaść)."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Arc
    if abs(d) < 1e-9:
        return [np.asarray(poly, float)]
    P = np.asarray(poly, float)
    if tt.ccw(P) < 0:
        P = P[::-1]
    try:
        mk = BRepOffsetAPI_MakeOffset(g2._face_xy([P]), GeomAbs_Arc)
        mk.Perform(float(d))
        from OCP.TopAbs import TopAbs_WIRE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        res = []
        ex = TopExp_Explorer(mk.Shape(), TopAbs_WIRE)
        while ex.More():
            q = vf._wire_pts(TopoDS.Wire_s(ex.Current()))
            if len(q) >= 3:
                res.append(q)
            ex.Next()
        return res
    except Exception:
        return []


def allowed_region(region, zones, margin, margin_holes):
    """Obszar, na którym wolno umieścić elementy: kontur obszaru pomniejszony o margines od krawędzi, otwory powiększone o
    margines od otworów, strefy zabronione powiększone o odstęp. Zwraca (outers, holes) jako wielokąty (Boolean 2D w OCC)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    acc = None
    for o in region.outers:
        for q in _offset(o, -margin) if margin > 1e-9 else [o]:
            f = g2._face_xy([q])
            acc = f if acc is None else BRepAlgoAPI_Fuse(acc, f).Shape()
    if acc is None:
        raise kernel.CadError('Margines od krawędzi jest większy od obszaru - nie ma gdzie umieścić tekstury.')
    cuts = []
    for h in region.holes:
        cuts += _offset(h, margin_holes) if margin_holes > 1e-9 else [h]
    for z in zones or []:
        cuts += _offset(np.asarray(z['poly'], float), float(z.get('gap', 0.0)))
    for q in cuts:
        acc = BRepAlgoAPI_Cut(acc, g2._face_xy([q])).Shape()
    loops = _loops_of(acc)
    if not loops:
        raise kernel.CadError('Po uwzględnieniu marginesów i stref nie zostaje obszar na teksturę - zmniejsz marginesy.')
    return [o for o, _h in loops], [h for _o, hs in loops for h in hs]


# ---------------------------------------------------------------------------------------------- plan
def _group_faces(faces, multi, mode, report, rotate=0.0):
    groups = []
    if multi in ('independent', 'phase', 'origin', 'direction') or len(faces) == 1:
        for f in faces:
            groups.append(([su.Mapper(f, mode, rotate=rotate)], [np.eye(3)]))
        return groups
    chain, left = su.unfold_chain(faces)
    if left:
        report.append(('warning', f'{len(left)} ścian nie przylega do pozostałych - wzór na nich jest niezależny. Ciągłość możliwa tylko dla sąsiadujących powierzchni.'))
    groups.append(([m for m, _t in chain], [t for _m, t in chain]))
    for i in left:
        groups.append(([su.Mapper(faces[i], mode)], [np.eye(3)]))
    if any(getattr(m, 'approx', False) for m, _t in chain):
        report.append(('warning', 'Część ścian nie jest rozwijalna (kula, torus, B-Spline) - ciągłość wzoru na nich przybliżona. Możliwe wyjścia: Niezależny wzór dla każdej ściany, Wspólny początek wzoru albo mniejsza wielkość elementów.'))
    return groups


def _region(recipe, mapper, outs, hols, bodies):
    r = dict(recipe.get('region') or {'type': 'face'})
    invert = r.get('type') == 'sketch_out'
    if invert:
        r['type'] = 'sketch'
    reg = vf._region_of(dict(region=r), mapper, outs, hols, bodies)
    if invert:
        return g2.Region([np.asarray(o, float) for o in outs], [np.asarray(h, float) for h in hols] + list(reg.outers))
    return reg


def _kmax(mapper):
    """Największa krzywizna powierzchni ściany (1/mm) - z próbek siatki UV; zapas przy osadzaniu elementów."""
    if hasattr(mapper, '_kmax'):
        return mapper._kmax
    if mapper.kind == 'plane':
        mapper._kmax = 0.0
        return 0.0
    from OCP.BRepLProp import BRepLProp_SLProps
    k = 0.0
    u0, u1, v0, v1 = mapper.ub
    try:
        ls = BRepLProp_SLProps(mapper.ad, 2, 1e-6)
        for u in np.linspace(u0, u1, 6):
            for v in np.linspace(v0, v1, 6):
                ls.SetParameters(float(u), float(v))
                if ls.IsCurvatureDefined():
                    k = max(k, abs(ls.MaxCurvature()), abs(ls.MinCurvature()))
    except Exception:
        k = 0.05
    mapper._kmax = min(k, 50.0)
    return mapper._kmax


class Group:
    """Jedna dziedzina wzoru (jedna ściana albo kilka rozłożonych do wspólnej płaszczyzny)."""

    def __init__(self, mappers, Ts):
        self.mappers, self.Ts = mappers, Ts
        self.region = None
        self.allowed = None
        self.elements = []
        self.p = None
        self.frame = None
        self.field = None

    def locate(self, c):
        if len(self.mappers) == 1:
            return self.mappers[0], np.asarray(c, float)
        return vf._locate(dict(mappers=self.mappers, T=self.Ts), c)

    def frame_at(self, c):
        m, q = self.locate(c)
        P, N, X, Y = m.to3d(q)
        return P, N, X, Y, m


def gradient_field(gr, Q, region_centroid, domain_of=None):
    """Wartość gradientu g ∈ [0, 1] w punktach Q (Nx2). linear - wzdłuż kierunku angle na długości length; radial - od środka;
    bidirectional - iloczyn dwóch liniowych (kierunki angle i angle + 90°); point - odległość od punktu; curve - odległość wzdłuż krzywej."""
    Q = np.asarray(Q, float).reshape(-1, 2)
    t = gr.get('type', 'linear')
    c = np.array([float(gr.get('cx', region_centroid[0])), float(gr.get('cy', region_centroid[1]))])
    L = max(float(gr.get('length', 50.0)), 1e-6)
    a = math.radians(float(gr.get('angle', 0.0)))
    d = np.array([math.cos(a), math.sin(a)])
    if t == 'radial' or t == 'point':
        g = np.linalg.norm(Q - c, axis=1) / L
    elif t == 'bidirectional':
        d2 = np.array([-d[1], d[0]])
        g1 = np.clip((Q - c) @ d / L + .5, 0, 1)
        g2_ = np.clip((Q - c) @ d2 / L + .5, 0, 1)
        g = (g1 + g2_) / 2
    elif t == 'curve' and gr.get('curve_pts') is not None:
        C = np.asarray(gr['curve_pts'], float)
        seg = np.linalg.norm(np.diff(C, axis=0), axis=1)
        cum = np.r_[0, np.cumsum(seg)]
        D = np.linalg.norm(Q[:, None, :] - C[None, :, :], axis=2)
        g = cum[D.argmin(1)] / max(cum[-1], 1e-9)
    else:
        g = (Q - c) @ d / L + .5
    return np.clip(g, 0.0, 1.0)


def _lerp(gr, g):
    return float(gr.get('v0', 0.0)) + (float(gr.get('v1', 1.0)) - float(gr.get('v0', 0.0))) * g


def apply_gradients(p, els, grads, centroid, mode, report):
    """Zmiana parametrów elementów wzdłuż gradientu (wysokość, głębokość, wielkość, kąt, grubość ścianki); rozstaw i gęstość -
    rozciągnięcie położeń wzdłuż osi gradientu (siatka węzłów zagęszczona lub rozrzedzona)."""
    if not grads or not els:
        return els
    C = np.array([e.c for e in els])
    for gr in grads:
        prm = gr.get('param')
        g = gradient_field(gr, C, centroid)
        vals = np.array([_lerp(gr, x) for x in g]) if len(g) else g
        if prm == 'height':
            base = max(float(p['height']), 1e-9)
            for e, v in zip(els, vals):
                e.hs = max(v, 0.0) / base
        elif prm == 'depth':
            base = max(float(p['depth']), 1e-9)
            for e, v in zip(els, vals):
                e.hd = max(v, 0.0) / base
        elif prm == 'size':
            base = max(float(p['size']), 1e-9)
            for e, v in zip(els, vals):
                f = max(v, 0.02) / base
                if e.kind == 'poly':
                    e.poly = e.c + (e.poly - e.c) * f
                    e.holes = [e.c + (h - e.c) * f for h in e.holes]
                elif e.kind == 'dome':
                    e.d *= f
                elif e.kind == 'bar':
                    e.w *= f
        elif prm == 'angle':
            for e, v in zip(els, vals):
                R = tp.rot(math.radians(v))
                if e.kind == 'poly':
                    e.poly = e.c + (e.poly - e.c) @ R.T
                    e.holes = [e.c + (h - e.c) @ R.T for h in e.holes]
                elif e.kind == 'bar':
                    m = (np.asarray(e.p0) + np.asarray(e.p1)) / 2
                    e.p0 = m + (np.asarray(e.p0) - m) @ R.T
                    e.p1 = m + (np.asarray(e.p1) - m) @ R.T
        elif prm == 'wall':
            base = max(float(p['wall']), 1e-9)
            for e, v in zip(els, vals):
                if e.kind == 'poly' and len(e.poly) >= 3 and v > 0:
                    try:
                        from . import vent_layout as vl
                        q = vl.inset_convex(e.poly, max(v - base, -base * .9) / 2 * -1.0)
                        if len(q) >= 3:
                            e.poly = q
                    except Exception:
                        pass
        elif prm in ('spacing', 'density'):
            pass                                                     # obsłużone w warp_positions (przed generowaniem)
    return els


def _warp_for(p, grads, centroid, lo, hi):
    """Odwzorowanie położeń elementów dla gradientów rozstawu / gęstości (liniowy i promieniowy): współrzędna wzdłuż osi gradientu
    jest rozciągana tak, że lokalny rozstaw = wartość gradientu / wartość bazowa. Zwraca funkcję Nx2 → Nx2 albo None."""
    gs = [gr for gr in grads or [] if gr.get('param') in ('spacing', 'density') and gr.get('type', 'linear') in ('linear', 'radial')]
    if not gs:
        return None
    gr = gs[0]
    base = max(float(p['px']) or float(p['size']), 1e-9)
    def factor(g):
        v = _lerp(gr, g)
        if gr['param'] == 'density':
            return 1.0 / max(v, .05)
        return max(v, .02) / base
    L = max(float(gr.get('length', 50.0)), 1e-6)
    ss = np.linspace(0, L * 1.5, 600)
    f = np.array([factor(min(s / L, 1.0)) for s in ss])
    real = np.r_[0, np.cumsum(f[:-1] * np.diff(ss))]                 # współrzędna rzeczywista dla współrzędnej siatki
    c = np.array([float(gr.get('cx', centroid[0])), float(gr.get('cy', centroid[1]))])
    d = np.array([math.cos(math.radians(float(gr.get('angle', 0.0)))), math.sin(math.radians(float(gr.get('angle', 0.0))))])
    radial = gr.get('type') == 'radial'
    start = L / 2 if not radial else 0.0

    def warp(Q):
        Q = np.asarray(Q, float)
        if radial:
            r = np.linalg.norm(Q - c, axis=1)
            rr = np.interp(r, ss, real)
            u = (Q - c) / np.maximum(r, 1e-9)[:, None]
            return c + u * rr[:, None]
        s = (Q - c) @ d + start
        s2 = np.interp(np.clip(s, 0, ss[-1]), ss, real)
        return Q + d * (s2 - s)[:, None]
    return warp


def _fit_frame(p, group, region, report, seed_origin=None):
    """Układ wzoru (początek, obrót, skala) i skorygowane parametry według trybu dopasowania; dla powierzchni zamkniętych
    (walec) liczba powtórzeń na obwodzie jest całkowita - bez podwójnych elementów na szwie."""
    p = dict(p)
    lo, hi = region.lo, region.hi
    cen = (np.asarray(lo) + np.asarray(hi)) / 2
    fit = p.get('fit', 'exact')
    fr0 = tp.Frame(cen, float(p['angle']), float(p['sx']), float(p['sy']), bool(p['mirror']))
    a, b = fr0.uv_box(lo, hi)
    margin = float(p['margin'])
    size = float(p['size'])
    px0 = float(p['px']) or size
    py0 = float(p['py']) or px0
    ext = (b - a) - 2 * margin
    O = cen.copy()
    shift_uv = np.zeros(2)
    if fit in ('auto', 'fill', 'count', 'proportion', 'stretch', 'edge'):
        nx = int(p['nx']) or max(1, int(round(ext[0] / max(px0, 1e-6))))
        ny = int(p['ny']) or max(1, int(round(ext[1] / max(py0, 1e-6))))
        if fit == 'fill':
            ext = b - a
            nx = int(p['nx']) or max(1, int(math.ceil(ext[0] / max(px0, 1e-6))))
            ny = int(p['ny']) or max(1, int(math.ceil(ext[1] / max(py0, 1e-6))))
        if fit == 'edge':
            nx = max(1, int(round(ext[0] / max(px0, 1e-6))))
            ny = max(1, int(round(ext[1] / max(py0, 1e-6))))
            sx_, sy_ = px0, py0
        elif fit == 'proportion':
            f = ext[0] / (nx * px0)
            sx_, sy_ = px0 * f, py0 * f
        elif fit == 'stretch':
            sx_, sy_ = ext[0] / nx, ext[1] / ny
            p['sx'] = float(p['sx']) * sx_ / px0
            p['sy'] = float(p['sy']) * sy_ / py0
            sx_, sy_ = px0, py0
        else:
            sx_, sy_ = ext[0] / nx, ext[1] / ny
        if fit != 'stretch':
            p['px'], p['py'] = sx_, sy_
        lo_u = a + (margin if fit != 'fill' else 0.0)
        shift_uv = lo_u + np.array([sx_, sy_]) / 2
        if fit == 'stretch':
            shift_uv = lo_u + np.array([ext[0] / nx, ext[1] / ny]) / 2
        report.append(('ok', f'Dopasowanie: {nx} × {ny} powtórzeń, rozstaw {p["px"]:.3g} × {p["py"]:.3g} mm.'))
    elif fit == 'center':
        shift_uv = np.zeros(2)
    elif fit == 'start':
        org = p.get('origin_xy')
        if org is None:
            report.append(('warning', 'Tryb „od wskazanego punktu”: nie wskazano punktu - wzór zaczyna się w środku obszaru.'))
        else:
            O = np.asarray(org, float)
    else:
        shift_uv = a + margin + np.array([px0, py0]) / 2 - np.array([0.0, 0.0])
        shift_uv = np.zeros(2) + (a + margin + np.array([px0, py0]) / 2)
    # powierzchnia zamknięta (walec): całkowita liczba powtórzeń na obwodzie, szew pomiędzy elementami
    m0 = group.mappers[0]
    if len(group.mappers) == 1 and m0.mode == 'unwrap' and m0.kind == 'cylinder' and m0._closed():
        per = 2 * math.pi * m0.R
        pxe = float(p['px']) or tp.default_pitch(p)
        n = max(1, int(round(per / (pxe / max(float(p['density']), .05)))))
        step = per / n
        if abs(step - pxe) > 1e-9 and p.get('pattern') in ('knurl_cross', 'knurl_straight', 'dots', 'pyramids', 'honeycomb', 'scales', 'checker', 'weave', 'triangles', 'herringbone', 'knurl_spiral'):
            p['px'] = step * max(float(p['density']), .05)
            if not float(p['py']):
                p['py'] = pxe * 1.0
            report.append(('ok', f'Walec: {n} powtórzeń na obwodzie ({per:.2f} mm) - rozstaw {step:.3f} mm, bez podwójnych elementów na szwie.'))
        if abs(float(p['angle'])) < 1e-9:
            shift_uv = np.array([a[0] + step / 2, shift_uv[1]]) if fit in ('exact', 'center', 'auto', 'fill') else shift_uv
            shift_uv = np.array([-per / 2 + step / 2 - 0.0 * margin, shift_uv[1]]) if fit in ('exact', 'center') else shift_uv
    Rot = tp.rot(math.radians(float(p['angle'])))
    S = np.array([float(p['sx']) * (-1 if p['mirror'] else 1), float(p['sy'])])
    O = O + (shift_uv * S) @ Rot.T if fit != 'start' else O
    O = O + np.array([float(p['ox']), float(p['oy'])])
    return p, tp.Frame(O, float(p['angle']), float(p['sx']), float(p['sy']), bool(p['mirror']))


def _filter(els, allowed, boundary, report, group):
    """Elementy w dozwolonym obszarze: pełne zostają, częściowe są przycinane (clip), usuwane (remove) albo cały wzór jest dopasowany
    (fit - jak remove po dopasowaniu rozstawu). Elementy punktowe (kopuły, bryły) wymagają całego koła w obszarze."""
    outers, holes = allowed
    R = g2.Region(outers, holes)
    out = []
    if not els:
        return out, 0, 0
    removed = clipped = 0
    polys = [e for e in els if e.kind == 'poly']
    if polys:
        counts = [len(e.poly) for e in polys]
        V = np.vstack([e.poly for e in polys])
        inside = R.contains(V)
        starts = np.r_[0, np.cumsum(counts)]
        full = np.array([inside[a:b].all() for a, b in zip(starts[:-1], starts[1:])])
        any_in = np.array([inside[a:b].any() for a, b in zip(starts[:-1], starts[1:])])
        # pełne wg wierzchołków, ale krawędź mogła przeciąć wcięcie obszaru: kontrola punktów środkowych boków
        for e, f, a_ in zip(polys, full, any_in):
            if f:
                M = (e.poly + np.roll(e.poly, -1, axis=0)) / 2
                f = bool(R.contains(M).all()) and bool(R.contains(e.c)[0] or e.holes or True)
            if f:
                out.append(e)
            elif not a_ and not R.contains(e.c)[0]:
                removed += 1
            elif boundary == 'clip':
                for loops in g2.occ_clip([e.poly] + list(e.holes), outers, holes):
                    q = loops[0]
                    if abs(tt.ccw(q)) < 1e-4:
                        continue
                    ne = tp.El('poly', q.mean(0), poly=q, holes=loops[1:], hs=e.hs, hd=e.hd, sign=e.sign, k=1.0,
                               tilt=e.tilt, idx=e.idx, extra=e.extra)
                    out.append(ne)
                    clipped += 1
            else:
                removed += 1
    for e in els:
        if e.kind == 'poly':
            continue
        if e.kind == 'bar':
            runs = _bar_runs(e, R)
            for (a, b) in runs:
                ne = tp.El('bar', (np.asarray(a) + np.asarray(b)) / 2, p0=a, p1=b, w=e.w, prof=e.prof, k=e.k, hs=e.hs, hd=e.hd, sign=e.sign, idx=e.idx)
                out.append(ne)
            if not runs:
                removed += 1
            elif len(runs) > 1 or np.linalg.norm(np.asarray(runs[0][0]) - e.p0) + np.linalg.norm(np.asarray(runs[0][1]) - e.p1) > 1e-6:
                clipped += 1
                if boundary == 'remove' or boundary == 'fit':
                    pass
            continue
        if e.kind == 'field':
            out.append(e)
            continue
        r = e.extent()
        c = np.asarray(e.c).reshape(1, 2)
        if not R.contains(c)[0]:
            removed += 1
            continue
        dist = min(float(R.edge_dist(c)[0]), float(R.hole_dist(c)[0]))
        if dist >= r - 1e-9:
            out.append(e)
        else:
            removed += 1
    if boundary in ('remove', 'fit'):                                 # tylko pełne elementy
        out = [e for e in out if _is_full(e, R)]
    return out, removed, clipped


def _is_full(e, R):
    if e.kind == 'poly':
        return bool(R.contains(e.poly).all())
    return True


def _bar_runs(e, R, step=.4):
    """Odcinki belki leżące w obszarze (próbkowanie co step mm, końce dopracowane połowieniem)."""
    p0, p1 = np.asarray(e.p0, float), np.asarray(e.p1, float)
    L = float(np.linalg.norm(p1 - p0))
    n = max(2, int(L / step) + 1)
    t = np.linspace(0, 1, n)
    Q = p0 + (p1 - p0) * t[:, None]
    ins = R.contains(Q)
    runs = []
    i = 0
    while i < n:
        if not ins[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and ins[j + 1]:
            j += 1
        a, b = t[i], t[j]
        if i > 0:
            lo_, hi_ = t[i - 1], t[i]
            for _ in range(12):
                m = (lo_ + hi_) / 2
                if R.contains(p0 + (p1 - p0) * m)[0]:
                    hi_ = m
                else:
                    lo_ = m
            a = hi_
        if j < n - 1:
            lo_, hi_ = t[j], t[j + 1]
            for _ in range(12):
                m = (lo_ + hi_) / 2
                if R.contains(p0 + (p1 - p0) * m)[0]:
                    lo_ = m
                else:
                    hi_ = m
            b = lo_
        if (b - a) * L > .15:
            runs.append((p0 + (p1 - p0) * a, p0 + (p1 - p0) * b))
        i = j + 1
    return runs


def assign_signs(p, els, mode):
    """Znak elementu: +1 wypustka, -1 zagłębienie. Tryb mieszany: naprzemiennie (szachownica), losowo (udział procentowy) albo rzędami."""
    if mode in ('convex', 'separate', 'preview'):
        for e in els:
            e.sign = 1
        return
    if mode == 'concave':
        for e in els:
            e.sign = -1
        return
    rule = p.get('mixed_rule', 'alternate')
    size = max(float(p.get('size', 4)) * .8, .5)
    pct = float(p.get('mixed_pct', 50)) / 100.0
    rng = np.random.default_rng(int(p.get('seed', 1)) + 7)
    flags = {tuple(): None}
    for k, e in enumerate(els):
        if p.get('pattern') == 'triangles' and p.get('alternate', True):
            continue                                                  # znak z wzoru (trójkąty do góry / w dół)
        if rule == 'random':
            e.sign = -1 if rng.random() < pct else 1
        elif rule == 'rows':
            e.sign = -1 if int(math.floor(e.c[1] / size)) % 2 else 1
        else:
            e.sign = -1 if (int(math.floor(e.c[0] / size)) + int(math.floor(e.c[1] / size))) % 2 else 1
    if p.get('pattern') == 'triangles' and p.get('alternate', True):
        pass



def _resolve_curves(grads, by_id, mapper, T, report):
    """Gradient „wzdłuż krzywej”: punkty szkicu wskazanego identyfikatorem rzutowane na dziedzinę pierwszej ściany."""
    out = []
    for gr in grads or []:
        if gr.get('type') == 'curve' and gr.get('curve') and gr.get('curve_pts') is None:
            sk = by_id.get(gr['curve'])
            pts = None
            if sk is not None and hasattr(sk.shape, 'Edges'):
                try:
                    from OCP.BRepAdaptor import BRepAdaptor_Curve
                    P3 = []
                    for e in sk.shape.Edges():
                        c = BRepAdaptor_Curve(e.wrapped)
                        for t in np.linspace(c.FirstParameter(), c.LastParameter(), 24 if c.GetType() != 0 else 2):
                            P3.append(c.Value(t).Coord())
                    pts = np.array([(np.r_[mapper.to2d(np.asarray(q, float)), 1.0] @ T.T)[:2] for q in P3])
                except Exception:
                    pts = None
            if pts is None or len(pts) < 2:
                report.append(('warning', 'Gradient wzdłuż krzywej: szkic krzywej nie istnieje albo nie leży na powierzchni - użyto gradientu liniowego.'))
                gr = dict(gr, type='linear')
            else:
                gr = dict(gr, curve_pts=pts)
        out.append(gr)
    return out

def plan(bodies, recipe, cancel=None):
    """Plan bez Boolean: ściany, odwzorowania, obszary z marginesami, elementy 2D. Szybki podgląd i podstawa budowy."""
    t0 = time.time()
    p = params(recipe)
    by_id = {b.id: b for b in bodies}
    tb = by_id.get(recipe['target'])
    if tb is None or tb.kind != 'solid':
        raise kernel.CadError('Bryły z teksturą już nie ma.')
    faces = vf.match_faces(tb.shape, recipe['faces'])
    if not faces:
        raise kernel.CadError('Zaznacz co najmniej jedną powierzchnię.')
    for k in ('size',):
        if float(p[k]) <= 0:
            raise kernel.CadError('Wielkość elementu musi być większa od zera.')
    for k in ('height', 'depth'):
        if float(p[k]) < 0:
            raise kernel.CadError('Wysokość i głębokość nie mogą być ujemne.')
    multi = recipe.get('multi', 'independent')
    mode = recipe.get('mapping', 'auto')
    report = []
    groups = []
    gx = _group_faces(faces, multi, mode, report, float(recipe.get('map_rotate', 0.0)))
    first_origin = None
    for gi, (ms, Ts) in enumerate(gx):
        G = Group(ms, Ts)
        outs, hols = [], []
        for m, T in zip(ms, Ts):
            o, h = m.boundary()
            outs += [(np.c_[q, np.ones(len(q))] @ T.T)[:, :2] for q in o]
            hols += [(np.c_[q, np.ones(len(q))] @ T.T)[:, :2] for q in h]
        if len(ms) > 1:
            outs = vf._merge_outlines(outs)
        G.region = _region(recipe, ms[0], outs, hols, bodies)
        zones = vf._zones_for(ms[0], recipe, bodies, recipe['target'])
        G.allowed = allowed_region(G.region, zones, max(float(p['margin']), MIN_MARGIN), float(p['margin_holes']))
        pg = dict(p)
        if p.get('origin') is not None:
            try:
                pg['origin_xy'] = ms[0].to2d(np.asarray(p['origin'], float))
            except Exception:
                pass
        if multi == 'origin' and p.get('origin') is None and first_origin is not None:
            pg['origin_xy'] = ms[0].to2d(first_origin)
            pg['fit'] = 'start'
        if multi == 'origin' and first_origin is None:
            first_origin = ms[0].eval_uv(ms[0].uc, ms[0].vc)[0]
        if multi == 'direction' and gi > 0:
            pass                                                      # kierunek wzoru: ten sam wektor globalny (obrót odwzorowania)
        if multi == 'phase' and pg['fit'] == 'exact':
            pg['fit'] = 'edge'
        region_for_fit = g2.Region(G.allowed[0], G.allowed[1]) if G.allowed[0] else G.region
        pg, G.frame = _fit_frame(pg, G, G.region, report)
        G.p = pg
        lo, hi = G.region.lo - 2 * float(pg['size']), G.region.hi + 2 * float(pg['size'])
        warp = _warp_for(pg, pg.get('gradients'), G.region.centroid(), lo, hi)
        ext = hi - lo
        if warp is not None:
            lo, hi = lo - ext * .6, hi + ext * .6
        els = tp.generate(pg, G.frame, lo, hi)
        if warp is not None:
            for e in els:
                d = warp(e.c[None])[0] - e.c
                e.c = e.c + d
                if e.poly is not None:
                    e.poly = e.poly + d
                    e.holes = [h + d for h in e.holes]
                if e.p0 is not None:
                    e.p0 = np.asarray(e.p0) + d
                    e.p1 = np.asarray(e.p1) + d
        if len(els) > LIMIT_MESH:
            raise kernel.CadError(f'Za dużo elementów tekstury ({len(els)}) - największa liczba to {LIMIT_MESH}; zwiększ rozstaw albo wielkość elementów.')
        if cancel is not None and cancel():
            raise kernel.CadError('Obliczenia przerwane - model bez zmian.')
        n0 = len(els)
        fld = [e for e in els if e.kind == 'field']
        if fld:
            G.field = fld[0]
            els = []
        else:
            els, removed, clipped = _filter(els, G.allowed, pg['boundary'], report, G)
            if removed or clipped:
                report.append(('ok', f'Granice: {clipped} elementów przyciętych, {removed} usuniętych (poza obszarem lub niepełnych).'))
        grads = _resolve_curves(pg.get('gradients'), by_id, ms[0], Ts[0], report)
        els = apply_gradients(pg, els, grads, G.region.centroid(), recipe.get('p', {}).get('mode', 'convex'), report)
        assign_signs(pg, els, pg['mode'])
        G.elements = els
        groups.append(G)
    n = sum(len(g.elements) for g in groups)
    return dict(target=tb, faces=faces, groups=groups, report=report, count=n, time_plan=time.time() - t0, p=p)


SURFACE_FACTOR = {'torus': 8.0, 'bspline': 4.0, 'bezier': 4.0, 'sphere': 1.5, 'cylinder': 1.2, 'cone': 1.3, 'revolution': 4.0, 'extrusion': 2.0, 'other': 3.0}


PATTERN_FACTOR = {'scales': 5.0, 'weave': 3.0, 'pyramids': 1.5, 'waves': 2.0}   # nakładające się elementy i skomplikowane bryły liczą się dłużej


def surface_factor(recipe):
    """Mnożnik kosztu operacji Boolean zależny od rodzaju powierzchni (torus i B-Spline są wielokrotnie wolniejsze od płaszczyzny)."""
    f = 1.0
    for r in recipe.get('faces') or []:
        f = max(f, SURFACE_FACTOR.get(str(r.get('kind', '')).lower(), 1.0))
    return f * PATTERN_FACTOR.get((recipe.get('p') or {}).get('pattern'), 1.0)


def complexity(n, accuracy='exact', factor=1.0):
    """Informacja o przewidywanej złożoności: liczba elementów, szacowany czas, tryb zalecany."""
    n0, n = n, n * factor
    t = n / EXACT_PER_S
    if n <= 300:
        label = 'mała'
    elif n <= 2500:
        label = 'średnia'
    elif n <= LIMIT_EXACT:
        label = 'duża'
    elif n <= LIMIT_OPT:
        label = 'bardzo duża - zalecany zoptymalizowany B-Rep'
    else:
        label = 'ekstremalna - zalecany tryb siatkowy'
    return dict(label=label, seconds=t, elements=n0)


# ---------------------------------------------------------------------------------------------- narzędzia przestrzenne
MIN_MARGIN = .1          # elementy nie dotykają krawędzi ściany (styczność daje niepoprawne bryły po Boolean)
TILE_FROM = 600


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


class Ctx:
    """Wspólne dane budowy: parametry, grubość ścianek, liczniki stanu elementów."""

    def __init__(self, p, solid, bodies, mode, opt=False, separate=False):
        self.p, self.mode, self.opt, self.separate = p, mode, opt, separate
        self.solid = solid
        self.thick = vc.Thickness(solid) if bool(p.get('protect_wall', True)) or True else None
        self.bodies = bodies
        self.count = dict(ok=0, thin=0, bad=0, skipped=0)
        self.thin_pts = []
        self.bad_pts = []
        self.proto = None
        self.tol = float(p.get('tol', .05))
        self.tools_up, self.tools_down = [], []
        self.seam_check = False


def _proto_solid(ctx, p):
    """Bryła użytkownika jako element: kształt wyśrodkowany, dolna ściana w z = 0, skala c_scale."""
    if ctx.proto is not None:
        return ctx.proto
    bid = p.get('custom_body')
    body = {b.id: b for b in ctx.bodies}.get(bid)
    if body is None or body.kind != 'solid':
        raise kernel.CadError('Własny wzór: wskaż bryłę, która ma być powtarzanym elementem.')
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Pnt, gp_Trsf, gp_Vec
    sh = body.shape.wrapped
    b = Bnd_Box()
    BRepBndLib.Add_s(sh, b, False)
    x0, y0, z0, x1, y1, z1 = b.Get()
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(-(x0 + x1) / 2, -(y0 + y1) / 2, -z0))
    sh = BRepBuilderAPI_Transform(sh, t, True).Shape()
    sc = float(p.get('c_scale', 1.0))
    if abs(sc - 1.0) > 1e-9:
        t2 = gp_Trsf()
        t2.SetScale(gp_Pnt(0, 0, 0), sc)
        sh = BRepBuilderAPI_Transform(sh, t2, True).Shape()
    ctx.proto = sh
    return sh


def _heights(el, p):
    h_up = float(p['height']) * el.hs
    h_dn = float(p['depth']) * (el.hd if el.hd is not None else el.hs)
    return h_up, h_dn


def _embed(h, sag, thick_wall):
    e = max(.12, .12 * h) + 1.2 * sag
    if thick_wall is not None:
        e = min(e, max(.08, .7 * thick_wall))
    return e


def _piece_tools(el, G, ctx, h, sign, report_pts):
    """Listwa: dzielona na odcinki o błędzie cięciwy poniżej tolerancji (na walcu / kuli); każdy odcinek to profil wytłoczony wzdłuż."""
    p = ctx.p
    a, b = np.asarray(el.p0, float), np.asarray(el.p1, float)
    L = float(np.linalg.norm(b - a))
    m0, _q = G.locate((a + b) / 2)
    k = _kmax(m0)
    tolc = max(.03, .15 * h)
    Lseg = L if k < 1e-6 else max(.6, math.sqrt(8 * tolc / k))
    n = max(1, int(math.ceil(L / Lseg)))
    out = []
    for i in range(n):
        s0, s1 = i / n, (i + 1) / n
        qa, qb = a + (b - a) * s0, a + (b - a) * s1
        ov = min(.15, el.w * .1) if n > 1 else 0.0
        if n > 1:
            d = (b - a) / L
            qa = qa - d * ov if i > 0 else qa
            qb = qb + d * ov if i < n - 1 else qb
        qm = (qa + qb) / 2
        try:
            Pm, Nm, Xm, Ym, mm = G.frame_at(qm)
            Pa = G.frame_at(qa)[0]
            Pb = G.frame_at(qb)[0]
        except kernel.CadError:
            ctx.count['bad'] += 1
            continue
        A = Pb - Pa
        A = A - Nm * float(A @ Nm)
        Lp = float(np.linalg.norm(A))
        if Lp < 1e-6:
            continue
        A = A / Lp
        sag = _kmax(mm) * (el.w / 2) ** 2 / 2
        tw = ctx.thick.wall(Pm, -Nm) if ctx.thick is not None else None
        if sign < 0 and ctx.p.get('protect_wall', True) and tw is not None and tw - h - (0 if sag < 0 else 0) < float(ctx.p['min_wall']):
            ctx.count['thin'] += 1
            ctx.thin_pts.append(Pm)
            continue
        e = _embed(h, sag, tw)
        prof = el.prof
        trap = el.k if el.k else .4
        s = tt.ridge(prof, el.w, h * sign, Lp, e, trap)
        if s is None:
            ctx.count['bad'] += 1
            continue
        X = np.cross(A, Nm)
        P0 = Pm - A * Lp / 2
        out.append(tt.placed(s, P0, Nm, X))
    return out


def tool_for(el, G, ctx, p):
    """Bryły narzędzi jednego elementu (lista; pusta - element pominięty, stan w ctx.count)."""
    sign = el.sign if ctx.mode in ('mixed',) else (-1 if ctx.mode == 'concave' else 1)
    h_up, h_dn = _heights(el, p)
    h = h_up if sign > 0 else h_dn
    if h <= 1e-6:
        ctx.count['skipped'] += 1
        return []
    if el.kind == 'bar':
        out = _piece_tools(el, G, ctx, h, sign, None)
        if out:
            ctx.count['ok'] += 1
        return out
    try:
        P, N, X, Y, m = G.frame_at(el.c)
    except kernel.CadError:
        ctx.count['bad'] += 1
        ctx.bad_pts.append(el.c)
        return []
    r = el.extent()
    kk = _kmax(m)
    if kk * r >= .95:
        ctx.count['bad'] += 1
        ctx.bad_pts.append(P)
        return []
    sag = kk * r * r / 2 if kk * r < .5 else (1 / kk) * (1 - math.sqrt(max(0.0, 1 - (kk * r) ** 2)))
    tw = ctx.thick.wall(P, -N) if (sign < 0 or kk > 1e-4) else None
    if sign < 0 and p.get('protect_wall', True) and tw is not None and tw - h < float(p['min_wall']):
        ctx.count['thin'] += 1
        ctx.thin_pts.append(P)
        return []
    e = _embed(h, sag, tw) if not ctx.separate else 0.02
    sg = 1.0 if float(np.dot(np.cross(N, X), Y)) >= 0 else -1.0
    sol = None
    if el.kind == 'poly':
        V = (el.poly - el.c) * [1.0, sg]
        H = [(hh - el.c) * [1.0, sg] for hh in el.holes]
        k = el.k
        tilt = (el.tilt[0], el.tilt[1] * sg)
        if abs(k - 1.0) > 1e-9 and not H:
            k0 = 1.0 + (1.0 - k) * e / max(h, 1e-6)
            tl = tilt
            if sign > 0:
                sol = tt.prism(V, H, -e, h, k=k, shift=tl, k0=k0)
            else:
                sol = tt.prism(V, H, e, -h, k=k, shift=(-tl[0], -tl[1]), k0=k0)
        else:
            if sign > 0:
                sol = tt.prism(V, H, -e, h, shift=tilt)
            else:
                sol = tt.prism(V, H, e, -h, shift=(-tilt[0], -tilt[1]))
        if sol is not None and sign > 0 and float(p.get('edge_round', 0)) > 1e-6 and not ctx.opt and not H:
            sol = tt.fillet_top(sol, min(float(p['edge_round']), h * .45, r * .3), h)
    elif el.kind == 'dome' and ctx.seam_check and el.shape == 'hemisphere' and abs(el.hs - 1.0) < 1e-6 and (el.hd is None or abs(el.hd - 1.0) < 1e-6) and (tw is None or tw > el.d * .5 + float(p['min_wall'])):
        # stożek, torus, B-Spline: obrotowy kołnierz z szwem daje czasem niepoprawną ścianę po Boolean - kula o środku na powierzchni nie ma tego problemu
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
        ctx.count['ok'] += 1
        return [BRepPrimAPI_MakeSphere(gp_Ax2(gp_Pnt(*map(float, P)), gp_Dir(*map(float, N)), gp_Dir(*map(float, X))), float(el.d) / 2).Shape()]
    elif el.kind == 'dome':
        trunc = el.k if el.k else .5
        kind_ = el.shape
        hh = h * sign
        if kind_ == 'hemisphere' and abs((el.hs if sign > 0 else (el.hd if el.hd is not None else el.hs)) - 1.0) > 1e-6:
            kind_, hh = 'cap', (el.d / 2) * (el.hs if sign > 0 else (el.hd if el.hd is not None else el.hs)) * sign      # gradient wysokości: czasza o proporcjonalnej wysokości
        sol = tt.dome(kind_, el.d, hh, e, trunc)
    elif el.kind == 'solid':
        proto = _proto_solid(ctx, p)
        from OCP.TopLoc import TopLoc_Location
        Nn = N if sign > 0 else -N
        Xr = tp.rot(el.ang + math.radians(float(p.get('c_rot', 0.0))))
        xr = _unit(X * math.cos(el.ang) + np.cross(N, X) * math.sin(el.ang))
        base = P - N * e if sign > 0 else P + N * e
        sol = proto.Moved(tt.location(base, Nn, xr))
        ctx.count['ok'] += 1
        return [sol]
    if sol is None:
        ctx.count['bad'] += 1
        ctx.bad_pts.append(P)
        return []
    ctx.count['ok'] += 1
    return [tt.placed(sol, P, N, X)]


def _tool_volumes(tools):
    return sum(abs(tt.volume(t)) for t in tools[:400]) / max(min(len(tools), 400), 1) * len(tools) if tools else 0.0


def build_tools(pl, recipe, ctx, cancel=None, progress=None):
    """Narzędzia wszystkich elementów (lista wypustek i lista zagłębień) oraz pola wysokości (fale, obraz)."""
    p = ctx.p
    ups, downs = [], []
    total = max(pl['count'], 1)
    done = 0
    for G in pl['groups']:
        pg = G.p
        for el in G.elements:
            done += 1
            if cancel is not None and done % 25 == 0 and cancel():
                raise kernel.CadError('Obliczenia przerwane - model bez zmian.')
            if progress is not None and done % 50 == 0:
                progress(.5 * done / total)
            sign = el.sign if ctx.mode == 'mixed' else (-1 if ctx.mode == 'concave' else 1)
            for t in tool_for(el, G, ctx, pg):
                (ups if sign > 0 else downs).append(t)
        if G.field is not None:
            from . import tex_relief as tr
            u2, d2 = tr.field_tools(G, pl, recipe, ctx, cancel)
            ups += u2
            downs += d2
    return ups, downs


def _stats(pl, ctx, ups, downs):
    return dict(count=pl['count'], tools=len(ups) + len(downs), ok=ctx.count['ok'], thin=ctx.count['thin'], bad=ctx.count['bad'], skipped=ctx.count['skipped'],
                raised=len(ups), recessed=len(downs), complexity=complexity(pl['count'])['label'], est_seconds=complexity(pl['count'])['seconds'])


def _build_once(bodies, recipe, cancel=None, progress=None, exact=True):
    """Operacja Tekstury: (bryła wynikowa, plan, raport, statystyki). exact=False - tylko plan i narzędzia (podgląd przestrzenny)."""
    import cadquery as cq
    from .enclosure import _volume
    t0 = time.time()
    p = params(recipe)
    mode = p.get('mode', 'convex')
    pl = plan(bodies, recipe, cancel)
    tb = pl['target']
    solid = tb.shape.wrapped
    report = list(pl['report'])
    n = pl['count']
    acc = p.get('accuracy', 'exact')
    limit = LIMIT_EXACT if acc == 'exact' else LIMIT_OPT
    pl_mesh = False
    kf = surface_factor(recipe)
    if kf > 1.0 and n * kf > limit >= n:
        report.append(('warning', f'Powierzchnia {recipe["faces"][0].get("kind", "")} jest trudna dla operacji Boolean (≈{kf:g}× wolniej niż płaszczyzna): {n} elementów przekracza bezpieczną granicę.'))
    n_eff = n * kf
    if n_eff > limit and acc != 'mesh':
        n = n_eff
        if recipe.get('auto_mesh', True):
            acc = 'mesh'
            report.append(('warning', f'{n} elementów przekracza granicę trybu {"dokładnego" if p.get("accuracy") == "exact" else "zoptymalizowanego"} B-Rep ({limit}) - wynik zostanie zapisany jako siatka '
                                      f'(STL / 3MF, bez dalszej edycji B-Rep). Aby zachować B-Rep, zwiększ rozstaw albo wielkość elementów.'))
        else:
            raise kernel.CadError(f'Za dużo elementów dla trybu B-Rep ({n:.0f} > {limit}) - wybierz tryb siatkowy albo zwiększ rozstaw.')
    ctx = Ctx(p, solid, bodies, mode, opt=acc != 'exact', separate=mode == 'separate')
    ctx.seam_check = acc != 'mesh' and any(str(r.get('kind', '')).lower() in ('cone', 'torus', 'bspline', 'other') for r in recipe.get('faces') or [])
    if n == 0 and not any(g.field is not None for g in pl['groups']):
        raise kernel.CadError('Żaden element tekstury nie mieści się w obszarze - zmień rozmiar, marginesy albo obszar.')
    ups, downs = build_tools(pl, recipe, ctx, cancel, progress)
    stats = _stats(pl, ctx, ups, downs)
    if ctx.count['thin']:
        report.append(('warning', f'{ctx.count["thin"]} elementów pominięto, bo pozostałaby ścianka cieńsza niż {p["min_wall"]:g} mm (ochrona grubości). Zmniejsz głębokość albo wyłącz ochronę.'))
    if ctx.count['bad']:
        report.append(('warning', f'{ctx.count["bad"]} elementów nie udało się zbudować (zbyt duże względem krzywizny albo niepoprawny profil).'))
    if not exact:
        return dict(shape=None, plan=pl, ups=ups, downs=downs, ctx=ctx, report=report, stats=stats)
    if not ups and not downs:
        raise kernel.CadError('Żaden element nie spełnia wymagań (ochrona grubości, krzywizna, obszar) - zmień parametry.')
    v0 = _volume(solid)[0]
    prog = (lambda f: progress(.5 + .4 * f)) if progress else None
    if mode == 'preview':
        return dict(shape=None, plan=pl, ups=ups, downs=downs, ctx=ctx, report=report + [('ok', 'Podgląd graficzny - model nie zostaje zmieniony.')], stats=stats)
    if mode == 'separate':
        sep = _separate(ups + downs, cancel)
        stats.update(volume=_volume(sep)[0])
        report.append(('ok', f'Wygenerowano {len(ups) + len(downs)} elementów jako osobne bryły.'))
        return dict(shape=cq.Shape.cast(sep), plan=pl, ups=ups, downs=downs, ctx=ctx, report=report, stats=stats, separate=True)
    if acc == 'mesh':
        from . import tex_mesh as tm
        res = tm.apply(solid, ups, downs, cancel=cancel, progress=prog, tol=ctx.tol)
        stats.update(removed=0.0, remaining=0.0, mesh=True, triangles=res['triangles'])
        report.append(('warning', f'Tryb siatkowy: {res["triangles"]} trójkątów, wynik nie jest bryłą B-Rep (eksport STL / 3MF; bez zaokrągleń, fazowań i eksportu STEP).'))
        return dict(shape=res['shape'], plan=pl, ups=ups, downs=downs, ctx=ctx, report=report + res['report'], stats=stats, mesh=True)
    res = solid
    up_vol = _tool_volumes(ups)
    dn_vol = _tool_volumes(downs)
    tiled_ok = False
    if ups:
        t = vc.cut_tiled(res, ups, cancel=cancel, progress=prog, op='fuse') if len(ups) > TILE_FROM else None
        tiled_ok = t is not None
        res = t if t is not None else vc.fuse_batches(res, ups, cancel=cancel, progress=prog)
    if downs:
        t = vc.cut_tiled(res, downs, cancel=cancel, progress=prog) if len(downs) > TILE_FROM else None
        tiled_ok = tiled_ok or t is not None
        res = t if t is not None else vc.cut_many(res, downs, cancel=cancel, progress=prog)
    res, rep2 = vc.check_result(res, True, unify=not (tiled_ok or len(ups) + len(downs) > 3000))
    if tiled_ok:
        vc.trust_result(res)
    report += rep2
    from .enclosure import _solids
    sols = [s for s in _solids(res) if _volume(s)[0] > 1e-6]
    if len(sols) > 1:
        if mode == 'convex' or (mode == 'mixed' and not downs):
            sols.sort(key=lambda s_: -_volume(s_)[0])
            extra = sols[1:]
            ev = sum(_volume(s_)[0] for s_ in extra)
            if ev <= .05 * max(up_vol, 1e-9) + 1e-6 and len(extra) <= max(3, len(ups) // 20):
                res = sols[0]
                report.append(('warning', f'{len(extra)} drobnych elementów przy krawędzi powierzchni nie dotykało bryły - pominięto je (łącznie {ev:.2f} mm³).'))
                sols = [res]
            else:
                raise kernel.CadError(f'{len(sols) - 1} elementów tekstury nie łączy się z bryłą - sprawdź wysokość i powierzchnię.')
    if len(sols) > 1:
        report.append(('warning', f'Wynik ma {len(sols)} rozłączne fragmenty (zagłębienia odcięły materiał).'))
    v1 = _volume(res)[0]
    if v1 <= 1e-6 or v1 < v0 * .02:
        raise kernel.CadError('Operacja usunęłaby prawie całą bryłę - zostaje poprzednia geometria (zmniejsz głębokość).')
    if ups and not downs and v1 < v0 - 1e-6 * max(v0, 1):
        raise kernel.CadError('Dodawanie wypustek zmniejszyło objętość - wynik niepoprawny, zostaje poprzednia geometria.')
    if downs and not ups and v1 > v0 + 1e-6 * max(v0, 1):
        raise kernel.CadError('Wycinanie zagłębień zwiększyło objętość - wynik niepoprawny, zostaje poprzednia geometria.')
    stats.update(volume_before=v0, volume_after=v1, added=max(v1 - v0, 0.0) if ups else 0.0, removed=max(v0 - v1, 0.0) if downs else 0.0)
    dens = float(recipe.get('density') or 0)
    if dens > 0:
        stats['mass_change'] = (v1 - v0) * dens / 1000.0
    stats['seconds'] = time.time() - t0
    stats['faces'] = len(cq.Shape.cast(res).Faces()) if len(ups) + len(downs) < 5000 else None
    report.append(('ok', f'Tekstura: {len(ups)} wypustek, {len(downs)} zagłębień; zmiana objętości {v1 - v0:+.1f} mm³.'))
    return dict(shape=cq.Shape.cast(res), plan=pl, ups=ups, downs=downs, ctx=ctx, report=report, stats=stats)



def build(bodies, recipe, cancel=None, progress=None, exact=True):
    """Operacja Tekstury. Relief (fale, obraz) z siatką punktów bywa numerycznie wrażliwy w operacji Boolean - przy niepoprawnym
    wyniku siatka jest rzedsza (do 3 prób), zamiast od razu zgłaszać błąd."""
    is_field = (recipe.get('p') or {}).get('pattern') in ('waves', 'image')
    k = 1.0
    last = None
    for attempt in range(4 if is_field and exact else 1):
        rec = recipe
        if attempt:
            rec = dict(recipe, p=dict(recipe.get('p') or {}, _cell_k=k))
        try:
            res = _build_once(bodies, rec, cancel, progress, exact)
            if attempt:
                res['report'].append(('warning', f'Siatka reliefu została zrzedzona {k:.2f}× (pierwsza próba dawała niepoprawną bryłę).'))
            return res
        except kernel.CadError as exc:
            last = exc
            msg = str(exc)
            if not is_field and exact and recipe.get('auto_mesh', True) and (recipe.get('p') or {}).get('accuracy', 'exact') != 'mesh' and \
                    any(t in msg for t in ('poprawną bryłą', 'nie łączy się', 'nie powiodło', 'zmniejszyło objętość', 'zwiększyło objętość', 'prawie całą bryłę')):
                # operacja B-Rep zawiodła (zwykle trudna powierzchnia: B-Spline, wyciągnięcie, obrót) - ta sama tekstura jako szczelna siatka
                try:
                    res = _build_once(bodies, dict(recipe, p=dict(recipe.get('p') or {}, accuracy='mesh')), cancel, progress, exact)
                    res['report'].insert(0, ('warning', f'Operacja B-Rep nie powiodła się ({msg[:110]}). Wynik zapisano jako siatkę - eksport STL / 3MF, bez STEP.'))
                    return res
                except kernel.CadError:
                    raise exc
            if 'poprawną bryłą' not in msg or not is_field:
                raise
            k *= 1.33
    raise last


def _separate(tools, cancel=None):
    """Elementy jako niezależne bryły: stykające się / nakładające scalone jedną operacją Fuse, rozłączne zostają osobno (Compound)."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.TopTools import TopTools_ListOfShape
    if len(tools) > 1 and len(tools) <= 4000:
        a, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
        a.Append(tools[0])
        for t in tools[1:]:
            tl.Append(t)
        op = BRepAlgoAPI_Fuse()
        op.SetArguments(a)
        op.SetTools(tl)
        op.SetRunParallel(True)
        op.Build()
        if op.IsDone():
            return op.Shape()
    comp = TopoDS_Compound()
    bld = BRep_Builder()
    bld.MakeCompound(comp)
    for t in tools:
        bld.Add(comp, t)
    return comp


def run(bodies, recipe):
    """Krok historii 'tex': bryła z teksturą (ta sama bryła, nowa geometria) albo nowa bryła z oddzielnych elementów."""
    from dataclasses import replace
    if recipe.get('disabled'):
        return list(bodies)
    p = params(recipe)
    if p.get('mode') == 'preview':
        return list(bodies)
    res = build(bodies, recipe)
    out = []
    sep = res.get('separate')
    for b in bodies:
        if b.id == recipe['target'] and not sep:
            meta = dict(b.meta or {})
            meta['tex'] = [*[r for r in meta.get('tex', []) if r.get('id') != recipe.get('id')], dict(id=recipe.get('id'), pattern=p.get('pattern'), stats=_jsonable(res['stats']), mesh=bool(res.get('mesh')))]
            if res.get('mesh'):
                meta['mesh_body'] = True
            b = replace(b, shape=res['shape'], meta=meta, mesh=None, source='stl' if res.get('mesh') else b.source).prepared()
        out.append(b)
    if sep:
        from .document import Body
        from .history import stable_id
        ids = list(recipe.get('out_ids') or []) or [stable_id(f'{recipe.get("id")}:tex', 0)]
        recipe['out_ids'] = ids
        tb = {b.id: b for b in bodies}[recipe['target']]
        out = [b for b in out if b.id != ids[0]] + [Body(f'{tb.name} - tekstura', res['shape'], id=ids[0], folder=tb.folder).prepared()]
    return out
