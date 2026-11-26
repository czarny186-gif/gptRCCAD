"""Wentylacja - operacja parametryczna (VentilationFeature): przepis → ściany (stabilne odniesienia: punkt, normalna,
środek, pole - jak pozostałe kroki historii) → odwzorowanie → obszary → wzór → narzędzia → cięcie → kontrola →
statystyki. Krok historii 'vent' (edycja, cofanie, wyłączanie, duplikowanie, regeneracja po zmianie bryły źródłowej).
Generator obudów może używać tej samej funkcji build()."""
from __future__ import annotations

import uuid

import numpy as np

from . import kernel
from . import vent_cut as vc
from . import vent_geom2d as g2
from . import vent_layout as vl
from . import vent_shapes as vs
from . import vent_surface as su

MULTI = ('independent', 'common', 'continue', 'fillets', 'wrap', 'outer')
MULTI_LABELS = {'independent': 'Niezależny wzór na każdej ścianie', 'common': 'Wspólne położenie wzoru (rzut)', 'continue': 'Kontynuacja przez krawędzie',
                'fillets': 'Kontynuacja przez zaokrąglenia', 'wrap': 'Zawijanie wokół bryły', 'outer': 'Wspólny wzór na całym zaznaczonym obszarze'}
CROSS = ('stop', 'margin', 'continue', 'cross')
CROSS_LABELS = {'stop': 'Zakończ wzór przed krawędzią', 'margin': 'Zachowaj margines od krawędzi', 'continue': 'Kontynuuj na następnej ścianie',
                'cross': 'Otwory przechodzące przez krawędź'}
CUT_DEFAULTS = dict(direction='normal', vector=None, dir_angle=60.0, tilt=0.0, reverse=False, depth_mode='wall', depth=1.0, depth2=1.0,
                    hole_type='through', size_in=1.0, size_out=.6, size_mid=.7, step_depth=1.0, step_scale=1.6, chamfer=.4,
                    louver_t=1.0, louver_angle=35.0, louver_h=3.0, louver_dir='up', profile_mode='tangent', obstacle_factor=1.6)
MAX_TOOLS = 20000
TILE_FROM = 600                                                        # od tylu narzędzi cięcie kawałkami (vent_cut.cut_tiled)


def face_refs(shape, faces):
    """Odniesienia do ścian (bez numerów indeksowych): punkt na ścianie, normalna w nim, środek, pole, rodzaj."""
    import cadquery as cq
    out = []
    for f in faces:
        cf = cq.Face(f) if not hasattr(f, 'wrapped') else f
        m = su.Mapper(cf.wrapped, 'uv')
        P, N, _x, _y = m.eval_uv(m.uc, m.vc)
        out.append(dict(point=[float(x) for x in P], normal=[float(x) for x in N], centroid=list(cf.Center().toTuple()),
                        area=float(cf.Area()), kind=su.surface_kind(cf.wrapped)))
    return out


def match_faces(shape, refs):
    """Ściany bryły odpowiadające zapisanym odniesieniom (ściana zawierająca punkt o zgodnej normalnej; po zmianie
    rozmiaru - najlepiej pasująca tego samego rodzaju)."""
    out = []
    for r in refs:
        try:
            f, _n = kernel.face_at(shape, r['normal'], r['point'], curved=True)
            out.append(f.wrapped if hasattr(f, 'wrapped') else f)
            continue
        except kernel.CadError:
            pass
        best = None
        for f in shape.Faces():
            if su.surface_kind(f.wrapped) != r.get('kind'):
                continue
            d = float(np.linalg.norm(np.array(f.Center().toTuple()) - np.array(r['centroid'])))
            score = d + abs(f.Area() - r['area']) / max(r['area'], 1e-9) * 10
            if best is None or score < best[0]:
                best = (score, f)
        if best is None:
            raise kernel.CadError('Ściana zaznaczona w operacji Wentylacja już nie istnieje - wskaż ściany ponownie.')
        out.append(best[1].wrapped)
    return out


def _zones_for(mapper, recipe, bodies, target_id):
    """Strefy zabronione w dziedzinie ściany: zaznaczone komponenty (rzut obrysu), szkice, strefy ręczne."""
    zones = []
    by_id = {b.id: b for b in bodies}
    for z in recipe.get('exclusions') or []:
        t = z.get('type')
        gap = float(z.get('gap', recipe.get('obstacle_gap', 2.0)))
        if t == 'component' and z.get('id') in by_id:
            from .enclosure_optimize import _points
            pts = _points(by_id[z['id']].shape)
            q2 = np.array([mapper.to2d(q) for q in pts[::max(1, len(pts) // 400)]])
            hull = np.array(vs._hull(q2))
            if len(hull) >= 3:
                zones.append(dict(poly=hull, gap=gap, name=by_id[z['id']].name))
        elif t == 'sketch' and z.get('id') in by_id:
            for lp in _sketch_loops(by_id[z['id']]):
                zones.append(dict(poly=np.array([mapper.to2d(q) for q in lp]), gap=gap, name='szkic'))
        elif t in ('rect', 'circle', 'polygon'):
            o, h_ = su.region_polys(dict(z, type=t), [], [])
            for q in o:
                zones.append(dict(poly=q, gap=gap, name=z.get('name', 'strefa')))
    return zones


def _sketch_loops(body, samples=48):
    """Zamknięte kontury szkicu jako punkty 3D (do obszarów, stref i własnych wzorów)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    out = []
    wires = body.shape.Wires() if hasattr(body.shape, 'Wires') else []
    for w in wires:
        pts = []
        we = BRepTools_WireExplorer(w.wrapped)
        while we.More():
            c = BRepAdaptor_Curve(we.Current())
            ts = np.linspace(c.FirstParameter(), c.LastParameter(), samples if c.GetType() != 0 else 2)
            if we.Orientation() == 1:
                ts = ts[::-1]
            pts += [np.array(c.Value(float(t)).Coord()) for t in ts[:-1]]
            we.Next()
        if len(pts) >= 3:
            out.append(np.array(pts))
    return out


def _region_of(area, mapper, faces_outer, faces_holes, bodies):
    r = dict(area.get('region') or {'type': 'face'})
    if r.get('type') in ('sketch', 'contours', 'between', 'edges') and r.get('sketch'):
        by_id = {b.id: b for b in bodies}
        b = by_id.get(r['sketch'])
        if b is None:
            raise kernel.CadError('Szkic obszaru wentylacji już nie istnieje.')
        r['loops'] = [np.array([mapper.to2d(q) for q in lp]) for lp in _sketch_loops(b)]
    outers, holes = su.region_polys(r, faces_outer, faces_holes)
    if r.get('type', 'face') != 'face':                                # obszar przycinany do ściany: otwory ściany zostają
        holes = holes + [np.asarray(q, float) for q in faces_holes]
        fo = [np.asarray(q, float) for q in faces_outer]
        if fo:
            outers = [o for o in outers if g2.pip(o, fo[0]).any() or g2.pip(fo[0][:1], o).any()] or outers
            outers = [_clip_to(o, fo) for o in outers]
    return g2.Region([o for o in outers if len(o) >= 3], holes)


def _clip_to(poly, face_outer):
    res = g2.occ_clip([poly], face_outer)
    if not res:
        raise kernel.CadError('Obszar wentylacji leży poza ścianą.')
    return max(res, key=lambda L: abs(g2.area(L[0])))[0]


def plan(bodies, recipe, cancel=None):
    """Plan bez Boolean: ściany, odwzorowania, obszary, strefy i otwory (z kontrolą 2D). Szybki podgląd i podstawa cięcia."""
    by_id = {b.id: b for b in bodies}
    tb = by_id.get(recipe['target'])
    if tb is None or tb.kind != 'solid':
        raise kernel.CadError('Bryły z wentylacją już nie ma.')
    faces = match_faces(tb.shape, recipe['faces'])
    if not faces:
        raise kernel.CadError('Zaznacz co najmniej jedną powierzchnię.')
    multi = recipe.get('multi', 'independent')
    mode = recipe.get('mapping', 'auto')
    groups = []                                                         # (mappers, transforms, region source)
    report = []
    if multi == 'independent' or len(faces) == 1:
        for f in faces:
            m = su.Mapper(f, mode, rotate=float(recipe.get('map_rotate', 0.0)))
            groups.append(([m], [np.eye(3)]))
    elif multi == 'common':
        ns = [su.Mapper(f, 'uv').n for f in faces]
        d = -vc._unit(np.mean(ns, axis=0))
        ms = [su.Mapper(f, 'linear', direction=d) for f in faces]
        o, x, y = ms[0].o, ms[0].x, ms[0].y
        for m in ms:                                                    # wspólna płaszczyzna rzutu
            m.o, m.x, m.y = o, x, y
        groups.append((ms, [np.eye(3)] * len(ms)))
    else:
        chain, left = su.unfold_chain(faces)
        if left:
            report.append(('warning', f'{len(left)} ścian nie przylega do pozostałych - wzór na nich niezależny.'))
        groups.append(([m for m, _t in chain], [t for _m, t in chain]))
        for i in left:
            groups.append(([su.Mapper(faces[i], mode)], [np.eye(3)]))
        if any(getattr(m, 'approx', False) for m, _t in chain):
            report.append(('warning', 'Część ścian nie jest rozwijalna - kontynuacja wzoru na nich przybliżona (współrzędne UV).'))
    plans = []
    for gi, (ms, Ts) in enumerate(groups):
        outs, hols = [], []
        for m, T in zip(ms, Ts):
            o, h = m.boundary()
            outs += [(np.c_[q, np.ones(len(q))] @ T.T)[:, :2] for q in o]
            hols += [(np.c_[q, np.ones(len(q))] @ T.T)[:, :2] for q in h]
        if len(ms) > 1 and multi != 'common':
            merged = _merge_outlines(outs)
            outs = merged
        for ai, area in enumerate(recipe.get('areas') or [{}]):
            p = dict(vl.DEFAULTS, **area)
            reg = _region_of(area, ms[0], outs, hols, bodies)
            zones = _zones_for(ms[0], recipe, bodies, recipe['target'])
            if multi == 'wrap' and len(ms) > 1:                         # zawijanie: rozstaw dopasowany do obwodu
                per = float(np.ptp(np.vstack(outs)[:, 0]))
                px = float(p['px']) or float(p['w']) + float(p['bridge'])
                n = max(1, round(per / px))
                p['px'] = per / n
                report.append(('ok', f'Zawijanie: rozstaw {p["px"]:.2f} mm ({n} otworów na obwodzie) - wzór ciągły na styku.'))
            holes, rep, st, used = vl.generate(p, reg, zones, cancel)
            report += rep
            plans.append(dict(group=gi, area=ai, mappers=ms, T=Ts, region=reg, zones=zones, holes=holes, stats=st, params=used))
    return dict(target=tb, faces=faces, plans=plans, report=report)


def _merge_outlines(outs):
    """Obrysy rozłożonych ścian połączone w jeden obszar (Boolean 2D)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    acc = None
    for o in outs:
        f = g2._face_xy([o])
        acc = f if acc is None else BRepAlgoAPI_Fuse(acc, f).Shape()
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRepTools import BRepTools
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    un = ShapeUpgrade_UnifySameDomain(acc, True, True, False)
    un.Build()
    acc = un.Shape()
    out = []
    ex = TopExp_Explorer(acc, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        w = BRepTools.OuterWire_s(f)
        out.append(_wire_pts(w))
        ex.Next()
    return out


def _wire_pts(w, n=12):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    pts = []
    we = BRepTools_WireExplorer(w)
    while we.More():
        c = BRepAdaptor_Curve(we.Current())
        ts = np.linspace(c.FirstParameter(), c.LastParameter(), 2 if c.GetType() == 0 else n)
        if we.Orientation() == 1:
            ts = ts[::-1]
        pts += [c.Value(float(t)).Coord()[:2] for t in ts[:-1]]
        we.Next()
    return np.array(pts, float)


def _locate(pl, c):
    """Ściana grupy, na której leży punkt dziedziny wspólnej, i punkt w jej własnej dziedzinie."""
    ms, Ts = pl['mappers'], pl['T']
    if len(ms) == 1:
        return ms[0], np.asarray(c, float)
    best = None
    for m, T in zip(ms, Ts):
        Ti = np.linalg.inv(T)
        q = (Ti @ np.r_[c, 1])[:2]
        o, _h = getattr(m, '_bnd', None) or m.boundary(8)
        m._bnd = (o, _h)
        inside = any(g2.pip(q[None], oo)[0] for oo in o)
        d = 0.0 if inside else min(float(g2.dist_to_poly(q[None], oo)[0]) for oo in o)
        if best is None or d < best[0]:
            best = (d, m, q)
    return best[1], best[2]


class _LocalMap:
    """Odwzorowanie ściany z przesuniętym środkiem dziedziny (otwór we wspólnej dziedzinie → ściana)."""

    def __init__(self, m, shift, T=None):
        self.m, self.shift, self.mode = m, np.asarray(shift, float), m.mode
        self.T = T

    def to3d(self, xy):
        q = np.asarray(xy, float)
        if self.T is not None:
            q = (np.linalg.inv(self.T) @ np.r_[q, 1])[:2]
        return self.m.to3d(q)


def build(bodies, recipe, cancel=None, progress=None, exact=True):
    """Operacja Wentylacja: (bryła wynikowa, plan, raport, statystyki). exact=False - tylko plan i narzędzia (podgląd
    przestrzenny), bez Boolean."""
    import cadquery as cq
    from .enclosure import _volume
    cut_p = dict(CUT_DEFAULTS, **(recipe.get('cut') or {}))
    pl = plan(bodies, recipe, cancel)
    tb = pl['target']
    solid = tb.shape.wrapped
    thick = vc.Thickness(solid)
    axis = recipe.get('axis')
    ref = None
    if cut_p['depth_mode'] == 'face' and recipe.get('end_face'):
        ref = match_faces(tb.shape, [recipe['end_face']])[0]
    tools, blades, report = [], [], list(pl['report'])
    all_holes = []
    n_total = sum(len(x['holes']) for x in pl['plans'])
    if n_total > MAX_TOOLS:
        raise kernel.CadError(f'Za dużo otworów ({n_total}) - największa liczba to {MAX_TOOLS}; zwiększ otwory albo rozstaw.')
    if n_total > 2000:
        report.append(('warning', f'Duża liczba otworów ({n_total}) - dłuższe obliczenia i większy plik (każdy otwór to kilka ścian B-Rep).'))
    thick_med = []
    done = 0
    for plan_ in pl['plans']:
        for h in plan_['holes']:
            done += 1
            if cancel is not None and done % 50 == 0 and cancel():
                raise kernel.CadError('Obliczenia przerwane - model bez zmian.')
            if progress is not None and done % 50 == 0:
                progress(.5 * done / max(n_total, 1))
            if h['status'] not in ('ok', 'adjust'):
                all_holes.append(h)
                continue
            m, q = _locate(plan_, h['c'])
            lm = _LocalMap(m, 0, plan_['T'][plan_['mappers'].index(m)] if len(plan_['mappers']) > 1 else None)
            hp = dict(cut_p, **{k: h[k] for k in ('dir',) if h.get(k) is not None})
            try:
                if cut_p['hole_type'] in ('louver_out', 'louver_in'):
                    t, b, why = vc.louver(h, lm, hp, thick)
                    if t is None:
                        h.update(status='bad', reason=why)
                        all_holes.append(h)
                        continue
                    tools.append(t)
                    blades.append(b)
                else:
                    t, why = vc.tool(h, lm, hp, thick, axis, ref)
                    if t is None or not _tool_ok(t):
                        h.update(status='bad', reason=why or 'niepoprawna bryła narzędzia (profil)')
                        all_holes.append(h)
                        continue
                    tools.append(t)
                # grubość w środku - wykrywanie elementów za ścianką (słupki, żebra, przegrody)
                P, N, X, _Y = lm.to3d(h['c'])
                d = vc.direction(h, P, N, X, hp, axis)
                tw = thick.wall(P, d)
                h['thickness'] = tw
                if tw is not None:
                    thick_med.append(tw)
                h['tool'] = len(tools) - 1
            except kernel.CadError as exc:
                h.update(status='bad', reason=str(exc))
            all_holes.append(h)
    # elementy za ścianką: grubość wyraźnie większa niż typowa - otwór pominięty (nie przecina słupka / żebra)
    if thick_med and cut_p['depth_mode'] in ('wall',):
        med = float(np.median(thick_med))
        skip = {h['tool'] for h in all_holes if h.get('tool') is not None and h.get('thickness') and h['thickness'] > med * float(cut_p['obstacle_factor']) + .2}
        if skip:
            for h in all_holes:
                if h.get('tool') in skip:
                    h.update(status='skip', reason='element za ścianką (słupek, żebro, przegroda) - grubość niejednoznaczna', tool=None)
            report.append(('warning', f'{len(skip)} otworów pominięto: za ścianką jest element konstrukcyjny (lokalna grubość > {cut_p["obstacle_factor"]:g} × typowa {med:.2f} mm). Można wskazać powierzchnię końcową.'))
            keep = [i for i in range(len(tools)) if i not in skip]
            remap = {old: new for new, old in enumerate(keep)}
            tools = [tools[i] for i in keep]
            if blades:
                blades = [blades[i] for i in keep]
            for h in all_holes:
                if h.get('tool') is not None:
                    h['tool'] = remap.get(h['tool'])
    active = [h for h in all_holes if h['status'] in ('ok', 'adjust') and h.get('tool') is not None]
    stats = _stats_plan(pl, all_holes, recipe)
    if not exact:
        return dict(shape=None, plan=pl, tools=tools, blades=blades, holes=all_holes, report=report, stats=stats)
    if not tools:
        raise kernel.CadError('Żaden otwór nie spełnia wymagań - zmień obszar, wymiary albo marginesy.')
    v0 = _volume(solid)[0]
    faces0 = pl['faces']
    a0 = vc.face_area(solid, faces0)
    prog = (lambda f: progress(.5 + .4 * f)) if progress else None
    tiled = vc.cut_tiled(solid, tools, cancel=cancel, progress=prog) if len(tools) > TILE_FROM and not blades else None
    if tiled is not None:                                              # tysiące otworów: kawałkami (czas i kontrola liniowo)
        res, after = tiled, []
    else:
        res, after = vc.cut_many(solid, tools, cancel=cancel, progress=prog, track=faces0)
    if not after:                                                      # historia bez następników - dopasowanie geometryczne
        after = _same_surface_faces(res, faces0)
    a1 = vc.face_area(res, after)                                     # rzeczywista powierzchnia otwarta na wejściu (historia Boolean)
    if blades:
        res = vc.fuse_many(res, blades)
    res, rep2 = vc.check_result(res, bool(recipe.get('allow_islands')), unify=tiled is None)
    if tiled is not None:
        vc.trust_result(res)
    report += rep2
    v1 = _volume(res)[0]
    if v1 <= 1e-6 or v1 < v0 * .02:
        raise kernel.CadError('Wycięcie usunęłoby prawie całą bryłę - zostaje poprzednia geometria (sprawdź profil i głębokość otworów).')
    stats.update(removed=v0 - v1, remaining=v1, open_entry=max(0.0, a0 - a1), face_area=a0)
    dens = float(recipe.get('density') or 0)
    if dens > 0:
        stats['mass_change'] = -(v0 - v1) * dens / 1000.0
    if stats.get('region_area'):
        stats['open_percent'] = 100.0 * stats['open_entry'] / stats['region_area']
    expect = stats.get('open_plan', 0.0)
    if expect > 0 and stats['open_entry'] > 0 and abs(stats['open_entry'] - expect) > .15 * expect + 1.0 and cut_p['hole_type'] in ('through', 'blind', 'recess'):
        report.append(('warning', f'Powierzchnia otwarta po wycięciu ({stats["open_entry"]:.1f} mm²) różni się od planowanej ({expect:.1f} mm²) - sprawdź otwory przy krawędziach.'))
    report.append(('ok', f'Wycięto {len(active)} otworów; usunięto {stats["removed"]:.1f} mm³ materiału.'))
    return dict(shape=cq.Shape.cast(res), plan=pl, tools=tools, holes=all_holes, report=report, stats=stats)


def _tool_ok(t):
    from .enclosure import _volume
    for q in (t if isinstance(t, list) else [t]):
        if _volume(q)[0] <= 1e-9:
            return False
    return True


def _same_surface_faces(shape, faces0):
    """Ściany wyniku leżące na powierzchniach ścian zaznaczonych (środek ściany na pierwotnej ścianie)."""
    import cadquery as cq
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    out = []
    for f in cq.Shape.cast(shape).Faces():
        try:
            ad = su.Mapper(f.wrapped, 'uv')
            P, _N, _a, _b = ad.eval_uv(ad.uc, ad.vc)
        except Exception:
            continue
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
        from OCP.gp import gp_Pnt
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, P))).Vertex()
        for f0 in faces0:
            d = BRepExtrema_DistShapeShape(v, f0)
            d.Perform()
            if d.IsDone() and d.Value() < 1e-5 and su.surface_kind(f.wrapped) == su.surface_kind(f0):
                out.append(f.wrapped)
                break
    return out


def _stats_plan(pl, holes, recipe):
    """Statystyki planu (przybliżone w podglądzie): liczby, pola rzeczywiste (jakobian odwzorowania), mostki, krawędzie."""
    st = dict(count=0, skipped=0, bad=0, adjusted=0, open_plan=0.0, region_area=0.0, min_bridge=None, min_edge=None)
    for plan_ in pl['plans']:
        reg = plan_['region']
        m = plan_['mappers'][0]
        J = 1.0 if m.mode == 'plane' else _mean_jac(m, reg)
        st['region_area'] += reg.area() * J
        mb = plan_['stats'].get('min_bridge')
        if mb is not None:
            st['min_bridge'] = mb if st['min_bridge'] is None else min(st['min_bridge'], mb)
    for h in holes:
        s_ = h.get('status')
        if s_ in ('ok', 'adjust') and h.get('tool') is not None:
            st['count'] += 1
            st['adjusted'] += s_ == 'adjust'
            st['open_plan'] += vs.profile_area(h['loops'])
        elif s_ == 'skip':
            st['skipped'] += 1
        else:
            st['bad'] += 1
    act = [h for h in holes if h.get('status') in ('ok', 'adjust') and h.get('tool') is not None]
    if act and pl['plans']:
        reg = pl['plans'][0]['region']
        st['min_edge'] = float(min(reg.edge_dist(h['poly']).min() for h in act[:4000]))
    if st['region_area']:
        st['open_percent_plan'] = 100.0 * st['open_plan'] / st['region_area']
    return st


def _mean_jac(m, reg):
    pts = [reg.centroid()]
    lo, hi = reg.lo, reg.hi
    for fx in (.25, .75):
        for fy in (.25, .75):
            q = lo + (hi - lo) * [fx, fy]
            if reg.contains(q[None])[0]:
                pts.append(q)
    try:
        return float(np.mean([m.jacobian(q) for q in pts]))
    except Exception:
        return 1.0


def run(bodies, recipe):
    """Krok historii 'vent': bryła z wentylacją (ta sama bryła, nowa geometria); inne bryły bez zmian."""
    from dataclasses import replace
    if recipe.get('disabled'):
        return list(bodies)
    res = build(bodies, recipe)
    out = []
    for b in bodies:
        if b.id == recipe['target']:
            meta = dict(b.meta or {})
            meta['vent'] = [*[r for r in meta.get('vent', []) if r.get('id') != recipe.get('id')], dict(id=recipe.get('id'), stats=_jsonable(res['stats']))]
            b = replace(b, shape=res['shape'], meta=meta, mesh=None).prepared()
        out.append(b)
    return out


def _jsonable(d):
    return {k: (float(v) if isinstance(v, (int, float, np.floating)) and not isinstance(v, bool) else v) for k, v in d.items() if v is not None}


def new_recipe(target, refs, areas=None, **kw):
    r = dict(type='vent', id=uuid.uuid4().hex, target=target, faces=refs, areas=areas or [dict(vl.DEFAULTS)], multi='independent',
             mapping='auto', cut=dict(CUT_DEFAULTS), exclusions=[])
    r.update(kw)
    return r

