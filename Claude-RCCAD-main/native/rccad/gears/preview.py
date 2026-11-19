"""Szybki podgląd koła - siatka trójkątów do wyświetlania podczas edycji parametrów (bez Open CASCADE i bez Qt).

Przekrój czołowy z gęstych punktów dokładnego zarysu (profile.outline_points) wyciągnięty w manifold3d - dla zębów
skośnych ze skrętem przekroju o ten sam kąt co w bryle (kilka warstw na szerokości), z otworem, rowkiem i piastą.
To tylko obraz na ekranie: po Zastosuj powstaje dokładna bryła B-Rep (occ.gear_solid)."""
from __future__ import annotations

import math

import numpy as np

from .params import GearParams, derived, keyway_size
from .profile import outline_points

STEP_DEG = 5.0          # kąt skrętu na jedną warstwę siatki koła skośnego


def _circle(radius, n=96):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack((radius * np.cos(a), radius * np.sin(a)))


def _bore(p: GearParams):
    """Zarys otworu (z rowkiem wpustowym na +X) jako wielokąt albo None."""
    R = float(p.bore) / 2
    if p.internal or R <= 0:
        return None
    key = keyway_size(p)
    if key is None:
        return _circle(R)
    width, depth = key
    h = width / 2
    a0 = math.asin(min(h / R, 1.0))
    a = np.linspace(a0, 2 * math.pi - a0, 90)
    arc = np.column_stack((R * np.cos(a), R * np.sin(a)))
    top = R + depth
    return np.vstack((arc, [(top, -h), (top, h)]))


def _twist_deg(p: GearParams):
    if not p.helical:
        return 0.0
    angle = math.degrees(2 * float(p.width) * math.tan(math.radians(p.beta)) / derived(p)['d'])
    return angle if p.hand == 'right' else -angle


def mesh_arrays(p: GearParams):
    """(wierzchołki (N, 3), trójkąty (M, 3)) szybkiej siatki koła w tym samym położeniu co bryła z occ.gear_solid."""
    import manifold3d as mf
    samples = int(max(3, min(12, 1200 // max(int(p.teeth), 1))))      # punkty na krzywą zarysu: mniej przy wielu zębach
    outline = outline_points(p, samples)
    polygons = [outline]
    if p.internal:
        polygons = [_circle(derived(p)['rim'] / 2, 192), outline]
    else:
        bore = _bore(p)
        if bore is not None:
            polygons.append(bore)
    section = mf.CrossSection([np.asarray(q, float) for q in polygons], mf.FillRule.EvenOdd)
    twist = _twist_deg(p)
    layers = max(1, int(math.ceil(abs(twist) / STEP_DEG)))
    body = mf.Manifold.extrude(section, float(p.width), layers - 1 if layers > 1 else 0, twist)   # dodatni kąt: jak bryła (prawy skręt)
    if not p.internal and p.hub and p.hub_length > 0 and p.hub_diameter > 0:
        ring = [_circle(float(p.hub_diameter) / 2)]
        bore = _bore(p)
        if bore is not None:
            ring.append(bore)
        hub = mf.Manifold.extrude(mf.CrossSection([np.asarray(q, float) for q in ring], mf.FillRule.EvenOdd), float(p.hub_length))
        body = body + hub.translate((0, 0, float(p.width)))
    mesh = body.to_mesh()
    return np.asarray(mesh.vert_properties, float)[:, :3], np.asarray(mesh.tri_verts, np.int64)
