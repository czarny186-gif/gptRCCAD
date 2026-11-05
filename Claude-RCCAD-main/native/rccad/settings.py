"""Ustawienia programu w folderze „Ustawienia” obok pliku RCCAD Desktop.exe.

Każde ustawienie to osobny plik JSON (np. favorites.json - Ulubione, flange.json, hem.json - zapamiętane wartości).
Po aktualizacji wystarczy przenieść folder „Ustawienia” do nowej wersji programu, a stare ustawienia wrócą.
Gdy folderu programu nie da się zapisać (np. instalacja w Program Files), ustawienia trafiają do profilu użytkownika.
Pliki zapisane przez wcześniejsze wersje w profilu użytkownika są przy pierwszym odczycie przenoszone do folderu programu.
"""
import json
import os
import sys
from pathlib import Path

FOLDER = 'Ustawienia'


def program_dir():
    """Folder programu: obok RCCAD Desktop.exe (wersja spakowana) albo katalog native (uruchamianie ze źródeł)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _profile_dir():
    try:
        from PySide6.QtCore import QStandardPaths
        location = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    except Exception:
        location = ''
    return Path(location or Path.home() / '.rccad')


def _writable(folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / '.zapis'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        return True
    except Exception:
        return False


_DIR = None


def settings_dir():
    """Folder ustawień: RCCAD_CONFIG_DIR (testy), folder programu/Ustawienia, a gdy nie da się w nim zapisać - profil."""
    global _DIR
    override = os.environ.get('RCCAD_CONFIG_DIR')
    if override:
        return Path(override)
    if _DIR is None:
        local = program_dir() / FOLDER
        _DIR = local if _writable(local) else _profile_dir()
    return _DIR


def path(name):
    return settings_dir() / f'{name}.json'


def read(name):
    """Słownik ustawienia albo None. Plik ze starszej wersji (profil użytkownika) jest kopiowany do folderu programu."""
    target = path(name)
    sources = [target]
    if not os.environ.get('RCCAD_CONFIG_DIR'):
        old = _profile_dir() / f'{name}.json'
        if old != target:
            sources.append(old)
    for source in sources:
        try:
            values = json.loads(source.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(values, dict):
            continue
        if source != target:
            write(name, values)          # przeniesienie do folderu Ustawienia przy pierwszym odczycie
        return values
    return None


def write(name, values):
    try:
        target = path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(values, ensure_ascii=False, indent=1), encoding='utf-8')
        return True
    except Exception:
        return False
