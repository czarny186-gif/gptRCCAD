"""Section material as ordinary scene objects: no stencil queries or manual render passes."""
import uuid
import weakref
import numpy as np
import pyqtgraph.opengl as gl
from OpenGL import GL
from PySide6.QtCore import QObject,Signal,QRunnable,QThreadPool,QTimer
from .perfcache import LRU
from .sectionmesh import section_frame


def section_quad(low,high,plane,matrix=None):
    corners=np.array([[x,y,z] for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])],float)
    if matrix is not None:corners=corners@matrix[:3,:3].T+matrix[:3,3]
    distances=corners@plane[:3]+plane[3]
    if distances.min()>=-1e-7 or distances.max()<=1e-7:return None
    o,u,v=section_frame(plane);uv=np.column_stack(((corners-o)@u,(corners-o)@v));lo,hi=uv.min(axis=0),uv.max(axis=0)
    quad=np.array([o+x*u+y*v for x,y in ((lo[0],lo[1]),(hi[0],lo[1]),(hi[0],hi[1]),(lo[0],hi[1]))],np.float32)
    return quad,u,v,max(np.linalg.norm(corners.max(axis=0)-corners.min(axis=0))*.025,1e-5)


class _MaterialSurface(gl.GLMeshItem):
    def paint(self):
        GL.glEnable(GL.GL_POLYGON_OFFSET_FILL);GL.glPolygonOffset(1,1)
        try:super().paint()
        finally:GL.glDisable(GL.GL_POLYGON_OFFSET_FILL);GL.glDepthFunc(GL.GL_LESS)


class _MaterialLines(gl.GLLinePlotItem):
    def paint(self):
        try:super().paint()
        finally:GL.glDepthFunc(GL.GL_LESS)


class _CapSignals(QObject):
    done=Signal(object)


class _CapWork(QRunnable):
    def __init__(self,requests):
        super().__init__();self.requests=requests;self.signals=_CapSignals()
    def run(self):
        from .sectionmesh import cap_mesh,cached_cap_mesh
        from . import workers
        results=[]
        for bid,key,mesh,plane,matrix,token in self.requests:
            error=None
            try:
                if workers.ready():
                    try:
                        answer=workers.call_affine(('section-material',bid),cached_cap_mesh,token,None,plane,matrix)
                        if answer[0]=='missing':answer=workers.call_affine(('section-material',bid),cached_cap_mesh,token,mesh,plane,matrix)
                        value=answer[1]
                    except workers.Unavailable:value=cap_mesh(mesh,plane,matrix)
                else:value=cap_mesh(mesh,plane,matrix)
            except Exception as exc:
                value=None;error=str(exc)
            results.append((bid,key,mesh,value,error))
        self.signals.done.emit(results)


class SectionCaps(gl.GLGraphicsItem.GLGraphicsItem):
    def __init__(self):
        super().__init__();self.setDepthValue(9);self.available=True
        self._planes={};self._bounds={};self._solid_patches={};self._pending={};self._running=False
        self._mesh_tokens=LRU(max_entries=2048);self._material=LRU(96*1024*1024,max_entries=256)
        self.last_error=None
        self._cap_pool=QThreadPool(self);self._cap_pool.setMaxThreadCount(1)
        self._cap_timer=QTimer(self);self._cap_timer.setSingleShot(True);self._cap_timer.setInterval(25)
        self._cap_timer.timeout.connect(self._start_caps)

    def _remove_patch(self,bid):
        old=self._solid_patches.pop(bid,None)
        if old:
            for item in old[1:]:item.setParentItem(None)

    def retain_bodies(self,live):
        self._planes={bid:value for bid,value in self._planes.items() if bid in live}
        self._bounds={bid:value for bid,value in self._bounds.items() if bid in live}
        for bid in list(self._solid_patches):
            if bid not in live:self._remove_patch(bid)
        self._pending={bid:value for bid,value in self._pending.items() if bid in live}

    def _request_cap(self,body,key,matrix):
        cached=self._material.get(key)
        if cached is not None and cached[0] is body.mesh:return cached
        token=self._mesh_tokens.get(id(body.mesh))
        if token is None or token[0]() is not body.mesh:
            token=(weakref.ref(body.mesh),uuid.uuid4().hex);self._mesh_tokens[id(body.mesh)]=token
        self._pending[body.id]=(body.id,key,body.mesh,np.array(self.view().section_plane,float),matrix,token[1])
        if not self._running and not self._cap_timer.isActive():self._cap_timer.start()
        return None

    def _start_caps(self):
        if self._running or not self._pending:return
        view=self.view()
        if view is None or view.section_plane is None:self._pending.clear();return
        requests=list(self._pending.values());self._pending.clear();self._running=True
        work=self._cap_work=_CapWork(requests);work.signals.done.connect(self._caps_ready);self._cap_pool.start(work)

    def _caps_ready(self,results):
        self._running=False
        for bid,key,source,mesh,error in results:
            if bid in self._pending and self._pending[bid][1]==key:self._pending.pop(bid,None)
            if error:self.last_error=error
            self._material[key]=(source,mesh)
        self.update_section()
        if self._pending:self._cap_timer.start()

    def update_section(self):
        view=self.view()
        if view is None:return
        active=set();live={b.id for b in view.bodies};self.retain_bodies(live)
        if view.section_plane is not None:
            for index,body in enumerate(view.bodies):
                parts=view._parts.get(body.id);fill=parts.get('fill') if parts else None
                if not body.visible or body.mesh is None or fill is None or not parts.get('cap_solid'):continue
                bounds=self._bounds.get(body.id)
                if bounds is None or bounds[0] is not body.mesh:
                    vertices=body.mesh.vertices
                    if not len(vertices):continue
                    bounds=(body.mesh,vertices.min(axis=0),vertices.max(axis=0));self._bounds[body.id]=bounds
                matrix=np.array(fill.transform().data(),float).reshape(4,4).T
                key=(id(body.mesh),tuple(view.section_plane),tuple(matrix.ravel()),index%2)
                if section_quad(bounds[1],bounds[2],view.section_plane,matrix) is None:continue
                active.add(body.id);old=self._solid_patches.get(body.id)
                if old is not None and old[0]==key:
                    for item in old[1:]:item.setVisible(True)
                    continue
                if old is not None:
                    for item in old[1:]:item.setVisible(False)
                cached=self._request_cap(body,key,matrix)
                if cached is None or cached[1] is None:continue
                mesh=cached[1];self._remove_patch(body.id)
                opts={GL.GL_DEPTH_TEST:True,GL.GL_BLEND:False,GL.GL_CULL_FACE:False,'glDepthFunc':(GL.GL_LEQUAL,)}
                surface=_MaterialSurface(parentItem=self,vertexes=mesh.vertices,faces=mesh.triangles,smooth=False,drawEdges=False,shader=None,color=(.96,.75,.91,1))
                surface.setGLOptions(opts)
                lines=_MaterialLines(parentItem=self,pos=mesh.hatches[index%2],color=(.15,.12,.15,1),width=1,antialias=True,mode='lines')
                lines.setGLOptions(opts);lines.setDepthValue(1)
                self._solid_patches[body.id]=(key,surface,lines)
        for bid,patch in self._solid_patches.items():
            if bid not in active:
                for item in patch[1:]:item.setVisible(False)
        if view.section_plane is None:self._pending.clear();self._cap_timer.stop()
        view.update()

    def paint(self):
        # Geometry is drawn by GLViewWidget's normal scene traversal, which
        # supplies the correct context/VAO/state for each child object.
        pass
