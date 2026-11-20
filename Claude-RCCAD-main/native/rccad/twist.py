"""TWIST – Skręcanie brył: geometria osi skręcenia (bez interfejsu).

Oś = (punkt, kierunek jednostkowy). Źródła osi:
- 'global' - oś X / Y / Z układu globalnego przez środek bryły (środek prostopadłościanu otaczającego),
- 'local'  - oś własna bryły: główne osie bezwładności (Open CASCADE, GProp) przez środek masy, dopasowane do X / Y / Z
             (bryła nieobrócona: lokalne osie = globalne; obrócona - osie idą razem z nią),
- 'points' - prosta przez dwa wskazane punkty,
- 'edge'   - prosta krawędź B-Rep,
- 'cyl'    - oś powierzchni walcowej.
Kąt dodatni = obrót prawoskrętny wokół kierunku osi (kciuk prawej dłoni wzdłuż osi)."""
from __future__ import annotations

import numpy as np

from . import kernel

AXIS_VECTORS = {'X': np.array([1.0, 0.0, 0.0]), 'Y': np.array([0.0, 1.0, 0.0]), 'Z': np.array([0.0, 0.0, 1.0])}


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise kernel.CadError('Oś skręcenia ma zerową długość.')
    return v / n


def body_center(shape):
    """Środek bryły: środek prostopadłościanu otaczającego."""
    return np.asarray(kernel.bounds(shape).center.toTuple(), float)


def principal_axes(shape):
    """(środek masy, osie lokalne {'X','Y','Z': wektor}) - główne osie bezwładności dopasowane do osi globalnych.
    Gdy osie główne są nieokreślone (np. sześcian, kula - równe momenty), zostają osie globalne."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props)
    if props.Mass() <= 1e-12:
        raise kernel.CadError('Bryła nie ma objętości - nie da się wyznaczyć jej osi lokalnych.')
    c = props.CentreOfMass()
    center = np.array([c.X(), c.Y(), c.Z()], float)
    pp = props.PrincipalProperties()
    if pp.HasSymmetryPoint():                      # trzy równe momenty: każda oś jest główna - zostają osie globalne
        return center, dict(AXIS_VECTORS)
    found = [_unit((v.X(), v.Y(), v.Z())) for v in (pp.FirstAxisOfInertia(), pp.SecondAxisOfInertia(), pp.ThirdAxisOfInertia())]
    if pp.HasSymmetryAxis():
        # dwa równe momenty: jednoznaczna jest tylko oś symetrii (moment różny od dwóch pozostałych); w płaszczyźnie
        # prostopadłej kierunki są dowolne - biorę osie globalne rzutowane na tę płaszczyznę
        m = pp.Moments()
        k = max(range(3), key=lambda i: min(abs(m[i] - m[j]) for j in range(3) if j != i))
        s = found[k]
        name = max('XYZ', key=lambda n: abs(float(s @ AXIS_VECTORS[n])))
        axes = {name: s if float(s @ AXIS_VECTORS[name]) >= 0 else -s}
        rest = [n for n in 'XYZ' if n != name]
        g = AXIS_VECTORS[rest[0]] - axes[name] * float(AXIS_VECTORS[rest[0]] @ axes[name])
        if float(np.linalg.norm(g)) < 1e-6:
            g = AXIS_VECTORS[rest[1]] - axes[name] * float(AXIS_VECTORS[rest[1]] @ axes[name])
        axes[rest[0]] = _unit(g)
        third = _unit(np.cross(axes[name], axes[rest[0]]))
        axes[rest[1]] = third if float(third @ AXIS_VECTORS[rest[1]]) >= 0 else -third
        return center, axes
    axes = {}
    left = list(range(3))
    # każda oś globalna dostaje najbardziej z nią zgodną oś główną (zachłannie, od najlepszego dopasowania)
    pairs = sorted(((abs(float(found[j] @ AXIS_VECTORS[name])), name, j) for name in 'XYZ' for j in range(3)), reverse=True)
    for _, name, j in pairs:
        if name in axes or j not in left:
            continue
        v = found[j]
        axes[name] = v if float(v @ AXIS_VECTORS[name]) >= 0 else -v
        left.remove(j)
    return center, axes


def edge_axis(edge):
    """Oś wzdłuż prostej krawędzi B-Rep: (początek krawędzi, kierunek)."""
    if edge.geomType() != 'LINE':
        raise kernel.CadError('Wybierz prostą krawędź (odcinek) - łuk albo krzywa nie wyznacza osi.')
    a, b = np.asarray(edge.startPoint().toTuple(), float), np.asarray(edge.endPoint().toTuple(), float)
    return a, _unit(b - a)


def cylinder_axis(face):
    """Oś powierzchni walcowej (Open CASCADE gp_Cylinder): (punkt osi, kierunek)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    surface = BRepAdaptor_Surface(face.wrapped)
    if surface.GetType() != GeomAbs_Cylinder:
        raise kernel.CadError('Wybierz powierzchnię walcową (np. otwór albo wałek).')
    ax = surface.Cylinder().Axis()
    p, d = ax.Location(), ax.Direction()
    return np.array([p.X(), p.Y(), p.Z()], float), _unit((d.X(), d.Y(), d.Z()))


def points_axis(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if float(np.linalg.norm(b - a)) < 1e-6:
        raise kernel.CadError('Dwa punkty osi muszą być różne.')
    return a, _unit(b - a)


def resolve(spec, shape):
    """Oś skręcenia (punkt, kierunek) z opisu spec: dict(kind, axis 'X'/'Y'/'Z', p, d, reverse)."""
    kind = spec.get('kind', 'global')
    if kind == 'global':
        origin, direction = body_center(shape), AXIS_VECTORS[spec.get('axis', 'Z')].copy()
    elif kind == 'local':
        origin, axes = principal_axes(shape)
        direction = axes[spec.get('axis', 'Z')]
    elif spec.get('p') is not None and spec.get('d') is not None:
        origin, direction = np.asarray(spec['p'], float), _unit(spec['d'])
    else:
        raise kernel.CadError('Wskaż oś skręcenia.')
    if spec.get('reverse'):
        direction = -direction
    return np.asarray(origin, float), np.asarray(direction, float)


def extent(points, origin, direction):
    """Zasięg punktów bryły wzdłuż osi i od osi: (t_min, t_max, największa odległość od osi)."""
    pts = np.asarray(points, float).reshape(-1, 3)
    rel = pts - origin
    t = rel @ direction
    radial = np.linalg.norm(rel - np.outer(t, direction), axis=1)
    return float(t.min()), float(t.max()), float(radial.max())


def ring_basis(axis):
    """Te same kierunki odniesienia co pierścienie obrotu w widoku (Overlay2D._draw_ring): kąt 0 wzdłuż e1."""
    axis = np.asarray(axis, float)
    e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(axis, e1)
