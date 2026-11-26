"""Wentylacja - okno szablonów użytkownika: wczytaj, zmień nazwę, usuń, duplikuj, ulubione, kategorie, import i eksport."""
from __future__ import annotations

import base64

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout

from . import vent_library as lib


class TemplatesDialog(QDialog):
    def __init__(self, parent, on_load):
        super().__init__(parent)
        self.setWindowTitle('Szablony wentylacji')
        self.on_load = on_load
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 48))
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for title, fn in (('Wczytaj', self.load), ('Zmień nazwę', self.rename), ('Usuń', self.delete), ('Duplikuj', self.duplicate)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        for title, fn in (('★ Ulubiony', self.favorite), ('Kategoria', self.category), ('Importuj…', self.import_), ('Eksportuj…', self.export), ('Zamknij', self.accept)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        lay.addLayout(row)
        self.fill()

    def fill(self):
        self.list.clear()
        for t in sorted(lib.templates(), key=lambda t: (not t.get('favorite'), t.get('category', ''), t['name'])):
            it = QListWidgetItem(('★ ' if t.get('favorite') else '') + f'{t["name"]}  [{t.get("category", "")}]')
            it.setData(Qt.UserRole, t['name'])
            if t.get('thumb'):
                pm = QPixmap()
                pm.loadFromData(base64.b64decode(t['thumb']), 'PNG')
                it.setIcon(QIcon(pm))
            self.list.addItem(it)

    def _name(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def load(self):
        n = self._name()
        t = next((x for x in lib.templates() if x['name'] == n), None)
        if t:
            self.on_load(t.get('config') or {})
            self.accept()

    def rename(self):
        n = self._name()
        if not n:
            return
        new, ok = QInputDialog.getText(self, 'Zmień nazwę', 'Nowa nazwa:', text=n)
        if ok and new.strip():
            try:
                lib.rename_template(n, new.strip())
            except ValueError as exc:
                QMessageBox.warning(self, 'Szablony', str(exc))
            self.fill()

    def delete(self):
        n = self._name()
        if n:
            lib.delete_template(n)
            self.fill()

    def duplicate(self):
        n = self._name()
        if n:
            lib.duplicate_template(n)
            self.fill()

    def favorite(self):
        n = self._name()
        t = next((x for x in lib.templates() if x['name'] == n), None)
        if t:
            lib.set_template_favorite(n, not t.get('favorite'))
            self.fill()

    def category(self):
        n = self._name()
        if not n:
            return
        cat, ok = QInputDialog.getText(self, 'Kategoria', 'Kategoria szablonu:')
        if ok:
            lib.set_template_category(n, cat.strip() or 'Moje')
            self.fill()

    def import_(self):
        path, _f = QFileDialog.getOpenFileName(self, 'Importuj szablony', '', 'Szablony wentylacji (*.json)')
        if path:
            try:
                lib.import_templates(path)
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, 'Szablony', str(exc))
            self.fill()

    def export(self):
        path, _f = QFileDialog.getSaveFileName(self, 'Eksportuj szablony', 'szablony_wentylacji.json', 'Szablony wentylacji (*.json)')
        if path:
            lib.export_templates(path)
