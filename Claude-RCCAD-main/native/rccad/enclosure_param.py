"""Generator obudów - etap 13: obudowa jako operacja parametryczna dokumentu.

Zapis: definicja obudowy (EnclosureSpec - elementy źródłowe, układ, kształt, wymiary i odstępy, ścianki, podział,
mocowania, zamknięcia, technologia) w kroku historii 'enclosure' i w meta brył; otwory ('enc_hole') i wentylacja
('enc_vent') - osobne kroki z kolejnością (seq) zapisaną w meta części. Do tego podpis elementów źródłowych (środek masy,
osie bezwładności, ramka) - pozwala wykryć zmianę geometrii / położenia i przenieść referencje (punkty montażowe, ściany
elementów wskazane dla otworów, ścianki obudowy) sztywnym przekształceniem dopasowanym do nowego położenia - bez
polegania na numerach ścian i krawędzi.

Tryby obudowy (meta 'enclosure_mode'): 'auto' - po zmianie elementów obudowa przebudowuje się sama (krok „Aktualizacja
obudowy”), 'manual' - obudowa oznaczona jako wymagająca aktualizacji, przebudowa przyciskiem, 'frozen' - parametry
zamrożone (bez aktualizacji i edycji), konwersja - generator usunięty, zostają niezależne bryły B-Rep. Gdy przebudowa się
nie uda, zostaje ostatnia poprawna geometria, a obudowa jest oznaczona jako wymagająca aktualizacji (z powodem); gdy
referencji nie da się jednoznacznie odtworzyć - komunikat z prośbą o ponowne wskazanie."""
from __future__ import annotations

import copy
import itertools

import numpy as np

from . import kernel

MODES = ('auto', 'manual', 'frozen')
MODE_LABELS = {'auto': 'Automatyczna aktualizacja', 'manual': 'Aktualizacja ręczna', 'frozen': 'Parametry zamrożone'}
POS_TOL = 1e-3


_FRAMES = {}


def frame_of(shape):
    """Podpis elementu (z pamięcią dla tego samego kształtu)."""
    key = id(shape)
    hit = _FRAMES.get(key)
    if hit is not None and hit[0] is shape:
        return hit[1]
    value = _frame_of(shape)
    if len(_FRAMES) > 512:
        _FRAMES.clear()
    _FRAMES[key] = (shape, value)
    return value


def _frame_of(shape):
    """Podpis elementu: środek masy, osie główne bezwładności (wiersze), ramka - do wykrycia zmian i przeniesienia referencji."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped if hasattr(shape, 'wrapped') else shape, props)
    if props.Mass() <= 1e-12:
        BRepGProp.SurfaceProperties_s(shape.wrapped if hasattr(shape, 'wrapped') else shape, props)
    c = np.array(props.CentreOfMass().Coord(), float)
    pp = props.PrincipalProperties()
    axes = np.array([pp.FirstAxisOfInertia().Coord(), pp.SecondAxisOfInertia().Coord(), pp.ThirdAxisOfInertia().Coord()], float)
    moments = list(map(float, pp.Moments()))
    lo, hi = _bbox(shape)
    return dict(center=[float(x) for x in c], axes=axes.tolist(), moments=moments, lo=list(lo), hi=list(hi), mass=float(props.Mass()))


def _bbox(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped if hasattr(shape, 'wrapped') else shape, box, False, False)
    x0, y0, z0, x1, y1, z1 = box.Get()
    return (round(x0, 6), round(y0, 6), round(z0, 6)), (round(x1, 6), round(y1, 6), round(z1, 6))


def signature(bodies, spec):
    by_id = {b.id: b for b in bodies}
    return {s.id: frame_of(by_id[s.id].shape) for s in spec.sources if s.id in by_id}


def changed(old, new):
    """Czy element zmienił geometrię albo położenie (środek, ramka, masa)."""
    if old is None or new is None:
        return old is not new
    for key in ('center', 'lo', 'hi'):
        if np.linalg.norm(np.asarray(old[key], float) - np.asarray(new[key], float)) > POS_TOL:
            return True
    return abs(float(old['mass']) - float(new['mass'])) > max(1e-6, 1e-7 * abs(float(old['mass'])))


def stale(bodies, body):
    """Obudowa wymaga aktualizacji: któryś element źródłowy zmienił się od ostatniej przebudowy (albo zniknął)."""
    meta = body.meta or {}
    sig = meta.get('enclosure_sig')
    if not sig:
        return False
    by_id = {b.id: b for b in bodies}
    for sid, old in sig.items():
        b = by_id.get(sid)
        if b is None:
            return True
        try:
            if changed(old, frame_of(b.shape)):
                return True
        except Exception:
            return True
    return False


def rigid_candidates(old, new):
    """Sztywne przekształcenia (R, t) przenoszące stary podpis na nowy: osie główne z niejednoznacznym zwrotem - kandydaci
    z wyznacznikiem +1; samo przesunięcie (R = I) - pierwszy kandydat."""
    c0, c1 = np.asarray(old['center'], float), np.asarray(new['center'], float)
    A0, A1 = np.asarray(old['axes'], float), np.asarray(new['axes'], float)
    out = [(np.eye(3), c1 - c0)]
    for signs in itertools.product((1, -1), repeat=3):
        S = np.diag(signs)
        R = A1.T @ S @ A0
        if np.linalg.det(R) < .5:
            continue
        out.append((R, c1 - R @ c0))
    return out


def _apply(T, p):
    R, t = T
    return R @ np.asarray(p, float) + t


def remap_mounts(bodies, spec, sig):
    """Punkty montażowe po zmianie położenia elementów: przekształcenie wybrane tak, by otwory trafiały w ponownie wykryte
    otwory elementu (ten sam rodzaj i średnica). Ręczne punkty - przekształcenie dopasowane do pozostałych otworów elementu
    albo samo przesunięcie. Bez jednoznacznego dopasowania - CadError (wskaż punkt ponownie)."""
    from . import enclosure_mounts as mnt
    from .enclosure import envelope
    if not spec.mounts:
        return spec.mounts
    by_id = {b.id: b for b in bodies}
    env = envelope(bodies, spec)
    out = []
    per_source = {}
    for m in spec.mounts:
        per_source.setdefault(m.get('source'), []).append(m)
    for sid, mounts in per_source.items():
        body = by_id.get(sid)
        old = (sig or {}).get(sid)
        if body is None:
            raise kernel.CadError('Element z punktami montażowymi został usunięty - wskaż punkty ponownie.')
        new = frame_of(body.shape)
        if old is None or not changed(old, new):
            out += mounts
            continue
        found = mnt.detect(bodies, [sid], env) if body.kind == 'solid' else []
        best = None
        for T in rigid_candidates(old, new):
            score, mapped = 0, []
            for m in mounts:
                c = _apply(T, m['center'])
                a = T[0] @ np.asarray(m['axis'], float)
                if m.get('manual'):
                    mapped.append(dict(m, center=c.tolist(), axis=a.tolist()))
                    continue
                hit = next((h for h in found if abs(h['diameter'] - m['diameter']) < 1e-3 and min(
                    np.linalg.norm(np.asarray(h['center']) - c), *(np.linalg.norm(np.asarray(e) - c) for e in h.get('ends') or [])) < 1e-2), None)
                if hit is not None:
                    score += 1
                    mapped.append(dict(m, center=c.tolist(), axis=a.tolist(), ends=hit.get('ends'), side=hit.get('side')))
            if len(mapped) == len(mounts) and (best is None or score > best[0]):
                best = (score, mapped)
        auto = [m for m in mounts if not m.get('manual')]
        if best is None or (auto and best[0] < len(auto)):
            names = ', '.join(sorted({m.get('source_name', '') for m in mounts}))
            raise kernel.CadError(f'Nie można jednoznacznie odtworzyć punktów montażowych elementu „{names}” po jego zmianie - wskaż je ponownie (Utwórz obudowę → Punkty montażowe).')
        out += best[1]
    return out


def remap_point_on(bodies, sig, sid, point):
    """Punkt na elemencie (np. ściana wskazana dla otworu) po zmianie jego położenia - najlepszy kandydat, który leży na
    powierzchni elementu."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    by_id = {b.id: b for b in bodies}
    body, old = by_id.get(sid), (sig or {}).get(sid)
    if body is None or old is None:
        return point
    new = frame_of(body.shape)
    if not changed(old, new):
        return point
    for T in rigid_candidates(old, new):
        q = _apply(T, point)
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, q))).Vertex()
        d = BRepExtrema_DistShapeShape(v, body.shape.wrapped)
        d.Perform()
        if d.IsDone() and d.Value() < 1e-3:
            return [float(x) for x in q]
    raise kernel.CadError('Nie można odtworzyć ściany elementu wskazanej dla otworu - wskaż ją ponownie (edycja kroku otworu).')


def rematch_wall(part_shape, point, normal, old_env, new_env):
    """Ścianka obudowy po przebudowie: płaska ściana nowej części o tej samej orientacji względem obudowy (normalna
    przeniesiona obrotem układu przestrzeni), najbliższa przeniesionemu punktowi - bez numerów ścian."""
    ax0, ax1 = np.asarray(old_env.axes, float), np.asarray(new_env.axes, float)
    R = ax1.T @ ax0
    n = R @ np.asarray(normal, float)
    p = np.asarray(new_env.center, float) + R @ (np.asarray(point, float) - np.asarray(old_env.center, float))
    best = None
    for f in part_shape.Faces():
        if f.geomType() != 'PLANE':
            continue
        fn = np.asarray(f.normalAt(f.Center()).toTuple(), float)
        if float(fn @ n) < 1 - 1e-6:
            continue
        c = np.asarray(f.Center().toTuple(), float)
        d = abs(float((c - p) @ n)) + .01 * float(np.linalg.norm((c - p) - ((c - p) @ n) * n))
        if best is None or d < best[0]:
            best = (d, c, fn)
    if best is None:
        raise kernel.CadError('Nie można odtworzyć ścianki obudowy wskazanej dla otworu - wskaż ją ponownie.')
    plane_pt = p - float((p - best[1]) @ best[2]) * best[2]
    return [float(x) for x in plane_pt], [float(x) for x in best[2]]


def group(bodies, body):
    """Części jednej obudowy: bryła obudowy albo podstawa i pokrywa (ta sama grupa)."""
    if not (body.meta or {}).get('enclosure_part'):
        return [body]
    return [b for b in bodies if (b.meta or {}).get('enclosure_part') and b.folder == body.folder and (b.meta or {}).get('enclosure')]


def regenerate(bodies, recipe):
    """Krok 'enc_regen': przebudowa obudowy z aktualnych elementów źródłowych - definicja, potem otwory i wentylacja w
    zapisanej kolejności (zależności: część obudowy → jej otwory). Identyfikatory brył zostają, meta (tryb, operacje) też."""
    from . import enclosure as enc
    from .enclosure_hole_ui import run as run_hole
    from .enclosure_vent_ui import run as run_vent
    by_id = {b.id: b for b in bodies}
    first = by_id.get(recipe['id'])
    if first is None:
        raise kernel.CadError('Obudowy do aktualizacji już nie ma.')
    parts = group(bodies, first)
    meta0 = first.meta or {}
    spec = enc.EnclosureSpec.from_json(meta0['enclosure'])
    old_env = copy.deepcopy(spec.envelope)
    sig = meta0.get('enclosure_sig')
    spec.mounts = remap_mounts(bodies, spec, sig)
    base = next((b for b in parts if (b.meta or {}).get('enclosure_part') in (None, 'base')), parts[0])
    lid = next((b for b in parts if (b.meta or {}).get('enclosure_part') == 'lid'), None)
    name = (base.folder or base.name.split(' - ')[0]) if lid is not None else base.name
    rec = dict(type='enclosure', spec=spec.to_json(), out=base.id, name=name)
    if lid is not None:
        rec.update(out_lid=lid.id, folder=base.folder or name)
    ops = []
    for b in parts:
        for kind, key in (('hole', 'enclosure_holes'), ('vent', 'enclosure_vents')):
            for r in (b.meta or {}).get(key, []):
                ops.append((r.get('seq', 0), kind, dict(r, type='enc_hole' if kind == 'hole' else 'enc_vent')))
    ops.sort(key=lambda x: x[0])
    # części bez otworów: przebudowa definicji (meta otworów wyczyszczona, operacje dołożone ponownie niżej)
    cleaned = []
    for b in bodies:
        if b in parts:
            meta = {k: v for k, v in (b.meta or {}).items() if k not in ('enclosure_holes', 'enclosure_vents')}
            from dataclasses import replace
            b = replace(b, meta=meta)
        cleaned.append(b)
    out = enc.run(cleaned, rec)
    new_env = enc.EnclosureSpec.from_json(next(b for b in out if b.id == base.id).meta['enclosure']).envelope
    for _seq, kind, r in ops:
        target = next(b for b in out if b.id == r['target'])
        point, normal = rematch_wall(target.shape, r['point'], r['normal'], old_env, new_env)
        r = dict(r, point=point, normal=normal)
        if kind == 'hole':
            r['faces'] = [[fid, remap_point_on(bodies, sig, fid, p)] for fid, p in r.get('faces') or []]
            out = run_hole(out, r)
        else:
            out = run_vent(out, r)
    keep = {k: meta0[k] for k in ('enclosure_mode',) if k in meta0}
    from dataclasses import replace
    ids = {b.id for b in parts}
    return [replace(b, meta=dict(b.meta or {}, **keep)) if b.id in ids else b for b in out]


def set_mode(bodies, recipe):
    """Krok 'enc_mode': tryb aktualizacji obudowy (auto / ręczna / zamrożona) we wszystkich jej częściach."""
    from dataclasses import replace
    by_id = {b.id: b for b in bodies}
    first = by_id.get(recipe['id'])
    if first is None:
        raise kernel.CadError('Obudowy już nie ma.')
    if recipe['mode'] not in MODES:
        raise kernel.CadError('Nieznany tryb obudowy.')
    ids = {b.id for b in group(bodies, first)}
    return [replace(b, meta=dict(b.meta or {}, enclosure_mode=recipe['mode'])) if b.id in ids else b for b in bodies]


def convert(bodies, recipe):
    """Krok 'enc_convert': konwersja do niezależnych brył B-Rep - parametry generatora usunięte, geometria zostaje."""
    from dataclasses import replace
    by_id = {b.id: b for b in bodies}
    first = by_id.get(recipe['id'])
    if first is None:
        raise kernel.CadError('Obudowy już nie ma.')
    ids = {b.id for b in group(bodies, first)}
    drop = ('enclosure', 'enclosure_part', 'enclosure_holes', 'enclosure_vents', 'enclosure_sig', 'enclosure_mode')
    return [replace(b, meta={k: v for k, v in (b.meta or {}).items() if k not in drop} or None) if b.id in ids else b for b in bodies]
