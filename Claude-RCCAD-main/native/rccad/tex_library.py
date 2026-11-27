"""Tekstury geometryczne - biblioteka gotowych konfiguracji (12 zestawów), miniatury rysowane z RZECZYWISTEGO wyniku generatora wzorów,
konfiguracje użytkownika (zapis, edycja nazwy, usuwanie, duplikowanie, import i eksport JSON) w folderze Ustawienia programu."""
from __future__ import annotations

import base64
import copy
import json
import math

import numpy as np

from . import tex_patterns as tp

CONFIG_FORMAT = 'rccad-texture-configs'


def _e(pid, label, pattern, mode='convex', **p):
    return dict(id=pid, label=label, params=dict(pattern=pattern, mode=mode, **p))


PRESETS = (
    _e('antislip', 'Antypoślizgowa', 'pyramids', size=2.0, height=.5, sides=4, trunc=.15, margin=1.0),
    _e('knob', 'Radełkowanie pokrętła', 'knurl_cross', size=1.6, groove=.4, height=.45, groove_angle=90.0, tip='sharp', margin=.5),
    _e('tool_grip', 'Uchwyt narzędzia', 'knurl_straight', size=2.4, width=1.4, height=.55, profile='round', margin=1.0),
    _e('checker_plate', 'Blacha ryflowana', 'checker', bump_len=9.0, bump_w=2.2, bump_gap=1.0, bump_n=2, bump_shape='oval', height=.7, bump_angle=45.0, draft=10.0),
    _e('honeycomb', 'Plaster miodu', 'honeycomb', size=6.0, wall=.8, fill='outline', height=.8, margin=1.5),
    _e('decor', 'Powierzchnia dekoracyjna', 'weave', strip=2.0, weave_gap=.3, height=.8, weave_kind='diagonal'),
    _e('electronics', 'Tekstura obudowy elektronicznej', 'dots', size=1.2, dot_shape='cap', dot_layout='stagger', height=.25, px=2.2, margin=1.5),
    _e('leather', 'Tekstura imitująca skórę', 'voronoi', size=3.0, wall=.35, irregular=.7, corner=.4, height=.25, fill='solid', seed=3),
    _e('stone', 'Tekstura imitująca kamień', 'hammered', mode='concave', ham_min=2.0, ham_max=5.0, ham_dmin=.2, ham_dmax=.6, randomness=.8, density=1.1, depth=.6, seed=7),
    _e('carbon', 'Tekstura imitująca włókno węglowe', 'weave', strip=1.6, weave_gap=.1, height=.35, weave_kind='straight'),
    _e('scales', 'Łuski dekoracyjne', 'scales', size=4.5, overlap=.35, tilt=20.0, height=.8, scale_shape='round'),
    _e('hammer', 'Powierzchnia młotkowana', 'hammered', mode='concave', ham_min=3.0, ham_max=6.0, ham_dmin=.15, ham_dmax=.45, randomness=.5, depth=.5, seed=11),
)
CATEGORY_LABELS = {'': 'Wszystkie', 'preset': 'Gotowe konfiguracje', 'pattern': 'Rodzaje wzorów', 'user': 'Konfiguracje użytkownika'}


def preset(pid):
    for e in PRESETS:
        if e['id'] == pid:
            return copy.deepcopy(e['params'])
    return None


def pattern_entries():
    return [dict(id='pat:' + k, label=v, params=dict(pattern=k)) for k, v in tp.PATTERN_LABELS.items()]


def thumbnail_polys(params, size=40.0):
    """Elementy wzoru w kwadratowym obszarze (rzeczywisty wynik generatora - miniatura pokazuje prawdziwy wygląd)."""
    p = dict(tp.DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None})
    pat = p['pattern']
    scale = {'knurl_cross': (6.0, 'size'), 'knurl_straight': (5.0, 'size'), 'knurl_spiral': (5.0, 'size'), 'honeycomb': (10.0, 'size'), 'dots': (6.0, 'size'),
             'pyramids': (7.0, 'size'), 'voronoi': (9.0, 'size'), 'scales': (9.0, 'size'), 'triangles': (9.0, 'size'), 'custom': (7.0, 'size')}.get(pat)
    if scale and abs(float(p[scale[1]]) - scale[0]) > 1e-9 and float(p['size']) < scale[0] * .5 or (scale and float(p['size']) > scale[0] * 2):
        pass
    f = 1.0
    if scale:
        f = scale[0] / max(float(p['size']), .2)
        for k in ('size', 'width', 'wall', 'groove', 'px', 'py', 'strip', 'weave_gap', 'ham_min', 'ham_max', 'corner'):
            if p.get(k):
                p[k] = float(p[k]) * f
    if pat == 'checker':
        f = 14.0 / max(float(p['bump_len']), .5)
        for k in ('bump_len', 'bump_w', 'bump_gap'):
            p[k] = float(p[k]) * f
    if pat in ('weave', 'hammered', 'herringbone'):
        f = 5.0 / max(float(p.get('strip') or p.get('arm_w') or p.get('ham_max') or 2.0), .3) if pat == 'weave' else 1.0
        if pat == 'weave':
            p['strip'] = float(p['strip']) * f
            p['weave_gap'] = float(p['weave_gap']) * f
        if pat == 'hammered':
            f = 8.0 / max(float(p['ham_max']), .5)
            p['ham_min'] = float(p['ham_min']) * f
            p['ham_max'] = float(p['ham_max']) * f
    p.update(margin=0.0, fit='exact', angle=float(p['angle']))
    if pat == 'rings':
        p.update(ring_r0=2.0, ring_gap=3.0, ring_w=1.6, ring_cx=0.0, ring_cy=0.0)
    if pat == 'herringbone':
        p.update(arm_len=7.0, arm_w=2.2)
    if pat == 'custom':
        p['custom_loops'] = [np.array([[-1.5, -1.5], [1.5, -1.5], [0, 2.0]])]
        p['custom_src'] = 'sketch'
    h = size / 2
    lo, hi = np.array([-h, -h]), np.array([h, h])
    if pat in ('waves', 'image'):
        out = []
        for i in range(-int(h), int(h), 3):
            x = np.linspace(-h, h, 40)
            out.append(('line', np.c_[x, i + 1.2 * np.sin(x * .6 + (0 if pat == 'waves' else i))]))
        return out
    fr = tp.Frame((0, 0), float(p['angle']), float(p['sx']), float(p['sy']), bool(p['mirror']))
    try:
        els = tp.generate(p, fr, lo, hi)
    except Exception:
        return []
    out = []
    for e in els[:600]:
        if e.kind == 'poly':
            out.append(('poly', e.poly, e.holes))
        elif e.kind == 'bar':
            d = np.asarray(e.p1) - np.asarray(e.p0)
            n = np.array([-d[1], d[0]]) / max(np.linalg.norm(d), 1e-9) * e.w / 2
            out.append(('poly', np.array([np.asarray(e.p0) + n, np.asarray(e.p1) + n, np.asarray(e.p1) - n, np.asarray(e.p0) - n]), []))
        elif e.kind == 'dome':
            t = np.linspace(0, 2 * math.pi, 14, endpoint=False)
            out.append(('poly', np.asarray(e.c) + e.d / 2 * np.c_[np.cos(t), np.sin(t)], []))
    return out


def thumbnail(params, px=64):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
    from . import icons
    size = 40.0
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    k = (px - 4) / size
    T = lambda q: QPointF(px / 2 + q[0] * k, px / 2 - q[1] * k)
    p.setBrush(QColor(icons.BLUE_SOFT))
    p.setPen(QPen(QColor(icons.BLUE), 1.2))
    p.drawRoundedRect(2, 2, px - 4, px - 4, 4, 4)
    p.setClipRect(3, 3, px - 6, px - 6)
    p.setPen(QPen(QColor(icons.INK), .8))
    for item in thumbnail_polys(params, size):
        if item[0] == 'line':
            path = QPainterPath(T(item[1][0]))
            for q in item[1][1:]:
                path.lineTo(T(q))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            continue
        path = QPainterPath(T(item[1][0]))
        for q in item[1][1:]:
            path.lineTo(T(q))
        path.closeSubpath()
        for hh in item[2]:
            path.moveTo(T(hh[0]))
            for q in hh[1:]:
                path.lineTo(T(q))
            path.closeSubpath()
        p.setBrush(QColor(255, 255, 255))
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


# ---------------------------------------------------------------------------------------------- konfiguracje użytkownika
def _read(name):
    from . import settings
    return settings.read(name) or {}


def _write(name, data):
    from . import settings
    settings.write(name, data)


def templates():
    return list(_read('tex_templates').get('items', []))


def _save_all(items):
    _write('tex_templates', {'items': items})


def portable(config):
    """Konfiguracja bez odniesień do bryły (ściany, identyfikatory szkiców i brył), z obrazem osadzonym."""
    cfg = _jsonable(copy.deepcopy(config))
    p = cfg.get('p') or {}
    for k in ('origin', 'origin_xy', 'custom_body'):
        p.pop(k, None)
    if p.get('custom_src') == 'solid':
        p['custom_src'] = 'sketch'
    for g in p.get('gradients') or []:
        g.pop('curve', None)
        g.pop('curve_pts', None)
    cfg['p'] = p
    reg = dict(cfg.get('region') or {})
    reg.pop('sketch', None)
    cfg['region'] = reg
    cfg.pop('exclusions', None)
    return cfg


def save_template(name, config, category='Moje'):
    items = [t for t in templates() if t['name'] != name]
    cfg = portable(config)
    items.append(dict(name=name, category=category or 'Moje', config=cfg, thumb=thumbnail_png(cfg.get('p') or {})))
    _save_all(items)
    return items


def rename_template(old, new):
    items = templates()
    if any(t['name'] == new for t in items):
        raise ValueError('Konfiguracja o tej nazwie już istnieje.')
    for t in items:
        if t['name'] == old:
            t['name'] = new
    _save_all(items)


def edit_template(name, config):
    items = templates()
    for t in items:
        if t['name'] == name:
            t['config'] = portable(config)
            t['thumb'] = thumbnail_png(t['config'].get('p') or {})
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


def export_templates(path, names=None):
    items = [t for t in templates() if names is None or t['name'] in names]
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(dict(format=CONFIG_FORMAT, version=1, items=items), fh, ensure_ascii=False, indent=1)
    return len(items)


def import_templates(path):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    if data.get('format') != CONFIG_FORMAT:
        raise ValueError('To nie jest plik konfiguracji tekstur RCCAD.')
    items = templates()
    names = {t['name'] for t in items}
    added = 0
    for t in data.get('items', []):
        nm = t.get('name') or 'Konfiguracja'
        while nm in names:
            nm += ' (import)'
        t = dict(t, name=nm)
        if not t.get('thumb'):
            t['thumb'] = thumbnail_png((t.get('config') or {}).get('p') or {})
        items.append(t)
        names.add(nm)
        added += 1
    _save_all(items)
    return added


def save_file(path, config):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(dict(format=CONFIG_FORMAT, version=1, items=[dict(name='config', config=portable(config))]), fh, ensure_ascii=False, indent=1)


def load_file(path):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    if data.get('format') != CONFIG_FORMAT or not data.get('items'):
        raise ValueError('To nie jest plik konfiguracji tekstur RCCAD.')
    return data['items'][0].get('config') or {}


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


def set_template_favorite(name, value):
    items = templates()
    for t in items:
        if t['name'] == name:
            t['favorite'] = bool(value)
    _save_all(items)


def set_template_category(name, cat):
    items = templates()
    for t in items:
        if t['name'] == name:
            t['category'] = cat
    _save_all(items)
