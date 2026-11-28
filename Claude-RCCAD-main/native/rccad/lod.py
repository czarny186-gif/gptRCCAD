"""Render-only levels of detail. Picking and modelling keep the document mesh."""
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QFormLayout

from . import kernel, settings, workers
from .perfcache import LRU

PROFILES = (
    ('auto', 'Automatyczny'),
    ('speed', 'Maksymalna wydajność'),
    ('balanced', 'Zrównoważony'),
    ('quality', 'Maksymalna jakość'),
)
TARGETS = (30, 60, 120)


def build_mesh(shape, level):
    """Triangulate an isolated copy without sampling picking edges."""
    import cadquery as cq
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.TopLoc import TopLoc_Location

    tolerance, angular = {0: (.025, .09), 1: (.065, .14), 3: (.35, .38), 4: (.75, .65)}[level]
    copy = cq.Shape.cast(BRepBuilderAPI_Copy(shape.wrapped, True, False).Shape())
    kernel.mesh_parallel(copy, tolerance, angular)
    for face in copy.Faces():
        poly = BRep_Tool.Triangulation_s(face.wrapped, TopLoc_Location())
        if poly is None or not poly.NbTriangles():
            return None
    data = kernel._fast_triangles(copy)
    if data is None:
        return None
    vertices, triangles, _ = data
    return kernel.DisplayMesh(vertices, triangles, {}, (0., 0., 0.), 1.)


def select_level(profile, moving, frame_ms, fps, pixels, previous):
    if profile == 'quality':
        return 0 if pixels >= 400 else 1
    if not moving:
        return 1 if profile != 'speed' and pixels >= 600 else 2
    budget = 1000 / fps
    if profile == 'speed' or pixels < 100 or frame_ms > budget * 1.25:
        return 4
    if previous == 4 and frame_ms >= budget * .8:
        return 4
    if pixels < 300 or frame_ms > budget or profile == 'balanced':
        return 3
    return 2


class AdaptiveDetail:
    def __init__(self, studio):
        self.studio = studio
        self.view = studio.view
        self.view.adaptive_detail = self
        values = settings.read('performance') or {}
        profile, fps = values.get('profile'), values.get('fps')
        self.profile = profile if profile in tuple(key for key, _ in PROFILES) else 'auto'
        self.fps = fps if fps in TARGETS else 60
        self.cache = LRU(96 * 1024 * 1024, max_entries=128)
        self.failed = LRU(max_entries=128)
        self.pose = None
        self.scene_revision = None
        self.last_move = -1e9
        self.frame_ms = 0.
        self.pending = None
        self.levels = {}
        self.timer = QTimer(studio)
        self.timer.setSingleShot(True)
        self.timer.setInterval(140)
        self.timer.timeout.connect(self.update)
        self.view.cameraMoved.connect(self.camera_changed)

    def settings_form(self, parent):
        form = QFormLayout()
        profile = QComboBox(parent)
        for key, label in PROFILES:
            profile.addItem(label, key)
        profile.setCurrentIndex(profile.findData(self.profile))
        fps = QComboBox(parent)
        for value in TARGETS:
            fps.addItem(str(value), value)
        fps.setCurrentIndex(fps.findData(self.fps))
        form.addRow('Tryb', profile)
        form.addRow('Docelowe FPS', fps)

        def apply(_index):
            self.profile, self.fps = profile.currentData(), fps.currentData()
            settings.write('performance', dict(profile=self.profile, fps=self.fps))
            self.timer.start()

        profile.currentIndexChanged.connect(apply)
        fps.currentIndexChanged.connect(apply)
        return form

    def camera_changed(self):
        view = self.view
        # Scene revisions and repaint requests do not count as movement.
        key = view._camera_key()
        pose = (*key[:3], *key[4:])
        moved = self.pose != pose
        if not moved and self.scene_revision == key[3]:
            return
        self.scene_revision = key[3]
        if moved:
            self.pose = pose
            self.last_move = time.monotonic()
        if not self.timer.isActive():
            self.timer.start()

    def frame_rendered(self, elapsed):
        if not self.frame_ms and not self.timer.isActive():
            self.timer.start()
        self.frame_ms = .8 * self.frame_ms + 200 * elapsed

    def update(self):
        view = self.view
        moving = time.monotonic() - self.last_move < .25
        if moving:
            self.timer.start()
        if not self.frame_ms or view.section_plane is not None:
            view.set_detail_meshes({})
            return

        visible = view._visible_body_ids()
        distance = max(float(view.opts['distance']), 1.)
        # Orthographic and perspective both use this conservative scale estimate.
        pixels_per_unit = view.height() / distance
        wanted, presented, levels = [], {}, {}
        for body in view.bodies:
            mesh = body.mesh
            if (body.id not in visible or body.kind != 'solid' or mesh is None
                    or not mesh.fine or len(mesh.triangles) < 2000):
                continue
            pixels = pixels_per_unit * mesh.size
            level = select_level(self.profile, moving, self.frame_ms, self.fps, pixels, self.levels.get(body.id, 2))
            levels[body.id] = level
            if level == 2:
                continue
            key = (id(body.shape), level)
            cached = self.cache.get(key)
            if cached is not None and cached[0] is body.shape:
                presented[body.id] = (body.shape, cached[1])
            elif self.failed.get(key) is not body.shape:
                wanted.append((pixels, body.shape, level))
                current = view._detail_meshes.get(body.id)
                if current is not None and current[0] is body.shape:
                    presented[body.id] = current
        self.levels = levels
        view.set_detail_meshes(presented)
        if wanted and self.pending is None:
            _, shape, level = max(wanted, key=lambda item: item[0])
            self.submit(shape, level)

    def submit(self, shape, level):
        from .studio import _Work

        key = (id(shape), level)

        def compute():
            if workers.ready():
                try:
                    return workers.call_any(build_mesh, shape, level)
                except workers.Unavailable:
                    pass
            return build_mesh(shape, level)

        def done(mesh):
            self.pending = None
            if mesh is None:
                self.failed[key] = shape
            elif any(body.shape is shape for body in self.view.bodies):
                self.cache[key] = (shape, mesh)
                if self.cache.get(key) is None:
                    self.failed[key] = shape
            self.timer.start()

        work = _Work(compute, f"Teselacja LOD {level}")
        self.pending = work
        work.signals.done.connect(done)
        work.signals.failed.connect(lambda _message: done(None))
        self.studio.pool.start(work, -2)
