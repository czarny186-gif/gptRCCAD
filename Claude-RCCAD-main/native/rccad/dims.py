"""Wymiary szkicu jako linie konstrukcyjne (zakładka Szkic → Wymiar).

Wymiar między dwoma punktami szkicu zostaje na polu roboczym jako purpurowa przerywana linia z wartością - obiekt rodzaju
'cline' (pozycja „Linie konstrukcyjne” na liście Obiekty). Nie jest geometrią modelu: nie trafia do eksportu, nie bierze
udziału w wyciąganiu ani operacjach. Jego końce wskazują punkty kształtów (id kształtu + numer punktu z
kernel.sketch_points), więc linia idzie za kształtami, gdy się przesuwają. Usunięcie linii nie zmienia ustawionego odstępu.

meta['dim'] = dict(a=dict(id, i, p), b=dict(id, i, p), axis=[x, y, z] | None, sym=bool)
  a / b - punkt: id kształtu, numer punktu i ostatnie znane położenie (gdy kształtu już nie ma),
  axis - wymiar poziomy / pionowy (oś szkicu) albo None (najkrótsza odległość),
  sym - wpisany wymiar rozsuwa oba kształty po równo (inaczej przesuwa się tylko kształt punktu b)."""
from __future__ import annotations

from dataclasses import replace
import uuid

import numpy as np

from . import kernel
from . import sketchmeta as sm

COLOR = '#9b30c8'            # purpurowy kolor linii wymiarowej


def line_shape(a, b):
    import cadquery as cq
    a, b = (np.asarray(p, float) for p in (a, b))
    if np.linalg.norm(b - a) < 1e-9:
        b = a + np.array([1e-6, 0.0, 0.0])
    return cq.Wire.assembleEdges([cq.Edge.makeLine(cq.Vector(*map(float, a)), cq.Vector(*map(float, b)))])


_POINTS = {}


def points_of(shape):
    """Punkty wymiarowania kształtu (kernel.sketch_points) z pamięcią podręczną."""
    key = id(shape)
    hit = _POINTS.get(key)
    if hit is None or hit[0] is not shape:
        try:
            pts = kernel.sketch_points(shape)
        except Exception:
            pts = []
        if len(_POINTS) > 512:
            _POINTS.clear()
        hit = _POINTS[key] = (shape, pts)
    return hit[1]


def ref(body, point, index=None):
    """Opis końca wymiaru: id kształtu, numer najbliższego punktu kształtu i położenie."""
    point = np.asarray(point, float)
    if index is None:
        pts = points_of(body.shape)
        index = int(np.argmin([np.linalg.norm(p - point) for p, _ in pts])) if pts else -1
    return dict(id=body.id, i=int(index), p=[float(c) for c in point])


def ref_free(point):
    """Koniec wymiaru w stałym miejscu (punkt siatki, krawędzi, dowolny punkt szkicu) - nie należy do kształtu."""
    return dict(id=None, i=-1, p=[float(c) for c in point])


def end_point(end, bodies):
    """Aktualne położenie końca wymiaru (kształt mógł się przesunąć)."""
    body = bodies.get(end['id']) if isinstance(bodies, dict) else next((b for b in bodies if b.id == end['id']), None)
    if body is not None and body.kind == 'sketch' and end.get('i', -1) >= 0:
        pts = points_of(body.shape)
        if end['i'] < len(pts):
            return np.asarray(pts[end['i']][0], float)
    return np.asarray(end['p'], float)


def measure(a, b, axis=None):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.linalg.norm(b - a)) if axis is None else abs(float((b - a) @ np.asarray(axis, float)))


def total_shift(a, b, value, axis=None):
    """Przesunięcie punktu b (względem a), po którym wymiar ma wartość value."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if axis is None:
        d = b - a
        length = float(np.linalg.norm(d))
        if length < 1e-12:
            raise kernel.CadError('Punkty leżą w tym samym miejscu - nie wiadomo, w którą stronę przesunąć.')
        return d / length * (float(value) - length)
    axis = np.asarray(axis, float)
    cur = float((b - a) @ axis)
    sign = 1.0 if cur >= 0 else -1.0
    return axis * (sign * float(value) - cur)


def moved(body, shift, meta_shape):
    """Kształt przesunięty o wektor; kształt z wymiarami (okrąg, prostokąt…) przesuwa swoje punkty i zachowuje wymiary."""
    shift = np.asarray(shift, float)
    if float(np.linalg.norm(shift)) < 1e-12:
        return body
    meta = body.meta
    if meta and meta.get('tool') in sm.EDITABLE and meta.get('points'):
        p0 = np.asarray(kernel.uv_of(body.plane, (0.0, 0.0, 0.0)), float)
        p1 = np.asarray(kernel.uv_of(body.plane, tuple(float(c) for c in shift)), float)
        du, dv = (p1 - p0).tolist()
        meta2 = dict(meta, points=[[round(float(p[0]) + du, 6), round(float(p[1]) + dv, 6)] for p in meta['points']])
        shape = meta_shape(body.plane, meta2)
        return replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=meta2)
    shape = body.shape.translate(tuple(float(c) for c in shift))
    return replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=None if not (meta or {}).get('surface') else meta)


def _line_ends(body):
    meta = body.meta
    if meta and meta.get('tool') == 'line' and len(meta.get('points') or ()) == 2:
        return [np.asarray(kernel.to_world(body.plane, *p), float) for p in meta['points']], True
    edges = body.shape.Edges()
    if len(edges) == 1 and edges[0].geomType() == 'LINE':
        return [np.array(edges[0].startPoint().toTuple(), float), np.array(edges[0].endPoint().toTuple(), float)], False
    return None, False


def stretched(body, a, b, shift_a, shift_b, meta_shape):
    """Oba punkty na jednym kształcie: linia zmienia długość - jej końce przesuwają się o shift_a / shift_b."""
    ends, parametric = _line_ends(body)
    if ends is None:
        raise kernel.CadError('Oba punkty leżą na tym samym kształcie - wybierz punkty dwóch różnych kształtów '
                              '(albo kliknij sam kształt, żeby zmienić jego wymiary).')
    new = [e.copy() for e in ends]
    for point, shift in ((a, shift_a), (b, shift_b)):
        k = int(np.argmin([np.linalg.norm(e - point) for e in ends]))
        if np.linalg.norm(ends[k] - point) < 1e-4:
            new[k] = new[k] + shift
    if np.linalg.norm(new[1] - new[0]) < 1e-6:
        raise kernel.CadError('Wymiar musi być większy od zera.')
    if parametric:
        pts = [[round(float(c), 6) for c in kernel.uv_of(body.plane, tuple(float(c) for c in e))] for e in new]
        meta2 = dict(body.meta, points=pts)
        shape = meta_shape(body.plane, meta2)
        return replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=meta2)
    shape = line_shape(*new)
    return replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=None)


def apply(bodies, a_end, b_end, value, axis, sym, meta_shape):
    """Kształty po ustawieniu wymiaru: {id: nowy kształt}. sym - oba kształty rozsuwają się po równo (każdy o połowę),
    inaczej przesuwa się tylko kształt punktu b."""
    by_id = {b.id: b for b in bodies}
    a, b = end_point(a_end, by_id), end_point(b_end, by_id)
    total = total_shift(a, b, value, axis)
    body_a, body_b = by_id.get(a_end['id']), by_id.get(b_end['id'])
    if a_end['id'] is None and b_end['id'] is None:
        raise kernel.CadError('Oba końce wymiaru to stałe punkty (siatka) - ten wymiar tylko mierzy.')
    if b_end['id'] is None:                  # drugi koniec stały (punkt siatki): przesuwa się kształt pierwszego punktu
        if body_a is None:
            raise kernel.CadError('Kształtu, do którego prowadzi wymiar, już nie ma.')
        return {body_a.id: moved(body_a, -total, meta_shape)}
    if a_end['id'] is None:
        sym = False                          # pierwszy koniec stały: rusza się tylko kształt drugiego punktu
    shift_a, shift_b = (-total / 2, total / 2) if sym else (np.zeros(3), total)
    if body_b is None or (sym and body_a is None):
        raise kernel.CadError('Kształtu, do którego prowadzi wymiar, już nie ma.')
    if a_end['id'] == b_end['id']:
        return {body_b.id: stretched(body_b, a, b, shift_a, shift_b, meta_shape)}
    out = {body_b.id: moved(body_b, shift_b, meta_shape)}
    if sym:
        out[body_a.id] = moved(body_a, shift_a, meta_shape)
    return out


def make(plane, a_end, b_end, axis, sym, bodies, ident=None):
    """Nowa linia konstrukcyjna wymiaru (obiekt 'cline')."""
    from .document import Body
    a, b = end_point(a_end, bodies), end_point(b_end, bodies)
    meta = dict(dim=dict(a=dict(a_end, p=[float(c) for c in a]), b=dict(b_end, p=[float(c) for c in b]),
                         axis=None if axis is None else [float(c) for c in axis], sym=bool(sym)))
    value = measure(a, b, axis)
    return Body(f'Wymiar {value:g} mm', line_shape(a, b), 'cline', plane, id=ident or uuid.uuid4().hex, meta=meta).prepared()


def refreshed(cline, bodies):
    """Linia wymiaru z końcami w aktualnym położeniu kształtów (po ustawieniu nowej wartości)."""
    d = cline.meta['dim']
    a, b = end_point(d['a'], bodies), end_point(d['b'], bodies)
    meta = dict(cline.meta, dim=dict(d, a=dict(d['a'], p=[float(c) for c in a]), b=dict(d['b'], p=[float(c) for c in b])))
    return replace(cline, shape=line_shape(a, b), name=f'Wymiar {measure(a, b, d.get("axis")):g} mm', meta=meta).prepared()


def view_items(bodies, selected=(), hidden=()):
    """Linie wymiarów do narysowania nad modelem: końce w aktualnym położeniu kształtów, wartość, zaznaczenie."""
    by_id = {b.id: b for b in bodies}
    out = []
    for body in bodies:
        if body.kind != 'cline' or not body.visible or body.id in hidden or not (body.meta or {}).get('dim'):
            continue
        d = body.meta['dim']
        a, b = end_point(d['a'], by_id), end_point(d['b'], by_id)
        axis = d.get('axis')
        out.append(dict(id=body.id, a=a, b=b, axis=None if axis is None else np.asarray(axis, float),
                        value=measure(a, b, axis), sym=bool(d.get('sym')), selected=body.id in selected))
    return out
