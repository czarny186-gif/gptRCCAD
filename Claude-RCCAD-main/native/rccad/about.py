"""Okno „O programie”: nazwa, wersja, daty i twórca."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import AUTHOR, BUILD, BUILD_DATE, CREATED, FULL_VERSION, icons


def _date(text):
    """2026-11-01 -> 01.11.2026"""
    try:
        y, m, d = text.split('-')
        return f'{d}.{m}.{y}'
    except ValueError:
        return text


def rows():
    out = [('Nazwa', 'RCCAD Desktop'), ('Wersja', FULL_VERSION), ('Data utworzenia', CREATED)]
    if BUILD_DATE:
        out.append(('Data kompilacji', _date(BUILD_DATE)))
    out.append(('Twórca', AUTHOR))
    return out


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('O programie')
        self.setFixedWidth(420)
        self.setStyleSheet('QDialog{background:#f4f7fb;} QLabel{color:#27415a;font-size:13px;background:transparent;border:0;}'
                           'QLabel#name{font-size:24px;font-weight:800;color:#17314a;} QLabel#tag{color:#607b90;font-size:12px;}'
                           'QLabel#key{color:#607b90;font-weight:600;} QLabel#val{color:#17314a;font-weight:700;}'
                           'QPushButton{background:#2f87e8;border:1px solid #2379d6;color:#fff;font-weight:700;border-radius:8px;padding:8px 26px;}'
                           'QPushButton:hover{background:#1f6fc9;}')
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        head = QHBoxLayout()
        head.setSpacing(14)
        pic = QLabel()
        pic.setPixmap(icons.badge('x_revolve', icons.BLUE, 64, True))
        head.addWidget(pic)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel('RCCAD')
        name.setObjectName('name')
        tag = QLabel('Modelowanie brył 3D · silnik OpenCascade')
        tag.setObjectName('tag')
        col.addWidget(name)
        col.addWidget(tag)
        head.addLayout(col, 1)
        root.addLayout(head)
        card = QFrame()
        card.setStyleSheet('QFrame{background:#ffffff;border:1px solid #d6e0ea;border-radius:12px;}')
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(9)
        self.values = {}
        for n, (key, value) in enumerate(rows()):
            k, v = QLabel(key), QLabel(value)
            k.setObjectName('key')
            v.setObjectName('val')
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(k, n, 0)
            grid.addWidget(v, n, 1)
            self.values[key] = v
        grid.setColumnStretch(1, 1)
        root.addWidget(card)
        ok = QPushButton('Zamknij')
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(ok)
        root.addLayout(row)
