"""Generator obudów - etap 12: kontrola poprawności obudowy.

Sprawdzenia (każde z poziomem: 'ok' - poprawne, 'warning' - ostrzeżenie, 'error' - błąd, i opcjonalnym kształtem
obszaru do podświetlenia w widoku):
- kolizje elementów ze ściankami i z mocowaniami, podstawy z pokrywą, elementów systemów zamykania, mocowań między
  sobą, uszkodzenia mocowań przez otwory i wentylację (BRepAlgoAPI_Common, objętość BRepGProp),
- minimalne odstępy elementów od obudowy (BRepExtrema_DistShapeShape), minimalna grubość materiału (promienie przez
  ścianki w punktach próbnych),
- poprawność brył (BRepCheck_Analyzer), niepołączone fragmenty, otwarte / nieprawidłowe powłoki, samoprzecięcia
  (BOPAlgo_ArgumentAnalyzer),
- możliwość włożenia elementów i otwierania / zamykania obudowy - położenia pośrednie (kontrola próbkowana: nie
  gwarantuje wykrycia wszystkich kolizji podczas ruchu).
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
    narzędzi otworów / wentylacji, motion: funkcja(t) -> przekształcona pokrywa dla t w (0, 1] (ruch otwierania).
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
            hit = None
            for t in np.linspace(.1, 1.0, 10):
                moved, label = motion(float(t))
                vol, common = _common(parts['base'], moved)
                if vol is not None and vol > TOL_VOLUME:
                    hit = (label, common)
                    break
            if hit:
                add('error', f'Otwieranie: pokrywa koliduje z podstawą {hit[0]}.', hit[1])
            else:
                add('ok', 'Otwieranie i zamykanie: bez kolizji w położeniach pośrednich.')
            add('warning', 'Kontrola ruchu jest próbkowana (10 położeń) - nie gwarantuje wykrycia wszystkich kolizji podczas ruchu.')
    # montaż elementów: wsuwanie od strony otwarcia (podstawa bez pokrywy)
    if insertion_dir is not None:
        import cadquery as cq
        base = parts.get('base', parts.get('body'))
        d = np.asarray(insertion_dir, float)
        height = float(np.linalg.norm(np.asarray(_bb(base).CornerMax().Coord()) - np.asarray(_bb(base).CornerMin().Coord())))
        for comp in components:
            if comp.kind != 'solid':
                continue
            blocked = None
            for t in np.linspace(.1, 1.0, 10):
                moved = cq.Shape.cast(comp.shape.wrapped).translate(cq.Vector(*(d * height * t))).wrapped
                vol, common = _common(moved, base)
                if vol is not None and vol > TOL_VOLUME:
                    blocked = (t * height, common)
                    break
            if blocked:
                add('warning', f'Montaż: „{comp.name}” nie przejdzie przez otwarcie (kolizja po {blocked[0]:.0f} mm wysuwania) - może wymagać montażu przed zamknięciem ścianek.', blocked[1], comp.id)
            else:
                add('ok', f'Montaż: „{comp.name}” da się włożyć od strony otwarcia.', None, comp.id)
        add('warning', 'Kontrola montażu jest próbkowana - nie gwarantuje wykrycia wszystkich kolizji podczas wkładania.')
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
        f = None
        if systems:
            from . import enclosure_closure as ec
            fr, f = ec.features(env, spec, lay, plane)
            interference = f['interference']
            for key in ('base_add', 'lid_add'):
                for n, sh in enumerate(f[key]):
                    closure_solids.append((f'{key.split("_")[0]}:{n + 1}', fr.world_shape(sh)))
        if 'lid' in parts:
            motion = _motion(env, spec, f, parts, lay, plane)
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


def _motion(env, spec, f, parts, lay, plane):
    """Ruch otwierania pokrywy: zawias - obrót, wsuwana - przesunięcie, inne - uniesienie (zatrzaski pomijane - ugięcie)."""
    import cadquery as cq
    lid = cq.Shape.cast(parts['lid'])
    ax = np.asarray(env.axes, float)
    c = np.asarray(env.center, float)
    m = f['motion'] if f else None
    if m is not None and m[0] == 'hinge':
        _k, pt, d, _s, angle = m
        pw, dw = c + ax.T @ pt, ax.T @ d
        probe = lid.rotate(cq.Vector(*pw), cq.Vector(*(pw + dw)), 10.0)
        sgn = 1 if float((probe.Center() - lid.Center()).dot(cq.Vector(*plane[1]))) >= 0 else -1
        return lambda t: (lid.rotate(cq.Vector(*pw), cq.Vector(*(pw + dw)), sgn * angle * t).wrapped, f'przy otwarciu o {angle * t:.0f}°')
    if m is not None and m[0] == 'slide':
        _k, axis, sign, length = m
        v = ax[axis] * sign
        return lambda t: (lid.translate(cq.Vector(*(v * length * t * 1.05))).wrapped, f'przy wysunięciu o {length * t:.0f} mm')
    if any(s.get('type') == 'snap' for s in (spec.closure or {}).get('systems', [])):
        return None
    n = np.asarray(plane[1], float)
    h = float(np.max(lay['outer_size']))
    return lambda t: (lid.translate(cq.Vector(*(n * h * t))).wrapped, f'przy uniesieniu o {h * t:.0f} mm')
