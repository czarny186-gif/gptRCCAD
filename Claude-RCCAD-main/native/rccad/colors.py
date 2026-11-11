"""Kolory brył: paleta 16 kolorów (okno Kolor, kolorowanie importowanych modeli) i pomocnicze przeliczenia."""
from __future__ import annotations

from dataclasses import replace

# (nazwa, kolor #rrggbb) - kolejność jak w siatce 4 x 4 okna Kolor
PALETTE = (
    ('Czerwony', '#e5484d'), ('Pomarańczowy', '#f28c28'), ('Żółty', '#f5c518'), ('Limonkowy', '#a3d13a'),
    ('Zielony', '#2fa56d'), ('Turkusowy', '#1fb5a8'), ('Błękitny', '#3bb0e8'), ('Niebieski', '#3b6fe0'),
    ('Granatowy', '#2a3f8f'), ('Fioletowy', '#7a4fd6'), ('Purpurowy', '#b44cc2'), ('Różowy', '#ec6fa8'),
    ('Brązowy', '#8b5a3c'), ('Beżowy', '#d9c3a0'), ('Jasnoszary', '#9eadc2'), ('Grafitowy', '#4a4f57'),
)

# kolejność kolorów dla kolejnych brył importowanego modelu: sąsiednie części wyraźnie się różnią
IMPORT_ORDER = (0, 7, 4, 1, 9, 6, 2, 11, 8, 3, 12, 5, 10, 13, 15, 14)

# jasnoszary programu (viewport.SOLID_COLOR) - kolor domyślny, gdy projekt nie ma własnego
PROGRAM_DEFAULT = (.62, .68, .76)


def to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def to_hex(rgb) -> str:
    return '#' + ''.join(f'{max(0, min(255, round(float(c) * 255))):02x}' for c in rgb)


def palette_rgb(index: int) -> tuple:
    return to_rgb(PALETTE[index % len(PALETTE)][1])


def name_of(rgb) -> str:
    """Nazwa koloru z palety albo zapis #rrggbb dla koloru własnego."""
    code = to_hex(rgb)
    return next((name for name, value in PALETTE if value == code), code.upper())


def imported(bodies, name: str):
    """Obiekty z jednego importowanego pliku: kilka obiektów razem w jednym folderze na liście obiektów (zamiast osobno
    na głównej liście), a bryły każda w innym kolorze z palety (powyżej 16 kolory się powtarzają)."""
    bodies = list(bodies)
    folder = (name or 'Import').strip()[:60] if len(bodies) > 1 else ''
    out, k = [], 0
    solids = sum(1 for b in bodies if b.kind == 'solid')
    for b in bodies:
        changes = {}
        if folder and not b.folder:
            changes['folder'] = folder
        if b.kind == 'solid' and solids > 1 and b.color is None:
            changes['color'] = palette_rgb(IMPORT_ORDER[k % len(IMPORT_ORDER)])
            k += 1
        out.append(replace(b, **changes) if changes else b)
    return out
