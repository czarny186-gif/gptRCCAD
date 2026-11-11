"""Kolor (zakładka Edycja): kolorowanie brył i kolor domyślny nowych brył.

Mixin okna Studio. Dopóki okno jest otwarte i wybrany jest kolor, kliknięte bryły od razu zmieniają kolor na polu
roboczym (podgląd), ale do projektu trafia to dopiero po „Zapisz” - jako krok historii 'color' (history.run_color).
Zamknięcie okna bez zapisu przywraca poprzednie kolory. Kolor domyślny dotyczy brył bez własnego koloru i zapisuje się
w projekcie razem z nim."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QGridLayout, QHBoxLayout, QMenu, QPushButton, QSizePolicy,
                               QToolButton, QWidget, QWidgetAction)

from . import colors as pal
from . import shell_ui as ui


def swatch_icon(rgb, size=30, checked=False, empty=False):
    """Kwadracik koloru (z ramką; wybrany - gruba niebieska ramka i znaczek)."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    if empty:
        p.setPen(QPen(QColor('#9fb2c4'), 1.4, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
    else:
        p.setPen(QPen(QColor('#40586f'), 1.2))
        p.setBrush(QColor(pal.to_hex(rgb)))
    p.drawRoundedRect(2, 2, size - 4, size - 4, 5, 5)
    if checked and not empty:
        p.setPen(QPen(QColor('#ffffff'), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        light = sum(rgb) / 3 > .72
        if light:
            p.setPen(QPen(QColor('#1d2a38'), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        s = size / 30
        p.drawPolyline([QPointF(9 * s, 15.5 * s), QPointF(13.5 * s, 20 * s), QPointF(21.5 * s, 10.5 * s)])
    p.end()
    return QIcon(pm)


class _Swatch(QToolButton):
    def __init__(self, rgb, name, size=40):
        super().__init__()
        self.rgb, self.size_ = rgb, size
        self.setCheckable(True)
        self.setFixedSize(size + 6, size + 6)
        self.setIconSize(QSize(size, size))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(name)
        self.setAutoRaise(True)
        self.setStyleSheet('QToolButton { border: 2px solid transparent; border-radius: 9px; background: transparent; }'
                           'QToolButton:checked { border-color: #2f87e8; background: #e6f0fc; }'
                           'QToolButton:hover { background: #eef4fb; }')
        self.toggled.connect(lambda *_: self.paint())
        self.paint()

    def set_rgb(self, rgb, name=None):
        self.rgb = rgb
        if name:
            self.setToolTip(name)
        self.paint()

    def paint(self):
        self.setIcon(swatch_icon(self.rgb or (1, 1, 1), self.size_, self.isChecked(), self.rgb is None))


class ColorTools:
    def _build_color_panel(self):
        from .studio import _label
        self.color_panel, lay = self._panel(296, 'Kolor', 'x_color', 'Kolory brył', plain=True, scroll=True)
        lay.addWidget(ui.StepRow(1, 'x_color', 'Wybierz kolor', plain=True))
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.co_group = QButtonGroup(self)
        self.co_group.setExclusive(True)
        self.co_swatches = []
        for i, (name, code) in enumerate(pal.PALETTE):
            sw = _Swatch(pal.to_rgb(code), name)
            sw.clicked.connect(lambda _=False, s=sw: self._co_pick_swatch(s))
            self.co_group.addButton(sw)
            grid.addWidget(sw, i // 4, i % 4)
            self.co_swatches.append(sw)
        lay.addWidget(grid_box)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.co_custom = _Swatch(None, 'Własny kolor (jeszcze nie wybrany)')
        self.co_custom.clicked.connect(lambda _=False: self._co_pick_swatch(self.co_custom) if self.co_custom.rgb else self.co_custom_dialog())
        self.co_group.addButton(self.co_custom)
        row.addWidget(self.co_custom)
        more = QPushButton('Własny kolor…')
        more.setToolTip('Dowolny kolor z palety barw - dla klikanych brył.')
        more.clicked.connect(lambda _=False: self.co_custom_dialog())
        row.addWidget(more, 1)
        lay.addLayout(row)
        lay.addWidget(ui.StepRow(2, 'x_object', 'Klikaj bryły', plain=True))
        self.co_status = _label('', 'status')
        self.co_status.setWordWrap(True)
        lay.addWidget(self.co_status)
        lay.addWidget(_label('Domyślny'))
        drow = QHBoxLayout()
        drow.setSpacing(8)
        self.co_default_button = QToolButton()
        self.co_default_button.setPopupMode(QToolButton.InstantPopup)
        self.co_default_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.co_default_button.setIconSize(QSize(26, 26))
        self.co_default_button.setCursor(Qt.PointingHandCursor)
        self.co_default_button.setToolTip('Kolor nowych brył i brył, którym nie nadano własnego koloru.')
        self.co_default_button.setMinimumHeight(38)
        self.co_default_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.co_default_button.setStyleSheet('QToolButton { text-align: left; padding-left: 8px; }')
        self.co_default_button.setMenu(self._co_default_menu())
        drow.addWidget(self.co_default_button, 1)
        lay.addLayout(drow)
        help_ = _label('Nowe bryły dostają kolor domyślny. Bryły pokolorowane zachowują swój kolor.', 'help')
        help_.setWordWrap(True)
        lay.addWidget(help_)
        self.co_save, close = self._buttons(self.color_panel.footer, 'Zapisz', 'Zamknij', self.apply_color, lambda: self.set_mode(None))
        self.co_save.setToolTip('Zapisuje kolory brył i kolor domyślny w projekcie (krok historii, można cofnąć).')
        close.setToolTip('Zamyka okno. Niezapisane kolory wracają do poprzednich.')
        self.co_current = None
        self.co_pending = {}
        self.co_default_new = None

    def _co_default_menu(self):
        menu = QMenu(self)
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 8, 8, 4)
        grid.setSpacing(4)
        for i, (name, code) in enumerate(pal.PALETTE):
            sw = _Swatch(pal.to_rgb(code), name, 30)
            sw.setCheckable(False)
            sw.clicked.connect(lambda _=False, rgb=pal.to_rgb(code), m=menu: (m.close(), self._co_set_default(rgb)))
            grid.addWidget(sw, i // 4, i % 4)
        action = QWidgetAction(menu)
        action.setDefaultWidget(box)
        menu.addAction(action)
        menu.addSeparator()
        menu.addAction('Własny kolor…', self.co_default_dialog)
        menu.addAction('Jasnoszary programu', lambda: self._co_set_default(pal.PROGRAM_DEFAULT))
        return menu

    # ------------------------------------------------------------------ tryb
    def _color_enter(self):
        self.color_panel.show()
        self.co_pending = {}
        self.co_default_new = None
        self.selected = []                  # zaznaczenie (niebieskie) zasłaniałoby kolory
        self.view.setCursor(Qt.PointingHandCursor)
        self._co_refresh()
        self.hint('Kolor: wybierz kolor, potem klikaj bryły. Zapisz zachowuje kolory w projekcie.')

    def _color_view_default(self):
        """Kolor domyślny pokazywany w widoku (w oknie Kolor - także niezapisany)."""
        if self.mode == 'color' and self.co_default_new is not None:
            return self.co_default_new
        return self.document.default_color

    def _co_pick_swatch(self, swatch):
        swatch.setChecked(True)
        self.co_current = swatch.rgb
        self._co_refresh()

    def co_custom_dialog(self):
        start = QColor(pal.to_hex(self.co_current or self.co_custom.rgb or pal.PROGRAM_DEFAULT))
        color = QColorDialog.getColor(start, self, 'Własny kolor bryły')
        if not color.isValid():
            return
        rgb = (color.redF(), color.greenF(), color.blueF())
        self.co_custom.set_rgb(rgb, 'Własny kolor ' + pal.to_hex(rgb).upper())
        self._co_pick_swatch(self.co_custom)

    def co_default_dialog(self):
        start = QColor(pal.to_hex(self.co_default_new or self.document.default_color or pal.PROGRAM_DEFAULT))
        color = QColorDialog.getColor(start, self, 'Domyślny kolor brył')
        if color.isValid():
            self._co_set_default((color.redF(), color.greenF(), color.blueF()))

    def _co_set_default(self, rgb):
        rgb = tuple(float(c) for c in rgb)
        current = self.document.default_color or pal.PROGRAM_DEFAULT
        self.co_default_new = None if pal.to_hex(rgb) == pal.to_hex(current) else rgb
        self._co_refresh()
        self.refresh()

    def pick_color(self, x, y):
        if self.co_current is None:
            self.toast('Najpierw wybierz kolor w oknie Kolor.')
            return
        bid = self.view.pick_body(x, y)
        body = self.document.get(bid) if bid else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij bryłę.')
            return
        for i in self._group_ids(body.id):        # szyk „jako jeden element” - cały razem
            b = self.document.get(i)
            if b is not None and b.kind == 'solid':
                self.co_pending[i] = self.co_current
        self._co_refresh()

    def _co_refresh(self):
        """Podgląd: kliknięte bryły w nowym kolorze (widok), opis i stan przycisków."""
        if not hasattr(self, 'co_status'):
            return
        live = {b.id for b in self.document.bodies}
        self.co_pending = {i: c for i, c in self.co_pending.items() if i in live}
        if self.mode == 'color':
            self.view.tints = {i: (*c, 1.0) for i, c in self.co_pending.items()}
        default = self.co_default_new or self.document.default_color or pal.PROGRAM_DEFAULT
        self.co_default_button.setIcon(swatch_icon(default, 26))
        self.co_default_button.setText(pal.name_of(default) + ('  (niezapisany)' if self.co_default_new else ''))
        count = len(self.co_pending)
        if self.co_current is None:
            text = 'Wybierz kolor, a potem klikaj bryły na polu roboczym.'
        else:
            text = f'Kolor: {pal.name_of(self.co_current)}. Klikaj bryły, które mają go dostać.'
        if count or self.co_default_new:
            parts = []
            if count:
                parts.append(f'pokolorowano brył: {count}')
            if self.co_default_new:
                parts.append('zmieniono kolor domyślny')
            text += ' ' + ', '.join(parts).capitalize() + ' - kliknij Zapisz, aby zachować.'
        self.co_status.setText(text)
        self.co_save.setEnabled(bool(count or self.co_default_new))
        if self.mode == 'color':
            self.refresh()

    def apply_color(self):
        if self.busy:
            return
        changed = {i: c for i, c in self.co_pending.items()
                   if (b := self.document.get(i)) is not None and (b.color is None or pal.to_hex(b.color) != pal.to_hex(c))}
        if self.co_default_new is not None:
            self.document.set_default_color(self.co_default_new)
        doc = self.document
        last = doc.info.get('op') or {}
        merged = {}
        if changed and last.get('type') == 'color' and doc.can_undo and not doc.can_redo and not self.step_editing:
            merged = dict(last.get('colors') or {})       # kolejne kolorowanie zaraz po poprzednim: jeden krok zamiast kilku
            doc.undo(mesh=False)
            doc._redo.clear()
            changed = {**{i: tuple(c) for i, c in merged.items() if doc.get(i) is not None}, **changed}
        if changed:
            colors = {i: [round(float(v), 4) for v in c] for i, c in changed.items()}
            n = len(colors)
            self.document.pending_op = dict(type='color', colors=colors)
            self.document.pending_label = f'Kolor: {n} ' + ('bryła' if n == 1 else 'bryły' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'brył')
            self.document.pending_icon = 'color'
            self.document.commit([replace(b, color=tuple(colors[b.id])) if b.id in colors else b for b in self.document.bodies])
        saved = bool(changed) or self.co_default_new is not None
        self.co_pending = {}
        self.co_default_new = None
        self.view.tints = {}
        self._co_refresh()
        self.refresh()
        self.toast('Zapisano kolory w projekcie.' if saved else 'Brak zmian do zapisania.', 2000)
