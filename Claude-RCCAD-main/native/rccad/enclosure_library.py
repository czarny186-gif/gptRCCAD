"""Generator obudów - etap 15: biblioteka konfiguracji, szablony użytkownika, eksport, zestawienie i masa.

Szablon zapisuje parametry i reguły generowania (kształt, rodzaj, odstępy, ścianki, podział i połączenie, systemy
zamykania, mocowania, technologia, sposób montażu, reguły wentylacji ścianek), a nie gotową geometrię - pasuje do
dowolnych elementów. Szablony użytkownika: pliki JSON w „Ustawienia/Szablony obudów” obok programu.

Eksport: STEP (każda część i cała obudowa), STL (druk 3D), 3MF (cadquery ThreeMFWriter), DXF (rozwinięcia blach z
liniami gięcia - moduł blach; płyty laserowe - obrysy), SVG (płaskie kontury), zestawienie parametrów i wymiarów (CSV i
tekst) z objętością, powierzchnią, wymiarami zewnętrznymi i szacunkową masą z gęstości materiału."""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

import numpy as np

from . import kernel

FOLDER = 'Szablony obudów'
DENSITIES = {'PLA': 1.24, 'PETG': 1.27, 'ABS': 1.04, 'ASA': 1.07, 'Nylon PA12': 1.01, 'Aluminium': 2.70, 'Stal': 7.85, 'Sklejka': .68, 'Akryl (PMMA)': 1.19}
_W = lambda v: {k: v for k in ('x-', 'x+', 'y-', 'y+', 'bottom', 'top')}
_C = lambda v, z=None: {k: (z if (z is not None and k[0] == 'z') else v) for k in ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')}
_VENT = lambda side, pattern='hex', **p: dict(kind='vent', side=side, params=dict(pattern=pattern, **p))

TEMPLATES = {
    'universal': ('Uniwersalna obudowa elektroniczna', 'Prostokątna, podstawa i pokrywa na zakładkę, śruby w narożnikach.',
                  dict(shape='box', mode='closed', clearance=_C(2.0), walls=_W(2.0), split=dict(enabled=True, mode='z', unit='%', position=75, joint='lap_in'),
                       closure=dict(systems=[dict(type='screw')])), []),
    'pcb': ('Obudowa PCB', 'Słupki pod otwory płytki, podstawa i pokrywa, śruby.',
            dict(shape='rounded', shape_params=dict(radius=4.0), mode='closed', clearance=_C(2.0, 3.0), walls=_W(2.0),
                 split=dict(enabled=True, mode='z', unit='%', position=60, joint='lap_in'), posts=dict(enabled=True, type='cylinder', fastening='pilot', screw='M3'),
                 closure=dict(systems=[dict(type='screw')])), []),
    'display': ('Obudowa wyświetlacza', 'Pulpitowa z pochyloną górą (pod wyświetlacz), zatrzaski.',
                dict(shape='desk', shape_params=dict(angle=20.0), mode='closed', clearance=_C(2.0), walls=_W(2.0),
                     split=dict(enabled=True, mode='z', unit='%', position=40, joint='lap_out')), []),
    'controller': ('Obudowa sterownika', 'Zaokrąglona, wentylacja z boków, śruby, mocowania płytki.',
                   dict(shape='rounded', shape_params=dict(radius=3.0), mode='closed', clearance=_C(3.0), walls=_W(2.5),
                        split=dict(enabled=True, mode='z', unit='%', position=70, joint='tongue'), posts=dict(enabled=True, type='ribbed'),
                        closure=dict(systems=[dict(type='screw')])), [_VENT('x-', 'slot', size=2.0, length=14.0), _VENT('x+', 'slot', size=2.0, length=14.0)]),
    'psu': ('Obudowa zasilacza', 'Wentylacja z obu stron i u góry, grube ścianki.',
            dict(shape='box', mode='closed', clearance=_C(4.0), walls=_W(3.0), split=dict(enabled=True, mode='z', unit='%', position=70, joint='lap_in'),
                 closure=dict(systems=[dict(type='screw')])), [_VENT('x-', 'hex', size=4.0), _VENT('x+', 'hex', size=4.0), _VENT('z+', 'hex', size=4.0)]),
    'sensor': ('Obudowa czujnika', 'Mała, okrągła wentylacja, zatrzaski.',
               dict(shape='rounded', shape_params=dict(radius=2.0), mode='closed', clearance=_C(1.5), walls=_W(1.6),
                    split=dict(enabled=True, mode='z', unit='%', position=60, joint='lap_in'), closure=dict(systems=[dict(type='snap')])),
               [_VENT('y-', 'circle', size=2.0)]),
    'remote': ('Obudowa pilota', 'Zaokrąglona, cienkie ścianki, zatrzaski.',
               dict(shape='rounded', shape_params=dict(radius=6.0), mode='closed', clearance=_C(1.0), walls=_W(1.6),
                    split=dict(enabled=True, mode='z', unit='%', position=50, joint='lap_in'), closure=dict(systems=[dict(type='snap')])), []),
    'desk': ('Obudowa pulpitowa', 'Pochylona góra 15°, podstawa i pokrywa, śruby.',
             dict(shape='desk', shape_params=dict(angle=15.0), mode='closed', clearance=_C(3.0), walls=_W(2.5),
                  split=dict(enabled=True, mode='z', unit='%', position=35, joint='lap_in')), []),
    'din': ('Obudowa na szynę DIN', 'Prostokątna, rowek pod szynę TS35 na tylnej ścianie, podstawa i pokrywa.',
            dict(shape='box', mode='closed', clearance=_C(2.0), walls=_W(2.5), split=dict(enabled=True, mode='z', unit='%', position=70, joint='lap_in'),
                 closure=dict(systems=[dict(type='screw')]), process=dict(mounting='din')), []),
    'vented': ('Obudowa wentylowana', 'Kratki sześciokątne na górze i z boków.',
               dict(shape='box', mode='closed', clearance=_C(3.0), walls=_W(2.0), split=dict(enabled=True, mode='z', unit='%', position=70, joint='lap_in')),
               [_VENT('z+', 'hex', size=5.0), _VENT('y-', 'hex', size=4.0), _VENT('y+', 'hex', size=4.0)]),
    'gasket': ('Obudowa z uszczelką', 'Rowek pod uszczelkę i śruby, grube ścianki.',
               dict(shape='box', mode='closed', clearance=_C(3.0), walls=_W(3.5), split=dict(enabled=True, mode='z', unit='%', position=70, joint='flat'),
                    closure=dict(systems=[dict(type='screw', params=dict(boss=8.0)), dict(type='gasket', params=dict(width=1.5, depth=1.2))])), []),
    'wall': ('Obudowa ścienna', 'Uszy montażowe z otworami na dnie, podstawa i pokrywa.',
             dict(shape='box', mode='closed', clearance=_C(2.0), walls=_W(2.5), split=dict(enabled=True, mode='z', unit='%', position=70, joint='lap_in'),
                  closure=dict(systems=[dict(type='screw')]), process=dict(mounting='wall')), []),
}


# ---------------------------------------------------------------------------------------------- szablony
def template_spec(params, sources=(), frame=None):
    """Definicja obudowy z szablonu (parametry) dla podanych elementów."""
    from .enclosure import EnclosureSpec, SPEC_VERSION
    spec = EnclosureSpec.from_json(dict(copy.deepcopy(params), version=SPEC_VERSION))
    spec.sources = list(sources)
    if frame is not None:
        spec.frame = frame
    return spec


def strip(spec):
    """Parametry i reguły szablonu z definicji obudowy (bez elementów, przestrzeni i punktów montażowych)."""
    data = spec.to_json()
    for key in ('sources', 'envelope', 'mounts', 'version', 'units'):
        data.pop(key, None)
    fr = data.get('frame') or {}
    data['frame'] = dict(mode=fr.get('mode', 'global') if fr.get('mode') != 'face' else 'global', face=None)
    sp = data.get('split') or {}
    if sp.get('face'):
        sp['face'] = None
    if (data.get('shape_params') or {}).get('sketch'):
        data['shape_params']['sketch'] = None
    return data


def user_folder():
    from . import settings
    folder = Path(settings.path(FOLDER))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _safe(name):
    name = re.sub(r'[\\\\/:*?"<>|]+', '_', name).strip() or 'Szablon'
    return name[:80]


def save_user(name, spec, rules=(), folder=None):
    folder = Path(folder) if folder else user_folder()
    path = folder / f'{_safe(name)}.json'
    path.write_text(json.dumps(dict(name=name, params=strip(spec), rules=list(rules)), ensure_ascii=False, indent=1), encoding='utf-8')
    return path


def user_templates(folder=None):
    folder = Path(folder) if folder else user_folder()
    out = {}
    for p in sorted(folder.glob('*.json')):
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            out[f'user:{p.stem}'] = (data.get('name') or p.stem, 'Szablon użytkownika', data['params'], data.get('rules') or [])
        except Exception:
            continue
    return out


def all_templates(folder=None):
    out = dict(TEMPLATES)
    out.update(user_templates(folder))
    return out


def rule_recipes(bodies, part_ids, rules):
    """Reguły szablonu dla gotowej obudowy: wentylacja na wskazanej stronie (płaska ściana części, pole wypełnione).
    Zwraca (przepisy kroków 'enc_vent', ostrzeżenia)."""
    from . import enclosure_holes as eh
    from .enclosure_vent_ui import frame_of
    by_id = {b.id: b for b in bodies}
    parts = [by_id[i] for i in part_ids if i in by_id and by_id[i].kind == 'solid']
    out, warnings = [], []
    for rule in rules or []:
        if rule.get('kind') != 'vent':
            continue
        side = rule['side']
        meta = parts[0].meta['enclosure'] if parts else None
        if meta is None:
            continue
        from .enclosure import EnclosureSpec
        ax = np.asarray(EnclosureSpec.from_json(meta).envelope.axes, float)
        d = ax['xyz'.index(side[0])] * (1 if side[1] == '+' else -1)
        best = None
        for b in parts:
            for f in b.shape.Faces():
                if f.geomType() != 'PLANE':
                    continue
                nn = np.asarray(f.normalAt(f.Center()).toTuple(), float)
                if float(nn @ d) < 1 - 1e-6:
                    continue
                c = np.asarray(f.Center().toTuple(), float)
                score = float(c @ d) + 1e-3 * f.Area()
                if best is None or score > best[0]:
                    best = (score, b, f, c, nn)
        if best is None:
            continue
        _s, body, face, c, nn = best
        recipe = dict(type='enc_vent', target=body.id, point=[float(x) for x in c], normal=[float(x) for x in nn], params={})
        frame = frame_of(recipe)
        lo, hi, _uv = eh._bbox_uv(face.wrapped, frame)
        try:
            th = eh.wall_thickness(body.shape.wrapped, frame, (lo + hi) / 2)
        except kernel.CadError:
            continue
        params = dict(cu=float((lo[0] + hi[0]) / 2), cv=float((lo[1] + hi[1]) / 2), width=float(max(1.0, hi[0] - lo[0] - 2 * th - 2)),
                      height=float(max(1.0, hi[1] - lo[1] - 2 * th - 2)), margin=3.0)
        params.update(rule.get('params') or {})
        from . import enclosure_vents as ev
        fitted = None
        for _attempt in range(6):                          # reguła dopasowana do ścianki: mniejsze otwory, gdy się nie mieszczą
            try:
                holes, _area = ev.layout(dict(ev.DEFAULTS, **params))
            except kernel.CadError:
                holes = []
            if any(h[-1] == 'vent' for h in holes):
                fitted = params
                break
            params = dict(params, size=float(params.get('size', ev.DEFAULTS['size'])) * .7,
                          length=float(params.get('length', ev.DEFAULTS['length'])) * .7, margin=float(params['margin']) * .6)
        if fitted is None:
            warnings.append(f'Wentylacja ({side}): ścianka za mała na otwory - reguła pominięta.')
            continue
        recipe['params'] = fitted
        out.append(recipe)
    return out, warnings


def apply_rules(bodies, part_ids, rules, seq0=0):
    """Reguły szablonu na gotowej obudowie: każda wentylacja budowana jak krok 'enc_vent' (z kontrolą uszkodzeń); gdy
    otwory trafiają w mocowania / sąsiednie ścianki, obszar jest zmniejszany (do 4 prób), a w końcu reguła pomijana z
    ostrzeżeniem. Zwraca (bryły po regułach, [(przepis kroku, bryły po kroku)], ostrzeżenia)."""
    from .enclosure_vent_ui import run as vent_run
    recipes, warnings = rule_recipes(bodies, part_ids, rules)
    done = []
    for n, recipe in enumerate(recipes):
        last = None
        for _attempt in range(7):
            try:
                import uuid
                rec = dict(recipe, id=uuid.uuid4().hex, seq=seq0 + len(done))
                bodies = vent_run(bodies, rec)
                done.append((rec, list(bodies)))
                last = None
                break
            except kernel.CadError as e:
                last = e
                p = recipe['params']
                f = .8
                q = dict(p, width=float(p['width']) * f, height=float(p['height']) * f)
                if 'Żaden otwór' in str(e) or 'wychodzą poza' in str(e):
                    q.update(size=float(q.get('size', 4.0)) * f, length=float(q.get('length', 12.0)) * f, margin=float(q.get('margin', 2.0)) * f)
                recipe = dict(recipe, params=q)
        if last is not None:
            warnings.append(f'Wentylacja szablonu pominięta: {last}')
    return bodies, done, warnings


def fit_template(spec, env, bodies=None):
    """Dopasowanie reguł szablonu do wielkości elementów: ramię zatrzasku skrócone do wysokości podstawy.
    Zwraca listę opisów zmian."""
    from .enclosure import layout, split_of, split_position
    notes = []
    sp = split_of(spec)
    systems = (spec.closure or {}).get('systems') or []
    if not sp.get('enabled') or sp.get('mode') not in ('x', 'y', 'z') or not systems:
        return notes
    from .enclosure_closure import DEFAULTS as CD
    lay = layout(env, spec, bodies=bodies)
    i = 'xyz'.index(sp['mode'])
    room = split_position(env, spec, lay) - float(lay['inner'][0][i]) - 1.5
    for s in systems:
        if s.get('type') != 'snap':
            continue
        prm = dict(CD['snap'], **(s.get('params') or {}))
        if prm['length'] > room:
            if room < 3.0:
                raise kernel.CadError('Podstawa za niska na zatrzaski szablonu - przesuń podział albo wybierz śruby.')
            s['params'] = dict(s.get('params') or {}, length=round(room, 2))
            notes.append(f'Ramię zatrzasku skrócone do {room:.1f} mm (wysokość podstawy).')
    return notes


# ---------------------------------------------------------------------------------------------- montaż (DIN, ścienny)
def mounting(env, spec, parts, bodies=None):
    """Sposób montażu z szablonu: rowek pod szynę DIN TS35 (tylna / dolna ściana) albo uszy do montażu na ścianie."""
    import cadquery as cq
    from .enclosure import _boolean, _single, _unified, check_solid, layout
    kind = (spec.process or {}).get('mounting')
    if kind not in ('din', 'wall'):
        return parts
    if (spec.shape or 'box') not in ('box', 'rounded', 'chamfer'):
        raise kernel.CadError('Montaż na szynie DIN / ścianie jest dostępny dla obudowy prostokątnej, zaokrąglonej i fazowanej.')
    name = 'base' if 'base' in parts else ('body' if 'body' in parts else None)
    if name is None:
        return parts
    lay = layout(env, spec, bodies=bodies)
    olo, ohi = (np.asarray(x, float) for x in lay['outer'])
    ax = np.asarray(env.axes, float)
    c = np.asarray(env.center, float)
    W = lambda s: kernel.transformed(cq.Shape.cast(s), ax.T, c).wrapped
    from .enclosure import _make_box
    shape = parts[name].wrapped
    if kind == 'din':
        width, depth = 35.4, 1.5                         # TS35: szerokość szyny 35 mm + luz
        if ohi[0] - olo[0] < width + 4 or lay['outer_size'][2] < 10:
            raise kernel.CadError('Obudowa za mała na rowek szyny DIN TS35 (szerokość co najmniej 39,4 mm).')
        mid = (olo[0] + ohi[0]) / 2
        groove = _make_box((mid - width / 2, olo[1] - 1, olo[2] - 1), (mid + width / 2, ohi[1] + 1, olo[2] + depth))
        bottom = lay['inner'][0][2] - olo[2]
        if depth >= bottom - .4:
            raise kernel.CadError('Dno za cienkie na rowek szyny DIN - pogrub dno.')
        shape = _boolean('cut', shape, W(groove), 'rowek szyny DIN')
    else:
        ear, hole, th = 12.0, 4.5, max(2.0, float(lay['inner'][0][2] - olo[2]))
        for sx in (-1, 1):
            x0 = olo[0] - ear if sx < 0 else ohi[0]
            tab = _make_box((x0, (olo[1] + ohi[1]) / 2 - ear / 2, olo[2]), (x0 + ear, (olo[1] + ohi[1]) / 2 + ear / 2, olo[2] + th))
            shape = _boolean('fuse', shape, W(tab), 'ucho montażowe')
            cx = x0 + ear / 2
            cyl = cq.Solid.makeCylinder(hole / 2, th + 2, cq.Vector(cx, (olo[1] + ohi[1]) / 2, olo[2] - 1)).wrapped
            shape = _boolean('cut', shape, W(cyl), 'otwór ucha')
    out = dict(parts)
    out[name] = check_solid(_single(_unified(shape), 'Obudowa z mocowaniem'))
    return out


# ---------------------------------------------------------------------------------------------- zestawienie i eksport
def properties(shape, density=1.24):
    """Objętość (mm³), powierzchnia (mm²), wymiary zewnętrzne (mm) i masa (g) z gęstości (g/cm³)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    s = shape.wrapped if hasattr(shape, 'wrapped') else shape
    v, a = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(s, v)
    BRepGProp.SurfaceProperties_s(s, a)
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(s, box, False, False)
    x0, y0, z0, x1, y1, z1 = box.Get()
    vol = float(v.Mass())
    return dict(volume=vol, area=float(a.Mass()), dims=(x1 - x0, y1 - y0, z1 - z0), mass=vol * float(density) / 1000.0)


def group_parts(bodies, body_id):
    from .enclosure_param import group
    by_id = {b.id: b for b in bodies}
    body = by_id.get(body_id)
    if body is None or not (body.meta or {}).get('enclosure'):
        raise kernel.CadError('Wskaż obudowę z Generatora obudów.')
    return group(bodies, body)


def summary(bodies, body_id, density=1.24):
    """Zestawienie: części (bryły) z właściwościami i sumy."""
    rows = []
    for b in group_parts(bodies, body_id):
        part = (b.meta or {}).get('enclosure_part') or 'body'
        if b.kind != 'solid' or part.startswith(('flat_', 'bends_')):
            continue
        rows.append(dict(name=b.name, part=part, **properties(b.shape, density)))
    total = dict(volume=sum(r['volume'] for r in rows), area=sum(r['area'] for r in rows), mass=sum(r['mass'] for r in rows))
    return rows, total


def _polyline_faces(shape):
    """Kontury płaskiej części (górna ściana) jako łamane 2D (DXF / SVG)."""
    import cadquery as cq
    sh = cq.Shape.cast(shape.wrapped if hasattr(shape, 'wrapped') else shape)
    top = max(sh.Faces(), key=lambda f: f.Center().z if f.geomType() == 'PLANE' else -1e9)
    loops = []
    for w in top.Wires():
        pts = []
        for e in w.Edges():
            n = 2 if e.geomType() == 'LINE' else 24
            pts += [e.positionAt(t).toTuple()[:2] for t in np.linspace(0, 1, n)][:-1]
        if pts:
            loops.append(pts + [pts[0]])
    return loops


def export(bodies, body_id, folder, density=1.24, material='PLA', formats=('step', 'stl', '3mf', 'dxf', 'svg', 'report')):
    """Eksport obudowy do folderu; zwraca listę zapisanych plików. Każda bryła sprawdzana BRepCheck przed zapisem."""
    import cadquery as cq
    from OCP.BRepCheck import BRepCheck_Analyzer
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    parts = group_parts(bodies, body_id)
    base = next((b for b in parts if (b.meta or {}).get('enclosure_part') in (None, 'base', 'body')), parts[0])
    title = _safe(base.folder or base.name)
    solids, flats, written = [], [], []
    for b in parts:
        part = (b.meta or {}).get('enclosure_part') or 'body'
        if b.kind != 'solid':
            continue
        if not BRepCheck_Analyzer(b.shape.wrapped).IsValid():
            raise kernel.CadError(f'„{b.name}” ma niepoprawną geometrię B-Rep - eksport przerwany.')
        (flats if part.startswith('flat_') else solids).append(b)
    if 'step' in formats:
        p = folder / f'{title} - całość.step'
        kernel.export_shapes([b.shape for b in solids], p)
        written.append(p)
        for b in solids:
            p = folder / f'{_safe(b.name)}.step'
            kernel.export_shapes([b.shape], p)
            written.append(p)
    if 'stl' in formats:
        for b in solids:
            p = folder / f'{_safe(b.name)}.stl'
            kernel.export_shapes([b.shape], p)
            written.append(p)
    if '3mf' in formats:
        p = folder / f'{title}.3mf'
        try:
            cq.exporters.export(cq.Compound.makeCompound([b.shape for b in solids]), str(p), exportType='3MF', tolerance=.05, angularTolerance=.08)
            written.append(p)
        except Exception:
            pass                                            # 3MF niedostępny w tej wersji - pozostałe formaty zapisane
    if 'dxf' in formats or 'svg' in formats:
        from . import sheetmetal as shm
        sheet_done = set()
        for b in solids:
            sheet = (b.meta or {}).get('sheet')
            if sheet and 'dxf' in formats:                  # rozwinięcie blachy z liniami gięcia (moduł blach)
                p = folder / f'{_safe(b.name)} - rozwinięcie.dxf'
                try:
                    shm.export_flat_dxf(sheet['recipe'], str(p))
                    written.append(p)
                    sheet_done.add('flat_' + ((b.meta or {}).get('enclosure_part') or 'body'))
                except kernel.CadError:
                    pass
        for b in flats:
            loops = _polyline_faces(b.shape)
            if 'dxf' in formats and (b.meta or {}).get('enclosure_part') not in sheet_done:   # blacha: DXF z liniami gięcia już jest
                import ezdxf
                doc = ezdxf.new()
                doc.layers.add('CUT')
                msp = doc.modelspace()
                for loop in loops:
                    msp.add_lwpolyline(loop, close=True, dxfattribs={'layer': 'CUT'})
                p = folder / f'{_safe(b.name)}.dxf'
                doc.saveas(str(p))
                written.append(p)
            if 'svg' in formats:
                pts = np.array([q for loop in loops for q in loop])
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                paths = ''.join('<path d="M ' + ' L '.join(f'{x - lo[0]:.4f} {hi[1] - y:.4f}' for x, y in loop) + ' Z" />' for loop in loops)
                svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{hi[0] - lo[0]:.3f}mm" height="{hi[1] - lo[1]:.3f}mm" '
                       f'viewBox="0 0 {hi[0] - lo[0]:.4f} {hi[1] - lo[1]:.4f}"><g fill="none" stroke="black" stroke-width="0.1">{paths}</g></svg>')
                p = folder / f'{_safe(b.name)}.svg'
                p.write_text(svg, encoding='utf-8')
                written.append(p)
    if 'report' in formats:
        rows, total = summary(bodies, body_id, density)
        from .enclosure import EnclosureSpec
        spec = EnclosureSpec.from_json(base.meta['enclosure'])
        lines = ['część;objętość mm3;powierzchnia mm2;X mm;Y mm;Z mm;masa g']
        for r in rows:
            lines.append(f'{r["name"]};{r["volume"]:.3f};{r["area"]:.3f};{r["dims"][0]:.3f};{r["dims"][1]:.3f};{r["dims"][2]:.3f};{r["mass"]:.3f}')
        lines.append(f'RAZEM;{total["volume"]:.3f};{total["area"]:.3f};;;;{total["mass"]:.3f}')
        p = folder / f'{title} - zestawienie.csv'
        p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        written.append(p)
        text = [f'{base.folder or base.name} - zestawienie parametrów', '',
                f'Kształt: {spec.shape}; rodzaj: {spec.mode}; technologia: {(spec.process or {}).get("tech", "brak")}',
                f'Odstępy: {spec.clearance}', f'Ścianki: {spec.walls}', f'Podział: {spec.split}', f'Zamknięcia: {(spec.closure or {}).get("systems", [])}',
                f'Punkty montażowe: {len(spec.mounts or [])}', f'Materiał: {material}, gęstość {density:g} g/cm³', '']
        for r in rows:
            text.append(f'{r["name"]}: {r["dims"][0]:.2f} × {r["dims"][1]:.2f} × {r["dims"][2]:.2f} mm, objętość {r["volume"]:.1f} mm³, '
                        f'powierzchnia {r["area"]:.1f} mm², masa {r["mass"]:.2f} g')
        text.append(f'Razem: objętość {total["volume"]:.1f} mm³, masa (szacunkowa) {total["mass"]:.2f} g')
        p = folder / f'{title} - zestawienie.txt'
        p.write_text('\n'.join(text) + '\n', encoding='utf-8')
        written.append(p)
    return written
