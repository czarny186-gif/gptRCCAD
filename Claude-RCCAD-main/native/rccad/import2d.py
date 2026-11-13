"""Wczytywanie płaskich rysunków SVG i DXF do rysunku technicznego (zakładka Rysunek → Załaduj plik).

Wynikiem jest zbiór krawędzi CadQuery leżących w płaszczyźnie XY (w mm). Okręgi i łuki zostają prawdziwymi okręgami,
więc rysunek techniczny może je zwymiarować (średnice, promienie, osie). Moduł nie zależy od Qt."""
from __future__ import annotations
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import cadquery as cq
import numpy as np

from .kernel import CadError

MAX_BYTES = 40 * 1024 * 1024
MAX_EDGES = 60000
_TOL = 1e-6


class _Sink:
    """Zbiera krawędzie, pomijając zdegenerowane (zerowej długości)."""

    def __init__(self):
        self.edges = []
        self.marks = []              # początki kolejnych elementów (SVG: każdy kształt łączony w obwody osobno)

    def mark(self):
        if not self.marks or self.marks[-1] != len(self.edges):
            self.marks.append(len(self.edges))

    def _check(self):
        if len(self.edges) > MAX_EDGES:
            raise CadError('Plik zawiera zbyt wiele elementów do narysowania.')

    def line(self, a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        if np.linalg.norm(b - a) > _TOL:
            self.edges.append(cq.Edge.makeLine(cq.Vector(a[0], a[1], 0), cq.Vector(b[0], b[1], 0)))
            self._check()

    def polyline(self, pts, closed=False):
        pts = [np.asarray(p, float) for p in pts]
        for a, b in zip(pts, pts[1:]):
            self.line(a, b)
        if closed and len(pts) > 2:
            self.line(pts[-1], pts[0])

    def circle(self, c, r):
        if r > _TOL:
            self.edges.append(cq.Edge.makeCircle(float(r), cq.Vector(float(c[0]), float(c[1]), 0)))
            self._check()

    def arc(self, c, r, a0, a1):
        """Łuk przeciwnie do ruchu wskazówek zegara od kąta a0 do a1 (stopnie)."""
        if r <= _TOL:
            return
        sweep = (a1 - a0) % 360.0
        if sweep < 1e-7:
            sweep = 360.0
        if abs(sweep - 360.0) < 1e-7:
            self.circle(c, r)
            return
        cx, cy = float(c[0]), float(c[1])
        pt = lambda a: cq.Vector(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)), 0)
        self.edges.append(cq.Edge.makeThreePointArc(pt(a0), pt(a0 + sweep / 2), pt(a0 + sweep)))
        self._check()

    def bezier(self, pts):
        pts = [np.asarray(p, float) for p in pts]
        if np.linalg.norm(pts[-1] - pts[0]) < _TOL and max(np.linalg.norm(p - pts[0]) for p in pts) < _TOL:
            return
        if all(np.linalg.norm(np.cross(np.append(p - pts[0], 0), np.append(pts[-1] - pts[0], 0))) < 1e-9 for p in pts[1:-1]):
            self.line(pts[0], pts[-1])       # krzywa leżąca na prostej
            return
        try:
            self.edges.append(cq.Edge.makeBezier([cq.Vector(p[0], p[1], 0) for p in pts]))
            self._check()
        except CadError:
            raise
        except Exception:
            self.polyline([_bezier_point(pts, t) for t in np.linspace(0, 1, 24)])

    def spline(self, pts, closed=False):
        """Gładka krzywa przez punkty jako JEDNA krawędź (zamiast setek odcinków, które spowalniają rysunek)."""
        pts = [np.asarray(p, float) for p in pts]
        clean = [pts[0]] if pts else []
        for q in pts[1:]:
            if np.linalg.norm(q - clean[-1]) > 1e-7:
                clean.append(q)
        if closed and len(clean) > 2 and np.linalg.norm(clean[-1] - clean[0]) < 1e-7:
            clean = clean[:-1]
        if len(clean) < 2:
            return
        if len(clean) == 2:
            self.line(clean[0], clean[1])
            return
        try:
            self.edges.append(cq.Edge.makeSpline([cq.Vector(q[0], q[1], 0) for q in clean], periodic=closed))
            self._check()
        except CadError:
            raise
        except Exception:
            self.polyline(clean, closed)

    def bspline(self, poles, knots, degree, weights=None):
        """Dokładna krzywa B-sklejana z DXF (punkty kontrolne, węzły, stopień) jako jedna krawędź."""
        from OCP.Geom import Geom_BSplineCurve
        from OCP.TColgp import TColgp_Array1OfPnt
        from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
        from OCP.gp import gp_Pnt
        uniq, mult = [], []
        for k in knots:
            if uniq and abs(k - uniq[-1]) < 1e-12:
                mult[-1] += 1
            else:
                uniq.append(float(k)); mult.append(1)
        cp = TColgp_Array1OfPnt(1, len(poles))
        for i, q in enumerate(poles, 1):
            cp.SetValue(i, gp_Pnt(float(q[0]), float(q[1]), 0.0))
        kn = TColStd_Array1OfReal(1, len(uniq))
        mu = TColStd_Array1OfInteger(1, len(mult))
        for i, (k, m) in enumerate(zip(uniq, mult), 1):
            kn.SetValue(i, k); mu.SetValue(i, m)
        if weights is not None and len(weights) == len(poles) and any(abs(w - 1) > 1e-12 for w in weights):
            wt = TColStd_Array1OfReal(1, len(weights))
            for i, w in enumerate(weights, 1):
                wt.SetValue(i, float(w))
            curve = Geom_BSplineCurve(cp, wt, kn, mu, int(degree))
        else:
            curve = Geom_BSplineCurve(cp, kn, mu, int(degree))
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        edge = cq.Edge(BRepBuilderAPI_MakeEdge(curve).Edge())
        if edge.Length() > _TOL:
            self.edges.append(edge)
            self._check()

    def shape(self):
        if not self.edges:
            raise CadError('W pliku nie znaleziono linii, łuków ani krzywych do narysowania.')
        return cq.Compound.makeCompound(self.edges)


def _bezier_point(pts, t):
    pts = [np.asarray(p, float) for p in pts]
    while len(pts) > 1:
        pts = [a + (b - a) * t for a, b in zip(pts, pts[1:])]
    return pts[0]


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
_UNITS = {'mm': 1.0, 'cm': 10.0, 'in': 25.4, 'pt': 25.4 / 72, 'pc': 25.4 / 6, 'px': 25.4 / 96, 'q': 0.25}
_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def _length(text, default=None):
    """Długość z jednostką SVG w mm (bez jednostki: None - wtedy jednostka użytkownika = 1 mm)."""
    if text is None:
        return default, None
    m = re.match(r'\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)', str(text))
    if not m:
        return default, None
    unit = m.group(2).lower()
    return float(m.group(1)), unit or None


def _num(el, name, default=0.0):
    value, _ = _length(el.get(name), default)
    return float(value) if value is not None else default


def _matrix(a, b, c, d, e, f):
    return np.array([[a, c, e], [b, d, f], [0, 0, 1]], float)


def _transform(text):
    """Atrybut transform → macierz 3x3 (matrix, translate, scale, rotate, skewX, skewY)."""
    m = np.eye(3)
    for name, args in re.findall(r'([a-zA-Z]+)\s*\(([^)]*)\)', text or ''):
        v = [float(x) for x in _NUM.findall(args)]
        name = name.lower()
        if name == 'matrix' and len(v) == 6:
            t = _matrix(*v)
        elif name == 'translate' and v:
            t = _matrix(1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == 'scale' and v:
            t = _matrix(v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == 'rotate' and v:
            a = math.radians(v[0])
            r = _matrix(math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) == 3:
                t = _matrix(1, 0, 0, 1, v[1], v[2]) @ r @ _matrix(1, 0, 0, 1, -v[1], -v[2])
            else:
                t = r
        elif name == 'skewx' and v:
            t = _matrix(1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == 'skewy' and v:
            t = _matrix(1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = m @ t
    return m


class _SvgOut:
    """Przekształca punkty SVG (macierz elementu, odwrócona oś Y) i rozpoznaje, czy łuki zostają okręgami (bez skośnego zniekształcenia)."""

    def __init__(self, sink, matrix):
        self.sink, self.m = sink, matrix
        a, b, c, d = matrix[0, 0], matrix[1, 0], matrix[0, 1], matrix[1, 1]
        self.uniform = abs(a * c + b * d) < 1e-9 and abs(math.hypot(a, b) - math.hypot(c, d)) < 1e-9 * max(1.0, math.hypot(a, b))
        self.scale = math.hypot(a, b)
        self.flip = (a * d - b * c) > 0       # po odwróceniu osi Y kierunek obiegu zmienia się, gdy macierz go nie odwraca

    def p(self, pt):
        q = self.m @ np.array([pt[0], pt[1], 1.0])
        return np.array([q[0], -q[1]])

    def line(self, a, b):
        self.sink.line(self.p(a), self.p(b))

    def bezier(self, pts):
        self.sink.bezier([self.p(q) for q in pts])

    def ellipse_arc(self, c, rx, ry, phi, t0, dt):
        """Łuk elipsy (parametry SVG po konwersji na środek): okrąg → łuk / okrąg, inaczej łamana."""
        c = np.asarray(c, float)
        if self.uniform and abs(rx - ry) < 1e-9 * max(1.0, rx):
            centre = self.p(c)
            r = rx * self.scale
            ang = lambda t: math.degrees(math.atan2(*(self.p(c + rx * np.array([math.cos(t + phi), math.sin(t + phi)])) - centre)[::-1]))
            if abs(abs(dt) - 2 * math.pi) < 1e-9:
                self.sink.circle(centre, r)
                return
            a0, a1 = ang(t0), ang(t0 + dt)
            ccw_on_paper = (dt > 0) != self.flip     # oś Y odwrócona względem SVG
            self.sink.arc(centre, r, a0, a1) if ccw_on_paper else self.sink.arc(centre, r, a1, a0)
            return
        n = max(8, int(abs(dt) / (2 * math.pi) * 48))
        cp, sp = math.cos(phi), math.sin(phi)
        pts = []
        for t in np.linspace(t0, t0 + dt, n + 1):
            x, y = rx * math.cos(t), ry * math.sin(t)
            pts.append(self.p((c[0] + x * cp - y * sp, c[1] + x * sp + y * cp)))
        closed = abs(abs(dt) - 2 * math.pi) < 1e-9
        self.sink.spline(pts, closed)


def _arc_center(p0, p1, rx, ry, phi_deg, large, sweep):
    """Konwersja łuku SVG (punkty końcowe) na parametryzację środkową: (środek, rx, ry, phi, kąt początkowy, przyrost)."""
    phi = math.radians(phi_deg % 360)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = cp * dx + sp * dy, -sp * dx + cp * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / den)) if den > 0 else 0.0
    if large == sweep:
        k = -k
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx = cp * cx1 - sp * cy1 + (p0[0] + p1[0]) / 2
    cy = sp * cx1 + cp * cy1 + (p0[1] + p1[1]) / 2
    ang = lambda ux, uy, vx, vy: math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t0 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    return (cx, cy), rx, ry, phi, t0, dt


def _path(out, d):
    tokens = re.findall(r'[MmLlHhVvCcSsQqTtAaZz]|' + _NUM.pattern, d or '')
    i, cmd = 0, None
    cur = np.zeros(2)
    start = np.zeros(2)
    last_c = last_q = None

    def nums(n):
        nonlocal i
        vals = []
        while len(vals) < n:
            if i >= len(tokens) or tokens[i].isalpha():
                raise ValueError
            vals.append(float(tokens[i]))
            i += 1
        return vals

    def flag():
        """Flagi łuku mogą być sklejone bez odstępu (np. 'a1 1 0 01 1 1')."""
        nonlocal i
        t = tokens[i]
        if t in ('0', '1'):
            i += 1
            return int(t)
        if t[0] in '01' and len(t) > 1:
            tokens[i] = t[1:]
            return int(t[0])
        i += 1
        return int(float(t) != 0)

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
        elif cmd is None:
            break
        rel = cmd.islower()
        c = cmd.upper()
        base = cur if rel else np.zeros(2)
        try:
            if c == 'Z':
                out.line(cur, start)
                cur = start.copy()
                last_c = last_q = None
                cmd = None if i >= len(tokens) or tokens[i].isalpha() else cmd
                continue
            if c == 'M':
                cur = base + nums(2)
                start = cur.copy()
                cmd = 'l' if rel else 'L'      # kolejne pary po M to linie
                last_c = last_q = None
            elif c == 'L':
                p = base + nums(2)
                out.line(cur, p)
                cur, last_c, last_q = p, None, None
            elif c == 'H':
                x = nums(1)[0] + (cur[0] if rel else 0)
                p = np.array([x, cur[1]])
                out.line(cur, p)
                cur, last_c, last_q = p, None, None
            elif c == 'V':
                y = nums(1)[0] + (cur[1] if rel else 0)
                p = np.array([cur[0], y])
                out.line(cur, p)
                cur, last_c, last_q = p, None, None
            elif c == 'C':
                v = nums(6)
                c1, c2, p = base + v[0:2], base + v[2:4], base + v[4:6]
                out.bezier([cur, c1, c2, p])
                cur, last_c, last_q = p, c2, None
            elif c == 'S':
                v = nums(4)
                c1 = 2 * cur - last_c if last_c is not None else cur.copy()
                c2, p = base + v[0:2], base + v[2:4]
                out.bezier([cur, c1, c2, p])
                cur, last_c, last_q = p, c2, None
            elif c == 'Q':
                v = nums(4)
                q, p = base + v[0:2], base + v[2:4]
                out.bezier([cur, q, p])
                cur, last_q, last_c = p, q, None
            elif c == 'T':
                q = 2 * cur - last_q if last_q is not None else cur.copy()
                p = base + nums(2)
                out.bezier([cur, q, p])
                cur, last_q, last_c = p, q, None
            elif c == 'A':
                rx, ry, rot = nums(3)
                large, sweep = flag(), flag()
                p = base + nums(2)
                if np.linalg.norm(p - cur) > _TOL:
                    if rx < _TOL or ry < _TOL:
                        out.line(cur, p)
                    else:
                        out.ellipse_arc(*_arc_center(cur, p, rx, ry, rot, large, sweep))
                cur, last_c, last_q = p, None, None
            else:
                break
        except (ValueError, IndexError):
            break


def _points(text):
    v = [float(x) for x in _NUM.findall(text or '')]
    return [(v[k], v[k + 1]) for k in range(0, len(v) - 1, 2)]


def _tag(el):
    return el.tag.rsplit('}', 1)[-1].lower()


def _hidden(el):
    style = el.get('style', '')
    return el.get('display') == 'none' or 'display:none' in style.replace(' ', '') or el.get('visibility') == 'hidden'


def _svg_walk(el, matrix, sink, defs):
    if _hidden(el):
        return
    tag = _tag(el)
    if tag in ('defs', 'clippath', 'mask', 'symbol', 'marker', 'pattern', 'title', 'desc', 'metadata', 'style', 'text', 'script', 'lineargradient', 'radialgradient'):
        return
    m = matrix @ _transform(el.get('transform'))
    out = _SvgOut(sink, m)
    if tag in ('line', 'polyline', 'polygon', 'rect', 'circle', 'ellipse', 'path'):
        sink.mark()
    if tag == 'line':
        out.line((_num(el, 'x1'), _num(el, 'y1')), (_num(el, 'x2'), _num(el, 'y2')))
    elif tag in ('polyline', 'polygon'):
        pts = _points(el.get('points'))
        for a, b in zip(pts, pts[1:]):
            out.line(a, b)
        if tag == 'polygon' and len(pts) > 2:
            out.line(pts[-1], pts[0])
    elif tag == 'rect':
        x, y, w, h = _num(el, 'x'), _num(el, 'y'), _num(el, 'width'), _num(el, 'height')
        rx = el.get('rx'); ry = el.get('ry')
        rx = _num(el, 'rx') if rx is not None else (_num(el, 'ry') if ry is not None else 0.0)
        ry = _num(el, 'ry') if ry is not None else rx
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if w > 0 and h > 0:
            if rx > _TOL and ry > _TOL:
                out.line((x + rx, y), (x + w - rx, y)); out.line((x + w, y + ry), (x + w, y + h - ry))
                out.line((x + w - rx, y + h), (x + rx, y + h)); out.line((x, y + h - ry), (x, y + ry))
                for cx, cy, a in ((x + w - rx, y + ry, -math.pi / 2), (x + w - rx, y + h - ry, 0.0), (x + rx, y + h - ry, math.pi / 2), (x + rx, y + ry, math.pi)):
                    out.ellipse_arc((cx, cy), rx, ry, 0.0, a, math.pi / 2)
            else:
                pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    out.line(a, b)
    elif tag == 'circle':
        r = _num(el, 'r')
        if r > 0:
            out.ellipse_arc((_num(el, 'cx'), _num(el, 'cy')), r, r, 0.0, 0.0, 2 * math.pi)
    elif tag == 'ellipse':
        rx, ry = _num(el, 'rx'), _num(el, 'ry')
        if rx > 0 and ry > 0:
            out.ellipse_arc((_num(el, 'cx'), _num(el, 'cy')), rx, ry, 0.0, 0.0, 2 * math.pi)
    elif tag == 'path':
        _path(out, el.get('d'))
    elif tag == 'use':
        ref = el.get('{http://www.w3.org/1999/xlink}href') or el.get('href') or ''
        target = defs.get(ref.lstrip('#'))
        if target is not None:
            shift = _matrix(1, 0, 0, 1, _num(el, 'x'), _num(el, 'y'))
            for child in ([target] if _tag(target) != 'symbol' else list(target)):
                _svg_walk(child, m @ shift, sink, defs)
        return
    for child in list(el):
        _svg_walk(child, m, sink, defs)


def svg_edges(path):
    data = Path(path).read_bytes()
    if len(data) > MAX_BYTES:
        raise CadError('Plik SVG jest zbyt duży.')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CadError(f'Nie można odczytać pliku SVG: {exc}')
    # skala: jednostki użytkownika → mm (gdy szerokość ma jednostkę i jest viewBox), bez jednostek 1 jednostka = 1 mm
    # skala: jednostki użytkownika → mm. Długość bez jednostki to piksele (96 na cal, jak w przeglądarce i Inkscape) -
    # wcześniej liczona jako 1 mm, przez co rysunki z sieci wchodziły prawie 4 razy za duże.
    base = np.eye(3)
    box = [float(v) for v in _NUM.findall(root.get('viewBox', ''))]
    w, wu = _length(root.get('width'))
    h, hu = _length(root.get('height'))
    wu = 'px' if (w and wu is None) else wu
    hu = 'px' if (h and hu is None) else hu
    if len(box) == 4 and box[2] > 0 and box[3] > 0:
        sx = (w * _UNITS[wu]) / box[2] if w and wu in _UNITS else _UNITS['px']
        sy = (h * _UNITS[hu]) / box[3] if h and hu in _UNITS else sx
        if not (w and wu in _UNITS) and h and hu in _UNITS:
            sx = sy
        base = _matrix(sx, 0, 0, sy, 0, 0) @ _matrix(1, 0, 0, 1, -box[0], -box[1])
    else:
        s = _UNITS[wu] if (w and wu in _UNITS) else _UNITS['px']
        base = _matrix(s, 0, 0, s, 0, 0)
    defs = {el.get('id'): el for el in root.iter() if el.get('id')}
    sink = _Sink()
    _svg_walk(root, base, sink, defs)
    return sink


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------
def _dxf_scale(doc):
    try:
        from ezdxf import units
        u = int(doc.header.get('$INSUNITS', 0))
        return units.conversion_factor(u, units.MM) if u else 1.0
    except Exception:
        return 1.0


def _dxf_entity(e, sink, s, depth=0):
    kind = e.dxftype()
    try:
        if kind == 'LINE':
            sink.line(_xy(e.dxf.start) * s, _xy(e.dxf.end) * s)
        elif kind == 'CIRCLE':
            sink.circle(_xy(e.dxf.center) * s, e.dxf.radius * s)
        elif kind == 'ARC':
            if _flat(e):
                sink.arc(_xy(e.dxf.center) * s, e.dxf.radius * s, e.dxf.start_angle, e.dxf.end_angle)
            else:
                _flatten(e, sink, s)
        elif kind in ('LWPOLYLINE', 'POLYLINE'):
            for sub in e.virtual_entities():       # odcinki i łuki (wybrzuszenia) jako LINE / ARC
                _dxf_entity(sub, sink, s, depth)
        elif kind == 'INSERT' and depth < 12:
            for sub in e.virtual_entities():
                _dxf_entity(sub, sink, s, depth + 1)
        elif kind == 'SPLINE':
            _spline(e, sink, s)
        elif kind == 'ELLIPSE':
            closed = abs(((e.dxf.end_param - e.dxf.start_param) % (2 * math.pi))) < 1e-9
            pts = [_xy(v) * s for v in e.vertices(np.linspace(e.dxf.start_param, e.dxf.end_param if not closed else e.dxf.start_param + 2 * math.pi, 49))]
            sink.spline(pts, closed)
        elif kind in ('SOLID', 'TRACE', '3DFACE'):
            pts = [_xy(e.dxf.get(n)) * s for n in ('vtx0', 'vtx1', 'vtx3', 'vtx2') if e.dxf.hasattr(n)]
            sink.polyline(pts, True)
    except CadError:
        raise
    except Exception:
        pass        # nieobsługiwany lub uszkodzony element nie przerywa wczytywania reszty


def _xy(v):
    return np.array([float(v[0]), float(v[1])])


def _flat(e):
    try:
        n = e.dxf.extrusion
        return abs(n[2] - 1) < 1e-9
    except Exception:
        return True


def _spline(e, sink, s):
    """SPLINE z DXF jako jedna dokładna krawędź B-sklejana; gdy dane są niepełne - krzywa przez punkty dopasowania lub spłaszczenie."""
    try:
        tool = e.construction_tool()
        poles = [_xy(v) * s for v in tool.control_points]
        weights = list(tool.weights()) if tool.is_rational else None
        sink.bspline(poles, list(tool.knots()), tool.degree, weights)
        return
    except CadError:
        raise
    except Exception:
        pass
    fit = [_xy(v) * s for v in getattr(e, 'fit_points', [])]
    if len(fit) >= 2:
        sink.spline(fit, bool(getattr(e, 'closed', False)))
    else:
        _flatten(e, sink, s)


def _flatten(e, sink, s):
    from ezdxf import path as ezpath
    p = ezpath.make_path(e)
    pts = [_xy(v) * s for v in p.flattening(0.02 / max(s, 1e-9))]
    if len(pts) > 200:
        pts = [pts[int(i)] for i in np.linspace(0, len(pts) - 1, 200)]
    if all(np.linalg.norm(np.cross(np.append(q - pts[0], 0), np.append(pts[-1] - pts[0], 0))) < 1e-9 for q in pts[1:-1]):
        sink.line(pts[0], pts[-1])
    else:
        sink.spline(pts)


def dxf_edges(path):
    if Path(path).stat().st_size > MAX_BYTES:
        raise CadError('Plik DXF jest zbyt duży.')
    import ezdxf
    try:
        doc = ezdxf.readfile(str(path))
    except Exception:
        try:
            from ezdxf import recover
            doc, _ = recover.readfile(str(path))
        except Exception as exc:
            raise CadError(f'Nie można odczytać pliku DXF: {exc}')
    s = _dxf_scale(doc)
    sink = _Sink()
    sink.bends = []
    for e in doc.modelspace():
        direction = _bend_layer(e)
        if direction is not None:          # linie gięcia (BEND_UP / BEND_DOWN z rozwinięcia blachy) nie należą do konturu
            tmp = _Sink()
            _dxf_entity(e, tmp, s)
            for edge in tmp.edges:
                a, b = edge.startPoint(), edge.endPoint()
                sink.bends.append(((a.x, a.y), (b.x, b.y), direction))
            continue
        _dxf_entity(e, sink, s)
    return sink


def _bend_layer(e):
    """'up' / 'down' dla elementu na warstwie linii gięcia (BEND_UP, BEND_DOWN, GIECIE_GORA, GIECIE_DOL), inaczej None."""
    try:
        layer = str(e.dxf.layer).upper()
    except Exception:
        return None
    if not (layer.startswith('BEND') or layer.startswith('GIECIE') or layer.startswith('GIĘCIE')):
        return None
    return 'down' if ('DOWN' in layer or 'DOL' in layer or 'DÓŁ' in layer) else 'up'


def _outline_faces(edges):
    """Płaskie ściany z zamkniętych konturów (zewnętrzne z otworami), do przycinania linii gięcia; [] gdy kontury nie są zamknięte."""
    try:
        wires = [w for w in cq.Wire.combine(edges, tol=1e-4) if w.IsClosed()]
    except Exception:
        return []
    faces = []
    for w in wires:
        try:
            faces.append((cq.Face.makeFromWires(w), w))
        except Exception:
            continue
    from .kernel import face_contains
    faces.sort(key=lambda fw: -fw[0].Area())
    probe = [_inside_point(fw[0]) for fw in faces]
    contains = lambda j, i: faces[j][0].Area() > faces[i][0].Area() and face_contains(faces[j][0], probe[i])
    depth = [sum(1 for j in range(i) if contains(j, i)) for i in range(len(faces))]
    out = []
    for i, (face, wire) in enumerate(faces):
        if depth[i] % 2:
            continue            # otwór w większym konturze
        holes = [faces[j][1] for j in range(i + 1, len(faces)) if depth[j] == depth[i] + 1 and contains(i, j)]
        try:
            out.append(cq.Face.makeFromWires(wire, holes))
        except Exception:
            out.append(face)
    return out


def _inside_point(face):
    """Punkt wewnątrz ściany (środek trójkąta siatki) - środek ciężkości pierścienia lub litery C leży poza nią."""
    try:
        vertices, triangles = face.tessellate(0.1, 0.5)
        if triangles:
            return tuple(np.mean([vertices[k].toTuple() for k in triangles[0]], axis=0))
    except Exception:
        pass
    return face.Center().toTuple()


def _pt_key(v, q=1e-4):
    return (round(v.x / q), round(v.y / q))


def _edge_key(edge):
    """Klucz krawędzi niezależny od kierunku: końce i punkt środkowy (zaokrąglone do 0,0001 mm)."""
    a, b, m = _pt_key(edge.startPoint()), _pt_key(edge.endPoint()), _pt_key(edge.positionAt(0.5))
    return (min(a, b), max(a, b), m)


def dedupe_edges(edges):
    """Usuwa krawędzie zdublowane (ten sam przebieg, także odwrócony) - bez zmiany kształtu pozostałych."""
    seen, out = set(), []
    for e in edges:
        try:
            key = _edge_key(e)
        except Exception:
            out.append(e)
            continue
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def clean_wires(wires):
    """Porządkuje obwody po imporcie, nie zmieniając ich kształtu (krzywe zostają dokładne, nic nie jest próbkowane):
    zamyka obwody z mikroszczelinami (do 0,05 mm i mniej niż 0,5% wymiaru), usuwa obwody zdublowane (z dokładnością 0,02 mm)
    (ten sam kontur narysowany kilka razy) i punkty zerowej wielkości."""
    out, seen = [], set()
    for w in wires:
        try:
            box = w.BoundingBox()
            diag = box.DiagonalLength
            if diag < 1e-4:
                continue
            if not w.IsClosed():
                a, b = w.startPoint(), w.endPoint()
                gap = (a - b).Length
                if 1e-7 < gap <= min(0.05, 0.005 * diag):
                    w = cq.Wire.assembleEdges([*w.Edges(), cq.Edge.makeLine(b, a)])
            c = w.Center()
            key = (round(w.Length() / 2e-2), round(box.xmin / 2e-2), round(box.ymin / 2e-2), round(box.xmax / 2e-2),
                   round(box.ymax / 2e-2), round(c.x / 2e-2), round(c.y / 2e-2), w.IsClosed())
        except Exception:
            out.append(w)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def load_flat_parts(path):
    """Plik SVG albo DXF → (płaski kształt konturu, linie gięcia [(a, b, 'up' | 'down')] przycięte do obrysu)."""
    ext = Path(path).suffix.lower()
    if ext == '.svg':
        sink = svg_edges(path)
    elif ext == '.dxf':
        sink = dxf_edges(path)
    else:
        raise CadError('Obsługiwane są pliki SVG i DXF.')
    sink.edges = dedupe_edges(sink.edges)
    shape = sink.shape()
    bends = []
    raw = getattr(sink, 'bends', [])
    if raw:
        from .sheetmetal import clip_line_to_faces
        faces = _outline_faces(sink.edges)
        for a, b, d in raw:
            if faces:
                for p, q in clip_line_to_faces((a[0], a[1], 0.0), (b[0], b[1], 0.0), faces):
                    bends.append((tuple(p[:2]), tuple(q[:2]), d))
            else:
                bends.append((a, b, d))
    return shape, bends


def load_flat(path):
    """Plik SVG albo DXF → płaski kształt (zbiór krawędzi w płaszczyźnie XY, mm) gotowy do rzutu z góry."""
    return load_flat_parts(path)[0]


def sketch_wires(path):
    """Plik SVG albo DXF → kontury szkicu (krawędzie połączone w obwody), w mm, w płaszczyźnie XY.
    Krzywe Béziera, łuki, przekształcenia i jednostki jak w rysunku technicznym; zamiast setek osobnych odcinków
    powstaje jeden obwód na kształt (szybsze wyświetlanie, obszary i wyciąganie)."""
    ext = Path(path).suffix.lower()
    if ext == '.svg':
        sink = svg_edges(path)
    elif ext == '.dxf':
        sink = dxf_edges(path)
    else:
        raise CadError('Obsługiwane są pliki SVG i DXF.')
    if not sink.edges:
        raise CadError('W pliku nie znaleziono linii, łuków ani krzywych.')
    marks = [*sink.marks, len(sink.edges)] if ext == '.svg' and sink.marks else [0, len(sink.edges)]
    if marks[0] != 0:
        marks = [0, *marks]
    wires = []
    for a, b in zip(marks, marks[1:]):          # SVG: osobno każdy kształt (stykające się kształty się nie zlewają)
        group = dedupe_edges(sink.edges[a:b])
        if not group:
            continue
        try:
            wires += list(cq.Wire.combine(group, tol=1e-4))
        except Exception:
            wires += [cq.Wire.assembleEdges([e]) for e in group]
    out = []
    for w in clean_wires(wires):
        try:
            if w.Length() > _TOL:
                out.append(w)
        except Exception:
            continue
    if not out:
        raise CadError('W pliku nie znaleziono linii, łuków ani krzywych.')
    out.sort(key=lambda w: (-w.BoundingBox().DiagonalLength))
    return out
