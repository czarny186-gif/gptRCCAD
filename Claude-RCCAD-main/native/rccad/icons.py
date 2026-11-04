"""Ikony operacji rysowane wektorowo (QPainter) — kolorowe, czytelne piktogramy w panelach narzędzi."""
from __future__ import annotations
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

BLUE = '#2f87e8'
BLUE_SOFT = '#cfe4fb'
ORANGE = '#f09a22'
GREEN = '#2fa56d'
RED = '#e5484d'
INK = '#40586f'
PALE = '#e6edf5'


def _rounded(x, y, w, h, r=4):
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _circle(cx, cy, r):
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _draw_drawing(p, which, ink, acc, soft, pen):
    """Ikony rysunku technicznego: arkusz z rzutem i wymiarem (auto = z iskrą)."""
    p.setBrush(soft); p.setPen(pen(ink, 2.4))
    p.drawRoundedRect(QRectF(7, 6, 34, 36), 3, 3)
    p.setBrush(Qt.NoBrush); p.setPen(pen(ink, 2.2)); p.drawRect(QRectF(13, 13, 13, 11))
    p.setPen(pen(ink, 1.8)); p.drawLine(QPointF(30, 13), QPointF(35, 13)); p.drawLine(QPointF(30, 24), QPointF(35, 24))
    p.setPen(pen(acc, 2.4)); p.drawLine(QPointF(33, 14), QPointF(33, 23))
    p.drawLine(QPointF(13, 31), QPointF(26, 31)); p.drawLine(QPointF(13, 28), QPointF(13, 34)); p.drawLine(QPointF(26, 28), QPointF(26, 34))
    if which == 'autodrawing':
        p.setBrush(QColor(acc)); p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(36, 28), QPointF(38.5, 34), QPointF(45, 36.5), QPointF(38.5, 39), QPointF(36, 46), QPointF(33.5, 39), QPointF(27, 36.5), QPointF(33.5, 34)]))


def _draw_datum(p, which, ink, acc, soft, pen):
    """Sposób mierzenia długości kołnierza: płyta bazowa, gięcie i nowy kołnierz z wymiarem długości (pomarańczowy)
    od odniesienia (przerywane linie): prosta część / przecięcie zewnętrznych lub wewnętrznych powierzchni / styczna do zagięcia."""
    import numpy as np
    alpha = math.radians(120.0 if which == 'tangent' else 60.0)
    t, r, L, base = 4.0, 4.0, 22.0, 20.0
    d = np.array([-math.cos(alpha), math.sin(alpha)])
    C = np.array([0.0, t + r])
    u = lambda phi: np.array([-math.sin(phi), -math.cos(phi)])
    Ti, To = C + r * u(alpha), C + (r + t) * u(alpha)
    Ei, Eo = Ti + L * d, To + L * d
    out_n = (To - Ti) / t                       # od wnętrza gięcia na zewnątrz, prostopadle do kołnierza
    if which == 'outer':
        start, end, side = To - (r + t) * math.tan(alpha / 2) * d, Eo, out_n
    elif which == 'inner':
        start, end, side = Ti - r * math.tan(alpha / 2) * d, Ei, -out_n
    elif which == 'tangent':
        start, end, side = To - (r + t) * d, Eo, out_n
    else:
        start, end, side = To, Eo, out_n
    a = start + 5.0 * side
    b = a + float((end - start) @ d) * d
    pts = [np.array([base, 0.0]), np.array([base, t]), Ei, Eo, start, a, b, np.array([0.0, 0.0])]
    lo, hi = np.min(pts, axis=0) - 1.5, np.max(pts, axis=0) + 1.5
    k = 42.0 / max(hi - lo)
    cx, cy = (lo + hi) / 2
    Q = lambda v: QPointF(float(24.0 + (v[0] - cx) * k), float(24.0 - (v[1] - cy) * k))
    # płyta bazowa
    p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 1.8))
    p.drawPolygon(QPolygonF([Q((0, 0)), Q((base, 0)), Q((base, t)), Q((0, t))]))
    # gięcie i nowy kołnierz
    path = QPainterPath(Q((0, t)))
    for phi in np.linspace(0, alpha, 12)[1:]:
        path.lineTo(Q(C + r * u(phi)))
    path.lineTo(Q(Ei)); path.lineTo(Q(Eo))
    for phi in np.linspace(alpha, 0, 12):
        path.lineTo(Q(C + (r + t) * u(phi)))
    path.closeSubpath()
    p.setBrush(soft); p.setPen(pen(ink, 1.8)); p.drawPath(path)
    # odniesienie (przerywane)
    dash = pen(acc, 1.4); dash.setStyle(Qt.DashLine); dash.setDashPattern([2.2, 1.6]); p.setPen(dash); p.setBrush(Qt.NoBrush)
    if which in ('outer', 'inner'):
        y = 0.0 if which == 'outer' else t
        p.drawLine(Q((base, y)), Q((start[0] - 1.5, y)))
        p.drawLine(Q(start - 1.5 * d), Q(end))
    elif which == 'tangent':
        p.drawLine(Q(start - 2.0 * side), Q(a + 1.5 * side))
    else:
        p.drawLine(Q(start - 1.0 * side), Q(a + 1.5 * side))
    p.setPen(pen(acc, 1.2)); p.drawLine(Q(end), Q(b + 1.5 * side))
    # wymiar długości: równoległy do kołnierza
    p.setPen(pen(acc, 2.0)); p.drawLine(Q(a), Q(b))
    p.setBrush(QColor(acc)); p.setPen(Qt.NoPen)
    for tip, back in ((a, d), (b, -d)):
        across = np.array([-back[1], back[0]])
        p.drawPolygon(QPolygonF([Q(tip), Q(tip + 3.4 * back + 1.6 * across), Q(tip + 3.4 * back - 1.6 * across)]))


def _draw_sheet_drawing(p, ink, acc, soft, pen):
    """Rysunek blachy do gięcia: arkusz z rozwinięciem, linie gięcia (ciągła i przerywana) i wymiar między nimi."""
    p.setBrush(soft); p.setPen(pen(ink, 2.4))
    p.drawRoundedRect(QRectF(5, 6, 38, 36), 3, 3)
    p.setBrush(QColor('#ffffff')); p.setPen(pen(ink, 2.0)); p.drawRect(QRectF(11, 12, 26, 18))
    p.setPen(pen(acc, 2.0)); p.drawLine(QPointF(18, 12), QPointF(18, 30))
    pn = pen(acc, 2.0); pn.setStyle(Qt.DashLine); pn.setDashPattern([2.0, 1.5]); p.setPen(pn); p.drawLine(QPointF(30, 12), QPointF(30, 30))
    p.setPen(pen(ink, 1.6)); p.drawLine(QPointF(18, 36), QPointF(30, 36)); p.drawLine(QPointF(18, 33), QPointF(18, 39)); p.drawLine(QPointF(30, 33), QPointF(30, 39))


def _draw_measure(p, which, ink, acc, soft, pen):
    """Ikony narzędzi pomiarowych (wspólne dla paska i nagłówków paneli)."""
    p.setBrush(Qt.NoBrush)
    if which == 'mdist':
        p.setPen(pen(ink, 2.6)); p.drawLine(QPointF(8, 12), QPointF(8, 36)); p.drawLine(QPointF(40, 12), QPointF(40, 36))
        p.setPen(pen(acc, 3.0)); p.drawLine(QPointF(10, 24), QPointF(38, 24))
        p.setBrush(QColor(acc)); p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(9, 24), QPointF(17, 19), QPointF(17, 29)])); p.drawPolygon(QPolygonF([QPointF(39, 24), QPointF(31, 19), QPointF(31, 29)]))
    elif which == 'mangle':
        p.setPen(pen(ink, 2.8)); p.drawLine(QPointF(8, 38), QPointF(42, 38)); p.drawLine(QPointF(8, 38), QPointF(34, 9))
        p.setPen(pen(acc, 3.0)); p.drawArc(QRectF(-8, 22, 32, 32), 0, 49 * 16)
    elif which == 'mrad':
        p.setBrush(soft); p.setPen(pen(ink, 2.6)); p.drawEllipse(QPointF(24, 24), 16, 16)
        p.setPen(pen(acc, 3.0)); p.drawLine(QPointF(24, 24), QPointF(35.5, 12.5))
        p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 24), 3.4, 3.4)
    elif which == 'mprops':
        top = QPainterPath(); top.moveTo(22, 6); top.lineTo(38, 13); top.lineTo(22, 20); top.lineTo(6, 13); top.closeSubpath()
        left = QPainterPath(); left.moveTo(6, 13); left.lineTo(22, 20); left.lineTo(22, 38); left.lineTo(6, 31); left.closeSubpath()
        right = QPainterPath(); right.moveTo(38, 13); right.lineTo(22, 20); right.lineTo(22, 38); right.lineTo(38, 31); right.closeSubpath()
        p.setPen(pen(ink, 2.4)); p.setBrush(soft); p.drawPath(left); p.setBrush(Qt.NoBrush); p.drawPath(right); p.setBrush(soft); p.drawPath(top)
        p.setBrush(QColor('#ffffff')); p.setPen(pen(acc, 2.6)); p.drawEllipse(QPointF(37, 36), 8.5, 8.5)
        p.setPen(pen(acc, 3.0)); p.drawLine(QPointF(37, 36), QPointF(37, 41)); p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(37, 31.5), 1.9, 1.9)


def pixmap(kind: str, size: int = 38, scale: int = 2) -> QPixmap:
    S = 48.0
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size * scale / S, size * scale / S)
    pen = lambda c, w=2.2: QPen(QColor(c), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    fill = lambda path, c, edge=INK: (p.setBrush(QColor(c)), p.setPen(pen(edge)), p.drawPath(path))
    a, b = _rounded(7, 11, 24, 24), _rounded(17, 17, 24, 24)
    ca, cb = _circle(19, 24, 12), _circle(30, 24, 12)
    if kind == 'new':
        fill(_rounded(9, 13, 26, 26), BLUE_SOFT, BLUE)
        p.setPen(pen(BLUE, 2.6)); p.drawLine(QPointF(38, 8), QPointF(38, 22)); p.drawLine(QPointF(31, 15), QPointF(45, 15))
    elif kind in ('join', 'union'):
        path = (ca.united(cb)) if kind == 'union' else (a.united(b))
        fill(path, BLUE_SOFT, BLUE)
    elif kind in ('cut', 'subtract'):
        base, tool = (a, b) if kind == 'cut' else (ca, cb)
        fill(base.subtracted(tool), BLUE_SOFT, BLUE)
        p.setBrush(Qt.NoBrush); pn = pen(ORANGE, 1.8); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawPath(tool)
    elif kind in ('intersect', 'common'):
        base, tool = (a, b) if kind == 'intersect' else (ca, cb)
        p.setBrush(Qt.NoBrush); p.setPen(pen('#9fb4c8', 1.8)); p.drawPath(base); p.drawPath(tool)
        fill(base.intersected(tool), BLUE, BLUE)
    elif kind in ('one', 'sym', 'two'):
        fill(_rounded(15, 20, 18, 8, 2), BLUE_SOFT, BLUE)
        p.setPen(pen(ORANGE, 2.6))
        if kind in ('one', 'sym', 'two'):
            p.drawLine(QPointF(24, 20), QPointF(24, 6)); p.drawPolyline(QPolygonF([QPointF(19, 11), QPointF(24, 5), QPointF(29, 11)]))
        if kind in ('sym', 'two'):
            p.setPen(pen(BLUE if kind == 'two' else ORANGE, 2.6))
            p.drawLine(QPointF(24, 28), QPointF(24, 42)); p.drawPolyline(QPolygonF([QPointF(19, 37), QPointF(24, 43), QPointF(29, 37)]))
    elif kind == 'ends':
        # bryła (niebieska) i dwie pomarańczowe strzałki wychodzące z przeciwległych ścian
        fill(_rounded(13, 17, 22, 14, 2), BLUE_SOFT, BLUE)
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen)
        p.drawRect(QRectF(13, 13, 22, 4)); p.drawRect(QRectF(13, 31, 22, 4))
        p.setPen(pen(ORANGE, 2.6)); p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(24, 13), QPointF(24, 4)); p.drawPolyline(QPolygonF([QPointF(20, 8), QPointF(24, 3.5), QPointF(28, 8)]))
        p.drawLine(QPointF(24, 35), QPointF(24, 44)); p.drawPolyline(QPolygonF([QPointF(20, 40), QPointF(24, 44.5), QPointF(28, 40)]))
    elif kind in ('ex_dist', 'ex_upto'):
        # profil (niebieski), strzałka wyciągnięcia (pomarańczowa); "do elementu": przerywana płaszczyzna-cel z punktem
        fill(QPainterPath(_rounded(8, 34, 22, 8, 2)), BLUE_SOFT, BLUE)
        if kind == 'ex_dist':
            p.setPen(pen(ORANGE, 2.6)); p.drawLine(QPointF(19, 34), QPointF(19, 12)); p.drawPolyline(QPolygonF([QPointF(14, 17), QPointF(19, 11), QPointF(24, 17)]))
            p.setPen(pen(INK, 1.8)); p.drawLine(QPointF(34, 10), QPointF(42, 10)); p.drawLine(QPointF(34, 38), QPointF(42, 38))
            p.setPen(pen(INK, 2.2)); p.drawLine(QPointF(38, 11), QPointF(38, 37))
        else:
            pn = pen(INK, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush)
            p.drawPolygon(QPolygonF([QPointF(4, 12), QPointF(14, 5), QPointF(44, 5), QPointF(34, 12)]))
            p.setPen(pen(ORANGE, 2.6)); p.drawLine(QPointF(19, 34), QPointF(19, 13)); p.drawPolyline(QPolygonF([QPointF(14, 18), QPointF(19, 12), QPointF(24, 18)]))
            p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(34, 8.5), 3.4, 3.4)
    elif kind == 'fillet':
        path = QPainterPath(); path.moveTo(10, 8); path.lineTo(10, 40); path.lineTo(38, 40); path.lineTo(38, 30)
        path.lineTo(28, 30); path.quadTo(20, 30, 20, 22); path.lineTo(20, 8); path.closeSubpath()
        fill(path, BLUE_SOFT, BLUE)
        p.setBrush(Qt.NoBrush); p.setPen(pen(GREEN, 2.4)); p.drawArc(QRectF(12, 22, 16, 16), 90 * 16, 90 * 16)
    elif kind == 'chamfer':
        path = QPainterPath(); path.moveTo(10, 8); path.lineTo(10, 40); path.lineTo(38, 40); path.lineTo(38, 30)
        path.lineTo(30, 30); path.lineTo(20, 22); path.lineTo(20, 8); path.closeSubpath()
        fill(path, BLUE_SOFT, BLUE)
        p.setPen(pen(ORANGE, 2.4)); p.drawLine(QPointF(20, 22), QPointF(30, 30))
    elif kind == 'mirror':
        tri = QPolygonF([QPointF(8, 38), QPointF(8, 10), QPointF(21, 38)])
        mir = QPolygonF([QPointF(40, 38), QPointF(40, 10), QPointF(27, 38)])
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE)); p.drawPolygon(tri)
        p.setBrush(QColor('#d6f1e3')); p.setPen(pen(GREEN)); p.drawPolygon(mir)
        pn = pen(ORANGE, 2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawLine(QPointF(24, 5), QPointF(24, 43))
    elif kind == 'x_extrude':
        pn = pen(BLUE, 2.0); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(5, 22), QPointF(17, 12), QPointF(43, 12), QPointF(31, 22)]))
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4))
        p.drawPolygon(QPolygonF([QPointF(5, 40), QPointF(17, 30), QPointF(43, 30), QPointF(31, 40)]))
        p.setPen(pen(ORANGE, 3.6)); p.drawLine(QPointF(24, 30), QPointF(24, 16))
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(24, 7), QPointF(17, 17), QPointF(31, 17)]))
    elif kind in ('ax_u', 'ax_v', 'ax_line', 'x_axis'):
        horiz = kind == 'ax_u'
        diag = kind in ('ax_line', 'x_axis')
        a, b = ((6, 24), (42, 24)) if horiz else (((8, 40), (40, 8)) if diag else ((24, 6), (24, 42)))
        pn = pen(INK, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush); p.drawLine(QPointF(*a), QPointF(*b))
        if diag:
            p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 24), 4.4, 4.4)
        else:
            q = QPainterPath()
            if horiz:
                q.addRoundedRect(QRectF(12, 8, 24, 11), 2, 2)
            else:
                q.addRoundedRect(QRectF(29, 12, 11, 24), 2, 2)
            fill(q, BLUE_SOFT, BLUE)
    elif kind in ('sh_in', 'sh_out'):
        outer = _rounded(6, 8, 36, 34, 3)
        if kind == 'sh_in':
            fill(outer, BLUE_SOFT, BLUE); p.setBrush(QColor('#ffffff')); p.setPen(pen(ORANGE, 2.6)); p.drawRoundedRect(QRectF(15, 17, 18, 16), 2, 2)
        else:
            p.setBrush(Qt.NoBrush); p.setPen(pen(ORANGE, 2.6)); p.drawRoundedRect(QRectF(4, 6, 40, 38), 3, 3)
            fill(_rounded(13, 15, 22, 20, 2), BLUE_SOFT, BLUE)
    elif kind == 'x_shell':
        cup = QPainterPath(); cup.moveTo(6, 8); cup.lineTo(6, 42); cup.lineTo(42, 42); cup.lineTo(42, 8); cup.lineTo(33, 8); cup.lineTo(33, 33); cup.lineTo(15, 33); cup.lineTo(15, 8); cup.closeSubpath()
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.6)); p.drawPath(cup)
        p.setBrush(Qt.NoBrush); p.setPen(pen(ORANGE, 3.2)); p.drawLine(QPointF(17, 25), QPointF(31, 25)); p.drawPolyline(QPolygonF([QPointF(20, 20), QPointF(24, 25), QPointF(28, 20)]))
    elif kind == 'x_sheet':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.6)); p.drawRoundedRect(QRectF(4, 30, 30, 9), 2, 2)
        p.setBrush(Qt.NoBrush); p.setPen(pen(ORANGE, 3.2)); p.drawPolyline(QPolygonF([QPointF(30, 35), (QPointF(38, 35)), QPointF(42, 10)]))
    elif kind == 'x_flange':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.6)); p.drawRoundedRect(QRectF(4, 32, 28, 9), 2, 2); p.drawRoundedRect(QRectF(26, 6, 9, 35), 2, 2)
        p.setPen(pen(ORANGE, 3.2)); p.drawLine(QPointF(42, 20), QPointF(42, 6)); p.drawPolyline(QPolygonF([QPointF(37, 11), QPointF(42, 5), QPointF(47, 11)]))
    elif kind == 'rl_par':
        # łączenie równoległe: dwie ściany, każda kończy się prostopadle (pionowa linia cięcia)
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4)); p.drawRoundedRect(QRectF(6, 8, 14, 32), 2, 2); p.drawRoundedRect(QRectF(28, 8, 14, 32), 2, 2)
        p.setPen(pen(ORANGE, 3.0)); p.drawLine(QPointF(24, 6), QPointF(24, 42))
    elif kind == 'rl_skos':
        # łączenie skośne: ukos 45° przez narożnik
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4)); p.drawPolygon(QPolygonF([QPointF(6, 8), QPointF(20, 8), QPointF(30, 42), QPointF(6, 42)])); p.drawPolygon(QPolygonF([QPointF(28, 8), QPointF(42, 8), QPointF(42, 42), QPointF(30, 42)]))
        p.setPen(pen(ORANGE, 3.0)); p.drawLine(QPointF(24, 6), QPointF(30, 42))
    elif kind == 'rl_sheet':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4))
        p.drawRoundedRect(QRectF(7,8,10,32),1,1)
        p.drawRoundedRect(QRectF(22,30,20,10),1,1)
        p.setPen(pen(ORANGE,2.8)); p.drawArc(QRectF(12,16,22,22),90*16,-90*16)
    elif kind == 'x_hem':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.6)); p.drawRoundedRect(QRectF(26, 6, 9, 35), 2, 2); p.drawRoundedRect(QRectF(8, 6, 27, 8), 2, 2)
        p.setPen(pen(ORANGE, 3.2)); p.drawLine(QPointF(12, 20), QPointF(12, 32)); p.drawPolyline(QPolygonF([QPointF(7, 27), QPointF(12, 33), QPointF(17, 27)]))
    elif kind == 'x_rules':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.6)); p.drawRoundedRect(QRectF(5, 14, 38, 22), 3, 3)
        p.setPen(pen(ORANGE, 3.0))
        for x in (13, 21, 29, 37):
            p.drawLine(QPointF(x, 14), QPointF(x, 24 if x % 16 else 29))
    elif kind == 'x_sweep':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.6)); p.drawEllipse(QPointF(11, 36), 8, 8)
        path = QPainterPath(); path.moveTo(11, 36); path.cubicTo(11, 10, 36, 40, 39, 12)
        p.setBrush(Qt.NoBrush); p.setPen(pen(ORANGE, 3.6)); p.drawPath(path)
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(39, 5), QPointF(32, 15), QPointF(45, 15)]))
    elif kind in ('x_loft', 'lf_ruled', 'lf_smooth', 'lf_profiles', 'lf_point'):
        smooth = kind in ('x_loft', 'lf_smooth')
        pn = pen(BLUE, 2.2); p.setPen(pn); p.setBrush(Qt.NoBrush)
        lower = QPolygonF([QPointF(5, 40), QPointF(30, 40), QPointF(43, 31), QPointF(18, 31)])
        if kind == 'lf_point':
            tip = QPointF(26, 8)
            for q in (QPointF(5, 40), QPointF(30, 40), QPointF(43, 31), QPointF(18, 31)):
                p.drawLine(q, tip)
            p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4)); p.drawPolygon(lower)
            p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawEllipse(tip, 3.6, 3.6)
        else:
            upper = QPolygonF([QPointF(16, 17), QPointF(28, 17), QPointF(35, 9), QPointF(23, 9)])
            for a, b in ((QPointF(5, 40), QPointF(16, 17)), (QPointF(30, 40), QPointF(28, 17)), (QPointF(43, 31), QPointF(35, 9)), (QPointF(18, 31), QPointF(23, 9))):
                if smooth:
                    c = QPainterPath(); c.moveTo(a); c.quadTo(QPointF((a.x() + b.x()) / 2 + (6 if a.x() < 24 else -6), (a.y() + b.y()) / 2), b); p.drawPath(c)
                else:
                    p.drawLine(a, b)
            p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4)); p.drawPolygon(lower)
            p.setBrush(QColor(ORANGE)); p.setPen(pen(ORANGE, 2.4)); p.drawPolygon(upper)
    elif kind in ('x_drawing', 'x_autodrawing'):
        _draw_drawing(p, kind[2:], BLUE, ORANGE, QColor(BLUE_SOFT), pen)
    elif kind in ('dl_leg', 'dl_outer', 'dl_inner', 'dl_tangent'):
        _draw_datum(p, kind[3:], INK, ORANGE, QColor(BLUE_SOFT), pen)
    elif kind == 'x_sheetdrawing':
        _draw_sheet_drawing(p, BLUE, ORANGE, QColor(BLUE_SOFT), pen)
    elif kind in ('x_mdist', 'x_mangle', 'x_mrad', 'x_mprops'):
        _draw_measure(p, kind[2:], BLUE, ORANGE, QColor(BLUE_SOFT), pen)
    elif kind == 'x_revolve':
        pn = pen(BLUE, 2.0); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush); p.drawLine(QPointF(14, 4), QPointF(14, 44))
        prof = QPainterPath(); prof.moveTo(15, 8); prof.lineTo(30, 8); prof.lineTo(26, 24); prof.lineTo(30, 40); prof.lineTo(15, 40); prof.closeSubpath()
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4)); p.drawPath(prof)
        p.setBrush(Qt.NoBrush); p.setPen(pen(ORANGE, 3.4)); p.drawArc(QRectF(2, 28, 42, 15), 200 * 16, 150 * 16)
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(44, 31), QPointF(36, 29), QPointF(41, 40)]))
    elif kind == 'x_bool':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4)); p.drawRoundedRect(QRectF(5, 7, 26, 26), 5, 5)
        p.setBrush(QColor('#d6f1e3')); p.setPen(pen(GREEN, 2.4)); p.drawRoundedRect(QRectF(17, 17, 26, 26), 5, 5)
        pn = pen(ORANGE, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush); p.drawRect(QRectF(17, 17, 14, 16))
    elif kind == 'x_mod':
        path = QPainterPath(); path.moveTo(7, 41); path.lineTo(7, 14); path.lineTo(25, 14); path.quadTo(41, 14, 41, 30); path.lineTo(41, 41); path.closeSubpath()
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.4)); p.drawPath(path)
        arc = QPainterPath(); arc.moveTo(25, 14); arc.quadTo(41, 14, 41, 30)
        p.setBrush(Qt.NoBrush); p.setPen(pen(ORANGE, 4.0)); p.drawPath(arc)
    elif kind == 'x_object':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.2))
        p.drawPolygon(QPolygonF([QPointF(6, 18), QPointF(20, 10), QPointF(34, 18), QPointF(20, 26)]))
        p.setBrush(QColor('#9cc6f4')); p.drawPolygon(QPolygonF([QPointF(6, 18), QPointF(20, 26), QPointF(20, 42), QPointF(6, 34)]))
        p.setBrush(QColor('#74aeea')); p.drawPolygon(QPolygonF([QPointF(20, 26), QPointF(34, 18), QPointF(34, 34), QPointF(20, 42)]))
        p.setBrush(QColor(ORANGE)); p.setPen(pen('#ffffff', 1.6))
        p.drawPolygon(QPolygonF([QPointF(30, 24), QPointF(30, 42), QPointF(35, 37), QPointF(38.5, 45), QPointF(41.5, 43.6), QPointF(38, 35.5), QPointF(44.5, 35)]))
    elif kind == 'x_wall':
        p.setBrush(QColor('#d6f1e3')); p.setPen(pen(GREEN, 2.4))
        p.drawPolygon(QPolygonF([QPointF(15, 7), QPointF(33, 13), QPointF(33, 41), QPointF(15, 35)]))
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.0))
        p.drawPolygon(QPolygonF([QPointF(4, 36), QPointF(4, 22), QPointF(12, 29)]))
        p.drawPolygon(QPolygonF([QPointF(44, 36), QPointF(44, 22), QPointF(36, 29)]))
        pn = pen(ORANGE, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawLine(QPointF(24, 4), QPointF(24, 44))
    elif kind == 'x_pattern' or kind == 'x_pat_rect':
        for r in range(2):
            for c in range(3):
                first = (r, c) == (0, 0)
                p.setBrush(QColor(BLUE if first else BLUE_SOFT)); p.setPen(pen(BLUE, 2.0))
                p.drawRoundedRect(QRectF(5 + c * 13.5, 10 + r * 15, 10, 10), 2.4, 2.4)
        p.setPen(pen(ORANGE, 2.8)); p.drawLine(QPointF(10, 38), QPointF(38, 38))
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(43, 38), QPointF(35, 33.5), QPointF(35, 42.5)]))
    elif kind == 'x_history':
        p.setBrush(QColor('#ffffff')); p.setPen(pen(BLUE, 2.4)); p.drawEllipse(QPointF(24, 24), 16, 16)
        p.setPen(pen(ORANGE, 2.8)); p.drawLine(QPointF(24, 24), QPointF(24, 13)); p.drawLine(QPointF(24, 24), QPointF(32, 28))
        p.setPen(pen(BLUE, 2.6)); p.drawPolyline(QPolygonF([QPointF(5, 13), QPointF(8, 23), QPointF(17, 19)]))
    elif kind == 'x_pat_circ':
        pn = pen(ORANGE, 2.0); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush); p.drawEllipse(QPointF(24, 24), 15, 15)
        for k in range(6):
            a = math.radians(-90 + 60 * k)
            cx, cy = 24 + 15 * math.cos(a), 24 + 15 * math.sin(a)
            p.setBrush(QColor(BLUE if k == 0 else BLUE_SOFT)); p.setPen(pen(BLUE, 2.0)); p.drawRoundedRect(QRectF(cx - 4.5, cy - 4.5, 9, 9), 2.2, 2.2)
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 24), 2.6, 2.6)
    elif kind == 'x_pat_path':
        pn = pen(ORANGE, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawLine(QPointF(6, 40), QPointF(42, 8))
        for k in range(4):
            cx, cy = 10 + k * 9.5, 36 - k * 8.5
            p.setBrush(QColor(BLUE if k == 0 else BLUE_SOFT)); p.setPen(pen(BLUE, 2.0)); p.drawRoundedRect(QRectF(cx - 4.5, cy - 4.5, 9, 9), 2.2, 2.2)
    elif kind == 'x_text':
        p.setPen(pen(INK, 4.6)); p.drawLine(QPointF(10, 11), QPointF(34, 11)); p.drawLine(QPointF(22, 11), QPointF(22, 36))
        p.setPen(pen(BLUE, 2.4)); p.drawLine(QPointF(35, 20), QPointF(35, 36)); p.drawLine(QPointF(32, 20), QPointF(38, 20)); p.drawLine(QPointF(32, 36), QPointF(38, 36))
        p.setPen(pen(ORANGE, 3.2)); p.drawLine(QPointF(12, 42), QPointF(32, 42))
    elif kind == 'x_surface':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.2))
        p.drawPolygon(QPolygonF([QPointF(4, 34), QPointF(16, 18), QPointF(42, 18), QPointF(30, 34)]))
        p.setBrush(QColor(ORANGE)); p.setPen(pen('#ffffff', 1.6))
        p.drawPolygon(QPolygonF([QPointF(26, 20), QPointF(26, 40), QPointF(31.5, 34.5), QPointF(35.5, 44), QPointF(39, 42.4), QPointF(35, 33), QPointF(42, 32.5)]))
    elif kind == 'x_area':
        pn = pen(BLUE, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(QColor(207, 228, 251, 150))
        p.drawRect(QRectF(9, 13, 30, 22))
        p.setBrush(QColor('#ffffff')); p.setPen(pen(BLUE, 2.2))
        for cx, cy in ((9, 13), (39, 13), (9, 35), (39, 35)):
            p.drawRect(QRectF(cx - 3.2, cy - 3.2, 6.4, 6.4))
        p.setPen(pen(ORANGE, 3.0)); p.drawLine(QPointF(15, 19), QPointF(31, 29))
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(34, 31), QPointF(26, 31), QPointF(31, 24)]))
    elif kind == 'sketch':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE)); p.drawRoundedRect(QRectF(8, 14, 28, 22), 3, 3)
        p.setPen(pen(ORANGE, 2.8)); p.drawLine(QPointF(30, 12), QPointF(42, 24))
        p.setBrush(QColor(ORANGE)); p.drawPolygon(QPolygonF([QPointF(28, 14), QPointF(26, 21), QPointF(34, 18)]))
    elif kind in ('f_new', 'f_save', 'f_saveas', 'f_open', 'f_import', 'f_export'):
        if kind == 'f_new':
            page = QPainterPath(); page.moveTo(12, 6); page.lineTo(29, 6); page.lineTo(37, 14); page.lineTo(37, 42); page.lineTo(12, 42); page.closeSubpath()
            fill(page, '#ffffff', INK)
            p.setPen(pen(INK, 2)); p.drawPolyline(QPolygonF([QPointF(29, 6), QPointF(29, 14), QPointF(37, 14)]))
            p.setPen(pen(BLUE, 3)); p.drawLine(QPointF(24.5, 22), QPointF(24.5, 36)); p.drawLine(QPointF(17.5, 29), QPointF(31.5, 29))
        elif kind in ('f_save', 'f_saveas'):
            body = QPainterPath(); body.moveTo(8, 8); body.lineTo(34, 8); body.lineTo(41, 15); body.lineTo(41, 41); body.lineTo(8, 41); body.closeSubpath()
            fill(body, BLUE_SOFT, BLUE)
            fill(_rounded(14, 8, 18, 10, 1.5), '#ffffff', BLUE)
            fill(_rounded(13, 26, 22, 15, 2), '#ffffff', BLUE)
            if kind == 'f_saveas':
                p.setPen(pen(ORANGE, 3)); p.drawLine(QPointF(30, 44), QPointF(44, 30))
                p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(28, 46), QPointF(29, 40), QPointF(34, 45)]))
        elif kind == 'f_open':
            back = QPainterPath(); back.moveTo(5, 12); back.lineTo(18, 12); back.lineTo(22, 17); back.lineTo(40, 17); back.lineTo(40, 40); back.lineTo(5, 40); back.closeSubpath()
            fill(back, BLUE_SOFT, BLUE)
            front = QPainterPath(); front.moveTo(5, 40); front.lineTo(11, 23); front.lineTo(45, 23); front.lineTo(39, 40); front.closeSubpath()
            fill(front, '#ffffff', BLUE)
        else:
            up = kind == 'f_export'
            tray = QPainterPath(); tray.moveTo(7, 30); tray.lineTo(7, 41); tray.lineTo(41, 41); tray.lineTo(41, 30)
            p.setBrush(Qt.NoBrush); p.setPen(pen(BLUE, 2.6)); p.drawPath(tray)
            p.setPen(pen(ORANGE if up else GREEN, 3))
            if up:
                p.drawLine(QPointF(24, 32), QPointF(24, 8)); p.drawPolyline(QPolygonF([QPointF(15, 17), QPointF(24, 8), QPointF(33, 17)]))
            else:
                p.drawLine(QPointF(24, 8), QPointF(24, 32)); p.drawPolyline(QPolygonF([QPointF(15, 23), QPointF(24, 32), QPointF(33, 23)]))
    elif kind.startswith('t_'):
        name = kind[2:]
        white = name.endswith('_w')
        name = name[:-2] if white else name
        ink = '#ffffff' if white else '#324c68'
        acc = '#ffb54d' if white else ORANGE
        soft = (QColor(255, 255, 255, 46) if white else QColor('#dbe9f8'))
        st = lambda c=ink, w=2.6: (p.setBrush(Qt.NoBrush), p.setPen(pen(c, w)))
        fl = lambda path, c, edge=ink, w=2.6: (p.setBrush(c if isinstance(c, QColor) else QColor(c)), p.setPen(pen(edge, w)), p.drawPath(path))
        poly = lambda pts: QPolygonF([QPointF(*q) for q in pts])
        if name in ('unfold_sheet', 'fold_sheet', 'sheet_sync'):
            outline=QPainterPath();outline.moveTo(5,32);outline.lineTo(22,32)
            if name=='unfold_sheet':
                outline.lineTo(42,32);outline.lineTo(42,38);outline.lineTo(5,38)
            else:
                outline.lineTo(22,12);outline.lineTo(29,12);outline.lineTo(29,38);outline.lineTo(5,38)
            outline.closeSubpath();fl(outline,soft)
            st(acc,3)
            if name=='sheet_sync':
                p.drawArc(QRectF(29,5,14,14),30*16,290*16)
                p.drawPolyline(poly([(39,4),(44,7),(40,11)]))
            elif name=='unfold_sheet':
                p.drawArc(QRectF(17,6,22,22),0,150*16)
                p.drawPolyline(poly([(35,18),(40,18),(40,12)]))
            else:
                p.drawArc(QRectF(29,12,14,17),0,140*16)
                p.drawPolyline(poly([(30,9),(28,15),(34,16)]))
        elif name == 'file':
            body = QPainterPath(); body.moveTo(8, 8); body.lineTo(34, 8); body.lineTo(41, 15); body.lineTo(41, 41); body.lineTo(8, 41); body.closeSubpath()
            fl(body, soft)
            fl(_rounded(14, 8, 17, 10, 1.5), QColor(acc), ink, 2.2)
            fl(_rounded(13, 26, 22, 15, 2), QColor(0, 0, 0, 0), ink, 2.4)
        elif name == 'sketch':
            fl(_rounded(7, 18, 26, 22, 3), soft)
            st(acc, 3.2); p.drawLine(QPointF(24, 30), QPointF(39, 12))
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(20, 33), (22, 26), (28, 31)]))
        elif name == 'extrude':
            fl(_rounded(8, 28, 26, 14, 2), soft)
            st(acc, 3.0); p.drawLine(QPointF(21, 24), QPointF(21, 6)); p.drawPolyline(poly([(14, 13), (21, 6), (28, 13)]))
            st(ink, 2.0); pn = pen(ink, 2.0); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawRect(QRectF(8, 10, 0, 0))
        elif name == 'revolve':
            prof = QPainterPath(); prof.moveTo(25, 8); prof.lineTo(38, 8); prof.lineTo(34, 24); prof.lineTo(38, 40); prof.lineTo(25, 40); prof.closeSubpath()
            fl(prof, soft)
            pn = pen(ink, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush); p.drawLine(QPointF(24, 4), QPointF(24, 44))
            st(acc, 3.0); p.drawArc(QRectF(5, 29, 38, 14), 200 * 16, 140 * 16)
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(42, 33), (35, 31), (40, 40)]))
        elif name == 'shell':
            cup = QPainterPath(); cup.moveTo(8, 9); cup.lineTo(8, 42); cup.lineTo(40, 42); cup.lineTo(40, 9); cup.lineTo(33, 9); cup.lineTo(33, 34); cup.lineTo(15, 34); cup.lineTo(15, 9); cup.closeSubpath()
            fl(cup, soft)
            st(acc, 3.0); p.drawLine(QPointF(16, 27), QPointF(32, 27)); p.drawPolyline(poly([(20, 22), (24, 27), (28, 22)]))
        elif name == 'sheet':
            fl(_rounded(6, 30, 24, 7, 1.5), soft)
            st(acc, 3.0); p.drawPolyline(poly([(26, 33), (34, 33), (40, 12)]))
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(37, 6), (32, 15), (43, 15)]))
        elif name == 'flat':
            # rozwinięcie pudełka: dno z czterema ściankami (krzyż z wycięciami w narożnikach), linie gięcia tylko wewnątrz obrysu
            cross = QPainterPath(); cross.moveTo(15, 4); cross.lineTo(33, 4); cross.lineTo(33, 13); cross.lineTo(35, 15); cross.lineTo(44, 15)
            cross.lineTo(44, 33); cross.lineTo(35, 33); cross.lineTo(33, 35); cross.lineTo(33, 44); cross.lineTo(15, 44); cross.lineTo(15, 35)
            cross.lineTo(13, 33); cross.lineTo(4, 33); cross.lineTo(4, 15); cross.lineTo(13, 15); cross.lineTo(15, 13); cross.closeSubpath()
            fl(cross, soft, ink, 2.3)
            pn = pen(acc, 2.2); pn.setStyle(Qt.DashLine); pn.setDashPattern([2.2, 1.6]); p.setPen(pn); p.setBrush(Qt.NoBrush)
            for a, b in (((16, 15), (32, 15)), ((16, 33), (32, 33)), ((15, 16), (15, 32)), ((33, 16), (33, 32))):
                p.drawLine(QPointF(*a), QPointF(*b))
            st(ink, 1.6); p.drawEllipse(QPointF(24, 24), 3.2, 3.2)
        elif name == 'importdrawing':
            p.setBrush(soft); p.setPen(pen(ink, 2.4)); p.drawRoundedRect(QRectF(5, 12, 30, 31), 3, 3)
            st(ink, 2.0); p.drawRect(QRectF(10, 20, 12, 9)); p.drawEllipse(QPointF(16, 24.5), 2.2, 2.2)
            st(ink, 1.6); p.drawLine(QPointF(10, 35), QPointF(22, 35)); p.drawLine(QPointF(26, 20), QPointF(26, 29))
            fl(_rounded(30, 3, 14, 17, 2), QColor('#ffffff') if not white else QColor(255, 255, 255, 60), ink, 2.0)
            st(acc, 3.0); p.drawLine(QPointF(37, 9), QPointF(37, 26)); p.drawPolyline(poly([(31.5, 21), (37, 27), (42.5, 21)]))
        elif name == 'flange':
            fl(_rounded(6, 30, 22, 7, 1.5), soft)
            fl(_rounded(24, 8, 7, 29, 1.5), soft)
            st(acc, 3.0); p.drawLine(QPointF(40, 14), QPointF(40, 4))
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(40, 2), (35, 9), (45, 9)]))
        elif name == 'hem':
            fl(_rounded(4, 32, 22, 7, 1.5), soft)
            fl(_rounded(14, 9, 14, 7, 1.5), soft)
            st(ink, 2.2); p.setBrush(Qt.NoBrush); p.drawArc(QRectF(14, 9, 24, 24), 270 * 16, 180 * 16)
            st(acc, 3.0); p.drawLine(QPointF(14, 14), QPointF(14, 20))
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(14, 25), (9, 18), (19, 18)]))
        elif name == 'rules':
            fl(_rounded(6, 14, 36, 20, 2), soft)
            st(acc, 2.6)
            for x in (12, 20, 28, 36):
                p.drawLine(QPointF(x, 14), QPointF(x, 22 if x % 16 else 26))
        elif name == 'sweep':
            fl(_circle(12, 35, 7.5), soft)
            path = QPainterPath(); path.moveTo(12, 35); path.cubicTo(12, 12, 36, 38, 38, 11)
            st(acc, 3.2); p.drawPath(path)
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(38, 6), (32, 14), (44, 14)]))
        elif name == 'loft':
            lower = poly([(5, 41), (30, 41), (42, 32), (17, 32)]); upper = poly([(15, 17), (27, 17), (34, 10), (22, 10)])
            st(ink, 2.2)
            for a, b in (((5, 41), (15, 17)), ((30, 41), (27, 17)), ((42, 32), (34, 10)), ((17, 32), (22, 10))):
                p.drawLine(QPointF(*a), QPointF(*b))
            p.setBrush(soft); p.setPen(pen(ink, 2.4)); p.drawPolygon(lower)
            p.setBrush(QColor(acc)); p.setPen(pen(acc, 2.4)); p.drawPolygon(upper)
        elif name == 'surface':
            lower = poly([(5, 30), (30, 30), (43, 40), (18, 40)]); upper = poly([(8, 10), (30, 10), (41, 19), (19, 19)])
            p.setBrush(soft); p.setPen(pen(ink, 2.4)); p.drawPolygon(lower)
            p.setBrush(QColor(acc)); p.setPen(pen(acc, 2.2)); p.drawPolygon(upper)
            st(ink, 2.4); p.drawLine(QPointF(24, 22), QPointF(24, 28)); p.drawPolyline(poly([(20, 25), (24, 29), (28, 25)]))
        elif name == 'dist':
            fl(_circle(15, 22, 9), soft); st(ink, 2.4); p.drawEllipse(QPointF(15, 22), 9, 9); p.drawLine(QPointF(15, 18), QPointF(15, 26)); p.drawLine(QPointF(11, 22), QPointF(19, 22))
            st(ink, 2.6); p.drawLine(QPointF(42, 8), QPointF(42, 40))
            st(acc, 3.0); p.drawLine(QPointF(15, 22), QPointF(41, 22))
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(41, 22), (33, 18), (33, 26)]))
        elif name == 'dim':
            st(ink, 2.4); p.drawRect(QRectF(10, 7, 28, 14)); p.setBrush(soft); p.drawEllipse(QPointF(24, 14), 3.5, 3.5)
            st(ink, 2.0); p.drawLine(QPointF(10, 24), QPointF(10, 40)); p.drawLine(QPointF(38, 24), QPointF(38, 40))
            st(acc, 3.0); p.drawLine(QPointF(11, 34), QPointF(37, 34))
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(10, 34), (18, 30), (18, 38)])); p.drawPolygon(poly([(38, 34), (30, 30), (30, 38)]))
        elif name in ('drawing', 'autodrawing'):
            _draw_drawing(p, name, ink, acc, soft, pen)
        elif name == 'sheetdrawing':
            _draw_sheet_drawing(p, ink, acc, soft, pen)
        elif name in ('mdist', 'mangle', 'mrad', 'mprops'):
            _draw_measure(p, name, ink, acc, soft, pen)
        elif name == 'bool':
            a2, b2 = _rounded(6, 9, 25, 25, 4), _rounded(17, 15, 25, 25, 4)
            fl(a2, soft); fl(b2, QColor(0, 0, 0, 0))
            fl(a2.intersected(b2), QColor(acc), acc, 1.2)
            st(ink, 2.6); p.drawPath(a2); p.drawPath(b2)
        elif name == 'mod':
            path = QPainterPath(); path.moveTo(8, 40); path.lineTo(8, 14); path.lineTo(24, 14); path.arcTo(QRectF(12, 14, 24, 24), 90, -90); path.lineTo(40, 40); path.closeSubpath()
            path2 = QPainterPath(); path2.moveTo(8, 40); path2.lineTo(8, 10); path2.lineTo(24, 10); path2.arcTo(QRectF(8, 10, 32, 32), 90, -90); path2.lineTo(40, 40); path2.closeSubpath()
            fl(path2, soft)
            st(acc, 3.0); p.drawArc(QRectF(8, 10, 32, 32), 90 * 16, -90 * 16)
        elif name == 'mirror':
            fl(QPainterPath(), QColor(0, 0, 0, 0))
            tri = QPainterPath(); tri.moveTo(21, 10); tri.lineTo(21, 40); tri.lineTo(5, 40); tri.closeSubpath()
            tri2 = QPainterPath(); tri2.moveTo(27, 10); tri2.lineTo(27, 40); tri2.lineTo(43, 40); tri2.closeSubpath()
            fl(tri, soft); fl(tri2, QColor(acc), acc, 2.0)
            pn = pen(ink, 2.2); pn.setStyle(Qt.DashLine); p.setPen(pn); p.drawLine(QPointF(24, 5), QPointF(24, 44))
        elif name in ('undo', 'redo'):
            flip = name == 'redo'
            m = (lambda x: 48 - x) if flip else (lambda x: x)
            st(ink, 3.0)
            p.drawPolyline(poly([(m(15), 11), (m(7), 19), (m(15), 27)]))
            path = QPainterPath(); path.moveTo(m(8), 19); path.lineTo(m(28), 19); path.cubicTo(m(41), 19, m(41), 38, m(28), 38); path.lineTo(m(20), 38)
            p.drawPath(path)
        elif name.startswith('s_'):
            dot = lambda x, y, c=None: (p.setBrush(QColor(c or acc)), p.setPen(pen('#ffffff' if white else '#ffffff', 1.6)), p.drawEllipse(QPointF(x, y), 3.6, 3.6))
            sh = name[2:]
            if sh == 'line':
                st(ink, 3.0); p.drawLine(QPointF(10, 38), QPointF(38, 10)); dot(10, 38); dot(38, 10)
            elif sh == 'rect':
                fl(_rounded(8, 13, 32, 22, 2), soft); dot(8, 13); dot(40, 35)
            elif sh == 'circle':
                fl(_circle(24, 24, 15), soft); st(acc, 2.4); p.drawLine(QPointF(24, 24), QPointF(34.6, 13.4)); dot(24, 24, ink); dot(34.6, 13.4)
            elif sh == 'text':
                st(ink, 3.4); p.drawLine(QPointF(11, 12), QPointF(37, 12)); p.drawLine(QPointF(24, 12), QPointF(24, 38))
                st(acc, 3.0); p.drawLine(QPointF(17, 40), QPointF(31, 40))
            elif sh == 'ellipse':
                path = QPainterPath(); path.addEllipse(QRectF(6, 14, 36, 20)); fl(path, soft); dot(24, 24, acc)
            elif sh == 'slot':
                path = QPainterPath(); path.addRoundedRect(QRectF(6, 15, 36, 18), 9, 9); fl(path, soft); dot(15, 24); dot(33, 24)
            elif sh == 'polygon':
                pts = [(24 + 16 * math.sin(2 * math.pi * k / 5), 25 - 16 * math.cos(2 * math.pi * k / 5)) for k in range(5)]
                path = QPainterPath(); path.addPolygon(poly(pts + [pts[0]])); fl(path, soft); dot(24, 25, ink); dot(*pts[0])
            elif sh == 'arc':
                st(ink, 3.0); p.drawArc(QRectF(7, 17, 34, 34), 28 * 16, 124 * 16); dot(10.5, 30); dot(37.5, 30); dot(24, 17, ink)
            elif sh == 'point':
                st(ink, 2.4); p.drawLine(QPointF(24, 8), QPointF(24, 40)); p.drawLine(QPointF(8, 24), QPointF(40, 24)); dot(24, 24)
            elif sh == 'construction':
                pn = pen(acc, 3.0); pn.setStyle(Qt.DashLine); p.setPen(pn); p.setBrush(Qt.NoBrush); p.drawLine(QPointF(9, 38), QPointF(39, 10)); dot(9, 38, ink); dot(39, 10, ink)
            elif sh == 'measure':
                st(ink, 2.6); p.drawLine(QPointF(8, 31), QPointF(40, 31)); p.drawLine(QPointF(8, 24), QPointF(8, 38)); p.drawLine(QPointF(40, 24), QPointF(40, 38))
                st(acc, 3.0); p.drawLine(QPointF(15, 17), QPointF(33, 17)); p.drawPolyline(poly([(19, 13), (14, 17), (19, 21)])); p.drawPolyline(poly([(29, 13), (34, 17), (29, 21)]))
            elif sh == 'trim':
                st(ink, 2.8); p.drawLine(QPointF(14, 14), QPointF(40, 36)); p.drawLine(QPointF(14, 34), QPointF(40, 12))
                st(acc, 2.6); p.drawEllipse(QPointF(11, 12), 4.5, 4.5); p.drawEllipse(QPointF(11, 36), 4.5, 4.5)
        elif name in ('move', 'rotate'):
            if name == 'move':
                st(ink, 2.8)
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    p.drawLine(QPointF(24, 24), QPointF(24 + dx * 16, 24 + dy * 16))
                    tip = (24 + dx * 18, 24 + dy * 18)
                    p.drawPolyline(poly([(tip[0] - dx * 6 - dy * 5, tip[1] - dy * 6 + dx * 5), tip, (tip[0] - dx * 6 + dy * 5, tip[1] - dy * 6 - dx * 5)]))
                p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 24), 4.2, 4.2)
            else:
                st(ink, 3.0); p.drawArc(QRectF(9, 9, 30, 30), 40 * 16, 270 * 16)
                p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawPolygon(poly([(36, 10), (38, 22), (27, 17)]))
        elif name in ('eye', 'eyeoff'):
            eye = QPainterPath(); eye.moveTo(4, 24); eye.cubicTo(13, 9, 35, 9, 44, 24); eye.cubicTo(35, 39, 13, 39, 4, 24); eye.closeSubpath()
            fl(eye, soft)
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 24), 6, 6)
            if name == 'eyeoff':
                st(acc, 3.4); p.drawLine(QPointF(8, 41), QPointF(40, 7))
        elif name in ('lock', 'unlock'):
            st(ink, 3.0)
            sh = QPainterPath(); sh.moveTo(15, 22); sh.lineTo(15, 16); sh.arcTo(QRectF(15, 6, 18, 20), 180, -180)
            if name == 'lock':
                sh.lineTo(33, 22)
            else:
                sh.lineTo(33, 14)
            p.drawPath(sh)
            fl(_rounded(10, 22, 28, 20, 4), soft)
            p.setBrush(QColor(acc)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 31), 3.2, 3.2)
        elif name == 'solid':
            top = QPainterPath(); top.moveTo(24, 7); top.lineTo(41, 15); top.lineTo(24, 23); top.lineTo(7, 15); top.closeSubpath()
            left = QPainterPath(); left.moveTo(7, 15); left.lineTo(24, 23); left.lineTo(24, 42); left.lineTo(7, 33); left.closeSubpath()
            right = QPainterPath(); right.moveTo(41, 15); right.lineTo(24, 23); right.lineTo(24, 42); right.lineTo(41, 33); right.closeSubpath()
            fl(left, soft); fl(right, QColor(0, 0, 0, 0)); fl(top, QColor(acc), acc, 2.0)
            st(ink, 2.6); p.drawPath(left); p.drawPath(right)
        elif name == 'trash':
            st(ink, 2.8); p.drawLine(QPointF(9, 13), QPointF(39, 13)); p.drawPolyline(poly([(19, 13), (19, 8), (29, 8), (29, 13)]))
            body = QPainterPath(); body.moveTo(12, 13); body.lineTo(14, 41); body.lineTo(34, 41); body.lineTo(36, 13)
            fl(body, soft)
            st(acc, 2.6); p.drawLine(QPointF(20, 20), QPointF(20, 34)); p.drawLine(QPointF(28, 20), QPointF(28, 34))
        elif name == 'home':
            path = QPainterPath(); path.moveTo(7, 24); path.lineTo(24, 8); path.lineTo(41, 24); path.lineTo(36, 24); path.lineTo(36, 40); path.lineTo(12, 40); path.lineTo(12, 24); path.closeSubpath()
            fl(path, soft)
            fl(_rounded(20, 28, 8, 12, 1.5), QColor(acc), acc, 1.2)
        elif name == 'grid':
            st(ink, 2.4)
            for k in (9, 19, 29, 39):
                p.drawLine(QPointF(k, 8), QPointF(k, 40)); p.drawLine(QPointF(8, k), QPointF(40, k))
            st(acc, 3.0); p.drawLine(QPointF(24, 6), QPointF(24, 42)); p.drawLine(QPointF(6, 24), QPointF(42, 24))
        elif name == 'pattern':
            for r in range(2):
                for c in range(2):
                    fl(_rounded(7 + c * 18, 7 + r * 18, 14, 14, 3), QColor(acc) if (r, c) == (0, 0) else soft)
        elif name == 'cut':
            fl(_rounded(8, 14, 32, 26, 3), soft)
            st(acc, 3.0); p.drawEllipse(QPointF(24, 27), 7, 7); p.drawLine(QPointF(24, 20), QPointF(24, 6)); p.drawPolyline(poly([(18, 13), (24, 20), (30, 13)]))
        elif name == 'text':
            st(ink, 3.4); p.drawLine(QPointF(11, 12), QPointF(37, 12)); p.drawLine(QPointF(24, 12), QPointF(24, 38))
            st(acc, 3.0); p.drawLine(QPointF(17, 40), QPointF(31, 40))
        elif name == 'history':
            st(ink, 2.4); p.setBrush(Qt.NoBrush); p.drawEllipse(QPointF(24, 24), 16, 16)
            st(acc, 3.0); p.drawLine(QPointF(24, 24), QPointF(24, 13)); p.drawLine(QPointF(24, 24), QPointF(32, 28))
            st(acc, 3.0); p.drawPolyline(poly([(6, 12), (8, 21), (16, 18)]))
        elif name == 'layers':
            for k, y in enumerate((30, 20, 10)):
                q = poly([(24, y + 8), (42, y), (24, y - 8 + 0), (6, y)])
                p.setBrush(soft if k else QColor(acc)); p.setPen(pen(ink if k else acc, 2.4)); p.drawPolygon(poly([(24, y + 9), (42, y), (24, y - 9), (6, y)]))
    elif kind == 'f_about':
        p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE, 2.6)); p.drawEllipse(QPointF(24, 24), 17, 17)
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(24, 15), 2.8, 2.8)
        p.setPen(pen(BLUE, 3.6)); p.drawLine(QPointF(24, 22), QPointF(24, 34))
    elif kind == 'f_help':
        fill(_rounded(7, 9, 34, 30, 3), '#ffffff', BLUE)
        p.setPen(pen(BLUE, 2.2)); p.drawLine(QPointF(24, 9), QPointF(24, 39))
        p.setPen(pen(BLUE_SOFT, 2.4))
        for y in (17, 23, 29):
            p.drawLine(QPointF(11, y), QPointF(20, y)); p.drawLine(QPointF(28, y), QPointF(37, y))
        p.setBrush(QColor(ORANGE)); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(31, 9), QPointF(37, 9), QPointF(37, 21), QPointF(34, 18), QPointF(31, 21)]))
    elif kind in ('xray', 'xray_w'):
        ink = '#ffffff' if kind == 'xray_w' else '#324c68'
        p.setBrush(Qt.NoBrush)
        dashed = pen(ink, 1.8); dashed.setStyle(Qt.DashLine)
        p.setPen(dashed)
        p.drawRect(QRectF(15, 6, 24, 24)); p.drawLine(QPointF(15, 6), QPointF(6, 15)); p.drawLine(QPointF(39, 6), QPointF(30, 15)); p.drawLine(QPointF(39, 30), QPointF(30, 39))
        p.setPen(pen(ink, 2.4))
        p.drawRect(QRectF(6, 15, 24, 24)); p.drawLine(QPointF(6, 15), QPointF(15, 6)); p.drawLine(QPointF(30, 15), QPointF(39, 6)); p.drawLine(QPointF(30, 39), QPointF(39, 30))
        p.drawLine(QPointF(30, 15), QPointF(39, 6)); p.drawLine(QPointF(39, 6), QPointF(39, 30))
    elif kind.startswith('v_'):
        dot = lambda x, y, c=ORANGE: (p.setBrush(QColor(c)), p.setPen(Qt.NoPen), p.drawEllipse(QPointF(x, y), 3.2, 3.2))
        thin = lambda c=BLUE, w=2.2: (p.setBrush(Qt.NoBrush), p.setPen(pen(c, w)))
        if kind == 'v_rect2':
            fill(_rounded(8, 12, 32, 24, 2), BLUE_SOFT, BLUE); dot(8, 12); dot(40, 36)
        elif kind == 'v_rectC':
            fill(_rounded(8, 12, 32, 24, 2), BLUE_SOFT, BLUE); thin(ORANGE, 1.8); p.drawLine(QPointF(24, 24), QPointF(40, 12)); dot(24, 24, GREEN); dot(40, 12)
        elif kind == 'v_rect3':
            poly = QPolygonF([QPointF(6, 30), QPointF(26, 12), QPointF(42, 24), QPointF(22, 42)])
            p.setBrush(QColor(BLUE_SOFT)); p.setPen(pen(BLUE)); p.drawPolygon(poly); dot(6, 30); dot(26, 12); dot(22, 42)
        elif kind == 'v_circle':
            fill(_circle(24, 24, 15), BLUE_SOFT, BLUE); thin(ORANGE, 1.8); p.drawLine(QPointF(24, 24), QPointF(39, 24)); dot(24, 24, GREEN); dot(39, 24)
        elif kind == 'v_circle2':
            fill(_circle(24, 24, 15), BLUE_SOFT, BLUE); thin(ORANGE, 1.8); p.drawLine(QPointF(9, 24), QPointF(39, 24)); dot(9, 24); dot(39, 24)
        elif kind == 'v_circle3':
            fill(_circle(24, 24, 15), BLUE_SOFT, BLUE); dot(24, 9); dot(10.8, 31.5); dot(37.2, 31.5)
        elif kind == 'v_tan':
            thin(INK, 2.4); p.drawLine(QPointF(6, 42), QPointF(42, 42)); p.drawLine(QPointF(6, 42), QPointF(6, 6))
            fill(_circle(22, 26, 16), BLUE_SOFT, BLUE); dot(6, 26, GREEN); dot(22, 42, GREEN)
    elif kind == 'check':
        p.setPen(pen('#ffffff', 4)); p.drawPolyline(QPolygonF([QPointF(11, 25), QPointF(21, 35), QPointF(38, 14)]))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def badge(kind: str, color: str = BLUE, size: int = 34, plain: bool = False) -> QPixmap:
    """Okrągła plakietka z ikoną (nagłówek panelu)."""
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    if plain:       # sama grafika, bez zaokrąglonego kwadratu
        pm = pixmap(kind, size, scale)
        pm.setDevicePixelRatio(scale)
        return pm
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    tint, edge = QColor(color), QColor(color)
    tint.setAlpha(34); edge.setAlpha(120)
    p.setBrush(tint); p.setPen(QPen(edge, 1.4 * scale))
    p.drawRoundedRect(QRectF(scale, scale, (size - 2) * scale, (size - 2) * scale), 10 * scale, 10 * scale)
    p.end()
    kind = {'one': 't_extrude', 'union': 't_bool', 'fillet': 't_mod', 'chamfer': 't_mod', 'mirror': 't_mirror', 'sym': 't_mirror',
            'sketch': 't_sketch', 'extrude': 't_extrude', 'bool': 't_bool'}.get(kind, kind)
    inner = pixmap(kind, size - 8, scale)
    q = QPainter(pm)
    q.drawPixmap(4 * scale, 4 * scale, inner)
    q.end()
    pm.setDevicePixelRatio(scale)
    return pm
