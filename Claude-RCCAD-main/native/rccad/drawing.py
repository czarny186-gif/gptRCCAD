"""Rysunek techniczny z bryły: rzuty (HLR OpenCascade), wymiary, rozmieszczenie na arkuszu i zapis DXF.
Moduł nie zależy od Qt - zwraca listę prymitywów (linie, napisy) we współrzędnych arkusza w mm (oś Y w górę), którą
rysuje okno rysunku (PDF / SVG / JPG) albo zapisuje eksport DXF."""
from __future__ import annotations
import datetime
import math
from dataclasses import dataclass, field
import cadquery as cq
import numpy as np

# nazwa -> (opis, kierunek do obserwatora, kierunek osi X obrazu); oś Y obrazu = normalna × X
VIEWS = {
    'front': ('Widok z przodu', (0, -1, 0), (1, 0, 0)),
    'back': ('Widok z tyłu', (0, 1, 0), (-1, 0, 0)),
    'left': ('Widok z lewej', (-1, 0, 0), (0, -1, 0)),
    'right': ('Widok z prawej', (1, 0, 0), (0, 1, 0)),
    'top': ('Widok z góry', (0, 0, 1), (1, 0, 0)),
    'bottom': ('Widok z dołu', (0, 0, -1), (1, 0, 0)),
    'iso': ('Widok izometryczny', (1, -1, 1), (1, 1, 0)),
}
SHEETS = {'A4': (297.0, 210.0), 'A3': (420.0, 297.0), 'A2': (594.0, 420.0)}
SCALES = (50, 20, 10, 5, 2, 1, .5, .2, .1, .05, .02, .01)
# położenie rzutów (kolumna, wiersz; wiersz rośnie w dół arkusza): metoda europejska (1) i amerykańska (3)
CELLS = {'eu': {'right': (-1, 0), 'front': (0, 0), 'left': (1, 0), 'back': (2, 0), 'top': (0, 1), 'bottom': (0, -1), 'iso': (1, 1)},
         'us': {'left': (-1, 0), 'front': (0, 0), 'right': (1, 0), 'back': (2, 0), 'top': (0, -1), 'bottom': (0, 1), 'iso': (1, -1)}}
PAD = 14.0          # miejsce na wymiary wokół rzutu (mm na arkuszu)
CAPTION = 2.0      # miejsce nad rzutem (podpisów widoków nie rysujemy)
GAP = 6.0
TITLE_H = 34.0      # miejsce na tabelkę rysunkową


@dataclass
class Poly:
    pts: list
    style: str = 'visible'      # visible | hidden | center | dim | frame | thin
    closed: bool = False
    fill: bool = False


@dataclass
class Label:
    x: float
    y: float
    text: str
    h: float = 3.5
    align: str = 'c'            # l | c | r (poziomo od punktu x, y)
    rot: float = 0.0
    style: str = 'text'
    font: str = 'Arial'
    bold: bool = False
    italic: bool = False


@dataclass
class Drawing:
    width: float
    height: float
    scale: float
    prims: list = field(default_factory=list)
    snaps: list = field(default_factory=list)       # punkty do przyciągania przy pomiarach
    views: dict = field(default_factory=dict)        # nazwa -> dict(origin, bbox)
    sheet: str = 'A4'
    name: str = ''
    features: list = field(default_factory=list)     # elementy, które można wymiarować ręcznie (współrzędne arkusza)

    @property
    def scale_text(self):
        return f'{self.scale:g}:1' if self.scale >= 1 else f'1:{1 / self.scale:g}'


def fmt(value):
    text = f'{float(value):.2f}'.rstrip('0').rstrip('.')
    return ('0' if text in ('-0', '') else text).replace('.', ',')


def _unit(v):
    v = np.array(v, float)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# rzuty
# ---------------------------------------------------------------------------
@dataclass
class ViewGeom:
    name: str
    visible: list          # łamane (N x 2) w mm bryły
    hidden: list
    circles: list          # dict(c=(x, y), r, full, mid=(x, y))
    bbox: tuple            # xmin, ymin, xmax, ymax widocznych krawędzi
    centers: list = field(default_factory=list)     # środki zamkniętych kształtów (wielokąty, fasolki, prostokąty): (x, y)
    bends: list = field(default_factory=list)       # linie gięcia rozwinięcia: (łamana N x 2, 'up' | 'down')


def _compound_edges(compound):
    if compound is None or compound.IsNull():
        return []
    return cq.Shape.cast(compound).Edges()


def _edge_points(edge):
    length = float(edge.Length())
    kind = edge.geomType()
    n = 2 if kind == 'LINE' else max(12, min(240, int(length * 1.5)))
    return np.array([edge.positionAt(t).toTuple()[:2] for t in np.linspace(0.0, 1.0, n)], float)


def hlr_edges(shape, normal, xdir):
    """(widoczne, ukryte) krawędzie rzutu jako łamane w układzie obrazu (X w prawo, Y w górę)."""
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    algo = HLRBRep_Algo()
    algo.Add(shape.wrapped)
    algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*[float(c) for c in _unit(normal)]), gp_Dir(*[float(c) for c in _unit(xdir)]))))
    algo.Update()
    algo.Hide()
    conv = HLRBRep_HLRToShape(algo)
    visible = [e for c in (conv.VCompound(), conv.Rg1LineVCompound(), conv.OutLineVCompound()) for e in _compound_edges(c)]
    hidden = [e for c in (conv.HCompound(), conv.OutLineHCompound()) for e in _compound_edges(c)]
    return [_edge_points(e) for e in visible if e.Length() > 1e-6], [_edge_points(e) for e in hidden if e.Length() > 1e-6]


def _circle_of(edge):
    """(środek, promień, normalna, pełny okrąg, punkt środkowy łuku) krawędzi kołowej albo None."""
    if edge.geomType() != 'CIRCLE':
        return None
    p0, p1, p2 = (np.array(edge.positionAt(t).toTuple(), float) for t in (0.0, 1 / 3, 2 / 3))
    a, b = p1 - p0, p2 - p0
    n = np.cross(a, b)
    nn = float(np.linalg.norm(n))
    if nn < 1e-9:
        return None
    n /= nn
    cross = np.cross(a, b)
    d = 2 * nn ** 2
    center = p0 + (float(b @ b) * np.cross(cross, a) + float(a @ a) * np.cross(b, cross)) / d
    radius = float(np.linalg.norm(p0 - center))
    full = bool(np.linalg.norm(np.array(edge.positionAt(0.0).toTuple()) - np.array(edge.positionAt(1.0).toTuple())) < 1e-6)
    mid = np.array(edge.positionAt(0.5).toTuple(), float)
    return center, radius, n, full, mid


def _near_segments(a, b, q):
    """Odległość punktu q od najbliższego z odcinków a[i]-b[i]."""
    q = np.asarray(q, float)
    v = b - a
    ll = np.maximum((v * v).sum(axis=1), 1e-12)
    t = np.clip(((q - a) * v).sum(axis=1) / ll, 0.0, 1.0)
    return float(np.linalg.norm(a + v * t[:, None] - q, axis=1).min())


def figure_centers(polylines, skip=()):
    """Środki figur: łamane, które łączą się końcami w zamknięty kontur (każdy węzeł ma dokładnie dwie krawędzie). Zwraca środek ciężkości pola."""
    key = lambda p: (round(float(p[0]), 2), round(float(p[1]), 2))
    edges, seen = [], set()
    for pts in polylines:
        a, b = key(pts[0]), key(pts[-1])
        ident = (min(a, b), max(a, b), round(float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1))), 1))
        if a == b or ident in seen:
            continue
        seen.add(ident)
        edges.append((a, b, pts))
    at = {}
    for i, (a, b, _) in enumerate(edges):
        at.setdefault(a, []).append(i)
        at.setdefault(b, []).append(i)
    done, out = set(), []
    for start in range(len(edges)):
        if start in done:
            continue
        comp, stack = set(), [start]
        while stack:
            i = stack.pop()
            if i in comp:
                continue
            comp.add(i)
            for node in edges[i][:2]:
                stack.extend(at[node])
        done |= comp
        if len(comp) < 2 or any(len(at[n]) != 2 for i in comp for n in edges[i][:2]):
            continue
        ring, node, used = [], edges[start][0], set()
        while len(used) < len(comp):
            nxt = next((i for i in at[node] if i in comp and i not in used), None)
            if nxt is None:
                break
            used.add(nxt)
            a, b, pts = edges[nxt]
            seg = pts if a == node else pts[::-1]
            ring.extend(seg[:-1])
            node = b if a == node else a
        if len(used) < len(comp) or len(ring) < 3:
            continue
        r = np.array(ring, float)
        x, y = r[:, 0], r[:, 1]
        x2, y2 = np.roll(x, -1), np.roll(y, -1)
        cross = x * y2 - x2 * y
        area = float(cross.sum()) / 2
        if abs(area) < 1e-6:
            continue
        c = (float(((x + x2) * cross).sum() / (6 * area)), float(((y + y2) * cross).sum() / (6 * area)))
        if all(math.hypot(c[0] - q[0], c[1] - q[1]) > 1e-3 for q in skip):
            out.append(c)
    return out


def project_view(shape, name):
    label, normal, xdir = VIEWS[name]
    n, x = _unit(normal), _unit(xdir)
    y = np.cross(n, x)
    visible, hidden = hlr_edges(shape, n, x)
    pts = np.vstack(visible) if visible else (np.vstack(hidden) if hidden else np.zeros((1, 2)))
    bbox = (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))
    seg_a = np.vstack([p[:-1] for p in visible]) if visible else np.zeros((0, 2))
    seg_b = np.vstack([p[1:] for p in visible]) if visible else np.zeros((0, 2))
    circles, seen = [], set()
    for edge in shape.Edges():
        info = _circle_of(edge)
        if info is None:
            continue
        center, radius, cn, full, mid = info
        if abs(float(cn @ n)) < 0.9999 or radius < 1e-6:
            continue
        c2 = (float(center @ x), float(center @ y))
        m2 = (float(mid @ x), float(mid @ y))
        key = (round(c2[0], 2), round(c2[1], 2), round(radius, 2), full)
        if key in seen:
            continue
        # tylko okręgi i łuki widoczne w tym rzucie: punkty próbne leżą na widocznych krawędziach (odległość od odcinków, nie od punktów)
        if len(seg_a):
            tol = max(0.2, 0.02 * radius)
            if full:
                probe = [(c2[0] + radius * np.cos(t), c2[1] + radius * np.sin(t)) for t in (0.3, 2.4, 4.5)]
            else:
                probe = []
                for t in (0.15, 0.5, 0.85):
                    q = np.array(edge.positionAt(t).toTuple(), float)
                    probe.append((float(q @ x), float(q @ y)))
            if not all(_near_segments(seg_a, seg_b, q) <= tol for q in probe):
                continue
        seen.add(key)
        circles.append(dict(c=c2, r=radius, full=full, mid=m2))
    return ViewGeom(name, visible, hidden, circles, bbox, figure_centers(visible, [c['c'] for c in circles]))


class DrawingSource:
    """Bryła z pamięcią rzutów (liczenie HLR jest najdroższe, więc zmiana opcji nie powtarza go).
    bends: linie gięcia rozłożonej blachy w płaszczyźnie XY - [(a, b, 'up' | 'down')] - rysowane w rzutach z góry i z dołu."""

    def __init__(self, shape, name='Bryła', bends=None, sheet=None, iso_shape=None):
        """sheet: opis blachy do rysunku do gięcia - dict(t, k); włącza wymiary linii gięcia.
        iso_shape: bryła do widoku izometrycznego (rozłożona blacha pokazuje tam blachę zgiętą)."""
        self.shape, self.name = shape, name
        self.iso_shape = iso_shape
        self.bends = [(tuple(map(float, b[0][:2])), tuple(map(float, b[1][:2])), 'down' if str(b[2]).lower() == 'down' else 'up') for b in (bends or ())]
        self.bend_info = [dict(b[3]) if len(b) > 3 and b[3] else {} for b in (bends or ())]
        self.sheet = sheet
        self._cache = {}

    def view(self, name):
        if name not in self._cache:
            g = project_view(self.iso_shape if name == 'iso' and self.iso_shape is not None else self.shape, name)
            if self.bends and name in ('top', 'bottom'):
                _, normal, xdir = VIEWS[name]
                n, x = _unit(normal), _unit(xdir)
                y = np.cross(n, x)
                flip = name == 'bottom'          # od spodu gięcie w górę wygląda jak gięcie w dół
                for (a, b, d), info in zip(self.bends, self.bend_info):
                    pts = np.array([[a[0] * x[0] + a[1] * x[1], a[0] * y[0] + a[1] * y[1]], [b[0] * x[0] + b[1] * x[1], b[0] * y[0] + b[1] * y[1]]], float)
                    g.bends.append((pts, ({'up': 'down', 'down': 'up'}[d] if flip else d), info))
            self._cache[name] = g
        return self._cache[name]


# ---------------------------------------------------------------------------
# prymitywy rysunku
# ---------------------------------------------------------------------------
def _arrow(tip, direction, size=3.0):
    d = _unit(direction)
    base = np.array(tip) - d * size
    perp = np.array([-d[1], d[0]])
    return Poly([tuple(tip), tuple(base + perp * size * .3), tuple(base - perp * size * .3)], 'dim', True, True)


def _dim_horizontal(prims, x0, x1, y_ref, y_line, text):
    for x in (x0, x1):
        prims.append(Poly([(x, y_ref - 1.0), (x, y_line - 2.0)], 'dim'))
    prims.append(Poly([(x0, y_line), (x1, y_line)], 'dim'))
    prims.append(_arrow((x0, y_line), (-1, 0)))
    prims.append(_arrow((x1, y_line), (1, 0)))
    prims.append(Label((x0 + x1) / 2, y_line + 1.2, text, 3.5, 'c'))


def _dim_vertical(prims, y0, y1, x_ref, x_line, text):
    for y in (y0, y1):
        prims.append(Poly([(x_ref + 1.0, y), (x_line + 2.0, y)], 'dim'))
    prims.append(Poly([(x_line, y0), (x_line, y1)], 'dim'))
    prims.append(_arrow((x_line, y0), (0, -1)))
    prims.append(_arrow((x_line, y1), (0, 1)))
    prims.append(Label(x_line - 1.2, (y0 + y1) / 2, text, 3.5, 'c', 90.0))


def _dim_circle(prims, snaps, c, rp, r, full, mid, angle=45.0):
    """Wymiar Ø (pełny okrąg) albo R (łuk): linia odniesienia z grotem na obrysie i napis."""
    if full:
        u = np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle))])
        tip = np.array(c) + u * rp
        text = 'Ø' + fmt(2 * r)
    else:
        u = np.array(mid) - np.array(c)
        u = u / max(float(np.linalg.norm(u)), 1e-9)
        tip = np.array(mid)
        text = 'R' + fmt(r)
    end = tip + u * 8.0
    side = 1.0 if u[0] >= 0 else -1.0
    tail = end + np.array([side * 6.0, 0.0])
    prims.append(Poly([tuple(tip), tuple(end), tuple(tail)], 'dim'))
    prims.append(_arrow(tip, -u))
    prims.append(Label(tail[0] + side * 0.8, tail[1] - 1.2, text, 3.5, 'l' if side > 0 else 'r'))


def _centerlines(prims, c, rp):
    e = rp + 2.5
    prims.append(Poly([(c[0] - e, c[1]), (c[0] + e, c[1])], 'center'))
    prims.append(Poly([(c[0], c[1] - e), (c[0], c[1] + e)], 'center'))


def _bend_dims(prims, g, place, x0, y0, x1, y1):
    """Rysunek do gięcia: łańcuch wymiarów krawędź - linia gięcia - linia gięcia - ... - krawędź, osobno dla linii poziomych
    (wymiary po lewej) i pionowych (wymiary nad rzutem), oraz opis każdej linii: kierunek, kąt i promień gięcia."""
    xs, ys = set(), set()
    for pts, direction, info in g.bends:
        (ax, ay), (bx, by) = pts[0], pts[-1]
        tol = 1e-5 * max(1.0, float(np.hypot(bx - ax, by - ay)))
        if abs(ay - by) < tol:
            ys.add(round(float(ay + by) / 2, 4))
        elif abs(ax - bx) < tol:
            xs.add(round(float(ax + bx) / 2, 4))
        # opis linii gięcia: kierunek, kąt, promień (wzdłuż linii, tuż obok niej)
        text = ('GÓRA' if direction == 'up' else 'DÓŁ') + (f" {fmt(info['angle'])}°" if info.get('angle') is not None else '') + \
               (f" R{fmt(info['r'])}" if info.get('r') is not None else '')
        A, B = np.array(place((ax, ay)), float), np.array(place((bx, by)), float)
        t = B - A
        length = float(np.linalg.norm(t))
        if length < 1e-6:
            continue
        t /= length
        ang = math.degrees(math.atan2(t[1], t[0]))
        if ang > 90.0 + 1e-6 or ang <= -90.0 + 1e-6:
            ang += 180.0 if ang <= 0 else -180.0
        r = math.radians(ang)
        pos = (A + B) / 2 + np.array([-math.sin(r), math.cos(r)]) * 1.0
        prims.append(Label(float(pos[0]), float(pos[1]), text, 2.5, 'c', ang))
    def chain_of(values, lo, hi):
        """Krawędź zewnętrzna - kolejne linie gięcia - krawędź zewnętrzna (bez powtórzeń i odcinków zerowych)."""
        out = [lo]
        for v in sorted(values):
            if v - out[-1] > 1e-4 and hi - v > 1e-4:
                out.append(v)
        return out + [hi]

    def place_label(label, a, b, index, count, vertical):
        """Napis odcinka łańcucha: gdy nie mieści się między grotami, skrajny wychodzi za krawędź zewnętrzną,
        a środkowy odsuwa się od linii wymiarowej (naprzemiennie), więc sąsiednie wartości się nie nakładają."""
        width = 2.0 * len(label.text) + 1.5
        if abs(b - a) >= width + 2.0:
            return False
        lo, hi = min(a, b), max(a, b)
        if index == 0 or index == count - 1:
            target = lo - width / 2 - 2.5 if index == 0 else hi + width / 2 + 2.5
            if vertical:
                label.y = target
            else:
                label.x = target
            return False
        return True

    for values, lo_edge, hi_edge, vertical in ((ys, g.bbox[1], g.bbox[3], True), (xs, g.bbox[0], g.bbox[2], False)):
        if not values:
            continue
        chain = chain_of(values, lo_edge, hi_edge)
        count, alternate = len(chain) - 1, False
        for index, (p, q) in enumerate(zip(chain, chain[1:])):
            if vertical:
                a, b = place((0, p))[1], place((0, q))[1]
                _dim_vertical(prims, a, b, x0, x0 - 10.0, fmt(q - p))
            else:
                a, b = place((p, 0))[0], place((q, 0))[0]
                _dim_horizontal(prims, a, b, y1, y1 + 10.0, fmt(q - p))
            if place_label(prims[-1], a, b, index, count, vertical):
                alternate = not alternate
                if alternate:
                    if vertical:
                        prims[-1].x -= 3.8
                    else:
                        prims[-1].y += 3.8
            else:
                alternate = False


def _sheet_notes(d, source, names):
    """Opis blachy w lewym dolnym rogu arkusza: grubość, promienie, współczynnik K, rozmiar rozwinięcia i znaczenie linii."""
    sheet = source.sheet
    radii = sorted({round(float(i['r']), 4) for i in source.bend_info if i.get('r') is not None})
    lines = []
    if sheet.get('t') is not None:
        lines.append(f"Grubość blachy t = {fmt(sheet['t'])} mm")
    if radii:
        lines.append('Promień gięcia (wewn.) R = ' + ', '.join(fmt(r) for r in radii) + ' mm')
    if sheet.get('k') is not None:
        lines.append(f"Współczynnik K = {fmt(sheet['k'])}")
    for v in ('top', 'bottom'):
        if v in names:
            g = source.view(v)
            lines.append(f"Rozwinięcie {fmt(g.bbox[2] - g.bbox[0])} × {fmt(g.bbox[3] - g.bbox[1])} mm, gięć: {len(source.bends)}")
            break
    lines.append('Gięcie w górę - linia ciągła, w dół - przerywana')
    y = 10 + 3.0 + 4.6 * (len(lines) - 1)
    for text in lines:
        d.prims.append(Label(24.0, y, text, 3.0, 'l'))
        y -= 4.6


def _title_block(d, version):
    W, H = d.width, d.height
    x1, y0 = W - 10, 10
    x0, y1 = x1 - 150, y0 + 30
    prims = d.prims
    prims.append(Poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], 'frame', True))
    prims.append(Poly([(x0, y0 + 10), (x1, y0 + 10)], 'frame'))
    prims.append(Poly([(x0 + 100, y0 + 10), (x0 + 100, y1)], 'frame'))
    for dx in (50, 100):
        prims.append(Poly([(x0 + dx, y0), (x0 + dx, y0 + 10)], 'frame'))
    prims.append(Label(x0 + 3, y0 + 14.5, d.name, 6.0, 'l'))
    prims.append(Label(x0 + 103, y0 + 21.5, 'RCCAD', 4.5, 'l'))
    prims.append(Label(x0 + 103, y0 + 14.2, version, 3.0, 'l'))
    prims.append(Label(x0 + 3, y0 + 3.2, 'Skala ' + d.scale_text, 3.5, 'l'))
    prims.append(Label(x0 + 53, y0 + 3.2, 'Format ' + d.sheet, 3.5, 'l'))
    prims.append(Label(x0 + 103, y0 + 3.2, datetime.date.today().strftime('%d.%m.%Y'), 3.5, 'l'))


def sheet_size(sheet, landscape=True):
    w, h = SHEETS[sheet]
    return (w, h) if landscape else (h, w)


def _extent(source, names, scale, dims, cells, extra=0.0):
    cols, rows = {}, {}
    for v in names:
        g = source.view(v)
        w, h = g.bbox[2] - g.bbox[0], g.bbox[3] - g.bbox[1]
        pad = 2 * PAD + extra if (dims and v != 'iso') else 12.0
        c, r = cells[v]
        cols[c] = max(cols.get(c, 0.0), w * scale + pad)
        rows[r] = max(rows.get(r, 0.0), h * scale + pad + CAPTION)
    return cols, rows


def build_drawing(source, views=('front', 'top', 'right'), sheet='A4', landscape=True, projection='eu', scale=None,
                  overall=True, circles=True, centers=True, hidden=False, version='RCCAD', details=False, bends=True) -> Drawing:
    """bends: wymiary linii gięcia (łańcuch od zewnętrznych krawędzi blachy przez wszystkie linie gięcia) i ich opisy."""
    names = [v for v in VIEWS if v in views]
    if not names:
        raise ValueError('Wybierz co najmniej jeden rzut.')
    W, H = sheet_size(sheet, landscape)
    cells = CELLS[projection]
    dims = overall or circles or details
    extra = 22.0 if details else 0.0
    avail_w, avail_h = W - 20 - 10 - 4, H - 20 - TITLE_H
    chosen = None
    candidates = [float(scale)] if scale else list(SCALES)
    for s in candidates:
        cols, rows = _extent(source, names, s, dims, cells, extra)
        if sum(cols.values()) + GAP * (len(cols) - 1) <= avail_w and sum(rows.values()) + GAP * (len(rows) - 1) <= avail_h:
            chosen = s
            break
    if chosen is None:
        chosen = candidates[-1]
    s = chosen
    cols, rows = _extent(source, names, s, dims, cells, extra)
    col_keys, row_keys = sorted(cols), sorted(rows)
    total_w = sum(cols.values()) + GAP * (len(cols) - 1)
    total_h = sum(rows.values()) + GAP * (len(rows) - 1)
    left = 20 + 2 + max(0.0, (avail_w - total_w) / 2)
    top = 10 + 2 + max(0.0, (avail_h - total_h) / 2)
    col_x, x = {}, left
    for c in col_keys:
        col_x[c] = x
        x += cols[c] + GAP
    row_y, y = {}, top
    for r in row_keys:
        row_y[r] = y
        y += rows[r] + GAP
    d = Drawing(W, H, s, sheet=sheet, name=source.name)
    prims = d.prims
    prims.append(Poly([(20, 10), (W - 10, 10), (W - 10, H - 10), (20, H - 10)], 'frame', True))
    for v in names:
        g = source.view(v)
        c, r = cells[v]
        cx = col_x[c] + cols[c] / 2
        cy_down = row_y[r] + CAPTION + (rows[r] - CAPTION) / 2
        bx, by = (g.bbox[0] + g.bbox[2]) / 2, (g.bbox[1] + g.bbox[3]) / 2
        place = lambda p, cx=cx, cy_down=cy_down, bx=bx, by=by: (cx + (p[0] - bx) * s, H - (cy_down - (p[1] - by) * s))
        for pts in g.visible:
            line = [place(p) for p in pts]
            prims.append(Poly(line, 'visible'))
            d.snaps += [line[0], line[-1]]
        for pts, direction, _info in g.bends:       # linie gięcia: w górę ciągła, w dół przerywana; można je wymiarować i mierzyć jak krawędzie
            line = [place(p) for p in pts]
            prims.append(Poly(line, 'bend_up' if direction == 'up' else 'bend_down'))
            d.snaps += [line[0], line[-1]]
            if v != 'iso' and len(pts) == 2 and float(np.linalg.norm(pts[1] - pts[0])) > 1e-6:
                d.features.append(dict(view=v, kind='line', bend=direction, name='linia gięcia',
                                       mdl=(tuple(map(float, pts[0])), tuple(map(float, pts[1]))), a=line[0], b=line[1]))
        if hidden:
            for pts in g.hidden:
                line = [place(p) for p in pts]
                prims.append(Poly(line, 'hidden'))
                d.snaps += [line[0], line[-1]]
                if v != 'iso' and len(pts) == 2 and float(np.linalg.norm(pts[1] - pts[0])) > 1e-6:      # krawędzie niewidoczne też można mierzyć (np. głębokość wgłębienia)
                    d.features.append(dict(view=v, kind='line', hidden=True, mdl=(tuple(map(float, pts[0])), tuple(map(float, pts[1]))), a=line[0], b=line[1]))
        x0, y0 = place((g.bbox[0], g.bbox[1]))
        x1, y1 = place((g.bbox[2], g.bbox[3]))
        d.views[v] = dict(origin=(cx, H - cy_down), bbox=(x0, y0, x1, y1), map=(cx, H - cy_down, bx, by, s))
        if v != 'iso':
            for pts in g.visible:
                if len(pts) == 2 and float(np.linalg.norm(pts[1] - pts[0])) > 1e-6:
                    d.features.append(dict(view=v, kind='line', mdl=(tuple(map(float, pts[0])), tuple(map(float, pts[1]))), a=place(pts[0]), b=place(pts[1])))
            for c in g.centers:
                d.features.append(dict(view=v, kind='fcenter', mdl=c, c=place(c)))
            for circ in g.circles:
                d.features.append(dict(view=v, kind='circle', mdl=(circ['c'], circ['r'], circ['full'], circ['mid']), c=place(circ['c']),
                                       r=circ['r'] * s, full=circ['full'], mid=place(circ['mid'])))
        if v == 'iso':
            continue
        if centers or circles or details:
            for circ in g.circles:
                cp, rp = place(circ['c']), circ['r'] * s
                d.snaps.append(cp)
                if centers and circ['full']:
                    _centerlines(prims, cp, rp)
        if circles or details:
            used = set()
            for k, circ in enumerate(g.circles):
                rp = circ['r'] * s
                if rp < 0.4:
                    continue
                key = (round(circ['r'], 2), circ['full'])
                if not circ['full'] and key in used:
                    continue
                used.add(key)
                _dim_circle(prims, d.snaps, place(circ['c']), rp, circ['r'], circ['full'], place(circ['mid']), 45.0 + 30.0 * (k % 3))
        if bends and g.bends:
            _bend_dims(prims, g, place, x0, y0, x1, y1)
        if overall and (g.bbox[2] - g.bbox[0]) > 1e-6:
            _dim_horizontal(prims, x0, x1, y0, y0 - 10.0, fmt(g.bbox[2] - g.bbox[0]))
        if overall and (g.bbox[3] - g.bbox[1]) > 1e-6:
            _dim_vertical(prims, y0, y1, x1, x1 + 10.0, fmt(g.bbox[3] - g.bbox[1]))
    if details:
        for m in contour_dims(d, {v: source.view(v) for v in names}):
            prims += manual_prims(d, m)
    if getattr(source, 'sheet', None):
        _sheet_notes(d, source, names)
    _title_block(d, version)
    return d


# ---------------------------------------------------------------------------
# wymiary dodawane ręcznie (i wymiary konturu z opcji automatycznych)
# ---------------------------------------------------------------------------
def place_in(d, view, p):
    cx, cy, bx, by, s = d.views[view]['map']
    return (cx + (p[0] - bx) * s, cy + (p[1] - by) * s)


def model_of(d, view, p):
    """Odwrotność place_in: punkt arkusza -> współrzędne rzutu w mm bryły."""
    cx, cy, bx, by, s = d.views[view]['map']
    return (bx + (p[0] - cx) / s, by + (p[1] - cy) / s)


def view_at(d, p, pad=3.0):
    best, size = None, 1e18
    for name, v in d.views.items():
        x0, y0, x1, y1 = v['bbox']
        if x0 - pad <= p[0] <= x1 + pad and y0 - pad <= p[1] <= y1 + pad and name != 'iso' and (x1 - x0) * (y1 - y0) < size:
            best, size = name, (x1 - x0) * (y1 - y0)
    return best


def foot_on_line(pt, line):
    a, b = np.array(line[0], float), np.array(line[1], float)
    v = b - a
    t = float((np.array(pt, float) - a) @ v) / max(float(v @ v), 1e-12)
    f = a + v * t
    return (float(f[0]), float(f[1]))


def dist_points(r1, r2):
    """Dwa punkty (mm bryły), między którymi mierzymy: punkt-punkt albo punkt-krawędź (rzut prostopadły na krawędź)."""
    line = None
    if r2.get('kind') == 'edge' and r2.get('line'):
        p, line = r1['pt'], r2['line']
    elif r1.get('kind') == 'edge' and r1.get('line'):
        p, line = r2['pt'], r1['line']
    else:
        return tuple(r1['pt']), tuple(r2['pt']), False
    q = foot_on_line(p, line)
    slanted = abs(line[1][0] - line[0][0]) > 1e-6 and abs(line[1][1] - line[0][1]) > 1e-6
    return tuple(p), q, slanted


def resolve_feature(d, m):
    """Współrzędne arkusza elementu wymiarowanego (liczone z modelu, więc wymiar przeżywa zmianę skali i układu)."""
    if m['view'] not in d.views:
        return None
    if m['kind'] in ('line', 'dist'):
        a, b = m['mdl']
        return dict(a=place_in(d, m['view'], a), b=place_in(d, m['view'], b))
    c, r, full, mid = m['mdl']
    return dict(c=place_in(d, m['view'], c), r=r * d.views[m['view']]['map'][4], full=full, mid=place_in(d, m['view'], mid), model_r=r)


def anchor_of(d, m):
    f = resolve_feature(d, m)
    if m['kind'] == 'circle':
        return f['c']
    return ((f['a'][0] + f['b'][0]) / 2, (f['a'][1] + f['b'][1]) / 2)


def default_offset(d, m, f=None, extra=0.0):
    """Położenie wymiaru tuż obok elementu: względem środka okręgu albo środka odcinka (mm arkusza)."""
    f = f or resolve_feature(d, m)
    if m['kind'] == 'circle':
        return ((f['r'] + 9.0 + extra) * 0.7071, (f['r'] + 9.0 + extra) * 0.7071)
    ax, ay = f['a']; bx, by = f['b']
    length = math.hypot(bx - ax, by - ay) or 1.0
    n = (-(by - ay) / length, (bx - ax) / length)
    vb = d.views[m['view']]['bbox']
    mx, my = (ax + bx) / 2, (ay + by) / 2
    away = (mx - (vb[0] + vb[2]) / 2) * n[0] + (my - (vb[1] + vb[3]) / 2) * n[1]
    if away < 0 or (abs(away) < 1e-6 and (n[1] < 0 or (n[1] == 0 and n[0] > 0))):
        n = (-n[0], -n[1])
    return (n[0] * (10.0 + extra), n[1] * (10.0 + extra))


def _dim_generic(a, b, A, B, text):
    """Wymiar między punktami a, b; linia wymiarowa A-B, pomocnicze od a do A i od b do B, napis czytelny od dołu / od prawej."""
    a, b, A, B = (np.array(x, float) for x in (a, b, A, B))
    length = float(np.linalg.norm(B - A))
    if length < 1e-6:
        return []
    t = (B - A) / length
    out = []
    for p, P in ((a, A), (b, B)):
        e = P - p
        le = float(np.linalg.norm(e))
        if le > 1e-6:
            e = e / le
            out.append(Poly([tuple(p + e * 1.0), tuple(P + e * 2.0)], 'dim'))
    out.append(Poly([tuple(A), tuple(B)], 'dim'))
    out.append(_arrow(A, -t))
    out.append(_arrow(B, t))
    ang = math.degrees(math.atan2(t[1], t[0]))
    if ang > 90.0 + 1e-6 or ang <= -90.0 + 1e-6:
        ang += 180.0 if ang <= 0 else -180.0
    r = math.radians(ang)
    pos = (A + B) / 2 + np.array([-math.sin(r), math.cos(r)]) * 1.4
    out.append(Label(float(pos[0]), float(pos[1]), text, 3.5, 'c', ang))
    return out


def dist_mode(d, m, f=None):
    """'h' / 'v' / 'a' (poziomy, pionowy, równoległy): jak w programach CAD wynika z położenia wymiaru względem mierzonych punktów."""
    f = f or resolve_feature(d, m)
    P, Q = f['a'], f['b']
    dx, dy = Q[0] - P[0], Q[1] - P[1]
    if m.get('aligned'):
        return 'a'
    if abs(dx) < 1e-4:
        return 'v'
    if abs(dy) < 1e-4:
        return 'h'
    mid = ((P[0] + Q[0]) / 2, (P[1] + Q[1]) / 2)
    pos = (mid[0] + m['off'][0], mid[1] + m['off'][1])
    inx = min(P[0], Q[0]) <= pos[0] <= max(P[0], Q[0])
    iny = min(P[1], Q[1]) <= pos[1] <= max(P[1], Q[1])
    return 'h' if inx and not iny else ('v' if iny and not inx else 'a')


def text_pos(d, m):
    """Punkt zaczepienia (lewy dolny róg pierwszej linii) tekstu na arkuszu."""
    if m.get('view') is not None:
        return place_in(d, m['view'], m['mdl'])
    return tuple(m['mdl'])


def leader_target(d, m):
    t = m.get('leader')
    if not t:
        return None
    if t.get('view') is not None:
        return place_in(d, t['view'], t['mdl']) if t['view'] in d.views else None
    return tuple(t['mdl'])


def text_lines(m):
    return str(m['text']).split('\n')


def text_box(d, m):
    """Ramka tekstu na arkuszu (x0, y0, x1, y1) w mm - do zaznaczania, przesuwania i zaczepiania strzałki."""
    if m.get('view') is not None and m['view'] not in d.views:
        return None
    x, y = text_pos(d, m)
    h = float(m.get('h', 3.5))
    lines = text_lines(m)
    width = max(len(line) for line in lines) * h * (0.62 if m.get('bold') else 0.56)
    return (x - 0.8, y - (len(lines) - 1) * h * 1.3 - 0.35 * h, x + width + 0.8, y + 0.95 * h)


def manual_prims(d, m):
    """Prymitywy jednego wymiaru m = dict(view, kind, mdl, off): 'circle' (Ø / R), 'line' (długość krawędzi), 'dist' (odległość dwóch punktów)."""
    if m['kind'] == 'text':
        box = text_box(d, m)
        if box is None:
            return []
        x, y = text_pos(d, m)
        out = [Label(x, y, m['text'], m.get('h', 3.5), 'l', 0.0, 'text', m.get('font', 'Arial'), bool(m.get('bold')), bool(m.get('italic')))]
        target = leader_target(d, m)
        if target is not None:
            x0, y0, x1, y1 = box
            starts = [((x0 + x1) / 2, y1), ((x0 + x1) / 2, y0), (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
            start = min(starts, key=lambda q: math.hypot(q[0] - target[0], q[1] - target[1]))
            inside = x0 <= target[0] <= x1 and y0 <= target[1] <= y1
            if not inside and math.hypot(start[0] - target[0], start[1] - target[1]) > 1.0:
                out.append(Poly([start, target], 'dim'))
                out.append(_arrow(target, (target[0] - start[0], target[1] - start[1])))
        return out
    f = resolve_feature(d, m)
    if f is None:
        return []
    out = []
    if m['kind'] == 'circle':
        c, rp = f['c'], f['r']
        off = np.array(m['off'], float)
        u = off / max(float(np.linalg.norm(off)), 1e-9)
        tip = np.array(c) + u * rp if f['full'] else np.array(f['mid'])
        end = np.array(c) + off
        side = 1.0 if u[0] >= 0 else -1.0
        tail = end + np.array([side * 6.0, 0.0])
        text = ('Ø' + fmt(2 * m['mdl'][1])) if f['full'] else ('R' + fmt(m['mdl'][1]))
        out.append(Poly([tuple(tip), tuple(end), tuple(tail)], 'dim'))
        out.append(_arrow(tip, -u))
        out.append(Label(tail[0] + side * 0.8, tail[1] - 1.2, text, 3.5, 'l' if side > 0 else 'r'))
        return out
    a, b = np.array(f['a']), np.array(f['b'])
    mid = (a + b) / 2
    pos = mid + np.array(m['off'], float)
    if m['kind'] == 'dist':
        mode = dist_mode(d, m, f)
        if mode == 'h':
            A, B, value = (a[0], pos[1]), (b[0], pos[1]), abs(b[0] - a[0])
        elif mode == 'v':
            A, B, value = (pos[0], a[1]), (pos[0], b[1]), abs(b[1] - a[1])
        else:
            length = float(np.linalg.norm(b - a))
            if length < 1e-9:
                return []
            n = np.array([-(b[1] - a[1]), b[0] - a[0]]) / length
            dist = float(np.array(m['off'], float) @ n)
            dist = (2.5 if dist >= 0 else -2.5) if abs(dist) < 2.5 else dist
            A, B, value = a + n * dist, b + n * dist, length
        return _dim_generic(a, b, A, B, ('R' if m.get('radial') and mode == 'a' else '') + fmt(value / d.scale))
    length = float(np.linalg.norm(b - a))
    if length < 1e-9:
        return []
    n = np.array([-(b[1] - a[1]), b[0] - a[0]]) / length
    dist = float(np.array(m['off'], float) @ n)
    if abs(dist) < 2.5:
        dist = 2.5 if dist >= 0 else -2.5
    return _dim_generic(a, b, a + n * dist, b + n * dist, fmt(length / d.scale))


def compose(d, manual):
    """Kopia rysunku z dołożonymi wymiarami ręcznymi (do ekranu i do eksportu)."""
    import dataclasses
    prims = list(d.prims)
    for m in manual:
        prims += manual_prims(d, m)
    return dataclasses.replace(d, prims=prims)


def contour_dims(d, g_by_view):
    """Wymiary wszystkich elementów konturu: boki wielokątów, proste krawędzie fasolek i wycięć oraz położenie otworów od krawędzi rzutu."""
    out = []
    for v, g in g_by_view.items():
        if v == 'iso':
            continue
        seen, sides = set(), {}
        bw, bh = g.bbox[2] - g.bbox[0], g.bbox[3] - g.bbox[1]
        for f in [x for x in d.features if x['view'] == v and x['kind'] == 'line' and not x.get('hidden') and not x.get('bend')]:      # wymiary konturu (linie gięcia mają własne)
            (ax, ay), (bx, by) = f['mdl']
            length = math.hypot(bx - ax, by - ay)
            if length * d.scale < 2.0 or abs(length - bw) < 0.01 or abs(length - bh) < 0.01:
                continue
            horiz, vert = abs(ay - by) < 1e-6, abs(ax - bx) < 1e-6
            key = (round(length, 2), 'h' if horiz else 'v' if vert else round(math.atan2(by - ay, bx - ax) % math.pi, 2))
            if key in seen or len(seen) >= 60:
                continue
            seen.add(key)
            m = dict(view=v, kind='line', mdl=f['mdl'], off=(0, 0))
            fa = resolve_feature(d, m)
            n0 = default_offset(d, m, fa)
            side = (round(n0[0] / 10.0), round(n0[1] / 10.0))
            k = sides.get(side, 0)
            sides[side] = k + 1
            m['off'] = default_offset(d, m, fa, extra=6.0 * (k % 5))
            out.append(m)
        arcs = [x for x in d.features if x['view'] == v and x['kind'] == 'circle' and not x['full']]
        lens = set()
        for i, f1 in enumerate(arcs):
            for f2 in arcs[i + 1:]:
                (c1, r1, _, m1), (c2, r2, _, m2) = f1['mdl'], f2['mdl']
                if abs(r1 - r2) > 1e-3 or math.hypot(c1[0] - c2[0], c1[1] - c2[1]) < 1e-3:
                    continue
                u1, u2 = (m1[0] - c1[0], m1[1] - c1[1]), (m2[0] - c2[0], m2[1] - c2[1])
                if u1[0] * u2[0] + u1[1] * u2[1] >= 0:          # końce fasolki odwrócone do siebie plecami
                    continue
                total = math.hypot(m1[0] - m2[0], m1[1] - m2[1])
                if total * d.scale < 3.0 or round(total, 2) in lens:
                    continue
                lens.add(round(total, 2))
                slanted = abs(m1[0] - m2[0]) > 1e-6 and abs(m1[1] - m2[1]) > 1e-6
                m = dict(view=v, kind='dist', mdl=(m1, m2), off=(0, 0), aligned=slanted)
                m['off'] = default_offset(d, m, extra=6.0 * (len(lens) - 1))
                out.append(m)
        pos_seen = set()
        for f in [x for x in d.features if x['view'] == v and x['kind'] == 'circle' and x['full']]:
            (cx, cy), r = f['mdl'][0], f['mdl'][1]
            for tag, p, q in (('x', (g.bbox[0], cy), (cx, cy)), ('y', (cx, g.bbox[1]), (cx, cy))):
                value = abs(q[0] - p[0]) + abs(q[1] - p[1])
                key = (tag, round(value, 2))
                if value * d.scale < 3.0 or key in pos_seen:
                    continue
                pos_seen.add(key)
                m = dict(view=v, kind='dist', mdl=(p, q), off=(0, 0))
                fa = resolve_feature(d, m)
                m['off'] = (0.0, -(10.0 + 6.0 * len([1 for k2 in pos_seen if k2[0] == 'x']))) if tag == 'x' else (-(10.0 + 6.0 * len([1 for k2 in pos_seen if k2[0] == 'y'])), 0.0)
                out.append(m)
    return out


def auto_settings(source):
    """Ustawienia rysunku automatycznego: rzuty z przodu, z góry, z prawej i izometria; arkusz najmniejszy, na którym skala jest czytelna."""
    names = ('front', 'top', 'right', 'iso')
    for sheet in ('A4', 'A3', 'A2'):
        d = build_drawing(source, names, sheet, True, 'eu', None, True, True, True, False, details=True)
        if d.scale >= 0.2 or sheet == 'A2':
            return dict(views=names, sheet=sheet, landscape=True, projection='eu', scale=None, overall=True, circles=True, centers=True, hidden=True, details=True)


# ---------------------------------------------------------------------------
# eksport DXF (format R12, czytany przez każdy program CAD)
# ---------------------------------------------------------------------------
_LAYERS = {'visible': ('WIDOCZNE', 7, 'CONTINUOUS'), 'hidden': ('UKRYTE', 8, 'DASHED'), 'center': ('OSIE', 1, 'CENTER'),
           'dim': ('WYMIARY', 3, 'CONTINUOUS'), 'frame': ('RAMKA', 7, 'CONTINUOUS'), 'thin': ('CIENKIE', 8, 'CONTINUOUS'), 'text': ('TEKST', 7, 'CONTINUOUS'),
           'bend_up': ('GIECIE_GORA', 1, 'CONTINUOUS'), 'bend_down': ('GIECIE_DOL', 5, 'DASHED')}


def dxf_text(drawing: Drawing) -> str:
    out = []
    add = lambda *pairs: out.extend(str(p) for p in pairs)
    add(0, 'SECTION', 2, 'HEADER', 9, '$ACADVER', 1, 'AC1009', 9, '$DWGCODEPAGE', 3, 'ANSI_1250', 0, 'ENDSEC')
    add(0, 'SECTION', 2, 'TABLES', 0, 'TABLE', 2, 'LTYPE', 70, 3)
    add(0, 'LTYPE', 2, 'CONTINUOUS', 70, 0, 3, 'Solid line', 72, 65, 73, 0, 40, 0.0)
    add(0, 'LTYPE', 2, 'DASHED', 70, 0, 3, 'Dashed', 72, 65, 73, 2, 40, 6.0, 49, 4.0, 49, -2.0)
    add(0, 'LTYPE', 2, 'CENTER', 70, 0, 3, 'Center', 72, 65, 73, 4, 40, 16.0, 49, 10.0, 49, -2.0, 49, 2.0, 49, -2.0)
    add(0, 'ENDTAB', 0, 'TABLE', 2, 'LAYER', 70, len(_LAYERS))
    for name, color, ltype in _LAYERS.values():
        add(0, 'LAYER', 2, name, 70, 0, 62, color, 6, ltype)
    add(0, 'ENDTAB', 0, 'ENDSEC', 0, 'SECTION', 2, 'ENTITIES')
    for p in drawing.prims:
        if isinstance(p, Poly):
            layer = _LAYERS[p.style][0]
            if p.fill and len(p.pts) == 3:
                (x0, y0), (x1, y1), (x2, y2) = p.pts
                add(0, 'SOLID', 8, layer, 10, f'{x0:.4f}', 20, f'{y0:.4f}', 11, f'{x1:.4f}', 21, f'{y1:.4f}', 12, f'{x2:.4f}', 22, f'{y2:.4f}', 13, f'{x2:.4f}', 23, f'{y2:.4f}')
                continue
            pts = list(p.pts) + ([p.pts[0]] if p.closed else [])
            for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
                add(0, 'LINE', 8, layer, 10, f'{x0:.4f}', 20, f'{y0:.4f}', 11, f'{x1:.4f}', 21, f'{y1:.4f}')
        else:
            for i, line in enumerate(p.text.split('\n')):
                text = line.replace('Ø', '%%c')
                y = p.y - i * p.h * 1.3
                add(0, 'TEXT', 8, _LAYERS['text'][0], 10, f'{p.x:.4f}', 20, f'{y:.4f}', 40, f'{p.h:.3f}', 1, text, 50, f'{p.rot:.2f}',
                    72, {'l': 0, 'c': 1, 'r': 2}[p.align], 11, f'{p.x:.4f}', 21, f'{y:.4f}')
    add(0, 'ENDSEC', 0, 'EOF')
    return '\n'.join(out) + '\n'


def save_dxf(drawing: Drawing, path):
    with open(path, 'w', encoding='cp1250', errors='replace', newline='\n') as handle:
        handle.write(dxf_text(drawing))
