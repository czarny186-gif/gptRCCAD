"""Okno rysunku technicznego: wybór rzutów, wymiarów i arkusza, pomiary na rysunku oraz zapis do PDF / DXF / SVG / JPG."""
from __future__ import annotations
import math
from pathlib import Path
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QRunnable, QObject, Qt, QSize, QSizeF, QThreadPool, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPageSize, QPainter, QPdfWriter, QPen, QPolygonF
from PySide6.QtGui import QIcon, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFontComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

import dataclasses
from . import FULL_VERSION, drawing as D, icons

K = 10.0        # jednostek rysowania na milimetr arkusza (254 dpi)
INK = QColor('#14202e')
STYLES = {'visible': (0.5, None), 'hidden': (0.25, [10, 4]), 'center': (0.2, [28, 4, 4, 4]), 'dim': (0.2, None), 'frame': (0.7, None), 'thin': (0.2, None),
          'bend_up': (0.3, None), 'bend_down': (0.3, [14, 6])}      # linie gięcia rozwinięcia: w górę ciągła, w dół przerywana
FILTERS = 'PDF (*.pdf);;DXF (*.dxf);;SVG (*.svg);;JPG (*.jpg)'


def paint_drawing(p: QPainter, d: D.Drawing, k: float = K, color=None):
    """Rysuje arkusz w układzie, w którym 1 mm = k jednostek malarza (ta sama funkcja rysuje ekran, PDF, SVG i JPG)."""
    H = d.height
    ink = QColor(color) if color is not None else INK
    pt = lambda q: QPointF(q[0] * k, (H - q[1]) * k)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    for prim in d.prims:
        if isinstance(prim, D.Poly):
            width, dash = STYLES.get(prim.style, STYLES['thin'])
            pen = QPen(ink, width * k)
            pen.setCapStyle(Qt.FlatCap)
            pen.setJoinStyle(Qt.RoundJoin)
            if dash:
                pen.setDashPattern([float(x) for x in dash])
            if prim.fill:
                p.setBrush(QBrush(ink))
                p.setPen(QPen(ink, 0.1 * k))
                p.drawPolygon(QPolygonF([pt(q) for q in prim.pts]))
                continue
            p.setBrush(Qt.NoBrush)
            p.setPen(pen)
            points = [pt(q) for q in prim.pts]
            if prim.closed:
                p.drawPolygon(QPolygonF(points))
            else:
                p.drawPolyline(QPolygonF(points))
        else:
            font = QFont(prim.font or 'Arial')
            font.setPixelSize(max(4, int(round(prim.h * k))))
            font.setBold(bool(prim.bold))
            font.setItalic(bool(prim.italic))
            p.setFont(font)
            p.setPen(QPen(ink))
            metrics = QFontMetricsF(font)
            p.save()
            p.translate(pt((prim.x, prim.y)))
            p.rotate(-prim.rot)
            for i, line in enumerate(prim.text.split('\n')):
                width = metrics.horizontalAdvance(line)
                p.drawText(QPointF({'l': 0.0, 'c': -width / 2, 'r': -width}[prim.align], i * prim.h * 1.3 * k), line)
            p.restore()


def render_image(d: D.Drawing, ppmm: float = 10.0) -> QImage:
    image = QImage(int(round(d.width * ppmm)), int(round(d.height * ppmm)), QImage.Format_RGB32)
    image.fill(Qt.white)
    p = QPainter(image)
    paint_drawing(p, d, ppmm)
    p.end()
    return image


def export_drawing(d: D.Drawing, path):
    """Zapis według rozszerzenia: .pdf, .svg, .jpg / .jpeg, .dxf."""
    path = str(path)
    ext = Path(path).suffix.lower()
    if ext == '.dxf':
        D.save_dxf(d, path)
    elif ext in ('.jpg', '.jpeg'):
        if not render_image(d, 12.0).save(path, 'JPG', 95):
            raise RuntimeError('Nie udało się zapisać pliku JPG.')
    elif ext == '.svg':
        from PySide6.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setResolution(254)
        gen.setSize(QSize(int(round(d.width * K)), int(round(d.height * K))))
        gen.setViewBox(QRectF(0, 0, d.width * K, d.height * K))
        gen.setTitle(d.name or 'Rysunek RCCAD')
        p = QPainter(gen)
        p.fillRect(QRectF(0, 0, d.width * K, d.height * K), Qt.white)
        paint_drawing(p, d, K)
        p.end()
    elif ext == '.pdf':
        writer = QPdfWriter(path)
        writer.setResolution(254)
        writer.setPageSize(QPageSize(QSizeF(d.width, d.height), QPageSize.Millimeter))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        writer.setTitle(d.name or 'Rysunek RCCAD')
        p = QPainter(writer)
        paint_drawing(p, d, K)
        p.end()
    else:
        raise RuntimeError('Obsługiwane formaty: PDF, DXF, SVG, JPG.')
    return path


# ---------------------------------------------------------------------------
class _Signals(QObject):
    done = Signal(int, object)
    failed = Signal(int, str)


class _Job(QRunnable):
    def __init__(self, ticket, function):
        super().__init__()
        self.ticket, self.function, self.signals = ticket, function, _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.ticket, self.function())
        except Exception as exc:
            self.signals.failed.emit(self.ticket, str(exc))


ORANGE = QColor('#f08a00')
BLUE = QColor('#2f87e8')


def view_icon(name, size=40):
    """Sześcian z zaznaczoną (pomarańczową) ścianą, z której patrzymy - czytelny wybór rzutu."""
    k = 3
    pm = QPixmap(size * k, size * k)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    sx = lambda c: (c[0] + c[1]) / math.sqrt(2)
    sy = lambda c: (-c[0] + c[1] + 2 * c[2]) / math.sqrt(6)
    scale = size * k * 0.34
    ox, oy = size * k * 0.5, size * k * 0.55
    pt = lambda c: QPointF(ox + (sx(c) - sx((.5, .5, .5))) * scale * 1.35, oy - (sy(c) - sy((.5, .5, .5))) * scale * 1.35)
    faces = {'top': [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], 'bottom': [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
             'front': [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], 'back': [(0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)],
             'left': [(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)], 'right': [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]}
    shown = ('top', 'front', 'right')
    for face in ('bottom', 'back', 'left', 'top', 'front', 'right'):
        poly = QPolygonF([pt(c) for c in faces[face]])
        chosen = name == 'iso' and face in shown or name == face
        hidden = face not in shown
        pen = QPen(QColor('#324c68'), 1.6 * k / 2)
        if hidden:
            pen.setStyle(Qt.DashLine)
            pen.setColor(QColor('#8aa3ba'))
        p.setPen(pen)
        p.setBrush(QColor(240, 138, 0, 200) if chosen else (QColor(0, 0, 0, 0) if hidden else QColor('#dbe9f8')))
        p.drawPolygon(poly)
    p.end()
    return QIcon(pm)


class TextDialog(QDialog):
    """Okno ustawień tekstu: treść wielowierszowa (Enter = nowa linia), czcionka, wysokość liter; przycisk zatwierdza i dodaje tekst na rysunek."""

    def __init__(self, parent, style, existing=False, has_leader=False):
        super().__init__(parent)
        self.setWindowTitle('Tekst na rysunku')
        self.setModal(True)
        self.action = None
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        title = QLabel('Edytuj tekst' if existing else 'Nowy tekst na rysunku')
        title.setObjectName('cardtitle')
        lay.addWidget(title)
        self.edit = QPlainTextEdit(style.get('text', ''))
        self.edit.setPlaceholderText('Wpisz tekst. Enter przechodzi do następnej linii.')
        self.edit.setMinimumHeight(110)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(style.get('font', 'Arial')))
        row.addWidget(self.font, 1)
        self.size = QDoubleSpinBox()
        self.size.setRange(1.0, 80.0)
        self.size.setDecimals(1)
        self.size.setSingleStep(0.5)
        self.size.setSuffix(' mm')
        self.size.setValue(float(style.get('h', 3.5)))
        self.size.setToolTip('Wysokość liter na arkuszu')
        row.addWidget(self.size)
        self.bold = QPushButton('B')
        self.italic = QPushButton('I')
        for b, name in ((self.bold, 'bold'), (self.italic, 'italic')):
            b.setCheckable(True)
            b.setChecked(bool(style.get(name)))
            b.setFixedSize(32, 30)
            b.setStyleSheet('QPushButton{border:1px solid #b9cde0;border-radius:7px;background:white;font-weight:700;}'
                            'QPushButton:checked{background:#2f87e8;color:white;border-color:#2f87e8;}')
            row.addWidget(b)
        self.italic.setStyleSheet(self.italic.styleSheet() + 'QPushButton{font-style:italic;}')
        lay.addLayout(row)
        hint = QLabel('Po dodaniu przeciągnij tekst w inne miejsce, a z pomarańczowego uchwytu wyciągnij strzałkę do elementu, którego dotyczy.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#6b8499;font-size:11px;')
        lay.addWidget(hint)
        buttons = QHBoxLayout()
        if existing:
            delete = QPushButton('Usuń tekst')
            delete.clicked.connect(lambda: self._finish('delete'))
            buttons.addWidget(delete)
            if has_leader:
                nolead = QPushButton('Usuń strzałkę')
                nolead.clicked.connect(lambda: self._finish('noleader'))
                buttons.addWidget(nolead)
        buttons.addStretch(1)
        cancel = QPushButton('Anuluj')
        cancel.clicked.connect(self.reject)
        ok = QPushButton('Zapisz zmiany' if existing else 'Zatwierdź i dodaj na rysunek')
        ok.setDefault(False)
        ok.setAutoDefault(False)
        ok.setStyleSheet('QPushButton{background:#2f87e8;color:white;border:0;border-radius:9px;padding:7px 14px;font-weight:700;}QPushButton:hover{background:#1f6fc9;}')
        ok.clicked.connect(lambda: self._finish('ok'))
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self.edit.setFocus()
        self.edit.selectAll()

    def _finish(self, action):
        self.action = action
        self.accept()

    def values(self):
        return dict(text=self.edit.toPlainText().strip('\n').rstrip(), font=self.font.currentFont().family(), h=float(self.size.value()),
                    bold=self.bold.isChecked(), italic=self.italic.isChecked())


class Canvas(QWidget):
    info = Signal(str)
    manual_changed = Signal()
    want_tool = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(240, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.drawing: D.Drawing | None = None        # rysunek bazowy (bez wymiarów ręcznych)
        self.manual = []
        self.zoom, self.origin = 1.0, QPointF(20, 20)
        self.tool = 'dim'
        self.pending = None
        self.pairs = []
        self.hover = None            # (punkt, czy_przyciągnięty) dla pomiaru
        self.hot = None              # element pod kursorem w trybie wymiarowania
        self.placing = None          # wymiar "wyciągany" myszą
        self._drag = None
        self._moved = False
        self.message = 'Liczę rzuty…'
        self._label_rects = []
        self.text_h = 3.5
        self.text_style = dict(font='Arial', bold=False, italic=False)
        self._text_drag = None
        self._leader_drag = None

    # --- dane ---
    def composed(self):
        return D.compose(self.drawing, self.manual) if self.drawing is not None else None

    def fit(self):
        if self.drawing is None:
            return
        z = min((self.width() - 30) / self.drawing.width, (self.height() - 30) / self.drawing.height)
        self.zoom = max(0.05, z)
        self.origin = QPointF((self.width() - self.drawing.width * self.zoom) / 2, (self.height() - self.drawing.height * self.zoom) / 2)
        self.update()

    def set_drawing(self, d):
        first = self.drawing is None or (self.drawing.width, self.drawing.height) != (d.width, d.height)
        self.drawing = d
        self.pairs, self.pending, self.hot, self.placing = [], None, None, None
        if first:
            self.fit()
        self.update()

    def to_screen(self, q):
        return QPointF(self.origin.x() + q[0] * self.zoom, self.origin.y() + (self.drawing.height - q[1]) * self.zoom)

    def to_sheet(self, pos):
        return ((pos.x() - self.origin.x()) / self.zoom, self.drawing.height - (pos.y() - self.origin.y()) / self.zoom)

    def resizeEvent(self, event):
        if self.drawing is not None and not self.pairs:
            self.fit()
        super().resizeEvent(event)

    # --- wskazywanie elementów do wymiarowania ---
    def feature_at(self, sheet):
        tol = 8.0 / self.zoom
        best, score = None, 1e9
        for f in self.drawing.features:
            if f['kind'] == 'circle':
                dist = math.hypot(sheet[0] - f['c'][0], sheet[1] - f['c'][1])
                ring = abs(dist - f['r'])
                if ring <= tol or (f['full'] and dist < f['r']):
                    value = (0.0 if ring <= tol else 0.5 * tol) + f['r'] * 1e-3
                    if value < score:
                        best, score = f, value
        if best is not None:
            return best
        for f in self.drawing.features:
            if f['kind'] == 'line':
                a, b = f['a'], f['b']
                dx, dy = b[0] - a[0], b[1] - a[1]
                ll = dx * dx + dy * dy
                t = max(0.0, min(1.0, ((sheet[0] - a[0]) * dx + (sheet[1] - a[1]) * dy) / ll)) if ll else 0.0
                dist = math.hypot(sheet[0] - a[0] - t * dx, sheet[1] - a[1] - t * dy)
                if dist <= tol and dist < score:
                    best, score = f, dist
        return best

    def _dim_of(self, f):
        return dict(view=f['view'], kind=f['kind'], mdl=f['mdl'], off=(0.0, 0.0))

    def start_placing(self, f):
        m = self._dim_of(f)
        m['off'] = D.default_offset(self.drawing, m)
        self.placing = m
        self.info.emit('Przesuń wymiar w wybrane miejsce i kliknij, aby go zostawić. Esc / prawy przycisk – rezygnacja.')
        self.update()

    def place_at(self, sheet):
        """Zostawia wymiar w miejscu sheet (współrzędne arkusza)."""
        if self.placing is None:
            return
        ax, ay = D.anchor_of(self.drawing, self.placing)
        self.placing['off'] = (sheet[0] - ax, sheet[1] - ay)
        self.manual.append(self.placing)
        self.placing = None
        self.info.emit(f'Wymiarów dodanych ręcznie: {len(self.manual)}. Najedź na kolejny otwór lub krawędź.')
        self.manual_changed.emit()
        self.update()

    def undo_dim(self):
        if self.manual:
            self.manual.pop()
            self.manual_changed.emit()
            self.update()

    def clear_dims(self):
        self.manual = []
        self.placing = None
        self.manual_changed.emit()
        self.update()

    # --- mysz i klawiatura ---
    def wheelEvent(self, event):
        if self.drawing is None:
            return
        f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        pos = event.position()
        new = max(0.05, min(40.0, self.zoom * f))
        f = new / self.zoom
        self.origin = QPointF(pos.x() - (pos.x() - self.origin.x()) * f, pos.y() - (pos.y() - self.origin.y()) * f)
        self.zoom = new
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.placing, self.pending = None, None
            self.update()
        elif event.key() in (Qt.Key_Backspace, Qt.Key_Delete) and self.placing is None:
            self.undo_dim()
        else:
            super().keyPressEvent(event)

    # --- punkty odniesienia: tylko prawdziwa geometria bryły ---
    def ref_at(self, sheet):
        """Punkt charakterystyczny pod kursorem: środek otworu, koniec lub środek krawędzi, a w ostateczności punkt na krawędzi."""
        d = self.drawing
        tp, te = 10.0 / self.zoom, 7.0 / self.zoom
        best, score = None, 1e9

        def consider(dist, limit, ref):
            nonlocal best, score
            if dist <= limit and dist < score:
                best, score = ref, dist

        for f in d.features:
            v = f['view']
            if f['kind'] == 'fcenter':
                consider(math.hypot(sheet[0] - f['c'][0], sheet[1] - f['c'][1]), tp,
                         dict(view=v, kind='fcenter', pt=tuple(f['mdl']), line=None, sheet=f['c'], label='środek figury'))
            elif f['kind'] == 'circle':
                consider(math.hypot(sheet[0] - f['c'][0], sheet[1] - f['c'][1]), tp,
                         dict(view=v, kind='center', pt=tuple(f['mdl'][0]), line=None, sheet=f['c'], label='środek otworu'))
                if not f['full']:
                    consider(math.hypot(sheet[0] - f['mid'][0], sheet[1] - f['mid'][1]), tp,
                             dict(view=v, kind='end', pt=tuple(f['mdl'][3]), line=None, sheet=f['mid'], label='środek łuku'))
            elif f['kind'] == 'line':
                name = f.get('name', 'krawędź')
                for key, idx in (('a', 0), ('b', 1)):
                    consider(math.hypot(sheet[0] - f[key][0], sheet[1] - f[key][1]), tp,
                             dict(view=v, kind='end', pt=tuple(f['mdl'][idx]), line=None, sheet=f[key], label='koniec: ' + name if 'name' in f else 'koniec krawędzi'))
                mid = ((f['a'][0] + f['b'][0]) / 2, (f['a'][1] + f['b'][1]) / 2)
                consider(math.hypot(sheet[0] - mid[0], sheet[1] - mid[1]), tp * 0.8,
                         dict(view=v, kind='end', pt=D.model_of(d, v, mid), line=None, sheet=mid, label='środek: ' + name if 'name' in f else 'środek krawędzi'))
        if best is not None:
            return best
        for s in d.snaps:      # końce krawędzi krzywych (łuki, fasolki, elipsy)
            v = D.view_at(d, s)
            if v:
                consider(math.hypot(sheet[0] - s[0], sheet[1] - s[1]), tp, dict(view=v, kind='end', pt=D.model_of(d, v, s), line=None, sheet=s, label='koniec krawędzi'))
        if best is not None:
            return best
        for f in d.features:
            v = f['view']
            if f['kind'] == 'line':
                a, b = f['a'], f['b']
                dx, dy = b[0] - a[0], b[1] - a[1]
                ll = dx * dx + dy * dy
                t = max(0.0, min(1.0, ((sheet[0] - a[0]) * dx + (sheet[1] - a[1]) * dy) / ll)) if ll else 0.0
                q = (a[0] + t * dx, a[1] + t * dy)
                (ma, mb) = f['mdl']
                consider(math.hypot(sheet[0] - q[0], sheet[1] - q[1]), te,
                         dict(view=v, kind='edge', pt=(ma[0] + t * (mb[0] - ma[0]), ma[1] + t * (mb[1] - ma[1])), line=(ma, mb), sheet=q, label=f.get('name', 'krawędź')))
            elif f['kind'] == 'circle':
                dist = math.hypot(sheet[0] - f['c'][0], sheet[1] - f['c'][1])
                if dist > 1e-9:
                    u = ((sheet[0] - f['c'][0]) / dist, (sheet[1] - f['c'][1]) / dist)
                    c, r = f['mdl'][0], f['mdl'][1]
                    consider(abs(dist - f['r']), te, dict(view=v, kind='arc', pt=(c[0] + u[0] * r, c[1] + u[1] * r), line=None,
                                                         sheet=(f['c'][0] + u[0] * f['r'], f['c'][1] + u[1] * f['r']), label='obrys otworu'))
        return best

    def _pair_points(self, r1, r2):
        P, Q, slanted = D.dist_points(r1, r2)
        return P, Q, slanted

    def _pair_sheet(self, pair):
        r1, r2 = pair
        P, Q, _ = self._pair_points(r1, r2)
        v = r1['view']
        return D.place_in(self.drawing, v, P), D.place_in(self.drawing, v, Q)

    def _make_dist(self, r1, r2):
        if r1['view'] != r2['view']:
            self.info.emit('Wymiar można dodać tylko między elementami tego samego rzutu.')
            return None
        P, Q, slanted = self._pair_points(r1, r2)
        if math.hypot(Q[0] - P[0], Q[1] - P[1]) < 1e-6:
            self.info.emit('Punkty leżą w tym samym miejscu – brak odległości.')
            return None
        radial = {r1['kind'], r2['kind']} & {'fcenter'} and not ({r1['kind'], r2['kind']} & {'edge'})
        m = dict(view=r1['view'], kind='dist', mdl=(P, Q), off=(0.0, 0.0), aligned=bool(slanted or radial), radial=bool(radial))
        m['off'] = D.default_offset(self.drawing, m)
        return m

    def mousePressEvent(self, event):
        if self.drawing is None:
            return
        self.setFocus()
        left = event.button() == Qt.LeftButton
        if event.button() == Qt.RightButton and (self.placing is not None or self.pending is not None):
            self.placing, self.pending = None, None
            self.update()
            return
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self._drag = (event.position(), QPointF(self.origin))
            self.setCursor(Qt.ClosedHandCursor)
            return
        if not left:
            return
        sheet = self.to_sheet(event.position())
        if self.placing is not None:
            self.place_at(sheet)
            return
        if self.tool == 'dim':
            f = self.feature_at(sheet)
            if f is not None:
                self.start_placing(f)
            else:
                self._drag = (event.position(), QPointF(self.origin))
                self.setCursor(Qt.ClosedHandCursor)
        elif self.tool == 'text':
            self._text_press(event.position(), sheet)
        elif self.tool == 'measure':
            for rect, index in self._label_rects:      # klik w gotowy pomiar zamienia go w wymiar do wyciągnięcia
                if rect.contains(event.position()):
                    self._pair_to_dim(index)
                    return
            ref = self.ref_at(sheet)
            if ref is None:
                self.info.emit('Pomiar tylko po prawdziwej geometrii: kliknij środek otworu, koniec lub środek krawędzi albo samą krawędź.')
                return
            if self.pending is None:
                self.pending = ref
            else:
                pair = (self.pending, ref)
                self.pending = None
                P, Q = self._pair_sheet(pair) if pair[0]['view'] == pair[1]['view'] else (pair[0]['sheet'], pair[1]['sheet'])
                self.pairs.append(pair)
                self.info.emit(self.describe(pair) + '   Kliknij wynik, aby zamienić go w wymiar.')
            self.update()
        elif self.tool == 'dist':
            ref = self.ref_at(sheet)
            if ref is None:
                self.info.emit('Kliknij środek otworu, koniec lub środek krawędzi albo samą krawędź.')
                return
            if self.pending is None:
                self.pending = ref
                self.info.emit('Teraz kliknij drugi element (np. krawędź – wymiar od środka otworu do krawędzi).')
            else:
                m = self._make_dist(self.pending, ref)
                self.pending = None
                if m is not None:
                    self.placing = m
                    self.info.emit('Przesuń wymiar w wybrane miejsce i kliknij, aby go zostawić.')
            self.update()

    # --- tekst na rysunku ---
    def add_text(self, sheet, style):
        view = D.view_at(self.drawing, sheet, pad=14.0)
        m = dict(kind='text', view=view, mdl=D.model_of(self.drawing, view, sheet) if view else tuple(sheet), leader=None, **style)
        self.manual.append(m)
        self.manual_changed.emit()
        self.update()
        return m

    def _text_screen_box(self, m):
        box = D.text_box(self.drawing, m)
        if box is None:
            return None
        a, b = self.to_screen((box[0], box[1])), self.to_screen((box[2], box[3]))
        return QRectF(QPointF(min(a.x(), b.x()), min(a.y(), b.y())), QPointF(max(a.x(), b.x()), max(a.y(), b.y())))

    def _handle_center(self, m):
        rect = self._text_screen_box(m)
        return None if rect is None else QPointF(rect.right() + 11, rect.center().y())

    def _text_hit(self, pos):
        for m in reversed(self.manual):
            if m['kind'] == 'text':
                rect = self._text_screen_box(m)
                if rect is not None and rect.adjusted(-3, -3, 3, 3).contains(pos):
                    return m
        return None

    def _handle_hit(self, pos):
        for m in reversed(self.manual):
            if m['kind'] == 'text':
                c = self._handle_center(m)
                if c is not None and math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= 9:
                    return m
        return None

    def _text_press(self, pos, sheet):
        m = self._handle_hit(pos)
        if m is not None:
            self._leader_drag = m
            self.info.emit('Przeciągnij strzałkę do elementu, którego dotyczy tekst (przyciąga się do geometrii) i puść.')
            return
        m = self._text_hit(pos)
        if m is not None:
            self._text_drag = dict(m=m, start=pos, base=D.text_pos(self.drawing, m), moved=False)
            return
        self.open_text_dialog(None, sheet)

    def open_text_dialog(self, target, sheet=None):
        style = dict(self.text_style, h=self.text_h) if target is None else {k: target.get(k) for k in ('text', 'font', 'h', 'bold', 'italic') if target.get(k) is not None}
        dlg = TextDialog(self.window(), style, existing=target is not None, has_leader=bool(target and target.get('leader')))
        if not dlg.exec():
            return None
        values = dlg.values()
        if dlg.action == 'delete' and target is not None:
            self.manual.remove(target)
        elif dlg.action == 'noleader' and target is not None:
            target['leader'] = None
            target.update({k: v for k, v in values.items() if values['text']})
        elif dlg.action == 'ok':
            if not values['text']:
                if target is not None:
                    self.manual.remove(target)
            else:
                self.text_style = {k: values[k] for k in ('font', 'bold', 'italic')}
                self.text_h = values['h']
                if target is None:
                    target = self.add_text(sheet, values)
                else:
                    target.update(values)
        self.manual_changed.emit()
        self.update()
        return target

    def _drag_text(self, pos, sheet):
        drag = self._text_drag
        if drag is None:
            return
        if not drag['moved'] and math.hypot(pos.x() - drag['start'].x(), pos.y() - drag['start'].y()) < 4:
            return
        drag['moved'] = True
        dx, dy = pos.x() - drag['start'].x(), -(pos.y() - drag['start'].y())
        new = (drag['base'][0] + dx / self.zoom, drag['base'][1] + dy / self.zoom)
        m = drag['m']
        view = D.view_at(self.drawing, new, pad=14.0)
        m['view'] = view
        m['mdl'] = D.model_of(self.drawing, view, new) if view else new
        self.update()

    def _drag_leader(self, sheet):
        m = self._leader_drag
        ref = self.ref_at(sheet)
        if ref is not None:
            m['leader'] = dict(view=ref['view'], mdl=tuple(ref['pt']))
            self.hover = ref
        else:
            view = D.view_at(self.drawing, sheet, pad=14.0)
            m['leader'] = dict(view=view, mdl=D.model_of(self.drawing, view, sheet) if view else tuple(sheet))
            self.hover = None
        self.update()

    def _text_release(self):
        if self._leader_drag is not None:
            self._leader_drag = None
            self.hover = None
            self.manual_changed.emit()
        elif self._text_drag is not None:
            drag, self._text_drag = self._text_drag, None
            if drag['moved']:
                self.manual_changed.emit()
            else:
                self.open_text_dialog(drag['m'])
        self.update()

    def _pair_to_dim(self, index):
        pair = self.pairs[index]
        m = self._make_dist(*pair)
        if m is None:
            return
        del self.pairs[index]
        self.want_tool.emit('dim')          # przełączenie narzędzia czyści stan, więc wymiar ustawiamy dopiero po nim
        self.placing = m
        self.info.emit('Wymiar gotowy do wyciągnięcia: przesuń go w wybrane miejsce i kliknij.')
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            start, origin = self._drag
            self.origin = QPointF(origin.x() + event.position().x() - start.x(), origin.y() + event.position().y() - start.y())
            self.update()
            return
        if self.drawing is None:
            return
        sheet = self.to_sheet(event.position())
        if self.placing is not None:
            ax, ay = D.anchor_of(self.drawing, self.placing)
            self.placing['off'] = (sheet[0] - ax, sheet[1] - ay)
        elif self.tool == 'text':
            if self._leader_drag is not None:
                self._drag_leader(sheet)
            elif self._text_drag is not None:
                self._drag_text(event.position(), sheet)
            else:
                over_handle = self._handle_hit(event.position()) is not None
                self.setCursor(Qt.PointingHandCursor if over_handle else Qt.SizeAllCursor if self._text_hit(event.position()) else Qt.IBeamCursor)
        elif self.tool in ('measure', 'dist'):
            self.hover = self.ref_at(sheet)
            self.setCursor(Qt.CrossCursor if self.hover is not None else Qt.ForbiddenCursor)
            if self.hover is not None:
                self.info.emit(self.hover['label'])
        else:
            hot = self.feature_at(sheet)
            if hot is not self.hot:
                self.hot = hot
                if hot is not None:
                    self.info.emit(self._feature_text(hot) + ' — kliknij, aby wyciągnąć wymiar.')
            self.setCursor(Qt.PointingHandCursor if hot is not None else Qt.OpenHandCursor)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.tool == 'text' and event.button() == Qt.LeftButton and (self._leader_drag is not None or self._text_drag is not None):
            self._text_release()
            return
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.OpenHandCursor if self.tool == 'dim' else Qt.IBeamCursor if self.tool == 'text' else Qt.CrossCursor)

    def _feature_text(self, f):
        if f['kind'] == 'circle':
            return ('Otwór Ø' + D.fmt(2 * f['mdl'][1])) if f['full'] else ('Łuk R' + D.fmt(f['mdl'][1]))
        a, b = f['mdl']
        return 'Krawędź ' + D.fmt(math.hypot(b[0] - a[0], b[1] - a[1])) + ' mm'

    def set_tool(self, tool):
        self.tool = tool
        self.pending, self.hover, self.placing, self.hot = None, None, None, None
        self._text_drag = self._leader_drag = None
        self.setCursor(Qt.OpenHandCursor if tool == 'dim' else Qt.IBeamCursor if tool == 'text' else Qt.CrossCursor)
        self.update()

    def clear_measures(self):
        self.pairs, self.pending = [], None
        self.update()

    def describe(self, pair):
        P, Q, _ = self._pair_points(*pair)
        dx, dy = Q[0] - P[0], Q[1] - P[1]
        return f'Odległość: {D.fmt(math.hypot(dx, dy))} mm   (poziomo {D.fmt(abs(dx))} mm, pionowo {D.fmt(abs(dy))} mm)'

    # --- rysowanie ---
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#dfe7ef'))
        self._label_rects = []
        if self.drawing is None:
            p.setPen(QColor('#29475e'))
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
            return
        d = self.drawing
        sheet = QRectF(self.origin.x(), self.origin.y(), d.width * self.zoom, d.height * self.zoom)
        p.fillRect(sheet.translated(4, 4), QColor(0, 0, 0, 40))
        p.fillRect(sheet, Qt.white)
        p.save()
        p.translate(self.origin)
        p.scale(self.zoom / K, self.zoom / K)
        paint_drawing(p, self.composed(), K)
        ghost = None
        if self.placing is not None:
            ghost = self.placing
        elif self.tool == 'dim' and self.hot is not None:
            ghost = self._dim_of(self.hot)
            ghost['off'] = D.default_offset(d, ghost)
        if ghost is not None:
            paint_drawing(p, dataclasses.replace(d, prims=D.manual_prims(d, ghost)), K, color=ORANGE)
        p.restore()
        p.setRenderHint(QPainter.Antialiasing, True)
        if self.tool == 'dim' and self.hot is not None and self.placing is None:
            self._highlight(p, self.hot)
        elif self.placing is not None and self.placing['kind'] != 'dist':
            self._highlight(p, dict(self.placing, **(D.resolve_feature(d, self.placing) or {})))
        for index, pair in enumerate(self.pairs):
            if pair[0]['view'] == pair[1]['view']:
                a, b = self._pair_sheet(pair)
            else:
                a, b = pair[0]['sheet'], pair[1]['sheet']
            self._measure_line(p, a, b, ORANGE, index=index)
        if self.tool == 'text':
            for m in self.manual:
                if m['kind'] != 'text':
                    continue
                rect = self._text_screen_box(m)
                c = self._handle_center(m)
                if rect is None:
                    continue
                pen = QPen(QColor('#f08a00'), 1)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect.adjusted(-2, -2, 2, 2))
                p.setBrush(QColor('#f08a00'))
                p.setPen(QPen(QColor('white'), 1.5))
                p.drawEllipse(c, 6, 6)
                p.setPen(QPen(QColor('white'), 1.6))
                p.drawLine(QPointF(c.x() - 3, c.y()), QPointF(c.x() + 3, c.y()))
                p.drawLine(QPointF(c.x() + 0.5, c.y() - 2.5), QPointF(c.x() + 3, c.y()))
                p.drawLine(QPointF(c.x() + 0.5, c.y() + 2.5), QPointF(c.x() + 3, c.y()))
            if self._leader_drag is not None and self.hover is not None:
                self._dot(p, self.hover['sheet'], QColor('#1f9d55'))
        if self.tool in ('measure', 'dist'):
            p.setPen(QPen(QColor('#7fb2ea'), 1.6))
            for f in d.features:
                if f['kind'] == 'fcenter':
                    c = self.to_screen(f['c'])
                    p.drawLine(QPointF(c.x() - 5, c.y()), QPointF(c.x() + 5, c.y()))
                    p.drawLine(QPointF(c.x(), c.y() - 5), QPointF(c.x(), c.y() + 5))
            if self.pending is not None:
                self._dot(p, self.pending['sheet'], ORANGE)
                if self.hover is not None and self.placing is None:
                    if self.hover['view'] == self.pending['view']:
                        P, Q = self._pair_sheet((self.pending, self.hover))
                    else:
                        P, Q = self.pending['sheet'], self.hover['sheet']
                    self._measure_line(p, P, Q, ORANGE, dashed=True)
            if self.hover is not None and self.placing is None:
                self._dot(p, self.hover['sheet'], QColor('#1f9d55'))

    def _highlight(self, p, f):
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ORANGE, 3.5))
        if f['kind'] == 'circle':
            c = self.to_screen(f['c'])
            p.drawEllipse(c, f['r'] * self.zoom, f['r'] * self.zoom)
        else:
            p.drawLine(self.to_screen(f['a']), self.to_screen(f['b']))

    def _dot(self, p, q, color):
        p.setPen(QPen(color, 2))
        p.setBrush(color)
        p.drawEllipse(self.to_screen(q), 4, 4)

    def _measure_line(self, p, a, b, color, dashed=False, index=None):
        pen = QPen(color, 2)
        if dashed:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        sa, sb = self.to_screen(a), self.to_screen(b)
        p.drawLine(sa, sb)
        self._dot(p, a, color)
        self._dot(p, b, color)
        text = D.fmt(math.hypot(b[0] - a[0], b[1] - a[1]) / self.drawing.scale) + ' mm'
        mid = QPointF((sa.x() + sb.x()) / 2, (sa.y() + sb.y()) / 2)
        font = QFont('Arial', 10)
        font.setBold(True)
        p.setFont(font)
        w = QFontMetricsF(font).horizontalAdvance(text) + 12
        box = QRectF(mid.x() - w / 2, mid.y() - 24, w, 20)
        if index is not None:
            self._label_rects.append((box.adjusted(-4, -4, 4, 8), index))
        p.setPen(QPen(color, 1))
        p.setBrush(QColor(255, 250, 238))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor('#7a4300'))
        p.drawText(box, Qt.AlignCenter, text)


QSS = """
QMainWindow, QWidget#root { background:#eef3f8; }
QWidget#side, QScrollArea#sidescroll, QWidget#sidebody { background:transparent; border:0; }
QFrame#card { background:white; border:1px solid #cfdcea; border-radius:14px; }
QFrame#bar { background:white; border:1px solid #cfdcea; border-radius:14px; }
QLabel { color:#29475e; background:transparent; }
QLabel#cardtitle { font-size:13px; font-weight:700; color:#1d3a56; }
QLabel#hint { font-size:11px; color:#6b8499; }
QLabel#status { background:#fff7e8; border:1px solid #f3cf8e; border-radius:10px; padding:7px 12px; color:#7a4300; font-size:12px; }
QCheckBox { spacing:8px; padding:3px 0; color:#29475e; font-size:12px; }
QComboBox { background:white; border:1px solid #b9cde0; border-radius:8px; padding:4px 8px; min-height:24px; }
QToolButton#tile { background:#f4f8fc; border:1px solid #d3e0ec; border-radius:11px; color:#29475e; font-size:10px; padding:3px 0 2px 0; }
QToolButton#tile:hover { background:#e6f1fc; }
QToolButton#tile:checked { background:#dcecff; border:2px solid #2f87e8; color:#1d3a56; font-weight:700; }
QToolButton#big { background:transparent; border:1px solid transparent; border-radius:11px; color:#29475e; font-size:11px; font-weight:600; padding:5px 10px 3px 10px; min-width:62px; }
QToolButton#big:hover { background:#e6f1fc; }
QToolButton#big:checked { background:#2f87e8; color:white; }
QToolButton#primary { background:#2f87e8; color:white; border-radius:11px; font-size:11px; font-weight:700; padding:5px 14px 3px 14px; min-width:70px; }
QToolButton#primary:hover { background:#1f6fc9; }
"""


def _card(title, icon=None):
    frame = QFrame()
    frame.setObjectName('card')
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(6)
    label = QLabel(title)
    label.setObjectName('cardtitle')
    lay.addWidget(label)
    return frame, lay


def _big(text, icon_name, checkable=False, primary=False, tip=''):
    b = QToolButton()
    b.setObjectName('primary' if primary else 'big')
    b.setText(text)
    b.setIcon(QIcon(icons.pixmap('t_' + icon_name + ('_w' if primary else ''), 30)))
    b.setIconSize(QSize(30, 30))
    b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    b.setCheckable(checkable)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class DrawingWindow(QMainWindow):
    """Osobne, niemodalne okno. Rzuty liczone są w tle, zmiana opcji przelicza tylko rozmieszczenie."""

    def __init__(self, shape, name='Bryła', parent=None, views=None, bends=None, sheet=None, iso_shape=None, checked=None):
        """views: rzuty dostępne w oknie (np. ('top',) dla płaskiego rysunku wczytanego z SVG / DXF); None = wszystkie."""
        super().__init__(parent)
        self._only_views = tuple(views) if views else None
        self._checked_views = tuple(checked) if checked else None
        self.setWindowTitle(f'Rysunek techniczny — {name}')
        self.setWindowFlag(Qt.Window, True)
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        w, h = (min(1280, int(avail.width() * 0.92)), min(820, int(avail.height() * 0.9))) if avail else (1100, 720)
        self.resize(w, h)
        self.setMinimumSize(min(760, w), min(520, h))
        self.setStyleSheet(QSS)
        self.source = D.DrawingSource(shape, name, bends, sheet, iso_shape)
        self.pool = QThreadPool.globalInstance()
        self._ticket = 0
        self._busy = False
        self._again = False
        self._jobs = []
        self.drawing = None

        root = QWidget()
        root.setObjectName('root')
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 8)
        outer.setSpacing(8)

        # --- pasek narzędzi ---
        bar = QFrame()
        bar.setObjectName('bar')
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(4)
        self.dim_btn = _big('Wymiaruj', 'dim', True, tip='Najedź na otwór lub krawędź – obok pokaże się wymiar. Kliknij, wyciągnij w wybrane miejsce i kliknij ponownie.')
        self.dist_btn = _big('Odległość', 'dist', True, tip='Kliknij dwa elementy (np. środek otworu i krawędź) – wymiar między nimi wyciągniesz w bok.')
        self.text_btn = _big('Tekst', 'text', True, tip='Kliknij miejsce na arkuszu i wpisz tekst (Enter zatwierdza). Kliknięcie istniejącego tekstu pozwala go zmienić.')
        self.measure_btn = _big('Mierz', 'mdist', True, tip='Kliknij dwa punkty rysunku – wynik w mm bryły (nie trafia do pliku).')
        self.dim_btn.setChecked(True)
        self.dim_btn.clicked.connect(lambda: self._tool('dim'))
        self.measure_btn.clicked.connect(lambda: self._tool('measure'))
        self.dist_btn.clicked.connect(lambda: self._tool('dist'))
        self.text_btn.clicked.connect(lambda: self._tool('text'))
        self.undo_btn = _big('Cofnij wymiar', 'undo', tip='Usuwa ostatnio dodany wymiar (Backspace)')
        self.clear_btn = _big('Usuń wymiary', 'trash', tip='Usuwa wszystkie wymiary dodane ręcznie i pomiary')
        self.fit_btn = _big('Dopasuj', 'home', tip='Cały arkusz w oknie')
        self.save_btn = _big('Zapisz…', 'file', primary=True, tip='PDF, DXF, SVG lub JPG')
        self.undo_btn.clicked.connect(lambda: self.canvas.undo_dim())
        self.clear_btn.clicked.connect(self._clear_all)
        self.fit_btn.clicked.connect(lambda: self.canvas.fit())
        self.save_btn.clicked.connect(self.save)
        for b in (self.dim_btn, self.dist_btn, self.text_btn, self.measure_btn):
            bl.addWidget(b)
        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setStyleSheet('color:#d3e0ec;'); bl.addWidget(sep)
        for b in (self.undo_btn, self.clear_btn, self.fit_btn):
            bl.addWidget(b)
        bl.addStretch(1)
        bl.addWidget(self.save_btn)
        outer.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(10)
        scroll = QScrollArea()
        scroll.setObjectName('sidescroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(322)
        self.side_scroll = scroll
        side = QWidget()
        side.setObjectName('sidebody')
        side.setFixedWidth(300)       # stała szerokość = szerokość widoku przewijania minus pasek, więc nic nie wystaje poza prawą krawędź
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 8, 0)
        sl.setSpacing(10)

        card, cl = _card('Rzuty')
        grid = QGridLayout()
        grid.setSpacing(5)
        self.view_boxes = {}
        spots = {'front': (0, 0), 'back': (0, 1), 'top': (0, 2), 'bottom': (0, 3), 'left': (1, 0), 'right': (1, 1), 'iso': (1, 2)}
        short = {'top': 'Góra', 'right': 'Prawy', 'front': 'Przód', 'left': 'Lewy', 'back': 'Tył', 'bottom': 'Dół', 'iso': 'Izo'}
        for key, (r, c) in spots.items():
            t = QToolButton()
            t.setObjectName('tile')
            t.setCheckable(True)
            t.setChecked(key in (self._checked_views or self._only_views or ('front', 'top', 'right')))
            t.setEnabled(self._only_views is None or key in self._only_views)
            t.setIcon(view_icon(key, 32))
            t.setIconSize(QSize(32, 32))
            t.setText(short[key])
            t.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            t.setMinimumWidth(44)
            t.setFixedHeight(56)
            t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            t.setToolTip(D.VIEWS[key][0])
            t.setCursor(Qt.PointingHandCursor)
            t.toggled.connect(self.request)
            grid.addWidget(t, r, c)
            self.view_boxes[key] = t
        for c in range(4):
            grid.setColumnStretch(c, 1)
        cl.addLayout(grid)
        sl.addWidget(card)

        card, cl = _card('Arkusz')
        self.sheet = QComboBox()
        for s in D.SHEETS:
            self.sheet.addItem('Format ' + s, s)
        self.orient = QComboBox()
        self.orient.addItem('Poziomo', True)
        self.orient.addItem('Pionowo', False)
        self.proj = QComboBox()
        self.proj.addItem('Metoda europejska (1)', 'eu')
        self.proj.addItem('Metoda amerykańska (3)', 'us')
        self.scale = QComboBox()
        self.scale.addItem('Skala automatyczna', None)
        for s in D.SCALES:
            self.scale.addItem(f'Skala {s:g}:1' if s >= 1 else f'Skala 1:{1 / s:g}', s)
        for combo in (self.sheet, self.orient, self.proj, self.scale):
            combo.currentIndexChanged.connect(self.request)
            cl.addWidget(combo)
        sl.addWidget(card)

        card, cl = _card('Tekst na rysunku')
        self.text_size = QComboBox()
        for h in (2.5, 3.5, 5.0, 7.0, 10.0):
            self.text_size.addItem(f'Wysokość liter {D.fmt(h)} mm', h)
        self.text_size.setCurrentIndex(1)
        self.text_size.currentIndexChanged.connect(lambda *_: setattr(self.canvas, 'text_h', self.text_size.currentData()))
        cl.addWidget(self.text_size)
        sl.addWidget(card)

        card, cl = _card('Opisy automatyczne')
        hint = QLabel('Własne wymiary dodasz myszą na rysunku (przycisk Wymiaruj).')
        hint.setObjectName('hint'); hint.setWordWrap(True)
        cl.addWidget(hint)
        self.opt = {}
        for key, text, on in (('overall', 'Wymiary gabarytowe', False), ('circles', 'Średnice i promienie', False),
                              ('details', 'Wszystkie wymiary konturu', False),
                              ('centers', 'Osie symetrii otworów', True), ('hidden', 'Krawędzie niewidoczne (kreskowane)', True)):
            box = QCheckBox(text)
            if sheet:       # rysunek blachy do gięcia: wymiary całości i otworów, bez krawędzi spodu (powtarzają obrys)
                on = {'overall': True, 'circles': True, 'hidden': False}.get(key, on)
            box.setChecked(on)
            box.toggled.connect(self.request)
            cl.addWidget(box)
            box.setStyleSheet('QCheckBox{font-size:12px;}')
            if key == 'details':
                box.setToolTip('Boki wielokątów, proste krawędzie fasolek i wycięć, łuki, cała długość fasolki i położenie otworów od krawędzi rzutu')
            self.opt[key] = box
        sl.addWidget(card)
        sl.addStretch(1)
        scroll.setWidget(side)
        body.addWidget(scroll)

        self.canvas = Canvas()
        self.canvas.setCursor(Qt.OpenHandCursor)
        self.canvas.info.connect(self._info)
        self.canvas.want_tool.connect(self._tool)
        body.addWidget(self.canvas, 1)
        outer.addLayout(body, 1)

        self.status = QLabel('Liczę rzuty…')
        self.status.setObjectName('status')
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.setCentralWidget(root)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._start)
        self._timer.start()

    def _info(self, text):
        self.status.setText(text)

    def _tool(self, tool):
        self.dim_btn.setChecked(tool == 'dim')
        self.measure_btn.setChecked(tool == 'measure')
        self.dist_btn.setChecked(tool == 'dist')
        self.text_btn.setChecked(tool == 'text')
        self.canvas.set_tool(tool)
        self.status.setText({'dim': 'Najedź na otwór lub krawędź – obok pokaże się wymiar do wyciągnięcia.',
                             'dist': 'Kliknij pierwszy element (środek otworu, koniec lub środek krawędzi, krawędź), potem drugi – np. krawędź.',
                             'text': 'Kliknij miejsce na arkuszu, wpisz tekst i naciśnij Enter. Kliknięcie istniejącego tekstu pozwala go zmienić.',
                             'measure': 'Kliknij dwa elementy bryły (przyciągają się do środków otworów i krawędzi). Kliknięcie wyniku zamienia go w wymiar.'}[tool])

    def _clear_all(self):
        self.canvas.clear_dims()
        self.canvas.clear_measures()

    # --- ustawienia ---
    def settings(self):
        return dict(views=tuple(k for k, b in self.view_boxes.items() if b.isChecked()), sheet=self.sheet.currentData(),
                    landscape=self.orient.currentData(), projection=self.proj.currentData(), scale=self.scale.currentData(),
                    overall=self.opt['overall'].isChecked(), circles=self.opt['circles'].isChecked(),
                    centers=self.opt['centers'].isChecked(), hidden=self.opt['hidden'].isChecked(), details=self.opt['details'].isChecked())

    def apply_settings(self, s):
        for key, box in self.view_boxes.items():
            box.blockSignals(True)
            box.setChecked(key in s['views'])
            box.blockSignals(False)
        for combo, value in ((self.sheet, s['sheet']), (self.orient, s['landscape']), (self.proj, s['projection']), (self.scale, s['scale'])):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        for key, box in self.opt.items():
            box.blockSignals(True)
            box.setChecked(bool(s[key]))
            box.blockSignals(False)
        self.request()

    def request(self, *_):
        self._timer.start()

    def _start(self):
        if self._busy:
            self._again = True
            return
        s = self.settings()
        if not s['views']:
            self.status.setText('Zaznacz co najmniej jeden rzut.')
            return
        self._busy = True
        self.status.setText('Liczę rzuty…')
        self._ticket += 1
        job = _Job(self._ticket, lambda: D.build_drawing(self.source, version=FULL_VERSION, **s))
        job.signals.done.connect(self._done)
        job.signals.failed.connect(self._failed)
        self._jobs.append(job)
        self.pool.start(job)

    def _finish(self, ticket):
        self._busy = False
        self._jobs = [j for j in self._jobs if j.ticket != ticket]
        if self._again:
            self._again = False
            self._start()

    def _done(self, ticket, drawing):
        self.drawing = drawing
        self.canvas.set_drawing(drawing)
        self.status.setText(f'Arkusz {drawing.sheet}, skala {drawing.scale_text}. Najedź na otwór lub krawędź i kliknij, aby wyciągnąć wymiar. Kółko – powiększenie, prawy przycisk – przesuwanie.')
        self._finish(ticket)

    def _failed(self, ticket, message):
        self.status.setText('Nie udało się utworzyć rysunku: ' + message)
        self._finish(ticket)

    def save(self):
        final = self.canvas.composed()
        if final is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Zapisz rysunek techniczny', f'{self.source.name}.pdf', FILTERS)
        if not path:
            return
        if not Path(path).suffix:
            path += '.pdf'
        try:
            export_drawing(final, path)
            self.status.setText('Zapisano: ' + path)
        except Exception as exc:
            self.status.setText('Nie udało się zapisać: ' + str(exc))
