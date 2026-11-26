"""Generator obudów - etap 12: kontrola poprawności obudowy.

Sprawdzenia (każde z poziomem: 'ok' - poprawne, 'warning' - ostrzeżenie, 'error' - błąd, i opcjonalnym kształtem
obszaru do podświetlenia w widoku):
- kolizje elementów ze ściankami i z mocowaniami, podstawy z pokrywą, elementów systemów zamykania, mocowań między
  sobą, uszkodzenia mocowań przez otwory i wentylację (BRepAlgoAPI_Common, objętość BRepGProp),
- minimalne odstępy elementów od obudowy (BRepExtrema_DistShapeShape), minimalna grubość materiału (promienie przez
  ścianki w punktach próbnych),
- poprawność brył (BRepCheck_Analyzer), niepołączone fragmenty, otwarte / nieprawidłowe powłoki, samoprzecięcia
  (BOPAlgo_ArgumentAnalyzer),
- możliwość włożenia elementów i otwierania / zamykania obudowy - na całej drodze ruchu (sweep: postęp zachowawczy według
  odległości ramek ścian; przy styku ramek sprawdzenie co 0,5 mm przesunięcia / 1 mm lub 1° obrotu).
Rzeczywista kolizja objętościowa (część wspólna > TOL_VOLUME) jest odróżniana od dozwolonego styku powierzchni
(odległość < TOL_DIST, objętość wspólna zerowa). Przed dokładnymi operacjami - wstępne sprawdzenie ramek (Bounding Box)."""
from __future__ import annotations

import numpy as np

from . import kernel

TOL_VOLUME = 1e-3          # mm³ - mniejsza część wspólna to styk (dokładność operacji Boolean)
TOL_DIST = 1e-4            # mm - styk powierzchni
MIN_MATERIAL = .8          # mm - domyślna minimalna grubość materiału
LEVELS = ('ok', 'warning', 'error')


def _bb(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return box


def _apart(a, b, gap=0.0):
    """Wstępne sprawdzenie ramek: True - ramki rozłączne (o więcej niż gap), dokładne liczenie zbędne."""
    ba, bb = _bb(a), _bb(b)
    if ba.IsVoid() or bb.IsVoid():
        return True
    if gap > 0:
        ba.Enlarge(gap)
    return ba.IsOut(bb)


def _common(a, b):
    from .enclosure import _boolean, _volume
    if _apart(a, b):
        return 0.0, None
    try:
        sh = _boolean('common', a, b, 'kontrola kolizji')
    except kernel.CadError:
        return None, None
    return _volume(sh)[0], sh


def _distance(a, b, limit):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    if _apart(a, b, limit):
        return None
    d = BRepExtrema_DistShapeShape(a, b)
    d.Perform()
    if not d.IsDone():
        return None
    return float(d.Value()), (np.array(d.PointOnShape1(1).Coord()), np.array(d.PointOnShape2(1).Coord())) if d.NbSolution() else None


MIN_STEP = .5              # mm - przesunięcie: największy ruch ścian o stykających się ramkach między sprawdzeniami
ROT_STEP = 1.0             # mm - obrót (zawias): największy ruch takich ścian między sprawdzeniami części wspólnej,
ROT_MIN = 0.017453292519943295   # ale nie rzadziej niż co 1° (duże pokrywy)
MAX_STEPS = 4000


def _faces_of(shape):
    import cadquery as cq
    return [f.wrapped for f in cq.Shape.cast(shape).Faces()]


def _face_boxes(faces):
    """Ramki (AABB) ścian: (N, 2, 3) - ramka zawiera ścianę."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    out = []
    for f in faces:
        b = Bnd_Box()
        BRepBndLib.Add_s(f, b)
        x0, y0, z0, x1, y1, z1 = b.Get() if not b.IsVoid() else (0, 0, 0, 0, 0, 0)
        out.append(((x0, y0, z0), (x1, y1, z1)))
    return np.asarray(out, float).reshape(-1, 2, 3)


def _moved_boxes(boxes, R, t):
    """Ramki ścian po ruchu sztywnym: ramka obróconych narożników (zawiera obróconą ścianę - ograniczenie bezpieczne)."""
    lo, hi = boxes[:, 0], boxes[:, 1]
    corners = np.stack([np.where(np.array([k & 1, k & 2, k & 4], bool), hi, lo) for k in range(8)], axis=1)
    moved = corners @ R.T + t
    return np.stack([moved.min(axis=1), moved.max(axis=1)], axis=1)


def _box_gaps(A, B):
    """Odległości między ramkami (macierz N_A x N_B) - dolne ograniczenia odległości par ścian."""
    gap = np.maximum(0.0, np.maximum(A[:, None, 0] - B[None, :, 1], B[None, :, 0] - A[:, None, 1]))
    return np.sqrt((gap ** 2).sum(axis=2))


def sweep(fixed, motion, total, speed, label, xform=None, axis=None):
    """Kontrola ruchu na całej drodze (postęp zachowawczy). Dla każdej pary ścian (nieruchoma, ruchoma) dolne ograniczenie
    ich odległości = odległość ramek (ramka zawiera ścianę). Ściana
    ruchoma przesuwa się co najwyżej z prędkością v_f na jednostkę parametru (przesunięcie: `speed`; obrót wokół osi
    `axis` = (punkt, kierunek): największa odległość narożnika jej ramki od osi), więc do położenia u + min(odległość / v_f)
    żadna para nie może się zetknąć - ten odcinek ruchu jest pomijany bez ryzyka przeoczenia kolizji. Gdy ramki ścian
    się stykają: sprawdzenie części wspólnej brył (BRepAlgoAPI_Common, objętość > TOL_VOLUME = kolizja) co MIN_STEP
    (przesunięcie) / ROT_STEP (obrót) ruchu najszybszej z tych ścian. Zwraca (opis, część wspólna) albo None."""
    speed = max(float(speed), 1e-9)
    ff = _faces_of(fixed)
    fb = _face_boxes(ff)
    mb = _face_boxes(_faces_of(motion(0.0))) if xform is not None else None
    u, steps = 0.0, 0
    while steps < MAX_STEPS:
        steps += 1
        shape_u = None
        if xform is not None and len(fb) and len(mb):
            R, t = xform(u)
            moved = _moved_boxes(mb, R, t)
            if axis is not None:                                 # prędkość ściany przy obrocie: promień od osi
                p0, dd = (np.asarray(x, float) for x in axis)
                dd = dd / max(float(np.linalg.norm(dd)), 1e-12)
                corners = np.stack([np.where(np.array([k & 1, k & 2, k & 4], bool), moved[:, 1], moved[:, 0]) for k in range(8)], axis=1) - p0
                radial = corners - (corners @ dd)[..., None] * dd
                v = np.maximum(np.linalg.norm(radial, axis=2).max(axis=1), 1e-6)
            else:
                v = np.full(len(moved), speed)
            G = _box_gaps(fb, moved)
            contact = G <= 1e-9
            ratio = G / v[None, :]
            safe = float(ratio[~contact].min()) if (~contact).any() else total
            touching_m = contact.any(axis=0)
        else:
            touching_m, v, safe = np.array([True]), np.array([speed]), 0.0
        if touching_m.any():
            vol, common = _common(fixed, shape_u if shape_u is not None else motion(u))
            if vol is not None and vol > TOL_VOLUME:
                return label(u), common
            step = MIN_STEP / float(v[touching_m].max()) if axis is None else max(ROT_STEP / float(v[touching_m].max()), ROT_MIN)
            adv = (min(safe, step) if safe > 0 else step) if axis is None else max(min(safe, step), ROT_MIN)
        else:
            adv = safe
        if u >= total:
            return None
        u = min(total, u + max(adv, 1e-6))
    return None


def _marker(p, q=None, r=1.0):
    """Mały obszar do podświetlenia (sfera w punkcie / walec między punktami)."""
    import cadquery as cq
    p = np.asarray(p, float)
    if q is None or np.linalg.norm(np.asarray(q) - p) < 1e-6:
        return cq.Solid.makeSphere(r, cq.Vector(*p)).wrapped
    q = np.asarray(q, float)
    d = q - p
    return cq.Solid.makeCylinder(max(r * .4, .2), float(np.linalg.norm(d)), cq.Vector(*p), cq.Vector(*d)).wrapped


def solid_checks(name, shape):
    """Poprawność bryły: BRepCheck, liczba brył (fragmenty), zamknięte powłoki, samoprzecięcia."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    out = []
    ok = BRepCheck_Analyzer(shape).IsValid()
    out.append(('ok' if ok else 'error', f'{name}: geometria B-Rep ' + ('poprawna (BRepCheck_Analyzer).' if ok else 'niepoprawna - nie można jej zapisać.'), None))
    solids, shells, open_shells = 0, 0, 0
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        solids += 1
        ex.Next()
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    while ex.More():
        shells += 1
        if not BRep_Tool.IsClosed_s(ex.Current()):
            open_shells += 1
        ex.Next()
    out.append(('ok' if solids == 1 else 'error', f'{name}: ' + ('jedna spójna bryła.' if solids == 1 else f'{solids} niepołączone fragmenty.'), None))
    out.append(('ok' if open_shells == 0 else 'error', f'{name}: ' + ('powłoki zamknięte.' if open_shells == 0 else f'{open_shells} otwarte powłoki.'), None))
    try:
        an = BOPAlgo_ArgumentAnalyzer()
        an.SetShape1(shape)
        an.SelfInterMode = True
        an.Perform()
        bad = an.HasFaulty()
    except Exception:
        bad = None
    out.append(('ok' if bad is False else ('warning' if bad is None else 'error'),
                f'{name}: ' + ('bez samoprzecięć.' if bad is False else ('nie udało się sprawdzić samoprzecięć.' if bad is None else 'samoprzecięcia w geometrii.')), None))
    return out


def thickness(name, shape, minimum, samples=6):
    """Minimalna grubość materiału: promienie od zewnętrznych ścian płaskich do środka bryły w punktach próbnych."""
    import cadquery as cq
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    sh = cq.Shape.cast(shape)
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1e-6)
    worst = None
    for face in sh.Faces():
        if face.geomType() != 'PLANE' or face.Area() < 1.0:
            continue
        bb = face.BoundingBox()
        n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
        for t in np.linspace(.15, .85, samples):
            for s in np.linspace(.15, .85, samples):
                p = np.array([bb.xmin + (bb.xmax - bb.xmin) * t, bb.ymin + (bb.ymax - bb.ymin) * s, bb.zmin + (bb.zmax - bb.zmin) * (t + s) / 2])
                # punkt na ścianie: rzut punktu ramki na płaszczyznę ściany i sprawdzenie, czy leży na ścianie
                c = np.asarray(face.Center().toTuple(), float)
                p = p - float((p - c) @ n) * n
                from OCP.BRepClass import BRepClass_FaceClassifier
                from OCP.TopAbs import TopAbs_IN
                if BRepClass_FaceClassifier(face.wrapped, gp_Pnt(*map(float, p)), 1e-6).State() != TopAbs_IN:
                    continue
                start = p - n * 1e-4
                inter.Perform(gp_Lin(gp_Pnt(*map(float, start)), gp_Dir(*map(float, -n))), 1e-6, 1e9)
                if not inter.IsDone() or inter.NbPnt() == 0:
                    continue
                d = min(inter.WParameter(i) for i in range(1, inter.NbPnt() + 1)) + 1e-4
                if worst is None or d < worst[0]:
                    worst = (d, p, p - n * d)
    if worst is None:
        return [('warning', f'{name}: nie udało się zmierzyć grubości materiału.', None)]
    d, p, q = worst
    if d < minimum - 1e-6:
        return [('warning', f'{name}: najcieńsze miejsce {d:.2f} mm - mniej niż minimum {minimum:g} mm.', _marker(p, q, max(d, .5)))]
    return [('ok', f'{name}: najmniejsza zmierzona grubość materiału {d:.2f} mm (minimum {minimum:g} mm).', None)]


def run(parts, components, spec=None, posts=None, closure_solids=None, cut_tools=None, interference=False, motion=None,
        clearance=None, min_material=MIN_MATERIAL, insertion_dir=None):
    """Pełna kontrola. parts: dict nazwa -> bryła (TopoDS), components: lista Body (elementy źródłowe), posts: lista
    (nazwa, bryła) mocowań, closure_solids: lista (nazwa, bryła) elementów zamknięcia, cut_tools: lista (nazwa, bryła)
    narzędzi otworów / wentylacji, motion: (funkcja(u) -> pokrywa w położeniu u, zakres u, największa prędkość punktu, opis(u)) - ruch otwierania sprawdzany w sposób ciągły (sweep).
    Zwraca listę wyników (poziom, tekst, kształt obszaru albo None, id elementu albo None)."""
    out = []
    add = lambda lvl, text, shape=None, ref=None: out.append((lvl, text, shape, ref))
    names = {'body': 'Obudowa', 'base': 'Podstawa', 'lid': 'Pokrywa'}
    for name, shape in parts.items():
        for lvl, text, sh in solid_checks(names.get(name, name), shape):
            add(lvl, text, sh)
        for lvl, text, sh in thickness(names.get(name, name), shape, min_material):
            add(lvl, text, sh)
    # elementy a ścianki: kolizja objętościowa / styk / odstęp
    need = float(min((clearance or {0: 0.0}).values())) if clearance else 0.0
    for comp in components:
        if comp.kind not in ('solid', 'mesh'):
            continue
        worst = None
        hit = False
        for name, shape in parts.items():
            vol, common = _common(comp.shape.wrapped, shape) if comp.kind == 'solid' else (0.0, None)
            if vol is None:
                add('warning', f'„{comp.name}” / {names.get(name, name).lower()}: nie udało się policzyć części wspólnej.', None, comp.id)
                continue
            if vol > TOL_VOLUME:
                hit = True
                add('error', f'Kolizja: „{comp.name}” wchodzi w {names.get(name, name).lower()} ({vol:.3f} mm³).', common, comp.id)
                continue
            dist = _distance(comp.shape.wrapped, shape, max(need, 1.0) + 1.0)
            if dist is not None and (worst is None or dist[0] < worst[0]):
                worst = (dist[0], dist[1], name)
        if hit:
            continue
        if worst is not None and worst[0] < TOL_DIST:
            add('ok', f'„{comp.name}”: styk powierzchni z częścią {names.get(worst[2], worst[2]).lower()} (dozwolony, bez kolizji objętościowej).', None, comp.id)
        elif worst is not None and need > 0 and worst[0] < need - 1e-3:
            add('warning', f'„{comp.name}”: odstęp {worst[0]:.2f} mm - mniej niż wymagane {need:g} mm.', _marker(*worst[1]), comp.id)
        else:
            add('ok', f'„{comp.name}”: bez kolizji ze ściankami' + (f', odstęp co najmniej {need:g} mm.' if need > 0 else '.'), None, comp.id)
    # mocowania: z elementami, między sobą, uszkodzenia przez otwory
    posts = posts or []
    for name, post in posts:
        for comp in components:
            if comp.kind != 'solid':
                continue
            vol, common = _common(post, comp.shape.wrapped)
            if vol and vol > TOL_VOLUME:
                add('error', f'Kolizja: mocowanie {name} wchodzi w „{comp.name}” ({vol:.3f} mm³).', common, comp.id)
    for i in range(len(posts)):
        for j in range(i + 1, len(posts)):
            vol, common = _common(posts[i][1], posts[j][1])
            if vol and vol > TOL_VOLUME:
                add('warning', f'Mocowania {posts[i][0]} i {posts[j][0]} nachodzą na siebie ({vol:.2f} mm³).', common)
    for tname, tool in cut_tools or []:
        for name, post in posts:
            vol, common = _common(tool, post)
            if vol and vol > TOL_VOLUME:
                add('error', f'{tname} uszkadza mocowanie {name} ({vol:.2f} mm³).', common)
        for cname, cs in closure_solids or []:
            vol, common = _common(tool, cs)
            if vol and vol > TOL_VOLUME:
                add('error', f'{tname} uszkadza element zamknięcia: {cname}.', common)
    if posts:
        add('ok', f'Mocowania sprawdzone ({len(posts)}): kolizje z elementami, między sobą i z otworami.')
    # elementy systemów zamykania
    cs = closure_solids or []
    bad = False
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            if cs[i][0].split(':')[0] == cs[j][0].split(':')[0]:
                continue                                  # elementy jednego systemu (np. ramię i zaczep) stykają się celowo
            vol, common = _common(cs[i][1], cs[j][1])
            if vol and vol > TOL_VOLUME:
                bad = True
                add('warning', f'Elementy zamknięcia {cs[i][0]} i {cs[j][0]} nachodzą na siebie.', common)
        for comp in components:
            if comp.kind == 'solid':
                vol, common = _common(cs[i][1], comp.shape.wrapped)
                if vol and vol > TOL_VOLUME:
                    bad = True
                    add('error', f'Element zamknięcia {cs[i][0]} koliduje z „{comp.name}”.', common, comp.id)
    if cs and not bad:
        add('ok', f'Systemy zamykania ({len(cs)} elementów): bez kolizji.')
    # podstawa i pokrywa
    if 'base' in parts and 'lid' in parts:
        vol, common = _common(parts['base'], parts['lid'])
        if vol is not None and vol > TOL_VOLUME:
            add('warning' if interference else 'error', f'Podstawa i pokrywa przenikają się ({vol:.3f} mm³)' + (' - zamierzony wcisk.' if interference else '.'), common)
        else:
            add('ok', 'Podstawa i pokrywa: bez przenikania (najwyżej styk powierzchni).')
        if motion is not None:
            fn, total, speed, label, xf, axis = motion
            hit = sweep(parts['base'], fn, total, speed, label, xf, axis)
            if hit:
                add('error', f'Otwieranie: pokrywa koliduje z podstawą {hit[0]}.', hit[1])
            else:
                add('ok', 'Otwieranie i zamykanie: bez kolizji na całej drodze ruchu (kontrola ciągła - postęp według odległości '
                          f'ramek ścian, przy styku ramek sprawdzenie co {MIN_STEP:g} mm przesunięcia / {ROT_STEP:g} mm lub 1° obrotu).')
    # montaż elementów: wsuwanie od strony otwarcia (podstawa bez pokrywy)
    if insertion_dir is not None:
        import cadquery as cq
        base = parts.get('base', parts.get('body'))
        d = np.asarray(insertion_dir, float)
        height = float(np.linalg.norm(np.asarray(_bb(base).CornerMax().Coord()) - np.asarray(_bb(base).CornerMin().Coord())))
        for comp in components:
            if comp.kind != 'solid':
                continue
            src = cq.Shape.cast(comp.shape.wrapped)
            hit = sweep(base, lambda u, src=src: src.translate(cq.Vector(*(d * u))).wrapped, height, 1.0, lambda u: f'{u:.1f}',
                        lambda u: (np.eye(3), d * u))
            if hit:
                add('warning', f'Montaż: „{comp.name}” nie przejdzie przez otwarcie (kolizja po {hit[0]} mm wysuwania) - może wymagać montażu przed zamknięciem ścianek.', hit[1], comp.id)
            else:
                add('ok', f'Montaż: „{comp.name}” da się włożyć od strony otwarcia.', None, comp.id)
        add('ok', f'Kontrola montażu na całej drodze wkładania (odcinki bez możliwości kolizji pomijane z gwarancją, przy styku '
                  f'ramek ścian - co {MIN_STEP:g} mm).')
    return out


def summary(results):
    errors = sum(1 for r in results if r[0] == 'error')
    warnings = sum(1 for r in results if r[0] == 'warning')
    return errors, warnings


# ---------------------------------------------------------------------------------------------- dane do kontroli
def gather(bodies, spec, parts, hole_recipes=(), vent_recipes=(), part_of=None):
    """Dane kontroli z definicji obudowy: części przed otworami (do narzędzi i mocowań), mocowania, elementy zamknięcia,
    narzędzia otworów i wentylacji, ruch pokrywy, kierunek montażu. parts - części do sprawdzenia (TopoDS)."""
    import copy
    from . import enclosure as enc
    env = enc.envelope(bodies, spec)
    spec = copy.deepcopy(spec)
    spec.envelope = env
    by_id = {b.id: b for b in bodies}
    comps = [by_id[s.id] for s in spec.sources if s.id in by_id]
    kw = dict(components=comps, clearance=dict(enc.clearance_of(spec)))
    pre = None
    if (spec.posts and spec.mounts) or hole_recipes or vent_recipes:
        bare = copy.deepcopy(spec)
        bare.posts = {}
        pre, _t, _i = enc.build_parts(env, bare, bodies, check_sources=False)
    posts = []
    if spec.posts and spec.mounts:
        from . import enclosure_posts as ep
        defaults = dict(ep.DEFAULTS, **spec.posts)
        for n, m in enumerate(spec.mounts):
            best = None
            for name, sh in pre.items():
                hit = ep.wall_hit(sh.wrapped, m['center'], m['axis'])
                if hit is not None and (best is None or hit[1] < best[0]):
                    best = (hit[1], name)
            if best is None:
                continue
            try:
                post = ep.build_post(m, defaults, pre[best[1]].wrapped, up=np.asarray(env.axes, float)[2])
            except kernel.CadError:
                continue
            posts.append((f'#{n + 1} ({m.get("source_name", "")})', post['solid']))
    closure_solids, interference, motion, insertion = [], False, None, None
    lay = enc.layout(env, spec, bodies=bodies)
    if enc.split_of(spec)['enabled']:
        plane = enc.split_plane(env, spec, lay, bodies)
        systems = [s for s in (spec.closure or {}).get('systems', []) if s.get('enabled', True)]
        f = fr = None
        if systems:
            from . import enclosure_closure as ec
            fr, f = ec.features(env, spec, lay, plane)
            interference = f['interference']
            for key in ('base_add', 'lid_add', 'base_raw', 'lid_raw'):
                for n, sh in enumerate(f[key]):
                    closure_solids.append((f'{key.split("_")[0]}:{n + 1}', fr.world_shape(fr.clip(sh) if key.endswith('add') else sh)))
        if 'lid' in parts:
            motion = _motion(env, spec, f, parts, lay, plane, fr)
        insertion = np.asarray(plane[1], float)
    elif spec.mode == 'open':
        insertion = np.asarray(env.axes, float)[2]
    tools = []
    for r in hole_recipes:
        target = (part_of or {}).get(r['target'])
        if target is None or pre is None or target not in pre:
            continue
        try:
            from . import enclosure_hole_ui as hu
            tools.append(('Otwór na element', hu.tool_only(bodies, r, pre[target])))
        except kernel.CadError:
            continue
    for r in vent_recipes:
        target = (part_of or {}).get(r['target'])
        if target is None or pre is None or target not in pre:
            continue
        try:
            from . import enclosure_vent_ui as vu
            tools += [('Wentylacja', t) for t in vu.tools_only(r, pre[target])]
        except kernel.CadError:
            continue
    return dict(kw, posts=posts, closure_solids=closure_solids, cut_tools=tools, interference=interference, motion=motion,
                insertion_dir=insertion)


def _motion(env, spec, f, parts, lay, plane, fr=None):
    """Ruch otwierania pokrywy dla kontroli ciągłej: (funkcja położenia, zakres, największa prędkość punktu, opis).
    Zawias - obrót (prędkość = największa odległość punktu pokrywy od osi), wsuwana - przesunięcie, inne - uniesienie
    (zatrzaski pomijane - ugięcie ramion)."""
    import math
    import cadquery as cq
    lid = cq.Shape.cast(parts['lid'])
    ax = fr.axes if fr is not None else np.asarray(env.axes, float)
    c = np.asarray(env.center, float)
    m = f['motion'] if f else None
    if m is not None and m[0] == 'hinge':
        _k, pt, d, _s, angle = m
        pw, dw = c + ax.T @ pt, ax.T @ d
        probe = lid.rotate(cq.Vector(*pw), cq.Vector(*(pw + dw)), 10.0)
        sgn = 1 if float((probe.Center() - lid.Center()).dot(cq.Vector(*plane[1]))) >= 0 else -1
        bb = lid.BoundingBox()
        corners = np.array([[x, y, z] for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)])
        du = _unit_vec(dw)
        rel = corners - pw
        radius = float(np.max(np.linalg.norm(rel - np.outer(rel @ du, du), axis=1)))
        def xf(u, pw=pw, du=du, sg=sgn):
            k = du * sg
            K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
            R = np.eye(3) + math.sin(u) * K + (1 - math.cos(u)) * K @ K          # obrót Rodriguesa wokół osi zawiasu
            return R, pw - R @ pw
        return (lambda u: lid.rotate(cq.Vector(*pw), cq.Vector(*(pw + dw)), sgn * math.degrees(u)).wrapped, math.radians(angle), radius,
                lambda u: f'przy otwarciu o {math.degrees(u):.0f}°', xf, (pw, du))
    if m is not None and m[0] == 'slide':
        _k, axis, sign, length = m
        v = ax[axis] * sign
        return (lambda u: lid.translate(cq.Vector(*(v * u))).wrapped, length * 1.05, 1.0, lambda u: f'przy wysunięciu o {u:.0f} mm',
                lambda u: (np.eye(3), v * u), None)
    if any(s.get('type') == 'snap' for s in (spec.closure or {}).get('systems', [])):
        return None
    n = np.asarray(plane[1], float)
    h = float(np.max(lay['outer_size']))
    return (lambda u: lid.translate(cq.Vector(*(n * u))).wrapped, h, 1.0, lambda u: f'przy uniesieniu o {u:.0f} mm',
            lambda u: (np.eye(3), n * u), None)


def _unit_vec(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)