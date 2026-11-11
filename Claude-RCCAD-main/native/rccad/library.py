"""Biblioteka obiektów i szkiców (zakładka Biblioteka): zwykłe foldery i pliki w folderze „Ustawienia/Biblioteka”
obok programu. Po aktualizacji wystarczy przenieść folder „Ustawienia” do nowej wersji - biblioteka wraca bez zmian.

Obiekty: pliki STEP / STL / BREP (zaimportowane bez zmiany formatu) oraz obiekty z pola roboczego w formacie programu
(.rccad). Szkice: DXF / SVG oraz szkice z pola roboczego (.rccad). Okno biblioteki (LibraryDialog) pozwala tworzyć
foldery, zmieniać nazwy, kopiować / wycinać / wklejać / usuwać, importować, eksportować i wstawiać na pole robocze."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget)

from . import icons, settings

NATIVE = '.rccadx'
KINDS = {
    'object': dict(folder='Obiekty', title='Biblioteka obiektów', files=('.step', '.stp', '.stl', '.brep', '.brp'),
                   filter='Modele (*.step *.stp *.stl *.brep *.brp)', what='obiekt', icon='libobj'),
    'sketch': dict(folder='Szkice', title='Biblioteka szkiców', files=('.dxf', '.svg'),
                   filter='Szkice (*.dxf *.svg)', what='szkic', icon='libsketch'),
}
BAD = re.compile(r'[\\/:*?"<>|]')


# ---------------------------------------------------------------------------
# pliki i foldery
# ---------------------------------------------------------------------------
def root(kind):
    path = settings.settings_dir() / 'Biblioteka' / KINDS[kind]['folder']
    path.mkdir(parents=True, exist_ok=True)
    return path


def allowed(kind, path):
    path = Path(path)
    return path.is_dir() or path.suffix.lower() in (*KINDS[kind]['files'], NATIVE)


def _key(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', path.name)]


def entries(kind, folder):
    """Zawartość folderu: najpierw foldery, potem pliki biblioteki (kolejność naturalna: 2 przed 10)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    items = [p for p in folder.iterdir() if not p.name.startswith('.') and allowed(kind, p)]
    return sorted([p for p in items if p.is_dir()], key=_key) + sorted([p for p in items if p.is_file()], key=_key)


def clean_name(name):
    name = BAD.sub('_', str(name)).strip().strip('.')
    return name[:80] or 'Bez nazwy'


def unique(folder, stem, suffix=''):
    """Wolna nazwa w folderze: „Nazwa”, „Nazwa (2)”, „Nazwa (3)”..."""
    folder = Path(folder)
    stem = clean_name(stem)
    candidate = folder / f'{stem}{suffix}'
    n = 2
    while candidate.exists():
        candidate = folder / f'{stem} ({n}){suffix}'
        n += 1
    return candidate


def display_name(path):
    path = Path(path)
    return path.name if path.is_dir() else path.stem


def file_format(path):
    path = Path(path)
    if path.is_dir():
        return 'Folder'
    return {'.stp': 'STEP', '.brp': 'BREP', NATIVE: 'RCCAD'}.get(path.suffix.lower(), path.suffix[1:].upper())


def new_folder(folder, name='Nowy folder'):
    path = unique(folder, name)
    path.mkdir(parents=True)
    return path


def rename(path, name):
    """Nowa nazwa pliku lub folderu (rozszerzenie pliku zostaje). Zwraca nową ścieżkę."""
    path = Path(path)
    name = clean_name(name)
    if name == display_name(path):
        return path
    target = path.with_name(name if path.is_dir() else name + path.suffix)
    if target.exists():
        target = unique(path.parent, name, '' if path.is_dir() else path.suffix)
    return path.rename(target)


def remove(path):
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def inside(path, folder):
    try:
        Path(folder).resolve().relative_to(Path(path).resolve())
        return True
    except ValueError:
        return False


def paste(paths, folder, move=False):
    """Wkleja skopiowane albo wycięte elementy do folderu. Folderu nie da się wkleić do niego samego."""
    out = []
    folder = Path(folder)
    for source in map(Path, paths):
        if not source.exists():
            continue
        if source.is_dir() and inside(source, folder):
            raise ValueError(f'Nie można wkleić folderu „{source.name}” do niego samego.')
        if move and source.parent.resolve() == folder.resolve():
            out.append(source)
            continue
        target = unique(folder, display_name(source), '' if source.is_dir() else source.suffix)
        if move:
            shutil.move(str(source), str(target))
        elif source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        out.append(target)
    return out


def import_files(kind, paths, folder):
    """Kopiuje pliki z komputera do folderu biblioteki bez zmiany formatu."""
    out = []
    for source in map(Path, paths):
        if source.suffix.lower() not in KINDS[kind]['files']:
            continue
        target = unique(folder, source.stem, source.suffix.lower())
        shutil.copy2(source, target)
        out.append(target)
    return out


def save_bodies(bodies, folder, name):
    """Obiekt albo szkic z pola roboczego w formacie programu (.rccadx: kształty, nazwy, płaszczyzny szkiców, grupy)."""
    from .document import Document
    from dataclasses import replace
    doc = Document()
    doc.commit([replace(b, mesh=None, visible=True) for b in bodies])
    target = unique(folder, name, NATIVE)
    doc.save(target, mark=False)
    return target


def load_bodies(kind, path):
    """Obiekty zapisane w pliku biblioteki, gotowe do wstawienia (z siatkami)."""
    from .document import Body, Document
    from . import kernel
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == NATIVE:
        bodies = [b for b in Document.load(path).bodies if b.visible]
        return [b if b.mesh is not None else b.prepared() for b in bodies]
    if suffix == '.svg':
        return [Body(f'{path.stem} {i + 1}' if i else path.stem, w, 'sketch', 'XY').prepared() for i, w in enumerate(kernel.svg_profiles(str(path), 'XY'))]
    from .colors import imported
    shapes = kernel.import_shapes(path)
    return [b.prepared() for b in imported((Body(path.stem if i == 0 else f'{path.stem} {i + 1}', s, k)
                                            for i, (s, k) in enumerate(shapes)), path.stem)]


def export_item(kind, path, folder):
    """Eksport do folderu na komputerze: pliki z własnym formatem bez zmian, obiekty z pola roboczego jako STEP,
    szkice z pola roboczego jako DXF. Zwraca ścieżkę zapisanego pliku."""
    from . import kernel
    path, folder = Path(path), Path(folder)
    if path.is_dir():
        target = unique(folder, path.name)
        shutil.copytree(path, target, ignore=lambda d, names: [n for n in names if (Path(d) / n).is_file() and Path(n).suffix.lower() == NATIVE])
        for native in path.rglob('*' + NATIVE):        # zawartość folderu: pliki programu też w formacie wymiany
            export_item(kind, native, target / native.parent.relative_to(path))
        return target
    if path.suffix.lower() != NATIVE:
        target = unique(folder, path.stem, path.suffix)
        shutil.copy2(path, target)
        return target
    bodies = load_bodies(kind, path)
    suffix = '.step' if kind == 'object' else '.dxf'
    target = unique(folder, path.stem, suffix)
    folder.mkdir(parents=True, exist_ok=True)
    kernel.export_shapes([b.shape for b in bodies], target)
    return target


# ---------------------------------------------------------------------------
# okno biblioteki
# ---------------------------------------------------------------------------
QSS = """
QDialog#library { background:#f6f9fc; }
QLabel#libtitle { font-size:17px; font-weight:800; color:#1d3a56; }
QLabel#libpath { font-size:12px; color:#5b7a93; }
QLabel#libstatus { font-size:11px; color:#6c8399; }
QToolButton#libnav { border:1px solid #c9d9e8; border-radius:9px; background:white; }
QToolButton#libnav:hover { background:#e6f1fc; border-color:#8ec0f3; }
QToolButton#libnav:disabled { background:#f1f4f7; }
QPushButton#libbtn { border:1px solid #c9d9e8; border-radius:10px; background:white; padding:7px 12px; font-size:12px; color:#1d3a56; }
QPushButton#libbtn:hover { background:#e6f1fc; border-color:#8ec0f3; }
QPushButton#libbtn:disabled { color:#a5b6c6; }
QPushButton#libmain { border:0; border-radius:10px; background:#2f87e8; color:white; padding:8px 18px; font-weight:700; }
QPushButton#libmain:hover { background:#1f74d4; }
QListWidget#libview { background:white; border:1px solid #d3e0ec; border-radius:14px; padding:10px; font-size:12px; }
QListWidget#libview::item { border-radius:10px; padding:6px 2px; color:#1d3a56; }
QListWidget#libview::item:hover { background:#eef5fc; }
QListWidget#libview::item:selected { background:#dcecff; color:#1d3a56; }
"""


def _badge_icon(name, badge, size=96):
    """Ikona elementu z plakietką formatu (STEP, STL, RCCAD, DXF, SVG)."""
    base = icons.pixmap('t_' + name, size)
    pm = QPixmap(base.size())
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawPixmap(pm.rect(), base, base.rect())          # cały obraz (ikona ma podwójną rozdzielczość)
    if badge:
        scale = base.width() / size * .9
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(17 * scale))
        p.setFont(font)
        w = p.fontMetrics().horizontalAdvance(badge) + int(10 * scale)
        h = int(22 * scale)
        x, y = base.width() - w, base.height() - h
        colour = {'RCCAD': '#2f87e8', 'STEP': '#3aa77a', 'STL': '#f08a24', 'DXF': '#8a5cd6', 'SVG': '#d65c8a'}.get(badge, '#5b7a93')
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(colour))
        p.drawRoundedRect(x, y, w, h, 4 * scale, 4 * scale)
        p.setPen(QColor('white'))
        p.drawText(x, y, w, h, Qt.AlignCenter, badge)
    p.end()
    return QIcon(pm)


class _View(QListWidget):
    """Siatka elementów; klawisz Backspace cofa, a puste miejsce czyści zaznaczenie."""
    back = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Backspace and self.state() != QAbstractItemView.EditingState:
            self.back.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()
        super().mousePressEvent(event)


class LibraryDialog(QDialog):
    """Okno Wstaw obiekt / Wstaw szkic. `studio` dostarcza wstawianie z pola roboczego i na pole robocze."""

    def __init__(self, studio, kind):
        super().__init__(studio)
        self.studio, self.kind = studio, kind
        self.info = KINDS[kind]
        self.home = root(kind)
        self.folder = self.home
        self.clip = None                  # (ścieżki, wycięte?)
        self._renaming = False
        self.setObjectName('library')
        self.setWindowTitle(self.info['title'])
        self.setStyleSheet(QSS)
        self.setModal(False)
        self.resize(900, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.back_btn = self._nav('libback', 'Cofnij o jeden folder (Backspace)', self.go_back)
        self.home_btn = self._nav('libhome', 'Strona startowa biblioteki', self.go_home)
        pic = QLabel()
        pic.setPixmap(icons.pixmap('t_' + self.info['icon'], 30))
        title = QLabel(self.info['title'])
        title.setObjectName('libtitle')
        self.path_label = QLabel()
        self.path_label.setObjectName('libpath')
        top.addWidget(self.back_btn)
        top.addWidget(self.home_btn)
        top.addSpacing(8)
        top.addWidget(pic)
        top.addWidget(title)
        top.addSpacing(10)
        top.addWidget(self.path_label, 1)
        outer.addLayout(top)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.buttons = {}
        for key, icon, text, tip, slot in (
                ('folder', 'folderadd', 'Nowy folder', 'Nowy folder w bieżącym miejscu - od razu wpisz nazwę', self.add_folder),
                ('import', 'libimport', 'Importuj', 'Kopiuje pliki z komputera do bieżącego folderu: ' + self.info['filter'], self.import_dialog),
                ('export', 'f_export', 'Eksportuj', 'Zapisuje zaznaczone elementy na komputerze (pliki programu jako '
                 + ('STEP' if kind == 'object' else 'DXF') + ', pozostałe bez zmiany formatu)', self.export_selected),
                ('take', 'libtake', 'Wstaw z pola roboczego', f'Okno chowa się - kliknij {self.info["what"]} na polu roboczym, zapisze się w bieżącym folderze '
                 '(prawy przycisk albo Esc anuluje)', self.take_from_workspace),
                ('place', 'libplace', 'Wstaw na pole robocze', 'Okno chowa się - kliknij miejsce na polu roboczym, w którym ma stanąć zaznaczony element', self.place_selected)):
            b = QPushButton(text)
            b.setObjectName('libbtn')
            b.setIcon(QIcon(icons.pixmap(('t_' + icon) if not icon.startswith('f_') else icon, 22)))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            self.buttons[key] = b
            bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)

        self.view = _View()
        self.view.setObjectName('libview')
        self.view.setViewMode(QListWidget.IconMode)
        self.view.setResizeMode(QListWidget.Adjust)
        self.view.setMovement(QListWidget.Static)
        self.view.setIconSize(QSize(72, 72))
        self.view.setGridSize(QSize(132, 124))
        self.view.setWordWrap(True)
        self.view.setUniformItemSizes(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.itemDoubleClicked.connect(self._open)
        self.view.itemChanged.connect(self._renamed)
        self.view.itemSelectionChanged.connect(self._update_buttons)
        self.view.back.connect(self.go_back)
        outer.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName('libstatus')
        close = QPushButton('Zamknij')
        close.setObjectName('libmain')
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(close)
        outer.addLayout(bottom)

        for keys, slot in ((QKeySequence.Copy, lambda: self.copy(False)), (QKeySequence.Cut, lambda: self.copy(True)),
                           (QKeySequence.Paste, self.paste_here), (QKeySequence.Delete, self.delete_selected),
                           (QKeySequence('F2'), self.rename_selected)):
            QShortcut(keys, self.view, activated=slot, context=Qt.WidgetWithChildrenShortcut)
        self.refresh()

    # ---- budowa ----
    def _nav(self, icon, tip, slot):
        b = QToolButton()
        b.setObjectName('libnav')
        b.setIcon(QIcon(icons.pixmap('t_' + icon, 26)))
        b.setIconSize(QSize(24, 24))
        b.setFixedSize(38, 38)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _item_icon(self, path):
        if path.is_dir():
            return _badge_icon('folder', '')
        fmt = file_format(path)
        return _badge_icon(self.info['icon'] if fmt == 'RCCAD' else ('libfile' if self.kind == 'object' else 'libsketchfile'), fmt)

    # ---- nawigacja ----
    def refresh(self, select=None, edit=None):
        self._renaming = True
        self.view.clear()
        for path in entries(self.kind, self.folder):
            item = QListWidgetItem(self._item_icon(path), display_name(path))
            item.setData(Qt.UserRole, str(path))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setToolTip(f'{display_name(path)} · {file_format(path)}' + ('' if path.is_dir() else ' · dwuklik: wstaw na pole robocze'))
            self.view.addItem(item)
            if select is not None and Path(select) == path:
                item.setSelected(True)
                self.view.setCurrentItem(item)
                if edit:
                    QTimer.singleShot(0, lambda it=item: self.view.editItem(it))
        self._renaming = False
        rel = self.folder.relative_to(self.home)
        parts = [self.info['title'], *rel.parts]
        self.path_label.setText('  ›  '.join(parts))
        at_home = self.folder == self.home
        self.back_btn.setEnabled(not at_home)
        self.home_btn.setEnabled(not at_home)
        n = self.view.count()
        self.status.setText(f'{n} element(y) · dwuklik na folderze - otwórz · prawy przycisk - kopiuj, wytnij, wklej, usuń, zmień nazwę'
                            if n else 'Pusty folder - dodaj folder, zaimportuj plik albo wstaw z pola roboczego.')
        self._update_buttons()

    def _update_buttons(self):
        files = [p for p in self.selected() if p.is_file()]
        self.buttons['place'].setEnabled(len(files) == 1)
        self.buttons['export'].setEnabled(bool(self.selected()))

    def selected(self):
        return [Path(it.data(Qt.UserRole)) for it in self.view.selectedItems()]

    def enter(self, folder):
        self.folder = Path(folder)
        self.refresh()

    def go_back(self):
        if self.folder != self.home:
            previous = self.folder
            self.folder = self.folder.parent
            self.refresh(select=previous)

    def go_home(self):
        self.folder = self.home
        self.refresh()

    def _open(self, item):
        path = Path(item.data(Qt.UserRole))
        if path.is_dir():
            self.enter(path)
        else:
            self.place_selected()

    # ---- foldery i nazwy ----
    def add_folder(self):
        path = new_folder(self.folder)
        self.refresh(select=path, edit=True)       # od razu wpisywanie nazwy

    def rename_selected(self):
        items = self.view.selectedItems()
        if len(items) == 1:
            self.view.editItem(items[0])

    def _renamed(self, item):
        if self._renaming:
            return
        path = Path(item.data(Qt.UserRole))
        text = item.text().strip()
        if not text or text == display_name(path):
            self._renaming = True
            item.setText(display_name(path))
            self._renaming = False
            return
        try:
            new = rename(path, text)
        except OSError as exc:
            QMessageBox.warning(self, 'Biblioteka', f'Nie można zmienić nazwy: {exc}')
            new = path
        QTimer.singleShot(0, lambda: self.refresh(select=new))

    # ---- schowek ----
    def copy(self, cut):
        paths = self.selected()
        if paths:
            self.clip = ([str(p) for p in paths], cut)
            self.status.setText(f'{"Wycięto" if cut else "Skopiowano"}: {len(paths)} - wejdź do folderu i wybierz Wklej (Ctrl+V).')

    def paste_here(self, folder=None):
        if not self.clip:
            return
        paths, cut = self.clip
        try:
            made = paste(paths, folder or self.folder, move=cut)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'Biblioteka', str(exc))
            return
        if cut:
            self.clip = None                  # wycięte: po wklejeniu schowek pusty
        self.refresh(select=made[-1] if made and Path(made[-1]).parent == self.folder else None)

    def delete_selected(self):
        paths = self.selected()
        if not paths:
            return
        names = ', '.join(f'„{display_name(p)}”' for p in paths[:4]) + (' …' if len(paths) > 4 else '')
        folders = any(p.is_dir() and any(p.iterdir()) for p in paths)
        text = f'Usunąć {names}?' + ('\nFoldery zostaną usunięte razem z zawartością.' if folders else '')
        if QMessageBox.question(self, 'Usuń z biblioteki', text) != QMessageBox.Yes:
            return
        for p in paths:
            remove(p)
        self.refresh()

    def _menu(self, pos):
        item = self.view.itemAt(pos)
        if item is not None and not item.isSelected():
            self.view.clearSelection()
            item.setSelected(True)
        has = bool(self.selected())
        menu = QMenu(self)
        menu.addAction('Kopiuj', lambda: self.copy(False)).setEnabled(has)
        menu.addAction('Wytnij', lambda: self.copy(True)).setEnabled(has)
        target = Path(item.data(Qt.UserRole)) if item is not None and Path(item.data(Qt.UserRole)).is_dir() and len(self.selected()) == 1 and self.clip else None
        menu.addAction('Wklej' + (f' do „{target.name}”' if target else ''), lambda: self.paste_here(target)).setEnabled(bool(self.clip))
        menu.addAction('Usuń', self.delete_selected).setEnabled(has)
        menu.addSeparator()
        menu.addAction('Zmień nazwę (F2)', self.rename_selected).setEnabled(len(self.selected()) == 1)
        menu.addAction('Nowy folder', self.add_folder)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    # ---- pliki ----
    def import_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Importuj do biblioteki', '', self.info['filter'])
        if paths:
            made = import_files(self.kind, paths, self.folder)
            self.refresh(select=made[-1] if made else None)
            self.status.setText(f'Zaimportowano {len(made)} plik(i) do folderu „{display_name(self.folder)}”.')

    def export_selected(self):
        paths = self.selected()
        if not paths:
            return
        folder = QFileDialog.getExistingDirectory(self, 'Eksportuj do folderu')
        if not folder:
            return
        done = []
        for p in paths:
            try:
                done.append(export_item(self.kind, p, folder))
            except Exception as exc:
                QMessageBox.warning(self, 'Eksport', f'Nie udało się wyeksportować „{display_name(p)}”: {exc}')
        if done:
            self.status.setText(f'Wyeksportowano {len(done)} element(y) do {folder}.')

    def take_from_workspace(self):
        self.studio.library_pick(self)

    def place_selected(self):
        files = [p for p in self.selected() if p.is_file()]
        if len(files) != 1:
            self.status.setText('Zaznacz jeden obiekt w oknie, a potem wybierz Wstaw na pole robocze.')
            return
        self.studio.library_place(self, files[0])

    def picked(self, path):
        """Wywoływane przez okno główne po zapisaniu elementu z pola roboczego."""
        self.show()
        self.raise_()
        self.refresh(select=path)
        self.status.setText(f'Zapisano „{display_name(path)}” w folderze „{display_name(self.folder)}”.')
