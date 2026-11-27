"""Tekstury geometryczne - relief ze zbioru wysokości: fale (jedna i dwie fale nałożone) oraz mapa wysokości z obrazu PNG / JPG / BMP.

Nie powstaje bryła na piksel. Relief to jedna powierzchnia B-Spline (GeomAPI_PointsToBSplineSurface) przez siatkę punktów
P(u, v) + N(u, v)·h(u, v) odwzorowanych na rzeczywistą powierzchnię (rozwinięcie walca, mapa wykładnicza kuli itd.), zamknięta w bryłę
prasą wzdłuż normalnej i przycięta do ściany „ciasteczkiem” (ściana pogrubiona w obie strony - BRepOffset). Poza obszarem
dozwolonym (marginesy, maski, otwory) wysokość spada poniżej powierzchni, więc tam nic nie jest dodawane ani wycinane.
Fala jednokierunkowa na ścianie płaskiej to dokładne wytłoczenie przekroju (trójkątna, prostokątna, sinusoidalna)."""
from __future__ import annotations

import base64
import io
import math

import numpy as np

from . import kernel
from . import tex_patterns as tp
from . import tex_tools as tt
from . import vent_geom2d as g2

MAX_GRID = 100


# ---------------------------------------------------------------------------------------------- obraz
def load_image(path, max_side=256):
    """Obraz PNG / JPG / BMP → słownik do zapisu w przepisie: skala szarości zmniejszona do max_side (PNG w base64) - projekt jest
    samowystarczalny, nie zależy od pliku na dysku."""
    from PIL import Image
    im = Image.open(path).convert('L')
    w, h = im.size
    k = min(1.0, max_side / max(w, h))
    if k < 1.0:
        im = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return dict(data=base64.b64encode(buf.getvalue()).decode('ascii'), w=im.size[0], h=im.size[1], name=str(path).replace('\\', '/').split('/')[-1])


def decode(img):
    from PIL import Image
    if not img or not img.get('data'):
        raise kernel.CadError('Mapa wysokości: wczytaj obraz PNG, JPG albo BMP.')
    im = Image.open(io.BytesIO(base64.b64decode(img['data']))).convert('L')
    return np.asarray(im, float) / 255.0


IMG_DEFAULTS = dict(min_h=0.0, max_h=1.0, invert=False, contrast=1.0, smooth=0, threshold=0.0, scale=1.0, rotate=0.0, tile_x=1, tile_y=1, fit='fill', cell=0.0)


def image_field(img, X, Y, lo, hi):
    """Jasność (0..1) obrazu w punktach (X, Y) dziedziny: dopasowanie do obszaru (fill - wypełnij z zachowaniem proporcji,
    fit - zmieść całość, stretch - rozciągnij), skalowanie, obrót, powielenie, kontrast, wygładzanie, próg."""
    cfg = dict(IMG_DEFAULTS, **{k: v for k, v in img.items() if k in IMG_DEFAULTS})
    A = decode(img)
    h, w = A.shape
    for _ in range(int(cfg['smooth'])):                               # wygładzanie 3×3
        P = np.pad(A, 1, mode='edge')
        A = (P[:-2, :-2] + P[:-2, 1:-1] + P[:-2, 2:] + P[1:-1, :-2] + P[1:-1, 1:-1] * 4 + P[1:-1, 2:] + P[2:, :-2] + P[2:, 1:-1] + P[2:, 2:]) / 12.0
    A = np.clip((A - .5) * float(cfg['contrast']) + .5, 0, 1)
    if cfg['invert']:
        A = 1.0 - A
    if cfg['threshold'] > 0:
        A = (A >= float(cfg['threshold'])).astype(float)
    ext = np.asarray(hi, float) - np.asarray(lo, float)
    ratio = w / max(h, 1)
    if cfg['fit'] == 'stretch':
        sw, sh = ext[0], ext[1]
    elif cfg['fit'] == 'fit':
        sw, sh = (ext[0], ext[0] / ratio) if ext[0] / ratio <= ext[1] else (ext[1] * ratio, ext[1])
    else:
        sw, sh = (ext[0], ext[0] / ratio) if ext[0] / ratio >= ext[1] else (ext[1] * ratio, ext[1])
    sc = max(float(cfg['scale']), .01)
    sw, sh = sw * sc / max(int(cfg['tile_x']), 1), sh * sc / max(int(cfg['tile_y']), 1)
    c = (np.asarray(lo, float) + np.asarray(hi, float)) / 2
    a = math.radians(float(cfg['rotate']))
    dx, dy = X - c[0], Y - c[1]
    u = dx * math.cos(a) + dy * math.sin(a)
    v = -dx * math.sin(a) + dy * math.cos(a)
    uu = u / sw + .5 * max(int(cfg['tile_x']), 1)
    vv = v / sh + .5 * max(int(cfg['tile_y']), 1)
    inside = np.ones(X.shape, bool)
    if cfg['tile_x'] <= 1 and cfg['tile_y'] <= 1:
        inside = (uu >= 0) & (uu <= 1) & (vv >= 0) & (vv <= 1)
    uu = uu - np.floor(uu)
    vv = vv - np.floor(vv)
    fx, fy = uu * (w - 1), (1 - vv) * (h - 1)
    x0, y0 = np.clip(np.floor(fx).astype(int), 0, w - 2), np.clip(np.floor(fy).astype(int), 0, h - 2)
    tx, ty = fx - x0, fy - y0
    val = (A[y0, x0] * (1 - tx) * (1 - ty) + A[y0, x0 + 1] * tx * (1 - ty) + A[y0 + 1, x0] * (1 - tx) * ty + A[y0 + 1, x0 + 1] * tx * ty) if w > 1 and h > 1 else np.full(X.shape, A.mean())
    return np.where(inside, val, 0.0)


def field_values(p, X, Y, lo, hi):
    """Znormalizowany zbiór wysokości f: fale ∈ [-1, 1], obraz ∈ [0, 1], oraz amplituda skali."""
    if p.get('pattern') == 'image':
        return image_field(p.get('image') or {}, X, Y, lo, hi), 'image'
    z = tp.wave_field(p, X, Y)
    amp = float(p['amp']) + (float(p['wave2_amp']) if p.get('wave2') else 0.0)
    return z / max(amp, 1e-9), 'waves'


def signed_heights(p, f, kind, mode):
    """Wysokość nad powierzchnią (ujemna - zagłębienie) w punktach siatki dla trybu wypukłego / wklęsłego / mieszanego."""
    h_up, h_dn = float(p['height']), float(p['depth'])
    if kind == 'waves':
        A = float(p['amp']) + (float(p['wave2_amp']) if p.get('wave2') else 0.0)
        if mode == 'concave':
            return -A * (1 - f)
        if mode == 'mixed':
            return f * A
        return A * (f + 1)
    cfg = dict(IMG_DEFAULTS, **(p.get('image') or {}))
    lo_, hi_ = float(cfg['min_h']), float(cfg['max_h'])
    rng = (h_up if mode != 'concave' else h_dn)
    if mode == 'concave':
        return -(lo_ + (hi_ - lo_) * f) * h_dn
    if mode == 'mixed':
        return -h_dn + (h_up + h_dn) * f
    return (lo_ + (hi_ - lo_) * f) * h_up


# ---------------------------------------------------------------------------------------------- B-Spline
def _surface(T, tol):
    from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface
    from OCP.GeomAbs import GeomAbs_C2
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.gp import gp_Pnt
    nu, nv = T.shape[:2]
    arr = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            arr.SetValue(i + 1, j + 1, gp_Pnt(float(T[i, j, 0]), float(T[i, j, 1]), float(T[i, j, 2])))
    ap = GeomAPI_PointsToBSplineSurface(arr, 3, 8, GeomAbs_C2, float(tol))
    if not ap.IsDone():
        raise kernel.CadError('Nie udało się zbudować powierzchni reliefu (B-Spline).')
    return ap.Surface()


def _cookie(face_shape, out, inn):
    """Ściana pogrubiona o out na zewnątrz i inn do wewnątrz (bryła): narzędzie przycinane do tej bryły nie wystaje poza ścianę."""
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    f = cq.Face(face_shape)
    a = f.thicken(float(out))
    b = f.thicken(-float(inn))
    sh = BRepAlgoAPI_Fuse(a.wrapped, b.wrapped).Shape()
    return sh


def field_tools(G, pl, recipe, ctx, cancel=None):
    """Narzędzia reliefu grupy G: (wypustki, zagłębienia)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    p = G.p
    mode = ctx.mode
    m = G.mappers[0]
    if len(G.mappers) > 1:
        pl['report'].append(('warning', 'Relief (fale, obraz) powstaje na pierwszej z zaznaczonych ścian - dla kilku ścian użyj niezależnego wzoru.'))
    R = g2.Region(G.allowed[0], G.allowed[1])
    lo, hi = R.lo, R.hi
    cell = float(p.get('image', {}).get('cell', 0) or 0) if p.get('pattern') == 'image' else 0.0
    if cell <= 0:
        if p.get('pattern') == 'image':
            cell = max(max(hi - lo) / 55.0, .3)
        else:
            lam = min(float(p['wavelength']), float(p['wave2_len']) if p.get('wave2') else 1e9)
            cell = max(lam / (10 if p.get('wave_type', 'sine') == 'sine' else 16), .1)
    cell *= float(p.get('_cell_k', 1.0))
    nx = int(math.ceil((hi[0] - lo[0]) / cell)) + 1
    ny = int(math.ceil((hi[1] - lo[1]) / cell)) + 1
    if max(nx, ny) > MAX_GRID:
        k = max(nx, ny) / MAX_GRID
        nx, ny = int(nx / k) + 1, int(ny / k) + 1
        pl['report'].append(('warning', f'Relief ograniczono do siatki {nx} × {ny} punktów (limit złożoności) - drobne detale mogą być wygładzone; zmniejsz obszar albo zwiększ długość fali.'))
    xs, ys = np.linspace(lo[0], hi[0], nx), np.linspace(lo[1], hi[1], ny)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    f, kind = field_values(p, X, Y, lo, hi)
    if kind == 'image' and float((p.get('image') or {}).get('threshold') or 0) > 0:
        for _ in range(2):                                          # ostre progi: zbocze o szerokości kilku oczek zamiast skoku (B-Spline nie oscyluje)
            P_ = np.pad(f, 1, mode='edge')
            f = (P_[:-2, :-2] + P_[:-2, 1:-1] + P_[:-2, 2:] + P_[1:-1, :-2] + P_[1:-1, 1:-1] * 4 + P_[1:-1, 2:] + P_[2:, :-2] + P_[2:, 1:-1] + P_[2:, 2:]) / 12.0
    h = signed_heights(p, f, kind, 'concave' if mode == 'concave' else ('mixed' if mode == 'mixed' else 'convex'))
    inside = R.contains(np.c_[X.ravel(), Y.ravel()]).reshape(X.shape)
    # komórki narożne siatki: punkt aktywny, jeśli jakikolwiek sąsiad jest w obszarze (gładkie zbocze zamiast stopnia)
    act = inside.copy()
    act[1:, :] |= inside[:-1, :]
    act[:-1, :] |= inside[1:, :]
    act[:, 1:] |= inside[:, :-1]
    act[:, :-1] |= inside[:, 1:]
    hmax = float(np.abs(h[inside]).max()) if inside.any() else 0.0
    if hmax < 1e-6:
        raise kernel.CadError('Relief ma zerową wysokość - zwiększ amplitudę / wysokość.')
    sign_mode = 'down' if mode == 'concave' else 'up'
    delta = max(.04 * hmax, .02)
    base = {'up': delta, 'down': -delta}[sign_mode] if mode != 'mixed' else 0.0
    h = np.where(inside, h + (base if mode != 'mixed' else 0.0), (-.5 if sign_mode == 'up' else .5) * max(.15, .1 * hmax))
    if mode == 'mixed':
        h = np.where(inside, h, -.4 * max(.15, .1 * hmax))
        h = np.where(inside & (np.abs(h) < delta), np.where(h >= 0, delta, -delta), h)
    kk = max((getattr(mm, '_kmax', 0.0) or 0.0) for mm in G.mappers)
    from . import tex_engine as te
    kk = max(te._kmax(m), kk)
    Rr = float(np.linalg.norm(hi - lo)) / 2
    if kk * Rr > .9:
        raise kernel.CadError('Relief jest zbyt duży względem krzywizny ściany - wskaż mniejszy obszar albo użyj wzoru z elementami.')
    sag = kk * Rr * Rr / 2 if kk * Rr < .5 else (1 / kk) * (1 - math.sqrt(1 - (kk * Rr) ** 2))
    T = np.zeros((nx, ny, 3))
    Nn = np.zeros((nx, ny, 3))
    for i in range(nx):
        if cancel is not None and cancel():
            raise kernel.CadError('Obliczenia przerwane - model bez zmian.')
        for j in range(ny):
            P, N, _X, _Y = m.to3d((xs[i], ys[j]))
            T[i, j] = P + N * h[i, j]
            Nn[i, j] = N
    n0 = te._unit(Nn.reshape(-1, 3).mean(0))
    surf = _surface(T, tol=max(hmax * .01, .005))
    top = BRepBuilderAPI_MakeFace(surf, 1e-6).Face()
    e = max(.2, .15 * hmax)
    depth = hmax * 1.3 + sag * 1.5 + e + .3
    up = mode != 'concave'
    vec = gp_Vec(*(-n0 * depth)) if up else gp_Vec(*(n0 * depth))
    raw = BRepPrimAPI_MakePrism(top, vec).Shape()
    raw = tt._fix(raw)
    cookie = _cookie(m.face, hmax * 1.4 + .3, e + sag * 1.6 + .2) if up else _cookie(m.face, e + sag * 1.5 + .3, hmax * 1.4 + .3)
    sols = []
    try:
        if getattr(m, 'kind', '') == 'plane':
            rect = len(R.outers) == 1 and not R.holes and abs(abs(tt.ccw(R.outers[0])) - float(np.prod(R.hi - R.lo))) < 1e-6 * float(np.prod(R.hi - R.lo))
            sols = [raw] if rect else _mask_clip(raw, m, R, hmax * 1.5 + 1.0)
        if not sols:
            tool = BRepAlgoAPI_Common(raw, cookie)
            tool.SetRunParallel(True)
            tool.Build()
            sols = [tool.Shape()]
    except Exception as exc:
        raise kernel.CadError('Przycięcie reliefu do ściany nie powiodło się.') from exc
    sols = [s_ for s_ in sols if tt.volume(s_) > 1e-6]
    if not sols:
        raise kernel.CadError('Relief nie przecina się ze ścianą - sprawdź obszar i wysokość.')
    ctx.count['ok'] += 1
    return (sols, []) if up else ([], sols)


def _mask_clip(raw, m, R, ext):
    """Płaska ściana: relief przycięty pionowymi ściankami do obszaru dozwolonego (bez zboczy poniżej powierzchni - stabilna operacja Boolean)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    q0 = (R.lo + R.hi) / 2
    P0, N, X0, Y0 = m.to3d(q0)
    P1 = m.to3d(q0 + np.array([1.0, 0.0]))[0]
    P2 = m.to3d(q0 + np.array([0.0, 1.0]))[0]
    X = np.asarray(P1, float) - np.asarray(P0, float)
    Y = np.asarray(P2, float) - np.asarray(P0, float)
    flip = float(np.dot(np.cross(X, Y), N)) < 0
    out = []
    for o in R.outers:
        holes = [h for h in R.holes if len(h) and _inside_poly(h.mean(0), o)]
        def loc(q):
            q = np.asarray(q, float) - q0
            return np.c_[q[:, 0], -q[:, 1] if flip else q[:, 1]]
        po = loc(o)
        if tt.ccw(po) < 0:
            po = po[::-1]
        ph = []
        for h in holes:
            hh = loc(h)
            ph.append(hh[::-1] if tt.ccw(hh) > 0 else hh)
        mp = tt.prism(po, ph, -ext, ext)
        if mp is None:
            continue
        mp = tt.placed(mp, np.asarray(P0, float), np.asarray(N, float), X / max(np.linalg.norm(X), 1e-12))
        com = BRepAlgoAPI_Common(raw, mp)
        com.Build()
        if com.IsDone():
            out.append(com.Shape())
    return out


def _inside_poly(pt, poly):
    from .vent_geom2d import pip
    return bool(pip(np.asarray(pt, float).reshape(1, 2), poly)[0])
