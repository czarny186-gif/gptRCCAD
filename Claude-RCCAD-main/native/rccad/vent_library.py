"""Wentylacja - biblioteka wzorów (PatternLibrary): kategorie, gotowe wzory (zestawy parametrów kształtu, układu
i generatora), miniatury rysowane z RZECZYWISTEGO wyniku generatora (nie obrazki), ulubione, szablony użytkownika
(zapis, nazwy, usuwanie, duplikowanie, import i eksport JSON, kategorie, miniatury) w folderze Ustawienia programu."""
from __future__ import annotations

import base64
import copy
import json

import numpy as np

from . import vent_geom2d as g2
from . import vent_layout as vl
from . import vent_shapes as vs

CATEGORIES = ('basic', 'technical', 'organic', 'fan', 'user')
CATEGORY_LABELS = {'basic': 'Podstawowe kształty', 'technical': 'Wzory techniczne', 'organic': 'Organiczne i dekoracyjne', 'fan': 'Kratki wentylatorów',
                   'user': 'Szablony użytkownika'}


def _e(pid, cat, label, **p):
    return dict(id=pid, cat=cat, label=label, params=p)


PATTERNS = [
    # A. podstawowe
    _e('circle', 'basic', 'Otwory okrągłe', kind='circle', w=4.0, layout='hexagonal'),
    _e('square', 'basic', 'Otwory kwadratowe', kind='square', w=4.0, layout='square'),
    _e('rect', 'basic', 'Otwory prostokątne', kind='rect', w=6.0, h=3.0, layout='rect'),
    _e('rrect', 'basic', 'Prostokąty zaokrąglone', kind='rrect', w=6.0, h=3.5, corner=1.0, layout='offset_h'),
    _e('tri', 'basic', 'Trójkąty równoboczne', kind='tri', w=5.0, layout='alternating', alt_angle=180.0),
    _e('tri_ratio', 'basic', 'Trójkąty (proporcje)', kind='tri_ratio', w=6.0, h=4.0, layout='alternating', alt_angle=180.0),
    _e('rhombus', 'basic', 'Romby', kind='rhombus', w=6.0, h=4.0, layout='offset_h'),
    _e('trapezoid', 'basic', 'Trapezy', kind='trapezoid', w=6.0, h=4.0, ratio=.6, layout='alternating', alt_angle=180.0),
    _e('pentagon', 'basic', 'Pięciokąty', kind='pentagon', w=5.0, layout='offset_h'),
    _e('hex', 'basic', 'Sześciokąty - plaster miodu', kind='hex', w=5.0, layout='hexagonal', hole_angle=30.0),
    _e('octagon', 'basic', 'Ośmiokąty', kind='octagon', w=5.0, layout='square'),
    _e('ngon', 'basic', 'Wielokąty (n boków)', kind='ngon', w=5.0, sides=7, layout='hexagonal'),
    _e('ellipse', 'basic', 'Elipsy', kind='ellipse', w=6.0, h=3.0, layout='offset_h'),
    _e('capsule', 'basic', 'Kapsuły', kind='capsule', w=8.0, h=3.0, layout='offset_h'),
    _e('bean', 'basic', 'Fasolki', kind='bean', w=8.0, h=3.0, bend=70.0, layout='offset_h'),
    _e('cross', 'basic', 'Krzyże', kind='cross', w=6.0, h=6.0, arm=.3, layout='offset_h'),
    _e('star', 'basic', 'Gwiazdy', kind='star', w=6.0, arms=5, ratio=.45, layout='offset_h'),
    _e('drop', 'basic', 'Krople', kind='drop', w=4.0, h=6.0, layout='offset_h'),
    _e('halfcircle', 'basic', 'Półokręgi', kind='halfcircle', w=6.0, layout='alternating', alt_angle=180.0),
    # B. techniczne
    _e('slot_h', 'technical', 'Szczeliny poziome', kind='rect', w=14.0, h=2.0, layout='offset_h', shift_row=0.0),
    _e('slot_v', 'technical', 'Szczeliny pionowe', kind='rect', w=14.0, h=2.0, layout='offset_h', shift_row=0.0, hole_angle=90.0),
    _e('slot_d', 'technical', 'Szczeliny ukośne', kind='rect', w=14.0, h=2.0, layout='offset_h', shift_row=0.0, hole_angle=45.0),
    _e('slot_r', 'technical', 'Szczeliny zaokrąglone', kind='capsule', w=14.0, h=2.5, layout='offset_h', shift_row=50.0),
    _e('herringbone', 'technical', 'Jodełka', generator='herringbone', channel=2.0, px=12.0),
    _e('zigzag', 'technical', 'Zygzaki', generator='zigzag', channel=1.6, amplitude=2.5, frequency=.12),
    _e('arcs', 'technical', 'Łuki koncentryczne', generator='arcs', channel=2.0, arms_n=4),
    _e('spiral', 'technical', 'Spirale', generator='spiral', channel=2.0, arms_n=2, turns=4.0),
    _e('turbine', 'technical', 'Wzór turbinowy', generator='turbine', channel=2.0, arms_n=10, branch_angle=40.0),
    _e('labyrinth', 'technical', 'Labirynt', generator='labyrinth', channel=1.6, cell=7.0),
    _e('sine', 'technical', 'Fale sinusoidalne', generator='sine', channel=1.6, amplitude=2.5, frequency=.1),
    _e('weave', 'technical', 'Plecionka', generator='weave', channel=2.0, px=12.0),
    _e('grid_rect', 'technical', 'Kratka prostokątna', generator='grid_rect', kind='square', w=5.0, bridge=1.0),
    _e('grid_diag', 'technical', 'Kratka ukośna', generator='grid_diag', kind='square', w=5.0, bridge=1.0),
    _e('louvers', 'technical', 'Żaluzje wentylacyjne', kind='rect', w=16.0, h=3.0, layout='rect', py=7.0, louver=True),
    _e('radial', 'technical', 'Wzór promieniowy', kind='circle', w=3.0, layout='radial', arms_n=16),
    _e('radial_slots', 'technical', 'Szczeliny promieniowe', generator='radial_slots', channel=2.0, arms_n=12),
    # C. organiczne
    _e('voronoi', 'organic', 'Voronoi', generator='voronoi', cell=8.0, bridge=1.2, relax=2, round_r=.6),
    _e('gyroid2d', 'organic', 'Gyroid 2D', generator='gyroid2d', cell=10.0, opening=.35),
    _e('gyroid3d', 'organic', 'Gyroid 3D (przestrzenny)', generator='gyroid3d', cell=10.0),
    _e('branches', 'organic', 'Organiczne rozgałęzienia', generator='branches', channel=1.8, arms_n=5, branch_angle=35.0),
    _e('gradient', 'organic', 'Gradient wielkości otworów', kind='circle', w=5.0, layout='hexagonal',
       gradients=[dict(param='size', dir='h', func='linear', k0=1.0, k1=.35)]),
    _e('bubbles', 'organic', 'Losowe pęcherzyki', generator='bubbles', w=7.0, size_min=1.5),
    _e('fishscale', 'organic', 'Rybie łuski', generator='fishscale', w=8.0, ratio=.5),
    _e('arabesque', 'organic', 'Arabeski', kind='quatrefoil', w=8.0, layout='offset_h'),
    _e('fractal', 'organic', 'Fraktale (dywan Sierpińskiego)', generator='fractal', level=3),
    _e('leaves', 'organic', 'Struktury liści', generator='leaves', w=8.0, branch_angle=35.0),
    _e('irregular', 'organic', 'Nieregularne wielokąty', kind='irregular', w=5.0, sides=7, irregularity=.5, layout='random'),
    _e('mixed', 'organic', 'Wzór mieszany (okręgi + sześciokąty)', kind='circle', w=4.0, layout='hexagonal', mix_mode='alternate',
       mixed=[dict(kind='circle', w=4.0), dict(kind='hex', w=4.0, angle=30.0)]),
]
for _st in vl.FAN_STYLES:                                              # D. kratki wentylatorów (osobna kategoria)
    PATTERNS.append(_e(f'fan_{_st}', 'fan', f'Kratka wentylatora - {vl.FAN_STYLE_LABELS[_st]}', generator='fan', fan=40, fan_style=_st,
                       w=3.0, h=8.0, channel=2.5, arms_n=8 if _st in ('radial', 'turbine') else 4, region=dict(type='circle', d=54.0)))
BY_ID = {e['id']: e for e in PATTERNS}


def preset(pid):
    """Parametry wzoru z biblioteki (kopia) - kształt, układ, generator."""
    e = BY_ID.get(pid)
    return copy.deepcopy(e['params']) if e else {}


# ---------------------------------------------------------------------------------------------- miniatury
def thumbnail_holes(params, size=56.0):
    """Otwory wzoru w kwadratowym obszarze (rzeczywisty wynik generatora - miniatura pokazuje prawdziwy wygląd)."""
    p = dict(vl.DEFAULTS, **params)
    p.update(margin=1.0, margin_holes=0.0)
    if p.get('generator') == 'fan':
        p['fan'] = 40
        p['fan_d'] = size - 4
    if p.get('generator') == 'gyroid3d':
        p = dict(p, generator='gyroid2d')
    h = size / 2
    reg = g2.Region([np.array([[-h, -h], [h, -h], [h, h], [-h, h]], float)])
    try:
        holes, _r, _s, _u = vl.generate(p, reg)
    except Exception:
        return []
    return [x for x in holes if x['status'] in ('ok', 'adjust')]


def thumbnail(params, px=64):
    """QPixmap miniatury: płyta (jasnoniebieska) z otworami (białe) i obrysem w kolorze atramentu programu."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
    from . import icons
    size = 56.0
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    k = (px - 4) / size
    T = lambda q: QPointF(px / 2 + q[0] * k, px / 2 - q[1] * k)
    p.setBrush(QColor(icons.BLUE_SOFT))
    p.setPen(QPen(QColor(icons.BLUE), 1.2))
    p.drawRoundedRect(2, 2, px - 4, px - 4, 4, 4)
    p.setBrush(QColor(255, 255, 255))
    p.setPen(QPen(QColor(icons.INK), .9))
    for h in thumbnail_holes(params, size):
        for n, poly in enumerate(vs.outline(h['loops'], 16)):
            path = QPainterPath(T(poly[0]))
            for q in poly[1:]:
                path.lineTo(T(q))
            path.closeSubpath()
            p.setBrush(QColor(255, 255, 255) if n == 0 else QColor(icons.BLUE_SOFT))
            p.drawPath(path)
    p.end()
    return pm


def thumbnail_png(params, px=64):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    pm = thumbnail(params, px)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, 'PNG')
    return base64.b64encode(bytes(ba)).decode('ascii')


# ---------------------------------------------------------------------------------------------- szablony i ulubione
def _read(name):
    from . import settings
    return settings.read(name) or {}


def _write(name, data):
    from . import settings
    settings.write(name, data)


def favorites():
    return list(_read('vent_favorites').get('ids', []))


def set_favorite(pid, on=True):
    ids = [x for x in favorites() if x != pid]
    if on:
        ids.append(pid)
    _write('vent_favorites', {'ids': ids})
    return ids


def templates():
    """Szablony użytkownika: [dict(name, category, favorite, config, thumb)] - config: pełne parametry obszaru
    (wzór, układ, wymiary, gradienty...) i ustawienia cięcia, bez odniesień do konkretnej bryły."""
    return list(_read('vent_templates').get('items', []))


def _save_all(items):
    _write('vent_templates', {'items': items})


def save_template(name, config, category='Moje', favorite=False):
    items = [t for t in templates() if t['name'] != name]
    cfg = _portable(config)
    items.append(dict(name=name, category=category or 'Moje', favorite=bool(favorite), config=cfg, thumb=thumbnail_png(cfg.get('area') or {})))
    _save_all(items)
    return items


def rename_template(old, new):
    items = templates()
    if any(t['name'] == new for t in items):
        raise ValueError('Szablon o tej nazwie już istnieje.')
    for t in items:
        if t['name'] == old:
            t['name'] = new
    _save_all(items)


def delete_template(name):
    _save_all([t for t in templates() if t['name'] != name])


def duplicate_template(name):
    items = templates()
    src = next(t for t in items if t['name'] == name)
    n = 2
    while any(t['name'] == f'{name} ({n})' for t in items):
        n += 1
    items.append(dict(copy.deepcopy(src), name=f'{name} ({n})'))
    _save_all(items)
    return f'{name} ({n})'


def set_template_favorite(name, on):
    items = templates()
    for t in items:
        if t['name'] == name:
            t['favorite'] = bool(on)
    _save_all(items)


def set_template_category(name, cat):
    items = templates()
    for t in items:
        if t['name'] == name:
            t['category'] = cat
    _save_all(items)


def export_templates(path, names=None):
    items = [t for t in templates() if names is None or t['name'] in names]
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(dict(format='rccad-vent-templates', version=1, items=items), fh, ensure_ascii=False, indent=1)
    return len(items)


def import_templates(path):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    if data.get('format') != 'rccad-vent-templates':
        raise ValueError('To nie jest plik szablonów wentylacji RCCAD.')
    items = templates()
    names = {t['name'] for t in items}
    added = 0
    for t in data.get('items', []):
        nm = t.get('name') or 'Szablon'
        while nm in names:
            nm += ' (import)'
        t = dict(t, name=nm)
        if not t.get('thumb'):
            t['thumb'] = thumbnail_png((t.get('config') or {}).get('area') or {})
        items.append(t)
        names.add(nm)
        added += 1
    _save_all(items)
    return added


def _portable(config):
    """Konfiguracja bez odniesień do bryły (ściany, identyfikatory szkiców, ręczne zmiany otworów)."""
    cfg = copy.deepcopy(config)
    area = dict(cfg.get('area') or {})
    for k in ('overrides', 'added', 'curve', 'points'):
        area.pop(k, None)
    reg = dict(area.get('region') or {})
    reg.pop('sketch', None)
    area['region'] = reg
    cfg['area'] = _jsonable(area)
    cfg['cut'] = _jsonable(cfg.get('cut') or {})
    return cfg


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x
