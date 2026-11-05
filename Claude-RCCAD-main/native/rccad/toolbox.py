"""Przybornik: wybór ulubionych narzędzi do zakładki Ulubione.

Okno pokazuje wszystkie narzędzia ze wszystkich zakładek. Ptaszek dodaje narzędzie do Ulubionych, strzałki ▲ ▼ ustawiają
kolejność (pierwsze od lewej stoi zaraz po Pliku i Przyborniku). U góry podgląd paska narzędzi tak, jak będzie wyglądał.
"""
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton, QVBoxLayout,
                               QWidget)

from . import icons

STYLE = """
QDialog#toolbox { background:#f4f7fb; }
QLabel#tbTitle { font-size:17px; font-weight:800; color:#1f3b57; }
QLabel#tbSub { font-size:12px; color:#607b90; }
QLabel#tbSection { font-size:11px; font-weight:800; color:#7b93a8; letter-spacing:1px; padding:8px 4px 2px 4px; }
QFrame#tbPreview { background:white; border:1.4px solid #cfdcea; border-radius:12px; }
QLabel#tbSlot { background:white; border:1.4px solid #d6e0ea; border-radius:9px; }
QLabel#tbSlotFixed { background:#eef4fb; border:1.4px solid #b9cde0; border-radius:9px; }
QLabel#tbEmpty { color:#9fb2c4; font-size:12px; }
QFrame#tbRow { background:white; border:1.4px solid #dbe5ef; border-radius:11px; }
QFrame#tbRow[chosen="true"] { background:#eaf3fe; border:1.6px solid #2f87e8; }
QLabel#tbName { font-size:13px; font-weight:700; color:#27415a; }
QLabel#tbChip { background:#eef2f6; color:#5d7890; border-radius:8px; padding:2px 8px; font-size:10px; font-weight:700; }
QLabel#tbNo { background:#2f87e8; color:white; border-radius:11px; font-weight:800; font-size:11px; }
QToolButton#tbCheck { border:2px solid #b9c9d8; border-radius:13px; background:white; color:white; font-weight:900; font-size:14px; }
QToolButton#tbCheck:checked { border:2px solid #2fa56d; background:#2fa56d; }
QToolButton#tbCheck:hover { border-color:#2f87e8; }
QToolButton#tbMove { border:1.2px solid #cfdcea; border-radius:7px; background:white; color:#2f87e8; font-size:11px; font-weight:900; }
QToolButton#tbMove:hover { background:#eaf3fe; }
QToolButton#tbMove:disabled { color:#c9d5e1; border-color:#e3eaf1; }
QScrollArea#tbScroll, QWidget#tbBody { background:transparent; border:0; }
QPushButton { border:1.4px solid #c6d4e2; border-radius:8px; background:white; padding:8px 14px; color:#27415a; font-weight:600; }
QPushButton:hover { background:#eef4fb; }
QPushButton#primary { background:#2f87e8; border-color:#2379d6; color:white; font-weight:700; }
QPushButton#primary:hover { background:#1f6fc9; }
"""


class ToolboxDialog(QDialog):
    def __init__(self, parent, items, chosen, on_apply):
        """items: [(klucz, nazwa, zakładka, QIcon)] w kolejności zakładek; chosen: wybrane klucze w kolejności paska."""
        super().__init__(parent)
        self.setObjectName('toolbox')
        self.setWindowTitle('Przybornik — ulubione narzędzia')
        self.setStyleSheet(STYLE)
        self.setModal(True)
        self.resize(560, 720)
        self.items = {key: (name, tab, icon) for key, name, tab, icon in items}
        self.order = [key for key, *_ in items]
        self.chosen = [k for k in chosen if k in self.items]
        self.on_apply = on_apply
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        pic = QLabel()
        pic.setPixmap(icons.pixmap('t_toolbox', 52))
        pic.setFixedSize(52, 52)
        head.addWidget(pic)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel('Przybornik')
        title.setObjectName('tbTitle')
        sub = QLabel('Zaznacz ptaszkiem narzędzia, których często używasz, i ustaw ich kolejność strzałkami. '
                     'Pojawią się w zakładce Ulubione zaraz po Pliku i Przyborniku.')
        sub.setObjectName('tbSub')
        sub.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(sub)
        head.addLayout(text, 1)
        lay.addLayout(head)
        # podgląd paska Ulubionych
        self.preview = QFrame()
        self.preview.setObjectName('tbPreview')
        self.preview_lay = QHBoxLayout(self.preview)
        self.preview_lay.setContentsMargins(10, 8, 10, 8)
        self.preview_lay.setSpacing(6)
        lay.addWidget(self.preview)
        # lista narzędzi
        self.scroll = QScrollArea()
        self.scroll.setObjectName('tbScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.apply_button, self.close_button, self.reset_button = QPushButton('Zastosuj'), QPushButton('Zamknij'), QPushButton('Reset')
        self.apply_button.setObjectName('primary')
        self.apply_button.setToolTip('Zapisuje wybór i kolejność - zakładka Ulubione od razu się zmienia.')
        self.reset_button.setToolTip('Odznacza wszystkie narzędzia (w Ulubionych zostaje tylko Przybornik).')
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self.reset)
        for b in (self.apply_button, self.close_button, self.reset_button):
            row.addWidget(b, 1)
        lay.addLayout(row)
        self.rows = {}
        self.rebuild()

    # ---------- dane ----------
    def toggle(self, key, on):
        if on and key not in self.chosen:
            self.chosen.append(key)              # nowe ulubione narzędzie trafia na koniec paska
        elif not on and key in self.chosen:
            self.chosen.remove(key)
        self._later()

    def move(self, key, step):
        i = self.chosen.index(key)
        j = i + step
        if 0 <= j < len(self.chosen):
            self.chosen[i], self.chosen[j] = self.chosen[j], self.chosen[i]
            self._later()

    def reset(self):
        self.chosen = []
        self._later()

    def _later(self):
        """Lista odbudowuje się po obsłudze kliknięcia - kliknięty przycisk nie może zniknąć w trakcie własnego sygnału."""
        QTimer.singleShot(0, self.rebuild)

    def apply(self):
        self.on_apply(list(self.chosen))
        self.accept()

    # ---------- wygląd ----------
    def _slot(self, icon, name, fixed=False):
        label = QLabel()
        label.setObjectName('tbSlotFixed' if fixed else 'tbSlot')
        label.setFixedSize(40, 40)
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(icon.pixmap(QSize(28, 28)))
        label.setToolTip(name)
        return label

    def _row(self, key):
        name, tab, icon = self.items[key]
        chosen = key in self.chosen
        frame = QFrame()
        frame.setObjectName('tbRow')
        frame.setProperty('chosen', 'true' if chosen else 'false')
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)
        check = QToolButton()
        check.setObjectName('tbCheck')
        check.setCheckable(True)
        check.setChecked(chosen)
        check.setText('✓' if chosen else '')
        check.setFixedSize(26, 26)
        check.setCursor(Qt.PointingHandCursor)
        check.setToolTip('Usuń z Ulubionych' if chosen else 'Dodaj do Ulubionych')
        check.toggled.connect(lambda on, k=key: self.toggle(k, on))
        lay.addWidget(check)
        pic = QLabel()
        pic.setFixedSize(36, 36)
        pic.setAlignment(Qt.AlignCenter)
        pic.setPixmap(icon.pixmap(QSize(32, 32)))
        lay.addWidget(pic)
        col = QVBoxLayout()
        col.setSpacing(3)
        title = QLabel(name)
        title.setObjectName('tbName')
        chip = QLabel(tab)
        chip.setObjectName('tbChip')
        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.addWidget(chip)
        chip_row.addStretch(1)
        col.addWidget(title)
        col.addLayout(chip_row)
        lay.addLayout(col, 1)
        frame.check = check
        frame.up = frame.down = None
        if chosen:
            index = self.chosen.index(key)
            number = QLabel(str(index + 1))
            number.setObjectName('tbNo')
            number.setFixedSize(22, 22)
            number.setAlignment(Qt.AlignCenter)
            number.setToolTip('Miejsce na pasku Ulubionych')
            lay.addWidget(number)
            for text, step, tip in (('▲', -1, 'W lewo na pasku (wyżej na liście)'), ('▼', 1, 'W prawo na pasku (niżej na liście)')):
                b = QToolButton()
                b.setObjectName('tbMove')
                b.setText(text)
                b.setFixedSize(28, 26)
                b.setToolTip(tip)
                b.setCursor(Qt.PointingHandCursor)
                b.setEnabled(0 <= index + step < len(self.chosen))
                b.clicked.connect(lambda _=False, k=key, st=step: self.move(k, st))
                lay.addWidget(b)
                if step < 0:
                    frame.up = b
                else:
                    frame.down = b
        return frame

    def _section(self, text):
        label = QLabel(text.upper())
        label.setObjectName('tbSection')
        return label

    def rebuild(self):
        # podgląd paska: Plik i Przybornik stoją zawsze na początku
        while self.preview_lay.count():
            item = self.preview_lay.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        from .shell_ui import style_icon
        self.preview_lay.addWidget(self._slot(style_icon('file', 28), 'Plik', True))
        self.preview_lay.addWidget(self._slot(style_icon('toolbox', 28), 'Przybornik', True))
        for key in self.chosen:
            name, _, icon = self.items[key]
            self.preview_lay.addWidget(self._slot(icon, name))
        if not self.chosen:
            empty = QLabel('Zaznacz narzędzia poniżej - pojawią się tutaj.')
            empty.setObjectName('tbEmpty')
            self.preview_lay.addWidget(empty)
        self.preview_lay.addStretch(1)
        # lista: najpierw wybrane (w kolejności paska), potem pozostałe według zakładek
        body = QWidget()
        body.setObjectName('tbBody')
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(6)
        self.rows = {}
        lay.addWidget(self._section(f'Ulubione ({len(self.chosen)})'))
        for key in self.chosen:
            self.rows[key] = self._row(key)
            lay.addWidget(self.rows[key])
        tab = None
        for key in self.order:
            if key in self.chosen:
                continue
            if self.items[key][1] != tab:
                tab = self.items[key][1]
                lay.addWidget(self._section(tab))
            self.rows[key] = self._row(key)
            lay.addWidget(self.rows[key])
        lay.addStretch(1)
        position = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(body)
        self.scroll.verticalScrollBar().setValue(position)
