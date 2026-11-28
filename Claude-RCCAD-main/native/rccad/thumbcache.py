"""Miniatury bibliotek (wentylacja, tekstury): zapis na dysku (PNG w folderze Ustawienia) oraz kolejka, która rysuje je po jednej
w tle głównego wątku (okno otwiera się od razu, miniatury dochodzą po kolei, a przy następnym uruchomieniu są już gotowe)."""
from __future__ import annotations

import hashlib
import json
import os
import time

VERSION = 'v1'


def _path(kind, params, px):
    from . import settings
    key = hashlib.sha1((VERSION + kind + str(px) + json.dumps(params, sort_keys=True, default=str)).encode('utf-8')).hexdigest()[:20]
    return os.path.join(settings.settings_dir(), 'thumbs', f'{kind}_{key}.png')


def cached_pixmap(kind, params, px, make):
    """QPixmap z pliku, a gdy go nie ma - z make() i zapis na dysk (błędy zapisu są pomijane)."""
    from PySide6.QtGui import QPixmap
    path = _path(kind, params, px)
    pm = QPixmap()
    if os.path.exists(path) and pm.load(path):
        return pm
    pm = make()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pm.save(path, 'PNG')
    except Exception:
        pass
    return pm


def placeholder(px=56):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QPixmap
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    return QIcon(pm)


class Queue:
    """Rysuje miniatury po jednej (w budżecie ~20 ms na przebieg), żeby okno nie czekało na całą galerię."""

    def __init__(self):
        self.jobs = []
        self.active = False

    def add(self, cache, key, make, widget):
        if any(j[0] is cache and j[1] == key for j in self.jobs):
            return
        self.jobs.append((cache, key, make, widget))
        if not self.active:
            self.active = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._tick)

    def clear(self):
        self.jobs.clear()

    def _tick(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QIcon
        end = time.monotonic() + .02
        while self.jobs and time.monotonic() < end:
            cache, key, make, widget = self.jobs.pop(0)
            try:
                icon = QIcon(make())
            except Exception:
                icon = QIcon()
            cache[key] = icon
            try:
                for i in range(widget.count()):
                    item = widget.item(i)
                    if item.data(Qt.UserRole) == key:
                        item.setIcon(icon)
            except RuntimeError:        # lista już usunięta
                pass
        if self.jobs:
            QTimer.singleShot(1, self._tick)
        else:
            self.active = False
