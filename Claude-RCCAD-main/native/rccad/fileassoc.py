"""Skojarzenie plików .rccadx z programem (Windows, tylko bieżący użytkownik - bez uprawnień administratora).

Dwuklik w plik projektu w Eksploratorze uruchamia RCCAD z tym plikiem. Wpisy są poprawiane przy każdym starcie, więc po
przeniesieniu folderu programu skojarzenie wskazuje nowe miejsce. Działa tylko w spakowanym programie (RCCAD Desktop.exe)."""
from __future__ import annotations

import sys

PROG_ID = 'RCCAD.Project'


def command():
    """Polecenie otwierania pliku albo None (uruchomienie ze źródeł Pythona - bez skojarzenia)."""
    if not getattr(sys, 'frozen', False):
        return None
    return f'"{sys.executable}" "%1"'


def register():
    if sys.platform != 'win32':
        return False
    cmd = command()
    if cmd is None:
        return False
    import winreg
    root = winreg.HKEY_CURRENT_USER
    base = r'Software\Classes'
    try:
        with winreg.OpenKey(root, base + '\\' + PROG_ID + r'\shell\open\command') as key:
            if winreg.QueryValueEx(key, '')[0] == cmd:
                return True              # już wskazuje ten program
    except OSError:
        pass
    with winreg.CreateKey(root, base + r'\.rccadx') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, PROG_ID)
    with winreg.CreateKey(root, base + '\\' + PROG_ID) as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'Projekt RCCAD')
    with winreg.CreateKey(root, base + '\\' + PROG_ID + r'\DefaultIcon') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, f'"{sys.executable}",0')
    with winreg.CreateKey(root, base + '\\' + PROG_ID + r'\shell\open\command') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, cmd)
    try:                                   # Eksplorator odświeża ikony i skojarzenia
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass
    return True
