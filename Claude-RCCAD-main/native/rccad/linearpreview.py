"""Display-only linear prisms: reuse planar triangulation, never construct a CAD solid."""
import inspect
import numpy as np
import cadquery as cq
from OCP.TopAbs import TopAbs_REVERSED
from . import kernel as k
from .perfcache import LRU

_PROFILES=LRU(96*1024*1024,max_entries=2048)


def _profile(shape,tol):
    key=(id(shape),tol);cached=_PROFILES.get(key)
    if cached is not None and cached[0] is shape:return cached[1:]
    if not isinstance(shape,cq.Face) and not shape.IsClosed():return None
    face=shape if isinstance(shape,cq.Face) else cq.Face.makeFromWires(shape)
    if not k.is_planar_face(face) or not face.isValid():return None
    mesh=k.display_mesh(face,tol)
    if not len(mesh.triangles):return None
    edges=face.Edges();segments=[];vertical=[]
    for index,points in mesh.edges.items():
        edge=edges[index]
        if edge.wrapped.Orientation()==TopAbs_REVERSED:points=points[::-1]
        segments.append(np.stack((points[:-1],points[1:]),axis=1))
        if edge.geomType()=='LINE':vertical.extend((points[0],points[-1]))
    pairs=np.concatenate(segments) if segments else np.empty((0,2,3))
    data=(face,mesh,pairs,np.asarray(vertical).reshape(-1,3));_PROFILES[key]=(shape,*data)
    return data


def preview(make,tol):
    """Return a lightweight preview for a supported partial, else None for exact fallback."""
    if not hasattr(make,'func') or make.func not in (k.extrude,k.extrude_dir,k.extrude_face):return None
    args=inspect.signature(make.func).bind(*make.args,**(make.keywords or {}));args.apply_defaults();v=args.arguments
    shape=v.get('face',v.get('wire'));data=_profile(shape,tol)
    if data is None:return None
    face,mesh,pairs,vertical=data
    normal=np.asarray(v['normal'] if 'normal' in v else k.frame_of(v['plane']).normal,float).copy()
    normal/=np.linalg.norm(normal);d1=float(v.get('d1',v.get('distance',0)));d2=float(v.get('d2',0))
    shift,total=(-d1/2,d1) if v['symmetric'] else (-d2,d1+d2)
    if not np.isfinite(total) or abs(total)<1e-5:raise k.CadError('Odległość wyciągnięcia musi być różna od zera.')
    a=normal*shift;b=normal*(shift+total);count=len(mesh.vertices)
    near=mesh.triangles[:,::-1];far=mesh.triangles
    # The existing triangulation carries face orientation, including reversed planes.
    if len(far):
        tri=mesh.vertices[far[0]]
        if np.cross(tri[1]-tri[0],tri[2]-tri[0])@(normal*total)<0:near,far=far,near
    side=np.concatenate((pairs[:,0]+a,pairs[:,1]+a,pairs[:,0]+b,pairs[:,1]+b))
    n=len(pairs);i=np.arange(n,dtype=np.uint32)+2*count
    sides=np.vstack((np.stack((i,i+n,i+3*n),axis=1),np.stack((i,i+3*n,i+2*n),axis=1)))
    triangles=np.vstack((near,far+count,sides)).astype(np.uint32)
    vertices=np.vstack((mesh.vertices+a,mesh.vertices+b,side)).astype(np.float32)
    edges={j:points+a for j,points in mesh.edges.items()}
    edges.update({j+len(mesh.edges):points+b for j,points in mesh.edges.items()})
    for point in {tuple(p) for p in vertical}:edges[len(edges)]=np.array([np.asarray(point)+a,np.asarray(point)+b],np.float32)
    low=vertices.min(axis=0);high=vertices.max(axis=0)
    return k.DisplayMesh(vertices,triangles,edges,tuple((low+high)*.5),float(max(1,np.max(high-low))))
