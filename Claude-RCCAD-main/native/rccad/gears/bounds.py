"""Prostopadłościan otaczający koła - liczony z dokładnego zarysu, bez Open CASCADE (numpy).

Dokładny prostopadłościan bryły z powierzchniami B-spline (BRepBndLib.AddOptimal) przy kilkuset zębach skośnych liczy się
sekundy. Koło da się opisać wzorem: każdy punkt przekroju czołowego (r, φ) obraca się wzdłuż szerokości o kąt skrętu,
więc jego współrzędna w kierunku ψ na całej szerokości osiąga max r·cos(t) dla t w przedziale [φ - ψ, φ - ψ + skręt] -
liczone wprost. Piasta i wieniec to pełne okręgi. Dla położenia z osią koła wzdłuż osi układu (tak powstają koła i pary)
wynik jest dokładny (do odchyłki zarysu ~1e-6 mm); inne położenia - None (wtedy liczy OCC)."""
from __future__ import annotations

import math

import numpy as np

from .params import GearParams, derived
from .profile import outline_points


def _twist(p: GearParams):
    if not p.helical:
        return 0.0
    angle = 2 * float(p.width) * math.tan(math.radians(p.beta)) / derived(p)['d']
    return angle if p.hand == 'right' else -angle


def _max_cos(start, length):
    """max cos(t) dla t w [start, start + length] (length >= 0), wektorowo."""
    a = np.mod(start, 2 * math.pi)
    contains = (a == 0) | (a + length >= 2 * math.pi)
    return np.where(contains, 1.0, np.maximum(np.cos(a), np.cos(a + length)))


def gear_box(params: GearParams, place=None):
    """(min (3,), max (3,)) prostopadłościanu bryły koła z occ.gear_solid w położeniu place (macierz 3x4, None - koło
    z generatora) albo None, gdy oś koła nie leży wzdłuż osi układu."""
    p = params
    M = np.eye(4)[:3] if place is None else np.asarray(place, float)[:3, :4]
    R, t = M[:, :3], M[:, 3]
    axis = R[:, 2]
    j = int(np.argmax(np.abs(axis)))
    if abs(abs(axis[j]) - 1) > 1e-9:
        return None
    width = float(p.width)
    height = width + (float(p.hub_length) if (not p.internal and p.hub and p.hub_length > 0) else 0.0)
    rings = []                                       # (r, φ, długość przedziału obrotu)
    if p.internal:
        rim = derived(p)['rim'] / 2
        rings.append((np.array([rim]), np.array([0.0]), 2 * math.pi))
    else:
        pts = outline_points(p)
        twist = _twist(p)
        r = np.hypot(pts[:, 0], pts[:, 1])
        phi = np.arctan2(pts[:, 1], pts[:, 0]) + min(0.0, twist)
        rings.append((r, phi, abs(twist)))
        if p.hub and p.hub_length > 0 and p.hub_diameter > 0:
            rings.append((np.array([float(p.hub_diameter) / 2]), np.array([0.0]), 2 * math.pi))
    lo, hi = np.empty(3), np.empty(3)
    for i in range(3):
        if i == j:
            ends = (R[i, 2] * 0.0 + t[i], R[i, 2] * height + t[i])
            lo[i], hi[i] = min(ends), max(ends)
            continue
        rho = math.hypot(R[i, 0], R[i, 1])
        psi = math.atan2(R[i, 1], R[i, 0])
        top, bottom = -math.inf, math.inf
        for r, phi, length in rings:
            top = max(top, float(np.max(rho * r * _max_cos(phi - psi, length))))
            bottom = min(bottom, float(np.min(-rho * r * _max_cos(phi - psi + math.pi, length))))
        lo[i], hi[i] = bottom + t[i], top + t[i]
    return lo, hi
