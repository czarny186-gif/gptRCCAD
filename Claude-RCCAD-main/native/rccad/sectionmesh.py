"""Planar section material from the existing display mesh, without cutting a CAD solid.

Used as a portable cap when the viewport stencil buffer is missing or unreliable.
Triangle/plane intersection is vectorized; only the small planar contours are meshed.
"""
import numpy as np
from . import kernel as k
from .spatial import BoundsTree
from .perfcache import LRU


def section_frame(plane):
    p=np.asarray(plane,float);length=np.linalg.norm(p[:3])
    n=p[:3]/length;o=-p[3]*p[:3]/(length*length)
    axis=np.eye(3)[int(np.argmin(np.abs(n)))]
    u=np.cross(n,axis);u/=np.linalg.norm(u)
    return o,u,np.cross(n,u)

_REMOTE_MESHES=LRU(96*1024*1024,max_entries=256)


def cached_cap_mesh(token,mesh,plane,matrix=None):
    cached=_REMOTE_MESHES.get(token)
    if mesh is not None:
        cached=mesh;_REMOTE_MESHES[token]=mesh
    if cached is None:return 'missing',None
    return 'ready',cap_mesh(cached,plane,matrix)



def _inside(point,ring):
    a=ring;b=np.roll(ring,-1,axis=0);x,y=point
    keep=(a[:,1]>y)!=(b[:,1]>y)
    if not keep.any():return False
    return bool(np.count_nonzero(a[keep,0]+(y-a[keep,1])*(b[keep,0]-a[keep,0])/(b[keep,1]-a[keep,1])>x)%2)


def cap_mesh(mesh,plane,matrix=None):
    plane=np.asarray(plane,float);n=plane[:3];length=np.linalg.norm(n);plane=plane/length
    vertices=np.asarray(mesh.vertices,float)
    if matrix is not None:vertices=vertices@matrix[:3,:3].T+matrix[:3,3]
    if not len(vertices) or not len(mesh.triangles):return None
    mesh_vertices=vertices
    distances=vertices@plane[:3]+plane[3]
    epsilon=max(1e-8,float(np.ptp(vertices,axis=0).max())*1e-9)
    if distances.min()>=-epsilon or distances.max()<=epsilon:return None
    # Resolve a plane through an existing vertex/edge consistently on one side.
    distances+=epsilon*.25
    ids=np.asarray(mesh.triangles);d=distances[ids]
    ids=ids[(d.min(axis=1)<0)&(d.max(axis=1)>=0)]
    if not len(ids):return None
    a=ids[:,[0,1,2]];b=ids[:,[1,2,0]];da=distances[a];db=distances[b]
    cross=(da<0)!=(db<0)
    start=vertices[a[cross]];end=vertices[b[cross]]
    t=da[cross]/(da[cross]-db[cross]);points=start+(end-start)*t[:,None]
    # Every intersected triangle contributes exactly two endpoints.
    segments=points.reshape(-1,2,3)
    origin,u,v=section_frame(plane)
    points=segments.reshape(-1,3);uv=np.column_stack(((points-origin)@u,(points-origin)@v))
    tolerance=max(1e-7,epsilon*8)
    quantized=np.rint(uv/tolerance).astype(np.int64)
    _,first,inverse=np.unique(quantized,axis=0,return_index=True,return_inverse=True)
    coords=uv[first];pairs=inverse.reshape(-1,2);pairs=pairs[pairs[:,0]!=pairs[:,1]]
    # Eliminate duplicate unoriented segments (shared coplanar mesh boundaries).
    pairs=np.unique(np.sort(pairs,axis=1),axis=0)
    adjacent={}
    for i,(a,b) in enumerate(pairs):
        adjacent.setdefault(int(a),[]).append((int(b),i));adjacent.setdefault(int(b),[]).append((int(a),i))
    used=set();rings=[]
    for edge,(start,next_node) in enumerate(pairs):
        if edge in used:continue
        used.add(edge);path=[int(start)];current=int(next_node)
        while current!=path[0]:
            path.append(current)
            options=[(q,e) for q,e in adjacent.get(current,()) if e not in used]
            if not options:break
            current,chosen=options[0];used.add(chosen)
        if current!=path[0] or len(path)<3:continue
        ring=coords[path]
        previous=ring-np.roll(ring,1,axis=0);following=np.roll(ring,-1,axis=0)-ring
        turn=np.abs(previous[:,0]*following[:,1]-previous[:,1]*following[:,0])
        keep=turn>tolerance*np.maximum(np.linalg.norm(previous,axis=1)+np.linalg.norm(following,axis=1),1e-6)
        ring=ring[keep]
        if len(ring)>=3:rings.append(ring)
    if not rings:return None
    lows=np.array([r.min(axis=0) for r in rings]);highs=np.array([r.max(axis=0) for r in rings])
    tree=BoundsTree(np.column_stack((lows,np.zeros(len(rings)))),np.column_stack((highs,np.zeros(len(rings)))))
    areas=np.array([abs(np.sum(r[:,0]*np.roll(r[:,1],-1)-r[:,1]*np.roll(r[:,0],-1))*.5) for r in rings])
    parents=[]
    for i,ring in enumerate(rings):
        candidates=[j for j in tree.point([*ring[0],0],tolerance) if areas[j]>areas[i]+tolerance*tolerance and _inside(ring[0],rings[j])]
        parents.append(min(candidates,key=lambda j:areas[j]) if candidates else None)
    depths=[]
    for i in range(len(rings)):
        depth=0;parent=parents[i]
        while parent is not None:depth+=1;parent=parents[parent]
        depths.append(depth)
    # VTK is already shipped with CadQuery. Triangulate the planar contours in
    # native code instead of constructing thousands of temporary CAD edges.
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkPolyData,vtkCellArray
    from vtkmodules.vtkFiltersGeneral import vtkContourTriangulator
    from vtkmodules.util.numpy_support import numpy_to_vtk,numpy_to_vtkIdTypeArray,vtk_to_numpy
    oriented=[]
    for ring,depth in zip(rings,depths):
        signed=np.sum(ring[:,0]*np.roll(ring[:,1],-1)-ring[:,1]*np.roll(ring[:,0],-1))
        oriented.append(ring[::-1] if (signed>0)!=(depth%2==0) else ring)
    uv=np.concatenate(oriented);points=vtkPoints();points.SetData(numpy_to_vtk(np.column_stack((uv,np.zeros(len(uv)))),deep=True))
    cells=[];offset=0;edges={}
    for index,ring in enumerate(oriented):
        count=len(ring);cells.extend([count+1,*range(offset,offset+count),offset]);offset+=count
        world=origin+ring[:,0,None]*u+ring[:,1,None]*v
        edges[index]=np.vstack((world,world[:1])).astype(np.float32)
    lines=vtkCellArray();lines.SetCells(len(oriented),numpy_to_vtkIdTypeArray(np.asarray(cells,dtype=np.int64),deep=True))
    data=vtkPolyData();data.SetPoints(points);data.SetLines(lines)
    triangulator=vtkContourTriangulator();triangulator.SetInputData(data);triangulator.Update()
    result=triangulator.GetOutput()
    if not result.GetNumberOfPolys():return None
    cells=vtk_to_numpy(result.GetPolys().GetData()).reshape(-1,4)
    if not np.all(cells[:,0]==3):raise ValueError('Section contours did not produce triangles')
    p=vtk_to_numpy(result.GetPoints().GetData())
    vertices=(origin+p[:,0,None]*u+p[:,1,None]*v).astype(np.float32)
    low,high=vertices.min(axis=0),vertices.max(axis=0)
    mesh=k.DisplayMesh(vertices,cells[:,1:].astype(np.uint32),edges,tuple((low+high)*.5),float(max(1,np.max(high-low))))
    spacing=max(float(np.linalg.norm(np.ptp(np.asarray(mesh_vertices),axis=0)))*.025,1e-5)
    mesh.hatches=tuple(_hatch_lines(oriented,origin,u,v,spacing,sign) for sign in (1,-1))
    return mesh


def _hatch_lines(rings,origin,u,v,spacing,sign):
    a=np.concatenate(rings);b=np.concatenate([np.roll(r,-1,axis=0) for r in rings])
    normal=np.array([1.,float(sign)])/np.sqrt(2);direction=np.array([1.,-float(sign)])/np.sqrt(2)
    ta=a@normal;tb=b@normal;lines=[]
    for level in np.arange(np.floor(min(ta.min(),tb.min())/spacing),np.ceil(max(ta.max(),tb.max())/spacing))+.5:
        value=level*spacing;cross=((ta<=value)&(tb>value))|((tb<=value)&(ta>value))
        if not cross.any():continue
        aa=a[cross];bb=b[cross];t=(value-ta[cross])/(tb[cross]-ta[cross])
        hits=aa+(bb-aa)*t[:,None];hits=hits[np.argsort(hits@direction)]
        if len(hits)%2:continue
        pairs=hits.reshape(-1,2,2);pairs=pairs[np.linalg.norm(pairs[:,1]-pairs[:,0],axis=1)>1e-7]
        if len(pairs):lines.append(origin+pairs[:,:,0,None]*u+pairs[:,:,1,None]*v)
    return np.concatenate(lines).reshape(-1,3).astype(np.float32) if lines else np.empty((0,3),np.float32)
