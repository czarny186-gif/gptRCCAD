"""Kostka orientacji w prawym górnym rogu (jak ViewCube w Fusion 360): obraca się razem z kamerą; klik ściany = widok z tej strony,
klik narożnika lub krawędzi = widok izometryczny / ukośny."""
from __future__ import annotations
import itertools
import math
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

FACES = {  # nazwa widoku -> (normalna, etykieta)
    'Z': ((0, 0, 1), 'GÓRA'), '-Z': ((0, 0, -1), 'DÓŁ'),
    'X': ((1, 0, 0), 'PRAWO'), '-X': ((-1, 0, 0), 'LEWO'),
    '-Y': ((0, -1, 0), 'PRZÓD'), 'Y': ((0, 1, 0), 'TYŁ'),
}
# wierzchołki ścian (kolejność dookoła; pierwsza krawędź to „dół” napisu)
QUADS = {
    'Z': [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)],
    '-Z': [(-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)],
    'X': [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)],
    '-X': [(-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)],
    '-Y': [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)],
    'Y': [(1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)],
}


class ViewCube(QWidget):
    faceClicked = Signal(str)
    directionClicked = Signal(float, float)   # azymut, elewacja (stopnie)
    rotateClicked = Signal(float, float)      # zmiana azymutu, zmiana elewacji (stopnie)
    rollClicked = Signal(float)               # obrót obrazu w płaszczyźnie ekranu (stopnie, + = w lewo)

    SCALE = 24.0

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setFixedSize(138, 138)
        self.setMouseTracking(True)
        self.hover = None          # ('face', nazwa) | ('corner', wektor) | ('edge', wektor) | ('arrow', nazwa) | ('roll', ±1)
        self.setCursor(Qt.PointingHandCursor)

    # ---- rzut: ortograficzny, zgodny z kamerą widoku 3D (także z obrotem obrazu) ----
    def _basis(self):
        axes = getattr(self.view, 'screen_axes', None)
        if axes is not None:
            r, u, c = axes()
            return np.asarray(c, float), np.asarray(r, float), np.asarray(u, float)
        az, el = math.radians(float(self.view.opts['azimuth'])), math.radians(float(self.view.opts['elevation']))
        c = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        r = np.array([-math.sin(az), math.cos(az), 0.0])
        u = np.array([-math.sin(el) * math.cos(az), -math.sin(el) * math.sin(az), math.cos(el)])
        return c, r, u

    def _project(self, p):
        c, r, u = self._basis()
        p = np.asarray(p, float)
        return QPointF(self.width() / 2 + float(p @ r) * self.SCALE, self.height() / 2 - float(p @ u) * self.SCALE), float(p @ c)

    def _visible_faces(self):
        c, _, _ = self._basis()
        out = []
        for name, (n, label) in FACES.items():
            depth = float(np.dot(n, c))
            if depth > 1e-3:
                out.append((depth, name))
        return sorted(out)

    ARROWS = {'up': (0, -1, 0, 90.0), 'down': (0, 1, 0, -90.0), 'left': (-1, 0, -90.0, 0), 'right': (1, 0, 90.0, 0)}
    ROLLS = {1: (-1, -1), -1: (1, -1)}      # obrót w lewo (lewy górny róg), w prawo (prawy górny róg)

    def _arrow_center(self, name):
        dx, dy = self.ARROWS[name][:2]
        return QPointF(self.width() / 2 + dx * (self.width() / 2 - 11), self.height() / 2 + dy * (self.height() / 2 - 11))

    def _roll_center(self, sign):
        sx, sy = self.ROLLS[sign]
        return QPointF(self.width() / 2 + sx * (self.width() / 2 - 17), self.height() / 2 + sy * (self.height() / 2 - 17))

    def _hit(self, pos):
        c, _, _ = self._basis()
        for sign in self.ROLLS:
            ctr = self._roll_center(sign)
            if math.hypot(ctr.x() - pos.x(), ctr.y() - pos.y()) <= 12:
                return ('roll', sign)
        for name in self.ARROWS:
            ctr = self._arrow_center(name)
            if math.hypot(ctr.x() - pos.x(), ctr.y() - pos.y()) <= 11:
                return ('arrow', name)
        for sx, sy, sz in itertools.product((-1, 1), repeat=3):
            v = np.array([sx, sy, sz])
            pt, depth = self._project(v)
            if float(v @ c) > 0 and math.hypot(pt.x() - pos.x(), pt.y() - pos.y()) <= 9:
                return ('corner', v)
        for a, b in itertools.combinations(itertools.product((-1, 1), repeat=3), 2):
            if sum(1 for i in range(3) if a[i] != b[i]) != 1:
                continue
            m = (np.array(a) + np.array(b)) / 2.0
            if float(m @ c) > 0.2:
                pt, _ = self._project(m * 1.0)
                if math.hypot(pt.x() - pos.x(), pt.y() - pos.y()) <= 7:
                    return ('edge', m / np.linalg.norm(m))
        for depth, name in reversed(self._visible_faces()):
            poly = QPolygonF([self._project(q)[0] for q in QUADS[name]])
            if poly.containsPoint(QPointF(pos), Qt.OddEvenFill):
                return ('face', name)
        return None

    # ---- rysowanie ----
    def _face_points(self, name, inset=0.0):
        """Narożniki ściany; inset > 0 odsuwa je do środka ściany (fazowane krawędzie kostki)."""
        quad = np.array(QUADS[name], float)
        if inset:
            centre = quad.mean(axis=0)
            quad = centre + (quad - centre) * (1.0 - inset)
        return [self._project(q)[0] for q in quad]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        # podkład: miękka karta z lekkim cieniem
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 60, 95, 18))
        p.drawRoundedRect(QRectF(2, 4, w - 3, h - 4), 18, 18)
        card = QLinearGradient(0, 0, 0, h)
        card.setColorAt(0, QColor(255, 255, 255, 235))
        card.setColorAt(1, QColor(240, 246, 252, 225))
        p.setBrush(card)
        p.setPen(QPen(QColor('#d3dfeb'), 1))
        p.drawRoundedRect(QRectF(.5, .5, w - 2, h - 3), 17, 17)
        # pierścień orientacji pod kostką
        centre = QPointF(w / 2, h / 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(120, 150, 185, 45), 3))
        p.drawEllipse(centre, 52, 52)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1))
        p.drawEllipse(centre, 54, 54)
        c, r, u = self._basis()
        # cień kostki
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(40, 70, 110, 28))
        p.drawEllipse(QPointF(w / 2 + 2, h / 2 + 5), 34, 30)
        light = np.array([-.35, .55, .76])
        light /= np.linalg.norm(light)
        for depth, name in self._visible_faces():
            normal = np.array(FACES[name][0], float)
            outer = QPolygonF(self._face_points(name))
            inner = QPolygonF(self._face_points(name, .14))
            hot = self.hover == ('face', name)
            # krawędź (fazka) ciemniejsza, środek ściany jaśniejszy - kostka wygląda na zaokrągloną
            bright = .84 + .16 * max(0.0, float(normal @ light))
            edge = QColor.fromHsvF(.58, .22, bright * .80)
            p.setBrush(edge)
            p.setPen(QPen(QColor('#7f98b3'), 1.1))
            p.drawPolygon(outer)
            pts = [pt for pt in inner]
            grad = QLinearGradient(pts[3], pts[1])
            if hot:
                grad.setColorAt(0, QColor('#dcedff'))
                grad.setColorAt(1, QColor('#9fcbff'))
            else:
                grad.setColorAt(0, QColor.fromHsvF(.58, .03, min(1.0, bright * 1.06)))
                grad.setColorAt(1, QColor.fromHsvF(.58, .09, bright * .96))
            p.setBrush(grad)
            p.setPen(QPen(QColor(255, 255, 255, 170), 1.0))
            p.drawPolygon(inner)
            # napis zgodny z perspektywą ściany
            size = 100.0
            tr = QTransform()
            if QTransform.quadToQuad(QPolygonF([QPointF(0, size), QPointF(size, size), QPointF(size, 0), QPointF(0, 0)]), inner, tr):
                p.save()
                p.setTransform(tr, True)
                font = QFont()
                font.setFamilies(['Segoe UI Semibold', 'Segoe UI', 'Arial'])
                font.setWeight(QFont.DemiBold)
                font.setPixelSize(19 if len(FACES[name][1]) <= 4 else 17)
                font.setLetterSpacing(QFont.PercentageSpacing, 104)
                p.setFont(font)
                p.setPen(QColor(255, 255, 255, 150))
                p.drawText(QRectF(0, 1.5, size, size), Qt.AlignCenter, FACES[name][1])
                p.setPen(QColor('#1d5fae' if hot else '#3c5a78'))
                p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, FACES[name][1])
                p.restore()
        # strzałki przerzucania widoku o 90°
        for name, (dx, dy, _, _) in self.ARROWS.items():
            ctr = self._arrow_center(name)
            hot = self.hover == ('arrow', name)
            if hot:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(47, 135, 232, 40))
                p.drawEllipse(ctr, 10, 10)
            tri = QPolygonF([QPointF(ctr.x() + dx * 6.5, ctr.y() + dy * 6.5),
                             QPointF(ctr.x() - dx * 4.5 - dy * 6.5, ctr.y() - dy * 4.5 + dx * 6.5),
                             QPointF(ctr.x() - dx * 4.5 + dy * 6.5, ctr.y() - dy * 4.5 - dx * 6.5)])
            p.setPen(QPen(QColor('#2f87e8') if hot else QColor('#8ea9c6'), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor('#2f87e8') if hot else QColor('#a9c0d8'))
            p.drawPolygon(tri)
        # strzałki obrotu obrazu w płaszczyźnie (o 90°)
        for sign in self.ROLLS:
            self._draw_roll(p, sign, self.hover == ('roll', sign))
        if self.hover and self.hover[0] in ('corner', 'edge'):
            pt, _ = self._project(self.hover[1] if self.hover[0] == 'corner' else self.hover[1] * 1.2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(47, 135, 232, 60))
            p.drawEllipse(pt, 9, 9)
            p.setBrush(QColor('#2f87e8'))
            p.setPen(QPen(QColor('#ffffff'), 2))
            p.drawEllipse(pt, 5, 5)
        # osie świata w rogu
        origin = QPointF(16, h - 16)
        for axis, color, label in (((1, 0, 0), '#df5a5e', 'X'), ((0, 1, 0), '#3aa77a', 'Y'), ((0, 0, 1), '#4a8fe0', 'Z')):
            e, _ = self._project(np.array(axis) * 1.9)
            e = QPointF(origin.x() + (e.x() - w / 2) * .40, origin.y() + (e.y() - h / 2) * .40)
            p.setPen(QPen(QColor(color), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(origin, e)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(e, 2.2, 2.2)
            font = QFont('Segoe UI')
            font.setBold(True)
            font.setPixelSize(10)
            p.setFont(font)
            p.setPen(QColor(color))
            p.drawText(QPointF(e.x() + 2.5, e.y() + 3.5), label)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#6c7f93'))
        p.drawEllipse(origin, 2, 2)
        p.end()

    def _draw_roll(self, p, sign, hot):
        """Zaokrąglona strzałka „obróć obraz o 90°” (w lewo w lewym górnym rogu, w prawo w prawym)."""
        ctr = self._roll_center(sign)
        if hot:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(47, 135, 232, 40))
            p.drawEllipse(ctr, 12, 12)
        color = QColor('#2f87e8') if hot else QColor('#8ea9c6')
        radius = 7.0
        rect = QRectF(ctr.x() - radius, ctr.y() - radius, 2 * radius, 2 * radius)
        start = -50 if sign > 0 else 230      # łuk ok. 240°: w lewo (przeciwnie do wskazówek) albo w prawo
        span = 240 if sign > 0 else -240
        path = QPainterPath()
        path.arcMoveTo(rect, start)
        path.arcTo(rect, start, span)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)
        end = math.radians(start + span)
        tip = QPointF(ctr.x() + radius * math.cos(end), ctr.y() - radius * math.sin(end))
        # grot styczny do łuku
        tangent = np.array([-math.sin(end), -math.cos(end)]) * (1 if span > 0 else -1)
        normal = np.array([-tangent[1], tangent[0]])
        a = np.array([tip.x(), tip.y()]) + tangent * 4.2
        b = np.array([tip.x(), tip.y()]) - tangent * 1.2 + normal * 3.6
        c = np.array([tip.x(), tip.y()]) - tangent * 1.2 - normal * 3.6
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF([QPointF(*a), QPointF(*b), QPointF(*c)]))

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        key = None if hit is None else (hit[0], hit[1] if hit[0] in ('face', 'arrow', 'roll') else tuple(np.round(hit[1], 3)))
        old = None if self.hover is None else (self.hover[0], self.hover[1] if self.hover[0] in ('face', 'arrow', 'roll') else tuple(np.round(self.hover[1], 3)))
        if key != old:
            self.hover = hit
            tips = {'roll': 'Obróć widok w płaszczyźnie ekranu o 90°', 'arrow': 'Przerzuć widok o 90°',
                    'face': 'Widok z tej strony', 'corner': 'Widok ukośny', 'edge': 'Widok ukośny'}
            self.setToolTip(tips.get(hit[0], '') if hit else '')
            self.update()

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        hit = self._hit(event.position())
        if hit is None:
            return
        if hit[0] == 'roll':
            self.rollClicked.emit(90.0 * hit[1])
        elif hit[0] == 'arrow':
            self.rotateClicked.emit(*self.ARROWS[hit[1]][2:])
        elif hit[0] == 'face':
            self.faceClicked.emit(hit[1])
        else:
            d = np.asarray(hit[1], float)
            d /= np.linalg.norm(d)
            self.directionClicked.emit(math.degrees(math.atan2(d[1], d[0])), math.degrees(math.asin(max(-1, min(1, d[2])))))
