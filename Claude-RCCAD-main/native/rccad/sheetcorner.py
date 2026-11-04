"""Analytic butt-joint curtains from complete flange-chain cross sections.

A through wall ends at the neighbour's far skin. The terminating wall ends
against the through wall's near skin, offset by the requested clearance. Filled
radial shadows avoid carving grooves or islands with individual neighbour solids.
"""
import math
from collections import OrderedDict
from threading import RLock
import numpy as np
import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.TopoDS import TopoDS
from . import kernel as k


_TOL=1e-7
_CACHE=OrderedDict()
_CACHE_LOCK=RLock()


def _positive(face):
    if face.normalAt().z<0:
        return cq.Face(TopoDS.Face_s(face.wrapped.Reversed()))
    return face


def _rectangle(x0,y0,x1,y1):
    wire=cq.Wire.makePolygon([cq.Vector(x0,y0,0),cq.Vector(x1,y0,0),cq.Vector(x1,y1,0),cq.Vector(x0,y1,0)],close=True)
    return _positive(cq.Face.makeFromWires(wire))


def _monotone_edges(edge):
    """Split exact circular arcs at height extrema before constructing shadows."""
    ad=edge._geomAdaptor();first,last=ad.FirstParameter(),ad.LastParameter();params=[first,last]
    if edge.geomType()=='CIRCLE':
        circle=ad.Circle();phase=math.atan2(circle.YAxis().Direction().Y(),circle.XAxis().Direction().Y())
        for turn in range(math.floor((first-phase)/math.pi)-1,math.ceil((last-phase)/math.pi)+2):
            p=phase+turn*math.pi
            if first+1e-10<p<last-1e-10:params.append(p)
    elif edge.geomType()!='LINE':
        raise k.CadError('Nie rozpoznano analitycznego przekroju gięcia równoległego.')
    curve=ad.Curve().Curve().Copy();curve.Transform(ad.Trsf())
    params.sort()
    for lo,hi in zip(params,params[1:]):
        yield cq.Edge(BRepBuilderAPI_MakeEdge(curve,lo,hi).Edge())


def _relief_edge(edge):
    """A conservative straight relief in the radial/height plane.

    Chords lie inside right-facing circular skins. For left-facing skins a
    midpoint tangent lies outside the material. Both choices lower radial X:
    the through end only loses material, and the terminating end gains relief.
    This avoids tiny offset circles and hooks where successive bends meet.
    The circular skins of the sheet itself are never approximated.
    """
    if edge.geomType()!='CIRCLE':return edge
    a,b=edge.startPoint(),edge.endPoint()
    if abs(a.y-b.y)<_TOL:return edge
    middle=edge.positionAt(.5)
    chord=a+(b-a)*((middle.y-a.y)/(b.y-a.y))
    if middle.x>=chord.x-_TOL:
        return cq.Edge.makeLine(a,b)
    tangent=edge.tangentAt(.5)
    if abs(tangent.y)<1e-12:
        raise k.CadError('Nie można wyznaczyć prostego podcięcia narożnika gięcia.')
    slope=tangent.x/tangent.y
    return cq.Edge.makeLine(cq.Vector(middle.x+(a.y-middle.y)*slope,a.y,0),
                            cq.Vector(middle.x+(b.y-middle.y)*slope,b.y,0))


def _shadow(edge,far):
    a,b=edge.startPoint(),edge.endPoint()
    if abs(a.y-b.y)<_TOL:return None
    c,d=cq.Vector(far,b.y,0),cq.Vector(far,a.y,0)
    edges=[edge,cq.Edge.makeLine(b,c),cq.Edge.makeLine(c,d),cq.Edge.makeLine(d,a)]
    return _positive(cq.Face.makeFromWires(cq.Wire.assembleEdges(edges)))


def _union(faces):
    result=faces[0].fuse(*faces[1:]).clean() if len(faces)>1 else faces[0]
    if not result.isValid() or result.Area()<1e-8:
        raise k.CadError('Nie można zbudować ciągłego obrysu narożnika równoległego.')
    return result


def _polygon_expand(region,gap):
    """Conservative planar fallback for offsets at re-entrant corners.

    Edge strips give the exact normal gap; square vertex pads contain the
    radius-gap disk, so difficult joins gain clearance instead of colliding.
    This is a polygonal Minkowski expansion, not an offset of a 3D bend.
    """
    faces=list(region.Faces())
    for edge in region.Edges():
        if edge.geomType()!='LINE':
            raise k.CadError('Nie można wyznaczyć prostego luzu narożnika gięcia.')
        a,b=edge.startPoint(),edge.endPoint()
        delta=b-a
        if delta.Length<_TOL:continue
        n=cq.Vector(-delta.y,delta.x,0).normalized()*gap
        wire=cq.Wire.makePolygon([a+n,b+n,b-n,a-n],close=True)
        faces.append(_positive(cq.Face.makeFromWires(wire)))
    for vertex in region.Vertices():
        p=vertex.Center()
        faces.append(_rectangle(p.x-gap,p.y-gap,p.x+gap,p.y+gap))
    result=_union(faces)
    if result.Area()<=region.Area() or region.cut(result).Area()>1e-5:
        raise k.CadError('Nie można zachować szczeliny przy tym narożniku gięcia.')
    return result


def _expand(region,gap,kind='arc'):
    if gap<=_TOL:return region
    # Offset the entire filled region, not translated copies of separate walls.
    # The gap is a normal distance, including inclined and circular skins.
    for sign in (1,-1):
        faces=[]
        try:
            for face in region.Faces():
                for wire in _positive(face).outerWire().offset2D(sign*gap,kind):
                    faces.append(_positive(cq.Face.makeFromWires(wire)))
            if not faces:continue
            result=_union(faces)
            if result.Area()>region.Area() and region.cut(result).Area()<1e-5:
                return result
        except Exception:
            continue
    if kind=='intersection':return _polygon_expand(region,gap)
    raise k.CadError('Szczelina nie mieści się przy tym narożniku równoległym. Zmniejsz szczelinę lub promień sąsiednich gięć.')


def _extrude(region,reach):
    solids=[cq.Solid.extrudeLinear(face.outerWire(),face.innerWires(),cq.Vector(0,0,2*reach)).translate((0,0,-reach)) for face in region.Faces()]
    if not solids:raise k.CadError('Nie można zbudować narzędzia docinania narożnika.')
    return k.valid(solids[0].fuse(*solids[1:]).clean()) if len(solids)>1 else k.valid(solids[0])


def _curtains(root,family_parts,normal,reach,gap,planar=False):
    """Return local (far-skin cutter, offset near-skin cutter), in radial/Z axes."""
    radial=np.asarray(root['m'],float);normal=np.asarray(normal,float)
    axis=np.cross(radial,normal);axis/=np.linalg.norm(axis)
    origin=(root['p0']+root['p1'])/2
    plane=cq.Plane(origin=tuple(origin),xDir=tuple(radial),normal=tuple(axis))
    profiles=[]
    for part in family_parts:
        cap=next((face for face in part.Faces() if face.geomType()=='PLANE' and abs(float(np.array(face.normalAt().toTuple())@axis))>1-1e-6),None)
        if cap is None:raise k.CadError('Nie znaleziono przekroju kołnierza równoległego.')
        face=cap.transformShape(plane.fG)
        profiles.append(face.translate((0,0,-face.Center().z)))
    edges=[piece for face in profiles for edge in face.Edges() for piece in _monotone_edges(edge)]
    vertices=[point for edge in edges for point in (edge.startPoint(),edge.endPoint())]
    low,high=min(p.y for p in vertices),max(p.y for p in vertices)
    relief=[_relief_edge(edge) for edge in edges] if planar else edges
    left=[face for edge in relief if (face:=_shadow(edge,-reach)) is not None]
    right=[face for edge in relief if (face:=_shadow(edge,reach)) is not None]
    for height,bottom,top in ((low,-reach,low),(high,high,reach)):
        points=[p.x for p in vertices if abs(p.y-height)<1e-6]
        if top-bottom>_TOL:
            left.append(_rectangle(-reach,bottom,max(points),top))
            right.append(_rectangle(min(points),bottom,reach,top))
    left_region=_union(left);right_region=_union(right)
    far=_rectangle(-reach,-reach,reach,reach).cut(left_region).clean()
    near=_expand(right_region,gap,'intersection' if planar else 'arc')
    return _extrude(far,reach),_extrude(near,reach)


def curtains(root,family_parts,normal,reach,gap,cache_key=None,planar=False):
    # The key contains thickness, reach, gap and the complete normalized chain;
    # opposite box walls can share templates regardless of world placement.
    if cache_key is not None:
        cache_key=(planar,cache_key)
        with _CACHE_LOCK:
            found=_CACHE.get(cache_key)
            if found is not None:
                _CACHE.move_to_end(cache_key)
                return tuple(shape.copy() for shape in found)
    result=_curtains(root,family_parts,normal,reach,gap,planar)
    if cache_key is not None:
        with _CACHE_LOCK:
            _CACHE[cache_key]=result
            _CACHE.move_to_end(cache_key)
            while len(_CACHE)>32:_CACHE.popitem(last=False)
    return tuple(shape.copy() for shape in result)
