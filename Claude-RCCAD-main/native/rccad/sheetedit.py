"""Reversible sheet editing. Rigid panel maps and compensated cylindrical development.

Edits are measured against the nominal recipe at each switch; ordinary CAD
operations remain ordinary history steps. Rigid panel maps preserve arbitrary
panel features; cylindrical surface maps carry through cuts across bends.
Unsupported local thickness edits on bends are rejected without losing edits.
"""
from dataclasses import dataclass
import math
import copy
import json
import threading
from functools import lru_cache
import numpy as np
import cadquery as cq
from . import kernel as k, sheetmetal as s


def state(recipe, flat=False):
    return {'recipe': copy.deepcopy({key:recipe[key] for key in ('base','t','flanges','rules') if key in recipe}), 'flat':bool(flat), 'dirty':False, 'edited':False, 'bend_engine':s.ENGINE}


_POINT_KEYS = ('o', 'p0', 'p1')
_DIR_KEYS = ('x', 'y', 'z', 'n', 'm')


def placed_state(metadata, matrix):
    """Stan blachy po sztywnym przesunięciu / obrocie całej bryły (macierz 3x4): punkty i kierunki przepisu
    (płyta bazowa, krawędzie kołnierzy) przenoszą się razem z bryłą, a pozostałe dane - bez zmian. Ruch nie jest
    edycją blachy, więc znacznik zmian (dirty) zostaje taki, jaki był."""
    M = np.asarray(matrix, float)
    u, _, vt = np.linalg.svd(M[:, :3])
    R, t = u @ vt, M[:, 3]

    def move(node):
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                vec = isinstance(value, (list, tuple)) and len(value) == 3 and all(isinstance(c, (int, float)) for c in value)
                if vec and key in _POINT_KEYS:
                    out[key] = [float(c) for c in R @ np.asarray(value, float) + t]
                elif vec and key in _DIR_KEYS:
                    out[key] = [float(c) for c in R @ np.asarray(value, float)]
                else:
                    out[key] = move(value)
            return out
        if isinstance(node, list):
            return [move(v) for v in node]
        return copy.deepcopy(node)

    result = copy.deepcopy(metadata)
    result['recipe'] = move(metadata['recipe'])
    return result


def _matrix(origin, axes):
    q = np.column_stack(axes)
    from OCP.gp import gp_Trsf
    trsf=gp_Trsf()
    trsf.SetValues(*(float(v) for row in range(3) for v in [*q[row,:],origin[row]]))
    return cq.Matrix(trsf)


def _inverse(matrix):
    a = np.array([[matrix[row,col] for col in range(4)] for row in range(4)])
    inv=np.linalg.inv(a)
    return _matrix(inv[:3,3],inv[:3,:3].T)


def _map(shape, source, target):
    return shape.transformShape(_inverse(source)).transformShape(target)


def _faces_slab(faces, t):
    solids=[]
    for face in faces:
        face=face.translate((0,0,-face.Center().z))
        solids.append(k.valid(cq.Solid.extrudeLinear(face.outerWire(),face.innerWires(),cq.Vector(0,0,t))))
    if not solids:
        raise k.CadError('Nie znaleziono powierzchni obojętnej blachy.')
    return k.valid(solids[0].fuse(*solids[1:]).clean()) if len(solids)>1 else solids[0]


def _section(piece, point, normal, xdir, reach):
    wire=cq.Workplane(cq.Plane(origin=tuple(point),xDir=tuple(xdir),normal=tuple(normal))).rect(2*reach,2*reach).val()
    return cq.Face.makeFromWires(wire).intersect(piece).Faces()


@dataclass
class Panel:
    key: int
    folded: cq.Shape
    flat: cq.Shape
    folded_frame: cq.Matrix
    flat_frame: cq.Matrix


@dataclass
class Layout:
    folded: cq.Shape
    flat: cq.Shape
    panels: list
    folded_bends: list
    flat_bends: list
    bends: list


@dataclass
class Bend:
    key: str
    folded: cq.Shape
    flat: cq.Shape
    frame: dict
    work_frame: dict
    flat_frame: cq.Matrix
    origin: np.ndarray
    outward: np.ndarray
    axis: np.ndarray
    thickness: float
    factor: float


def _develop_face(face, mapper, target_surface=None, stretch=1.):
    """Affine map of the cylinder's UV curves, preserving rational splines."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.Geom2d import Geom2d_TrimmedCurve
    from OCP.Geom2dConvert import Geom2dConvert
    from OCP.GeomAPI import GeomAPI
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.gp import gp_Pnt2d, gp_Pln, gp_Pnt, gp_Dir
    from OCP.TopAbs import TopAbs_REVERSED
    def wire(source):
        explorer=BRepTools_WireExplorer(source.wrapped,face.wrapped);edges=[]
        while explorer.More():
            edge=explorer.Current();ad=BRepAdaptor_Curve2d(edge,face.wrapped)
            curve=BRep_Tool.CurveOnSurface_s(edge,face.wrapped,ad.FirstParameter(),ad.LastParameter())
            spline=Geom2dConvert.CurveToBSplineCurve_s(Geom2d_TrimmedCurve(curve,ad.FirstParameter(),ad.LastParameter())).Copy()
            for i in range(1,spline.NbPoles()+1):
                pole=spline.Pole(i);point=mapper(np.array([pole.X(),pole.Y()]))
                spline.SetPole(i,gp_Pnt2d(float(point[0]),float(point[1])))
            if target_surface is None:
                edge3=BRepBuilderAPI_MakeEdge(GeomAPI.To3d_s(spline,gp_Pln(gp_Pnt(0,0,0),gp_Dir(0,0,1)))).Edge()
            else:
                from OCP.BRepLib import BRepLib
                edge3=BRepBuilderAPI_MakeEdge(spline,target_surface).Edge()
                if not BRepLib.BuildCurves3d_s(edge3,1e-8):
                    raise k.CadError('Nie można dokładnie odwzorować konturu na łuku gięcia.')
            # Boolean pcurves may extend a fraction of the original vertex
            # tolerance beyond their shared endpoints. Preserve that tolerance
            # after mapping instead of disconnecting an otherwise closed wire.
            from OCP.BRep import BRep_Builder
            tolerance=max([BRep_Tool.Tolerance_s(vertex.wrapped) for vertex in cq.Edge(edge).Vertices()]+[1e-7])*stretch
            builder=BRep_Builder()
            for vertex in cq.Edge(edge3).Vertices():builder.UpdateVertex(vertex.wrapped,tolerance)
            builder.UpdateEdge(edge3,tolerance)
            if edge.Orientation()==TopAbs_REVERSED:
                from OCP.TopoDS import TopoDS
                edge3=TopoDS.Edge_s(edge3.Reversed())
            edges.append(cq.Edge(edge3));explorer.Next()
        return cq.Wire.assembleEdges(edges)
    outer=wire(face.outerWire());inners=[wire(w) for w in face.innerWires()]
    if target_surface is None:
        return cq.Face.makeFromWires(outer,inners)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    builder=BRepBuilderAPI_MakeFace(target_surface,outer.wrapped,True)
    for inner in inners:builder.Add(inner.wrapped)
    return cq.Face(builder.Face())


def _bend_blank(piece, frame, work_frame, t, factor, flat_origin, outward, flat_axis):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.gp import gp_Vec
    origin,X,Y,Z,_=s._frame(frame['p0'],frame['p1'],t,frame['n'],frame['m'])
    work_origin,_,_,_,span=s._frame(work_frame['p0'],work_frame['p1'],t,work_frame['n'],work_frame['m'])
    radius=frame['r']+.5*t;developed_radius=frame['r']+factor*t
    theta=math.radians(frame['angle']);center=t+frame['r']
    def point(phi):return cq.Vector(*(work_origin+radius*math.sin(phi)*X+(center-radius*math.cos(phi))*Y))
    edge=cq.Edge.makeThreePointArc(point(0),point(theta/2),point(theta))
    surface=cq.Shape.cast(BRepPrimAPI_MakePrism(edge.wrapped,gp_Vec(*(span*Z))).Shape())
    result=surface.intersect(piece)
    developed=[]
    for face in result.Faces():
        ad=BRepAdaptor_Surface(face.wrapped)
        u,v=ad.FirstUParameter(),ad.FirstVParameter()
        def coordinates(uv):
            p=np.array(ad.Value(float(uv[0]),float(uv[1])).Coord())
            radial=p-origin-center*Y
            phi=math.atan2(float(radial@X),-float(radial@Y))
            if phi < -1e-7:phi+=2*math.pi
            return np.array([phi,float((p-origin)@Z)])
        uv=np.array([u,v]);q=coordinates(uv)
        from OCP.gp import gp_Pnt,gp_Vec
        p0,dU,dV=gp_Pnt(),gp_Vec(),gp_Vec();ad.D1(u,v,p0,dU,dV)
        radial=np.array(p0.Coord())-origin-center*Y
        du,dv=np.array(dU.Coord()),np.array(dV.Coord())
        angular=(-float(radial@Y)*float(du@X)+float(radial@X)*float(du@Y))/(radius*radius)
        axial=float(dv@Z)
        if abs(abs(angular)-1)>1e-6 or abs(abs(axial)-1)>1e-6:
            raise k.CadError('Nie rozpoznano parametrów powierzchni gięcia.')
        # Use exact surface derivatives: an extrusion's V direction need not
        # agree with the equivalent cylinder's reported axis orientation.
        u_sense=1. if angular>0 else -1.;v_sense=1. if axial>0 else -1.
        basis=np.column_stack([developed_radius*u_sense*outward,v_sense*flat_axis])
        offset=flat_origin+developed_radius*q[0]*outward+q[1]*flat_axis-basis@uv
        developed.append(_develop_face(face,lambda p:basis@p+offset,stretch=max(1.,developed_radius/radius)))
    return _faces_slab(developed,t)


def _build_layout(recipe, require_blank=True, parallel_version=s.ENGINE):
    recipe=s.normalize(recipe)      # wymiary zewnętrzne / wewnętrzne -> proste części i przycięta płyta
    specs=recipe.get('flanges') or [];rules=recipe.get('rules') or {};t=float(recipe['t'])
    factor=float(rules.get('kfactor',s.K_DEFAULT))
    if not math.isfinite(factor) or not 0<=factor<=.5:raise k.CadError('Współczynnik K musi być w zakresie 0–0,5.')
    folded=s.build_sheet(recipe,parallel_version=parallel_version)
    eff,corners=s._effective(specs,t,bool(rules.get('miter',True)),bool(rules.get('outside',False)))
    if corners:
        pieces=s._corner_parts(recipe,eff,corners,parallel_version=parallel_version)
        work,_,_,_=s._corner_layout(specs,eff,corners,t)
    else:
        pieces={i:s._flange_parts(f,t) for i,f in enumerate(eff)};work=eff
    base=recipe['base'];base_origin=s._arr(base['o']);x,y,z=[s._unit(base[key]) for key in ('x','y','z')]
    base_frame=_matrix(base_origin,[x,y,z]);identity=_matrix([0,0,0],np.eye(3))
    relief=rules.get('relief','none')!='none' and float(rules.get('relief_size',0))>0
    base_piece=s.base_solid(base)
    if relief:base_piece=base_piece.intersect(folded).clean()
    base_faces=_section(base_piece,base_origin+t/2*z,z,x,sum(base[key] for key in ('lx','ly','lz'))+1)
    base_blank=_faces_slab([_map(face,base_frame,identity) for face in base_faces],t)
    panels=[Panel(-1,base_piece,base_blank,base_frame,identity)];bent=[];flat_bent=[];flat_frames=[];bend_maps=[]
    reach=sum(float(base[key]) for key in ('lx','ly','lz'))+4*sum(f['length']+2*(f['r']+t) for f in eff)+1
    def xy(p):
        d=s._arr(p)-base_origin;return np.array([d@x,d@y])
    for i,(spec,f) in enumerate(zip(specs,eff)):
        if spec['kind']=='base':
            a,b=xy(f['p0']),xy(f['p1']);outward=np.array([f['m']@x,f['m']@y]);direction=1 if f['n']@z>0 else -1
        else:
            par=eff[spec['parent']];prior=flat_frames[spec['parent']]
            d3=s._unit(par['p1']-par['p0']);d2=(prior['b']-prior['a'])/np.linalg.norm(prior['b']-prior['a'])
            a=prior['end_a']+float((f['p0']-par['p0'])@d3)*d2
            b=prior['end_a']+float((f['p1']-par['p0'])@d3)*d2
            outward=prior['outward'];direction=prior['direction']*(1 if spec['side']=='in' else -1)
        allowance=math.radians(f['angle'])*(f['r']+factor*t)
        flat_frames.append(dict(a=a,b=b,outward=outward,direction=direction,
                                end_a=a+(allowance+f['length'])*outward,end_b=b+(allowance+f['length'])*outward))
        origin,X,Y,Z,span=s._frame(f['p0'],f['p1'],t,f['n'],f['m'])
        forward=float(Z@s._unit(f['p1']-f['p0']))>0
        flat_origin=a if forward else b;flat_axis=(b-a)/np.linalg.norm(b-a)*(1 if forward else -1)
        theta=math.radians(f['angle']);D=math.cos(theta)*X+math.sin(theta)*Y;V=math.sin(theta)*X-math.cos(theta)*Y
        inner=origin+f['r']*math.sin(theta)*X+(t+f['r']-f['r']*math.cos(theta))*Y
        folded_frame=_matrix(inner,[D,Z,V])
        flat_point=np.r_[flat_origin+allowance*outward,t if direction>0 else 0]
        flat_frame=_matrix(flat_point,[np.r_[outward,0],np.r_[flat_axis,0],np.array([0,0,-direction])])
        bend,leg=pieces[i]
        if relief and spec['kind']=='base':
            bend=bend.intersect(folded).clean();leg=leg.intersect(folded).clean()
        sections=_section(leg,inner+.5*t*V,V,D,reach)
        blank=_faces_slab([_map(face,folded_frame,flat_frame) for face in sections],t)
        bend_blank=_bend_blank(bend,f,work[i],t,factor,flat_origin,outward,flat_axis)
        panels.append(Panel(i,leg,blank,folded_frame,flat_frame));bent.append(bend);flat_bent.append(bend_blank)
        bend_frame=_matrix(np.r_[flat_origin,t if direction>0 else 0],
                           [np.r_[outward,0],np.r_[flat_axis,0],np.array([0,0,-direction])])
        bend_maps.append(Bend('b'+str(i),bend,bend_blank,f,work[i],bend_frame,flat_origin,outward,flat_axis,t,factor))
    if parallel_version>=4 and corners:
        from . import sheetparallel
        if (parallel_version>=5 and rules.get('auto_corners')) or sheetparallel.eligible(recipe,eff,corners):
            sheetparallel.partition_flat_roots(flat_bent,bend_maps,corners)
    all_flat=[p.flat for p in panels]+flat_bent
    blank=k.valid(all_flat[0].fuse(*all_flat[1:]).clean()) if len(all_flat)>1 else all_flat[0]
    expected=sum(p.Volume(1e-9) for p in all_flat)
    if require_blank and expected-blank.Volume(1e-9)>max(1e-4,expected*1e-8):
        # Spline boundary quadrature can change after a planar union. Confirm
        # overlap geometrically rather than accepting/rejecting by mass alone.
        for i,left in enumerate(all_flat):
            bb=left.BoundingBox()
            for right in all_flat[i+1:]:
                cb=right.BoundingBox()
                if any(min(getattr(bb,d+'max'),getattr(cb,d+'max'))<=max(getattr(bb,d+'min'),getattr(cb,d+'min'))+1e-6 for d in 'xy'):
                    continue
                if abs(left.intersect(right).Volume(1e-9))>1e-5:
                    raise k.CadError('Rozłożone fragmenty blachy nachodzą na siebie. Ten układ wymaga innego rozcięcia lub podziału rozwinięcia.')
    if require_blank and len(blank.Solids())!=1:raise k.CadError('Rozwinięcie nie tworzy jednej połączonej blachy.')
    return Layout(folded,blank,panels,bent,flat_bent,bend_maps)


@lru_cache(maxsize=4)
def _cached_layout(key, require_blank=True, parallel_version=s.ENGINE):
    return _build_layout(json.loads(key),require_blank,parallel_version)


_LAYOUT_LOCKS={}
_LOCKS_GUARD=threading.Lock()
_WARM=set()


def _layout_key(recipe):
    return json.dumps(state(recipe)['recipe'],sort_keys=True,allow_nan=False)


def layout(recipe):
    # Geometry is immutable: repeated mode switches and previews reuse the
    # same validated maps. Edits remain in the document, never in this cache.
    key=_layout_key(recipe)
    with _LOCKS_GUARD:
        lock=_LAYOUT_LOCKS.setdefault(key,threading.Lock())
    with lock:          # rozwinięcie liczone właśnie w tle: zamiast liczyć drugi raz, poczekaj na gotowy wynik
        model=_cached_layout(key)
    _WARM.add(key)
    return model


def is_warm(recipe):
    try:
        return _layout_key(recipe) in _WARM
    except Exception:
        return True


def warm(recipe):
    """Rozwinięcie przygotowane w tle (po zmianie blachy, gdy nic się nie dzieje): Rozłóż / Zegnij, DXF i rysunek
    blachy biorą je potem gotowe z pamięci. Błędy są tu pomijane - pokaże je dopiero właściwa operacja."""
    try:
        layout(recipe)
        return True
    except Exception:
        return False


def _source_engine(source_state):
    version=source_state.get('bend_engine',1)
    if version not in (1,2,3,4,5,6):
        raise k.CadError('Ten projekt używa nieobsługiwanej wersji konstrukcji gięć.')
    joint=(source_state['recipe'].get('rules') or {}).get('joint','parallel')
    return version if joint=='parallel' else max(version,5)


def _source_layout(source_state):
    key=json.dumps(state(source_state['recipe'])['recipe'],sort_keys=True,allow_nan=False)
    return _cached_layout(key,False,_source_engine(source_state))


def _bend_cut(canonical, bend):
    """Wrap a through-thickness contour onto an analytic cylindrical bend."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.gp import gp_Ax3,gp_Pnt,gp_Dir
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
    t=bend.thickness;f=bend.frame
    origin,X,Y,Z,_=s._frame(f['p0'],f['p1'],t,f['n'],f['m'])
    center=origin+(t+f['r'])*Y
    surface=Geom_CylindricalSurface(gp_Ax3(gp_Pnt(*center),gp_Dir(*Z),gp_Dir(*(-Y))),f['r'])
    reach=1+sum(abs(v) for point in canonical.Vertices() for v in point.toTuple())
    faces=_section(canonical,np.array([0,0,t/2]),np.array([0,0,1]),np.array([1,0,0]),reach)
    solids=[]
    for face in faces:
        ad=BRepAdaptor_Surface(face.wrapped)
        o=np.array(ad.Value(0,0).Coord());u=np.array(ad.Value(1,0).Coord())-o;v=np.array(ad.Value(0,1).Coord())-o
        radius=f['r']+bend.factor*t
        def mapper(p):
            point=o+p[0]*u+p[1]*v
            return np.array([point[0]/radius,point[1]])
        curved=_develop_face(face,mapper,surface,stretch=max(1.,(f['r']+t)/radius))
        radial=np.array(curved.Center().toTuple())-center
        radial-=float(radial@Z)*Z
        if np.array(curved.normalAt().toTuple())@radial<0:
            from OCP.TopoDS import TopoDS
            curved=cq.Face(TopoDS.Face_s(curved.wrapped.Reversed()))
        thick=BRepOffsetAPI_MakeThickSolid();thick.MakeThickSolidBySimple(curved.wrapped,t)
        solid=cq.Shape.cast(thick.Shape())
        if solid.Volume()<0:solid=cq.Shape.cast(solid.wrapped.Reversed())
        solids.append(k.valid(solid))
    return solids


def _through_cut(canonical,t):
    reach=1+sum(abs(v) for point in canonical.Vertices() for v in point.toTuple())
    faces=_section(canonical,np.array([0,0,t/2]),np.array([0,0,1]),np.array([1,0,0]),reach)
    if not faces:raise k.CadError('Zmiana grubości w obszarze gięcia nie jest obsługiwana.')
    prism=_faces_slab(faces,t)
    if _volume(prism.cut(canonical))+_volume(canonical.cut(prism))>max(1e-5,_volume(canonical)*1e-7):
        raise k.CadError('W obszarze łuku obsługiwane są wycięcia przez całą grubość. Kieszenie i zaokrąglenia zmieniające grubość łuku pozostają w bieżącym modelu.')
    return prism


def _volume(shape):
    return abs(shape.Volume(1e-9)) if shape.Solids() else 0.


def _edge_keys(shape):
    """Krawędzie pogrupowane według geometrii (rodzaj, długość, środek, końce) - do szybkiego porównania dwóch brył."""
    out={}
    for edge in shape.Edges():
        try:
            ends=sorted(tuple(round(v,5) for v in p.toTuple()) for p in (edge.startPoint(),edge.endPoint()))
            key=(edge.geomType(),round(edge.Length(),5),*[round(v,5) for v in edge.positionAt(.5).toTuple()],*ends)
        except Exception:
            key=('?',id(edge))
        out.setdefault(key,[]).append(edge)
    return out


def _diff(baseline, actual):
    """Materiał usunięty i dodany względem wzorca. Szybko: tylko w obszarze krawędzi, które się różnią (np. wokół otworu) -
    poza tym obszarem obie bryły są identyczne, a porównanie całych, prawie takich samych brył trwa sekundy.
    Wynik jest sprawdzany bilansem objętości; przy jakiejkolwiek niezgodności liczony jest dawnym, pełnym sposobem."""
    def full():
        return baseline.cut(actual).clean(),actual.cut(baseline).clean()
    try:
        keys_a,keys_b=_edge_keys(actual),_edge_keys(baseline)
        differing=[edge for key in set(keys_a)^set(keys_b) for edge in (keys_a.get(key) or keys_b.get(key))]
        total=_volume(actual)-_volume(baseline)
        if not differing:
            if abs(total)>1e-6:
                return full()
            empty=cq.Compound.makeCompound([])
            return empty,empty
        boxes=[edge.BoundingBox() for edge in differing]
        lo=np.min([[b.xmin,b.ymin,b.zmin] for b in boxes],axis=0);hi=np.max([[b.xmax,b.ymax,b.zmax] for b in boxes],axis=0)
        size=float(np.linalg.norm(hi-lo));margin=0.0123+0.0371*size+1.37*max(1e-3,min(hi-lo))
        lo,hi=lo-margin,hi+margin
        box=cq.Solid.makeBox(*(float(v) for v in hi-lo),cq.Vector(*(float(v) for v in lo)))
        local_a,local_b=actual.intersect(box),baseline.intersect(box)
        removed,added=local_b.cut(local_a).clean(),local_a.cut(local_b).clean()
        if abs((_volume(added)-_volume(removed))-total)>max(1e-5,abs(total)*1e-6):
            return full()
        return removed,added
    except Exception:
        return full()


def _changes(actual, model, flat):
    baseline=model.flat if flat else model.folded
    removed,added=_diff(baseline,actual)
    changes={p.key:{'removed':[], 'added':[]} for p in [*model.panels,*model.bends]}
    covered=0.
    for panel in model.panels:
        if _volume(removed)<=1e-7:break
        source=panel.flat if flat else panel.folded
        frame=panel.flat_frame if flat else panel.folded_frame
        cut=removed.intersect(source).clean()
        if _volume(cut)>1e-7:
            covered+=_volume(cut)
            changes[panel.key]['removed'].append(cut.transformShape(_inverse(frame)))
    for bend in model.bends:
        if _volume(removed)<=1e-7:break
        source=bend.flat if flat else bend.folded
        cut=removed.intersect(source).clean()
        if _volume(cut)<=1e-7:continue
        if flat:
            canonical=cut.transformShape(_inverse(bend.flat_frame))
            canonical=_through_cut(canonical,bend.thickness)
        else:
            blank=_bend_blank(cut,bend.frame,bend.work_frame,bend.thickness,bend.factor,bend.origin,bend.outward,bend.axis)
            canonical=blank.transformShape(_inverse(bend.flat_frame))
            reconstructed=_bend_cut(canonical,bend)
            rebuilt=reconstructed[0].fuse(*reconstructed[1:]).clean() if len(reconstructed)>1 else reconstructed[0]
            if _volume(rebuilt.cut(cut))+_volume(cut.cut(rebuilt))>max(2e-5,_volume(cut)*1e-6):
                raise k.CadError('Zmiana na łuku nie jest wycięciem przez grubość prowadzonym wzdłuż gięcia. Nie można jej bezpiecznie rozłożyć; bieżące zmiany zostały zachowane.')
        covered+=_volume(cut)
        changes[bend.key]['removed'].append(canonical)
    if _volume(removed)-covered>max(1e-5,_volume(removed)*1e-7):
        raise k.CadError('Zmiana wychodzi poza rozpoznane obszary blachy. Nie można jej bezpiecznie przenieść; bieżący model i wykonane zmiany pozostają bez zmian.')
    bends=model.flat_bends if flat else model.folded_bends
    for solid in added.Solids():
        if _volume(solid)<1e-7:continue
        owners=[p for p in model.panels if solid.distance(p.flat if flat else p.folded)<1e-5]
        if len(owners)!=1 or any(solid.distance(bend)<1e-5 for bend in bends):
            raise k.CadError('Dodany materiał musi należeć do jednej prostej ściany blachy i nie przekraczać obszaru gięcia. Bieżące zmiany zostały zachowane.')
        panel=owners[0];frame=panel.flat_frame if flat else panel.folded_frame
        changes[panel.key]['added'].append(solid.transformShape(_inverse(frame)))
    return changes


def _apply(model, changes, flat):
    result=model.flat if flat else model.folded
    panels={p.key:p for p in model.panels}
    bends={b.key:b for b in model.bends}
    for key,delta in changes.items():
        panel=panels.get(key)
        bend=bends.get(key)
        if bend is not None:
            for cut in delta['removed']:
                tools=[cut.transformShape(bend.flat_frame)] if flat else _bend_cut(cut,bend)
                for tool in tools:
                    if _volume(tool)-_volume(result.intersect(tool))>max(2e-5,_volume(tool)*1e-6):
                        raise k.CadError('Kontur wycięcia wychodzi poza obszar materiału przy narożniku gięcia. Bieżący model został zachowany.')
                    result=k.boolean('subtract',result,[tool])
            continue
        if panel is None and any(delta.values()):raise k.CadError('Zmodyfikowana ściana nie istnieje w nowym układzie gięć.')
        if panel is None:continue
        frame=panel.flat_frame if flat else panel.folded_frame
        for cut in delta['removed']:
            tool=cut.transformShape(frame)
            available=_volume(result.intersect(tool))
            if _volume(tool)-available>max(1e-5,_volume(tool)*1e-7):
                raise k.CadError('Nie można dokładnie przenieść zmiany przy zakończeniu lub narożniku gięcia. Model i wykonane zmiany pozostają bez zmian.')
            result=k.boolean('subtract',result,[tool])
    for key,delta in changes.items():
        panel=panels.get(key)
        if panel is None:continue
        frame=panel.flat_frame if flat else panel.folded_frame
        for added in delta['added']:
            tool=added.transformShape(frame)
            if _volume(result.intersect(tool))>max(1e-5,_volume(tool)*1e-7):
                raise k.CadError('Dodany materiał po zgięciu koliduje z inną częścią blachy. Zmień jego kształt lub położenie.')
            result=k.boolean('union',result,[tool])
    if len(result.Solids())!=1:raise k.CadError('Operacja rozdzieliłaby blachę na osobne części. Bieżący model został zachowany.')
    return k.valid(result)


def _unchanged(actual, baseline):
    """Szybkie potwierdzenie, że nieedytowana blacha jest dokładnie bryłą z układu gięć (objętość, wymiary, liczba ścian).
    Każda zmiana geometrii oznacza blachę jako edytowaną, a ten test dodatkowo chroni przed przesunięciem lub inną bryłą."""
    try:
        if actual is baseline or actual.wrapped.IsSame(baseline.wrapped):
            return True
        va,vb=_volume(actual),_volume(baseline)
        if abs(va-vb)>max(1e-6,vb*1e-7) or len(actual.Faces())!=len(baseline.Faces()) or len(actual.Solids())!=len(baseline.Solids()):
            return False
        a,b=actual.BoundingBox(),baseline.BoundingBox()
        return all(abs(getattr(a,n)-getattr(b,n))<1e-5 for n in ('xmin','ymin','zmin','xmax','ymax','zmax'))
    except Exception:
        return False


def _switch(actual, source_state, flat, sync=False):
    """Switch atomically, including all accumulated edits on straight panels."""
    model=layout(source_state['recipe'])
    source_model=model if _source_engine(source_state)==s.ENGINE else _source_layout(source_state)
    source_flat=source_state.get('flat',False)
    if not source_state.get('dirty') and not source_state.get('edited') and _unchanged(actual,source_model.flat if source_flat else source_model.folded):
        changes={p.key:{'removed':[],'added':[]} for p in [*source_model.panels,*source_model.bends]}      # blacha bez zmian: bez kosztownego porównania brył
    else:
        changes=_changes(actual,source_model,source_flat)
    if sync:
        _apply(model,changes,not flat)  # Confirm edits survive the other state.
    target_state=state(source_state['recipe'],flat)
    target_state['edited']=any(any(delta.values()) for delta in changes.values())
    return _apply(model,changes,flat),target_state


def switch(actual, source_state, flat, sync=False):
    try:
        return _switch(actual,source_state,flat,sync)
    except k.CadError:
        raise
    except Exception as exc:
        raise k.CadError('Nie udało się dokładnie przeliczyć rozwinięcia i wykonanych zmian. Bieżący model został zachowany.') from exc


def rebuild(actual, source_state, recipe):
    """Retain panel edits when another flange or new corner rules are added."""
    if source_state.get('flat'):
        raise k.CadError('Najpierw zegnij blachę, zanim dodasz kołnierz lub zmienisz reguły gięć.')
    if not source_state.get('dirty') and not source_state.get('edited'):
        return s.build_sheet(recipe),state(recipe,False)
    # Carrying edits in folded space does not require the complete model to
    # be manufacturable as a single flat blank. Mode switches still do.
    old=_source_layout(source_state)
    changes=_changes(actual,old,False)
    new=_cached_layout(json.dumps(state(recipe)['recipe'],sort_keys=True,allow_nan=False),False)
    target_state=state(recipe,False)
    target_state['edited']=any(any(delta.values()) for delta in changes.values())
    return _apply(new,changes,False),target_state


BEND_DASH=[6.0,4.0,-2.0]      # linia gięcia w dół: kreska 4 mm, przerwa 2 mm (wzór DXF: długość całkowita, kreska, przerwa)


def _flat_sections(blank, t):
    reach=1+sum(abs(v) for vertex in blank.Vertices() for v in vertex.toTuple())
    return _section(blank,np.array([0,0,t/2]),np.array([0,0,1]),np.array([1,0,0]),reach)


def _bend_lines(model, sections, recipe):
    """Linie gięcia rozwinięcia (środek strefy gięcia) przycięte do obrysu blachy: dict(a, b, direction UP/DOWN, index, angle, r)."""
    t=float(recipe['t']);factor=float((recipe.get('rules') or {}).get('kfactor',s.K_DEFAULT))
    lines=[]
    for bend in model.bends:
        f=bend.frame;allowance=math.radians(f['angle'])*(f['r']+factor*t)
        a=bend.origin+allowance/2*bend.outward
        span=float(np.linalg.norm(f['p1']-f['p0']));b=a+span*bend.axis
        direction='UP' if bend.flat_frame[2,2]<0 else 'DOWN'
        for start,end in s.clip_line_to_faces(a,b,sections):      # linia gięcia nie wychodzi poza kontur blachy
            start,end=np.asarray(start,float)[:len(a)],np.asarray(end,float)[:len(a)]
            lines.append(dict(a=start.tolist(),b=end.tolist(),direction=direction,index=int(bend.key[1:])+1,angle=float(f['angle']),r=float(f['r'])))
    return lines


def flat_bend_lines(actual, source_state):
    """Linie gięcia rozłożonej blachy w jej własnych współrzędnych (do rysunku technicznego): lista dict(a, b, direction)."""
    blank=actual if source_state.get('flat') else switch(actual,source_state,True)[0]
    model=layout(source_state['recipe']);t=float(source_state['recipe']['t'])
    return _bend_lines(model,_flat_sections(blank,t),source_state['recipe'])


def export_dxf(actual, source_state, path):
    """Export the edited constant-thickness blank, with analytic cut curves.
    Linie gięcia: BEND_UP ciągła, BEND_DOWN przerywana (typ linii GIECIE_DOL), obie przycięte do konturu cięcia."""
    import os
    import tempfile
    from pathlib import Path
    from cadquery.occ_impl.exporters.dxf import DxfDocument
    model=layout(source_state['recipe']);t=float(source_state['recipe']['t'])
    pristine=not source_state.get('dirty') and not source_state.get('edited')
    if pristine and source_state.get('flat') and _unchanged(actual,model.flat):
        blank=actual
    elif pristine and not source_state.get('flat') and _unchanged(actual,model.folded):
        blank=model.flat          # nieedytowana blacha: rozwinięcie wprost z układu gięć
    else:
        blank=switch(actual,source_state,True)[0]
    pristine=pristine and blank is model.flat or (pristine and blank is actual)
    sections=_flat_sections(blank,t)
    prism=_faces_slab(sections,t)
    # Nieedytowana blacha ma z definicji stałą grubość; kosztowne porównanie brył tylko po edycjach (kieszenie, występy).
    if not pristine and _volume(blank.cut(prism))+_volume(prism.cut(blank))>max(1e-5,_volume(blank)*1e-8):
        raise k.CadError('DXF do lasera wymaga jednakowej grubości. Kieszenie, występy i zaokrąglenia zmieniające grubość pozostają w modelu 3D, ale nie mogą być zapisane jako zwykły kontur cięcia.')
    writer=DxfDocument(doc_units=4,approx=None)
    if 'GIECIE_DOL' not in writer.document.linetypes:
        writer.document.linetypes.add('GIECIE_DOL',pattern=BEND_DASH,description='Giecie w dol ----  ----')
    for name,color,ltype in [('CUT',7,'CONTINUOUS'),('BEND_UP',1,'CONTINUOUS'),('BEND_DOWN',5,'GIECIE_DOL')]:writer.add_layer(name,color=color,linetype=ltype)
    for face in sections:
        for wire in face.Wires():
            contour=wire.translate((0,0,-face.Center().z)).copy()
            writer.add_shape(cq.Workplane('XY').newObject([contour]),layer='CUT')
    writer.document.appids.add('RCCAD')
    factor=float((source_state['recipe'].get('rules') or {}).get('kfactor',s.K_DEFAULT))
    lines=_bend_lines(model,sections,source_state['recipe'])
    for bend in lines:
        line=writer.msp.add_line(tuple(bend['a']),tuple(bend['b']),dxfattribs={'layer':'BEND_'+bend['direction'],'linetype':'CONTINUOUS' if bend['direction']=='UP' else 'GIECIE_DOL'})
        line.set_xdata('RCCAD',[(1070,bend['index']),(1040,bend['angle']),(1040,bend['r']),(1040,t),(1040,factor)])
    target=Path(path);fd,tmp=tempfile.mkstemp(prefix='.rccad-edited-flat-',suffix='.dxf',dir=target.parent);os.close(fd)
    try:
        writer.document.saveas(tmp);os.replace(tmp,target)
    finally:Path(tmp).unlink(missing_ok=True)
    return dict(shape=blank,thickness=t,kfactor=factor,bends=[dict(a=l['a'],b=l['b'],direction=l['direction']) for l in lines],area=_volume(prism)/t)
