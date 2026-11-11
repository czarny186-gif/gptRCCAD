"""Native Qt/OpenGL viewport with picking against displayed CAD edge curves."""
from __future__ import annotations
import math
import time
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders
from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QCoreApplication
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QVector3D, QVector4D, QColor
from OpenGL import GL
from PySide6.QtGui import QMatrix4x4, QSurfaceFormat
from .document import Body
from . import kernel
from .sectionview import clip_segments
from .sectioncaps import SectionCaps
from .perfcache import LRU
from .spatial import BoundsTree


# pyqtgraph caches shader programs globally; their GL share group must outlive
# individual model/drawing windows. Main also enables this before QApplication.
if QCoreApplication.instance() is None:
    _format=QSurfaceFormat.defaultFormat();_format.setStencilBufferSize(8);QSurfaceFormat.setDefaultFormat(_format)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)


class GradientBackground(gl.GLGraphicsItem.GLGraphicsItem):
    """Pionowy gradient tła (jak w wersji HTML), rysowany jako pierwszy, bez głębi."""

    def __init__(self, top, bottom):
        super().__init__()
        self.top, self.bottom = top, bottom
        self.setDepthValue(-1000)

    def paint(self):
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPushMatrix()
        GL.glLoadIdentity()
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glPushMatrix()
        GL.glLoadIdentity()
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glBegin(GL.GL_QUADS)
        GL.glColor3f(*self.top)
        GL.glVertex2f(-1, 1)
        GL.glVertex2f(1, 1)
        GL.glColor3f(*self.bottom)
        GL.glVertex2f(1, -1)
        GL.glVertex2f(-1, -1)
        GL.glEnd()
        GL.glDepthMask(GL.GL_TRUE)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPopMatrix()
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glPopMatrix()

# Wygląd jak w wersji HTML: jasne tło, niebieska siatka, jasnoszare bryły z czarnym obrysem.
BACKGROUND = '#edf2f8'
GRID_COLOR = '#9fb6cf'
BG_TOP = (0.985, 0.992, 1.0)
BG_BOTTOM = (0.875, 0.915, 0.96)
SOLID_COLOR = (.62, .68, .76, 1)
SOLID_SELECTED = (.40, .60, .90, 1)
EDGE_COLOR = (.10, .13, .18, 1)
SKETCH_COLOR = (.03, .20, .52, 1)
PREVIEW_COLOR = (1, .48, .05, 1)
PICKED_COLOR = (.16, .43, .90, 1)         # zaznaczony obiekt: ciepły niebieski obrys
PICKED_FILL = (.53, .69, .93, 1)           # i spokojne, ciepłe niebieskie wypełnienie (nie razi oczu)
PLANE_COLORS = {'XY': '#4a8fe0', 'XZ': '#3aa77a', 'YZ': '#df5a5e'}
PLANE_SIZES = (2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128)
PLANE_HALF = 14.0
GRID_LEVELS = (.01, .02, .05, .1, .2, .5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
GRID_PX = 8           # najmniejszy odstęp cienkich linii siatki (px) - tak samo przyciąga kursor (snap.GRID_PX)
VIEWS = {  # (elewacja, azymut) kamery pyqtgraph
    'iso': (25, -55), 'XY': (90, -90), 'XZ': (0, -90), 'YZ': (0, 0),
    'Z': (90, -90), '-Z': (-90, -90), 'X': (0, 0), '-X': (0, 180), 'Y': (0, 90), '-Y': (0, -90),
}



def camera_for_normal(n):
    """Elewacja i azymut kamery patrzącej z kierunku `n` z „górą do góry” (bez przekręcenia obrazu)."""
    n = np.asarray(n, float)
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, float(n[2])))))
    if math.hypot(n[0], n[1]) < 1e-6:
        azimuth = -90.0                       # widok z góry / z dołu: X w prawo, Y w górę - jak ściana GÓRA kostki
    else:
        azimuth = math.degrees(math.atan2(n[1], n[0]))
    return dict(elevation=elevation, azimuth=azimuth)


class Overlay2D(QWidget):
    """Przezroczysta warstwa 2D nad widokiem 3D (jak <canvas> w wersji HTML): strzałki i uchwyty są ZAWSZE na wierzchu,
    nigdy nie chowają się za bryłą. Rysuje też środki szkiców i znacznik przyciągania."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)

    @staticmethod
    def _qc(color, alpha=None):
        c = QColor.fromRgbF(*[min(1.0, max(0.0, float(x))) for x in color[:4]]) if len(color) >= 3 else QColor('#f09a22')
        if len(color) < 4:
            c.setAlphaF(1.0)
        if alpha is not None:
            c.setAlpha(alpha)
        return c

    def paintEvent(self, event):
        v = self.view
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        try:
            if v.sketch_centers:
                key=(v._camera_key(),id(v.sketch_centers));cached=getattr(v,'_centers_overlay_cache',None)
                if cached is None or cached[0]!=key:
                    xy,_,w=v.project_points(np.asarray(v.sketch_centers,float))
                    keep=(w>0)&np.isfinite(xy).all(axis=1)&(xy[:,0]>=-12)&(xy[:,0]<=v.width()+12)&(xy[:,1]>=-12)&(xy[:,1]<=v.height()+12)
                    path=QPainterPath()
                    for x,y in xy[keep]:
                        path.addEllipse(QRectF(x-4.5,y-4.5,9,9))
                        path.moveTo(x-9,y);path.lineTo(x+9,y);path.moveTo(x,y-9);path.lineTo(x,y+9)
                    cached=(key,v.sketch_centers,path);v._centers_overlay_cache=cached
                p.setPen(QPen(QColor('#087d55'),1.6));p.setBrush(QColor('#ffffff'));p.drawPath(cached[2])
            box = v.sketch_box
            if box:
                pts = [v.project_one(c) for c in box['corners']]
                if all(q is not None for q in pts):
                    blue = QColor('#2f87e8')
                    p.setPen(QPen(blue, 1.6, Qt.DashLine))
                    p.setBrush(QColor(47, 135, 232, 24))
                    p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))
                    corner, rot = v.project_one(box['corners'][2]), v.project_one(box['rotate'])
                    if corner is not None and rot is not None:
                        p.setPen(QPen(QColor('#e5262b'), 1.6))
                        p.drawLine(QPointF(*corner), QPointF(*rot))
                    sc, mv = v.project_one(box['scale']), v.project_one(box['move'])
                    if mv is not None:
                        p.setPen(QPen(blue, 1.8))
                        p.drawLine(QPointF(mv[0] - 6, mv[1]), QPointF(mv[0] + 6, mv[1]))
                        p.drawLine(QPointF(mv[0], mv[1] - 6), QPointF(mv[0], mv[1] + 6))
                    if sc is not None:
                        p.setPen(QPen(blue, 2))
                        p.setBrush(QColor('#ffffff'))
                        p.drawRect(QRectF(sc[0] - 7, sc[1] - 7, 14, 14))
                        p.drawLine(QPointF(sc[0] - 3.5, sc[1] + 3.5), QPointF(sc[0] + 3.5, sc[1] - 3.5))
                    if rot is not None:
                        p.setPen(QPen(QColor('#ffffff'), 2))
                        p.setBrush(QColor('#e5262b'))
                        p.drawEllipse(QPointF(*rot), 8, 8)
            if v.hover_vertex is not None or v.sel_vertices:
                p.setRenderHint(QPainter.Antialiasing)
                for pt, chosen in [*((q, True) for q in v.sel_vertices), *(((v.hover_vertex, False),) if v.hover_vertex is not None else ())]:
                    xy = v.project_one(pt)
                    if xy is None:
                        continue
                    p.setPen(QPen(QColor('#ffffff'), 2))
                    p.setBrush(QColor('#f09a22') if chosen else QColor(240, 154, 34, 120))
                    p.drawEllipse(QPointF(*xy), 7.5 if chosen else 9, 7.5 if chosen else 9)
            for g in v.sketch_grips:
                xy = v.project_one(g)
                if xy is None:
                    continue
                p.setPen(QPen(QColor('#2f87e8'), 1.8))
                p.setBrush(QColor('#ffffff'))
                p.drawRect(QRectF(xy[0] - 4.5, xy[1] - 4.5, 9, 9))
            if v.measure_live is not None:
                a,b=(v.project_one(q) for q in v.measure_live)
                if a is not None and b is not None:
                    p.setPen(QPen(QColor('#e58a16'),1.5,Qt.DashLine));p.drawLine(QPointF(*a),QPointF(*b))
            for q,label in v.measure_labels:
                if not v.section_contains(q):continue
                xy=v.project_one(q)
                if xy is None:continue
                p.setPen(QPen(QColor('#1664b1'),1.4));p.setBrush(QColor('white'))
                rect=QRectF(xy[0]+8,xy[1]-25,21,21);p.drawEllipse(rect)
                p.drawText(rect,Qt.AlignCenter,label)
            order = {'plane': 0, 'ring': 1, 'axis': 2, 'arrow': 3}
            for h in sorted(v.all_handles(), key=lambda h: order.get(h.get('kind', 'arrow'), 3)):
                hot = v.hover_handle == h['id'] or (v._handle_drag is not None and v._handle_drag['id'] == h['id'])
                getattr(self, '_draw_' + h.get('kind', 'arrow'))(p, v, h, hot)
            snap = v.snap_marker
            if snap is not None:
                xy, text = snap
                p.setPen(QPen(QColor('#e06c12'), 2))
                p.setBrush(QColor('#ffffff'))
                p.drawEllipse(QPointF(*xy), 5.5, 5.5)
                if text:
                    font = QFont('Segoe UI')
                    font.setPixelSize(12)
                    p.setFont(font)
                    p.setPen(QColor('#9a4b0b'))
                    p.drawText(QPointF(xy[0] + 10, xy[1] - 10), text)
        finally:
            p.end()

    def _draw_plane(self, p, v, h, hot):
        pts = [v.project_one(q) for q in h['quad']]
        if any(q is None for q in pts):
            return
        poly = QPolygonF([QPointF(*q) for q in pts])
        p.setBrush(self._qc(h['color'], 170 if hot else 95))
        p.setPen(QPen(self._qc(h['color'], 235), 2))
        p.drawPolygon(poly)

    def _draw_ring(self, p, v, h, hot):
        c, axis, radius = (np.asarray(h['ring'][0], float), np.asarray(h['ring'][1], float), float(h['ring'][2]))
        e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        pts = np.array([c + radius * (np.cos(a) * e1 + np.sin(a) * e2) for a in np.linspace(0, 2 * np.pi, 97)])
        xy, _, w = v.project_points(pts)
        if not np.isfinite(xy).all():
            return
        poly = QPolygonF([QPointF(float(a), float(b)) for a, b in xy])
        halo = QPen(QColor(255, 255, 255, 190), 8.5 if hot else 7)
        halo.setCapStyle(Qt.RoundCap)
        p.setBrush(Qt.NoBrush)
        p.setPen(halo)
        p.drawPolyline(poly)
        pen = QPen(self._qc(h['color'], 255 if hot else 225), 5.5 if hot else 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPolyline(poly)
        tip = v.project_one(h['tip'])
        if tip is not None:
            self._badge(p, tip, h['color'], h.get('label'), 10 + (2 if hot else 0))

    def _badge(self, p, xy, color, label, r):
        p.setPen(QPen(QColor('#ffffff'), 2.4))
        p.setBrush(self._qc(color))
        p.drawEllipse(QPointF(*xy), r, r)
        if label:
            font = QFont('Segoe UI')
            font.setBold(True)
            font.setPixelSize(12)
            p.setFont(font)
            p.setPen(QColor('#ffffff'))
            p.drawText(QRectF(xy[0] - r, xy[1] - r, 2 * r, 2 * r), Qt.AlignCenter, label)

    def _draw_axis(self, p, v, h, hot, big=False):
        geo = v.handle_geometry(h)
        if geo is None:
            return
        s, e = geo['start'], geo['end']
        dx, dy = e[0] - s[0], e[1] - s[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        head = (24 if big else 17) + (3 if hot else 0)
        base = (e[0] - ux * head * .7, e[1] - uy * head * .7)
        halo = QPen(QColor(255, 255, 255, 200), 10.5 if big else 8.5)
        halo.setCapStyle(Qt.RoundCap)
        p.setPen(halo)
        p.drawLine(QPointF(*s), QPointF(*base))
        pen = QPen(self._qc(h['color']), (6 if big else 4.6) + (1.4 if hot else 0))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(*s), QPointF(*base))
        tri = QPolygonF([QPointF(*e), QPointF(e[0] - ux * head + -uy * head * .5, e[1] - uy * head + ux * head * .5),
                         QPointF(e[0] - ux * head - -uy * head * .5, e[1] - uy * head - ux * head * .5)])
        p.setPen(QPen(QColor('#ffffff'), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(self._qc(h['color']))
        p.drawPolygon(tri)
        if h.get('label'):
            font = QFont('Segoe UI')
            font.setBold(True)
            font.setPixelSize(13)
            p.setFont(font)
            p.setPen(self._qc(h['color']).darker(125))
            p.drawText(QPointF(e[0] + ux * 12 - 4, e[1] + uy * 12 + 5), h['label'])

    def _draw_arrow(self, p, v, h, hot):
        return self._draw_axis(p, v, dict(h, label=h.get('label') if h.get('label') not in ('+', '-') else None), hot, big=True)

    def _draw_arrow_old(self, p, v, h, hot):
        geo = v.handle_geometry(h)
        if geo is None:
            return
        s, e = geo['start'], geo['end']
        halo = QPen(QColor(255, 255, 255, 215), 9)
        halo.setCapStyle(Qt.RoundCap)
        p.setPen(halo)
        p.drawLine(QPointF(*s), QPointF(*e))
        pen = QPen(self._qc(h['color']), 5.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(*s), QPointF(*e))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QPointF(e[0] + 1, e[1] + 3), 14, 14)
        self._badge(p, e, h['color'], h.get('label'), 13 if hot else 11.5)


class SectionMesh(gl.GLMeshItem):
    """Clip fragments in the shader: moving a section never rebuilds CAD or mesh buffers."""
    def paint(self):
        view=getattr(self,'section_view',None);bid=getattr(self,'section_body_id',None)
        if bid is not None and view is not None and bid not in view._visible_body_ids():return
        super().paint()

    def shader(self):
        view=getattr(self,'section_view',None)
        plane=view.item_section(self) if view is not None else None
        if plane is None:return super().shader()
        shader=shaders.getShaderProgram('rccad-section')
        shader['u_cut']=plane
        return shader


class SectionLine(gl.GLLinePlotItem):
    """Clip line fragments on the GPU; preserve VBOs throughout section dragging."""
    _cut_programs={}

    def getShaderProgram(self):
        view=getattr(self,'section_view',None)
        plane=view.item_section(self) if view is not None and not getattr(self,'section_ignore',False) else None
        if plane is None:return super().getShaderProgram()
        import importlib
        from OpenGL.GL import shaders as compiler
        from PySide6.QtGui import QOpenGLContext
        module=importlib.import_module('pyqtgraph.opengl.items.GLLinePlotItem')
        ctx=QOpenGLContext.currentContext();es=ctx.isOpenGLES();version=ctx.format().version()
        core=version>=(3,0) if es else version>=(3,1)
        prefix=('#version 300 es\n' if es else '#version 140\n') if core else ''
        key=(es,core);program=self._cut_programs.get(key)
        if program is None:
            sources=module.SHADER_CORE if core else module.SHADER_LEGACY
            vertex=sources[GL.GL_VERTEX_SHADER];fragment=sources[GL.GL_FRAGMENT_SHADER]
            vertex=vertex.replace('void main()',('out' if core else 'varying')+' float v_cut; uniform vec4 u_cut; void main()')
            vertex=vertex.replace('v_color = a_color;','v_color = a_color; v_cut = dot(a_position,u_cut);')
            fragment=fragment.replace('void main()',('in' if core else 'varying')+' float v_cut; void main()')
            fragment=fragment.replace('void main() {','void main() { if(v_cut < -0.00001) discard;')
            program=compiler.compileProgram(compiler.compileShader(prefix+vertex,GL.GL_VERTEX_SHADER),compiler.compileShader(prefix+fragment,GL.GL_FRAGMENT_SHADER))
            GL.glBindAttribLocation(program,0,'a_position');GL.glBindAttribLocation(program,1,'a_color');GL.glLinkProgram(program)
            self._cut_programs[key]=program
        with program:GL.glUniform4fv(GL.glGetUniformLocation(program,'u_cut'),1,np.asarray(plane,np.float32))
        return program

    def paint(self):
        view=getattr(self,'section_view',None);bid=getattr(self,'section_body_id',None)
        if bid is not None and view is not None and bid not in view._visible_body_ids():return
        super().paint()


class OverMesh(SectionMesh):
    """Półprzezroczysta nakładka na ścianę: przesunięta ku kamerze, więc nie ginie w z-fightingu z bryłą."""

    def paint(self):
        GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
        GL.glPolygonOffset(-2.0, -2.0)
        try:
            super().paint()
        finally:
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)


class OffsetMesh(SectionMesh):
    """Siatka z przesunięciem wielokątów w głąb: krawędzie leżą czysto na ścianach, a ukryte części są naprawdę zasłonięte."""

    def paint(self):
        GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
        GL.glPolygonOffset(2.0, 2.0)
        try:
            super().paint()
        finally:
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)


class OverLine(SectionLine):
    """Linie szkicu: rysowane zawsze po bryłach (wyższa wartość depth), więc przebudowa bryły (zmiana zaznaczenia, koloru) nie zakrywa szkicu na jej ścianie."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDepthValue(10)
        # jawne opcje GL: bez testu głębokości i ze zwykłym mieszaniem (nie addytywnym) - kolor linii zawsze taki sam, niezależnie od tła i ściany pod spodem
        self.setGLOptions({GL.GL_DEPTH_TEST: False, GL.GL_BLEND: True, GL.GL_ALPHA_TEST: False, GL.GL_CULL_FACE: False,
                           'glBlendFunc': (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)})


_MESHDATA = LRU(192*1024*1024)


def _meshdata(mesh):
    """Dane siatki dla karty graficznej z kierunkami do cieniowania liczonymi tablicami (pyqtgraph liczy je w pętli Pythona,
    punkt po punkcie - przy dużej bryle to setki milisekund przy każdym pokazaniu). Wynik jest zapamiętany dla siatki."""
    hit = _MESHDATA.get(id(mesh))
    if hit is not None and hit[0] is mesh:
        return hit[1]
    v = np.asarray(mesh.vertices, dtype=np.float32)
    f = np.asarray(mesh.triangles, dtype=np.uint32)
    md = gl.MeshData(vertexes=v, faces=f)
    if len(f):
        a = v[f[:, 0]].astype(np.float64)
        n = np.cross(v[f[:, 1]] - a, v[f[:, 2]] - a)            # waga = pole trójkąta, jak w pyqtgraph
        normals = np.empty((len(v), 3))
        flat = f.ravel()
        for c in range(3):
            normals[:, c] = np.bincount(flat, weights=np.repeat(n[:, c], 3), minlength=len(v))
        length = np.linalg.norm(normals, axis=1)
        normals /= np.where(length > 1e-20, length, 1.0)[:, None]
        md._vertexNormals = normals.astype(np.float32)
    _MESHDATA[id(mesh)] = (mesh, md)
    return md


_PICK = LRU(256*1024*1024)
PICK_CHUNK = 1024


def _pick_data(mesh):
    """Przygotowane dla wskazywania myszą: trójkąty w blokach z prostopadłościanami ograniczającymi (promień sprawdza
    najpierw bloki, potem tylko trójkąty w trafionych blokach), wszystkie odcinki krawędzi i końce krawędzi naraz."""
    hit = _PICK.get(id(mesh))
    if hit is not None and hit[0] is mesh:
        return hit[1]
    data = {}
    if len(mesh.triangles):
        tri = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.triangles)]
        v0, e1, e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        starts = np.arange(0, len(tri), PICK_CHUNK)
        low = np.minimum.reduceat(tri.min(axis=1), starts)
        high = np.maximum.reduceat(tri.max(axis=1), starts)
        data.update(v0=v0, e1=e1, e2=e2, starts=starts, low=low, high=high, box=(tri.min(axis=(0, 1)), tri.max(axis=(0, 1))))
    chains = [(index, np.asarray(points, dtype=np.float64)) for index, points in mesh.edges.items() if len(points) >= 2]
    if chains:
        data['a'] = np.concatenate([p[:-1] for _, p in chains])
        data['b'] = np.concatenate([p[1:] for _, p in chains])
        data['edge'] = np.concatenate([np.full(len(p) - 1, index) for index, p in chains])
    ends = {}
    for points in mesh.edges.values():
        for q in (points[0], points[-1]):
            ends[tuple(np.round(q, 3))] = q
    data['ends'] = np.array(list(ends.values()), dtype=float) if ends else None
    _PICK[id(mesh)] = (mesh, data)
    return data


def _ray_box(origin, inv, low, high):
    """Które prostopadłościany (low/high: N x 3) przecina półprosta: test płyt, naraz dla wszystkich."""
    t1, t2 = (low - origin) * inv, (high - origin) * inv
    near = np.nanmax(np.minimum(t1, t2), axis=-1)
    far = np.nanmin(np.maximum(t1, t2), axis=-1)
    return (far >= np.maximum(near, 0.0) - 1e-6)


def _ray_triangles(data, origin, direction, cut=None):
    """(t, indeks trójkąta) najbliższego trafienia albo None - tylko trójkąty z bloków, które promień przecina."""
    if 'v0' not in data:
        return None
    with np.errstate(divide='ignore', invalid='ignore'):
        inv = 1.0 / direction
        if not _ray_box(origin, inv, data['box'][0][None], data['box'][1][None])[0]:
            return None
        chunks = np.nonzero(_ray_box(origin, inv, data['low'], data['high']))[0]
    if not len(chunks):
        return None
    n = len(data['v0'])
    index = np.concatenate([np.arange(data['starts'][c], min(data['starts'][c] + PICK_CHUNK, n)) for c in chunks])
    v0, e1, e2 = data['v0'][index], data['e1'][index], data['e2'][index]
    h = np.cross(np.broadcast_to(direction, e2.shape), e2)
    a = np.einsum('ij,ij->i', e1, h)
    f = np.divide(1., a, out=np.zeros_like(a), where=np.abs(a) > 1e-9)
    sv = origin - v0
    u = f * np.einsum('ij,ij->i', sv, h)
    q = np.cross(sv, e1)
    v = f * np.einsum('j,ij->i', direction, q)
    t = f * np.einsum('ij,ij->i', e2, q)
    ok = (np.abs(a) > 1e-9) & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 1e-6)
    if cut is not None:
        points=origin+t[:,None]*direction
        ok &= points @ cut[:3]+cut[3]>=-1e-5
    if not ok.any():
        return None
    j = np.nonzero(ok)[0][int(np.argmin(t[ok]))]
    return float(t[j]), int(index[j])


def _segments(chains):
    """Wiele łamanych -> jedna tablica odcinków (tryb 'lines'): jedno wywołanie rysowania zamiast setek (płynny obrót modelu z tekstem)."""
    parts = []
    for pts in chains:
        pts = np.asarray(pts, dtype=np.float32)
        if len(pts) < 2:
            continue
        seg = np.empty((2 * (len(pts) - 1), 3), dtype=np.float32)
        seg[0::2], seg[1::2] = pts[:-1], pts[1:]
        parts.append(seg)
    return np.concatenate(parts) if parts else None


PAN_STEP = 40.0      # px na jedno naciśnięcie strzałki


def pan_arrow(view, event):
    """Strzałka bez modyfikatorów (poza blokiem numerycznym i Shift) przesuwa widok w jej kierunku. Zwraca, czy obsłużono."""
    moves = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
    move = moves.get(event.key())
    if move is None or event.modifiers() & ~(Qt.KeypadModifier | Qt.ShiftModifier):
        return False
    step = PAN_STEP * (4 if event.modifiers() & Qt.ShiftModifier else 1)
    view.pan_step(move[0] * step, move[1] * step)
    return True


class CadView(gl.GLViewWidget):
    edgeClicked = Signal(str, int, bool, bool)  # bryła, krawędź, dodaj do zaznaczenia, cały łańcuch styczny
    planeClicked = Signal(str)
    sketchDrawn = Signal(str, str, float, float, float, float)
    sketchInfo = Signal(str)
    # tryb "studio" (jak HTML): klik-klik na płaszczyźnie szkicu i ogólne kliknięcia / ruch kursora
    sketchMoved = Signal(object, float, float)
    sketchClicked = Signal(object, float, float)
    viewClicked = Signal(float, float, bool, bool)  # x, y, Shift, Ctrl
    viewHover = Signal(float, float)
    viewDoubleClicked = Signal(float, float)
    bodyClicked = Signal(str, bool)
    selectionCleared = Signal()
    contextRequested = Signal(float, float)
    handleDragged = Signal(str, float)   # id uchwytu, przesunięcie wzdłuż jego osi (mm)
    handleReleased = Signal(str)
    pointDragged = Signal(str, object)    # id uchwytu płaszczyznowego / swobodnego, wektor przesunięcia w świecie (mm)
    cameraMoved = Signal()

    locked = frozenset()      # wyłączone obiekty: widoczne, ale nieaktywne dla myszy

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt=self.format();fmt.setStencilBufferSize(8);self.setFormat(fmt)
        if 'rccad' not in shaders.ShaderProgram.names:
            shaders.ShaderProgram('rccad', [
                shaders.VertexShader(shaders.getShaderProgram('shaded').shaders[0].code),
                shaders.FragmentShader("""
                    #ifdef GL_ES
                    precision mediump float;
                    #endif
                    varying vec4 v_color;
                    varying vec3 v_normal;
                    void main() {
                        vec3 n = normalize(v_normal);
                        float key = max(0.0, dot(n, normalize(vec3(0.3, 0.6, 1.0))));
                        float fill = max(0.0, dot(n, normalize(vec3(-0.6, -0.4, 0.25))));
                        float sky = 0.5 + 0.5 * n.z;
                        float light = 0.46 + 0.34 * key + 0.12 * sky + 0.16 * fill;
                        gl_FragColor = vec4(v_color.rgb * light, v_color.a);
                    }
                """),
            ])
        if 'rccad-section' not in shaders.ShaderProgram.names:
            vertex=shaders.getShaderProgram('shaded').shaders[0].code
            vertex=vertex.replace('varying vec4 v_color;', 'varying vec4 v_color; varying vec3 v_position;').replace('v_color = a_color;', 'v_color = a_color; v_position = a_position.xyz;')
            fragment=shaders.getShaderProgram('rccad').shaders[1].code
            fragment=fragment.replace('varying vec4 v_color;', 'varying vec4 v_color; varying vec3 v_position; uniform float u_cut[4];').replace('vec3 n =', 'if (dot(vec3(u_cut[0],u_cut[1],u_cut[2]),v_position)+u_cut[3] < -0.00001) discard; vec3 n =')
            shaders.ShaderProgram('rccad-section',[shaders.VertexShader(vertex),shaders.FragmentShader(fragment)])
        self.section_plane=None
        self.section_handles=[]
        self.measure_labels=[];self.measure_live=None
        self.section_hover_items=[]
        self.setMouseTracking(True)   # bez tego widok nie dostaje ruchów myszy bez wciśniętego przycisku (brak podglądu na żywo)
        self.setBackgroundColor(BACKGROUND)
        self.setCameraPosition(distance=120, elevation=25, azimuth=-55)
        self.addItem(GradientBackground(BG_TOP, BG_BOTTOM))
        self.grid_items = []
        self.axis_lines = []
        self._grid_plane = None
        self._plane_half = 8.0
        self._grid_key = None
        for size, step, color in ((600, 5, '#d3deeb'), (600, 25, '#9db5cc')):
            grid = gl.GLGridItem()
            grid.setSize(size, size)
            grid.setSpacing(step, step)
            grid.setColor(pg.mkColor(color))
            self.addItem(grid)
            self.grid_items.append(grid)
        self.grid_item = self.grid_items[-1]
        for pts, col in (([(-1000, 0, 0), (1000, 0, 0)], (.89, .31, .33, .85)), ([(0, -1000, 0), (0, 1000, 0)], (.14, .64, .42, .85)),
                         ([(0, 0, 0), (0, 0, 1000)], (.2, .5, .9, .85))):
            axis = SectionLine(pos=np.array(pts, dtype=np.float32), color=col, width=2, antialias=True)
            self.addItem(axis)
            axis.section_ignore=True
            self.axis_lines.append((axis, np.array(pts[1], float) / 1000.0))
        self.custom_plane_items = []
        self.sketch_axis_items = []      # tymczasowy krzyż osi szkicu na ściance bryły
        self.marker_items = []
        self.bodies = ()
        self.model_items = []
        self.highlight_items = []
        self.selected_bodies = set()
        self.selected_edges = {}
        self.edge_mode = False
        self.mouse_mode = "select"
        self.multi_select = False
        self._drag_position = None
        self._press = None
        # szkicowanie myszą
        self.sketch_plane = None
        self.sketch_tool = None
        self.sketch_sides = 6
        self.plane_pick = False
        self._sk_start = None
        self._sk_item = None
        self._hover_plane = None
        self._hover_item = None
        self._hover_key = None
        self._hover_time = 0.0
        self.plane_items = {}
        self._build_planes()
        self.click_mode = False       # True: studio (klik-klik), False: klasyczne okno (przeciąganie)
        self.tints = {}               # id bryły -> kolor RGBA (np. baza / narzędzia Boolean)
        self.preview_items = []
        self.handles = []             # uchwyty-strzałki: dict(id, tip, dir, color, ring=(środek, oś, promień)|None)
        self.handle_items = []
        self._handle_drag = None
        self.snap_label = None
        self.sketch_centers = []
        self.sketch_grips = []
        self.sketch_box = None
        self.hover_vertex = None
        self.sel_vertices = []
        self._dbl = False
        self.drag_hook = None
        self._hook_active = False
        self.snap_marker = None       # ((x, y), etykieta) - przyciąganie jak w wersji HTML
        self.hover_handle = None
        self.free_drag = None         # (id bryły, środek): przeciąganie bryły lewym przyciskiem po płaszczyźnie najbardziej zwróconej do kamery
        self.xray = False
        self.hover_gate = None        # funkcja () -> bool: czy w ogóle liczyć kursor szkicu (Studio włącza po pierwszym kliknięciu)
        self.snapper = None           # funkcja (x, y, (u, v)) -> (u, v, etykieta) ustawiana przez Studio
        self._body_m = {}             # id bryły -> macierz podglądu przesunięcia / obrotu (bez ponownego liczenia geometrii)
        self._cache = {}              # id bryły -> (klucz, elementy GL): bez przebudowy całej sceny przy każdej zmianie
        self._parts = {}              # id bryły -> wypełnienie i linie z kluczami (wypełnienie zostaje przy zmianie koloru)
        self._solid_batches = {}      # stałe szyki rysowane wspólnym buforem zamiast setkami wywołań GL
        self.overlay = Overlay2D(self)
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.raise_()
        self.section_caps=SectionCaps();self.addItem(self.section_caps)
        self._section_classifiers={}
        self._sketch_batches=[];self._sketch_batch_key=None
        self._scene_revision=0;self._scene_signature=None
        self._projection_cache=LRU(96*1024*1024)

    def _refresh_grid(self):
        """Siatka zagęszcza się przy przybliżaniu (min. GRID_PX px między cienkimi liniami) i podąża za środkiem widoku."""
        if not getattr(self, 'grid_items', None) or self.width() < 2:
            return
        dist = max(float(self.opts['distance']), 1e-6)
        ppm = (self.height() / 2) / (dist * math.tan(math.radians(float(self.opts['fov']) / 2)))
        step = next((g for g in GRID_LEVELS if g * ppm >= GRID_PX), GRID_LEVELS[-1])
        want = next((z for z in PLANE_SIZES if z >= dist * .035), PLANE_SIZES[-1])
        if want != self._plane_half and hasattr(self, '_plane_corners'):
            self._plane_half = float(want)
            self._apply_plane_size()
        major = step * 5
        plane = self._grid_plane or 'XY'
        c = self.opts['center']
        u, v = kernel.uv_of(plane, (c.x(), c.y(), c.z()))
        cu, cv = round(u / major) * major, round(v / major) * major
        key = (step, cu, cv, id(plane) if not isinstance(plane, str) else plane)
        if key == self._grid_key:
            return
        self._grid_key = key
        frame = kernel.frame_of(plane)
        m = QMatrix4x4()
        x, y, n = (np.array(vec, float) for vec in (frame.xdir, frame.ydir, frame.normal))
        o = np.array(frame.origin, float) + x * cu + y * cv
        for r in range(3):
            m.setRow(r, QVector4D(float(x[r]), float(y[r]), float(n[r]), float(o[r])))
        half = step * 170
        for grid, spacing in zip(self.grid_items, (step, major)):
            grid.setSize(2 * half, 2 * half)
            grid.setSpacing(spacing, spacing)
            grid.setTransform(m)

    def update(self, *args):
        self._refresh_grid()
        self._refresh_axes()
        super().update(*args)
        self.cameraMoved.emit()
        ov = getattr(self, 'overlay', None)
        if ov is not None:
            ov.update()

    def _refresh_axes(self):
        """Oś patrzenia wzdłuż osi świata (np. widok z góry) rzutowałaby się jako skośna kreska - wtedy ją chowamy."""
        try:
            cam = self.camera_dir()
        except Exception:
            return
        if getattr(self, '_axes_busy', False):
            return
        self._axes_busy = True
        try:
            hidden = getattr(self, '_main_axes_hidden', False)
            for item, direction in getattr(self, 'axis_lines', ()):
                show = not hidden and abs(float(np.dot(cam, direction))) < .985
                if item.visible() != show:
                    item.setVisible(show)
        finally:
            self._axes_busy = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.raise_()

    def set_xray(self, on):
        """Przezroczyste bryły (podgląd ukrytych krawędzi); domyślnie bryły są w pełni nieprzezroczyste."""
        self.xray = bool(on)
        for bid in list(self._cache):
            for item in self._cache.pop(bid)[1]:
                self.removeItem(item)
        self._parts.clear()
        self.set_models(self.bodies, self.selected_bodies, self.selected_edges)

    THREAD_COLOR = (.16, .45, .86, 1)      # gwint: niebieska linia śrubowa

    def set_threads(self, items):
        """Gwinty kosmetyczne: linie śrubowe przy bryłach ({id bryły: opisy gwintów}). Elementy GL powstają tylko
        przy zmianie gwintów - obracanie widoku nic nie kosztuje."""
        from .threads import thread_lines
        store = self.__dict__.setdefault('_thread_items', {})
        for bid in list(store):
            if bid not in items:
                self.removeItem(store.pop(bid)[1])
        for bid, threads in items.items():
            key = repr(threads)
            old = store.get(bid)
            if old is not None and old[0] == key:
                continue
            if old is not None:
                self.removeItem(old[1])
            segs = np.concatenate([thread_lines(t) for t in threads]) if threads else np.zeros((0, 2, 3), np.float32)
            item = SectionLine(pos=segs.reshape(-1, 3), color=self.THREAD_COLOR, width=1.5, antialias=True, mode='lines')
            self.addItem(item)
            store[bid] = (key, item)
            m = self._body_m.get(bid)
            if m is not None:
                item.setTransform(m)
        self.update()

    def set_thread_preview(self, thread):
        """Podgląd gwintu przed zatwierdzeniem (niebieski, rysowany od razu - bez liczenia geometrii)."""
        from .threads import thread_lines
        old = self.__dict__.get('_thread_preview')
        if old is not None:
            self.removeItem(old)
            self._thread_preview = None
        threads = [t for t in (thread if isinstance(thread, (list, tuple)) else [thread]) if t is not None]
        if threads:
            segs = np.concatenate([thread_lines(t) for t in threads])
            self._thread_preview = SectionLine(pos=segs.reshape(-1, 3), color=(.35, .68, 1.0, 1), width=2.2, antialias=True, mode='lines')
            self.addItem(self._thread_preview)
        self.update()

    def _apply_body_matrix(self, bid):
        thread = self.__dict__.get('_thread_items', {}).get(bid)
        if thread is not None:
            m = self._body_m.get(bid)
            thread[1].resetTransform() if m is None else thread[1].setTransform(m)
        cached = self._cache.get(bid)
        if not cached:
            return
        m = self._body_m.get(bid)
        for item in cached[1]:
            if m is None:
                item.resetTransform()
            else:
                item.setTransform(m)

    def set_body_matrix(self,bid,matrix):
        self.set_body_matrices({bid:matrix})

    def set_body_matrices(self,matrices):
        """Update a whole selection, rebuilding sketch batches just once."""
        for bid,matrix in matrices.items():
            if matrix is None:self._body_m.pop(bid,None)
            else:self._body_m[bid]=QMatrix4x4(matrix)
            self._apply_body_matrix(bid)
        self._scene_revision+=1;self._sync_sketch_batches();self.section_caps.update_section();self.update()

    def clear_body_matrices(self):
        self._scene_revision+=1
        for bid in list(self._body_m):
            self._body_m.pop(bid)
            self._apply_body_matrix(bid)
        self._sync_sketch_batches()
        self.section_caps.update_section()
        self.update()

    def project_one(self, point):
        xy, _, w = self.project_points(np.asarray([point], float))
        if not np.isfinite(xy[0]).all() or w[0] <= 0:
            return None
        return float(xy[0][0]), float(xy[0][1])

    def _sync_solid_batches(self):
        """Draw idle pattern solids together; their individual CAD shapes remain pickable."""
        groups={}
        if self.section_plane is None and not self.xray:
            for body in self.bodies:
                key=body.group or body.folder
                if (key and body.kind=='solid' and body.visible and body.mesh is not None
                        and body.id not in self._body_m and not self.selected_edges.get(body.id)
                        and body.id not in self.tints):
                    batch_key=(key,'picked') if body.id in self.selected_bodies else key
                    groups.setdefault(batch_key,[]).append(body)
        groups={key:members for key,members in groups.items() if len(members)>=24}
        old=self._solid_batches
        fresh={}
        for key,members in groups.items():
            signature=tuple((b.id,id(b.mesh)) for b in members)
            previous=old.pop(key,None)
            if previous is not None and previous[0]==signature:
                fresh[key]=previous;continue
            if previous is not None:
                for item in previous[1:]:self.removeItem(item)
            vertices=np.concatenate([b.mesh.vertices for b in members])
            offsets=np.cumsum([0]+[len(b.mesh.vertices) for b in members[:-1]],dtype=np.uint32)
            triangles=np.concatenate([b.mesh.triangles+offset for b,offset in zip(members,offsets)])
            edges={i:pts for i,pts in enumerate(pts for b in members for pts in b.mesh.edges.values())}
            combined=kernel.DisplayMesh(vertices,triangles,edges,(0.,0.,0.),1.)
            picked=isinstance(key,tuple) and key[1]=='picked'
            fill=OffsetMesh(meshdata=_meshdata(combined),smooth=True,color=PICKED_FILL if picked else SOLID_COLOR,shader='rccad',drawEdges=False)
            fill.setGLOptions('opaque');self.addItem(fill)
            items=[fill];segments=_segments(edges.values())
            if segments is not None:
                line=SectionLine(pos=segments,color=PICKED_COLOR if picked else EDGE_COLOR,width=4.0 if picked else 1.5,antialias=True,mode='lines')
                line.setGLOptions('translucent');self.addItem(line);items.append(line)
            fresh[key]=(signature,*items)
        for previous in old.values():
            for item in previous[1:]:self.removeItem(item)
        self._solid_batches=fresh
        return {bid for signature,*_ in fresh.values() for bid,_ in signature}

    def set_models(self, bodies, selected_bodies=(), selected_edges=None):
        self._set_hover_edge(None)
        self.bodies = tuple(bodies)
        signature=tuple((b.id,id(b.mesh),id(b.shape),b.kind,b.visible) for b in self.bodies)
        if signature!=self._scene_signature:
            self._scene_signature=signature;self._scene_revision+=1
        live_ids={b.id for b in self.bodies}
        self.section_caps.retain_bodies(live_ids)
        self._section_classifiers={bid:c for bid,c in self._section_classifiers.items() if bid in live_ids}
        self.selected_bodies = set(selected_bodies)
        self.selected_edges = selected_edges or {}
        batched=self._sync_solid_batches()
        live = set()
        centers = []
        for body in self.bodies:
            if not body.visible or body.mesh is None or body.id in batched:
                continue
            live.add(body.id)
            mesh = body.mesh
            picked = body.id in self.selected_bodies
            color = PICKED_FILL if picked and body.kind != 'sketch' else (self.tints.get(body.id) or SOLID_COLOR)
            sel = frozenset(self.selected_edges.get(body.id, ()))
            # obraz bryły (wypełnienie w pamięci karty graficznej) zostaje, dopóki nie zmieni się siatka - zaznaczenie i kolory
            # zmieniają tylko kolor; od nowa budują się wyłącznie linie krawędzi (lekkie)
            shown = (*color[:3], .30) if self.xray and body.kind != 'sketch' else tuple(color)
            fill_key = (id(mesh), body.kind, self.xray)
            line_key = (id(mesh), picked, sel, body.kind, self.xray)
            parts = self._parts.get(body.id)
            if parts is None or parts['fill_key'] != fill_key or parts['line_key'] != line_key:
                old_parts = parts or {}
                fill = old_parts.get('fill')
                if parts is None or parts['fill_key'] != fill_key:
                    if fill is not None:
                        self.removeItem(fill)
                    fill = None
                    if len(mesh.triangles):
                        fill = OffsetMesh(meshdata=_meshdata(mesh), smooth=True, color=shown, shader='rccad', drawEdges=False)
                        fill.setGLOptions('translucent' if self.xray else 'opaque')
                        fill.section_body_id=body.id
                        self.addItem(fill)
                elif fill is not None and old_parts.get('color') != shown:
                    fill.setColor(shown)
                for line in old_parts.get('lines', ()):
                    self.removeItem(line)
                lines = []
                base = SKETCH_COLOR if body.kind == 'sketch' else EDGE_COLOR
                for hot, color_, width_ in ((False, base, 2.3 if body.kind == 'sketch' else 1.5), (True, PICKED_COLOR if picked else PREVIEW_COLOR, 4.0 if picked else 3.5)):
                    seg = _segments([pts for index, pts in mesh.edges.items() if (index in sel or picked) == hot])
                    if seg is None:
                        continue
                    line = (OverLine if body.kind == 'sketch' else SectionLine)(pos=seg, color=color_, width=width_, antialias=True, mode='lines')
                    if body.kind != 'sketch':
                        line.setGLOptions('additive' if self.xray else 'translucent')
                    line.section_body_id=body.id
                    self.addItem(line)
                    lines.append(line)
                parts = self._parts[body.id] = dict(fill_key=fill_key, line_key=line_key, fill=fill, lines=lines, color=shown, cap_solid=body.kind=='solid' and bool(body.shape.Solids()))
                self._cache[body.id] = (line_key, ([fill] if fill is not None else []) + lines)
                if body.id in self._body_m:
                    self._apply_body_matrix(body.id)
            elif parts['color'] != shown:
                if parts['fill'] is not None:
                    parts['fill'].setColor(shown)        # sam kolor (zaznaczenie, podświetlenie narzędzia) - bez przebudowy
                parts['color'] = shown
            if body.kind == 'sketch' and len(mesh.vertices) + len(mesh.edges):
                pts = np.concatenate([e.reshape(-1, 3) for e in mesh.edges.values()]) if mesh.edges else mesh.vertices
                if len(pts):
                    centers.append(((pts.min(axis=0) + pts.max(axis=0)) / 2).tolist())
        for bid in [b for b in self._cache if b not in live]:
            for item in self._cache.pop(bid)[1]:
                self.removeItem(item)
            self._parts.pop(bid, None)
        self.sketch_centers = centers
        self.section_caps.update_section()
        self._sync_sketch_batches()
        self.update()

    def _sync_sketch_batches(self):
        sketches=[b for b in self.bodies if b.visible and b.kind=='sketch' and b.id in self._parts]
        eligible=[b for b in sketches if b.id not in self._body_m]
        key=tuple((b.id,self._parts[b.id]['line_key']) for b in eligible) if len(eligible)>=24 else ()
        if key==self._sketch_batch_key:return
        self._sketch_batch_key=key
        for item in self._sketch_batches:self.removeItem(item)
        self._sketch_batches=[];groups={};merged={b.id for b in eligible} if key else set()
        for body in sketches:
            for line in self._parts[body.id]['lines']:
                line.setVisible(body.id not in merged)
                if body.id in merged:
                    style=(tuple(line.color),line.width)
                    groups.setdefault(style,[]).append(line.pos)
        for (color,width),arrays in groups.items():
            item=OverLine(pos=np.concatenate(arrays),color=color,width=width,antialias=True,mode='lines')
            self.addItem(item);self._sketch_batches.append(item)

    def fit_all(self):
        visible = [b for b in self.bodies if b.visible and b.mesh is not None and len(b.mesh.vertices)]
        if not visible:
            self.opts['center'] = QVector3D(0, 0, 0)
            self.setCameraPosition(distance=120)
            return
        low = np.min([b.mesh.vertices.min(axis=0) for b in visible], axis=0)
        high = np.max([b.mesh.vertices.max(axis=0) for b in visible], axis=0)
        center = (low + high) / 2
        self.opts['center'] = QVector3D(*map(float, center))
        self.setCameraPosition(distance=max(20, float(np.linalg.norm(high - low)) * 1.6))

    def set_grid_visible(self, on):
        """Siatka robocza włączana / wyłączana przyciskiem na dolnym pasku."""
        self._grid_on = bool(on)
        for grid in getattr(self, 'grid_items', ()):
            grid.setVisible(self._grid_on)
        self.update()

    def set_view(self, name):
        el, az = VIEWS[name]
        self.setCameraPosition(elevation=el, azimuth=az)

    # ---------- płaszczyzny (jak w HTML) ----------
    def _build_planes(self):
        """Płaszczyzny podstawowe w stylu Fusion 360: małe, półprzezroczyste kwadraty z cienkim obrysem; rozmiar zależy od powiększenia."""
        corners = {
            'XY': [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)],
            'XZ': [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)],
            'YZ': [(0, -1, -1), (0, 1, -1), (0, 1, 1), (0, -1, 1)],
        }
        self._plane_corners = corners
        for name, pts in corners.items():
            color = pg.mkColor(PLANE_COLORS[name])
            rgb = (color.redF(), color.greenF(), color.blueF())
            fill = SectionMesh(vertexes=np.array(pts, dtype=np.float32), faces=np.array([[0, 1, 2], [0, 2, 3]]),
                                 color=(*rgb, .10), smooth=False, drawEdges=False)
            fill.setGLOptions('translucent')
            outline = SectionLine(pos=np.array([*pts, pts[0]], dtype=np.float32), color=(*rgb, .75), width=1.6, antialias=True)
            label = gl.GLTextItem(pos=np.array(pts[2], dtype=np.float32) * .8, text=name, color=QColor(PLANE_COLORS[name]))
            self.plane_items[name] = (fill, outline, label, rgb)
        self._apply_plane_size()

    def _apply_plane_size(self):
        half = self._plane_half
        m = QMatrix4x4()
        m.scale(half, half, half)
        for name, (fill, outline, label, rgb) in self.plane_items.items():
            fill.setTransform(m)
            outline.setTransform(m)
            label.setData(pos=np.array(self._plane_corners[name][2], dtype=np.float32) * half * .8)

    def show_planes(self, visible, only=None):
        for name, (fill, outline, label, rgb) in self.plane_items.items():
            show = visible and (only is None or name == only)
            for item in (fill, outline, label):
                if show and item not in self.items:
                    self.addItem(item)
                elif not show and item in self.items:
                    self.removeItem(item)
        self._hover_plane = None
        self.update()

    def _highlight_plane(self, name):
        if name == self._hover_plane:
            return
        self._hover_plane = name
        for key, (fill, outline, label, rgb) in self.plane_items.items():
            fill.setColor((*rgb, .38 if key == name else .16))
        self.update()

    def _plane_hit(self, plane, x, y):
        ray = self._ray(x, y)
        if ray is None:
            return None
        origin, direction = ray
        frame = kernel.frame_of(plane)
        n, o = np.array(frame.normal), np.array(frame.origin)
        denom = float(direction @ n)
        if abs(denom) < 1e-9:
            return None
        t = float((o - origin) @ n) / denom
        if t <= 0:
            return None
        return t, origin + direction * t

    def plane_at(self, x, y):
        best = None
        for name in self.plane_items:
            if self.plane_items[name][0] not in self.items:
                continue
            hit = self._plane_hit(name, x, y)
            if hit:
                u, v = kernel.uv_of(name, hit[1])
                if abs(u) <= self._plane_half and abs(v) <= self._plane_half and (best is None or hit[0] < best[0]):
                    best = (hit[0], name)
        return best[1] if best else None

    def plane_point(self, plane, x, y):
        hit = self._plane_hit(plane, x, y)
        if hit is None:
            return None
        return kernel.uv_of(plane, hit[1])

    def _snap(self, point, event=None, pos=None):
        if event is not None and event.modifiers() & Qt.AltModifier:
            self.snap_label = None
            return point
        if pos is None and event is not None:
            pos = event.position()
        if self.snapper is not None and pos is not None:
            u, v, label = self.snapper(pos.x(), pos.y(), point)
            self.snap_label = label
            return u, v
        distance = float(self.opts['distance'])
        step = 10 ** math.floor(math.log10(max(distance / 40, 1e-3)))
        return round(point[0] / step) * step, round(point[1] / step) * step

    def _sketch_outline(self, plane, start, end):
        (u0, v0), (u1, v1) = start, end
        if self.sketch_tool == 'rectangle':
            uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1), (u0, v0)]
        else:
            r = math.hypot(u1 - u0, v1 - v0)
            n = 72 if self.sketch_tool == 'circle' else max(3, int(self.sketch_sides))
            uv = [(u0 + r * math.cos(2 * math.pi * k / n), v0 + r * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]
        return np.array([kernel.to_world(plane, u, v) for u, v in uv], dtype=np.float32)

    def _set_sketch_preview(self, points):
        if self._sk_item is not None:
            self.removeItem(self._sk_item)
            self._sk_item = None
        if points is not None:
            self._sk_item = SectionLine(pos=points, color=PREVIEW_COLOR, width=2.5, antialias=True)
            self.addItem(self._sk_item)
        self.update()

    def set_picked_edge(self, hit):
        """Trwałe podświetlenie wybranej krawędzi blachy (zostaje, dopóki nie zmieni się wybór)."""
        if getattr(self, '_picked_item', None) is not None:
            self.removeItem(self._picked_item)
            self._picked_item = None
        if hit:
            body = next((b for b in self.bodies if b.id == hit[0]), None)
            points = body.mesh.edges.get(hit[1]) if body and body.mesh else None
            if points is not None:
                self._picked_item = OverLine(pos=points, color=(.95, .42, .02, 1), width=6, antialias=True)
                self.addItem(self._picked_item)
        self.update()

    def _set_hover_edge(self, hit):
        if hit == self._hover_key:
            return
        self._hover_key = hit
        if self._hover_item is not None:
            self.removeItem(self._hover_item)
            self._hover_item = None
        if hit:
            body = next((b for b in self.bodies if b.id == hit[0]), None)
            points = body.mesh.edges.get(hit[1]) if body and body.mesh else None
            if points is not None:
                self._hover_item = OverLine(pos=points, color=(1, .65, .2, 1), width=5, antialias=True)
                self.addItem(self._hover_item)
        self.update()

    def set_hover_body(self, bid):
        """Podświetla na pomarańczowo wszystkie krawędzie jednego obiektu (np. szkicu) - widać, co zostanie wybrane."""
        key = ('body', bid)
        if key == self._hover_key or (bid is None and self._hover_key is None):
            return
        self._hover_key = key if bid is not None else None
        if self._hover_item is not None:
            self.removeItem(self._hover_item)
            self._hover_item = None
        body = next((b for b in self.bodies if b.id == bid), None) if bid is not None else None
        if body is not None and body.mesh is not None:
            seg = _segments(body.mesh.edges.values())
            if seg is not None:
                self._hover_item = OverLine(pos=seg, color=(1, .65, .2, 1), width=5, antialias=True, mode='lines')
                self.addItem(self._hover_item)
        self.update()

    # ---------- podglądy i wybieranie (studio) ----------
    def _dashed(self, points):
        pts = np.asarray(points, float)
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        total = float(seg.sum())
        if total < 1e-9:
            return None
        dash = max(float(self.opts['distance']) * .012, 1e-3)
        cum = np.concatenate([[0], np.cumsum(seg)])
        starts = np.arange(0, total, dash * 2)
        ends = np.minimum(starts + dash, total)
        point_at = lambda t: np.column_stack([np.interp(t, cum, pts[:, k]) for k in range(3)])
        out = np.empty((len(starts) * 2, 3))
        out[0::2], out[1::2] = point_at(starts), point_at(ends)
        return out.astype(np.float32)

    def stretch_preview(self, origin, normal, factor):
        """Natychmiastowe skalowanie podglądu wyciągnięcia wzdłuż normalnej (płynność w czasie rzeczywistym, zanim OCC policzy dokładny wynik)."""
        n = np.asarray(normal, float)
        n = n / np.linalg.norm(n)
        o = np.asarray(origin, float)
        m = np.eye(3) + (float(factor) - 1.0) * np.outer(n, n)
        t = o - m @ o
        mat = QMatrix4x4(m[0, 0], m[0, 1], m[0, 2], t[0], m[1, 0], m[1, 1], m[1, 2], t[1], m[2, 0], m[2, 1], m[2, 2], t[2], 0, 0, 0, 1)
        for item in self.preview_items:
            item.setTransform(mat)
        self.update()

    def transform_preview_uv(self, plane, a0, a1, factor, angle_deg):
        """Natychmiastowe przekształcenie podglądu w płaszczyźnie szkicu (podobieństwo: obrót + skala wokół a0, potem przesunięcie do a1) - bez liczenia geometrii."""
        f = kernel.frame_of(plane)
        B = np.array([f.xdir, f.ydir, f.normal], float).T
        o = np.array(f.origin, float)
        c, sn = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
        L = np.array([[factor * c, -factor * sn, 0], [factor * sn, factor * c, 0], [0, 0, 1]], float)
        M = B @ L @ B.T
        t = o - M @ o + B @ (np.array([a1[0], a1[1], 0.0]) - L @ np.array([a0[0], a0[1], 0.0]))
        mat = QMatrix4x4(M[0, 0], M[0, 1], M[0, 2], t[0], M[1, 0], M[1, 1], M[1, 2], t[1], M[2, 0], M[2, 1], M[2, 2], t[2], 0, 0, 0, 1)
        for item in self.preview_items:
            item.setTransform(mat)
        self.update()

    def set_preview_mesh(self, mesh, color=(.25, .55, .95, .55), line_color=(.1, .25, .5, 1), width=1.5, dashed=False, on_top=False):
        """on_top: podgląd widoczny także przez bryłę (np. tworzone zaokrąglenie wewnątrz jeszcze ostrego narożnika)."""
        for item in self.preview_items:
            self.removeItem(item)
        self.preview_items = []
        if mesh is not None:
            if len(mesh.triangles):
                item = OverMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=True, color=color, drawEdges=False, shader='rccad') if on_top \
                    else OverMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=False, color=color, drawEdges=False)
                if on_top:
                    item.setDepthValue(10)
                    item.setGLOptions({GL.GL_DEPTH_TEST: False, GL.GL_BLEND: True, GL.GL_ALPHA_TEST: False, GL.GL_CULL_FACE: False,
                                       'glBlendFunc': (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)})
                else:
                    item.setGLOptions('translucent')
                self.addItem(item)
                self.preview_items.append(item)
            if dashed:
                chains = [self._dashed(points) for points in mesh.edges.values()]
                seg = np.concatenate([c for c in chains if c is not None]) if any(c is not None for c in chains) else None
            else:
                seg = _segments(mesh.edges.values())
            if seg is not None:
                line = SectionLine(pos=seg, color=line_color, width=width, antialias=True, mode='lines')
                self.addItem(line)
                self.preview_items.append(line)
        self.update()

    def set_pattern_preview_mesh(self, mesh):
        """Keep pattern GL items alive while only their vertex data changes."""
        segments=_segments(mesh.edges.values())
        has_fill=bool(len(mesh.triangles));has_line=segments is not None
        old=getattr(self,'_pattern_preview_items',None)
        if old and tuple(self.preview_items)==old[0] and (has_fill,has_line)==old[1]:
            index=0
            if has_fill:
                self.preview_items[index].setMeshData(vertexes=mesh.vertices,faces=mesh.triangles)
                index+=1
            if has_line:self.preview_items[index].setData(pos=segments)
            self.update();return
        self.set_preview_mesh(mesh,color=(.3,.8,.5,.55),line_color=(.05,.4,.2,1),width=2)
        self._pattern_preview_items=(tuple(self.preview_items),(has_fill,has_line))

    SPLIT_COLORS = {1: ((.30, .80, .50, .62), (.08, .50, .25, 1)), 2: ((.96, .58, .18, .62), (.65, .33, .03, 1))}

    def set_split_preview(self, parts, cut=None):
        """Podgląd przecięcia: części [(siatka, strona, zostaje)] - strona 1 zielona, 2 pomarańczowa, odrzucone ledwie widoczne;
        cut - płaszczyzna cięcia (półprzezroczysty fiolet). Czyści się razem z set_preview_mesh(None)."""
        for item in self.preview_items:
            self.removeItem(item)
        self.preview_items = []
        for mesh, side, kept in parts:
            fill, line = self.SPLIT_COLORS.get(side, self.SPLIT_COLORS[1])
            if not kept:
                fill, line = (.55, .6, .66, .10), (.45, .5, .56, .45)
            if len(mesh.triangles):
                item = OverMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=False, color=fill, drawEdges=False)
                item.setGLOptions('translucent')
                self.addItem(item)
                self.preview_items.append(item)
            seg = _segments(mesh.edges.values())
            if seg is not None:
                item = SectionLine(pos=seg, color=line, width=2.0, antialias=True, mode='lines')
                self.addItem(item)
                self.preview_items.append(item)
        if cut is not None and len(cut.triangles):
            item = OverMesh(vertexes=cut.vertices, faces=cut.triangles, smooth=False, color=(.62, .45, .90, .28), drawEdges=False)
            item.setGLOptions('translucent')
            self.addItem(item)
            self.preview_items.append(item)
            seg = _segments(cut.edges.values())
            if seg is not None:
                item = SectionLine(pos=seg, color=(.45, .25, .75, .9), width=1.6, antialias=True, mode='lines')
                self.addItem(item)
                self.preview_items.append(item)
        self.update()

    def set_hover_mesh(self, mesh, color=(.35, .65, .94, .45), line_color=(.1, .3, .6, 1), width=2.4):
        """Podświetlenie elementu pod kursorem - osobna warstwa, więc nie zastępuje podglądu operacji ani wyboru."""
        for item in getattr(self, 'hover_items', []):
            self.removeItem(item)
        self.hover_items = []
        if mesh is not None:
            if len(mesh.triangles):
                item = OverMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=False, color=color, drawEdges=False)
                item.setGLOptions('translucent')
                self.addItem(item)
                self.hover_items.append(item)
            seg = _segments(mesh.edges.values())
            if seg is not None:
                line = SectionLine(pos=seg, color=line_color, width=width, antialias=True, mode='lines')
                self.addItem(line)
                self.hover_items.append(line)
        self.update()

    def set_selection_meshes(self, meshes, color=(1, .55, .1, .55), line_color=(.95, .42, .02, 1)):
        """Trwałe podświetlenie wybranych ścian / profili (świeci się, dopóki operacja trwa)."""
        for item in getattr(self, 'selection_items', []):
            self.removeItem(item)
        self.selection_items = []
        for mesh in meshes or []:
            if mesh is None:
                continue
            if len(mesh.triangles):
                item = OverMesh(vertexes=mesh.vertices, faces=mesh.triangles, smooth=False, color=color, drawEdges=False)
                item.setGLOptions('translucent')
                self.addItem(item)
                self.selection_items.append(item)
            seg = _segments(mesh.edges.values())
            if seg is not None:
                line = SectionLine(pos=seg, color=line_color, width=3.2, antialias=True, mode='lines')
                self.addItem(line)
                self.selection_items.append(line)
        self.update()

    def set_handles(self, handles):
        """Uchwyty-strzałki rysowane na wierzchu (Overlay2D): dict(id, start, tip, dir, color, label, min_px, ring=(środek, oś, promień)|None)."""
        self.handles = []
        for h in handles or []:
            d = np.asarray(h.get('dir', (0, 0, 1)), dtype=float)
            d = d / np.linalg.norm(d)
            tip = np.asarray(h.get('tip', h.get('start', (0, 0, 0))), dtype=float)
            start = np.asarray(h.get('start', tip - d), dtype=float)
            self.handles.append(dict(h, dir=d, tip=tip, start=start))
        self.update()

    def set_handle(self, tip, direction):
        self.set_handles([] if tip is None else [dict(id='ex', tip=tip, dir=direction)])

    # ---------- obrót widoku w płaszczyźnie ekranu (wokół osi patrzenia) ----------
    def roll(self):
        return float(self.opts.get('roll', 0.0))

    def set_roll(self, degrees):
        self.opts['roll'] = ((float(degrees) + 180.0) % 360.0) - 180.0
        self.update()

    def roll_by(self, degrees):
        self.set_roll(self.roll() + degrees)

    def viewMatrix(self):
        tr = QMatrix4x4()
        tr.translate(0.0, 0.0, -self.opts['distance'])
        roll = self.roll()
        if roll:
            tr.rotate(roll, 0, 0, 1)            # obraz obrócony wokół osi patrzenia
        tr.rotate(self.opts['elevation'] - 90, 1, 0, 0)
        tr.rotate(self.opts['azimuth'] + 90, 0, 0, -1)
        center = self.opts['center']
        tr.translate(-center.x(), -center.y(), -center.z())
        return tr

    def _unroll(self, dx, dy):
        """Ruch myszy na ekranie -> ruch w układzie kamery bez obrotu (przesuwanie i obracanie idą za kursorem także po obróceniu widoku)."""
        roll = math.radians(self.roll())
        if not roll:
            return dx, dy
        c, s = math.cos(roll), math.sin(roll)
        return c * dx - s * dy, s * dx + c * dy

    def pan(self, dx, dy, dz, relative='global'):
        if relative == 'view':
            dx, dy = self._unroll(dx, dy)
        super().pan(dx, dy, dz, relative)

    def orbit(self, azim, elev):
        if self.roll():
            ox, oy = self._unroll(-azim, elev)
            azim, elev = -ox, oy
        super().orbit(azim, elev)

    def setCameraPosition(self, pos=None, distance=None, elevation=None, azimuth=None, rotation=None):
        if elevation is not None or azimuth is not None:
            self.opts['roll'] = 0.0             # nowy kierunek patrzenia: napisy kostki znowu prosto, obrót można potem dodać strzałkami
        super().setCameraPosition(pos=pos, distance=distance, elevation=elevation, azimuth=azimuth, rotation=rotation)

    def orient(self, back, up):
        """Kamera patrzy z kierunku `back` (wersor od celu do kamery), a `up` jest u góry ekranu."""
        back = np.asarray(back, float)
        back = back / max(np.linalg.norm(back), 1e-12)
        super().setCameraPosition(**camera_for_normal(back))
        self.opts['roll'] = 0.0
        right, cur_up, _ = self.screen_axes()
        up = np.asarray(up, float)
        x, y = float(up @ right), float(up @ cur_up)
        if math.hypot(x, y) > 1e-6:
            self.set_roll(round(-math.degrees(math.atan2(-x, y)), 6))
        self.update()

    def screen_axes(self):
        """Wersory świata: w prawo i w górę ekranu oraz do kamery (z uwzględnieniem obrotu widoku)."""
        m = self.viewMatrix()
        rows = [np.array([m.row(i).x(), m.row(i).y(), m.row(i).z()]) for i in range(3)]
        return rows[0], rows[1], rows[2]

    def camera_dir(self):
        """Wersor od celu do kamery (świat)."""
        az, el = math.radians(float(self.opts['azimuth'])), math.radians(float(self.opts['elevation']))
        return np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])

    def _cam_ppm(self):
        return (self.height() / 2) / (max(float(self.opts['distance']), 1e-6) * math.tan(math.radians(float(self.opts['fov']) / 2)))

    def handle_geometry(self, h):
        """Ekranowe położenie strzałki: start, koniec, kierunek jednostkowy i skala px/mm. Dopasowuje się do kamery:
        przy patrzeniu wzdłuż osi (skrót perspektywiczny) kierunek i skala są stabilizowane, więc uchwyt zawsze da się złapać."""
        s0 = self.project_one(h['start'])
        s1 = self.project_one(h['tip'])
        u = self.project_one(h['start'] + h['dir'] * 10.0)
        if s0 is None or s1 is None or u is None:
            return None
        dx, dy = u[0] - s0[0], u[1] - s0[1]
        length = math.hypot(dx, dy)
        cam = self._cam_ppm()
        ppm = length / 10.0
        if length < 3.0:
            ux, uy = 0.0, -1.0
        else:
            ux, uy = dx / length, dy / length
        floor = .4 * cam
        foreshortened = ppm < floor
        ppm_eff = max(ppm, floor)
        minimum = h.get('min_px', 44)
        signed = float(np.dot(h['tip'] - h['start'], h['dir']))
        end = s1
        if foreshortened or math.hypot(s1[0] - s0[0], s1[1] - s0[1]) < minimum:
            px = signed * ppm_eff
            if abs(px) < minimum:
                px = minimum if signed >= 0 else -minimum
            if minimum == 0:
                px = signed * ppm_eff
            end = (s0[0] + ux * px, s0[1] + uy * px)
        return dict(start=s0, end=end, ux=ux, uy=uy, px_per_mm=ppm_eff)

    def _seg_dist(self, x, y, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 < 1e-9 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / l2))
        return math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy))

    def _ring_points(self, h):
        c, axis, radius = (np.asarray(h['ring'][0], float), np.asarray(h['ring'][1], float), float(h['ring'][2]))
        e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        return np.array([c + radius * (np.cos(a) * e1 + np.sin(a) * e2) for a in np.linspace(0, 2 * np.pi, 97)])

    def _grab_handle(self, x, y):
        """Najbliższy uchwyt pod kursorem: strzałki i osie mają pierwszeństwo, potem pierścienie, na końcu kwadraty płaszczyzn."""
        best = None
        for h in self.all_handles():
            kind = h.get('kind', 'arrow')
            try:
                if kind in ('arrow', 'axis'):
                    geo = self.handle_geometry(h)
                    if geo is None:
                        continue
                    d = min(math.hypot(x - geo['end'][0], y - geo['end'][1]) - 6, self._seg_dist(x, y, geo['start'], geo['end']))
                    ok, rank = d <= 12, 0
                elif kind == 'ring':
                    xy, _, _ = self.project_points(self._ring_points(h))
                    d = min(self._seg_dist(x, y, xy[i], xy[i + 1]) for i in range(len(xy) - 1))
                    ok, rank = d <= 10, 1
                else:
                    pts = [self.project_one(q) for q in h['quad']]
                    if any(q is None for q in pts):
                        continue
                    inside = QPolygonF([QPointF(*q) for q in pts]).containsPoint(QPointF(x, y), Qt.OddEvenFill)
                    d, ok, rank = 0.0, inside, 2
            except Exception:
                continue
            if ok and (best is None or (rank, d) < (best[0], best[1])):
                best = (rank, d, h)
        return best[2] if best else None

    # ---------- przeciąganie uchwytów: promień kursora → oś / płaszczyzna / pierścień (zawsze zgodnie z kamerą) ----------
    @staticmethod
    def _line_param(ray, p0, d):
        """Parametr t punktu osi p0 + t·d najbliższego promieniowi kursora; None, gdy promień jest równoległy do osi."""
        o, r = ray
        w0 = o - p0
        b, dd, e = float(r @ d), float(r @ w0), float(d @ w0)
        den = 1.0 - b * b
        if den < .02:
            return None
        return (e - b * dd) / den

    @staticmethod
    def _ray_plane(ray, origin, normal):
        o, r = ray
        den = float(r @ normal)
        if abs(den) < 1e-4:
            return None
        t = float((origin - o) @ normal) / den
        return o + r * t if t > 0 else None

    def _begin_drag(self, h, x, y):
        ray = self._ray(x, y)
        if ray is None:
            return None
        kind = h.get('kind', 'arrow')
        st = dict(id=h['id'], kind=kind, x0=x, y0=y, geo=self.handle_geometry(h) if kind in ('arrow', 'axis') else None)
        if kind in ('arrow', 'axis'):
            st['line'] = (np.asarray(h['start'], float), np.asarray(h['dir'], float))
            st['t0'] = self._line_param(ray, *st['line'])
        elif kind == 'plane':
            st['plane'] = (np.asarray(h['plane_origin'], float), np.asarray(h['normal'], float))
            st['hit0'] = self._ray_plane(ray, *st['plane'])
        elif kind == 'ring':
            c, axis, radius = (np.asarray(h['ring'][0], float), np.asarray(h['ring'][1], float), float(h['ring'][2]))
            e1 = np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0))
            e1 /= np.linalg.norm(e1)
            st.update(c=c, axis=axis, radius=radius, e1=e1, e2=np.cross(axis, e1), total=0.0)
            hit = self._ray_plane(ray, c, axis)
            st['ang'] = None if hit is None else math.atan2(float((hit - c) @ st['e2']), float((hit - c) @ e1))
        return st

    def _drag_to(self, st, x, y):
        ray = self._ray(x, y)
        if ray is None:
            return
        kind = st['kind']
        if kind in ('arrow', 'axis'):
            t = self._line_param(ray, *st['line'])
            if st['t0'] is not None and t is not None:
                self.handleDragged.emit(st['id'], float(t - st['t0']))
            elif st['t0'] is None and st['geo'] is not None:
                g = st['geo']
                self.handleDragged.emit(st['id'], ((x - st['x0']) * g['ux'] + (y - st['y0']) * g['uy']) / g['px_per_mm'])
        elif kind in ('plane', 'free'):
            hit = self._ray_plane(ray, *st['plane'])
            if hit is not None and st['hit0'] is not None:
                self.pointDragged.emit(st['id'], hit - st['hit0'])
        elif kind == 'ring':
            hit = self._ray_plane(ray, st['c'], st['axis'])
            if hit is None or st['ang'] is None:
                return
            ang = math.atan2(float((hit - st['c']) @ st['e2']), float((hit - st['c']) @ st['e1']))
            delta = (ang - st['ang'] + math.pi) % (2 * math.pi) - math.pi
            st['ang'] = ang
            st['total'] += delta
            self.handleDragged.emit(st['id'], st['total'] * st['radius'])

    def _update_hover_handle(self, pos):
        if not self.all_handles() and not self.free_drag:
            if self.hover_handle is not None:
                self.hover_handle = None
                self.overlay.update()
            return
        h = self._grab_handle(pos.x(), pos.y())
        hid = h['id'] if h else None
        if hid != self.hover_handle:
            self.hover_handle = hid
            self.setCursor(Qt.OpenHandCursor if hid else Qt.ArrowCursor)
            self.overlay.update()

    def addItem(self,item):
        item.section_view=self
        super().addItem(item)

    def item_section(self,item):
        plane=getattr(self,'section_plane',None)
        if plane is None:return None
        m=np.array(item.transform().data(),float).reshape(4,4).T
        return m.T @ plane

    def _local_section(self,bid):
        if self.section_plane is None:return None
        m=self._moved(bid)
        return self.section_plane if m is None else m.T @ self.section_plane

    def section_contains(self,points):
        points=np.asarray(points,float)
        return np.ones(points.shape[:-1],bool) if self.section_plane is None else points @ self.section_plane[:3]+self.section_plane[3]>=-1e-5

    def set_section_plane(self,plane):
        previous_plane=self.section_plane
        self.section_plane=None if plane is None else np.asarray(plane,float)
        if self._solid_batches or (previous_plane is not None and plane is None):
            self.set_models(self.bodies,self.selected_bodies,self.selected_edges)
        self.section_caps.update_section()
        self._set_hover_edge(None);self.hover_vertex=None
        self.update();self.overlay.update()

    def set_section_hover(self,mesh):
        for item in self.section_hover_items:self.removeItem(item)
        self.section_hover_items=[]
        if mesh is not None:
            item=OverMesh(vertexes=mesh.vertices,faces=mesh.triangles,color=(.55,.75,.92,.22),smooth=False,drawEdges=False)
            item.setGLOptions('translucent');self.addItem(item);self.section_hover_items.append(item)
        self.update()

    def all_handles(self):
        return [*self.handles,*self.section_handles]

    def _section_cap_hit(self,body,origin,direction):
        """Depth of visible cut material; the hatch is not a new editable CAD face."""
        plane=self.section_plane
        if plane is None or body.kind!='solid' or not self.section_caps.visible() or self.section_caps.available is False:return None
        denominator=float(plane[:3]@direction)
        if abs(denominator)<1e-12:return None
        distance=-float(plane[:3]@origin+plane[3])/denominator
        if distance<=1e-6:return None
        parts=self._parts.get(body.id);fill=parts.get('fill') if parts else None
        if fill is None or not fill.visible() or not parts.get('cap_solid'):return None
        local_origin,local_direction=self._local_ray(body.id,origin,direction)
        point=local_origin+distance*local_direction
        data=_pick_data(body.mesh)
        if 'box' not in data:return None
        low,high=data['box']
        if np.any(point<low-1e-5) or np.any(point>high+1e-5):return None
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN,TopAbs_ON
        cached=self._section_classifiers.get(body.id)
        if cached is None or cached[0] is not body.shape:
            cached=(body.shape,[BRepClass3d_SolidClassifier(solid.wrapped) for solid in body.shape.Solids()])
            self._section_classifiers[body.id]=cached
        p=gp_Pnt(*map(float,point))
        for classifier in cached[1]:
            classifier.Perform(p,1e-6)
            if classifier.State() in (TopAbs_IN,TopAbs_ON):return distance
        return None

    def section_reference(self,x,y):
        """A construction plane on visible section material, not a new CAD face."""
        if self.section_plane is None:return None
        ray=self._ray(x,y)
        if ray is None:return None
        hits=[(t,body.id) for body in self._ray_bodies(*ray) if body.id not in self.locked
              for t in [self._section_cap_hit(body,*ray)] if t is not None]
        if not hits:return None
        t,_=min(hits);point=ray[0]+t*ray[1]
        return kernel.face_frame(point,-np.asarray(self.section_plane[:3],float))

    def pick_body(self, x, y):
        ray = self._ray(x, y)
        hit = self._hit(*ray) if ray else None
        return hit[1] if hit else None

    def pick_face(self, x, y):
        """Zwraca (id bryły, normalna, punkt) dla trójkąta pod kursorem albo None."""
        ray = self._ray(x, y)
        if ray is None:
            return None
        origin, direction = ray
        best = None;blocked=None
        for body in self._ray_bodies(origin,direction):
            if (not body.visible or body.id in self.locked) or not body.mesh or not len(body.mesh.triangles):
                continue
            cap=self._section_cap_hit(body,origin,direction)
            if cap is not None:blocked=cap if blocked is None else min(blocked,cap)
            data = _pick_data(body.mesh)
            hit = _ray_triangles(data, *self._local_ray(body.id, origin, direction),cut=self._local_section(body.id))
            if hit is not None and (best is None or hit[0] < best[0]):
                n = np.cross(data['e1'][hit[1]], data['e2'][hit[1]])
                m = self._moved(body.id)
                if m is not None:
                    n = m[:3, :3] @ n
                n = n / max(np.linalg.norm(n), 1e-12)
                best = (hit[0], body.id, n, origin + direction * hit[0],hit[1],id(body.mesh))
        if blocked is not None and (best is None or blocked<best[0]-1e-5):return None
        if best is not None:
            self._face_hint=(best[1],best[4],tuple(best[3]),best[5])
        return None if best is None else (best[1], best[2], best[3])

    def face_at(self,body,hit,curved=False):
        hint=getattr(self,'_face_hint',None);face_id=None
        if hint is not None and hint[0]==body.id and tuple(hit[2])==hint[2] and id(body.mesh)==hint[3]:
            ids=getattr(body.mesh,'face_ids',None)
            if ids is not None and hint[1]<len(ids):face_id=int(ids[hint[1]])
        return kernel.face_at(body.shape,hit[1],hit[2],curved=curved,face_hint=face_id)

    def pick_profile(self, x, y):
        """Identyfikator szkicu, którego zamknięty obrys obejmuje punkt pod kursorem."""
        best = None
        for body in self._screen_bodies(x,y,1):
            if body.kind != 'sketch' or (not body.visible or body.id in self.locked) or not body.mesh:
                continue
            if (body.meta or {}).get('surface'):
                # Wskazuj widoczny, rzutowany obrys, nie jego niewidoczną płaszczyznę styczną.
                key=('surface-profile',body.id,id(body.mesh),self._camera_key())
                outlines=self._projection_cache.get(key)
                if outlines is None:
                    outlines=[]
                    for points in body.mesh.edges.values():
                        if len(points)<2:continue
                        xy, _, w = self.project_points(points)
                        if np.all(w>0) and np.isfinite(xy).all():outlines.append(xy)
                    self._projection_cache[key]=outlines
                crossings = 0
                for xy in outlines:
                    ax, ay, bx, by = xy[:-1, 0], xy[:-1, 1], xy[1:, 0], xy[1:, 1]
                    straddle = (ay > y) != (by > y)
                    with np.errstate(divide='ignore', invalid='ignore'):
                        xc = ax + (y - ay) * (bx - ax) / (by - ay)
                    crossings += int(np.count_nonzero(straddle & (xc > x)))
                if crossings % 2:
                    return body.id
                continue
            try:
                if not body.shape.IsClosed():
                    continue
            except Exception:
                pass
            hit = self._plane_hit(body.plane, x, y)
            if not hit or not self.section_contains(hit[1]):
                continue
            frame = kernel.frame_of(body.plane)
            o, ux, uy = np.array(frame.origin), np.array(frame.xdir), np.array(frame.ydir)
            px, py = kernel.uv_of(body.plane, hit[1])
            crossings = 0
            for points in body.mesh.edges.values():
                rel = points.astype(float) - o
                us, vs = rel @ ux, rel @ uy
                ax, ay, bx, by = us[:-1], vs[:-1], us[1:], vs[1:]
                straddle = (ay > py) != (by > py)
                with np.errstate(divide='ignore', invalid='ignore'):
                    xc = ax + (py - ay) * (bx - ax) / (by - ay)
                crossings += int(np.count_nonzero(straddle & (xc > px)))
            if crossings % 2 == 1 and (best is None or hit[0] < best[0]):
                best = (hit[0], body.id)
        return best[1] if best else None

    # ---------- siatka szkicu, płaszczyzna ściany, kamera, znacznik ----------
    def set_grid_frame(self, plane):
        """Siatka leży na płaszczyźnie szkicu (None = XY). Na ściance bryły dochodzi tymczasowy krzyż osi szkicu
        (czerwona oś U, zielona V) przechodzący przez środek ścianki - jak osie głównej siatki."""
        self._grid_plane = plane
        self._grid_key = None
        for item in self.sketch_axis_items:
            self.removeItem(item)
        self.sketch_axis_items = []
        if plane is not None and not isinstance(plane, str):
            frame = kernel.frame_of(plane)
            o, x, y, n = (np.array(v, float) for v in (frame.origin, frame.xdir, frame.ydir, frame.normal))
            lift = n * 0.02          # nad ścianką, żeby linie nie migotały na jej powierzchni
            for direction, col in ((x, (.89, .31, .33, .9)), (y, (.14, .64, .42, .9))):
                pts = np.array([o + lift - direction * 1000.0, o + lift + direction * 1000.0], dtype=np.float32)
                item = SectionLine(pos=pts, color=col, width=2, antialias=True)
                item.setGLOptions('translucent')
                self.addItem(item)
                self.sketch_axis_items.append(item)
        # szkic na ściance: główny krzyż osi świata znika, żeby nie mylił się z krzyżem ścianki
        self._main_axes_hidden = bool(self.sketch_axis_items)
        for item, _ in self.axis_lines:
            item.setVisible(not self._main_axes_hidden)
        self.update()

    def keyPressEvent(self, event):
        """W szkicu strzałki (także z bloku numerycznego) przesuwają widok; Shift - większy krok."""
        if self.sketch_plane is not None and pan_arrow(self, event):
            event.accept()
            return
        super().keyPressEvent(event)

    def show_custom_plane(self, frame, half=30.0, color=(1.0, .55, .1)):
        for item in self.custom_plane_items:
            self.removeItem(item)
        self.custom_plane_items = []
        if frame is not None:
            pts = np.array([kernel.to_world(frame, u, v) for u, v in ((-half, -half), (half, -half), (half, half), (-half, half))], dtype=np.float32)
            fill = SectionMesh(vertexes=pts, faces=np.array([[0, 1, 2], [0, 2, 3]]), color=(*color, .14), smooth=False, drawEdges=False)
            fill.setGLOptions('translucent')
            outline = SectionLine(pos=np.array([*pts, pts[0]], dtype=np.float32), color=(*color, .9), width=2, antialias=True)
            for item in (fill, outline):
                self.addItem(item)
                self.custom_plane_items.append(item)
        self.update()

    def look_along(self, plane):
        """Kamera patrzy na płaszczyznę szkicu wprost (z jej strony normalnej). Najpierw zawsze „góra do góry”: na ścianach
        pionowych i ukośnych oś Z świata wskazuje w górę ekranu, na poziomych - oś Y (napis GÓRA na kostce stoi prosto);
        obrót w płaszczyźnie dopasowuje się potem strzałkami przy kostce."""
        frame = kernel.frame_of(plane)
        n = np.array(frame.normal, float)
        n = n / max(np.linalg.norm(n), 1e-12)
        self.opts['center'] = QVector3D(*[float(c) for c in frame.origin])
        self.setCameraPosition(**camera_for_normal(n))
        self.upright(n)

    def upright(self, n=None):
        """Obraca obraz wokół osi patrzenia tak, żeby „góra” była u góry: przy patrzeniu z góry / z dołu oś Y (±),
        w pozostałych widokach oś Z świata."""
        n = self.camera_dir() if n is None else np.asarray(n, float)
        want = np.array([0.0, 1.0 if n[2] > 0 else -1.0, 0.0]) if abs(n[2]) > .9 else np.array([0.0, 0.0, 1.0])
        self.opts['roll'] = 0.0
        right, up, back = self.screen_axes()
        x, y = float(want @ right), float(want @ up)
        if math.hypot(x, y) < 1e-6:
            return
        self.set_roll(round(-math.degrees(math.atan2(-x, y)), 6))

    def set_marker(self, point, color=None, label=None):
        """Znacznik przyciągania (pomarańczowe kółko z etykietą) - tylko gdy kursor złapał punkt, jak w wersji HTML."""
        self.snap_marker = None
        if point is not None and label:
            xy = self.project_one(point)
            if xy is not None:
                self.snap_marker = (xy, label)
        self.overlay.update()

    ortho = True           # rzut równoległy (bez perspektywy): na widoku prosto na płaszczyznę ścianki zasłaniają to, co za nimi

    def set_ortho(self, on):
        self.ortho = bool(on)
        self._refresh_grid() if hasattr(self, '_refresh_grid') else None
        self.update()

    def _scene_extent(self):
        """Promień sceny wokół punktu, na który patrzy kamera - zakres głębi rzutu równoległego (bez ucinania brył).
        Zapamiętany dla tych samych brył i środka (liczony był przy każdym rzucie punktu - setki razy na ruch myszy)."""
        center = np.array([self.opts['center'].x(), self.opts['center'].y(), self.opts['center'].z()], float)
        bodies = getattr(self, 'bodies', ())
        key = (getattr(self,'_scene_revision',0), tuple(center))
        cached = getattr(self, '_extent_cache', None)
        if cached is not None and cached[0] == key:
            return cached[1]
        extent=100.0
        if hasattr(self,'_scene_revision'):
            _,_,tree=self._scene_index()
            if len(tree.low):
                centres=(tree.low+tree.high)*.5;sizes=np.linalg.norm(tree.high-tree.low,axis=1)*.5
                extent=max(extent,float((np.linalg.norm(centres-center,axis=1)+sizes).max()))
        self._extent_cache = (key, extent)
        return extent

    def projectionMatrix(self, region=None, viewport=None):
        """Rzut równoległy: ta sama skala co perspektywa w punkcie, na który patrzy kamera, ale bez zbiegania się linii -
        widok prosto na płaszczyznę pokazuje bryły jak rysunek (tylne krawędzie nie „odstają”)."""
        if region is None:
            region = viewport = self.getViewport()
        if not self.ortho:
            return super().projectionMatrix(region, viewport)
        x0, y0, w, h = viewport
        dist = float(self.opts['distance'])
        r = dist * math.tan(math.radians(float(self.opts['fov'])) / 2)
        t = r * h / max(w, 1)
        left = r * ((region[0] - x0) * (2.0 / w) - 1)
        right = r * ((region[0] + region[2] - x0) * (2.0 / w) - 1)
        bottom = t * ((region[1] - y0) * (2.0 / h) - 1)
        top = t * ((region[1] + region[3] - y0) * (2.0 / h) - 1)
        depth = dist + 2 * self._scene_extent()
        matrix = QMatrix4x4()
        matrix.ortho(left, right, bottom, top, -depth, depth)
        return matrix

    def _camera_key(self):
        c=self.opts['center']
        return (self.width(),self.height(),self.ortho,getattr(self,'_scene_revision',0),c.x(),c.y(),c.z(),
                self.opts['distance'],self.opts['elevation'],self.opts['azimuth'],self.roll(),self.opts['fov'])

    def _camera_data(self):
        key=self._camera_key();cached=getattr(self,'_camera_cache',None)
        if cached is None or cached[0]!=key:
            viewport=(0,0,max(1,self.width()),max(1,self.height()))
            matrix=self.projectionMatrix(viewport,viewport)*self.viewMatrix()
            inverse,ok=matrix.inverted()
            array=np.array(matrix.data(),float).reshape(4,4).T
            cached=(key,matrix,array,inverse,ok);self._camera_cache=cached
        return cached

    def camera_matrix(self):
        return QMatrix4x4(self._camera_data()[1])

    def project_points(self, points):
        m=self._camera_data()[2]
        homogeneous=np.asarray(points)@m[:,:3].T+m[:,3]
        w=homogeneous[:,3];safe=np.where(np.abs(w)>1e-12,w,np.nan)
        ndc=homogeneous[:,:3]/safe[:,None]
        xy=np.column_stack(((ndc[:,0]+1)*self.width()/2,(1-ndc[:,1])*self.height()/2))
        return xy,ndc[:,2],w

    def _scene_index(self):
        cached=getattr(self,'_scene_index_cache',None)
        if cached is not None and cached[0]==self._scene_revision:return cached
        bodies=[];lows=[];highs=[]
        for b in self.bodies:
            if not b.visible or b.mesh is None:continue
            mesh=b.mesh;bounds=getattr(mesh,'_scene_bounds',None)
            if bounds is None:
                arrays=[a for a in (mesh.vertices,*mesh.edges.values()) if len(a)]
                if not arrays:continue
                points=np.concatenate(arrays)
                bounds=(points.min(axis=0),points.max(axis=0));mesh._scene_bounds=bounds
            lo,hi=bounds
            m=self._moved(b.id)
            if m is not None:
                corners=np.array([[x,y,z] for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])])
                corners=self._apply_m(m,corners);lo=corners.min(axis=0);hi=corners.max(axis=0)
            bodies.append(b);lows.append(lo);highs.append(hi)
        tree=BoundsTree(lows,highs)
        cached=(self._scene_revision,bodies,tree);self._scene_index_cache=cached
        return cached

    def _ray_bodies(self,origin,direction):
        _,bodies,tree=self._scene_index()
        return (bodies[i] for i in tree.ray(origin,direction))

    def _screen_bodies(self,x,y,radius=11):
        key=self._camera_key();cached=getattr(self,'_screen_index_cache',None)
        _,bodies,tree=self._scene_index()
        if cached is None or cached[0]!=key:
            lows=[];highs=[];indices=[];always=[]
            if bodies:
                corners=np.array([[[a,b,c] for a in (lo[0],hi[0]) for b in (lo[1],hi[1]) for c in (lo[2],hi[2])]
                                  for lo,hi in zip(tree.low,tree.high)])
                xy,z,w=self.project_points(corners.reshape(-1,3));xy=xy.reshape(-1,8,2);w=w.reshape(-1,8)
                for i,pts in enumerate(xy):
                    if np.any(w[i]<=0) or not np.isfinite(pts).all():always.append(i);continue
                    lows.append([*pts.min(axis=0),0]);highs.append([*pts.max(axis=0),0]);indices.append(i)
            cached=(key,BoundsTree(lows,highs),indices,always);self._screen_index_cache=cached
        _,screen,indices,always=cached
        margin=np.broadcast_to(np.asarray(radius,float),(2,))
        ids=sorted({*always,*(indices[i] for i in screen.point([x,y,0],[*margin,0]))})
        return (bodies[i] for i in ids)

    def _visible_body_ids(self):
        key=self._camera_key();cached=getattr(self,'_visible_ids_cache',None)
        if cached is None or cached[0]!=key:
            bodies=self._screen_bodies(self.width()/2,self.height()/2,np.array([self.width(),self.height()])/2+12)
            cached=(key,frozenset(b.id for b in bodies));self._visible_ids_cache=cached
        return cached[1]

    def _edge_projection(self,body):
        plane=None if self.section_plane is None else tuple(self.section_plane)
        key=('edges',body.id,id(body.mesh),self._camera_key(),plane)
        cached=self._projection_cache.get(key)
        if cached is not None:return cached[1]
        data=_pick_data(body.mesh)
        if 'a' not in data:return None
        m=self._moved(body.id)
        a,b=(data['a'],data['b']) if m is None else (self._apply_m(m,data['a']),self._apply_m(m,data['b']))
        ids=data['edge']
        if self.section_plane is not None:
            cut=self.section_plane;keep=np.maximum(a@cut[:3]+cut[3],b@cut[:3]+cut[3])>=-1e-7
            if not keep.any():return None
            pairs=clip_segments(np.stack((a,b),axis=1).reshape(-1,3),cut).reshape(-1,2,3)
            a,b=pairs[:,0],pairs[:,1];ids=ids[keep]
        pa,_,wa=self.project_points(a);pb,_,wb=self.project_points(b)
        result=(a,b,ids,pa,pb,wa,wb);self._projection_cache[key]=(body.mesh,result)
        return result

    def nearest_edge(self, x, y, solids_only=False, kinds=None):
        """Krawędź najbliżej kursora (do 10 px), widoczna (nie zasłonięta bryłą, chyba że przezroczystość): (id, indeks) albo None.
        Wszystkie odcinki krawędzi bryły rzutowane naraz; zasłonięcie sprawdzane tylko dla najbliższych kandydatów."""
        found = []
        cursor = np.array([x, y], dtype=float)
        for body in self._screen_bodies(x,y,10):
            if (not body.visible or body.id in self.locked) or not body.mesh or (solids_only and body.kind != 'solid') or (kinds and body.kind not in kinds):
                continue
            projected=self._edge_projection(body)
            if projected is None:continue
            seg_a,seg_b,edge_ids,pa,pb,wa,wb=projected
            delta = pb - pa
            denom = (delta * delta).sum(axis=1)
            t = np.clip(((cursor - pa) * delta).sum(axis=1) / np.maximum(denom, 1e-12), 0, 1)
            dist = np.linalg.norm(pa + delta * t[:, None] - cursor, axis=1)
            dist[(wa <= 0) | (wb <= 0) | ~np.isfinite(dist)] = np.inf
            near = np.nonzero(dist < 10.)[0]
            parameter=np.divide(t*wa,wb*(1-t)+wa*t,out=t.copy(),where=np.abs(wb*(1-t)+wa*t)>1e-12)
            for j in near:
                found.append((float(dist[j]), len(found), body.id, int(edge_ids[j]), seg_a[j] + (seg_b[j] - seg_a[j]) * parameter[j]))
        found.sort(key=lambda item: (item[0], item[1]))
        seen = set()
        for _, _, bid, index, world in found:
            if (bid, index) in seen:
                continue
            seen.add((bid, index))
            if self.section_contains(world) and (self.xray or self._visible_point(world)):
                return (bid, index)
            if len(seen) > 24:
                break
        return None

    def nearest_vertex(self, x, y, radius=11.0, solids_only=True):
        """Wierzchołek (koniec krawędzi) najbliżej kursora: (id obiektu, punkt 3D) albo None; solids_only=False obejmuje też punkty szkiców."""
        best = None
        for body in self._screen_bodies(x,y,radius):
            if (not body.visible or body.id in self.locked) or not body.mesh or (solids_only and body.kind != 'solid') or body.kind not in ('solid', 'sketch'):
                continue
            key=('vertices',body.id,id(body.mesh),self._camera_key())
            cached=self._projection_cache.get(key)
            if cached is None:
                pts=_pick_data(body.mesh)['ends']
                if pts is None:continue
                m=self._moved(body.id)
                if m is not None:pts=self._apply_m(m,pts)
                xy,_,w=self.project_points(pts)
                cached=(body.mesh,(pts,xy,w));self._projection_cache[key]=cached
            pts,xy,w=cached[1]
            if len(xy) != len(pts):
                continue
            dist = np.linalg.norm(xy - [x, y], axis=1)
            dist[(w <= 0) | ~self.section_contains(pts)] = np.inf
            near=np.nonzero(dist<radius)[0]
            for j in sorted(near,key=lambda i:dist[i]):
                if best is not None and dist[j]>=best[0]:break
                if self.xray or self._visible_point(pts[j]):
                    best=(float(dist[j]),body.id,pts[j]);break
        return None if best is None else (best[1], best[2])

    def _ray(self, x, y):
        _,_,_,inverse,ok=self._camera_data()
        if not ok:
            return None
        from PySide6.QtGui import QVector4D
        pts = []
        for z in (-1, 1):
            p = inverse.map(QVector3D(float(2*x/self.width()-1), float(1-2*y/self.height()), float(z)))
            pts.append(np.array([p.x(), p.y(), p.z()]))
        direction = pts[1] - pts[0]
        return pts[0], direction / np.linalg.norm(direction)

    def _moved(self, bid):
        """Macierz podglądu przesunięcia / obrotu bryły (numpy 4x4) albo None. Wskazywanie myszą trafia w bryłę tam,
        gdzie ją widać - także zanim przesunięcie zostanie zatwierdzone."""
        m = self._body_m.get(bid) if getattr(self, '_body_m', None) else None
        if m is None:
            return None
        return np.array(m.data(), float).reshape(4, 4).T

    @staticmethod
    def _apply_m(m, points):
        points = np.asarray(points, float)
        return points @ m[:3, :3].T + m[:3, 3]

    def _local_ray(self, bid, origin, direction):
        m = self._moved(bid)
        if m is None:
            return origin, direction
        r, t = m[:3, :3], m[:3, 3]
        inv = np.linalg.inv(r)            # obrót + przesunięcie: odległość wzdłuż promienia się nie zmienia
        return inv @ (np.asarray(origin, float) - t), inv @ np.asarray(direction, float)

    def _hit(self, origin, direction, with_cap=False):
        best = None
        for body in self._ray_bodies(origin,direction):
            if (not body.visible or body.id in self.locked) or not body.mesh or not len(body.mesh.triangles):
                continue
            hit = _ray_triangles(_pick_data(body.mesh), *self._local_ray(body.id, origin, direction),cut=self._local_section(body.id))
            cap=self._section_cap_hit(body,origin,direction)
            is_cap=cap is not None and (hit is None or cap<hit[0])
            if is_cap:hit=(cap,-1)
            if hit is None:
                continue
            # szkic leżący na ścianie bryły (ta sama odległość) wygrywa z bryłą - inaczej trafiałoby się w bryłę
            tie = 1e-4 * max(1.0, hit[0])
            if best is None or hit[0] < best[0] - tie or (abs(hit[0] - best[0]) <= tie and body.kind == 'sketch' and best[2] != 'sketch'):
                best = (hit[0], body.id, body.kind,is_cap)
        if best is None:return None
        return (best[0],best[1],best[3]) if with_cap else best[:2]

    def _visible_point(self, point):
        if not self.section_contains(point):return False
        xy, _, _ = self.project_points(np.asarray([point]))
        ray = self._ray(*xy[0])
        if ray is None:
            return False
        origin, direction = ray
        hit = self._hit(origin, direction,with_cap=True)
        tolerance=1e-5 if hit is not None and hit[2] else .25
        return hit is None or hit[0] >= np.linalg.norm(point-origin)-tolerance

    def mouseMoveEvent(self, event):
        pos = event.position()
        buttons = event.buttons()
        if self._hook_active:
            self.drag_hook('move', pos.x(), pos.y())
            event.accept()
            return
        if self._handle_drag is not None:
            self._drag_to(self._handle_drag, pos.x(), pos.y())
            event.accept()
            return
        if self._sk_start is not None and buttons & Qt.LeftButton:
            point = self.plane_point(self.sketch_plane, pos.x(), pos.y())
            if point:
                end = self._snap(point, event)
                self._set_sketch_preview(self._sketch_outline(self.sketch_plane, self._sk_start, end))
                du, dv = end[0] - self._sk_start[0], end[1] - self._sk_start[1]
                if self.sketch_tool == 'rectangle':
                    self.sketchInfo.emit(f"Prostokąt {abs(du):.2f} × {abs(dv):.2f} mm")
                else:
                    self.sketchInfo.emit(f"Promień {math.hypot(du, dv):.2f} mm")
            event.accept()
            return
        if buttons & Qt.MiddleButton or (self._press and (buttons & Qt.RightButton or (buttons & Qt.LeftButton and event.modifiers() & Qt.ShiftModifier))):
            # przesuwanie w płaszczyźnie ekranu: na boki i w górę / w dół w każdym widoku (także patrząc prosto na płaszczyznę)
            delta = pos - (self._drag_position or pos)
            self._drag_position = pos
            self.pan(delta.x(), delta.y(), 0, relative='view')
            event.accept()
            return
        if self._press and self._press[2] == Qt.LeftButton and self.mouse_mode in ('orbit', 'pan'):
            previous = self._drag_position or pos
            delta = pos - previous
            self._drag_position = pos
            if self.mouse_mode == 'orbit':
                self.orbit(-delta.x(), delta.y())
            else:
                self.pan(delta.x(), delta.y(), 0, relative='view')
            event.accept()
            return
        if not buttons:
            self._update_hover_handle(pos)
            self._hover(pos)
        super().mouseMoveEvent(event)

    def pan_step(self, dx, dy):
        """Obraz przesuwa się o (dx, dy) pikseli ekranu (x w prawo, y w dół), jak przy przeciąganiu - w płaszczyźnie ekranu,
        więc działa także przy patrzeniu prosto na ściankę (tryb 'view-upright' przesuwa tylko w płaszczyźnie XY świata)."""
        self.pan(float(dx), float(dy), 0, relative='view')
        self.update()

    def _hover(self, pos):
        now = time.monotonic()
        if now - self._hover_time < .04:
            return
        self._hover_time = now
        if getattr(self,'section_picking',False):
            self.viewHover.emit(pos.x(),pos.y());return
        try:
            if self.click_mode and not self.plane_pick:
                if self.sketch_plane and self.sketch_tool:
                    if self.hover_gate is not None and not self.hover_gate():
                        if self.snap_marker is not None:
                            self.snap_marker = None
                            self.overlay.update()
                        return
                    point = self.plane_point(self.sketch_plane, pos.x(), pos.y())
                    if point:
                        u, v = self._snap(point, pos=pos)
                        self.sketchMoved.emit(self.sketch_plane, u, v)
                else:
                    self.viewHover.emit(pos.x(), pos.y())
                return
            if self.plane_pick:
                self._highlight_plane(self.plane_at(pos.x(), pos.y()))
                self.setCursor(Qt.PointingHandCursor)
                self.viewHover.emit(pos.x(), pos.y())
            elif self.edge_mode and self.mouse_mode == 'select':
                self._set_hover_edge(self.nearest_edge(pos.x(), pos.y()))
        except Exception:
            self._hover_key = None  # podświetlenie jest tylko pomocnicze

    def mousePressEvent(self, event):
        self._drag_position = event.position()
        if event.buttons() & Qt.MiddleButton:
            # kółko (samo albo razem z lewym przyciskiem) przesuwa obraz - nie rysuje i nie zaznacza
            self._press = None
            event.accept()
            return
        self._press = (event.position().x(), event.position().y(), event.button())
        if getattr(self,'section_picking',False) and event.button()==Qt.LeftButton:
            event.accept();return
        if self.drag_hook is not None and event.button() == Qt.LeftButton and not event.modifiers() & Qt.ShiftModifier:
            if self.drag_hook('press', event.position().x(), event.position().y()):
                self._hook_active = True
                self._press = None
                event.accept()
                return
        if (not self.click_mode and self.sketch_plane and self.sketch_tool and event.button() == Qt.LeftButton
                and not event.modifiers() & Qt.ShiftModifier
                and not (self.all_handles() and self._grab_handle(event.position().x(), event.position().y()))):   # strzałka w szkicu (np. ofset) ma pierwszeństwo
            point = self.plane_point(self.sketch_plane, event.position().x(), event.position().y())
            if point:
                self._sk_start = self._snap(point, event)
                event.accept()
                return
        if self.all_handles() and event.button() == Qt.LeftButton:
            grabbed = self._grab_handle(event.position().x(), event.position().y())
            if grabbed:
                self._handle_drag = self._begin_drag(grabbed, event.position().x(), event.position().y())
                if self._handle_drag is not None:
                    self.setCursor(Qt.ClosedHandCursor)
                    self._press = None
                    event.accept()
                    return
        if self.free_drag and event.button() == Qt.LeftButton and not event.modifiers() & Qt.ShiftModifier:
            x, y = event.position().x(), event.position().y()
            bid = self.pick_body(x, y)
            if bid is None:
                near = self.nearest_edge(x, y)
                bid = near[0] if near else None
            ray = self._ray(x, y)
            ids = self.free_drag[2] if len(self.free_drag) > 2 else {self.free_drag[0]}
            if bid in ids and ray is not None:
                c = self.camera_dir()
                axis = np.zeros(3)
                axis[int(np.argmax(np.abs(c)))] = 1.0
                origin = np.asarray(self.free_drag[1], float)
                self._handle_drag = dict(id='free', kind='free', plane=(origin, axis), hit0=self._ray_plane(ray, origin, axis))
                self.setCursor(Qt.ClosedHandCursor)
                self._press = None
                event.accept()
                return
        if event.button() == Qt.RightButton or (event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier):
            event.accept()  # przesuwanie widoku obsługujemy sami (prawy przycisk lub Shift + przeciąganie)
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.click_mode and not event.modifiers() & Qt.ShiftModifier:
            self._dbl = True
            self.viewDoubleClicked.emit(event.position().x(), event.position().y())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dbl:
            self._dbl = False
            event.accept()
            return
        if self._hook_active:
            self._hook_active = False
            self.drag_hook('release', event.position().x(), event.position().y())
            event.accept()
            return
        if self._handle_drag is not None:
            hid = self._handle_drag['id']
            self._handle_drag = None
            self.setCursor(Qt.OpenHandCursor if self.hover_handle else Qt.ArrowCursor)
            self.overlay.update()
            self.handleReleased.emit(hid)
            event.accept()
            return
        if self._sk_start is not None:
            start, self._sk_start = self._sk_start, None
            self._press = None
            point = self.plane_point(self.sketch_plane, event.position().x(), event.position().y())
            self._set_sketch_preview(None)
            if point:
                end = self._snap(point, event)
                if abs(end[0] - start[0]) > 1e-4 or abs(end[1] - start[1]) > 1e-4:
                    self.sketchDrawn.emit(self.sketch_plane, self.sketch_tool, start[0], start[1], end[0], end[1])
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if not self._press:
            return
        x, y, button = self._press
        self._press = None
        moved = np.hypot(event.position().x()-x, event.position().y()-y) > 4
        if button == Qt.RightButton and not moved and self.click_mode:
            self.contextRequested.emit(x, y)
            return
        if button != Qt.LeftButton or moved:
            return
        if self.plane_pick:
            if self.click_mode:
                self.viewClicked.emit(x, y, bool(event.modifiers() & Qt.ShiftModifier), bool(event.modifiers() & Qt.ControlModifier))
                return
            name = self.plane_at(x, y)
            if name:
                self.planeClicked.emit(name)
            return
        if self.click_mode:
            if self.sketch_plane and self.sketch_tool:
                point = self.plane_point(self.sketch_plane, x, y)
                if point:
                    u, v = self._snap(point, event)
                    self.sketchClicked.emit(self.sketch_plane, u, v)
                return
            if self.mouse_mode == 'select':
                self.viewClicked.emit(x, y, bool(event.modifiers() & Qt.ShiftModifier), bool(event.modifiers() & Qt.ControlModifier))
            return
        if self.mouse_mode != "select" or self.sketch_plane:
            return
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        additive = self.multi_select or bool(event.modifiers() & Qt.ControlModifier)
        if self.edge_mode:
            hit = self.nearest_edge(x, y)
            if hit:
                self.edgeClicked.emit(*hit, additive, shift)
            elif not additive:
                self.selectionCleared.emit()
        else:
            ray = self._ray(x, y)
            hit = self._hit(*ray) if ray else None
            if hit:
                self.bodyClicked.emit(hit[1], additive or shift)
            elif not additive and not shift:
                self.selectionCleared.emit()
