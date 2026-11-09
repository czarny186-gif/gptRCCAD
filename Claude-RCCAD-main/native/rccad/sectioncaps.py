"""GPU winding caps for a display-only section, including holes and nested shells.

A stencil pass reuses each body's existing vertex buffers. No CAD Boolean or
triangulation runs while dragging the plane. Only a four-vertex hatch plane moves.
"""
import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders
from OpenGL import GL


def section_frame(plane):
    p=np.asarray(plane,float);length=np.linalg.norm(p[:3])
    n=p[:3]/length;o=-p[3]*p[:3]/(length*length)
    axis=np.eye(3)[int(np.argmin(np.abs(n)))]
    u=np.cross(n,axis);u/=np.linalg.norm(u)
    return o,u,np.cross(n,u)


def section_quad(low,high,plane,matrix=None):
    """World-space plane patch covering the transformed body bounds, or no cut."""
    corners=np.array([[x,y,z] for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])],float)
    if matrix is not None:corners=corners@matrix[:3,:3].T+matrix[:3,3]
    distances=corners@plane[:3]+plane[3]
    if distances.min()>=-1e-7 or distances.max()<=1e-7:return None
    o,u,v=section_frame(plane);uv=np.column_stack(((corners-o)@u,(corners-o)@v))
    lo,hi=uv.min(axis=0),uv.max(axis=0)
    vertices=np.array([o+x*u+y*v for x,y in ((lo[0],lo[1]),(hi[0],lo[1]),(hi[0],hi[1]),(lo[0],hi[1]))],np.float32)
    spacing=max(np.linalg.norm(corners.max(axis=0)-corners.min(axis=0))*.025,1e-5)
    return vertices,u,v,spacing


def register_shader():
    if 'rccad-cap' in shaders.ShaderProgram.names:return
    vertex=shaders.getShaderProgram('shaded').shaders[0].code
    vertex=vertex.replace('varying vec4 v_color;','varying vec4 v_color; varying vec3 v_position;').replace('v_color = a_color;','v_color = a_color; v_position = a_position.xyz;')
    fragment='''
        #ifdef GL_ES
        #extension GL_OES_standard_derivatives : enable
        precision mediump float;
        #endif
        varying vec4 v_color;
        varying vec3 v_position;
        uniform float u_hatch[4];
        void main() {
            float t=dot(v_position,vec3(u_hatch[0],u_hatch[1],u_hatch[2]))+u_hatch[3];
            float pixel=max(fwidth(t),0.00001);
            float d=min(fract(t),1.0-fract(t));
            float line=(1.0-smoothstep(pixel*0.3,pixel*0.9,d))*(1.0-smoothstep(0.35,0.8,pixel));
            gl_FragColor=vec4(mix(v_color.rgb,v_color.rgb*0.28,line),1.0);
        }
    '''
    shaders.ShaderProgram('rccad-cap',[shaders.VertexShader(vertex),shaders.FragmentShader(fragment)])


class _HatchPlane(gl.GLMeshItem):
    def shader(self):
        shader=shaders.getShaderProgram('rccad-cap');shader['u_hatch']=self.hatch
        return shader

    def setupGLState(self):
        GL.glEnable(GL.GL_DEPTH_TEST);GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glDisable(GL.GL_BLEND);GL.glDisable(GL.GL_CULL_FACE)
        GL.glColorMask(True,True,True,True);GL.glDepthMask(True)
        GL.glEnable(GL.GL_STENCIL_TEST);GL.glStencilMask(0)
        GL.glStencilFunc(GL.GL_NOTEQUAL,0,0xff);GL.glStencilOp(GL.GL_KEEP,GL.GL_KEEP,GL.GL_KEEP)


def _stencil_state():
    GL.glDisable(GL.GL_DEPTH_TEST);GL.glDisable(GL.GL_BLEND);GL.glDisable(GL.GL_CULL_FACE)
    GL.glDisable(GL.GL_POLYGON_OFFSET_FILL);GL.glDisable(GL.GL_ALPHA_TEST);GL.glDisable(GL.GL_SAMPLE_ALPHA_TO_COVERAGE)
    GL.glColorMask(False,False,False,False);GL.glDepthMask(False)
    GL.glEnable(GL.GL_STENCIL_TEST);GL.glStencilMask(0xff);GL.glStencilFunc(GL.GL_ALWAYS,0,0xff)
    GL.glStencilOpSeparate(GL.GL_FRONT,GL.GL_KEEP,GL.GL_KEEP,GL.GL_INCR_WRAP)
    GL.glStencilOpSeparate(GL.GL_BACK,GL.GL_KEEP,GL.GL_KEEP,GL.GL_DECR_WRAP)


class SectionCaps(gl.GLGraphicsItem.GLGraphicsItem):
    def __init__(self):
        super().__init__();self.setDepthValue(9);self._planes={};self._bounds={};self.available=None
        register_shader()

    def retain_bodies(self,live):
        self._planes={bid:value for bid,value in self._planes.items() if bid in live}
        self._bounds={bid:value for bid,value in self._bounds.items() if bid in live}

    def paint(self):
        view=self.view()
        if view.section_plane is None or not view.bodies:return
        self.available=int(GL.glGetIntegerv(GL.GL_STENCIL_BITS))>0
        if not self.available:return
        enabled={k:bool(GL.glIsEnabled(k)) for k in (GL.GL_DEPTH_TEST,GL.GL_STENCIL_TEST,GL.GL_BLEND,GL.GL_CULL_FACE,GL.GL_POLYGON_OFFSET_FILL,GL.GL_ALPHA_TEST,GL.GL_SAMPLE_ALPHA_TO_COVERAGE)}
        color=GL.glGetBooleanv(GL.GL_COLOR_WRITEMASK);depth=bool(GL.glGetBooleanv(GL.GL_DEPTH_WRITEMASK))
        offset=(float(GL.glGetFloatv(GL.GL_POLYGON_OFFSET_FACTOR)),float(GL.glGetFloatv(GL.GL_POLYGON_OFFSET_UNITS)))
        depth_func=int(GL.glGetIntegerv(GL.GL_DEPTH_FUNC));clear=int(GL.glGetIntegerv(GL.GL_STENCIL_CLEAR_VALUE))
        front=[int(GL.glGetIntegerv(k)) for k in (GL.GL_STENCIL_FUNC,GL.GL_STENCIL_REF,GL.GL_STENCIL_VALUE_MASK,GL.GL_STENCIL_WRITEMASK,GL.GL_STENCIL_FAIL,GL.GL_STENCIL_PASS_DEPTH_FAIL,GL.GL_STENCIL_PASS_DEPTH_PASS)]
        back=[int(GL.glGetIntegerv(k)) for k in (GL.GL_STENCIL_BACK_FUNC,GL.GL_STENCIL_BACK_REF,GL.GL_STENCIL_BACK_VALUE_MASK,GL.GL_STENCIL_BACK_WRITEMASK,GL.GL_STENCIL_BACK_FAIL,GL.GL_STENCIL_BACK_PASS_DEPTH_FAIL,GL.GL_STENCIL_BACK_PASS_DEPTH_PASS)]
        try:
            live={b.id for b in view.bodies}
            self.retain_bodies(live)
            for index,body in enumerate(view.bodies):
                if body.kind!='solid' or not body.visible or body.mesh is None or not len(body.mesh.triangles):continue
                parts=view._parts.get(body.id);fill=parts.get('fill') if parts else None
                if fill is None or not fill.visible() or not parts.get('cap_solid'):continue
                # Mesh bounds and item matrix match the regular rendering, including live transforms.
                key=(id(body.mesh),tuple(view.section_plane),tuple(fill.transform().data()))
                cached=self._planes.get(body.id)
                if cached is None or cached[0]!=key:
                    bounds=self._bounds.get(body.id)
                    if bounds is None or bounds[0] is not body.mesh:
                        vertices=body.mesh.vertices
                        bounds=(body.mesh,vertices.min(axis=0),vertices.max(axis=0));self._bounds[body.id]=bounds
                    m=np.array(fill.transform().data(),float).reshape(4,4).T
                    result=section_quad(bounds[1],bounds[2],view.section_plane,m)
                    if result is None:continue
                    quad,u,v,spacing=result
                    if cached is None:
                        patch=_HatchPlane(vertexes=quad,faces=np.array([[0,1,2],[0,2,3]]),smooth=False,drawEdges=False,shader='rccad-cap')
                        patch._setView(view);patch.initialize()
                    else:
                        patch=cached[1];patch.setMeshData(vertexes=quad,faces=np.array([[0,1,2],[0,2,3]]))
                    self._planes[body.id]=(key,patch,u,v,spacing)
                _,patch,u,v,spacing=self._planes[body.id]
                patch.hatch=[*((u+(1 if index%2==0 else -1)*v)/spacing),0.0]
                base=parts['color'][:3];patch.opts['color']=tuple(.38+.62*float(c) for c in base)+(1.0,)
                GL.glStencilMask(0xff);GL.glClearStencil(0);GL.glClear(GL.GL_STENCIL_BUFFER_BIT)
                old=fill.__dict__.get('setupGLState');had='setupGLState' in fill.__dict__
                fill.setupGLState=_stencil_state
                view._modelViewStack.append(view.currentModelView()*fill.transform())
                try:fill.paint()
                finally:
                    view._modelViewStack.pop()
                    if had:fill.setupGLState=old
                    else:del fill.setupGLState
                patch.paint()
        finally:
            GL.glColorMask(*map(bool,color));GL.glDepthMask(depth);GL.glDepthFunc(depth_func)
            GL.glClearStencil(clear);GL.glPolygonOffset(*offset)
            for face,data in ((GL.GL_FRONT,front),(GL.GL_BACK,back)):
                GL.glStencilFuncSeparate(face,*data[:3]);GL.glStencilMaskSeparate(face,data[3]);GL.glStencilOpSeparate(face,*data[4:])
            for flag,on in enabled.items():GL.glEnable(flag) if on else GL.glDisable(flag)
