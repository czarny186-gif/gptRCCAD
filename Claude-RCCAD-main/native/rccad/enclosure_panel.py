"""Generator obudów - etap 19: panel sterowania.

Elementy na wskazanej zewnętrznej płaskiej powierzchni części obudowy (układ powierzchni: punkt, normalna na zewnątrz,
osie u, v). Położenie elementu (u, v) - ręcznie albo z rzutu wskazanego komponentu (środek jego obrysu; komponent nie
jest zmieniany). Elementy:
- ramka wyświetlacza (LCD / OLED) i ekranu dotykowego: otwór = powierzchnia aktywna (osobno od obrysu modułu) powiększona
  o niezależne odsunięcia z każdej strony, montaż na równi (wnęka od zewnątrz na obrys), poniżej (wnęka od środka) albo
  powyżej (ramka wystająca na zewnątrz), podpory w narożnikach modułu, miejsce na przewody / złącze;
- zagłębienie pod wyświetlacz, otwory pod enkoder i potencjometr (z wycięciem pod wypust ustalający), przełącznik
  (prostokątny), suwak (szczelina), maskownica głośnika (wzór otworów z generatora wentylacji), otwór mikrofonowy
  (z wnęką na uszczelkę od środka), okno ochronne (osobna przezroczysta płytka + wnęka i otwór), przycisk membranowy
  (wnęka na klawiaturę + szczelina na taśmę);
- przycisk mechaniczny: osobna bryła - nasadka nad powierzchnią, trzpień przez otwór (z luzem) do przycisku wewnątrz,
  kołnierz-ogranicznik od środka; prowadnica (tulejka) w obudowie; sprawdzane położenie spoczynkowe (kołnierz przy
  ściance) i po naciśnięciu (trzpień dosięga przycisku w zakresie skoku);
- pokrętło: osobna bryła (cylindryczne, stożkowe, wielokątne, radełkowane, z uchwytem), otwór na wałek okrągły, D,
  sześciokątny, wielowypustowy albo z profilu szkicu, z głębokością osadzenia i luzem;
- prowadnica światła: osobna bryła od diody do powierzchni - prosta, stopniowana albo zakrzywiona (BRepOffsetAPI_MakePipe po
  łuku), z otworem w ściance.
Elementy ruchome i okna to osobne bryły. Kontrole: dostępność od zewnątrz, kolizje osobnych brył z obudową i komponentami,
zakres ruchu przycisków. Program nie deklaruje skuteczności optycznej prowadnic światła ani szczelności."""
from __future__ import annotations

import math

import numpy as np

from . import kernel
from . import enclosure_holes as eh

ELEMENTS = ('display', 'touch', 'recess', 'encoder', 'pot', 'knob', 'button', 'membrane', 'slider', 'switch', 'lightpipe', 'speaker', 'mic', 'window')
ELEMENT_LABELS = {'display': 'Ramka wyświetlacza LCD / OLED', 'touch': 'Ramka ekranu dotykowego', 'recess': 'Zagłębienie pod wyświetlacz',
                  'encoder': 'Otwór pod enkoder', 'pot': 'Otwór pod potencjometr', 'knob': 'Pokrętło', 'button': 'Przycisk mechaniczny',
                  'membrane': 'Przycisk membranowy (geometria)', 'slider': 'Suwak', 'switch': 'Otwór pod przełącznik', 'lightpipe': 'Prowadnica światła LED',
                  'speaker': 'Maskownica głośnika', 'mic': 'Otwór mikrofonowy', 'window': 'Okno ochronne'}
MOUNTS = ('flush', 'below', 'above')
KNOBS = ('cylinder', 'cone', 'polygon', 'knurled', 'handle')
BORES = ('round', 'd', 'hex', 'spline', 'sketch')
PIPES = ('straight', 'stepped', 'curved')
DEFAULTS = dict(element='display', u=0.0, v=0.0, angle=0.0, active_w=40.0, active_h=30.0, module_w=50.0, module_h=40.0, module_t=4.0,
                module_du=0.0, module_dv=0.0, frame_l=0.0, frame_r=0.0, frame_t=0.0, frame_b=0.0, mount='below', bezel=1.5, clearance=.3,
                supports=True, conn_w=12.0, conn_h=5.0, diameter=7.0, tab=True, width=6.0, length=20.0, height=8.0, depth=1.0,
                travel=.5, stem=0.0, stop=1.0, shape='flat', knob='knurled', sides=6, bore='d', shaft=6.0, flat=4.5, insert=6.0, splines=18,
                pipe='straight', pipe_d=3.0, pipe_d2=5.0, bend=10.0, pattern='hex', hole=2.0, web=1.2, gasket=.8, window_t=1.5)


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _rot(p, a):
    c, s = math.cos(a), math.sin(a)
    return np.array([c * p[0] - s * p[1], s * p[0] + c * p[1]])


def frame_of(face):
    n = np.asarray(face['normal'], float)
    up = (0, 0, 1.0) if abs(n[2]) < .9 else (0, 1.0, 0)
    return eh.wall_frame(face['point'], n, up)[:4]


def _rectf(fr, cu, cv, w, h, ang, z=0.0, r=0.0):
    o, u, v, n = fr
    pts = [tuple(np.array([cu, cv]) + _rot(q, ang)) for q in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
    face = eh._plane_face(pts, (o + n * z, u, v, n))
    if r > 1e-6:
        face = eh._fillet2d(face, min(r, w / 2 - 1e-3, h / 2 - 1e-3))
    return face


def _box_tool(fr, cu, cv, w, h, ang, z0, z1, r=0.0):
    return eh._prism(_rectf(fr, cu, cv, w, h, ang, 0.0, r), fr, z1, z0)


def _cyl(fr, cu, cv, d, z0, z1):
    return eh._prism(eh._circle_face(cu, cv, d / 2, fr), fr, z1, z0)


def _wall(target, fr, cu, cv):
    """Grubość ścianki pod punktem (u, v)."""
    return eh.wall_thickness(target, fr, (cu, cv))


def from_component(fr, comp_shape):
    """Środek rzutu komponentu na powierzchnię i odległość jego najbliższego punktu od powierzchni (w głąb)."""
    import cadquery as cq
    bb = cq.Shape.cast(comp_shape).BoundingBox()
    pts = np.array([[x, y, z] for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)])
    uv = eh._uv(pts, fr)
    o, u, v, n = fr
    depth = (pts - o) @ n
    return (uv.min(axis=0) + uv.max(axis=0)) / 2, float(-depth.max()), uv.min(axis=0), uv.max(axis=0)


# ---------------------------------------------------------------------------------------------- elementy
def element(target, fr, it, components=()):
    """Jeden element panelu: dict(cut=[narzędzia w obudowie], add=[bryły do obudowy], parts=[(nazwa, bryła osobna)],
    checks=[...], access=[walec dostępu od zewnątrz])."""
    import cadquery as cq
    from .enclosure import _boolean
    p = dict(DEFAULTS, **it)
    kind = p['element']
    if kind not in ELEMENTS:
        raise kernel.CadError('Nieznany element panelu.')
    cu, cv, ang = float(p['u']), float(p['v']), math.radians(float(p['angle']))
    g = float(p['clearance'])
    th = _wall(target, fr, cu, cv)
    out = dict(cut=[], add=[], parts=[], checks=[], access=[])
    o, u, v, n = fr
    if kind in ('display', 'touch', 'recess'):
        aw = float(p['active_w']) + float(p['frame_l']) + float(p['frame_r'])
        ah = float(p['active_h']) + float(p['frame_t']) + float(p['frame_b'])
        acu = cu + (float(p['frame_r']) - float(p['frame_l'])) / 2
        acv = cv + (float(p['frame_t']) - float(p['frame_b'])) / 2
        mw, mh, mt = float(p['module_w']) + 2 * g, float(p['module_h']) + 2 * g, float(p['module_t'])
        mcu, mcv = cu + float(p['module_du']), cv + float(p['module_dv'])
        if kind != 'recess' and (float(p['active_w']) > float(p['module_w']) or float(p['active_h']) > float(p['module_h'])):
            raise kernel.CadError('Powierzchnia aktywna większa niż moduł wyświetlacza - podaj osobno obrys modułu i powierzchnię aktywną.')
        mount = p['mount'] if kind != 'recess' else 'flush'
        if kind != 'recess':
            out['cut'].append(_box_tool(fr, acu, acv, aw, ah, ang, -th - 1, 1.0))                   # okno powierzchni aktywnej
        if mount == 'flush':                                                                         # wnęka od zewnątrz: moduł na równi
            d = min(mt, th - .4) if kind != 'recess' else float(p['depth'])
            if d >= th - .3:
                raise kernel.CadError('Wnęka wyświetlacza przebiłaby ściankę - zmniejsz głębokość albo pogrub ściankę.')
            out['cut'].append(_box_tool(fr, mcu, mcv, mw, mh, ang, -d, 1.0, 1.0))
        elif mount == 'below':                                                                       # moduł za ścianką: wnęka od środka
            d = max(0.0, th - max(.8, float(p['bezel'])))
            if d > 0:
                out['cut'].append(_box_tool(fr, mcu, mcv, mw, mh, ang, -th - 1, -th + d))
            if p.get('supports'):
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        q = np.array([mcu, mcv]) + _rot((sx * (mw / 2 + 1.5), sy * (mh / 2 - 2.0)), ang)
                        out['add'].append(_box_tool(fr, q[0], q[1], 3.0, 4.0, ang, -th - mt, -th + .2))   # podpory przy krawędzi modułu
        else:                                                                                        # powyżej: ramka na zewnątrz
            bw = float(p['bezel'])
            ring = _boolean('cut', _box_tool(fr, mcu, mcv, mw + 2 * bw, mh + 2 * bw, ang, -.2, mt), _box_tool(fr, mcu, mcv, mw, mh, ang, -1, mt + 1),
                            'ramka wyświetlacza')
            out['add'].append(ring)
        if float(p['conn_w']) > 0 and mount == 'below':                                              # miejsce na przewody / złącze
            q = np.array([mcu, mcv]) + _rot((0.0, -(mh / 2 + float(p['conn_h']) / 2)), ang)
            out['checks'].append(('space', _box_tool(fr, q[0], q[1], float(p['conn_w']), float(p['conn_h']), ang, -th - mt - 6.0, -th - .01),
                                  'miejsce na złącze wyświetlacza'))
        out['access'].append(_box_tool(fr, acu, acv, aw, ah, ang, .02, 15.0))
    elif kind in ('encoder', 'pot'):
        d = float(p['diameter']) + 2 * g
        out['cut'].append(_cyl(fr, cu, cv, d, -th - 1, 1.0))
        if p.get('tab'):                                                                              # wycięcie pod wypust ustalający
            q = np.array([cu, cv]) + _rot((0.0, d / 2 + 1.2), ang)
            out['cut'].append(_box_tool(fr, q[0], q[1], 1.6, 2.4, ang, -th - 1, -th + min(1.0, th / 2)))
        out['access'].append(_cyl(fr, cu, cv, float(p['diameter']) * 2.5, .02, 20.0))
    elif kind == 'switch':
        out['cut'].append(_box_tool(fr, cu, cv, float(p['width']) + 2 * g, float(p['height']) + 2 * g, ang, -th - 1, 1.0, .3))
        out['access'].append(_box_tool(fr, cu, cv, float(p['width']) * 2, float(p['height']) * 2, ang, .02, 15.0))
    elif kind == 'slider':
        w = float(p['width']) + 2 * g
        face = _rectf(fr, cu, cv, float(p['length']) + w, w, ang, 0.0)
        face = eh._fillet2d(face, w / 2 - 1e-3)
        out['cut'].append(eh._prism(face, fr, 1.0, -th - 1))
        out['access'].append(_box_tool(fr, cu, cv, float(p['length']) + 3 * w, 3 * w, ang, .02, 15.0))
    elif kind == 'membrane':
        out['cut'].append(_box_tool(fr, cu, cv, float(p['width']), float(p['height']), ang, -float(p['depth']), 1.0, 1.0))
        q = np.array([cu, cv]) + _rot((0.0, -float(p['height']) / 2 + 1.0), ang)
        out['cut'].append(_box_tool(fr, q[0], q[1], float(p['conn_w']), 1.0, ang, -th - 1, 1.0))                  # szczelina na taśmę
        if float(p['depth']) >= th - .3:
            raise kernel.CadError('Wnęka klawiatury membranowej przebiłaby ściankę - zmniejsz głębokość.')
    elif kind == 'speaker':
        from . import enclosure_vents as ev
        D = float(p['diameter'])
        holes, _a = ev.layout(dict(ev.DEFAULTS, pattern='radial' if p['pattern'] == 'radial' else p['pattern'], size=float(p['hole']), web=float(p['web']),
                                   cu=cu, cv=cv, width=D, height=D, margin=1.0))
        tools = [eh._prism(ev.hole_face(h, fr), fr, 1.0, -th - 1) for h in holes if h[4] == 'vent'
                 and np.hypot(h[1][0] - cu, h[1][1] - cv) + float(p['hole']) / 2 <= D / 2]
        if not tools:
            raise kernel.CadError('Otwory maskownicy nie mieszczą się w średnicy głośnika - zmniejsz otwory.')
        out['cut'] += tools
    elif kind == 'mic':
        out['cut'].append(_cyl(fr, cu, cv, float(p['hole']), -th - 1, 1.0))
        gk = float(p['gasket'])
        if gk >= th - .3:
            raise kernel.CadError('Wnęka uszczelki mikrofonu przebiłaby ściankę.')
        out['cut'].append(_cyl(fr, cu, cv, float(p['diameter']), -th - 1, -th + gk))
    elif kind == 'window':
        w, h, wt = float(p['width']), float(p['height']), float(p['window_t'])
        if wt >= th - .4:
            raise kernel.CadError('Okno grubsze niż ścianka - zmniejsz grubość okna albo pogrub ściankę.')
        out['cut'].append(_box_tool(fr, cu, cv, w + 2 * g, h + 2 * g, ang, -wt, 1.0, .5))            # wnęka na okno od zewnątrz
        out['cut'].append(_box_tool(fr, cu, cv, w - 2 * float(p['bezel']), h - 2 * float(p['bezel']), ang, -th - 1, 1.0, .5))
        out['parts'].append(('Okno ochronne', _box_tool(fr, cu, cv, w, h, ang, -wt, 0.0, .5)))
    elif kind == 'button':
        _button(target, fr, p, cu, cv, ang, th, components, out)
    elif kind == 'knob':
        _knob(fr, p, cu, cv, ang, th, out)
    elif kind == 'lightpipe':
        _lightpipe(fr, p, cu, cv, th, components, out)
    return out


def _button(target, fr, p, cu, cv, ang, th, components, out):
    """Przycisk: nasadka (średnica / szerokość, wysokość, kształt powierzchni), trzpień (długość do przycisku wewnątrz),
    kołnierz-ogranicznik od środka, prowadnica - tulejka w obudowie; otwór w ściance z luzem."""
    from .enclosure import _boolean
    d, h, g = float(p['diameter']), float(p['height']), float(p['clearance'])
    travel, stop = float(p['travel']), float(p['stop'])
    gap_switch = float(p['stem'])                           # odległość od wewnętrznej powierzchni do przycisku (0 = z komponentu)
    if gap_switch <= 0 and p.get('component_depth') is not None:
        gap_switch = float(p['component_depth']) - th
    if gap_switch <= 0:
        raise kernel.CadError('Podaj odległość przycisku od ścianki (długość trzpienia) albo wskaż komponent przycisku.')
    stem_d = d * .55
    cap = _cyl(fr, cu, cv, d, 0.05, h) if p['shape'] != 'square' else _box_tool(fr, cu, cv, d, d, ang, .05, h, .6)
    if p['shape'] == 'dome':                                 # powierzchnia naciskowa wypukła: kula przycięta do walca
        import cadquery as cq
        o, u, v, n = fr
        c = o + u * cu + v * cv + n * (h - d * .6)
        sph = cq.Solid.makeSphere(d * .8, cq.Vector(*c)).wrapped
        cap = _boolean('common', _cyl(fr, cu, cv, d, .05, h + d), _boolean('fuse', _cyl(fr, cu, cv, d, .05, h - .2), sph, 'nasadka'), 'nasadka')
    stem = _cyl(fr, cu, cv, stem_d, -th - gap_switch + .1, .5)
    flange = _cyl(fr, cu, cv, d + 2 * stop, -th - stop, -th)
    body = _boolean('fuse', _boolean('fuse', cap, stem, 'przycisk'), flange, 'przycisk')
    out['parts'].append(('Przycisk', body))
    out['cut'].append(_cyl(fr, cu, cv, d + 2 * g, -th - 1, 1.0))
    # prowadnica: tulejka od środka (wewnętrzna średnica = kołnierz + luz), wysokość = skok + kołnierz + 1
    gl = stop + travel + 1.0
    sleeve = _boolean('cut', _cyl(fr, cu, cv, d + 2 * stop + 2 * g + 2.4, -th - gl, -th + .2), _cyl(fr, cu, cv, d + 2 * stop + 2 * g, -th - gl - 1, -th + .3),
                      'prowadnica przycisku')
    out['add'].append(sleeve)
    out['checks'].append(('motion', body, travel, 'przycisk'))
    out['access'].append(_cyl(fr, cu, cv, d * 2, h + .02, h + 15.0))


def _knob(fr, p, cu, cv, ang, th, out):
    """Pokrętło na wałku: kształt, otwór na wałek (okrągły, D, sześciokątny, wielowypustowy, profil szkicu) z luzem."""
    from .enclosure import _boolean
    from .enclosure_ribs import _multi
    import cadquery as cq
    D, H, g = float(p['diameter']), float(p['height']), float(p['clearance'])
    z0 = 1.0                                                  # szczelina nad powierzchnią
    kind = p['knob']
    if kind == 'cone':
        o, u, v, n = fr
        base = o + u * cu + v * cv + n * z0
        body = cq.Solid.makeCone(D / 2, D * .38, H, cq.Vector(*base), cq.Vector(*n)).wrapped
    elif kind == 'polygon':
        N = max(3, int(p['sides']))
        R = D / 2
        pts = [tuple(np.array([cu, cv]) + _rot((R * math.cos(2 * math.pi * k / N), R * math.sin(2 * math.pi * k / N)), ang)) for k in range(N)]
        o, u, v, n = fr
        body = eh._prism(eh._plane_face(pts, (o, u, v, n)), fr, z0 + H, z0)
    else:
        body = _cyl(fr, cu, cv, D, z0, z0 + H)
        if kind == 'knurled':                                 # radełko: rowki na obwodzie
            grooves = []
            N = max(12, int(D * 2.2))
            for k in range(N):
                q = np.array([cu, cv]) + _rot((D / 2, 0.0), 2 * math.pi * k / N)
                grooves.append(_cyl(fr, q[0], q[1], .8, z0 + .8, z0 + H + 1))
            body = _multi('cut', body, grooves, 'radełko')
        elif kind == 'handle':                                # uchwyt: żeberko na górze
            body = _boolean('fuse', body, _box_tool(fr, cu, cv, D * .9, D * .22, ang, z0 + H - .2, z0 + H + D * .35, .5), 'uchwyt pokrętła')
    s, depth = float(p['shaft']) + 2 * g, float(p['insert'])
    if depth >= H:
        raise kernel.CadError('Głębokość osadzenia większa niż wysokość pokrętła.')
    bore = p['bore']
    if bore == 'round':
        tool = _cyl(fr, cu, cv, s, z0 - 1, z0 + depth)
    elif bore == 'd':
        tool = _boolean('common', _cyl(fr, cu, cv, s, z0 - 1, z0 + depth),
                        _box_tool(fr, cu, cv - (s - (float(p['flat']) + g)) / 2, s + 1, float(p['flat']) + g, ang, z0 - 2, z0 + depth + 1), 'otwór D')
    elif bore == 'hex':
        R = s / math.sqrt(3)
        pts = [tuple(np.array([cu, cv]) + _rot((R * math.cos(math.pi / 6 + k * math.pi / 3), R * math.sin(math.pi / 6 + k * math.pi / 3)), ang)) for k in range(6)]
        o, u, v, n = fr
        tool = eh._prism(eh._plane_face(pts, (o, u, v, n)), fr, z0 + depth, z0 - 1)
    elif bore == 'spline':                                    # wielowypustowy: wałek radełkowany (np. 18 wypustów)
        N = max(6, int(p['splines']))
        tool = _cyl(fr, cu, cv, s * .9, z0 - 1, z0 + depth)
        teeth = [_box_tool(fr, *(np.array([cu, cv]) + _rot((s * .45, 0.0), 2 * math.pi * k / N)), s * .12, s * .16, 2 * math.pi * k / N, z0 - 1, z0 + depth)
                 for k in range(N)]
        tool = _multi('fuse', tool, teeth, 'otwór wielowypustowy')
    elif bore == 'sketch':
        prof = p.get('bore_face')
        if prof is None:
            raise kernel.CadError('Wskaż szkic z profilem otworu na wałek.')
        tool = eh._prism(eh.offset_region(prof, g) if g > 0 else prof, fr, z0 + depth, z0 - 1)
    else:
        raise kernel.CadError('Nieznany rodzaj otworu na wałek.')
    out['parts'].append(('Pokrętło', _boolean('cut', body, tool, 'otwór na wałek')))
    out['cut'].append(_cyl(fr, cu, cv, float(p['shaft']) * 1.6 + 2 * g, -th - 1, 1.0))         # otwór na tulejkę enkodera / potencjometru
    out['access'].append(_cyl(fr, cu, cv, D * 1.5, z0 + H + .02, z0 + H + 15))


def _lightpipe(fr, p, cu, cv, th, components, out):
    """Prowadnica światła od diody (głębokość pod wewnętrzną powierzchnią) do powierzchni: prosta, stopniowana albo
    zakrzywiona (rura po łuku, BRepOffsetAPI_MakePipe); otwór w ściance."""
    from .enclosure import _boolean
    d, g = float(p['pipe_d']), float(p['clearance'])
    depth = float(p['stem']) if float(p['stem']) > 0 else (float(p['component_depth']) - th if p.get('component_depth') is not None else 0.0)
    if depth <= 0:
        raise kernel.CadError('Podaj odległość diody od ścianki albo wskaż komponent diody.')
    if p['pipe'] == 'straight':
        body = _cyl(fr, cu, cv, d, -th - depth + .2, 0.0)
    elif p['pipe'] == 'stepped':
        body = _boolean('fuse', _cyl(fr, cu, cv, d, -th - .01, 0.0), _cyl(fr, cu, cv, float(p['pipe_d2']), -th - depth + .2, -th), 'prowadnica światła')
    else:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
        from OCP.GC import GC_MakeArcOfCircle
        from OCP.gp import gp_Pnt
        o, u, v, n = fr
        off = float(p['bend'])
        top = o + u * cu + v * cv - n * th
        mid = top - n * depth * .5 + u * off * .3
        bot = top - n * (depth - .2) + u * off
        arc = GC_MakeArcOfCircle(gp_Pnt(*map(float, top)), gp_Pnt(*map(float, mid)), gp_Pnt(*map(float, bot))).Value()
        spine = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(arc).Edge()).Wire()
        circ = eh._circle_face(cu, cv, d / 2, (o - n * th, u, v, n))
        pipe = BRepOffsetAPI_MakePipe(spine, circ)
        pipe.Build()
        if not pipe.IsDone():
            raise kernel.CadError('Nie udało się poprowadzić zakrzywionej prowadnicy światła.')
        body = _boolean('fuse', pipe.Shape(), _cyl(fr, cu, cv, d, -th - .01, 0.0), 'prowadnica światła')
    out['parts'].append(('Prowadnica światła', body))
    out['cut'].append(_cyl(fr, cu, cv, d + 2 * g, -th - 1, 1.0))


# ---------------------------------------------------------------------------------------------- budowa, rozmieszczenie
def build(part, face, items, components=(), others=()):
    """Panel: dict(part=bryła obudowy, parts=[(nazwa, bryła)], report)."""
    import cadquery as cq
    from .enclosure import _boolean, _single, _unified, _volume, check_solid
    from .enclosure_ribs import _multi
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_OUT
    from OCP.gp import gp_Pnt
    target = part.wrapped if hasattr(part, 'wrapped') else part
    fr = frame_of(face)
    o, u, v, n = fr
    if BRepClass3d_SolidClassifier(target, gp_Pnt(*map(float, o + n * .05)), 1e-6).State() != TopAbs_OUT:
        raise kernel.CadError('Wskaż zewnętrzną powierzchnię obudowy.')
    if not items:
        raise kernel.CadError('Dodaj co najmniej jeden element panelu.')
    cuts, adds, parts, checks, access = [], [], [], [], []
    for it in items:
        e = element(target, fr, it, components)
        cuts += e['cut']
        adds += e['add']
        parts += [(nm, sh) for nm, sh in e['parts']]
        checks += e['checks']
        access += e['access']
    shape = target
    if adds:
        shape = _multi('fuse', shape, adds, 'elementy panelu')
    if cuts:
        shape = _multi('cut', shape, cuts, 'otwory panelu')
    shape = check_solid(_single(_unified(shape), 'Obudowa z panelem'))
    report = []
    for c in components:                                     # komponenty nie są zmieniane - osobne bryły i obudowa ich nie przenikają
        for nm, sh in [('obudowa', shape.wrapped), *parts]:
            if _volume(_boolean('common', sh, c, 'kolizja z komponentem'))[0] > 1e-4:
                raise kernel.CadError(f'{nm.capitalize()} koliduje z komponentem wewnątrz obudowy - zmień wymiary albo położenie.')
    for nm, sh in parts:
        if _volume(_boolean('common', sh, shape.wrapped, 'element a obudowa'))[0] > 1e-3:
            raise kernel.CadError(f'{nm} nachodzi na obudowę - zwiększ luz otworu.')
        for o_ in others:
            if _volume(_boolean('common', sh, o_, 'element a pokrywa'))[0] > 1e-3:
                raise kernel.CadError(f'{nm} koliduje z inną częścią obudowy.')
    blocked = sum(1 for a in access if _volume(_boolean('common', a, shape.wrapped, 'dostępność'))[0] > 1e-3)
    report.append(('warning' if blocked else 'ok', f'Dostępność od zewnątrz: {len(access) - blocked} z {len(access)} elementów wolnych.'))
    for chk in checks:
        if chk[0] == 'space':
            busy = any(_volume(_boolean('common', chk[1], c, 'miejsce'))[0] > 1e-4 for c in components) or \
                _volume(_boolean('common', chk[1], shape.wrapped, 'miejsce'))[0] > 1e-3
            report.append(('warning' if busy else 'ok', f'{chk[2].capitalize()}: ' + ('zajęte' if busy else 'wolne')))
        elif chk[0] == 'motion':
            body, travel = chk[1], chk[2]
            moved = cq.Shape.cast(body).translate(cq.Vector(*(-n * travel))).wrapped
            hit_wall = _volume(_boolean('common', moved, shape.wrapped, 'naciśnięcie'))[0] > 1e-3
            hit_comp = [c for c in components if _volume(_boolean('common', moved, c, 'naciśnięcie'))[0] > 1e-4]
            if hit_wall:
                raise kernel.CadError('Przycisk po naciśnięciu zahacza o obudowę - zwiększ luz albo zmniejsz skok.')
            report.append(('ok', f'Przycisk: spoczynek bez kolizji, po naciśnięciu o {travel:g} mm ' +
                                 ('trzpień dosięga przycisku.' if hit_comp else 'trzpień nie dosięga przycisku - skróć odległość albo zwiększ skok.')))
    if any(nm == 'Prowadnica światła' for nm, _s in parts):
        report.append(('info', 'Prowadnice światła: skuteczność optyczna nie była analizowana.'))
    return dict(part=shape, parts=[(nm, check_solid(sh)) for nm, sh in parts], report=report)


def arrange(items, mode, value=0.0):
    """Rozmieszczanie elementów: wyrównanie (lewo / prawo / góra / dół / środek poziomo / pionowo), centrowanie na
    zadanej pozycji, symetria względem osi u = value, równy rozstaw (poziomo / pionowo), szyk (kopie co value w u)."""
    out = [dict(it) for it in items]
    if not out:
        return out
    us, vs = np.array([float(it.get('u', 0.0)) for it in out]), np.array([float(it.get('v', 0.0)) for it in out])
    if mode == 'left':
        for it in out:
            it['u'] = float(us.min())
    elif mode == 'right':
        for it in out:
            it['u'] = float(us.max())
    elif mode == 'top':
        for it in out:
            it['v'] = float(vs.max())
    elif mode == 'bottom':
        for it in out:
            it['v'] = float(vs.min())
    elif mode == 'hcenter':
        for it in out:
            it['v'] = float(vs.mean())
    elif mode == 'vcenter':
        for it in out:
            it['u'] = float(us.mean())
    elif mode == 'center':
        du, dv = float(value) - float(us.mean()), -float(vs.mean())
        for it in out:
            it['u'] = float(it['u']) + du
            it['v'] = float(it['v']) + dv
    elif mode == 'mirror':
        out += [dict(it, u=2 * float(value) - float(it['u'])) for it in out]
    elif mode in ('hspace', 'vspace'):
        key = 'u' if mode == 'hspace' else 'v'
        order = sorted(range(len(out)), key=lambda k: float(out[k][key]))
        a, b = float(out[order[0]][key]), float(out[order[-1]][key])
        for rank, k in enumerate(order):
            out[k][key] = a + (b - a) * rank / max(1, len(order) - 1)
    elif mode == 'array':
        n = max(1, int(value))
        base = out[-1]
        step = float(base.get('pitch', 15.0))
        out += [dict(base, u=float(base['u']) + step * k) for k in range(1, n)]
    else:
        raise kernel.CadError('Nieznany sposób rozmieszczenia.')
    return out
