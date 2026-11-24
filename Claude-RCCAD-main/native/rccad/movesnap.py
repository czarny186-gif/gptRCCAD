"""Przyciąganie podczas przesuwania myszą (Przesuń): szkice i bryły „kleją się”, gdy są bardzo blisko.

- środek na środek: okręgi (i łuki) przesuwane na inne okręgi - wspólny środek; tak samo środki zamkniętych kształtów
  (kwadrat na kwadrat) i wierzchołki (narożnik na narożnik, koniec linii na koniec linii);
- prosta do prostej: równoległe proste odcinki ustawiają się w jednej linii;
- styczność: okrąg dotyka prostej albo innego okręgu (z zewnątrz lub od środka) w punkcie stycznym.
Działa w przestrzeni: dla brył bierze ich krawędzie (wierzchołki, proste krawędzie, okręgi otworów i walców).
Poprawka przesunięcia leży tylko w kierunkach, w których wolno przesuwać (oś strzałki albo płaszczyzna)."""
from __future__ import annotations

import numpy as np

MAX_POINTS = 4000
MAX_LINES = 3000
MAX_CIRCLES = 800
_CACHE = {}


def features(shape):
    """Cechy kształtu do przyciągania: punkty (N x 3) z rodzajami, odcinki (M x 2 x 3), okręgi [(środek, normalna, promień)]."""
    key = id(shape)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] is shape:
        return hit[1]
    pts, kinds, lines, circles = [], [], [], []
    try:
        edges = shape.Edges()
    except Exception:
        edges = []
    for e in edges[:6000]:
        try:
            gt = e.geomType()
            if gt == 'LINE':
                a, b = np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)
                if np.linalg.norm(b - a) > 1e-6:
                    lines.append((a, b))
                pts += [a, b]
                kinds += ['end', 'end']
            elif gt == 'CIRCLE':
                c = np.array(e.arcCenter().toTuple(), float)
                n = np.array(e._geomAdaptor().Circle().Axis().Direction().Coord(), float) if hasattr(e, '_geomAdaptor') else np.array(e.normal().toTuple(), float)
                r = float(e.radius())
                circles.append((c, n / max(np.linalg.norm(n), 1e-12), r))
                pts.append(c)
                kinds.append('center')
                if not e.IsClosed():
                    pts += [np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)]
                    kinds += ['end', 'end']
            elif not e.IsClosed():
                pts += [np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)]
                kinds += ['end', 'end']
        except Exception:
            continue
    try:                     # środek zamkniętego kształtu szkicu (kwadrat, wielokąt): kwadrat na kwadrat
        if not shape.Solids() and not shape.Faces():
            for w in shape.Wires():
                if w.IsClosed():
                    bb = w.BoundingBox()
                    pts.append(np.array([(bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2]))
                    kinds.append('center')
    except Exception:
        pass
    out = dict(points=np.asarray(pts, float).reshape(-1, 3), kinds=list(kinds),
               lines=np.asarray(lines, float).reshape(-1, 2, 3), circles=circles)
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[key] = (shape, out)
    return out


def gather(shapes):
    """Cechy kilku kształtów razem (z limitem, żeby duże bryły nie spowalniały przeciągania)."""
    pts, kinds, lines, circles = [], [], [], []
    for sh in shapes:
        f = features(sh)
        pts.append(f['points'])
        kinds += f['kinds']
        lines.append(f['lines'])
        circles += f['circles']
    points = np.concatenate(pts) if pts else np.zeros((0, 3))
    order = np.argsort([0 if k == 'center' else 1 for k in kinds], kind='stable')[:MAX_POINTS] if kinds else np.zeros(0, int)
    return dict(points=points[order] if len(points) else points, kinds=[kinds[i] for i in order],
                lines=(np.concatenate(lines) if lines else np.zeros((0, 2, 3)))[:MAX_LINES], circles=circles[:MAX_CIRCLES])


def _projector(allowed):
    basis = np.asarray(allowed, float).reshape(-1, 3)
    q, _ = np.linalg.qr(basis.T)
    q = q[:, :basis.shape[0]]
    return lambda d: (np.asarray(d, float) @ q) @ q.T


LABELS = {'center': 'środek', 'end': 'wierzchołek', 'line': 'w linii', 'tangent': 'styczna'}


def snap(offset, moving, static, allowed, threshold):
    """Najlepsza poprawka przesunięcia offset: (poprawka, punkt znacznika, etykieta) albo None.
    moving / static - cechy z gather(); moving w położeniu przed przesunięciem; allowed - kierunki ruchu (wiersze)."""
    offset = np.asarray(offset, float)
    proj = _projector(allowed)
    thr = float(threshold)
    best = None

    def consider(corr, point, label, weight=1.0):
        nonlocal best
        full = np.asarray(corr, float)
        corr = proj(full)
        rest = float(np.linalg.norm(full - corr))         # części nie da się poprawić w dozwolonym kierunku
        if float(np.linalg.norm(corr)) < 1e-9 and rest > 1e-6:
            return                                          # nic by się nie zmieniło - to nie jest przyciąganie
        size = (float(np.linalg.norm(corr)) + 2 * rest) * weight
        if best is None or size < best[0]:
            best = (size, corr, point, label)

    # punkt na punkt (środki mają pierwszeństwo)
    mp, sp = moving['points'], static['points']
    if len(mp) and len(sp):
        m = mp[:600] + offset
        diff = sp[None, :, :] - m[:, None, :]
        dist = np.linalg.norm(diff, axis=2)
        cand = np.argwhere(dist < thr)
        for i, j in cand[:400]:
            d = diff[i, j]
            if np.linalg.norm(d - proj(d)) < thr * .5:
                center = moving['kinds'][i] == 'center' and static['kinds'][j] == 'center'
                consider(d, sp[j], 'center' if center else 'end', .4 if center else .7)
    # prosta do prostej: równoległe odcinki w jednej linii (gdy się na siebie nakładają)
    ml, sl = moving['lines'], static['lines']
    if len(ml) and len(sl):
        p0 = ml[:300, 0] + offset
        u = ml[:300, 1] - ml[:300, 0]
        lu = np.linalg.norm(u, axis=1)
        u = u / np.maximum(lu, 1e-12)[:, None]
        q0, q1 = sl[:, 0], sl[:, 1]
        w = q1 - q0
        w = w / np.maximum(np.linalg.norm(w, axis=1), 1e-12)[:, None]
        par = np.abs(np.einsum('ik,jk->ij', u, w)) > .9998
        for i, j in np.argwhere(par)[:2000]:
            rel = q0[j] - p0[i]
            d = rel - (rel @ u[i]) * u[i]
            if np.linalg.norm(d) >= thr or np.linalg.norm(d) < 1e-9:
                continue
            t0, t1 = sorted(((q0[j] - p0[i]) @ u[i], (q1[j] - p0[i]) @ u[i]))
            if t1 < -thr or t0 > lu[i] + thr:
                continue                        # odcinki daleko od siebie wzdłuż linii
            if np.linalg.norm(d - proj(d)) < thr * .5:
                consider(d, p0[i] + d + u[i] * float(np.clip((t0 + t1) / 2, 0, lu[i])), 'line', .9)
    # styczność: okrąg - prosta, prosta - okrąg, okrąg - okrąg
    mc, sc = moving['circles'], static['circles']

    def circle_line(cs, segs, sign):
        """Okręgi cs (środek, normalna, promień) i odcinki segs (K x 2 x 3) - wektorowo; sign=+1: rusza się okrąg."""
        if not cs or not len(segs):
            return
        a = segs[:, 0]
        wv = segs[:, 1] - a
        lw = np.linalg.norm(wv, axis=1)
        ok = lw > 1e-9
        a, wv, lw = a[ok], wv[ok], lw[ok]
        wv = wv / lw[:, None]
        for c, n, r in cs:
            rel = a - c
            flat = (np.abs(wv @ n) < .02) & (np.abs(rel @ n) < thr)
            if not flat.any():
                continue
            e = rel[flat] - (np.einsum('ij,ij->i', rel[flat], wv[flat]))[:, None] * wv[flat]
            dist = np.linalg.norm(e, axis=1)
            near = np.nonzero((dist > 1e-9) & (np.abs(dist - r) < thr))[0]
            for k in near[:50]:
                corr = e[k] / dist[k] * (dist[k] - r) * sign
                consider(corr, c + (corr if sign > 0 else 0) + e[k] / dist[k] * r, 'tangent')

    circle_line([(c + offset, n, r) for c, n, r in mc[:150]], sl, 1.0)
    circle_line(sc[:400], ml[:300] + offset if len(ml) else ml, -1.0)
    if mc and sc:
        sc_c = np.array([c for c, _, _ in sc[:400]])
        sc_n = np.array([n for _, n, _ in sc[:400]])
        sc_r = np.array([r for _, _, r in sc[:400]])
        for c, n, r in mc[:150]:
            c = c + offset
            D = sc_c - c
            ok = (np.abs(np.abs(sc_n @ n) - 1) < 1e-3) & (np.abs(D @ n) < thr)
            if not ok.any():
                continue
            Dp = D - (D @ n)[:, None] * n
            dist = np.linalg.norm(Dp, axis=1)
            for target in (r + sc_r, np.abs(r - sc_r)):
                near = np.nonzero(ok & (dist > 1e-6) & (target > 1e-6) & (np.abs(dist - target) < thr))[0]
                for k in near[:50]:
                    corr = Dp[k] / dist[k] * (dist[k] - target[k])
                    consider(corr, c + corr + Dp[k] / dist[k] * r, 'tangent')
    if best is None:
        return None
    return best[1], np.asarray(best[2], float), LABELS[best[3]]
