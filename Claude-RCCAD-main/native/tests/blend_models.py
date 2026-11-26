"""Modele testowe zaokrąglania / fazowania (wspólne dla diagnostyki i testów regresji)."""
import os, tempfile
import cadquery as cq
import numpy as np


def models():
    W = cq.Workplane
    out = {}
    out['cube'] = W().box(20, 20, 20).val()
    out['box'] = W().box(60, 30, 12).val()
    out['cylinder'] = W().cylinder(30, 10).val()
    out['cone'] = cq.Solid.makeCone(12, 0, 25)
    out['frustum'] = cq.Solid.makeCone(12, 6, 20)
    out['tube'] = W().cylinder(30, 12).faces('>Z').workplane().hole(14).val()
    out['sphere_cut'] = W().sphere(15).cut(W().box(40, 40, 40).translate((0, 0, -26))).val()
    out['torus_cut'] = cq.Solid.makeTorus(20, 6).cut(W().box(60, 60, 20).translate((0, -30, 0)).val()).cut(W().box(60, 4, 30).val())
    out['through_hole'] = W().box(40, 30, 10).faces('>Z').workplane().hole(8).val()
    out['blind_hole'] = W().box(40, 30, 10).faces('>Z').workplane().hole(8, 5).val()
    out['multi_holes'] = W().box(60, 40, 8).faces('>Z').workplane().rarray(12, 10, 4, 3).hole(4).val()
    out['thin_wall'] = W().box(50, 40, 25).faces('>Z').shell(-1.2).val()
    rib = W().box(60, 40, 30).faces('>Z').shell(-2)
    for x in (-15, 0, 15):
        rib = rib.union(W().box(2, 36, 20).translate((x, 0, -4)))
    out['ribbed'] = rib.val()
    out['inclined'] = cq.Solid.extrudeLinear(cq.Wire.makePolygon([(0, 0, 0), (40, 0, 0), (32, 0, 20), (6, 0, 14)], close=True), [], cq.Vector(0, 25, 0))
    out['curved'] = W('XZ').polyline([(0, 0), (20, 0), (20, 5)]).threePointArc((15, 12), (5, 15)).lineTo(0, 15).close().revolve(270, (0, 0, 0), (0, 1, 0)).val()
    out['bspline'] = W().rect(30, 20).workplane(offset=15).ellipse(12, 7).loft().val()
    out['short_edges'] = W().box(30, 30, 10).cut(W().box(0.3, 31, 0.3).translate((14.85, 0, 4.85))).val()
    out['small_faces'] = W().box(30, 30, 10).union(W().box(0.4, 0.4, 0.4).translate((0, 0, 5.2))).val()
    many = W().box(200, 200, 10).faces('>Z').workplane().rarray(9, 9, 20, 20).hole(4)
    out['many_edges'] = many.val()
    path = os.path.join(tempfile.mkdtemp(), 'm.step')
    asm = W().box(40, 40, 10).union(W().cylinder(20, 8).translate((0, 0, 15))).faces('>Z').workplane().hole(5).val()
    cq.exporters.export(W().add(asm), path)
    out['step'] = cq.importers.importStep(path).val()
    return out


def edge_sets(shape):
    """Konfiguracje zaznaczenia: nazwa -> lista indeksów (puste konfiguracje pomijane)."""
    from rccad import kernel as k
    E = shape.Edges()
    n = len(E)
    real = set(k.display_mesh(shape).edges)              # krawędzie, które da się kliknąć w widoku (bez szwów walców i stożków)
    emap = k._edge_faces(shape) if hasattr(k, '_edge_faces') else None
    sets = {}
    lines = [i for i, e in enumerate(E) if e.geomType() == 'LINE' and i in real]
    circles = [i for i, e in enumerate(E) if e.geomType() == 'CIRCLE' and i in real]
    ellipses = [i for i, e in enumerate(E) if e.geomType() == 'ELLIPSE' and i in real]
    splines = [i for i, e in enumerate(E) if e.geomType() in ('BSPLINE', 'BEZIER') and i in real]
    if real:
        longest = max(real, key=lambda i: E[i].Length())
        sets['one'] = [longest]
        sets['all'] = sorted(real)
    # dwie sąsiednie / niesąsiednie, trzy w narożniku
    vtx = {}
    for i, e in enumerate(E):
        for v in e.Vertices():
            vtx.setdefault(tuple(np.round(v.toTuple(), 5)), []).append(i)
    corner = next((ids for ids in vtx.values() if len(set(ids)) == 3 and set(ids) <= real), None)
    if corner:
        sets['corner3'] = sorted(set(corner))
        sets['adjacent2'] = sorted(set(corner))[:2]
    if len(lines) >= 2:
        a = lines[0]
        va = {tuple(np.round(v.toTuple(), 5)) for v in E[a].Vertices()}
        far = [i for i in lines if not ({tuple(np.round(v.toTuple(), 5)) for v in E[i].Vertices()} & va)]
        if far:
            sets['separate2'] = [a, far[-1]]
    faces = shape.Faces()
    if faces:
        big = max(faces, key=lambda f: f.Area())
        ids = [i for i, e in enumerate(E) if i in real and any(e.isSame(fe) for fe in big.Edges())]
        if ids:
            sets['face_loop'] = ids
    for name, group in (('circle', circles), ('ellipse', ellipses), ('spline', splines)):
        if group:
            sets[name] = group[:1]
    # wklęsłe: krawędzie z kątem wewnętrznym > 180°
    concave = []
    try:
        from OCP.TopoDS import TopoDS
        em = k._edge_faces(shape)
        for i in lines:
            fl = em.FindFromKey(E[i].wrapped)
            if fl.Size() != 2:
                continue
            fs = [cq.Face(TopoDS.Face_s(f)) for f in fl]
            if any(f.geomType() != 'PLANE' for f in fs):
                continue
            m = E[i].positionAt(.5)
            nsum = fs[0].normalAt(m) + fs[1].normalAt(m)
            if nsum.Length < 1e-9:
                continue
            q = m + nsum.normalized() * 1e-3
            if k.point_state(shape, q.toTuple()) == 'in':
                concave.append(i)
    except Exception as e:
        print('concave?', e)
    if concave:
        sets['concave'] = concave[:1]
    return sets
